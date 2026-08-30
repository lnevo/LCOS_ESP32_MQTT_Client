#!/usr/bin/env python3
"""Kill serial_to_mqtt then run flash_lcos.bat; print FLASH_OK/FAIL."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def kill_bridge() -> None:
    ps = (
        "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
        "Where-Object { $_.CommandLine -and ($_.CommandLine -match 'serial_to_mqtt\\.py') } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False)
    import time

    time.sleep(2)


def main() -> int:
    kill_bridge()
    bat = ROOT / "flash_lcos.bat"
    r = subprocess.run(
        ["cmd", "/c", str(bat)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (r.stdout or "") + (r.stderr or "")
    for line in out.splitlines()[-40:]:
        print(line.encode("ascii", "replace").decode("ascii"), flush=True)
    print(f"EXIT={r.returncode}", flush=True)
    if r.returncode == 0:
        print("FLASH_OK", flush=True)
        return 0
    print("FLASH_FAIL", flush=True)
    return r.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
