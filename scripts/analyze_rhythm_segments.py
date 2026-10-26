# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Verify rhythm clip boundaries against quiet windows in the original latent trajectory."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import yaml


def analyze(config_path):
    """Report data-derived pauses and verify configured cuts stay inside them."""
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    root = config_path.parent.parent
    catalog = config["dance_actions"]
    names = catalog["action_names"]
    if names != [f"rhythm_{i}" for i in range(1, 5)]:
        raise ValueError("Only the four rhythm clips may be selectable")
    actions = [catalog["actions"][name] for name in names]
    paths = {action["file"] for action in actions}
    models = {action["model_path"] for action in actions}
    if len(paths) != 1 or len(models) != 1:
        raise ValueError("Rhythm clips must share the original data and decoder")
    path = root / actions[0]["file"]
    data = np.loadtxt(path, delimiter=",")
    dt = float(config["rl_policy"]["rl_dt"])
    if data.shape != (5385, 135) or not np.isfinite(data).all() or dt != 0.02:
        raise ValueError("Unexpected source shape, sampling period or nonfinite data")
    # First 128 columns are latent commands, not joint angles. This is an
    # activity measure for choosing pauses; closed-loop validation is separate.
    speed = np.linalg.norm(np.diff(data[:, :128], axis=0), axis=1) / dt
    window = 25
    threshold = 0.3
    quiet = np.convolve((speed < threshold).astype(int), np.ones(window, dtype=int),
                        mode="same") == window
    edges = np.flatnonzero(np.diff(np.r_[False, quiet, False]))
    pauses = [(int(start), int(end)) for start, end in zip(edges[::2], edges[1::2])
              if end - start >= window]
    if len(pauses) != 4:
        raise ValueError(f"Expected three separators and a closing pause; found {pauses}")
    clips = []
    for index, action in enumerate(actions):
        start = round(action["start_time"] / dt)
        end = round(action["end_time"] / dt)
        if not 0 <= start < end <= len(data):
            raise ValueError("Invalid frame interval")
        if index and not pauses[index - 1][0] <= start < pauses[index - 1][1]:
            raise ValueError(f"{names[index]} starts outside the preceding pause")
        if not pauses[index][0] <= end < pauses[index][1]:
            raise ValueError(f"{names[index]} ends outside its closing pause")
        clips.append({"key": names[index], "display_name": action["display_name"],
                      "start_frame": start, "end_frame_exclusive": end,
                      "start_s": start * dt, "end_s": end * dt,
                      "duration_s": round((end - start) * dt, 2)})
    return {"source": actions[0]["file"], "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "frames": len(data), "fps": 1 / dt, "duration_s": len(data) * dt,
            "activity": "L2 norm of latent first difference per second, not joint speed",
            "quiet_threshold": threshold, "quiet_window_frames": window,
            "quiet_intervals_s": [[round(a * dt, 2), round(b * dt, 2)] for a, b in pauses],
            "clips": clips}


def main():
    """Print the auditable segmentation report, optionally saving it as JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path,
                        default=Path(__file__).resolve().parents[1] / "config/g1.yaml")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.dumps(analyze(args.config), ensure_ascii=False, indent=2) + "\n"
    print(report, end="")
    if args.output:
        args.output.write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
