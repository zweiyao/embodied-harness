# Resolve evidence for the next primitive

- id: next-action-evidence
- scope: libero
- kind: planning
- title: Resolve evidence for the next primitive
- applies when: LIBERO offers a learned pick primitive and localization continues before manipulation.
- symptom: Repeated geometry queries on an unchanged scene without starting an action.
- evidence:
  - cells: libero10-task-no-memory-dual-20-20261107/qwen/task4/seed0; libero10-task-no-memory-dual-20-20261107/qwen/task3/seed0; e0994d4389f86809f327
  - attempts: historical trajectory review
- confidence: hypothesis; task benefit unvalidated
- related: object-relative-transfer

Choose the next primitive before measuring. Query only a fact whose answer could change that action. A learned pick needs an unambiguous target description, not a manually reconstructed grasp pose. If identity and access are sufficiently supported, try the primitive and inspect its feedback. Resolve a specific ambiguity when they are not. Defer later placement geometry until needed; reuse geometry only while its object and scene relation remain unchanged.

Fails when the primitive cannot reach the target, the target is ambiguous or occluded, or relevant geometry has changed. Earlier action alone does not establish success.
