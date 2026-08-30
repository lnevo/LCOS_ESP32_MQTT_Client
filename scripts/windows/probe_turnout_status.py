#!/usr/bin/env python3
"""Probe packed turnouts for MQTT status after RESUBSCRIBE. Run on Windows mini PC."""

from __future__ import annotations

import sys
import threading
import time

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("need paho-mqtt", file=sys.stderr)
    sys.exit(1)

BROKER = "192.168.137.2"
# 100 known-good on Windows lab; others often ACK with no status.
TURNOUTS = ["100", "108", "408", "411", "1208"]


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


def probe_one(packed: str) -> None:
    topics = [f"track/turnout/{packed}", "track/sensor/#"]
    rx: list[str] = []

    def listen():
        rx.extend(mqtt_listen(topics, 5.0))

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    time.sleep(0.3)
    mqtt_pub(f"track/cmd/turnout/{packed}", "GET")
    t.join()
    print(f"GET {packed} count={len(rx)}", flush=True)
    for line in rx:
        print(f"  RX {line}", flush=True)


def main() -> int:
    print("=== RESUBSCRIBE ===", flush=True)
    mqtt_pub("track/bridge/cmd", "RESUBSCRIBE")
    time.sleep(5)
    print("=== USB PING ===", flush=True)
    mqtt_pub("track/bridge/cmd", "PING")
    time.sleep(1)
    print("=== TURNOUT GET sweep ===", flush=True)
    for packed in TURNOUTS:
        probe_one(packed)
    print("=== DONE ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
