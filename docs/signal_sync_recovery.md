# Bridge sync recovery (USB + LCOS radio)

HBLOOP watches the radio path to MASTER (often via a **DCC node**). Layout power-off can
drop that path without clearing MASTER’s subscription RAM.

## Recovery cycle (while unhealthy)

1. **lost** → quiet echo probes; **RESUBSCRIBE disarmed for 60s**
2. If **echo** or **layout traffic** returns in that minute → **recovered** (no enroll)
3. If still quiet → **miss** + **one RESUBSCRIBE**, then another **60s echo-only** window
4. Repeat until healthy (covers MASTER reboot while the layout was down: within ~1 minute
   after the path is back, one enroll can land)

Never permanently disarm the monitor after a miss (agent restart with layout down must
still recover).

## Agent restart vs MASTER reboot vs layout power

| Event | What should happen |
|-------|--------------------|
| **Agent restart** | Open COM **without** DTR. Prior plant subscriptions stay on MASTER. Cold-start miss enters the same 60s cycle (does not give up). |
| **Layout / DCC off** | **lost**; echo continues; resub disarmed 60s. Path/traffic back → **recovered**. |
| **MASTER reboot** | Echo stays dead → after 60s **miss** + one `RESUBSCRIBE`; repeat minute cycles until healthy. |
| **Intentional Nano reset** | MQTT `REOPEN` (or unplug) pulses DTR → `setup()` plant+self enroll again. |

Plant event-125 targets nodes **`1,2,3,4,12,13`** plus **self (015)** once for HBLOOP echo — never MASTER (`0`).

## HBLOOP

Every ~5s the agent may send serial `HBLOOP` **only if** no fresh `track/sensor/*`,
`track/signal*`, or `track/turnout/*` feedback arrived in that window. While
recovering, probes continue; the **minute timer** fires the one `RESUBSCRIBE` (not
an echo-miss edge). Probe/ACK/ECHO lines are quiet; lifecycle only:

| Log | Meaning |
|-----|---------|
| `sync: HBLOOP established` | First echo (or layout feedback) |
| `sync: HBLOOP lost - …` | Health dropped / cold-start miss; 60s echo-only |
| `sync: HBLOOP miss - …; RESUBSCRIBE` | Minute timer: still recovering — one enroll, then echo-only again |
| `sync: HBLOOP recovered` | Echo or layout feedback returned |

Ghost Digicon topic `track/sensor/<display*100+7>` is never published. Self node OCT is
announced by firmware as `HBLOOP_SELF <oct>` (from `thisNode` / `getNodeID()`).

## Failure modes

| Symptom | Likely layer | What broke |
|---------|--------------|------------|
| Turnout cmd, no `ACK …` on serial | USB | COM stolen, Nano reset mid-handle, dead pyserial handle |
| `ACK` OK, no `track/turnout` / `track/sensor` updates | Radio | MASTER dropped Nano’s event-125 subscriptions |
| HBLOOP lost, then recovered (no miss) | RF path | DCC/layout routing node off briefly — sub intact |
| HBLOOP miss + RESUBSCRIBE | Radio | Still quiet after 60s (path up but sub gone, or path still down) |

## Host recovery (`serial_to_mqtt.py`, `--sync-watch` default on)

1. Periodic USB **`PING`** (~12s). Missed `ACK PING` → reopen streak.
2. Turnout **ACK miss** streak (≥3) → **reopen COM** (DTR) + **`RESUBSCRIBE`**.
3. **SerialException** → reopen COM (DTR re-runs Nano `setup()` plant enroll).
4. After Nano boot (DTR path only): wait for plant accepts; **thin accept** after grace → one **`RESUBSCRIBE`**.
5. Manual MQTT `track/bridge/cmd`:
   - **`RESUBSCRIBE`** — only if HBLOOP is **not** established (no cooldown)
   - **`RESUBSCRIBE FORCE`** — always (no cooldown), even while healthy
   - **`REOPEN`** / **`PING`** / **`HBLOOP`**
6. HBLOOP minute cycle as above.

## Firmware

`RESUBSCRIBE`, plant+self event-125, and `HBLOOP` Block-7 beat live in `lcos_mqtt_bridge.cpp`.
Flash the Nano after pulling this branch.
