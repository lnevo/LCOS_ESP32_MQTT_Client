# Run in THIS console (foreground). Do not Start-Process -WindowStyle Hidden.
Set-Location 'C:\Users\lnevo\Documents\LCOS_ESP32_MQTT_Client'
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -and ($_.CommandLine -match 'serial_to_mqtt\.py') } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
$env:PYTHONUNBUFFERED = '1'
python -u serial_to_mqtt.py --com COM3 --broker 192.168.137.2 --verbose

