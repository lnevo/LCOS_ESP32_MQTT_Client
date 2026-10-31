# AGENTS.md — lcos-bridge

Nano firmware and the serial-to-MQTT bridge for the HART layout. These rules apply to every tool; detail is in `.cursor/rules/`.

- **Bridge:** `serial_to_mqtt.py` is operator-owned and runs in a visible foreground console. Start it only for a lab test, stop it before ending the turn, and ask the user to restart it (`.\run_serial_mqtt.cmd verbose`).
- **Vendor source:** do not edit `lcos/` or `reference/` without explicit instruction and confirmation. API and protocol truth comes from `lcos/lcos.h`, `lcos/lcos.cpp` and the reference sketch, not `README.md`.
- **Git:** commit and push when a task is done, unless told not to. Agents use an `agent/...` branch, not `main`.
- **Layout hub:** the `hart` repo, where this is the `external/lcos-bridge` submodule.
