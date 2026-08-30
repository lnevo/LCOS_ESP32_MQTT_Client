#!/usr/bin/env python3
"""One SSH session: bridge up, probe MASTER remote signal GET + SET (packed 32).

Addressing: JMRI packed = displayNode*100 + signal UID. MASTER display digits are 0,
so Signal UID 32 → packed **32** (topic track/signalhead/32). Prefer saying
MASTER / packed 32 — not “node 0, signal 0”.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("need paho-mqtt", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[2]
BROKER = "192.168.137.2"
LOG = ROOT / "_probe_bridge.log"
# MASTER remote signal (UID 32) → packed 32
MASTER_SIGNAL_PACKED = "32"
# Plant control (optional): Digicon Signal UID 32 on display 4
PLANT_SIGNAL_PACKED = "432"


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
    time.sleep(0.4)
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


def probe(label: str, topic: str, payload: str, listen: list[str], seconds: float = 6.0) -> list[str]:
    rx: list[str] = []

    def listen_fn() -> None:
        rx.extend(mqtt_listen(listen, seconds))

    t = threading.Thread(target=listen_fn, daemon=True)
    t.start()
    time.sleep(0.3)
    mqtt_pub(topic, payload)
    t.join()
    print(f"=== {label} RX={len(rx)} ===", flush=True)
    for line in rx:
        print(f"  RX {line}", flush=True)
    return rx


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
    print(f"BRIDGE_PID {proc.pid}", flush=True)
    connected = False
    for _ in range(40):
        time.sleep(0.5)
        text = LOG.read_text(encoding="utf-8", errors="replace")
        if "Connected to MQTT" in text and "Opening COM3" in text:
            connected = True
            break
        if proc.poll() is not None:
            print("BRIDGE_DIED early", flush=True)
            print(text[-2000:], flush=True)
            return 1
    if not connected:
        print("BRIDGE_NOT_CONNECTED", flush=True)
        print(LOG.read_text(encoding="utf-8", errors="replace")[-2000:], flush=True)
        proc.terminate()
        return 1
    print("BRIDGE_UP", flush=True)
    time.sleep(4)

    mqtt_pub("track/bridge/cmd", "RESUBSCRIBE")
    time.sleep(5)
    mqtt_pub("track/bridge/cmd", "PING")
    time.sleep(1)

    # Radio sanity
    probe("TURNOUT GET 100", "track/cmd/turnout/100", "GET", ["track/turnout/100"])

    mast_listen = [f"track/signalmast/{MASTER_SIGNAL_PACKED}", "track/signalmast/#"]
    head = f"track/signalhead/{MASTER_SIGNAL_PACKED}"

    print(f"--- MASTER remote signal packed={MASTER_SIGNAL_PACKED} ---", flush=True)
    probe("MASTER SIGNAL GET", head, "Get", mast_listen)
    probe("MASTER SIGNAL SET Red", head, "Red", mast_listen)
    time.sleep(0.5)
    probe("MASTER SIGNAL GET after SET", head, "Get", mast_listen)
    probe("MASTER SIGNAL SET Yellow", head, "Yellow", mast_listen)
    time.sleep(0.5)
    probe("MASTER SIGNAL SET Green", head, "Green", mast_listen)

    # Optional plant path (enrolled Digicon) for comparison
    probe(
        f"PLANT SIGNAL GET {PLANT_SIGNAL_PACKED}",
        f"track/signalhead/{PLANT_SIGNAL_PACKED}",
        "Get",
        [f"track/signalmast/{PLANT_SIGNAL_PACKED}", "track/signalmast/#"],
    )

    print("=== BRIDGE LOG (ACK/MQTT/signal) ===", flush=True)
    for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        if any(
            k in line
            for k in (
                "ACK",
                "MQTT RX",
                "signalhead",
                "signalmast",
                "RESUBSCRIBE",
                "PING",
                "Subscription",
                "boot subscriptions",
                "track/turnout",
            )
        ):
            print(line.encode("ascii", "replace").decode("ascii"), flush=True)

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    logf.close()
    print("=== DONE ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
