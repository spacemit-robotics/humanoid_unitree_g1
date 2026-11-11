#!/usr/bin/env python3
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Verify the machine's policy catalog and GameSir button table offline."""

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
            ("LT+A", ""): ("policy", "stand", 1000, "press"),
            ("LT+B", ""): ("policy", "walk_mjlab", 1000, "press"),
            ("LT+X", ""): ("policy", "dance_mode", 1000, "press"),
            ("LT+Y", ""): ("policy", "sonic", 1000, "press"),
            ("LT+UP", ""): ("policy", "sonic_planner", 1000, "press"),
            ("LT+DOWN", ""): ("policy", "walk_rlgym", 1000, "press"),
            ("LT+LEFT", ""): ("policy", "supermimic_mode", 1000, "press"),
            ("RT+A", "dance_mode"): ("action", "dance", 1000, "press"),
            ("RT+B", "dance_mode"): ("action", "kungfu", 1000, "press"),
            ("RT+X", "dance_mode"): ("action", "dance1", 1000, "press"),
            ("RT+Y", "dance_mode"): ("action", "packed", 1000, "press"),
            ("RT+UP", "dance_mode"): ("action", "jumps1", 1000, "press"),
            ("RT+A", "supermimic_mode"): ("action", "sm_walk", 1000, "press"),
            ("RT+B", "supermimic_mode"): ("action", "sm_clap", 1000, "press"),
            ("RT+X", "supermimic_mode"): ("action", "sm_point", 1000, "press"),
            ("RT+Y", "supermimic_mode"): ("action", "sm_dance", 1000, "press"),
            ("Y", "walk_mjlab"): ("preset", "toggle", 0, "tap"),
            ("Y", "walk_rlgym"): ("preset", "toggle", 0, "tap"),
            ("Y", "sonic_planner"): ("preset", "toggle", 0, "tap"),
            ("RT+A", "sonic"): ("action", "standing", 1000, "press"),
            ("RT+B", "sonic"): ("action", "walk", 1000, "press"),
            ("RT+X", "sonic"): ("action", "macarena", 1000, "press"),
            ("RT+UP", "sonic"): ("action", "slow_walk", 1000, "press"),
            ("RT", ""): ("cancel", "", 1000, "press"),
        }
        actual = {
            ("+".join(b["buttons"]), b.get("policy", "")):
                (b["operation"], b.get("value", ""), b.get("hold_ms", 0), b.get("trigger", "press"))
            for b in self.bindings
        }
        self.assertEqual(len(actual), len(self.bindings))
        self.assertEqual(actual, expected)

    def test_catalog(self):
        catalog = self.config["rl_policy"]["onnx_infer"]
        mapped = {binding["value"] for binding in self.bindings if binding["operation"] == "policy"}
        self.assertEqual(mapped, set(catalog["policy_names"]))
        self.assertEqual(len(mapped), 7)
        self.assertNotIn("protomotions", catalog["policy_names"])
        self.assertEqual(catalog["default_policy"], "stand")
        for name, policy in catalog["policies"].items():
            if "policy_actions" not in policy:
                self.assertTrue(policy["model_path"].endswith(".onnx"))
            self.assertEqual(policy["switch_group"], "full_body")
            if name not in ("stand", "walk_mjlab", "walk_rlgym", "sonic_planner"):
                self.assertEqual(policy["command"]["limits"], {"max_vx": 0, "max_vy": 0, "max_wz": 0})
        self.assertEqual(self.config["sonic_actions"]["action_names"],
                         ["standing", "slow_walk", "walk", "macarena"])

    def test_locomode_commands_and_motion_actions(self):
        policies = self.config["rl_policy"]["onnx_infer"]["policies"]
        self.assertEqual(policies["stand"]["command"]["scale"], [1.0, 1.0, 1.0])
        self.assertEqual(policies["stand"]["command"]["limits"],
                         {"min_vx": -0.4, "max_vx": 0.7, "max_vy": 0.4, "max_wz": 1.57})
        for name in ("dance", "kungfu"):
            self.assertEqual(policies[name]["action_blend_ratio"], 1.0)

    def test_modes_wait_for_explicit_actions(self):
        catalog = self.config["rl_policy"]["onnx_infer"]
        policies = catalog["policies"]
        for mode in catalog["policy_names"]:
            self.assertIn("运控", policies[mode]["display_name"])
        dance = policies["dance_mode"]["policy_actions"]
        self.assertEqual(dance["idle_policy"], "stand")
        self.assertEqual(dance["action_names"], ["dance", "kungfu", "dance1", "packed", "jumps1"])
        for mode in ("dance_mode",):
            actions = policies[mode]["policy_actions"]
            for key in actions["action_names"]:
                target = actions["actions"][key]["policy"]
                self.assertNotIn(target, catalog["policy_names"])
                self.assertNotIn("prerequisite", policies[target])
                self.assertNotIn("return_policy", policies[target])
            bound = {b["value"] for b in self.bindings
                     if b["operation"] == "action" and b.get("policy") == mode}
            self.assertEqual(bound, set(actions["action_names"]))

    def test_supermimic_catalog(self):
        policy = self.config["rl_policy"]["onnx_infer"]["policies"]["supermimic_mode"]
        self.assertNotIn("policy_actions", policy)
        self.assertEqual(policy["policy_adapter"], {"type": "supermimic", "catalog": "supermimic_actions",
                                                    "anchor_body_index": 0})
        home = self.config["behavior_manager"]["home"]
        self.assertEqual(policy["target_position_lower"], home["target_position_lower"])
        self.assertEqual(policy["target_position_upper"], home["target_position_upper"])
        self.assertNotIn("zero_target_pos", policy)
        catalog = self.config["supermimic_actions"]
        self.assertEqual(catalog["default_action"], "sm_standby")
        self.assertEqual(catalog["action_names"],
                         ["sm_standby", "sm_walk", "sm_clap", "sm_point", "sm_dance", "sm_langzi_tiqiu"])
        self.assertEqual(list(catalog["actions"]), catalog["action_names"])
        for name, action in catalog["actions"].items():
            self.assertEqual(action["file"], f"policy/supermimic/references/{name.removeprefix('sm_')}.npz")
        bound = {b["value"] for b in self.bindings
                 if b["operation"] == "action" and b.get("policy") == "supermimic_mode"}
        self.assertEqual(bound, {"sm_walk", "sm_clap", "sm_point", "sm_dance"})

    def test_unique_yaml_keys(self):
        package = Path(__file__).resolve().parents[1]

        def visit(node):
            if isinstance(node, yaml.MappingNode):
                keys = [key.value for key, _value in node.value]
                self.assertEqual(len(keys), len(set(keys)), str(node.start_mark))
                for _key, value in node.value:
                    visit(value)
            elif isinstance(node, yaml.SequenceNode):
                for value in node.value:
                    visit(value)

        visit(yaml.compose((package / "config/g1.yaml").read_text()))

    def test_physical_keys(self):
        self.assertEqual(self.config["operator_gamepad"]["button_codes"], {"CAPTURE": 317})
        self.assertFalse(any("M" in b["buttons"] for b in self.bindings))
        self.assertFalse(any(b["buttons"] == ["BACK", "START"] for b in self.bindings))

    def test_speed_presets_only_increase_forward_speed(self):
        teleop = self.config["operator_service"]["teleop"]
        self.assertEqual(teleop["slow_limits"], [0.6, 0.3, 0.5])
        self.assertEqual(teleop["fast_limits"], [1.0, 0.3, 0.5])
        self.assertEqual(teleop["acceleration"], [1.0, 1.0, 2.0])
        self.assertEqual(teleop["deceleration"], [2.5, 0.5, 2.5])
        policies = self.config["rl_policy"]["onnx_infer"]["policies"]
        forward_limits = {"stand": 0.7, "walk_mjlab": 1.0, "walk_rlgym": 0.8, "sonic_planner": 0.8}
        reverse_limits = {"stand": 0.4, "walk_mjlab": 0.5, "walk_rlgym": 0.6, "sonic_planner": 0.3}
        for name, forward in forward_limits.items():
            with self.subTest(policy=name):
                limits = policies[name]["command"]["limits"]
                presets = policies[name]["command"].get("teleop", teleop)
                self.assertEqual(limits["min_vx"], -reverse_limits[name])
                self.assertEqual(limits["max_vx"], forward)
                self.assertEqual(min(presets["slow_limits"][0], limits["max_vx"]),
                                 0.7 if name == "stand" else 0.6)
                self.assertEqual(min(presets["fast_limits"][0], limits["max_vx"]), forward)
                for preset in ("slow_limits", "fast_limits"):
                    self.assertEqual(max(-presets[preset][0], limits["min_vx"]), -reverse_limits[name])
                self.assertGreaterEqual(limits["max_vy"], 0.3)
                self.assertGreaterEqual(limits["max_wz"], 0.5)


if __name__ == "__main__":
    unittest.main()
