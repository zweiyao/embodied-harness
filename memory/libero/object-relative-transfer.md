# Separate object evidence from end-effector geometry

- id: object-relative-transfer
- scope: libero
- kind: perception
- title: Separate object evidence from end-effector geometry
- applies when: Grasping and transferring a visible object with LIBERO manipulation primitives.
- symptom: Repeated alignment, uncertain grasp, or an end effector above a goal without completed placement.
- evidence:
  - cells: d50624cbffb925e23222; a36a0500616f1edae655; libero10-task-no-memory-dual-20-20261107/qwen/task2/seed0
  - attempts: historical trajectory review
- confidence: hypothesis; task benefit unvalidated
- related: next-action-evidence

Check target identity and holding evidence separately from a pick heuristic. For an open container, measure its visible inner rim and a visible point on the held object; compare the object with the opening, accounting for its offset from the end effector. Batch related measurements when available. A surface point is not a grasp pose, a point inside the rim is not full-object clearance, and placement is not official task success. Compare requested motion with observed change; when progress stalls, identify the blocker before repeating it.

Occlusion, uncertain correspondence or changed geometry makes the relation unknown. Re-observe the missing fact; do not invent hidden boundaries or infer holding from gripper state alone.
