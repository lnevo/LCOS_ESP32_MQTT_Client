#!/usr/bin/env python3
"""SSH-safe detached bridge start for Windows lab."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "_probe_bridge.log"
DETACH_FLAGS = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def kill_bridge() -> None:
    ps = (
        "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
        "Where-Object { $_.CommandLine -and ($_.CommandLine -match 'serial_to_mqtt\\.py') } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False, capture_output=True)
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
            "--signalhead",
        ],
        cwd=str(ROOT),
        stdout=LOG.open("w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        creationflags=DETACH_FLAGS,
        close_fds=True,
    )
    print(f"BRIDGE_PID {proc.pid}", flush=True)
    text = ""
    for _ in range(35):
        time.sleep(1)
        text = LOG.read_text(encoding="utf-8", errors="replace") if LOG.exists() else ""
        if "Connected to MQTT" in text:
            print("CONNECTED True", flush=True)
            for line in text.splitlines():
                if any(k in line for k in ("Subscription", "online", "sync:", "ACK", "ERROR")):
                    print(line.encode("ascii", "replace").decode("ascii"), flush=True)
            return 0
    print("CONNECTED False", flush=True)
    print(text[-2500:].encode("ascii", "replace").decode("ascii"), flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
