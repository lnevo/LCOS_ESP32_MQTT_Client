@echo off
REM Kill background serial_to_mqtt.py bridge processes.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0kill_bridge.ps1"
pause
