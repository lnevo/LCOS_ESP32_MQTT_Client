#!/usr/bin/env python3
"""One-shot Windows lab: start bridge (SSH-safe), probe turnouts, leave bridge detached."""

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
LOG = ROOT / "_probe_bridge.log"
BROKER = "192.168.137.2"
TURNOUTS = ["100", "108", "408", "411", "1208"]

# Survive SSH logout on Windows
CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008
DETACH_FLAGS = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def kill_bridge() -> None:
    ps = (
        "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
        "Where-Object { $_.CommandLine -and ($_.CommandLine -match 'serial_to_mqtt\\.py') } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        check=False,
        capture_output=True,
    )
    time.sleep(2)


def start_bridge() -> subprocess.Popen:
    if LOG.exists():
        LOG.unlink()
    return subprocess.Popen(
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
        stdout=LOG.open("w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        creationflags=DETACH_FLAGS,
        close_fds=True,
    )


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


def wait_connected(timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if LOG.exists() and "Connected to MQTT" in LOG.read_text(
            encoding="utf-8", errors="replace"
        ):
            return True
        time.sleep(0.5)
    return False


def bridge_alive() -> bool:
    ps = (
        "if (Get-CimInstance Win32_Process | Where-Object { "
        "$_.CommandLine -match 'serial_to_mqtt\\.py' }) { 'YES' } else { 'NO' }"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
    )
    return "YES" in (r.stdout or "")


def log_interesting() -> None:
    if not LOG.exists():
        print("(no log)", flush=True)
        return
    keys = (
        "ACK",
        "MQTT",
        "turnout",
        "Subscription",
        "RESUBSCRIBE",
        "PING",
        "sync:",
        "ERROR",
        "SerialException",
    )
    for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        if any(k in line for k in keys):
            print(line.encode("ascii", "replace").decode("ascii"), flush=True)


def probe_one(packed: str) -> int:
    rx: list[str] = []

    def listen():
        rx.extend(mqtt_listen([f"track/turnout/{packed}", "track/sensor/#"], 5.0))

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    time.sleep(0.3)
    mqtt_pub(f"track/cmd/turnout/{packed}", "GET")
    t.join()
    print(f"GET {packed} count={len(rx)}", flush=True)
    for line in rx:
        print(f"  RX {line}", flush=True)
    return len(rx)


def main() -> int:
    print("=== KILL/START BRIDGE (detached) ===", flush=True)
    kill_bridge()
    proc = start_bridge()
    print(f"BRIDGE_PID {proc.pid}", flush=True)
    if not wait_connected():
        print("FAIL: bridge did not connect", flush=True)
        log_interesting()
        return 1
    print(f"CONNECTED True ALIVE {bridge_alive()}", flush=True)
    time.sleep(4)

    print("=== RESUBSCRIBE + PING ===", flush=True)
    mqtt_pub("track/bridge/cmd", "RESUBSCRIBE")
    time.sleep(5)
    mqtt_pub("track/bridge/cmd", "PING")
    time.sleep(2)

    print("=== TURNOUT GET sweep ===", flush=True)
    total = 0
    for packed in TURNOUTS:
        total += probe_one(packed)

    print("=== BRIDGE LOG (interesting) ===", flush=True)
    log_interesting()
    print(f"=== DONE status_hits={total} bridge_alive={bridge_alive()} ===", flush=True)
    return 0 if bridge_alive() else 2


if __name__ == "__main__":
    raise SystemExit(main())
