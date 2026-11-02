#!/bin/bash
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
# Start the G1 runtimes and optional local TUI.
set -euo pipefail

usage() {
    echo "Usage: run_g1.sh --sim [--stairs] [--no-tui]"
    echo "       run_g1.sh --real [--tui] [--listen ADDRESS] [--public-url URL]"
    echo "仿真默认启动 TUI；实机默认启动三个核心进程，网页和 App 共用 HMI。"
}

MODE="${1:-}"
case "$MODE" in
    --sim) TUI=yes ;;
    --real) TUI=no ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 1 ;;
esac
shift
HMI_ARGS=("$MODE")
DRIVER_ARGS=("$MODE")
while (($#)); do
    case "$1" in
        --tui) TUI=yes ;;
        --no-tui) TUI=no ;;
        --stairs)
            [[ "$MODE" == --sim ]] || { echo "台阶场景仅用于仿真。" >&2; exit 1; }
            DRIVER_ARGS+=(--stairs) ;;
        --listen|--public-url)
            if [[ "$MODE" != --real || $# -lt 2 ]]; then
                echo "网络入口只用于 --real 实机模式。" >&2
                exit 1
            fi
            HMI_ARGS+=("$1" "$2"); shift ;;
        *) usage >&2; exit 1 ;;
    esac
    shift
done

STARTUP_TIMEOUT="${G1_STARTUP_TIMEOUT_S:-60}"
if [[ ! "$STARTUP_TIMEOUT" =~ ^[1-9][0-9]{0,2}$ ]]; then
    echo "G1_STARTUP_TIMEOUT_S 必须是 1–999 的整数秒。" >&2
    exit 1
fi

if [[ -z "${SDK_ROOT:-}" ]]; then
    SDK_ROOT=$(dirname "$(readlink -f "$0")")
    while [[ "$SDK_ROOT" != / && ! -f "$SDK_ROOT/build/envsetup.sh" ]]; do
        SDK_ROOT=$(dirname "$SDK_ROOT")
    done
fi
export SDK_ROOT
BIN="$SDK_ROOT/output/staging/bin"
CONFIG=$(readlink -f "${G1_CONFIG:-$SDK_ROOT/application/native/humanoid_unitree_g1/config/g1.yaml}")
export G1_CONFIG="$CONFIG"
for NAME in driver control hmi; do
    if [[ ! -x "$BIN/run_${NAME}_g1.sh" || ! -x "$BIN/${NAME}_runtime" ]]; then
        echo "缺少 $NAME 程序，请先编译 humanoid_common 和 humanoid_unitree_g1。" >&2
        exit 1
    fi
done
if [[ ! -x "$BIN/hmi_tui" ]]; then
    echo "缺少 hmi_tui，请先编译 humanoid_common。" >&2
    exit 1
fi
if [[ "$TUI" == yes && ( ! -t 0 || ! -t 1 ) ]]; then
    echo "TUI 需要交互终端；仅启动核心进程请加 --no-tui。" >&2
    exit 1
fi

STATE="${XDG_STATE_HOME:-$HOME/.local/state}/humanoid-operator/g1"
CONNECTION="$STATE/connection.json"
umask 077
mkdir -p "$STATE"
exec 9>"$STATE/launch.lock"
if ! flock -n 9; then
    echo "G1 启动脚本已在运行，请连接现有 TUI 或先正常退出。" >&2
    exit 1
fi
for PID in $(pgrep -x 'driver_main|driver_runtime|control_main|control_runtime|hmi_runtime' || true); do
    [[ -r "/proc/$PID/cmdline" ]] || continue
    mapfile -d '' -t PROCESS <"/proc/$PID/cmdline"
    PROCESS_CONFIG="${PROCESS[1]:-}"
    if [[ "$PROCESS_CONFIG" == "$CONFIG" || "$PROCESS_CONFIG" == *humanoid_unitree_g1/* ||
        "${PROCESS_CONFIG##*/}" == g1.yaml ]]; then
        echo "已有 G1 核心进程 $PID 运行，请先正常退出；不会终止已有进程。" >&2
        exit 1
    fi
done
SETTINGS=$(python3 -c '
import pathlib
import sys
import yaml

config = pathlib.Path(sys.argv[1])
with config.open(encoding="utf-8") as source:
    settings = yaml.safe_load(source)
if settings.get("robot_base", {}).get("name") != "g1":
    sys.exit("run_g1.sh requires robot_base.name: g1")
directory = settings.get("logging", {}).get("directory", "log/humanoid")
print((config.parent / directory).resolve())
connection = settings.get("operator_service", {}).get("connection_file", sys.argv[2])
print(pathlib.Path(connection).absolute())
' "$CONFIG" "$CONNECTION")
mapfile -t SETTINGS <<<"$SETTINGS"
LOG_ROOT="${SETTINGS[0]}"
CONNECTION="${SETTINGS[1]}"
LOG_TOOL="$BIN/humanoid_logs.py"
if [[ ! -f "$LOG_TOOL" ]]; then
    echo "缺少日志工具，请先编译安装 humanoid_common。" >&2
    exit 1
fi
LOG_SETTINGS=$(python3 "$LOG_TOOL" prepare --config "$CONFIG")
mapfile -t LOG_SETTINGS <<<"$LOG_SETTINGS"
LOG_ROOT="${LOG_SETTINGS[0]}"
LOG_DIR="${LOG_SETTINGS[1]}"
export HUMANOID_LOG_DIRECTORY="$LOG_ROOT"
LAUNCH_DIR="$LOG_DIR"
exec 7>"$LAUNCH_DIR/.active.lock"
flock -n 7
PIDS=()
NAMES=()
TUI_PID=""
AUDIO_PID=""
GAMEPAD_PID=""
FAILED_NAME=""
FAILED_STATUS=0
signal_children() {
    local PID
    if [[ -n "$TUI_PID" ]]; then
        kill -s "$1" "$TUI_PID" 2>/dev/null || true
    fi
    if [[ -n "$GAMEPAD_PID" ]]; then
        kill -s "$1" -- "-$GAMEPAD_PID" 2>/dev/null || true
    fi
    if [[ -n "$AUDIO_PID" ]]; then
        kill -s "$1" -- "-$AUDIO_PID" 2>/dev/null || true
    fi
    for PID in "${PIDS[@]}"; do
        kill -s "$1" -- "-$PID" 2>/dev/null || true
    done
}
stop_children() {
    local SIGNAL ATTEMPT
    for SIGNAL in INT TERM; do
        signal_children "$SIGNAL"
        for ((ATTEMPT=0; ATTEMPT<30; ATTEMPT++)); do
            [[ -n "$(jobs -pr)" ]] || break
            sleep 0.1
        done
    done
    if [[ -n "$(jobs -pr)" ]]; then
        echo "本次进程停止超时，强制清理；日志：$LOG_DIR" >&2
        signal_children KILL
    fi
    wait 2>/dev/null || true
    PIDS=()
    NAMES=()
    TUI_PID=""
    AUDIO_PID=""
    GAMEPAD_PID=""
    exec 8>&-
}
cleanup() {
    trap '' INT TERM HUP
    stop_children
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
start() {
    local NAME="$1"
    shift
    setsid "$@" 7>&- 9>&- </dev/null > >(
        python3 "$LOG_TOOL" sink --config "$CONFIG" --file "$LOG_DIR/$NAME.log" 7>&- 8>&- 9>&-
    ) 2>&1 &
    PIDS+=("$!")
    NAMES+=("$NAME")
}
check_children() {
    local INDEX
    for INDEX in "${!PIDS[@]}"; do
        if ! kill -0 "${PIDS[$INDEX]}" 2>/dev/null; then
            FAILED_NAME="${NAMES[$INDEX]}"
            FAILED_STATUS=0
            wait "${PIDS[$INDEX]}" || FAILED_STATUS=$?
            echo "$FAILED_NAME 已退出（$FAILED_STATUS），日志：$LOG_DIR/$FAILED_NAME.log" >&2
            tail -n 15 "$LOG_DIR/${NAMES[$INDEX]}.log" >&2 2>/dev/null || true
            return 1
        fi
    done
}

echo "启动 G1 ${MODE#--}；日志：$LAUNCH_DIR"
DEADLINE=$((SECONDS + STARTUP_TIMEOUT))
ATTEMPT=0
while :; do
    ATTEMPT=$((ATTEMPT + 1))
    if ((ATTEMPT > 1)); then
        LOG_DIR="$LAUNCH_DIR/attempt_$ATTEMPT"
        mkdir -p "$LOG_DIR"
    fi
    mkfifo "$LOG_DIR/control.ready"
    exec 8<>"$LOG_DIR/control.ready"
    CONTROL_READY=no
    start driver "$BIN/run_driver_g1.sh" "${DRIVER_ARGS[@]}" 8>&-
    # Reopen the writer: control's O_NONBLOCK must not affect the parent's reader.
    start control env HUMANOID_STARTUP_READY_FD=8 "$BIN/run_control_g1.sh" 8>"$LOG_DIR/control.ready"
    start hmi "$BIN/run_hmi_g1.sh" "${HMI_ARGS[@]}" 8>&-
    while :; do
        if ! check_children; then
            # 75 is only returned before whole_body enters its command loop.
            # Tear down the entire attempt so startup faults cannot carry over.
            if [[ "$MODE" == --real && "$FAILED_NAME" == driver &&
                "$FAILED_STATUS" == 75 ]] && ((SECONDS + 2 < DEADLINE)); then
                echo "硬件初始化未完成，保持失能，2 秒后重试（总等待上限 ${STARTUP_TIMEOUT}s）。"
                stop_children
                sleep 2
                if ((SECONDS >= DEADLINE)); then exit 1; fi
                break
            fi
            exit 1
        fi
        STATUS=$("$BIN/hmi_tui" --connection "$CONNECTION" --status 2>/dev/null || true)
        # HMI online only proves that control is alive, not that hardware works.
        NOTICE=""
        IFS= read -r -t 0.02 -u 8 NOTICE || true
        if [[ "$NOTICE" == ready ]]; then CONTROL_READY=yes; fi
        if [[ "$STATUS" == *"online=1"* && "$CONTROL_READY" == yes ]]; then
            break 2
        fi
        if ((SECONDS >= DEADLINE)); then
            echo "启动超时，硬件反馈或 HMI 尚未就绪。日志：$LOG_DIR" >&2
            exit 1
        fi
        sleep 0.2
    done
done
exec 8>&-
echo "三个核心进程已就绪；启动保持 POWER_OFF，不会自动上电。"
# Optional observer: its failure must not stop any core process.
if [[ "$MODE" == --real && -x "$BIN/operator_audio" ]]; then
    setsid "$BIN/operator_audio" "$CONFIG" --connection "$CONNECTION" \
        7>&- 9>&- </dev/null > >(
            python3 "$LOG_TOOL" sink --config "$CONFIG" --file "$LOG_DIR/audio.log" 7>&- 9>&-
        ) 2>&1 &
    AUDIO_PID=$!
fi
if [[ "$MODE" == --real && -x "$BIN/hmi_gamepad" ]]; then
    setsid "$BIN/hmi_gamepad" "$CONFIG" --connection "$CONNECTION" \
        7>&- 9>&- </dev/null > >(
            python3 "$LOG_TOOL" sink --config "$CONFIG" --file "$LOG_DIR/gamepad.log" 7>&- 9>&-
        ) 2>&1 &
    GAMEPAD_PID=$!
fi
if [[ "$MODE" == --real ]]; then
    sed -n '/^\[hmi\]/p' "$LOG_DIR/hmi.log" 2>/dev/null || true
fi
echo "Ctrl+C 退出本次启动的全部进程；独立 TUI：run_hmi_tui_g1.sh"
if [[ "$TUI" == yes ]]; then
    "$BIN/hmi_tui" --connection "$CONNECTION" 9>&- <&0 &
    TUI_PID=$!
    while kill -0 "$TUI_PID" 2>/dev/null; do
        check_children || exit 1
        sleep 0.2
    done
    wait "$TUI_PID"
else
    while :; do check_children || exit 1; sleep 0.5; done
fi
