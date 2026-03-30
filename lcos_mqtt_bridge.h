/**
 * LCOS JMRI/MQTT bridge — subscriptions, serial text/binary routing, heartbeat command.
 * Target board for this project: Arduino Nano (repo/folder name may still say ESP32).
 * Keep LCOS_ESP32_MQTT_Client.ino aligned with reference/LCOS_Client_Bare.ino (Beagle Bay v1.10); customize here.
 */
#ifndef LCOS_MQTT_BRIDGE_H
#define LCOS_MQTT_BRIDGE_H

#include <Arduino.h>
#include <lcos.h>

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
