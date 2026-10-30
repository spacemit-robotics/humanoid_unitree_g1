#!/usr/bin/env python3
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Select full kernel preemption and keep peripheral work away from G1 CPUs 1, 2, 7.

Run once before starting G1, not inside any control loop. Without --apply this
only prints the plan. It does not enable motors, unload drivers or play audio.
"""

import argparse
import os
from pathlib import Path
import re
import time

HOUSEKEEPING = {0, 3, 4, 5, 6}
CONTROL_CPUS = {1, 2, 7}
USB_CONTROLLERS = {"81400000.usb3": 6, "cad00000.usb3": 5, "c0a00000.usb2": 4}
PREEMPT_CONTROL = Path("/sys/kernel/debug/sched/preempt")


def preempt_state(text):
    """Linux sched/debug.c marks the current PREEMPT_DYNAMIC mode with parentheses."""
    modes = text.split()
    active = [mode[1:-1] for mode in modes if mode.startswith("(") and mode.endswith(")")]
    if len(active) != 1 or "full" not in {mode.strip("()") for mode in modes}:
        raise ValueError(f"Unsupported PREEMPT_DYNAMIC state: {text.strip()!r}")
    return active[0]


def configure_preempt(apply=False, path=PREEMPT_CONTROL):
    """Change the runtime mode before starting hardware, then verify the read-back."""
    before = preempt_state(path.read_text(encoding="ascii"))
    if not apply:
        print(f"kernel preemption: current={before}, planned=full")
        return
    if before != "full":
        path.write_text("full\n", encoding="ascii")
    after = preempt_state(path.read_text(encoding="ascii"))
    if after != "full":
        raise ValueError(f"Kernel preemption did not change to full (actual={after})")
    print(f"kernel preemption: {before} -> {after} (verified)")


def check_board():
    """Do not apply this physical wiring/CPU layout to simulation or other boards."""
    compatible = Path("/proc/device-tree/compatible").read_bytes().split(b"\0")
    if b"spacemit,k3-com260" not in compatible:
        raise ValueError("This profile requires the G1 K3-COM260 board")
    online = parse_cpus(Path("/sys/devices/system/cpu/online").read_text())
    if not (HOUSEKEEPING | CONTROL_CPUS) <= online:
        raise ValueError("The G1 profile requires online CPUs 0-7")


def parse_cpus(value):
    """Parse Linux's comma-separated CPU IDs and inclusive ranges."""
    result = set()
    for item in value.strip().split(","):
        if item:
            ends = item.split("-")
            result.update(range(int(ends[0]), int(ends[-1]) + 1))
    return result


def usb_targets(root=Path("/sys/bus/platform/devices")):
    """Resolve USB bus numbers by controller address, not boot-dependent IRQ IDs."""
    result = {}
    for controller, cpu in USB_CONTROLLERS.items():
        for bus in (root / controller).glob("xhci-hcd.*/usb*/busnum"):
            result[f"xhci-hcd:usb{bus.read_text().strip()}"] = cpu
    return result


def irq_target(description, usb):
    """Separate motor USB, audio USB, networking, storage and display interrupts."""
    for token in description.split():
        if token in usb:
            return usb[token]
    if any(name in description for name in ("fusb301", "gpio-bank")):
        return 5
    if any(name in description for name in ("rtw89", "end1", "pcie", "PCI-MSI")):
        return 4
    if any(name in description for name in ("ufshcd", "mmc", "DPU_", "pvrsrv", "v2d")):
        return 0
    return 3


def irq_plan(text, usb):
    """Leave CPU-local timers/IPIs alone; move only peripheral interrupts."""
    result = {}
    for line in text.splitlines():
        number, separator, description = line.partition(":")
        if separator and number.strip().isdigit() and "RISC-V INTC" not in description:
            result[int(number)] = (irq_target(description, usb), description.split()[-1])
    return result


def apply_irqs(plan, root=Path("/proc/irq")):
    """Apply affinities; GPIO child IRQs may be fixed, their parent is movable."""
    (root / "default_smp_affinity").write_text(f"{sum(1 << cpu for cpu in HOUSEKEEPING):x}\n")
    for irq, (cpu, name) in plan.items():
        directory = root / str(irq)
        try:
            (directory / "smp_affinity_list").write_text(f"{cpu}\n")
        except OSError as error:
            if name.startswith("xhci-hcd:"):
                raise
            print(f"IRQ {irq} {name}: fixed/unsupported affinity ({error.strerror})")
            continue
        requested = (directory / "smp_affinity_list").read_text().strip()
        if parse_cpus(requested) != {cpu}:
            raise ValueError(f"IRQ {irq} {name} rejected target CPU {cpu}: {requested}")
        for attempt in range(6):
            effective = (directory / "effective_affinity_list").read_text().strip()
            if parse_cpus(effective) == {cpu}:
                break
            if attempt < 5:
                time.sleep(0.02)
        else:
            # Inactive peripheral IRQs may apply the accepted affinity only on
            # their next interrupt. Do not abort the entire robot startup for
            # that pending migration. Motor/IMU USB must be verified now.
            message = (f"IRQ {irq} {name}: requested CPU {cpu}, "
                       f"effective CPU {effective or 'none'}; migration pending")
            if name.startswith("xhci-hcd:"):
                raise ValueError(message)
            print(f"WARNING: {message}")
            continue
        print(f"IRQ {irq} {name}: effective CPU {effective}")


def apply_workers(plan):
    """Also move threaded IRQ handlers and DRM workers; never kill kernel tasks."""
    for process in Path("/proc").glob("[0-9]*"):
        try:
            name = (process / "comm").read_text().strip()
            match = re.match(r"irq/(\d+)-", name)
            if match and int(match[1]) in plan:
                cpus = {plan[int(match[1])][0]}
            elif re.fullmatch(r"card\d+-crtc\d+", name):
                cpus = {0}
            else:
                continue
            os.sched_setaffinity(int(process.name), cpus)
            print(f"worker {process.name} {name}: CPU {sorted(cpus)}")
        except (FileNotFoundError, ProcessLookupError):
            continue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="apply board affinities; requires root")
    parser.add_argument("--preempt-only", action="store_true",
                        help="only configure/verify full kernel preemption before G1 starts")
    args = parser.parse_args()
    check_board()
    if args.apply and os.geteuid() != 0:
        parser.error("--apply requires root")
    try:
        configure_preempt(args.apply)
    except (OSError, ValueError) as error:
        parser.error(f"Cannot configure full preemption: {error}; check debugfs and PREEMPT_DYNAMIC")
    if args.preempt_only:
        return
    usb = usb_targets()
    if 6 not in usb.values():
        parser.error("The motor/IMU USB controller is not ready")
    plan = irq_plan(Path("/proc/interrupts").read_text(), usb)
    if not args.apply:
        for irq, (cpu, name) in plan.items():
            print(f"IRQ {irq} {name}: planned CPU {cpu}")
        return
    apply_irqs(plan)
    apply_workers(plan)


if __name__ == "__main__":
    main()
