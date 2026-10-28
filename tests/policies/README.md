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
然后依次切换 stand、walk_mjlab、walk_rlgym、walk_mjlab。
每次交接保持 RL，检查请求完成、故障状态和切换后 5 秒运行。
测试使用独立共享内存、端口、日志目录，禁用手柄和音频，退出时仅停止自己启动的进程。

测试其他策略：

```bash
python3 -B application/native/humanoid_unitree_g1/tests/policies/test_runtime.py --policies dance stand kungfu stand tracking stand tracking_packed stand tracking_wbt_jumps1 stand sonic stand protomotions wait:6 stand
python3 -B application/native/humanoid_unitree_g1/tests/policies/test_runtime.py --policies tracking reference stand tracking_packed reference stand
python3 -B application/native/humanoid_unitree_g1/tests/policies/test_runtime.py --policies sonic action:dance_in_da_party wait:12 stand
```

`reference` 开始手动参考，`action:<ID>` 启动动作目录中的条目，`wait:<秒数>` 保持运行。
参考动作播放中请求切换会等到末帧；Dance 1/Packed 各约 131 秒，Jumps 1 约 244 秒。
因此“选择后保持首帧”和“播放完整动作”的测试耗时不同。

`--viewer` 显示仿真窗口，`--initial <ID>` 选择初始策略。
`--transition-duration <秒数>` 仅覆盖测试副本中的交接时长，用于对比；不修改机型配置。
结果及完整进程日志存于脚本打印的 `output/g1_policy_sim_*` 目录。

手动查看切换效果：

```bash
source build/envsetup.sh
run_g1.sh --sim
```

先按 DAMP→HOME→ZERO→RL 进入默认行走策略，再从策略列表选择同组策略。
MJLab 跟踪策略进入后等待参考启动，SONIC 从动作列表选择播放。
实机的机械范围、接线、IMU 安装与落地稳定性另行验收。
