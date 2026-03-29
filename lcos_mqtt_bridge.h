/**
 * LCOS JMRI/MQTT bridge — subscriptions, serial text/binary routing, heartbeat command.
 * Keep LCOS_ESP32_MQTT_Client.ino aligned with reference/LCOS_Client_Bare.ino; customize here.
 */
#ifndef LCOS_MQTT_BRIDGE_H
#define LCOS_MQTT_BRIDGE_H

#include <Arduino.h>
#include <lcos.h>
#include "gateways.h"

#define MQTT_BRIDGE_SYS_ID "LCOS MQTT bridge (JMRI) — subscriptions to nodes 4, 3, 13"

void mqtt_bridge_setup_subscriptions(lcos_layout *layout, uint16_t sourceNode);
void mqtt_bridge_poll_serial(lcos_layout *layout, LCMNetwork *net, gateway *serial_gw);
void mqtt_bridge_print_subscription_result(const DATAGRAM *pkt);

#endif
