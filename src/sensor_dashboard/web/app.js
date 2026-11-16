/* Sensor Test Bench dashboard - no external libraries, works offline. */
'use strict';

const $ = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const fmt = (v, d = 2) => (v === undefined || v === null || Number.isNaN(v)) ? '–' : Number(v).toFixed(d);
const b64 = (s) => { const bin = atob(s || ''); const a = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i); return a; };
const DPR = () => window.devicePixelRatio || 1;

function fitCanvas(c) {
  const r = c.getBoundingClientRect();
  const w = Math.max(1, Math.round(r.width * DPR())), h = Math.max(1, Math.round(r.height * DPR()));
  if (c.width !== w || c.height !== h) { c.width = w; c.height = h; return true; }
  return false;
}

/* ---------------------------------------------------------------- theme */
let theme = {};
function readTheme() {
  theme = {
    text: css('--text-primary'), text2: css('--text-secondary'), muted: css('--text-muted'),
    grid: css('--grid'), surface: css('--surface-1'), s1: css('--series-1'), s2: css('--series-2'),
    s3: css('--series-3'), good: css('--good'), warn: css('--warning'), crit: css('--critical'),
  };
}
(function initTheme() {
  let t = 'dark';
  try { t = localStorage.getItem('stb-theme') || 'dark'; } catch (e) { /* storage blocked */ }
  document.documentElement.dataset.theme = t;
  readTheme();
  $('themeBtn').onclick = () => {
    const n = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = n;
    try { localStorage.setItem('stb-theme', n); } catch (e) { /* ignore */ }
    readTheme(); redrawAll(); themeLabel();
  };
  const themeLabel = () => { $('themeBtn').textContent = document.documentElement.dataset.theme === 'dark' ? 'Light' : 'Dark'; };
  themeLabel();
})();

/* ---------------------------------------------------------------- toast */
let toastT;
function toast(msg, ok = true) {
  const t = $('toast'); t.textContent = msg; t.classList.toggle('bad', !ok); t.classList.add('show');
  clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove('show'), ok ? 2600 : 6000);
}
async function command(body) {
  try {
    const r = await fetch('/api/command', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const j = await r.json();
    return j;
  } catch (e) { return { ok: false, message: 'dashboard node unreachable' }; }
}

/* ------------------------------------------------------- time series chart */
class TimeChart {
  constructor(canvas, opts) {
    this.c = canvas; this.ctx = canvas.getContext('2d');
    this.series = opts.series;               // [{key,label,color:()=>css}]
    this.window = opts.window || 60;
    this.yMin = opts.yMin; this.yMax = opts.yMax;
    this.invert = !!opts.invert;
    this.unit = opts.unit || '';
    this.decimals = opts.decimals ?? 2;
    this.data = [];                          // [t, v1, v2, ...]
    this.hover = null;
    this.legend = this.series.length > 1;
    const wrap = document.createElement('div'); wrap.className = 'chart-wrap';
    canvas.parentNode.insertBefore(wrap, canvas); wrap.appendChild(canvas);
    this.tip = document.createElement('div'); this.tip.className = 'tip'; wrap.appendChild(this.tip);
    canvas.addEventListener('mousemove', (e) => { const r = canvas.getBoundingClientRect(); this.hover = e.clientX - r.left; this.draw(); });
    canvas.addEventListener('mouseleave', () => { this.hover = null; this.tip.style.display = 'none'; this.draw(); });
    this.dirty = true;
  }
  push(t, values) {
    this.data.push([t, ...values]);
    const cut = t - this.window - 2;
    while (this.data.length && this.data[0][0] < cut) this.data.shift();
    this.dirty = true;
  }
  draw() {
    fitCanvas(this.c);
    const ctx = this.ctx, d = DPR(), W = this.c.width / d, H = this.c.height / d;
    ctx.setTransform(d, 0, 0, d, 0, 0); ctx.clearRect(0, 0, W, H);
    const padL = 44, padR = 10, padT = this.legend ? 18 : 6, padB = 18;
    const pw = W - padL - padR, ph = H - padT - padB;
    const now = this.data.length ? this.data[this.data.length - 1][0] : Date.now() / 1000;
    const t0 = now - this.window;
    let lo = Infinity, hi = -Infinity;
    for (const r of this.data) for (let i = 1; i < r.length; i++) { const v = r[i]; if (v !== null && isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }
    if (!isFinite(lo)) { lo = 0; hi = 1; }
    if (this.yMin !== undefined) lo = this.yMin;
    if (this.yMax !== undefined) hi = this.yMax;
    if (hi - lo < 1e-6) { hi += 0.5; lo -= 0.5; }
    const span = hi - lo, step = niceStep(span / Math.max(1, Math.min(4, Math.floor(ph / 26))));
    lo = this.yMin !== undefined ? lo : Math.floor(lo / step) * step;
    hi = this.yMax !== undefined ? hi : Math.ceil(hi / step) * step;
    const X = (t) => padL + (t - t0) / this.window * pw;
    const Y = (v) => this.invert ? padT + (v - lo) / (hi - lo) * ph : padT + ph - (v - lo) / (hi - lo) * ph;

    ctx.font = '11px system-ui, sans-serif'; ctx.textBaseline = 'middle';
    ctx.strokeStyle = theme.grid; ctx.lineWidth = 1; ctx.fillStyle = theme.muted; ctx.textAlign = 'right';
    for (let v = lo; v <= hi + step * 1e-6; v += step) {
      const y = Math.round(Y(v)) + 0.5;
      ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + pw, y); ctx.stroke();
      ctx.fillText(+v.toFixed(6) + '', padL - 6, y);
    }
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    for (let s = 0; s <= this.window; s += this.window / 4) {
      ctx.textAlign = s === 0 ? 'right' : s === this.window ? 'left' : 'center';
      ctx.fillText(s === 0 ? 'now' : `-${s}s`, X(now - s), padT + ph + 4);
    }

    // series
    this.series.forEach((s, i) => {
      ctx.strokeStyle = s.color(); ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.beginPath();
      let pen = false;
      for (const r of this.data) {
        const v = r[i + 1];
        if (v === null || !isFinite(v) || r[0] < t0) { pen = false; continue; }
        const x = X(r[0]), y = Y(Math.max(lo, Math.min(hi, v)));
        if (pen) ctx.lineTo(x, y); else { ctx.moveTo(x, y); pen = true; }
      }
      ctx.stroke();
    });
    // legend
    if (this.legend) {
      let x = padL; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
      for (const s of this.series) {
        ctx.fillStyle = s.color(); roundRect(ctx, x, 6, 12, 4, 2); ctx.fill();
        ctx.fillStyle = theme.text2; ctx.fillText(s.label, x + 16, 8); x += ctx.measureText(s.label).width + 34;
      }
    }
    // hover crosshair
    if (this.hover !== null && this.data.length) {
      const th = t0 + (this.hover - padL) / pw * this.window;
      let best = null, bd = Infinity;
      for (const r of this.data) { const dd = Math.abs(r[0] - th); if (dd < bd) { bd = dd; best = r; } }
      if (best && best[0] >= t0) {
        const x = X(best[0]);
        ctx.strokeStyle = theme.muted; ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT + ph); ctx.stroke(); ctx.setLineDash([]);
        let html = `<div class="muted">${(best[0] - now).toFixed(1)} s</div>`;
        this.series.forEach((s, i) => {
          const v = best[i + 1];
          if (v !== null && isFinite(v)) {
            ctx.fillStyle = s.color(); ctx.strokeStyle = theme.surface; ctx.lineWidth = 2;
            ctx.beginPath(); ctx.arc(x, Y(v), 4, 0, 7); ctx.fill(); ctx.stroke();
          }
          html += `<div><span class="sw" style="background:${s.color()}"></span>${s.label} <b>${v === null || !isFinite(v) ? '–' : v.toFixed(this.decimals)}</b> ${this.unit}</div>`;
        });
        this.tip.innerHTML = html; this.tip.style.display = 'block';
        const left = Math.min(x + 12, W - this.tip.offsetWidth - 4);
        this.tip.style.left = left + 'px'; this.tip.style.top = padT + 'px';
      }
    }
    this.dirty = false;
  }
}
function niceStep(raw) {
  const p = Math.pow(10, Math.floor(Math.log10(raw || 1))), f = raw / p;
  return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p;
}
function roundRect(ctx, x, y, w, h, r) { ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }

/* ---------------------------------------------------------- colormaps */
function makeCmap(stops) {
  const lut = new Uint8ClampedArray(256 * 4);
  const rgb = stops.map(([p, hex]) => [p, parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)]);
  for (let i = 0; i < 256; i++) {
    const t = i / 255; let k = 0;
    while (k < rgb.length - 2 && t > rgb[k + 1][0]) k++;
    const [p0, r0, g0, b0] = rgb[k], [p1, r1, g1, b1] = rgb[k + 1], u = (t - p0) / (p1 - p0 || 1);
    lut.set([r0 + (r1 - r0) * u, g0 + (g1 - g0) * u, b0 + (b1 - b0) * u, 255], i * 4);
  }
  return lut;
}
const CMAPS = {
  blue: makeCmap([[0, '#0d0d0c'], [0.25, '#104281'], [0.55, '#3987e5'], [0.8, '#9ec5f4'], [1, '#f4f9ff']]),
  copper: makeCmap([[0, '#0d0d0c'], [0.3, '#5a2a0c'], [0.6, '#c4692a'], [0.85, '#f2b57a'], [1, '#fff1df']]),
  gray: makeCmap([[0, '#0d0d0c'], [1, '#f4f4f2']]),
};

/* ---------------------------------------------------------- sonar view */
class SonarView {
  constructor(img, overlay, tip) {
    this.img = img; this.ov = overlay; this.tip = tip;
    this.bins = 320; this.buf = new Uint8Array(400 * this.bins);
    this.cmap = CMAPS.blue; this.range = 20; this.angle = 0; this.step = 1; this.lastAngle = null;
    this.dirty = true; this.lut = null;
    overlay.addEventListener('mousemove', (e) => this.onHover(e));
    overlay.addEventListener('mouseleave', () => { this.tip.style.display = 'none'; });
  }
  clear() { this.buf.fill(0); this.dirty = true; }
  setCmap(name) { this.cmap = CMAPS[name] || CMAPS.blue; this.dirty = true; }
  addPing(angle, range, data) {
    if (Math.abs(range - this.range) > 1e-3) { this.range = range; this.clear(); this.drawOverlay(); }
    const B = this.bins, n = data.length, row = new Uint8Array(B);
    for (let b = 0; b < B; b++) {                     // resample, keep max
      const i0 = Math.floor(b * n / B), i1 = Math.max(i0 + 1, Math.floor((b + 1) * n / B));
      let m = 0; for (let i = i0; i < i1 && i < n; i++) if (data[i] > m) m = data[i];
      row[b] = m;
    }
    // fill the gap between the previous and current angle (step > 1)
    let span = 1;
    if (this.lastAngle !== null) { const dA = (angle - this.lastAngle + 400) % 400; if (dA > 0 && dA <= 50) span = dA; }
    for (let k = 0; k < span; k++) this.buf.set(row, ((angle - k + 400) % 400) * B);
    this.lastAngle = angle; this.angle = angle; this.dirty = true;
  }
  buildLut() {
    const W = this.img.width, H = this.img.height, R = Math.min(W, H) / 2, cx = W / 2, cy = H / 2, B = this.bins;
    this.lut = new Int32Array(W * H);
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const dx = x + 0.5 - cx, dy = y + 0.5 - cy, r = Math.sqrt(dx * dx + dy * dy) / R;
      if (r >= 1) { this.lut[y * W + x] = -1; continue; }
      let a = Math.atan2(dx, -dy); if (a < 0) a += 2 * Math.PI;   // 0 = up, clockwise
      const g = Math.floor(a / (2 * Math.PI) * 400) % 400;
      this.lut[y * W + x] = g * B + Math.min(B - 1, Math.floor(r * B));
    }
    this.image = new ImageData(W, H);
  }
  render() {
    if (fitCanvas(this.img) || !this.lut) { this.buildLut(); this.dirty = true; }
    if (fitCanvas(this.ov)) this.drawOverlay();
    if (!this.dirty) return;
    const px = this.image.data, lut = this.lut, buf = this.buf, cm = this.cmap;
    for (let i = 0, j = 0; i < lut.length; i++, j += 4) {
      const k = lut[i];
      if (k < 0) { px[j + 3] = 0; continue; }
      const c = buf[k] * 4; px[j] = cm[c]; px[j + 1] = cm[c + 1]; px[j + 2] = cm[c + 2]; px[j + 3] = 255;
    }
    this.img.getContext('2d').putImageData(this.image, 0, 0);
    this.drawOverlay();
    this.dirty = false;
  }
  drawOverlay() {
    const c = this.ov, ctx = c.getContext('2d'), W = c.width, H = c.height, R = Math.min(W, H) / 2 - 1, cx = W / 2, cy = H / 2, d = DPR();
    ctx.clearRect(0, 0, W, H);
    ctx.strokeStyle = 'rgba(240,239,236,.22)'; ctx.lineWidth = d; ctx.fillStyle = 'rgba(240,239,236,.75)';
    ctx.font = `${11 * d}px system-ui, sans-serif`; ctx.textAlign = 'left'; ctx.textBaseline = 'bottom';
    const st = niceStep(this.range / 4);
    for (let r = st; r <= this.range + 1e-6; r += st) {
      const rp = r / this.range * R; ctx.beginPath(); ctx.arc(cx, cy, rp, 0, 2 * Math.PI); ctx.stroke();
      ctx.fillText(`${+r.toFixed(2)} m`, cx + 4 * d, cy - rp - 2 * d);
    }
    for (let deg = 0; deg < 360; deg += 45) {
      const a = deg * Math.PI / 180; ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(cx + Math.sin(a) * R, cy - Math.cos(a) * R); ctx.stroke();
    }
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    for (const [deg, lbl] of [[0, '0°'], [90, '90°'], [180, '180°'], [270, '270°']]) {
      const a = deg * Math.PI / 180, rr = R - 14 * d; ctx.fillText(lbl, cx + Math.sin(a) * rr, cy - Math.cos(a) * rr);
    }
    // sweep line
    const a = this.angle / 400 * 2 * Math.PI;
    ctx.strokeStyle = 'rgba(250,178,25,.9)'; ctx.lineWidth = 2 * d; ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(cx + Math.sin(a) * R, cy - Math.cos(a) * R); ctx.stroke();
  }
  onHover(e) {
    const r = this.ov.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    const R = Math.min(r.width, r.height) / 2, dx = x - r.width / 2, dy = y - r.height / 2, rr = Math.sqrt(dx * dx + dy * dy) / R;
    if (rr >= 1) { this.tip.style.display = 'none'; return; }
    let a = Math.atan2(dx, -dy); if (a < 0) a += 2 * Math.PI;
    const g = Math.floor(a / (2 * Math.PI) * 400) % 400, v = this.buf[g * this.bins + Math.floor(rr * this.bins)];
    this.tip.innerHTML = `${(a * 180 / Math.PI).toFixed(1)}° · ${(rr * this.range).toFixed(2)} m · echo <b>${v}</b>`;
    this.tip.style.display = 'block'; this.tip.style.left = (x + 14) + 'px'; this.tip.style.top = (y + 10) + 'px';
  }
}

/* ------------------------------------------------------------ A-scan */
class AScan {
  constructor(c) { this.c = c; this.data = null; this.range = 20; this.dirty = false; }
  set(data, range) { this.data = data; this.range = range; this.dirty = true; }
  draw() {
    fitCanvas(this.c);
    const ctx = this.c.getContext('2d'), d = DPR(), W = this.c.width / d, H = this.c.height / d;
    ctx.setTransform(d, 0, 0, d, 0, 0); ctx.clearRect(0, 0, W, H);
    const padL = 44, padR = 10, padT = 6, padB = 18, pw = W - padL - padR, ph = H - padT - padB;
    ctx.font = '11px system-ui, sans-serif'; ctx.fillStyle = theme.muted; ctx.strokeStyle = theme.grid; ctx.lineWidth = 1;
    ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    for (const v of [0, 128, 255]) { const y = Math.round(padT + ph - v / 255 * ph) + 0.5; ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + pw, y); ctx.stroke(); ctx.fillText(v, padL - 6, y); }
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    const st = niceStep(this.range / 5);
    for (let r = 0; r <= this.range + 1e-6; r += st) { ctx.textAlign = r + st > this.range + 1e-6 ? 'right' : 'center'; ctx.fillText(`${+r.toFixed(2)} m`, padL + r / this.range * pw, padT + ph + 4); }
    if (!this.data) return;
    ctx.strokeStyle = theme.s1; ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.beginPath();
    const n = this.data.length;
    for (let i = 0; i < n; i++) { const x = padL + (i + 0.5) / n * pw, y = padT + ph - this.data[i] / 255 * ph; i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }
    ctx.stroke(); this.dirty = false;
  }
}

/* ------------------------------------------------------------ echogram */
class Echogram {
  constructor(c, tip) {
    this.c = c; this.tip = tip; this.cols = []; this.maxCols = 600; this.depth = 10; this.dirty = false; this.cmap = CMAPS.blue;
    c.addEventListener('mousemove', (e) => this.hover(e)); c.addEventListener('mouseleave', () => { tip.style.display = 'none'; });
  }
  add(p) {
    this.cols.push(p); if (this.cols.length > this.maxCols) this.cols.shift();
    let m = 0; for (const c of this.cols) m = Math.max(m, c.start + c.len);
    this.depth = Math.max(1, m); this.dirty = true;
  }
  draw() {
    fitCanvas(this.c);
    const ctx = this.c.getContext('2d'), W = this.c.width, H = this.c.height, d = DPR();
    const padL = 44 * d, pw = W - padL - 10 * d, ph = H;
    ctx.fillStyle = css('--sonar-bg'); ctx.fillRect(0, 0, W, H);
    const n = this.cols.length; if (!n) return;
    const cw = pw / this.maxCols, img = ctx.createImageData(Math.max(1, Math.ceil(cw)), ph);
    for (let k = 0; k < n; k++) {
      const c = this.cols[k], x = padL + pw - (n - k) * cw, L = c.prof.length;
      if (!L) continue;
      const px = img.data, iw = img.width;
      for (let y = 0; y < ph; y++) {
        const depth = y / ph * this.depth, s = Math.floor((depth - c.start) / c.len * L);
        const v = (s >= 0 && s < L) ? c.prof[s] : 0, ci = v * 4;
        for (let xx = 0; xx < iw; xx++) { const j = (y * iw + xx) * 4; px[j] = this.cmap[ci]; px[j + 1] = this.cmap[ci + 1]; px[j + 2] = this.cmap[ci + 2]; px[j + 3] = 255; }
      }
      ctx.putImageData(img, Math.floor(x), 0);
    }
    // distance trace
    ctx.fillStyle = theme.warn;
    for (let k = 0; k < n; k++) { const c = this.cols[k]; if (c.conf < 50) continue; const x = padL + pw - (n - k - 0.5) * cw; ctx.fillRect(x - d, c.dist / this.depth * ph - d, 2 * d, 2 * d); }
    // axis
    ctx.fillStyle = theme.muted; ctx.font = `${11 * d}px system-ui, sans-serif`; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    ctx.clearRect(0, 0, padL, H); ctx.fillStyle = theme.surface; ctx.fillRect(0, 0, padL, H); ctx.fillStyle = theme.muted;
    const st = niceStep(this.depth / 4);
    for (let v = 0; v <= this.depth + 1e-6; v += st) { const y = Math.min(H - 6 * d, Math.max(6 * d, v / this.depth * ph)); ctx.fillText(`${+v.toFixed(2)} m`, padL - 6 * d, y); }
    this.dirty = false;
  }
  hover(e) {
    const r = this.c.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top, padL = 44, pw = r.width - padL - 10;
    const n = this.cols.length, k = n - Math.ceil((padL + pw - x) / (pw / this.maxCols));
    if (k < 0 || k >= n || x < padL) { this.tip.style.display = 'none'; return; }
    const c = this.cols[k], depth = y / r.height * this.depth;
    this.tip.innerHTML = `depth ${depth.toFixed(2)} m · bottom ${c.dist.toFixed(2)} m (${c.conf}%)`;
    this.tip.style.display = 'block'; this.tip.style.left = Math.min(x + 12, r.width - 230) + 'px'; this.tip.style.top = Math.min(y + 8, r.height - 26) + 'px';
  }
}

/* ------------------------------------------------------- DR track view */
class TrackView {
  constructor(c, read) { this.c = c; this.read = read; this.pts = []; this.dirty = false; this.yaw = 0; }
  add(p) { const l = this.pts[this.pts.length - 1]; if (l && Math.hypot(l.x - p.x, l.y - p.y) > 2 && Math.hypot(p.x, p.y) < 0.5) this.pts = []; this.pts.push(p); if (this.pts.length > 20000) this.pts.shift(); this.yaw = p.yaw; this.dirty = true; this.last = p; }
  clear() { this.pts = []; this.dirty = true; }
  draw() {
    fitCanvas(this.c);
    const ctx = this.c.getContext('2d'), d = DPR(), W = this.c.width / d, H = this.c.height / d;
    ctx.setTransform(d, 0, 0, d, 0, 0); ctx.clearRect(0, 0, W, H);
    let minx = -1, maxx = 1, miny = -1, maxy = 1;
    for (const p of this.pts) { minx = Math.min(minx, p.y); maxx = Math.max(maxx, p.y); miny = Math.min(miny, p.x); maxy = Math.max(maxy, p.x); }
    // north (x) up, east (y) right, equal aspect
    const pad = 16, sx = (W - 2 * pad) / (maxx - minx), sy = (H - 2 * pad) / (maxy - miny), s = Math.min(sx, sy);
    const cx = W / 2 - (minx + maxx) / 2 * s, cy = H / 2 + (miny + maxy) / 2 * s;
    const P = (p) => [cx + p.y * s, cy - p.x * s];
    const st = niceStep(Math.max(maxx - minx, maxy - miny) / 5);
    ctx.strokeStyle = theme.grid; ctx.lineWidth = 1;
    for (let v = Math.floor((cx - W) / s / st) * st - st; v * s + cx < W + st * s; v += st) { const x = cx + v * s; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
    for (let v = Math.floor(-cy / s / st) * st - st; cy - v * s > -st * s; v += st) { const y = cy - v * s; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
    ctx.fillStyle = theme.muted; ctx.font = '11px system-ui, sans-serif'; ctx.textAlign = 'right'; ctx.fillText(`grid ${+st.toFixed(3)} m`, W - 8, 14);
    if (!this.pts.length) return;
    ctx.strokeStyle = theme.s1; ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.beginPath();
    this.pts.forEach((p, i) => { const [x, y] = P(p); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }); ctx.stroke();
    const [x0, y0] = P(this.pts[0]); ctx.fillStyle = theme.muted; ctx.beginPath(); ctx.arc(x0, y0, 3, 0, 7); ctx.fill();
    const [x, y] = P(this.last), a = this.yaw * Math.PI / 180;
    ctx.save(); ctx.translate(x, y); ctx.rotate(a); ctx.fillStyle = theme.s2; ctx.strokeStyle = theme.surface; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(0, -9); ctx.lineTo(6, 6); ctx.lineTo(0, 3); ctx.lineTo(-6, 6); ctx.closePath(); ctx.stroke(); ctx.fill(); ctx.restore();
    this.read.textContent = `x ${fmt(this.last.x)} m · y ${fmt(this.last.y)} m · yaw ${fmt(this.last.yaw, 1)}° · σ ${fmt(this.last.std, 3)} m`;
    this.dirty = false;
  }
}

/* ============================================================ widgets */
const sonar = new SonarView($('sonarImg'), $('sonarOverlay'), $('sonarTip'));
const ascan = new AScan($('ascan'));
const p1dChart = new TimeChart($('p1dChart'), { series: [{ key: 'd', label: 'distance', color: () => theme.s1 }], unit: 'm', invert: true, yMin: 0 });
const p1dConf = new TimeChart($('p1dConfChart'), { series: [{ key: 'c', label: 'confidence', color: () => theme.s1 }], unit: '%', yMin: 0, yMax: 100, decimals: 0 });
const dvlChart = new TimeChart($('dvlChart'), {
  series: [{ key: 'vx', label: 'vx (forward)', color: () => theme.s1 }, { key: 'vy', label: 'vy (right)', color: () => theme.s2 }, { key: 'vz', label: 'vz (down)', color: () => theme.s3 }],
  unit: 'm/s', decimals: 3,
});
const echo = new Echogram($('echogram'), $('echoTip'));
const track = new TrackView($('track'), $('trackRead'));
const charts = [p1dChart, p1dConf, dvlChart];
$('p360Cmap').onchange = (e) => { sonar.setCmap(e.target.value); echo.cmap = CMAPS[e.target.value]; echo.dirty = true; };
$('p360Clear').onclick = () => sonar.clear();

function redrawAll() { charts.forEach((c) => c.draw()); ascan.draw(); echo.draw(); track.draw(); sonar.dirty = true; sonar.drawOverlay(); }
window.addEventListener('resize', () => { sonar.lut = null; redrawAll(); });

function frame() {
  sonar.render();
  if (ascan.dirty) ascan.draw();
  charts.forEach((c) => { if (c.dirty && c.hover === null) c.draw(); });
  if (echo.dirty) echo.draw();
  if (track.dirty) track.draw();
  requestAnimationFrame(frame);
}

/* ============================================================== health */
const SENSORS = [
  { key: 'ping360', name: 'Ping360', ch: 'ping360' },
  { key: 'ping1d', name: 'Ping / Ping2', ch: 'ping1d' },
  { key: 'dvl', name: 'DVL', ch: 'dvl' },
  { key: 'logger', name: 'Logger' },
];
const health = {};
const ICON = { ok: '✓', warn: '!', error: '×', stale: '×', none: '?' };
function buildHealth() {
  const box = $('health');
  for (const s of SENSORS) {
    const el = document.createElement('div'); el.className = 'hcard none';
    el.innerHTML = `<div class="icon">?</div><div class="name">${s.name}<span class="lvl">no status</span></div><div class="msg">waiting for node…</div>`
      + (s.ch ? `<div class="conn"><span class="pill pill-off"><i></i><b>checking…</b></span><span class="detail"></span></div>` : '') + `<div class="kv"></div>`;
    box.appendChild(el); health[s.key] = { el, status: null, t: 0 };
  }
}
function setHealth(key, level, label, msg, kv) {
  const h = health[key]; if (!h) return;
  h.el.className = 'hcard ' + level; h.el.querySelector('.icon').textContent = ICON[level] || '?';
  h.el.querySelector('.lvl').textContent = label; h.el.querySelector('.msg').textContent = msg; h.el.querySelector('.kv').textContent = kv || '';
}
const LEVEL_LABEL = { ok: 'OK', warn: 'warning', error: 'error', stale: 'no status' };
let rx = {};
/* Connection state per sensor:
   node offline  -> no status message from the driver node for > 3.5 s
   disconnected  -> node runs but cannot open the serial port / socket
   no data       -> device open, but nothing received for > 3 s
   connected     -> device open and data flowing */
function connState(s, now) {
  const h = health[s.key], st = h.status, r = rx[s.ch];
  const age = r && r.last ? now - r.last : Infinity;
  if (!st || now - h.t > 3.5) return { cls: 'pill-off', label: 'Node offline', detail: `no status from /${s.key} - is the node running?` };
  const v = st.values || {};
  if (v.connected === 'false') {
    const tries = Number(v.connect_attempts || 0);
    return { cls: 'pill-error', label: 'Disconnected', detail: `${v.target || st.hardware_id || ''}${tries ? ` · retry ${tries}` : ''}`, tip: st.message };
  }
  if (v.connected === 'true' && age > 3) return { cls: 'pill-warn', label: 'Connected · no data', detail: `${st.hardware_id}${isFinite(age) ? ` · last data ${age.toFixed(0)} s ago` : ' · no data yet'}` };
  const since = Number(v.connected_since || 0), up = since ? fmtDur(Math.max(0, now - since)) : '';
  const rc = Number(v.reconnects || 0);
  return { cls: 'pill-ok', label: 'Connected', detail: `${st.hardware_id}${up ? ' · up ' + up : ''}${rc ? ` · ${rc} reconnect${rc > 1 ? 's' : ''}` : ''}` };
}
function setConn(s, c) {
  for (const pill of [health[s.key].el.querySelector('.conn .pill'), $('conn-' + s.key)]) {
    if (!pill) continue;
    pill.className = 'pill ' + c.cls + (pill.id ? ' conn-pill' : ''); pill.querySelector('b').textContent = c.label; pill.title = c.tip ? `${c.detail}\n${c.tip}` : c.detail;
  }
  const d = health[s.key].el.querySelector('.conn .detail'); if (d) d.textContent = c.detail;
}
function refreshHealth() {
  const now = Date.now() / 1000;
  for (const s of SENSORS.slice(0, 3)) {
    const h = health[s.key], st = h.status, r = rx[s.ch];
    const age = r && r.last ? now - r.last : Infinity;
    setConn(s, connState(s, now));
    if (!st || now - h.t > 3.5) {
      setHealth(s.key, 'stale', 'no status', age < 3 ? 'data arriving, but no status topic' : 'node not running?', r ? `${r.count} msgs · last ${age.toFixed(1)} s ago` : '');
      continue;
    }
    const v = st.values || {}, parts = [];
    if (v.rate_hz) parts.push(`${v.rate_hz} Hz`);
    if (v.firmware) parts.push(`fw ${v.firmware}`);
    if (isFinite(age)) parts.push(`last msg ${age < 1 ? '<1' : age.toFixed(1)} s`);
    if (v.connected === 'false') parts.length = 0;
    setHealth(s.key, st.level, LEVEL_LABEL[st.level] || st.level, st.message, parts.join(' · '));
  }
  const lg = health.logger;
  if (!lg.status || now - lg.t > 3.5) setHealth('logger', 'stale', 'no status', 'sensor_logger not running?', '');
  else {
    const l = lg.status;
    setHealth('logger', l.active ? 'ok' : 'ok', l.active ? 'recording' : 'idle', l.active ? l.session : 'ready', l.active ? `${fmtDur(l.elapsed_s)}${l.bag ? ' · + rosbag' : ''}` : (l.directory ? `last: ${l.directory}` : ''));
  }
}
function fmtDur(s) { s = Math.floor(s); const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, ss = s % 60; return (h ? h + ':' : '') + String(m).padStart(h ? 2 : 1, '0') + ':' + String(ss).padStart(2, '0'); }
function fmtSize(b) { return b > 1e9 ? (b / 1e9).toFixed(2) + ' GB' : b > 1e6 ? (b / 1e6).toFixed(1) + ' MB' : b > 1e3 ? (b / 1e3).toFixed(0) + ' kB' : b + ' B'; }

/* ============================================================== logger */
let loggerState = null;
function updateLogger(l) {
  loggerState = l; health.logger.status = l; health.logger.t = Date.now() / 1000;
  const btn = $('logBtn'); btn.disabled = false;
  btn.classList.toggle('recording', l.active);
  btn.querySelector('.lbl').textContent = l.active ? 'Stop logging' : 'Start logging';
  $('logName').disabled = $('logNote').disabled = l.active;
  if (l.active) {
    const rows = Object.entries(l.rows || {}).map(([k, v]) => `${k} ${v.toLocaleString()}`).join(' · ');
    $('logStat').innerHTML = `<b>REC ${fmtDur(l.elapsed_s)}</b> · ${rows || 'waiting for data'}`;
  } else $('logStat').textContent = l.directory ? 'idle · last session saved' : 'idle';
}
$('logBtn').onclick = async () => {
  const btn = $('logBtn'); btn.disabled = true;
  const active = loggerState && loggerState.active;
  const r = active ? await command({ action: 'log_stop' })
    : await command({ action: 'log_start', name: $('logName').value, note: $('logNote').value });
  toast(r.message || (r.ok ? 'done' : 'failed'), r.ok); btn.disabled = false;
  setTimeout(loadLogs, 600);
};

async function loadLogs() {
  try {
    const j = await (await fetch('/api/logs')).json();
    $('logDir').textContent = j.log_dir;
    const tb = $('logRows'); tb.innerHTML = '';
    if (!j.sessions.length) { tb.innerHTML = '<tr><td colspan="7" class="muted">No sessions yet - press Start logging.</td></tr>'; return; }
    const activeDir = loggerState && loggerState.active ? loggerState.session : null;
    for (const s of j.sessions) {
      const i = s.info || {}, rows = Object.entries(i.rows || {}).map(([k, v]) => `${k}: ${v.toLocaleString()}`).join(', ');
      const tr = document.createElement('tr'); if (s.name === activeDir) tr.className = 'active';
      const files = s.files.map((f) => `<a href="/logs/${encodeURIComponent(s.name)}/${encodeURIComponent(f.name.replace(/\/$/, ''))}" title="${fmtSize(f.size)}">${f.name}</a>`).join('');
      const live = s.name === activeDir;
      tr.innerHTML = `<td>${s.name}</td><td>${escapeHtml(i.note || '')}</td><td>${live ? 'recording…' : i.duration_s !== undefined ? fmtDur(i.duration_s) : '–'}</td><td>${live ? '–' : rows || '–'}</td><td>${files}</td><td>${fmtSize(s.size)}</td><td><a href="/logs/${encodeURIComponent(s.name)}">zip</a></td>`;
      tb.appendChild(tr);
    }
  } catch (e) { /* offline */ }
}
function escapeHtml(s) { return s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
$('logsRefresh').onclick = loadLogs;

/* ============================================================ controls */
function bindForm(formId, sensor, transform) {
  const f = $(formId);
  f.addEventListener('submit', async (e) => {
    e.preventDefault();
    const items = [];
    for (const el of f.querySelectorAll('[name]')) {
      if (!el.dataset.type) continue;
      const v = el.type === 'checkbox' ? el.checked : el.dataset.type === 'string' ? el.value : Number(el.value);
      items.push({ name: el.name, value: v, type: el.dataset.type });
    }
    if (transform) items.push(...transform(f));
    let bad = null;
    for (const it of items) { const r = await command({ action: 'set_param', sensor, ...it }); if (!r.ok) { bad = r.message; break; } }
    toast(bad ? `Not applied: ${bad}` : 'Settings applied', !bad);
  });
}
const deg2grad = (d) => Math.round(Number(d) * 400 / 360) % 400;
bindForm('p360Form', 'ping360', (f) => [
  { name: 'start_angle', value: deg2grad(f.start_deg.value), type: 'integer' },
  { name: 'stop_angle', value: Math.min(399, Math.round(Number(f.stop_deg.value) * 400 / 360)), type: 'integer' },
]);
bindForm('p1dForm', 'ping1d');
$('dvlReset').onclick = async () => { const r = await command({ action: 'dvl_reset' }); toast(r.message, r.ok); if (r.ok) track.clear(); };

async function loadParams(formId, sensor, extra) {
  const f = $(formId), names = [...f.querySelectorAll('[data-type]')].map((e) => e.name).concat(extra || []);
  const r = await command({ action: 'get_params', sensor, names });
  if (!r.ok) return false;
  for (const [k, v] of Object.entries(r.values)) {
    const el = f.querySelector(`[name="${k}"]`); if (!el || v === null || v === undefined) continue;
    if (el.type === 'checkbox') el.checked = !!v; else el.value = v;
  }
  if (sensor === 'ping360' && r.values.start_angle !== undefined) {
    f.start_deg.value = +(r.values.start_angle * 0.9).toFixed(1); f.stop_deg.value = +(r.values.stop_angle * 0.9).toFixed(1);
  }
  return true;
}

/* ============================================================ data feed */
const rates = { ping360: [], ping1d: [], dvl: [] };
function tick(key) { const now = performance.now(), a = rates[key]; a.push(now); while (a.length && a[0] < now - 2000) a.shift(); }
function rate(key) { const a = rates[key]; return a.length > 1 ? (a.length - 1) / ((a[a.length - 1] - a[0]) / 1000 || 1) : 0; }

let lastDvlEnv = null, lastAtt = null;
function drawEnv() {
  const e = lastDvlEnv || {}, a = lastAtt;
  const parts = [`temperature ${e.temp !== null && e.temp !== undefined ? fmt(e.temp, 2) + ' °C' : '–'}`,
    `pressure ${e.pres !== null && e.pres !== undefined ? fmt(e.pres, 3) + ' bar' : '–'}`,
    `sound speed ${e.sos !== null && e.sos !== undefined ? fmt(e.sos, 1) + ' m/s' : '–'}`,
    a ? `roll ${fmt(a.roll, 1)}° · pitch ${fmt(a.pitch, 1)}° · heading ${fmt(a.yaw, 1)}°` : 'attitude –'];
  $('dvlEnv').textContent = parts.join(' · ');
}
const handlers = {
  ping360(d) {
    const data = b64(d.data); sonar.addPing(d.angle, d.range_m, data); ascan.set(data, d.range_m); tick('ping360');
    $('p360Angle').textContent = (d.angle * 0.9).toFixed(1) + '°'; $('p360Range').textContent = fmt(d.range_m, 1) + ' m';
  },
  ping1d(d, t) {
    tick('ping1d'); const ok = d.confidence > 0;
    p1dChart.push(t, [ok ? d.distance_m : null]); p1dConf.push(t, [d.confidence]);
    $('p1dDist').textContent = fmt(d.distance_m, 2) + ' m'; $('p1dConf').textContent = d.confidence + ' %';
    echo.add({ prof: b64(d.profile), start: d.scan_start_m, len: d.scan_length_m || 1, dist: d.distance_m, conf: d.confidence });
  },
  dvl(d, t) {
    tick('dvl');
    dvlChart.push(t, d.valid ? [d.vx, d.vy, d.vz] : [null, null, null]);
    $('dvlLock').innerHTML = d.valid ? '<span class="lock-yes">✓ yes</span>' : '<span class="lock-no">× no</span>';
    $('dvlAlt').textContent = d.altitude !== null && d.altitude >= 0 ? fmt(d.altitude, 2) + ' m' : '–';
    $('dvlAlt').title = d.alt_src ? `from ${d.alt_src.replace('_', ' ')}` : '';
    $('dvlFom').textContent = fmt(d.fom, 4);
    lastDvlEnv = d; drawEnv();
    const hasRssi = d.beams.some((b) => b.rssi !== null), hasFom = d.beams.some((b) => b.fom !== null);
    $('beams').tHead.innerHTML = `<tr><th>#</th><th>dist (m)</th><th>vel (m/s)</th>${hasFom ? '<th>FOM (m/s)</th>' : ''}${hasRssi ? '<th>RSSI (dBm)</th>' : ''}<th>lock</th></tr>`;
    $('beams').tBodies[0].innerHTML = d.beams.map((b) => `<tr><td>${b.id + 1}</td><td>${fmt(b.d, 2)}</td><td>${fmt(b.v, 3)}</td>${hasFom ? `<td>${fmt(b.fom, 4)}</td>` : ''}${hasRssi ? `<td>${fmt(b.rssi, 1)}</td>` : ''}<td class="${b.valid ? 'lock-yes' : 'lock-no'}">${b.valid ? '✓' : '×'}</td></tr>`).join('') || '<tr><td colspan="6" class="muted">no beam data in this protocol</td></tr>';
  },
  dvl_position(d) { track.add(d); lastAtt = d; drawEnv(); },
  logger(d) { updateLogger(d); },
  rx(d) { rx = d; },
};

let es, loadedParams = {};
function connect() {
  es = new EventSource('/events');
  const conn = $('conn');
  es.onopen = () => { conn.className = 'pill pill-ok'; conn.querySelector('b').textContent = 'live'; loadLogs(); };
  es.onerror = () => { conn.className = 'pill pill-error'; conn.querySelector('b').textContent = 'offline – retrying'; };
  es.onmessage = (ev) => {
    const m = JSON.parse(ev.data), t = m.d.stamp && m.d.stamp > 1e8 ? m.d.stamp : m.t;
    if (m.ch.startsWith('status_')) {
      const key = m.ch.slice(7); if (health[key]) { health[key].status = m.d; health[key].t = Date.now() / 1000; }
      if (!loadedParams[key] && m.d.level !== 'error') {
        loadedParams[key] = true;
        if (key === 'ping360') loadParams('p360Form', 'ping360', ['start_angle', 'stop_angle']).then((ok) => { loadedParams[key] = ok; });
        if (key === 'ping1d') loadParams('p1dForm', 'ping1d').then((ok) => { loadedParams[key] = ok; });
      }
      return;
    }
    const h = handlers[m.ch]; if (h) h(m.d, t);
  };
}

setInterval(() => {
  refreshHealth();
  $('p360Rate').textContent = fmt(rate('ping360'), 1) + ' Hz'; $('p1dRate').textContent = fmt(rate('ping1d'), 1) + ' Hz'; $('dvlRate').textContent = fmt(rate('dvl'), 1) + ' Hz';
}, 500);
setInterval(loadLogs, 15000);

buildHealth();
connect();
requestAnimationFrame(frame);
redrawAll();
