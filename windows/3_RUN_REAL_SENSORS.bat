@echo off
title Marine Sensor Bench - REAL SENSORS
cd /d "%~dp0"
echo Using settings from test_bench.yaml in this folder (edit ports / Nucleus IP there).
echo Serial sensors must be attached to WSL first: run 4_ATTACH_USB_SENSORS.bat
start "" /min powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0open_dashboard.ps1" -Port 8765
wsl.exe -d Ubuntu-24.04 -e bash "./run_bench.sh" real
pause
