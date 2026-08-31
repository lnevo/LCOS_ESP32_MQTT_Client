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

    def test_hbloop_skips_probe_when_sensor_traffic_fresh(self) -> None:
        w = SerialSyncWatchdog(
            enabled=True,
            hbloop_enabled=True,
            hbloop_interval_sec=5.0,
            hbloop_fail_limit=1,
        )
        w.maybe_queue_hbloop_probe()
        w.note_hbloop_echo("echo")
        w.note_layout_traffic("track/sensor/470")
        self.assertFalse(w.maybe_queue_hbloop_probe())
        self.assertTrue(w.hbloop_is_established())

    def test_hbloop_lost_keeps_echoing_without_immediate_resub(self) -> None:
        """DCC/RF path down: lost once, quiet probes, no RESUBSCRIBE until minute gate."""
        w = SerialSyncWatchdog(
            enabled=True,
            hbloop_enabled=True,
            hbloop_interval_sec=0.0,
            hbloop_fail_limit=1,
            hbloop_retry_sec=1.0,
            resubscribe_cooldown_sec=0.0,
        )
        w.maybe_queue_hbloop_probe()
        w.note_hbloop_echo("echo")
        w.maybe_queue_hbloop_probe()
        buf = io.StringIO()
        with redirect_stderr(buf):
            w.maybe_queue_hbloop_probe()  # lost
            w.maybe_queue_hbloop_probe()  # recovering — still disarmed
            w.maybe_queue_hbloop_probe()
        text = buf.getvalue()
        self.assertEqual(text.count("HBLOOP lost"), 1)
        self.assertNotIn("HBLOOP miss", text)
        self.assertIsNone(w.take_resubscribe_request())
        # Echo returns before the gate — no RESUBSCRIBE.
        with redirect_stderr(buf):
            w.note_hbloop_echo("echo")
        self.assertIn("HBLOOP recovered", buf.getvalue())
        self.assertTrue(w.hbloop_is_established())
        self.assertIsNone(w.take_resubscribe_request())

    def test_hbloop_one_resub_per_minute_then_disarm_again(self) -> None:
        w = SerialSyncWatchdog(
            enabled=True,
            hbloop_enabled=True,
            hbloop_interval_sec=0.0,
            hbloop_fail_limit=1,
            hbloop_retry_sec=0.05,
            resubscribe_cooldown_sec=0.0,
        )
        w.maybe_queue_hbloop_probe()
        w.note_hbloop_echo("echo")
        w.maybe_queue_hbloop_probe()
        w.maybe_queue_hbloop_probe()  # lost; start 0.05s echo-only
        self.assertIsNone(w.take_resubscribe_request())
        time.sleep(0.06)
        buf = io.StringIO()
        with redirect_stderr(buf):
            w.maybe_queue_hbloop_probe()  # miss + one RESUBSCRIBE
        self.assertIn("HBLOOP miss", buf.getvalue())
        self.assertEqual(w.take_resubscribe_request(), "hbloop-miss-echo-gate")
        # Still in post-resub echo-only window — no second RESUBSCRIBE yet.
        w.maybe_queue_hbloop_probe()
        w.maybe_queue_hbloop_probe()
        self.assertIsNone(w.take_resubscribe_request())
        time.sleep(0.06)
        with redirect_stderr(buf):
            w.maybe_queue_hbloop_probe()  # next cycle's one RESUBSCRIBE
        self.assertEqual(w.take_resubscribe_request(), "hbloop-miss-echo-gate")

    def test_hbloop_cold_start_enters_cycle_not_permanent_disarm(self) -> None:
        w = SerialSyncWatchdog(
            enabled=True,
            hbloop_enabled=True,
            hbloop_interval_sec=0.0,
            hbloop_fail_limit=1,
            hbloop_retry_sec=0.05,
            resubscribe_cooldown_sec=0.0,
        )
        self.assertTrue(w.maybe_queue_hbloop_probe())
        buf = io.StringIO()
        with redirect_stderr(buf):
            w.maybe_queue_hbloop_probe()  # first miss → lost / recovering cycle
        self.assertIn("HBLOOP lost", buf.getvalue())
        self.assertNotIn("never returned", buf.getvalue())
        self.assertTrue(w._hbloop_monitor_armed)
        self.assertTrue(w._hbloop_recovering)
        self.assertIsNone(w.take_resubscribe_request())
        time.sleep(0.06)
        with redirect_stderr(buf):
            w.maybe_queue_hbloop_probe()
        self.assertIn("HBLOOP miss", buf.getvalue())
        self.assertEqual(w.take_resubscribe_request(), "hbloop-miss-echo-gate")

    def test_plain_resubscribe_blocked_when_hbloop_established(self) -> None:
        w = SerialSyncWatchdog(
            enabled=True,
            hbloop_enabled=True,
            hbloop_interval_sec=0.0,
            resubscribe_cooldown_sec=0.0,
        )
        w.maybe_queue_hbloop_probe()
        w.note_hbloop_echo("echo")
        self.assertTrue(w.hbloop_is_established())
        self.assertTrue(
            w.request_resubscribe("mqtt-force", force=True, reset_hbloop_budget=True)
        )
        self.assertEqual(w.take_resubscribe_request(), "mqtt-force")

    def test_hbloop_self_oct_from_firmware(self) -> None:
        w = SerialSyncWatchdog(enabled=True, hbloop_enabled=True, verbose=False)
        w.note_serial_line("HBLOOP_SELF 15")
        self.assertEqual(w._hbloop_self_oct, "15")
        self.assertEqual(w.hbloop_sensor_topic_prefix(), "track/sensor/1507")
        w.note_serial_line("@<012>")
        self.assertEqual(w._hbloop_self_oct, "12")
        self.assertEqual(w.hbloop_sensor_topic_prefix(), "track/sensor/1207")

    def test_disabled_noop(self) -> None:
        w = SerialSyncWatchdog(enabled=False, ack_fail_limit=1, hbloop_enabled=False)
        w.note_turnout_ack(False)
        self.assertIsNone(w.take_reopen_request())


if __name__ == "__main__":
    unittest.main()
