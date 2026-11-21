# Serial ↔ MQTT bridge on Linux

The script `serial_to_mqtt.py` relays MQTT-formatted lines between the **Arduino Nano** (USB serial, usually `/dev/ttyUSB*` or `/dev/ttyACM*`) and your MQTT broker. See also **[serial_mqtt_windows.md](serial_mqtt_windows.md)** for Windows.

## 1. Python 3

Install Python 3 and `pip` from your distribution (package names vary):

- **Debian / Ubuntu:** `sudo apt update && sudo apt install python3 python3-pip python3-venv`
- **Fedora:** `sudo dnf install python3 python3-pip`

Check:

```bash
python3 --version
```

## 2. Dependencies and venv

From the repository root:

```bash
cd /path/to/LCOS_ESP32_MQTT_Client
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Using a **`.venv` in the repo root** matches **`pyproject.toml`** so Pyright/Pylance resolves `serial` and `paho.mqtt`. In Cursor or VS Code: **Python: Select Interpreter** → `.venv/bin/python3`.

## 3. Serial device

Plug in the Nano and find the device node:

```bash
ls -l /dev/serial/by-id/
# or
dmesg | tail
```

Common paths: `/dev/ttyUSB0`, `/dev/ttyACM0`. Your user must be allowed to open it:

- **Quick test:** `sudo ./run_serial_mqtt.sh` (not ideal long-term).
- **Permanent:** add your user to the `dialout` group (Debian/Ubuntu: `sudo usermod -aG dialout "$USER"`, then log out and back in).

## 4. Run the bridge

Make the launcher executable once:

```bash
chmod +x run_serial_mqtt.sh
```

Default serial port and broker match the Windows launchers; override with environment variables:

```bash
export SERIAL_PORT=/dev/ttyACM0
export BROKER=192.168.137.1
./run_serial_mqtt.sh
```

Verbose MQTT publishes:

```bash
./run_serial_mqtt.sh -v
# or (legacy word-style)
./run_serial_mqtt.sh verbose
# or
SERIAL_VERBOSE=1 ./run_serial_mqtt.sh
```

Debug (`-d`) and serial heartbeat (`-hb`):

```bash
./run_serial_mqtt.sh -d
./run_serial_mqtt.sh -hb
./run_serial_mqtt.sh -v -d -hb
```

Launcher help: `./run_serial_mqtt.sh -h` (also `-?`, `--help`).

Extra arguments are passed through to `serial_to_mqtt.py`:

```bash
./run_serial_mqtt.sh -- --mqtt-port 1883 --debug
```

Direct invocation (with venv activated):

```bash
python3 serial_to_mqtt.py --com /dev/ttyUSB0 --broker 192.168.137.1
python3 serial_to_mqtt.py --help
```

## 5. MQTT heartbeat test

With the bridge running:

```bash
mosquitto_pub -h <broker_host> -p 1883 -t track/bridge/heartbeat -m PING
```

Use the same host/port as `--broker` / `--mqtt-port` on the script.

## 6. Run it as a service (layout Pi)

On a host that runs the bridge all the time, use the systemd service instead of a terminal. Clone the repo into a folder named `lcos-bridge` (the sketch folder must match `lcos-bridge.ino`), then:

```bash
sudo apt install python3-serial python3-paho-mqtt
./bridge install      # udev rule /dev/lcos-nano + lcos-bridge.service, enabled at boot (sudo)
./bridge start
./bridge status       # state, port, last log lines
./bridge log          # follow the log; Ctrl+C stops the tail only (-t adds timestamps)
./bridge stop | restart | uninstall
```

`./bridge` links to `scripts/linux/bridge.sh`. The service runs `serial_to_mqtt.py --com $SERIAL_PORT --broker $BROKER $BRIDGE_ARGS` as your user, restarts it 10 s after any exit (Nano unplugged, USB drop), and logs to the journal (`journalctl -u lcos-bridge`). Defaults: `/dev/lcos-nano`, `127.0.0.1` (Mosquitto on the same host), `--verbose`; override them in `.bridgerc` (see `.bridgerc.example`).

`/dev/lcos-nano` is a udev symlink to the first CH340 (USB id `1a86:7523`). CH340 chips have no serial number; if a second one is ever plugged into the same host, pin the rule to a USB port (see the comment in `scripts/linux/99-lcos-nano.rules`).

For a lab test that needs the port: `./bridge stop`, run the test, `./bridge start`.

## 7. Flash the Nano from Linux (no Arduino IDE)

Install `arduino-cli` and the AVR core once. Pick the build that matches the **userland**, not the kernel: Raspberry Pi OS 32-bit (`dpkg --print-architecture` says `armhf`) needs the ARMv7 build even on a 64-bit kernel, or the AVR compiler it downloads will not start (`required file not found`).

```bash
mkdir -p ~/.local/bin
curl -fsSL -o /tmp/acli.tgz https://downloads.arduino.cc/arduino-cli/arduino-cli_latest_Linux_ARMv7.tar.gz   # armhf; use _ARM64 / _64bit to match
tar -xzf /tmp/acli.tgz -C ~/.local/bin arduino-cli
~/.local/bin/arduino-cli core update-index
~/.local/bin/arduino-cli core install arduino:avr
```

Then:

```bash
./bridge compile   # arduino:avr:nano with the vendored lcos/ RF24 libraries; no upload
./bridge flash     # compile, stop the bridge, upload to /dev/lcos-nano, start the bridge
```

## macOS

Same flow: use `python3`, **`source .venv/bin/activate`**, and a device path such as `/dev/tty.usbserial-*` or `/dev/cu.usbserial-*` for `--com` / `SERIAL_PORT`.
