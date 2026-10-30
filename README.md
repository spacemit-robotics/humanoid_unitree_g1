# humanoid_unitree_g1 — Unitree G1

## 项目简介

Unitree G1 人形机器人应用包，29 自由度（腿 12 + 腰 3 + 臂 14）。包含该机型专属的 YAML 配置、MuJoCo 仿真资源、RL 策略接口及启动脚本，通用控制逻辑见 `humanoid_common` 仓库。

## 功能特性

支持：

- FSM 完整控制流程（driver + control + hmi 三进程），支持仿真与真实硬件。
- sim2sim 跨机推理（PC 仿真 + K3 板卡 RL 推理），支持 SHM 与 UDP 通信。
- 单机一键启动、开机服务，以及 TUI、网页和手柄遥控。
- 通过 YAML 配置运控模式、模式内动作和运行中的策略交接。

| 显示名称 | 策略键 | 执行方式 |
| --- | --- | --- |
| 常规运控（LocoMode） | `stand` | 默认模式；29 轴站走策略，零速站立，收到速度后行走 |
| 常规运控（MJLab） | `walk_mjlab` | 29 轴行走，零命令站立 |
| 常规运控（RL Gym） | `walk_rlgym` | 12 轴腿部策略，上身保持准备姿态；零速仍有步态相位 |
| 舞蹈运控 | `dance_mode` | 进入后站立待命；从动作列表触发舞蹈、功夫、Dance 1、Packed、Jumps 1 |
| SONIC 运控 | `sonic` | 使用中性姿态的静态参考站立 |
| SONIC 运控（规划行走） | `sonic_planner` | 速度指令经 kinematic planner 生成参考，再交给 SONIC tracker |

## 快速开始

### 环境准备

本应用需在 spacemit_robot SDK 内使用，依赖 `humanoid_common`、`whole_body`、`motor`、`imu`、`rl` 和 `mujoco`。

**PC 端（x86_64）**：

```bash
sudo apt install -y libeigen3-dev libyaml-cpp-dev libglfw3-dev cmake g++ python3-yaml
```

MuJoCo 与 x86_64 ONNX Runtime 由对应组件的 CMake 查找或自动获取，统一缓存到 `~/.cache/thirdparty/`，无需手动复制到系统目录。

**K3 板卡端**：

```bash
sudo apt install -y libeigen3-dev libyaml-cpp-dev spacemit-tcm pkg-config python3-yaml
```

安装 SpacemiT ONNX Runtime 的步骤见 SDK 中 `components/model_zoo/rl/README.md`；如需在 K3 显示仿真窗口，还需按 `components/simulation/mujoco/README.md` 准备图形依赖。

### 构建编译

完整构建在 SDK 根目录执行：

```bash
source build/envsetup.sh
lunch k3-com260-kit-humanoid-unitree-g1
m
```

依赖已构建后，只更新本机型的配置或脚本时，可在同一环境中单包安装：

```bash
cd application/native/humanoid_unitree_g1
mm
```

### 模型下载

```bash
download_models_g1.sh
```

`policy/` 不纳入 Git。脚本只从 SpacemiT 模型库下载已发布资源，并保留目录层级，不单独访问上游模型网站。所选模式的模型与参考动作路径以 `config/g1.yaml` 为准，资源清单见 [运控与动作说明](resources/motion_modes/README.md)。

模型缺失时先补齐对应资源，不要替换成其他模型而沿用当前观测、增益和动作尺度。实机还需配套的腰踝标定数据，准备方式见 [硬件接入](docs/hardware.md)。

### 运行示例

以下命令在 SDK 根目录加载环境后执行；每个新终端均需执行 `source build/envsetup.sh`。

**单机完整仿真**：

```bash
run_g1.sh --sim
```

默认启动三个核心进程和 TUI；只启动核心进程加 `--no-tui`。台阶场景使用 `run_g1.sh --sim --stairs`，它只改变地形，不改变所选模型的能力。

**FSM 分终端启动**：

```bash
run_driver_g1.sh --sim  # 终端 1：MuJoCo 仿真
run_control_g1.sh      # 终端 2：控制与 RL 推理
run_hmi_g1.sh --sim    # 终端 3：操作服务
run_hmi_tui_g1.sh      # 终端 4：连接操作服务的 TUI
```

三个核心进程也可分布在 PC 与 K3 上：PC 启动 driver，K3 启动 control 和 HMI；先在两端 `config/g1.yaml` 中配置 UDP 通信地址与端口，并确保网络互通。分终端启动时不要同时运行一键启动器。

**sim2sim（双终端）**：

```bash
run_driver_g1.sh --sim  # 终端 1（PC）
run_sim2sim_g1.sh       # 终端 2（K3 板卡）
```

**实机运行**：

完成 [硬件接入](docs/hardware.md) 后启动：

```bash
run_g1.sh --real --tui
```

仅启动服务使用 `run_g1.sh --real`。服务已运行时用 `run_hmi_tui_g1.sh` 连接，或用 `run_hmi_tui_g1.sh --status` 只读查询状态，不要重复启动占用同一电机总线的 driver。

启动保持 POWER_OFF，不自动使能。接管控制权后依次经过 DAMP、HOME、ZERO、RL，等待当前过渡完成再切下一状态。HOME 为收腿准备姿态，ZERO 使用所选策略的准备姿态。首次硬件校准、修改接线或更换模型后的验证应使用可靠支撑。

在界面的模式列表中选择运控；舞蹈运控进入后保持站立，需从动作列表另行触发舞蹈。兼容模式支持在 RL 中交接，动作结束或取消后回到所属模式待命。交接条件、动作资源和参数见 [运控与动作说明](resources/motion_modes/README.md)。

## 详细使用

主要配置与资源：

| 路径 | 用途 |
| --- | --- |
| `config/g1.yaml` | 仿真与实机共用的主配置，包括状态机、策略、遥控和日志 |
| `config/g1_hardware.yaml` | 电机总线、关节映射、腰踝耦合及 IMU 安装配置 |
| `resources/xml/`、`resources/urdf/`、`resources/meshes/` | 仿真与结构资源 |
| `resources/kinematics/` | 腰踝耦合标定数据接口，数据单独提供 |
| `policy/` | 模型与参考动作，按 YAML 路径放置 |
| `resources/arm_interactions/`、`resources/audio/` | 可选交互动作与音频资源 |

按功能查阅：

- [运控与动作](resources/motion_modes/README.md)：模式选择、动作触发及策略交接。
- [硬件接入](docs/hardware.md)：总线设备、IMU 安装与部署前检查。
- [耦合标定](resources/kinematics/README.md)：腰踝数据格式、关节顺序与映射接口。
- [手柄操作](docs/gamepad.md)：按键绑定、长按、控制权与震动。
- [手机遥控](docs/phone_teleop.md)：网页入口、按键、双摇杆与速度配置。
- [提示音](docs/audio_prompts.md)：事件、播报内容与播放配置。
- [手臂动作接口](resources/arm_interactions/README.md)：可选上身轨迹格式；默认策略不挂载此目录。
- [启动器与开机服务](tests/launcher/README.md)：安装参数、服务状态与调度配置。
- [测试说明](tests/README.md)：离线映射、启动器、遥控和 MuJoCo 回归入口。

`install_g1_service.py` 可安装开机服务，使用前查看 `--help`；安装需要系统管理权限。服务异常重启后仍保持 POWER_OFF，确认故障和设备状态后再接管。网页监听地址和入口由部署参数指定，仓库不保存配对凭据。

日志目录由 `logging.directory` 指定，`logging.storage` 限制占用，`logging.blackbox` 配置故障前后片段。日志、故障包和测试输出不纳入源码仓库。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| ONNX 模型或参考动作不存在 | 运行 `download_models_g1.sh`，按 YAML 检查所选模式的运行资产是否完整 |
| 进程启动后通信无数据 | 检查两端通信方式、地址和端口是否匹配；跨机使用 UDP，并检查网络及防火墙 |
| 实机反馈未就绪 | 按 [硬件接入](docs/hardware.md) 核对设备路径、总线归属、IMU 和标定数据，保持 POWER_OFF 排查 |
| RL 控制不稳定 / 立即摔倒 | 在可靠支撑下检查关节顺序、零位、IMU 方向，以及模型配套的观测、动作尺度和增益 |
| 选择舞蹈运控后没有跳舞 | 该模式先站立待命，需在动作列表中触发具体动作 |

## 版本与发布

| 版本 | 说明 |
| --- | --- |
| 0.1.0 | 初始版本，支持 G1 29-DOF FSM 与 sim2sim 仿真 |

## 贡献方式

欢迎通过本仓库的 Issue 反馈问题，或提交 Pull Request 改进配置、资源和脚本。

## License

本仓库源码文件头声明为 Apache-2.0，最终以本目录 [LICENSE](LICENSE) 文件为准。第三方许可证与版权说明见 [NOTICE](NOTICE)；运行模型、动作与媒体需按各自许可使用。
