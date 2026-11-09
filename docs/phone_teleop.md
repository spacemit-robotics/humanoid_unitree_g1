# G1 手机遥控

默认只监听 `127.0.0.1`。手机与机器人处于同一局域网时，在 SDK 根目录启动：

```bash
source build/envsetup.sh
run_g1.sh --real --listen ROBOT_LAN_IP --public-url http://ROBOT_LAN_IP:8766
```

将两处 `ROBOT_LAN_IP` 替换为机器人实际局域网地址。扫码访问启动时输出的配对入口，
接管控制权后再操作；不要把这个服务映射到公网。
若使用开机服务，安装时也传入同样的 `--listen` 和 `--public-url`，例如：

```bash
sudo python3 output/staging/bin/install_g1_service.py --sdk-root "$PWD" --user "$USER" --listen ROBOT_LAN_IP --public-url http://ROBOT_LAN_IP:8766
```

安装器只启用下次开机自启动，不立即启动硬件；服务已运行时不要另开一套启动进程。

Web 与 Android App 共用 `humanoid_common` 的方向按键网页。接管并进入 RL 后，
按住前后、横移或转向键发送速度，支持双指同时操作。切换模式时自动填入该模式的
速度预设，也可手动调整；两档模式默认慢速，LocoMode 为单档、不显示快慢档按钮。
正常停车松开按键即可。页面没有独立的“停止移动”按钮，
控制权释放、故障确认和状态切换入口保留。
切后台、失联、故障和状态切换会撤销旧输入，沿用配置的速度平滑。
网络恢复后网页会自动重连，不用重新扫码；重连不会自动接管或恢复旧速度。

先从模式列表选择“舞蹈运控”，机器人保持站立；再从动作列表点击具体舞蹈。
动作结束或取消后仍停留在舞蹈运控、等待下次触发。SONIC 运控从动作列表触发
平稳站立、行走转身、玛卡莲娜舞，进入模式时保持站立，
SONIC 规划行走通过方向键或双摇杆给规划器发送速度。ProtoMotions 暂不显示。

各模式速度位于 [g1.yaml](../config/g1.yaml) 的策略 `command.limits` 与
`command.teleop`；未配置策略预设时使用 `operator_service.teleop`。
手柄满幅、网页默认按键及双摇杆满幅对应以下指令速度：

| 运控模式 | 慢速前进 | 快速前进 | 倒退 | 横移 | 转向 |
| --- | --- | --- | --- | --- | --- |
| 常规运控（LocoMode） | 单档 0.7 m/s | — | 0.4 m/s | 0.4 m/s | 1.57 rad/s |
| 常规运控（RL Gym） | 0.6 m/s | 0.8 m/s | 0.6 m/s | 0.5 m/s | 1.57 rad/s |
| 常规运控（MJLab） | 0.6 m/s | 1.0 m/s | 0.5 m/s | 0.5 m/s | 1.0 rad/s |
| SONIC 规划行走 | 0.6 m/s | 0.8 m/s | 0.3 m/s | 0.3 m/s | 0.5 rad/s |

常规运控的配置依据为 [LocoMode cmd_range](https://github.com/ccrpRepo/RoboMimic_Deploy/blob/master/policy/loco_mode/config/LocoMode.yaml)、
[RL Gym max_cmd](https://github.com/unitreerobotics/unitree_rl_gym/blob/main/deploy/deploy_real/configs/g1.yaml) 和
[MJLab 模型配套部署配置](https://github.com/unitreerobotics/unitree_rl_mjlab/blob/1425b15f73bd4095f0df53709d7c389c3eb9e790/deploy/robots/g1/config/policy/velocity/v0/params/deploy.yaml)。
快档只增加前进速度；RL Gym 两档倒退均采用慢档前进的 0.6 m/s。
表中数值是下发指令，不是实测极限速度。

平滑参数保持在 `operator_service.teleop`：

| 参数 | 前进 | 倒退 | 横移 | 转向 |
| --- | --- | --- | --- | --- |
| 客户端加速度（启用时） | 1.0 m/s² | 1.0 m/s² | 1.0 m/s² | 2.0 rad/s² |
| 客户端减速度（启用时） | 2.5 m/s² | 2.5 m/s² | 0.5 m/s² | 2.5 rad/s² |

三套常规运控和 SONIC 规划行走接收速度，
舞蹈与 SONIC 参考动作播放的限速为零，方向键禁用。
`stand` 对应 LocoMode 站走模型，不是仅站立模式。
各策略限幅同样覆盖手柄、横屏双摇杆和 TUI，客户端不增加额外滤波。

三套常规运控和 SONIC 规划行走均使用表中的加减速度。

横屏模式提供双摇杆：左摇杆负责前后和横移，右摇杆负责转向。
发送周期为 50 ms，不等待速度回执才发送下一条指令。
界面“实际采用”显示 control 返回的指令，
不表示机器人测得的行走速度。
