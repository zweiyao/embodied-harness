# P: visible-region preview and one-shot alignment

P is implemented and validated in an isolated checkout. No Qwen task result is established by these checks. The approved next screen keeps iteration04's restricted18 background and C materials, replaces its old container tool with the two P tools, and retains the old patch tool and M: 19 selected tools in total. The original workbench and prior frozen conditions are unchanged.

`preview_placement` accepts integer full-image `[row,column]` pixels, separating the held feature, visible target subregion and support/rim plane anchors. It fits the selected plane, intersects region rays with it, and computes `EEF_xy + region_center_xy - feature_xy` while retaining EEF height. Returned O/P/R markers and computed target C make the selected roles reviewable. A single-use preview ID commits the frozen target through M; actions, changed pose/calibration, a replaced preview or ID reuse invalidate it. It does not lower, release, select hidden boundaries or infer holding/clearance.

The pair is opt-in and adds only the approved short placement contract. No new experiential memory is added. The complete module, including geometry and rendering, defines both native versions: `3542ec64f42640baf1288aa36f3386a29475f659bd118bf3cc44cf623b71e3ac`. The existing M version is unchanged. See [source provenance](source-differences.md), [reviewed draft](candidate-placement-preview.md) and [authorization](authorization.json).

| Check | Evidence |
| --- | --- |
| Full remote unit suite | 2086 passed / 15 skipped, 71.93 s |
| Latest focused placement/manual/workbench checks | 49 passed, 0.82 s; includes one routing/image-recording case added after the full run, with unchanged production code |
| Scoped hooks and validation scripts | Passed; no full CI Python matrix run |
| Existing behavior | All 19 prior native declarations and four default/selected prompt snapshots unchanged |
| Independent archived replay | Four manually annotated cases, zero actions/model requests |
| Real simulator interface | One owned environment, one valid align, three actual control steps, three returned images, zero model/VLA requests |
| Probe cleanup and protection | Owned descendants exited, no forced cleanup; 563 protected files and private config unchanged |

The first test-development run was 37 passed / 11 failed because its coarse synthetic pixel pitch exceeded the fixed local-patch spread check. The fixture was refined at the same field of view; production thresholds were not loosened. Formatting changes were limited to this implementation and its tests/scripts. Complete logs remain remote; [validation.json](validation.json) records the final checks.

Historical replay provides two distinct results. For task4's independently selected cup feature and plate subregion, plane residual was about 0.000067 m and the computed XY correction was 0.0994 m. For task0's visible basket interior, the selected rim plane fit with about 0.000222 m residual, but the 0.4484 m correction exceeded the existing documented 0.30 m staging rule, so no executable ID was issued. A waypoint and fresh preview would be required; no such action was taken in replay.

The deliberate wrong-robot feature was also numerically accepted. The deliberate wrong-table plane likewise fitted and gave a different conditional target, though its distance required a waypoint. These are retained counterexamples: a consistent plane and C lying inside R do not establish semantic correctness. In particular, projection onto a wrong plane can keep C inside the same image region by construction. Only inspecting the P marks exposes that wrong plane role. Task4's secondary wrist projection supports the plate correspondence, not metric accuracy; task0's projected target was outside the wrist field of view. See [independent review](independent-replay-review.md) and [replay summary](replay-summary.json).

The real probe used a visible surface feature as a diagnostic input, not an actually held object. Its one valid align produced 0.01017 m of actual horizontal EEF movement, zero angular/gripper command components, normal recorded observations and rejection of a reused ID without further control steps. The original servo reported `steps_used=4`, including its final arrival check; actual control steps were three. Gripper target-retention semantics are inherited from unchanged M and its earlier installed-controller probe. This does not demonstrate held transport, placement accuracy or task success. Raw frames and traces remain in the remote probe directory.

The root reviewed both actual O/P/R/C overlays before authorizing the finite probe. Model adoption, corrections of wrong semantic selections, whole-object fit, successful placement and matched-budget task improvement remain for the next experiment. All such attempts must keep valid failures in the denominator.
