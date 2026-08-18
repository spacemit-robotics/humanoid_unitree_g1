# humanoid_unitree_g1 — Unitree G1

## 项目简介

Unitree G1 人形机器人应用包，29 自由度（腿 12 + 腰 3 + 臂 14）。包含该机型专属的 YAML 配置、MuJoCo 仿真资源、RL 策略模型及启动脚本，通用控制逻辑见 `humanoid_common` 仓库。

## 功能特性

支持：
- FSM 完整仿真流程（driver + control + hmi 三进程）
- sim2sim 跨机推理（PC 仿真 + K3 板卡 RL 推理）
- PC 单机仿真（SHM 或 UDP 本机通信）
- motion / dance / kungfu / stand / tracking / tracking_packed / tracking_wbt_jumps1 / holomotion / protomotions 九套预训练 RL 策略
  - stand 为独立站立策略，也作为 dance/kungfu 的前置策略
  - tracking / tracking_packed 为 unitree_rl_mjlab motion tracking 策略：tracking 使用纯 actor + 外挂 npz，tracking_packed 使用包装版 ONNX（motion 内嵌，提取为 npz 后走同一路线）
  - tracking_wbt_jumps1 为 BeyondMimic (whole_body_tracking) 训练的 LAFAN1 jumps1 跳跃动作策略（244s），ZERO 阶段经 `zero_target_pos` 对齐动作起始姿态
  - holomotion / protomotions 为 G1 通用动作追踪策略，参考动作由 `humanoid_common` 的 `policy_adapter` 转换为对应模型输入
  - tracking_packed 的 npz 可通过 `download_models_g1.sh` 直接下载；自训新模型时用 `extract_packed_motion.py` 从包装版 ONNX 提取：
    ```
    python3 components/model_zoo/rl/scripts/extract_packed_motion.py <packed.onnx> -o <output.npz>
    ```

不支持：
- 真实机器人部署（当前仅仿真）
- 在线训练或策略更新

## 快速开始

### 环境准备

**PC 端（x86_64）**：

```bash
# 系统依赖
sudo apt install -y libeigen3-dev libyaml-cpp-dev libglfw3-dev cmake g++

# MuJoCo 3.4.0
mkdir -p ~/.mujoco
wget https://github.com/google-deepmind/mujoco/releases/download/3.4.0/mujoco-3.4.0-linux-x86_64.tar.gz
tar -xzf mujoco-3.4.0-linux-x86_64.tar.gz -C ~/.mujoco/

# ONNX Runtime 1.21.0（仅需 x86_64 本机 RL 推理时安装）
wget https://github.com/microsoft/onnxruntime/releases/download/v1.21.0/onnxruntime-linux-x64-1.21.0.tgz
tar -xzf onnxruntime-linux-x64-1.21.0.tgz
sudo cp -r onnxruntime-linux-x64-1.21.0/include/* /usr/local/include/
sudo cp -r onnxruntime-linux-x64-1.21.0/lib/* /usr/local/lib/
sudo ldconfig
```

**K3 板卡端**：

```bash
# 系统依赖
sudo apt install -y libeigen3-dev libyaml-cpp-dev spacemit-tcm pkg-config

# SpacemiT 定制版 ONNX Runtime（含 A100 核 EP 加速）
# 如已安装标准版，先卸载：
sudo apt remove libonnxruntime-dev libonnxruntime1.23 python3-onnxruntime
# 安装定制版：
sudo apt install -y libonnx-dev libonnx-testdata libonnx1t64 \
  libonnxruntime-providers onnxruntime-tools python3-onnx \
  python3-spacemit-ort spacemit-onnxruntime
```

### 构建编译

本仓库只包含机型配置、资源和启动脚本。策略输入适配由
`humanoid_common` 的 `behavior_manager/policy_adapter` 提供，需在
spacemit_robot SDK 内构建：

```bash
source build/envsetup.sh
lunch k3-com260-kit-humanoid-unitree-g1
m
```

### 模型下载

```bash
download_models_g1.sh
```

`policy/` 不纳入 Git。HoloMotion 与 ProtoMotions 至少需要以下运行资产；
尚未发布到模型库时，可按相同目录结构手动放置：

```text
policy/holomotion/motion_tracking_model_v1.3.2.onnx
policy/holomotion/lafan1_walk1_subject1_50hz_formal_12s.csv
policy/protomotions/unified_pipeline.onnx
policy/protomotions/output_walk_50hz.csv
```

### 运行示例

**FSM 完整仿真（三终端）**：

```bash
run_driver_g1.sh    # 终端1（PC，x86_64）
run_control_g1.sh   # 终端2（K3 板卡）
run_hmi_g1.sh       # 终端3（K3 板卡）
```

在 HMI 中按 `p` 进入策略选择页，通过方向键选择策略并按 Enter 确认。
策略应在 POWER_OFF 或 DAMP 状态切换；随后依次进入 DAMP、ZERO 和 RL。

通用 tracker 的运行数据流为：

```text
参考动作 -> policy_adapter -> PolicyExecutor/ONNX Runtime
        -> 29 维 PD 目标 -> MuJoCo
```

**sim2sim（双终端）**：

```bash
run_driver_g1.sh    # 终端1（PC）
run_sim2sim_g1.sh   # 终端2（K3 板卡）
```

## 详细使用

参考 SpacemiT 人形机器人 SDK 官方文档。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `[PolicyConfigLoader] ONNX 模型文件不存在` | 运行 `download_models_g1.sh`，或检查对应策略的 `policy/` 运行资产是否完整 |
| 进程启动后通信无数据 | 检查 `config/g1.yaml` 中 `driver_ip` / `control_ip` 是否正确，确认两机可互相 ping 通 |
| RL 控制不稳定 / 立即摔倒 | 检查 YAML 中 `action_joint_index` 和 `rl_default_pos` 与当前策略是否匹配 |

## 版本与发布

| 版本 | 说明 |
| --- | --- |
| 0.1.0 | 初始版本，支持 G1 29-DOF FSM 与 sim2sim 仿真 |

## 贡献方式

贡献者与维护者名单见：`CONTRIBUTORS.md`

## License

本仓库源码文件头声明为 Apache-2.0，最终以本目录 `LICENSE` 文件为准。
