# Return controlled arms to the episode-start pose

The common prompt adds one approved sentence: after completing the task, return
each controlled arm to its recorded episode-start pose using motion tools before
calling `finish`; do not reset the scene. Existing authorization, operator and
control requirements remain present. No controller, tool, experience, task
supplement, threshold or scoring implementation changes.

The single file `rpent/prompt/common.md` is deployed to the active layered checkout
`checkouts/prompt-system-refactor-20261116`. Existing conversations are unchanged;
new TaskRuns read the updated file. Deployment preserved workbench configurations
and service PIDs, without restarts or robot actions. Older language-material
prompts and separate legacy workspaces were not changed.

Remote Python 3.11 validation on an isolated source snapshot: **2156 passed /
16 skipped**, 77.11 seconds; all-files pre-commit passed. Candidate and deployed
source renderings using the four workbenches' selected tool names contain the
new sentence once and preserve the existing authorization rule. Recorded prompt
source hashes match. These are rendering checks for RoboDojo, Flexiv, LIBERO and
UniVTAC, not live task validations of all four environments. The initial render
probe omitted UniVTAC tool descriptions; it was corrected to use native catalog
declarations and rerun successfully. No production code change was needed.

## Why tasks 3 and 4 can look finished but fail

Both installed native task definitions require `all_robot_back_to_origin()`.
Their generated language omits this condition. Recorded final EEF poses fail
the installed predicate against their recorded initial poses; task 5's successful
episode explicitly requests robot return and passes the same offline check.
This confirms a failed mandatory completion condition, not that every object
predicate would pass after returning home. The runtime's separate internal home
reference was not saved; the first recorded observation was the offline reference.

`build_tower` is task **3**. Its native instruction only says "Build a tower using
the wooden blocks and wooden boards." Its separate reward implementation checks
specific support relationships, upright axes, alignment and centering. The
adapter reads this native language, and the generic task supplement does not
describe that geometry. This is a mismatch between language and the native
completion contract; the reason the upstream authors chose this wording is not
established. Task **4**, `classify_objects`, is category sorting into baskets.

The new two-episode retry adds only the return instruction; hidden tower geometry
was not added. Original results remain **4/10 native successes**. Retried results
must be reported separately and cannot establish a general success-rate gain.

Remote evidence is under `validation/return-initial-pose-20261117/` (unit and
pre-commit logs, candidate/deployed render reports, deployment backup/report) and
`debug/robodojo-score-t3-t4-20261117/` (offline native-predicate probe and findings).
No simulator was launched during software validation; the separately authorized
task retries are recorded under `validation/robodojo-tasks3-4-return-pose-20261117/`.
