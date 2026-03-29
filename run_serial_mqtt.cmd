@echo off
REM Default: quiet serial bridge, no PING heartbeat.
REM Verbose (MQTT TX lines on console, still NO heartbeat): run_serial_mqtt.cmd verbose
REM   or: run_serial_mqtt.cmd -verbose   or   run_serial_mqtt.cmd --verbose
REM Any other args pass through to serial_to_mqtt.py (e.g. --com COM5).
REM Heartbeat + verbose: use run_serial_mqtt_debug.cmd
cd /d "%~dp0"

set "COM=COM3"
set "BROKER=192.168.137.1"

set "VF="
if /i "%~1"=="verbose" set "VF=--verbose" & shift
if /i "%~1"=="-verbose" set "VF=--verbose" & shift
if /i "%~1"=="--verbose" set "VF=--verbose" & shift

python "%~dp0serial_to_mqtt.py" --com %COM% --broker %BROKER% %VF% %*
