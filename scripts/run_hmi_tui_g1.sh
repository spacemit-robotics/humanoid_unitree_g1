#!/bin/bash
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
# Attach a terminal to the existing G1 operator service.
set -euo pipefail
if [[ -z "${SDK_ROOT:-}" ]]; then
    SDK_ROOT=$(dirname "$(readlink -f "$0")")
    while [[ "$SDK_ROOT" != / && ! -f "$SDK_ROOT/build/envsetup.sh" ]]; do
        SDK_ROOT=$(dirname "$SDK_ROOT")
    done
fi
CONFIG="${G1_CONFIG:-$SDK_ROOT/application/native/humanoid_unitree_g1/config/g1.yaml}"
CONNECTION="${XDG_STATE_HOME:-$HOME/.local/state}/humanoid-operator/g1/connection.json"
CONNECTION=$(python3 -c '
import sys
import yaml
with open(sys.argv[1], encoding="utf-8") as source:
    config = yaml.safe_load(source)
print(config.get("operator_service", {}).get("connection_file", sys.argv[2]))
' "$CONFIG" "$CONNECTION")
exec "$SDK_ROOT/output/staging/bin/hmi_tui" --connection "$CONNECTION" "$@"
