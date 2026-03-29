@echo off
REM Same as run_serial_mqtt.cmd but enables serial heartbeat + MQTT publish of ACK replies.
cd /d "%~dp0"

set "COM=COM3"
set "BROKER=192.168.137.1"

python "%~dp0serial_to_mqtt_phase_a.py" --com %COM% --broker %BROKER% --debug-heartbeat --verbose %*
