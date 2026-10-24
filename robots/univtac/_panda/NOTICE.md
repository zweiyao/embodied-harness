These files come from [TacTalent](https://github.com/ccyydd/TacTalent),
commit `75441c18c3054b6032c4923f4047b9deaef26694`:

- `src/tactalent/robot/ik.py`
- `src/tactalent/robot/state.py`
- `src/tactalent/robot/transforms.py`

They are distributed under the accompanying Apache-2.0 LICENSE. RPent's
`../control.py` adapts the same commit's `src/tactalent/roboicl/controller.py`.
Only its generic Panda IK, frame checks and explicitly counted native
interpolation are used; no task demonstrations or task-specific policies are
included. RPent adds attribution headers and applies repository import ordering
and formatting; the vendored algorithms are unchanged.
