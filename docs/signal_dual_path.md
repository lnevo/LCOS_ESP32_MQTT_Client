# Dual-path signals: IH command vs signalmast status (API packing)

**Source of truth:** `reference/LCOS Public API.xlsx` UID Map + `lcos/lcos.h` (`UID_OFFSET_SIGNALS` 32).

## Packing

```text
packed = displayNode * 100 + UID
UID    = 32 + signal_index     # Signal 0 → 32 … Signal 15 → 47
Node 4 Signal 0 → 432
```

Do **not** add `UID_OFFSET_SIGNALS` again on status publish (that produced MQTT **464**, which is Relay Obj 13 in the UID map, not a signal).

## Topics

| Direction | Topic | Payload |
|-----------|-------|---------|
| JMRI → LCOS | `track/signalhead/IH432` or `track/signalmast/432` | Red/Yellow/Green or Stop/Approach/Clear |
| LCOS → JMRI | `track/signalmast/432` | `Stop; Lit; Unheld` |

`EVENT_SIGNAL_CMD` radio frames are not republished. Status never goes on `signalhead`.

## Aspect map (`lcos.h` / status table)

| MQTT | LCOS `data2` |
|------|--------------|
| Red / Stop | `SIGNAL_STOP` (1) |
| Yellow / Approach | `SIGNAL_APPROACH` (2) |
| Green / Clear | `SIGNAL_CLEAR` (3) |
| Dark / Off | `0` |

Brick Digicon uses JMRI MQTT mast `IF$mqm:AAR-1946:SL-1-high-abs($432)` → topic `track/signalmast/432`.
