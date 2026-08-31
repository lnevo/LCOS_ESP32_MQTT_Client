# LCOS JMRI / MQTT bridge (Arduino Nano)

Host + firmware bridge between an **LCOS radio network** (Beagle Bay) and **JMRI** over **MQTT**.

Hardware target is an **Arduino Nano + nRF24**. The repo folder name still says `ESP32` for history only.

This stack is **not HART-specific**. It uses standard LCOS packing and JMRI-style `track/…` MQTT topics. You configure **your** radio node addresses, COM port, and broker. Optional Digicon/SML hand-off lives in a separate JMRI Jython script (see below).

## What you get

```text
JMRI  ←→  MQTT broker  ←→  serial_to_mqtt.py  ←→  USB serial  ←→  Nano (LCOS node)
                                                                      ↕ nRF24
                                                                   field nodes
```

| Piece | Role |
|-------|------|
| **`LCOS_ESP32_MQTT_Client.ino`** + **`lcos_mqtt_bridge.*`** + **`mqtt_serial.*`** | Nano firmware: event-125 subscriptions, LCOS ↔ MQTT text lines |
| **`serial_to_mqtt.py`** | PC: USB serial ↔ broker; sync-watch; optional signalhead forward; SML mode guard |
| **MQTT broker** | Shared bus (Mosquitto, etc.) that JMRI also uses |

## Prerequisites

1. Working **LCOS** layout (MASTER / distributor, RF24 channel, node addresses).
2. **MQTT broker** reachable from the PC that runs the Python bridge and from JMRI.
3. JMRI with **MQTT** connection (turnouts / sensors / signal masts as you prefer).
4. Arduino IDE or **arduino-cli**, with **LCOS**, **RF24**, **RF24Network** libraries installed.
5. Python 3 + `requirements.txt` (`pyserial`, `paho-mqtt`).

Authoritative LCOS protocol: **`lcos/lcos.h`**, **`reference/LCOS_Client_Bare.ino`**, and Beagle Bay’s Public API — not this README.

## Address packing (required convention)

```text
packed = displayNode * 100 + UID
```

| Object | UID range (typical) | Example |
|--------|---------------------|---------|
| Turnout | 8–15 | Node `1`, turnout 0 → **`100`** |
| Signal | 32–47 | Node `4`, signal 0 → **`432`** |
| Relay / control | 51+ | Layout-specific |

`displayNode` must be **octal-legal** as a decimal digit string (LCOS RF24 address mapping). JMRI MQTT system names usually look like `MT100`, `MS…`, Virtual heads `IH432` with MQTT leaf **`432`** (no `IH` in the topic).

## 1. Configure and flash the Nano

Edit **`LCOS_ESP32_MQTT_Client.ino`**:

- `channel` — must match your LCOS RF channel  
- `thisNode` — this Nano’s LCOS node id (octal literal, e.g. `015`)

Edit **`lcos_mqtt_bridge.cpp`** — subscribe list for **your** display / field nodes:

```cpp
static const uint16_t kSubscribeDisplayNodes[] = { 1, 2, 3, 4, 12, 13 };
```

Replace with the JMRI-style **display** node numbers you need event-125 coverage for. After changing firmware, reflash (Windows helper: `scripts/windows/flash_nano.py` or your usual `flash_lcos.bat` / IDE upload).

On boot you should see library banner lines and `Subscription accepted - node: …` for each target (also after host `RESUBSCRIBE`).

## 2. Run the Python bridge

```bash
cd LCOS_ESP32_MQTT_Client
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -u serial_to_mqtt.py --com /dev/ttyUSB0 --broker 192.168.1.10 --verbose
# Windows example:
# python -u serial_to_mqtt.py --com COM3 --broker 192.168.1.10 --verbose
```

Or use **`run_serial_mqtt.cmd`** / **`run_serial_mqtt.sh`** (edit COM/broker defaults there).

| Flag / behavior | Meaning |
|-----------------|--------|
| `--com` / `--broker` / `--mqtt-port` | Serial + MQTT |
| `--verbose` | Log MQTT publishes and non-PING ACKs |
| `--signalhead` | Forward `track/signalhead/<packed>` → Nano (also on by default via `FORWARD_SIGNALHEAD_CMDS`) |
| `--no-sync-watch` | Disable USB PING / ACK-miss recovery |
| `--debug-heartbeat` | Extra USB-only `PING` interval (no turnout throws) |

**Sync-watch (default on):** quiet USB `PING` every ~12s; missed ACKs or turnout ACK failures reopen COM and/or send serial `RESUBSCRIBE`. Nano `setup()` already subscribes on reset — the host does **not** double-subscribe on every boot banner unless accepts look thin. **HBLOOP** (radio path): after established→lost, auto-`RESUBSCRIBE` in **1s**, then echo every **5s** / `RESUBSCRIBE` every **60s** until recovered — see **`docs/signal_sync_recovery.md`**.

**Host ops** (not retained): publish to `track/bridge/cmd`:

| Payload | Effect |
|---------|--------|
| `PING` | USB-only health (`ACK PING`) |
| `RESUBSCRIBE` | Re-emit event 125 (refused while HBLOOP established — use `RESUBSCRIBE FORCE`) |
| `RESUBSCRIBE FORCE` | Always re-emit event 125 |
| `REOPEN` | Reopen the serial port (DTR reset → Nano `setup()` enroll) |
| `HBLOOP` | One Block-7 distributor echo probe |

Presence: retained `track/bridge/status` = `online` / `offline`.

OS-specific install notes: **`docs/serial_mqtt_windows.md`**, **`docs/serial_mqtt_linux.md`**. Recovery detail: **`docs/signal_sync_recovery.md`**.

## 3. Wire JMRI MQTT

Point JMRI’s MQTT connection at the **same broker**. Typical topics this bridge uses:

| Direction | Topic pattern | Notes |
|-----------|---------------|--------|
| Field → JMRI | `track/turnout/<packed>` | Status |
| Field → JMRI | `track/sensor/<packed>` | Occupancy / inputs |
| Field → JMRI | `track/signalmast/<packed>` | Signal aspect report |
| JMRI → field | `track/cmd/turnout/<packed>` | Payload `THROWN` / `CLOSED` / `TOGGLE` / `GET` |
| JMRI → field | `track/signalhead/<packed>` | `Red` / `Yellow` / `Green` / `Dark` / `Unheld` / … |

Create MQTT beans whose system names match your packing. You do **not** need Digicon or any HART panel for basic turnout/sensor/signal MQTT.

## 4. Optional: Digicon / SML hand-off (Jython)

If you run a Digicon-style **Signal Mast Logic** CTC that should **SET** searchlights when SML is Enabled and **follow field** `signalmast` when Disabled, use a JMRI Jython companion (example in the HART layout repo: `jmri/scripts/mqtt_signalhead_publisher.py`). That script is **layout-specific** for:

- Virtual head list (`IH…` / packed IDs)  
- Digicon SML pair table  

It shares the portable topic **`track/bridge/sml_mode`** with `serial_to_mqtt.py` so a dead JMRI session can RELEASE field signals safely. Details: **`docs/signal_dual_path.md`**.

Without that script, the Nano + Python bridge still works for MQTT turnouts/sensors and optional `signalhead` commands.

## Quick validation

1. Bridge prints `Connected to MQTT broker…` and `track/bridge/status` → `online`.  
2. `mosquitto_pub -h <broker> -t track/bridge/cmd -m PING` → Nano/`ACK PING` (quiet in the bridge log unless a miss).  
3. Throw or `GET` a known turnout:  
   `mosquitto_pub -h <broker> -t track/cmd/turnout/<packed> -m GET`  
   Expect serial `ACK …` and later `track/turnout/<packed> …` if radio subscriptions are healthy.  
4. If ACKs work but status is silent: `track/bridge/cmd` → `RESUBSCRIBE`, confirm `Subscription accepted` lines, recheck node list / MASTER.

## Repository map

| Path | Purpose |
|------|---------|
| `LCOS_ESP32_MQTT_Client.ino` | Sketch entry (`channel`, `thisNode`) |
| `lcos_mqtt_bridge.cpp` / `.h` | Serial text, subscriptions, `RESUBSCRIBE` / `PING` |
| `mqtt_serial.cpp` / `.h` | LCOS events → `track/…` lines |
| `serial_to_mqtt.py` | Host bridge |
| `lcos/` | Vendor LCOS library (do not “fix” casually) |
| `reference/` | Upstream bare-client patterns |
| `docs/` | OS setup, dual-path signals, sync recovery |
| `scripts/windows/` | Lab helpers (flash, smoke, restart) |
| `tests/` | Unit tests for sync-watch / SML guard |

## License / copyright

LCOS under **`lcos/`** is **Copyright 2022–26 Beagle Bay Inc.** (see `lcos.h`). Other project files follow your repo licensing.
