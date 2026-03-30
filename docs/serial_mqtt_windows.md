# Serial ↔ MQTT bridge on Windows

The script `serial_to_mqtt.py` relays MQTT-formatted lines between the Arduino COM port and your MQTT broker (for JMRI and testing). This page covers installing Python and dependencies on Windows.

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

Optional isolated environment:

```bat
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If you use a venv, run `serial_to_mqtt.py` from an activated shell, or call `.venv\Scripts\python.exe serial_to_mqtt.py`.

## 3. Run the bridge

Edit COM port and broker in `run_serial_mqtt.cmd` if needed, then:

```bat
run_serial_mqtt.cmd
```

Verbose MQTT publishes:

```bat
run_serial_mqtt.cmd verbose
```

Other launchers: `run_serial_mqtt_debug.cmd`, `run_serial_mqtt_heartbeat.cmd`. You can pass extra arguments through to the script (e.g. `--com COM5`).

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

## Linux / macOS later

Use the same `requirements.txt` with `python3 -m pip install -r requirements.txt`; the `.cmd` launchers are Windows-only—run `python3 serial_to_mqtt.py` with the right `--com` or `/dev/tty*` device path.
