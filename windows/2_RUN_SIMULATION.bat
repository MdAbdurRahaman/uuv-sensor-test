@echo off
title Marine Sensor Bench - SIMULATION
cd /d "%~dp0"
start "" /min powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0open_dashboard.ps1" -Port 8765
wsl.exe -d Ubuntu-24.04 -e bash "./run_bench.sh" sim
pause
