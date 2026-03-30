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

void mqttPublish(Print &out, const char *topic, const char *payload) {
  out.print(topic);
  out.print(' ');
  out.print(payload);
  out.print('\n');  // LF only, no CR
}

uint16_t mqttPackedAddress(uint16_t node, byte uid) {
  return (uint16_t)node * 100 + (uint16_t)uid;
}

char *mqttTopicWithPackedAddress(char *buf, size_t bufSize, const char *prefix, uint16_t node, byte uid) {
  if (buf == nullptr || bufSize == 0) return buf;
  snprintf(buf, bufSize, "%s%u", prefix, (unsigned)mqttPackedAddress(node, uid));
  return buf;
}

const char *turnoutStateToPayload(byte data1) {
  /* JMRI: 0 = CLOSED, 1 = THROWN. If your node uses the opposite, swap the strings. */
  return data1 == 0 ? "CLOSED" : "THROWN";
}

/** Map LCOS turnout data1 to JMRI payload strings (track/turnout/...). */
static const char *turnoutLcOsData1ToJmriPayload(byte data1) {
  /* lcos.h: 0x1 closed/main, 0x2 thrown, 0x3 toggle. Multicast turnout CMD echoes often use data1==0 for closed. */
  if (data1 == 2) {
    return "THROWN";
  }
  if (data1 == 1 || data1 == 0) {
    return "CLOSED";
  }
  return "THROWN";
}

const char *sensorStateToPayload(byte data1) {
  return data1 == 0 ? "INACTIVE" : "ACTIVE";
}

const char *powerStateToPayload(byte data1) {
  return data1 == 0 ? "OFF" : "ON";
}

// --- Signal mast (EVENT_SIGNAL 0x3 status, EVENT_SIGNAL_CMD 0x11 command; UID_OFFSET_SIGNALS 32.)
//     data1: 0=Off, 1=Stop. For 2/3: formal LCOS API lists 2=Clear, 3=Approach; on this layout we observe
//     2=Approach, 3=Clear — adjust here if your nodes match the doc instead.
// JMRI expects "AspectName; Lit|Unlit; Held|Unheld" on track/signalmast/.
static const char *signalMastAspectName(byte data1) {
  switch (data1) {
    case 0:  return "Off";
    case 1:  return "Stop";
    case 2:  return "Approach";  // Approach/Caution
    case 3:  return "Clear";
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

// LCOS operations event codes we publish (turnouts, sensors, blocks, signal masts, lights)
#define EV_TURNOUT      0x02
#define EV_SIGNAL       0x03
#define EV_BLOCK        0x04
#define EV_BUTTON       0x0B
#define EV_SWITCH       0x0C
#define EV_TURNOUT_CMD  0x10
#define EV_SIGNAL_CMD   0x11
#define EV_BLOCK_CMD    0x16

// Internal: LCOS payload source vs RF24 last-hop often differ on relay trees (compare when "wrong" node in MQTT).
static void debugOperationPayload(Print &out, byte event, uint16_t lcos_source_node, uint16_t rf24_from_node, uint16_t to_node,
  byte d0, byte d1, byte d2, byte d3, byte d4, byte d5, byte d6, byte cr) {
  out.print(F("DBG event="));
  out.print((int)event);
  out.print(F(" src="));
  out.print(lcos_source_node);
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

  if (debug && (event == EV_TURNOUT || event == EV_TURNOUT_CMD || event == EV_SIGNAL || event == EV_SIGNAL_CMD || event == EV_BLOCK || event == EV_BLOCK_CMD || event == EV_BUTTON || event == EV_SWITCH)) {
    debugOperationPayload(out, event, node, pkt->from_node, pkt->to_node, uid, data1, data2,
      pkt->data3, pkt->data4, pkt->data5, pkt->data6, pkt->cmd_response);
  }

  char topic[32];
  const char *payload = nullptr;
  const char *prefix = nullptr;
  byte topic_uid = uid;  // default: data0 is already full LCOS UID (e.g. turnouts 8–15)

  switch (event) {
    case EV_TURNOUT:
      prefix = MQTT_TOPIC_TURNOUT;
      payload = turnoutLcOsData1ToJmriPayload(data1);
      break;
    case EV_TURNOUT_CMD:
      /* CMD acks often put function codes in data0 (e.g. 0x7f=127), not turnout UID — topic would be wrong (e.g. 3*100+127=427). */
      if (uid < UID_OFFSET_TURNOUTS || uid > UID_OFFSET_TURNOUTS + 7) {
        return;
      }
      prefix = MQTT_TOPIC_TURNOUT;
      payload = turnoutLcOsData1ToJmriPayload(data1);
      break;
    case EV_SIGNAL:
    case EV_SIGNAL_CMD:
      prefix = MQTT_TOPIC_SIGNALMAST;
      payload = signalMastStateToPayload(data1);
      /* lcos.h: UID_OFFSET_SIGNALS 32 (range 32–47). data0 = uid or index not defined in library; we use offset+data0. */
      topic_uid = UID_OFFSET_SIGNALS + uid;
      break;
    case EV_BLOCK:
    case EV_BLOCK_CMD:
    case EV_BUTTON:
    case EV_SWITCH:
      prefix = MQTT_TOPIC_SENSOR;
      payload = sensorStateToPayload(data1);
      /* data0 is index; LCOS UID = offset + index (blocks 0–7, button/switch 67–82) */
      topic_uid = (event == EV_BLOCK || event == EV_BLOCK_CMD) ? (UID_OFFSET_BLOCKS + uid) : (UID_OFFSET_CONTROL_OBJECTS + uid);
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
