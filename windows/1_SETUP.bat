@echo off
title Marine Sensor Bench - SETUP
REM Installs and builds everything inside WSL (Ubuntu-24.04 / ROS 2 Jazzy).
cd /d "%~dp0"
echo Setting up the marine sensor workspace in WSL (Ubuntu-24.04)...
echo You may be asked for your WSL (Linux) password once.
echo.
wsl.exe -d Ubuntu-24.04 -e bash "./setup_wsl.sh"
echo.
pause
