# Bridge sync recovery (USB + LCOS radio)

When Digicon throws a turnout and **sensors do not move**, or the host logs
**`no ACK within timeout`**, the usual cause is not MQTT broker subscription loss.
It is **Nano USB desync** and/or **lost LCOS event-125 radio subscriptions**.

## Failure modes

| Symptom | Likely layer | What broke |
|---------|--------------|------------|
| Turnout cmd, no `ACK …` on serial | USB | COM stolen, Nano reset mid-handle, dead pyserial handle |
| `ACK` OK, no `track/turnout` / `track/sensor` updates | Radio | MASTER (or distributor) dropped Nano’s event-125 subscriptions |
| Opening COM7 while bridge runs | USB | Exclusive COM + Arduino DTR reset; bridge handle dies |

Simulating Nano reboot: open COM7 (or the bridge COM) in another serial tool so the
Nano resets. The Python process often keeps a dead handle until reopen.

## Probes (API / serial text)

| Probe | Serial line | Proves |
|-------|-------------|--------|
| USB ping | `PING` | Nano text stack alive (`ACK PING`) — **no radio, no turnout** |
| Resubscribe | `RESUBSCRIBE` | Re-emits event 125 to display nodes 1,2,3,4,12,13; watch `Subscription accepted - node: …` |
| Turnout GET | `track/cmd/turnout/<packed> GET` | Field should publish `EVENT_TURNOUT` → MQTT `track/turnout/…` |
| Live Digicon throw | MQTT `track/cmd/turnout/<packed> THROWN` | Full path: MQTT→USB→radio→status |

## Host recovery (`serial_to_mqtt.py`, `--sync-watch` default on)

1. Periodic **USB `PING`** (12s). Quiet unless miss; missed `ACK PING` counts toward fail streak.
2. Turnout **ACK miss** streak (≥3) → request **reopen COM** + **`RESUBSCRIBE`**.
3. **SerialException** → reopen COM (DTR usually re-runs Nano `setup()` subscriptions).
4. Nano **boot banner** → wait for `setup()` accepts; **`RESUBSCRIBE` only if thin** (avoids double).
5. Cooldowns avoid recovery storms.

Disable with `--no-sync-watch`.

## Firmware flash required

`RESUBSCRIBE`, USB-only `PING`, and turnout `GET` live in
`lcos_mqtt_bridge.cpp`. Flash the Nano after pulling this branch.

## Manual Windows check

```bat
python -u serial_to_mqtt.py --com COM3 --broker 192.168.137.2 --verbose --signalhead
```

In another window, open COM7 briefly (or the same COM after killing the bridge) to
reset the Nano, then watch for `sync: reopening` / `sync: RESUBSCRIBE` and
`Subscription accepted` lines. Probe a **known-good** turnout with MQTT `GET`
(lab: packed `100` → `track/turnout/100 CLOSED`). Smoke default used to be `408`,
which often ACKs on USB with **no** status reply.

One-shot from SSH (`win` / `10.0.0.6:2222`):

```bat
python -u scripts\windows\win_sync_lab.py
python -u scripts\windows\win_com7_turnout100.py
```

SSH sessions kill non-detached children when the session ends — lab starters use
Windows `DETACHED_PROCESS` so the bridge can outlive the SSH command.

## Windows lab results (2026-08-29)

| Check | Result |
|-------|--------|
| Boot banner → `RESUBSCRIBE` | Nodes 1,2,3,4,12,13 `Subscription accepted` (×2 with setup()) |
| `track/bridge/cmd` `PING` | `ACK PING` |
| GET `408`/`411`/`1208`/`108` | Serial `ACK`, **no** MQTT status |
| GET `100` | Serial `ACK` + `track/turnout/100 CLOSED` |
| COM7 open/close then GET `100` | Still `CLOSED` (USB ping stays healthy; COM7 alone does not force the ACK-miss path) |

Gap: master reboot that leaves USB ACK working will **not** trip the current
watchdog. Need a follow-up rule: after turnout ACK, expect `track/turnout/…`
status within N seconds → else `RESUBSCRIBE`.
