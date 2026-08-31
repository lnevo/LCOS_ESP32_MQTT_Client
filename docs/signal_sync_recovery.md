# Bridge sync recovery (USB + LCOS radio)

Pre-heartbeat baseline. Signalhead / Digicon `sml_mode` unchanged.

## Agent restart vs MASTER reboot

| Event | What should happen |
|-------|--------------------|
| **Agent restart** | Open COM **without** DTR reset so Nano does not re-run `setup()` event-125. Prior plant subscriptions stay on MASTER. |
| **MASTER reboot** | Distributor empty → MQTT `track/bridge/cmd` **`RESUBSCRIBE`** (no cooldown). Do not restart the agent. |
| **Intentional Nano reset** | MQTT `REOPEN` (or unplug) pulses DTR → `setup()` plant enroll again. |

Plant event-125 targets nodes **`1,2,3,4,12,13` only** — never MASTER (`0`). Re-subscribing to node 0 fouls a healthy MASTER (turnout ACK works; sensors/status silent).

## Failure modes

| Symptom | Likely layer | What broke |
|---------|--------------|------------|
| Turnout cmd, no `ACK …` on serial | USB | COM stolen, Nano reset mid-handle, dead pyserial handle |
| `ACK` OK, no `track/turnout` / `track/sensor` updates | Radio | MASTER dropped Nano’s event-125 subscriptions (or poisoned by node-0 / re-enroll storm) |
| Opening COM while bridge runs | USB | Exclusive COM + Arduino DTR reset; bridge handle dies |

## Host recovery (`serial_to_mqtt.py`, `--sync-watch` default on)

1. Periodic USB **`PING`** (~12s). Missed `ACK PING` → reopen streak.
2. Turnout **ACK miss** streak (≥3) → **reopen COM** (DTR) + **`RESUBSCRIBE`**.
3. **SerialException** → reopen COM (DTR re-runs Nano `setup()` plant enroll).
4. After Nano boot (DTR path only): wait for plant accepts; **thin accept** after grace → one **`RESUBSCRIBE`**.
5. Manual MQTT `track/bridge/cmd`: **`RESUBSCRIBE`** (no cooldown; **`RESUBSCRIBE FORCE`**
   is the same alias) / **`REOPEN`** / **`PING`**.

There is **no** HBLOOP / Block-7 distributor heartbeat in this build. Archived HBLOOP
agent/firmware: [`docs/archive/`](archive/manual_resubscribe_hbloop_era.md).

## Firmware

`RESUBSCRIBE` and plant event-125 (`1,2,3,4,12,13`) live in `lcos_mqtt_bridge.cpp`.
Flash the Nano after pulling this branch.
