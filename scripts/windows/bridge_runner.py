#!/usr/bin/env python3
"""Run serial_to_mqtt.py in the background and write its output to logs/bridge.log.

Started by bridge.ps1 (the LcosBridge scheduled task at boot, or `bridge start`).
Each line gets a timestamp. If the bridge exits (COM port not ready yet, crash),
it is restarted after RESTART_DELAY seconds. Stop it with `bridge stop`.

Extra arguments are passed to serial_to_mqtt.py; with none, the defaults below
match `run_serial_mqtt.cmd verbose`.
"""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / "logs"
LOG = LOG_DIR / "bridge.log"
MAX_BYTES = 20 * 1024 * 1024  # rotate to bridge.log.1 at start-up when bigger
RESTART_DELAY = 10
DEFAULT_ARGS = ["--com", "COM3", "--broker", "10.0.0.150", "--verbose"]


def stamp() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def rotate() -> None:
    try:
        if LOG.exists() and LOG.stat().st_size > MAX_BYTES:
            os.replace(LOG, LOG.with_suffix(".log.1"))
    except OSError:
        pass  # a reader has it open; try again next start


def main() -> int:
    LOG_DIR.mkdir(exist_ok=True)
    rotate()
    args = sys.argv[1:] or DEFAULT_ARGS
    cmd = [sys.executable, "-u", str(ROOT / "serial_to_mqtt.py"), *args]
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    with LOG.open("a", encoding="utf-8", errors="replace", buffering=1) as log:

        def note(msg: str) -> None:
            log.write(f"{stamp()} [runner] {msg}\n")

        note(f"runner pid {os.getpid()} starting: {' '.join(cmd)}")
        while True:
            proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            note(f"bridge pid {proc.pid} started")
            assert proc.stdout is not None
            for line in proc.stdout:
                log.write(f"{stamp()} {line.rstrip()}\n")
            rc = proc.wait()
            note(f"bridge exited rc={rc}; restarting in {RESTART_DELAY}s")
            time.sleep(RESTART_DELAY)


if __name__ == "__main__":
    raise SystemExit(main())
