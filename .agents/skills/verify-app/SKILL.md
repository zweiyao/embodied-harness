---
name: verify-app
description: Verify RPent UI and interaction changes using mapped user journeys, isolated Playwright browser tests and existing pytest contracts. Use after edits or when asked to demonstrate app behavior and provide diagnostic artifacts.
---

# Verify the app

1. Inspect the diff and affected entry points. Match each changed behavior to a row in the [feature map](../../../docs/feature-map.md). Record the user action, observable result and test selector. Extend the nearest journey if the changed behavior is missing. For CLI, API or robot-adapter behavior, use its mapped pytest contracts and the repository’s [verify-change](../verify-change/SKILL.md) checks.
2. Work from the candidate source in the project test environment. Use disposable roots, synthetic inputs and fixture model profiles. A normal dashboard launch can initialize services and recover records. The [browser suite](../../../tests/e2e_tests/dashboard/test_workbench_browser.py) starts its own loopback DashboardServer and discards its state. Keep verification away from deployed dashboards, credentials, robot hardware, production records and destructive actions.
3. After the edit, run the selected tests yourself. On a shared dashboard change run all four browser journeys. Run the associated API or JavaScript contract tests as well. In an isolated Python 3.11 environment with the project installed, provision missing browser dependencies once using the commands below. Reuse a matching installed Chromium when available.

   ```sh
   uv pip install -e '.[test,browser]'
   python -m playwright install chromium
   ```

   From the repository root, use a fresh output directory on each attempt. The same commands apply on the remote test host.

   ```bash
   set -o pipefail
   export VERIFY_APP_ARTIFACTS="$(mktemp -d)"
   python -m pytest -q tests/e2e_tests/dashboard \
     --junitxml="$VERIFY_APP_ARTIFACTS/results.xml" 2>&1 | tee "$VERIFY_APP_ARTIFACTS/pytest.log"
   ```

4. Check the rendered state after each action. The suite fails on assertion errors, JavaScript exceptions, console errors, failed requests and HTTP errors. It saves a viewport screenshot, Playwright trace and browser error log per journey, including teardown on assertion failure. For a layout change inspect the screenshot and exercise the affected viewport. Use `python -m playwright show-trace PATH/trace.zip` to inspect the action, DOM and request timeline.
5. On failure, preserve the original directory. Match the first failing request or assertion to the server response or frontend handler. Distinguish product errors, fixture errors and missing test dependencies. Fix the demonstrated cause within the authorized scope, rerun the failing journey, then its related checks. Preserve failures that need credentials, hardware or additional authorization as unverified. Review trace contents before sharing. Publish synthetic test evidence only.
6. Report the feature and user action, revision, actual pass/fail/skip counts, errors and cause, fix and retest outcome, screenshot/trace/log paths and remaining risks. Keep checks that did not run explicitly listed. The [browser CI workflow](../../../.github/workflows/verify-app.yml) repeats the suite for relevant pull requests and pushes to main.
