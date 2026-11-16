@echo off
title Marine Sensor Bench - DIAGNOSTICS
echo Collecting diagnostics (about 30 s). Keep the bench window running...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0diag.ps1"
pause
