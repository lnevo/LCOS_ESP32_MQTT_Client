# Bridge sync recovery (USB + LCOS radio)

Pre-heartbeat baseline (post-HBLOOP revert). Signalhead / Digicon `sml_mode` unchanged.

## Failure modes

| Symptom | Likely layer | What broke |
|---------|--------------|------------|
| Turnout cmd, no `ACK …` on serial | USB | COM stolen, Nano reset mid-handle, dead pyserial handle |
| `ACK` OK, no `track/turnout` / `track/sensor` updates | Radio | MASTER dropped Nano’s event-125 subscriptions |
| Opening COM while bridge runs | USB | Exclusive COM + Arduino DTR reset; bridge handle dies |

## Host recovery (`serial_to_mqtt.py`, `--sync-watch` default on)

1. Periodic USB **`PING`** (~12s). Missed `ACK PING` → reopen streak.
2. Turnout **ACK miss** streak (≥3) → **reopen COM** + **`RESUBSCRIBE`**.
3. **SerialException** → reopen COM (DTR re-runs Nano `setup()` plant enroll).
4. After Nano boot: wait for plant accepts; **thin accept** after grace → one **`RESUBSCRIBE`**
   (setup already enrolled — avoid immediate double-send).
5. Manual MQTT `track/bridge/cmd`: **`RESUBSCRIBE`** / **`RESUBSCRIBE FORCE`** / **`REOPEN`** / **`PING`**.

There is **no** HBLOOP / Block-7 distributor heartbeat in this build. Archived HBLOOP
agent/firmware: [`docs/archive/`](archive/manual_resubscribe_hbloop_era.md).

## Firmware

`RESUBSCRIBE` and plant event-125 (`0,1,2,3,4,12,13`) live in `lcos_mqtt_bridge.cpp`.
Flash the Nano after pulling this branch.
