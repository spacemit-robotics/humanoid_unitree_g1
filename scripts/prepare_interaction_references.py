#!/usr/bin/env python3
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Build SONIC CSV and SuperMimic NPZ references from timed upper-body trajectories.

Each input YAML has ``time`` (seconds) and ``q`` (radians, N x 17): left arm 7,
right arm 7, waist yaw/roll/pitch. The legs and pelvis retain each tracker's
standby reference. Both ends blend to that same standby pose. Optional ``hold``
keeps the last input pose for --hold-last seconds before returning to standby.
The outputs are reference inputs to the trackers, not motor command overrides.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import yaml

from prepare_supermimic_assets import FPS, G1_DIR, compose, sha256, write_reference


def load_trajectory(path, hold_last):
    """Validate timed keyframes and resample their linear trajectory to 50 Hz."""
    source = yaml.safe_load(path.read_text())
    times = np.asarray(source["time"], dtype=np.float64)
    positions = np.asarray(source["q"], dtype=np.float64)
    if (times.ndim != 1 or len(times) < 2 or positions.shape != (len(times), 17)
            or not np.isfinite(times).all() or not np.isfinite(positions).all()
            or times[0] != 0 or np.any(np.diff(times) <= 0)):
        raise ValueError(f"{path.name}: expected increasing times from zero and finite N x 17 joint positions")
    duration = times[-1] + (hold_last if source.get("hold", False) else 0.0)
    samples = np.arange(int(np.ceil(duration * FPS - 1.0e-9)) + 1) / FPS
    return np.column_stack([np.interp(samples, times, positions[:, joint]) for joint in range(17)])


def load_standby(policy, catalog):
    """Read the configured default reference, converting SONIC back to canonical joint order."""
    path = G1_DIR / catalog["actions"][catalog["default_action"]]["file"]
    if policy["policy_adapter"]["type"] == "sonic":
        joint_pos = np.loadtxt(path / "joint_pos.csv", delimiter=",", skiprows=1, ndmin=2)
        quat = np.loadtxt(path / "body_quat.csv", delimiter=",", skiprows=1, ndmin=2)
        canonical = np.empty_like(joint_pos)
        canonical[:, policy["action_joint_index"]] = joint_pos
        root_pos = np.zeros((len(canonical), 3))  # SONIC does not consume root position.
    else:
        with np.load(path, allow_pickle=False) as reference:
            canonical = reference["joint_pos"].astype(np.float64)
            root_pos = reference["body_pos_w"][:, 0].astype(np.float64)
            quat = reference["body_quat_w"][:, 0].astype(np.float64)
    for name, values in (("joint_pos", canonical), ("root_pos", root_pos), ("root_quat", quat)):
        if not np.isfinite(values).all() or not np.allclose(values, values[0], atol=1.0e-6):
            raise ValueError(f"standby {name} must be static and finite")
    return {"joint_pos": canonical[0], "height": root_pos[0, 2], "tilt": quat[0]}, root_pos[0]


def build_reference(upper_body, stance, root_pos, hold, blend):
    """Compose a full-body reference in G1 canonical joint order."""
    count = len(upper_body)
    joint_pos = np.repeat(stance["joint_pos"][None], count, axis=0)
    joint_pos[:, 15:29] = upper_body[:, :14]
    joint_pos[:, 12:15] = upper_body[:, 14:17]
    clip = {"joint_pos": joint_pos,
            "root_pos": np.repeat(root_pos[None], count, axis=0),
            "root_quat": np.repeat(stance["tilt"][None], count, axis=0)}
    return compose(clip, stance, hold, blend)


def write_sonic(directory, motion, joint_order):
    """Write the three files consumed by the SONIC adapter, in model joint order."""
    directory.mkdir(parents=True, exist_ok=True)
    columns = ",".join(f"joint_{joint}" for joint in range(29))
    for name, values, header in (
            ("joint_pos", motion["joint_pos"][:, joint_order], columns),
            ("joint_vel", np.gradient(motion["joint_pos"], 1 / FPS, axis=0)[:, joint_order], columns),
            ("body_quat", motion["root_quat"], "w,x,y,z")):
        np.savetxt(directory / f"{name}.csv", values, delimiter=",", fmt="%.9g", header=header, comments="")


def main():
    """Generate only requested interactions; leave existing models and other references intact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--motion", action="append", required=True, metavar="ID=YAML")
    parser.add_argument("--hold", type=float, default=0.5, help="Standby at each end, seconds")
    parser.add_argument("--blend", type=float, default=1.5, help="Transition at each end, seconds")
    parser.add_argument("--hold-last", type=float, default=2.0, help="Final pose dwell for hold:true inputs, seconds")
    args = parser.parse_args()
    if (not np.isfinite([args.hold, args.blend, args.hold_last]).all()
            or args.hold < 0 or args.hold_last < 0 or args.blend * FPS < 1):
        parser.error("hold times must be nonnegative; blend must span at least one frame")
    config = yaml.safe_load((G1_DIR / "config/g1.yaml").read_text())
    policies = config["rl_policy"]["onnx_infer"]["policies"]
    sources = {}
    for argument in args.motion:
        name, separator, filename = argument.partition("=")
        if not separator or not name or name in sources:
            parser.error("provide unique ID=YAML arguments")
        path = Path(filename)
        sources[name] = (path, load_trajectory(path, args.hold_last))

    for mode, prefix in (("sonic", ""), ("supermimic_mode", "sm_")):
        policy = policies[mode]
        catalog = config[policy["policy_adapter"]["catalog"]]
        stance, root_pos = load_standby(policy, catalog)
        manifest = {}
        for name, (path, upper_body) in sources.items():
            action = prefix + name
            if action not in catalog["action_names"]:
                parser.error(f"{mode}: {action} is not in the configured action list")
            motion = build_reference(upper_body, stance, root_pos, args.hold, args.blend)
            lower = np.asarray(policy["target_position_lower"])
            upper = np.asarray(policy["target_position_upper"])
            if np.any(motion["joint_pos"] < lower - 1.0e-6) or np.any(motion["joint_pos"] > upper + 1.0e-6):
                raise ValueError(f"{mode}/{action}: reference exceeds configured joint limits")
            output = G1_DIR / catalog["actions"][action]["file"]
            if mode == "sonic":
                write_sonic(output, motion, policy["action_joint_index"])
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                write_reference(output, motion)
            manifest[action] = {"input": path.name, "input_sha256": sha256(path), "fps": FPS,
                                "frames": len(motion["joint_pos"]),
                                "duration_s": (len(motion["joint_pos"]) - 1) / FPS,
                                "standby_hold_s": args.hold, "blend_s": args.blend,
                                "hold_last_s": args.hold_last}
            print(f"{mode}/{action}: {manifest[action]['duration_s']:.2f} s -> {output.relative_to(G1_DIR)}")
        folder = "sonic" if mode == "sonic" else "supermimic"
        manifest_path = G1_DIR / "policy" / folder / "INTERACTIONS.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
