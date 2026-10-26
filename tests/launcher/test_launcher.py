#!/usr/bin/env python3
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Check G1 launch, child cleanup and fresh restart state in MuJoCo only."""

import csv
from datetime import datetime
import http.client
import os
from pathlib import Path
import pty
import select
import signal
import socket
import subprocess
import time

import yaml


def wait_for(predicate, message, timeout=20):
    """Wait for the expected process or status result."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise RuntimeError(message)


def children(parent):
    """Select only runtimes launched by this test process."""
    result = {}
    child_file = Path(f"/proc/{parent}/task/{parent}/children")
    for pid in child_file.read_text().split():
        try:
            command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            name = Path(os.fsdecode(command[0])).name
            if name in ("driver_runtime", "control_runtime", "hmi_runtime"):
                result[name] = int(pid)
        except FileNotFoundError:
            continue
    return result


def attach_tui(sdk, environment, output, fail_hmi_pid=None):
    """Detach normally, or interrupt HMI while the simulated robot has a command."""
    master, slave = pty.openpty()
    command = [str(sdk / "output/staging/bin/run_hmi_tui_g1.sh")]
    process = subprocess.Popen(  # noqa: S603
        command, env=environment, stdin=slave, stdout=slave, stderr=slave,
        start_new_session=True)
    os.close(slave)
    captured = bytearray()
    try:
        def online():
            if process.poll() is not None:
                raise RuntimeError("Attached TUI exited before showing status")
            if select.select([master], [], [], 0.05)[0]:
                captured.extend(os.read(master, 65536))
            return b"CONTROL ONLINE" in captured
        wait_for(online, "Attached TUI was not online", 10)
        if fail_hmi_pid is not None:
            events = [(0.1, "l"), (1, "o"), (2, "h"), (7, "z"),
                      (11, "r"), (15, "v"), (16, "wwwww")]
            start = time.monotonic()
            while time.monotonic() - start < 18:
                if process.poll() is not None:
                    raise RuntimeError("TUI exited before the injected HMI failure")
                if events and time.monotonic() - start >= events[0][0]:
                    os.write(master, events.pop(0)[1].encode())
                if select.select([master], [], [], 0.02)[0]:
                    captured.extend(os.read(master, 65536))
            os.kill(fail_hmi_pid, signal.SIGTERM)
        else:
            process.send_signal(signal.SIGINT)
        process.wait(timeout=5)
        if fail_hmi_pid is None and process.returncode != 0:
            raise RuntimeError("Attached TUI did not exit cleanly")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
        name = "moving-tui.txt" if fail_hmi_pid is not None else "attached-tui.txt"
        (output / name).write_bytes(captured)


def run_case(sdk, machine, output, fail_hmi):
    """Exercise the actual processes, with state commands only in MuJoCo."""
    output.mkdir(mode=0o700)
    config = yaml.safe_load((machine / "config/g1.yaml").read_text())
    config["robot_base"]["robot_dir"] = str(machine)
    config["driver"]["backend"] = "mujoco"
    config["simulation"]["mujoco"]["viewer"] = False
    config["transport"]["shm"]["prefix"] = f"g1_launch_{os.getpid()}_{int(fail_hmi)}"
    config["logging"]["directory"] = str(output / "logs")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config["operator_service"]["port"] = port
    config_file = output / "sim.yaml"
    config_file.write_text(yaml.safe_dump(config, sort_keys=False))
    environment = dict(os.environ, SDK_ROOT=str(sdk), G1_CONFIG=str(config_file),
                       XDG_STATE_HOME=str(output / "state"))
    command = [str(sdk / "output/staging/bin/run_g1.sh"), "--sim", "--no-tui"]
    status_command = [str(sdk / "output/staging/bin/run_hmi_tui_g1.sh"), "--status"]
    with (output / "launcher.txt").open("wb") as log:
        process = subprocess.Popen(  # noqa: S603
            command, env=environment, stdin=subprocess.DEVNULL, stdout=log,
            stderr=subprocess.STDOUT, start_new_session=True)
        owned = {}
        try:
            def ready():
                if process.poll() is not None:
                    raise RuntimeError(f"Launcher failed: {output}")
                result = subprocess.run(  # noqa: S603
                    status_command, env=environment, capture_output=True, timeout=3,
                    check=False, text=True)
                announced = "三个核心进程已就绪" in (output / "launcher.txt").read_text()
                return (announced and "online=1" in result.stdout
                        and "state=POWER_OFF" in result.stdout)
            wait_for(ready, "Core services did not become ready", 65)
            owned = children(process.pid)
            if len(owned) != 3:
                raise RuntimeError(f"Expected three runtime children, got {owned}")
            duplicate = subprocess.run(  # noqa: S603
                command, env=environment, capture_output=True, timeout=5, check=False, text=True)
            if duplicate.returncode == 0 or "已在运行" not in duplicate.stderr:
                raise RuntimeError("Duplicate launch was not rejected")
            for path in ("/", "/app.js", "/pairing.svg", "/api/v1/local-session"):
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                connection.request("GET", path)
                response = connection.getresponse()
                response.read()
                connection.close()
                if response.status != 404:
                    raise RuntimeError(f"Unexpected web entry: {path} {response.status}")
            attach_tui(sdk, environment, output)
            if not ready():
                raise RuntimeError("Closing the attached TUI stopped the core services")
            if fail_hmi:
                attach_tui(sdk, environment, output, owned["hmi_runtime"])
                process.wait(timeout=10)
                if process.returncode == 0:
                    raise RuntimeError("HMI failure was not reported by the launcher")
            else:
                process.send_signal(signal.SIGINT)
                process.wait(timeout=10)
                if process.returncode != 130:
                    raise RuntimeError("Launcher did not return the interrupt status")
            wait_for(lambda: all(not Path(f"/proc/{pid}").exists() for pid in owned.values()),
                     "Launcher left a runtime alive", 5)
            if fail_hmi:
                previous_traces = set((output / "logs").glob("*_control_*/control_trace.csv"))
                previous_rows = []
                for path in previous_traces:
                    with path.open() as stream:
                        previous_rows.extend(csv.DictReader(stream))
                if not any(row["state"] == "RL" and float(row["vx"]) > 0.1
                           for row in previous_rows):
                    raise RuntimeError("Failure case did not start from RL with nonzero velocity")
                # Reproduce the unit's restart delay without installing a local service.
                time.sleep(3)
                process = subprocess.Popen(  # noqa: S603
                    command, env=environment, stdin=subprocess.DEVNULL, stdout=log,
                    stderr=subprocess.STDOUT, start_new_session=True)
                wait_for(ready, "Restart did not return to POWER_OFF", 65)
                owned = children(process.pid)
                if len(owned) != 3:
                    raise RuntimeError("Restart did not create three fresh runtimes")
                result = subprocess.run(  # noqa: S603
                    status_command, env=environment, capture_output=True, timeout=3,
                    check=True, text=True)
                if not result.stdout.rstrip().endswith("owner="):
                    raise RuntimeError("Restart restored old control ownership")
                time.sleep(2)
                process.send_signal(signal.SIGINT)
                process.wait(timeout=10)
                wait_for(lambda: all(not Path(f"/proc/{pid}").exists() for pid in owned.values()),
                         "Restarted launcher left a runtime alive", 5)
                new_traces = set((output / "logs").glob("*_control_*/control_trace.csv")) - previous_traces
                rows = []
                for path in new_traces:
                    with path.open() as stream:
                        rows.extend(csv.DictReader(stream))
                if not rows or any(row["state"] != "POWER_OFF" or row["enabled"] != "0"
                                   or any(float(row[axis]) != 0 for axis in ("vx", "vy", "wz"))
                                   for row in rows):
                    raise RuntimeError("Restart carried over an enabled state or velocity")
                print(f"PASS: restart after moving RL; {len(rows)} disabled POWER_OFF samples, "
                      "zero velocity and no owner")
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            for pid in owned.values():
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
    print(f"PASS: {'failed HMI' if fail_hmi else 'Ctrl+C'} cleanup; no-tui, attach, duplicate, no web")


def main():
    """Run isolated launch and failure cases and retain evidence under output."""
    machine = Path(__file__).resolve().parents[2]
    sdk = machine.parents[2]
    output = sdk / "output" / datetime.now().strftime("g1_launcher_test_%Y%m%d_%H%M%S")
    output.mkdir(mode=0o700)
    for name, failed in (("interrupt", False), ("hmi_exit", True)):
        run_case(sdk, machine, output / name, failed)
    print(output)


if __name__ == "__main__":
    main()
