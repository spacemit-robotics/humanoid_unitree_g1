# G1 验证入口

所有离线测试使用模拟设备，不打开电机或 IMU 串口。
先按依赖顺序编译 motor、imu、whole_body、rl、humanoid_common、humanoid_unitree_g1。
在 SDK 根目录执行：

```bash
cmake -S application/native/humanoid_unitree_g1/tests -B output/build/g1_tests
cmake --build output/build/g1_tests -j4
ctest --test-dir output/build/g1_tests --output-on-failure
```

| 测试 | 内容 |
| --- | --- |
| hardware_mapping | 29 轴映射、耦合表列序、镜像、正反速度与力矩转换、IMU 变换 |
| coupling_commands | 独立三角平面公式与命令五字段比较 |
| pre_rl | 失能反馈、DAMP/HOME/ZERO 过渡与策略准备、悬垂脚踝 HOME 目标范围 |
| waist_damping | 阻尼命令、串口增益量化与异常速度回归 |
| rl_entry | 观测到目标、关节范围、腕部力矩与耦合指令回归 |

耦合测试需要 `resources/kinematics/` 下配套 CSV；策略测试需要 `policy/` 下模型。
腰部测试同时加载 `g1_waist_triangles.csv`，独立计算三角平面及命令字段。
`tests/data/` 是确定性数值回归夹具，不是运行配置或机器标定参数。

```bash
python3 -B application/native/humanoid_unitree_g1/tests/test_gamepad_bindings.py
python3 -B application/native/humanoid_unitree_g1/tests/test_record_g1_calibration.py
python3 -B application/native/humanoid_unitree_g1/tests/audio/test_audio_assets.py
python3 -B -m unittest discover -s application/native/humanoid_unitree_g1/tests/launcher -p 'test_*.py'
```

[MNN 仿真](mnn/README.md) 验证模型、状态机与交接，
[启动器测试](launcher/README.md) 验证三进程生命周期和服务配置。
实机接线、机械范围与承载测试需在实际硬件上单独进行。
