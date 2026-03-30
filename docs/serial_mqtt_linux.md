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

## macOS

Same flow: use `python3`, **`source .venv/bin/activate`**, and a device path such as `/dev/tty.usbserial-*` or `/dev/cu.usbserial-*` for `--com` / `SERIAL_PORT`.
