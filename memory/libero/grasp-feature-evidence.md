# Ground a manual grasp in the visible feature

- id: grasp-feature-evidence
- scope: libero
- kind: perception
- title: Ground a manual grasp in the visible feature
- applies when: Considering a manual grasp of a visible narrow handle on a wider object.
- symptom: Repeated surface scans without a grasp, or open-finger descent that does not reach its target.
- evidence:
  - cells: 9cbe14f94f25bc734075; a4ad5d50d4b873066dd3
  - attempts: two failed episodes reviewed; not a successful intervention
- confidence: hypothesis; task benefit unvalidated
- related: next-action-evidence; object-relative-transfer

Label the intended grasp feature in the image before querying depth. Distinguish solid handle, handle opening, body and background; similar coordinates do not establish the same surface. If correspondence remains unclear, obtain a more informative view or a relevant segmentation rather than scanning unchanged pixels indefinitely.

A valid surface point alone does not specify a feasible end-effector pose. Manual grasping also needs evidence for approach clearance and finger orientation. Choose between a supported learned grasp and a manual approach using the current target and observed failure, not an unconditional ban inferred from an old episode.

Compare requested motion with the returned pose. A stalled open-gripper descent is not a completed grasp or evidence that an object is seated. Resolve the blocked approach before repeating it. When the feature is occluded or clearance is unknown, preserve that uncertainty instead of inventing a grasp pose.
