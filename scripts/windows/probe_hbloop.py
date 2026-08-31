#!/usr/bin/env python3
"""Probe MASTER distributor echo: HBLOOP block beat from bridge node 015.

Theory: Nano broadcasts EVENT_BLOCK (block 7) to MASTER; if event-125 includes
self (015), distributor echoes it back → serial 'HBLOOP ECHO' (+ maybe
track/sensor/1507).
"""
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
            print("BRIDGE_DIED", text[-1500:], flush=True)
            return 1
    else:
        print("NO_CONNECT", flush=True)
        return 1
    print("BRIDGE_UP", flush=True)
    time.sleep(5)  # subscription accepts including self

    rx: list[str] = []

    def listen() -> None:
        rx.extend(mqtt_listen(["track/sensor/#"], 8.0))

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    time.sleep(0.3)
    mqtt_pub("track/bridge/cmd", "HBLOOP")
    time.sleep(2)
    mqtt_pub("track/bridge/cmd", "HBLOOP")
    t.join()

    print(f"=== MQTT sensor RX={len(rx)} ===", flush=True)
    for line in rx:
        print(f"  RX {line}", flush=True)

    text = LOG.read_text(encoding="utf-8", errors="replace")
    print("=== SERIAL HBLOOP / Subscription / sensor ===", flush=True)
    for line in text.splitlines():
        if any(
            k in line
            for k in (
                "HBLOOP",
                "Subscription",
                "boot subscriptions",
                "track/sensor/15",
                "ACK HBLOOP",
            )
        ):
            print(line.encode("ascii", "replace").decode("ascii"), flush=True)

    echoed = "HBLOOP ECHO" in text
    print(f"RESULT echo={'YES' if echoed else 'NO'}", flush=True)

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    logf.close()
    return 0 if echoed else 2


if __name__ == "__main__":
    raise SystemExit(main())
