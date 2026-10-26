# 启动器与服务验证

`run_g1.sh` 管理 driver、control、HMI 的启动顺序和就绪通知。
实机默认不打开 TUI，可用独立终端连接；仿真默认打开 TUI。
正常退出和异常核心进程退出分别处理，可选音频/手柄进程退出不关闭核心进程。

`install_g1_service.py --help` 列出安装参数。`--dry-run` 打印服务配置而不修改系统。
安装完成后可以使用 `systemctl status g1.service` 和
`journalctl -u g1.service -n 50 --no-pager` 查看服务状态。
服务启动后保持 POWER_OFF；异常重启不会自动恢复 RL。

`--headless` 是显式的系统配置选项，会关闭桌面并配置 CPU/IRQ 分区。
安装器保存被修改的服务状态，保留网络和 ALSA 音频。
`configure_g1_realtime.py` 在服务启动前检查调度配置；动态抢占内核需支持 full 模式。
实时线程、推理和后台工作分别由 YAML 配置，不能只提高优先级而忽略 IRQ 与 CPU 亲和性。

离线测试覆盖模板生成、权限边界、实时配置及启动超时重试：

```bash
python3 -B -m unittest discover -s tests/launcher -p 'test_*.py'
```

在 SDK 根目录执行 `python3 application/native/humanoid_unitree_g1/tests/launcher/test_launcher.py --help`
查看完整三进程验证入口。该工具使用 MuJoCo 和独立日志目录，不操作硬件。
