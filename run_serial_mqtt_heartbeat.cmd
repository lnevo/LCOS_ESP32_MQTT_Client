@echo off
REM Arduino Nano serial <-> MQTT. PING heartbeat + MQTT ACK publish + verbose TX lines.
REM Arduino DBG lines stay suppressed unless you pass --debug (see run_serial_mqtt_debug.cmd).
cd /d "%~dp0"

set "COM=COM3"
set "BROKER=192.168.137.1"

python "%~dp0serial_to_mqtt.py" --com %COM% --broker %BROKER% --debug-heartbeat --verbose %*
