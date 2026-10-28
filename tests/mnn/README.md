# MNN 运控仿真

仿真使用与实机相同的 YAML、MNN 网络、观测构造和动作映射，
driver 后端固定为 MuJoCo，不访问电机串口。
模型、动作资源按 [运控资源接口](../../resources/motion_modes/README.md) 安装。

SDK 根目录初始化环境后运行 `run_g1.sh --sim`。TUI 中 L 接管，
O/H/Z/R 依次进入 DAMP/HOME/ZERO/RL；P 选择模式，V 打开速度页，A 打开动作列表。
Enter 启动选中动作，C 取消。台阶场景用 `run_g1.sh --sim --stairs`。

自动三进程回归会隔离共享内存、端口与日志：

```bash
python3 application/native/humanoid_unitree_g1/tests/mnn/test_runtime.py
python3 application/native/humanoid_unitree_g1/tests/mnn/test_runtime.py --gestures
python3 application/native/humanoid_unitree_g1/tests/mnn/test_runtime.py --motion-modes
python3 application/native/humanoid_unitree_g1/tests/mnn/test_runtime.py --dance-catalog
python3 application/native/humanoid_unitree_g1/tests/mnn/test_runtime.py --stairs
```

`--viewer` 打开可视化；`--logging-check` 校验日志概览与高频片段。
`--dance-catalog` 检查待命取消、律动 1–4 播放、重复取消及返回走跑，验证每次
请求都有回执、状态持续回传且无锁存故障。测试单独保留八份日志分片，生产日志配置不变。
`--check-run output/记录目录` 配合原场景参数仅复查已有日志，不启动进程。
另有 `test_mnn_sim.cpp` 在同一进程内测试策略与物理仿真，构建文件位于本目录。
结果写入 SDK 的 `output/`，不进入源码版本控制。
