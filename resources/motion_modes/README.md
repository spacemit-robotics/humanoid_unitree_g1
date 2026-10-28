# 策略与动作

`config/g1.yaml` 注册全部策略，默认 `walk_mjlab`。界面显示中文功能名，
配置和日志使用下表 ID。权重与参考资源单独放入 `policy/`，不随源码提交；
`download_models_g1.sh` 用于获取模型库中已发布的资源。

| 功能 | 策略 ID | 模型路径（相对机型目录） | 播放方式 |
| --- | --- | --- | --- |
| 行走 · MjLab | `walk_mjlab` | `policy/walk_mjlab/policy.onnx` | 速度控制，零速站立 |
| 行走 · RLGym | `walk_rlgym` | `policy/motion/motion.onnx` | 速度控制，零速仍有步态 |
| 站立 | `stand` | `policy/stand/stand_29dof.onnx` | 零速度全身站立 |
| 动作跟踪 · 舞蹈 | `dance` | `policy/dance/dance_0605.onnx` | 先运行 stand 2 秒，再播放内置动作 |
| 动作跟踪 · 功夫 | `kungfu` | `policy/kungfu/kungfu_0609.onnx` | 先运行 stand 2 秒，再播放内置动作 |
| 动作跟踪 · Dance 1 | `tracking` | `policy/tracking/policy.onnx` | 进入后保持首帧，手动开始 |
| 动作跟踪 · Packed | `tracking_packed` | `policy/tracking_packed/policy_packed_0430.onnx` | 进入后保持首帧，手动开始 |
| 动作跟踪 · Jumps 1 | `tracking_wbt_jumps1` | `policy/tracking_wbt_jumps1/policy.onnx` | 进入后保持首帧，手动开始 |
| ProtoMotions | `protomotions` | `policy/protomotions/unified_pipeline.onnx` | 自动播放配套参考 |
| SONIC | `sonic` | `policy/sonic/sonic_release_unified.onnx` | 进入后保持默认首帧，从动作目录选择播放 |

完整路径以 YAML 为准。SONIC 的 `sonic_actions` 是同一模型下的动作目录，
添加动作时增加目录条目即可；不需要复制 SONIC 策略或修改 common。
其他独立训练模型仍按不同策略注册，不把它们伪装成同一模型的参考数据。

RL 内选择同组策略时保持控制：速度归零，后台加载目标，当前策略到达交接点后切换。
普通站走策略在零速有效推理帧交接；正在播放的定时动作等到末帧。
SONIC 会先收回到待命参考。完成的有限动作按 `return_policy` 返回 stand。
Dance 1 和 Packed 的参考长 131.48 秒，Jumps 1 长 244.44 秒；播放中切换需等待该段结束。
机型交接等待上限为 300 秒，模型加载失败或超时会报告失败并保留当前策略。
HOME/ZERO 中不切换策略，仍遵守 DAMP→HOME→ZERO→RL 的准备顺序。

输出过渡由各策略 `policy_switch.transition_duration` 配置，位置与增益同步变化。
内置定时舞蹈不叠加输出延迟，依靠前置站立策略准备；模型时间、历史观测和动作映射保持各自协议。

台阶场景启动命令为 `run_g1.sh --sim --stairs`。它仅增加仿真地形，不改变模型能力；
当前行走策略不是专门的越障模型。

验证命令见 [策略测试](../../tests/policies/README.md)。
