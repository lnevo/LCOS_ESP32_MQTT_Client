#!/usr/bin/env python3
"""
Serial -> MQTT bridge (read-only from the LCOS node's perspective: LCOS lines out, MQTT publish).

Host companion for an Arduino Nano running the LCOS JMRI/MQTT bridge sketch (repo folder name
retains ESP32 historically). The Nano sends one line per message:  <topic><space><payload>\\n  (LF only).
We publish each line to the MQTT broker with retain=True (same as mosquitto_pub -r).

Optional debug heartbeat (DEBUG_HEARTBEAT or --debug-heartbeat): periodically sends USB-only
PING on serial (same as sync-watch; no turnout throw). Inbound MQTT on HEARTBEAT_MQTT_TOPIC
with payload PING is forwarded to serial; serial ACK lines are published to that topic.
Retained MQTT messages are skipped by default (--restore / -r applies them: turnout cmds to
serial, and retained PING on the heartbeat topic).
With heartbeat off,
none of that runs. Turnout state on MQTT still comes only from real layout traffic on the serial
lines, not from the heartbeat path.

On MQTT connect we publish BRIDGE_STATUS_ONLINE to track/bridge/status (retained). On clean exit we
publish BRIDGE_STATUS_OFFLINE (best-effort before disconnect).

Host -> bridge ops (not retained): payload RESUBSCRIBE | RESUBSCRIBE FORCE | REOPEN | PING | HBLOOP on
track/bridge/cmd. Plain MQTT RESUBSCRIBE is refused while HBLOOP is established (use FORCE);
when not established it fires with no cooldown. HBLOOP: skip probes while sensor/signal*
feedback is fresh; on loss keep quiet echo probes with RESUBSCRIBE disarmed (RF path may
return via DCC node without re-enroll); after 60s only RESUBSCRIBE if a probe echo still
fails. Lifecycle logs: established / lost / miss / recovered. Auto sync-watch RESUBSCRIBE
(USB/boot thin-accept) still uses cooldown to avoid storms.
(see docs/archive/manual_resubscribe_hbloop_era.md).

Digicon SML guard (track/bridge/sml_mode): on bridge start (and JMRI track/state
OFFLINE), only if retained/last sml_mode is **enabled**, publish "query". A live Digicon
with SML Enabled replies "enabled". If no reply within SML_MODE_QUERY_TIMEOUT_SEC, publish
retained **"disabling"** immediately, wait SML_MODE_DISABLING_WAIT_SEC (live Digicon may
still ACK "enabled" and abort), then one Red/Unheld burst for the live signalmast roster (UID 32–47) on serial **and** MQTT (`track/signalhead/<packed>` Red, then Unheld)
→ retain "disabled". **enabling / aborting / aborted** are not treated as
disabled: watch until **enabled** (SML_MODE_BOOT_ABORT_TIMEOUT_SEC); if that never
arrives, run the same query/disabling/RELEASE path. Duplicate track/state OFFLINE is ignored
while a challenge/RELEASE is already in flight. If sml_mode is already
disabled/missing, skip — no radio storm.

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

# --- Debug heartbeat (USB-only serial ping; publish Arduino "ACK ..." to MQTT) ---
# Set True here, or pass --debug-heartbeat on the command line (either enables the feature).
# Never throws turnouts — health is text ACK only. Turnout ACK miss is separate (normal ops).
DEBUG_HEARTBEAT = False
HEARTBEAT_INTERVAL_SEC = 10.0
# USB-only health (firmware ACKs; no radio / no turnout). Sync watchdog + debug HB use this.
USB_PING_SERIAL_LINE = b"PING\n"
HEARTBEAT_SERIAL_LINE = USB_PING_SERIAL_LINE
# Re-emit LCOS event-125 subscriptions on the Nano (after master loss / soft desync).
RESUBSCRIBE_SERIAL_LINE = b"RESUBSCRIBE\n"
# MQTT topic for the raw serial reply (e.g. "ACK PING").
HEARTBEAT_MQTT_TOPIC = "track/bridge/heartbeat"

# Sync recovery (USB ACK miss / serial death → reopen COM and/or RESUBSCRIBE).
SYNC_WATCH_DEFAULT = True
SYNC_ACK_FAIL_LIMIT = 3
SYNC_USB_PING_INTERVAL_SEC = 12.0
SYNC_RESUBSCRIBE_COOLDOWN_SEC = 45.0
SYNC_REOPEN_COOLDOWN_SEC = 20.0
# Must match kSubscribeDisplayNodes[] in lcos_mqtt_bridge.cpp (plant nodes only — no MASTER 0).
SYNC_SUBSCRIBE_DISPLAY_NODES = (1, 2, 3, 4, 12, 13)
SYNC_EXPECT_SUBSCRIPTION_ACCEPTS = len(SYNC_SUBSCRIBE_DISPLAY_NODES)
# After Nano boot/setup(), wait before deciding subscriptions are thin (avoid double RESUBSCRIBE).
SYNC_BOOT_ACCEPT_GRACE_SEC = 8.0
# Real HBLOOP: probe every 5s only when sensor/signal* feedback is quiet.
# Expect HBLOOP ECHO (or suppressed track/sensor/<display*100+7>). Self oct/topic
# learned from firmware "HBLOOP_SELF <oct>" (and boot "@<0…>"); fallbacks below.
# Layout RF often routes via a DCC node — layout power-off drops the path to MASTER
# without clearing MASTER's subscription RAM. On loss: keep probing; RESUBSCRIBE only
# after hbloop_retry_sec if echo still fails (path may heal on its own).
SYNC_HBLOOP_DEFAULT = True
SYNC_HBLOOP_INTERVAL_SEC = 5.0
SYNC_HBLOOP_FAIL_LIMIT = 1
SYNC_HBLOOP_RETRY_SEC = 60.0
HBLOOP_SERIAL_LINE = b"HBLOOP\n"
HBLOOP_BLOCK_INDEX = 7
# Fallbacks until firmware announces HBLOOP_SELF / boot @<0…> (thisNode 015 → "15").
HBLOOP_SELF_OCT_DEFAULT = "15"
HBLOOP_SENSOR_TOPIC_PREFIX_DEFAULT = (
    f"track/sensor/{int(HBLOOP_SELF_OCT_DEFAULT) * 100 + HBLOOP_BLOCK_INDEX}"
)
_HBLOOP_SELF_RE = re.compile(r"^HBLOOP_SELF\s+(\d+)\s*$", re.IGNORECASE)
_AT_NODE_RE = re.compile(r"^@<0*(\d+)>\s*$")
# Layout feedback that proves distributor health (skip HBLOOP probe while fresh).
_HBLOOP_TRAFFIC_TOPIC_PREFIXES = (
    "track/sensor/",
    "track/signalmast/",
    "track/signalhead/",
    "track/turnout/",
)

# Host bridge presence: same topic for startup and shutdown (retained; QoS 1).
BRIDGE_STATUS_TOPIC = "track/bridge/status"
BRIDGE_STATUS_ONLINE = "online"
BRIDGE_STATUS_OFFLINE = "offline"
# Host -> bridge ops (not retained): RESUBSCRIBE | PING | HBLOOP
BRIDGE_CMD_TOPIC = "track/bridge/cmd"

# JMRI -> bridge -> serial -> LCOS (distinct from state topic track/turnout/<packed>).
CMD_TURNOUT_TOPIC = "track/cmd/turnout"
# Wildcard subscription: receive track/cmd/turnout/408, payload THROWN|CLOSED|TOGGLE.
CMD_TURNOUT_SUBSCRIBE = "track/cmd/turnout/#"
_TURNOUT_HIER_TOPIC_RE = re.compile(r"^track/cmd/turnout/(\d+)$")
_TURNOUT_STATE_RE = re.compile(
    r"^(THROWN|CLOSED|TOGGLE|ON|OFF|GET|QUERY)\s*$", re.IGNORECASE
)
# Legacy: single topic track/cmd/turnout, payload "408 THROWN".
_TURNOUT_FLAT_PAYLOAD_RE = re.compile(
    r"^\d+\s+(THROWN|CLOSED|TOGGLE|ON|OFF|GET|QUERY)\s*$", re.IGNORECASE
)

# Track power CMD (Public API EVENT_TRACK_PWR_CMD): district 0–127 on MASTER.
CMD_POWER_TOPIC = "track/cmd/power"
CMD_POWER_SUBSCRIBE = "track/cmd/power/#"
_POWER_HIER_TOPIC_RE = re.compile(r"^track/cmd/power/(\d+)$")
_POWER_STATE_RE = re.compile(
    r"^(GET|QUERY|ON|OFF|NORMAL|REVERSE|REVERSED|RELEASE)\s*$", re.IGNORECASE
)

# Digicon / JMRI Virtual heads → LCOS SIGNAL_CMD (set-only on firmware). On by default.
# Disable with FORWARD_SIGNALHEAD_CMDS = False (or omit --signalhead when already False).
FORWARD_SIGNALHEAD_CMDS = True
SIGNALHEAD_TOPIC_PREFIX = "track/signalhead/"
SIGNALHEAD_SUBSCRIBE = "track/signalhead/#"
SIGNALMAST_TOPIC_PREFIX = "track/signalmast/"
SIGNALMAST_SUBSCRIBE = "track/signalmast/#"
# Packed digits; optional legacy IH prefix still accepted.
_SIGNALHEAD_TOPIC_RE = re.compile(r"^track/signalhead/(?:IH)?(\d+)$", re.IGNORECASE)
_SIGNALMAST_TOPIC_RE = re.compile(r"^track/signalmast/(?:IH)?(\d+)$", re.IGNORECASE)
_SIGNALHEAD_APPEARANCE_RE = re.compile(
    r"^(Red|Yellow|Green|Dark|Off|FlashRed|FlashYellow|FlashGreen|Lunar|FlashLunar|"
    r"Stop|Approach|Clear|Release|Unheld|Get|Query)\s*$",
    re.IGNORECASE,
)

# LCOS signal UIDs: UID_OFFSET_SIGNALS .. UID_OFFSET_CROSSINGS-1 (lcos.h).
LCOS_SIGNAL_UID_MIN = 32
LCOS_SIGNAL_UID_MAX = 47
SML_MODE_TOPIC = "track/bridge/sml_mode"
JMRI_STATE_TOPIC = "track/state"
SML_MODE_QUERY_TIMEOUT_SEC = 1.0
# After query timeout: announce disabling, wait for a late Digicon enabled ACK, then RELEASE.
SML_MODE_DISABLING_WAIT_SEC = 1.0
SML_MODE_RED_HOLD_SEC = 3.0
# enabling (1s) → aborting → Hold 3s → enabled. Then challenge if that never arrives.
SML_MODE_BOOT_ABORT_TIMEOUT_SEC = 5.0
_SML_BOOT_ABORT_MODES = ("enabling", "aborting", "aborted")
# Pace Digicon bulk Red/Unheld on USB serial (seconds between lines).
SML_MODE_SERIAL_GAP_SEC = 0.05
# Sentinel queued for main loop: disabling announce → optional abort → Red/hold/Unheld.
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


def packed_is_lcos_signal(packed: str) -> bool:
    """True if packed is node*100 + signal UID 32–47 and the node is octal-legal."""
    if packed_mqtt_lcos_node_validation_error(packed) is not None:
        return False
    uid = int(packed, 10) % 100
    return LCOS_SIGNAL_UID_MIN <= uid <= LCOS_SIGNAL_UID_MAX


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
    """Challenge Digicon JMRI via sml_mode=query; RELEASE only if mode was enabled."""

    def __init__(
        self,
        client: mqtt.Client,
        serial_cmd_queue: queue.Queue,
        *,
        verbose: bool,
        packed_heads: tuple[str, ...] = (),
        query_timeout_sec: float = SML_MODE_QUERY_TIMEOUT_SEC,
        disabling_wait_sec: float = SML_MODE_DISABLING_WAIT_SEC,
        red_hold_sec: float = SML_MODE_RED_HOLD_SEC,
        boot_abort_timeout_sec: float = SML_MODE_BOOT_ABORT_TIMEOUT_SEC,
    ) -> None:
        self._client = client
        self._cmd_q = serial_cmd_queue
        self._verbose = verbose
        self._packed: set[str] = set(packed_heads)
        self._query_timeout_sec = query_timeout_sec
        self._disabling_wait_sec = disabling_wait_sec
        self._red_hold_sec = red_hold_sec
        self._boot_abort_timeout_sec = boot_abort_timeout_sec
        self._lock = threading.Lock()
        self._waiting = False
        self._got_enabled = False
        self._releasing = False
        self._release_queued = False
        self._abort_release = False
        self._timer: threading.Timer | None = None
        self._boot_abort_timer: threading.Timer | None = None
        self._generation = 0
        # Last sml_mode from retain/live. query/disabling are not stored here.
        self._last_mode: str | None = None
        # Own Red/Unheld MQTT publishes so the subscribe path does not re-queue serial.
        self._own_signalhead: list[tuple[str, str]] = []

    @property
    def packed_heads(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._packed, key=lambda p: (len(p), p)))

    def has_packed(self, packed: str) -> bool:
        packed = str(packed).strip()
        with self._lock:
            return packed in self._packed

    def note_signalmast(self, packed: str) -> bool:
        """Enroll packed from track/signalmast (MQTT retain or serial). Returns True if new."""
        packed = str(packed).strip()
        if not packed_is_lcos_signal(packed):
            return False
        with self._lock:
            if packed in self._packed:
                return False
            self._packed.add(packed)
        print(f"sml_mode: enrolled packed {packed} from signalmast")
        return True

    def is_in_flight(self) -> bool:
        """True while query-wait, RELEASE queued, or Red/Unheld burst is running."""
        with self._lock:
            return self._waiting or self._releasing or self._release_queued

    def publish_head_to_mqtt(self, packed: str, payload: str) -> None:
        """Mirror a guard Red/Unheld onto the broker (serial write is unchanged)."""
        topic = f"{SIGNALHEAD_TOPIC_PREFIX}{packed}"
        body = str(payload).strip()
        with self._lock:
            self._own_signalhead.append((topic, body.lower()))
        try:
            info = self._client.publish(topic, body, qos=1, retain=False)
            if hasattr(info, "wait_for_publish"):
                info.wait_for_publish(timeout=3.0)
        except Exception as e:
            print(f"sml_mode MQTT {topic} {body} publish failed: {e}", file=sys.stderr)
            return
        print(f"TX -> {topic} {body}")

    def consume_own_signalhead(self, topic: str, payload: str) -> bool:
        """True if this MQTT delivery is our own Red/Unheld mirror (do not serial it)."""
        key = (str(topic), str(payload).strip().lower())
        with self._lock:
            try:
                self._own_signalhead.remove(key)
            except ValueError:
                return False
        return True

    def maybe_start_challenge(self, reason: str) -> None:
        """Query+RELEASE only when Digicon was left in enabled (stuck SET risk).

        Boot-abort tokens (enabling / aborting / aborted) start a watch
        until enabled; they are not skipped as disabled.
        """
        with self._lock:
            mode = self._last_mode
            in_flight = self._waiting or self._releasing or self._release_queued
            watching = self._boot_abort_timer is not None
        if in_flight:
            print(
                f"sml_mode: skip challenge ({reason}); "
                "already waiting/releasing (one Unheld burst)"
            )
            return
        if mode in _SML_BOOT_ABORT_MODES:
            if watching:
                print(
                    f"sml_mode: skip challenge ({reason}); "
                    f"watching boot-abort (last_mode={mode!r})"
                )
                return
            self._ensure_boot_abort_watch()
            return
        if mode != "enabled":
            print(
                f"sml_mode: skip challenge ({reason}); "
                f"last_mode={mode!r} (only challenge when enabled)"
            )
            return
        self.start_challenge(reason)

    def start_challenge(self, reason: str) -> None:
        with self._lock:
            self._cancel_boot_abort_timer_locked()
            self._generation += 1
            gen = self._generation
            self._waiting = True
            self._got_enabled = False
            self._releasing = False
            self._abort_release = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        try:
            info = self._client.publish(SML_MODE_TOPIC, "query", qos=1, retain=True)
            if hasattr(info, "wait_for_publish"):
                info.wait_for_publish(timeout=3.0)
        except Exception as e:
            print(f"sml_mode query publish failed: {e}", file=sys.stderr)
            with self._lock:
                if gen == self._generation:
                    self._waiting = False
            return
        if self._verbose:
            print(f"TX -> {SML_MODE_TOPIC} query ({reason})")
        with self._lock:
            if gen != self._generation or not self._waiting:
                return
            self._timer = threading.Timer(
                self._query_timeout_sec, self._on_timeout, args=(gen,)
            )
            self._timer.daemon = True
            self._timer.start()

    def on_sml_mode_message(self, payload: str) -> None:
        mode = payload.strip().lower()
        start_watch = False
        restart_watch = False
        with self._lock:
            if mode in ("enabled", "disabled"):
                self._last_mode = mode
                self._cancel_boot_abort_timer_locked()
            elif mode == "enabling":
                self._last_mode = mode
                start_watch = True
                restart_watch = True
            elif mode in ("aborting", "aborted"):
                # Ignore late abort tokens after Digicon already resumed enabled.
                if self._last_mode != "enabled":
                    self._last_mode = mode
                    start_watch = True
            if mode == "enabled" and self._releasing:
                self._abort_release = True
                if self._verbose:
                    print("sml_mode: enabled during disabling — abort RELEASE")
            if self._waiting:
                start_watch = False
                if mode == "enabled":
                    self._got_enabled = True
                    self._waiting = False
                    if self._timer is not None:
                        self._timer.cancel()
                        self._timer = None
                    if self._verbose:
                        print("sml_mode: ACK enabled — cancel RELEASE")
        if start_watch:
            self._ensure_boot_abort_watch(restart=restart_watch)

    def _cancel_boot_abort_timer_locked(self) -> None:
        if self._boot_abort_timer is not None:
            self._boot_abort_timer.cancel()
            self._boot_abort_timer = None

    def _ensure_boot_abort_watch(self, *, restart: bool = False) -> None:
        with self._lock:
            if self._boot_abort_timer is not None:
                if not restart:
                    return
                self._cancel_boot_abort_timer_locked()
            if self._waiting or self._releasing or self._release_queued:
                return
            self._boot_abort_timer = threading.Timer(
                self._boot_abort_timeout_sec, self._on_boot_abort_timeout
            )
            self._boot_abort_timer.daemon = True
            self._boot_abort_timer.start()
        print(
            f"sml_mode: watching boot-abort until enabled "
            f"({self._boot_abort_timeout_sec:.0f}s)"
        )

    def _on_boot_abort_timeout(self) -> None:
        with self._lock:
            self._boot_abort_timer = None
            mode = self._last_mode
            in_flight = self._waiting or self._releasing or self._release_queued
        if mode in ("enabled", "disabled"):
            return
        if in_flight:
            return
        print(
            f"sml_mode: boot-abort ({mode!r}) did not reach enabled within "
            f"{self._boot_abort_timeout_sec:.0f}s — challenge"
        )
        self.start_challenge("boot-abort-incomplete")

    def should_abort_release(self) -> bool:
        with self._lock:
            return self._abort_release

    def begin_disabling(self) -> bool:
        """Publish retained disabling and wait for a late Digicon enabled ACK.

        Returns True if RELEASE should proceed; False if Digicon is still alive.
        """
        with self._lock:
            self._releasing = True
            self._release_queued = False
            self._abort_release = False
        try:
            info = self._client.publish(SML_MODE_TOPIC, "disabling", qos=1, retain=True)
            if hasattr(info, "wait_for_publish"):
                info.wait_for_publish(timeout=3.0)
            print(
                f"sml_mode: TX disabling — wait {self._disabling_wait_sec}s "
                "for Digicon enabled ACK before Red/Unheld"
            )
        except Exception as e:
            print(f"sml_mode disabling publish failed: {e}", file=sys.stderr)
            # Still wait briefly so a concurrent enabled can abort.
        deadline = time.monotonic() + self._disabling_wait_sec
        while time.monotonic() < deadline:
            if self.should_abort_release():
                with self._lock:
                    self._releasing = False
                print("sml_mode: Digicon still enabled — suspend RELEASE")
                return False
            time.sleep(0.05)
        if self.should_abort_release():
            with self._lock:
                self._releasing = False
            print("sml_mode: Digicon still enabled — suspend RELEASE")
            return False
        return True

    def finish_disabled(self) -> None:
        """Retain disabled after a completed RELEASE burst."""
        with self._lock:
            self._releasing = False
            self._release_queued = False
            self._last_mode = "disabled"
        try:
            info = self._client.publish(SML_MODE_TOPIC, "disabled", qos=1, retain=True)
            if hasattr(info, "wait_for_publish"):
                info.wait_for_publish(timeout=3.0)
            print(f"TX -> {SML_MODE_TOPIC} disabled")
        except Exception as e:
            print(f"sml_mode disabled publish failed: {e}", file=sys.stderr)

    def cancel_release(self) -> None:
        """Digicon reclaimed control mid-burst; leave mode as Digicon published."""
        with self._lock:
            self._releasing = False
            self._release_queued = False
            self._abort_release = False

    def _on_timeout(self, generation: int) -> None:
        with self._lock:
            if generation != self._generation or not self._waiting:
                return
            if self._got_enabled:
                self._waiting = False
                return
            self._waiting = False
            self._timer = None
            if self._release_queued or self._releasing:
                return
            self._release_queued = True
        print(
            f"sml_mode: enabled but no live ACK within {self._query_timeout_sec}s — "
            f"queue disabling / Red / Unheld "
            f"(packed={list(self._packed)})"
        )
        try:
            self._cmd_q.put_nowait(SML_GUARD_RELEASE)
        except queue.Full:
            with self._lock:
                self._release_queued = False
            print("sml_mode: serial queue full; cannot schedule RELEASE", file=sys.stderr)

    def stop(self) -> None:
        with self._lock:
            self._waiting = False
            self._releasing = False
            self._release_queued = False
            self._cancel_boot_abort_timer_locked()
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


class SerialSyncWatchdog:
    """Detect Nano/USB desync and MASTER distributor / RF-path loss.

    Layers (cheapest first):
      1) USB PING -> ACK PING  (serial path alive; quiet unless miss)
      2) Turnout cmd ACK miss streak  (Nano not echoing text)
      3) Nano boot banner  (arm thin-accept check; setup() already subscribed)
      4) SerialException  (COM stolen / USB drop) -> reopen
      5) RESUBSCRIBE text  (manual / USB recovery — re-emit event 125)
      6) HBLOOP: probe when sensor/signal* quiet. On lost: keep probing with
         RESUBSCRIBE disarmed (DCC/RF path may return; MASTER sub often intact).
         After hbloop_retry_sec, a failed echo probe → miss + RESUBSCRIBE.

    MQTT broker resubscribe alone does not fix layout silence — LCOS radio
    subscriptions live on the Nano / MASTER.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        ack_fail_limit: int = SYNC_ACK_FAIL_LIMIT,
        ping_interval_sec: float = SYNC_USB_PING_INTERVAL_SEC,
        resubscribe_cooldown_sec: float = SYNC_RESUBSCRIBE_COOLDOWN_SEC,
        reopen_cooldown_sec: float = SYNC_REOPEN_COOLDOWN_SEC,
        boot_accept_grace_sec: float = SYNC_BOOT_ACCEPT_GRACE_SEC,
        expect_subscription_accepts: int = SYNC_EXPECT_SUBSCRIPTION_ACCEPTS,
        hbloop_enabled: bool = SYNC_HBLOOP_DEFAULT,
        hbloop_interval_sec: float = SYNC_HBLOOP_INTERVAL_SEC,
        hbloop_fail_limit: int = SYNC_HBLOOP_FAIL_LIMIT,
        hbloop_retry_sec: float = SYNC_HBLOOP_RETRY_SEC,
        verbose: bool = False,
    ) -> None:
        self.enabled = enabled
        self.ack_fail_limit = ack_fail_limit
        self.ping_interval_sec = ping_interval_sec
        self.resubscribe_cooldown_sec = resubscribe_cooldown_sec
        self.reopen_cooldown_sec = reopen_cooldown_sec
        self.boot_accept_grace_sec = boot_accept_grace_sec
        self.expect_subscription_accepts = expect_subscription_accepts
        self.hbloop_enabled = hbloop_enabled
        self.hbloop_interval_sec = hbloop_interval_sec
        self.hbloop_fail_limit = hbloop_fail_limit
        self.hbloop_retry_sec = hbloop_retry_sec
        self.verbose = verbose
        self._lock = threading.Lock()
        self._ack_fails = 0
        # Defer first ping a full interval so boot serial traffic is not a false miss.
        self._last_ping_mono = time.monotonic()
        self._last_resubscribe_mono = 0.0
        self._last_reopen_mono = 0.0
        self._awaiting_ping_ack = False
        self._subscription_accepts = 0
        self._boot_verify_deadline = 0.0
        self._boot_verify_reason = ""
        self._want_reopen = False
        self._want_resubscribe = False
        self._reopen_reason = ""
        self._resubscribe_reason = ""
        # HBLOOP: traffic-gated probe; on loss wait hbloop_retry_sec before echo-gated RESUBSCRIBE.
        self._hbloop_fails = 0
        self._awaiting_hbloop_echo = False
        self._seen_hbloop_echo = False
        self._hbloop_established = False
        self._hbloop_monitor_armed = bool(hbloop_enabled)
        self._hbloop_recovering = False
        # While recovering: RESUBSCRIBE stays disarmed until this mono time (echo-only window).
        self._hbloop_resub_armed_mono = 0.0
        self._last_layout_traffic_mono = 0.0
        self._last_hbloop_tick_mono = time.monotonic()
        self._hbloop_self_oct = HBLOOP_SELF_OCT_DEFAULT
        self._hbloop_sensor_topic_prefix = HBLOOP_SENSOR_TOPIC_PREFIX_DEFAULT

    def hbloop_sensor_topic_prefix(self) -> str:
        with self._lock:
            return self._hbloop_sensor_topic_prefix

    def note_hbloop_self_oct(self, oct_digits: str) -> None:
        """Learn bridge node from firmware HBLOOP_SELF / boot @<0…> (OCT digits)."""
        raw = (oct_digits or "").strip()
        if not raw:
            return
        normalized = raw.lstrip("0") or "0"
        try:
            display = int(normalized, 10)
        except ValueError:
            return
        prefix = f"track/sensor/{display * 100 + HBLOOP_BLOCK_INDEX}"
        with self._lock:
            prev = self._hbloop_self_oct
            self._hbloop_self_oct = normalized
            self._hbloop_sensor_topic_prefix = prefix
        if self.verbose and normalized != prev:
            print(
                f"sync: HBLOOP self node oct={normalized} "
                f"(quiet Subscription accepted; ghost {prefix})",
                file=sys.stderr,
            )

    def _mark_hbloop_healthy_locked(self, source: str) -> str | None:
        """Caller holds lock. Returns a log label if a lifecycle message should print."""
        first = not self._hbloop_established
        recovering = self._hbloop_recovering or (
            self._seen_hbloop_echo and not self._hbloop_established
        )
        self._hbloop_fails = 0
        self._awaiting_hbloop_echo = False
        self._seen_hbloop_echo = True
        self._hbloop_established = True
        self._hbloop_monitor_armed = True
        self._hbloop_recovering = False
        self._hbloop_resub_armed_mono = 0.0
        if first and not recovering:
            return "established"
        if recovering:
            return f"recovered:{source}"
        return None

    def note_layout_traffic(self, topic: str) -> None:
        """Sensor / signal* serial feedback — proves distributor; skip HBLOOP probes."""
        if not self.enabled or not self.hbloop_enabled:
            return
        if not topic.startswith(_HBLOOP_TRAFFIC_TOPIC_PREFIXES):
            return
        with self._lock:
            self._last_layout_traffic_mono = time.monotonic()
            label = self._mark_hbloop_healthy_locked("traffic")
        if label == "established":
            print("sync: HBLOOP established (layout feedback)", file=sys.stderr)
        elif label and label.startswith("recovered:"):
            print("sync: HBLOOP recovered (layout feedback)", file=sys.stderr)

    def note_turnout_ack(self, ok: bool) -> None:
        if not self.enabled:
            return
        with self._lock:
            if ok:
                self._ack_fails = 0
                return
            self._ack_fails += 1
            fails = self._ack_fails
        print(
            f"sync: turnout serial ACK miss ({fails}/{self.ack_fail_limit})",
            file=sys.stderr,
        )
        if fails >= self.ack_fail_limit:
            self.request_reopen(f"ack-miss-{fails}")
            self.request_resubscribe(f"ack-miss-{fails}")

    def arm_boot_subscription_verify(self, reason: str) -> None:
        """Wait for setup() accepts; RESUBSCRIBE only if still thin after grace."""
        if not self.enabled:
            return
        with self._lock:
            now = time.monotonic()
            # Multiple boot banner lines arrive; only zero accepts on first arm.
            if self._boot_verify_deadline <= 0.0:
                self._subscription_accepts = 0
                self._boot_verify_reason = reason
            self._boot_verify_deadline = now + self.boot_accept_grace_sec

    def maybe_finish_boot_subscription_verify(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            deadline = self._boot_verify_deadline
            if deadline <= 0.0 or time.monotonic() < deadline:
                return
            accepts = self._subscription_accepts
            reason = self._boot_verify_reason or "boot-thin-accepts"
            self._boot_verify_deadline = 0.0
            self._boot_verify_reason = ""
        expected = self.expect_subscription_accepts
        if accepts >= expected:
            if self.verbose:
                print(f"sync: boot subscriptions ok ({accepts}/{expected})")
            return
        print(
            f"sync: boot subscriptions thin ({accepts}/{expected}) -> RESUBSCRIBE",
            file=sys.stderr,
        )
        self.request_resubscribe(reason)

    def note_serial_line(self, stripped: str) -> None:
        if not self.enabled:
            return
        if stripped.startswith("ACK PING"):
            with self._lock:
                self._awaiting_ping_ack = False
                self._ack_fails = 0
            return
        if stripped.startswith("ACK HBLOOP"):
            return
        if stripped == "HBLOOP ECHO" or stripped.startswith("HBLOOP ECHO"):
            self.note_hbloop_echo("echo")
            return
        if stripped.startswith("Subscription accepted"):
            with self._lock:
                self._subscription_accepts += 1
                n = self._subscription_accepts
                self_oct = self._hbloop_self_oct
            if self.verbose:
                # Accept line uses OCT node id (same digits as HBLOOP_SELF).
                m = re.search(r"node:\s*(\d+)", stripped)
                oct_node = m.group(1) if m else ""
                if oct_node != self_oct:
                    print(f"sync: {stripped} (accepts={n})")
            return
        if stripped.startswith("Subscription declined"):
            if self.verbose:
                print(f"sync: {stripped}", file=sys.stderr)
            return
        self_m = _HBLOOP_SELF_RE.match(stripped)
        if self_m is not None:
            self.note_hbloop_self_oct(self_m.group(1))
            return
        at_m = _AT_NODE_RE.match(stripped)
        if at_m is not None:
            self.note_hbloop_self_oct(at_m.group(1))
            if self.verbose:
                print(f"sync: Nano boot marker seen: {stripped!r}")
            self.arm_boot_subscription_verify("nano-boot-banner")
            return
        if (
            stripped.startswith("LCOS Integration Library")
            or stripped.startswith("LCOS MQTT bridge")
        ):
            if self.verbose:
                print(f"sync: Nano boot marker seen: {stripped!r}")
            self.arm_boot_subscription_verify("nano-boot-banner")

    def note_serial_exception(self, exc: BaseException) -> None:
        print(f"sync: serial exception: {exc}", file=sys.stderr)
        self.request_reopen(f"serial-exception:{exc}")

    def request_reopen(self, reason: str) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        with self._lock:
            if now - self._last_reopen_mono < self.reopen_cooldown_sec:
                return
            self._want_reopen = True
            self._reopen_reason = reason
            self._last_reopen_mono = now

    def hbloop_is_established(self) -> bool:
        with self._lock:
            return bool(self._hbloop_established)

    def request_resubscribe(
        self, reason: str, *, force: bool = False, reset_hbloop_budget: bool = False
    ) -> bool:
        """Queue RESUBSCRIBE.

        force=True: bypass cooldown (MQTT FORCE, HBLOOP auto-lost, etc.).
        reset_hbloop_budget=True (manual MQTT): clear the one-shot auto-RESUBSCRIBE flag
        so a later MASTER reboot can auto-recover once again.
        """
        if not self.enabled:
            return False
        now = time.monotonic()
        with self._lock:
            if not force:
                remaining = self.resubscribe_cooldown_sec - (now - self._last_resubscribe_mono)
                if remaining > 0:
                    if self.verbose:
                        print(
                            f"sync: RESUBSCRIBE ignored (cooldown {remaining:.0f}s left)",
                            file=sys.stderr,
                        )
                    return False
            self._want_resubscribe = True
            self._resubscribe_reason = reason
            self._last_resubscribe_mono = now
            self._awaiting_hbloop_echo = False
            self._hbloop_fails = 0
            self._hbloop_monitor_armed = True
            self._hbloop_established = False
            self._last_hbloop_tick_mono = now
            if reset_hbloop_budget:
                self._hbloop_recovering = False
                self._hbloop_resub_armed_mono = 0.0
                self._seen_hbloop_echo = False
        return True

    def take_reopen_request(self) -> str | None:
        with self._lock:
            if not self._want_reopen:
                return None
            self._want_reopen = False
            return self._reopen_reason or "reopen"

    def take_resubscribe_request(self) -> str | None:
        with self._lock:
            if not self._want_resubscribe:
                return None
            self._want_resubscribe = False
            self._subscription_accepts = 0
            return self._resubscribe_reason or "resubscribe"

    def note_hbloop_echo(self, source: str = "echo") -> None:
        """Real LCOS HBLOOP path: serial HBLOOP ECHO or suppressed track/sensor/1507."""
        with self._lock:
            cleared = self._hbloop_fails
            label = self._mark_hbloop_healthy_locked(source)
        if label == "established":
            print("sync: HBLOOP established", file=sys.stderr)
        elif label and label.startswith("recovered:"):
            print("sync: HBLOOP recovered", file=sys.stderr)
        elif cleared and self.verbose:
            print(f"sync: HBLOOP ok ({source})", file=sys.stderr)

    def maybe_queue_usb_ping(self) -> bool:
        """Return True if the main loop should send USB_PING_SERIAL_LINE."""
        if not self.enabled:
            return False
        now = time.monotonic()
        with self._lock:
            if now - self._last_ping_mono < self.ping_interval_sec:
                return False
            missed = self._awaiting_ping_ack
            if missed:
                self._ack_fails += 1
                fails = self._ack_fails
            else:
                fails = 0
            self._last_ping_mono = now
            self._awaiting_ping_ack = True
        if missed:
            print(
                f"sync: USB PING ACK miss ({fails}/{self.ack_fail_limit})",
                file=sys.stderr,
            )
            if fails >= self.ack_fail_limit:
                self.request_reopen(f"ping-miss-{fails}")
        return True

    def maybe_queue_hbloop_probe(self) -> bool:
        """Queue serial HBLOOP beat when layout feedback is quiet.

        While recovering: keep probing; RESUBSCRIBE stays disarmed until
        hbloop_retry_sec after loss, then only fire on a failed echo (path test).
        """
        if not self.enabled or not self.hbloop_enabled:
            return False
        now = time.monotonic()
        trigger_lost = False
        trigger_miss_resub = False
        disarm_msg: str | None = None
        with self._lock:
            if not self._hbloop_monitor_armed:
                return False
            # Fresh sensor/signal* traffic — distributor is alive; skip the beat.
            if (
                self._last_layout_traffic_mono > 0.0
                and now - self._last_layout_traffic_mono < self.hbloop_interval_sec
            ):
                self._awaiting_hbloop_echo = False
                self._hbloop_fails = 0
                self._last_hbloop_tick_mono = now
                return False
            if now - self._last_hbloop_tick_mono < self.hbloop_interval_sec:
                return False
            if self._awaiting_hbloop_echo:
                self._hbloop_fails += 1
                fails = self._hbloop_fails
                if fails >= self.hbloop_fail_limit:
                    self._hbloop_fails = 0
                    self._awaiting_hbloop_echo = False
                    if self._hbloop_established:
                        # Path likely down (e.g. DCC node off) — MASTER sub may still be OK.
                        self._hbloop_established = False
                        self._hbloop_recovering = True
                        self._hbloop_resub_armed_mono = now + self.hbloop_retry_sec
                        trigger_lost = True
                    elif self._hbloop_recovering:
                        # Echo-gated RESUBSCRIBE: only after the disarm window, and only
                        # because this probe just failed (layout may have returned earlier).
                        if (
                            self._hbloop_resub_armed_mono > 0.0
                            and now >= self._hbloop_resub_armed_mono
                        ):
                            self._hbloop_resub_armed_mono = now + self.hbloop_retry_sec
                            trigger_miss_resub = True
                    elif not self._seen_hbloop_echo:
                        self._hbloop_monitor_armed = False
                        disarm_msg = (
                            "sync: HBLOOP echo never returned after enroll - monitor disarmed "
                            "(plants stay enrolled; use MQTT RESUBSCRIBE if sensors die)"
                        )
            self._last_hbloop_tick_mono = now
            if disarm_msg is None:
                self._awaiting_hbloop_echo = True
        if disarm_msg is not None:
            print(disarm_msg, file=sys.stderr)
            return False
        if trigger_lost:
            print(
                f"sync: HBLOOP lost - echo probes continue; "
                f"RESUBSCRIBE disarmed for {self.hbloop_retry_sec:.0f}s "
                f"(path may return without re-enroll)",
                file=sys.stderr,
            )
        if trigger_miss_resub:
            print(
                f"sync: HBLOOP miss - no echo after {self.hbloop_retry_sec:.0f}s; RESUBSCRIBE",
                file=sys.stderr,
            )
            self.request_resubscribe("hbloop-miss-echo-gate", force=True)
        return True

    def maybe_queue_hbloop_recovery(self) -> None:
        """No-op: RESUBSCRIBE is echo-gated inside maybe_queue_hbloop_probe."""
        return

    def mark_resubscribe_sent(self) -> None:
        if self.verbose:
            print("sync: RESUBSCRIBE sent - waiting for Subscription accepted lines")


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


def open_bridge_serial(
    port: str,
    baud: int,
    *,
    pulse_reset: bool = False,
    timeout: float = 0.25,
) -> serial.Serial:
    """Open COM to the Nano.

    Default pulse_reset=False keeps DTR/RTS low so agent restart does not reset the
    Nano (no setup() event-125 storm on a healthy MASTER). Use pulse_reset=True for
    intentional REOPEN / USB recovery so setup() re-enrolls plants.
    """
    ser = serial.Serial()
    ser.port = port
    ser.baudrate = baud
    ser.bytesize = serial.EIGHTBITS
    ser.parity = serial.PARITY_NONE
    ser.stopbits = serial.STOPBITS_ONE
    ser.timeout = timeout
    if not pulse_reset:
        # Set before open — Windows Arduino drivers pulse DTR on open otherwise.
        ser.dtr = False
        ser.rts = False
    ser.open()
    if not pulse_reset:
        try:
            ser.dtr = False
            ser.rts = False
        except Exception:
            pass
    return ser


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
    sml_guard: DigiconSmlGuard | None = None,
    sync_watch: SerialSyncWatchdog | None = None,
) -> None:
    """Handle one decoded serial text line and route to MQTT/logging."""
    stripped = line.strip("\r\n")
    if not stripped:
        return

    if sync_watch is not None:
        sync_watch.note_serial_line(stripped)

    if stripped.startswith("DBG "):
        if debug:
            print(stripped)
        return

    # Quiet USB health / HBLOOP ACK and ECHO (watchdog already logged lifecycle).
    if stripped.startswith("ACK PING") or stripped.startswith("ACK HBLOOP"):
        _publish_heartbeat_ack_if_present(
            client, stripped, heartbeat_on=heartbeat_on, verbose=verbose
        )
        return
    if stripped == "HBLOOP ECHO" or stripped.startswith("HBLOOP ECHO"):
        return

    # ACK … from Nano (command echo). Visible with --verbose.
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
        # Ghost Digicon topic if HBLOOP were MQTT-published — count as echo, never Digicon.
        ghost = (
            sync_watch.hbloop_sensor_topic_prefix()
            if sync_watch is not None
            else HBLOOP_SENSOR_TOPIC_PREFIX_DEFAULT
        )
        if topic == ghost or topic.startswith(ghost + "/"):
            if sync_watch is not None:
                sync_watch.note_hbloop_echo("1507")
            return
        mast_m = _SIGNALMAST_TOPIC_RE.match(topic)
        if mast_m is not None and sml_guard is not None:
            sml_guard.note_signalmast(mast_m.group(1))
        if sync_watch is not None:
            sync_watch.note_layout_traffic(topic)
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
        help="Debug heartbeat: USB-only PING on an interval (no turnout); MQTT PING->serial; "
        "serial ACK->MQTT (also DEBUG_HEARTBEAT in script). Same serial line as sync-watch.",
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
    ap.add_argument(
        "--sync-watch",
        action=argparse.BooleanOptionalAction,
        default=SYNC_WATCH_DEFAULT,
        help="USB PING + ACK-miss recovery + HBLOOP monitor (miss/lost logs only; "
        "no auto-RESUBSCRIBE from HBLOOP). On by default.",
    )
    args = ap.parse_args()

    heartbeat_on = bool(DEBUG_HEARTBEAT or args.debug_heartbeat)
    signalhead_on = bool(FORWARD_SIGNALHEAD_CMDS or args.signalhead)
    sync_watch = SerialSyncWatchdog(
        enabled=bool(args.sync_watch),
        hbloop_enabled=bool(args.sync_watch) and SYNC_HBLOOP_DEFAULT,
        verbose=args.verbose,
    )

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
        _subscribe_line(_client, CMD_POWER_SUBSCRIBE, qos=1)
        _subscribe_line(_client, SML_MODE_TOPIC, qos=1)
        _subscribe_line(_client, JMRI_STATE_TOPIC, qos=1)
        _subscribe_line(_client, BRIDGE_CMD_TOPIC, qos=1)
        # signalmast first (live roster, including retain), then signalhead SET/Unheld.
        _subscribe_line(_client, SIGNALMAST_SUBSCRIBE, qos=1)
        if signalhead_on:
            _subscribe_line(_client, SIGNALHEAD_SUBSCRIBE, qos=1)
            print("Signalhead MQTT->serial: live roster from track/signalmast/#")
        else:
            print(
                "Subscribe signalhead: skipped "
                "(signalhead->bridge off; use --signalhead to enable)"
            )
        guard = userdata[2] if isinstance(userdata, tuple) and len(userdata) > 2 else None
        if isinstance(guard, DigiconSmlGuard):
            # Wait for retained sml_mode, then challenge if enabled or watch boot-abort.
            threading.Timer(
                1.0, guard.maybe_start_challenge, args=("bridge-start",)
            ).start()

    def on_message(_client, userdata, msg):
        ping_q, cmd_q, guard = userdata
        if msg.topic == BRIDGE_CMD_TOPIC:
            if bool(getattr(msg, "retain", False)):
                return
            try:
                body = msg.payload.decode("utf-8", errors="replace").strip().upper()
            except Exception:
                return
            if body == "RESUBSCRIBE" or body == "RESUBSCRIBE FORCE":
                want_force = body.endswith("FORCE")
                # While HBLOOP is healthy, refuse plain RESUBSCRIBE (avoids fouling MASTER).
                # FORCE always allowed. When not established, plain RESUBSCRIBE still has
                # no cooldown (force=True on the queue path).
                if not want_force and sync_watch.hbloop_is_established():
                    print(
                        "sync: MQTT RESUBSCRIBE ignored "
                        "(HBLOOP established - use RESUBSCRIBE FORCE)",
                        file=sys.stderr,
                    )
                    return
                if sync_watch.request_resubscribe(
                    "mqtt-bridge-cmd",
                    force=True,
                    reset_hbloop_budget=True,
                ):
                    print("sync: MQTT track/bridge/cmd RESUBSCRIBE queued")
            elif body == "PING":
                try:
                    cmd_q.put_nowait(USB_PING_SERIAL_LINE)
                except queue.Full:
                    pass
            elif body == "REOPEN":
                sync_watch.request_reopen("mqtt-bridge-cmd")
                print("sync: MQTT track/bridge/cmd REOPEN queued")
            elif body == "HBLOOP":
                try:
                    cmd_q.put_nowait(HBLOOP_SERIAL_LINE)
                    print("sync: MQTT track/bridge/cmd HBLOOP queued")
                except queue.Full:
                    pass
            return
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
                    print("MQTT track/state OFFLINE -> maybe sml_mode challenge")
                guard.maybe_start_challenge("jmri-offline")
            return

        # --- signalmast/<packed>: enroll only (retain counts). Never serial. ---
        mast_m = _SIGNALMAST_TOPIC_RE.match(msg.topic)
        if mast_m is not None:
            if isinstance(guard, DigiconSmlGuard):
                guard.note_signalmast(mast_m.group(1))
            return
        if msg.topic.startswith(SIGNALMAST_TOPIC_PREFIX):
            if args.verbose:
                print(
                    f"MQTT signalmast ignored (need packed digits): {msg.topic!r}",
                    file=sys.stderr,
                )
            return

        # --- signalhead/<packed> (optional legacy IH prefix) ---
        if not signalhead_on and msg.topic.startswith(SIGNALHEAD_TOPIC_PREFIX):
            return
        signal_m = _SIGNALHEAD_TOPIC_RE.match(msg.topic)
        if signal_m is not None:
            if not args.restore and bool(getattr(msg, "retain", False)):
                return
            try:
                _own_body = msg.payload.decode("utf-8", errors="replace").strip()
            except Exception:
                _own_body = ""
            if (
                isinstance(guard, DigiconSmlGuard)
                and _own_body
                and guard.consume_own_signalhead(msg.topic, _own_body)
            ):
                if args.verbose:
                    print(
                        f"MQTT signalhead ignored (own TX echo): {msg.topic!r} {_own_body}"
                    )
                return
            if isinstance(guard, DigiconSmlGuard) and guard.is_in_flight():
                if args.verbose:
                    print(
                        "MQTT signalhead ignored (sml_mode RELEASE in flight): "
                        f"{msg.topic!r}"
                    )
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
            # GET/QUERY may probe any signal UID without Digicon roster enroll.
            # MASTER (display node 0 → packed 32–47) is not Digicon-rostered; allow SET too.
            is_probe = body.lower() in ("get", "query")
            is_master_signal = (
                packed_mqtt_lcos_node_validation_error(packed) is None
                and int(packed, 10) // 100 == 0
                and packed_is_lcos_signal(packed)
            )
            if not packed_is_lcos_signal(packed) or (
                not is_probe
                and not is_master_signal
                and not (isinstance(guard, DigiconSmlGuard) and guard.has_packed(packed))
            ):
                if args.verbose:
                    print(
                        f"MQTT signalhead ignored (not on live roster): {msg.topic!r}"
                    )
                return
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

        # --- track power ---
        power_m = _POWER_HIER_TOPIC_RE.match(msg.topic)
        if power_m is not None:
            if not args.restore and bool(getattr(msg, "retain", False)):
                return
            try:
                body = msg.payload.decode("utf-8", errors="replace").strip()
            except Exception as e:
                if args.verbose:
                    print(f"MQTT power cmd: UTF-8 decode failed: {e}", file=sys.stderr)
                return
            if not _POWER_STATE_RE.match(body):
                if args.verbose:
                    print(
                        "MQTT power cmd rejected: expected GET/ON/OFF/NORMAL/REVERSE/RELEASE; "
                        f"decoded={body!r}"
                    )
                return
            district = power_m.group(1)
            if int(district, 10) > 127:
                if args.verbose:
                    print(f"MQTT power cmd rejected: district {district!r} > 127")
                return
            if args.verbose:
                print(f"MQTT RX power cmd topic={msg.topic!r} body={body!r}")
            line = f"{CMD_POWER_TOPIC}/{district} {body}\n".encode("utf-8")
            _queue_serial_cmd(cmd_q, line, label="power")
            return
        if msg.topic.startswith(f"{CMD_POWER_TOPIC}/"):
            if args.verbose:
                print(
                    f"MQTT power cmd ignored (need district digits): {msg.topic!r}",
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
        f"{'; sync-watch ON' if sync_watch.enabled else '; sync-watch OFF'}"
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
        ser = open_bridge_serial(args.com, args.baud, pulse_reset=False)
    except serial.SerialException as e:
        print(f"Serial open failed: {e}", file=sys.stderr)
        if bridge_online_published:
            _publish_bridge_status(client, BRIDGE_STATUS_OFFLINE, verbose=args.verbose)
        client.loop_stop()
        client.disconnect()
        return 1

    last_heartbeat = time.monotonic()
    # Turnout cmds: wait briefly for Nano ACK (USB RX was garbled without pacing).
    # Signalhead cmds: no ACK expected — pace with a short gap only.
    # TODO: revisit serial ACK/pacing speeds (turnout 0.35s, signalhead 50ms).
    _ACK_WAIT_SEC = 0.35
    _SIGNALHEAD_GAP_SEC = SML_MODE_SERIAL_GAP_SEC

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
            sml_guard=sml_guard,
            sync_watch=sync_watch,
        )
        return line.strip("\r\n").startswith("ACK ")

    def _drain_serial_nonblocking(max_sec: float = 0.02) -> None:
        """Pull any pending Nano lines (status/ACK) without waiting for a specific ACK."""
        deadline = time.monotonic() + max_sec
        while time.monotonic() < deadline:
            line = _read_one_serial_line()
            if line is None:
                break
            _handle_and_is_ack(line)

    def _write_serial_signalhead(line_out: bytes, *, gap_sec: float | None = None) -> None:
        """Signalhead SET/RELEASE — no ACK wait; short gap for USB/Nano pacing."""
        ser.write(line_out)
        ser.flush()
        if args.verbose:
            print(f"MQTT -> serial {line_out!r}")
        _drain_serial_nonblocking(0.02)
        time.sleep(_SIGNALHEAD_GAP_SEC if gap_sec is None else gap_sec)

    def _write_serial_cmd(line_out: bytes) -> None:
        # Digicon / JMRI signalhead: firmware does not ACK these the way turnout cmds do.
        if line_out.startswith(SIGNALHEAD_TOPIC_PREFIX.encode("ascii")):
            _write_serial_signalhead(line_out)
            return
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
                drain_until = time.monotonic() + 0.05
                while time.monotonic() < drain_until:
                    more = _read_one_serial_line()
                    if more is None:
                        break
                    _handle_and_is_ack(more)
                break
        if not saw_ack:
            sync_watch.note_turnout_ack(False)
            print("MQTT -> serial: no ACK within timeout", file=sys.stderr)
        else:
            sync_watch.note_turnout_ack(True)

    def _run_sml_guard_release() -> None:
        """Announce disabling → wait → (unless Digicon ACKs) Red → hold → Unheld → disabled."""
        if not sml_guard.begin_disabling():
            return
        gap = SML_MODE_SERIAL_GAP_SEC
        hold = SML_MODE_RED_HOLD_SEC
        heads = sml_guard.packed_heads
        print(
            f"sml_mode: serial Red ({list(heads)}), "
            f"hold {hold}s, then Unheld (gap={gap}s, no ACK wait)"
        )
        for packed in heads:
            if sml_guard.should_abort_release():
                print("sml_mode: Digicon enabled mid-burst — abort RELEASE")
                sml_guard.cancel_release()
                return
            err = packed_mqtt_lcos_node_validation_error(packed)
            if err is not None:
                print(f"sml_mode burst skip {packed}: {err}", file=sys.stderr)
                continue
            _write_serial_signalhead(
                f"{SIGNALHEAD_TOPIC_PREFIX}{packed} Red\n".encode("utf-8"),
                gap_sec=gap,
            )
            sml_guard.publish_head_to_mqtt(packed, "Red")
        print(f"sml_mode: holding Red {hold}s before Unheld")
        hold_deadline = time.monotonic() + hold
        while time.monotonic() < hold_deadline:
            if sml_guard.should_abort_release():
                print("sml_mode: Digicon enabled during Red hold — abort Unheld")
                sml_guard.cancel_release()
                return
            line = _read_one_serial_line()
            if line is not None:
                _handle_and_is_ack(line)
            else:
                time.sleep(0.02)
        for packed in heads:
            if sml_guard.should_abort_release():
                print("sml_mode: Digicon enabled before Unheld — abort")
                sml_guard.cancel_release()
                return
            err = packed_mqtt_lcos_node_validation_error(packed)
            if err is not None:
                continue
            _write_serial_signalhead(
                f"{SIGNALHEAD_TOPIC_PREFIX}{packed} Unheld\n".encode("utf-8"),
                gap_sec=gap,
            )
            sml_guard.publish_head_to_mqtt(packed, "Unheld")
        sml_guard.finish_disabled()

    def _reopen_serial(reason: str) -> bool:
        nonlocal ser
        print(f"sync: reopening {args.com} ({reason})", file=sys.stderr)
        try:
            if ser is not None and getattr(ser, "is_open", False):
                ser.close()
        except Exception:
            pass
        time.sleep(1.5)
        for attempt in range(1, 8):
            try:
                ser = open_bridge_serial(
                    args.com, args.baud, pulse_reset=True
                )
                print(f"sync: serial reopened (attempt {attempt})")
                boot_deadline = time.monotonic() + 4.0
                while time.monotonic() < boot_deadline:
                    line = _read_one_serial_line()
                    if line is not None:
                        _handle_and_is_ack(line)
                    else:
                        time.sleep(0.05)
                return True
            except serial.SerialException as exc:
                print(f"sync: reopen failed attempt {attempt}: {exc}", file=sys.stderr)
                time.sleep(1.0)
        return False

    def _send_resubscribe(reason: str) -> None:
        print(f"sync: RESUBSCRIBE ({reason})")
        try:
            ser.write(RESUBSCRIBE_SERIAL_LINE)
            ser.flush()
        except serial.SerialException as exc:
            sync_watch.note_serial_exception(exc)
            return
        sync_watch.mark_resubscribe_sent()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            line = _read_one_serial_line()
            if line is not None:
                _handle_and_is_ack(line)
            else:
                time.sleep(0.05)

    try:
        while not stop:
            try:
                reopen_reason = sync_watch.take_reopen_request()
                if reopen_reason is not None:
                    if not _reopen_serial(reopen_reason):
                        time.sleep(2.0)
                        continue
                    # DTR reset runs setup(); boot markers arm thin-accept verify.
                    # Do not RESUBSCRIBE here — that doubles event-125 with setup().
                    sync_watch.arm_boot_subscription_verify(f"after-reopen:{reopen_reason}")

                sync_watch.maybe_finish_boot_subscription_verify()
                sync_watch.maybe_queue_hbloop_recovery()
                resub_reason = sync_watch.take_resubscribe_request()
                if resub_reason is not None:
                    _send_resubscribe(resub_reason)

                while True:
                    try:
                        line_out = serial_cmd_queue.get_nowait()
                    except queue.Empty:
                        break
                    if line_out is SML_GUARD_RELEASE:
                        _run_sml_guard_release()
                        continue
                    if line_out == USB_PING_SERIAL_LINE:
                        try:
                            ser.write(USB_PING_SERIAL_LINE)
                            ser.flush()
                        except serial.SerialException as exc:
                            sync_watch.note_serial_exception(exc)
                        continue
                    if line_out == HBLOOP_SERIAL_LINE:
                        try:
                            ser.write(HBLOOP_SERIAL_LINE)
                            ser.flush()
                        except serial.SerialException as exc:
                            sync_watch.note_serial_exception(exc)
                        continue
                    _write_serial_cmd(line_out)

                while True:
                    try:
                        ping_cmd_queue.get_nowait()
                    except queue.Empty:
                        break
                    ser.write(HEARTBEAT_SERIAL_LINE)
                    ser.flush()

                now = time.monotonic()
                if heartbeat_on and (now - last_heartbeat) >= HEARTBEAT_INTERVAL_SEC:
                    ser.write(HEARTBEAT_SERIAL_LINE)
                    ser.flush()
                    last_heartbeat = now
                elif sync_watch.maybe_queue_usb_ping():
                    try:
                        ser.write(USB_PING_SERIAL_LINE)
                        ser.flush()
                    except serial.SerialException as exc:
                        sync_watch.note_serial_exception(exc)
                if sync_watch.maybe_queue_hbloop_probe():
                    try:
                        ser.write(HBLOOP_SERIAL_LINE)
                        ser.flush()
                    except serial.SerialException as exc:
                        sync_watch.note_serial_exception(exc)

                line = _read_one_serial_line()
                if line is None:
                    continue
                _handle_and_is_ack(line)
            except serial.SerialException as e:
                sync_watch.note_serial_exception(e)
                time.sleep(0.5)
    finally:
        sml_guard.stop()
        if bridge_online_published:
            _publish_bridge_status(client, BRIDGE_STATUS_OFFLINE, verbose=args.verbose)
        try:
            if ser is not None and getattr(ser, "is_open", False):
                ser.close()
        except Exception:
            pass
        client.loop_stop()
        client.disconnect()
        print("Stopped.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
