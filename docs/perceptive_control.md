# Hiking 感知运控

修改 [g1.yaml](../config/g1.yaml) 对应配置，以下命令在 SDK 根目录执行。

## 仿真

```yaml
perception:
  depth:
    publish_sim: true  # 启用仿真深度端点，有订阅时才渲染
    endpoint: "tcp://127.0.0.1:5560"
    clock: sim
    timeout_s: 0.2
  clock:
    publish: false

simulation:
  mujoco:
    sim_dt: 0.001
```

```bash
bash application/native/humanoid_unitree_g1/scripts/download_models_g1.sh
output/staging/bin/run_g1.sh --sim --stairs
```

`--stairs` 的直梯每级高 16 cm；换成 `--office` 可测两次右转的办公室楼梯（每级 16.5 cm）；不指定场景时使用 YAML 中的场景。仿真深度有订阅时才渲染。

## 实机

小脑 `g1.yaml`：

```yaml
perception:
  depth:
    publish_sim: false
    endpoint: "tcp://192.168.60.1:5560"
    clock: robot
    timeout_s: 0.2
  clock:
    publish: true
    endpoint: "tcp://0.0.0.0:5561"
    receive_delay_bound_s: 0.01
```

小脑 `g1.service` 启动 driver 时自动提供 `5561` 时间锚点服务。
大脑先启动 `640×360@30` 的 RealSense 相机（`ROS_DOMAIN_ID=73`），再执行：

```bash
source /opt/ros/humble/setup.bash
python3 middleware/ros2/control/humanoid/scripts/realsense_depth_zmq.py \
  --mode control --clock-endpoint tcp://192.168.60.153:5561
```

桥接自动运行时间同步，约 5 s 后出现 `[clock] ready`，深度状态应为 `state=ready`。

## 切换策略

`DAMP → 选择“感知运控（Hiking）” → HOME → ZERO → RL`。
同属 `full_body` 的策略支持在 RL 中切换；深度历史需至少 0.7 s。

## 深度发布与订阅

仿真 driver 使用 ZMQ XPUB，control 使用 SUB 并订阅空前缀（接收全部深度帧）。
准备 Hiking 时，control 开始订阅，driver 才开始渲染；切换到其他策略且没有剩余订阅时停止。
深度查看器也算订阅者，因此查看器运行期间仍会渲染。
`publish_sim: true` 表示启用深度端点，不表示持续渲染。
未编入深度发布模块的 driver 仍可运行普通 MuJoCo 仿真。

实机由大脑桥接使用 ZMQ PUB 发布，小脑 control 通过有线网络订阅。
大脑只发送重采样后的 `64×36` 深度，小脑无需接收完整 ROS 图像。

## 相机与模型输入

使用 SDK 的 `torso_link/rgbd_camera`，相机相对躯干的位置为
`[0.0576235, 0.01753, 0.42987] m`，方向 `xyaxes` 为
`[0, -1, 0, 0.738455340625884, 0, 0.674302387583723]`。
XML 垂直视场为 54.5°，独立深度渲染模型使用 58.29°，不改变机器人安装位姿或物理模型。
实机桥接按 CameraInfo 重采样到同一投影。

control 从 `64×36` 深度中裁出底部居中的 `32×18` 区域，无效值填为 2.5 m，
经过 3×3 高斯滤波、截断到 `[0, 2.5] m` 并归一化；每隔 0.1 s 取一帧，共 8 帧交给 encoder，
再由 actor 输出 29 轴控制。策略频率为 50 Hz；实机深度按相机实际 30 FPS 发布，不复制帧补频率。
仿真物理步长为 `0.001 s`，加载后由 `simulation.mujoco.sim_dt` 统一覆盖 XML timestep。

## 消息协议

每帧为一个 ZMQ 消息，不带 topic，依次包含：

1. 4 字节小端整数：后续 JSON 头的字节数。
2. JSON 头：相机参数、采集时间、帧序号和会话等信息。
3. `64×36` 个小端 float32 深度：按行排列，单位为米，表示相机光轴方向的 Z 距离。

JSON 头的主要字段：

| 字段 | 含义 |
| --- | --- |
| `version`、`profile` | 固定为 `1`、`g1-sdk-hiking-v1`，标识协议版本和相机输入约定 |
| `width`、`height`、`dtype` | 固定为 `64`、`36`、`float32le` |
| `unit`、`distance` | 固定为 `m`、`optical_z` |
| `frame`、`fovy_deg`、`camera_pos`、`camera_xyaxes` | 对应上述 SDK 相机及 58.29° 投影，接收端会校验 |
| `clock`、`time` | 采集时刻及所属时钟域：仿真用 `sim`，实机用与机器人状态一致的 `robot` |
| `sequence`、`session` | 会话内递增的帧序号及发布会话标识；重启或时间复位时更换会话，接收端清空历史 |

接收端还检查时间递增、深度与状态时间差、到帧超时和历史完整性，默认超时为 0.2 s。
参数不能只改标签；真实安装位置和投影必须匹配。

## 实机时间映射

小脑 driver 提供 HI91 设备采样时间和主机接收时间；大脑以 10 Hz 查询，
通过四时间戳估计网络偏移，再拟合 ROS 采集时间到机器人时间的映射。
`receive_delay_bound_s: 0.01` 是 IMU 采样到接收的延迟预算，不是网络测得的绝对延迟。

映射默认最多保留 2 s，误差预算上限为 20 ms；缺失、过期或不满足限制时停止发布控制深度。
当前 Hiking 在深度超时或历史不可用时触发策略故障，进入 `SAFETY` 后卸力到 `POWER_OFF`，
不会自动切回常规站立。
