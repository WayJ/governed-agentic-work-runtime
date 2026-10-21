# Worker report — the native automatic-action context API

Task: `task_694a38d13eed`, dispatch `ctx_c3a9ee4ad9cf`.
Branch: `WayJ/gawr-mixed-node-design`, baseline `345706e`.
Plan: [2026-10-22-action-context-plan.md](2026-10-22-action-context-plan.md).

Commits (development branch only — nothing was merged or pushed):

| commit | what |
|---|---|
| `87de33d` | `feat: the native action context of an automatic action` — the API and its tests |
| `1e8b9c4` | `docs: the worker report of the native action context` |
| `4f89df5` | `fix: the action context is named, historical and self-consistent` — the three items of the coordinator's review |
| see below | `fix: the stable context does not move when the work does` — the two drifts of the follow-up dispatch |

## What was built

A small public, **local**, **read-only** API on the engine:

```python
WorkflowEngine.action_context(business_key: str) -> dict
```

It resolves `operations.business_key` → the operation uuid → **exactly one**
`workflow_nodes` action instance that references that `operation_id`, and
returns the stored facts that describe the action. Every row is read inside
**one deferred transaction**, so the answer always describes one committed
state.

Nothing else changed: `work_runtime/runtime.py` keeps its S16 digest
(`19555fcfe1e602ae6598d5ef7392536c3bc19171129686516c53fcda63d8c7ac`) and
`work_runtime/adapters.py` keeps its byte pin
(`ce132f24d84c17a083bcf0b61bf90e1c62ff75faf2ec52fe2c7348ab86b6985e`). The
adapter `execute` ABI is untouched: the adapter still receives exactly the
native business key.

## The coordinator's review, and what it changed

| review item | answer |
|---|---|
| **the name**: `action_context` / `read_action_context`, not `suggest_action_context` — the read resolves a *real persisted relation*, it does not suggest a context that may or may not be there | `WorkflowEngine.action_context(business_key)`. The old name is gone from the code, the tests and the docs. |
| **the contract after a migration**: the equality of `work.contract.revision` and the historical `op.contract_revision` refused the lookup of every effect produced before a `migrate_policy`. The historical context must survive; the current difference belongs to the observation; an unrecoverable snapshot must be an explicit boundary and never an invention. | The stable `context.contract` is the **historical** contract, recovered from the event ledger (`ContractBound`, and every `PolicyMigrated` records the contract it replaced). `context.contract.source` says where it came from: `current` (the work's contract *is* the action's), `ledger` (recovered from the ledger) or `unknown` (the ledger does not hold that revision — the revision is reported, the identity is `null`, nothing is invented). The contract in force now is an observation under `current.contract` / `current.contractRevision`. A migration test proves the historical lookup. |
| **the redundant consistency**: `operations` row `work_id == body.work_id`, `workflow_nodes` row `node`/`state == body.node`/`body.state` | Both are checked and a row that disagrees with its body is **refused**: `OPERATION_ROW_INCONSISTENT`, `NODE_ROW_INCONSISTENT`. The answer can never carry a self-contradictory relation. |
| **`current` may carry `planRevision` / `contractRevision`** | `current` carries `contract`, `contractRevision` and `planRevision` (the work's now) next to the stable `contractRevision` / `planRevision` (the operation's). |
| **the no-execution boundary in the returned status**, not only in prose | Every answer — absence, refusal and context — carries **`authorizesExecution: false`**. |
| **the original CAS**: the native operation does not store the proposal `expectedVersion`; do not synthesize the original CAS; `Runtime.dispatch`/`_resolve` carry the concurrency check themselves | No original CAS is synthesized anywhere. The *current* state version is reported under `current` and is never presented as the proposal's CAS. `runtime.py` was not touched. |
| **the platform** keeps the first request bytes and the native identity itself | Nothing was required on this side; the read is a description and never a substitute for that record. |
| **the scope stays narrow** | No new workflow framework, no adapter ABI change, no HTTP surface, no `dsh-saas`. |

## The exact API shape

Three answers, always the same outer keys:

```python
# 1. absence — no operation carries that key
{"present": False, "businessKey": "…", "code": "ACTION_CONTEXT_ABSENT",
 "authorizesExecution": False}

# 2. refusal — the operation exists, the linkage does not hold
{"present": False, "businessKey": "…", "code": "ACTION_CONTEXT_REFUSED",
 "reason": "OPERATION_LINK_AMBIGUOUS", "detail": "…", "authorizesExecution": False}

# 3. context
{"present": True, "businessKey": "…", "authorizesExecution": False,
 "context": {
   "businessKey": "…", "operationId": "…", "workId": "…",
   "node": "n06", "attempt": 1,
   "actor": "coordinator", "capability": "work.dispatch",
   "contract": {"policyId": "workflow-demo", "policyVersion": "demo-1",
                "goal": "workflow.completed", "revision": 1, "source": "current"},
   "contractRevision": 1, "planRevision": 1,
   "inputDigest": "…",
   "template": {"id": "…", "version": "…", "digest": "…"},
   "subject": {"name": "proposal", "revision": 1, "digest": "…", "body": {…}},
   "envelope": {"sessionId": "…", "participants": {…}, "parameters": {…},
                "owner": "coordinator", "runner": "workflow-runner"}},
 "current": {
   "operationStatus": "confirmed_succeeded", "dispatchState": "…", "externalId": "…",
   "nodeState": "completed", "nodeOutcome": "completed", "nodeReason": None,
   "workStatus": "active", "workflowStatus": "active", "stateVersion": 17,
   "contract": {"policyId": "workflow-demo", "policyVersion": "demo-2",
                "goal": "workflow.completed", "revision": 2},
   "contractRevision": 2, "planRevision": 1,
   "cancelled": False, "cancellation": None,
   "task": {"document": {…}, "documentDigest": "…", "documentRevision": 1}}}
```

`WorkflowError` is raised only for API misuse (a key that is not a nonempty
string). The method never raises for a missing, ambiguous or corrupt linkage:
an adapter that asks inside `execute` must not turn a refusal into a runtime
`outcome_unknown`.

### The refusal reasons

`OPERATION_NOT_WORKFLOW_BOUND` (no node proposed it — a manual
`propose_action` operation), `OPERATION_LINK_AMBIGUOUS` (several node
instances reference it), `OPERATION_LINK_WORK_MISMATCH`,
`OPERATION_LINK_WRONG_KIND`, `OPERATION_IDENTITY_MISMATCH`,
`OPERATION_ROW_INCONSISTENT`, `NODE_ROW_INCONSISTENT`,
`OPERATION_BODY_INVALID`, `OPERATION_WORK_UNKNOWN`, `OPERATION_WORK_INVALID`,
`OPERATION_WORK_NOT_BOUND`, `OPERATION_NODE_UNKNOWN`,
`OPERATION_CAPABILITY_MISMATCH`, `OPERATION_TEMPLATE_UNKNOWN`,
`OPERATION_TEMPLATE_MISMATCH`, `OPERATION_SUBJECT_MISSING`,
`OPERATION_SUBJECT_MISMATCH`, `OPERATION_OBJECT_UNAVAILABLE`,
`OPERATION_OBJECT_DIGEST_MISMATCH`, `OPERATION_OBJECT_BODY_INVALID`,
`OPERATION_OBJECT_BODY_MISMATCH`, `OPERATION_DOCUMENT_MISMATCH`,
`OPERATION_INPUT_DIGEST_MISSING`.

## RED/GREEN evidence

| step | RED | GREEN |
|---|---|---|
| the whole slice | `PYTHONPATH=.:tests python3 -m unittest test_workflow_action_context` against the baseline engine → **19 tests, 3 failures + 15 errors** (every one of them: `'WorkflowEngine' object has no attribute 'action_context'`) | same command → **19 tests, OK** |

The RED was reproduced against the committed baseline: `git checkout 345706e
-- work_runtime/workflow.py`, run, restore (`shasum -a 256
work_runtime/workflow.py` → `b0f2770b…`, identical to the committed file).

Every test drives the **real** engine: the operations are created by the
real proposal path, the effects by the real adapter, the routing by the real
engine. Only the corrupt-linkage tests write rows by hand, because a corrupt
store is what they are about.

| test | what it proves |
|---|---|
| `test_the_context_is_readable_inside_the_adapter_execute` | the adapter reads the context **inside its own `execute`**; the stable part does not change while the effect is in flight, the mutable part does |
| `test_the_context_survives_a_process_reopen_and_is_readable_through_lookup` | a **fresh process** (`subprocess`, same store) reads the same context; the adapter's `lookup` path reads it too |
| `test_the_lookup_of_a_closed_effect_reads_the_same_context` | the lookup path of the adapter sees the same context |
| `test_an_unknown_key_is_a_documented_absence` | `ACTION_CONTEXT_ABSENT` |
| `test_a_malformed_key_is_refused` | `WorkflowError` for a key that is not a nonempty string |
| `test_a_manual_operation_is_refused` | an operation proposed by hand (a real `propose_action` on a work without a workflow) is `OPERATION_NOT_WORKFLOW_BOUND` |
| `test_a_mutated_answer_does_not_change_the_store` | the answer is a copy: a mutated answer leaves the rows byte-identical |
| `test_the_read_writes_no_event_and_changes_no_state_version` | three reads: no event, no state version, no node row changed |
| `test_a_cancelled_work_keeps_its_context_and_grants_no_execution` | a cancelled work keeps its context and dispatches nothing |
| `test_two_node_instances_of_one_operation_are_refused` | `OPERATION_LINK_AMBIGUOUS` |
| `test_a_link_of_another_kind_is_refused` | `OPERATION_LINK_WRONG_KIND` |
| `test_a_subject_that_does_not_match_the_operation_is_refused` | `OPERATION_SUBJECT_MISMATCH` |
| `test_an_object_with_a_broken_digest_is_refused` | `OPERATION_OBJECT_DIGEST_MISMATCH` |
| `test_a_capability_that_does_not_match_the_node_is_refused` | `OPERATION_CAPABILITY_MISMATCH` |
| `test_an_operation_row_that_disagrees_with_its_body_is_refused` | `OPERATION_ROW_INCONSISTENT` |
| `test_a_node_row_that_disagrees_with_its_body_is_refused` | `NODE_ROW_INCONSISTENT` |
| `test_two_nodes_of_the_same_capability_map_to_their_own_action` | two action nodes of **one** capability on two subjects: each operation maps to its own node and subject |
| `test_a_historical_attempt_keeps_its_own_action` | a superseded attempt keeps its operation, its subject revision (1) and its attempt (1); the live attempt (2) has its own operation and revision (2) |
| `test_a_migrated_contract_keeps_the_historical_action_readable` | after a real `migrate_policy` the action still resolves with the contract it was proposed under (`source` is `ledger`), and the contract in force now is an observation under `current` |

## The gates

| gate | command | result |
|---|---|---|
| full suite | `python3 -m unittest discover -s tests` | **1368 tests, OK (skipped=2)** — the 19 new tests included, no regression |
| contracts (docs) | `python3 scripts/check_docs.py` | 126 markdown files, 680 local links, **0 broken** |
| syntax | `python3 -m compileall -q work_runtime tests scripts` | clean |
| demo | `python3 -m work_runtime demo` | exit 0 |
| site | `python3 scripts/check_site.py` | 2 pages, 0 findings |

## Files

| file | change |
|---|---|
| `work_runtime/workflow.py` | `action_context`, its helpers, the two codes |
| `tests/test_workflow_action_context.py` | new: 19 tests |
| `docs/workflow-runtime.md` | new §11 *The native action context* (§12 is the old §11) and a pointer in §6 |
| `docs/verification.md` | W59–W68; the stale matrix header `(W01–W16)` corrected to `(W01–W68)` |
| `.agents/notes/2026-10-22-action-context-plan.md` | the scoped plan |

## Disclosed decisions and remaining risks

1. **One operation, one node instance.** The brief asks for *exactly one*
   linking node instance, and zero or several links are refused. A
   consequence: when a rework re-proposes **the same** operation for a
   second attempt of the same node (the subject was not revised, so the
   business key is unchanged), the store then references that operation
   twice and the context is refused as `OPERATION_LINK_AMBIGUOUS`. The
   completed, cancelled and historical operations — one instance each —
   stay resolvable, which is what receipt reconciliation needs. A family
   that needs the live attempt of a re-proposed operation would need a
   different rule; the coordinator should say so.
2. **No original compare-and-swap and no original task document.** Neither
   is persisted, so neither is reported. The *current* state version is
   reported under `current`, and the Work's document (mutable through
   `revise_document`) is reported under `current.task`. The concurrency
   control stays where the runtime already has it: `Runtime.dispatch` and
   `Runtime._resolve`.
3. **The historical contract is recovered, not reconstructed.** It comes
   from the event ledger. A revision the ledger does not hold keeps a null
   identity with `source: "unknown"` — the boundary is explicit, nothing is
   invented.
4. **The name clash is real.** `AdapterContract.supports_action_context` is
   an older, unrelated opt-in (the adapter receives the explicit `action=`
   and `compensates=` execution context). The new API is the *workflow*
   action context. The docs say so explicitly.
5. **The link scan is O(node instances).** `_operation_links` reads every
   `workflow_nodes` row and parses its body, so a cross-work link is
   detected (a corrupt store is refused, not half-answered). The store is
   local and small; a very large store would want an index on the
   operation id.
6. **The HTTP bridge does not expose it.** The brief asked for a *local*
   API; `work_runtime/workflow_server.py` is untouched.
7. **The refusal is a value, not an exception.** A caller that ignores
   `present` cannot mistake a refusal for a context: the `context` and
   `current` keys exist only when `present` is true, and every answer says
   `authorizesExecution: false`.

---

# Follow-up dispatch — the stable context correction

Task: `task_8e0f459eb1b6`, dispatch `ctx_827fecda5092`. The follow-up of
`task_694a38d13eed`.

## The two drifts, reproduced first

Both were reproduced against the committed code, with a real migration and
a real owner transfer on a really executed action:

| drift | before | after | why it drifted |
|---|---|---|---|
| `context.contract.source` | `"current"` | `"ledger"` | the provenance of the *recovery* was stored inside the stable contract, and the recovery path itself depends on whether the work has been migrated |
| `context.envelope.owner` | `"coordinator"` | `"coordinator-2"` | `envelope.owner` read the mutable `work.owner`, and a `transfer_owner` moves it |

RED, before the fix:

```
test_a_migrated_contract_keeps_the_historical_action_readable ... ERROR
    KeyError: 'contractProvenance'
test_the_stable_context_survives_a_migration_and_an_owner_transfer ... FAIL
    AssertionError: {… 'source': 'ledger'} != {… 'source': 'current'}
```

The exact drift, printed field by field:

```
DRIFT context.contract -> {… "revision": 1, "source": "current"}
                      => {… "revision": 1, "source": "ledger"}
DRIFT context.envelope -> {… "owner": "coordinator" …}
                      => {… "owner": "coordinator-2" …}
```

## The fix — exactly two fields moved

| moved out of `context` | moved into `current` |
|---|---|
| `context.contract.source` — how the historical contract was *retrieved* | `current.contractProvenance` = `{"source": "current" \| "ledger" \| "unknown", "revision": <the historical revision>}` |
| `context.envelope.owner` — the mutable owner of the work | `current.owner` — the owner of the work now |

Nothing else moved. `context.actor` (the actor of the operation) stays in
the stable context, `context.contract` keeps the immutable identity of the
contract the action was proposed under (`policyId`, `policyVersion`,
`goal`, `revision`), and `current.contract` keeps the contract in force
now. `authorizesExecution: false` is on every answer.

## The test that holds the line

`test_the_stable_context_survives_a_migration_and_an_owner_transfer`
(`tests/test_workflow_action_context.py`) captures the **complete** context
of a successful action, then runs a real `migrate_policy` **and** a real
`transfer_owner`, and asserts:

* `after["context"] == before["context"]` — the entire stable context, not
  one field of it;
* the observations do move: `current.contractRevision` is 2,
  `current.contract.policyVersion` is `"demo-2"`, `current.owner` is
  `"coordinator-2"`, `current.contractProvenance.source` is `"ledger"`;
* `after["current"] != before["current"]`;
* `after["authorizesExecution"]` is still false.

GREEN: `PYTHONPATH=.:tests python3 -m unittest test_workflow_action_context`
→ **20 tests, OK**.

## One residual drift, disclosed and NOT fixed in this slice

The stable context is the fact of the **stored operation**, and the
operation body is not immutable: when a prepared operation whose dispatch
was cancelled or held is **re-admitted**, the runtime rewrites it in place
(`actor`, `plan_revision`, `contract_revision`). The proposal-time values
are not persisted separately, so they cannot be recovered — and inventing
them is exactly what the brief forbids.

Reachable path, verified in this session: revise the plan (the prepared
operation is cancelled as `STALE_INTENT`), then propose the same object
binding again — the operation is re-admitted and `context.planRevision`
moves from 1 to 2 (and `context.actor` would move with it if another
principal re-proposed it).

This is **out of scope** for the two named drifts and was therefore left
alone; it is now stated in [workflow-runtime.md](../../docs/workflow-runtime.md)
under *What the context is not*.

**The coordinator's decision (independent review of `432f9ab`):** the
limitation is accepted, because the platform's business phase is prepared
exclusively inside the native `adapter.execute`, after the operation is
persisted as `dispatched`/`in_flight`, and its lookup reads that frozen
phase. The review asked for two things, and both are done in the follow-up
commit:

* the public API documentation states that the context reflects the
  **current native admission** before the dispatch and **stabilises** for
  dispatched/reconciled operations;
* the context is **not** claimed to be globally immutable across a
  pre-dispatch re-admission.

The docstring of `WorkflowEngine.action_context` and the whole of §11 of
[workflow-runtime.md](../../docs/workflow-runtime.md) now say exactly that.
No `runtime.py` edit was made in this slice.
