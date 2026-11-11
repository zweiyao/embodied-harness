# Iteration08 visual follow-up

Read-only review after the terminal report, while09 was running. Three saved
external images (task0 step0; task4 steps0/1) were inspected through640px JPEG
review copies outside Git. Original images, policy inputs and running09 were
not changed. Large direct downloads initially failed; bounded read-only retrieval
completed with byte hashes, without changing any network/proxy settings.

Task0's scene visibly includes a bottle labeled Tomato Ketchup, separate from
the tomato-sauce can. The policy query `bottle of tomato ketchup` therefore
names a real distractor, despite the goal asking for tomato sauce. The detector
returning a confident match is not itself a failure of coordinate arithmetic;
the wrong object query preceded any attempt to manipulate it. No task0 action
occurred in08, so there is no executed coordinate error to diagnose there.

Task4's yellow/white mug changes image position and appears raised beneath the
hand after Pi0. This is consistent with the reported ascent and grasp, but the
single post-action view does not establish stable holding during transport.
No transfer or placement was attempted in08. The subsequent plate segmentation
lies on the visible left-hand plate. The installed task's BDDL initializes
plate_1 in plate_left_region and plate_2 in plate_right_region; their declared
lateral ranges have opposite signs. The returned left-plate surface point falls
within the former range, consistent with the requested yellow/white destination.
This checks the archived candidate's region correspondence, not runtime object
tracking or official goal satisfaction. No benchmark definition was changed.

Thus08 task4 should not be described as a demonstrated wrong-plate or failed
coordinate computation. Its observed limit was progression: long pre-action
checks, one grasp, then additional perception before the full time budget ended.
A grasp-consistent image is also insufficient to claim task success.

Evidence paths under the08 experiment root:

- a/runs/session/tasks/0001_libero_10_task_t0_s0/agentview_high.png/00.png
- b/runs/session/tasks/0001_libero_10_task_t4_s0/agentview_high.png/00.png
- b/runs/session/tasks/0001_libero_10_task_t4_s0/agentview_high.png/01.png
- Corresponding events.jsonl and task4 segment_02.json/01.json.

The BDDL is the exact task4 file recorded in task-audit.json. An initial parser
read used system Python without bddl installed and failed before reading the
problem; the same read succeeded with the existing project virtualenv. Neither
command constructed a simulator or called a model. These observations remain
analyst evidence only and were not injected into09.
