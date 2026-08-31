#!/usr/bin/env python3
"""Unit tests for SerialSyncWatchdog (no hardware)."""

from __future__ import annotations

import io
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout

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

    def test_hbloop_lost_resub_after_1s_then_60s(self) -> None:
        w = SerialSyncWatchdog(
            enabled=True,
            hbloop_enabled=True,
            hbloop_interval_sec=0.0,
            hbloop_fail_limit=1,
            hbloop_first_resub_delay_sec=0.05,
            hbloop_retry_sec=0.08,
            resubscribe_cooldown_sec=0.0,
        )
        w.maybe_queue_hbloop_probe()
        w.note_hbloop_echo("echo")
        w.maybe_queue_hbloop_probe()
        buf = io.StringIO()
        with redirect_stderr(buf):
            w.maybe_queue_hbloop_probe()  # lost → 1s path
        self.assertIn("HBLOOP lost", buf.getvalue())
        self.assertIn("RESUBSCRIBE in", buf.getvalue())
        self.assertIsNone(w.take_resubscribe_request())
        time.sleep(0.06)
        with redirect_stderr(buf):
            w.maybe_queue_hbloop_recovery()
        text = buf.getvalue()
        self.assertIn("RESUBSCRIBE after", text)
        self.assertNotIn("retrying every", text)
        self.assertEqual(w.take_resubscribe_request(), "hbloop-first-1s")
        self.assertFalse(w.hbloop_quiet_retry_mode())
        # Still recovering — next shot after 60s window, not immediately.
        w.maybe_queue_hbloop_recovery()
        self.assertIsNone(w.take_resubscribe_request())
        time.sleep(0.09)
        buf2 = io.StringIO()
        with redirect_stderr(buf2):
            w.maybe_queue_hbloop_recovery()
        # Enter quiet 60s cadence once; still queues RESUBSCRIBE.
        self.assertEqual(w.take_resubscribe_request(), "hbloop-retry-60s")
        self.assertIn("retrying every", buf2.getvalue())
        self.assertNotIn("HBLOOP miss", buf2.getvalue())
        self.assertTrue(w.hbloop_quiet_retry_mode())
        time.sleep(0.09)
        buf3 = io.StringIO()
        with redirect_stderr(buf3):
            w.maybe_queue_hbloop_recovery()
        self.assertEqual(w.take_resubscribe_request(), "hbloop-retry-60s")
        self.assertEqual(buf3.getvalue(), "")

    def test_hbloop_echo_after_lost_resets_for_next_time(self) -> None:
        w = SerialSyncWatchdog(
            enabled=True,
            hbloop_enabled=True,
            hbloop_interval_sec=0.0,
            hbloop_fail_limit=1,
            hbloop_first_resub_delay_sec=1.0,
            hbloop_retry_sec=60.0,
            resubscribe_cooldown_sec=0.0,
        )
        w.maybe_queue_hbloop_probe()
        w.note_hbloop_echo("echo")
        w.maybe_queue_hbloop_probe()
        w.maybe_queue_hbloop_probe()  # lost
        buf = io.StringIO()
        with redirect_stderr(buf):
            w.note_hbloop_echo("echo")
        self.assertIn("HBLOOP recovered", buf.getvalue())
        self.assertFalse(w._hbloop_recovering)
        self.assertTrue(w._hbloop_awaiting_first_resub is False)
        # Next loss should again use the 1s path.
        w.maybe_queue_hbloop_probe()
        with redirect_stderr(buf):
            w.maybe_queue_hbloop_probe()
        self.assertIn("RESUBSCRIBE in", buf.getvalue())
        self.assertTrue(w._hbloop_awaiting_first_resub)

    def test_hbloop_cold_start_uses_60s_not_1s(self) -> None:
        w = SerialSyncWatchdog(
            enabled=True,
            hbloop_enabled=True,
            hbloop_interval_sec=0.0,
            hbloop_fail_limit=1,
            hbloop_first_resub_delay_sec=0.05,
            hbloop_retry_sec=0.05,
            resubscribe_cooldown_sec=0.0,
        )
        self.assertTrue(w.maybe_queue_hbloop_probe())
        buf = io.StringIO()
        with redirect_stderr(buf):
            w.maybe_queue_hbloop_probe()
        self.assertIn("cold start", buf.getvalue())
        self.assertIn("retrying every", buf.getvalue())
        self.assertFalse(w._hbloop_awaiting_first_resub)
        self.assertTrue(w.hbloop_quiet_retry_mode())
        time.sleep(0.06)
        buf2 = io.StringIO()
        with redirect_stderr(buf2):
            w.maybe_queue_hbloop_recovery()
        self.assertEqual(w.take_resubscribe_request(), "hbloop-retry-60s")
        self.assertNotIn("HBLOOP miss", buf2.getvalue())

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

    def test_subscription_accepts_rolled_up(self) -> None:
        w = SerialSyncWatchdog(
            enabled=True,
            hbloop_enabled=False,
            expect_subscription_accepts=2,
            verbose=True,
        )
        w.note_hbloop_self_oct("15")
        buf = io.StringIO()
        with redirect_stdout(buf):
            w.note_serial_line("Subscription accepted - node: 1")
            w.note_serial_line("Subscription accepted - node: 15")  # self — quiet
            w.note_serial_line("Subscription accepted - node: 2")
        text = buf.getvalue()
        self.assertEqual(text.count("Subscriptions accepted"), 1)
        self.assertIn("(2 plants)", text)
        self.assertNotIn("node: 1", text)

    def test_disabled_noop(self) -> None:
        w = SerialSyncWatchdog(enabled=False, ack_fail_limit=1, hbloop_enabled=False)
        w.note_turnout_ack(False)
        self.assertIsNone(w.take_reopen_request())


if __name__ == "__main__":
    unittest.main()
