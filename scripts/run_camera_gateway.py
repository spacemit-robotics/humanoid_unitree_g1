#!/usr/bin/env python3
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Start the local WebRTC endpoint; encoders run only while the path has a reader."""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

import yaml


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("mode", choices=["sim", "real"])
    args = parser.parse_args()
    cfg = yaml.safe_load(args.config.read_text())
    preview = cfg.get("operator_service", {}).get("camera_preview")
    if not preview:
        return
    simulated = args.mode == "sim"
    media = {"logLevel": "warn", "rtsp": simulated, "rtspTransports": ["tcp"],
             "rtspAddress": "127.0.0.1:18554", "rtmp": False, "srt": False, "hls": False,
             "webrtcAddress": f"127.0.0.1:{preview['port']}", "webrtcLocalUDPAddress": ":8189",
             "webrtcLocalTCPAddress": ":8189",
             "webrtcAllowOrigins": [], "authInternalUsers": [
                 {"user": "any", "ips": ["127.0.0.1"], "permissions": [
                     {"action": "read", "path": "preview"}, {"action": "publish", "path": "preview"}]}]}
    if simulated:
        reader = Path(os.environ["SDK_ROOT"]) / "output/staging/bin/sim_rgbd_frames.py"
        endpoint = cfg["simulation"]["mujoco"]["preview_endpoint"]
        command = (f"/usr/bin/python3 -u {shlex.quote(str(reader))} {shlex.quote(endpoint)} | "
                   "ffmpeg -hide_banner -loglevel error -f rawvideo -pixel_format bgr24 "
                   "-video_size 640x180 -framerate 30 -i pipe:0 -an -c:v libx264 "
                   "-preset ultrafast -tune zerolatency -pix_fmt yuv420p -threads 2 "
                   "-b:v 1500k -g 15 -bf 0 -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:18554/preview")
        path = {"runOnDemand": "sh -c " + shlex.quote(command), "runOnDemandCloseAfter": "1s"}
    else:
        path = {"source": preview["real_rtsp"], "sourceOnDemand": True, "rtspTransport": "tcp",
                "sourceOnDemandCloseAfter": "1s"}
    media["paths"] = {"preview": path}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml") as conf:
        yaml.safe_dump(media, conf)
        conf.flush()
        env = {k: v for k, v in os.environ.items() if not k.startswith(("MTX_", "RTSP_"))}
        subprocess.run(["mediamtx", conf.name], check=True, env=env)


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as exc:
        sys.exit(f"Camera gateway unavailable: {exc}")
