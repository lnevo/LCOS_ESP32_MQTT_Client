/**
 * LCOS JMRI/MQTT bridge implementation (see lcos_mqtt_bridge.h).
 */
#include <stdlib.h>
#include <string.h>
#include "lcos_mqtt_bridge.h"
#include "gateways.h"

/* Must match serial_to_mqtt.py CMD_TURNOUT_TOPIC and MQTT_TOPIC_CMD_TURNOUT in mqtt_serial.h */
#define CMD_TURNOUT_PREFIX "track/cmd/turnout "
#define CMD_TURNOUT_PREFIX_LEN (sizeof(CMD_TURNOUT_PREFIX) - 1)

static bool streq_ci(const char *a, const char *b) {
  for (; *a && *b; a++, b++) {
    char ca = *a;
    char cb = *b;
    if (ca >= 'a' && ca <= 'z') {
      ca = (char)(ca - 32);
    }
    if (cb >= 'a' && cb <= 'z') {
      cb = (char)(cb - 32);
    }
    if (ca != cb) {
      return false;
    }
  }
  return *a == *b;
}

static void handleTurnoutCmdFromSerialLine(lcos_layout *layout, const char *rest) {
  if (layout == NULL || rest == NULL) {
    return;
  }
  char *end = NULL;
  unsigned long packed_ul = strtoul(rest, &end, 10);
  if (end == rest) {
    return;
  }
  while (*end == ' ') {
    end++;
  }
  if (*end == '\0') {
    return;
  }
  uint16_t node = (uint16_t)(packed_ul / 100u);
  byte uid = (byte)(packed_ul % 100u);
  byte align;
  if (streq_ci(end, "CLOSED")) {
    align = (byte)ALIGN_CLOSED;
  } else if (streq_ci(end, "THROWN")) {
    align = (byte)ALIGN_THROWN;
  } else {
    return;
  }
  layout->sendShortMessage(false, node, ETYPE_OPERATING, EVENT_TURNOUT_CMD,
    uid, LCOS_CMD_SET_STATE_NO_LOCK, align, 0);
  layout->update();
}

/* Event 125 subscription mask — INCLUDE_* bits from lcos.h */
#define SUBSCRIBE_EVENT_MASK (INCLUDE_BLOCK_EVENTS | INCLUDE_TURNOUT_EVENTS | INCLUDE_SIGNAL_EVENTS \
  | INCLUDE_BUTTON_EVENTS | INCLUDE_SWITCH_EVENTS | INCLUDE_TRACK_POWER_EVENTS | INCLUDE_SENSOR_EVENTS)

static const uint16_t kSubscribeTargets[] = { 4, 3, 13 };

// --- Serial text: heartbeat from Python (serial_to_mqtt.py) ---
// sendShortMessage(..., dest, ..., uid, ...) uses RF24/LCOS node address as **decimal** (docs often show octal: 03=3, 010=8).
// Turnout index 0 => UID UID_OFFSET_TURNOUTS+0 (8). Replies on MQTT use pkt.source_node from the wire, not dest.
#define HB_SERIAL_TOKEN "PING"
#define HB_TURNOUT_NODE 3
#define HB_TURNOUT_UID 8

static char s_serialLineBuf[128];
static size_t s_serialLineLen = 0;

static void subscribeToNode(LCMNetwork *net, uint16_t sourceNode, uint16_t targetNode, uint16_t eventMask) {
  DATAGRAM out;
  out.source_node = sourceNode;
  out.to_node = 0;
  out.event_type = ETYPE_OPERATING;
  out.event = 125;
  out.data0 = highByte(eventMask);
  out.data1 = lowByte(eventMask);
  out.data2 = highByte(targetNode);
  out.data3 = lowByte(targetNode);
  out.data4 = 0;
  out.data5 = 0;
  out.data6 = 0;
  out.cmd_response = 0;
  net->emitEvent(false, 0, &out);
}

static void pollSerialTextLineForAck(lcos_layout *layout) {
  while (Serial.available()) {
    char ch = (char)Serial.read();
    if (ch == '\r') {
      continue;
    }
    if (ch == '\n') {
      s_serialLineBuf[s_serialLineLen] = '\0';
      if (s_serialLineLen > 0) {
        Serial.print(F("ACK "));
        Serial.println(s_serialLineBuf);
        if (layout != NULL && strncmp(s_serialLineBuf, CMD_TURNOUT_PREFIX, CMD_TURNOUT_PREFIX_LEN) == 0
            && s_serialLineBuf[CMD_TURNOUT_PREFIX_LEN] != '\0') {
          handleTurnoutCmdFromSerialLine(layout, s_serialLineBuf + CMD_TURNOUT_PREFIX_LEN);
        } else if (layout != NULL && strcmp(s_serialLineBuf, HB_SERIAL_TOKEN) == 0) {
          /* Unicast to the turnout owner: multicast=true only sends to master (00) per LCMNetwork::emitEvent. */
          /* Turnout CMD: data1 = command request, data2 = ALIGN_*; see lcos_mqtt_bridge.h / README LCOS API table. */
          layout->sendShortMessage(false, HB_TURNOUT_NODE, ETYPE_OPERATING, EVENT_TURNOUT_CMD,
            (byte)HB_TURNOUT_UID, LCOS_CMD_SET_STATE_NO_LOCK, (byte)ALIGN_THROWN, 0);
          layout->update();
        }
      }
      s_serialLineLen = 0;
      return;
    }
    if (s_serialLineLen < sizeof(s_serialLineBuf) - 1) {
      s_serialLineBuf[s_serialLineLen++] = (uint8_t)ch;
    } else {
      s_serialLineLen = 0;
    }
  }
}

void mqtt_bridge_setup_subscriptions(lcos_layout *layout, uint16_t sourceNode) {
  if (layout == NULL) {
    return;
  }
  LCMNetwork *net = layout->getNetworkObject();
  layout->update();
  for (unsigned i = 0; i < sizeof(kSubscribeTargets) / sizeof(kSubscribeTargets[0]); i++) {
    subscribeToNode(net, sourceNode, kSubscribeTargets[i], SUBSCRIBE_EVENT_MASK);
    layout->update();
  }
}

void mqtt_bridge_poll_serial(lcos_layout *layout, LCMNetwork *net, gateway *serial_gw) {
  if (!Serial.available()) {
    return;
  }
  int first = Serial.peek();
  if ((first == 0 || first == 1) && serial_gw != NULL && serial_gw->isEnabled() && serial_gw->isReadable()) {
    byte serialBuffer[PACKET_SIZE];
    uint8_t count = Serial.readBytes(serialBuffer, PACKET_SIZE);
    if (count > 0) {
      DATAGRAM pkt;
      net->parseMessage(serialBuffer, &pkt);
      pkt.source_node = serial_gw->getAddress();
      if (pkt.broadcast || pkt.to_node != net->getNodeID()) {
        if (serial_gw->isEnabled()) {
          net->emitEvent(serialBuffer[0], pkt.to_node, &pkt);
        }
      }
      if (pkt.broadcast || pkt.to_node == net->getNodeID()) {
        pkt.from_node = pkt.source_node;
        net->processSerialEvent(&pkt);
      }
    }
  } else {
    pollSerialTextLineForAck(layout);
  }
}

void mqtt_bridge_print_subscription_result(const DATAGRAM *pkt) {
  if (pkt->data6 == 1) {
    Serial.print(F("Subscription accepted - node: "));
    Serial.println(((uint16_t)pkt->data2 << 8) | pkt->data3, OCT);
  } else {
    Serial.print(F("Subscription declined - node: "));
    Serial.println(((uint16_t)pkt->data2 << 8) | pkt->data3, OCT);
  }
}
