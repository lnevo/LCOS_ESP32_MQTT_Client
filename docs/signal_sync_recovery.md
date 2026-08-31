# Bridge sync recovery (USB + LCOS radio)

HBLOOP watches the radio path to MASTER (often via a **DCC node**). Layout power-off can
drop that path without clearing MASTER’s subscription RAM.

## Recovery (after established → lost)

1. **lost** → **RESUBSCRIBE in 1s**
2. If still down → keep **echo every 5s**; **RESUBSCRIBE every 60s** until healthy
3. Echo or layout traffic → **recovered** and **reset** (next loss gets the 1s path again)

Cold-start (never established): echo for 60s, then RESUBSCRIBE / 60s cycles (no 1s thrash).

## Agent restart vs MASTER reboot vs layout power

| Event | What should happen |
|-------|--------------------|
| **Agent restart** | Open COM **without** DTR. Prior plant subscriptions stay on MASTER. Cold-start miss uses the 60s cycle. |
| **Layout / DCC off** (after established) | **lost** → RESUBSCRIBE in **1s**; then 5s echo / 60s RESUBSCRIBE until path or enroll heals. |
| **MASTER reboot** | Same as above; enroll lands once the RF path is up. |
| **Intentional Nano reset** | MQTT `REOPEN` (or unplug) pulses DTR → `setup()` plant+self enroll again. |

Plant event-125 targets nodes **`1,2,3,4,12,13`** plus **self (015)** once for HBLOOP echo — never MASTER (`0`).

## HBLOOP

Every ~5s the agent may send serial `HBLOOP` **only if** no fresh `track/sensor/*`,
`track/signal*`, or `track/turnout/*` feedback arrived in that window. While
recovering, probes continue; the **timer** fires RESUBSCRIBE (1s first, then 60s).
Probe/ACK/ECHO lines are quiet; auto-loop `ACK RESUBSCRIBE` is quiet too (manual
MQTT `RESUBSCRIBE` still echoes under `--verbose`). Lifecycle only:

| Log | Meaning |
|-----|---------|
| `sync: HBLOOP established` | First echo (or layout feedback) |
| `sync: HBLOOP lost - RESUBSCRIBE in 1s` | Was established; quick enroll coming |
| `sync: HBLOOP miss - RESUBSCRIBE after 1s` | First enroll after lost |
| `sync: HBLOOP retrying every 60s until recovered` | Entered quiet 60s cadence (no further miss spam) |
| `sync: HBLOOP recovered` | Echo or layout feedback returned (resets 1s-first) |

While recovering, ops traffic (turnout / signalhead / power / sml RELEASE) may append
`[HBLOOP down — cmds OK, no layout feedback]` at most once per 60s (same line as the
cmd log when `--verbose`).

Retained JMRI panel sensor: **`track/sensor/1567`** (`ACTIVE` when established,
`INACTIVE` when lost / cold-start / bridge start).

Ghost Digicon topic `track/sensor/<display*100+7>` is never published. Self node OCT is
announced by firmware as `HBLOOP_SELF <oct>` (from `thisNode` / `getNodeID()`).

## Failure modes

| Symptom | Likely layer | What broke |
|---------|--------------|------------|
| Turnout cmd, no `ACK …` on serial | USB | COM stolen, Nano reset mid-handle, dead pyserial handle |
| `ACK` OK, no `track/turnout` / `track/sensor` updates | Radio | MASTER dropped Nano’s event-125 subscriptions |
| HBLOOP lost → miss 1s → recovered | RF / MASTER | Path or enroll healed quickly |
| HBLOOP miss every 60s | Radio | Still quiet — path down or MASTER not accepting enroll |

## Host recovery (`serial_to_mqtt.py`, `--sync-watch` default on)

1. Periodic USB **`PING`** (~12s). Missed `ACK PING` → reopen streak.
2. Turnout **ACK miss** streak (≥3) → **reopen COM** (DTR) + **`RESUBSCRIBE`**.
3. **SerialException** → reopen COM (DTR re-runs Nano `setup()` plant enroll).
4. After Nano boot (DTR path only): wait for plant accepts; **thin accept** after grace → one **`RESUBSCRIBE`**.
5. Manual MQTT `track/bridge/cmd`:
   - **`RESUBSCRIBE`** — only if HBLOOP is **not** established (no cooldown)
   - **`RESUBSCRIBE FORCE`** — always (no cooldown), even while healthy
   - **`REOPEN`** / **`PING`** / **`HBLOOP`**
6. HBLOOP recovery as above.

## Firmware

`RESUBSCRIBE`, plant+self event-125, and `HBLOOP` Block-7 beat live in `lcos_mqtt_bridge.cpp`.
Flash the Nano after pulling this branch.
