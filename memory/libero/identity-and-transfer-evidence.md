# Keep object identity and transfer evidence consistent

- id: identity-and-transfer-evidence
- scope: libero
- kind: perception
- title: Keep object identity and transfer evidence consistent
- applies when: Selecting among similar objects or moving a visibly held object toward a goal.
- symptom: Checking the wrong object, changing the meaning of left/right, or confusing object-to-goal displacement with object-to-EEF offset.
- evidence:
  - cells: qwen-flash-eef-screen3-20261109/task4/seed0; qwen-flash-eef-screen3-20261109/task8/seed0
  - attempts: failed-trajectory review; task 8 benchmark has a language/goal inconsistency; only object-correspondence evidence used here
- confidence: mechanism supported; intervention benefit unvalidated
- related: next-action-evidence; grasp-feature-evidence

Keep the task's established viewpoint and the same object identity through selection, action and verification; robot axes do not rename the target. Verify the object actually acted on. After camera or object motion, locate the feature again; old pixels are not a track.

For a confirmed held object with unchanged orientation, align its visible point with the goal using the measured object-to-goal displacement. If available, use the tool's composed EEF target instead of treating that displacement as a grasp offset. Check returned images before lowering or releasing. Uncertain identity, occlusion, slipping or rotation invalidates this relation.

A motion returning at its target does not prove that the gripper closed. Check actual finger change and object motion; command execution, finger closure and holding are different claims.
