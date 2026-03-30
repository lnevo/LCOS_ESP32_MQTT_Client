# Serial ↔ MQTT bridge on Windows

The script `serial_to_mqtt.py` relays MQTT-formatted lines between the **Arduino Nano** USB serial port (COM) and your MQTT broker (for JMRI and testing). The repository name still mentions ESP32 for historical reasons; this bridge is documented for a **Nano**. This page covers installing Python and dependencies on Windows.

## 1. Install Python 3

1. Download the current **Python 3** installer from [https://www.python.org/downloads/windows/](https://www.python.org/downloads/windows/).
2. Run the installer. Enable **“Add python.exe to PATH”** (or use the **py** launcher and adjust commands below).
3. Open a new **Command Prompt** or **PowerShell** and verify:

   ```bat
   python --version
   ```

   If `python` is not found, try `py -3 --version`.

## 2. Install dependencies

From the folder that contains `serial_to_mqtt.py` (repository root):

```bat
cd path\to\LCOS_ESP32_MQTT_Client
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

That installs **pyserial** and **paho-mqtt** (see `requirements.txt`).

**Recommended:** use a **virtual environment** in the repo root (matches `pyproject.toml` / Pyright so **Cursor** and **VS Code** stop flagging `import serial` / `paho.mqtt`):

```bat
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Run `serial_to_mqtt.py` from that activated shell, or call `.venv\Scripts\python.exe serial_to_mqtt.py`.

**Cursor / VS Code:** after the venv exists and packages are installed, open the Command Palette and choose **Python: Select Interpreter** → pick **`.venv\Scripts\python.exe`** (this folder). Pyright reads `pyproject.toml` and uses the `.venv` under the repo root for analysis.

## 3. Run the bridge

Edit COM port and broker in `run_serial_mqtt.cmd` if needed, then:

```bat
run_serial_mqtt.cmd
```

Verbose MQTT publishes:

```bat
run_serial_mqtt.cmd verbose
```

Debug (Arduino `DBG` lines on the console) and serial heartbeat mode:

```bat
run_serial_mqtt.cmd debug
run_serial_mqtt.cmd heartbeat
```

Launcher help (`-h`, `-?`, `/h`, `/?`, `help`):

```bat
run_serial_mqtt.cmd -h
```

Any other tokens are passed through to Python (e.g. `--com COM5 --broker 10.0.0.1`).

Direct invocation:

```bat
python serial_to_mqtt.py --com COM3 --broker 192.168.137.1
python serial_to_mqtt.py --help
```

## 4. Quick MQTT test (heartbeat)

With the bridge running, publish payload `PING` to topic `track/bridge/heartbeat` (e.g. with Mosquitto on another machine):

```bat
mosquitto_pub -h <broker_host> -p 1883 -t track/bridge/heartbeat -m PING
```

Use the same host/port as `--broker` / `--mqtt-port` on the script.

## Linux / macOS

See **[serial_mqtt_linux.md](serial_mqtt_linux.md)** (`run_serial_mqtt.sh`, `dialout`, `/dev/ttyUSB0`, etc.).
