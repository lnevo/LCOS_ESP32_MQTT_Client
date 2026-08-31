#!/usr/bin/env python3
"""Paced USB sustain test at one baud (firmware already flashed). Find max ack/s."""

from __future__ import annotations

import argparse
import time

import serial

COM = "COM3"


def open_port(baud: int) -> serial.Serial:
    ser = serial.Serial()
    ser.port = COM
    ser.baudrate = baud
    ser.timeout = 0.1
    ser.dtr = False
    ser.rts = False
    ser.open()
    try:
        ser.dtr = False
        ser.rts = False
    except Exception:
        pass
    time.sleep(0.2)
    ser.reset_input_buffer()
    return ser


def drain(ser: serial.Serial, sec: float) -> str:
    end = time.monotonic() + sec
    chunks: list[bytes] = []
    while time.monotonic() < end:
        n = ser.in_waiting
        if n:
            chunks.append(ser.read(n))
        else:
            time.sleep(0.005)
    return b"".join(chunks).decode("utf-8", errors="replace")


def paced(ser: serial.Serial, n: int, gap_s: float) -> dict:
    ok = 0
    t0 = time.perf_counter()
    for _ in range(n):
        ser.write(b"PING\n")
        ser.flush()
        end = time.monotonic() + 0.4
        buf = ""
        while time.monotonic() < end:
            chunk = ser.read(ser.in_waiting or 1).decode("utf-8", errors="replace")
            if chunk:
                buf += chunk
                if "ACK PING" in buf:
                    ok += 1
                    break
            else:
                time.sleep(0.001)
        if gap_s > 0:
            time.sleep(gap_s)
    elapsed = time.perf_counter() - t0
    return {"ok": ok, "n": n, "elapsed": elapsed, "ack_s": ok / elapsed if elapsed else 0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baud", type=int, required=True)
    ap.add_argument("--n", type=int, default=40)
    args = ap.parse_args()
    ser = open_port(args.baud)
    drain(ser, 0.5)
    print(f"baud={args.baud}", flush=True)
    for gap_ms in (0, 0.5, 1, 2, 5):
        r = paced(ser, args.n, gap_ms / 1000.0)
        print(
            f"  gap={gap_ms:g}ms  {r['ok']}/{r['n']}  "
            f"{r['ack_s']:.0f} ack/s  elapsed={r['elapsed']:.2f}s",
            flush=True,
        )
    ser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
