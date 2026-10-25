# Workflow decision and output safety

Three related fixes address how a human node handles repeated judgments,
verification, read projections and named outputs. The changes are in
`work_runtime/workflow.py`; the public `outputs` and `checkResults` shapes
and the store schema are unchanged.

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

These rules preserve the authority, compare-and-swap, attempt and output
requirements. No history is deleted and no failed decision is converted
into an approval. The production-shaped M02 reproduction had accumulated
326 identical criterion reports and 327 `WorkflowOutputMissing` events
while the background pump kept advancing the same waiting decision.

## Evidence

The five focused regressions are:

- `tests/test_workflow_pump_idempotence.py` — 8 tests;
- `tests/test_workflow_decision_order.py` — 10 tests;
- `tests/test_workflow_check_projection.py` — 7 tests;
- `tests/test_workflow_judgment_conflict.py` — 3 tests;
- `tests/test_workflow_decision_output_binding.py` — 11 tests.

The implementation report records these 39 focused tests green, plus the
full suite of 1691 tests OK (2 skipped), the demo and syntax checks green,
and the documentation gate reporting 127 Markdown files, 682 local links,
and no broken links. The recorded RED runs reproduced the prior duplicate
pump writes, settling before verification, stale/conflicting projections,
and adoption of a refused decision's output. These results were reported
by the implementation worker; this integration checkpoint did not rerun
the suite.

## Deployment boundary

This is a core code change only: no migration, store change, dsh lock
change, adapter, UI or parent-platform change. The GAWR instance serving
the workflow must be rebuilt and restarted before it uses this behavior.
This note does not claim that the new core is deployed. The separate
published `on_decisions` template and its workflow acceptance remain
outside this change.

The implementation is documented in [workflow-runtime.md](../../docs/workflow-runtime.md),
[workflow-api-contract.md](../../docs/workflow-api-contract.md), and the
W178–W191 rows in [verification.md](../../docs/verification.md).
