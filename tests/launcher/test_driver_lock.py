#!/usr/bin/env python3
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Check driver lock diagnostics and lifetime without opening hardware devices."""

import fcntl
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

PACKAGE = Path(__file__).resolve().parents[2]
FAKE_DRIVER = r'''#!/usr/bin/env python3
import os
from pathlib import Path
import signal
import sys
import time

root = Path(os.environ["SDK_ROOT"])
(root / "driver.started").write_text(str(os.getpid()))
if os.environ.get("TEST_WAIT") == "1":
    signal.signal(signal.SIGINT, lambda *_: sys.exit(130))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    (root / "driver.ready").touch()
    while True:
        time.sleep(0.01)
sys.exit(int(os.environ.get("TEST_EXIT", "0")))
'''


class DriverLockTest(unittest.TestCase):
    """Use the real launcher and flock, with isolated lock and runtime fixtures."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="g1_driver_lock_")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.lock = self.root / "hardware.lock"
        self.launcher = self.root / "run_driver_g1.sh"
        source = (PACKAGE / "scripts/run_driver_g1.sh").read_text(encoding="utf-8")
        self.assertEqual(source.count("/tmp/g1_hardware.lock"), 1)
        self.launcher.write_text(source.replace("/tmp/g1_hardware.lock", str(self.lock)),
                                 encoding="utf-8")
        driver = self.root / "output/staging/bin/driver_runtime"
        driver.parent.mkdir(parents=True)
        driver.write_text(FAKE_DRIVER, encoding="utf-8")
        driver.chmod(0o755)
        config = self.root / "test.yaml"
        config.write_text("driver:\n  backend: whole_body\n", encoding="utf-8")
        self.environment = dict(os.environ, SDK_ROOT=str(self.root), G1_CONFIG=str(config))

    def run_driver(self, *arguments, **environment):
        return subprocess.run(  # noqa: S603
            ["bash", str(self.launcher), *arguments],
            env=dict(self.environment, **environment), capture_output=True,
            check=False, text=True, timeout=5)

    def test_busy_lock_reports_conflict_without_starting_driver(self):
        with self.lock.open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_driver("--real")
            self.assertEqual(result.returncode, 1)
            self.assertIn("硬件驱动已在运行", result.stderr)
            self.assertFalse((self.root / "driver.started").exists())

    def test_driver_failure_is_not_a_lock_conflict(self):
        result = self.run_driver("--real", TEST_EXIT="37")
        self.assertEqual(result.returncode, 37)
        self.assertEqual(result.stderr, "")
        self.assertTrue((self.root / "driver.started").exists())

    def test_simulation_does_not_take_hardware_lock(self):
        with self.lock.open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_driver("--sim")
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_lock_lives_until_driver_exits_and_signals_reach_driver(self):
        for signum in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=signum):
                (self.root / "driver.ready").unlink(missing_ok=True)
                process = subprocess.Popen(  # noqa: S603
                    ["bash", str(self.launcher), "--real"],
                    env=dict(self.environment, TEST_WAIT="1"),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True)
                try:
                    deadline = time.monotonic() + 5
                    while not (self.root / "driver.ready").exists():
                        self.assertIsNone(process.poll())
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(0.01)
                    self.assertEqual(int((self.root / "driver.started").read_text()), process.pid)
                    result = self.run_driver("--real")
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("硬件驱动已在运行", result.stderr)
                    process.send_signal(signum)
                    self.assertEqual(process.wait(timeout=5), 128 + signum)
                    with self.lock.open("w") as lock:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.assertEqual(self.run_driver("--real").returncode, 0)
                finally:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
