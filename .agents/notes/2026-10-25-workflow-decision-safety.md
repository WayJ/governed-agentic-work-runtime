# Workflow decisions, outputs and bounded rework

Four related fixes address repeated judgments, decision verification,
read projections, named outputs and routing after a node's attempt budget
is spent. The changes are in `work_runtime/workflow.py`; the public
`outputs` and `checkResults` shapes and the store schema are unchanged.

## What changed

- A routing pass now merges a criterion report once per judgment, using the
  judgment's content rather than its timestamp. Repeated passes while a
  required output is missing no longer add duplicate reports, events or
  state versions. A new decision, subject, input or attempt is still judged
  independently.
- A `record_decision` is verified before the engine settles it. If its
  proof is still pending, the node waits; it cannot route on an older
  decision. The read model projects the latest applied judgment for each
  declared criterion in declaration order, while retaining the complete
  history. Conflicting verdicts about the same judged fact appear as
  `conflict`, not as a silently chosen verdict.
- A named output is first recorded as a candidate bound to the decision's
  event ID. It becomes the node's output only when that same decision is
  verified and followed. A refused, pending or unrelated record cannot
  satisfy another decision's output requirement or become a downstream
  basis. Completed legacy outputs remain readable; an unbound output on a
  running legacy node is not guessed and leaves the node waiting.
- The routing cursor moves to a successor only after its attempt opens. If
  the successor's quality allowance is spent, the work escalates at the
  node that completed; later pump passes do not route again from the old
  terminal attempt or duplicate the escalation.

These rules preserve the authority, compare-and-swap, attempt and output
requirements. No history is deleted and no failed decision is converted
into an approval. The production-shaped M02 reproduction had accumulated
326 identical criterion reports and 327 `WorkflowOutputMissing` events
while the background pump kept advancing the same waiting decision.

## Incident evidence

The OA `oa-daily-report/oa-4` trace showed the failure directly:
`M02` attempt 1 was rejected (event 4221), `M01` attempt 2 completed with
output revision 2 (4222–4223), opening `M02` again exceeded its allowance
(4224), then the old rejection incorrectly sent work to `M01` attempt 3
(4225). The attempt-2 output remained persisted. The cursor fix keeps the
escalation stable without reopening a rejected attempt or changing history.

`max_attempts` is cumulative per node, not per input generation. Material
and authorized rework attempts do not spend it, and it is not reset by a
revalidation. The core default remains one. In oa-4, M01 declares three
attempts while M02 inherits the default one; a future workflow that needs a
second human review must use a newly published definition declaring two.
The core does not widen an already-pinned workflow's budget.

## Test evidence

The six focused regression files contain 51 tests:

- `tests/test_workflow_pump_idempotence.py` — 8 tests;
- `tests/test_workflow_decision_order.py` — 10 tests;
- `tests/test_workflow_check_projection.py` — 7 tests;
- `tests/test_workflow_judgment_conflict.py` — 3 tests;
- `tests/test_workflow_decision_output_binding.py` — 11 tests;
- `tests/test_workflow_reject_return.py` — 12 tests.

The reported focused total is 51 tests green. Root independently verified
the 12 new return tests and the full suite of 1703 tests OK (2 skipped);
the demo, syntax and site checks were also reported green. The documentation
gate reports 127 Markdown files, 682 local links and no broken links. RED
runs reproduced the duplicate pump writes, settling before verification,
stale/conflicting projections, adoption of a refused output and rerouting
after allowance exhaustion. This checkpoint did not rerun the suite.

## Deployment boundary

This is a core code change only: no migration, store change, dsh lock
change, adapter, UI or parent-platform change. The cursor fix is not yet
deployed; the GAWR instance must be rebuilt and restarted before it uses
that behavior. No live workflow is edited, and this note does not claim
end-to-end UI acceptance. The separate published `on_decisions` template
and its workflow acceptance remain outside this change.

The implementation is documented in [workflow-runtime.md](../../docs/workflow-runtime.md),
[workflow-api-contract.md](../../docs/workflow-api-contract.md),
[runtime-boundaries.md](../../docs/runtime-boundaries.md), and the W178–W194
rows in [verification.md](../../docs/verification.md).
