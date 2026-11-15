# RoboDojo GPT EEF control

Select `move_eef` explicitly in the RoboDojo dev workbench. It is the only
motion tool in this mode; `move_to`, `set_gripper`, `pi0_pick`, `stabilize`, and
`place_in_bin` cannot be selected alongside it. Default toolkits and prompts
retain their original behavior. This mode is unavailable in `eval-fair` replay.

Read `view_env_state` first. A `move_eef` call contains the latest recorded
`observation_step`, explicit `left` and `right` targets, and `steps` from 1 to 5.
Each target contains `position` in environment-origin meters,
`quaternion_wxyz` as a unit quaternion, and boolean `gripper_closed`.
The reference is the native X5 **link6**, not a contact point between fingers.
Keep a stationary arm at its measured pose with its intended gripper command.
Native gripper opening is a controller command, not measured finger gap or
proof of a grasp; `true` commands opening 0, `false` commands opening 1.

Targets must remain within 0.05 m and 0.35 rad of the current measured poses.
Robot-only URDF FK must agree with measured poses before execution. The local
damped least-squares controller limits each update to 0.02 m / 0.1 rad in task
space and 0.05 rad per joint, respecting native soft joint limits. It recomputes
from real feedback after each control ACK, without CuRobo or physics previews.
Actual tracking can differ from the target; inspect final measured poses and
RGB rather than treating command acceptance as arrival or task success.

Each short action returns fresh three-camera RGB, robot state, executed native
steps and error diagnostics through the existing artifact pipeline. Stale
`observation_step` calls execute no motion, preventing queued actions based on
one old observation. Choose the next action only after receiving feedback.
Native environment success remains the runner's final verdict, not a planner
tool. Episode budgets and read-only memory come from the selected run profile.

The robot-only FK/DLS implementation is adapted from
[GPT-as-Policy, fixed revision](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo_server/kinematics.py),
under the [retained MIT license](../../LICENSES/GPT-as-Policy-MIT.txt).
This aligns the EEF control contract; it does not reproduce that project's
complete harness or evaluation protocol.

## 中文说明

在 dev 工作台显式选择 `move_eef`，它是本模式唯一动作工具；Pi、原移动、夹爪及
搬放工具不能混选。默认工具和提示保持原样，eval-fair 回放不启用本模式。
先读取三路图像和本体状态，再给出双臂 link6 在环境原点坐标中的绝对位置（米）、
单位 wxyz 四元数和预期夹爪开合。每次执行 1–5 个原生控制步，收到新观测后再决策；
旧 observation_step 不产生动作。夹爪原生开度是控制器命令，不是实测指间距或抓稳证明。

局部 DLS 使用机器人 URDF 和实测关节，每个真实 ACK 后重算，不调用 CuRobo，也不
预演未来物理或使用物体真值。上述位置、角度、关节及软限位约束均在执行前校验，
运动学与实测位姿不符则拒绝执行。每次返回新图像、位姿、实际步数和误差；命令发送
成功不代表到达、接触或任务成功。预算和只读经验沿用运行配置，最终成绩由环境判定。
