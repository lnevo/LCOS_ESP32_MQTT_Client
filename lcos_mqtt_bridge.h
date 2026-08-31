/**
 * LCOS JMRI/MQTT bridge — subscriptions, serial text/binary routing, heartbeat command.
 * Target board for this project: Arduino Nano (repo/folder name may still say ESP32).
 * Keep LCOS_ESP32_MQTT_Client.ino aligned with reference/LCOS_Client_Bare.ino (Beagle Bay v1.10); customize here.
 */
#ifndef LCOS_MQTT_BRIDGE_H
#define LCOS_MQTT_BRIDGE_H

#include <Arduino.h>
#include <lcos.h>

/* Older Arduino Library Manager lcos may lack these; values match lcos/lcos.h v1.0.10. */
#ifndef INCLUDE_NODE_EVENTS
#define INCLUDE_NODE_EVENTS 1
#endif
#ifndef INCLUDE_TURNOUT_EVENTS
#define INCLUDE_TURNOUT_EVENTS 2
#endif
#ifndef INCLUDE_SIGNAL_EVENTS
#define INCLUDE_SIGNAL_EVENTS 4
#endif
#ifndef INCLUDE_BLOCK_EVENTS
#define INCLUDE_BLOCK_EVENTS 8
#endif
#ifndef INCLUDE_CROSSING_EVENTS
#define INCLUDE_CROSSING_EVENTS 16
#endif
#ifndef INCLUDE_TURNTABLE_EVENTS
#define INCLUDE_TURNTABLE_EVENTS 32
#endif
#ifndef INCLUDE_SCENE_EVENTS
#define INCLUDE_SCENE_EVENTS 64
#endif
#ifndef INCLUDE_TRACK_POWER_EVENTS
#define INCLUDE_TRACK_POWER_EVENTS 128
#endif
#ifndef INCLUDE_BUTTON_EVENTS
#define INCLUDE_BUTTON_EVENTS 1024
#endif
#ifndef INCLUDE_SWITCH_EVENTS
#define INCLUDE_SWITCH_EVENTS 2048
#endif
#ifndef INCLUDE_SENSOR_EVENTS
#define INCLUDE_SENSOR_EVENTS 4096
#endif
#ifndef ALIGN_NONE
#define ALIGN_NONE 0
#endif
#ifndef ALIGN_MAIN
#define ALIGN_MAIN 1
#endif
#ifndef ALIGN_CLOSED
#define ALIGN_CLOSED 1
#endif
#ifndef ALIGN_DIVERGENT
#define ALIGN_DIVERGENT 2
#endif
#ifndef ALIGN_THROWN
#define ALIGN_THROWN 2
#endif
#ifndef ALIGN_ANY
#define ALIGN_ANY 3
#endif
#ifndef ALIGN_TOGGLE
#define ALIGN_TOGGLE 3
#endif

class gateway;

/*
 * LCOS operating **command request** byte for turnout/signal CMD datagrams: goes in `sendShortMessage`
 * `data1` (after `data0` = UID). Alignment (`ALIGN_*`) or aspect (`SIGNAL_*`) goes in `data2`. Last
 * `sendShortMessage` argument = 0 for a new command (not a response).
 *
 * **Source:** Beagle Bay LCOS operating API — same numeric values as the “Command requests” table in
 * this repo’s README.md (*CTC Functions → LCOS API*). Stock `lcos.h` from the author does not define
 * these names; they are provided here only for this MQTT bridge sketch. You may use the hex literals
 * directly (0x01, 0x02, …) if you prefer not to depend on this header.
 */
#define LCOS_CMD_GET_STATE            0x01
#define LCOS_CMD_SET_STATE_NO_LOCK    0x02
#define LCOS_CMD_SET_STATE_WITH_LOCK  0x03
#define LCOS_CMD_RELEASE_LOCK         0x7F

#define MQTT_BRIDGE_SYS_ID "LCOS MQTT bridge (JMRI) — subscriptions to nodes 4, 3, 13"

void mqtt_bridge_setup_subscriptions(lcos_layout *layout, uint16_t sourceNode);
void mqtt_bridge_poll_serial(lcos_layout *layout, LCMNetwork *net, gateway *serial_gw);
void mqtt_bridge_print_subscription_result(const DATAGRAM *pkt);

#endif
