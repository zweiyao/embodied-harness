# holmes_RUA homepage evidence

Base revision: `c8029f02aa6577c7ae04e0bd854b56edd6ee4ab2` (`origin/main`).
The English and Chinese README display names become `holmes_RUA`.
The previous upstream logo, promotional framework image, leaderboard image,
news, and feature matrix are removed from the landing pages at the user's request.
Installation and environment instructions remain in the linked repository guides;
upstream attribution, paper citation, and the Apache-2.0 license are retained.
Python package names, command names, configuration, and the GitHub repository
slug are unchanged. No runtime code or running service is modified.

## Result provenance

`results.json` contains compact metadata read from existing remote experiment
records on 2026-11-13, with source paths relative to the remote workspace and
SHA-256 hashes. It contains no observations, videos, credentials, or weights.
The summaries in the original Astra launch directory are stale; the published
50-cell table combines valid rows from initial, continuation, resume34, and
resume32 result files and excludes the infrastructure incident with unknown
success. Each completed historical cohort covers tasks 0–9 and seeds 0–4 once.

- Astra: 35/50, 600 seconds, 30 completed model responses, reasoning low.
- Historical Qwen: 3/50, 30 requests; 8 runs at 3000 seconds and 42 at 1500 seconds.
- Object-T Qwen: 39/44 settled cells of 50 planned, 50 requests, no episode
  deadline, IPv4 direct; five old pre-switch cells excluded and four replaced.
  The six missing cells remain outside the denominator. This is a snapshot,
  not a live report and not a final 50-run score.

These are maintainer-run RPent results, not upstream paper scores and not
measured improvements from holmes_RUA. Suites and budgets differ. Astra's
archived turns count completed responses, while Qwen's counter counts requests;
these are not identical metrics. Elapsed averages include valid failures.
Tokens equal input plus output; cached input is a subset of input.

## Checks

Validation runs in an isolated remote copy of the base revision with the changed
Markdown and metadata overlaid. Numeric checks recompute task and overall
counts, rates, means, token totals, unique task/seed coverage, and source hashes;
all three tables in both languages must match the saved JSON. Relative Markdown
links are checked against the checkout. GitHub's Markdown renderer is checked
for three result tables and the `holmes_RUA` heading in both languages.

Repository checks: `pre-commit run --all-files` and
`python -m pytest tests/unit_tests -q`.
Results are recorded in `checks.json`. Sphinx is not run because its sources
and build inputs are unchanged. No model calls, new episodes, simulator launches,
robot actions, network switching, or service restarts are part of validation.
