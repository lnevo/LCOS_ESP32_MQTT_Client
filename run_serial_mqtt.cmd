@echo off
REM Shortcut: edit COM and BROKER here, then run this file or: run_serial_mqtt.cmd --verbose
cd /d "%~dp0"

set "COM=COM3"
set "BROKER=192.168.137.1"

python "%~dp0serial_to_mqtt.py" --com %COM% --broker %BROKER% %*
