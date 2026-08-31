# Bridge sync recovery (USB + LCOS radio)

HBLOOP detects MASTER/distributor loss with **traffic-gated** probes and paced auto-`RESUBSCRIBE`.

## Agent restart vs MASTER reboot

| Event | What should happen |
|-------|--------------------|
| **Agent restart** | Open COM **without** DTR reset so Nano does not re-run `setup()` event-125. Prior plant subscriptions stay on MASTER. |
| **MASTER reboot** | First HBLOOP miss → wait **1s** → auto `RESUBSCRIBE`. Retry every **60s** until echo or sensor/signal* feedback returns. |
| **Intentional Nano reset** | MQTT `REOPEN` (or unplug) pulses DTR → `setup()` plant+self enroll again. |

Plant event-125 targets nodes **`1,2,3,4,12,13`** plus **self (015)** once for HBLOOP echo — never MASTER (`0`).

## HBLOOP

Every ~5s the agent may send serial `HBLOOP` **only if** no fresh `track/sensor/*` or `track/signal*` feedback arrived in that window (layout traffic proves the distributor).

Firmware broadcasts Block-7 from node 015; if MASTER redistributes it, Nano prints `HBLOOP ECHO`.

| Log | Meaning |
|-----|---------|
| `sync: HBLOOP established` | First echo (or layout feedback) |
| `sync: HBLOOP miss (1/1)` | Probe got no echo within 5s |
| `sync: HBLOOP lost - auto RESUBSCRIBE in 1s` | First recovery attempt scheduled |
| `sync: HBLOOP recovery RESUBSCRIBE (hbloop-retry-60s)` | Still down — retry enroll |
| `sync: HBLOOP recovered` | Echo or sensor/signal* feedback returned |

Ghost Digicon topic `track/sensor/<display*100+7>` is never published. Self node OCT is
announced by firmware as `HBLOOP_SELF <oct>` (from `thisNode` / `getNodeID()`).

## Failure modes

| Symptom | Likely layer | What broke |
|---------|--------------|------------|
| Turnout cmd, no `ACK …` on serial | USB | COM stolen, Nano reset mid-handle, dead pyserial handle |
| `ACK` OK, no `track/turnout` / `track/sensor` updates | Radio | MASTER dropped Nano’s event-125 subscriptions |
| HBLOOP miss / lost | Radio | Distributor down — auto resub (1s), then every 60s |

## Host recovery (`serial_to_mqtt.py`, `--sync-watch` default on)

1. Periodic USB **`PING`** (~12s). Missed `ACK PING` → reopen streak.
2. Turnout **ACK miss** streak (≥3) → **reopen COM** (DTR) + **`RESUBSCRIBE`**.
3. **SerialException** → reopen COM (DTR re-runs Nano `setup()` plant enroll).
4. After Nano boot (DTR path only): wait for plant accepts; **thin accept** after grace → one **`RESUBSCRIBE`**.
5. Manual MQTT `track/bridge/cmd`:
   - **`RESUBSCRIBE`** — only if HBLOOP is **not** established (no cooldown)
   - **`RESUBSCRIBE FORCE`** — always (no cooldown), even while healthy
   - **`REOPEN`** / **`PING`** / **`HBLOOP`**
6. HBLOOP: traffic-gated probe; miss → 1s → RESUBSCRIBE; retry every 60s until recovered.

## Firmware

`RESUBSCRIBE`, plant+self event-125, and `HBLOOP` Block-7 beat live in `lcos_mqtt_bridge.cpp`.
Flash the Nano after pulling this branch.
