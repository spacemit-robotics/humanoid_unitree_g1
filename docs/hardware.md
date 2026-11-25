# G1 硬件接入

硬件配置位于 `config/g1_hardware.yaml`，由 `config/g1.yaml` 引用。
控制和 driver 周期为 2 ms，策略推理周期为 20 ms。
首次校准、修改接线或更换模型后的验证应使用可靠支撑。

## 总线与设备

串口使用 6 Mbaud，五路分别为腰部、左右臂、左右腿，共 29 轴。
默认使用 `/dev/g1/{waist,arm_right,arm_left,leg_left,leg_right,imu}`。设备名按 USB 转换器
序列号和接口号确定，与 `ttyUSB*` 的枚举顺序无关。五路电机串口使用 1 ms 延迟，IMU 不设置该参数。

### 更换运控板

1. 在原板 SDK 根目录，用本版本安装脚本导出已核对的接线（只读，无需 sudo）：
   `python3 application/native/humanoid_unitree_g1/scripts/install_g1_service.py --export-serial-map > g1-ports.json`。
   保存这份文件，随机器人迁移，不提交到公共仓库。
2. 新板按 README 编译 SDK、准备策略和本机标定，把同一套转换器按原接线接好。将 JSON 复制到新板 SDK 根目录。
   在运控服务停止时运行：
   `sudo python3 output/staging/bin/install_g1_service.py --user "$USER" --serial-map g1-ports.json`。
   网页入口和可选的无桌面配置仍使用原安装参数。此命令启用下次开机自启，不启动电机、不重绑 USB。
3. 下次开机后（或服务停止时重新插入转换器），在 POWER_OFF 下运行
   `python3 output/staging/bin/install_g1_service.py --check-serial-map g1-ports.json`。
   它逐项核对六个设备名和五路电机的延迟，不打开串口。首次使能前还需核实实物接线和反馈归属。

没有旧板或更换过转换器时，按实物接线填写 JSON：六个键就是上面的角色名，值为
`"转换器序列号/两位接口号"`（例如 `"ADAPTER_A/00"`）。用 `ls -l /dev/serial/by-id/` 找到设备，
用 `udevadm info -q property -n /dev/ttyUSB0` 查看该口的 `ID_SERIAL_SHORT` 和 `ID_USB_INTERFACE_NUM`。
不要按数字编号猜测肢体归属。若连电机到多口转换器的接线也有变化，必须重新核对映射。

安装器生成 `/etc/udev/rules.d/98-g1-sdk-roles.rules`，重新插入时仍会按同一映射命名并设置延迟。
新板不需要安装旧的 `g1-serial-order.service`。自行管理串口的部署也可以在硬件 YAML 中指定稳定路径，
首次安装使用 `--external-serial`，由部署方负责权限及延迟设置。

## 腰踝标定

普通关节发送位置、速度、前馈力矩和 KP/KD，由电机执行 PD。
左右踝 pitch/roll 和腰 pitch/roll 使用 `table_2d` 标定映射、
`motor_projected` 比例项投影以及电机侧阻尼。
部署前需提供配套的标定表和腰部三角网格，文件格式与路径见
[耦合标定](../resources/kinematics/README.md)。

## IMU 安装

默认配置对应 IMU 刚性固定在骨盆前侧，传感器 X 朝上、Y 朝左、Z 朝后；
`mounting_matrix` 转换为机器人 X 前、Y 左、Z 上。
如果改变安装方向或移到活动连杆上，必须同步修改安装变换与关节链配置。

## 反馈与故障

通信异常在配置的有限容错窗口内保留有效目标，超出窗口进入故障处理。
电机主动故障、非有限值或无效机构映射按对应故障处理，不延用过期目标。
串口帧量化、指令范围和反馈检查分别由驱动、whole_body 与机型配置负责。
