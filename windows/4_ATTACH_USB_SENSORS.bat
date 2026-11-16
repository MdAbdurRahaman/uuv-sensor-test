@echo off
title Marine Sensor Bench - ATTACH USB SENSORS
REM Shares the Ping360 / Ping2 USB adapters with WSL (asks for admin rights).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0attach_usb.ps1"
