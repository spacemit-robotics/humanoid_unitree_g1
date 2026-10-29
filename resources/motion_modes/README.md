# 运控模式与动作

`config/g1.yaml` 的 `policy_names` 定义六个可选模式，默认常规运控（MJLab）。
底层模型与动作资源放在 `policy/`，不随源码提交；
`download_models_g1.sh` 获取模型库中已发布的资源。

| 模式 | 模式 ID | 进入模式后的行为 | 模式内动作 |
| --- | --- | --- | --- |
| 常规运控（MJLab） | `walk_mjlab` | 零速站立，收到速度后行走 | 无 |
| 常规运控（RL Gym） | `walk_rlgym` | 零速仍踏步，收到速度后行走 | 无 |
| 站立运控 | `stand` | 零速度全身站立 | 无 |
| 舞蹈运控 | `dance_mode` | 使用 stand 站立待命 | 舞蹈、功夫、Dance 1、Packed、Jumps 1 |
| SONIC 运控 | `sonic` | 保持默认动作首帧 | Dance in da Party |
| ProtoMotions 运控 | `protomotions` | 使用 stand 站立待命 | 行走动作 |

舞蹈运控使用 `policy_actions.idle_policy: stand`。只有收到动作请求，
才后台加载对应模型并交接；动作结束或取消后回到该模式的 stand，等待下一条请求。
选模式、进入 RL、重复收到同一条请求，都不会自动开始或重复播放舞蹈。

| 动作 | 动作 ID | 执行策略 | 模型及参考资源（相对机型目录） |
| --- | --- | --- | --- |
| 舞蹈 | `dance` | `dance` | `policy/dance/dance_0605.onnx`，内置 18 秒动作 |
| 功夫 | `kungfu` | `kungfu` | `policy/kungfu/kungfu_0609.onnx`，内置 18 秒动作 |
| Dance 1 | `dance1` | `tracking` | `policy/tracking/`，配套参考 131.48 秒 |
| Packed | `packed` | `tracking_packed` | `policy/tracking_packed/`，配套参考 131.48 秒 |
| Jumps 1 | `jumps1` | `tracking_wbt_jumps1` | `policy/tracking_wbt_jumps1/`，配套参考 244.44 秒 |
| 行走动作 | `walk` | `protomotions_walk` | `policy/protomotions/`，配套参考 4.98 秒 |
| Dance in da Party | `dance_in_da_party` | `sonic` | `policy/sonic/`，配套参考 9.94 秒 |

前六项是不同模型，common 按 `policy_actions.actions.<ID>.policy` 调度；
SONIC 使用同一模型的 `sonic_actions` 参考目录。两者在客户端都采用“选模式，再触发动作”。
新增动作只需配置对应目录和资源，不在 common 中写机型名或固定动作数量。

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
