#!/usr/bin/env python3
"""Probe turnout SET after index translation fix."""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

ROOT = Path(r"C:/Users/lnevo/Documents/LCOS_ESP32_MQTT_Client")
BROKER = "192.168.137.2"
LOG = ROOT / "_probe_bridge.log"


def kill_bridge() -> None:
    ps = (
        "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
        "Where-Object { $_.CommandLine -and ($_.CommandLine -match 'serial_to_mqtt\\.py') } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False, capture_output=True)
    time.sleep(2)


def mqtt_pub(topic: str, payload: str) -> None:
    c = mqtt.Client()
    c.connect(BROKER, 1883, 60)
    c.loop_start()
    c.publish(topic, payload, qos=1, retain=False)
    time.sleep(0.35)
    c.loop_stop()
    c.disconnect()
    print(f"PUB {topic} {payload}", flush=True)


def mqtt_listen(topics: list[str], seconds: float) -> list[str]:
    seen: list[str] = []

    def on_msg(_c, _u, m):
        if getattr(m, "retain", False):
            return
        try:
            p = m.payload.decode("utf-8", "replace")
        except Exception:
            p = repr(m.payload)
        seen.append(f"{m.topic} {p}")

    c = mqtt.Client()
    c.on_message = on_msg
    c.connect(BROKER, 1883, 60)
    for t in topics:
        c.subscribe(t, 1)
    c.loop_start()
    time.sleep(seconds)
    c.loop_stop()
    c.disconnect()
    return seen


def probe(packed: str, cmd: str) -> None:
    rx: list[str] = []

    def listen() -> None:
        rx.extend(mqtt_listen(["track/turnout/#"], 5.0))

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    time.sleep(0.25)
    mqtt_pub(f"track/cmd/turnout/{packed}", cmd)
    t.join()
    print(f"=== {packed} {cmd} RX={len(rx)} ===", flush=True)
    for line in rx:
        print(f"  RX {line}", flush=True)


def main() -> int:
    kill_bridge()
    if LOG.exists():
        LOG.unlink()
    logf = LOG.open("w", encoding="utf-8", buffering=1)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "serial_to_mqtt.py",
            "--com",
            "COM3",
            "--broker",
            BROKER,
            "--verbose",
            "--signalhead",
        ],
        cwd=str(ROOT),
        stdout=logf,
        stderr=subprocess.STDOUT,
    )
    for _ in range(40):
        time.sleep(0.5)
        text = LOG.read_text(encoding="utf-8", errors="replace") if LOG.exists() else ""
        if "Connected to MQTT" in text and "Opening COM3" in text:
            break
        if proc.poll() is not None:
            print("BRIDGE_DIED", flush=True)
            print(text[-1500:], flush=True)
            return 1
    else:
        print("NO_CONNECT", flush=True)
        return 1
    print("BRIDGE_UP", flush=True)
    time.sleep(3)
    mqtt_pub("track/bridge/cmd", "RESUBSCRIBE")
    time.sleep(4)

    probe("408", "GET")
    probe("408", "CLOSED")
    time.sleep(1)
    probe("408", "GET")
    probe("408", "THROWN")
    time.sleep(1)
    probe("408", "GET")
    probe("400", "CLOSED")
    time.sleep(1)
    probe("400", "GET")

    print("=== LOG ===", flush=True)
    for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        if any(k in line for k in ("408", "400", "ACK track/cmd", "TX -> track/turnout", "rejected", "ignored")):
            print(line.encode("ascii", "replace").decode("ascii"), flush=True)

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    logf.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
