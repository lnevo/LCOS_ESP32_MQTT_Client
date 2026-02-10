/**
 * mqtt_serial.cpp
 * MQTT-formatted serial output for LCOS → JMRI bridge.
 * Protocol: <topic><space><payload>\n (LF only). See todo.txt SERIAL OUTPUT PROTOCOL.
 */

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

const char *sensorStateToPayload(byte data1) {
  return data1 == 0 ? "INACTIVE" : "ACTIVE";
}

const char *powerStateToPayload(byte data1) {
  return data1 == 0 ? "OFF" : "ON";
}

// LCOS operations event codes we publish (turnouts, sensors, lights only)
#define EV_TURNOUT      0x02
#define EV_BUTTON       0x0B
#define EV_SWITCH       0x0C
#define EV_TURNOUT_CMD  0x10

// Internal: print full turnout payload (event, from, to, d0-d6, cr).
static void debugTurnoutPayload(Print &out, byte event, uint16_t from_node, uint16_t to_node,
  byte d0, byte d1, byte d2, byte d3, byte d4, byte d5, byte d6, byte cr) {
  out.print(F("DBG TURNOUT event="));
  out.print((int)event);
  out.print(F(" from="));
  out.print(from_node);
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
  mqttPublishOperationEvent(out, pkt, false);
}

void mqttPublishOperationEvent(Print &out, const DATAGRAM *pkt, bool debug) {
  if (pkt == nullptr) return;

  byte event = pkt->event;
  uint16_t node = pkt->source_node;
  byte uid = pkt->data0;
  byte data1 = pkt->data1;
  byte data2 = pkt->data2;

  if (debug && (event == EV_TURNOUT || event == EV_TURNOUT_CMD)) {
    debugTurnoutPayload(out, event, node, pkt->to_node, uid, data1, data2,
      pkt->data3, pkt->data4, pkt->data5, pkt->data6, pkt->cmd_response);
  }

  char topic[32];
  const char *payload = nullptr;
  const char *prefix = nullptr;

  switch (event) {
    case EV_TURNOUT:
    case EV_TURNOUT_CMD:
      prefix = MQTT_TOPIC_TURNOUT;
      /* Node sends d1=d2=2 for CLOSED, d1=d2=1 for THROWN; map to JMRI 0=CLOSED 1=THROWN */
      payload = turnoutStateToPayload((data1 == 1) ? 1 : 0);
      break;
    case EV_BUTTON:
    case EV_SWITCH:
      prefix = MQTT_TOPIC_SENSOR;
      payload = sensorStateToPayload(data1);
      break;
    // lights: add case when LCOS event is defined
    default:
      return;
  }

  if (prefix && payload) {
    mqttTopicWithPackedAddress(topic, sizeof(topic), prefix, node, uid);
    mqttPublish(out, topic, payload);
  }
}
