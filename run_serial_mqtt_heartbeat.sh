#!/usr/bin/env bash
# PING heartbeat to serial + MQTT ACK publish + verbose TX lines.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

: "${SERIAL_PORT:=/dev/ttyUSB0}"
: "${BROKER:=192.168.137.1}"

PY=python3
command -v "$PY" >/dev/null 2>&1 || PY=python

exec "$PY" "$ROOT/serial_to_mqtt.py" --com "$SERIAL_PORT" --broker "$BROKER" --debug-heartbeat --verbose "$@"
