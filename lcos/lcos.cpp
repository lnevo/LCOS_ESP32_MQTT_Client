/**************************************************************************
 * LCOS Integration Library
 * @version 1.0.9
 * 1.8.2026
 * LCOS Version 1.1
 * LCOS Protocol Version 1.0
 * nRF2401 Radio Communications & Networking
 * Copyright 2020-26 Beagle Bay Inc
 * All Rights Reserved
 **************************************************************************/
#include "Arduino.h"
#include "lcos.h"
#include "radio.h"
#include <nRF24L01.h>
#include <RF24.h>
#include <RF24Network.h>

// Initialize the Radio 
RF24 radio(RADIO_CE, RADIO_CSN); // nRF24L01
RF24Network radioNet(radio);

int freeMemory() {
	char top;
	#ifdef __arm__
	return &top - reinterpret_cast<char*>(sbrk(0));
	#elif defined(CORE_TEENSY) || (ARDUINO > 103 && ARDUINO != 151)
	return &top - __brkval;
	#else  // __arm__
	return __brkval ? &top - __brkval : &top - __malloc_heap_start;
	#endif  // __arm__
}

/***********************************************
 * Implementations
 */
lcos_layout::lcos_layout(byte channel, uint16_t nodeID, byte children){
  this->_layoutNet = new LCMNetwork(channel, nodeID, children); 
  this->_opMode = OP_MODE_NORMAL;
  _netStarted = false; 
}
void lcos_layout::begin(){
   _netStarted = _layoutNet->begin();
}
String lcos_layout::getVersionString(){
   String ver = F(LIBVERSION);
   return ver;
}
void lcos_layout::setNodeType(byte data){
  _node_type = data;
}
byte lcos_layout::getNodeType(){
  return _node_type;
}
void lcos_layout::update(){
  if(_layoutNet->networkAvailable()) _layoutNet->handleNetComm();
}
void lcos_layout::setSession(byte data){
  _session = data;
}
byte lcos_layout::getSession(){
  return _session;
}
byte lcos_layout::getOpMode(){
  return _opMode;
}
void lcos_layout::setOpMode(byte data){
  _opMode = data;
}
byte lcos_layout::getChildMap(){
  return _layoutNet->getChildMap();
}
datetime lcos_layout::getLayoutTime(){
  return this->layout_time;
}   
void lcos_layout::setLayoutTime(uint16_t t, byte zone){
  this->layout_time.time = t;
  this->layout_time.tz = zone;
}
void lcos_layout::setLayoutDate(uint16_t y, byte m, byte d, byte wd){
  this->layout_time.year = y;
  this->layout_time.month = m;
  this->layout_time.day = d;
  this->layout_time.weekday = wd;
}
LCMNetwork *lcos_layout::getNetworkObject(){
  return this->_layoutNet;
}
LCMNetwork::LCMNetwork(byte channel, uint16_t address, byte children){
  _channel = channel;
  _thisNode = address;
  loadFamily(children);
}
bool LCMNetwork::networkAvailable(){
  return _radioAvailable;
}
byte LCMNetwork::numChildren(){
  return _numChildren;
}
byte LCMNetwork::getChannel(){
  return _channel;
}
void LCMNetwork::setChannel(byte channel){
  extern RF24 radio;
  _channel = channel;
  radio.setChannel(_channel);
}
uint16_t LCMNetwork::getParent(){
  return _parent;
}
uint16_t LCMNetwork::getChild(byte id){
  if(id < _numChildren){
    return _children[id];
  }
  return 0;
}
byte LCMNetwork::getChildMap(){
  return _childMap;
}
uint16_t LCMNetwork::getNodeID(){
  return _thisNode;
}
void LCMNetwork::loadFamily(byte children){
  float base;
  float exponent = 0;
  _numChildren = 0;
  _parent = 0;
  _childMap = children;
  if(_thisNode > 0){ // not node 00
    if(_thisNode > 512){
      _parent = _thisNode & 511;
      exponent = 3;
    } else if(_thisNode > 64){
      _parent = _thisNode & 63;
      exponent = 2;
    } else if(_thisNode > 8){
      _parent = _thisNode & 7;
      exponent = 1;
    } 
    base = pow(8, exponent);
    if(exponent < 3 && children > 0){
      for(int i = 0, j = 0; j < MAX_CHILDREN; i++){
        if(bitRead(children,i) == 1){
          if(base > 1){
            _children[j++] = _thisNode + ((i + 1) * base * 8) + 1;
          } else {
            _children[j++] = _thisNode + 8 + (i * base * 8 );
          }
           _numChildren++;
        }
      }
    }
  } else if(children > 0) { // this is master node 00
    for(int i = 0, j = 0; j < MAX_CHILDREN; i++){
      if(bitRead(children,i) == 1){
        _numChildren++;
        _children[j++] = 1 + _thisNode + i;
      }
    }
  }
}
bool LCMNetwork::begin(){
  radio.begin();
  if(!radio.isChipConnected()){
    _radioAvailable = false;
	Serial.println("Radio is not responding");
  } else {
    _radioAvailable = true;
    radio.setChannel(_channel);
    radio.setDataRate(RF24_2MBPS); 
    radio.setPALevel(RF24_PA_MAX);
    radioNet.begin(_thisNode);
    radioNet.multicastRelay = true;
  }
  return _radioAvailable;
}
void LCMNetwork::parseMessage(byte *data, DATAGRAM *dest) {
  dest->broadcast = (data[0] == 1);
  dest->source_node = word(data[1], data[2]);
  dest->to_node  = word(data[3], data[4]);
  dest->event_type = data[5];
  dest->event = data[6];
  dest->data0 = data[7];
  dest->data1 = data[8];
  dest->data2 = data[9];
  dest->data3 = data[10];
  dest->data4 = data[11];
  dest->data5 = data[12];
  dest->data6 = data[13];
  dest->cmd_response = data[14];
}
bool lcos_layout::isStarted(){
  return _netStarted;
}
void LCMNetwork::handleNetComm(){
  extern RF24Network radioNet;
  extern void handleConfigurationEvents(DATAGRAM *);
  extern void handleOperationsEvents(DATAGRAM *);
  extern void handleSystemEvents(DATAGRAM *);

  DATAGRAM pkt;
  byte packetBuffer[PACKET_SIZE + 1];

  radioNet.update();
  while( radioNet.available() ) {     // Is there any incoming data for this node?
    RF24NetworkHeader header;
    radioNet.read(header, &packetBuffer, PACKET_SIZE);
    parseMessage(packetBuffer, &pkt);
    pkt.from_node = header.from_node;
    if(!pkt.broadcast && pkt.to_node != _thisNode){
      emitEvent(0, pkt.to_node, &pkt); // redirect if to_node is not this node 
    } else {
      switch(header.type){
        case 'A': // event type 0x1, Operations
          handleOperationsEvents(&pkt);
          break;
        case 'N': // event type 0xe, Configuration
          handleGetSet(&pkt);
          break;
        case 'O': // event type 0xf, System
          handleSystemEvents(&pkt);
          break;
        default: 
          break;
      }
    }
  }
}
bool LCMNetwork::sendMessage(uint16_t to_node, byte *data, int bytes){
  extern RF24Network radioNet;
  boolean result = false;
  String packet = "";
  int count = 0;
  unsigned char mtype = data[5] + MESSAGE_TYPE_BASE;
  radioNet.update();
  RF24NetworkHeader header(to_node, mtype);
  do {
    result = radioNet.write(header, data, bytes);
    if(!result){
      radioNet.update();
      delayMicroseconds(random(15, 50));
    }
    count++;
  } while(!result && count < MAX_TRANSMIT_RETRIES);
  return result;
}
bool LCMNetwork::emitEvent(bool broadcast, uint16_t to_node, DATAGRAM *pkt){ 
  byte outBuffer[PACKET_SIZE + 1];
  bool result = false;
  outBuffer[0] = broadcast ? 1: 0;
  outBuffer[1] = highByte(pkt->source_node);
  outBuffer[2] = lowByte(pkt->source_node);
  outBuffer[3] = highByte(pkt->to_node);
  outBuffer[4] = lowByte(pkt->to_node);
  outBuffer[5] = pkt->event_type;
  outBuffer[6] = pkt->event;
  outBuffer[7] = pkt->data0;
  outBuffer[8] = pkt->data1;
  outBuffer[9] = pkt->data2;
  outBuffer[10] = pkt->data3;
  outBuffer[11] = pkt->data4;
  outBuffer[12] = pkt->data5;
  outBuffer[13] = pkt->data6;
  outBuffer[14] = pkt->cmd_response;
  
  if(broadcast){ // Send to the MASTER for multicasting
    result = this->sendMessage(00, outBuffer, PACKET_SIZE);
  } else { // node to node
    result = sendMessage(to_node, outBuffer, PACKET_SIZE);
  }
  return result;
}
void LCMNetwork::processSerialEvent(DATAGRAM *pkt){
  switch(pkt->event_type){
    case ETYPE_OPERATING:
      handleOperationsEvents(pkt);
      break;
    case ETYPE_CONFIGURATION:
      handleGetSet(pkt);
      break;
    case ETYPE_SYSTEM:
      handleSystemEvents(pkt);
      break;
    default:
      break;
  }
}
void lcos_layout::broadcastOpState(byte event, byte uid, byte data1, byte data2){
  sendShortMessage(true, 0, ETYPE_OPERATING, event, uid, data1, data2, 0);
}
bool lcos_layout::sendShortMessage(bool multicast, uint16_t dest, byte et, byte event, byte uid, byte data1, byte data2, byte responding_to){
  extern RF24Network radioNet;
  bool result;
  DATAGRAM out;
  out.to_node = dest;
  out.source_node = _layoutNet->getNodeID();
  out.event_type = et;
  out.event = event;
  out.data0 = uid;
  out.data1 = data1;
  out.data2 = data2;
  out.data3 = 0;
  out.data4 = 0;
  out.data5 = 0;
  out.data6 = 0;
  out.cmd_response = responding_to;
  result = this->_layoutNet->emitEvent(multicast, dest, &out);
  radioNet.update();
  return result;
}
///////////////////////////////////////
// SYSTEM EVENT HANDLER
//////////////////////////////////////
void handleClockEvents(DATAGRAM *pkt){
  extern lcos_layout *layout; 
  byte h, m, z;
  h = pkt->data0;
  m = pkt->data1;
  z = pkt->data2;
  layout->setLayoutTime(uint16_t(int(h) * 100) + int(m), z);
}
void handleSystemEvents(DATAGRAM *pkt){
  extern lcos_layout *layout;
  LCMNetwork *layoutNet;
  layoutNet = layout->getNetworkObject();
  DATAGRAM out;
  out.to_node = pkt->source_node;
  out.source_node = layoutNet->getNodeID();
  out.event_type = ETYPE_SYSTEM;
  out.event = pkt->event;
  switch(int(pkt->event)){
    case 1: // fast clock time signal
      handleClockEvents(pkt);
      break;
    case 2: // fast clock date change
      layout->setLayoutDate(word(pkt->data4, pkt->data3), pkt->data1, pkt->data2, pkt->data0);
      break;
    case 3: // real time clock change
    case 4: // real time date change
    case 5: // System Settings
    case 6: // reserved
    case 7: // reserved
    case 8: // reserved
      break;
    case 9:  // system recognition query
      out.data0 = EVENT_ACK;
      out.data1 = layout->getOpMode();
      out.data2 = LIBMAJORV; // major version
      out.data3 = LIBMINORV; // minor version
      out.data4 = LIBBUILD; // build
      out.data5 = layout->getNodeType();
      out.data6 = layout->getChildMap();
      out.cmd_response = pkt->data0;
      delayMicroseconds(random(1, 20));
      layoutNet->emitEvent(0, pkt->from_node, &out);
      //layout->setSession(pkt->data6);
      break;
    case 10: // set operating mode
      layout->setOpMode(pkt->data0);
      break;
    case 11: // system restart
      reboot();
      break;
    case 12: // resume suspended operations
      layout->setOpMode(OP_MODE_NORMAL);
      break;
    case 13: // suspend operations
      layout->setOpMode(OP_MODE_SUSPEND);
      break;
    case 14: // clear emergency OFF
      layout->setOpMode(OP_MODE_NORMAL);
      break;
    case 15: // EMERGENCY OFF
      layout->setOpMode(OP_MODE_ERROR);
      break;
  }
}

///////////////////////////////////////
// REBOOT FUNCTION
//////////////////////////////////////
void(* resetFunc)(void) = 0;  //declare reset function @ address 0
void reboot(){
  unsigned long cm, del;
  // delay before restart
  cm = millis();
  del = cm + random(25, 100);
  while(cm < del){
    radioNet.update();
    cm = millis();
  }
  resetFunc();
}
