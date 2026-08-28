$ErrorActionPreference = 'Continue'
$dir = 'C:\Users\lnevo\Documents\LCOS_ESP32_MQTT_Client'
Set-Location $dir
$env:PYTHONUNBUFFERED = '1'

$out = Join-Path $dir '_smoke.out.log'
$err = Join-Path $dir '_smoke.err.log'
Remove-Item $out,$err -ErrorAction SilentlyContinue

$p = Start-Process -FilePath python -ArgumentList @(
  '-u','serial_to_mqtt.py','--com','COM3','--broker','192.168.137.2','--verbose','--debug'
) -WorkingDirectory $dir -RedirectStandardOutput $out -RedirectStandardError $err -PassThru -WindowStyle Hidden

Write-Host "PID=$($p.Id)"
Start-Sleep 6

@'
import paho.mqtt.client as mqtt, time
got=[]
def on_message(c,u,m):
    if m.retain: return
    line=f"{m.topic} {m.payload.decode('utf-8','replace')}"
    print("RX", line, flush=True)
    got.append(line)
c=mqtt.Client(protocol=mqtt.MQTTv311)
c.on_message=on_message
c.connect("192.168.137.2",1883,60)
c.subscribe("track/turnout/408")
c.loop_start()
time.sleep(1)
print("PUB THROWN", flush=True)
c.publish("track/cmd/turnout/408","THROWN",qos=1)
time.sleep(5)
print("PUB CLOSED", flush=True)
c.publish("track/cmd/turnout/408","CLOSED",qos=1)
time.sleep(5)
c.loop_stop(); c.disconnect()
print("live_msgs", len(got), flush=True)
'@ | Set-Content (Join-Path $dir '_smoke_pub.py') -Encoding ASCII

python (Join-Path $dir '_smoke_pub.py')
Write-Host '==== BRIDGE ===='
Get-Content $out

Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
Start-Sleep 1
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'serial_to_mqtt' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Write-Host 'COM3_FREE'
