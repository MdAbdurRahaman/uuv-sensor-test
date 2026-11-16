#!/usr/bin/env bash
# Usage: run_bench.sh sim|real   (started by the .bat files)
# If ros2_ws_marine_sensors.zip in this folder is newer than the installed copy,
# the packages are updated and rebuilt first (no password needed).
HERE="$(cd "$(dirname "$0")" && pwd)"
WS="$HOME/ros2_ws"
ZIP="$HERE/ros2_ws_marine_sensors.zip"
STAMP="$WS/.marine_bench_zip_stamp"
REPO="$(cd "$HERE/.." && pwd)"
PKGS="marine_sensor_msgs ping360_driver ping1d_driver dvl_driver sensor_logger sensor_dashboard sensor_bringup"
. /opt/ros/jazzy/setup.bash
[ -f "$WS/install/setup.bash" ] || { echo "Not built yet - run 1_SETUP.bat first"; exit 1; }

# Update source: the zip next to this script, or (git clone) the repo's src/ folder.
NEWER=""
if [ -f "$ZIP" ]; then
  { [ ! -f "$STAMP" ] || [ "$ZIP" -nt "$STAMP" ]; } && NEWER=zip
elif [ -d "$REPO/src/sensor_bringup" ]; then
  { [ ! -f "$STAMP" ] || [ -n "$(find "$REPO/src" "$REPO/tools" -newer "$STAMP" -type f -print -quit)" ]; } && NEWER=repo
fi
if [ -n "$NEWER" ]; then
  echo "==> Update found ($NEWER) - updating and rebuilding..."
  TMP="$(mktemp -d)"
  if [ "$NEWER" = zip ]; then
    python3 -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$ZIP" "$TMP"
    SRC="$TMP/ros2_ws"
  else
    SRC="$REPO"
  fi
  for p in $PKGS; do rsync -a --delete --exclude __pycache__ "$SRC/src/$p/" "$WS/src/$p/"; touch "$WS/src/$p/.marine_bench"; done
  cp "$SRC/tools/plot_session.py" "$WS/tools/" 2>/dev/null
  rm -rf "$TMP"
  (cd "$WS" && colcon build --symlink-install --packages-up-to sensor_bringup 2>&1 | tail -n 8)
  touch "$STAMP"
fi

. "$WS/install/setup.bash"
SIM=false; [ "$1" = "sim" ] && SIM=true
if [ "$SIM" = false ]; then
  for n in ping360 ping1d; do
    P=$(grep -A8 "^/$n:" "$HERE/test_bench.yaml" | grep -m1 ' port:' | awk '{print $2}' | tr -d '\r')
    if [ -n "$P" ] && [ ! -e "$P" ]; then
      if ls /dev/serial/by-id/* /dev/ttyUSB* /dev/ttyACM* >/dev/null 2>&1; then
        echo "==> $n port $P not found - identifying sensors..."; python3 "$HERE/identify_sensors.py" "$HERE/test_bench.yaml"
      else
        echo "!! No USB serial devices in WSL - run 4_ATTACH_USB_SENSORS.bat (Ping360 / Ping2 will show Disconnected)"
      fi
      break
    fi
  done
fi
PORT=$(grep -A4 '^/sensor_dashboard:' "$HERE/test_bench.yaml" | grep -m1 'port:' | awk '{print $2}')
PORT=${PORT:-8765}
echo "Dashboard: http://localhost:$PORT   or   http://$(hostname -I | awk '{print $1}'):$PORT      (Ctrl+C to stop)"
echo "Settings file: $HERE/test_bench.yaml"
exec ros2 launch sensor_bringup test_bench.launch.py simulate:=$SIM params_file:="$HERE/test_bench.yaml" port:=$PORT "${@:2}"
