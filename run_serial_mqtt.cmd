@echo off
setlocal EnableDelayedExpansion
REM Arduino Nano USB serial <-> MQTT. Defaults: COM3, BROKER below. Edit as needed.
cd /d "%~dp0"

set "COM=COM3"
set "BROKER=192.168.137.1"
set "EXTRA="

:ploop
if "%~1"=="" goto prun

if /i "%~1"=="-h" goto pmhelp
if /i "%~1"=="-?" goto pmhelp
if /i "%~1"=="/h" goto pmhelp
if /i "%~1"=="/?" goto pmhelp
if /i "%~1"=="help" goto pmhelp

if /i "%~1"=="verbose" goto pverbose
if /i "%~1"=="-verbose" goto pverbose
if /i "%~1"=="--verbose" goto pverbose

if /i "%~1"=="debug" goto pdebug
if /i "%~1"=="--debug" goto pdebug

if /i "%~1"=="heartbeat" goto pheartbeat
if /i "%~1"=="--debug-heartbeat" goto pheartbeat

if "!EXTRA!"=="" (set "EXTRA=%~1") else (set "EXTRA=!EXTRA! %~1")
shift
goto ploop

:pverbose
if "!EXTRA!"=="" (set "EXTRA=--verbose") else (set "EXTRA=!EXTRA! --verbose")
shift
goto ploop

:pdebug
if "!EXTRA!"=="" (set "EXTRA=--debug") else (set "EXTRA=!EXTRA! --debug")
shift
goto ploop

:pheartbeat
if "!EXTRA!"=="" (set "EXTRA=--debug-heartbeat") else (set "EXTRA=!EXTRA! --debug-heartbeat")
shift
goto ploop

:pmhelp
echo run_serial_mqtt.cmd — run serial_to_mqtt.py with COM=%COM% BROKER=%BROKER%
echo.
echo  Help:  -h  -?  /h  /?  help
echo.
echo  Options ^(words only; CMD does not use -v / -hb^):
echo    verbose      MQTT publish lines
echo    debug        Arduino DBG ... on console
echo    heartbeat    serial PING + MQTT ACK ^(--debug-heartbeat^)
echo.
echo  Other tokens pass through ^(e.g. --com COM5 --broker 10.0.0.1^).
echo  Python flags:  python serial_to_mqtt.py --help
exit /b 0

:prun
python "%~dp0serial_to_mqtt.py" --com %COM% --broker %BROKER% !EXTRA!
exit /b %ERRORLEVEL%
