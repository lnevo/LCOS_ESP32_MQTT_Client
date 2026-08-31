/**
 * mqtt_serial.cpp
 * MQTT-formatted serial output for LCOS → JMRI bridge.
 * Protocol: <topic><space><payload>\n (LF only). See todo.txt SERIAL OUTPUT PROTOCOL.
 */

/* DBG … lines on Serial for turnout/signal/block/… publishes: 1 = ON, 0 = OFF (not inverted — 0 is “false” in C). */
#ifndef MQTT_SERIAL_OPS_DEBUG
#define MQTT_SERIAL_OPS_DEBUG 1
#endif

#include "mqtt_serial.h"
#include "lcos/lcos.h"
#include <stdio.h>
#include <stdlib.h>

void mqttPublish(Print &out, const char *topic, const char *payload) {
  out.print(topic);
  out.print(' ');
  out.print(payload);
  out.print('\n');  // LF only, no CR
}

uint16_t lcosNodeToMqttDisplayNode(uint16_t lcosNode) {
  char buf[8];
  snprintf(buf, sizeof(buf), "%o", (unsigned)lcosNode);
  return (uint16_t)strtoul(buf, nullptr, 10);
}

uint16_t mqttDisplayNodeToLcosNode(uint16_t jmriNode) {
  char buf[8];
  snprintf(buf, sizeof(buf), "%u", (unsigned)jmriNode);
  return (uint16_t)strtoul(buf, nullptr, 8);
}

uint16_t mqttPackedAddress(uint16_t lcosNode, byte uid) {
  uint16_t n = lcosNodeToMqttDisplayNode(lcosNode);
  return n * 100u + (uint16_t)uid;
}

char *mqttTopicWithPackedAddress(char *buf, size_t bufSize, const char *prefix, uint16_t node, byte uid) {
  if (buf == nullptr || bufSize == 0) return buf;
  snprintf(buf, bufSize, "%s%u", prefix, (unsigned)mqttPackedAddress(node, uid));
  return buf;
}

const char *turnoutStateToPayload(byte data1) {
  /* lcos.h: ALIGN_MAIN/ALIGN_CLOSED (1), ALIGN_THROWN/ALIGN_DIVERGENT (2), ALIGN_TOGGLE/ALIGN_ANY (3), ALIGN_NONE (0). */
  if (data1 == ALIGN_NONE || data1 == ALIGN_MAIN || data1 == ALIGN_CLOSED) {
    return "CLOSED";
  }
  if (data1 == ALIGN_THROWN || data1 == ALIGN_DIVERGENT) {
    return "THROWN";
  }
  /* Toggle/any: JMRI has no standard — publish THROWN as non-main. */
  return "THROWN";
}

const char *sensorStateToPayload(byte data1) {
  return data1 == 0 ? "INACTIVE" : "ACTIVE";
}

const char *powerStateToPayload(byte data1) {
  return data1 == 0 ? "OFF" : "ON";
}

// --- Signal mast (EVENT_SIGNAL 0x3 status, EVENT_SIGNAL_CMD 0x11 command; UID_OFFSET_SIGNALS 32.)
// lcos.h: SIGNAL_STOP 1, SIGNAL_APPROACH 2, SIGNAL_CLEAR 3, SIGNAL_OFF 4. Legacy packets may still use 0.
// JMRI expects "AspectName; Lit|Unlit; Held|Unheld" on track/signalmast/.
static const char *signalMastAspectName(byte data1) {
  switch (data1) {
    case 0:  return "Off";
    case SIGNAL_STOP:    return "Stop";
    case SIGNAL_APPROACH: return "Approach";
    case SIGNAL_CLEAR:   return "Clear";
    case SIGNAL_OFF:     return "Off";
    default: return "Dark";
  }
}

// Returns pointer to static buffer: "AspectName; Lit; Unheld".
const char *signalMastStateToPayload(byte data1) {
  static char buf[48];
  const char *aspect = signalMastAspectName(data1);
  snprintf(buf, sizeof(buf), "%s; Lit; Unheld", aspect);
  return buf;
}

// Internal: LCOS payload source vs RF24 last-hop often differ on relay trees (compare when "wrong" node in MQTT).
static void debugOperationPayload(Print &out, byte event, uint16_t lcos_source_node, uint16_t rf24_from_node, uint16_t to_node,
  byte d0, byte d1, byte d2, byte d3, byte d4, byte d5, byte d6, byte cr) {
  out.print(F("DBG event="));
  out.print((int)event);
  out.print(F(" src="));
  out.print(lcos_source_node);
  out.print(F(" jmriN="));
  out.print(lcosNodeToMqttDisplayNode(lcos_source_node));
  out.print(F(" rf24="));
  out.print(rf24_from_node);
  out.print(F(" to="));
  out.print(to_node);
  out.print(F(" d0="));
  out.print((int)d0);
  out.print(F(" d1="));
  out.print((int)d1);
  out.print(F(" d2="));
  out.print((int)d2);
  out.print(F(" d3="));
  out.print((int)d3);
  out.print(F(" d4="));
  out.print((int)d4);
  out.print(F(" d5="));
  out.print((int)d5);
  out.print(F(" d6="));
  out.print((int)d6);
  out.print(F(" cr="));
  out.println((int)cr);
}

void mqttPublishOperationEvent(Print &out, const DATAGRAM *pkt) {
  mqttPublishOperationEvent(out, pkt, MQTT_SERIAL_OPS_DEBUG != 0);
}

void mqttPublishOperationEvent(Print &out, const DATAGRAM *pkt, bool debug) {
  if (pkt == nullptr) return;

  byte event = pkt->event;
  uint16_t node = pkt->source_node;
  byte uid = pkt->data0;
  byte data1 = pkt->data1;
  byte data2 = pkt->data2;

  if (debug && (event == EVENT_TURNOUT || event == EVENT_TURNOUT_CMD || event == EVENT_SIGNAL || event == EVENT_SIGNAL_CMD || event == EVENT_BLOCK || event == EVENT_BLOCK_CMD || event == EVENT_BUTTON || event == EVENT_SWITCH_CONTACT)) {
    debugOperationPayload(out, event, node, pkt->from_node, pkt->to_node, uid, data1, data2,
      pkt->data3, pkt->data4, pkt->data5, pkt->data6, pkt->cmd_response);
  }

  char topic[32];
  const char *payload = nullptr;
  const char *prefix = nullptr;
  byte topic_uid = uid;  // default: data0 is already full LCOS UID (e.g. turnouts 8–15)

  switch (event) {
    case EVENT_TURNOUT_CMD:
      /* Status (EVENT_TURNOUT) is authoritative for JMRI; CMD frames often carry non-UID data0 (e.g. 0x7F). */
      return;
    case EVENT_TURNOUT:
      prefix = MQTT_TOPIC_TURNOUT;
      payload = turnoutStateToPayload(data1);
      break;
    case EVENT_SIGNAL:
    case EVENT_SIGNAL_CMD:
      prefix = MQTT_TOPIC_SIGNALMAST;
      payload = signalMastStateToPayload(data1);
      /* lcos.h: UID_OFFSET_SIGNALS 32 (range 32–47). data0 = uid or index not defined in library; we use offset+data0. */
      topic_uid = UID_OFFSET_SIGNALS + uid;
      break;
    case EVENT_BLOCK:
    case EVENT_BLOCK_CMD:
    case EVENT_BUTTON:
    case EVENT_SWITCH_CONTACT:
      prefix = MQTT_TOPIC_SENSOR;
      payload = sensorStateToPayload(data1);
      /* data0 is index; LCOS UID = offset + index (blocks 0–7, button/switch 67–82) */
      topic_uid = (event == EVENT_BLOCK || event == EVENT_BLOCK_CMD) ? (UID_OFFSET_BLOCKS + uid) : (UID_OFFSET_CONTROL_OBJECTS + uid);
      break;
    // lights: add case when LCOS event is defined
    default:
      return;
  }

  if (prefix && payload) {
    mqttTopicWithPackedAddress(topic, sizeof(topic), prefix, node, topic_uid);
    mqttPublish(out, topic, payload);
  }
} 
