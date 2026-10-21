# Worker report — the native automatic-action context API

Task: `task_694a38d13eed`, dispatch `ctx_c3a9ee4ad9cf`.
Branch: `WayJ/gawr-mixed-node-design`, baseline `345706e`.
Plan: [2026-10-22-action-context-plan.md](2026-10-22-action-context-plan.md).
Commit: **`87de33d`** — `feat: the native action context of an automatic action`.

## What was built

A small public, **local**, **read-only** API on the engine:

```python
WorkflowEngine.suggest_action_context(business_key: str) -> dict
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

## The exact API shape

Three answers, always the same outer keys:

```python
# 1. absence — no operation carries that key
{"present": False, "businessKey": "…", "code": "ACTION_CONTEXT_ABSENT"}

# 2. refusal — the operation exists, the linkage does not hold
{"present": False, "businessKey": "…", "code": "ACTION_CONTEXT_REFUSED",
 "reason": "OPERATION_LINK_AMBIGUOUS", "detail": "…"}

# 3. context
{"present": True, "businessKey": "…",
 "context": {
   "businessKey": "…", "operationId": "…", "workId": "…",
   "node": "n06", "attempt": 1,
   "actor": "coordinator", "capability": "work.dispatch",
   "contract": {"policyId": "…", "policyVersion": "…", "goal": "…", "revision": 1},
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
`OPERATION_LINK_WRONG_KIND`, `OPERATION_LINK_ATTEMPT_MISMATCH`,
`OPERATION_IDENTITY_MISMATCH`, `OPERATION_BODY_INVALID`,
`OPERATION_WORK_UNKNOWN`, `OPERATION_WORK_INVALID`,
`OPERATION_WORK_NOT_BOUND`, `OPERATION_NODE_UNKNOWN`,
`OPERATION_CAPABILITY_MISMATCH`, `OPERATION_TEMPLATE_UNKNOWN`,
`OPERATION_TEMPLATE_MISMATCH`, `OPERATION_CONTRACT_MISMATCH`,
`OPERATION_SUBJECT_MISSING`, `OPERATION_SUBJECT_MISMATCH`,
`OPERATION_OBJECT_UNAVAILABLE`, `OPERATION_OBJECT_DIGEST_MISMATCH`,
`OPERATION_OBJECT_BODY_INVALID`, `OPERATION_OBJECT_BODY_MISMATCH`,
`OPERATION_DOCUMENT_MISMATCH`, `OPERATION_INPUT_DIGEST_MISSING`.

## RED/GREEN evidence

| step | RED | GREEN |
|---|---|---|
| the whole slice | `PYTHONPATH=.:tests python3 -m unittest test_workflow_action_context` against the baseline engine → **16 tests, 2 failures + 13 errors** (every one of them: `'WorkflowEngine' object has no attribute 'suggest_action_context'`) | same command → **16 tests, OK** |

The RED was reproduced against the committed baseline: `git checkout 345706e
-- work_runtime/workflow.py`, run, restore (`shasum -a 256
work_runtime/workflow.py` → `224bb58d…`, identical to the committed file).

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
| `test_two_nodes_of_the_same_capability_map_to_their_own_action` | two action nodes of **one** capability on two subjects: each operation maps to its own node and subject |
| `test_a_historical_attempt_keeps_its_own_action` | a superseded attempt keeps its operation, its subject revision (1) and its attempt (1); the live attempt (2) has its own operation and revision (2) |

## The gates

| gate | command | result |
|---|---|---|
| full suite | `python3 -m unittest discover -s tests` | **1365 tests, OK (skipped=2)** — the 16 new tests included, no regression |
| contracts (docs) | `python3 scripts/check_docs.py` | 126 markdown files, 680 local links, **0 broken** |
| syntax | `python3 -m compileall -q work_runtime tests scripts` | clean |
| demo | `python3 -m work_runtime demo` | exit 0 |
| site | `python3 scripts/check_site.py` | 2 pages, 0 findings |

## Files

| file | change |
|---|---|
| `work_runtime/workflow.py` | +257: `suggest_action_context`, its helpers, the two codes |
| `tests/test_workflow_action_context.py` | new: 16 tests |
| `docs/workflow-runtime.md` | new §11 *The native action context* (§12 is the old §11) and a pointer in §6 |
| `docs/verification.md` | W59–W66; the stale matrix header `(W01–W16)` corrected to `(W01–W66)` |
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
   `revise_document`) is reported under `current.task`.
3. **The name clash is real.** `AdapterContract.supports_action_context` is
   an older, unrelated opt-in (the adapter receives the explicit `action=`
   and `compensates=` execution context). The new API is the *workflow*
   action context. The docs say so explicitly.
4. **The link scan is O(node instances).** `_operation_links` reads every
   `workflow_nodes` row and parses its body, so a cross-work link is
   detected (a corrupt store is refused, not half-answered). The store is
   local and small; a very large store would want an index on the
   operation id.
5. **The HTTP bridge does not expose it.** The brief asked for a *local*
   API; `work_runtime/workflow_server.py` is untouched.
6. **The refusal is a value, not an exception.** A caller that ignores
   `present` cannot mistake a refusal for a context: the `context` and
   `current` keys exist only when `present` is true.
