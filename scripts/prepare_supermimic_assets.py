#!/usr/bin/env python3
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Prepare the SuperMimic policy and references used by config/g1.yaml.

Inputs stay outside the SDK and keep their own licenses:

* NJU SuperMimic-Repro-Sim2Real release ``e13i_0291000`` (``policy_ir9.onnx``, ``deploy_config.json``);
* BONES-SEED G1 clips packed in ProtoMotions ``g1_bones_seed_mini.pt`` (source ``bones``);
* NJU ``motions/custom_dance`` CSVs, the dances e13i was fine-tuned on (source ``nju``).

``supermimic_mode`` keeps one policy instance for standby and actions: it holds the static default
action of ``supermimic_actions`` and swaps in an action reference on request. The standby pose is the
policy's ``rl_default_pos`` with an upright pelvis at the height where the MJCF sole spheres touch the
ground. Every action reference starts and ends there, holding it and blending into and out of the
clip. ``SOURCE:CLIP@START-STOP`` removes that interval (whole gait cycles) from a clip. Output
(``policy/supermimic``)::

    policy.onnx           obs_hist [1, 930], goal [1, 680] -> actions [1, 29]
    deploy_config.json    release constants: gains, default pose, joint limits
    references/<id>.npz   50 Hz joint_pos/joint_vel [T, 29] and pelvis body_*_w [T, 1, *],
                          including the static standby reference of the default action
    SOURCES.json          input checksums and per-clip checks
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import yaml

FPS = 50.0
NUM_JOINTS = 29
G1_DIR = Path(__file__).resolve().parents[1]
RENAMES = {"obs": "obs_hist", "goal": "goal", "action": "actions"}
DEFAULT_CLIPS = {
    "walk": "bones:short_walk_180_R_max_003__A076_M@3.52-6.98",
    "clap": "bones:clap_forced_002__A058_M",
    "point": "bones:point_dir_horizontal_right_hand_head_270_R_004__A201_M",
    "dance": "nju:shanshenbu",
}


def sha256(path):
    """Return the SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_config(name, policy, constants):
    """Require the YAML policy contract to match the release constants."""
    pairs = {"rl_default_pos": "default_joint_pos", "action_scale": "action_scale", "kp": "kp", "kd": "kd"}
    for key, release in pairs.items():
        if not np.allclose(policy[key], constants[release], rtol=1.0e-4, atol=1.0e-3):
            raise SystemExit(f"{name}.{key} differs from deploy_config.json {release}")
    if policy["action_joint_index"] != list(range(NUM_JOINTS)):
        raise SystemExit(f"{name} must use canonical joint order")


def export_policy(bundle, output):
    """Rename the release model's interface to the SDK contract and verify identical outputs."""
    import onnx
    import onnxruntime as ort

    source = bundle / "policy_ir9.onnx"
    model = onnx.load(str(source))
    if [value.name for value in model.graph.input] != ["obs", "goal"] or \
            [value.name for value in model.graph.output] != ["action"]:
        raise SystemExit("unexpected NJU policy interface")
    if {value.name for value in model.graph.initializer} & set(RENAMES.values()):
        raise SystemExit("policy graph already uses a target tensor name")
    for value in list(model.graph.input) + list(model.graph.output) + list(model.graph.value_info):
        value.name = RENAMES.get(value.name, value.name)
    for node in model.graph.node:
        node.input[:] = [RENAMES.get(name, name) for name in node.input]
        node.output[:] = [RENAMES.get(name, name) for name in node.output]
    onnx.checker.check_model(model)
    target = output / "policy.onnx"
    onnx.save(model, str(target))

    original = ort.InferenceSession(str(source), providers=["CPUExecutionProvider"])
    renamed = ort.InferenceSession(str(target), providers=["CPUExecutionProvider"])
    rng = np.random.default_rng(0)
    for _ in range(8):
        obs = rng.standard_normal((1, 930)).astype(np.float32)
        goal = rng.standard_normal((1, 680)).astype(np.float32)
        expected = original.run(None, {"obs": obs, "goal": goal})[0]
        if not np.array_equal(expected, renamed.run(None, {"obs_hist": obs, "goal": goal})[0]):
            raise SystemExit("renamed policy output differs from the release model")
    shutil.copyfile(bundle / "deploy_config.json", output / "deploy_config.json")
    return {"source": "SuperMimic-Repro-Sim2Real/e13i_0291000", "input": source.name,
            "input_sha256": sha256(source), "output_sha256": sha256(target)}


def load_bones(library, clip):
    """Read one clip from a ProtoMotions library: body 0 is the pelvis, quaternions are xyzw."""
    names = [name.removesuffix(".motion") for name in library["motion_files"]]
    if clip not in names:
        raise SystemExit(f"{clip} is not in the BONES library")
    index = names.index(clip)
    start = int(library["length_starts"][index])
    stop = start + int(library["motion_num_frames"][index])
    return {
        "fps": 1.0 / float(library["motion_dt"][index]),
        "root_pos": library["gts"][start:stop, 0].numpy().astype(np.float64),
        "root_quat": library["grs"][start:stop, 0].numpy().astype(np.float64)[:, [3, 0, 1, 2]],
        "joint_pos": library["dps"][start:stop].numpy().astype(np.float64),
    }


def load_nju(path):
    """Read an NJU CSV: 30 fps, pelvis xyz, pelvis quaternion xyzw, 29 joints in motor order."""
    table = np.loadtxt(path, delimiter=",", ndmin=2)
    if table.shape[1] != 7 + NUM_JOINTS:
        raise SystemExit(f"{path}: expected {7 + NUM_JOINTS} columns")
    return {"fps": 30.0, "root_pos": table[:, 0:3], "root_quat": table[:, [6, 3, 4, 5]],
            "joint_pos": table[:, 7:]}


def quat_mul(a, b):
    """Multiply wxyz quaternions."""
    aw, ax, ay, az = np.moveaxis(a, -1, 0)
    bw, bx, by, bz = np.moveaxis(b, -1, 0)
    return np.stack([aw * bw - ax * bx - ay * by - az * bz,
                     aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw], axis=-1)


def conjugate(quat):
    """Inverse of a unit wxyz quaternion."""
    return quat * np.array([1.0, -1.0, -1.0, -1.0])


def continuous(quat):
    """Normalize quaternions and keep adjacent frames in the same hemisphere."""
    quat = quat / np.linalg.norm(quat, axis=-1, keepdims=True)
    for frame in range(1, len(quat)):
        if np.dot(quat[frame], quat[frame - 1]) < 0.0:
            quat[frame] = -quat[frame]
    return quat


def slerp(q0, q1, alpha):
    """Spherical interpolation between wxyz quaternions."""
    q1 = np.where(np.sum(q0 * q1, axis=-1, keepdims=True) < 0.0, -q1, q1)
    theta = np.arccos(np.clip(np.sum(q0 * q1, axis=-1, keepdims=True), -1.0, 1.0))
    small = theta < 1.0e-6
    sin = np.where(small, 1.0, np.sin(theta))
    w0 = np.where(small, 1.0 - alpha, np.sin((1.0 - alpha) * theta) / sin)
    w1 = np.where(small, alpha, np.sin(alpha * theta) / sin)
    result = w0 * q0 + w1 * q1
    return result / np.linalg.norm(result, axis=-1, keepdims=True)


def rotate(quat, vectors):
    """Rotate vectors by a unit wxyz quaternion."""
    pure = np.concatenate([np.zeros(vectors.shape[:-1] + (1,)), vectors], axis=-1)
    return quat_mul(quat_mul(quat, pure), conjugate(quat))[..., 1:]


def heading(quat):
    """Yaw-only wxyz quaternion with the same heading."""
    w, x, y, z = quat
    yaw = np.arctan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
    return np.array([np.cos(yaw / 2.0), 0.0, 0.0, np.sin(yaw / 2.0)])


def standby_stance(joint_pos):
    """Idle pose with an upright pelvis at the height where the lowest MJCF sole sphere touches the ground."""
    import mujoco

    model = mujoco.MjModel.from_xml_path(str(G1_DIR / "resources/xml/g1_29dof_rev_1_0.xml"))
    if model.nq != 7 + NUM_JOINTS:
        raise SystemExit("unexpected G1 MJCF joint layout")
    data = mujoco.MjData(model)
    data.qpos[:] = 0.0
    data.qpos[3] = 1.0
    data.qpos[7:] = joint_pos
    mujoco.mj_kinematics(model, data)
    soles = [geom for geom in range(model.ngeom)
             if model.geom_type[geom] == mujoco.mjtGeom.mjGEOM_SPHERE and model.geom_contype[geom]]
    height = -min(data.geom_xpos[geom][2] - model.geom_size[geom][0] for geom in soles)
    return {"joint_pos": np.asarray(joint_pos, dtype=np.float64), "height": float(height),
            "tilt": np.array([1.0, 0.0, 0.0, 0.0])}


def resample(motion):
    """Resample a clip to 50 Hz with linear joints/positions and spherical orientations."""
    count = len(motion["joint_pos"])
    position = np.arange(0.0, (count - 1) / motion["fps"] + 0.5 / FPS, 1.0 / FPS) * motion["fps"]
    position = np.minimum(position, count - 1.0)
    first = np.floor(position).astype(int)
    second = np.minimum(first + 1, count - 1)
    alpha = (position - first)[:, None]
    quat = continuous(motion["root_quat"].copy())

    def lerp(values):
        return (1.0 - alpha) * values[first] + alpha * values[second]

    return {"joint_pos": lerp(motion["joint_pos"]), "root_pos": lerp(motion["root_pos"]),
            "root_quat": slerp(quat[first], quat[second], alpha)}


def remove_interval(motion, start, stop, fade=0.2):
    """Drop [start, stop) seconds of a periodic segment, aligning the remainder's root and cross-fading."""
    if not np.isfinite([start, stop, fade]).all() or fade <= 0:
        raise SystemExit("interval bounds and fade must be finite; fade must be positive")
    first, last, steps = (int(round(value * FPS)) for value in (start, stop, fade))
    if not 1 <= steps <= first < last < len(motion["joint_pos"]):
        raise SystemExit(f"interval {start}-{stop} s is outside the clip")
    turn = quat_mul(heading(motion["root_quat"][first]), conjugate(heading(motion["root_quat"][last])))
    root_pos = motion["root_pos"][first] + rotate(turn, motion["root_pos"][last - steps:] - motion["root_pos"][last])
    root_pos[:, 2] = motion["root_pos"][last - steps:, 2]
    rest = {"joint_pos": motion["joint_pos"][last - steps:], "root_pos": root_pos,
            "root_quat": quat_mul(turn, motion["root_quat"][last - steps:])}
    weight = (np.arange(1, steps + 1) / (steps + 1))[:, None]
    head = {key: value[first - steps:first] for key, value in motion.items()}
    joined = {"joint_pos": (1.0 - weight) * head["joint_pos"] + weight * rest["joint_pos"][:steps],
              "root_pos": (1.0 - weight) * head["root_pos"] + weight * rest["root_pos"][:steps],
              "root_quat": slerp(head["root_quat"], rest["root_quat"][:steps], weight)}
    spliced = {key: np.concatenate([motion[key][:first - steps], joined[key], rest[key][steps:]]) for key in motion}
    spliced["root_quat"] = continuous(spliced["root_quat"])
    return spliced


def transition(stance, frame, hold, blend, entering):
    """Standby hold plus cosine blend between the standby pose and one clip frame."""
    standing = quat_mul(heading(frame["root_quat"]), stance["tilt"])
    steps = int(round(blend * FPS))
    phase = 0.5 - 0.5 * np.cos(np.pi * np.arange(steps) / steps)
    weight = np.concatenate([np.zeros(int(round(hold * FPS))), phase])[:, None]
    if not entering:
        weight = weight[::-1]
    root_pos = np.repeat(frame["root_pos"][None], len(weight), axis=0)
    root_pos[:, 2] = stance["height"] + weight[:, 0] * (frame["root_pos"][2] - stance["height"])
    return {"joint_pos": stance["joint_pos"] + weight * (frame["joint_pos"] - stance["joint_pos"]),
            "root_pos": root_pos,
            "root_quat": slerp(np.repeat(standing[None], len(weight), axis=0),
                               np.repeat(frame["root_quat"][None], len(weight), axis=0), weight)}


def compose(clip, stance, hold, blend):
    """Concatenate standby entry, clip and standby exit."""
    first = {key: value[0] for key, value in clip.items()}
    last = {key: value[-1] for key, value in clip.items()}
    parts = [transition(stance, first, hold, blend, True), clip, transition(stance, last, hold, blend, False)]
    motion = {key: np.concatenate([part[key] for part in parts]) for key in clip}
    motion["root_quat"] = continuous(motion["root_quat"])
    return motion


def angular_velocity(quat):
    """World-frame angular velocity from central differences of wxyz quaternions."""
    following = np.concatenate([quat[1:], quat[-1:]])
    previous = np.concatenate([quat[:1], quat[:-1]])
    span = np.full((len(quat), 1), 2.0 / FPS)
    span[0] = span[-1] = 1.0 / FPS
    delta = quat_mul(following, conjugate(previous))
    delta = np.where(delta[:, :1] < 0.0, -delta, delta)
    norm = np.linalg.norm(delta[:, 1:], axis=-1, keepdims=True)
    axis = np.divide(delta[:, 1:], norm, out=np.zeros_like(delta[:, 1:]), where=norm > 1.0e-12)
    return axis * 2.0 * np.arctan2(norm, delta[:, :1]) / span


def write_reference(path, motion):
    """Write the arrays read by the common SuperMimic adapter; returns the velocities."""
    joint_vel = np.gradient(motion["joint_pos"], 1.0 / FPS, axis=0)
    lin_vel = np.gradient(motion["root_pos"], 1.0 / FPS, axis=0)

    def body(values):
        return values[:, None, :].astype(np.float32)

    np.savez(path, joint_pos=motion["joint_pos"].astype(np.float32), joint_vel=joint_vel.astype(np.float32),
             body_pos_w=body(motion["root_pos"]), body_quat_w=body(motion["root_quat"]),
             body_lin_vel_w=body(lin_vel), body_ang_vel_w=body(angular_velocity(motion["root_quat"])),
             fps=np.array([FPS], np.float32))
    return joint_vel, lin_vel


def check(name, motion, joint_vel, lin_vel, limits):
    """Summarize a reference against the G1 target envelope and the release velocity limits."""
    lower, upper, velocity_limit, names = limits
    outside = (motion["joint_pos"] < lower) | (motion["joint_pos"] > upper)
    speed = np.abs(joint_vel) / velocity_limit
    w, x, y, z = motion["root_quat"].T
    roll = np.arctan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))
    pitch = np.arcsin(np.clip(2.0 * (w * y - z * x), -1.0, 1.0))
    summary = {
        "seconds": round(len(motion["joint_pos"]) / FPS, 2),
        "travel_m": round(float(np.linalg.norm(motion["root_pos"][-1, :2] - motion["root_pos"][0, :2])), 2),
        "max_speed_mps": round(float(np.linalg.norm(lin_vel[:, :2], axis=1).max()), 2),
        "pelvis_z_m": [round(float(motion["root_pos"][:, 2].min()), 3),
                       round(float(motion["root_pos"][:, 2].max()), 3)],
        "max_roll_pitch_rad": round(float(max(np.abs(roll).max(), np.abs(pitch).max())), 2),
        "max_velocity_ratio": round(float(speed.max()), 2),
        "fastest_joint": names[int(np.argmax(speed.max(axis=0)))],
        "outside_frames": int(outside.any(axis=1).sum()),
        "outside_joints": [names[joint] for joint in np.flatnonzero(outside.any(axis=0))],
    }
    print(f"[supermimic] {name}: " + ", ".join(f"{key}={value}" for key, value in summary.items()))
    return summary


def main():
    """Generate the policy and reference package."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bundle", type=Path, required=True,
                        help="Extracted e13i_0291000 directory with policy_ir9.onnx and deploy_config.json")
    parser.add_argument("--bones-library", type=Path, help="ProtoMotions g1_bones_seed_mini.pt")
    parser.add_argument("--nju-motions", type=Path, help="NJU repository motions/custom_dance directory")
    parser.add_argument("--clip", action="append", default=[], metavar="ID=SOURCE:CLIP[@START-STOP]",
                        help="Reference to generate, SOURCE is bones or nju; START-STOP seconds are removed "
                             "(default: the config/g1.yaml set)")
    parser.add_argument("--hold", type=float, default=0.5, help="Seconds at the standby pose before and after")
    parser.add_argument("--blend", type=float, default=1.5, help="Seconds blending between standby and clip")
    parser.add_argument("--output", type=Path, default=G1_DIR / "policy/supermimic")
    args = parser.parse_args()
    if not np.isfinite([args.hold, args.blend]).all() or args.hold < 0 or args.blend * FPS < 1:
        parser.error("hold must be nonnegative and blend must span at least one frame")
    clips = dict(item.split("=", 1) for item in args.clip) if args.clip else DEFAULT_CLIPS
    library = None

    def load(spec):
        nonlocal library
        source, clip = spec.split(":", 1)
        clip, _, interval = clip.partition("@")
        if source == "bones" and args.bones_library:
            if library is None:
                import torch

                library = torch.load(str(args.bones_library), map_location="cpu", weights_only=True)
            origin, motion = args.bones_library, resample(load_bones(library, clip))
        elif source == "nju" and args.nju_motions:
            origin = args.nju_motions / f"{clip}.csv"
            motion = resample(load_nju(origin))
        else:
            raise SystemExit(f"{spec}: pass the input for source '{source}'")
        if interval:
            motion = remove_interval(motion, *(float(value) for value in interval.split("-")))
        return origin, motion

    constants = json.loads((args.bundle / "deploy_config.json").read_text())
    config = yaml.safe_load((G1_DIR / "config/g1.yaml").read_text())
    if constants["joint_names"] != config["robot_base"]["joint_names"]:
        raise SystemExit("release joint order differs from config/g1.yaml")
    policy = config["rl_policy"]["onnx_infer"]["policies"]["supermimic_mode"]
    check_config("supermimic_mode", policy, constants)
    catalog = config[policy["policy_adapter"]["catalog"]]
    files = {name: Path(action["file"]).name for name, action in catalog["actions"].items()}
    standby_file = files[catalog["default_action"]]
    if not args.clip and set(files.values()) != {standby_file} | {f"{name}.npz" for name in clips}:
        raise SystemExit("config/g1.yaml catalog files differ from the generated references")
    stance = standby_stance(policy["rl_default_pos"])
    limits = (np.asarray(policy["target_position_lower"]), np.asarray(policy["target_position_upper"]),
              np.asarray(constants["velocity_limit"]), constants["joint_names"])

    (args.output / "references").mkdir(parents=True, exist_ok=True)
    standby = {"joint_pos": np.repeat(stance["joint_pos"][None], 2, axis=0),
               "root_pos": np.repeat(np.array([[0.0, 0.0, stance["height"]]]), 2, axis=0),
               "root_quat": np.repeat(stance["tilt"][None], 2, axis=0)}
    write_reference(args.output / "references" / standby_file, standby)
    sources = {"policy": export_policy(args.bundle, args.output),
               "standby": {"action": catalog["default_action"], "file": standby_file,
                           "joint_pos": "supermimic_mode.rl_default_pos",
                           "pelvis_height_m": round(stance["height"], 4)},
               "references": {}}
    for name, spec in clips.items():
        origin, motion = load(spec)
        motion = compose(motion, stance, args.hold, args.blend)
        joint_vel, lin_vel = write_reference(args.output / "references" / f"{name}.npz", motion)
        sources["references"][name] = {"source": spec, "input": origin.name, "input_sha256": sha256(origin),
                                       "hold_s": args.hold, "blend_s": args.blend,
                                       **check(name, motion, joint_vel, lin_vel, limits)}
    (args.output / "SOURCES.json").write_text(json.dumps(sources, indent=2, ensure_ascii=False) + "\n")
    print(f"[supermimic] wrote {args.output}")


if __name__ == "__main__":
    main()
