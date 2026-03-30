# LCOS_ESP32_MQTT_Client

JMRI-oriented **MQTT bridge** for an **Arduino Nano** running LCOS: the sketch prints MQTT-style lines on USB serial; **`serial_to_mqtt.py`** forwards between the COM port and an MQTT broker. The repository folder name still mentions ESP32 for history; the current target is a **Nano**.

## Authoritative LCOS material (read these first)

| Source | Role |
|--------|------|
| **`lcos/lcos.h`**, **`lcos/lcos.cpp`** | Beagle Bay LCOS Integration Library — events, `DATAGRAM`, `sendShortMessage`, `ALIGN_*`, `SIGNAL_*`, UID offsets, subscription masks, etc. |
| **`reference/LCOS_Client_Bare.ino`** | Bare client reference (v1.10 style): subscriptions to the event distributor (event `125`), serial gateway usage, `layout->update()`. |

**This README is project scaffolding only.** It is **not** vendor LCOS documentation. Do not infer protocol details here; use the headers and reference sketch above.

## Repository layout (bridge and host)

- **`LCOS_ESP32_MQTT_Client.ino`** — Main sketch (align subscription/setup with the reference sketch as noted in `lcos_mqtt_bridge.h`).
- **`lcos_mqtt_bridge.cpp` / `.h`** — Event 125 subscriptions, serial line handling (e.g. heartbeat `PING`), coordination with `gateways.h`.
- **`mqtt_serial.cpp` / `.h`** — LCOS operations events → one MQTT line per publish: `topic payload\n` for JMRI-style topics under `track/`.
- **`serial_to_mqtt.py`** — Host bridge: serial ↔ MQTT; optional debug heartbeat; subscribes to `track/bridge/heartbeat` for `PING` relay.
- **`docs/serial_mqtt_windows.md`** — Windows: Python, venv, COM port, **`run_serial_mqtt.cmd`** (word options `verbose`, `debug`, `heartbeat`; help `-h` / `/?`).
- **`docs/serial_mqtt_linux.md`** — Linux/macOS: venv, `dialout`, **`run_serial_mqtt.sh`** (`-h`, `-v`, `-d`, `-hb`).
- **`docs/jmri_host_protocol_plan.md`** (on feature branches if present) — Planning notes for future host commands.

### Bridge-only symbols

**`lcos_mqtt_bridge.h`** defines optional aliases **`LCOS_CMD_*`** for command-request bytes used in **`sendShortMessage`** turnout/signal CMD traffic (e.g. `0x02` set-without-lock). Those **names are not in** stock **`lcos.h`**; the **numeric values** came from Beagle Bay LCOS operating practice / maintainer guidance — use **`lcos.h`** for everything else.

### MQTT / Python quick links

- Install: **`requirements.txt`**; setup: **`docs/serial_mqtt_windows.md`** or **`docs/serial_mqtt_linux.md`**.
- IDE (Pylance): **`pyproject.toml`** points Pyright at a local **`.venv`**.

### Hardware

- **This project:** Nano + nRF24 as an LCOS node; USB serial to the PC running the Python script.
- **LCOS generally:** See **`lcos/`** and RF24 / RF24Network dependencies (Arduino Library Manager).

### License / copyright

LCOS library files under **`lcos/`** are **Copyright 2022–26 Beagle Bay Inc.** per **`lcos.h`**. Other repo files follow your project licensing.
