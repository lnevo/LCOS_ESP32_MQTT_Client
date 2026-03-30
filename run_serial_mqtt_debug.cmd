@echo off
REM Arduino Nano serial <-> MQTT. Verbose MQTT TX + print DBG lines. No PING (use run_serial_mqtt_heartbeat.cmd).
cd /d "%~dp0"

set "COM=COM3"
set "BROKER=192.168.137.1"

python "%~dp0serial_to_mqtt.py" --com %COM% --broker %BROKER% --verbose --debug %*
