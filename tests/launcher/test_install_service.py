#!/usr/bin/env python3
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Offline checks for G1 service rendering and installation; no system changes."""

import importlib.util
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("install_g1_service", PACKAGE / "scripts/install_g1_service.py")
INSTALLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)


class ServiceTest(unittest.TestCase):
    """Exercise the same installer used on the robot with temporary files only."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="g1_service_test_")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.user = pwd.getpwuid(os.getuid()).pw_name
        binary_dir = self.root / "output/staging/bin"
        binary_dir.mkdir(parents=True)
        for name in ("run_g1.sh", "run_driver_g1.sh", "run_control_g1.sh", "run_hmi_g1.sh",
                     "hmi_tui", "driver_runtime", "control_runtime", "hmi_runtime", "operator_audio",
                     "configure_g1_realtime.py"):
            (binary_dir / name).symlink_to("/bin/true")
        share = self.root / "output/staging/share/humanoid_unitree_g1"
        share.mkdir(parents=True)
        shutil.copy2(PACKAGE / "services/g1.service.in", share)
        shutil.copy2(PACKAGE / "services/70-g1-gamepad-rumble.rules", share)

    def test_render_service(self):
        unit = INSTALLER.render_service(self.root, self.user, "0.0.0.0", "http://192.0.2.10:8766/")
        self.assertIn(f"User={self.user}\n", unit)
        self.assertIn(" --real --no-tui --listen 0.0.0.0 --public-url http://192.0.2.10:8766\n", unit)
        self.assertIn("LimitRTPRIO=70\n", unit)
        self.assertIn("LimitMEMLOCK=infinity\n", unit)
        self.assertIn("SupplementaryGroups=audio input\n", unit)
        self.assertIn("ExecStopPost=-", unit)
        self.assertIn(" --service-failure\n", unit)
        self.assertIn("Restart=on-failure\n", unit)
        self.assertIn("RestartSec=3\n", unit)
        self.assertIn("StartLimitIntervalSec=0\n", unit)
        self.assertIn("SuccessExitStatus=130 143\n", unit)
        self.assertIn("KillMode=mixed\n", unit)
        self.assertIn('Environment="G1_STARTUP_TIMEOUT_S=60"\n', unit)
        self.assertIn("After=network-online.target g1-serial-order.service sys-kernel-debug.mount\n", unit)
        self.assertIn("configure_g1_realtime.py --apply --preempt-only\n", unit)
        self.assertLess(unit.index("--preempt-only"), unit.index("ExecStart="))
        self.assertNotIn("@", unit)

    def test_network_validation(self):
        self.assertEqual(INSTALLER.network_arguments(None, None), "")
        for listen, public_url in (("0.0.0.0", None), (None, "http://robot:8766"),
                                   ("0.0.0.0", "http://robot:8766\nUser=root"),
                                   ("0.0.0.0", "http://user:password@robot:8766")):
            with self.subTest(listen=listen, public_url=public_url), self.assertRaises(ValueError):
                INSTALLER.network_arguments(listen, public_url)

    @unittest.skipUnless(shutil.which("systemd-analyze"), "systemd-analyze not installed")
    def test_systemd_accepts_rendered_unit(self):
        path = self.root / "g1.service"
        path.write_text(INSTALLER.render_service(self.root, self.user), encoding="utf-8")
        result = subprocess.run(  # noqa: S603
            ["systemd-analyze", "verify", str(path)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_keep_installed_network(self):
        path = self.root / "g1.service"
        self.assertEqual(INSTALLER.installed_network(path), (None, None))
        path.write_text(INSTALLER.render_service(self.root, self.user, "0.0.0.0", "http://robot:8766"),
                        encoding="utf-8")
        self.assertEqual(INSTALLER.installed_network(path), ("0.0.0.0", "http://robot:8766"))

    def test_install_enables_without_starting(self):
        path = self.root / "g1.service"
        path.write_text("old unit", encoding="utf-8")
        with patch.object(INSTALLER.subprocess, "run",
                          return_value=subprocess.CompletedProcess([], 3, "inactive\n")) as run:
            INSTALLER.install_service(path, "new unit")
        self.assertEqual(path.read_text(encoding="utf-8"), "new unit")
        self.assertEqual(next(self.root.glob("g1.service.*.bak")).read_text(encoding="utf-8"), "old unit")
        self.assertEqual([call.args[0] for call in run.call_args_list], [
            ["systemctl", "is-active", "g1.service"],
            ["systemctl", "daemon-reload"], ["systemctl", "enable", "g1.service"]])

    def test_running_service_not_overwritten(self):
        path = self.root / "g1.service"
        with patch.object(INSTALLER.subprocess, "run",
                          return_value=subprocess.CompletedProcess([], 0, "active\n")):
            with self.assertRaises(ValueError):
                INSTALLER.install_service(path, "new unit")
        self.assertFalse(path.exists())

    def test_root_runtime_rejected(self):
        with self.assertRaises(ValueError):
            INSTALLER.render_service(self.root, "root")

    def test_gamepad_rule_is_scoped_and_does_not_trigger_usb(self):
        rules = self.root / "rules.d"
        with patch.object(INSTALLER.subprocess, "run") as run:
            INSTALLER.install_gamepad_rule(self.root, rules)
        content = (rules / "70-g1-gamepad-rumble.rules").read_text()
        for match in ('SUBSYSTEM=="hidraw"', 'ATTRS{idVendor}=="054c"',
                      'ATTRS{idProduct}=="09cc"', 'GROUP="input"', 'MODE="0660"'):
            self.assertIn(match, content)
        self.assertEqual([call.args[0] for call in run.call_args_list],
                         [["udevadm", "control", "--reload-rules"]])

    def test_headless_profile_does_not_start_hardware_or_disable_audio(self):
        path = self.root / "g1.service"
        with patch.object(INSTALLER.subprocess, "run",
                          return_value=subprocess.CompletedProcess([], 0, "enabled\n")) as run:
            INSTALLER.install_headless(self.root, path)
        dropin = (self.root / "g1.service.d/50-headless.conf").read_text(encoding="utf-8")
        self.assertIn("CPUAffinity=0 3 4 5 6\n", dropin)
        self.assertIn("ExecStartPre=+/usr/bin/python3 ", dropin)
        self.assertIn("configure_g1_realtime.py --apply\n", dropin)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn(["systemctl", "mask", "--now", "rtkit-daemon.service"], commands)
        self.assertIn(["systemctl", "set-default", "multi-user.target"], commands)
        self.assertFalse(any("start" in command or "restart" in command for command in commands))
        self.assertFalse(any("pipewire" in str(command) or "alsa" in str(command) for command in commands))


if __name__ == "__main__":
    unittest.main()
