/**
 * mqtt_serial.cpp
 * MQTT-formatted serial output for LCOS → JMRI bridge.
 * Protocol: <topic><space><payload>\n (LF only). See todo.txt SERIAL OUTPUT PROTOCOL.
 */

#include "mqtt_serial.h"
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

void mqttPublishOperationEvent(Print &out, byte event, uint16_t node, byte uid, byte data1, byte data2) {
  char topic[32];
  const char *payload = nullptr;
  const char *prefix = nullptr;

  switch (event) {
    case EV_TURNOUT:
    case EV_TURNOUT_CMD:
      prefix = MQTT_TOPIC_TURNOUT;
      /* Node uses data2: 0 = thrown, non-zero = closed (invert for JMRI 0=CLOSED 1=THROWN) */
      payload = turnoutStateToPayload(data2 == 0 ? 1 : 0);
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
