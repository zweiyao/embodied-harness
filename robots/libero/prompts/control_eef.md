Robot: the LIBERO simulator arm and gripper. Read view_env_state for native
task_language, robot proprioception and camera images. Use recorded camera
calibration and depth for metric localization when needed.

In the opt-in move_eef interface, xyz is an absolute world-frame position in
metres; quat_xyzw is a unit quaternion in the same frame as robot0_eef_quat.
This interface uses xyzw, not RoboDojo's wxyz. gripper is -1 open, +1 close,
and 0 retains the intended command. steps is the number of environment control
steps allowed by this tool's schema; inspect the returned measured pose and RGB.

The adapter converts the world target using the active OSC controller scaling.
Do not send robot joint targets or reuse another embodiment's frame, TCP offset
or gripper convention. Only the actual selected tools are available. Native
observations and official task success remain owned by the existing environment.
The original frozen language-material prompt is a separately recorded protocol.
