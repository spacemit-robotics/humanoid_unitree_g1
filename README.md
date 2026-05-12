# humanoid_unitree_g1 — Unitree G1

## 项目简介

Unitree G1 人形机器人应用包，29 自由度（腿 12 + 腰 3 + 臂 14）。包含该机型专属的 YAML 配置、MuJoCo 仿真资源、RL 策略模型及启动脚本，通用控制逻辑见 `humanoid_common` 仓库。

## 功能特性

支持：
- FSM 完整仿真流程（driver + control + hmi 三进程）
- sim2sim 跨机推理（PC 仿真 + K3 板卡 RL 推理）
- PC 单机仿真（SHM 或 UDP 本机通信）
- motion / dance / kungfu / tracking 四套预训练 RL 策略
  - tracking 为 BeyondMimic 风格 motion tracking（unitree_rl_mjlab 训练，纯 actor + 外挂 npz 参考动作）

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

本仓库为纯资产包（配置、资源、脚本），不含可独立编译的源码，需在 spacemit_robot SDK 内对本应用案例全量构建：

```bash
source build/envsetup.sh
lunch k3-com260-kit-humanoid-unitree-g1
m
```

### 模型下载

```bash
download_models_g1.sh
```

### 运行示例

**FSM 完整仿真（三终端）**：

```bash
run_driver_g1.sh    # 终端1（PC，x86_64）
run_control_g1.sh   # 终端2（K3 板卡）
run_hmi_g1.sh       # 终端3（K3 板卡）
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
| `[PolicyConfigLoader] ONNX 模型文件不存在` | 运行 `download_models_g1.sh` 下载模型后重试 |
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
