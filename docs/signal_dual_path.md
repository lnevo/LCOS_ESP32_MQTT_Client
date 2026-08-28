# Dual-path signals: status vs Digicon IH vs relay lamps

**Checkpoint (IH SIGNAL_CMD experiments):** tag `working-ih-signalhead-2026-08-12`.

## Status (field → MQTT)

**Source of truth:** `reference/LCOS Public API.xlsx` UID Map + `lcos/lcos.h` (`UID_OFFSET_SIGNALS` 32).

```text
packed = displayNode * 100 + UID
UID    = 32 + signal_index     # Signal 0 → 32 … Signal 15 → 47
Node 4 Signal 0 → 432
```

Do **not** add `UID_OFFSET_SIGNALS` again on status publish (that produced MQTT **464**, which is Relay Obj 13).

| Direction | Topic | Payload |
|-----------|-------|---------|
| LCOS → JMRI | `track/signalmast/432` | `Stop; Lit; Unheld` (etc.) |
| Digicon set → JMRI (echo) | same | **off** (`MQTT_PUBLISH_SIGNALMAST_ON_SET` = 0) while testing field SoR |

`EVENT_SIGNAL_CMD` radio frames from the field are not republished (bogus UIDs). Status never goes on `signalhead`.

## Digicon Virtual heads (IH)

**MQTT topic:** `track/signalhead/<packed>` (no `IH` in the leaf). JMRI beans remain `IH###`.

**Python on by default** (`FORWARD_SIGNALHEAD_CMDS = True`): forwards those topics → Nano.

**Firmware:** `EVENT_SIGNAL_CMD` **set only** (no auto-RELEASE). Optional legacy `IH` prefix on the serial line still accepted. Explicit MQTT payloads `Release` / `Unheld` / `Get` still work for probes.

## Digicon SML mode guard (`serial_to_mqtt.py`)

Retained **`track/bridge/sml_mode`**: `enabled` | `disabled` | `query`.

| Event | Bridge action |
|-------|----------------|
| Bridge start / live `track/state` **OFFLINE** | Read last `sml_mode`. **Only if `enabled`**, publish `query` and wait ~5s |
| Digicon JMRI (SML Enabled) replies `enabled` | Cancel — leave field alone |
| No ACK (was enabled, controller gone) | Serial: **all** Digicon heads **Red** (paced ~50ms), **one** 3s hold, **all** **Unheld**, retain `disabled` |
| `sml_mode` already `disabled` / missing | **Skip** — no Red/Unheld storm |

JMRI Digicon script owns Enable→Disable `Unheld` and per-mast SML-off `Unheld`. Boot into Disabled does **not** RELEASE.

## Brick lamps (interim)

See **`docs/signal_relay_lamps.md`**: MQTT turnouts `M2T452/453/454` → Relay Obj 1/2/3 → Stop/Approach/Clear.
