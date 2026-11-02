#!/usr/bin/env python3
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Label manual poses in SDK CSV logs; never open hardware or send commands."""

import argparse
import csv
from datetime import datetime
import json
import math
from pathlib import Path
import statistics
import time


MOTIONS = {
    "ankle_pitch": "支撑小腿和脚跟，让脚尖向下少量转动（不要一起移动小腿）",
    "ankle_roll": "支撑小腿和脚跟，让脚掌朝机器人左侧的一边少量抬高；左右脚均按机器人左右判断",
    "hip_pitch": "支撑腿部，让大腿向后少量转动，保持骨盆不动",
    "hip_roll": "支撑腿部，让大腿朝机器人左侧少量侧摆，保持骨盆不动",
    "hip_yaw": "支撑腿部，让大腿绕自身竖轴少量旋转，使脚尖转向机器人左侧",
    "knee": "固定大腿，支撑小腿并少量屈膝，使脚跟向后；不要反向顶膝盖",
    "imu_pitch": "只用手安全支撑着让 IMU 所在刚体向前少量倾斜，保持 IMU 与安装板固定",
    "imu_roll": "只用手安全支撑着让 IMU 所在刚体向机器人右侧少量倾斜，保持 IMU 与安装板固定",
}
TESTS = [f"{side}_{joint}" for side in ("left", "right")
         for joint in ("ankle_pitch", "ankle_roll", "hip_pitch", "hip_roll", "hip_yaw", "knee")]
# Torso suspension cannot hold the pelvis fixed while independently moving the
# upper body. Do not offer those unsupported waist procedures as runnable tests.
TESTS += ["imu_pitch", "imu_roll"]


def csv_rows(directory, stem, start, end):
    rows = []
    for path in sorted(directory.glob(f"{stem}.csv*")):
        with path.open(newline="") as stream:
            for row in csv.DictReader(stream):
                try:
                    stamp = float(row["wall_time_s"])
                    if start <= stamp <= end and None not in row and None not in row.values():
                        rows.append(row)
                except (KeyError, ValueError):
                    continue
    rows.sort(key=lambda row: float(row["wall_time_s"]))
    if len(rows) < 10:
        raise RuntimeError(f"{stem}: only {len(rows)} samples; check driver, log path and flushing")
    return rows


def mean_fields(rows, fields):
    result = {}
    for field in fields:
        values = [float(row[field]) for row in rows]
        if not all(math.isfinite(value) for value in values):
            raise RuntimeError(f"non-finite {field}")
        result[field] = {"mean": statistics.mean(values), "min": min(values), "max": max(values)}
    return result


def pose(directory, label, seconds):
    input(f"\n{label}：到位、保持后按回车；随后保持 {seconds:g} 秒。")
    start = time.time()
    time.sleep(seconds)
    end = time.time()
    time.sleep(1.0)  # Allow the asynchronous logger to flush; do not move until prompted.
    motor = csv_rows(directory, "driver_motor", start, end)
    joint = csv_rows(directory, "driver_joint", start, end)
    imu = csv_rows(directory, "driver_imu", start, end)
    fields = motor[0].keys()
    for field in fields:
        if field.endswith((".received", ".fresh")) and any(row[field] != "1" for row in motor):
            raise RuntimeError(f"missing/stale motor feedback: {field}")
        if field.endswith(".command_valid") and any(row[field] != "0" for row in motor):
            raise RuntimeError("control commands observed; stop manual verification")
        if field.endswith(".error_raw") and any(int(row[field]) for row in motor):
            raise RuntimeError(f"motor error: {field}")
    if any(row["fresh"] != "1" or row["received"] != "1" for row in imu):
        raise RuntimeError("missing/stale IMU feedback")
    for field in joint[0]:
        if field.endswith(".valid") and any(row[field] != "1" for row in joint):
            raise RuntimeError(f"invalid joint mapping: {field}")
    print(f"已记录：{len(motor)} 个电机快照、{len(imu)} 个 IMU 快照。")
    return {
        "label": label, "start_wall_s": start, "end_wall_s": end,
        "motor": mean_fields(motor, [f for f in fields if f.endswith((".raw_pos", ".calibrated_pos"))]),
        "joint": mean_fields(joint, [f for f in joint[0] if f.endswith(".position")]),
        "imu": mean_fields(imu, ["qw", "qx", "qy", "qz", "roll", "pitch", "yaw", "ax", "ay", "az"]),
        "max_motor_age_ms": max(float(row[f]) * 1000 for row in motor for f in fields
                                if f.endswith(".age_s")),
    }


def difference(first, second, group):
    return {name: values["mean"] - first[group][name]["mean"]
            for name, values in second[group].items()}


def summarize(poses, test):
    moved = difference(poses[0], poses[1], "joint")
    raw = difference(poses[0], poses[1], "motor")
    result = {
        "joint_delta_rad": moved, "motor_delta_rad": raw,
        "imu_delta": difference(poses[0], poses[1], "imu"),
        "return_error_rad": difference(poses[0], poses[2], "joint"),
        "acceptance": "Manual evidence only; no automatic calibration or actuation approval.",
    }
    print("\n变化最大的模型关节（度）：")
    for name, value in sorted(moved.items(), key=lambda pair: abs(pair[1]), reverse=True)[:6]:
        print(f"  {name}: {math.degrees(value):+.3f}")
    print("原始电机角度变化最大的端点（度）：")
    raw_only = {name: value for name, value in raw.items() if name.endswith(".raw_pos")}
    for name, value in sorted(raw_only.items(), key=lambda pair: abs(pair[1]), reverse=True)[:6]:
        print(f"  {name}: {math.degrees(value):+.3f}")
    if test.startswith("imu_"):
        axis = test.removeprefix("imu_")
        change = math.degrees(result["imu_delta"][axis])
        print(f"原始 IMU {axis} 变化：{change:+.3f}°（本步骤预期为正）。")
        if abs(change) < 0.2:
            print("姿态变化不足：若已明显倾斜安装板，请检查冻结姿态/传感器配置，不能据此通过验收。")
    else:
        key = f"{test}_joint.position"
        print(f"本步骤目标关节应正向变化，当前为 {math.degrees(moved[key]):+.3f}°。")
    print("结果没有修改任何 YAML；实际移动方向和测得角度仍须由操作者确认。")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, default=Path("latest"),
                        help="driver log directory on K3; default: latest SDK G1 driver run")
    parser.add_argument("--test", choices=TESTS, required=True)
    parser.add_argument("--seconds", type=float, default=2.0)
    args = parser.parse_args()
    if not 0.5 <= args.seconds <= 10:
        parser.error("seconds must be within [0.5, 10]")
    if args.log == Path("latest"):
        sdk = Path(__file__).resolve().parents[4]
        runs = sorted((sdk / "log/humanoid").glob("g1_driver_*"))
        if not runs:
            parser.error("no G1 driver run found; start the read-only driver first")
        directory = runs[-1]
    else:
        directory = args.log.resolve()
    if not (directory / "driver_motor.csv").is_file():
        parser.error("driver_motor.csv not found")
    print(f"读取日志：{directory}")
    key = args.test
    if key.startswith(("left_", "right_")):
        side, key = key.split("_", 1)
        print("测试侧：" + ("机器人左侧" if side == "left" else "机器人右侧"))
    print("本脚本只读日志，不连接串口、不使能、不启动 driver。")
    print("先确认机器人可靠吊装、其他控制服务已停止，driver 使用 read_only/allow_actuation=false。")
    print("全程人工支撑肢体，少量移动，遇阻即停；不要通过拉脚尖强扭连杆或突破关节限位。")
    print("正方向步骤：" + MOTIONS[key])
    output = directory / f"manual_{args.test}_{datetime.now():%Y%m%d_%H%M%S}.json"
    report = {"test": args.test, "positive_instruction": MOTIONS[key], "poses": []}
    try:
        for label in ("起始舒适姿态", "按上述正方向少量移动后的姿态", "回到起始姿态"):
            report["poses"].append(pose(directory, label, args.seconds))
        report["result"] = summarize(report["poses"], args.test)
    except (KeyboardInterrupt, EOFError, RuntimeError) as error:
        report["incomplete"] = str(error) or type(error).__name__
        raise
    finally:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(f"记录保存到 {output}")


if __name__ == "__main__":
    main()
