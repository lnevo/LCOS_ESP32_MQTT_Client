# Bridge sync note

Firmware/agent restored to **pre–Digicon signalhead** baseline (`af51a20`).

There is no Digicon `sml_mode` / `track/signalhead` forwarding in this tree.
Field `EVENT_SIGNAL` → MQTT `track/signalmast/` may still publish via `mqtt_serial.cpp`
if the layout emits signal status.

HBLOOP-era and Digicon-era snapshots may still exist under `docs/archive/` from later work.
