#!/usr/bin/env python3
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Offline tests for the log-only manual calibration helper."""

import csv
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "calibration", Path(__file__).resolve().parents[1] / "scripts/record_g1_calibration.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CalibrationTests(unittest.TestCase):
    def test_no_unsupported_waist_prompts(self):
        self.assertFalse(any(name.startswith("waist_") for name in MODULE.TESTS))

    def test_pose_and_refusal(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            motor = {"motor_alias_1.received": 1, "motor_alias_1.fresh": 1,
                     "motor_alias_1.command_valid": 0, "motor_alias_1.error_raw": 0,
                     "motor_alias_1.age_s": 0.001, "motor_alias_1.raw_pos": 0.25,
                     "motor_alias_1.calibrated_pos": -0.25}
            joint = {"left_hip_pitch_joint.valid": 1, "left_hip_pitch_joint.position": -0.25}
            imu = {"received": 1, "fresh": 1,
                   **dict.fromkeys(["qx", "qy", "qz", "roll", "pitch", "yaw", "ax", "ay", "az"], 0),
                   "qw": 1}

            def save(stem, data):
                with (directory / f"{stem}.csv").open("w", newline="") as stream:
                    writer = csv.DictWriter(stream, ["wall_time_s", *data])
                    writer.writeheader()
                    for i in range(20):
                        writer.writerow({"wall_time_s": 1000.05 + i * 0.02, **data})

            def record():
                with patch("builtins.input", return_value=""), patch.object(MODULE.time, "sleep"), \
                        patch.object(MODULE.time, "time", side_effect=[1000, 1001]):
                    return MODULE.pose(directory, "offline fixture", 1)

            save("driver_motor", motor)
            save("driver_joint", joint)
            save("driver_imu", imu)
            value = record()
            self.assertEqual(value["motor"]["motor_alias_1.raw_pos"]["mean"], 0.25)
            self.assertEqual(value["max_motor_age_ms"], 1.0)
            for field, invalid in (("motor_alias_1.fresh", 0), ("motor_alias_1.command_valid", 1),
                                   ("motor_alias_1.error_raw", 3)):
                changed = {**motor, field: invalid}
                save("driver_motor", changed)
                with self.assertRaises(RuntimeError):
                    record()
            save("driver_motor", motor)
            save("driver_joint", {**joint, "left_hip_pitch_joint.valid": 0})
            with self.assertRaises(RuntimeError):
                record()
            with self.assertRaises(RuntimeError):
                MODULE.csv_rows(directory, "driver_motor", 2000, 2001)

    def test_finite_and_difference(self):
        with self.assertRaises(RuntimeError):
            MODULE.mean_fields([{"x": "nan"}], ["x"])
        first = {"joint": {"x": {"mean": 1}}}
        second = {"joint": {"x": {"mean": 1.2}}}
        self.assertAlmostEqual(MODULE.difference(first, second, "joint")["x"], 0.2)


if __name__ == "__main__":
    unittest.main()
