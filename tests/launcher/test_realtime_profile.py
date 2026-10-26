#!/usr/bin/env python3
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Check the board profile's IRQ routing without touching host settings."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

PACKAGE = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("g1_realtime", PACKAGE / "scripts/configure_g1_realtime.py")
PROFILE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROFILE)


class RealtimeProfileTest(unittest.TestCase):
    """Boot-dependent USB bus/IRQ numbering must not change the CPU roles."""

    def test_usb_bus_numbers_are_resolved_from_physical_controller(self):
        with tempfile.TemporaryDirectory(prefix="g1_irq_test_") as directory:
            root = Path(directory)
            for controller, number in (("81400000.usb3", 12), ("cad00000.usb3", 14)):
                bus = root / controller / f"xhci-hcd.9.auto/usb{number}/busnum"
                bus.parent.mkdir(parents=True)
                bus.write_text(f"{number}\n", encoding="utf-8")
            self.assertEqual(PROFILE.usb_targets(root), {"xhci-hcd:usb12": 6, "xhci-hcd:usb14": 5})

    def test_peripheral_routes_leave_local_timers_untouched(self):
        usb = {"xhci-hcd:usb12": 6, "xhci-hcd:usb14": 5}
        interrupts = "\n".join((
            "1: 1 2 3 RISC-V INTC 5 Edge riscv-timer",
            "81: 0 1 2 APLIC-MSI Level xhci-hcd:usb12",
            "82: 0 1 2 APLIC-MSI Level xhci-hcd:usb14",
            "83: 0 1 2 GPIO Edge fusb301_int_irq",
            "84: 0 1 2 PCI-MSI Edge rtw89_pci",
            "85: 0 1 2 APLIC-MSI Level DPU_ONLINE",
            "86: 0 1 2 APLIC-MSI Level mmc0",
            "87: 0 1 2 APLIC-MSI Level soc:rpmi_rtc@0",
            "IPI0: 1 2 3 Rescheduling interrupts"))
        plan = PROFILE.irq_plan(interrupts, usb)
        self.assertEqual({irq: value[0] for irq, value in plan.items()},
                         {81: 6, 82: 5, 83: 5, 84: 4, 85: 0, 86: 0, 87: 3})
        self.assertFalse({cpu for cpu, _ in plan.values()} & PROFILE.CONTROL_CPUS)

    def test_cpu_list(self):
        self.assertEqual(PROFILE.parse_cpus("0,3-6\n"), PROFILE.HOUSEKEEPING)

    def test_preempt_full_is_written_and_read_back(self):
        path = Mock()
        path.read_text.side_effect = ["none (voluntary) full lazy\n", "none voluntary (full) lazy\n"]
        PROFILE.configure_preempt(True, path)
        path.write_text.assert_called_once_with("full\n", encoding="ascii")
        self.assertEqual(path.read_text.call_count, 2)

    def test_preempt_full_is_idempotent(self):
        path = Mock()
        path.read_text.return_value = "none voluntary (full)\n"
        PROFILE.configure_preempt(True, path)
        path.write_text.assert_not_called()

    def test_preempt_dry_run_never_writes(self):
        path = Mock()
        path.read_text.return_value = "none (voluntary) full\n"
        PROFILE.configure_preempt(False, path)
        path.write_text.assert_not_called()

    def test_preempt_missing_or_unchanged_is_failure(self):
        for text in ("none (voluntary) full", "none voluntary full", "(voluntary)"):
            path = Mock()
            path.read_text.return_value = text
            with self.subTest(text=text), self.assertRaises(ValueError):
                PROFILE.configure_preempt(True, path)
        path = Mock()
        path.read_text.side_effect = FileNotFoundError("preempt")
        with self.assertRaises(FileNotFoundError):
            PROFILE.configure_preempt(True, path)


if __name__ == "__main__":
    unittest.main()
