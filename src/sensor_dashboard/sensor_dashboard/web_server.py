"""ROS-free web server for the dashboard (standard library only).

  GET  /                  static files from the web folder
  GET  /events            Server-Sent Events stream of JSON updates
  GET  /api/state         latest value of every channel (for page load)
  POST /api/command       {"action": "...", ...}  -> command handler
  GET  /api/logs          sessions + files under log_dir
  GET  /logs/<session>/<file>   download a log file
"""

from __future__ import annotations

import json
import mimetypes
import os
import queue
import shutil
import threading
import time
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from urllib.parse import unquote, urlparse


class Hub:
    """Fan-out of JSON updates to every connected browser."""

    def __init__(self, max_queue: int = 400) -> None:
        self._clients: set[queue.Queue] = set()
        self._lock = threading.Lock()
        self._latest: dict[str, dict] = {}
        self.max_queue = max_queue

    def publish(self, channel: str, data: dict, keep: bool = True) -> None:
        msg = {'ch': channel, 't': time.time(), 'd': data}
        if keep:
            self._latest[channel] = msg
        line = json.dumps(msg, separators=(',', ':'))
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            try:
                q.put_nowait(line)
            except queue.Full:            # slow browser: drop oldest
                try:
                    q.get_nowait()
                    q.put_nowait(line)
                except queue.Empty:
                    pass

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(self.max_queue)
        with self._lock:
            self._clients.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._clients.discard(q)

    def snapshot(self) -> list:
        return list(self._latest.values())

    @property
    def client_count(self) -> int:
        return len(self._clients)


def _safe_join(root: str, rel: str) -> str | None:
    """Join without letting `rel` escape `root` ('..', absolute paths).

    Uses normpath, not realpath: with `colcon build --symlink-install` the
    installed web files are symlinks into src/, and resolving them would make
    every file look like it is outside the web folder.
    """
    root = os.path.abspath(root)
    path = os.path.normpath(os.path.join(root, rel.lstrip('/\\')))
    if path != root and not path.startswith(root + os.sep):
        return None
    return path


def list_sessions(log_dir: str, limit: int = 50) -> list[dict]:
    root = os.path.expanduser(log_dir)
    if not os.path.isdir(root):
        return []
    out = []
    for name in sorted(os.listdir(root), reverse=True)[:limit]:
        d = os.path.join(root, name)
        if not os.path.isdir(d):
            continue
        files, total = [], 0
        for f in sorted(os.listdir(d)):
            p = os.path.join(d, f)
            if os.path.isfile(p):
                sz = os.path.getsize(p)
                total += sz
                files.append({'name': f, 'size': sz})
            elif os.path.isdir(p):
                sz = sum(os.path.getsize(os.path.join(a, b))
                         for a, _, bs in os.walk(p) for b in bs)
                total += sz
                files.append({'name': f + '/', 'size': sz})
        info = {}
        ip = os.path.join(d, 'session_info.json')
        if os.path.isfile(ip):
            try:
                with open(ip) as fh:
                    info = json.load(fh)
            except (OSError, ValueError):
                pass
        out.append({'name': name, 'files': files, 'size': total, 'info': info})
    return out


def make_server(host: str, port: int, web_dir: str, hub: Hub, log_dir: str,
                on_command, keepalive_s: float = 10.0) -> ThreadingHTTPServer:
    """on_command(dict) -> dict  (runs in the HTTP thread)."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        server_version = 'SensorDashboard/1.0'

        def log_message(self, *_):   # keep the ROS console clean
            pass

        def _send(self, code, body: bytes, ctype='application/json', extra=None):
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj).encode())

        def do_GET(self):  # noqa: N802
            path = unquote(urlparse(self.path).path)
            if path == '/events':
                return self._events()
            if path == '/api/state':
                return self._json({'channels': hub.snapshot()})
            if path == '/api/logs':
                return self._json({'log_dir': os.path.expanduser(log_dir),
                                   'sessions': list_sessions(log_dir)})
            if path.startswith('/logs/'):
                return self._log_file(path[len('/logs/'):])
            rel = 'index.html' if path in ('', '/') else path.lstrip('/')
            fp = _safe_join(web_dir, rel)
            if not fp or not os.path.isfile(fp):
                return self._send(404, b'not found', 'text/plain')
            with open(fp, 'rb') as fh:
                body = fh.read()
            ctype = mimetypes.guess_type(fp)[0] or 'application/octet-stream'
            self._send(200, body, ctype)

        def _log_file(self, rel):
            root = os.path.expanduser(log_dir)
            fp = _safe_join(root, rel.rstrip('/'))
            if not fp or not os.path.exists(fp):
                return self._send(404, b'not found', 'text/plain')
            if os.path.isdir(fp):            # zip a whole session (or bag folder)
                buf = BytesIO()
                with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
                    for a, _, bs in os.walk(fp):
                        for b in bs:
                            full = os.path.join(a, b)
                            z.write(full, os.path.relpath(full, os.path.dirname(fp)))
                name = os.path.basename(fp) + '.zip'
                return self._send(200, buf.getvalue(), 'application/zip',
                                  {'Content-Disposition': f'attachment; filename="{name}"'})
            self.send_response(200)
            self.send_header('Content-Type', 'text/csv' if fp.endswith('.csv')
                             else 'application/octet-stream')
            self.send_header('Content-Length', str(os.path.getsize(fp)))
            self.send_header('Content-Disposition',
                             f'attachment; filename="{os.path.basename(fp)}"')
            self.end_headers()
            with open(fp, 'rb') as fh:
                shutil.copyfileobj(fh, self.wfile)

        def _events(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            q = hub.subscribe()
            try:
                for msg in hub.snapshot():
                    self.wfile.write(f'data: {json.dumps(msg)}\n\n'.encode())
                self.wfile.flush()
                while True:
                    try:
                        line = q.get(timeout=keepalive_s)
                        batch = [line]
                        while len(batch) < 50:
                            try:
                                batch.append(q.get_nowait())
                            except queue.Empty:
                                break
                        self.wfile.write(''.join(f'data: {x}\n\n' for x in batch).encode())
                    except queue.Empty:
                        self.wfile.write(b': keepalive\n\n')
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                hub.unsubscribe(q)

        def do_POST(self):  # noqa: N802
            if urlparse(self.path).path != '/api/command':
                return self._send(404, b'not found', 'text/plain')
            try:
                n = int(self.headers.get('Content-Length', '0'))
                req = json.loads(self.rfile.read(n) or b'{}')
            except ValueError:
                return self._json({'ok': False, 'message': 'bad JSON'}, 400)
            try:
                res = on_command(req)
            except Exception as exc:  # noqa: BLE001
                res = {'ok': False, 'message': str(exc)}
            self._json(res, 200 if res.get('ok') else HTTPStatus.BAD_REQUEST)

    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    return srv
