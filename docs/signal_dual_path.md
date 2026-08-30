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

**Live roster:** MQTT→serial SET and the offline RELEASE burst use packed IDs seen on `track/signalmast/<packed>` (MQTT retain or serial `EVENT_SIGNAL`). Filter: octal-legal node and UID **32–47**. Relays (51+) and turnouts are ignored. No bean / no status → no SET.

**Firmware:** `EVENT_SIGNAL_CMD` **set only** (no auto-RELEASE). Optional legacy `IH` prefix on the serial line still accepted. Explicit MQTT payloads `Release` / `Unheld` / `Get` still work for probes.

## Digicon SML mode guard (`serial_to_mqtt.py`)

Retained **`track/bridge/sml_mode`**: `enabled` | `enabling` | `aborting` | `aborted` | `disabling` | `disabled` | `query`.

| Event | Bridge action |
|-------|----------------|
| Bridge start / live `track/state` **OFFLINE** | Read last `sml_mode`. **Only if `enabled`**, publish `query` and wait ~5s. Extra OFFLINE while in flight is ignored |
| Digicon JMRI (SML Enabled) replies `enabled` | Cancel — leave field alone |
| No ACK (was enabled, controller gone) | Retain **`disabling`**, wait ~3s (late Digicon `enabled` aborts); else **one** serial Red → hold → Unheld for the live `signalmast` roster, mirrored on MQTT as `track/signalhead/<packed>` **Red** then **Unheld** → retain `disabled` |
| Digicon sees `disabling` while Enabled | Replies `enabled` so bridge suspends RELEASE |
| Digicon dests stored Enabled, or operator **Force override** | That JMRI instance publishes **`enabling`** and does **not** abort. **Other** Digicon agents publish **`aborting`**, uncheck immediately (no Hold/Red/Unheld), then **`aborted`**. After ~3s the originator publishes **`enabled`**. Solo has nobody to abort. |
| `enabling` / `aborting` / `aborted` | **Watch** ~12s for `enabled`. If it never arrives, same **query → disabling → Red/Unheld → disabled** challenge |
| `sml_mode` already `disabled` / missing | **Skip** — no Red/Unheld storm |
| Inbound `signalhead` during RELEASE | Dropped so a dying Digicon cannot stack extra Unhelds |

JMRI Digicon script owns Enable→Disable `Unheld` and per-mast SML-off `Unheld`. Boot into Disabled does **not** RELEASE. Dirty-boot abort also does **not** RELEASE.

## Brick lamps (interim)

See **`docs/signal_relay_lamps.md`**: MQTT turnouts `M2T452/453/454` → Relay Obj 1/2/3 → Stop/Approach/Clear.
