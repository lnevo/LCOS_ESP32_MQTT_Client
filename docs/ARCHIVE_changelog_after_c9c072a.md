# Archived commit log (post–`c9c072a`, pre-rewind)

Branch was rewound to `c9c072a` after this snapshot was taken. Use this list to reimplement or cherry-pick work deliberately.

| Field | Value |
|--------|--------|
| Rewind target | `c9c072a` — Refactor: move MQTT bridge to `lcos_mqtt_bridge.*`; slim `.ino` |
| Tip before rewind | `714d87b4cc69f1ecdffa87e7ba05481efa64e3bd` |
| Range archived | `c9c072a..714d87b4cc69f1ecdffa87e7ba05481efa64e3bd` (commits not in `c9c072a`) |
| Full-tree backup | Branch `archive/pre-rewind-714d87b` points at the pre-rewind tip for `git diff` / cherry-pick |

## Commits (oldest first)

- **a4da6ac** Reference: replace LCOS_Client_Bare.ino with v1.10 (ex-new_client.txt); remove new_client.txt; fix typo, layoutNet init, case 125 break; note in bridge header

- **63c20db** Rename serial_to_mqtt.py (drop phase_a); point run_serial_mqtt*.cmd at it; remove PowerShell serial_to_mqtt.ps1 and old launcher .cmd

- **ffacbd6** Fix heartbeat turnout cmd: broadcast + data1=0 CLOSED + responding_to=0 (README); doc sendShortMessage 0/1 vs formal API

- **eb9174c** gateways.h: add include guards (fix redefinition when included from bridge header + sketch)

- **ceb2ecf** Fix gateway redefinition without changing gateways.h

- **714d87b** lcos_mqtt_bridge: Serial debug line for HB PING turnout sendShortMessage


## Full log (subject + body)

### a4da6ac Reference: replace LCOS_Client_Bare.ino with v1.10 (ex-new_client.txt); remove new_client.txt; fix typo, layoutNet init, case 125 break; note in bridge header

Made-with: Cursor

---

### 63c20db Rename serial_to_mqtt.py (drop phase_a); point run_serial_mqtt*.cmd at it; remove PowerShell serial_to_mqtt.ps1 and old launcher .cmd

Made-with: Cursor

---

### ffacbd6 Fix heartbeat turnout cmd: broadcast + data1=0 CLOSED + responding_to=0 (README); doc sendShortMessage 0/1 vs formal API

Made-with: Cursor

---

### eb9174c gateways.h: add include guards (fix redefinition when included from bridge header + sketch)

Made-with: Cursor

---

### ceb2ecf Fix gateway redefinition without changing gateways.h

Revert include guards on gateways.h. Drop gateways.h from lcos_mqtt_bridge.h
(use forward declaration); include gateways.h in lcos_mqtt_bridge.cpp only.
Sketch still includes gateways.h before the bridge header.

Made-with: Cursor

---

### 714d87b lcos_mqtt_bridge: Serial debug line for HB PING turnout sendShortMessage

Made-with: Cursor

---

