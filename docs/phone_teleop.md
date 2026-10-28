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
按住前后、横移或转向键发送速度，支持双指同时操作。默认慢速，快慢档自动填入
速度预设，也可手动调整；正常停车松开按键即可。页面没有独立的“停止移动”按钮，
控制权释放、故障确认和状态切换入口保留。
切后台、失联、故障和状态切换会撤销旧输入，沿用配置的速度平滑。
网络恢复后网页会自动重连，不用重新扫码；重连不会自动接管或恢复旧速度。

配置位于 [g1.yaml](../config/g1.yaml) 的 `operator_service.teleop`：

| 参数 | 前进 | 倒退 | 横移 | 转向 |
| --- | --- | --- | --- | --- |
| 慢速幅值上限 | 0.3 m/s | 0.3 m/s | 0.3 m/s | 0.5 rad/s |
| 快速幅值上限 | 0.5 m/s | 0.3 m/s | 0.3 m/s | 0.5 rad/s |
| 客户端加速度（启用时） | 1.0 m/s² | 1.0 m/s² | 1.0 m/s² | 2.0 rad/s² |
| 客户端减速度（启用时） | 2.5 m/s² | 2.5 m/s² | 0.5 m/s² | 2.5 rad/s² |

所有上限还要取当前策略 `command.limits` 的交集。例如定点站立策略的限速为零，
方向键会禁用；其他 walk 策略若限速更小，网页显示并使用较小范围。
两套行走均设 `command.limits.min_vx: -0.3`，快慢档倒退统一不超过 0.3 m/s；
该策略限幅同样覆盖手柄、横屏双摇杆和 TUI，客户端不增加额外滤波。

`walk_rlgym`、`walk_mjlab` 未关闭客户端平滑，继续使用表中的加减速度。

横屏模式提供双摇杆：左摇杆负责前后和横移，右摇杆负责转向。
发送周期为 50 ms，不等待速度回执才发送下一条指令。
界面“实际采用”显示 control 返回的指令，
不表示机器人测得的行走速度。
