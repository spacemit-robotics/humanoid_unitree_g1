# 运控配置与资源接口

模式由 `g1.yaml` 的策略目录注册；共享层不限制机型必须配置三种模式。
同一 `switch_group` 内允许 RL 状态下交接，准备失败保留当前策略。

| 模式 | 模型文件，相对于机型目录 | 输出 |
| --- | --- | --- |
| 走跑 | `policy/locomotion/stance.mnn`、`walk.mnn` | 29 维 |
| 越障 | `policy/locomotion/obstacle_stance.mnn`、`obstacle.mnn`、`obstacle_run.mnn` | 21 维 |
| 舞蹈 | `policy/motion-tracking/dance/decoder.mnn` | 29 维 |

模型必须与 YAML 的输入名、历史长度、关节索引、动作尺度、默认姿态和增益一致。
走跑的双网络共享历史，越障的三网络按速度条件选择；不通过退出 RL 来切换子网络。
越障使用速度指令、本体状态和历史观测，没有视觉或高度图输入。
`run_g1.sh --sim --stairs` 提供四级 5 cm 台阶、2 m 宽度、60 cm 踏步长的测试场景。

舞蹈参考数据为 `policy/motion-tracking/dance/standby.csv` 和 `rhythm.csv`。
潜变量、根部位置和四元数的列布局由 `history_actor` 配置解释，采样率为 50 Hz。
律动序列共 5385 帧、107.70 秒，只按下表播放选择的片段：

| 选项 | 时间范围，右端不含 | 帧范围 | 时长 |
| --- | --- | --- | --- |
| 律动 1 | 0.8–28.6 s | [40,1430) | 27.8 s |
| 律动 2 | 34.4–56.2 s | [1720,2810) | 21.8 s |
| 律动 3 | 57.2–74.2 s | [2860,3710) | 17.0 s |
| 律动 4 | 75.2–103.2 s | [3760,5160) | 28.0 s |

片段前后使用 0.5 秒潜变量过渡，完成或取消后返回待命，不自动播放下一段。
根部平移误差关闭，旋转误差使用姿态输入。片段检查工具为
`scripts/analyze_rhythm_segments.py`；完整三进程回归为
`tests/mnn/test_runtime.py --motion-modes` 和 `--dance-catalog`。

模型与参考数据单独提供，不随源码分发；取得资源后按以上相对路径安装。
