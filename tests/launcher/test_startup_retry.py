#!/usr/bin/env python3
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Exercise startup retries with fake processes; never open hardware devices."""

import os
import re
import shutil
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

PACKAGE = Path(__file__).resolve().parents[2]
FAKE_RUNTIME = r'''#!/usr/bin/env python3
import fcntl
import os
from pathlib import Path
import signal
import sys
import time

root = Path(os.environ["SDK_ROOT"])
name = Path(sys.argv[0]).name
case = os.environ["TEST_CASE"]
signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
if name == "pgrep":
    sys.exit(1)
if name == "hmi_tui":
    print("robot=g1 state=POWER_OFF online=1")
    sys.exit(0)
if name == "run_driver_g1.sh":
    count_file = root / "attempts"
    count = int(count_file.read_text()) + 1 if count_file.exists() else 1
    count_file.write_text(str(count))
    if case == "startup_fatal":
        sys.exit(1)
    if case == "always_unavailable" or (case == "retry" and count == 1):
        sys.exit(75)
    (root / "hardware.ready").touch()
    if case == "runtime_failure":
        while not (root / "fail_runtime").exists():
            time.sleep(0.02)
        sys.exit(75)
elif name == "run_control_g1.sh":
    ready_fd = int(os.environ["HUMANOID_STARTUP_READY_FD"])
    fcntl.fcntl(ready_fd, fcntl.F_SETFL, fcntl.fcntl(ready_fd, fcntl.F_GETFL) | os.O_NONBLOCK)
    while not (root / "hardware.ready").exists():
        time.sleep(0.02)
    print("[control][INFO] driver state stream ready", flush=True)
    if case == "delayed_ready":
        while not (root / "allow_ready").exists():
            time.sleep(0.02)
    os.write(ready_fd, b"ready\n")
elif name == "run_hmi_g1.sh" and case == "hmi_failure":
    sys.exit(1)
elif name == "hmi_gamepad":
    (root / "gamepad.started").touch()
    sys.exit(24)
elif name == "operator_audio":
    (root / "audio.started").touch()
    sys.exit(23)
while True:
    time.sleep(0.1)
'''


class StartupTest(unittest.TestCase):
    """Only pre-command-loop driver failures may retry within the time budget."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="g1_startup_")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        binary = self.root / "output/staging/bin"
        binary.mkdir(parents=True)
        shutil.copyfile(PACKAGE.parent / "humanoid_common/scripts/humanoid_logs.py",
                        binary / "humanoid_logs.py")
        for name in ("run_driver_g1.sh", "run_control_g1.sh", "run_hmi_g1.sh", "hmi_tui", "pgrep",
                     "operator_audio", "hmi_gamepad"):
            path = binary / name
            path.write_text(FAKE_RUNTIME, encoding="utf-8")
            path.chmod(0o755)
        for name in ("driver_runtime", "control_runtime", "hmi_runtime"):
            (binary / name).symlink_to("/bin/true")
        self.config = self.root / "test.yaml"
        self.config.write_text("robot_base:\n  name: g1\nlogging:\n  directory: logs\n",
                               encoding="utf-8")
        self.log_path = self.root / "launcher.log"
        self.log = self.log_path.open("w", encoding="utf-8")
        self.addCleanup(self.log.close)
        self.process = None
        self.addCleanup(self.stop)

    def start(self, case, timeout=12):
        environment = dict(os.environ, SDK_ROOT=str(self.root), G1_CONFIG=str(self.config),
                           XDG_STATE_HOME=str(self.root / "state"), TEST_CASE=case,
                           G1_STARTUP_TIMEOUT_S=str(timeout),
                           PATH=str(self.root / "output/staging/bin") + os.pathsep + os.environ["PATH"])
        self.process = subprocess.Popen(  # noqa: S603
            ["bash", str(PACKAGE / "scripts/run_g1.sh"), "--real", "--no-tui"],
            env=environment, stdin=subprocess.DEVNULL, stdout=self.log,
            stderr=subprocess.STDOUT, start_new_session=True)

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.send_signal(signal.SIGINT)
            self.process.wait(timeout=10)

    def wait_for(self, predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.05)
        self.fail(self.log_path.read_text(encoding="utf-8"))

    def ready(self):
        return "三个核心进程已就绪" in self.log_path.read_text(encoding="utf-8")

    def attempts(self):
        return int((self.root / "attempts").read_text(encoding="utf-8"))

    def test_initialization_failure_retries(self):
        self.start("retry")
        self.wait_for(self.ready)
        self.assertEqual(self.attempts(), 2)
        self.assertIsNone(self.process.poll())

    def test_online_is_not_hardware_ready(self):
        self.start("delayed_ready")
        self.wait_for(lambda: (self.root / "hardware.ready").exists())
        time.sleep(0.5)
        self.assertFalse(self.ready())
        self.assertFalse((self.root / "audio.started").exists())
        self.assertFalse((self.root / "gamepad.started").exists())
        fdinfo = Path(f"/proc/{self.process.pid}/fdinfo/8").read_text()
        flags = int(re.search(r"flags:\s+([0-7]+)", fdinfo).group(1), 8)
        self.assertFalse(flags & os.O_NONBLOCK, "Child must not change launcher's read flags")
        self.assertNotIn("read:", self.log_path.read_text(encoding="utf-8"))
        (self.root / "allow_ready").touch()
        self.wait_for(self.ready)
        self.wait_for(lambda: (self.root / "audio.started").exists())
        self.wait_for(lambda: (self.root / "gamepad.started").exists())
        time.sleep(0.3)
        self.assertIsNone(self.process.poll(), "Optional client failure must not terminate core processes")

    def test_runtime_failure_never_retries(self):
        self.start("runtime_failure")
        self.wait_for(self.ready)
        (self.root / "fail_runtime").touch()
        self.assertEqual(self.process.wait(timeout=10), 1)
        self.assertEqual(self.attempts(), 1)

    def test_permanent_unavailable_is_bounded(self):
        self.start("always_unavailable", timeout=5)
        self.assertEqual(self.process.wait(timeout=10), 1)
        self.assertGreaterEqual(self.attempts(), 2)
        self.assertFalse(self.ready())

    def test_normal_startup_error_never_retries(self):
        self.start("startup_fatal")
        self.assertEqual(self.process.wait(timeout=10), 1)
        self.assertEqual(self.attempts(), 1)

    def test_hmi_failure_never_retries(self):
        self.start("hmi_failure")
        self.assertEqual(self.process.wait(timeout=10), 1)
        self.assertEqual(self.attempts(), 1)

    def test_interrupt_cancels_pending_retry(self):
        self.start("always_unavailable")
        self.wait_for(lambda: "2 秒后重试" in self.log_path.read_text(encoding="utf-8"))
        self.stop()
        self.assertEqual(self.process.returncode, 130)
        self.assertEqual(self.attempts(), 1)


if __name__ == "__main__":
    unittest.main()
