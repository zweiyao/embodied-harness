# PR #6 timeout-test synchronization

PR #6 was mergeable without file conflicts; its Python 3.10 unit-test job
failed at `stopped.is_set()` in
`test_timeout_drains_physical_work_and_records_partial_history`
([original run](https://github.com/zweiyao/embodied-harness/actions/runs/43857966023)).

The 150 ms deadline included the fake model startup, so it could expire before
`move` started. A remote, offline reproduction adds a 250 ms delay before the
fake model response: the original test fails at exactly the same assertion.
This establishes a reproducible race; it does not identify the exact scheduler
delay on the original GitHub runner.

The test now starts the real `asyncio.wait_for` deadline after the fake move has
started. Startup has a separate bounded wait; cleanup runs if startup fails.
The original timeout, stopped-work, partial-history and JSON assertions remain.
No production code, prompts, experience, service configuration or experiment
behavior changes. No model API or robot is used.

Remote evidence is retained under
`/home/zwy/work/embodied_harness/validation/pr6-ci-repair-20261116/`.
The reproduction plugin and logs are validation-only and are not runtime inputs.

Validation on the remote Python 3.11 environment:

- Delayed-start reproduction: original fails; corrected test passes.
- Planner contracts: 61 passed.
- Full unit suite: 2152 passed / 16 skipped in 72.16 seconds.
- All-files pre-commit: passed after applying the formatter's signature wrapping.
- Post-format planner contracts: 61 passed in 3.15 seconds.

GitHub's Python 3.10/3.11/3.12 matrix will validate the pushed PR revision;
the remote full-suite result above is Python 3.11 only. The PR is not merged
automatically.
