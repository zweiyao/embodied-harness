# Hypotheses (read-only investigation; max 15 iterations)

H1: Model/provider waiting consumes the episode before sufficient interaction; repeated tools are secondary. Test per-request and per-tool wall-time intervals across all three Qwen cohorts; find counterexamples with fast requests yet no action.
H2: Repeated perception begins when localization lacks a stable semantic target and geometry validity contract: surface point, mixed regions and camera/frame ambiguity are interpreted as action-ready poses. Test first divergence on recorded frames and replay depth/masks; disprove if coherent target and valid geometry are already available and used correctly.
H3: The transition from perception to action and from action feedback to recovery is not grounded in an explicit evidence criterion. Test repeated calls on unchanged observations and corresponding tool outputs; contrast successful/failed matched tasks, with and without memory.
H4: Tool schema/feedback or implementation defects supply wrong coordinates or ambiguous action outcomes. Test current interface plus recorded outputs against raw sensor artifacts and action logs; separate model errors from implementation errors.
H5: Experience retrieval alone causes the planning delay. Test empty-library and concise-prompt trajectories for the same delays and repeated perception.

All hypotheses start unconfirmed. No new benchmark, prompt, memory, or runtime tool changes before concrete proposal approval.

## Investigation log (completed; 6 iterations of maximum 15)

1. Census of 128 archived episodes: Qwen response waiting is substantial; original fast no-action episode disproves waiting as the sole cause. H1 retained as amplifier, not sufficient root cause.
2. Compare original/short/empty cohorts: empty-memory no-action episodes persist; exact duplicate geometry queries are rare. H5 and exact-query-cache-only remedy rejected as complete explanations. Cohorts are not controlled interventions.
3. Read initial task 4/3 decision sequences and native pi0_pick schema: target identification precedes further full-scene mapping; grasp XYZ is not required by the available learned primitive. H3 supported as a mechanism hypothesis, not yet intervention-confirmed.
4. Inspect archived task 3/4 images: task 3 late cabinet segment selects the background fixture. H2 supported for semantic referent drift; not the earliest cause in that episode. No segmentation score threshold can certify identity.
5. Verify task 4 artifact paths and tool declarations: segment_01.json is a directory with frame 00.json, not 01.json. H4 confirmed for this local interface ambiguity; all 128 episodes selected only 17 native tools.
6. Replay published sensor_patch_batch directly on task 4 archived RGB/world/depth/proprio: four selected pixels and numeric statistics/EEF offsets agree; missing high data rejected. Existing capability can be reused; no task gain inferred. Prior 615/615 projection replay narrows H4 but does not establish calibration/semantic accuracy.

Stop reason: concrete approval-ready scope prepared. Deployment or new intervention would modify memory/tool selection and requires project approval. No experimental causal conclusion claimed; no additional read-only test can establish task benefit.
