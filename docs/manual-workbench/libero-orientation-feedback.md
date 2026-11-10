# LIBERO relative world-axis rotation

Select `rotate_axis` to request a signed rotation around world `x` or `z` without supplying a quaternion. This optional tool is off by default. `angle_rad` is in radians within [-pi, pi] and follows the right-hand rule; it describes a relative orientation change, not an Euler angle target or guaranteed rotation path.

The tool retains the starting grip-site position as its feedback target and preserves the gripper command target. It uses the existing EEF controller conversion with the active controller scale and reference frame. It checks pose errors between groups of ten native control steps and stops when both existing tolerances are met or after forty steps. A target already within tolerance requires no action. The response reports actual action count, final position/orientation errors and tolerances, and normal post-action images.

Inspect those images and measured errors before proceeding. Position is a feedback target, not an exact trajectory constraint. Pose arrival does not establish collision clearance, grasp or task success. The tool does not grasp, lower, open the fingers or release; use the corresponding selected tools for separate actions.

Position feedback refers to the grip site, while the observed quaternion refers to the end-effector body. For the verified fixed body-to-site rotation, their relative global rotation residuals agree. This does not make the two observations a common-frame pose for reconstructing arbitrary gripper contact points. A different robot or gripper mounting requires validating that convention first.

Owned workbench environments selected with this tool enable the existing robot-only controller observation wrapper. Borrowed environments must already provide that feedback; unsupported controllers are rejected. Original rotation and EEF tools remain in the catalog, and each experiment records its selected interfaces. Defaults and prompts without `rotate_axis` remain unchanged.
