#!/usr/bin/env python3
"""Kill existing bridge, run serial_to_mqtt for N seconds, print all output."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SECONDS = int(sys.argv[1]) if len(sys.argv) > 1 else 40


def kill_bridge() -> None:
    ps = (
        "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
        "Where-Object { $_.CommandLine -and ($_.CommandLine -match 'serial_to_mqtt\\.py') } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False)
    time.sleep(2)


def main() -> int:
    kill_bridge()
    p = subprocess.Popen(
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
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    )
    deadline = time.time() + SECONDS
    n = 0
    while time.time() < deadline:
        if p.stdout is None:
            break
        line = p.stdout.readline()
        if line:
            print(line.rstrip("\r\n").encode("ascii", "replace").decode("ascii"), flush=True)
            n += 1
            if n > 400:
                break
        elif p.poll() is not None:
            print(f"EXIT {p.returncode}", flush=True)
            break
        else:
            time.sleep(0.05)
    p.terminate()
    try:
        p.wait(timeout=5)
    except Exception:
        p.kill()
    print(f"DONE lines={n}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
