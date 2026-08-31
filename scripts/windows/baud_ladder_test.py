#!/usr/bin/env python3
"""Baud ladder on COM3: flash Nano + USB PING/burst/HBLOOP probes per rate.

Run on the Windows mini PC from the bridge repo root (kills serial_to_mqtt while testing).
Restores 115200 when done unless --keep-baud is set.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    import serial
except ImportError:
    print("need pyserial", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[2]
INO = ROOT / "LCOS_ESP32_MQTT_Client.ino"
AGENT = ROOT / "serial_to_mqtt.py"
COM = "COM3"
# Conservative → aggressive. 2M often works on CH340; included last.
BAUDS = (115200, 250000, 500000, 1000000, 2000000)
PING_N = 50
BURST_N = 200


def kill_bridge() -> None:
    ps = (
        "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
        "Where-Object { $_.CommandLine -and ($_.CommandLine -match 'serial_to_mqtt\\.py') } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False)
    time.sleep(1.5)


def set_baud_sources(baud: int) -> None:
    ino = INO.read_text(encoding="utf-8")
    ino2, n1 = re.subn(
        r"Serial\.begin\(\s*\d+\s*\)", f"Serial.begin({baud})", ino, count=1
    )
    if n1 != 1:
        raise SystemExit(f"Serial.begin patch failed in {INO}")
    INO.write_text(ino2, encoding="utf-8")

    agent = AGENT.read_text(encoding="utf-8")
    agent2, n2 = re.subn(
        r"^DEFAULT_BAUD\s*=\s*\d+",
        f"DEFAULT_BAUD = {baud}",
        agent,
        count=1,
        flags=re.M,
    )
    if n2 != 1:
        raise SystemExit(f"DEFAULT_BAUD patch failed in {AGENT}")
    AGENT.write_text(agent2, encoding="utf-8")


def flash() -> bool:
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
    ok = r.returncode == 0
    tail = ((r.stdout or "") + (r.stderr or "")).splitlines()[-8:]
    for line in tail:
        print(f"  flash: {line.encode('ascii', 'replace').decode('ascii')}", flush=True)
    print(f"  FLASH={'OK' if ok else 'FAIL'} exit={r.returncode}", flush=True)
    time.sleep(2.0)
    return ok


def open_port(baud: int) -> serial.Serial:
    ser = serial.Serial()
    ser.port = COM
    ser.baudrate = baud
    ser.timeout = 0.15
    ser.dtr = False
    ser.rts = False
    ser.open()
    try:
        ser.dtr = False
        ser.rts = False
    except Exception:
        pass
    time.sleep(0.3)
    ser.reset_input_buffer()
    return ser


def drain(ser: serial.Serial, sec: float = 0.2) -> str:
    end = time.monotonic() + sec
    chunks: list[bytes] = []
    while time.monotonic() < end:
        n = ser.in_waiting
        if n:
            chunks.append(ser.read(n))
        else:
            time.sleep(0.01)
    return b"".join(chunks).decode("utf-8", errors="replace")


def wait_line(ser: serial.Serial, needle: str, timeout: float) -> bool:
    end = time.monotonic() + timeout
    buf = ""
    while time.monotonic() < end:
        chunk = ser.read(ser.in_waiting or 1).decode("utf-8", errors="replace")
        if chunk:
            buf += chunk
            if needle in buf:
                return True
        else:
            time.sleep(0.005)
    return False


def bench_ping(ser: serial.Serial, n: int) -> dict:
    ok = 0
    rtts: list[float] = []
    ser.reset_input_buffer()
    for _ in range(n):
        t0 = time.perf_counter()
        ser.write(b"PING\n")
        ser.flush()
        if wait_line(ser, "ACK PING", 0.5):
            ok += 1
            rtts.append((time.perf_counter() - t0) * 1000.0)
        # clear any extra
        if ser.in_waiting:
            ser.read(ser.in_waiting)
    rtts.sort()
    p50 = rtts[len(rtts) // 2] if rtts else None
    p95 = rtts[int(len(rtts) * 0.95)] if rtts else None
    return {
        "ok": ok,
        "n": n,
        "pct": 100.0 * ok / n,
        "rtt_p50_ms": p50,
        "rtt_p95_ms": p95,
        "rtt_max_ms": max(rtts) if rtts else None,
    }


def bench_burst(ser: serial.Serial, n: int) -> dict:
    """Fire-and-forget PINGs as fast as possible; count ACK PINGs in a drain window."""
    ser.reset_input_buffer()
    t0 = time.perf_counter()
    for _ in range(n):
        ser.write(b"PING\n")
    ser.flush()
    # Allow USB + Nano to catch up
    time.sleep(0.05)
    text = drain(ser, 2.0)
    elapsed = time.perf_counter() - t0
    acks = text.count("ACK PING")
    return {
        "sent": n,
        "acks": acks,
        "pct": 100.0 * acks / n,
        "elapsed_s": elapsed,
        "acks_per_s": acks / elapsed if elapsed > 0 else 0.0,
    }


def bench_hbloop(ser: serial.Serial, n: int = 10) -> dict:
    ack_ok = 0
    echo_ok = 0
    ser.reset_input_buffer()
    for _ in range(n):
        ser.write(b"HBLOOP\n")
        ser.flush()
        end = time.monotonic() + 0.6
        buf = ""
        while time.monotonic() < end:
            chunk = ser.read(ser.in_waiting or 1).decode("utf-8", errors="replace")
            if chunk:
                buf += chunk
                if "ACK HBLOOP" in buf and "HBLOOP ECHO" in buf:
                    break
            else:
                time.sleep(0.005)
        if "ACK HBLOOP" in buf:
            ack_ok += 1
        if "HBLOOP ECHO" in buf:
            echo_ok += 1
    return {"ack_ok": ack_ok, "n": n, "echo_ok": echo_ok}


def run_one(baud: int) -> dict:
    print(f"\n=== BAUD {baud} ===", flush=True)
    set_baud_sources(baud)
    if not flash():
        return {"baud": baud, "flash": False}
    try:
        ser = open_port(baud)
    except serial.SerialException as exc:
        print(f"  open FAIL: {exc}", flush=True)
        return {"baud": baud, "flash": True, "open": False, "error": str(exc)}

    # Discard boot chatter
    boot = drain(ser, 1.5)
    boot_ok = "LCOS" in boot or "Subscription" in boot or "HBLOOP_SELF" in boot or len(boot) > 0
    print(f"  boot_chars={len(boot)} boot_marker={boot_ok}", flush=True)

    ping = bench_ping(ser, PING_N)
    print(
        f"  PING {ping['ok']}/{ping['n']} ({ping['pct']:.0f}%) "
        f"rtt_ms p50={ping['rtt_p50_ms']:.2f} p95={ping['rtt_p95_ms']:.2f} "
        f"max={ping['rtt_max_ms']:.2f}"
        if ping["rtt_p50_ms"] is not None
        else f"  PING {ping['ok']}/{ping['n']} ({ping['pct']:.0f}%)",
        flush=True,
    )

    burst = bench_burst(ser, BURST_N)
    print(
        f"  BURST sent={burst['sent']} acks={burst['acks']} ({burst['pct']:.0f}%) "
        f"{burst['acks_per_s']:.0f} ack/s",
        flush=True,
    )

    hb = bench_hbloop(ser, 8)
    print(
        f"  HBLOOP ack={hb['ack_ok']}/{hb['n']} echo={hb['echo_ok']}/{hb['n']} "
        f"(echo needs radio path)",
        flush=True,
    )

    ser.close()
    return {
        "baud": baud,
        "flash": True,
        "open": True,
        "ping": ping,
        "burst": burst,
        "hbloop": hb,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--bauds",
        default=",".join(str(b) for b in BAUDS),
        help="comma-separated baud list",
    )
    ap.add_argument(
        "--keep-baud",
        type=int,
        default=None,
        help="leave firmware/agent at this baud after tests (default: restore 115200)",
    )
    args = ap.parse_args()
    bauds = [int(x.strip()) for x in args.bauds.split(",") if x.strip()]

    print(f"ROOT={ROOT}", flush=True)
    print(f"COM={COM} bauds={bauds}", flush=True)
    kill_bridge()

    results = []
    for baud in bauds:
        results.append(run_one(baud))

    restore = args.keep_baud if args.keep_baud is not None else 115200
    print(f"\n=== RESTORE {restore} ===", flush=True)
    set_baud_sources(restore)
    flash()

    print("\n=== SUMMARY ===", flush=True)
    print(
        f"{'baud':>8} {'flash':>5} {'ping%':>6} {'p50ms':>7} {'burst%':>7} {'ack/s':>7} {'hb_ack':>6}",
        flush=True,
    )
    for r in results:
        if not r.get("flash"):
            print(f"{r['baud']:>8} FAIL", flush=True)
            continue
        if not r.get("open"):
            print(f"{r['baud']:>8} {'OK':>5} OPEN_FAIL", flush=True)
            continue
        p = r["ping"]
        b = r["burst"]
        h = r["hbloop"]
        p50 = f"{p['rtt_p50_ms']:.2f}" if p["rtt_p50_ms"] is not None else "-"
        print(
            f"{r['baud']:>8} {'OK':>5} {p['pct']:5.0f}% {p50:>7} "
            f"{b['pct']:6.0f}% {b['acks_per_s']:7.0f} "
            f"{h['ack_ok']}/{h['n']}",
            flush=True,
        )

    # Recommend highest baud with >=99% ping and >=95% burst
    pick = None
    for r in results:
        if not r.get("open"):
            continue
        if r["ping"]["pct"] >= 99.0 and r["burst"]["pct"] >= 95.0:
            pick = r["baud"]
    print(
        f"\nRECOMMEND={pick if pick is not None else '115200 (no higher rate met bar)'}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
