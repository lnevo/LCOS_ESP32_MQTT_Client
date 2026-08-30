#!/usr/bin/env python3
"""Unit tests for SerialSyncWatchdog (no hardware)."""

from __future__ import annotations

import time
import unittest

from serial_to_mqtt import SerialSyncWatchdog


class TestSerialSyncWatchdog(unittest.TestCase):
    def test_ack_miss_triggers_recovery(self) -> None:
        w = SerialSyncWatchdog(
            enabled=True,
            ack_fail_limit=3,
            resubscribe_cooldown_sec=0.0,
            reopen_cooldown_sec=0.0,
        )
        w.note_turnout_ack(False)
        w.note_turnout_ack(False)
        self.assertIsNone(w.take_reopen_request())
        w.note_turnout_ack(False)
        self.assertEqual(w.take_reopen_request(), "ack-miss-3")
        self.assertEqual(w.take_resubscribe_request(), "ack-miss-3")

    def test_ack_ok_resets_streak(self) -> None:
        w = SerialSyncWatchdog(enabled=True, ack_fail_limit=3)
        w.note_turnout_ack(False)
        w.note_turnout_ack(False)
        w.note_turnout_ack(True)
        w.note_turnout_ack(False)
        self.assertIsNone(w.take_reopen_request())

    def test_boot_banner_requests_resubscribe(self) -> None:
        w = SerialSyncWatchdog(
            enabled=True, resubscribe_cooldown_sec=0.0, reopen_cooldown_sec=0.0
        )
        w.note_serial_line("LCOS Integration Library, ver 1.0.10")
        self.assertEqual(w.take_resubscribe_request(), "nano-boot-banner")

    def test_ping_ack_clears_awaiting(self) -> None:
        w = SerialSyncWatchdog(enabled=True, ping_interval_sec=0.0)
        self.assertTrue(w.maybe_queue_usb_ping())
        w.note_serial_line("ACK PING")
        # Immediate second ping: prior ACK cleared awaiting, so no miss streak reopen.
        self.assertTrue(w.maybe_queue_usb_ping())
        self.assertIsNone(w.take_reopen_request())

    def test_disabled_noop(self) -> None:
        w = SerialSyncWatchdog(enabled=False, ack_fail_limit=1)
        w.note_turnout_ack(False)
        self.assertIsNone(w.take_reopen_request())


if __name__ == "__main__":
    unittest.main()
