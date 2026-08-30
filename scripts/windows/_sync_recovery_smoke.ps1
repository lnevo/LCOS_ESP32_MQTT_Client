# Windows lab: sync recovery smoke (COM3 bridge + COM7 master reset sim)
$ErrorActionPreference = 'Continue'
$Root = Join-Path $env:USERPROFILE 'Documents\LCOS_ESP32_MQTT_Client'
Set-Location $Root
$Broker = '192.168.137.2'
$Log = Join-Path $Root '_sync_test_bridge.log'
$Result = Join-Path $Root '_sync_test_result.txt'
Remove-Item $Log, $Result -ErrorAction SilentlyContinue

function Kill-Bridge {
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and ($_.CommandLine -match 'serial_to_mqtt\.py') } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Seconds 2
}

function Pub-Mqtt([string]$topic, [string]$payload) {
  python -c @"
import paho.mqtt.client as mqtt, time
c=mqtt.Client()
c.connect('$Broker',1883,60)
c.loop_start()
c.publish('$topic','$payload',qos=1,retain=False)
time.sleep(0.4)
c.loop_stop(); c.disconnect()
print('PUB', '$topic', '$payload')
"@
}

function Capture-Mqtt([string]$topic, [int]$sec = 8) {
  python -c @"
import paho.mqtt.client as mqtt, time
seen=[]
def on_msg(c,u,m):
    try: p=m.payload.decode('utf-8','replace')
    except: p=repr(m.payload)
    seen.append(f'{m.topic} {p}')
    print('RX', m.topic, p, flush=True)
c=mqtt.Client(); c.on_message=on_msg
c.connect('$Broker',1883,60); c.subscribe('$topic',1); c.loop_start()
time.sleep($sec); c.loop_stop(); c.disconnect()
print('CAPTURE_COUNT', len(seen))
"@
}

Kill-Bridge
"=== START BRIDGE ===" | Tee-Object -FilePath $Result
$env:PYTHONUNBUFFERED = '1'
$p = Start-Process -FilePath python -ArgumentList @(
  '-u','serial_to_mqtt.py','--com','COM3','--broker',$Broker,'--verbose','--signalhead'
) -WorkingDirectory $Root -RedirectStandardOutput $Log -RedirectStandardError $Log -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 6

$boot = Get-Content $Log -ErrorAction SilentlyContinue | Select-Object -Last 40
$boot | Tee-Object -FilePath $Result -Append
if (-not ($boot -match 'Connected to MQTT')) {
  'FAIL: bridge did not connect' | Tee-Object -FilePath $Result -Append
  Kill-Bridge
  exit 1
}

"=== USB PING via MQTT cmd ===" | Tee-Object -FilePath $Result -Append
Pub-Mqtt 'track/bridge/cmd' 'PING' | Tee-Object -FilePath $Result -Append
Start-Sleep -Seconds 2
Select-String -Path $Log -Pattern 'ACK PING|USB PING|sync' | Select-Object -Last 15 |
  ForEach-Object { $_.Line } | Tee-Object -FilePath $Result -Append

"=== COM7 open/close (master reset sim) ===" | Tee-Object -FilePath $Result -Append
try {
  $sp = New-Object System.IO.Ports.SerialPort 'COM7',115200
  $sp.ReadTimeout = 500
  $sp.Open()
  Start-Sleep -Milliseconds 800
  try { $null = $sp.ReadExisting() } catch {}
  $sp.Close()
  'COM7_OK' | Tee-Object -FilePath $Result -Append
} catch {
  "COM7_FAIL $($_.Exception.Message)" | Tee-Object -FilePath $Result -Append
}
Start-Sleep -Seconds 2

"=== Turnout throw after COM7 (may be silent on sensors) ===" | Tee-Object -FilePath $Result -Append
# Packed 408 = node 4 UID 8 — common Digicon turnout; adjust if needed
$listener = Start-Job -ScriptBlock {
  param($b)
  python -c @"
import paho.mqtt.client as mqtt, time
seen=[]
def on_msg(c,u,m):
    p=m.payload.decode('utf-8','replace')
    if m.retain: return
    print(f'STATUS {m.topic} {p}', flush=True)
    seen.append(1)
c=mqtt.Client(); c.on_message=on_msg
c.connect('$b',1883,60)
c.subscribe('track/turnout/#',1); c.subscribe('track/sensor/#',1)
c.loop_start(); time.sleep(10); c.loop_stop(); c.disconnect()
print('STATUS_COUNT', len(seen))
"@
} -ArgumentList $Broker
Start-Sleep -Seconds 1
Pub-Mqtt 'track/cmd/turnout/408' 'THROWN' | Tee-Object -FilePath $Result -Append
Start-Sleep -Seconds 11
Receive-Job $listener | Tee-Object -FilePath $Result -Append
Remove-Job $listener -Force

"=== MQTT RESUBSCRIBE ===" | Tee-Object -FilePath $Result -Append
Pub-Mqtt 'track/bridge/cmd' 'RESUBSCRIBE' | Tee-Object -FilePath $Result -Append
Start-Sleep -Seconds 6
Select-String -Path $Log -Pattern 'RESUBSCRIBE|Subscription accepted|Subscription declined|sync:' |
  Select-Object -Last 30 | ForEach-Object { $_.Line } | Tee-Object -FilePath $Result -Append

"=== Turnout GET after RESUBSCRIBE ===" | Tee-Object -FilePath $Result -Append
$listener2 = Start-Job -ScriptBlock {
  param($b)
  python -c @"
import paho.mqtt.client as mqtt, time
seen=[]
def on_msg(c,u,m):
    if m.retain: return
    p=m.payload.decode('utf-8','replace')
    print(f'GETRX {m.topic} {p}', flush=True)
    seen.append(1)
c=mqtt.Client(); c.on_message=on_msg
c.connect('$b',1883,60); c.subscribe('track/turnout/408',1)
c.loop_start(); time.sleep(6); c.loop_stop(); c.disconnect()
print('GET_COUNT', len(seen))
"@
} -ArgumentList $Broker
Start-Sleep -Seconds 1
Pub-Mqtt 'track/cmd/turnout/408' 'GET' | Tee-Object -FilePath $Result -Append
Start-Sleep -Seconds 7
Receive-Job $listener2 | Tee-Object -FilePath $Result -Append
Remove-Job $listener2 -Force

"=== BRIDGE LOG TAIL ===" | Tee-Object -FilePath $Result -Append
Get-Content $Log -Tail 40 | Tee-Object -FilePath $Result -Append

'=== DONE pid=' + $p.Id | Tee-Object -FilePath $Result -Append
# leave bridge running for inspection; comment next line to keep it
# Kill-Bridge
