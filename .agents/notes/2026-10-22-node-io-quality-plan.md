# Scoped implementation plan — per-node IO/quality for action and wait nodes

Task: `task_835d9f6650d1`, dispatch `ctx_c1c61469b029`.
Branch: `WayJ/gawr-mixed-node-design`, baseline `d79cbc4`.

## Problem

`_settle_action` completes a node on `confirmed_succeeded` alone and
`_settle_wait` completes on any verified proof of the declared kind. Neither
reads the node's declared criteria, neither validates the node's output, and
neither produces a validated named output. An automatic node's external effect
and its output quality are therefore not connected, and a wait can be
satisfied by a proof that belongs to an earlier attempt.

## Scope of this slice

1. **Inputs are validated before the effect.** A node's declared input
   validation runs the pinned validator (not only the shape descriptor)
   during activation. A failing input blocks the node; an action node that is
   blocked never proposes an operation, so no external effect is authorized.
2. **The actual adapter receipt is persisted.** The engine captures the
   receipt the adapter really returned (`execute`/`lookup`), bounded, with its
   origin (operation id, capability, business key, external id, digest,
   adapter class). The receipt schema and the digest/action linkage stay
   authoritative: a receipt that does not match the operation's document
   digest or capability is refused.
3. **Action nodes are quality controlled.** An action node may declare
   `output` (named object + shape/version-pinned validator) and `checks`.
   On `confirmed_succeeded` the engine validates the receipt's business
   payload, records the per-check report (method, criterion version, validator
   id/version, reviewed input/output digests, reason, evidence) and writes the
   validated payload as a named workflow object plus a workflow event proof.
   A failing output does **not** fake an external failure: the effect stays
   recorded as succeeded, the node fails with `WORKFLOW_OUTPUT_INVALID`, and
   the effect is never dispatched again.
4. **Wait nodes are quality controlled and bound.** A wait node may declare
   `output` and `checks`. A wait that matches verified evidence records the
   binding it matched on — work, node, attempt, object revision and digest,
   and the event provenance (source and event id). A wait that declares
   `match.bind` only accepts a proof of the bound node at the bound attempt,
   so an old proof never satisfies a new attempt.
5. **Compatibility.** A node that declares no output and no checks keeps the
   previous behaviour, and the read model says so explicitly
   (`quality.declared = false`, `quality.mode = "undeclared"`). No quality is
   invented for it and none is implied.

## Out of scope

`dsh-saas`, the GUI wave, authentication, distributed exactly-once, any change
to `work_runtime/runtime.py` (the byte pin in
`tests/test_publishing_compensation.py` stays valid) and any change to the
async `review_task` and human decision paths.

## Wire and read model

* Definition: `action`/`wait` nodes may carry `output`
  (`{object, evidence_kind?, validation{shape, validator, validator_version}}`)
  and `checks`; `wait.match` may carry `bind` (`{node, attempt?}`).
* Read model (`GET /v1/workflows/instances/{workId}`, node entries): `quality`,
  `effect`, `waitMatch`, `outputQuality` (the recorded verdict of the output
  validation) are added; `attempts` (`GET .../nodes/{node}/attempts`) carries
  the same per-attempt records.

## TDD sequence

1. `tests/test_workflow_node_quality.py` — written first, RED before the
   implementation: declared validator failure blocks downstream, missing
   per-check report, wrong/stale evidence, output provenance, replay after an
   external success, effect count stays one.
2. `work_runtime/workflow_spec.py` — the lint additions.
3. `work_runtime/workflow.py` — capture, validation, binding, read model.
4. `work_runtime/workflow_demo.py` — the N06 order output, the dispatch wait
   node, N07/N08 reading the order, the payload-carrying adapter.
5. Docs: `docs/workflow-runtime.md`, `docs/workflow-api-contract.md`,
   `docs/verification.md`, `README.md`, `README.zh-CN.md`.

## Known limitations to disclose

* The receipt is captured by the engine where it calls the adapter
  (`pump`/`recover`); an operation resolved by a runtime path outside the
  engine is back-filled by an authoritative `lookup` of the same business key.
* The wait binding compares the producing node's *current* attempt, so a wait
  that names an explicit attempt pins that attempt exactly.
