# 腰部与脚踝耦合标定

`g1_hardware.yaml` 使用 `table_2d` 加载四列 CSV，单位为 rad。
`g1_ankle.csv`、`g1_waist.csv` 是部署所需标定数据，单独提供、不进入源码版本控制。
腰部还需配套 `g1_waist_triangles.csv`，由 `table_triangles_file` 加载有序三角网格，
固定共享边和顶点处的选片顺序。表格和网格必须配套，缺少网格时初始化报错。
网格 SHA256 为 `62a273945fc045dac56078d68ebc954638ece72a1cc19d26f381331e378812db`。

| 表 | 输入列 | 输出列 |
| --- | --- | --- |
| 脚踝 | 电机 ID5、ID4 的规范化角度 | pitch、roll |
| 腰部 | 电机 ID0、ID1 的规范化角度 | pitch、roll |

左右脚的输入镜像和输出符号由 `polarity`、`table_output_scale` 配置。
全身关节顺序仍为腰 yaw、roll、pitch，耦合内部的 pitch/roll 顺序不能反用。
校准表、零位、极性与对应硬件应成套配置；不得用回归夹具替代校准数据。

令规范化电机位置为 `m`，虚拟关节为 `q=F(m)`，局部导数为 `A=dq/dm`：

- 速度：`dq=A dm`，目标速度反变换为 `dm_des=A^-1 dq_des`。
- 力矩：`tau_motor=A^T tau_joint`，回读使用对应的逆转置。
- 电机增益：`Km=clamp(diag(A^T diag(Kq) A),0,2000)`，阻尼上限为 25。
- 比例目标：`m_des=m+A^T[Kq(q_des-q)]/Km`，逐电机相除。
- 近零 KP 保持实测电机位置，DAMP 使用 KP=0、零目标速度和零前馈力矩。

当前配置使用 Delaunay 三角平面插值。插值有效域、非有限值与奇异雅可比检查保持启用。
`motor_projected` 在目标生成中保留两轴比例耦合，电机侧执行阻尼。
量化按串口协议向零截断；不足一个编码单位的增益可能编码为零。

`tests/test_coupling_commands.cpp` 使用独立平面公式检查命令五字段；
`tests/test_hardware_mapping.cpp` 检查列序、镜像、正反映射和雅可比。
不同插值方式的边界导数可能不同，校准表与插值配置必须一致。
