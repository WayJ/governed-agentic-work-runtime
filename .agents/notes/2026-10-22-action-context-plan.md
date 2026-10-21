# Scoped implementation plan — the native automatic-action context API

Task: `task_694a38d13eed`, dispatch `ctx_c3a9ee4ad9cf`.
Branch: `WayJ/gawr-mixed-node-design`, baseline `345706e`.

## Problem

An adapter's `execute`/`lookup` receives the **native business key** and
nothing else. From that key alone the adapter cannot tell

* which operation it is executing,
* which workflow node proposed it, at which attempt, with which input digest,
* which pinned definition, contract and plan revision it belongs to,
* which exact subject object (name, revision, digest, body) it acts on,
* which session/task envelope the work was started in.

`runtime.get_operation` takes the operation **UUID**, not the business key.
`engine.instance(work_id)` is a *latest* read model: it omits `operation_id`
and it omits the historical attempts. Neither can answer the question, and a
platform adapter must not reach into SQLite or the schema to find out.

## Scope of this slice

1. **One public, local, read-only API on the engine**:
   `WorkflowEngine.suggest_action_context(business_key)`. It resolves
   `operations.business_key` → operation uuid → **exactly one**
   `workflow_nodes` action instance that references that `operation_id`, and
   returns the stored facts that describe the action.
2. **One consistent read snapshot.** Every row the answer is built from is
   read inside a single deferred SQLite transaction, so the operation, the
   node instance, the subject object, the template and the work are always
   the same committed state.
3. **Stable context and mutable current state are separate.** The stable
   part carries the fixed identity (key, operation/work ids, actor,
   capability, contract/plan revision, node/attempt/input digest, template
   id/version/digest, subject ref/digest/body, the original session/task
   envelope). The mutable part carries what may still change (operation
   status, dispatch state, node state, work status, state version,
   cancellation, the current task document).
4. **Fail closed.** A zero-link operation, an ambiguous (multi-link)
   operation, a wrong-kind link, or an inconsistent work/object/digest/
   template link is **refused**, never guessed and never partially answered.
5. **Defensive copies.** The answer is a copy: mutating it cannot change the
   store.
6. **No authority.** The API never routes, never writes, never grants a
   capability and never calls an external system. It is a description of
   stored facts, not a permission.

## Out of scope

* `dsh-saas`, the HTTP bridge (`workflow_server.py`), the GUI wave.
* Any change to `work_runtime/runtime.py` and `work_runtime/adapters.py`
  (the freeze exception of S16 does not apply to this slice).
* Any change to the adapter `execute` ABI: the adapter keeps its exact
  three-positional-argument (or opted-in four-argument) call.
* Authentication, tenancy, multi-coordinator support, distributed
  exactly-once.

## The API

```python
engine.suggest_action_context(business_key) -> dict
```

One of three shapes, always the same outer keys:

| shape | keys |
|---|---|
| absence | `{"present": False, "businessKey": ..., "code": "ACTION_CONTEXT_ABSENT"}` |
| refusal | `{"present": False, "businessKey": ..., "code": "ACTION_CONTEXT_REFUSED", "reason": ..., "detail": ...}` |
| context | `{"present": True, "businessKey": ..., "context": {...}, "current": {...}}` |

`WorkflowError` is raised only for API misuse (a key that is not a nonempty
string). The method never raises for a missing, ambiguous or corrupt
linkage: an adapter that asks inside `execute` must not turn a refusal into
a runtime `outcome_unknown`.

### The stable `context`

```
businessKey, operationId, workId, node, attempt, actor, capability,
contractRevision, planRevision, inputDigest,
contract   {policyId, policyVersion, goal, revision}
template   {id, version, digest}
subject    {name, revision, digest, body}
envelope   {sessionId, participants, parameters, owner, runner}
```

### The mutable `current`

```
operationStatus, dispatchState, externalId,
nodeState, nodeOutcome, nodeReason,
workStatus, workflowStatus, stateVersion,
cancelled, cancellation,
task {document, documentDigest, documentRevision}
```

### The resolution, in one snapshot

1. `operations WHERE business_key = ?` → no row ⇒ **absence**.
2. Every `workflow_nodes` row is scanned for `operation_id == <uuid>`:
   * zero links ⇒ refused `OPERATION_NOT_WORKFLOW_BOUND` (a manual
     `propose_action` operation is not a workflow action);
   * more than one link ⇒ refused `OPERATION_LINK_AMBIGUOUS`.
3. The link must belong to the operation's work
   (`OPERATION_LINK_WORK_MISMATCH`) and its node must be an **action** node
   (`OPERATION_LINK_WRONG_KIND`).
4. The node's declared capability must be the operation's capability
   (`OPERATION_CAPABILITY_MISMATCH`); the operation's contract revision must
   be the work's contract revision (`OPERATION_CONTRACT_MISMATCH`).
5. The published template must still hash to the digest the work pinned
   (`OPERATION_TEMPLATE_MISMATCH`).
6. The instance's subject must be the operation's object binding
   (`OPERATION_SUBJECT_MISMATCH`), the object row at that exact revision
   must exist (`OPERATION_OBJECT_UNAVAILABLE`), and its digest must be the
   digest the operation and the instance carry
   (`OPERATION_OBJECT_DIGEST_MISMATCH`).
7. The instance must carry an input digest
   (`OPERATION_INPUT_DIGEST_MISSING`).

The node is never inferred from the capability, the work's cursor or the
latest instance: only the stored `operation_id` on the node instance links
the two.

## Deliberate consequences (disclosed)

* **One operation, one node instance.** When a store links several node
  instances to one operation, the context is refused. This includes the
  case where a rework re-proposes *the same* operation for a second attempt
  of the same node: the operation is then referenced twice and the context
  is refused as ambiguous. Completed, cancelled and historical operations —
  one node instance each — stay resolvable, which is what receipt
  reconciliation needs.
* **No original compare-and-swap is invented.** The state version at
  proposal time is not persisted as such; only the *current* state version
  is reported, and it is reported under `current`.
* **The Work's own document is mutable** (`revise_document`), so it is
  reported under `current.task`, not as an original fact. The *bound
  subject* is the frozen material of the operation.
* **The name clash is real.** `AdapterContract.supports_action_context` is
  an older, unrelated opt-in: it means "this adapter receives the explicit
  `action=` and `compensates=` execution context". The new API is the
  *workflow* action context and has nothing to do with it. The docs say so.

## TDD sequence

| step | test file | what it proves |
|---|---|---|
| 1 | `tests/test_workflow_action_context.py` | the context is readable **inside the adapter's `execute`**, on a really created operation |
| 2 | same | the context survives a runtime reopen and is readable through the adapter's `lookup` |
| 3 | same | same-capability distinct nodes map to their own operation and node |
| 4 | same | a historical attempt keeps its own operation, subject revision and attempt |
| 5 | same | an unknown key is a documented absence; a manual operation is refused |
| 6 | same | a corrupt/ambiguous linkage is refused (crafted rows) |
| 7 | same | the answer is a copy: mutating it does not change the store |
| 8 | same | the read changes no state version and writes no event |
| 9 | same | a cancelled work keeps its context and grants no execution |
