#!/usr/bin/env python3
"""
Serial -> MQTT bridge (read-only from the LCOS node's perspective: LCOS lines out, MQTT publish).

Host companion for an Arduino Nano running the LCOS JMRI/MQTT bridge sketch (repo folder name
retains ESP32 historically). The Nano sends one line per message:  <topic><space><payload>\\n  (LF only).
We publish each line to the MQTT broker with retain=True (same as mosquitto_pub -r).

Optional debug heartbeat: every HEARTBEAT_INTERVAL_SEC, send HEARTBEAT_SERIAL_LINE to serial;
Arduino ACKs and sends LCOS turnout CMD (HB node/UID in firmware). Turnout MQTT lines come only from
real layout ops events on serial (confirmation), not from a synthetic publish after PING.
We publish the "ACK ..." line to HEARTBEAT_MQTT_TOPIC (see DEBUG_HEARTBEAT).

We always subscribe to HEARTBEAT_MQTT_TOPIC: payload exactly PING is relayed to serial (same bytes as
heartbeat). Arduino replies with ACK PING on that topic; that payload does not re-trigger serial.

On MQTT connect we publish BRIDGE_STATUS_ONLINE to track/bridge/status (retained). On clean exit we
publish BRIDGE_STATUS_OFFLINE (best-effort before disconnect).

Usage:
  Windows:  run_serial_mqtt.cmd [-h|/?|...] [verbose] [debug] [heartbeat] [-- python-args...]
            python serial_to_mqtt.py --com COM3 --broker ...
  Linux:    ./run_serial_mqtt.sh [-h|-?|--help] [-v] [-d] [-hb] [-- extra python args]
            SERIAL_PORT=/dev/ttyACM0 BROKER=... ./run_serial_mqtt.sh

Requires: pip install -r requirements.txt. Setup: docs/serial_mqtt_windows.md, docs/serial_mqtt_linux.md.
"""

from __future__ import annotations

import argparse
import queue
import re
import signal
import sys
import time

import serial
import paho.mqtt.client as mqtt

try:
    from paho.mqtt.enums import CallbackAPIVersion as _CallbackAPIVersion
    _CALLBACK_API_V2 = _CallbackAPIVersion.VERSION2
except ImportError:
    _CALLBACK_API_V2 = None  # paho-mqtt 1.x

# paho-mqtt 2.x: callback API v2 (v1 deprecated). 1.x: no enums module; Client() without it.
def _make_mqtt_client() -> mqtt.Client:
    if _CALLBACK_API_V2 is not None:
        try:
            return mqtt.Client(
                callback_api_version=_CALLBACK_API_V2,
                protocol=mqtt.MQTTv311,
            )
        except (AttributeError, TypeError):
            pass
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

# Host bridge presence: same topic for startup and shutdown (retained; QoS 1).
BRIDGE_STATUS_TOPIC = "track/bridge/status"
BRIDGE_STATUS_ONLINE = "online"
BRIDGE_STATUS_OFFLINE = "offline"

# JMRI -> bridge -> serial -> LCOS (distinct from state topic track/turnout/<packed>).
CMD_TURNOUT_TOPIC = "track/cmd/turnout"
_TURNOUT_CMD_PAYLOAD_RE = re.compile(r"^\d+\s+(THROWN|CLOSED)\s*$", re.IGNORECASE)


def _publish_bridge_status(
    client: mqtt.Client,
    payload: str,
    *,
    verbose: bool,
) -> bool:
    """Publish lifecycle payload to BRIDGE_STATUS_TOPIC. Returns True if publish completed."""
    try:
        info = client.publish(BRIDGE_STATUS_TOPIC, payload, qos=1, retain=True)
        if hasattr(info, "wait_for_publish"):
            info.wait_for_publish(timeout=5.0)
        else:
            time.sleep(0.2)
        if verbose:
            print(f"TX -> {BRIDGE_STATUS_TOPIC} {payload}")
        return True
    except Exception as e:
        print(f"MQTT bridge status publish failed ({payload!r}): {e}", file=sys.stderr)
        return False


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


def _turnout_cmd_payload_ok(payload: str) -> bool:
    return bool(_TURNOUT_CMD_PAYLOAD_RE.match(payload.strip()))


def _mqtt_connect_ok(reason_code: object) -> bool:
    """paho-mqtt v1: rc int 0; v2: ReasonCode with is_failure."""
    if isinstance(reason_code, int):
        return reason_code == 0
    return not getattr(reason_code, "is_failure", True)


def _argv_for_argparse(argv: list[str]) -> list[str]:
    """Treat lone -? /h /? /H or help as --help (single-argument invocations only)."""
    if len(argv) == 2 and argv[1] in ("-h", "--help", "-?", "/h", "/H", "/?", "help"):
        return [argv[0], "--help"]
    return argv


def main() -> int:
    sys.argv = _argv_for_argparse(sys.argv)

    ap = argparse.ArgumentParser(
        description="Serial (LCOS MQTT lines) -> MQTT broker",
        epilog="Launchers: run_serial_mqtt.cmd (help -h /?; options: verbose debug heartbeat), "
        "run_serial_mqtt.sh (-h -v -d -hb).",
    )
    ap.add_argument("--com", default=DEFAULT_COM, help=f"Serial port (default {DEFAULT_COM})")
    ap.add_argument("--baud", type=int, default=DEFAULT_BAUD, help=f"Baud rate (default {DEFAULT_BAUD})")
    ap.add_argument("--broker", "-H", default=DEFAULT_BROKER, help=f"MQTT broker host (default {DEFAULT_BROKER})")
    ap.add_argument("--mqtt-port", type=int, default=DEFAULT_MQTT_PORT, help=f"MQTT port (default {DEFAULT_MQTT_PORT})")
    ap.add_argument("--verbose", "-v", action="store_true", help="Print each publish to stdout")
    ap.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Print Arduino DBG ... lines from serial (MQTT_SERIAL_OPS_DEBUG on firmware); default is to ignore them",
    )
    ap.add_argument(
        "--debug-heartbeat",
        "--hb",
        action="store_true",
        help="Enable serial heartbeat + MQTT publish of ACK replies (or set DEBUG_HEARTBEAT = True in script)",
    )
    args = ap.parse_args()

    heartbeat_on = bool(DEBUG_HEARTBEAT or args.debug_heartbeat)

    ping_cmd_queue: queue.Queue[object] = queue.Queue(maxsize=32)
    turnout_cmd_queue: queue.Queue[bytes] = queue.Queue(maxsize=32)
    mqtt_sub_announced = False

    client = _make_mqtt_client()
    client.user_data_set((ping_cmd_queue, turnout_cmd_queue))

    def on_connect(_client, _userdata, _flags, reason_code, _properties=None):
        nonlocal mqtt_sub_announced
        if not _mqtt_connect_ok(reason_code):
            return
        _client.subscribe(HEARTBEAT_MQTT_TOPIC, qos=1)
        _client.subscribe(CMD_TURNOUT_TOPIC, qos=1)
        if not mqtt_sub_announced:
            print(
                f"Subscribed to {HEARTBEAT_MQTT_TOPIC!r} — MQTT payload PING -> serial "
                f"{HEARTBEAT_SERIAL_LINE!r}"
            )
            print(
                f"Subscribed to {CMD_TURNOUT_TOPIC!r} — payload '<packed> THROWN|CLOSED' -> serial "
                f'(line "{CMD_TURNOUT_TOPIC} ...")'
            )
            mqtt_sub_announced = True

    def on_message(_client, userdata, msg):
        ping_q, turnout_q = userdata
        if msg.topic == HEARTBEAT_MQTT_TOPIC:
            try:
                payload = msg.payload.decode("utf-8", errors="replace").strip()
            except Exception:
                return
            if payload != "PING":
                return
            if not isinstance(ping_q, queue.Queue):
                return
            try:
                ping_q.put_nowait(True)
            except queue.Full:
                pass
            return
        if msg.topic == CMD_TURNOUT_TOPIC:
            try:
                payload = msg.payload.decode("utf-8", errors="replace").strip()
            except Exception:
                return
            if not _turnout_cmd_payload_ok(payload):
                return
            line = f"{CMD_TURNOUT_TOPIC} {payload}\n".encode("utf-8")
            if not isinstance(turnout_q, queue.Queue):
                return
            try:
                turnout_q.put_nowait(line)
            except queue.Full:
                pass

    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(args.broker, args.mqtt_port, keepalive=60)
    except OSError as e:
        print(f"Failed to connect to MQTT broker at {args.broker}:{args.mqtt_port}: {e}", file=sys.stderr)
        return 1

    client.loop_start()

    bridge_online_published = _publish_bridge_status(client, BRIDGE_STATUS_ONLINE, verbose=args.verbose)
    if not bridge_online_published:
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
    _sigbreak = getattr(signal, "SIGBREAK", None)
    if _sigbreak is not None:
        signal.signal(_sigbreak, on_sigint)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, on_sigint)

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
        if bridge_online_published:
            _publish_bridge_status(client, BRIDGE_STATUS_OFFLINE, verbose=args.verbose)
        client.loop_stop()
        client.disconnect()
        return 1

    last_heartbeat = time.monotonic()

    try:
        while not stop:
            try:
                while True:
                    try:
                        line_out = turnout_cmd_queue.get_nowait()
                    except queue.Empty:
                        break
                    ser.write(line_out)
                    ser.flush()
                    if args.verbose:
                        print(f"MQTT -> serial {line_out!r}")

                while True:
                    try:
                        ping_cmd_queue.get_nowait()
                    except queue.Empty:
                        break
                    ser.write(HEARTBEAT_SERIAL_LINE)
                    ser.flush()
                    if args.verbose:
                        print(f"MQTT -> serial {HEARTBEAT_SERIAL_LINE!r}")

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

                if stripped.startswith("DBG "):
                    if args.debug:
                        print(stripped)
                    continue

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
        if bridge_online_published:
            _publish_bridge_status(client, BRIDGE_STATUS_OFFLINE, verbose=args.verbose)
        ser.close()
        client.loop_stop()
        client.disconnect()
        print("Stopped.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
