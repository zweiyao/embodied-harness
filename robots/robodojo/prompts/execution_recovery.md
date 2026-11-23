A target-range rejection cancels only the unexecuted steps of the current call;
it does not end the episode. Inspect the returned executed prefix, latest images
and measured poses (view_env_state when needed), then choose a new short action.
Do not finish solely for this rejection or blindly replay the old command.
For other uncertain execution, inspect fresh feedback before planning again.
Stop on authorization faults or genuine transport/physics failure; report an
infrastructure error if usable feedback cannot be obtained. Do not reset the scene.

After completing the task, return each controlled arm to its recorded episode-start
pose using motion tools before calling finish; do not reset the scene.
