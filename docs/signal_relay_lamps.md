# Brick lamps via LCOS relays (interim)

**Checkpoint before this path:** git tag `working-ih-signalhead-2026-08-12` (branch `checkpoint/ih-signalhead-cmd`) — Digicon `track/signalhead/IH*` → `EVENT_SIGNAL_CMD`.

## Field signal status (API packing)

`EVENT_SIGNAL` → `track/signalmast/<displayNode*100+UID>` with aspect `Stop|Approach|Clear|…`.

- Signal 0 UID **32** on node 4 → **432** (not 464).
- Bridge no longer adds `UID_OFFSET_SIGNALS` a second time.

## Lamp drive (Node 04 relays)

| Relay | UID | MQTT turnout | Lamp |
|-------|-----|--------------|------|
| 0 | 51 | M2T451 | DCC detector reset (calibration) — not a signal lamp |
| 1 | 52 | M2T452 | Stop / Red |
| 2 | 53 | M2T453 | Approach / Yellow |
| 3 | 54 | M2T454 | Clear / Green |

JMRI Triple Output head **LH464** wires red→452, yellow→453, green→454 (`THROWN` = lamp on).

## Bridge command path

`track/cmd/turnout/<packed>` with packed UID in **51–66**:

- `THROWN` / `ON` → `EVENT_CONTROL_CMD` (0x14), `data1=0x02` (set), `data2=1`
- `CLOSED` / `OFF` → same with `data2=0`

Packing (same as turnouts): `452` → display node `4` → RF24 octal `4`, UID `52` (Relay Obj 1).
Octal is only applied to the **node** digits, not the UID.

Turnout UIDs 8–15 still use `EVENT_TURNOUT_CMD` as before.
