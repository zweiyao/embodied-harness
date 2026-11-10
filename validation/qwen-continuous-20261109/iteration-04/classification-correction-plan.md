# Iteration 04 classification correction

The batch stopped lane a after treating every `UnexpectedModelBehavior` as an
infrastructure incident. Its task 4 episode had already ended after two malformed
`sensor_patch_batch` calls. The actual declared schema requires normalized numeric
pairs; the first reply supplied pixel values, then the retry supplied three-item
lists containing a string. No patch implementation or physical action ran.

Under the existing approved protocol, model argument failures remain valid task
failures. This correction changes only derived classification and aggregation:

```diff
- classification: unexpected; evaluation_success: null; excluded from denominator
+ classification: model_argument_error; evaluation_success: false; included
```

The original outcome, events, incident entry and pre-correction derived files are
preserved. No episode is repeated, no SDK retry limit changes, and no harness,
source checkout, controller, material or selected tool changes. A narrow helper
will require the exact retry-exhaustion error, matching actual versus published
schema, two successive schema-invalid model calls, the corresponding retry
message, and no implementation dispatch for either rejected call. Other errors
remain unexpected. The runner may use that evidence only when given the run path.

Validation: replay the actual task 4 evidence remotely; check that missing run
evidence, transport errors, a valid call, a mismatched schema, a missing retry
message, or a dispatched implementation cannot receive this classification.
Recompute both rows and counts, verify image pairing and protected files, then
stop only idle workbenches whose server IDs and unit paths match this batch.

The original live environment-child audit was not saved. At finalization only the
same workbench processes remain. Record their actual source roots and absence of
proxy variables; preserve this evidence gap rather than claiming a retrospective
observation of exited environment process command lines. Frozen setup, preflight,
recorded run sources and logs provide indirect evidence about those children.
