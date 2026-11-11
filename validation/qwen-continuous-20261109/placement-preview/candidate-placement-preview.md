# Placement candidate P: reviewed visible region and held-feature alignment

Status: review draft only, 2026-11-09. No production/source/configuration changes, publication, simulator actions or model requests are authorized by this file. Iteration 04 and its source remain untouched. Root review is required before implementing this particular candidate.

## Evidence and hypothesis

03 task 4 already selected the correct left plate and visibly held the correct mug. At step 3 its valid mug samples differed from EEF y by about -0.074 to -0.083 m. The next action set EEF XY to the plate point, discarding that measured offset. Other purported object samples actually hit the robot/table. The hypothesis is that explicitly reviewing the actual sampled feature, then consuming a computed EEF target without retyping XYZ, will reduce this particular alignment error. A visible surface feature is not the object footprint center; eliminating its error does not prove that the whole mug fits the plate.

03 task 0 sampled the correct basket but mostly its near rim/outer wall. Three container calls rejected the geometry; the model then treated wall coordinates as an opening center. The old helper also accepted a coplanar patch of table; the model correctly rejected that result. Thus neither good depth nor a correct basket identity establishes the useful interior region. The hypothesis is that separately selecting a *visible interior subregion* in RGB and a trusted supporting/rim plane avoids substituting the depth behind the cavity for the intended placement location. It still requires correct semantic selection; wrong near-edge pixels remain wrong under correct projection.

The basket is cropped at the right in the recorded agentview. Do not reconstruct a complete hidden opening. A smaller fully visible region is sufficient for this candidate; its centroid is called `selected_region_center_xyz`, never the full opening center. No automatic hull completion, semantic mask-to-cavity assumption or privileged simulator pose is used.

The first `view_env_state` results in both 03 lanes actually supplied PNGs of 256x256 (policy), 1024x1024 (agentview), and 1024x1024 (wrist). `LiberoToolkit.get_env_state` uses native `view_env_state`; the API adapter sends these bytes without resizing. The separate research SensorInterface's 256x256 observation is not this experiment's model input. The overlay addresses auditable sample identity and functional-region selection, not an established lack of high-resolution inputs.

## Smallest proposed behavior

Add two opt-in native tools in one owned module:

1. `preview_placement(step, camera, held_feature, target_region, plane_samples)` is readonly. All arguments are required. Points are integer `[row, column]` pixels of the current calibrated high-resolution image, bounded against its actual dimensions. The schema accepts exactly two nonnegative integers; it never accepts normalized coordinates as an alternate format. This matches native back_project/container inputs and avoids the normalization errors already observed in 04. `target_region` is a convex 4–8 vertex polygon entirely inside a visibly suitable part of the plate or opening, ordered around that visible subregion. It is not the entire object silhouette or a guessed hidden boundary. Four to eight `plane_samples` select visible plate support or rim surfaces defining the same approximately horizontal plane. `held_feature` is a clearly visible point on the held object, not the robot, target or background.
2. The tool samples depths only for the held feature and plane anchors. It fits a plane, intersects the target-region rays with it, computes that region's area centroid, then computes `eef_xy + region_center_xy - held_feature_xy`; EEF z is retained. It returns a numbered full image plus a crop containing the selections, short numeric diagnostics, and a single-use `preview_id` only if numerical checks and the existing documented 0.30 m XY staging requirement are met. It does not sample cavity depth to estimate the target.
3. On the next request, Flash reviews the returned O/P/R overlay. If the object, plane anchors or region are wrong, it calls preview again with corrected selections. `align_placement(preview_id)` is the review/commit operation: it checks the same latest step, camera calibration and robot pose, consumes the stored target, and invokes the already verified M `translate_to` once. The model cannot change that target while committing. Subsequent lowering, release, recovery and image-based judgment remain model decisions.

Calling align establishes only that the model accepted the displayed evidence; it does not make the evidence semantically true. Readonly calls at an unchanged step do not expire the preview. Any recorded action, changed pose/calibration, replaced preview, consumed ID or terminated episode does. No request for a hidden camera pose, object mask, object pose or task evaluator state is added.

`align_placement` refuses a computed XY move longer than 0.30 m, without an executable preview ID. The current `move_to` only documents this staging rule; its implementation does not enforce it. The model must choose an intermediate carry-height translation and then make a fresh preview. This candidate neither changes the old primitive nor silently executes extra waypoints.

## Exact condition guidance

Append only when both new tools are selected:

> For placing a held object on a plate or into an open container, preview_placement selects a visible target region and includes the held-feature offset. Inspect its O/P/R overlay, then use align_placement with that preview_id; reselect incorrect marks. Recheck the returned images before lowering or releasing.

This is a task-scoped workflow contract, not new experiential memory. Existing on-demand object-relative-transfer memory already describes the general issue; no new note or MEMORY.md line is proposed in P.

## Files and exact code draft

- New `robots/libero/research/placement.py`: complete draft in `candidate-placement-preview.py.draft` beside this file. Numerical thresholds are explicit provisional interface checks, not task coordinates or a clearance claim; they require the offline checks below before approval for model use.
- `robots/libero/research/manual.py`: instantiate/register `PlacementTools` only if the two names are selected; add the exact conditional guidance above. Wrap `align_placement` with the existing `_execute_primitive` exactly as M, so normal recording, cancellation and returned observations remain intact. Reject selecting only one of the pair before creating an environment.
- `rpent/dashboard/workbench.py`: catalog those two native declarations, category perception/control respectively; exclude both from defaults. Hash the complete owned module as part of their version, not just each thin handler (the mathematical helper is behavior). Existing native versions/defaults unchanged.
- New focused tests `tests/unit_tests/robots/libero/research/test_placement.py`; narrow registration/default-selection tests in existing manual/workbench test files. No `robots/libero/tools.py`, core planner, runtime controller or frozen 03/04 checkout changes.

The concrete registration sketch is in `candidate-placement-registration.patch.draft`. It is not an apply-ready patch against a frozen runtime; rebase only in a new isolated checkout after root review.

## Selection and adoption

P's parent is frozen now as iteration 04 restricted-18, irrespective of 04's result. The primary mechanistic comparator is 04; original C remains the success incumbent until evidence supports a replacement. Preserve Flash, no thinking, 30 shared model requests, 600 s, direct API, C memory and controller settings. For the first two-task screen, replace old `sensor_container_geometry` with preview+align; keep old patch tool for unrelated measurement. This is 19 tools. Complete selection list must be frozen by the evaluation owner before startup.

Admission to `align_placement` requires a valid reviewed preview. This does **not** globally prohibit direct `translate_to`, negative `set_gripper`, or old `release`. The short placement contract is therefore a model instruction, not a hard semantic phase detector. Count skips explicitly: release without any accepted preview is valid task behavior but workflow non-adoption, never an infrastructure incident or an excluded failed episode. No claim about P's executed mechanism when it is unused. Hard-gating all releases would affect failed-grasp recovery and contact tasks and is not part of P.

If the 19-tool soft contract again yields zero adoption, do not call that geometry failure. A separate hard alternative would replace free `translate_to` with `translate_vertical(z)` and require `align_placement` for manual XY. Pi0 and explicit rotation/gripper controls remain. This forces a different control capability: arbitrary XY waypoints, manual grasp approach and some recovery become unavailable; >0.30 m alignment would be blocked unless a separately specified waypoint operation exists. Therefore that alternative is not included in P and cannot be quietly enabled after failures. A release gate based on model-claimed holding would not solve this distinction and is not recommended.

## Limits

- Initial scope: upright held objects and stationary roughly horizontal visible plate/open-container targets in tasks 4 and 0. It does not solve knobs, drawers, stove contact or arbitrary six-dimensional insertion.
- A consistent plane can be a table. A convex polygon can be on the outer wall. Overlay review must reject those roles; the code cannot independently certify semantic identity.
- The chosen object feature is a visible surface, not necessarily the object's center or lowest point. After alignment, inspect the whole object's relation and retained holding in fresh images. No full-footprint fit, collision path, release height, bottom clearance, stable placement or task success is inferred.
- Same-camera back-projection/reprojection is an algebraic consistency check, not independent accuracy evidence. Use the other recorded camera and subsequent object-relative motion for stronger evidence.
- Crop annotation does not change coordinate conventions: input points remain integer `[row,column]` pixels in the original full-resolution calibration image. Both original dimensions and crop bounds are returned.
- More review calls consume the same 30/600 budget. The criterion is task outcomes and reduced misalignment/corrections at matched budget, not simply tool execution or fewer text tokens.

## Falsifiable checks before a model screen

1. Synthetic calibration: recover known plane intersections, show cavity/background depth changes do not change the target, and prove object/EEF offset is preserved algebraically. Test translated/rotated cameras and image dimensions; verify integer pixel `[row,col]` conventions. Reject normalized fractions, strings/extra elements and out-of-image pixels instead of interpreting another coordinate format.
2. Invalid geometry: unavailable high RGB/world/calibration, stale step, nonfinite/out-of-range points, inconsistent depth, degenerate/steep plane, crossed/nonconvex region, backward/parallel ray, and >0.30 m correction return no executable ID. Do not loosen checks to accept 03 bad data.
3. Native interface: same-step read does not invalidate; action/pose/calibration changes do; a failed/replaced/consumed preview cannot be aligned. A valid commit calls M exactly once with the frozen target and no gripper/quaternion input; cancellation, termination and normal images remain inherited. Default tool selection and old prompts byte-identical without P.
4. Archived 03 replay, no model: manually annotated correct held feature/plane/visible region versus the original robot/table/near-rim selections, with annotations kept as diagnostic evidence only. Correct samples must produce an inspectable plausible region; wrong but planar/semantic samples must stay explicitly conditional and visibly wrong, not be called automatically rejected or verified. Full output JSON stays small; PNGs use ToolResult.images, outside Sandbox's 32 KiB JSON budget. Show actual O/P/R overlays for review before any model startup.
5. Independent geometry checks: compare goal-plane intersection to depth of trusted support/rim anchors, and project the proposed reference/region into the second camera at the same step. For task 4 replay report the predicted feature XY correction separately from actual object-footprint quality. No static replay can prove that a subsequent grasp remains held or that the full task succeeds.
6. After approval: a finite owned simulator interface probe in a new isolated checkout checks one preview/commit, bounded XY/gripper-preserving action, state-recording and cleanup, with no model call or success claim. Then matched tasks 4/0 seed 0 screening. Log preview count, corrected semantic selections, accepted IDs, actual align count, before/after selected-feature error, release without preview, model requests/time/tokens and official success. No additional provider/agent or uncounted perception request.

Current status: draft only; none of these checks have run for P.
