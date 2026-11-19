# Hiking 感知运控

Hiking 使用深度 encoder 和 actor，以 50 Hz 执行 29 轴策略。
模型路径、校验摘要、关节映射及控制增益统一配置在 [g1.yaml](../config/g1.yaml)。
当前支持 SDK MuJoCo 仿真，实机深度相机发布程序尚未接入。

## 启动与切换

完成 SDK 编译并安装 `libzmq3-dev libegl1-mesa-dev` 后，在 `spacemit_robot` 目录执行：

```bash
bash application/native/humanoid_unitree_g1/scripts/download_models_g1.sh
output/staging/bin/run_g1.sh --sim --stairs
```

楼梯每级高 16 cm；不加 `--stairs` 使用普通场景。启动保持 `POWER_OFF`，
默认模型为 `stand`。进入 `DAMP` 后选择“感知运控（Hiking）”，再依次 `HOME → ZERO → RL`。
同属 `full_body` 切换组的模型可在 RL 中直接切到 Hiking：先收零速度，等待至少
0.7 s 深度历史就绪，再按配置的 0.35 s 过渡时间交接。等待超时则保留当前模型，
终端显示等待或失败原因。建议从 `0.5 m/s` 前进速度开始手动验证。

楼梯场景 XML 与 YAML 的仿真步长均为 `0.001 s`。SDK 加载模型后以
`simulation.mujoco.sim_dt` 覆盖 `model->opt.timestep`，物理积分和仿真循环使用同一值。
策略推理和深度发布目标频率均为 50 Hz，不等于物理仿真频率。

## 相机与深度处理

相机为 [SDK 机器人模型](../resources/xml/g1_29dof_rev_1_0.xml) 的 `rgbd_camera`，
安装在 `torso_link`（躯干），位置相对该连杆为 `[0.0576235, 0.01753, 0.42987] m`，
方向 `xyaxes` 为 `[0, -1, 0, 0.738455340625884, 0, 0.674302387583723]`。
原 XML 的垂直视场角为 54.5°；深度发布器只在独立渲染模型中改为 58.29°，
不改变相机安装位姿或机器人物理模型。

准备 Hiking 时，control 订阅原始 `64×36` 深度，仿真 driver 开始渲染；切换到其他策略且无剩余订阅时停止。
未编入深度发布模块的 driver 仍可运行普通 MuJoCo 仿真。
control 将底部居中的 `32×18` 区域裁出，无效深度填为 2.5 m，经过
3×3 高斯滤波后裁剪至 `[0, 2.5] m` 并归一化；按 0.1 s 间隔取 8 帧交给 encoder。
接收器检查相机参数、帧序号、会话、时钟域、时间戳与历史完整性；默认超时为 0.2 s。

## ZMQ 接口

默认端点为 `perception.depth.endpoint: tcp://127.0.0.1:5560`。
driver 为 XPUB，control 为 SUB（订阅空前缀）；每帧是一个无 topic 的单消息：

```text
4 字节小端 uint32 JSON 长度 N | N 字节 UTF-8 JSON | 64×36 个小端 float32 深度
```

深度按图像从上到下、从左到右排列，单位为米，距离为相机光轴 Z 分量。
JSON 头字段如下，动态字段的值仅作示例：

```json
{
  "version": 1,
  "profile": "g1-sdk-hiking-v1",
  "width": 64,
  "height": 36,
  "dtype": "float32le",
  "unit": "m",
  "distance": "optical_z",
  "frame": "torso_link/rgbd_camera",
  "fovy_deg": 58.29,
  "camera_pos": [0.0576235, 0.01753, 0.42987],
  "camera_xyaxes": [0, -1, 0, 0.738455340625884, 0, 0.674302387583723],
  "clock": "sim",
  "time": 12.34,
  "sequence": 617,
  "session": "publisher-start-and-reset-id"
}
```

`time` 是采集时刻，必须与机器人状态时间同域；`sequence` 和时间在会话内递增。
重启或仿真复位后更换 `session`，接收器会清空历史。

## 验证与实机桥接

沿用 [策略测试框架](../tests/policies/README.md)，在 `spacemit_robot` 目录检查 RL 热切换：

```bash
python3 application/native/humanoid_unitree_g1/tests/policies/test_runtime.py \
  --policies hiking walk_mjlab hiking stand
```

离线模型接口测试跳过需要实时深度的 Hiking。楼梯场景使用上述启动命令手动检查
模型切换、前进、停止及上下楼梯；普通场景热切换测试不能替代楼梯通行验证。

实机需另写相机 PUB 程序，将真实深度校正、重采样到上述相机投影，并与机器人
状态对齐采集时钟。配置 `perception.depth.publish_sim: false`、`clock: robot`，
将 `endpoint` 指向发布器。安装误差、镜头视场和遮挡需重新验证，不能只修改 JSON 标签。
跨机仿真可由 driver 设置 `simulation.mujoco.depth_endpoint: tcp://*:5560`，
control 设置 `perception.depth.endpoint: tcp://仿真机地址:5560`，仍使用 `clock: sim`。
