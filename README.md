# Unitree G1

29 自由度 G1 的人形 SDK 机型配置。机型仓库负责关节顺序、模型接口、
硬件映射、遥控绑定和启动入口；控制状态机、操作服务、推理与驱动由共享组件提供。

## 配置与依赖

- `config/g1.yaml`：主配置，仿真与实机共用，包括状态机、策略、遥控和日志。
- `config/g1_hardware.yaml`：5 路 UART 总线、29 电机、腰踝耦合及 IMU。
- `resources/xml/`、`resources/urdf/`、`resources/meshes/`：仿真与结构资源。
- `resources/kinematics/`：耦合标定表的接口说明，数据单独提供。
- `policy/`：模型和参考动作，按使用许可单独提供，不纳入源码仓库。
- `resources/arm_interactions/`、`resources/audio/`：交互动作和可选音频的配置说明。

依赖 `humanoid_common`、`whole_body`、`motor`、`imu`、`rl` 和 `mujoco`。
本机型的策略目录使用 ONNX，推理依赖由 RL 组件的 CMake 管理。

完整构建在 SDK 根目录执行：

```bash
source build/envsetup.sh
lunch k3-com260-kit-humanoid-unitree-g1
m
```

单包构建时，按依赖顺序进入对应包执行 `mm`。缺少运行资源时先补齐资源，
不要用其他模型替代而沿用当前观测、增益和动作尺度。

## 启动

在 SDK 根目录执行：

```bash
source build/envsetup.sh
run_g1.sh --sim
```

台阶场景使用 `run_g1.sh --sim --stairs`；不启动终端界面使用 `--no-tui`。
实机启动为 `run_g1.sh --real --tui`，仅启动服务使用 `run_g1.sh --real`。
服务已运行时用 `run_hmi_tui_g1.sh` 连接，`--status` 只读查询状态。
不要重复启动占用同一电机总线的 driver。

启动保持 POWER_OFF，不自动使能。接管控制权后依次经过 DAMP、HOME、ZERO、RL。
HOME 为收腿准备姿态，ZERO 使用所选策略的准备姿态；等待当前过渡完成再切下一状态。
首次硬件校准、修改接线或更换模型后的验证应使用可靠支撑。

## 运控与遥控

| 显示名称 | 策略键 | 执行方式 |
| --- | --- | --- |
| 常规运控（LocoMode） | `stand` | 默认模式；29 轴站走策略，零速站立，收到速度后行走 |
| 常规运控（MJLab） | `walk_mjlab` | 29 轴行走，零命令站立 |
| 常规运控（RL Gym） | `walk_rlgym` | 12 轴腿部策略，上身保持准备姿态；零速仍有步态相位 |
| 舞蹈运控 | `dance_mode` | 进入后站立待命；从动作列表触发舞蹈、功夫、Dance 1、Packed、Jumps 1 |
| SONIC 运控 | `sonic` | 使用配置中性姿态的静态参考，展示通用 tracker 的站立控制 |
| SONIC 运控（规划行走） | `sonic_planner` | 速度指令经 kinematic planner 生成参考，再交给 SONIC tracker |

模式入口和动作目录均在 YAML 中配置。`policy_names` 只列界面可选的模式；
`policy_actions` 为模式配置待命策略与动作模型，选择模式不启动动作。
动作结束或取消后回到该模式的待命策略，不切换到另一个模式。
RL 内切换由 common 后台准备目标模型，保留当前控制；准备成功并满足交出条件后，
用目标策略的 `policy_switch.transition_duration` 同步过渡位置和 KP/KD。
加载失败保留当前策略。模型输入、动作尺度和增益不跨策略复用。
具体播放与交接条件见 [运控说明](resources/motion_modes/README.md)。

- [手柄操作](docs/gamepad.md)：绑定、长按、控制权与震动。
- [手机遥控](docs/phone_teleop.md)：按键、双摇杆、速度限制与平滑。
- [提示音](docs/audio_prompts.md)：事件、播报内容与独立播放进程。
- [手臂动作接口](resources/arm_interactions/README.md)：可选上身轨迹的格式；默认策略不挂载此目录。

## 硬件配置

控制和 driver 周期为 2 ms，策略推理周期为 20 ms。串口使用 6 Mbaud，
五路分别为腰部、左右臂、左右腿。设备路径默认以 `/dev/g1/` 下的角色名表示；
部署前必须改为实际、稳定的设备路径，或由安装环境创建相应 udev 链接。
不要依据 `/dev/ttyUSB*` 的出现顺序分配肢体。

先运行 `ls -l /dev/serial/by-id/`，按转换器序列号与接口号确认五路总线及 IMU，
将 `g1_hardware.yaml` 中各 `device` 替换为对应的完整 by-id 路径。
同一多口转换器的不同接口也必须分别核对，不能按路径列表顺序分配左右腿。
修改接线或更换转换器后，在 POWER_OFF 下重新检查反馈归属。
可选的自定义 udev 规则应匹配实际序列号及接口号，再创建 `/dev/g1/` 角色链接；
设备标识和本机规则由部署环境保存，不作为通用机型配置分发。

普通关节发送位置、速度、前馈力矩和 KP/KD，由电机执行 PD。
左右踝 pitch/roll 和腰 pitch/roll 使用 `table_2d` 标定映射、
`motor_projected` 比例项投影以及电机侧阻尼，见 [耦合接口](resources/kinematics/README.md)。

IMU 刚性固定在骨盆前侧，传感器 X 朝上、Y 朝左、Z 朝后；
`mounting_matrix` 转换为机器人 X 前、Y 左、Z 上。
如果改变安装方向或移到活动连杆上，必须同步修改安装变换与关节链配置。

通信异常在配置的有限容错窗口内保留有效目标，超出窗口进入故障处理。
容错不代表持续使用任意过期反馈，也不覆盖电机主动故障、非有限值或无效机构映射。
串口帧量化、指令范围和反馈检查分别由驱动、whole_body 与机型配置负责。

## 开机服务

`scripts/install_g1_service.py` 安装 `g1.service`，由启动器管理 driver、control、HMI，
并启动可选手柄与音频客户端。安装需要系统管理权限；先查看脚本 `--help`，
使用 `--sdk-root` 指定安装目录、`--user` 指定运行用户。
网络监听地址与网页入口通过 `--listen`、`--public-url` 配置，不在仓库保存配对凭据。

实时调度和无桌面配置由安装器显式选项启用，参见 [启动器说明](tests/launcher/README.md)。
服务异常重启后仍保持 POWER_OFF，操作者确认故障及设备状态后再接管。

## 日志与验证

日志目录由 `logging.directory` 指定。普通概览低频落盘，高频数据保留在有界内存环形缓冲区；
故障触发后保存前后片段。`storage` 限制总占用及剩余空间，`blackbox` 控制片段窗口和内存。
日志、故障包、配对码和测试输出不纳入源码仓库。

[测试说明](tests/README.md) 列出离线映射、启动器、遥控和 MuJoCo 回归入口。
测试数据用于确定性回归，不能作为其他机器的校准参数。
第三方许可证与版权说明见 [NOTICE](NOTICE)。运行模型、动作与媒体需由使用方按许可提供。
