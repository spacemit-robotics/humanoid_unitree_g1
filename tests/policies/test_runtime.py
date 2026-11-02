#!/usr/bin/env python3
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Run the real three-process stack in isolated MuJoCo simulation, without opening devices."""

import argparse
from datetime import datetime
import math
import os
from pathlib import Path
import signal
import socket
import subprocess
import time

import yaml


def main():
    """Generate a private simulation configuration and exercise the operator API."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--viewer", action="store_true")
    parser.add_argument("--policy-trace", action="store_true", help="Record model inputs and applied targets")
    parser.add_argument("--initial", help="Initial mode; defaults to the machine configuration")
    parser.add_argument("--transition-duration", type=float, help="Override live handoff duration for comparison")
    parser.add_argument("--idle-policy", help="Override action-mode standby policy in the test copy")
    parser.add_argument("--policies", nargs="*", default=["stand", "walk_mjlab", "walk_rlgym", "walk_mjlab"])
    args = parser.parse_args()
    machine = Path(__file__).resolve().parents[2]
    sdk = machine.parents[2]
    build = sdk / "output/build/g1_policy_tests"
    subprocess.run(["cmake", "-S", str(Path(__file__).parent), "-B", str(build)], check=True)
    subprocess.run(["cmake", "--build", str(build), "-j4"], check=True)
    output = sdk / "output" / f"g1_policy_sim_{datetime.now():%Y%m%d_%H%M%S}_{os.getpid()}"
    output.mkdir(exist_ok=False)
    config = yaml.safe_load((machine / "config/g1.yaml").read_text())
    args.initial = args.initial or config["rl_policy"]["onnx_infer"]["default_policy"]
    available = config["rl_policy"]["onnx_infer"]["policy_names"]
    if args.initial not in available:
        parser.error("Select a configured initial policy")
    extra_time = 0
    for step in args.policies:
        if step.startswith("velocity:"):
            try:
                values = [float(value) for value in step[9:].split(",")]
            except ValueError:
                parser.error("Velocity values must be finite numbers")
            if len(values) != 4 or not all(math.isfinite(value) for value in values) or not 0 < values[3] <= 60:
                parser.error("Velocity must be vx,vy,wz,seconds (0 < seconds <= 60)")
            extra_time += values[3] + 3
        elif step.startswith("wait:"):
            seconds = float(step[5:])
            if not 0 <= seconds <= 300:
                parser.error("Wait must be between 0 and 300 seconds")
            extra_time += seconds
        elif (step not in available and step not in ("reference", "cancel", "idle", "finished")
              and not step.startswith("action:")):
            parser.error("Steps must be modes, reference, action:ID, cancel, idle, finished, wait:SECONDS or velocity")
    config["robot_base"]["robot_dir"] = str(machine)
    config["driver"]["backend"] = "mujoco"
    config["simulation"]["mujoco"]["viewer"] = args.viewer
    config["rl_policy"]["onnx_infer"]["default_policy"] = args.initial
    if args.idle_policy:
        definitions = config["rl_policy"]["onnx_infer"]["policies"]
        if args.idle_policy not in definitions or "policy_actions" in definitions[args.idle_policy]:
            parser.error("Standby override must name an ordinary policy")
        for policy in definitions.values():
            if "policy_actions" in policy:
                policy["policy_actions"]["idle_policy"] = args.idle_policy
    if args.transition_duration is not None:
        if args.transition_duration < 0:
            parser.error("Transition duration must be nonnegative")
        for policy in config["rl_policy"]["onnx_infer"]["policies"].values():
            policy["policy_switch"] = {"transition_duration": args.transition_duration}
    config["transport"]["type"] = "shm"
    config["transport"]["shm"]["prefix"] = f"g1_policy_test_{os.getpid()}"
    config["logging"]["directory"] = str(output / "logs")
    config["logging"]["blackbox"]["enabled"] = False
    config["logging"]["telemetry"]["policy_enabled"] = args.policy_trace
    config["operator_gamepad"]["enabled"] = False
    config["audio_prompts"]["enabled"] = False
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        config["operator_service"]["port"] = probe.getsockname()[1]
    config_path = output / "sim.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    connection = output / "state/humanoid-operator/g1/connection.json"
    environment = dict(os.environ, SDK_ROOT=str(sdk), G1_CONFIG=str(config_path),
                       XDG_STATE_HOME=str(output / "state"))
    print(f"Simulation logs: {output}", flush=True)
    with (output / "launcher.log").open("wb") as log:
        process = subprocess.Popen(  # noqa: S603
            [str(sdk / "output/staging/bin/run_g1.sh"), "--sim", "--no-tui"],
            env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            deadline = time.monotonic() + 65
            while not connection.exists():
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("Simulation did not start; inspect launcher.log")
                time.sleep(0.1)
            subprocess.run(  # noqa: S603
                [str(build / "test_switch_client"), str(config_path), str(connection), *args.policies],
                env=environment, check=True,
                timeout=60 + (config["hmi"]["request_timeout"] + 10) * len(args.policies) + extra_time)
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


if __name__ == "__main__":
    main()
