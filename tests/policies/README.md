# 策略与动态切换测试

需要先构建 RL、MuJoCo、humanoid_common 和本机型，并下载 YAML 引用的模型及参考文件。
下面命令均在 SDK 根目录执行，不连接实际电机或 IMU。

## 模型接口

```bash
cmake -S application/native/humanoid_unitree_g1/tests/policies -B output/build/g1_policy_tests
cmake --build output/build/g1_policy_tests -j4
output/build/g1_policy_tests/test_policy_catalog application/native/humanoid_unitree_g1/config/g1.yaml
```

逐个加载配置中的 ONNX，按各自的观测、动作映射和参考协议推理，检查维度和有限数值。
该测试不包含物理仿真。

## 三进程仿真

```bash
python3 -B application/native/humanoid_unitree_g1/tests/policies/test_runtime.py
```

启动独立的 driver、control、operator，自动完成 DAMP→HOME→ZERO→RL，
默认进入常规运控（LocoMode），零速度站立，非零速度行走。
然后依次切换 stand、walk_mjlab、walk_rlgym、walk_mjlab。
每次交接保持 RL，检查请求完成、故障状态和切换后 5 秒运行。
测试使用独立共享内存、端口、日志目录，禁用手柄和音频，退出时仅停止自己启动的进程。

测试其他策略：

```bash
python3 -B application/native/humanoid_unitree_g1/tests/policies/test_runtime.py --initial dance_mode --policies idle wait:20 idle action:dance finished action:kungfu finished
python3 -B application/native/humanoid_unitree_g1/tests/policies/test_runtime.py --policies dance_mode idle action:dance1 finished action:packed finished action:jumps1 finished
python3 -B application/native/humanoid_unitree_g1/tests/policies/test_runtime.py --policies dance_mode action:dance1 cancel finished sonic idle action:standing finished
```

`action:<ID>` 触发模式内动作；`idle` 检查进入模式后不自动播放；`finished` 等待
动作结束并检查仍在原模式；`cancel` 取消动作；`wait:<秒数>` 保持运行。
Dance 1/Packed 各约 131 秒，Jumps 1 约 244 秒，完整播放回归需要等待相应时长。

行走、停止和舞蹈待命交接：

```bash
python3 -B application/native/humanoid_unitree_g1/tests/policies/test_runtime.py --policies velocity:0.3,0,0,5 velocity:-0.3,0,0,5 velocity:0,0.3,0,5 velocity:0,-0.3,0,5 velocity:0,0,0.5,5 velocity:0,0,-0.5,5 wait:20
python3 -B application/native/humanoid_unitree_g1/tests/policies/test_runtime.py --policies velocity:0.3,0,0,5 dance_mode idle wait:20 action:dance1 wait:10 cancel finished stand idle
```

`velocity:vx,vy,wz,秒数` 持续发送速度，检查实际位移或转角方向，然后归零并观察 3 秒。
`MOTION` 行给出机器人实际运动；`simulation_state.csv` 记录位置、姿态和速度。
LocoMode 在 0.2 m/s 前进指令下可能仅调整平衡姿态，0.3 m/s 可用于检查起步。

进入舞蹈模式不会自动开始动作。旧 `dance` 的完整播放仍存在仿真失稳，
不要把模式切入或模型接口测试通过当作这个动作的落地验收。

`--viewer` 显示仿真窗口，`--initial <ID>` 选择初始策略。
`--transition-duration <秒数>` 仅覆盖测试副本中的交接时长，用于对比；不修改机型配置。
`--idle-policy <策略 ID>` 仅替换测试副本的动作模式待命策略，用于交接对比。
`--policy-trace` 记录逐帧观测、动作及关节目标，用于与模型配套控制计算对照。
结果及完整进程日志存于脚本打印的 `output/g1_policy_sim_*` 目录。

手动查看切换效果：

```bash
source build/envsetup.sh
run_g1.sh --sim
```

先按 DAMP→HOME→ZERO→RL 进入默认常规运控，再选择同组模式。
舞蹈运控进入后站立待命，TUI 主页面按 A 打开动作列表，再选择开始；网页从动作列表触发。
实机的机械范围、接线、IMU 安装与落地稳定性另行验收。
