#!/usr/bin/env python3
"""
Serial -> MQTT bridge (read-only from the Arduino's perspective: LCOS lines out, MQTT publish).

Arduino sends one line per message:  <topic><space><payload>\\n  (LF only).
We publish each line to the MQTT broker with retain=True (same as mosquitto_pub -r).

Optional debug heartbeat: every HEARTBEAT_INTERVAL_SEC, send HEARTBEAT_SERIAL_LINE to serial;
Arduino ACKs and (for "PING") sends LCOS turnout command: node 3, UID 8 (JMRI track/turnout/308) -> CLOSED.
We publish the "ACK ..." line to HEARTBEAT_MQTT_TOPIC (see DEBUG_HEARTBEAT).

Usage (Windows):
  python serial_to_mqtt.py --com COM3 --broker 192.168.137.1
  run_serial_mqtt.cmd
  run_serial_mqtt_debug.cmd

Requires: pip install pyserial paho-mqtt
"""

from __future__ import annotations

import argparse
import signal
import sys
import time

import serial
import paho.mqtt.client as mqtt

# paho-mqtt 2.x: use callback API v2 (v1 is deprecated). paho-mqtt 1.x has no CallbackAPIVersion.
def _make_mqtt_client() -> mqtt.Client:
    try:
        return mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            protocol=mqtt.MQTTv311,
        )
    except (AttributeError, TypeError):
        return mqtt.Client(protocol=mqtt.MQTTv311)


DEFAULT_COM = "COM3"
DEFAULT_BAUD = 115200
DEFAULT_BROKER = "192.168.137.1"
DEFAULT_MQTT_PORT = 1883

# --- Debug heartbeat (serial ping + publish Arduino "ACK ..." line to MQTT) ---
# Set True here, or pass --debug-heartbeat on the command line (either enables the feature).
DEBUG_HEARTBEAT = False
HEARTBEAT_INTERVAL_SEC = 10.0
# Text line sent to serial (LF-terminated). Arduino must treat as text (not binary 0/1).
HEARTBEAT_SERIAL_LINE = b"PING\n"
# MQTT topic for the raw serial reply (e.g. "ACK PING").
HEARTBEAT_MQTT_TOPIC = "track/bridge/heartbeat"


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
    ap.add_argument(
        "--debug-heartbeat",
        action="store_true",
        help="Enable serial heartbeat + MQTT publish of ACK replies (or set DEBUG_HEARTBEAT = True in script)",
    )
    args = ap.parse_args()

    heartbeat_on = bool(DEBUG_HEARTBEAT or args.debug_heartbeat)

    client = _make_mqtt_client()
    try:
        client.connect(args.broker, args.mqtt_port, keepalive=60)
    except OSError as e:
        print(f"Failed to connect to MQTT broker at {args.broker}:{args.mqtt_port}: {e}", file=sys.stderr)
        return 1

    client.loop_start()

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
    print(f"Opening {args.com} @ {args.baud} baud — Serial -> MQTT. Ctrl+C to stop.")
    if heartbeat_on:
        print(
            f"Debug heartbeat ON: every {HEARTBEAT_INTERVAL_SEC:g}s send {HEARTBEAT_SERIAL_LINE!r} "
            f"-> serial; publish replies to {HEARTBEAT_MQTT_TOPIC!r}"
        )

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

    last_heartbeat = time.monotonic()

    try:
        while not stop:
            try:
                now = time.monotonic()
                if heartbeat_on and (now - last_heartbeat) >= HEARTBEAT_INTERVAL_SEC:
                    ser.write(HEARTBEAT_SERIAL_LINE)
                    ser.flush()
                    last_heartbeat = now
                    if args.verbose:
                        print(f"HB -> serial {HEARTBEAT_SERIAL_LINE!r}")

                raw = ser.readline()
                if not raw:
                    continue
                try:
                    line = raw.decode("utf-8", errors="replace")
                except Exception:
                    continue
                stripped = line.strip("\r\n")

                parsed = parse_line(line)
                if parsed is not None:
                    topic, payload = parsed
                    client.publish(topic, payload, qos=0, retain=True)
                    if args.verbose:
                        print(f"TX -> {topic} {payload}")
                    continue

                if heartbeat_on and stripped.startswith("ACK "):
                    client.publish(HEARTBEAT_MQTT_TOPIC, stripped, qos=0, retain=True)
                    if args.verbose:
                        print(f"TX -> {HEARTBEAT_MQTT_TOPIC} {stripped}")
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
