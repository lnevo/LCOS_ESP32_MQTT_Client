/***********************************************
 * LCOS_Client_Bare
 * LCOS - The Layout Control Operating System
 * System Version 1.0
 * Protocol Version 1.0
 * Library Version 1.0
 * Bare Client Node for LCOS Networks
 *
 * Global Variables Created and Used by LCOS Library:
 * RF24 radio; 
 * RF24Network radioNet;
 *
 */

/////////////////////////////////////////////////
// Event subscription masks (MASTER Event Distributor, event 125)
#define INCLUDE_NODE_EVENTS         1
#define INCLUDE_TURNOUT_EVENTS        2
#define INCLUDE_SIGNAL_EVENTS         4
#define INCLUDE_BLOCK_EVENTS          8
#define INCLUDE_CROSSING_EVENTS       16
#define INCLUDE_TURNTABLE_EVENTS      32
#define INCLUDE_SCENE_EVENTS          64
#define INCLUDE_TRACK_POWER_EVENTS    128
#define INCLUDE_BUTTON_EVENTS         1024
#define INCLUDE_SWITCH_EVENTS         2048
#define INCLUDE_SENSOR_EVENTS         4096

// Block, turnout, signal, button, switch, track power
#define SUBSCRIBE_EVENT_MASK (INCLUDE_BLOCK_EVENTS | INCLUDE_TURNOUT_EVENTS | INCLUDE_SIGNAL_EVENTS \
  | INCLUDE_BUTTON_EVENTS | INCLUDE_SWITCH_EVENTS | INCLUDE_TRACK_POWER_EVENTS)

/***********************************************
 * Header files
 */
#include <lcos.h>
#include "gateways.h"
#include "mqtt_serial.h"
#define ADDRESS_SERIAL 0xFFFF
#define SYS_ID "LCOS MQTT bridge (JMRI) — subscriptions to nodes 4, 3, 13"

// Basic Configuration Items
byte channel = 80;
uint16_t thisNode = 015;
byte childMap = 0;
byte configType = CONFIG_TYPE_CUSTOM_CLIENT;

// Global Variable for the LCOS layout object
lcos_layout *layout;
gateway *serial_gw;
byte opMode = OP_MODE_NORMAL;
byte errCode = 0;

/** Subscribe this node to operations events from a remote node (MASTER Event Distributor, event 125). */
static void subscribeToNode(LCMNetwork *net, uint16_t targetNode, uint16_t eventMask) {
  DATAGRAM out;
  out.source_node = thisNode;
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

// Serial input: LCOS binary gateway packets start with broadcast byte 0 or 1 (first byte of DATAGRAM).
// Any other first byte is treated as a text line (Serial Monitor) until LF; we ACK for testing.
static char s_serialLineBuf[128];
static size_t s_serialLineLen = 0;

static void pollSerialTextLineForAck() {
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

void setup() {
  // Create layout object
  layout = new lcos_layout(channel, thisNode, childMap);
  layout->setNodeType(configType);
  // setup Serial communications
  Serial.begin(115200);
  // call begin() to start the radio network
  layout->begin();
  if(!layout->isStarted()){
      opMode = OP_MODE_ERROR;
      errCode = 2;
      Serial.println("Unable to start the network.");
  }

  serial_gw = new gateway(3, ADDRESS_SERIAL);
  LCMNetwork *net = layout->getNetworkObject();
  Serial.println(LIBVERSION);
  Serial.println(SYS_ID);
  Serial.print(F("@<0"));
  Serial.print(net->getNodeID(), OCT);
  Serial.println(F(">"));

  layout->update();

  // Request subscriptions: block, turnout, signal, button, switch, track power from nodes 4, 3, 13
  const uint16_t subscribeTargets[] = { 4, 3, 13 };
  for (unsigned i = 0; i < sizeof(subscribeTargets) / sizeof(subscribeTargets[0]); i++) {
    subscribeToNode(net, subscribeTargets[i], SUBSCRIBE_EVENT_MASK);
    layout->update();
  }
}

void loop(){
  byte serialBuffer[PACKET_SIZE];
  DATAGRAM pkt;
  LCMNetwork *net = layout->getNetworkObject();
  ////////////////////////////////////////////////
  // Communications
  // Call the update() function frequently
  // to send/receive/relay network messages
  ///////////////////////////////////////////////
  layout->update(); 

  // Serial: LCOS binary packets start with byte 0 or 1 (broadcast). Anything else = text line (Serial Monitor).
  if (Serial.available()) {
    int first = Serial.peek();
    if ((first == 0 || first == 1) && serial_gw != NULL && serial_gw->isEnabled() && serial_gw->isReadable()) {
      uint8_t count = Serial.readBytes(serialBuffer, PACKET_SIZE);
      if (count > 0) {
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
      pollSerialTextLineForAck();
    }
  }
  ////////////////////////////////////////////////
  // Operations
  //////////////////////////////////////////////// 



}// end loop()

////////////////////////////////////////////////
// Event Handlers with Required Defaults
////////////////////////////////////////////////

void handleOperationsEvents(DATAGRAM *pkt){
  extern lcos_layout *layout;
  LCMNetwork *layoutNet;
  DATAGRAM out;
  boolean sendResponse = false;
  layoutNet = layout->getNetworkObject();

  mqttPublishOperationEvent(Serial, pkt);

  switch(pkt->event){
    case 1: // node status event
      break;
    case 2: // turnout status event
      break;
    case 3: // signal status event
      break;
    case 4: // block status event
      break;
    case 5: // crossing status event
      break;
    case 6: // track power status event
      break;
    case 7: // mpo status event
      break;
    case 8: // reserved
      break;
    case 9: // reserved
      break;
    case 10: //reserved
      break;
    case 11: // button status event
      break;
    case 12: // switch contact status event
      break;
    case 13: // reserved
      break;
    case 14: // reserved
      break;
    case 15: // reserved
      break;
    case 16: // turnout command
      break; 
    case 17: // signal command
      break;
    case 18: // crossing command
      break;
    case 19: // reserved
      break;
    case 20: // reserved
      break;
    case 21: // track power command
      break;
    case 22: // block command
      break;
    case 23: // Global Route Command
      break;
    case 125: // response to subscription requests (MASTER Event Distributor)
      if (pkt->data6 == 1) {
        Serial.print(F("Subscription accepted - node: "));
        Serial.println(((uint16_t)pkt->data2 << 8) | pkt->data3, OCT);
      } else {
        Serial.print(F("Subscription declined - node: "));
        Serial.println(((uint16_t)pkt->data2 << 8) | pkt->data3, OCT);
      }
      break;
  }
  // Nodes should not generally respond to OPS events except under special circumstances.
  if (sendResponse) {
    out.source_node = layoutNet->getNodeID();
    out.to_node = pkt->source_node;
    out.event_type = ETYPE_OPERATING;
    out.event = pkt->event;
    out.data0 = EVENT_ACK;
    out.data1 = 0;
    out.data2 = 0;
    out.data3 = 0;
    out.data4 = 0;
    out.data5 = 0;
    out.data6 = 0;
    out.cmd_response = pkt->data0;
    layoutNet->emitEvent(0, pkt->from_node, &out);
  }
}

void handleGetSet(DATAGRAM *pkt){
  extern lcos_layout *layout;
  extern uint16_t thisNode;
  uint16_t node;
  int dat;
  LCMNetwork *layoutNet;
  DATAGRAM out;
  layoutNet = layout->getNetworkObject();
  // prepare default response data
  out.source_node = layoutNet->getNodeID();
  out.to_node = pkt->source_node;
  out.event_type = ETYPE_CONFIGURATION;
  out.event = pkt->event;
  out.data0 = EVENT_ACK;
  out.data1 = pkt->data1;;
  out.data2 = 0;
  out.data3 = 0;
  out.data4 = 0;
  out.data5 = 0;
  out.data6 = 0;
  out.cmd_response = pkt->data0;
  // process the event
  switch(int(pkt->event)){
    case 1:
      out.data1 = configType;
      out.data2 = 0; // NA EEPROM LAYOUT
      out.data3 = layoutNet->getChannel();
      node = layoutNet->getNodeID();
      out.data4 = highByte(node);
      out.data5 = lowByte(node);
      break;
    case 2:
      out.data1 = LIBMAJORV;
      out.data2 = LIBMINORV;
      out.data3 = LIBBUILD;
      out.data4 = 1; // Lib Bit
      break;
    case 22: // free SRAM
      dat = freeMemory();
      out.data1 = highByte(dat);
      out.data2 = lowByte(dat);
      break;
    case 33: // get/set nodeID
      switch(pkt->data0){
        case 1:
          node = layoutNet->getNodeID();
          out.data1 = highByte(node);
          out.data2 = lowByte(node);
          break;
        case 2:
          node = word(pkt->data1, pkt->data2);
          // save to non-volatile storage, then reboot
          thisNode = node;
          layoutNet->emitEvent(0, pkt->from_node, &out);
          reboot();
          break;
      }
      break;
    case 46: // get/set radio channel
      switch(pkt->data0){
        case 1:
          out.data1 = layoutNet->getChannel();
          break;
        case 2:
          // save to non-volatile storage, then reboot
          layoutNet->emitEvent(0, pkt->from_node, &out);
          reboot();
      } 
      break;
    case 47: // get/set child node states
      switch(pkt->data0){
        case 1:
          out.data1 = childMap;
          break;
        case 2:
          // save to non-volatile storage,
          childMap = pkt->data1;
          break;
      } 
      break;
    case 77: // get / set Operations Mode
      switch(pkt->data0){
        case 1:
          out.data1 = layout->getOpMode();
          break;
        case 2:
          layout->setOpMode(pkt->data1);
          out.data1 = layout->getOpMode();
          break;
      }
      break;
    case 79: // reboot
      reboot();
      break;
    default:
      break;
  }
  // Send response
  layoutNet->emitEvent(0, pkt->from_node, &out);
}
///////////////////////////////////////////
// Gateway functions
///////////////////////////////////////////
void sendToGateways(DATAGRAM *pkt){ // dcc gateway isn't writable so not included
  extern gateway *serial_gw;
  if(serial_gw != NULL && serial_gw->isEnabled() && serial_gw->isWritable() && (pkt->broadcast == 1 || serial_gw->isThisGateway(pkt->to_node))){
    sendToSerialGateway(pkt);
  }
}
bool isGatewayHost(uint16_t addr){
  extern gateway *serial_gw;
  if(addr == 0) return (serial_gw != NULL);
  if(serial_gw != NULL && serial_gw->isThisGateway(addr)){
    return true;
  }
  return false;
}
boolean sendToSerialGateway(DATAGRAM *pkt){
  byte serialbuffer[PACKET_SIZE];
  String out = "";
  String comma = String(F(","));
  serialbuffer[0] = 0;
  serialbuffer[1] = highByte(pkt->source_node);
  serialbuffer[2] = lowByte(pkt->source_node);
  serialbuffer[3] = highByte(pkt->to_node);
  serialbuffer[4] = lowByte(pkt->to_node);
  serialbuffer[5] = pkt->event_type;
  serialbuffer[6] = pkt->event;
  serialbuffer[7] = pkt->data0;
  serialbuffer[8] = pkt->data1;
  serialbuffer[9] = pkt->data2;
  serialbuffer[10] = pkt->data3;
  serialbuffer[11] = pkt->data4;
  serialbuffer[12] = pkt->data5;
  serialbuffer[13] = pkt->data6;
  serialbuffer[14] = pkt->cmd_response;
  
  out += String(CHAR_PACKET_START);
  for(int i = 0; i < 15; i++){
    out += (comma);
    out += (String(serialbuffer[i]));
  }
  out += (String(F("^")));
  Serial.println(out);
  return true;
}
boolean sendToGatewayBinary(byte *buffer){
  for(int i = 0; i < 15; i++){
    Serial.print(buffer[i]);
  }
  Serial.println();
  return true;
}
