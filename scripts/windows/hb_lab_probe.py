#!/usr/bin/env python3
"""Windows lab: start bridge, RESUBSCRIBE, capture HBLOOP lines for ~25s."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent if "__file__" in dir() else Path.cwd()
# when copied to scripts/windows
if Path("serial_to_mqtt.py").exists():
    ROOT = Path.cwd()

DETACH = 0x00000008 | 0x00000200
OUT = ROOT / "_hb_lab.out"
ERR = ROOT / "_hb_lab.err"

ps = (
    "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
    "Where-Object { $_.CommandLine -and ($_.CommandLine -match 'serial_to_mqtt\\.py') } | "
    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
)
subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False)
time.sleep(2)
for p in (OUT, ERR):
    if p.exists():
        p.unlink()

proc = subprocess.Popen(
    [
        sys.executable,
        "-u",
        "serial_to_mqtt.py",
        "--com",
        "COM3",
        "--broker",
        "192.168.137.2",
        "--verbose",
        "--signalhead",
    ],
    cwd=str(ROOT),
    stdout=OUT.open("w", encoding="utf-8"),
    stderr=ERR.open("w", encoding="utf-8"),
    creationflags=DETACH,
)
print(f"PID {proc.pid}", flush=True)
time.sleep(4)
try:
    import paho.mqtt.client as mqtt

    c = mqtt.Client()
    c.connect("192.168.137.2", 1883, 60)
    c.loop_start()
    time.sleep(0.3)
    c.publish("track/bridge/cmd", "RESUBSCRIBE", qos=1)
    print("PUB RESUBSCRIBE", flush=True)
    time.sleep(1)
    c.loop_stop()
    c.disconnect()
except Exception as e:
    print(f"mqtt fail: {e}", flush=True)

time.sleep(22)
subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False)
time.sleep(1)
print("---OUT---", flush=True)
print(OUT.read_text(encoding="utf-8", errors="replace") if OUT.exists() else "")
print("---ERR---", flush=True)
print(ERR.read_text(encoding="utf-8", errors="replace") if ERR.exists() else "")
