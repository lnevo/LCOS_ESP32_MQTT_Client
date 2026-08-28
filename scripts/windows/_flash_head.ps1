$ErrorActionPreference = 'Stop'
$cli = 'C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe'
$sketch = 'C:\Users\lnevo\Documents\LCOS_ESP32_MQTT_Client'
$fqbn = 'arduino:avr:nano'

# Ensure COM3 free
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
  Where-Object { $_.CommandLine -match 'serial_to_mqtt' } |
  ForEach-Object {
    Write-Host "Killing bridge PID $($_.ProcessId)"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }
Start-Sleep 2

if (-not (Test-Path $cli)) { throw "arduino-cli not found: $cli" }

Write-Host '=== COMPILE ==='
& $cli compile -b $fqbn $sketch
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host '=== UPLOAD COM3 ==='
& $cli upload -p COM3 -b $fqbn $sketch
Write-Host "UPLOAD_EXIT $LASTEXITCODE"
exit $LASTEXITCODE
