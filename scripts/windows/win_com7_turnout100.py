#!/usr/bin/env python3
"""Windows one-shot: start bridge, baseline GET 100, COM7 reset, RESUBSCRIBE, GET again."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    import serial
except ImportError:
    print("need pyserial", file=sys.stderr)
    sys.exit(1)
try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("need paho-mqtt", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "_probe_bridge.log"
BROKER = "192.168.137.2"
TURNOUT = "100"
COM_MASTER = "COM7"
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


def start_bridge() -> None:
    if LOG.exists():
        LOG.unlink()
    subprocess.Popen(
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


def wait_connected(timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if LOG.exists() and "Connected to MQTT" in LOG.read_text(
            encoding="utf-8", errors="replace"
        ):
            return True
        time.sleep(0.5)
    return False


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


def probe_get(label: str) -> int:
    rx: list[str] = []

    def listen():
        rx.extend(mqtt_listen([f"track/turnout/{TURNOUT}"], 6.0))

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    time.sleep(0.3)
    mqtt_pub(f"track/cmd/turnout/{TURNOUT}", "GET")
    t.join()
    print(f"{label} GET {TURNOUT} count={len(rx)}", flush=True)
    for line in rx:
        print(f"  RX {line}", flush=True)
    return len(rx)


def main() -> int:
    print("=== START BRIDGE ===", flush=True)
    kill_bridge()
    start_bridge()
    if not wait_connected():
        print("FAIL: bridge did not connect", flush=True)
        return 1
    time.sleep(5)
    print(f"CONNECTED alive={bridge_alive()}", flush=True)

    print("=== BASELINE GET ===", flush=True)
    base = probe_get("BASE")

    print(f"=== {COM_MASTER} open/close ===", flush=True)
    try:
        sp = serial.Serial(COM_MASTER, 115200, timeout=0.5)
        time.sleep(0.8)
        try:
            _ = sp.read(sp.in_waiting or 1)
        except Exception:
            pass
        sp.close()
        print(f"{COM_MASTER}_OK", flush=True)
    except Exception as exc:
        print(f"{COM_MASTER}_FAIL {exc}", flush=True)
        return 1

    time.sleep(3)
    print("=== GET after COM7 (auto-recovery window) ===", flush=True)
    after_reset = probe_get("POST_COM7")

    print("=== Forced RESUBSCRIBE ===", flush=True)
    mqtt_pub("track/bridge/cmd", "RESUBSCRIBE")
    time.sleep(6)

    print("=== GET after RESUBSCRIBE ===", flush=True)
    after_resub = probe_get("POST_RESUB")

    print("--- log keys ---", flush=True)
    if LOG.exists():
        keys = ("ACK", "RESUBSCRIBE", "Subscription", "COM", "reopen", "100", "sync:")
        for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
            if any(k in line for k in keys):
                print(line.encode("ascii", "replace").decode("ascii"), flush=True)

    print(
        f"=== DONE base={base} post_com7={after_reset} post_resub={after_resub} "
        f"alive={bridge_alive()} ===",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
