from __future__ import annotations

import queue
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if "serial" not in sys.modules:
    serial_mod = types.ModuleType("serial")

    class SerialException(Exception):
        pass

    serial_mod.SerialException = SerialException
    sys.modules["serial"] = serial_mod

if "paho" not in sys.modules:
    paho = types.ModuleType("paho")
    mqtt = types.ModuleType("paho.mqtt")
    client = types.ModuleType("paho.mqtt.client")
    client.Client = object
    client.MQTTv311 = 4
    mqtt.client = client
    paho.mqtt = mqtt
    sys.modules["paho"] = paho
    sys.modules["paho.mqtt"] = mqtt
    sys.modules["paho.mqtt.client"] = client

from serial_to_mqtt import DIGICON_PACKED_HEADS, DigiconSmlGuard, SML_GUARD_RELEASE


class _FakePub:
    def wait_for_publish(self, timeout: float = 0.0) -> None:
        return None


class _FakeClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    def publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False):
        self.published.append((topic, str(payload)))
        return _FakePub()


class DigiconSmlGuardTest(unittest.TestCase):
    def test_packed_heads_are_432_only(self) -> None:
        self.assertEqual(DIGICON_PACKED_HEADS, ("432",))

    def test_second_offline_skipped_while_waiting(self) -> None:
        q: queue.Queue = queue.Queue()
        guard = DigiconSmlGuard(_FakeClient(), q, verbose=False, packed_heads=("432",))
        guard._last_mode = "enabled"
        guard._waiting = True
        guard.maybe_start_challenge("jmri-offline")
        self.assertTrue(q.empty())
        self.assertTrue(guard.is_in_flight())

    def test_second_offline_skipped_when_release_queued(self) -> None:
        q: queue.Queue = queue.Queue()
        guard = DigiconSmlGuard(_FakeClient(), q, verbose=False, packed_heads=("432",))
        guard._last_mode = "enabled"
        guard._release_queued = True
        guard.maybe_start_challenge("jmri-offline")
        self.assertTrue(q.empty())
        self.assertEqual(q.qsize(), 0)

    def test_timeout_queues_release_once(self) -> None:
        q: queue.Queue = queue.Queue()
        guard = DigiconSmlGuard(_FakeClient(), q, verbose=False, packed_heads=("432",))
        guard._last_mode = "enabled"
        guard._waiting = True
        guard._generation = 3
        guard._on_timeout(3)
        self.assertEqual(q.get_nowait(), SML_GUARD_RELEASE)
        self.assertTrue(q.empty())
        guard._on_timeout(3)
        self.assertTrue(q.empty())


if __name__ == "__main__":
    unittest.main()
