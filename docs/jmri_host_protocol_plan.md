# Plan: Direct JMRI support — host protocol (Python ↔ Arduino)

Branch: **`feature/jmri-host-protocol`**

## Goals

1. **JMRI-first API on the host:** Subscriptions and publishes match [JMRI MQTT](https://www.jmri.org/help/en/html/hardware/mqtt/index.shtml) usage (topics under `track/…`, payloads such as `THROWN` / `CLOSED`, `ACTIVE` / `INACTIVE`, etc.) as far as this layout needs.
2. **Thin firmware:** Arduino Nano stays responsible for RF24/LCOS only — unpack small binary frames, call `sendShortMessage` / `layout->update()`, optionally emit **compact** status upstream later. **No** parsing JMRI topic strings or ASCII payloads on the device.
3. **All string & topic logic in Python:** Map MQTT topic + payload ↔ LCOS parameters (node, UID, `data1`…), versioning, logging, retries, optional rate limits.

Non-goals for the first slice: changing the repo name; rewriting existing **Arduino → host** MQTT line protocol before we need to (see [Direction split](#direction-split) below).

## JMRI surface (reference)

The sketch already publishes using the same **topic prefix + packed address** scheme as JMRI receive conventions (see `mqtt_serial.h`):

| Prefix | Meaning |
|--------|---------|
| `track/turnout/<n>` | Turnout state |
| `track/sensor/<n>` | Sensor / block / control object |
| `track/signalmast/<n>` | Signal mast aspect string |
| `track/light/<n>` | Light (future) |
| `track/power` | Power (no numeric suffix in our header) |

Packed address: `node * 100 + uid` (documented in `mqtt_serial.h` and `README`).

Python must implement the **inverse** of `mqttTopicWithPackedAddress`: given a JMRI topic, recover **target node** (unicast destination), **LCOS UID**, and **object class** for command encoding. *Note:* Status events on the wire carry `source_node`; commands from JMRI are addressed by **which node owns the object** — subscription tables or a small config file on the host may be required for unicast routing (same problem as any layout bridge).

## Direction split

| Direction | Today | Target |
|-----------|--------|--------|
| **Arduino → Python → MQTT** | Text lines: `topic payload\n` | **Keep** for Phase 1 (proven, JMRI-compatible). Optional Phase 2: binary telemetry to save bandwidth — not required for “direct JMRI” on the host side. |
| **MQTT → Python → Arduino** | Text `PING\n` + special-case in firmware | **Replace commands** with a **binary host frame**; keep `PING` as optional legacy/debug or map to a dedicated opcode. |

Serial **framing must not collide** with the existing LCOS gateway path: `mqtt_bridge_poll_serial` treats leading byte `0` or `1` + enabled gateway as a **fixed-size LCOS serial packet**. Any new host protocol must use a **distinct lead-in** (magic bytes) so the first byte is never ambiguous.

## Host → Arduino binary frame (proposal)

Design principles: fixed maximum length, length inside frame, one byte opcode, big-endian or little-endian **documented once**, optional checksum for UART glitches.

**Sketch (little-endian on wire, aligns with typical Arduino/C usage):**

```
[0]     magic0     0xC0   (host command; not used as LCOS serial lead byte in our branch)
[1]     magic1     0x4C   ('L')
[2]     version    0x01
[3]     opcode     see table below
[4]     flags      bit0=need_ack (future), reserved
[5..6]  dest_node  uint16  LCOS destination (decimal as used in sendShortMessage)
[7]     uid        byte    full LCOS UID (e.g. turnout 8–15, not “index”)
[8]     data1      byte
[9]     data2      byte
[10]    event      byte    ETYPE_OPERATING event code (e.g. EVENT_TURNOUT_CMD)
[11]    cmd_resp   byte    LCOS cmd_response field
[12]    crc8       byte    over bytes 0..11 Polynomial 0x07 init 0x00 (TBD — pick one and lock)

Length: **13 bytes** fixed for Phase 1 (simple read loop, no malloc).

Arduino handler: verify magic/version/CRC → `layout->sendShortMessage(multicast?, dest, etype, event, uid, data1, data2, cmd_resp)` with `multicast=false` for targeted commands (match current heartbeat turnout pattern).

**Opcodes (host semantics, firmware maps to LCOS):**

| Opcode | Meaning |
|--------|---------|
| `0x01` | `OPERATING` turnout command (`EVENT_TURNOUT_CMD`) — `data1` = closed/thrown/toggle per `lcos.h` |
| `0x02` | Signal command (`EVENT_SIGNAL_CMD`) |
| `0x03` | Track power (`EVENT_TRACK_PWR_CMD`) — `uid` ignored per existing patterns |
| `0x04` | Output / raw shortcut: copy fields literally (escape hatch) |
| `0x10` | Heartbeat / echo request (optional; could replace `PING` text) |

Exact opcode set and `sendShortMessage` argument rules should be frozen in a single **protocol version** byte; bump `version` only when frame layout changes.

## Python (`serial_to_mqtt.py` or sibling module)

1. **Subscribe** to JMRI send topics (prefix configurable; default `track/` to match firmware output).
2. **Parse** topic → packed address or power topic; split into `(dest_node, uid)` using layout config (TOML/JSON/YAML in repo or env).
3. **Map** payload strings → `data1` / `data2` using the same tables as `mqtt_serial.cpp` (single source of truth ideally: **generate** C and Python from one CSV/JSON, or duplicate with tests — decide in implementation).
4. **Pack** binary frame, write to serial; optional wait for ACK frame (future).
5. **Coexist** with existing line reader for Arduino → MQTT (`readline` vs **state machine** for 13-byte packets — reader must demultiplex: if buffer sees magic, collect 13 bytes; else line mode for `topic payload\n`).

Demux strategy: **If `peek` matches magic0** after idle, consume binary frame; **else** `readline` for text. Document ordering if both could queue (usually one writer).

## Arduino changes (minimal)

1. New file or section: `host_serial_rx.cpp` — ring buffer or `readBytes` until 13 bytes aligned after sync (resync on magic if CRC fails).
2. Replace or extend `mqtt_bridge_poll_serial`: first check **host magic**; if match, handle host command; else existing LCOS packet / text branch.
3. Remove string compares for layout commands (retain `PING` text only during transition if desired).

## Configuration on host

- **Broker**, **COM**, **JMRI root topic**.
- **`nodes.json` / `layout.toml`**: maps packed address or `(node,uid)` → unicast destination node (and optional “this bridge node” id). Start with a single JSON object listing turnouts/sensors you command from JMRI.

## Testing

1. Unit-test Python pack/parse + CRC cases.
2. Loopback: Mosquitto publish turnout → Python → serial tap / logic analyzer → verify bytes.
3. Integration: JMRI panel → MQTT → physical turnout (same as today with `PING`, extended).

## Open decisions (to lock before coding)

1. **Multicast vs unicast** defaults per object type (match `lcos_mqtt_bridge` heartbeat).
2. **ACK** from Arduino: binary 4-byte “OK + seq” vs stay silent (status-only via LCOS events on radio).
3. **Single vs multiple** fixed frame sizes if we add variable-length raw datagram later.

---

*This document is the working agreement for branch `feature/jmri-host-protocol`; update it as decisions are made.*
