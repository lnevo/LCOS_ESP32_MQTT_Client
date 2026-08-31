/**
 * mqtt_serial.h
 * MQTT-formatted serial output for LCOS → JMRI bridge.
 *
 * Protocol: one line per publish, format <topic><space><payload>\n (LF only).
 * Topics and payloads follow JMRI MQTT receive conventions.
 */

#ifndef MQTT_SERIAL_H
#define MQTT_SERIAL_H

#include <Arduino.h>

struct DATAGRAM;  // forward decl; include lcos.h in .cpp

// JMRI receive topic prefixes (append packed address via mqttTopicWithPackedAddress)
// Packed address = jmriNode*100 + uid, where jmriNode = octal string of the RF24 address read as
// decimal (e.g. LCOS 012 = 10 → "12" → 12). See lcosNodeToMqttDisplayNode / mqttDisplayNodeToLcosNode.
// LCOS UID ranges (from lcos.h):
//   0–7   blocks, 8–15  turnouts, 16–31 routes, 32–47 signals, 48–49 crossings,
//   50    mpos,   51–66 relays,  67–82 control objects (buttons etc.), 83+ scene objects.
//   Turnout topic: uid = data0 (already full turnout UID 8–15).
//   Sensor topic (blocks):  uid = UID_OFFSET_BLOCKS + data0 (data0 = block index → 0–7).
//   Sensor topic (button/switch): uid = UID_OFFSET_CONTROL_OBJECTS + data0 (data0 = index → 67–82).
//   Signal mast topic: uid = UID_OFFSET_SIGNALS + data0 (data0 = signal index → 32–47).
#define MQTT_TOPIC_TURNOUT   "track/turnout/"
/** Base for cmd serial line: "track/cmd/turnout/<packed> THROWN|CLOSED\\n"; MQTT subscribe track/cmd/turnout/# */
#define MQTT_TOPIC_CMD_TURNOUT "track/cmd/turnout"
#define MQTT_TOPIC_SENSOR    "track/sensor/"
#define MQTT_TOPIC_LIGHT     "track/light/"
#define MQTT_TOPIC_SIGNALMAST "track/signalmast/"
#define MQTT_TOPIC_POWER     "track/power"   // no UID

/**
 * Emit one MQTT publish line to out: "topic payload\n" (LF only, no CR).
 * Safe if topic or payload contains spaces (first space separates topic from payload).
 */
void mqttPublish(Print &out, const char *topic, const char *payload);

/**
 * Map LCOS/RF24 internal node to the JMRI packed “node” digit group (string of %o digits read in base 10).
 */
uint16_t lcosNodeToMqttDisplayNode(uint16_t lcosNode);

/**
 * Map JMRI packed “node” group back to LCOS/RF24 internal (decimal string parsed as base 8).
 */
uint16_t mqttDisplayNodeToLcosNode(uint16_t jmriNode);

/**
 * Pack LCOS source_node + uid into one JMRI system number: jmriNode*100 + uid, jmriNode = lcosNodeToMqttDisplayNode(LCOS).
 */
uint16_t mqttPackedAddress(uint16_t lcosNode, byte uid);

/**
 * Build topic from prefix; lcosNode is the RF24 address from the datagram. Example: internal 10, uid 8 → 1208.
 * Returns buf (so you can chain with mqttPublish).
 */
char *mqttTopicWithPackedAddress(char *buf, size_t bufSize, const char *prefix, uint16_t lcosNode, byte uid);

// --- JMRI payload conversion (exact strings per SERIAL OUTPUT PROTOCOL) ---

/** Turnout: lcos.h ALIGN_* on data1 → JMRI "CLOSED" / "THROWN" */
const char *turnoutStateToPayload(byte data1);

/** Sensor/Block/Button/etc.: data1 0 → "INACTIVE", else → "ACTIVE" */
const char *sensorStateToPayload(byte data1);

/** Power: data1 0 → "OFF", else → "ON" */
const char *powerStateToPayload(byte data1);

/**
 * Signal mast: JMRI format "AspectName; Lit; Unheld" (see JMRI MQTT doc).
 * lcos.h/cpp define only EVENT_SIGNAL, EVENT_SIGNAL_CMD, UID_OFFSET_SIGNALS; no aspect
 * encoding. We treat data1 as aspect code and use a placeholder mapping in .cpp; adjust to match nodes.
 */
const char *signalMastStateToPayload(byte data1);

// --- One-call wrappers: build topic (packed address), choose payload, publish ---

/**
 * Publish one MQTT line for an operations event. Pass the full LCOS packet.
 *
 * Topic suffix uses pkt->source_node and data0 (etc.) from the LCOS payload — the sender's
 * self-reported node ID, not necessarily who you unicast in sendShortMessage, and not
 * RF24NetworkHeader.from_node (last radio hop; see three-arg debug line: src= vs rf24=).
 *
 * Turnout 0 on a node is UID (UID_OFFSET_TURNOUTS + 0) = 8. UID 27 is route band (16+11), not turnout 0.
 * EV_TURNOUT_CMD is not published to MQTT (only EV_TURNOUT status), to avoid bogus topics when data0 is not a turnout UID.
 *
 * Two-arg overload: MQTT_SERIAL_OPS_DEBUG in mqtt_serial.cpp (1 = DBG on, 0 = off).
 * Three-arg: explicit debug on/off regardless of MQTT_SERIAL_OPS_DEBUG.
 */
void mqttPublishOperationEvent(Print &out, const struct DATAGRAM *pkt);
void mqttPublishOperationEvent(Print &out, const struct DATAGRAM *pkt, bool debug);

#endif // MQTT_SERIAL_H
