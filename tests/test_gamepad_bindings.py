#!/usr/bin/env python3
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Verify the agreed GameSir button table and existing action/voice IDs offline."""

from pathlib import Path
import unittest

import yaml


class GamepadBindingsTest(unittest.TestCase):
    """Keep the machine's mapping distinct from the generic input implementation."""

    def setUp(self):
        package = Path(__file__).resolve().parents[1]
        self.config = yaml.safe_load((package / "config/g1.yaml").read_text())
        self.bindings = self.config["operator_gamepad"]["bindings"]

    def test_full_mapping(self):
        expected = {
            ("CAPTURE", ""): ("control", "", 0, "tap"),
            ("BACK", ""): ("state", "POWER_OFF", 1000, "press"),
            ("START", ""): ("state", "DAMP", 1000, "press"),
            ("LB", ""): ("state", "HOME", 1000, "press"),
            ("RB", ""): ("state", "ZERO", 1000, "press"),
            ("LB+RB", ""): ("state", "RL", 1000, "press"),
            ("R3", ""): ("ack", "", 0, "tap"),
            ("LT+A", ""): ("policy", "walk_mnn", 1000, "press"),
            ("LT+B", ""): ("policy", "walk_obstacle_mnn", 1000, "press"),
            ("LT+X", ""): ("policy", "dance_mnn", 1000, "press"),
            ("Y", "walk_mnn"): ("preset", "toggle", 0, "tap"),
            ("Y", "walk_obstacle_mnn"): ("preset", "toggle", 0, "tap"),
            ("RT+A", "walk_mnn"): ("action", "shake_hand", 0, "tap"),
            ("RT+B", "walk_mnn"): ("action", "wave_under_head", 0, "tap"),
            ("RT+X", "walk_mnn"): ("action", "blow_kiss_with_right_hand", 0, "tap"),
            ("RT+Y", "walk_mnn"): ("action", "clamp", 0, "tap"),
            ("RT+UP", "walk_mnn"): ("action", "wave_above_head", 0, "tap"),
            ("RT", ""): ("cancel", "", 1000, "press"),
        }
        for index, key in enumerate("ABXY", 1):
            expected[(f"RT+{key}", "dance_mnn")] = ("action", f"rhythm_{index}", 1000, "press")
        actual = {
            ("+".join(b["buttons"]), b.get("policy", "")):
                (b["operation"], b.get("value", ""), b.get("hold_ms", 0), b.get("trigger", "press"))
            for b in self.bindings
        }
        self.assertEqual(len(actual), len(self.bindings))
        self.assertEqual(actual, expected)

    def test_existing_actions_and_audio(self):
        catalog = {"walk_mnn": self.config["arm_interactions"]["action_names"],
                   "dance_mnn": self.config["dance_actions"]["action_names"]}
        for policy, actions in catalog.items():
            mapped = {b["value"] for b in self.bindings
                      if b["operation"] == "action" and b.get("policy") == policy}
            self.assertEqual(mapped, set(actions))
            for action in mapped:
                self.assertIn(f"action.{action}", self.config["audio_prompts"]["clips"])

    def test_physical_keys(self):
        self.assertEqual(self.config["operator_gamepad"]["button_codes"], {"CAPTURE": 317})
        self.assertFalse(any("M" in b["buttons"] for b in self.bindings))
        self.assertFalse(any(b["buttons"] == ["BACK", "START"] for b in self.bindings))

    def test_speed_presets_only_increase_forward_speed(self):
        teleop = self.config["operator_service"]["teleop"]
        self.assertEqual(teleop["slow_limits"], [0.6, 0.6, 1.0])
        self.assertEqual(teleop["fast_limits"], [1.5, 0.6, 1.0])
        policies = self.config["rl_policy"]["onnx_infer"]["policies"]
        for name in ("walk_mnn", "walk_obstacle_mnn"):
            with self.subTest(policy=name):
                limits = policies[name]["command"]["limits"]
                self.assertEqual(limits["min_vx"], -0.6)
                self.assertGreaterEqual(limits["max_vx"], 1.5)
                self.assertEqual(limits["max_vy"], 0.6)
                self.assertEqual(limits["max_wz"], 1.0)


if __name__ == "__main__":
    unittest.main()
