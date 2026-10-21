# Report — per-node IO/quality for action and wait nodes

Task `task_835d9f6650d1`, dispatch `ctx_c1c61469b029`.
Branch `WayJ/gawr-mixed-node-design`, baseline `d79cbc4`.

## What was built

| id | deliverable | outcome |
|---|---|---|
| Q1 | `work_runtime/workflow_spec.py` — the definition language accepts `output` and `checks` on `action` and `wait` nodes, `output.evidence_kind`, and `match.bind`; a wait `match` declares exactly one source; `bind.node` must name a declared node | shipped |
| Q2 | `work_runtime/workflow.py` — the engine judges the inputs before the effect, captures and bounds the receipt the adapter really returned, validates the automatic node's output, writes the named object and the engine's own event proof, binds a wait to the proof it matched, and records the quality of every node | shipped |
| Q3 | `work_runtime/workflow_demo.py` — the dispatch receipt becomes the *order* the field report and the independent review judge, a dispatch wait node binds the proof of the attempt that produced it, and the delivery receipt is validated the same way | shipped |
| Q4 | docs — `docs/workflow-runtime.md`, `docs/workflow-api-contract.md`, `docs/runtime-boundaries.md`, `docs/verification.md`, `README.md`, `README.zh-CN.md` | shipped |
| Q5 | `tests/test_workflow_node_quality.py` — 26 tests, written before the implementation | shipped |

## The behaviour, in one paragraph each

**Inputs before the effect.** A node's declared input validation now runs
the pinned validator, not only the shape descriptor. A failing input blocks
the node during activation, and a blocked action node never proposes an
operation — no external effect is authorized.

**The receipt is the material.** The engine wraps the adapter it calls
(`_ReceiptRecorder`) and keeps the receipt the external system really
returned, bounded (8 KiB transport fields, 64 KiB business payload), with
its origin: operation id, capability, business key, external id, document
digest and adapter class. It is stored on the node instance that awaits it.
The receipt schema and the digest/action linkage stay authoritative: a
receipt whose digest does not match the operation is quarantined by the
runtime itself (`outcome_unknown`), and a receipt that names another action
is refused (`WORKFLOW_RECEIPT_ACTION_MISMATCH`).

**The output is judged, then adopted.** The business payload in the receipt
is validated against the declared shape and the pinned validator; the
per-criterion report is persisted with the method, the criterion version,
the validator id and version, the reviewed input and output digests, the
reason and the evidence; the report itself is checked at the core boundary
(a verdict must name a declared criterion, a pass must carry its evidence,
a verdict must come from the validator the criterion was bound to). Only
then is the payload written as the named object and the node completed. A
declared criterion with no verdict is a refusal, never a pass.

**The effect and the output are two facts.** A successful effect whose
output fails stays recorded as what it was (`effect.status = "succeeded"`,
with its external id and operation id); the node fails with
`WORKFLOW_OUTPUT_INVALID`, the workflow reports `needs_attention`, and the
effect is never produced again — routing back into the same node is refused
and a second attempt fails closed with `WORKFLOW_EFFECT_ALREADY_APPLIED`.

**The wait binds what it matched.** A wait may declare `bind`
(`{node, attempt?}`). Without an explicit attempt the wait accepts the
proof of that node's *current* attempt; with one it accepts exactly that
attempt. A subject pins the proof to the current revision and digest of the
object it covers. The matched binding is persisted and readable
(`waitMatch`): work, node, attempt, bound node and attempt, object revision
and digest, and the event provenance (source and event id).

**The compatibility rule.** A node that declares neither an `output` nor
`checks` keeps its previous behaviour, and the read model says so
explicitly: `quality.declared = false`, `quality.mode = "undeclared"`, an
empty check report. A wait that declares neither a binding nor a subject
keeps matching any verified proof of its kind and reports
`waitMatch.mode = "kind_only"`. No quality is invented for either, and none
is implied.

## RED/GREEN evidence

| step | RED | GREEN |
|---|---|---|
| the new tests | `tests/test_workflow_node_quality.py` (19 tests) written first; the first run failed 17 of them — `SPEC_FIELD_UNKNOWN` on `nodes.n01.output`, `nodes.n01.output.evidence_kind` and `nodes.n02.match.bind`, and the wait and action assertions failed because no output, report, binding or named object existed | `PYTHONPATH=.:tests python3 -m unittest test_workflow_node_quality` → 26 tests, OK |
| the whole suite | after the definition changed, 12 existing tests failed: the review, engine, http and recovery tests drove the old ten-node fixture, in which N07/N08 judged the proposal and the node count was ten | the fixture was adapted (N07/N08 now judge the order; 11 nodes; the object set is now intake, analysis, proposal, order, dispatch_receipt) and `python3 -m unittest discover -s tests` → **1306 tests, OK (2 skipped)** |

The gates at the end of the slice:

```
python3 -m unittest discover -s tests            →  1306 tests, OK (skipped=2)
python3 -m compileall -q work_runtime tests scripts   →  clean
python3 scripts/check_docs.py                    →  125 markdown files, 676 local links, 0 broken
python3 scripts/check_site.py                    →  2 pages, 0 findings
python3 -m work_runtime workflow-demo            →  the eleven chapters, 2 external effects
python3 -m work_runtime demo                     →  clean
```

## The wire and read model

Sent to the coordinator early (message `msg_d61c906e8172`) and recorded in
[docs/workflow-api-contract.md](../../docs/workflow-api-contract.md):

* definition: `action`/`wait` nodes may declare `output`
  (`{object, evidence_kind?, validation{shape, validator, validator_version}}`)
  and `checks`; `wait.match` may declare `bind` (`{node, attempt?}`).
* read model (`GET /v1/workflows/instances/{workId}`, per node): `quality`,
  `effect`, `waitMatch` and `receipt` are added; `receipt` carries the
  transport facts only — the business payload is read as the named object.
  `GET .../nodes/{node}/attempts` carries the same per-attempt records.

## Remaining limitations (disclosed)

* The receipt is captured where the engine calls the adapter
  (`WorkflowEngine.pump` / `recover`). An operation confirmed by a host
  outside the engine is back-filled from the authoritative **lookup** of the
  same business key — never from a second effect.
* `work_runtime/runtime.py` and `work_runtime/adapters.py` are **byte
  unchanged**; the byte pin in `tests/test_publishing_compensation.py`
  still holds and was not touched. The receipt is persisted on the node
  instance, not on the operation.
* The engine writes its own event proofs under the source
  `workflow-engine` with the event id `wf:<operationId>`. That is a new
  source in the evidence ledger; it is deliberately **not** the ingress
  source of a signed evidence kind, so the engine never impersonates a
  platform channel.
* A declared output requires a resolvable, version-pinned validator. A
  shape-only output is refused at settlement
  (`WORKFLOW_VALIDATOR_MISSING`) — the engine does not treat a shape as a
  business judgement.
* The demonstration's stand-in business system is a local SQLite store, not
  a real external system, and the scenario grew from ten to eleven nodes;
  the existing review/engine/http/recovery tests were adapted to the new
  published definition (they now judge the order and expect 11 nodes and
  5 named objects). No assertion was weakened.
* The wait binding compares the *producing* node's current attempt. A wait
  that names an explicit attempt pins that attempt exactly. The wait's own
  attempt is recorded in the binding as well.

---

## Second round — the coordinator's five follow-ups

The coordinator sent five follow-ups on the first slice. All five are
implemented, tested and committed in the same branch.

| follow-up | implementation | evidence |
|---|---|---|
| the input validator was never invoked, for any node kind | `inputs[].validation` and `subject.validation` now run the **pinned validator**, not only the shape, during activation — before any intent and before any external effect. Every judgment is reported: `input_report[{object, role, revision, digest, validator, validatorVersion, verdict}]`, and every finding carries the pinned validator id, its version and the reviewed revision and digest. `input_digest` still covers exactly the declared `inputs`; the subject is pinned separately in `subject` and a decision must cover its exact revision and digest — the two semantics are documented separately | `test_an_input_rejection_blocks_with_pinned_provenance`, `test_an_accepted_input_is_reported_with_its_pinned_judge`, `test_an_unresolvable_input_validator_fails_closed_at_publication`, `test_a_subject_with_a_declared_validation_is_a_protected_input` |
| human nodes need an optional named output, written in the same CAS-guarded `record_decision` | a human node may declare `output`; the decision command accepts an optional `result`; the core judges it against the declared shape and the pinned validator and writes it as the named object **inside the same transaction**. The decision is never lost: a record that fails its quality is not written (the previous revision is untouched), the node does not complete and the findings say why. A node that declares an output and whose decision carries no record keeps waiting. The binding is persisted: actor, source, node, attempt, subject, input digest, output digest | `test_a_human_decision_writes_its_named_output`, `test_a_human_decision_without_its_record_keeps_the_node_waiting`, `test_a_rejected_record_is_not_written_and_does_not_route_on`, `test_a_rejected_record_never_overwrites_the_previous_revision`, `test_a_human_node_without_a_declared_output_is_not_implied_to_be_checked` |
| a required criterion must have a judge that can run | the lint refuses an orphan judge at publication (`NODE_JUDGE_MISSING`): a required `AGENT` criterion needs a declared review path, a required `PROGRAM` criterion needs an output validator | `test_a_required_agent_criterion_without_a_review_is_refused`, `test_a_required_program_criterion_without_an_output_validator_is_refused` |
| a revised candidate must not accept the old review | `_supersede_pinned` now pins the node's **output** as well as its inputs and subject, so a new revision of the candidate cancels the submitted node and the review of the superseded candidate cannot complete it. The same fix removes a crash: a subject that is a reference dict is no longer iterated as a list of keys | `test_a_revised_candidate_supersedes_the_reviewing_node`, `test_revising_the_subject_of_a_human_node_supersedes_it` |
| send the precise callback/descriptor extensions | sent as `msg_6690300c187f`: the wire addition (`result` on the decision route), the read-model additions (`quality`, `effect`, `waitMatch`, `receipt`, `outputBinding`), the validator callback (`validate(work, node_ref, value)`, `node_ref = {node, attempt, checks, role, capability|object}`, `role ∈ {input, subject, output, decision}`) and the definition invariant | — |

### The demonstration after the follow-ups

The published scenario now carries the whole chain: N04's decision archives
the **signed safety approval** as a named object, N05 reads that record as
its input, N06's dispatch receipt becomes the **order**, N06W waits for the
proof of that attempt, N07 and N08 judge the order and archive their own
**feedback** and **verification** records, and N10's delivery receipt is
validated the same way.

### The adapted tests

The published definition changed, so the tests that drive it were adapted —
no assertion was weakened:

* the review, engine, http and recovery tests now carry the named record
  where a human node declares one (the shared `decide` helper routes
  through the workflow command when the node declares an output, because a
  record can only arrive with the decision);
* the raw evidence path is still exercised where the *settlement* check is
  the subject (the assigned-authority and role-isolation tests), and those
  tests now say so explicitly (`raw=True`);
* the report assertions count the program verdict of the named record
  beside the human verdict, and the demo test asserts that a `HUMAN` entry
  names the person and a `PROGRAM` entry names the validator.

### The gates after the follow-ups

```
python3 -m unittest discover -s tests            →  1319 tests, OK (skipped=2)
python3 -m compileall -q work_runtime tests scripts   →  clean
python3 scripts/check_docs.py                    →  125 markdown files, 676 local links, 0 broken
python3 scripts/check_site.py                    →  2 pages, 0 findings
python3 -m work_runtime workflow-demo            →  the chapters, 2 external effects
```

`work_runtime/runtime.py` and `work_runtime/adapters.py` are still byte
unchanged; the byte pin in `tests/test_publishing_compensation.py` holds.

### New limitations to disclose

* A human node that declares an output can only complete through the
  `record_decision` command: the plain evidence path cannot carry the
  record. The decision is still admitted on that path, but the node waits
  for the record. This is deliberate — the record must travel with the
  decision under one compare-and-swap.
* The `input_digest` covers the declared `inputs` only. A subject is pinned
  separately (`subject.revision`, `subject.digest`) and a decision must
  cover it exactly; the two digests are documented separately rather than
  merged.
* The report of a node is ordered by the definition's declared criteria, so
  the order of the entries does not depend on which judge produced them.
