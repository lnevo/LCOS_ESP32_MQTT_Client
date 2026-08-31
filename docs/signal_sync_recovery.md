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
| Resubscribe | `RESUBSCRIBE` | Re-emits event 125 to display nodes 1,2,3,4,12,13 **+ self (015)**; watch `Subscription accepted` |
| Turnout GET | `track/cmd/turnout/<packed> GET` | Field answers turnout **index** 0–7 on the wire; Digicon packs **UID 8–15** (`408`). Bridge maps both ways. |
| Signal aspect GET | `track/signalhead/<packed> Get` | Field should publish `EVENT_SIGNAL` → MQTT `track/signalmast/…` (master Signal 0 = `32`) |
| Track power status | `track/cmd/power/<district> GET` | MASTER should publish `EVENT_TRACK_POWER` → MQTT `track/power/<district>` |
| Live Digicon throw | MQTT `track/cmd/turnout/<packed> THROWN` | Full path: MQTT→USB→radio→status |

## Host recovery (`serial_to_mqtt.py`, `--sync-watch` default on)

1. Periodic **USB `PING`** (~12s). Quiet unless miss; missed `ACK PING` → reopen streak.
2. Turnout **ACK miss** streak (≥3) → **reopen COM** + **`RESUBSCRIBE`**.
3. **SerialException** → reopen COM (DTR re-runs Nano `setup()` subscriptions).
4. **Subscriptions / HBLOOP status** (stderr always):
   - `sync: subscriptions complete (1,2,3,4,12,13)` when plant event-125 accepts land
     (self **015** is also subscribed for the HB echo; MASTER often never prints accept for self)
   - `sync: HBLOOP established` / `lost` / `recovered`
   - **HBLOOP probe (5s):** host sends serial `HBLOOP` → Nano broadcasts Block-7 on node
     **015**. With self subscribed, distributor should return the beat → serial
     **`HBLOOP ECHO`** (and would-be `track/sensor/1507`, suppressed from Digicon).
     No echo within the interval → `HBLOOP miss (n/3)`. **Layout**
     `track/sensor/*` / `track/signalmast/*` does **not** clear HB — only ECHO/1507 does.
     **3 misses (~15s)** → **`RESUBSCRIBE`**.
   - Manual **`RESUBSCRIBE`** while HBLOOP is running is skipped unless
     **`RESUBSCRIBE FORCE`**. Cooldown between RESUBSCRIBE attempts: **15s**.
   - After MASTER power-cycle with the bridge left up: wait for miss→RESUBSCRIBE, or
     send **`RESUBSCRIBE FORCE`**, or restart the bridge.
5. Turnout **SET/TOGGLE** does not push `EVENT_TURNOUT` on this plant — firmware follows SET
   with a **GET** so `track/turnout/…` updates. Block sensors still need distributor events.

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
| Boot banner → thin-accept check | Nodes **0**,1,2,3,4,12,13 → expect **7** accepts (`SYNC_SUBSCRIBE_DISPLAY_NODES`) |
| `track/bridge/cmd` `PING` | `ACK PING` |
| GET `408`/`411`/`1208`/`108` | Serial `ACK`, **no** MQTT status |
| GET `100` | Serial `ACK` + `track/turnout/100 CLOSED` |
| COM7 open/close then GET `100` | Still `CLOSED` (USB ping stays healthy; COM7 alone does not force the ACK-miss path) |

Gap: master reboot that leaves USB ACK working will **not** trip the current
watchdog. Need a follow-up rule: after turnout ACK, expect `track/turnout/…`
status within N seconds → else `RESUBSCRIBE`.

## Master status GET probe (2026-08-30)

Firmware now: subscribe display node **0**, `track/cmd/power/<district> GET`,
signalhead `Get` without Digicon roster. One-shot:
`python -u scripts\windows\probe_master_status_oneshot.py`

| Check | Serial ACK | MQTT status |
|-------|------------|-------------|
| GET turnout `100` (control) | yes | `track/turnout/100 CLOSED` |
| GET signal master `32` | yes | **none** |
| GET signal node4 `432` | yes | **none** |
| GET track power district `0` | yes | **none** |

Subscription accepted for node **0**. Conclusion: command path to MASTER works;
field did **not** publish `EVENT_SIGNAL` / `EVENT_TRACK_POWER` for these GETs
(likely no Signal / Track Power object answering on MASTER, and Digicon Signal 0
also silent on aspect GET). Not usable yet as a sync-recovery heartbeat.
