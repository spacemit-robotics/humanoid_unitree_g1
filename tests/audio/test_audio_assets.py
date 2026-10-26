#!/usr/bin/env python3
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Check audio event routing and optional PCM assets without playback."""

import array
import json
from pathlib import Path
import sys
import unittest
import wave

import yaml

PACKAGE = Path(__file__).resolve().parents[2]
AUDIO = PACKAGE / "resources/audio"


class AudioAssetsTest(unittest.TestCase):
    """Match event routing and the audio resource format."""

    def test_assets(self):
        prompts = json.loads((AUDIO / "prompts.json").read_text())
        self.assertEqual(len(prompts), 19)
        self.assertEqual(prompts["gamepad_connected.wav"], "手柄已连接")
        self.assertEqual(prompts["gamepad_disconnected.wav"], "手柄已断开")
        self.assertEqual(prompts["control_acquired.wav"], "已接管控制权")
        self.assertEqual(prompts["control_released.wav"], "控制权已释放")
        paths = list(AUDIO.glob("*.wav"))
        if not paths:
            self.skipTest("Optional audio asset package is not installed")
        for path in paths:
            filename = path.name
            with self.subTest(filename=filename):
                with wave.open(str(path), "rb") as wav:
                    self.assertEqual((wav.getframerate(), wav.getnchannels(), wav.getsampwidth()),
                                     (48000, 2, 2))
                    seconds = wav.getnframes() / wav.getframerate()
                    samples = array.array("h", wav.readframes(wav.getnframes()))
                if sys.byteorder != "little":
                    samples.byteswap()
                self.assertGreater(seconds, 0.2)
                self.assertLess(seconds, 30 if filename == "groove.wav" else 5)
                self.assertGreater(max(abs(value) for value in samples), 100)
                self.assertLess(max(abs(value) for value in samples), 30000)

    def test_event_catalog(self):
        config = yaml.safe_load((PACKAGE / "config/g1.yaml").read_text())["audio_prompts"]
        clips = config["clips"]
        for silent in ("state.HOME", "state.ZERO", "state.RL", "state.SAFETY",
                       "policy.walk_standard_mnn", "policy.walk_wbc_mnn"):
            self.assertNotIn(silent, clips)
        self.assertEqual(clips["policy.walk_mnn"], "walk_mode.wav")
        self.assertEqual(clips["policy.dance_mnn"], "dance_mode.wav")
        self.assertEqual(clips["policy.walk_obstacle_mnn"], "obstacle_mode.wav")
        self.assertEqual(clips["fault"], "fault.wav")
        self.assertEqual(config["fault_repeat_interval_s"], 15.0)
        self.assertEqual(clips["gamepad.connected"], "gamepad_connected.wav")
        self.assertEqual(clips["gamepad.disconnected"], "gamepad_disconnected.wav")
        self.assertEqual(clips["control.acquired"], "control_acquired.wav")
        self.assertEqual(clips["control.released"], "control_released.wav")
        for index in range(1, 5):
            music = clips[f"action.rhythm_{index}"]
            self.assertTrue(music["music"])
            self.assertEqual(music["file"], "groove.wav")
            self.assertEqual(music["prefix"], "wow.wav")
        gestures = {"shake_hand": "shake_hand.wav", "wave_above_head": "wave_above_head.wav",
                    "wave_under_head": "wave_under_head.wav",
                    "blow_kiss_with_right_hand": "blow_kiss.wav", "clamp": "clap.wav"}
        for action, filename in gestures.items():
            self.assertEqual(clips[f"action.{action}"], filename)
        referenced = {value["file"] if isinstance(value, dict) else value for value in clips.values()}
        referenced.update(value["prefix"] for value in clips.values()
                          if isinstance(value, dict) and "prefix" in value)
        prompts = json.loads((AUDIO / "prompts.json").read_text())
        self.assertEqual(referenced, set(prompts) | {"groove.wav", "wow.wav"})


if __name__ == "__main__":
    unittest.main()
