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
            ("LT+A", ""): ("policy", "walk_mjlab", 1000, "press"),
            ("LT+B", ""): ("policy", "walk_rlgym", 1000, "press"),
            ("LT+X", ""): ("policy", "dance_mode", 1000, "press"),
            ("LT+Y", ""): ("policy", "sonic", 1000, "press"),
            ("LT+UP", ""): ("policy", "protomotions", 1000, "press"),
            ("LT+DOWN", ""): ("policy", "stand", 1000, "press"),
            ("RT+A", "dance_mode"): ("action", "dance", 1000, "press"),
            ("RT+B", "dance_mode"): ("action", "kungfu", 1000, "press"),
            ("RT+X", "dance_mode"): ("action", "dance1", 1000, "press"),
            ("RT+Y", "dance_mode"): ("action", "packed", 1000, "press"),
            ("RT+UP", "dance_mode"): ("action", "jumps1", 1000, "press"),
            ("Y", "walk_mjlab"): ("preset", "toggle", 0, "tap"),
            ("Y", "walk_rlgym"): ("preset", "toggle", 0, "tap"),
            ("RT+A", "sonic"): ("action", "dance_in_da_party", 1000, "press"),
            ("RT+A", "protomotions"): ("action", "walk", 1000, "press"),
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
        self.assertEqual(len(mapped), 6)
        self.assertEqual(catalog["default_policy"], "walk_mjlab")
        for name, policy in catalog["policies"].items():
            if "policy_actions" not in policy:
                self.assertTrue(policy["model_path"].endswith(".onnx"))
            self.assertEqual(policy["switch_group"], "full_body")
            if name not in ("walk_mjlab", "walk_rlgym"):
                self.assertEqual(policy["command"]["limits"], {"max_vx": 0, "max_vy": 0, "max_wz": 0})
        self.assertEqual(self.config["sonic_actions"]["action_names"], ["dance_in_da_party"])

    def test_modes_wait_for_explicit_actions(self):
        catalog = self.config["rl_policy"]["onnx_infer"]
        policies = catalog["policies"]
        for mode in catalog["policy_names"]:
            self.assertIn("运控", policies[mode]["display_name"])
        dance = policies["dance_mode"]["policy_actions"]
        self.assertEqual(dance["idle_policy"], "stand")
        self.assertEqual(dance["action_names"], ["dance", "kungfu", "dance1", "packed", "jumps1"])
        for mode in ("dance_mode", "protomotions"):
            actions = policies[mode]["policy_actions"]
            for key in actions["action_names"]:
                target = actions["actions"][key]["policy"]
                self.assertNotIn(target, catalog["policy_names"])
                self.assertNotIn("prerequisite", policies[target])
                self.assertNotIn("return_policy", policies[target])
            bound = {b["value"] for b in self.bindings
                     if b["operation"] == "action" and b.get("policy") == mode}
            self.assertEqual(bound, set(actions["action_names"]))

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
        self.assertEqual(teleop["slow_limits"], [0.3, 0.3, 0.5])
        self.assertEqual(teleop["fast_limits"], [0.5, 0.3, 0.5])
        policies = self.config["rl_policy"]["onnx_infer"]["policies"]
        for name in ("walk_mjlab", "walk_rlgym"):
            with self.subTest(policy=name):
                limits = policies[name]["command"]["limits"]
                self.assertEqual(limits["min_vx"], -0.3)
                self.assertGreaterEqual(limits["max_vx"], 0.5)
                self.assertGreaterEqual(limits["max_vy"], 0.3)
                self.assertGreaterEqual(limits["max_wz"], 0.5)


if __name__ == "__main__":
    unittest.main()
