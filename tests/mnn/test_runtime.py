#!/usr/bin/env python3
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Exercise the real SDK driver/control/HMI processes in isolated MuJoCo simulation."""

import argparse
import csv
from datetime import datetime
import os
from pathlib import Path
import pty
import select
import signal
import socket
import subprocess
import time

import yaml

EXPECTED_GESTURES = {"shake_hand", "wave_above_head", "wave_under_head",
                     "blow_kiss_with_right_hand", "clamp"}


def csv_rows(path):
    """Read every rotated part in chronological order, including its header."""
    rotated = [part for part in path.parent.glob(path.name + ".*")
               if part.suffix[1:].isdigit()]
    for part in [*sorted(rotated, key=lambda item: int(item.suffix[1:]), reverse=True), path]:
        with part.open() as stream:
            yield from csv.DictReader(stream)


def main():
    """Use an isolated SHM prefix and force the MuJoCo backend; never open devices."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--viewer", action="store_true")
    parser.add_argument("--audio-check", action="store_true",
                        help="Observe real simulation status with the dry-run audio process")
    parser.add_argument("--logging-check", action="store_true",
                        help="Use production blackbox logging and validate a manual full-rate capture")
    parser.add_argument("--check-run", type=Path,
                        help="Validate saved logs only; use the same scenario flags as the original run")
    scenario = parser.add_mutually_exclusive_group()
    scenario.add_argument("--gestures", action="store_true")
    scenario.add_argument("--motion-modes", action="store_true")
    scenario.add_argument("--dance-catalog", action="store_true")
    scenario.add_argument("--stairs", action="store_true")
    args = parser.parse_args()
    if args.logging_check and (args.gestures or args.motion_modes or args.dance_catalog or args.stairs):
        parser.error("--logging-check uses the default stance/motion/turn sequence")
    if args.check_run:
        config = yaml.safe_load((args.check_run / "sim.yaml").read_text())
        validate_run(args, config, args.check_run)
        return
    machine = Path(__file__).resolve().parents[2]
    sdk = machine.parents[2]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = sdk / "output" / f"g1_mnn_runtime_{stamp}"
    output.mkdir(exist_ok=False)
    config = yaml.safe_load((machine / "config/g1.yaml").read_text())
    config["robot_base"]["robot_dir"] = str(machine)
    config["driver"]["backend"] = "mujoco"
    config["simulation"]["mujoco"]["viewer"] = args.viewer
    config["rl_policy"]["onnx_infer"]["default_policy"] = "walk_mnn"
    config["transport"]["type"] = "shm"
    config["transport"]["shm"]["prefix"] = f"g1_mnn_test_{os.getpid()}"
    config["logging"]["directory"] = str(output / "logs")
    if not args.logging_check:
        # These bounded regression scenarios compare every inference/transition sample.
        config["logging"]["blackbox"]["enabled"] = False
    if args.dance_catalog:
        # Full-rate dance observations exceed four 16 MiB parts over this
        # 154-second test. Retain the complete local fixture, not just its tail.
        config["logging"]["file"]["max_files"] = 8
    with socket.socket() as port_probe:
        port_probe.bind(("127.0.0.1", 0))
        config["operator_service"]["port"] = port_probe.getsockname()[1]
    config_path = output / "sim.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    processes = []
    streams = []
    master, slave = pty.openpty()
    events = [(0.3, "l"), (2, "o"), (3, "h"), (8, "z"), (12, "r"), (16, "v"),
              (17, "wwwww"), (25, " "), (30, "qqqqq"), (35, " "), (41, "v"), (42, "f")]
    if args.gestures:
        if set(config["arm_interactions"]["action_names"]) != EXPECTED_GESTURES:
            raise RuntimeError("Unexpected G1 gesture catalog")
        events = [(0.3, "l"), (2, "o"), (3, "h"), (8, "z"), (12, "r"),
                  (16, "a\r"), (20, "c"), (22, "aj\r"), (31, "ajj\r"),
                  (37, "ajjj\r"), (43, "ajjjj\r"), (49, "aj\r"), (49.6, "c"),
                  (53, "a\r"), (56, "f"), (57, "u")]
    if args.motion_modes:
        events = [(0.3, "l"), (2, "o"), (3, "h"), (8, "z"), (12, "r"),
                  (16, "vwwwww"), (20, " v"), (22, "pj\r"), (29, "vwwwww"),
                  (35, " v"), (40, "pj\r"), (45, "aj\r"), (74, "pkk\r"),
                  (82, "vwwwww"), (90, " "), (94, "v"), (102, "f")]
    if args.stairs:
        events = [(0.3, "l"), (2, "o"), (3, "h"), (8, "z"), (12, "r"),
                  (13, "pj\r"), (17, "vwwwww"), (39, " "), (41, "v"), (42, "f")]
    if args.dance_catalog:
        # Reproduce repeated standby cancellation, play all clips, then cancel
        # a repeated clip several times without restarting its blend-out.
        events = [(0.3, "l"), (2, "o"), (3, "h"), (8, "z"), (12, "r"),
                  (16, "pjj\r"), (18, "c"), (18.2, "c"), (18.4, "c"),
                  (20, "a\r"), (52, "aj\r"),
                  (78, "ajj\r"), (99, "ajjj\r"), (132, "a\r"),
                  (140, "c"), (140.2, "c"), (140.4, "c"), (141, "c"),
                  (146, "pkk\r"), (152, "f")]
    try:
        command = [str(sdk / "output/staging/bin/run_g1.sh"), "--sim"]
        if args.stairs:
            command.append("--stairs")
        environment = dict(os.environ, SDK_ROOT=str(sdk), G1_CONFIG=str(config_path),
                           XDG_STATE_HOME=str(output / "state"))
        stream = (output / "launcher.txt").open("wb")
        streams.append(stream)
        processes.append(subprocess.Popen(  # noqa: S603
            command, env=environment, stdin=slave, stdout=slave, stderr=slave,
            start_new_session=True))
        os.close(slave)
        ready_until = time.monotonic() + 65
        terminal_output = b""
        while b"CONTROL ONLINE" not in terminal_output:
            if processes[0].poll() is not None or time.monotonic() >= ready_until:
                raise RuntimeError("Launcher did not reach the TUI; inspect launcher.txt")
            if select.select([master], [], [], 0.1)[0]:
                chunk = os.read(master, 65536)
                stream.write(chunk)
                terminal_output = (terminal_output + chunk)[-65536:]
        start = time.monotonic()
        if args.audio_check:
            audio_log = (output / "audio.log").open("wb")
            streams.append(audio_log)
            processes.append(subprocess.Popen(  # noqa: S603
                [str(sdk / "output/staging/bin/operator_audio"), str(config_path),
                 "--connection", str(output / "state/humanoid-operator/g1/connection.json"),
                 "--dry-run"], stdout=audio_log, stderr=subprocess.STDOUT))
        event = 0
        capture_requested = False
        duration = 104 if args.motion_modes else 154 if args.dance_catalog else 58 if args.gestures else 44
        while time.monotonic() - start < duration:
            elapsed = time.monotonic() - start
            if args.logging_check and elapsed >= 1 and not capture_requested:
                subprocess.run(  # noqa: S603
                    ["python3", str(sdk / "output/staging/bin/humanoid_logs.py"), "capture",
                     "--config", str(config_path), "--seconds", "60", "--reason", "simulation regression"],
                    env=environment, check=True, timeout=5, capture_output=True)
                capture_requested = True
            if event < len(events) and elapsed >= events[event][0]:
                os.write(master, events[event][1].encode())
                print(f"{elapsed:.1f}s key={events[event][1]!r}", flush=True)
                event += 1
            if select.select([master], [], [], 0.02)[0]:
                stream.write(os.read(master, 65536))
            if any(process.poll() is not None for process in processes):
                raise RuntimeError("A runtime exited unexpectedly; inspect the saved logs")
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
        for process in reversed(processes):
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        os.close(master)
        for stream in streams:
            stream.close()
        print(output)
    validate_run(args, config, output)


def validate_run(args, config, output):
    """Validate recorded state transitions and replies without restarting a run."""
    if args.audio_check:
        audio = (output / "audio.log").read_text()
        required = {"service.ready", "state.DAMP", "policy.walk_mnn", "state.POWER_OFF"}
        if args.motion_modes or args.dance_catalog:
            required.add("policy.dance_mnn")
        if args.motion_modes:
            required.add("policy.walk_obstacle_mnn")
        if args.gestures:
            required.update("action." + key for key in EXPECTED_GESTURES)
            required.update(("control.acquired", "control.released"))
        if args.dance_catalog:
            required.update("action.rhythm_" + str(index) for index in range(1, 5))
        for event in required:
            if f"[audio] {event} -> " not in audio:
                raise RuntimeError(f"Missing audio event: {event}")
        if args.gestures:
            for cue in ("control.acquired", "control.released"):
                if audio.count(f"[audio] {cue} -> ") != 1:
                    raise RuntimeError(f"Duplicate ownership cue: {cue}")
        if args.dance_catalog:
            for index in range(1, 5):
                expected = 2 if index == 1 else 1
                lines = [line for line in audio.splitlines()
                         if f"[audio] action.rhythm_{index} -> " in line]
                if len(lines) != expected * 2 or any(
                        not line.endswith("wow.wav" if i % 2 == 0 else "groove.wav")
                        for i, line in enumerate(lines)):
                    raise RuntimeError(f"Duplicate or missing rhythm_{index} cue on cancel/replay")
        for silent in ("state.HOME", "state.ZERO", "state.RL", "policy.walk_standard_mnn",
                       "policy.walk_wbc_mnn"):
            if f"[audio] {silent} -> " in audio:
                raise RuntimeError(f"Unexpected audio event: {silent}")
        if "missing WAV" in audio:
            raise RuntimeError("Audio resource missing")
        print("PASS: confirmed simulation events drove the production audio observer")
    control_events = next((output / "logs").glob("*_control_*/events.log"))
    control_log = control_events.read_text(errors="replace")
    required_events = ["进入 RL", "[stance_motion] stance"]
    if not (args.gestures or args.motion_modes or args.stairs or args.dance_catalog):
        required_events += ["[stance_motion] motion", "[stance_motion] turn"]
    for required in required_events:
        if required not in control_log:
            raise RuntimeError(f"Missing runtime event: {required}")
    control_dir = next((output / "logs").glob("*_control_*"))
    if args.logging_check:
        overview = list(csv_rows(control_dir / "control_trace.csv"))
        if not 30 <= len(overview) <= 100:
            raise RuntimeError(f"Unexpected persistent overview rate: {len(overview)} rows")
        incidents = list(control_dir.glob("incident_*"))
        if len(incidents) != 1 or not (incidents[0] / ".complete").exists():
            raise RuntimeError("Manual incident did not complete")
        incident_name = incidents[0].name
        for component in ("driver", "hmi"):
            session = next((output / "logs").glob(f"*_{component}_*"))
            if not (session / incident_name / "trigger.json").is_file():
                raise RuntimeError(f"Incident ID was not shared with {component}")
        control_dir = incidents[0]
        print(f"PASS: {len(overview)} overview rows; shared full-rate incident {incident_name}")
    trace = list(csv_rows(control_dir / "control_trace.csv"))
    joints = {row["device_time_s"]: row for row in csv_rows(control_dir / "control_joint.csv")}
    # The asynchronous console logger may drop a duplicate informational line.
    # Count actual sampled FSM/policy changes, not printf delivery.
    expected_entries = 4 if args.motion_modes else 3 if args.dance_catalog else 2 if args.stairs else 1
    actual_entries = sum(current["state"] == "RL" and
                         (previous["state"] != "RL" or previous["policy"] != current["policy"])
                         for previous, current in zip(trace, trace[1:]))
    if actual_entries != expected_entries:
        raise RuntimeError(f"Unexpected number of policy entries: {actual_entries}, expected {expected_entries}")
    # Asynchronous diagnostic channels can drop different samples. Compare only
    # paired state/joint frames, with a bounded gap across the transition.
    paired_trace = [row for row in trace if row["device_time_s"] in joints]
    sample_period = 1.0 / config["logging"]["telemetry"]["control_rate_hz"]
    for previous, current in zip(paired_trace, paired_trace[1:]):
        if previous["state"] != "HOME" or current["state"] != "ZERO":
            continue
        if float(current["device_time_s"]) - float(previous["device_time_s"]) > 1.5 * sample_period:
            raise RuntimeError("Insufficient paired samples at HOME -> ZERO")
        before = joints[previous["device_time_s"]]
        after = joints[current["device_time_s"]]
        target_jump = max(abs(float(after[name]) - float(before[name]))
                          for name in after if name.endswith(".target_position"))
        start_time = float(current["device_time_s"])
        waist_speed = max(abs(float(row["waist_pitch_joint.velocity"]))
                          for row in joints.values()
                          if 0 <= float(row["device_time_s"]) - start_time <= 0.25)
        print(f"HOME -> ZERO: sampled target jump {target_jump:.6f} rad; "
              f"first 0.25 s waist pitch peak speed {waist_speed:.6f} rad/s")
        if target_jump > 0.001:
            raise RuntimeError("HOME -> ZERO target discontinuity; inspect control_joint.csv")
    if any(row["fault_latched"] != "0" for row in trace):
        raise RuntimeError("Latched runtime fault; inspect logs")
    rl_rows = [row for row in trace if row["state"] == "RL"]
    if not rl_rows or float(rl_rows[-1]["device_time_s"]) - float(rl_rows[0]["device_time_s"]) < 29:
        raise RuntimeError("RL did not remain active throughout the motion sequence")
    if args.dance_catalog:
        terminal = (output / "launcher.txt").read_text(errors="replace")
        for failure in ("invalid interaction metadata", "status validation/send failed"):
            if failure in control_log:
                raise RuntimeError(f"Dance cancellation damaged status reporting: {failure}")
        hmi_log = next((output / "logs").glob("*_hmi_*/events.log")).read_text()
        if hmi_log.count("cancel completed: control handled action request") != 7:
            raise RuntimeError("Standby/repeated cancellation requests did not all complete")
        if hmi_log.count("interaction completed: control handled action request") != 5:
            raise RuntimeError("Dance starts did not all complete after standby cancellation")
        inference = list(csv_rows(control_dir / "control_policy_dance_mnn.csv"))
        if len(inference) < 6000 or any(row["result"] != "published" for row in inference):
            raise RuntimeError("Incomplete dance catalog inference")
        for name in ("rhythm_1", "rhythm_2", "rhythm_3", "rhythm_4"):
            label = config["dance_actions"]["actions"][name]["display_name"]
            if label not in terminal:
                raise RuntimeError(f"Missing dance display name: {label}")
            action_rows = [row for row in inference if row["interaction_action"] == name]
            phases = {row["interaction_phase"] for row in action_rows}
            # RobotData::InteractionStatus::Phase values recorded by StateRL.
            if not {"2", "5"}.issubset(phases):
                raise RuntimeError(f"Incomplete dance selection/return: {name}: {phases}")
        print("PASS: standby/repeated cancellation kept status live; four rhythm clips "
              "completed via TUI; return to locomotion passed.")
        return
    if args.motion_modes:
        terminal = (output / "launcher.txt").read_text(errors="replace")
        for name in config["rl_policy"]["onnx_infer"]["policy_names"]:
            label = config["rl_policy"]["onnx_infer"]["policies"][name]["display_name"]
            if label not in terminal:
                raise RuntimeError(f"Missing policy display name in TUI: {label}")
            with (control_dir / f"control_policy_{name}.csv").open() as stream:
                inference = list(csv.DictReader(stream))
            if len(inference) < 100 or any(row["result"] != "published" for row in inference):
                raise RuntimeError(f"Incomplete motion policy inference: {name}")
        first, last = trace.index(rl_rows[0]), trace.index(rl_rows[-1])
        if any(row["state"] != "RL" for row in trace[first:last + 1]):
            raise RuntimeError("Live switching interrupted RL actuation")
        print("PASS: all three motion policies via TUI, dance playback, continuous RL, no faults.")
        return
    if args.stairs:
        artifacts = next((output / "logs").glob("*_driver_*/artifacts.csv")).read_text()
        if "scene_stairs.xml" not in artifacts:
            raise RuntimeError("Launcher did not select the stairs scene")
        with (control_dir / "control_policy_walk_obstacle_mnn.csv").open() as stream:
            inference = list(csv.DictReader(stream))
        if len(inference) < 1200 or any(row["result"] != "published" for row in inference):
            raise RuntimeError("Incomplete obstacle policy inference")
        if "motion" not in {row["model_variant"] for row in inference}:
            raise RuntimeError("Obstacle motion model was not activated")
        print("PASS: --sim --stairs loaded through launcher; obstacle locomotion, no faults.")
        return
    with (control_dir / "control_policy_walk_mnn.csv").open() as stream:
        inference = list(csv.DictReader(stream))
    if len(inference) < 1400 or any(row["result"] != "published" for row in inference):
        raise RuntimeError("Inference sequence incomplete")
    variants = {row["model_variant"] for row in inference}
    if args.gestures:
        if variants != {"stance"}:
            raise RuntimeError(f"Gesture test must remain in stance: {variants}")
        names = {row["interaction_action"] for row in inference}
        expected = set(config["arm_interactions"]["action_names"])
        if not expected.issubset(names):
            raise RuntimeError(f"Missing gesture execution: {expected - names}")
        gains = [float(row["left_shoulder_pitch_joint.kp"]) for row in joints.values()]
        if abs(max(gains) - 90) > 1e-6:
            raise RuntimeError("Trajectory gains did not reach the driver command")
        print(f"PASS: {len(inference)} frames, all {len(expected)} gestures via TUI, cancel and "
              "state exit, one continuous stance RL session, no faults.")
        return
    if variants != {"stance", "motion", "turn"}:
        raise RuntimeError(f"Missing model routes: {variants}")
    print(f"PASS: {len(inference)} inference frames, 30 s continuous RL, no faults; "
          "stance -> motion -> stance -> turn -> stance.")


if __name__ == "__main__":
    main()
