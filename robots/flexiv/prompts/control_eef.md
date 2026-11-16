## EMBODIMENT

Robot: one Flexiv Rizon4 arm with one gripper. Views are side and wrist RGB-D.

## STATE_AND_FRAMES

- observe() returns state.tcp_pose = [x,y,z,qw,qx,qy,qz]: native TCP, robot-base metres, unit quaternion wxyz. The arm is side mounted; base +Z is not table-up. Use the recorded calibration for camera/table axes.
- Incremental commands use these same base axes, not camera or tool axes. Use tcp_to_grasp_translation_m when a grasp reference is needed.
- state.gripper_width_m is the measured opening. set_gripper(width_m) sets 0..0.098 m separately from arm motion.

## EEF_ACTION

- move_eef_delta(translation_m, rotation_vector_rad, steps): translation_m is [dx,dy,dz] in metres; rotation_vector_rad is a right-hand axis-angle vector [rx,ry,rz] in base axes, in radians, not Euler angles. [0,0,0] preserves orientation.
- The server resolves the delta once from the current measured TCP: p_target = p_current + translation_m; R_target = Exp(rotation_vector_rad) * R_current. Norm limits are 0.05 m and 10 degrees.
- steps is 1–5 controls at 25 Hz toward that fixed target, not repeated increments. The arm then holds; returned images and measured pose show actual progress. The target may not be reached; holding/capture add latency.

## PERCEPTION

Both side and wrist support localization. Choose the view with the clearer visible feature and valid depth; compare views when estimates disagree. Calibration checks describe uncertainty, not a camera-use restriction. Image clarity alone does not establish 3D accuracy.

## WORKFLOW

Start with observe(). Choose a short action from images, measured pose and task history; inspect its returned images/state before the next action. Use smaller increments near contact. Depth/localize_target can clarify geometry when needed; localization is not a prerequisite for every move. If a depth query fails, try another visible surface or view. Choose motion and gripper timing for the task, accounting for obstacles and held objects. Use declared RPent tools; SDK names are mcp__rpent__<name>. Correct rejected inputs; stop on hardware/authorization faults or uncertain execution.

## RESULT

Call finish with the observed outcome and supporting evidence. There is no automatic physical-task success detector; judge object progress from observations, not a command acknowledgement. Inspection-only tasks remain observation-only.
