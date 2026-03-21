/////////////////////////////////////////
// LCOS.h
// @VERSION 1.0.9
// 1.8.26
// Arduino library for LCOS Integration, version 1.0
// LCOS Version 1.0
// LCOS Protocol v1.0
// Copyright 2022-26 Beagle Bay Inc
/////////////////////////////////////////
// inhibit multiple inclusions
#ifndef LCOS
#define LCOS
#include "Arduino.h"
int freeMemory();
#define LIBMAJORV 1
#define LIBMINORV 0
#define LIBBUILD 9
#define LIBVERSION "LCOS Integration Library, ver 1.0.9"

#ifdef __arm__
// could use uinstd.h to define sbrk but Due causes a conflict
extern "C" char* sbrk(int incr);
#else  // __ARM__
extern char *__brkval;
#endif  // __arm__
// defines for setting and clearing register bits
#ifndef cbi
#define cbi(sfr, bit) (_SFR_BYTE(sfr) &= ~_BV(bit))
#endif
#ifndef sbi
#define sbi(sfr, bit) (_SFR_BYTE(sfr) |= _BV(bit))
#endif

/////////////////////////////////////////
// Network
/////////////////////////////////////////
#define MAX_TRANSMIT_RETRIES 5
#define PACKET_SIZE 15
#define MAX_CHILDREN 5
#define CHAR_PACKET_START "~"
#define CHAR_PACKET_END "^"
#define MESSAGE_TYPE_BASE 64
#define CONFIGURATION_CHANNEL 75

/////////////////////////////////////////
// Configuration
/////////////////////////////////////////
#define EVENT_ERROR 0x7E
#define EVENT_ACK 0x7F

#define CONFIG_TYPE_STANDARD_CLIENT 1
#define CONFIG_TYPE_SCENE_CLIENT 2
#define CONFIG_TYPE_YARD_CLIENT 3
#define CONFIG_TYPE_DCC_CLIENT 4
#define CONFIG_TYPE_JMRI_CLIENT 8
#define CONFIG_TYPE_DCCPP_CLIENT 9
#define CONFIG_TYPE_CUSTOM_CLIENT 14
#define CONFIG_TYPE_MASTER 15

#define OP_MODE_CONFIGURATION 16
#define OP_MODE_NORMAL 32
#define OP_MODE_SUSPEND 64
#define OP_MODE_ERROR 128

///////////////////////////////////////
// UID OFFSETS
///////////////////////////////////////
#define UID_OFFSET_BLOCKS 0
#define UID_OFFSET_TURNOUTS 8
#define UID_OFFSET_ROUTES 16
#define UID_OFFSET_SIGNALS 32
#define UID_OFFSET_CROSSINGS 48
#define UID_OFFSET_MPOS 50
#define UID_OFFSET_RELAYS 51
#define UID_OFFSET_CONTROL_OBJECTS 67
#define UID_OFFSET_SCENE_OBJECTS 83

///////////////////////////////////////
// EVENTS
//////////////////////////////////////
#define ETYPE_OPERATING 1
#define ETYPE_CONFIGURATION 14
#define ETYPE_SYSTEM 15
#define MSG_TYPE_OPERATING 'A'
#define MSG_TYPE_CONFIGURATION 'N'
#define MSG_TYPE_SYSTEM 'O'
#define EVENT_NODE 0x1
#define EVENT_TURNOUT 0x2
#define EVENT_SIGNAL 0x3
#define EVENT_BLOCK 0x4
#define EVENT_CROSSINGS 0x5
#define EVENT_TRACK_POWER 0x6
#define EVENT_MPO 0x7
#define EVENT_SCENE_OBJECT 0x8
#define EVENT_RFID 0x9
#define EVENT_BUTTON 0xB
#define EVENT_SWITCH_CONTACT 0xC
#define EVENT_SENSOR 0xD
#define EVENT_TURNOUT_CMD 0x10
#define EVENT_SIGNAL_CMD 0x11
#define EVENT_CROSSING_CMD 0x12
#define EVENT_SCENE_CMD 0x13
#define EVENT_CONTROL_CMD 0x14
#define EVENT_TRACK_PWR_CMD 0x15
#define EVENT_BLOCK_CMD 0x16
#define EVENT_GLOBAL_ROUTE_CMD 0x17
// Command functions for EVENT_TURNOUT_CMD / EVENT_SIGNAL_CMD (e.g. cmd_response)
#define CMD_FUNC_GET_STATE   0x1
#define CMD_FUNC_SET_NO_LOCK 0x2
#define CMD_FUNC_SET_WITH_LOCK 0x3
#define CMD_FUNC_RELEASE_LOCK 0x7f
// Turnout state (data1): 0x1 closed/main, 0x2 thrown/divergent, 0x3 toggle
// Signal state (data1): 0x0 OFF, 0x1 Stop, 0x2 Clear, 0x3 Approach/Caution
////////////////////////////////////////
// TYPES
////////////////////////////////////////
struct DATAGRAM {
  bool broadcast;
  uint16_t from_node;
  uint16_t source_node;
  uint16_t to_node;
  byte event_type;
  byte event;
  byte data0;
  byte data1;
  byte data2;
  byte data3;
  byte data4;
  byte data5;
  byte data6;
  byte cmd_response;
};
struct datetime {
  unsigned int time; // 24 hour
  word year; 
  byte month; // 0 - 11
  byte day; // 1 - 31
  byte weekday; // 0 - 6 where 0 == Monday
  byte tz; // zone: 0 - 6
};

typedef void (*callback_function)(DATAGRAM *);

////////////////////////////////////////
// CLASS DECLARATIONS
////////////////////////////////////////
class LCMNetwork
{
  public:
    LCMNetwork(byte, uint16_t, byte);
    bool begin();
    bool networkAvailable();
    void handleNetComm(void);       
    bool emitEvent(bool, uint16_t, DATAGRAM *);
    uint16_t getChild(byte);
    uint16_t getParent();
    byte numChildren();
    byte getChannel();
    void setChannel(byte);
    uint16_t getNodeID();
    byte getChildMap();
    void parseMessage(byte *, DATAGRAM *);
    void processSerialEvent(DATAGRAM *);
  private:
    bool _radioAvailable;
    byte _channel;
    byte _numChildren;
    byte _childMap;
    uint16_t _thisNode;
    uint16_t _parent;
    uint16_t _children[MAX_CHILDREN];
    void loadFamily(byte);
    bool sendMessage(uint16_t, byte *, int);    
};
class lcos_layout{
  private:
    LCMNetwork *_layoutNet;
    datetime layout_time;
    byte _node_type;
    byte _session;
    byte _opMode;
    boolean _netStarted;
  public:
    lcos_layout(byte channel, uint16_t address, byte children);
    void begin();
    String getVersionString();
    bool isStarted();
    void setSession(byte);
    byte getSession();
    void setNodeType(byte);
    byte getNodeType();
    byte getOpMode();
    void setOpMode(byte);
    byte getChildMap();
    LCMNetwork *getNetworkObject();
    datetime getLayoutTime();
    void setLayoutTime(uint16_t, byte);
    void setLayoutDate(uint16_t, byte, byte, byte);
    void broadcastOpState(byte, byte, byte, byte);
    bool sendShortMessage(bool, uint16_t, byte, byte, byte, byte, byte, byte);
    void update();
};

////////////////////////////////////////
// MISC Prototypes
////////////////////////////////////////
void reboot();
extern void handleOperationsEvents(DATAGRAM *) __attribute__ ( (weak));
extern void handleGetSet(DATAGRAM *) __attribute__ ( (weak));
void handleSystemEvents(DATAGRAM *);
#endif
