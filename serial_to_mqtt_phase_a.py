#!/usr/bin/env python3
"""
Phase A: Serial -> MQTT only (read-only bridge, matches serial_to_mqtt.ps1 read path).

Arduino sends one line per message:  <topic><space><payload>\\n  (LF only).
We publish each line to the MQTT broker with retain=True (same as mosquitto_pub -r).

Usage (Windows):
  python serial_to_mqtt_phase_a.py --com COM3 --broker 192.168.137.1
  python serial_to_mqtt_phase_a.py --com COM3 --broker 192.168.137.1 --verbose

Requires: pip install pyserial paho-mqtt
"""

from __future__ import annotations

import argparse
import signal
import sys
import time

import serial
import paho.mqtt.client as mqtt

# paho-mqtt 2.x requires callback_api_version; 1.x does not
def _make_mqtt_client() -> mqtt.Client:
    try:
        return mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
            protocol=mqtt.MQTTv311,
        )
    except (AttributeError, TypeError):
        return mqtt.Client(protocol=mqtt.MQTTv311)


DEFAULT_COM = "COM3"
DEFAULT_BAUD = 115200
DEFAULT_BROKER = "192.168.137.1"
DEFAULT_MQTT_PORT = 1883


def parse_line(line: str) -> tuple[str, str] | None:
    line = line.strip("\r\n")
    if not line or line.isspace():
        return None
    i = line.find(" ")
    if i < 1:
        return None
    topic = line[:i]
    payload = line[i + 1 :].lstrip() if i + 1 < len(line) else ""
    if not topic.startswith("track"):
        return None
    if not payload:
        return None
    return topic, payload


def main() -> int:
    ap = argparse.ArgumentParser(description="Serial (LCOS MQTT lines) -> MQTT broker")
    ap.add_argument("--com", default=DEFAULT_COM, help=f"Serial port (default {DEFAULT_COM})")
    ap.add_argument("--baud", type=int, default=DEFAULT_BAUD, help=f"Baud rate (default {DEFAULT_BAUD})")
    ap.add_argument("--broker", "-H", default=DEFAULT_BROKER, help=f"MQTT broker host (default {DEFAULT_BROKER})")
    ap.add_argument("--mqtt-port", type=int, default=DEFAULT_MQTT_PORT, help=f"MQTT port (default {DEFAULT_MQTT_PORT})")
    ap.add_argument("--verbose", "-v", action="store_true", help="Print each publish to stdout")
    args = ap.parse_args()

    client = _make_mqtt_client()
    try:
        client.connect(args.broker, args.mqtt_port, keepalive=60)
    except OSError as e:
        print(f"Failed to connect to MQTT broker at {args.broker}:{args.mqtt_port}: {e}", file=sys.stderr)
        return 1

    client.loop_start()

    # Same sanity check as PowerShell script
    try:
        info = client.publish("track/test", "ping", qos=1, retain=False)
        if hasattr(info, "wait_for_publish"):
            info.wait_for_publish(timeout=5.0)
        else:
            time.sleep(0.2)
    except Exception as e:
        print(f"MQTT publish test failed: {e}", file=sys.stderr)
        client.loop_stop()
        client.disconnect()
        return 1

    print(f"Connected to MQTT broker at {args.broker}")
    print(f"Opening {args.com} @ {args.baud} baud — Serial -> MQTT (Phase A). Ctrl+C to stop.")

    stop = False

    def on_sigint(_sig, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, on_sigint)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, on_sigint)

    try:
        ser = serial.Serial(
            port=args.com,
            baudrate=args.baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.25,
        )
    except serial.SerialException as e:
        print(f"Serial open failed: {e}", file=sys.stderr)
        client.loop_stop()
        client.disconnect()
        return 1

    try:
        while not stop:
            try:
                raw = ser.readline()
                if not raw:
                    continue
                try:
                    line = raw.decode("utf-8", errors="replace")
                except Exception:
                    continue
                parsed = parse_line(line)
                if parsed is None:
                    continue
                topic, payload = parsed
                info = client.publish(topic, payload, qos=0, retain=True)
                if args.verbose:
                    print(f"TX -> {topic} {payload}")
                # Optional: info.wait_for_publish(1.0) if you need back-pressure
            except serial.SerialException as e:
                print(f"Serial error: {e}", file=sys.stderr)
                time.sleep(0.5)
    finally:
        ser.close()
        client.loop_stop()
        client.disconnect()
        print("Stopped.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
