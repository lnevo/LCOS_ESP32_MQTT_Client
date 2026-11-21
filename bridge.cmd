@echo off
REM bridge start^|stop^|restart^|status^|log^|install^|uninstall  (see scripts\windows\bridge.ps1)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\bridge.ps1" %*
