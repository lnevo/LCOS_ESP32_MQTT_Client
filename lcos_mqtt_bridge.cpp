/**
 * LCOS JMRI/MQTT bridge implementation (see lcos_mqtt_bridge.h).
 */
#include <string.h>
#include "lcos_mqtt_bridge.h"
#include "gateways.h"

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
        if (layout != NULL && strcmp(s_serialLineBuf, HB_SERIAL_TOKEN) == 0) {
          /* Unicast to the turnout owner: multicast=true only sends to master (00) per LCMNetwork::emitEvent. */
          /* lcos.h turnout alignment: ALIGN_MAIN/ALIGN_CLOSED = 1, ALIGN_THROWN/ALIGN_DIVERGENT = 2, etc. */
          /* cmd_response 0x02 = set state without lock (per LCOS command table / README). */
          layout->sendShortMessage(false, HB_TURNOUT_NODE, ETYPE_OPERATING, EVENT_TURNOUT_CMD,
            (byte)HB_TURNOUT_UID, (byte)ALIGN_THROWN, 0, 0x02);
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
