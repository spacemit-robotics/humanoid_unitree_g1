#!/usr/bin/env python3
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Check reference trimming boundaries without external models or motion libraries."""

import importlib.util
from pathlib import Path
import unittest

import numpy as np

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/prepare_supermimic_assets.py"
SPEC = importlib.util.spec_from_file_location("prepare_supermimic_assets", SCRIPT)
ASSETS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ASSETS)


class ReferenceTrimTest(unittest.TestCase):
    """The splice needs an existing stop frame and a nonempty overlap."""

    def setUp(self):
        self.motion = {"joint_pos": np.zeros((100, 29)),
                       "root_pos": np.column_stack((np.arange(100) * 0.01, np.zeros(100), np.ones(100))),
                       "root_quat": np.tile([1.0, 0.0, 0.0, 0.0], (100, 1))}

    def test_valid_interval(self):
        result = ASSETS.remove_interval(self.motion, 0.8, 1.4)
        self.assertEqual(result["joint_pos"].shape, (70, 29))
        np.testing.assert_allclose(result["root_pos"][:, 0], np.arange(70) * 0.01)
        np.testing.assert_allclose(result["root_quat"], np.tile([1, 0, 0, 0], (70, 1)))

    def test_stop_must_be_an_existing_frame(self):
        for stop in (2.0, 2.1):
            with self.subTest(stop=stop), self.assertRaises(SystemExit):
                ASSETS.remove_interval(self.motion, 0.8, stop)
        self.assertEqual(len(ASSETS.remove_interval(self.motion, 0.8, 1.98)["joint_pos"]), 41)

    def test_invalid_interval_and_fade(self):
        for start, stop, fade in ((0.8, 1.4, 0), (0.8, 1.4, 0.001), (0.8, 1.4, -0.2),
                                  (0.8, 1.4, float("nan")), (float("nan"), 1.4, 0.2),
                                  (0.8, float("inf"), 0.2), (0.1, 1.4, 0.2), (1.4, 0.8, 0.2)):
            with self.subTest(start=start, stop=stop, fade=fade), self.assertRaises(SystemExit):
                ASSETS.remove_interval(self.motion, start, stop, fade)


if __name__ == "__main__":
    unittest.main()
