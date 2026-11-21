# AGENTS.md — lcos-bridge

Nano firmware and the serial-to-MQTT bridge for the HART layout. These rules apply to every tool; detail is in `.cursor/rules/`.

- **Bridge:** `serial_to_mqtt.py` is operator-owned and runs in the background on the layout host: on Linux (the layout Pi) the `lcos-bridge` systemd service, on Windows the `LcosBridge` task (output in `logs/bridge.log`). Control it with `./bridge start|stop|restart|status|log` (`bridge.cmd` on Windows). If a lab test needs the serial port, `bridge stop` first and `bridge start` before ending the turn; otherwise ask the user to `bridge restart`.
- **Vendor source:** do not edit `lcos/` or `reference/` without explicit instruction and confirmation. API and protocol truth comes from `lcos/lcos.h`, `lcos/lcos.cpp` and the reference sketch, not `README.md`.
- **Git:** commit and push when a task is done, unless told not to. Agents use an `agent/...` branch, not `main`.
- **Layout hub:** the `hart` repo, where this is the `external/lcos-bridge` submodule.
