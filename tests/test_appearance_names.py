"""The bridge accepts JMRI's appearance names (the standard) and hands the firmware its tokens."""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# serial_to_mqtt imports pyserial and paho at load; stand-ins keep this test offline.
if "serial" not in sys.modules:
    serial_mod = types.ModuleType("serial")
    serial_mod.SerialException = type("SerialException", (Exception,), {})
    sys.modules["serial"] = serial_mod
if "paho" not in sys.modules:
    paho = types.ModuleType("paho")
    mqtt = types.ModuleType("paho.mqtt")
    client = types.ModuleType("paho.mqtt.client")
    client.Client = object
    client.MQTTv311 = 4
    mqtt.client = client
    paho.mqtt = mqtt
    sys.modules.update({"paho": paho, "paho.mqtt": mqtt, "paho.mqtt.client": client})

import serial_to_mqtt as bridge  # noqa: E402


class AppearanceNames(unittest.TestCase):
    def test_jmri_flashing_names_become_firmware_tokens(self) -> None:
        f = bridge.normalize_signalhead_appearance
        self.assertEqual(f("Flashing Red"), "FlashRed")
        self.assertEqual(f("flashing yellow"), "FlashYellow")
        self.assertEqual(f("Flashing  Green "), "FlashGreen")
        self.assertEqual(f("Flashing Lunar"), "FlashLunar")

    def test_other_payloads_pass_unchanged(self) -> None:
        f = bridge.normalize_signalhead_appearance
        for body in ("Red", "FlashRed", "Unheld", "Get", "Flashing Purple"):
            self.assertEqual(f(body), body)

    def test_normalized_names_are_accepted(self) -> None:
        for jmri in ("Flashing Red", "Flashing Yellow", "Flashing Green", "Flashing Lunar"):
            token = bridge.normalize_signalhead_appearance(jmri)
            self.assertIsNotNone(bridge._SIGNALHEAD_APPEARANCE_RE.match(token), token)
        self.assertIsNone(bridge._SIGNALHEAD_APPEARANCE_RE.match("Flashing Red"))


if __name__ == "__main__":
    unittest.main()
