# AGENTS.md — lcos-bridge

Nano firmware and the serial-to-MQTT bridge for the HART layout. These rules apply to every tool; detail is in `.cursor/rules/`.

- **Bridge:** `serial_to_mqtt.py` is operator-owned. On the Windows mini PC it runs in the background (`LcosBridge` task at boot, output in `logs/bridge.log`), controlled with `bridge start|stop|restart|status|log`. If a lab test needs the COM port, `bridge stop` first and `bridge start` before ending the turn; otherwise ask the user to `bridge restart`.
- **Vendor source:** do not edit `lcos/` or `reference/` without explicit instruction and confirmation. API and protocol truth comes from `lcos/lcos.h`, `lcos/lcos.cpp` and the reference sketch, not `README.md`.
- **Git:** commit and push when a task is done, unless told not to. Agents use an `agent/...` branch, not `main`.
- **Layout hub:** the `hart` repo, where this is the `external/lcos-bridge` submodule.
