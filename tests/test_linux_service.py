"""Offline checks that the Linux service files agree with each other and the bridge."""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINUX = ROOT / "scripts" / "linux"


class LinuxServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.unit = (LINUX / "lcos-bridge.service").read_text(encoding="utf-8")
        self.rule = (LINUX / "99-lcos-nano.rules").read_text(encoding="utf-8")
        self.script = (LINUX / "bridge.sh").read_text(encoding="utf-8")

    def test_unit_runs_the_bridge_from_the_repo(self) -> None:
        self.assertIn("WorkingDirectory=@REPO@", self.unit)
        self.assertIn("User=@USER@", self.unit)
        self.assertIn("EnvironmentFile=-@REPO@/.bridgerc", self.unit)
        exec_line = next(l for l in self.unit.splitlines() if l.startswith("ExecStart="))
        self.assertIn("serial_to_mqtt.py", exec_line)
        self.assertTrue((ROOT / "serial_to_mqtt.py").is_file())
        for opt in ("--com", "--broker"):
            self.assertIn(opt, exec_line)

    def test_unit_keeps_retrying(self) -> None:
        self.assertIn("Restart=always", self.unit)
        self.assertIn("StartLimitIntervalSec=0", self.unit)

    def test_default_port_matches_udev_symlink(self) -> None:
        link = re.search(r'SYMLINK\+="([^"]+)"', self.rule).group(1)
        self.assertIn(f"Environment=SERIAL_PORT=/dev/{link}", self.unit)
        self.assertIn(f"pref SERIAL_PORT /dev/{link}", self.script)

    def test_install_never_runs_as_root(self) -> None:
        self.assertIn("SUDO_USER", self.script)

    def test_rule_matches_ch340(self) -> None:
        self.assertIn('ATTRS{idVendor}=="1a86"', self.rule)
        self.assertIn('ATTRS{idProduct}=="7523"', self.rule)

    def test_root_link_points_at_script(self) -> None:
        link = ROOT / "bridge"
        if not link.is_symlink():
            self.skipTest("checkout without symlinks (Windows core.symlinks=false)")
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), (LINUX / "bridge.sh").resolve())

    @unittest.skipUnless(shutil.which("bash"), "bash not available")
    def test_help_exits_zero(self) -> None:
        r = subprocess.run(["bash", str(LINUX / "bridge.sh"), "help"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        for cmd in ("start", "stop", "status", "log", "flash", "install"):
            self.assertIn(f"bridge {cmd}", r.stdout)


if __name__ == "__main__":
    unittest.main()
