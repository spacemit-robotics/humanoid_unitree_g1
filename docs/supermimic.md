# SuperMimic 运控

`supermimic_mode` 使用 SuperMimic-Repro-Sim2Real 的 `e13i_0291000` 跟踪策略。
进入模式后保持待命参考；选择动作只替换参考输入，保留同一模型实例、观测历史和上一帧输出。
模式内动作沿用 SDK 的动作列表及取消接口，不另设控制通道。

## 模式与动作

| 动作 | 动作 ID | 参考文件 | 时长 |
| --- | --- | --- | --- |
| 待命 | `sm_standby` | `references/standby.npz` | 静态保持 |
| 走路 | `sm_walk` | `references/walk.npz` | 10.3 s |
| 鼓掌 | `sm_clap` | `references/clap.npz` | 17.0 s |
| 指向 | `sm_point` | `references/point.npz` | 10.7 s |
| 闪身步 | `sm_dance` | `references/dance.npz` | 11.2 s |

文件位于 `policy/supermimic/`，配置见 `config/g1.yaml` 的 `supermimic_actions`。
待命参考使用策略的默认关节姿态、直立骨盆和由 MJCF 脚底接触点确定的高度。
每段动作首尾包含 0.5 s 待命和 1.5 s 过渡，完整播放后保持末帧。
走路片段向前约 2.7 m；闪身步包含小幅跳跃，操作前应留出活动空间。

| 操作 | 方式 |
| --- | --- |
| 选择模式 | 手柄 LT + ← 长按 1 秒；TUI、网页从模式列表选择 |
| 开始动作 | 手柄 RT + A/B/X/Y 长按 1 秒，对应走路／鼓掌／指向／闪身步；TUI 按 A 打开动作列表 |
| 取消动作 | 手柄 RT 单独长按 1 秒；TUI 按 C；网页点击取消 |

取消及模式交接会从当前参考过渡回待命，而非等整段动作播完。
播放中的原动作在过渡期间继续推进并逐渐减弱，避免突然冻结正在运动的关节。
目录的 `transition_duration` 设为 1 s；单个动作可用 `cancel_transition_duration` 覆盖返回时长。
闪身步配置为 2 s，其他动作保持 1 s。过渡期间显示退出阶段，完成后才允许下一个动作或模式接管。
取消动作不是急停，不会立即失能电机。

## 模型接口

| 项 | 内容 |
| --- | --- |
| `obs_hist` | 10 帧 × 93：q−q0、dq、gyro、重力投影、上一帧原始 action；按项排列，旧帧在前 |
| `goal` | 10 帧 × 68：参考 q−q0、dq、骨盆重力投影、骨盆系角速度、航向系线速度、骨盆高度 |
| `actions` | 29 维；q_target = q0 + action_scale · action |
| 参考时序 | 播放时输入未来第 1–10 拍，即提前 20–200 ms；待命和播放结束后保持静态参考 |
| 控制频率 | 50 Hz，`infer_decimation: 1` |
| 关节顺序 | `robot_base.joint_names` 的 29 轴顺序 |
| 增益、默认姿态、动作尺度 | 发布包 `deploy_config.json` |
| 推理运行配置 | 复用 `g1_cpu_runtime`，与其他 CPU 策略一致 |
| 目标限位 | `target_position_lower/upper`；越界目标截幅后继续控制 |

发布包的 `obs`、`goal`、`action` 由准备脚本改名为 SDK 需要的
`obs_hist`、`goal`、`actions`，不改变网络计算。

## 资源准备

模型与动作单独提供。当前配置的 SuperMimic 资源需用准备脚本生成：

1. 下载并解压 `e13i_0291000`，目录内应有 `policy_ir9.onnx` 和 `deploy_config.json`。
2. 准备 ProtoMotions 的 `g1_bones_seed_mini.pt` 和上游 `motions/custom_dance/`。
3. 在机型目录执行：

```bash
python3 scripts/prepare_supermimic_assets.py \
    --bundle <e13i_0291000目录> \
    --bones-library <g1_bones_seed_mini.pt> \
    --nju-motions <上游目录>/motions/custom_dance
```

依赖 numpy、PyYAML、onnx、onnxruntime、torch 和 mujoco。
脚本检查 YAML 与模型参数一致、改名后推理结果相同，并生成
`policy.onnx`、`deploy_config.json`、`references/*.npz` 和 `SOURCES.json`。
清单保留来源标识、文件名、校验和及动作范围，不记录本机路径。

`--clip ID=bones:<片段>` 或 `--clip ID=nju:<CSV名>` 可指定其他片段。
片段后加 `@<起>-<止>` 可去掉该区间，单位为秒，起止应处于同一步态相位且均位于片段内。
`--hold` 和 `--blend` 调整首尾的待命与过渡时长。

NPZ 使用 50 Hz：`joint_pos`、`joint_vel` 为 `[T,29]`；`body_pos_w`、
`body_quat_w`（wxyz）、`body_lin_vel_w`、`body_ang_vel_w` 仅含骨盆，`anchor_body_index: 0`。
走路、鼓掌、指向来自 BONES-SEED；闪身步来自上游 `shanshenbu.csv`，具体片段及处理参数记录在清单中。

## 验证与使用范围

离线接口、完整播放、取消及模式交接的测试入口见 [策略测试](../tests/policies/README.md)。
该模式需要单独完成实机增益、动作中断及站稳验证；仿真中出现中断后持续迈步时，不应直接落地测试。
模型权重及动作数据遵循各自来源的许可；代码许可不替代模型与数据许可。
