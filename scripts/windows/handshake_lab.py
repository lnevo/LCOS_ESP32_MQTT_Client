#!/usr/bin/env python3
"""Lab handshake validation: enroll, HBLOOP echo, turnout 408 → sensor feedback.

Uses COM3 for the bridge. Optional --reboot-master opens COM7 briefly (MASTER reset).
"""
from __future__ import annotations

import argparse
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

ROOT = Path(r"C:/Users/lnevo/Documents/LCOS_ESP32_MQTT_Client")
BROKER = "192.168.137.2"
LOG = ROOT / "_handshake_lab.log"
TURNOUT = "408"
SENSOR_TOPICS = ("track/sensor/470", "track/sensor/471")


def kill_bridge() -> None:
    ps = (
        "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
        "Where-Object { $_.CommandLine -and ($_.CommandLine -match 'serial_to_mqtt\\.py') } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False, capture_output=True)
    time.sleep(2)


def reboot_master_via_com7() -> None:
    """Opening COM7 resets the MASTER Nano on this lab."""
    try:
        import serial
    except ImportError:
        print("NEED pyserial for COM7", flush=True)
        return
    print("MASTER reboot: opening COM7…", flush=True)
    try:
        s = serial.Serial("COM7", 115200, timeout=0.5)
        time.sleep(0.5)
        s.close()
    except Exception as exc:
        print(f"COM7 open failed: {exc}", flush=True)
        return
    print("MASTER reboot: COM7 closed — wait for MASTER boot", flush=True)
    time.sleep(8)


def mqtt_pub(topic: str, payload: str) -> None:
    c = mqtt.Client()
    c.connect(BROKER, 1883, 60)
    c.loop_start()
    c.publish(topic, payload, qos=0, retain=False)
    time.sleep(0.35)
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
        c.subscribe(t, 0)
    c.loop_start()
    time.sleep(seconds)
    c.loop_stop()
    c.disconnect()
    return seen


def start_bridge() -> subprocess.Popen:
    if LOG.exists():
        LOG.unlink()
    logf = LOG.open("w", encoding="utf-8", buffering=1)
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
        stdout=logf,
        stderr=subprocess.STDOUT,
    )


def wait_log(pred, timeout: float) -> str:
    deadline = time.time() + timeout
    text = ""
    while time.time() < deadline:
        text = LOG.read_text(encoding="utf-8", errors="replace") if LOG.exists() else ""
        if pred(text):
            return text
        time.sleep(0.4)
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reboot-master", action="store_true")
    ap.add_argument("--hold-sec", type=float, default=35.0, help="watch HBLOOP after validate")
    args = ap.parse_args()

    kill_bridge()
    if args.reboot_master:
        reboot_master_via_com7()

    proc = start_bridge()
    text = wait_log(
        lambda t: "subscriptions complete" in t or "startup plants incomplete" in t,
        25.0,
    )
    print("=== after enroll wait ===", flush=True)
    for line in text.splitlines():
        if any(k in line for k in ("sync:", "Subscription", "Opening", "Connected")):
            print(line.encode("ascii", "replace").decode("ascii"), flush=True)

    text = wait_log(
        lambda t: "HBLOOP established" in t or "HBLOOP recovered" in t or "no HBLOOP ECHO" in t,
        20.0,
    )
    echo_ok = "HBLOOP established" in text or "HBLOOP recovered" in text
    print(f"ECHO_OK={echo_ok}", flush=True)

    rx: list[str] = []

    def listen() -> None:
        rx.extend(mqtt_listen([*SENSOR_TOPICS, "track/turnout/408"], 6.0))

    th = threading.Thread(target=listen, daemon=True)
    th.start()
    time.sleep(0.4)
    mqtt_pub(f"track/cmd/turnout/{TURNOUT}", "TOGGLE")
    th.join()
    sensors = [x for x in rx if x.startswith("track/sensor/")]
    turnout = [x for x in rx if x.startswith("track/turnout/")]
    print(f"=== TOGGLE validate sensors={len(sensors)} turnout={len(turnout)} ===", flush=True)
    for x in rx:
        print(f"  RX {x}", flush=True)
    sensor_ok = len(sensors) > 0
    print(f"SENSOR_OK={sensor_ok}", flush=True)

    print(f"=== hold {args.hold_sec:.0f}s watching HBLOOP ===", flush=True)
    time.sleep(args.hold_sec)
    text = LOG.read_text(encoding="utf-8", errors="replace") if LOG.exists() else ""
    lost = text.count("HBLOOP lost")
    miss = text.count("HBLOOP miss")
    resub = text.count("sync: RESUBSCRIBE (")
    recovered = text.count("HBLOOP recovered")
    print(
        f"HOLD lost={lost} miss={miss} resubscribe_calls={resub} recovered={recovered}",
        flush=True,
    )
    for line in text.splitlines()[-40:]:
        if "sync:" in line or "Subscription" in line:
            print(line.encode("ascii", "replace").decode("ascii"), flush=True)

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

    ok = sensor_ok and echo_ok
    print(
        f"RESULT {'PASS' if ok else 'FAIL'} sensor_ok={sensor_ok} echo_ok={echo_ok}",
        flush=True,
    )
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
