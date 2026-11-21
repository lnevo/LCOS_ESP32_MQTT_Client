#!/usr/bin/env bash
# bridge.sh - control the LCOS serial<->MQTT bridge on a Linux host (systemd).
#
#   bridge start       start the service
#   bridge stop        stop it (frees the serial port for a lab test or a flash)
#   bridge restart     stop, then start
#   bridge status      service state, serial port and the last log lines
#   bridge log         follow the log (Ctrl+C stops the tail, not the bridge)
#   bridge log -t      same, with timestamps (-nt: without); also works with status
#   bridge compile     compile the Nano firmware with arduino-cli (no upload)
#   bridge flash       stop the bridge, compile and upload to the Nano, start the bridge
#   bridge install     install the udev rule and the systemd unit, enable at boot (uses sudo)
#   bridge uninstall   stop, disable and remove both
#
# Settings: .bridgerc in the repo root (see .bridgerc.example): SERIAL_PORT, BROKER,
# BRIDGE_ARGS, TIMESTAMPS. The service reads the same file.
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)"
HERE="$ROOT/scripts/linux"
UNIT=lcos-bridge
UNIT_DST=/etc/systemd/system/$UNIT.service
RULE_DST=/etc/udev/rules.d/99-lcos-nano.rules
RC="$ROOT/.bridgerc"
FQBN=arduino:avr:nano

# pref NAME DEFAULT: value of NAME from .bridgerc, else DEFAULT.
pref() {
  local name=$1 default=$2 line value
  if [[ -f $RC ]]; then
    line=$(grep -E "^[[:space:]]*${name}[[:space:]]*=" "$RC" | tail -n 1 || true)
    if [[ -n $line ]]; then
      value=${line#*=}
      value=${value%%#*}
      value=$(printf '%s' "$value" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e "s/^[\"']//" -e "s/[\"']\$//")
      printf '%s' "$value"
      return
    fi
  fi
  printf '%s' "$default"
}

SERIAL_PORT=$(pref SERIAL_PORT /dev/lcos-nano)

CMD=${1:-status}
shift || true

TS=$(pref TIMESTAMPS 0)
[[ $TS =~ ^(1|true|yes|on)$ ]] && TS=1 || TS=0
for a in "$@"; do
  case $a in
    -t|--timestamps) TS=1 ;;
    -nt|--no-timestamps) TS=0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done
OUT="cat"
[[ $TS == 1 ]] && OUT=short-iso

need_unit() {
  if [[ ! -f $UNIT_DST ]]; then
    echo "service not installed; run: $0 install" >&2
    exit 1
  fi
}

status() {
  if [[ -f $UNIT_DST ]]; then
    echo "bridge: $(systemctl is-active $UNIT || true) (boot: $(systemctl is-enabled $UNIT 2>/dev/null || true))"
    local pid
    pid=$(systemctl show -p MainPID --value $UNIT)
    [[ $pid != 0 ]] && echo "  pid $pid since $(systemctl show -p ActiveEnterTimestamp --value $UNIT)"
  else
    echo "bridge: service not installed"
  fi
  if [[ -e $SERIAL_PORT ]]; then
    echo "port $SERIAL_PORT -> $(readlink -f "$SERIAL_PORT")"
  else
    echo "port $SERIAL_PORT: missing (is the Nano plugged in?)"
  fi
  local others
  others=$(pgrep -af 'serial_to_mqtt\.py' | grep -v "^$(systemctl show -p MainPID --value $UNIT 2>/dev/null || echo x) " || true)
  [[ -n $others ]] && printf '  other bridge processes (not the service):\n%s\n' "$others"
  if [[ -f $UNIT_DST ]]; then
    echo "--- last 10 log lines"
    journalctl -u $UNIT -n 10 --no-pager -o $OUT
  fi
}

arduino_cli() {
  local cli
  cli=$(command -v arduino-cli || true)
  [[ -z $cli && -x $HOME/.local/bin/arduino-cli ]] && cli=$HOME/.local/bin/arduino-cli
  if [[ -z $cli ]]; then
    echo "arduino-cli not found; see docs/serial_mqtt_linux.md" >&2
    exit 1
  fi
  "$cli" "$@"
}

# The sketch folder must be named after the .ino (lcos-bridge); build from a copy if not.
sketch_dir() {
  if [[ $(basename "$ROOT") == lcos-bridge ]]; then
    printf '%s' "$ROOT"
    return
  fi
  local tmp
  tmp=$(mktemp -d)/lcos-bridge
  mkdir -p "$tmp"
  cp "$ROOT"/*.ino "$ROOT"/*.cpp "$ROOT"/*.h "$tmp"/
  ln -s "$ROOT/lcos" "$tmp/lcos"
  printf '%s' "$tmp"
}

# compile [arduino-cli compile args...]: build into $BUILD (kept for upload).
BUILD="${XDG_CACHE_HOME:-$HOME/.cache}/lcos-bridge-build"
compile() {
  local dir
  dir=$(sketch_dir)
  mkdir -p "$BUILD"
  arduino_cli compile --no-color -b $FQBN --output-dir "$BUILD" \
    --library "$ROOT/lcos" --library "$ROOT/lcos/nRF24-master" --library "$ROOT/lcos/nRF24Network-master" \
    "$dir"
}

flash() {
  compile   # a failed build stops here, with the bridge still running
  local port
  port=$(readlink -f "$SERIAL_PORT")
  if [[ ! -e $port ]]; then
    echo "port $SERIAL_PORT missing; is the Nano plugged in?" >&2
    exit 1
  fi
  local was_active=0
  if [[ -f $UNIT_DST ]] && systemctl is-active -q $UNIT; then
    was_active=1
    sudo systemctl stop $UNIT
  fi
  local rc=0
  arduino_cli upload --no-color -b $FQBN -p "$port" --input-dir "$BUILD" || rc=$?
  if [[ $was_active == 1 ]]; then sudo systemctl start $UNIT; fi
  if [[ $rc == 0 ]]; then echo FLASH_OK; else echo FLASH_FAIL; fi
  return $rc
}

install_unit() {
  local user
  user=$(id -un)
  sudo install -m 0644 "$HERE/99-lcos-nano.rules" "$RULE_DST"
  sudo udevadm control --reload-rules
  sudo udevadm trigger --subsystem-match=tty
  sed -e "s#@REPO@#$ROOT#g" -e "s#@USER@#$user#g" "$HERE/lcos-bridge.service" | sudo tee "$UNIT_DST" >/dev/null
  sudo systemctl daemon-reload
  sudo systemctl enable $UNIT
  echo "installed $UNIT_DST and $RULE_DST (enabled at boot; not started: run '$0 start')"
}

uninstall_unit() {
  sudo systemctl disable --now $UNIT 2>/dev/null || true
  sudo rm -f "$UNIT_DST" "$RULE_DST"
  sudo systemctl daemon-reload
  sudo udevadm control --reload-rules
  echo "removed $UNIT"
}

case $CMD in
  start)     need_unit; sudo systemctl start $UNIT; sleep 3; status ;;
  stop)      need_unit; sudo systemctl stop $UNIT; status ;;
  restart)   need_unit; sudo systemctl restart $UNIT; sleep 3; status ;;
  status)    status ;;
  log|tail)  need_unit; echo "following the $UNIT log (Ctrl+C stops the tail; the bridge keeps running)"; journalctl -u $UNIT -f -n 50 -o $OUT ;;
  compile)   compile ;;
  flash)     flash ;;
  install)   install_unit ;;
  uninstall) uninstall_unit ;;
  -h|--help|help) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//' ;;
  *)         echo "unknown command: $CMD (try: $0 help)" >&2; exit 2 ;;
esac
