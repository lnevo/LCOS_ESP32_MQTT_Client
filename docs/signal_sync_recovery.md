# Bridge sync recovery (USB + LCOS radio)

HBLOOP detects MASTER/distributor loss; **one** auto-`RESUBSCRIBE` on lost, then manual.

## Agent restart vs MASTER reboot

| Event | What should happen |
|-------|--------------------|
| **Agent restart** | Open COM **without** DTR reset so Nano does not re-run `setup()` event-125. Prior plant subscriptions stay on MASTER. |
| **MASTER reboot** | HBLOOP `miss (1/3)` … `lost` → **one auto RESUBSCRIBE**. If echo still missing, monitor disarms — publish MQTT `RESUBSCRIBE` when MASTER is ready. |
| **Intentional Nano reset** | MQTT `REOPEN` (or unplug) pulses DTR → `setup()` plant+self enroll again. |

Plant event-125 targets nodes **`1,2,3,4,12,13`** plus **self (015)** once for HBLOOP echo — never MASTER (`0`).

## HBLOOP

Every ~5s the agent sends serial `HBLOOP`. Firmware broadcasts Block-7 from node 015; if MASTER still redistributes to our self-subscription, Nano prints `HBLOOP ECHO`.

| Log | Meaning |
|-----|---------|
| `sync: HBLOOP established` | First echo after start |
| `sync: HBLOOP miss (1/3) - no ECHO/1507 within 5s` | First miss (often MASTER reboot) |
| `sync: HBLOOP lost (hbloop-miss-3)` | Three misses after established |
| `sync: HBLOOP lost - auto RESUBSCRIBE once` | One automatic enroll retry |
| `…did not re-establish after auto-RESUBSCRIBE` | Disarmed — wait for manual MQTT `RESUBSCRIBE` |
| `sync: HBLOOP recovered` | Echo returned after lost / auto-RESUB |

Ghost Digicon topic `track/sensor/<display*100+7>` is never published. Self node OCT is
announced by firmware as `HBLOOP_SELF <oct>` (from `thisNode` / `getNodeID()`); the agent
uses that to quiet self `Subscription accepted` lines (fallback `15` until learned).

## Failure modes

| Symptom | Likely layer | What broke |
|---------|--------------|------------|
| Turnout cmd, no `ACK …` on serial | USB | COM stolen, Nano reset mid-handle, dead pyserial handle |
| `ACK` OK, no `track/turnout` / `track/sensor` updates | Radio | MASTER dropped Nano’s event-125 subscriptions |
| HBLOOP miss / lost | Radio | Distributor down (MASTER reboot) — auto once, then manual |

## Host recovery (`serial_to_mqtt.py`, `--sync-watch` default on)

1. Periodic USB **`PING`** (~12s). Missed `ACK PING` → reopen streak.
2. Turnout **ACK miss** streak (≥3) → **reopen COM** (DTR) + **`RESUBSCRIBE`**.
3. **SerialException** → reopen COM (DTR re-runs Nano `setup()` plant enroll).
4. After Nano boot (DTR path only): wait for plant accepts; **thin accept** after grace → one **`RESUBSCRIBE`**.
5. Manual MQTT `track/bridge/cmd`:
   - **`RESUBSCRIBE`** — only if HBLOOP is **not** established (no cooldown)
   - **`RESUBSCRIBE FORCE`** — always (no cooldown), even while healthy
   - **`REOPEN`** / **`PING`** / **`HBLOOP`**
6. HBLOOP: miss → lost → **one** auto-`RESUBSCRIBE`; if no re-establish, disarm for manual.

## Firmware

`RESUBSCRIBE`, plant+self event-125, and `HBLOOP` Block-7 beat live in `lcos_mqtt_bridge.cpp`.
Flash the Nano after pulling this branch.
