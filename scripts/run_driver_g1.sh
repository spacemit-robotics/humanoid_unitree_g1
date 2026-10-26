#!/bin/bash
# Select the standard driver backend without duplicating the machine configuration.
set -euo pipefail
: "${SDK_ROOT:=$(cd "$(dirname "$(readlink -f "$0")")/../../.." && pwd)}"
CONFIG="${G1_CONFIG:-$SDK_ROOT/application/native/humanoid_unitree_g1/config/g1.yaml}"
DRIVER="$SDK_ROOT/output/staging/bin/driver_runtime"
BACKEND_OVERRIDE=""
DRIVER_ARGS=()
STAIRS=no
for ARG in "$@"; do
    if [[ "$ARG" == --stairs ]]; then STAIRS=yes; continue; fi
    if [[ -n "$BACKEND_OVERRIDE" ]]; then
        echo "Specify only one of --sim or --real" >&2
        exit 1
    fi
    case "$ARG" in
        --sim) BACKEND_OVERRIDE=mujoco ;;
        --real) BACKEND_OVERRIDE=whole_body ;;
        --help|-h)
            echo "Usage: run_driver_g1.sh [--sim|--real] [--stairs]"
            exit 0 ;;
        *) echo "Unknown option: $ARG" >&2; exit 1 ;;
    esac
done
if [[ ! -x "$DRIVER" || ! -f "$CONFIG" ]]; then
    echo "[run_driver_g1] Missing driver_runtime or machine configuration." >&2
    exit 1
fi
BACKEND=$(awk '
    /^driver:[[:space:]]*($|#)/ { in_driver = 1; next }
    in_driver && /^[^[:space:]#]/ { exit }
    in_driver && $1 == "backend:" { gsub(/[" ]/, "", $2); print $2; exit }
' "$CONFIG")
BACKEND="${BACKEND_OVERRIDE:-$BACKEND}"
if [[ -n "$BACKEND_OVERRIDE" ]]; then
    DRIVER_ARGS=(--backend "$BACKEND_OVERRIDE")
fi
if [[ "$STAIRS" == yes ]]; then
    [[ "$BACKEND" == mujoco ]] || { echo "台阶场景仅用于仿真。" >&2; exit 1; }
    DRIVER_ARGS+=(--scene scene_stairs.xml)
fi
if [[ "$BACKEND" == "whole_body" ]]; then
    # Serial access is provided by the board's device permissions; do not elevate here.
    exec flock --exclusive --nonblock /tmp/g1_hardware.lock "$DRIVER" "$CONFIG" "${DRIVER_ARGS[@]}"
fi
exec "$DRIVER" "$CONFIG" "${DRIVER_ARGS[@]}"
