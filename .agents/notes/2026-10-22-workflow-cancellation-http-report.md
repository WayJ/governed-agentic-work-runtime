# Report — cancellation of a bound workflow through the private service

Task `task_6a40ecd234f1`, dispatch `ctx_769145cd082c`.
Branch `WayJ/gawr-mixed-node-design`, baseline `4d1348b`.

## What was built

| id | deliverable | outcome |
|---|---|---|
| C1 | `work_runtime/workflow_server.py` — `POST …/cancel`, `POST …/cancel/finalize`, `GET …/cancellation` | shipped |
| C2 | `work_runtime/workflow.py` — the routing pass stops for a cancelling or closed work | shipped |
| C3 | `tests/test_workflow_cancellation_http.py` — 12 tests over a real service on a real store | shipped |
| C4 | docs — `workflow-api-contract.md`, `workflow-runtime.md`, `runtime-boundaries.md`, `verification.md` (W121–W128) | shipped |
| C5 | `tests/test_publishing_compensation.py` — the conscious byte-pin update owed by the earlier `runtime.py` edit | shipped |

## The design: no second cancellation engine

The bridge forwards the runtime's own commands. `POST …/cancel` issues
`request_cancel {reason}`; `POST …/cancel/finalize` issues
`finalize_cancel {acknowledged_operations}`. Both ride the existing
compare-and-swap, the existing command dedup under `(actor, commandId)`
and the existing receipt store, and both are issued with the caller's
asserted `actor` — the core alone decides authority (the owner with
`work.manage`, or a `work.intervene` administrator), so a transport
request grants nothing by itself. Nothing in the cancellation path is
re-implemented: the active nodes and the pending intents are cancelled in
the command's own transaction, the never-dispatched prepared operations
are cancelled, and a dispatched or unknown effect is never pretended away.

## The bug the exposure found: a cancelled work restarted

The first test run failed for a reason that was not the routes: after a
`request_cancel`, the engine's own `advance` (which every
`engine.command` and every ticker pass runs) walked the completed chain
from the entry node and **opened a fresh attempt of a completed node** —
a new `agent_task` intent was created for a work whose cancellation was
active. That contradicts the documented "while the intent is active the
Work stops" and would, on an action node, have re-admitted a proposal
behind the cancellation. The routing pass now stops for a cancelling or
closed work: no re-opened node, no new intent, no re-admission. Evidence
intake, the verifier, expiry and the unknown-effect reconciliation keep
running — they never go through the routing pass.

## The safe read

`GET …/cancellation` answers, in one snapshot: `state`
(`none`/`requested`/`cancelled`), the work's status, outcome and state
version, the intent's `requestedBy` and `reason`, the `unresolvedOperations`
that block the closure, the `requiredAcknowledgements` — **exactly** the
successful operation ids the acknowledgement must name — and every
operation with its `externalId`, `status` and `dispatchState`. No payload
body, no credential.

## RED/GREEN evidence

| step | RED | GREEN |
|---|---|---|
| the new tests | all **12** fail against the pre-change core (`git checkout -- work_runtime/workflow.py work_runtime/workflow_server.py`): the routes answered 404 and a cancelled work was restarted behind its own cancelled nodes | `PYTHONPATH=.:tests python3 -m unittest test_workflow_cancellation_http` → **12 tests, OK** |
| the full suite | `python3 -m unittest discover -s tests` → 1472 tests, **1 failure**: the `runtime.py` byte pin, stale since the coordinator-approved generic-completion guard (`647033c`, `19555fcf…` → `1b9c73e6…`, disclosed in `docs/runtime-boundaries.md`) whose brief skipped the full suite | the pin is consciously updated to the disclosed digest with a comment naming the edit; **1472 tests, OK (skipped=2)** |

The stale pin was a dormant breakage from an earlier approved edit, not
from this slice: `runtime.py` is byte-identical to `647033c` here
(`1b9c73e6…`), and `adapters.py` is untouched throughout.

## The exact wire

`POST /v1/workflows/instances/{workId}/cancel`
`{"actor": "coordinator", "reason": "duplicates found", "commandId": "cancel-1", "expectedVersion": 7}`
→ `200` the instance view + `"cancellation": {"requested": true, "requestedBy": "coordinator", "reason": "duplicates found", "resultStateVersion": 8}`.

`GET /v1/workflows/instances/{workId}/cancellation`
→ `200 {"workId", "state", "status", "outcome", "stateVersion", "requestedBy", "reason", "unresolvedOperations", "requiredAcknowledgements", "operations": [{"operationId", "externalId", "status", "dispatchState"}]}`.

`POST /v1/workflows/instances/{workId}/cancel/finalize`
`{"actor": "coordinator", "acknowledgedOperations": ["<op>"], "commandId": "cancel-final-1", "expectedVersion": 9}`
→ `200` the instance view + `"cancellation": {"finalized": true, "requestedBy", "acknowledgedOperations", "resultStateVersion"}`.

Refusals: `400 ACTOR_REQUIRED / REASON_REQUIRED / ACKNOWLEDGEMENT_INVALID /
COMMAND_ID_REQUIRED / EXPECTED_VERSION_REQUIRED`; `403 AUTHORITY_DENIED`;
`409 STATE_VERSION_CONFLICT / COMMAND_ID_REUSED /
CANCELLATION_ALREADY_REQUESTED / CANCELLATION_NOT_REQUESTED /
OUTCOME_UNRESOLVED / CANCEL_ACKNOWLEDGEMENT_MISMATCH` (the required ids
as the error's `findings`) / `WORK_NOT_ACTIONABLE`; `404 WORK_UNKNOWN`
on the read.

## Remaining boundaries

* The acknowledgement is an admission, not a compensation: the closure
  retains the confirmed effects and their external ids.
* The cancellation read names operations only; the payload bodies stay
  where they are (named objects, receipts on node instances).
* The routing stop is engine behaviour, disclosed in
  `docs/runtime-boundaries.md` and `docs/workflow-runtime.md`.

## The review wave (commit a1bc07d)

The coordinator's review of the new surface found three things; all are
fixed with real negative evidence.

**1. A refused cancellation mutated the workflow (critical).** The
workflow cancellation hook ran in the runtime's `_apply` before
`request_cancel` checked the actor's authority and the duplicate-intent
gate, so a request refused `AUTHORITY_DENIED` had still cancelled the
nodes and intents (reproduced: `nodes same: False | intents same: False`
next to a rejected receipt and an unchanged version). The hook now runs
inside `_request_cancel`, after the payload, the authority and the
duplicate gate have all passed. `AuthorizationOrderingTests` asserts that
a denied actor, a malformed request and a duplicate request each leave
the node rows, the intent rows, the operation rows, the events and the
state version byte for byte unchanged.

**2. The read classified every failure as a missing work.** `cancellation()`
caught every exception as `WORK_UNKNOWN`; a store that cannot answer now
fails unavailable (500) and only a genuinely unknown work is a 404. The
two command routes classify an unknown work as `404 WORK_UNKNOWN` too
(previously a bare 400).

**3. An accepted cancellation could be reported back as a missing work.**
`request_cancel`/`finalize_cancel` called `instance()` after the accepted
command; a work whose creation is still between its stages has no bound
workflow, so the view failed. The routes now answer the accepted
cancellation summary with `"instanceView": "unavailable"` — the receipt
is the truth, never the view. `PartialCreationTests` proves it: the
command is accepted, the summary is returned, the immutable receipt reads
back accepted, and cancelling an unknown work creates nothing.

**The creation-in-flight protocol** is documented in
`docs/workflow-api-contract.md` with the routes: the routes never create
anything; a 404 is a missing work, never a fact about effects; the
platform reads the immutable command receipt first; an already-completed
work stays completed; an in-flight effect is never rolled back.

**The `runtime.py` edits, disclosed.** This task's preamble froze
`runtime.py`, and the coordinator's review explicitly authorized the
ordering fix within the GAWR bug scope. Two edits exist in total, both
disclosed in `docs/runtime-boundaries.md` with their digests:
`19555fcf…` → `1b9c73e6…` (the earlier generic-completion guard) →
`1edb3bc0…` (this ordering fix). The byte pin is consciously updated to
the final digest. `adapters.py` is untouched throughout.

RED/GREEN of the review wave: the three review cases
(`test_a_denied_actor_changes_nothing`,
`test_an_unknown_work_is_not_created_by_cancelling_it`,
`test_a_work_without_a_bound_workflow_may_be_cancelled`) fail against
`c875f7f` and pass now; the file is **17 tests, OK**; the full suite is
**1477 tests, OK (skipped=2)**.
