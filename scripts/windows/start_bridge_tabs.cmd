@echo off
REM Opens one Windows Terminal window with two tabs at logon:
REM   Bridge log - follows logs\bridge.log (Ctrl+C stops the tail only)
REM   MQTT sub   - sub.bat (mosquitto_sub on #)
REM The bridge itself runs in the background (LcosBridge task, starts at boot).
REM Control it with: bridge start / stop / restart / status / log
REM Install: copy into shell:startup on the layout mini PC.  Remove: delete it from shell:startup.

set "LCOS=%USERPROFILE%\Documents\LCOS_ESP32_MQTT_Client"

REM Short wait so the terminal opens after the desktop settles.
timeout /t 5 /nobreak >nul

REM Make sure the background bridge is up (no-op if the boot task already started it).
call "%LCOS%\bridge.cmd" start >nul 2>&1

wt -w hart-bridge new-tab --title "Bridge log" --suppressApplicationTitle -d "%LCOS%" powershell -NoProfile -ExecutionPolicy Bypass -File "%LCOS%\scripts\windows\bridge.ps1" log ; new-tab --title "MQTT sub" --suppressApplicationTitle -d "%LCOS%" cmd /k sub.bat ; focus-tab -t 0
