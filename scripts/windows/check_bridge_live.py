#!/usr/bin/env python3
"""Check bridge process, publish PING, print log tail."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import paho.mqtt.client as mqtt

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "_probe_bridge.log"


def main() -> int:
    ps = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -match 'serial_to_mqtt\\.py' } | "
        "ForEach-Object { Write-Output ('PID=' + [string]$_.ProcessId) }"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
    )
    print("PROCS:", flush=True)
    print((r.stdout or "(none)").strip() or "(none)", flush=True)

    print(f"LOG_SIZE {LOG.stat().st_size if LOG.exists() else None}", flush=True)

    c = mqtt.Client()
    c.connect("192.168.137.2", 1883, 60)
    c.loop_start()
    c.publish("track/bridge/cmd", "PING", qos=1)
    print("PUB track/bridge/cmd PING", flush=True)
    time.sleep(3)
    c.publish("track/cmd/turnout/100", "GET", qos=1)
    print("PUB track/cmd/turnout/100 GET", flush=True)
    time.sleep(3)
    c.loop_stop()
    c.disconnect()

    print("---TAIL---", flush=True)
    if LOG.exists():
        for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]:
            print(line.encode("ascii", "replace").decode("ascii"), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
