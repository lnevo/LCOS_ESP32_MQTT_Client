# Archived: HBLOOP-era monitoring + manual RESUBSCRIBE notes

This tree was reverted to **pre-heartbeat** sync (`4255f74` baseline) for plant
event-125 and the Python agent, while **keeping Digicon signalhead / sml_mode**.

## Why

HBLOOP / continuous distributor monitoring introduced extra event-125 traffic and
auto-`RESUBSCRIBE` loops that fouled MASTER. Pre-HBLOOP behavior:

- Nano `setup()` plant subscribe once per DTR reset (nodes `0,1,2,3,4,12,13`)
- Host sync-watch: USB `PING`, ACK-miss reopen, thin-accept grace RESUBSCRIBE
- **No** Block-7 beat, **no** self-sub, **no** HBLOOP miss spiral

## Manual RESUBSCRIBE (kept on live agent)

| MQTT `track/bridge/cmd` | Effect |
|-------------------------|--------|
| `RESUBSCRIBE` | Re-emit event 125 (no cooldown on this MQTT path) |
| `RESUBSCRIBE FORCE` | Same as `RESUBSCRIBE` (alias) |
| `REOPEN` | Reopen COM (Nano `setup()` will enroll again) |
| `PING` | USB-only ping |

Serial text `RESUBSCRIBE` on the Nano still works (firmware).

## Snapshots in this folder

| File | Contents |
|------|----------|
| `serial_to_mqtt_hbloop_era.py` | Agent as of last HBLOOP/monitor build |
| `lcos_mqtt_bridge_hbloop_era.cpp` | Firmware with HBLOOP beat / echo hooks |

Do **not** deploy those snapshots unless deliberately re-testing HBLOOP.
