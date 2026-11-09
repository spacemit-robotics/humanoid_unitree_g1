# 运控模式与动作

`config/g1.yaml` 的 `policy_names` 定义六个可选模式，默认常规运控（LocoMode）。
底层模型与动作资源放在 `policy/`，不随源码提交；
`download_models_g1.sh` 获取模型库中已发布的资源。

| 模式 | 模式 ID | 进入模式后的行为 | 模式内动作 |
| --- | --- | --- | --- |
| 常规运控（LocoMode） | `stand` | 零速站立，收到速度后行走 | 无 |
| 常规运控（MJLab） | `walk_mjlab` | 零速站立，收到速度后行走 | 无 |
| 常规运控（RL Gym） | `walk_rlgym` | 零速仍踏步，收到速度后行走 | 无 |
| 舞蹈运控 | `dance_mode` | 使用 stand 站立待命 | 舞蹈、功夫、Dance 1、Packed、Jumps 1 |
| SONIC 运控 | `sonic` | 使用中性姿态静态参考站立，等待动作请求 | 平稳站立、行走转身、玛卡莲娜舞 |
| SONIC 运控（规划行走） | `sonic_planner` | 站立，收到速度后由规划器生成参考 | 无 |

舞蹈运控使用 `policy_actions.idle_policy: stand`。只有收到动作请求，
才后台加载对应模型并交接；动作结束或取消后回到该模式的 stand，等待下一条请求。
选模式、进入 RL、重复收到同一条请求，都不会自动开始或重复播放舞蹈。
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
| 行走转身 | `walk` | `sonic` | `policy/sonic/walking_quip_360_R_002__A428/`，9.10 秒 |
| 玛卡莲娜舞 | `macarena` | `sonic` | `policy/sonic/macarena_001__A545/`，27.50 秒 |

前五项是不同模型，common 按 `policy_actions.actions.<ID>.policy` 调度；
SONIC 使用同一模型的 `sonic_actions` 参考目录。两者在客户端都采用“选模式，再触发动作”。
新增动作只需配置对应目录和资源，不在 common 中写机型名或固定动作数量。
SONIC 的行走转身和舞蹈使用 GEAR-SONIC 的 G1 示例参考，每个目录提供
`joint_pos.csv`、`joint_vel.csv`、`body_quat.csv`，50 Hz，关节顺序保持模型顺序。
TUI 按 A 选择动作，播放期间按 C 取消回到站立；网页复用同一动作列表。
完整播放后保持末帧，可从列表再次选择平稳站立或其他动作。
手柄 RT+A/B/X 分别触发站立、行走转身、玛卡莲娜舞，均长按 1 秒。
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

RL 内选择同组模式时保持控制：速度归零，后台加载目标，当前策略到达交接点后切换。
普通站走策略在零速有效推理帧交接；定时动作播放中选择其他模式会等待末帧。
需要提前结束时先取消动作，准备好待命策略后从当前有效目标交接，位置与增益同步过渡。
SONIC 取消由自身参考过渡处理。模型加载失败保持当前控制并显示动作失败。
机型交接等待上限为 300 秒，HOME/ZERO 中不切换模式。

各执行策略的观测、历史、动作尺度与增益独立保留。
内置定时舞蹈不叠加输出过渡延迟；回待命使用 stand 的 0.5 秒目标与增益过渡。
进入模式的 ZERO 姿态也来自该模式的待命策略。

台阶场景启动命令为 `run_g1.sh --sim --stairs`。它仅增加仿真地形，不改变模型能力；
当前行走策略不是专门的越障模型。

验证命令见 [策略测试](../../tests/policies/README.md)。
