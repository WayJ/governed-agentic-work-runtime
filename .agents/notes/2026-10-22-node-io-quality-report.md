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
