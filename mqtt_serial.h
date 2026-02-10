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

// JMRI receive topic prefixes (append packed address via mqttTopicWithPackedAddress)
#define MQTT_TOPIC_TURNOUT   "track/turnout/"
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
 * Pack node + UID into one JMRI system number: node*100 + uid (e.g. node 4, uid 67 → 467).
 * Use for all MQTT topic suffixes so addresses are unique across nodes.
 */
uint16_t mqttPackedAddress(uint16_t node, byte uid);

/**
 * Build topic string from prefix + packed address: e.g. prefix "track/turnout/", node 4, uid 8 → "track/turnout/408".
 * Returns buf (so you can chain with mqttPublish). Use for turnouts, sensors, and all object types.
 */
char *mqttTopicWithPackedAddress(char *buf, size_t bufSize, const char *prefix, uint16_t node, byte uid);

// --- JMRI payload conversion (exact strings per SERIAL OUTPUT PROTOCOL) ---

/** Turnout: data1 0 → "CLOSED", else → "THROWN" */
const char *turnoutStateToPayload(byte data1);

/** Sensor/Block/Button/etc.: data1 0 → "INACTIVE", else → "ACTIVE" */
const char *sensorStateToPayload(byte data1);

/** Power: data1 0 → "OFF", else → "ON" */
const char *powerStateToPayload(byte data1);

// --- One-call wrappers: build topic (packed address), choose payload, publish ---

/**
 * Publish one MQTT line for an operations event. Uses node+uid packed address and
 * event type to pick topic prefix and payload. No-op for event types that don't map to MQTT.
 * State from data1 (LCOS sendShortMessage/broadcastOpState put primary value in data1); data2 passed for future use.
 */
void mqttPublishOperationEvent(Print &out, byte event, uint16_t node, byte uid, byte data1, byte data2);

#endif // MQTT_SERIAL_H
