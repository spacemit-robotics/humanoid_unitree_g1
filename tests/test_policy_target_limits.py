#!/usr/bin/env python3
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Verify RL target envelopes and SONIC inference thread placement on G1."""

from pathlib import Path
import unittest

import yaml


class PolicyTargetLimitsTest(unittest.TestCase):
    """The hardware rejects out-of-range targets, so policies must clamp them first."""

    def setUp(self):
        package = Path(__file__).resolve().parents[1]
        self.config = yaml.safe_load((package / "config/g1.yaml").read_text())
        hardware = yaml.safe_load((package / "config/g1_hardware.yaml").read_text())
        limits = {joint["name"]: joint["position_limit"]
                  for joint in hardware["whole_body"]["joints"]}
        joint_names = self.config["robot_base"]["joint_names"]
        self.assertEqual(sorted(limits), sorted(joint_names))
        self.lower = [limits[name][0] for name in joint_names]
        self.upper = [limits[name][1] for name in joint_names]
        self.policies = self.config["rl_policy"]["onnx_infer"]["policies"]

    def assert_hardware_envelope(self, name, settings):
        self.assertIn("target_position_lower", settings, name)
        self.assertIn("target_position_upper", settings, name)
        for actual, expected in ((settings["target_position_lower"], self.lower),
                                 (settings["target_position_upper"], self.upper)):
            self.assertEqual(len(actual), len(expected), name)
            for index, (value, bound) in enumerate(zip(actual, expected)):
                self.assertAlmostEqual(value, bound, places=9, msg=f"{name}[{index}]")
        self.assertEqual(settings.get("target_limit_margin", 0.0), 0.0, name)

    def test_every_model_policy_is_bounded(self):
        model_policies = [name for name, settings in self.policies.items()
                          if "model_path" in settings]
        self.assertGreaterEqual(len(model_policies), 11)
        for name in model_policies:
            with self.subTest(policy=name):
                self.assert_hardware_envelope(name, self.policies[name])

    def test_selectable_and_action_policies_are_bounded(self):
        catalog = self.config["rl_policy"]["onnx_infer"]
        reachable = set(catalog["policy_names"])
        for settings in self.policies.values():
            actions = settings.get("policy_actions", {})
            if actions:
                reachable.add(actions["idle_policy"])
                reachable.update(action["policy"] for action in actions["actions"].values())
        for name in sorted(reachable):
            with self.subTest(policy=name):
                settings = self.policies[name]
                if "model_path" in settings:
                    self.assert_hardware_envelope(name, settings)
                else:
                    self.assertIn("policy_actions", settings, name)

    def test_home_shares_the_envelope(self):
        self.assert_hardware_envelope("home", self.config["behavior_manager"]["home"])

    def test_sonic_inference_threads_avoid_irq_cpus(self):
        threads = self.config["robot_base"]["threads"]
        planner_cpus = set(threads["motion_planner"]["cpu_affinity"])
        reserved = {threads[name]["cpu_id"] for name in ("rl_infer", "control_main", "driver_main")}
        self.assertEqual(threads["motion_planner"]["sched"], "other")
        self.assertFalse(planner_cpus & (reserved | {4, 5, 6}))
        for name in ("sonic", "sonic_planner"):
            with self.subTest(policy=name):
                runtime = self.policies[name]["runtime"]
                self.assertFalse(runtime["ort_spinning"])
                self.assertEqual(runtime["provider"], "cpu")
                self.assertEqual(runtime["threads"], 2)
                self.assertEqual(runtime["affinity"], "4")
                self.assertEqual(runtime["worker_sched"], threads["rl_infer"]["sched"])
                self.assertEqual(runtime["worker_priority"], threads["rl_infer"]["priority"])
                encoder = self.policies[name]["policy_adapter"]["encoder"]
                self.assertEqual(encoder["runtime"], runtime)
                self.assertEqual(encoder["latent_dim"], 64)
                observation = self.policies[name]["observation"]
                self.assertEqual(observation["segment_0_terms"], ["sonic_latent"])
                self.assertEqual(observation["segment_1_length"], 10)
        planner = self.policies["sonic_planner"]["policy_adapter"]["planner"]
        self.assertEqual(planner_cpus, {0})
        self.assertEqual(planner["runtime"]["provider"], "auto")
        self.assertEqual(planner["runtime"]["threads"], 8)
        self.assertEqual(planner["runtime"]["ep_options"]["SPACEMIT_EP_INTRA_THREAD_AFFINITY"],
                         "8;9;10;11;12;13;14;15")
        self.assertFalse(planner["runtime"]["ort_spinning"])
        self.assertEqual(planner["lookahead"], 0.04)
        self.assertEqual(planner["check_interval"], 0.1)
        self.assertEqual(planner["replan_interval"], 1.0)
        self.assertEqual(planner["running_replan_interval"], 0.1)
        self.assertEqual(planner["crawling_replan_interval"], 0.2)
        self.assertEqual(planner["allowed_pred_num_tokens"], [0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0])


if __name__ == "__main__":
    unittest.main()
