# Recorded coordinate and image-presentation audit — 2026-11-10

The traces support **two different failure classes**, plus a confirmed presentation inconsistency. Iteration04 task4 violated the normalized-point/array contract. Other misplaced samples often selected the wrong surface or treated a visible object surface as a functional region. They do not establish a universal row/column swap, 0–1000 convention, incorrect camera map, or incorrectly implemented normalization. The planner nevertheless receives a mirrored policy thumbnail beside calibrated geometry views, without an explicit ordered image map. This is a testable presentation risk, not a demonstrated explanation of every failure.

Scope: read-only existing iteration03–05 task4/a and task0/b traces, source and images. No API requests, simulator construction/actions, source/config edits, or new experiment. [audit_recorded.py](audit_recorded.py) was executed remotely against recorded files only; [recorded-audit.json](recorded-audit.json) contains reproducible small metadata. Temporary review images remained outside Git.

## Actual producer → recording → planner path

1. Installed RLinf `envs/sim/libero/utils.py:89–90` creates the VLA external image as raw `agentview_image[::-1, ::-1]`, a 180-degree rotation. Its wrist helper does the same. `libero_env.py:753–790` places these in `main_images` and `wrist_images`.
2. Frozen `robots/libero/tools.py:1027` saves `main_images` unchanged as `agentview_policy.png`. The calibrated low external image is raw `agentview_image[::-1]`; calibrated low wrist is raw wrist `[::-1]`. High external/wrist rendering is likewise vertically flipped and paired with correspondingly oriented depth/world maps. Relative to the calibrated external view, the policy external view is therefore horizontally mirrored.
3. This is not only a current-source inference: **all47 recorded frame pairs** across the six runs have exact pixel equality between policy image and horizontal reflection of calibrated low external image. For both initial tasks, high images reduced to256 pixels match their calibrated low counterparts best without reflection: external mean absolute error1.01/1.43 versus horizontal reflection26.94/37.48; wrist0.54/0.96 versus13.44/12.67. These are orientation checks, not calibration-accuracy or semantic tests.
4. `tools.py:view_env_state` embeds policy first, then calibrated high external, then calibrated high wrist. The first image-bearing actual model request in each run contains the exact PNG artifacts in that order: **256×256 policy,1024×1024 external,1024×1024 wrist**. The API adapter (`rpent/planner/api_loop.py:483–493`) sends result text followed by binary images in order; no per-image caption is inserted. Recorded binary identifiers/vendor metadata are null. The result text lists sorted artifact filenames, not an ordered mapping from attached image to camera/orientation.
5. The same mixed presentation occurs after actions: `LiberoToolkit.get_env_state` records state then calls the same `view_env_state`; `Toolkit.call` appends these observed images to action feedback. Fixing only the explicit observation tool would leave the action-feedback path inconsistent.

Warnings already exist. The guide says policy orientation may differ and must not be treated as calibrated geometry. The generated patch/container descriptions explicitly say never use mirrored policy images. `back_project` states row0=top, column0=left and default high1024. Camera metadata also warns against policy pixels, but it is a separate artifact rather than a per-image caption. Thus this is **mixed presentation despite textual warnings**, not an absence-of-warning claim.

The installed producer hashes are recorded as inspected now. Historical mirroring is independently proved by the47 saved image pairs; we do not reconstruct uncaptured historical process configuration.

## Coordinate contracts and implementation checks

| Tool | Actual contract | Checked behavior |
| --- | --- | --- |
| `back_project` | Integer `row,col` or row/column windows; high image by default; explicit camera/resolution | Frozen03–05 source indexes the selected world map as `[row,col]`; no automatic1000-scale conversion or axis swap. |
| Old `sensor_patch_batch` | Each point is exactly two numbers in0–1, normalized `[row/(H−1),col/(W−1)]`; calibrated high image | All19 dispatched calls and98 returned points exactly match `round(p[0]*(H−1)), round(p[1]*(W−1))`. This verifies conversion, not point identity. |
| Old `sensor_container_geometry` | Integer `[row,col]` samples in calibrated high image | No claim that co-planarity or a numeric result proves these are opening-boundary points. |
| P preview/align | Integer pixel geometry with explicit scene references | Not invoked in05; no grounding performance inference is available. |

All frozen03–05 `robots/libero/tools.py` hashes agree. The patch declaration and implementation agree. A hypothetical1000→1024 adjustment moves a coordinate by at most about24 pixels and cannot explain many samples far from the requested surface; these records contain no evidence of a consistent implicit1000-scale convention. The exact1024-sized image bytes are recorded, but provider-internal visual resizing is not observable from these traces and is not assumed.

## Cases and counterexamples

| Evidence | Observation and causal limit |
| --- | --- |
|03a request13 | Native points `[672,68]` on the left plate and `[495,705]` on the held yellow/white mug are visually correct. A global row/column swap would invalidate these. Both locations were confirmed in the prior image review. |
|03a requests16/18 | Correctly converted normalized samples mix table, mug, robot/finger surfaces. The subsequent use of EEF XY as object alignment is a separate geometric reasoning error. A valid coordinate representation does not confer the intended semantic role. |
|03b requests5/10/19/20 | Samples cover basket inner/outer walls, parts of rim and nearby table; a basket-wide mask or coordinate-format repair does not turn them into a complete opening boundary. Several individual samples are on real basket features, so this is not uniformly the wrong object or camera. |
|03b request18→19 | Wrist samples return a numerical plane result; the model explicitly rejects it as table and switches views. Preserve this counterexample to blanket “model accepts every numeric geometry result.” |
|04a requests5/6 | Actual `[658,74]`-style integer pixels were submitted to the0–1 patch schema. After explicit validation feedback the retry had three-element arrays containing a tab string. Neither entered implementation. This is a definite model contract failure, independent of where those pixels would land. |
|04b request6→8 | Early normalized rows0.14–0.18 point into upper background; after explicitly reading the high image the model uses rows0.82–0.86 and obtains cheese surface measurements. A vertical inversion approximately moves the first group toward the object, but the verified policy/calibrated difference is horizontal, so policy mirroring alone does not explain this error. Later calls already use the correct orientation. |
|04b request9 | Claimed basket-rim rows760–900 fall mainly on low wall/table. Horizontal mirroring cannot repair incorrect vertical role;1000→1024 scaling would move them farther down. The later “opening” interpretation is not validated by the sample's numeric surface coordinates. |
|05a initial region measurement | The white-mug window rows610–680 includes mostly table below the mug. A global swap or1000→1024 adjustment does not repair this placement. It was not used to direct the initial learned grasp, so it is not the cause of that grasp's behavior. |
|05a request8 | Normalized `[0.625,0.7]` becomes `[639,716]`, on table just below the raised mug; swapping or enlarging the coordinates would not place it on that mug. No completed later model response or action used this sample. |
|05b request4 and segmentation | Native `[745,205]` and subsequent segmentation select the visible cheese package correctly. Grasp failure still follows. This is a counterexample to a universal localization/conversion explanation of failed grasp. |

These examples are diagnostic trace facts, not an experience containing reusable trajectory coordinates. Surface-role mistakes and unsupported grasp/alignment judgments remain independent causes after the presentation issue is removed.

## VLA language bridge and task8 boundary

`pi0_pick` assigns `instr = prompt`; `_vlm_chunk` places it unchanged into `task_descriptions`, predicts using the existing policy-oriented `main_images`/`wrist_images`, then restores task language. `Pi05VLAClient` batches those images and string without a left/right rewrite. The checked code contains no automatic viewpoint conversion of spatial language.

There is one direct spatial-language example in these six traces:03a request22 sends “pick up the yellow and white mug lying next to the left plate” unchanged. “Left plate” from the calibrated planner view refers to the opposite image side in the policy image. The subsequent pickup targets the wrong mug region, but object pose, occlusion and learned behavior also changed; this single observation does not identify the phrase as the sole cause. The other recorded initial grasp prompts identify objects by appearance/name without left/right.

See the dated [task8 clarification](task8-viewpoint-clarification.md). The approved private right-language cohort and official goal remain unchanged. No task8 episode was included in this03–05 audit.

## Next bounded test, draft only

Mixed orientation is confirmed strongly enough to justify a small planner-presentation candidate, documented in [candidate-draft.md](candidate-draft.md). It is not implemented and is not added to06. Before any policy evaluation, a paired recorded-frame grounding check should distinguish schema compliance, correct physical object, correct functional surface, and viewpoint binding. A success improvement in full tasks still requires a separate frozen matched evaluation; fixing display consistency alone does not establish grasp contact or successful placement.
