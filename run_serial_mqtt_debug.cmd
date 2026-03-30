@echo off
REM Verbose MQTT TX + print Arduino DBG lines from serial. No PING heartbeat (use run_serial_mqtt_heartbeat.cmd).
cd /d "%~dp0"

set "COM=COM3"
set "BROKER=192.168.137.1"

python "%~dp0serial_to_mqtt.py" --com %COM% --broker %BROKER% --verbose --debug %*
