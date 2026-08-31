#!/usr/bin/env python3
"""Start bridge in background on Windows lab PC; print short status."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "_probe_bridge.log"


def kill_bridge() -> None:
    ps = (
        "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
        "Where-Object { $_.CommandLine -and ($_.CommandLine -match 'serial_to_mqtt\\.py') } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        check=False,
        capture_output=True,
    )
    time.sleep(2)


def main() -> int:
    kill_bridge()
    if LOG.exists():
        LOG.unlink()
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
        ],
        cwd=str(ROOT),
        stdout=LOG.open("w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
    )
    print(f"BRIDGE_PID {proc.pid}", flush=True)
    time.sleep(16)
    text = LOG.read_text(encoding="utf-8", errors="replace") if LOG.exists() else ""
    print(f"CONNECTED {'Connected to MQTT' in text}", flush=True)
    print(f"ALIVE {proc.poll() is None}", flush=True)
    for line in text.splitlines():
        if any(
            k in line
            for k in (
                "Connected",
                "Subscription accepted",
                "ACK",
                "ERROR",
                "SerialException",
                "sync:",
                "online",
                "FAIL",
            )
        ):
            print(line.encode("ascii", "replace").decode("ascii"), flush=True)
    return 0 if "Connected to MQTT" in text else 1


if __name__ == "__main__":
    raise SystemExit(main())
