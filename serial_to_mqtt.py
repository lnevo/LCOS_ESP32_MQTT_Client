#!/usr/bin/env python3
"""
Serial -> MQTT bridge (read-only from the LCOS node's perspective: LCOS lines out, MQTT publish).

Host companion for an Arduino Nano running the LCOS JMRI/MQTT bridge sketch (repo folder name
retains ESP32 historically). The Nano sends one line per message:  <topic><space><payload>\\n  (LF only).
We publish each line to the MQTT broker with retain=True (same as mosquitto_pub -r).

Optional debug heartbeat (DEBUG_HEARTBEAT or --debug-heartbeat): periodically sends PING on serial;
the sketch ACKs. Inbound MQTT on HEARTBEAT_MQTT_TOPIC with payload PING is forwarded to serial;
serial ACK lines are published to that topic. Retained MQTT messages are skipped by default
(--restore / -r applies them: turnout cmds to serial, and retained PING on the heartbeat topic).
With heartbeat off,
none of that runs. Turnout state on MQTT still comes only from real layout traffic on the serial
lines, not from the heartbeat path.

On MQTT connect we publish BRIDGE_STATUS_ONLINE to track/bridge/status (retained). On clean exit we
publish BRIDGE_STATUS_OFFLINE (best-effort before disconnect).

Digicon SML guard (track/bridge/sml_mode): on bridge start and on track/state OFFLINE we publish
retained "query". A Digicon JMRI with SML Enabled replies "enabled". If no reply within
SML_MODE_QUERY_TIMEOUT_SEC, the serial thread SETs **all** Digicon heads Red (paced), waits
**one** SML_MODE_RED_HOLD_SEC, then Unheld (RELEASE) all, and retains "disabled".

Turnout commands: subscribe to track/cmd/turnout/# (JMRI: topic track/cmd/turnout/<packed>, payload
THROWN, CLOSED, TOGGLE, or ON/OFF for relay UIDs). Optionally still accept flat topic
track/cmd/turnout with payload "<packed> THROWN". Serial to the Nano is always
"track/cmd/turnout/<packed> …\\n". Packed UIDs 51–66 (Relay Obj) are sent as LCOS
EVENT_CONTROL_CMD on/off; 8–15 remain turnout ALIGN_*. TOGGLE is LCOS ALIGN_TOGGLE (turnouts only).

SignalHead → Nano: on by default (FORWARD_SIGNALHEAD_CMDS). Digicon/JMRI publish
track/signalhead/<packed> Red|Yellow|Green|… (no IH in the topic); firmware sends
EVENT_SIGNAL_CMD set-only (no auto-RELEASE; signalmast echo off unless compiled on).
Opt out with FORWARD_SIGNALHEAD_CMDS = False.

Usage:
  Windows:  run_serial_mqtt.cmd [-h|/?|...] [verbose] [debug] [heartbeat] [restore] [-- python-args...]
            python serial_to_mqtt.py --com COM3 --broker ...
  Linux:    ./run_serial_mqtt.sh [-h|-?|--help] [-v] [-d] [-hb] [-r] [-- extra python args]
            SERIAL_PORT=/dev/ttyACM0 BROKER=... ./run_serial_mqtt.sh

Requires: pip install -r requirements.txt. Setup: docs/serial_mqtt_windows.md, docs/serial_mqtt_linux.md.
"""

from __future__ import annotations

import argparse
import queue
import re
import signal
import sys
import threading
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
# Wildcard subscription: receive track/cmd/turnout/408, payload THROWN|CLOSED|TOGGLE.
CMD_TURNOUT_SUBSCRIBE = "track/cmd/turnout/#"
_TURNOUT_HIER_TOPIC_RE = re.compile(r"^track/cmd/turnout/(\d+)$")
_TURNOUT_STATE_RE = re.compile(r"^(THROWN|CLOSED|TOGGLE|ON|OFF)\s*$", re.IGNORECASE)
# Legacy: single topic track/cmd/turnout, payload "408 THROWN".
_TURNOUT_FLAT_PAYLOAD_RE = re.compile(r"^\d+\s+(THROWN|CLOSED|TOGGLE|ON|OFF)\s*$", re.IGNORECASE)

# Digicon / JMRI Virtual heads → LCOS SIGNAL_CMD (set-only on firmware). On by default.
# Disable with FORWARD_SIGNALHEAD_CMDS = False (or omit --signalhead when already False).
FORWARD_SIGNALHEAD_CMDS = True
SIGNALHEAD_TOPIC_PREFIX = "track/signalhead/"
SIGNALHEAD_SUBSCRIBE = "track/signalhead/#"
# Packed digits; optional legacy IH prefix still accepted.
_SIGNALHEAD_TOPIC_RE = re.compile(r"^track/signalhead/(?:IH)?(\d+)$", re.IGNORECASE)
_SIGNALHEAD_APPEARANCE_RE = re.compile(
    r"^(Red|Yellow|Green|Dark|Off|FlashRed|FlashYellow|FlashGreen|Lunar|FlashLunar|"
    r"Stop|Approach|Clear|Release|Unheld|Get|Query)\s*$",
    re.IGNORECASE,
)

# Digicon packed heads (cats/data/signal_wiring.csv). Keep in sync with HEAD_NAMES.
DIGICON_PACKED_HEADS = (
    "432",
    "433",
    "434",
    "436",
    "437",
    "438",
    "439",
    "1332",
    "1333",
    "1334",
    "1335",
    "1336",
    "1337",
    "1338",
    "1232",
    "1233",
    "1234",
    "1235",
    "1236",
    "1237",
    "1238",
    "1239",
    "1240",
    "1241",
    "132",
    "133",
    "134",
    "135",
    "136",
    "137",
    "138",
    "139",
    "140",
    "141",
    "142",
    "143",
)
SML_MODE_TOPIC = "track/bridge/sml_mode"
JMRI_STATE_TOPIC = "track/state"
SML_MODE_QUERY_TIMEOUT_SEC = 5.0
SML_MODE_RED_HOLD_SEC = 3.0
# Pace Digicon bulk Red/Unheld on USB serial (seconds between lines).
SML_MODE_SERIAL_GAP_SEC = 0.05
# Sentinel queued for main loop: Red-all → hold → Unheld-all (one 3s wait).
SML_GUARD_RELEASE = object()


def packed_mqtt_lcos_node_validation_error(packed: str) -> str | None:
    """
    JMRI-style packed = display_node*100 + uid. Before sending a line to serial, ensure the
    node part (packed // 100) is a valid "display" node: the decimal string must use only
    octal digits 0–7, because firmware maps it to the RF24 address with strtoul(digits, 8).

    Return None if valid; otherwise a short error message. Call this from any MQTT handler
    that embeds a packed address and forwards to serial, so bad addresses never leave Python.
    """
    if not packed:
        return "empty packed address"
    if not packed.isascii() or not packed.isdigit():
        return "packed address must be non-empty decimal digits"
    n = int(packed, 10)
    node_part = n // 100
    s = str(node_part)
    try:
        int(s, 8)
    except ValueError:
        return f"node part {node_part} is not valid (only digits 0–7 allowed in the node number)"
    return None


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


class DigiconSmlGuard:
    """Challenge Digicon JMRI via sml_mode=query; RELEASE all heads if no enabled ACK."""

    def __init__(
        self,
        client: mqtt.Client,
        serial_cmd_queue: queue.Queue,
        *,
        verbose: bool,
        packed_heads: tuple[str, ...] = DIGICON_PACKED_HEADS,
        query_timeout_sec: float = SML_MODE_QUERY_TIMEOUT_SEC,
        red_hold_sec: float = SML_MODE_RED_HOLD_SEC,
    ) -> None:
        self._client = client
        self._cmd_q = serial_cmd_queue
        self._verbose = verbose
        self._packed = packed_heads
        self._query_timeout_sec = query_timeout_sec
        self._red_hold_sec = red_hold_sec
        self._lock = threading.Lock()
        self._waiting = False
        self._got_enabled = False
        self._timer: threading.Timer | None = None
        self._generation = 0

    def start_challenge(self, reason: str) -> None:
        with self._lock:
            self._generation += 1
            gen = self._generation
            self._waiting = True
            self._got_enabled = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            try:
                info = self._client.publish(SML_MODE_TOPIC, "query", qos=1, retain=True)
                if hasattr(info, "wait_for_publish"):
                    info.wait_for_publish(timeout=3.0)
            except Exception as e:
                print(f"sml_mode query publish failed: {e}", file=sys.stderr)
                self._waiting = False
                return
            if self._verbose:
                print(f"TX -> {SML_MODE_TOPIC} query ({reason})")
            self._timer = threading.Timer(
                self._query_timeout_sec, self._on_timeout, args=(gen,)
            )
            self._timer.daemon = True
            self._timer.start()

    def on_sml_mode_message(self, payload: str) -> None:
        mode = payload.strip().lower()
        with self._lock:
            if not self._waiting:
                return
            if mode == "enabled":
                self._got_enabled = True
                self._waiting = False
                if self._timer is not None:
                    self._timer.cancel()
                    self._timer = None
                if self._verbose:
                    print(f"sml_mode: ACK enabled — cancel RELEASE")
                return
            # query/disabled while waiting: ignore (our query echo or stale)

    def _on_timeout(self, generation: int) -> None:
        with self._lock:
            if generation != self._generation or not self._waiting:
                return
            if self._got_enabled:
                self._waiting = False
                return
            self._waiting = False
            self._timer = None
        print(
            f"sml_mode: no enabled ACK within {self._query_timeout_sec}s — "
            f"queue Red-all / {self._red_hold_sec}s / Unheld-all "
            f"({len(self._packed)} Digicon heads)"
        )
        try:
            self._cmd_q.put_nowait(SML_GUARD_RELEASE)
        except queue.Full:
            print("sml_mode: serial queue full; cannot schedule RELEASE", file=sys.stderr)

    def stop(self) -> None:
        with self._lock:
            self._waiting = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


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

    # ACK … from Nano (command echo). Visible with --verbose; not an MQTT publish.
    if stripped.startswith("ACK "):
        if verbose:
            print(stripped)
        _publish_heartbeat_ack_if_present(
            client, stripped, heartbeat_on=heartbeat_on, verbose=verbose
        )
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
        epilog="Launchers: run_serial_mqtt.cmd (help -h /?; options: verbose debug heartbeat restore), "
        "run_serial_mqtt.sh (-h -v -d -hb -r).",
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
        help="Debug heartbeat: PING serial on an interval; MQTT PING->serial; serial ACK->MQTT "
        "(also DEBUG_HEARTBEAT in script)",
    )
    ap.add_argument(
        "-r",
        "--restore",
        action="store_true",
        help="Apply retained MQTT messages on subscribe (turnout cmds to serial; "
        "signalhead too if --signalhead; retained heartbeat PING if enabled)",
    )
    ap.add_argument(
        "--signalhead",
        action="store_true",
        help="Forward track/signalhead/<packed> MQTT to serial (EVENT_SIGNAL_CMD). "
        "On by default via FORWARD_SIGNALHEAD_CMDS; this flag forces on.",
    )
    args = ap.parse_args()

    heartbeat_on = bool(DEBUG_HEARTBEAT or args.debug_heartbeat)
    signalhead_on = bool(FORWARD_SIGNALHEAD_CMDS or args.signalhead)

    ping_cmd_queue: queue.Queue[object] = queue.Queue(maxsize=32)
    # Shared serial outbound queue for turnout + signalhead command lines.
    serial_cmd_queue: queue.Queue[bytes] = queue.Queue(maxsize=128)

    client = _make_mqtt_client()
    sml_guard = DigiconSmlGuard(client, serial_cmd_queue, verbose=args.verbose)
    client.user_data_set((ping_cmd_queue, serial_cmd_queue, sml_guard))

    def _subscribe_line(_client: mqtt.Client, topic: str, qos: int = 1) -> None:
        res = _client.subscribe(topic, qos=qos)
        rc = res[0] if isinstance(res, tuple) else res
        ok = getattr(mqtt, "MQTT_ERR_SUCCESS", 0)
        if isinstance(rc, int):
            st = "ok" if rc == ok else f"failed (rc={rc})"
        else:
            st = "ok" if not getattr(rc, "is_failure", True) else "failed"
        print(f"Subscribe {topic!r}: {st}")

    def _queue_serial_cmd(cmd_q: queue.Queue, line: bytes, *, label: str) -> None:
        try:
            cmd_q.put_nowait(line)
            if args.verbose:
                print(
                    f"MQTT {label} queued for serial: "
                    f"{line.decode('utf-8', errors='replace').rstrip()!r}"
                )
        except queue.Full:
            if args.verbose:
                print(
                    f"MQTT {label}: serial queue full (drop); increase drain rate or queue size",
                    file=sys.stderr,
                )

    def on_connect(_client, userdata, _flags, reason_code, _properties=None):
        if not _mqtt_connect_ok(reason_code):
            return
        if heartbeat_on:
            _subscribe_line(_client, HEARTBEAT_MQTT_TOPIC, qos=1)
        _subscribe_line(_client, CMD_TURNOUT_SUBSCRIBE, qos=1)
        _subscribe_line(_client, SML_MODE_TOPIC, qos=1)
        _subscribe_line(_client, JMRI_STATE_TOPIC, qos=1)
        if signalhead_on:
            _subscribe_line(_client, SIGNALHEAD_SUBSCRIBE, qos=1)
        else:
            print(
                f"Subscribe {SIGNALHEAD_SUBSCRIBE!r}: skipped "
                "(signalhead->bridge off; use --signalhead to enable)"
            )
        guard = userdata[2] if isinstance(userdata, tuple) and len(userdata) > 2 else None
        if isinstance(guard, DigiconSmlGuard):
            # Defer slightly so subscriptions are active before query.
            threading.Timer(0.5, guard.start_challenge, args=("bridge-start",)).start()

    def on_message(_client, userdata, msg):
        ping_q, cmd_q, guard = userdata
        if heartbeat_on and msg.topic == HEARTBEAT_MQTT_TOPIC:
            if not args.restore and bool(getattr(msg, "retain", False)):
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

        if msg.topic == SML_MODE_TOPIC:
            try:
                body = msg.payload.decode("utf-8", errors="replace").strip()
            except Exception:
                return
            if isinstance(guard, DigiconSmlGuard):
                guard.on_sml_mode_message(body)
            return

        if msg.topic == JMRI_STATE_TOPIC:
            if bool(getattr(msg, "retain", False)) and not args.restore:
                # Still honor retained OFFLINE after reconnect? Prefer live only.
                # Live OFFLINE is the kill/quit signal; skip retain on subscribe.
                return
            try:
                body = msg.payload.decode("utf-8", errors="replace").strip().upper()
            except Exception:
                return
            if body == "OFFLINE" and isinstance(guard, DigiconSmlGuard):
                if args.verbose:
                    print("MQTT track/state OFFLINE -> sml_mode query")
                guard.start_challenge("jmri-offline")
            return

        # --- signalhead/<packed> (optional legacy IH prefix) ---
        if not signalhead_on and msg.topic.startswith(SIGNALHEAD_TOPIC_PREFIX):
            return
        signal_m = _SIGNALHEAD_TOPIC_RE.match(msg.topic)
        if signal_m is not None:
            if not args.restore and bool(getattr(msg, "retain", False)):
                return
            if args.verbose:
                qos = getattr(msg, "qos", "?")
                ret = getattr(msg, "retain", "?")
                print(
                    f"MQTT RX signalhead topic={msg.topic!r} qos={qos} retain={ret} "
                    f"raw_bytes={msg.payload!r}"
                )
            try:
                body = msg.payload.decode("utf-8", errors="replace").strip()
            except Exception as e:
                if args.verbose:
                    print(f"MQTT signalhead: UTF-8 decode failed: {e}", file=sys.stderr)
                return
            if not _SIGNALHEAD_APPEARANCE_RE.match(body):
                if args.verbose:
                    print(
                        "MQTT signalhead rejected: expected Red/Yellow/Green/Dark "
                        f"(or Flash*/Lunar/Stop/Approach/Clear/Release/Get); decoded={body!r}"
                    )
                return
            packed = signal_m.group(1)
            addr_err = packed_mqtt_lcos_node_validation_error(packed)
            if addr_err is not None:
                print(
                    f"MQTT: skip serial/LCOS — topic {msg.topic!r} packed {packed!r}: {addr_err}",
                    file=sys.stderr,
                )
                return
            line = f"{SIGNALHEAD_TOPIC_PREFIX}{packed} {body}\n".encode("utf-8")
            _queue_serial_cmd(cmd_q, line, label="signalhead")
            return
        if msg.topic.startswith(SIGNALHEAD_TOPIC_PREFIX):
            if args.verbose:
                print(
                    f"MQTT signalhead ignored (need packed digits): {msg.topic!r}",
                    file=sys.stderr,
                )
            return

        # --- turnout ---
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
        if not args.restore and bool(getattr(msg, "retain", False)):
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
                        f"THROWN, CLOSED, TOGGLE, ON, or OFF; decoded={body!r}"
                    )
                return
            state = body
        else:
            if not _turnout_flat_payload_ok(body):
                if args.verbose:
                    print(
                        "MQTT turnout cmd rejected (flat topic): expected '<packed> THROWN', "
                        f"'<packed> CLOSED', or '<packed> TOGGLE', e.g. '408 THROWN': decoded={body!r}"
                    )
                return
            _flat_parts = body.split(None, 1)
            packed = _flat_parts[0]
            state = _flat_parts[1]
        addr_err = packed_mqtt_lcos_node_validation_error(packed)
        if addr_err is not None:
            print(
                f"MQTT: skip serial/LCOS — topic {msg.topic!r} packed {packed!r}: {addr_err}",
                file=sys.stderr,
            )
            return
        line = f"{CMD_TURNOUT_TOPIC}/{packed} {state}\n".encode("utf-8")
        _queue_serial_cmd(cmd_q, line, label="turnout")

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
    print(
        f"Opening {args.com} @ {args.baud} baud - Serial -> MQTT"
        f"{'; signalhead->serial ON' if signalhead_on else '; signalhead->serial OFF'}"
        f"; Digicon sml_mode guard ON"
        ". Ctrl+C to stop."
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
    # Wait for Nano ACK before sending the next cmd (Digicon bursts were garbling USB RX).
    _ACK_WAIT_SEC = 0.35

    def _read_one_serial_line() -> str | None:
        raw = ser.readline()
        if not raw:
            return None
        try:
            return raw.decode("utf-8", errors="replace")
        except Exception:
            return None

    def _handle_and_is_ack(line: str) -> bool:
        _handle_serial_text_line(
            client,
            line,
            debug=args.debug,
            verbose=args.verbose,
            heartbeat_on=heartbeat_on,
        )
        return line.strip("\r\n").startswith("ACK ")

    def _write_serial_cmd(line_out: bytes) -> None:
        ser.write(line_out)
        ser.flush()
        if args.verbose:
            print(f"MQTT -> serial {line_out!r}")
        deadline = time.monotonic() + _ACK_WAIT_SEC
        saw_ack = False
        while time.monotonic() < deadline:
            line = _read_one_serial_line()
            if line is None:
                continue
            if _handle_and_is_ack(line):
                saw_ack = True
                # Drain a few immediate follow-up lines (DBG / early status) without blocking long.
                drain_until = time.monotonic() + 0.05
                while time.monotonic() < drain_until:
                    more = _read_one_serial_line()
                    if more is None:
                        break
                    _handle_and_is_ack(more)
                break
        if not saw_ack and args.verbose:
            print("MQTT -> serial: no ACK within timeout", file=sys.stderr)

    def _write_serial_burst_line(line_out: bytes, *, gap_sec: float) -> None:
        """Write one line for Digicon bulk Red/Unheld — short pace, light ACK wait."""
        ser.write(line_out)
        ser.flush()
        if args.verbose:
            print(f"MQTT -> serial (burst) {line_out!r}")
        # Brief window for ACK / status; do not burn 0.35s per head.
        deadline = time.monotonic() + min(0.12, max(0.02, gap_sec * 2))
        while time.monotonic() < deadline:
            line = _read_one_serial_line()
            if line is None:
                continue
            _handle_and_is_ack(line)
        time.sleep(gap_sec)

    def _run_sml_guard_release() -> None:
        """All Red → one 3s hold → all Unheld → retain sml_mode disabled."""
        gap = SML_MODE_SERIAL_GAP_SEC
        hold = SML_MODE_RED_HOLD_SEC
        print(
            f"sml_mode: serial Red-all ({len(DIGICON_PACKED_HEADS)}), "
            f"hold {hold}s, then Unheld-all (gap={gap}s)"
        )
        for packed in DIGICON_PACKED_HEADS:
            err = packed_mqtt_lcos_node_validation_error(packed)
            if err is not None:
                print(f"sml_mode burst skip {packed}: {err}", file=sys.stderr)
                continue
            _write_serial_burst_line(
                f"{SIGNALHEAD_TOPIC_PREFIX}{packed} Red\n".encode("utf-8"),
                gap_sec=gap,
            )
        print(f"sml_mode: holding Red {hold}s before Unheld")
        # Keep draining serial during the hold so status lines do not backlog.
        hold_deadline = time.monotonic() + hold
        while time.monotonic() < hold_deadline:
            line = _read_one_serial_line()
            if line is not None:
                _handle_and_is_ack(line)
            else:
                time.sleep(0.02)
        for packed in DIGICON_PACKED_HEADS:
            err = packed_mqtt_lcos_node_validation_error(packed)
            if err is not None:
                continue
            _write_serial_burst_line(
                f"{SIGNALHEAD_TOPIC_PREFIX}{packed} Unheld\n".encode("utf-8"),
                gap_sec=gap,
            )
        try:
            info = client.publish(SML_MODE_TOPIC, "disabled", qos=1, retain=True)
            if hasattr(info, "wait_for_publish"):
                info.wait_for_publish(timeout=3.0)
            if args.verbose:
                print(f"TX -> {SML_MODE_TOPIC} disabled")
        except Exception as e:
            print(f"sml_mode disabled publish failed: {e}", file=sys.stderr)

    try:
        while not stop:
            try:
                while True:
                    try:
                        line_out = serial_cmd_queue.get_nowait()
                    except queue.Empty:
                        break
                    if line_out is SML_GUARD_RELEASE:
                        _run_sml_guard_release()
                        continue
                    _write_serial_cmd(line_out)

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

                line = _read_one_serial_line()
                if line is None:
                    continue
                _handle_and_is_ack(line)
            except serial.SerialException as e:
                print(f"Serial error: {e}", file=sys.stderr)
                time.sleep(0.5)
    finally:
        sml_guard.stop()
        if bridge_online_published:
            _publish_bridge_status(client, BRIDGE_STATUS_OFFLINE, verbose=args.verbose)
        ser.close()
        client.loop_stop()
        client.disconnect()
        print("Stopped.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
