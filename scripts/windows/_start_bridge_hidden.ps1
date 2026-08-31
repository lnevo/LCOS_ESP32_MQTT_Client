$ErrorActionPreference = 'Continue'
$root = 'C:\Users\lnevo\Documents\LCOS_ESP32_MQTT_Client'
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and ($_.CommandLine -match 'serial_to_mqtt\.py') } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
$log = Join-Path $root '_probe_bridge.log'
$err = Join-Path $root '_probe_bridge.err.log'
foreach ($f in @($log, $err)) { if (Test-Path $f) { Remove-Item $f -Force } }
$py = (Get-Command python).Source
$argList = '-u serial_to_mqtt.py --com COM3 --broker 192.168.137.2 --verbose'
Start-Process -FilePath $py -ArgumentList $argList -WorkingDirectory $root `
  -RedirectStandardOutput $log -RedirectStandardError $err -WindowStyle Hidden
Start-Sleep -Seconds 14
Write-Host '---LOG---'
if (Test-Path $log) { Get-Content $log -Tail 50 } else { Write-Host 'NO_LOG' }
Write-Host '---ERR---'
if (Test-Path $err) { Get-Content $err -Tail 20 }
Write-Host '---PROC---'
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'serial_to_mqtt\.py' } |
  Select-Object ProcessId, CommandLine |
  Format-List
