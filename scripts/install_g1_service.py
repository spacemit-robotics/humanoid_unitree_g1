#!/usr/bin/env python3
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Install the G1 boot service without starting robot hardware."""

import argparse
import configparser
import datetime
import grp
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import shutil
import subprocess
from urllib.parse import urlsplit

UNIT_PATH = Path("/etc/systemd/system/g1.service")
DESKTOP_UNITS = ("sddm.service", "wayvnc.service", "wayvnc-control.service", "rtkit-daemon.service")


def installed_network(path):
    """Keep the installed network entry when updating the service."""
    if not path.exists():
        return None, None
    config = configparser.ConfigParser(interpolation=None, strict=False)
    config.read(path, encoding="utf-8")
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--listen")
    parser.add_argument("--public-url")
    options, _ = parser.parse_known_args(shlex.split(config.get("Service", "ExecStart")))
    return options.listen, options.public_url


def network_arguments(listen, public_url):
    """Validate the network arguments used by the standard G1 launcher."""
    if listen is None and public_url is None:
        return ""
    if not listen or not public_url:
        raise ValueError("Specify --listen and --public-url together, or configure both in YAML")
    if "%" in listen:
        raise ValueError("--listen must be an unscoped numeric IP address")
    ipaddress.ip_address(listen)
    url = urlsplit(public_url)
    if (not re.fullmatch(r"[A-Za-z0-9.:/\[\]-]+", public_url)
            or url.scheme != "http" or not url.hostname or url.path not in ("", "/")
            or url.query or url.fragment or url.username or url.password):
        raise ValueError("--public-url must be an HTTP origin, such as http://192.0.2.10:8766")
    if url.port is not None and not 1 <= url.port <= 65535:
        raise ValueError("Invalid --public-url port")
    return f" --listen {listen} --public-url {public_url.rstrip('/')}"


def render_service(sdk_root, username, listen=None, public_url=None):
    """Render the installed template for an ordinary operator account."""
    account = pwd.getpwnam(username)
    if account.pw_uid == 0:
        raise ValueError("The operator must be an ordinary user, not root")
    values = {
        "SDK_ROOT": str(sdk_root),
        "USER": username,
        "GROUP": grp.getgrgid(account.pw_gid).gr_name,
        "HOME": account.pw_dir,
    }
    for name, value in values.items():
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", value):
            raise ValueError(f"Unsupported characters in {name}: {value!r}")
    for program in ("run_g1.sh", "run_driver_g1.sh", "run_control_g1.sh", "run_hmi_g1.sh",
                    "hmi_tui", "driver_runtime", "control_runtime", "hmi_runtime", "configure_g1_realtime.py"):
        if not os.access(sdk_root / "output/staging/bin" / program, os.X_OK):
            raise ValueError(f"Missing program: {program}; build the SDK first")
    template = sdk_root / "output/staging/share/humanoid_unitree_g1/g1.service.in"
    unit = template.read_text(encoding="utf-8")
    for name, value in values.items():
        unit = unit.replace(f"@{name}@", value)
    return unit.replace("@NETWORK_ARGS@", network_arguments(listen, public_url))


def install_service(path, unit):
    """Back up the previous unit and enable boot without starting hardware."""
    state = subprocess.run(["systemctl", "is-active", path.name], capture_output=True,
                           text=True, check=False).stdout.strip()
    if state not in ("inactive", "failed", "unknown"):
        raise ValueError(f"Stop {path.name} before installing an update (state={state or 'unavailable'})")
    if path.exists():
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        shutil.copy2(path, path.with_name(f"{path.name}.{stamp}.bak"))
    temporary = path.with_suffix(".service.new")
    temporary.write_text(unit, encoding="utf-8")
    temporary.chmod(0o644)
    temporary.replace(path)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", path.name], check=True)


def install_headless(sdk_root, unit_path=UNIT_PATH):
    """Opt-in K3 profile: disable the desktop and isolate G1's background work.

    Keep ALSA/USB audio and networking intact. The root pre-start step only sets
    IRQ/kernel-worker affinity; all three robot processes still run as the user.
    """
    dropin_dir = unit_path.parent / "g1.service.d"
    dropin_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    state = {}
    for name in DESKTOP_UNITS:
        state[name] = {}
        for query in ("is-enabled", "is-active"):
            state[name][query] = subprocess.run(
                ["systemctl", query, name], capture_output=True, text=True, check=False).stdout.strip()
    state["default_target"] = subprocess.run(
        ["systemctl", "get-default"], capture_output=True, text=True, check=True).stdout.strip()
    (dropin_dir / f"headless-before-{stamp}.json").write_text(json.dumps(state, indent=2) + "\n",
                                                          encoding="utf-8")
    dropin = dropin_dir / "50-headless.conf"
    if dropin.exists():
        shutil.copy2(dropin, dropin.with_name(f"{dropin.name}.{stamp}.bak"))
    dropin.write_text(
        "[Service]\n"
        "# Background log/HMI tasks inherit this; YAML assigns main loops to 1/2/7.\n"
        "CPUAffinity=0 3 4 5 6\n"
        f"ExecStartPre=+/usr/bin/python3 {sdk_root}/output/staging/bin/configure_g1_realtime.py --apply\n",
        encoding="utf-8")
    subprocess.run(["systemctl", "disable", "--now", *DESKTOP_UNITS[:3]], check=True)
    # Disabled alone is insufficient: D-Bus clients can restart RealtimeKit.
    subprocess.run(["systemctl", "mask", "--now", DESKTOP_UNITS[3]], check=True)
    subprocess.run(["systemctl", "set-default", "multi-user.target"], check=True)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    print(f"Headless profile installed. Previous desktop state: {dropin_dir}/headless-before-{stamp}.json")


def install_gamepad_rule(sdk_root, rules_dir=Path("/etc/udev/rules.d")):
    """Grant only the verified controller output to the existing input group."""
    source = sdk_root / "output/staging/share/humanoid_unitree_g1/70-g1-gamepad-rumble.rules"
    destination = rules_dir / source.name
    rules_dir.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.read_bytes() != source.read_bytes():
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        shutil.copy2(destination, destination.with_name(f"{destination.name}.{stamp}.bak"))
    shutil.copyfile(source, destination)
    destination.chmod(0o644)
    subprocess.run(["udevadm", "control", "--reload-rules"], check=True)
    # Do not re-enumerate USB buses shared with the motors. Applies on pad reconnection.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=os.environ.get("SUDO_USER"), help="ordinary operator account")
    root = next((path for path in Path(__file__).resolve().parents
                 if (path / "build/envsetup.sh").is_file()), Path.cwd())
    parser.add_argument("--sdk-root", type=Path, default=root)
    parser.add_argument("--listen", help="robot LAN listen address; saved in the boot service")
    parser.add_argument("--public-url", help="robot LAN HTTP origin for phone access and QR")
    parser.add_argument("--print-unit", action="store_true", help="render only; do not install or enable")
    parser.add_argument("--headless", action="store_true",
                        help="K3 only: stop/disable desktop, keep USB audio, configure IRQ/core isolation")
    args = parser.parse_args()
    if not args.user:
        parser.error("--user is required")
    try:
        if args.listen is None and args.public_url is None:
            args.listen, args.public_url = installed_network(UNIT_PATH)
        unit = render_service(args.sdk_root.resolve(), args.user, args.listen, args.public_url)
    except (OSError, KeyError, ValueError, configparser.Error) as error:
        parser.error(str(error))
    if args.print_unit:
        print(unit, end="")
        return
    if os.geteuid() != 0:
        parser.error("Installation requires sudo --user root")
    try:
        if args.headless:
            # Validate the board/wiring before changing the installed service or desktop.
            subprocess.run(["/usr/bin/python3", str(args.sdk_root.resolve()
                            / "output/staging/bin/configure_g1_realtime.py")], check=True)
        install_service(UNIT_PATH, unit)
        install_gamepad_rule(args.sdk_root.resolve())
        if args.headless:
            install_headless(args.sdk_root.resolve())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.error(str(error))
    print("Installed g1.service and enabled it for the next boot. Hardware has NOT been started.")
    print("Start: sudo --user root systemctl start g1.service")
    print("Status: systemctl status g1.service --no-pager")
    print("Gamepad rumble permissions apply when the controller next reconnects.")


if __name__ == "__main__":
    main()
