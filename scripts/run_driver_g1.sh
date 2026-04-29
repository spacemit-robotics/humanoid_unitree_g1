#!/bin/bash
# driver_runtime 链接 MuJoCo，仅在 x86_64 PC 上编译和运行。
# 跨机仿真时，在 PC 端执行此脚本；板卡端运行 run_control_g1.sh + run_hmi_g1.sh。
: "${SDK_ROOT:=$(cd "$(dirname "$(readlink -f "$0")")/../../.." && pwd)}"
if ! command -v driver_runtime &>/dev/null; then
    echo "[run_driver_g1] driver_runtime 未找到。请在 x86_64 PC 上编译后运行此脚本。" >&2
    exit 1
fi
exec driver_runtime "$SDK_ROOT/application/native/humanoid_unitree_g1/config/g1.yaml"
