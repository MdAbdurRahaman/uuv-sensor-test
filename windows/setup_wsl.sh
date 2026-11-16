#!/usr/bin/env bash
# Installs + builds the marine sensor workspace inside WSL (Ubuntu 24.04, ROS 2 Jazzy).
# Started by 1_SETUP.bat. Safe to run again (it updates the packages and rebuilds).
# Source: ros2_ws_marine_sensors.zip next to this script, or - when run from a
# git clone of uuv-sensor-test - the repo's own src/ folder (../src).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ZIP="$HERE/ros2_ws_marine_sensors.zip"
REPO="$(cd "$HERE/.." && pwd)"
WS="$HOME/ros2_ws"
PKGS="marine_sensor_msgs ping360_driver ping1d_driver dvl_driver sensor_logger sensor_dashboard sensor_bringup"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*"; exit 1; }

[ -f /opt/ros/jazzy/setup.bash ] || fail "ROS 2 Jazzy not found at /opt/ros/jazzy in this WSL distro."
if [ -f "$ZIP" ]; then SRCMODE=zip
elif [ -d "$REPO/src/sensor_bringup" ]; then SRCMODE=repo
else fail "No source found: put ros2_ws_marine_sensors.zip here or run from a clone of the repo"; fi
. /etc/os-release; say "WSL distro: $PRETTY_NAME   user: $USER   source: $SRCMODE"

say "1/6 Installing system packages (enter your WSL password if asked)"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-serial python3-colcon-common-extensions python3-pip \
     python3-numpy python3-matplotlib python3-pytest python3-rosdep ros-jazzy-rosbag2-storage-mcap rsync >/dev/null
echo "ok"

say "2/6 Installing Blue Robotics ping library (brping)"
if python3 -c "import brping" 2>/dev/null; then echo "already installed"; else
  pip3 install --break-system-packages --quiet bluerobotics-ping; echo "ok"; fi

say "3/6 Copying packages into $WS/src"
TMP="$(mktemp -d)"
if [ "$SRCMODE" = zip ]; then
  python3 -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$ZIP" "$TMP"
  SRC="$TMP/ros2_ws"
else
  SRC="$REPO"
fi
mkdir -p "$WS/src" "$WS/tools"
for p in $PKGS; do
  if [ -d "$WS/src/$p" ] && [ ! -L "$WS/src/$p" ] && [ ! -f "$WS/src/$p/.marine_bench" ]; then
    mv "$WS/src/$p" "$WS/src/${p}.backup_$(date +%s)"; echo "backed up existing $p"
  fi
  rsync -a --delete --exclude __pycache__ "$SRC/src/$p/" "$WS/src/$p/"
  touch "$WS/src/$p/.marine_bench"
done
cp "$SRC/tools/plot_session.py" "$WS/tools/"
[ -f "$WS/README_marine_sensors.md" ] || cp "$SRC/README.md" "$WS/README_marine_sensors.md"
rm -rf "$TMP"; touch "$WS/.marine_bench_zip_stamp"; echo "ok"

say "4/6 rosdep (dependencies)"
set +e
[ -f /etc/ros/rosdep/sources.list.d/20-default.list ] || sudo rosdep init >/dev/null 2>&1
rosdep update --rosdistro jazzy >/dev/null 2>&1
. /opt/ros/jazzy/setup.bash
rosdep install --from-paths $(for p in $PKGS; do echo "$WS/src/$p"; done) --ignore-src -r -y >/dev/null 2>&1 \
  && echo "ok" || echo "rosdep reported missing keys (usually harmless here), continuing"
set -e

say "5/6 Building (colcon)"
cd "$WS"
. /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-up-to sensor_bringup --event-handlers console_cohesion+ 2>&1 | tail -n 25
[ -f "$WS/install/sensor_bringup/share/sensor_bringup/launch/test_bench.launch.py" ] || fail "build failed - see messages above"

say "6/6 Shell + serial-port setup"
grep -q "ros2_ws/install/setup.bash" ~/.bashrc || {
  grep -q "/opt/ros/jazzy/setup.bash" ~/.bashrc || echo "source /opt/ros/jazzy/setup.bash" >> ~/.bashrc
  echo "source ~/ros2_ws/install/setup.bash" >> ~/.bashrc; }
id -nG | grep -qw dialout || { sudo usermod -aG dialout "$USER"; echo "added $USER to dialout (serial ports) - takes effect after 'wsl --shutdown'"; }

say "Quick self-test (unit tests)"
for p in ping360_driver ping1d_driver dvl_driver; do
  (cd "$WS/src/$p" && python3 -m pytest -q test -p no:cacheprovider 2>&1 | tail -n 1) || true
done

printf '\n\033[1;32mSETUP COMPLETE.\033[0m  Next: double-click 2_RUN_SIMULATION.bat\n'
