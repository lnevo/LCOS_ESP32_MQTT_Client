#!/usr/bin/env python3
"""
Serial -> MQTT bridge (read-only from the LCOS node's perspective: LCOS lines out, MQTT publish).

Host companion for an Arduino Nano running the LCOS JMRI/MQTT bridge sketch (repo folder name
retains ESP32 historically). The Nano sends one line per message:  <topic><space><payload>\\n  (LF only).
We publish each line to the MQTT broker with retain=True (same as mosquitto_pub -r).

Optional debug heartbeat: every HEARTBEAT_INTERVAL_SEC, send HEARTBEAT_SERIAL_LINE to serial;
Arduino ACKs and sends LCOS turnout CMD (HB node/UID in firmware). Turnout MQTT lines come only from
real layout ops events on serial (confirmation), not from a synthetic publish after PING.
When debug heartbeat is enabled (DEBUG_HEARTBEAT or --debug-heartbeat), we publish serial "ACK ..."
lines to HEARTBEAT_MQTT_TOPIC and subscribe to that topic: payload PING is relayed to serial. Arduino
replies with ACK PING; that payload does not re-trigger serial. With heartbeat off, we do not subscribe
to HEARTBEAT_MQTT_TOPIC and do not republish ACK lines there.

On MQTT connect we publish BRIDGE_STATUS_ONLINE to track/bridge/status (retained). On clean exit we
publish BRIDGE_STATUS_OFFLINE (best-effort before disconnect).

Turnout commands: subscribe to track/cmd/turnout/# (JMRI: topic track/cmd/turnout/<packed>, payload
THROWN or CLOSED). Optionally still accept flat topic track/cmd/turnout with payload "<packed> THROWN".
Serial to the Nano is always "track/cmd/turnout/<packed> THROWN|CLOSED\\n" (same shape as JMRI topic + payload).

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
# Wildcard subscription: receive track/cmd/turnout/408, payload THROWN|CLOSED (JMRI-style).
CMD_TURNOUT_SUBSCRIBE = "track/cmd/turnout/#"
_TURNOUT_HIER_TOPIC_RE = re.compile(r"^track/cmd/turnout/(\d+)$")
_TURNOUT_STATE_RE = re.compile(r"^(THROWN|CLOSED)\s*$", re.IGNORECASE)
# Legacy: single topic track/cmd/turnout, payload "408 THROWN".
_TURNOUT_FLAT_PAYLOAD_RE = re.compile(r"^\d+\s+(THROWN|CLOSED)\s*$", re.IGNORECASE)


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


def _publish_heartbeat_ack_if_present(
    client: mqtt.Client,
    stripped_line: str,
    *,
    heartbeat_on: bool,
    verbose: bool,
) -> bool:
    """Publish ACK lines from serial to heartbeat topic (only when heartbeat feature is enabled)."""
    if not heartbeat_on or not stripped_line.startswith("ACK "):
        return False
    client.publish(HEARTBEAT_MQTT_TOPIC, stripped_line, qos=0, retain=True)
    if verbose:
        print(f"TX -> {HEARTBEAT_MQTT_TOPIC} {stripped_line}")
    return True


def _handle_serial_text_line(
    client: mqtt.Client,
    line: str,
    *,
    debug: bool,
    verbose: bool,
    heartbeat_on: bool,
) -> None:
    """Handle one decoded serial text line and route to MQTT/logging."""
    stripped = line.strip("\r\n")
    if not stripped:
        return

    if stripped.startswith("DBG "):
        if debug:
            print(stripped)
        return

    parsed = parse_line(line)
    if parsed is not None:
        topic, payload = parsed
        client.publish(topic, payload, qos=0, retain=True)
        if verbose:
            print(f"TX -> {topic} {payload}")
        return

    _publish_heartbeat_ack_if_present(
        client, stripped, heartbeat_on=heartbeat_on, verbose=verbose
    )


def _turnout_state_payload_ok(payload: str) -> bool:
    return bool(_TURNOUT_STATE_RE.match(payload.strip()))


def _turnout_flat_payload_ok(payload: str) -> bool:
    return bool(_TURNOUT_FLAT_PAYLOAD_RE.match(payload.strip()))


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
        help="Enable heartbeat: MQTT subscribe to heartbeat topic, periodic PING to serial, "
        "and republish ACK lines (or set DEBUG_HEARTBEAT = True in script)",
    )
    args = ap.parse_args()

    heartbeat_on = bool(DEBUG_HEARTBEAT or args.debug_heartbeat)

    ping_cmd_queue: queue.Queue[object] = queue.Queue(maxsize=32)
    turnout_cmd_queue: queue.Queue[bytes] = queue.Queue(maxsize=32)

    client = _make_mqtt_client()
    client.user_data_set((ping_cmd_queue, turnout_cmd_queue))

    def _subscribe_line(_client: mqtt.Client, topic: str, qos: int = 1) -> None:
        res = _client.subscribe(topic, qos=qos)
        rc = res[0] if isinstance(res, tuple) else res
        ok = getattr(mqtt, "MQTT_ERR_SUCCESS", 0)
        if isinstance(rc, int):
            st = "ok" if rc == ok else f"failed (rc={rc})"
        else:
            st = "ok" if not getattr(rc, "is_failure", True) else "failed"
        print(f"Subscribe {topic!r}: {st}")

    def on_connect(_client, _userdata, _flags, reason_code, _properties=None):
        if not _mqtt_connect_ok(reason_code):
            return
        if heartbeat_on:
            _subscribe_line(_client, HEARTBEAT_MQTT_TOPIC, qos=1)
        _subscribe_line(_client, CMD_TURNOUT_SUBSCRIBE, qos=1)

    def on_message(_client, userdata, msg):
        ping_q, turnout_q = userdata
        if heartbeat_on and msg.topic == HEARTBEAT_MQTT_TOPIC:
            if bool(getattr(msg, "retain", False)):
                return
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
        hier = _TURNOUT_HIER_TOPIC_RE.match(msg.topic)
        is_flat = msg.topic == CMD_TURNOUT_TOPIC
        if hier is None and not is_flat:
            if args.verbose and msg.topic.startswith(f"{CMD_TURNOUT_TOPIC}/"):
                print(
                    f"MQTT turnout cmd ignored (topic must be {CMD_TURNOUT_TOPIC!r}/<digits>): "
                    f"{msg.topic!r}",
                    file=sys.stderr,
                )
            return
        if bool(getattr(msg, "retain", False)):
            return
        if args.verbose:
            qos = getattr(msg, "qos", "?")
            ret = getattr(msg, "retain", "?")
            print(
                f"MQTT RX turnout cmd topic={msg.topic!r} qos={qos} retain={ret} "
                f"raw_bytes={msg.payload!r}"
            )
        try:
            body = msg.payload.decode("utf-8", errors="replace").strip()
        except Exception as e:
            if args.verbose:
                print(f"MQTT turnout cmd: UTF-8 decode failed: {e}", file=sys.stderr)
            return
        if hier is not None:
            packed = hier.group(1)
            if not _turnout_state_payload_ok(body):
                if args.verbose:
                    print(
                        "MQTT turnout cmd rejected (hierarchical topic): expected payload "
                        f"THROWN or CLOSED only; decoded={body!r}"
                    )
                return
            state = body
        else:
            if not _turnout_flat_payload_ok(body):
                if args.verbose:
                    print(
                        "MQTT turnout cmd rejected (flat topic): expected '<packed> THROWN' or "
                        f"'<packed> CLOSED', e.g. '408 THROWN': decoded={body!r}"
                    )
                return
            _flat_parts = body.split(None, 1)
            packed = _flat_parts[0]
            state = _flat_parts[1]
        line = f"{CMD_TURNOUT_TOPIC}/{packed} {state}\n".encode("utf-8")
        if not isinstance(turnout_q, queue.Queue):
            if args.verbose:
                print("MQTT turnout cmd: internal error (bad queue)", file=sys.stderr)
            return
        try:
            turnout_q.put_nowait(line)
            if args.verbose:
                print(
                    "MQTT turnout cmd queued for serial: "
                    f"{line.decode('utf-8', errors='replace').rstrip()!r}"
                )
        except queue.Full:
            if args.verbose:
                print(
                    "MQTT turnout cmd: serial queue full (drop); increase drain rate or queue size",
                    file=sys.stderr,
                )

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
                _handle_serial_text_line(
                    client,
                    line,
                    debug=args.debug,
                    verbose=args.verbose,
                    heartbeat_on=heartbeat_on,
                )
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
