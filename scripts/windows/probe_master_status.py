#!/usr/bin/env python3
"""Probe Public API status GETs against MASTER (display node 0).

Run on Windows mini PC with bridge already up (COM3 → 192.168.137.2).

  1) Signal aspect GET  — track/signalhead/32 Get  (Signal 0 on master)
  2) Signal aspect GET  — track/signalhead/432 Get (Signal 0 on node 4; control)
  3) Track power status — track/cmd/power/0 GET   (district 0 → master)

Expect MQTT status on track/signalmast/<packed> or track/power/<district>.
"""

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


def probe(label: str, pub_topic: str, pub_payload: str, listen_topics: list[str]) -> list[str]:
    rx: list[str] = []

    def listen() -> None:
        rx.extend(mqtt_listen(listen_topics, 6.0))

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    time.sleep(0.3)
    mqtt_pub(pub_topic, pub_payload)
    t.join()
    print(f"=== {label} RX count={len(rx)} ===", flush=True)
    for line in rx:
        print(f"  RX {line}", flush=True)
    return rx


def main() -> int:
    print("=== RESUBSCRIBE (include master node 0) ===", flush=True)
    mqtt_pub("track/bridge/cmd", "RESUBSCRIBE")
    time.sleep(6)

    print("=== USB PING ===", flush=True)
    mqtt_pub("track/bridge/cmd", "PING")
    time.sleep(1)

    # Master Signal 0 → packed 32. Needs a Signal object on MASTER to reply.
    probe(
        "SIGNAL GET master/32",
        "track/signalhead/32",
        "Get",
        ["track/signalmast/#", "track/sensor/#", "track/power/#"],
    )

    # Known Digicon plant path (node 4 Signal 0) — proves GET path if master has no signal.
    probe(
        "SIGNAL GET node4/432",
        "track/signalhead/432",
        "Get",
        ["track/signalmast/#", "track/sensor/#", "track/power/#"],
    )

    # Track power district 0 status request → MASTER.
    probe(
        "TRACK POWER GET district/0",
        "track/cmd/power/0",
        "GET",
        ["track/power/#", "track/sensor/#", "track/signalmast/#"],
    )

    print("=== DONE ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
