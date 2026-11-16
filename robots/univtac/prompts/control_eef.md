Robot: Panda hand in the UniVTAC environment. Use the returned camera images,
metric depth, bilateral tactile images and measured robot state. Match evidence
by recorded step and compare motion/contact changes after each action.
Pixel or tactile-marker displacement is not calibrated force; missing data is
unknown. The initial tactile reference may already be loaded.

When move_eef is available, its target position is in world metres, orientation
is a unit quaternion wxyz, and gripper opening ranges from closed 0 to open 1.
Execute short targets, then inspect measured pose, object motion and contact.
Use only the selected tool schemas; do not apply another robot's TCP or axes.
Each model response counts toward the configured decision budget, including
perception and corrections. Official success is recorded separately from the
model's visual assessment.
