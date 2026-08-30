#!/usr/bin/env python3
"""Windows lab smoke for sync recovery. Run on the mini PC (COM3 bridge, COM7 reset)."""

from __future__ import annotations

import subprocess
import sys
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
BROKER = "192.168.137.2"
COM_BRIDGE = "COM3"
COM_MASTER = "COM7"
LOG = ROOT / "_sync_test_bridge.log"
RESULT = ROOT / "_sync_test_result.txt"
TURNOUT = "100"  # known-good on Windows lab (node1/uid0); 408 often ACKs with no status


def log(msg: str) -> None:
    line = msg.rstrip()
    safe = line.encode("ascii", "replace").decode("ascii")
    print(safe, flush=True)
    with RESULT.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


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


def mqtt_pub(topic: str, payload: str) -> None:
    c = mqtt.Client()
    c.connect(BROKER, 1883, 60)
    c.loop_start()
    c.publish(topic, payload, qos=1, retain=False)
    time.sleep(0.5)
    c.loop_stop()
    c.disconnect()
    log(f"PUB {topic} {payload}")


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


def log_tail(path: Path, n: int = 40) -> None:
    if not path.exists():
        log("(no bridge log yet)")
        return
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-n:]:
        log(line)


def main() -> int:
    if RESULT.exists():
        RESULT.unlink()
    if LOG.exists():
        LOG.unlink()

    kill_bridge()
    log("=== START BRIDGE ===")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "serial_to_mqtt.py",
            "--com",
            COM_BRIDGE,
            "--broker",
            BROKER,
            "--verbose",
            "--signalhead",
        ],
        cwd=str(ROOT),
        stdout=LOG.open("w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
    )
    time.sleep(7)
    log_tail(LOG, 50)
    text = LOG.read_text(encoding="utf-8", errors="replace") if LOG.exists() else ""
    if "Connected to MQTT" not in text:
        log("FAIL: bridge did not connect")
        kill_bridge()
        return 1

    log("=== USB PING via MQTT cmd ===")
    mqtt_pub("track/bridge/cmd", "PING")
    time.sleep(2)
    text = LOG.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if "ACK PING" in line or "USB PING" in line or line.startswith("sync:"):
            log(line)
    if "ACK PING" not in text and "ACK PING" not in text.replace("\r", ""):
        # ACK lines may only appear when verbose prints them
        ping_ok = "USB PING" in text or "mqtt cmd" in text
        log(f"PING_PATH_SEEN={ping_ok}")

    log(f"=== {COM_MASTER} open/close (master reset sim) ===")
    try:
        sp = serial.Serial(COM_MASTER, 115200, timeout=0.5)
        time.sleep(0.8)
        try:
            _ = sp.read(sp.in_waiting or 1)
        except Exception:
            pass
        sp.close()
        log(f"{COM_MASTER}_OK")
    except Exception as exc:
        log(f"{COM_MASTER}_FAIL {exc}")

    time.sleep(2)
    log("=== Turnout throw after master reset ===")
    # start listening shortly before publish
    import threading

    status: list[str] = []

    def listen():
        status.extend(
            mqtt_listen([f"track/turnout/{TURNOUT}", "track/sensor/#"], 8.0)
        )

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    time.sleep(0.5)
    mqtt_pub(f"track/cmd/turnout/{TURNOUT}", "THROWN")
    t.join()
    for s in status:
        log(f"STATUS {s}")
    log(f"STATUS_COUNT {len(status)}")

    log("=== MQTT RESUBSCRIBE ===")
    mqtt_pub("track/bridge/cmd", "RESUBSCRIBE")
    time.sleep(6)
    text = LOG.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if any(
            k in line
            for k in (
                "RESUBSCRIBE",
                "Subscription accepted",
                "Subscription declined",
                "sync:",
            )
        ):
            log(line)
    accepts = text.count("Subscription accepted")
    log(f"ACCEPT_LINES {accepts}")

    log("=== Turnout GET after RESUBSCRIBE ===")
    get_rx: list[str] = []

    def listen_get():
        get_rx.extend(mqtt_listen([f"track/turnout/{TURNOUT}"], 6.0))

    t2 = threading.Thread(target=listen_get, daemon=True)
    t2.start()
    time.sleep(0.5)
    mqtt_pub(f"track/cmd/turnout/{TURNOUT}", "GET")
    t2.join()
    for s in get_rx:
        log(f"GETRX {s}")
    log(f"GET_COUNT {len(get_rx)}")

    log("=== BRIDGE LOG TAIL ===")
    log_tail(LOG, 30)
    log(f"=== DONE pid={proc.pid} ===")
    # leave bridge running
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
