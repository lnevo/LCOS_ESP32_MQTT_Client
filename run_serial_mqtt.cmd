@echo off
REM Host bridge: Arduino Nano USB serial <-> MQTT. Quiet or verbose; no PING; DBG -> run_serial_mqtt_debug.cmd.
REM Verbose (MQTT TX lines only): run_serial_mqtt.cmd verbose  |  -verbose  |  --verbose
REM Heartbeat: run_serial_mqtt_heartbeat.cmd   |   DBG on console: run_serial_mqtt_debug.cmd
REM Extra args pass through (e.g. --com COM5 --debug).
cd /d "%~dp0"

set "COM=COM3"
set "BROKER=192.168.137.1"

set "VF="
if /i "%~1"=="verbose" set "VF=--verbose" & shift
if /i "%~1"=="-verbose" set "VF=--verbose" & shift
if /i "%~1"=="--verbose" set "VF=--verbose" & shift

python "%~dp0serial_to_mqtt.py" --com %COM% --broker %BROKER% %VF% %*
