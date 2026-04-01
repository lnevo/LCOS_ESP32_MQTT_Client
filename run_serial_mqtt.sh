#!/usr/bin/env bash
# Arduino Nano USB serial <-> MQTT.
# Defaults: SERIAL_PORT (/dev/ttyUSB0), BROKER. Env: SERIAL_VERBOSE=1 adds --verbose before args.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

: "${SERIAL_PORT:=/dev/ttyUSB0}"
: "${BROKER:=192.168.137.1}"

PY=python3
command -v "$PY" >/dev/null 2>&1 || PY=python

show_help() {
  cat <<'EOF'
run_serial_mqtt.sh — run serial_to_mqtt.py with defaults from SERIAL_PORT and BROKER.

  Help:  -h   -?   --help

  Short options (combine as separate tokens: -v -d -hb -r):
    -v     Verbose MQTT publishes (--verbose)
    -d     Arduino DBG lines on console (--debug)
    -hb    Serial PING heartbeat + MQTT ACK (--debug-heartbeat)
    -r     Apply retained turnout cmds (and heartbeat PING if -hb) on connect (--restore)

  Environment (optional):
    SERIAL_PORT   default /dev/ttyUSB0
    BROKER        default 192.168.137.1
    SERIAL_VERBOSE=1   same as -v

  Other arguments are passed to Python (e.g. --baud 115200 --mqtt-port 1883).

  Full Python usage:  python3 serial_to_mqtt.py --help
EOF
}

ARGS=()
if [[ "${SERIAL_VERBOSE:-0}" == "1" ]]; then
  ARGS+=(--verbose)
fi

while (($#)); do
  case "$1" in
    -h|-\?|--help)
      show_help
      exit 0
      ;;
    -v)
      ARGS+=(--verbose)
      shift
      ;;
    -d)
      ARGS+=(--debug)
      shift
      ;;
    -hb)
      ARGS+=(--debug-heartbeat)
      shift
      ;;
    -r)
      ARGS+=(--restore)
      shift
      ;;
    --)
      shift
      ARGS+=("$@")
      break
      ;;
    *)
      ARGS+=("$1")
      shift
      ;;
  esac
done

exec "$PY" "$ROOT/serial_to_mqtt.py" --com "$SERIAL_PORT" --broker "$BROKER" "${ARGS[@]}"
