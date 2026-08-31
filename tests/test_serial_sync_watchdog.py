#!/usr/bin/env python3
"""Unit tests for SerialSyncWatchdog (no hardware)."""

from __future__ import annotations

import io
import time
import unittest
from contextlib import redirect_stderr

from serial_to_mqtt import SerialSyncWatchdog


class TestSerialSyncWatchdog(unittest.TestCase):
    def test_ack_miss_triggers_recovery(self) -> None:
        w = SerialSyncWatchdog(
            enabled=True,
            ack_fail_limit=3,
            resubscribe_cooldown_sec=0.0,
            reopen_cooldown_sec=0.0,
            hbloop_enabled=False,
        )
        w.note_turnout_ack(False)
        w.note_turnout_ack(False)
        self.assertIsNone(w.take_reopen_request())
        w.note_turnout_ack(False)
        self.assertEqual(w.take_reopen_request(), "ack-miss-3")
        self.assertEqual(w.take_resubscribe_request(), "ack-miss-3")

    def test_ack_ok_resets_streak(self) -> None:
        w = SerialSyncWatchdog(enabled=True, ack_fail_limit=3, hbloop_enabled=False)
        w.note_turnout_ack(False)
        w.note_turnout_ack(False)
        w.note_turnout_ack(True)
        w.note_turnout_ack(False)
        self.assertIsNone(w.take_reopen_request())

    def test_boot_banner_arms_thin_accept_not_immediate_resub(self) -> None:
        w = SerialSyncWatchdog(
            enabled=True,
            resubscribe_cooldown_sec=0.0,
            reopen_cooldown_sec=0.0,
            boot_accept_grace_sec=0.05,
            expect_subscription_accepts=2,
            hbloop_enabled=False,
        )
        w.note_serial_line("LCOS Integration Library, ver 1.0.10")
        self.assertIsNone(w.take_resubscribe_request())
        time.sleep(0.08)
        w.maybe_finish_boot_subscription_verify()
        self.assertEqual(w.take_resubscribe_request(), "nano-boot-banner")

    def test_ping_ack_clears_awaiting(self) -> None:
        w = SerialSyncWatchdog(
            enabled=True, ping_interval_sec=0.0, hbloop_enabled=False
        )
        self.assertTrue(w.maybe_queue_usb_ping())
        w.note_serial_line("ACK PING")
        self.assertTrue(w.maybe_queue_usb_ping())
        self.assertIsNone(w.take_reopen_request())

    def test_hbloop_first_miss_logs_without_resubscribe(self) -> None:
        w = SerialSyncWatchdog(
            enabled=True,
            hbloop_enabled=True,
            hbloop_interval_sec=0.0,
            hbloop_fail_limit=3,
            resubscribe_cooldown_sec=0.0,
        )
        self.assertTrue(w.maybe_queue_hbloop_probe())  # first probe
        buf = io.StringIO()
        with redirect_stderr(buf):
            self.assertTrue(w.maybe_queue_hbloop_probe())  # miss 1
        self.assertIn("HBLOOP miss (1/3)", buf.getvalue())
        self.assertIsNone(w.take_resubscribe_request())

    def test_hbloop_established_then_lost_no_resubscribe(self) -> None:
        w = SerialSyncWatchdog(
            enabled=True,
            hbloop_enabled=True,
            hbloop_interval_sec=0.0,
            hbloop_fail_limit=3,
            resubscribe_cooldown_sec=0.0,
        )
        self.assertTrue(w.maybe_queue_hbloop_probe())
        w.note_hbloop_echo("echo")
        # Next probe arms await; then three misses → lost. Never RESUBSCRIBE.
        for _ in range(4):
            w.maybe_queue_hbloop_probe()
        self.assertIsNone(w.take_resubscribe_request())
        self.assertFalse(w._hbloop_established)

    def test_disabled_noop(self) -> None:
        w = SerialSyncWatchdog(enabled=False, ack_fail_limit=1, hbloop_enabled=False)
        w.note_turnout_ack(False)
        self.assertIsNone(w.take_reopen_request())


if __name__ == "__main__":
    unittest.main()
