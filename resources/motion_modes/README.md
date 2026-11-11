# 运控模式与动作

`config/g1.yaml` 的 `policy_names` 定义七个可选模式，默认常规运控（LocoMode）。
底层模型与动作资源放在 `policy/`，不随源码提交；
`download_models_g1.sh` 获取模型库中已发布的资源。

| 模式 | 模式 ID | 进入模式后的行为 | 模式内动作 |
| --- | --- | --- | --- |
| 常规运控（LocoMode） | `stand` | 零速站立，收到速度后行走 | 无 |
| 常规运控（MJLab） | `walk_mjlab` | 零速站立，收到速度后行走 | 无 |
| 常规运控（RL Gym） | `walk_rlgym` | 零速仍踏步，收到速度后行走 | 无 |
| 舞蹈运控 | `dance_mode` | 使用 stand 站立待命 | 舞蹈、功夫、Dance 1、Packed、Jumps 1 |
| SONIC 运控 | `sonic` | 使用中性姿态静态参考站立，等待动作请求 | 平稳站立、慢走、行走转身、玛卡莲娜舞、五个交互动作 |
| SONIC 运控（规划行走） | `sonic_planner` | 站立，收到速度后由规划器生成参考 | 无 |
| SuperMimic 运控 | `supermimic_mode` | 跟踪静态待命参考站立 | 走路、鼓掌、指向、闪身步、浪子踢球、五个交互动作 |

舞蹈运控使用 `policy_actions.idle_policy: stand`。只有收到动作请求，
才后台加载对应模型并交接；动作结束或取消后回到该模式的 stand，等待下一条请求。
SONIC 运控和 SuperMimic 运控由同一个跟踪策略完成待命和动作：待命时跟踪目录默认动作的静态参考，
触发动作只替换参考，不切换模型、不重置观测历史。
选模式、进入 RL、重复收到同一条请求，都不会自动开始或重复播放动作。
`stand` 是 LocoMode 站走模型的兼容策略键。独立选择时接收速度；
用作舞蹈待命时，由所属模式的零速度限幅保持站立。
ProtoMotions 暂不提供模式入口和动作绑定，保留执行策略与资源配置。

| 动作 | 动作 ID | 执行策略 | 模型及参考资源（相对机型目录） |
| --- | --- | --- | --- |
| 舞蹈 | `dance` | `dance` | `policy/dance/dance_0605.onnx`，内置 18 秒动作 |
| 功夫 | `kungfu` | `kungfu` | `policy/kungfu/kungfu_0609.onnx`，内置 18 秒动作 |
| Dance 1 | `dance1` | `tracking` | `policy/tracking/`，配套参考 131.48 秒 |
| Packed | `packed` | `tracking_packed` | `policy/tracking_packed/`，配套参考 131.48 秒 |
| Jumps 1 | `jumps1` | `tracking_wbt_jumps1` | `policy/tracking_wbt_jumps1/`，配套参考 244.44 秒 |
| 平稳站立 | `standing` | `sonic` | `policy/sonic/standing/`，两帧相同的中性姿态参考 |
| 慢走 | `slow_walk` | `sonic` | `policy/sonic/slow_walk/`，5.46 秒，起步、向前四步、停稳 |
| 行走转身 | `walk` | `sonic` | `policy/sonic/walking_quip_360_R_002__A428/`，9.10 秒 |
| 玛卡莲娜舞 | `macarena` | `sonic` | `policy/sonic/macarena_001__A545/`，27.50 秒 |
| 待命 | `sm_standby` | `supermimic_mode` | `policy/supermimic/references/standby.npz`，两帧相同的待命姿态参考 |
| 走路 | `sm_walk` | `supermimic_mode` | `policy/supermimic/references/walk.npz`，10.3 秒 |
| 鼓掌 | `sm_clap` | `supermimic_mode` | `policy/supermimic/references/clap.npz`，17.0 秒 |
| 指向 | `sm_point` | `supermimic_mode` | `policy/supermimic/references/point.npz`，10.7 秒 |
| 闪身步 | `sm_dance` | `supermimic_mode` | `policy/supermimic/references/dance.npz`，11.2 秒 |
| 浪子踢球 | `sm_langzi_tiqiu` | `supermimic_mode` | `policy/supermimic/references/langzi_tiqiu.npz`，约 9.1 秒 |

两个跟踪模式均支持以下交互参考，时长包含首尾各 0.5 秒待命和 1.5 秒过渡：

| 动作 | SONIC 动作 ID | SuperMimic 动作 ID | 时长 |
| --- | --- | --- | --- |
| 握手 | `handshake` | `sm_handshake` | 7.0 秒，含伸手停留 2 秒 |
| 高举挥手 | `wave_high` | `sm_wave_high` | 9.7 秒 |
| 胸前挥手 | `wave_chest` | `sm_wave_chest` | 6.6 秒 |
| 飞吻 | `blow_kiss` | `sm_blow_kiss` | 7.0 秒 |
| 鼓掌（短） | `clap_short` | `sm_clap_short` | 6.2 秒 |

TUI 和网页从原有动作列表选择；现有手柄绑定不变。这些参考保持腿部站姿、加入上身动作，
全身指令仍由跟踪模型输出，不使用上身电机直接接管。播放完成后回到待命姿态，也可按取消提前返回。
原来的 `sm_clap` 为 17 秒鼓掌片段，仍保留。

前五项是不同模型，common 按 `policy_actions.actions.<ID>.policy` 调度；
SONIC、SuperMimic 分别使用同一模型的 `sonic_actions`、`supermimic_actions` 参考目录。
它们在客户端都采用“选模式，再触发动作”。SuperMimic 动作参考首尾为待命姿态，
每端包含 0.5 秒待命和 1.5 秒过渡，完整播放后保持末帧。
待命参考使用策略默认关节姿态、直立骨盆和由 MJCF 脚底接触点确定的高度。
走路片段向前约 2.7 m；闪身步包含小幅跳跃，操作前应留出活动空间。
新增动作只需配置对应目录和资源，不在 common 中写机型名或固定动作数量。
SONIC 的行走转身和舞蹈使用 GEAR-SONIC 的 G1 示例参考，每个目录提供
`joint_pos.csv`、`joint_vel.csv`、`body_quat.csv`，50 Hz，关节顺序保持模型顺序。
TUI 按 A 选择动作，播放期间按 C 取消回到站立；网页复用同一动作列表。
慢走的末尾回到中性站姿并保持；其他动作完整播放后保持末帧。
可从列表再次选择平稳站立或其他动作。
手柄 RT+A/B/X 分别触发站立、行走转身、玛卡莲娜舞，均长按 1 秒。
RT+↑ 长按 1 秒触发完整慢走。慢走采用 BONES-SEED 的 G1 起步、连续行走和
停步参考，120 Hz 重采样为 50 Hz，再按左右脚落地相位裁剪、交叠衔接。
保留原始迈步节奏，末尾过渡到配置的 SONIC 中性站姿；每次触发只播放一次。
这些外部动作资源需依照 BONES-SEED 许可获取，不随源码再分发。
这是参考动作播放；自由行走速度指令仍使用 SONIC 规划行走模式。

SONIC 使用独立的 FP32 `model_encoder.onnx` 和 `model_decoder.onnx`，
先将参考编码为 64 维 latent，再与 930 维本体历史拼接交给 decoder，每秒执行 50 次。
静态展示与规划行走共用这两个模型；规划行走另用 `policy/sonic/planner_sonic.onnx`
在后台生成参考，控制线程持续使用最近的有效参考。
`robot_base.threads.motion_planner` 将规划线程及其 CPU 推理线程池配置到 CPU 0、3，
使用 `sched: other`；planner 的 `runtime.threads: 2`
包含调用线程。规划模型在选择该模式时加载并预热一次，进入 RL 不再加载。
所有策略及 SONIC encoder 复用 `g1_cpu_runtime`：CPU FP32、2 线程、关闭忙等，
调用线程为 `rl_infer`（CPU 7），额外 worker 绑定 CPU 4。encoder 与 decoder 串行执行，
共用这两个物理核，不占 A100。驱动、控制仍使用 CPU 1、2。
无桌面服务配置将日志/HMI 等后台任务限制在 CPU 0、3、5、6；网络和 USB2 中断移到 CPU 3，
电机/IMU USB 保持 CPU 6，Type-C 音频保持 CPU 5。其他主机可统一修改该 YAML 锚点。
提前量为 40 ms；行走每 1 s、跑步每 0.1 s、爬行每 0.2 s 重规划，
每 100 ms 检查指令变化，使用最新指令，不积压请求；推理超时跳过错过的检查拍。
允许规划输出 9–11 个 token；迟到轨迹跳过过期部分并完成 8 帧混合。
其他主机可按可用核心调整这组配置；`events.log` 的 `RL runtime ready`、
`SONIC encoder ready`、`SONIC planner model ready` 记录 provider 和 worker 实际落核与调度。

SuperMimic 使用 SuperMimic-Repro-Sim2Real 的 `e13i_0291000` 模型，
以 50 Hz 推理（`infer_decimation: 1`），复用 `g1_cpu_runtime`。
关节顺序为 `robot_base.joint_names` 的 29 轴顺序，增益、默认姿态及动作尺度来自配套的 `deploy_config.json`。

| 模型输入／输出 | 内容 |
| --- | --- |
| `obs_hist` | 10 帧 × 93：q−q0、dq、gyro、重力投影、上一帧原始 action；按项排列，旧帧在前 |
| `goal` | 10 帧 × 68：参考 q−q0、dq、骨盆重力投影、骨盆系角速度、航向系线速度、骨盆高度 |
| `actions` | 29 维；q_target = q0 + action_scale · action |

播放时参考窗口为未来第 1–10 拍，即提前 20–200 ms；待命和播放结束后保持静态参考。
`target_position_lower/upper` 对模型输出的关节目标截幅后继续控制。

RL 内选择同组模式时保持控制：速度归零，后台加载目标，当前策略到达交接点后切换。
普通站走策略在零速有效推理帧交接；定时动作播放中选择其他模式会等待末帧。
需要提前结束时先取消动作，准备好待命策略后从当前有效目标交接，位置与增益同步过渡。
SONIC、SuperMimic 的取消由自身参考过渡处理。模型加载失败保持当前控制并显示动作失败。
机型交接等待上限为 300 秒，HOME/ZERO 中不切换模式。

各执行策略的观测、历史、动作尺度与增益独立保留。
内置定时舞蹈不叠加输出过渡延迟；回待命使用 stand 的 0.5 秒目标与增益过渡。
进入模式的 ZERO 姿态也来自该模式的待命策略。

SuperMimic 取消及模式交接时，原动作继续推进并逐渐减弱，过渡回待命参考。
`supermimic_actions.transition_duration` 为 1 秒；单动作的 `cancel_transition_duration` 可覆盖返回时长，
闪身步配置为 2 秒，其他动作保持 1 秒。过渡期间显示退出阶段，结束后允许下一个动作或模式接管。
取消动作不会立即失能电机。

台阶场景启动命令为 `run_g1.sh --sim --stairs`。它仅增加仿真地形，不改变模型能力；
当前行走策略不是专门的越障模型。

## 资源准备

SuperMimic 的模型与基础参考动作由 `scripts/prepare_supermimic_assets.py` 生成。
准备解压后的 `e13i_0291000`（含 `policy_ir9.onnx`、`deploy_config.json`）、
ProtoMotions 的 `g1_bones_seed_mini.pt` 和上游 `motions/custom_dance/`，在机型目录执行：

```bash
python3 scripts/prepare_supermimic_assets.py \
    --bundle "<e13i_0291000目录>" \
    --bones-library "<g1_bones_seed_mini.pt路径>" \
    --nju-motions "<上游目录>/motions/custom_dance"
```

依赖 numpy、PyYAML、onnx、onnxruntime、torch 和 mujoco。
脚本将模型的 `obs`、`goal`、`action` 改名为 `obs_hist`、`goal`、`actions`，不改变网络计算，
并检查 YAML 与模型参数一致、改名后推理结果相同。
输出位于 `policy/supermimic/`，包括 `policy.onnx`、`deploy_config.json`、`references/*.npz` 和 `SOURCES.json`。
清单记录来源标识、文件名、校验和及动作范围，不记录本机路径。

`--clip ID=bones:<片段>` 或 `--clip ID=nju:<CSV名>` 可指定其他片段；
片段后加 `@<起>-<止>` 可去掉该区间，单位为秒，起止应处于同一步态相位且均位于片段内。
`--hold`、`--blend` 分别调整首尾待命与过渡时长。
NPZ 使用 50 Hz：`joint_pos`、`joint_vel` 为 `[T,29]`；`body_pos_w`、
`body_quat_w`（wxyz）、`body_lin_vel_w`、`body_ang_vel_w` 仅含骨盆，`anchor_body_index: 0`。
走路、鼓掌、指向来自 BONES-SEED，闪身步和浪子踢球分别来自上游 `shanshenbu.csv`、
`langzi_tiqiu.csv`，具体片段及处理参数记录在清单中。
模型权重及动作数据遵循各自来源的许可。

交互参考使用 `scripts/prepare_interaction_references.py --motion <ID>=<轨迹.yaml>`，
每个动作提供一个 `--motion`；ID 使用上表 SONIC 一列。输入包含 `time`（秒）、
`q`（N×17，rad，左臂 7＋右臂 7＋腰 yaw/roll/pitch），可选 `hold: true` 在末帧停留 2 秒。
先准备好两套模型的默认待命参考，再生成 `policy/sonic/<ID>/` 的 CSV 与
`policy/supermimic/references/<ID>.npz`。脚本分别读取两套待命姿态，按模型要求转换关节顺序，
重算速度并校验参考角度范围；生成清单 `INTERACTIONS.json` 记录输入校验和与处理参数。

验证命令见 [策略测试](../../tests/policies/README.md)。
