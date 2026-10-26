#!/usr/bin/env python3
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Render private G1 pairing SVGs in the existing SpacemiT robot sticker style."""

import argparse
import copy
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


NS = "http://www.w3.org/2000/svg"
SINGLE_LAYOUT = """<svg xmlns="http://www.w3.org/2000/svg"
    width="140mm" height="100mm" viewBox="0 0 1400 1000">
  <title>SpacemiT G1 操作入口</title>
  <style>text { font-family: 'Noto Sans CJK SC', sans-serif; }</style>
  <rect width="1400" height="1000" fill="#FFFFFF"/>
  <rect width="1400" height="156" fill="#191D20"/>
  <g id="brand-logo"/>
  <text x="1332" y="103" text-anchor="end" font-size="64"
    font-weight="700" fill="#FFFFFF">UNITREE G1</text>
  <rect y="156" width="1400" height="7" fill="#B0E237"/>
  <text x="68" y="210" font-size="29" fill="#58615D" id="network-label"/>
  <text x="1332" y="210" text-anchor="end" font-size="26"
    fill="#58615D" id="network-hint"/>
  <g id="primary-qr"/>
  <text x="700" y="942" text-anchor="middle" font-size="30"
    fill="#191D20" id="primary-address"/>
  <text x="700" y="982" text-anchor="middle" font-size="22"
    fill="#657067">网页控制 / 下载 App · 申请控制权后操作 · 配对码仅限授权人员</text>
</svg>"""
LAYOUT = """<svg xmlns="http://www.w3.org/2000/svg"
    width="140mm" height="100mm" viewBox="0 0 1400 1000">
  <title>SpacemiT G1 操作入口</title>
  <style>text { font-family: 'Noto Sans CJK SC', sans-serif; }</style>
  <rect width="1400" height="1000" fill="#FFFFFF"/>
  <rect width="1400" height="156" fill="#191D20"/>
  <g id="brand-logo"/>
  <text x="1332" y="103" text-anchor="end" font-size="64"
    font-weight="700" fill="#FFFFFF">UNITREE G1</text>
  <rect y="156" width="1400" height="7" fill="#B0E237"/>
  <text x="68" y="226" font-size="29" fill="#58615D">人形机器人 · 操作入口</text>
  <text x="1332" y="226" text-anchor="end" font-size="24"
    fill="#58615D">先连对应网络，再扫码控制</text>
  <rect x="83" y="272" width="55" height="55" fill="#B0E237"/>
  <text x="110.5" y="311" text-anchor="middle" font-size="32"
    font-weight="700" fill="#191D20">A</text>
  <text x="162" y="313" font-size="39" font-weight="700" fill="#191D20">公司网络入口</text>
  <rect x="783" y="272" width="55" height="55" fill="#B0E237"/>
  <text x="810.5" y="311" text-anchor="middle" font-size="32"
    font-weight="700" fill="#191D20">B</text>
  <text x="862" y="313" font-size="39" font-weight="700" fill="#191D20">机器人内网入口</text>
  <path d="M700 275v623" stroke="#DDE3DB" stroke-width="2"/>
  <g id="primary-qr"/><g id="secondary-qr"/>
  <text x="350" y="844" text-anchor="middle" font-size="30"
    fill="#191D20" id="primary-address"/>
  <text x="1050" y="844" text-anchor="middle" font-size="30"
    fill="#191D20" id="secondary-address"/>
  <text x="350" y="891" text-anchor="middle" font-size="25"
    fill="#58615D">公司 Wi-Fi · 地址随 DHCP 分配</text>
  <text x="1050" y="891" text-anchor="middle" font-size="25"
    fill="#58615D">G1 局域网 · 固定有线地址</text>
  <path d="M68 935h1264" stroke="#DDE3DB" stroke-width="2"/>
  <text x="700" y="976" text-anchor="middle" font-size="22"
    fill="#657067">网页控制 / 下载 App · 申请控制权后操作 · 配对码仅限授权人员</text>
</svg>"""


def main():
    """Keep QR vectors intact; place a 100 mm wide sticker on an A4 sheet."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary-qr", type=Path, required=True)
    parser.add_argument("--secondary-qr", type=Path, help="optional second network QR")
    parser.add_argument("--primary-address", required=True)
    parser.add_argument("--secondary-address", help="label for the optional second network QR")
    parser.add_argument("--network-label", default="公司网络 · 操作入口",
                        help="network caption for a single QR sticker")
    parser.add_argument("--network-hint", default="请先连接公司 Wi-Fi",
                        help="connection instructions for a single QR sticker")
    parser.add_argument("--output-dir", type=Path, required=True)
    sdk = Path(__file__).resolve().parents[4]
    parser.add_argument("--logo", type=Path, default=sdk / (
        "application/native/humanoid_common/clients/web/assets/spacemit-logo.svg"))
    args = parser.parse_args()
    if (args.secondary_qr is None) != (args.secondary_address is None):
        parser.error("--secondary-qr and --secondary-address must be supplied together")
    dual = args.secondary_qr is not None
    os.umask(0o077)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    ET.register_namespace("", NS)
    root = ET.fromstring(LAYOUT if dual else SINGLE_LAYOUT)
    if not dual:
        root.find(f".//{{{NS}}}text[@id='network-label']").text = args.network_label
        root.find(f".//{{{NS}}}text[@id='network-hint']").text = args.network_hint
    sources = [
        ("brand-logo", args.logo, (59, 30, 316, 96)),
        ("primary-qr", args.primary_qr, (116, 342, 468, 468) if dual else (360, 222, 680, 680)),
    ]
    if dual:
        sources.append(("secondary-qr", args.secondary_qr, (816, 342, 468, 468)))
    for group, path, bounds in sources:
        original = ET.parse(path).getroot()
        if original.tag != f"{{{NS}}}svg" or not original.get("viewBox"):
            raise ValueError(f"Expected a vector SVG with viewBox: {path}")
        nested = copy.deepcopy(original)
        for name, value in zip(("x", "y", "width", "height"), bounds):
            nested.set(name, str(value))
        root.find(f".//{{{NS}}}g[@id='{group}']").append(nested)
    for name in (("primary", "secondary") if dual else ("primary",)):
        root.find(f".//{{{NS}}}text[@id='{name}-address']").text = getattr(args, f"{name}_address")
    svg = args.output_dir / "g1-operator-sticker.svg"
    ET.ElementTree(root).write(svg, encoding="utf-8", xml_declaration=True)
    subprocess.run(["rsvg-convert", "--width", "1400", "--output",
                    str(args.output_dir / "g1-operator-preview.png"), str(svg)], check=True)
    pdf = args.output_dir / "g1-operator-a4-100mm.pdf"
    subprocess.run(["rsvg-convert", "--format", "pdf", "--width", "100mm",
                    "--height", "71.428571mm", "--page-width", "210mm", "--page-height", "297mm",
                    "--left", "55mm", "--top", "25mm", "--keep-aspect-ratio",
                    "--output", str(pdf), str(svg)], check=True)
    print(f"Created private pairing sticker: {pdf}; do not commit or publish its contents.")


if __name__ == "__main__":
    main()
