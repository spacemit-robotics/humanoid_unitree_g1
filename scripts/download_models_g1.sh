#!/bin/bash
ROBOT_NAME="humanoid_unitree_g1"
BASE_URL="https://archive.spacemit.com/spacemit-ai/model_zoo/rl/${ROBOT_NAME}/"
: "${SDK_ROOT:=$(cd "$(dirname "$(readlink -f "$0")")/../../.." && pwd)}"
POLICY_DIR="$SDK_ROOT/application/native/${ROBOT_NAME}/policy"

echo "[download_models] 从 SpacemiT 模型库拉取 ${ROBOT_NAME} 模型..."
mkdir -p "$POLICY_DIR"
wget -r -np -nH --cut-dirs=4 -R "index.html*" --no-check-certificate \
  -P "$POLICY_DIR" "$BASE_URL"
echo "[download_models] 完成，模型已保存至 $POLICY_DIR"
