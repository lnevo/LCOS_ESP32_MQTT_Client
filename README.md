# LCOS Library - User Guide

**LCOS (Layout Control Operating System) Integration Library**  
Version 1.0.9  
Copyright 2022-26 Beagle Bay Inc

**Repository note:** The project name still includes **ESP32** for historical reasons; the **JMRI/MQTT bridge sketch and host tooling** in this repository are built around an **Arduino Nano** on USB serial. LCOS itself runs on many Arduino-class boards—see [Hardware Requirements](#hardware-requirements).

### MQTT / JMRI serial bridge (Python)

This repo includes **`serial_to_mqtt.py`**, which connects the **Arduino Nano** USB serial port to an MQTT broker. On **Windows**, install Python 3, then `pip install -r requirements.txt`; full steps and test commands are in **[docs/serial_mqtt_windows.md](docs/serial_mqtt_windows.md)**. For **Cursor / VS Code** import hints, use a repo-local **`.venv`** and **`pyproject.toml`** (see that doc). Work toward **JMRI-sized command support** (binary host ↔ Nano, strings only in Python) is planned in **[docs/jmri_host_protocol_plan.md](docs/jmri_host_protocol_plan.md)** (branch **`feature/jmri-host-protocol`**).

## Table of Contents

1. [Overview](#overview)
2. [Installation](#installation)
3. [Basic Setup](#basic-setup)
4. [Network Configuration](#network-configuration)
5. [Event Handling](#event-handling)
6. [CTC Functions](#ctc-functions)
7. [Sending Commands](#sending-commands)
8. [Network Communication](#network-communication)
9. [Operating Modes](#operating-modes)
10. [Examples](#examples)

---

## Overview

LCOS is a distributed control system for model railroa0d layouts using nRF24L01 radio modules. The library provides a network protocol for coordinating turnouts, signals, blocks, routes, and other layout objects across multiple Arduino nodes.

### Key Features

- **Wireless Network**: Uses nRF24L01 radio modules for mesh networking
- **Distributed Control**: Multiple nodes can control and monitor layout objects
- **Event-Driven**: Asynchronous event system for status updates and commands
- **CTC Support**: Built-in support for Centralized Traffic Control functions
- **Scalable**: Supports hierarchical network topologies with up to 5 children per node

### Library Components

- **lcos_layout**: Main layout control object
- **LCMNetwork**: Low-level network communication
- **Event Handlers**: Callback functions for processing network events
- **DATAGRAM**: Message structure for network communication

---

## Installation

1. Place the `lcos` folder in your Arduino `libraries` directory
2. Ensure you have the RF24 and RF24Network libraries installed
3. Include the library in your sketch:

```cpp
#include <lcos.h>
```

### Hardware Requirements

- **This repository:** **Arduino Nano** as the LCOS node that speaks USB serial to `serial_to_mqtt.py` (project folder name retains “ESP32” for history only).
- **LCOS generally:** Arduino-compatible boards (Uno, Nano, ESP32, etc.)
- nRF24L01 radio module
- Radio pin definitions (defaults in `radio.h`):
  - `RADIO_CE`: Pin 9 (default)
  - `RADIO_CSN`: Pin 10 (default)

---

## Basic Setup

### Minimal Example

```cpp
#include <lcos.h>

// Configuration
byte channel = 75;           // Radio channel (0-125)
uint16_t thisNode = 05;      // Node address (octal)
byte childMap = 0;            // Child node map (bit flags)
byte configType = CONFIG_TYPE_CUSTOM_CLIENT;

// Global layout object
lcos_layout *layout;

void setup() {
  Serial.begin(115200);
  
  // Create and initialize layout
  layout = new lcos_layout(channel, thisNode, childMap);
  layout->setNodeType(configType);
  layout->begin();
  
  if (!layout->isStarted()) {
    Serial.println("Network failed to start!");
    return;
  }
  
  Serial.println("LCOS Network Started");
}

void loop() {
  // Must call update() frequently to process network messages
  layout->update();
  
  // Your application code here
}
```

### Required Event Handlers

You must implement these callback functions in your sketch:

```cpp
void handleOperationsEvents(DATAGRAM *pkt) {
  // Handle operations events (turnouts, signals, blocks, etc.)
  switch(pkt->event) {
    case EVENT_TURNOUT:      // 0x2
      // Turnout status changed
      break;
    case EVENT_SIGNAL:       // 0x3
      // Signal status changed
      break;
    case EVENT_BLOCK:        // 0x4
      // Block status changed
      break;
    // ... other events
  }
}

void handleGetSet(DATAGRAM *pkt) {
  // Handle configuration events
  // Usually responds to queries about node configuration
}
```

---

## Network Configuration

### Node Addressing

LCOS uses octal addressing (base 8) for nodes:
- **Master Node**: 00 (root of network)
- **Direct Children**: 01-07
- **Second Level**: 010-077
- **Third Level**: 0100-0777
- **Fourth Level**: 01000-07777

### Channel Configuration

```cpp
byte channel = 75;  // Radio channel (0-125)
// Default configuration channel is 75
```

### Node Types

```cpp
CONFIG_TYPE_STANDARD_CLIENT  // 1 - Standard layout node
CONFIG_TYPE_SCENE_CLIENT      // 2 - Scene control node
CONFIG_TYPE_YARD_CLIENT       // 3 - Yard control node
CONFIG_TYPE_DCC_CLIENT        // 4 - DCC command station
CONFIG_TYPE_JMRI_CLIENT       // 8 - JMRI interface node
CONFIG_TYPE_DCCPP_CLIENT      // 9 - DCC++ interface node
CONFIG_TYPE_CUSTOM_CLIENT     // 14 - Custom application
CONFIG_TYPE_MASTER            // 15 - Master control node
```

### Child Node Mapping

The `childMap` parameter uses bit flags to define child nodes:

```cpp
// Example: Node has children at positions 0, 2, and 4
byte childMap = 0b00010101;  // Bits 0, 2, 4 set
```

---

## Event Handling

### Event Types

LCOS uses three event types:

1. **Operations Events** (`ETYPE_OPERATING = 1`)
   - Layout object status and commands
   - Turnouts, signals, blocks, power, etc.

2. **Configuration Events** (`ETYPE_CONFIGURATION = 14`)
   - Node configuration queries
   - Settings get/set operations

3. **System Events** (`ETYPE_SYSTEM = 15`)
   - System-level operations
   - Clock synchronization, mode changes, etc.

### DATAGRAM Structure

```cpp
struct DATAGRAM {
  bool broadcast;        // true = broadcast to all nodes
  uint16_t from_node;   // Node that sent the message
  uint16_t source_node; // Original source node
  uint16_t to_node;     // Destination node (0 = broadcast)
  byte event_type;      // Event type (OPERATING, CONFIGURATION, SYSTEM)
  byte event;           // Specific event code
  byte data0;           // UID (object identifier)
  byte data1;           // Primary data/value
  byte data2;           // Secondary data
  byte data3;           // Additional data
  byte data4;           // Additional data
  byte data5;           // Additional data
  byte data6;           // Additional data
  byte cmd_response;    // Command/response identifier
};
```

### Processing Events

Events are automatically routed to the appropriate handler:

```cpp
void handleOperationsEvents(DATAGRAM *pkt) {
  byte uid = pkt->data0;      // Object UID
  byte state = pkt->data1;    // Object state
  
  switch(pkt->event) {
    case EVENT_TURNOUT:  // 0x2
      if (state == 0) {
        // Turnout is CLOSED
      } else {
        // Turnout is THROWN
      }
      break;
      
    case EVENT_BLOCK:  // 0x4
      if (state == 0) {
        // Block is CLEAR
      } else {
        // Block is OCCUPIED
      }
      break;
  }
}
```

---

## CTC Functions

**Centralized Traffic Control (CTC)** functions are built into LCOS for managing complex railroad operations. These functions allow you to control routes, signals, blocks, and turnouts in a coordinated manner.

### LCOS API (authoritative notes)

- **UIDs are static.** A UID map defines assignments; a UID reliably addresses specific objects on a node so long as those objects exist.
- **Bridging:** When bridging LCOS to an external system (e.g. JMRI), dedicate a node to that connection so the bridge is "just another node" on the LCOS network.

#### Turnout and Signal commands (lock semantics)

- **Commands:** Operations Event `0x10` (Turnout Command), `0x11` (Signal Command).
- **Status (listen):** Turnout status on Operations Event `0x2`; Signal status on Operations Event `0x3`.

**Command functions** (e.g. in `cmd_response` or as specified by the protocol):

| Value | Meaning |
|-------|--------|
| `0x1` | Get State |
| `0x2` | Set State without Lock |
| `0x3` | Set State with Lock |
| `0x7f` | Release Lock |

Lock/release for signals is not yet implemented; for turnouts it is only partially implemented. Semantics are the same for both when implemented. Lock authority: MASTER has automatic lock/release rights; MASTER may delegate to another node (e.g. CTC). Whether any node can issue lock commands or only MASTER/designated is a design decision.

**State options (data1):**

- **Turnouts:** `0x1` = Align closed/main, `0x2` = Align thrown/divergent, `0x3` = Toggle.
- **Signals:** `0x0` = OFF, `0x1` = Stop, `0x2` = Clear, `0x3` = Approach/Caution.

### UID Offsets for CTC Objects

LCOS uses predefined UID ranges for different object types:

```cpp
UID_OFFSET_BLOCKS          // 0-7: Block occupancy sensors
UID_OFFSET_TURNOUTS        // 8-15: Turnout controls
UID_OFFSET_ROUTES          // 16-31: Route definitions
UID_OFFSET_SIGNALS         // 32-47: Signal controls
UID_OFFSET_CROSSINGS       // 48-49: Grade crossing controls
UID_OFFSET_MPOS            // 50: Multi-position objects
UID_OFFSET_RELAYS          // 51-66: Relay controls
UID_OFFSET_CONTROL_OBJECTS // 67-82: Control panel objects
UID_OFFSET_SCENE_OBJECTS   // 83+: Scene/preset objects
```

### Route Commands

Routes coordinate multiple turnouts and signals to establish a path through the layout.

#### Sending a Route Command

```cpp
// Activate route 20 (UID = 16 + route number)
layout->sendShortMessage(
  true,                           // broadcast = true
  0,                              // destination (0 = broadcast)
  ETYPE_OPERATING,                // event type
  EVENT_GLOBAL_ROUTE_CMD,         // 0x17 - Route command
  20,                             // Route UID (UID_OFFSET_ROUTES + route number)
  1,                              // data1: 1 = activate, 0 = deactivate
  0,                              // data2: additional route data
  0                               // responding_to: 0 for new commands
);
```

#### Receiving Route Commands

```cpp
void handleOperationsEvents(DATAGRAM *pkt) {
  switch(pkt->event) {
    case EVENT_GLOBAL_ROUTE_CMD:  // 0x17
      {
        byte routeUID = pkt->data0;
        byte routeNumber = routeUID - UID_OFFSET_ROUTES;
        bool activate = (pkt->data1 != 0);
        
        if (activate) {
          // Activate route: set turnouts and signals
          activateRoute(routeNumber);
        } else {
          // Deactivate route
          deactivateRoute(routeNumber);
        }
      }
      break;
  }
}
```

### Signal Control

Signals display aspects to control train movement.

#### Setting Signal Aspect

```cpp
// Set signal 5 to aspect 2 (e.g., "Approach")
layout->sendShortMessage(
  true,                    // broadcast
  0,                       // destination
  ETYPE_OPERATING,
  EVENT_SIGNAL_CMD,        // 0x11
  UID_OFFSET_SIGNALS + 5,  // Signal UID
  2,                       // Aspect number
  0,                       // Additional data
  0                        // responding_to
);
```

#### Receiving Signal Commands

```cpp
void handleOperationsEvents(DATAGRAM *pkt) {
  switch(pkt->event) {
    case EVENT_SIGNAL:     // 0x3 - Signal status
    case EVENT_SIGNAL_CMD: // 0x11 - Signal command
      {
        byte signalUID = pkt->data0;
        byte signalNumber = signalUID - UID_OFFSET_SIGNALS;
        byte aspect = pkt->data1;
        
        // Update signal display
        setSignalAspect(signalNumber, aspect);
      }
      break;
  }
}
```

### Block Occupancy

Blocks detect train presence and coordinate signals and turnouts.

#### Reporting Block Status

```cpp
// Report block 3 as occupied
layout->broadcastOpState(
  EVENT_BLOCK,                    // 0x4
  UID_OFFSET_BLOCKS + 3,          // Block UID
  1,                              // 1 = occupied, 0 = clear
  0                               // Additional data
);
```

#### Receiving Block Status

```cpp
void handleOperationsEvents(DATAGRAM *pkt) {
  switch(pkt->event) {
    case EVENT_BLOCK:  // 0x4
      {
        byte blockUID = pkt->data0;
        byte blockNumber = blockUID - UID_OFFSET_BLOCKS;
        bool occupied = (pkt->data1 != 0);
        
        // Update block status
        updateBlockStatus(blockNumber, occupied);
        
        // CTC logic: update signals based on block occupancy
        if (occupied) {
          // Set signal to stop if block ahead is occupied
          setSignalAspect(getSignalForBlock(blockNumber), 0); // Stop
        }
      }
      break;
  }
}
```

### Turnout Control

Turnouts (switches) route trains between tracks.

#### Setting Turnout Position

```cpp
// Set turnout 2 to THROWN position
layout->sendShortMessage(
  true,                           // broadcast
  0,                              // destination
  ETYPE_OPERATING,
  EVENT_TURNOUT_CMD,              // 0x10
  UID_OFFSET_TURNOUTS + 2,        // Turnout UID
  1,                              // 1 = THROWN, 0 = CLOSED
  0,                              // Additional data
  0                               // responding_to
);
```

#### Receiving Turnout Status

```cpp
void handleOperationsEvents(DATAGRAM *pkt) {
  switch(pkt->event) {
    case EVENT_TURNOUT:     // 0x2 - Turnout status
    case EVENT_TURNOUT_CMD: // 0x10 - Turnout command
      {
        byte turnoutUID = pkt->data0;
        byte turnoutNumber = turnoutUID - UID_OFFSET_TURNOUTS;
        bool thrown = (pkt->data1 != 0);
        
        // Update turnout position
        setTurnoutPosition(turnoutNumber, thrown);
      }
      break;
  }
}
```

### Track Power Control

Control main track power for the entire layout.

#### Setting Track Power

```cpp
// Turn track power ON
layout->sendShortMessage(
  true,                    // broadcast
  0,                       // destination
  ETYPE_OPERATING,
  EVENT_TRACK_PWR_CMD,     // 0x15
  0,                       // UID not used for power
  1,                       // 1 = ON, 0 = OFF
  0,                       // Additional data
  0                        // responding_to
);
```

#### Receiving Power Status

```cpp
void handleOperationsEvents(DATAGRAM *pkt) {
  switch(pkt->event) {
    case EVENT_TRACK_POWER:    // 0x6 - Power status
    case EVENT_TRACK_PWR_CMD:  // 0x15 - Power command
      {
        bool powerOn = (pkt->data1 != 0);
        
        // Update power control
        setTrackPower(powerOn);
      }
      break;
  }
}
```

### Complete CTC Example: Route Activation

This example shows how to implement a complete route activation that coordinates turnouts and signals:

```cpp
void activateRoute(byte routeNumber) {
  // Example route: Main line through station
  // Route requires: Turnout 1 CLOSED, Turnout 3 THROWN
  // Signal 2 shows CLEAR, Signal 4 shows APPROACH
  
  byte routeUID = UID_OFFSET_ROUTES + routeNumber;
  
  // Step 1: Set turnouts
  layout->sendShortMessage(true, 0, ETYPE_OPERATING, 
    EVENT_TURNOUT_CMD, UID_OFFSET_TURNOUTS + 1, 0, 0, 0);  // Turnout 1 CLOSED
  
  layout->sendShortMessage(true, 0, ETYPE_OPERATING,
    EVENT_TURNOUT_CMD, UID_OFFSET_TURNOUTS + 3, 1, 0, 0);  // Turnout 3 THROWN
  
  // Step 2: Set signals
  layout->sendShortMessage(true, 0, ETYPE_OPERATING,
    EVENT_SIGNAL_CMD, UID_OFFSET_SIGNALS + 2, 3, 0, 0);    // Signal 2 CLEAR
  
  layout->sendShortMessage(true, 0, ETYPE_OPERATING,
    EVENT_SIGNAL_CMD, UID_OFFSET_SIGNALS + 4, 2, 0, 0);    // Signal 4 APPROACH
  
  // Step 3: Broadcast route activation
  layout->sendShortMessage(true, 0, ETYPE_OPERATING,
    EVENT_GLOBAL_ROUTE_CMD, routeUID, 1, 0, 0);            // Activate route
}

void handleOperationsEvents(DATAGRAM *pkt) {
  switch(pkt->event) {
    case EVENT_GLOBAL_ROUTE_CMD:  // 0x17
      {
        byte routeUID = pkt->data0;
        byte routeNumber = routeUID - UID_OFFSET_ROUTES;
        bool activate = (pkt->data1 != 0);
        
        if (activate) {
          activateRoute(routeNumber);
        }
      }
      break;
  }
}
```

---

## Sending Commands

### Using `sendShortMessage()`

The primary method for sending commands:

```cpp
bool sendShortMessage(
  bool multicast,        // true = broadcast, false = point-to-point
  uint16_t dest,         // Destination node (0 if multicast)
  byte et,               // Event type (ETYPE_OPERATING, etc.)
  byte event,            // Event code (EVENT_TURNOUT_CMD, etc.)
  byte uid,              // Object UID
  byte data1,            // Primary data
  byte data2,            // Secondary data
  byte responding_to     // Command being responded to (0 for new)
);
```

### Using `broadcastOpState()`

Convenience function for broadcasting object state:

```cpp
void broadcastOpState(
  byte event,    // Event code (EVENT_TURNOUT, EVENT_BLOCK, etc.)
  byte uid,      // Object UID
  byte data1,    // Primary state
  byte data2     // Secondary data
);
```

### Example: Sending a Turnout Command

```cpp
// Broadcast turnout command to all nodes
layout->sendShortMessage(
  true,                           // broadcast
  0,                              // destination (ignored if broadcast)
  ETYPE_OPERATING,                // operations event
  EVENT_TURNOUT_CMD,              // turnout command
  UID_OFFSET_TURNOUTS + 5,        // Turnout 5
  1,                              // 1 = THROWN, 0 = CLOSED
  0,                              // no secondary data
  0                               // not responding to another command
);
```

---

## Network Communication

### Getting Network Information

```cpp
LCMNetwork *net = layout->getNetworkObject();

uint16_t nodeID = net->getNodeID();      // This node's address
byte channel = net->getChannel();        // Radio channel
uint16_t parent = net->getParent();      // Parent node address
byte numChildren = net->numChildren();   // Number of child nodes
```

### Sending Point-to-Point Messages

```cpp
// Send message to specific node
DATAGRAM msg;
msg.source_node = layout->getNetworkObject()->getNodeID();
msg.to_node = 03;  // Destination node
msg.event_type = ETYPE_OPERATING;
msg.event = EVENT_TURNOUT_CMD;
msg.data0 = UID_OFFSET_TURNOUTS + 1;
msg.data1 = 1;  // THROWN
// ... set other fields

layout->getNetworkObject()->emitEvent(false, 03, &msg);
```

### Broadcasting Messages

```cpp
// Broadcast to all nodes
DATAGRAM msg;
// ... set message fields
layout->getNetworkObject()->emitEvent(true, 0, &msg);
```

---

## Operating Modes

LCOS supports different operating modes:

```cpp
OP_MODE_CONFIGURATION  // 16 - Configuration mode
OP_MODE_NORMAL        // 32 - Normal operations
OP_MODE_SUSPEND       // 64 - Suspended operations
OP_MODE_ERROR         // 128 - Error/emergency stop
```

### Setting Operating Mode

```cpp
layout->setOpMode(OP_MODE_NORMAL);
byte currentMode = layout->getOpMode();
```

### Mode Changes via System Events

The system can change modes via network commands:

```cpp
void handleSystemEvents(DATAGRAM *pkt) {
  switch(pkt->event) {
    case 10: // Set operating mode
      layout->setOpMode(pkt->data0);
      break;
    case 12: // Resume suspended operations
      layout->setOpMode(OP_MODE_NORMAL);
      break;
    case 13: // Suspend operations
      layout->setOpMode(OP_MODE_SUSPEND);
      break;
    case 15: // EMERGENCY OFF
      layout->setOpMode(OP_MODE_ERROR);
      break;
  }
}
```

---

## Examples

### Example 1: Simple Turnout Control

```cpp
#include <lcos.h>

lcos_layout *layout;

void setup() {
  Serial.begin(115200);
  layout = new lcos_layout(75, 05, 0);
  layout->setNodeType(CONFIG_TYPE_CUSTOM_CLIENT);
  layout->begin();
}

void loop() {
  layout->update();
  
  // Toggle turnout 1 every 5 seconds
  static unsigned long lastToggle = 0;
  static bool turnoutState = false;
  
  if (millis() - lastToggle > 5000) {
    turnoutState = !turnoutState;
    layout->sendShortMessage(true, 0, ETYPE_OPERATING,
      EVENT_TURNOUT_CMD, UID_OFFSET_TURNOUTS + 1, 
      turnoutState ? 1 : 0, 0, 0);
    lastToggle = millis();
  }
}

void handleOperationsEvents(DATAGRAM *pkt) {
  // Handle incoming events
}
```

### Example 2: Block Occupancy Monitor

```cpp
void handleOperationsEvents(DATAGRAM *pkt) {
  if (pkt->event == EVENT_BLOCK) {
    byte blockNumber = pkt->data0 - UID_OFFSET_BLOCKS;
    bool occupied = (pkt->data1 != 0);
    
    Serial.print("Block ");
    Serial.print(blockNumber);
    Serial.print(" is now ");
    Serial.println(occupied ? "OCCUPIED" : "CLEAR");
    
    // CTC logic: Set signal based on block occupancy
    if (occupied) {
      // Block occupied - set signal to stop
      layout->sendShortMessage(true, 0, ETYPE_OPERATING,
        EVENT_SIGNAL_CMD, UID_OFFSET_SIGNALS + blockNumber,
        0, 0, 0);  // Aspect 0 = Stop
    }
  }
}
```

### Example 3: Route Control Panel

```cpp
// Function to activate a predefined route
void activateRoute(byte routeNum) {
  // Route definitions (example)
  struct Route {
    byte turnoutUID;
    byte turnoutState;
    byte signalUID;
    byte signalAspect;
  };
  
  // Route 1: Main line through station
  Route route1[] = {
    {UID_OFFSET_TURNOUTS + 1, 0, UID_OFFSET_SIGNALS + 2, 3},
    {UID_OFFSET_TURNOUTS + 3, 1, UID_OFFSET_SIGNALS + 4, 2}
  };
  
  // Set all turnouts and signals for route
  for (int i = 0; i < 2; i++) {
    layout->sendShortMessage(true, 0, ETYPE_OPERATING,
      EVENT_TURNOUT_CMD, route1[i].turnoutUID,
      route1[i].turnoutState, 0, 0);
      
    layout->sendShortMessage(true, 0, ETYPE_OPERATING,
      EVENT_SIGNAL_CMD, route1[i].signalUID,
      route1[i].signalAspect, 0, 0);
  }
  
  // Broadcast route activation
  layout->sendShortMessage(true, 0, ETYPE_OPERATING,
    EVENT_GLOBAL_ROUTE_CMD, UID_OFFSET_ROUTES + routeNum,
    1, 0, 0);
}
```

---

## Additional Resources

### Event Codes Reference

**Operations Events:**
- `EVENT_NODE` (0x1) - Node status
- `EVENT_TURNOUT` (0x2) - Turnout status
- `EVENT_SIGNAL` (0x3) - Signal status
- `EVENT_BLOCK` (0x4) - Block status
- `EVENT_CROSSINGS` (0x5) - Crossing status
- `EVENT_TRACK_POWER` (0x6) - Track power status
- `EVENT_MPO` (0x7) - Multi-position object
- `EVENT_BUTTON` (0xB) - Button press
- `EVENT_SWITCH_CONTACT` (0xC) - Switch contact
- `EVENT_TURNOUT_CMD` (0x10) - Turnout command
- `EVENT_SIGNAL_CMD` (0x11) - Signal command
- `EVENT_CROSSING_CMD` (0x12) - Crossing command
- `EVENT_TRACK_PWR_CMD` (0x15) - Track power command
- `EVENT_BLOCK_CMD` (0x16) - Block command
- `EVENT_GLOBAL_ROUTE_CMD` (0x17) - Route command

### Constants Reference

- `PACKET_SIZE` = 15 bytes
- `MAX_CHILDREN` = 5
- `MAX_TRANSMIT_RETRIES` = 5
- `CONFIGURATION_CHANNEL` = 75

---

## Troubleshooting

### Network Not Starting

- Check radio module connections (CE, CSN pins)
- Verify radio module is working
- Check channel configuration
- Ensure node address is valid for network topology

### Messages Not Received

- Call `layout->update()` frequently in `loop()`
- Check that event handlers are implemented
- Verify node addresses are correct
- Check radio range and interference

### CTC Functions Not Working

- Verify UID offsets are correct
- Ensure route definitions match network expectations
- Check that all nodes are in `OP_MODE_NORMAL`
- Verify event handlers process route commands

---

## License

Copyright 2022-26 Beagle Bay Inc. All Rights Reserved.

---

## Support

For questions and support, refer to the LCOS documentation or contact Beagle Bay Inc.
