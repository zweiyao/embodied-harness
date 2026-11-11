# LIBERO 短程 EEF 控制

`move_eef` 是工作台的可选控制工具：VLM 读取图像和末端位姿，给出一个目标，
现有 OSC 控制器执行短段运动，再返回图像、实际位姿及误差供下一次决策。
工具内部不调用 Pi0，不做任务规划，也不保证无碰撞或到达目标。

在 LIBERO 工作台的工具选择中勾选 `move_eef`。选择会让本次新建的环境启用
控制器参数读取；默认工具选择不包含它，旧工具的参数和执行方式不变。
如要单独启动环境服务或连接外部环境，须在该环境启动命令中加
`--enable-eef-control`。当前适配范围是 robosuite 1.5 的单臂、固定增益、
delta OSC_POSE、基于实际位姿更新目标的控制器；实际验证使用 LIBERO-PRO。

```python
move_eef(xyz, quat_xyzw, gripper, steps=5)
```

| 参数 | 契约 |
| --- | --- |
| `xyz` | 世界坐标系中的目标 EEF 位置，3 个有限数值，单位米 |
| `quat_xyzw` | 世界坐标中的单位四元数，顺序与 `robot0_eef_quat` 一致 |
| `gripper` | 必填，`-1` 开、`+1` 闭、`0` 保留当前指令 |
| `steps` | 1–10 个环境控制步，默认 5；不是物理子步或模型请求次数 |

四元数范数允许 0.001 的舍入误差，接受后归一化。每步依据实际机器人位姿
重新计算位置和旋转误差，使用当前控制器的参考系、输入/输出缩放和动作边界。
每个平移或旋转向量整体缩放到原控制器边界内；不改变控制器增益或底层限制。
到执行步数预算即返回；环境结束或取消时提前停止。位姿已经匹配时仍发送夹爪指令。

动作结果沿用原图像反馈格式。`log.result` 包含 `steps_used`、
`final_eef_pos`、`final_eef_quat_xyzw`、`position_error_m` 和
`orientation_error_rad`。一次动作后无需再读取相同帧。
末端误差小不代表抓住物体、物体稳定或任务成功。

仅选中此工具时增加以下提示：

> Use the latest images and EEF pose to choose the next short move_eef target.
> Revise it using returned images, measured pose and object motion; EEF arrival is not task completion.

经验仍按需读取；此功能不新增或修改经验。要测试由 VLM 直接完成抓取和移动的
条件，应显式选择此控制工具及所需感知/记忆工具，并记录完整工具选择。
更多动作反馈可能增加模型调用与等待；接口验证不能证明任务成功率或 token 收益。
