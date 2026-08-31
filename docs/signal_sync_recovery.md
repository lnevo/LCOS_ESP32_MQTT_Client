# Bridge sync recovery (USB + LCOS radio)

HBLOOP watches the radio path to MASTER (often via a **DCC node**). Layout power-off can
drop that path without clearing MASTER’s subscription RAM — so we **keep echoing** and only
`RESUBSCRIBE` if the path stays dead.

## Agent restart vs MASTER reboot vs layout power

| Event | What should happen |
|-------|--------------------|
| **Agent restart** | Open COM **without** DTR reset so Nano does not re-run `setup()` event-125. Prior plant subscriptions stay on MASTER. |
| **Layout / DCC off** | HBLOOP **lost**; quiet echo probes continue; **RESUBSCRIBE disarmed** for **60s**. If path returns → **recovered** (no re-enroll). |
| **MASTER reboot** | Echo stays dead after path is up → after **60s** a failed echo → **miss** + auto `RESUBSCRIBE`. Retry every **60s** the same way until echo or layout feedback. |
| **Intentional Nano reset** | MQTT `REOPEN` (or unplug) pulses DTR → `setup()` plant+self enroll again. |

Plant event-125 targets nodes **`1,2,3,4,12,13`** plus **self (015)** once for HBLOOP echo — never MASTER (`0`).

## HBLOOP

Every ~5s the agent may send serial `HBLOOP` **only if** no fresh `track/sensor/*`,
`track/signal*`, or `track/turnout/*` feedback arrived in that window. Probe/ACK/ECHO
lines are quiet; lifecycle only:

| Log | Meaning |
|-----|---------|
| `sync: HBLOOP established` | First echo (or layout feedback) |
| `sync: HBLOOP lost - …` | Health dropped; echo continues; RESUBSCRIBE disarmed for 60s |
| `sync: HBLOOP miss - …; RESUBSCRIBE` | Still no echo after the disarm window (echo-gated enroll) |
| `sync: HBLOOP recovered` | Echo or layout feedback returned |

Ghost Digicon topic `track/sensor/<display*100+7>` is never published. Self node OCT is
announced by firmware as `HBLOOP_SELF <oct>` (from `thisNode` / `getNodeID()`).

## Failure modes

| Symptom | Likely layer | What broke |
|---------|--------------|------------|
| Turnout cmd, no `ACK …` on serial | USB | COM stolen, Nano reset mid-handle, dead pyserial handle |
| `ACK` OK, no `track/turnout` / `track/sensor` updates | Radio | MASTER dropped Nano’s event-125 subscriptions |
| HBLOOP lost, then recovered (no miss) | RF path | DCC/layout routing node off briefly — sub intact |
| HBLOOP miss + RESUBSCRIBE | Radio | Path up but distributor sub gone (e.g. MASTER reboot) |

## Host recovery (`serial_to_mqtt.py`, `--sync-watch` default on)

1. Periodic USB **`PING`** (~12s). Missed `ACK PING` → reopen streak.
2. Turnout **ACK miss** streak (≥3) → **reopen COM** (DTR) + **`RESUBSCRIBE`**.
3. **SerialException** → reopen COM (DTR re-runs Nano `setup()` plant enroll).
4. After Nano boot (DTR path only): wait for plant accepts; **thin accept** after grace → one **`RESUBSCRIBE`**.
5. Manual MQTT `track/bridge/cmd`:
   - **`RESUBSCRIBE`** — only if HBLOOP is **not** established (no cooldown)
   - **`RESUBSCRIBE FORCE`** — always (no cooldown), even while healthy
   - **`REOPEN`** / **`PING`** / **`HBLOOP`**
6. HBLOOP: traffic-gated probe; lost → echo-only for 60s; then miss+RESUBSCRIBE only if echo still fails.

## Firmware

`RESUBSCRIBE`, plant+self event-125, and `HBLOOP` Block-7 beat live in `lcos_mqtt_bridge.cpp`.
Flash the Nano after pulling this branch.
