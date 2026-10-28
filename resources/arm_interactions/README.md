# 可选关节轨迹

默认配置不挂载上身接管动作。需要接入时，可在支持接管的站立策略上使用 common 的
`joint_trajectory` 适配器，并在机型 YAML 声明动作目录。

资源为 NPZ，`joint_pos` 使用 float32 的 `[帧数,关节数]` 数组，单位 rad。
每列对应 `joint_indices` 中的一项，采样率由 `motion_fps` 指定。
动作目录还可配置 `blend_in_duration`、`blend_out_duration`、`kp/kd`、
`hold_last_frame` 和 `max_hold_duration`。

动作资源、接管关节和增益须与所选策略共同验证；不要直接把一个模型的接管配置
套到另一模型。腿部持续由策略控制，轨迹完成或取消后交还被接管关节。
HMI 的动作列表来自策略引用的目录；仅把 NPZ 放在此目录不会自动启用动作。
