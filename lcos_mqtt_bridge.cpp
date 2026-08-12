/**
 * LCOS JMRI/MQTT bridge implementation (see lcos_mqtt_bridge.h).
 */
#include <stdlib.h>
#include <string.h>
#include "lcos_mqtt_bridge.h"
#include "gateways.h"
#include "mqtt_serial.h"

/* Must match serial_to_mqtt.py CMD_TURNOUT_TOPIC + "/" and MQTT_TOPIC_CMD_TURNOUT in mqtt_serial.h */
#define CMD_TURNOUT_PREFIX "track/cmd/turnout/"
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
  uint16_t jmriNode = (uint16_t)(packed_ul / 100u);
  uint16_t lcosNode = mqttDisplayNodeToLcosNode(jmriNode);
  byte uid = (byte)(packed_ul % 100u);
  byte align;
  if (streq_ci(end, "CLOSED")) {
    align = (byte)ALIGN_CLOSED;
  } else if (streq_ci(end, "THROWN")) {
    align = (byte)ALIGN_THROWN;
  } else if (streq_ci(end, "TOGGLE")) {
    align = (byte)ALIGN_TOGGLE;
  } else {
    return;
  }
  layout->sendShortMessage(false, lcosNode, ETYPE_OPERATING, EVENT_TURNOUT_CMD,
    uid, LCOS_CMD_SET_STATE_NO_LOCK, align, 0);
  layout->update();
}

/* JMRI Virtual head: track/signalhead/IH<packed> Red|Yellow|Green|Dark|… */
#define SIGNALHEAD_PREFIX "track/signalhead/"
#define SIGNALHEAD_PREFIX_LEN (sizeof(SIGNALHEAD_PREFIX) - 1)
#define SIGNALHEAD_IH_TOKEN "IH"
#define SIGNALHEAD_IH_TOKEN_LEN 2

/**
 * Map appearance name → LCOS SIGNAL_* for EVENT_SIGNAL_CMD data2.
 * Red→Stop, Yellow→Approach, Green→Clear. Dark/Off→0.
 */
static bool appearanceToLcosAspect(const char *name, byte *aspect_out) {
  if (name == NULL || aspect_out == NULL || *name == '\0') {
    return false;
  }
  if (streq_ci(name, "Red") || streq_ci(name, "FlashRed") || streq_ci(name, "Stop")) {
    *aspect_out = (byte)SIGNAL_STOP;
    return true;
  }
  if (streq_ci(name, "Yellow") || streq_ci(name, "FlashYellow") || streq_ci(name, "Lunar")
      || streq_ci(name, "FlashLunar") || streq_ci(name, "Approach")) {
    *aspect_out = (byte)SIGNAL_APPROACH;
    return true;
  }
  if (streq_ci(name, "Green") || streq_ci(name, "FlashGreen") || streq_ci(name, "Clear")) {
    *aspect_out = (byte)SIGNAL_CLEAR;
    return true;
  }
  if (streq_ci(name, "Dark") || streq_ci(name, "Off")) {
    *aspect_out = 0;
    return true;
  }
  return false;
}

/**
 * Status remapping publishes topic_uid = OFFSET + wire_uid (Signal 0 → MQTT …64 / IH464).
 * Digicon Virtual heads already use API UIDs 32–47 (IH433 → 33). Only reverse the remapped band 64–79.
 */
static byte mqttSignalUidToWireData0(byte mqtt_uid) {
  if (mqtt_uid >= (byte)(UID_OFFSET_SIGNALS * 2)) {
    return (byte)(mqtt_uid - (byte)UID_OFFSET_SIGNALS);
  }
  return mqtt_uid;
}

static void sendSignalCmd(lcos_layout *layout, uint16_t lcosNode, byte wire_uid,
                          byte cmd_req, byte aspect_or_zero) {
  layout->sendShortMessage(false, lcosNode, ETYPE_OPERATING, EVENT_SIGNAL_CMD,
    wire_uid, cmd_req, aspect_or_zero, 0);
  layout->update();
}

static void handleSignalHeadCmdFromSerialLine(lcos_layout *layout, const char *rest) {
  if (layout == NULL || rest == NULL) {
    return;
  }
  if (strncmp(rest, SIGNALHEAD_IH_TOKEN, SIGNALHEAD_IH_TOKEN_LEN) != 0) {
    return;
  }
  const char *num = rest + SIGNALHEAD_IH_TOKEN_LEN;
  char *end = NULL;
  unsigned long packed_ul = strtoul(num, &end, 10);
  if (end == num) {
    return;
  }
  while (*end == ' ') {
    end++;
  }
  if (*end == '\0') {
    return;
  }
  uint16_t jmriNode = (uint16_t)(packed_ul / 100u);
  uint16_t lcosNode = mqttDisplayNodeToLcosNode(jmriNode);
  byte mqtt_uid = (byte)(packed_ul % 100u);
  byte wire_uid = mqttSignalUidToWireData0(mqtt_uid);

  /* Public API signal CMD: 1=GET, 2=set, 3=RELEASE. Explicit payloads for probes. */
  if (streq_ci(end, "Release") || streq_ci(end, "Unheld")) {
    sendSignalCmd(layout, lcosNode, wire_uid, LCOS_SIGNAL_CMD_RELEASE, 0);
    return;
  }
  if (streq_ci(end, "Get") || streq_ci(end, "Query")) {
    sendSignalCmd(layout, lcosNode, wire_uid, LCOS_SIGNAL_CMD_GET, 0);
    return;
  }

  byte aspect;
  if (!appearanceToLcosAspect(end, &aspect)) {
    return;
  }
  /* Set aspect, then RELEASE so field auto logic is not left in command mode. */
  sendSignalCmd(layout, lcosNode, wire_uid, LCOS_SIGNAL_CMD_SET, aspect);
  sendSignalCmd(layout, lcosNode, wire_uid, LCOS_SIGNAL_CMD_RELEASE, 0);
}

/* Event 125 subscription mask — INCLUDE_* bits from lcos.h */
#define SUBSCRIBE_EVENT_MASK (INCLUDE_BLOCK_EVENTS | INCLUDE_TURNOUT_EVENTS | INCLUDE_SIGNAL_EVENTS \
  | INCLUDE_BUTTON_EVENTS | INCLUDE_SWITCH_EVENTS | INCLUDE_TRACK_POWER_EVENTS | INCLUDE_SENSOR_EVENTS)

/* JMRI display nodes (decimal digit string of RF24 octal addr). Mapped via mqttDisplayNodeToLcosNode. */
static const uint16_t kSubscribeDisplayNodes[] = { 1, 2, 3, 4, 12, 13 };

// --- Serial text: heartbeat from Python (serial_to_mqtt.py) ---
// Turnout line "track/cmd/turnout/<packed> ..." uses jmriNode*100+uid; mqttDisplayNodeToLcosNode() before sendShortMessage.
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
        } else if (layout != NULL && strncmp(s_serialLineBuf, SIGNALHEAD_PREFIX, SIGNALHEAD_PREFIX_LEN) == 0
            && s_serialLineBuf[SIGNALHEAD_PREFIX_LEN] != '\0') {
          handleSignalHeadCmdFromSerialLine(layout, s_serialLineBuf + SIGNALHEAD_PREFIX_LEN);
        } else if (layout != NULL && strcmp(s_serialLineBuf, HB_SERIAL_TOKEN) == 0) {
          /* Unicast to the turnout owner: multicast=true only sends to master (00) per LCMNetwork::emitEvent. */
          /* Turnout CMD: data1 = command request, data2 = ALIGN_*; see lcos_mqtt_bridge.h / README LCOS API table. */
          layout->sendShortMessage(false, HB_TURNOUT_NODE, ETYPE_OPERATING, EVENT_TURNOUT_CMD,
            (byte)HB_TURNOUT_UID, LCOS_CMD_SET_STATE_NO_LOCK, (byte)ALIGN_THROWN, 0);
          layout->update();
        }
      }
      s_serialLineLen = 0;
      /* Keep draining: Digicon often bursts several IH lines; one-per-call left them queued. */
      continue;
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
  for (unsigned i = 0; i < sizeof(kSubscribeDisplayNodes) / sizeof(kSubscribeDisplayNodes[0]); i++) {
    uint16_t lcosTarget = mqttDisplayNodeToLcosNode(kSubscribeDisplayNodes[i]);
    subscribeToNode(net, sourceNode, lcosTarget, SUBSCRIBE_EVENT_MASK);
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
