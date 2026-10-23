# Report — controlled source replacement and transitive revalidation

Task `task_cd5a605af6fc`, dispatch `ctx_cb2dc3e63fc1`.
Branch `WayJ/gawr-material-wait`, baseline `ed0efd9` (the material-wait slice).

## What was built

A trusted manager can replace the archived source material of a running
workflow and revalidate the consumers that judged it — in the same
workflow and session. The replacement is a bounded, pre-effect
intervention: the **source read is never re-run**, no business effect is
ever replayed, the quality allowance is never raised, and the number of
material generations is bounded by a fixed core allowance that a
definition may only tighten.

| id | deliverable | outcome |
|---|---|---|
| C1 | `work_runtime/workflow.py` — the command `replace_material`, the consumer/transitive closure, the attestation, the material attempt, the queue-driven revalidation | shipped |
| C2 | `work_runtime/workflow_spec.py` — the optional node field `material_generations` | shipped |
| C3 | `work_runtime/workflow_server.py` — the route `POST …/material/replace`, the status table, the view | shipped |
| C4 | `tests/test_workflow_material_revalidation.py` — 19 tests over a real store | shipped |
| C5 | `tests/test_workflow_material_revalidation_http.py` — 14 tests over a real service on a real store | shipped |
| C6 | docs — `workflow-runtime.md` (§14), `workflow-api-contract.md`, `verification.md` (W154–W167) | shipped |
| C7 | `tests/test_workflow_spec.py` — 4 lint tests for the material budget | shipped |

`work_runtime/runtime.py` and `work_runtime/adapters.py` are **untouched**:
the command rides the existing `WORKFLOW_COMMANDS` seam, so there is no
schema change and no new table. The byte pin in
`tests/test_publishing_compensation.py` still holds.

## The design

### One command, one transaction

`replace_material` is an ordinary runtime command: a compare-and-swap on
`state_version`, a durable receipt under `(actor, commandId)`, one
transaction, and a replay admitted only while the manager authority
still holds.

The **source read is never re-run**. The core never re-proposes the
source node's operation, never re-dispatches it and never reuses its
operation key. The platform acquires the archive; the core receives only
the frozen manifest and records it as a new revision of the material the
source node produced. The source node keeps its attempt, its effect, its
receipts and its accepted revision — and the **attestation** says so
explicitly: the previous acceptance does not cover the new revision.

### The closure

Computed over the **stored instances**, not over the published graph: a
node is a consumer when it judged the material or what was derived from
it; a node still working on the material is in the closure too. The
closure holds **only the consumers that were instantiated** — a node
without history has nothing to invalidate and proceeds through the
ordinary routing. The chain is ordered: a consumer comes after the node
whose output it judged.

### The two allowances, separate and never raised

| | bound | counts |
|---|---|---|
| the quality allowance | `max_attempts` (declared) | the attempts that are **not** material attempts |
| the material allowance | **one generation per workflow** (a core bound) | the revalidations |

A definition may only **tighten** the material allowance: a node that
declares `material_generations: 0` may not be revalidated. A definition
published before the field existed keeps the core allowance — the live
safety template is **not** mutated to make a revalidation possible.

The attempt number stays **monotonic** and is never reused, and every
attempt records the **trigger** that opened it (`initial`, `quality`,
`material`), so the history of a node is never ambiguous. A material
attempt that fails on quality opens **no further attempt**.

### What blocks the revalidation

A prepared, unknown or confirmed business effect in the affected branch
(`WORKFLOW_REVALIDATION_EFFECT_PRESENT`) — and a **human judgement** in
that branch, because an approval granted on the replaced material is a
business fact the revalidation would contradict. Also: an exhausted
budget, a stale ticket, a source that produced nothing, a work that is
cancelling or finalized, and an acceptance while a revalidation is
pending (`WORKFLOW_REVALIDATION_PENDING`).

## The coordinator's three adjustments (all in)

1. **The live definition is preserved.** The core allowance is one
   generation per workflow, a core bound rather than a caller-supplied
   number; a definition may only tighten it. A legacy template without
   the field works, and the tests cover it
   (`test_the_core_allowance_carries_a_legacy_definition`) and the
   used-up node (`test_a_used_up_node_gets_a_fresh_material_attempt`:
   three quality attempts used, the material attempt is number 4).
2. **The frozen manifest is the platform's.** The core accepts the
   bounded manifest as an opaque reference (≤ 4 KiB, no invented
   `archiveId`/`revision`/`capturedAt`), validates the kind, the work and
   the source, refuses a raw location, a credential or the raw material,
   and writes it wrapped as `{"sourceReference": <manifest>}` — the same
   envelope the source output carries, so the declared structural
   validator still judges it.
3. **The closure holds only instantiated consumers**, a material attempt
   has no automatic further retry, and a human approval in the affected
   branch blocks the revalidation.

## RED/GREEN evidence

| step | RED | GREEN |
|---|---|---|
| the definition's budget | 3 of 4 lint tests fail (`NODE_FIELD_UNKNOWN`) | `test_workflow_spec.MaterialGenerationLintTests` → 4 tests, OK |
| the replacement | 5 tests fail (`COMMAND_UNSUPPORTED`) | `test_the_manager_replaces_the_source_material`, `test_the_source_read_is_never_rerun`, `test_a_refused_replacement_mutates_nothing` → OK |
| the material attempt | 4 failures + 1 error: the cursor routed past the invalidated node, the wait was not invalidated, the ticket did not move | `test_the_affected_chain_re_runs_on_material_attempts` → OK |
| the coordinator's adjustments | the global ticket formula, the producer-only guard, the invented manifest fields and the automatic retry after a material failure | `test_the_core_allowance_carries_a_legacy_definition`, `test_a_used_up_node_gets_a_fresh_material_attempt`, `test_a_human_approval_in_the_branch_blocks_the_revalidation`, `test_every_consumer_of_the_source_is_invalidated` → OK |
| the bridge | the route answered 404 | `PYTHONPATH=.:tests python3 -m unittest test_workflow_material_revalidation_http` → **14 tests, OK** |
| the whole slice | — | `PYTHONPATH=.:tests python3 -m unittest test_workflow_material_revalidation test_workflow_material_revalidation_http` → **33 tests, OK** |
| the full suite | the baseline before this slice was 1556 tests, OK (skipped=2) | **1593 tests, OK (skipped=2)** — 1556 + 33 new in the two revalidation files + 4 new lint tests in `tests/test_workflow_spec.py`; the byte pin of `runtime.py` still holds |

The gates: `python3 scripts/check_docs.py` (127 files, 682 links, 0
broken); `python3 -m compileall -q work_runtime tests scripts`;
`python3 -m work_runtime demo`; `python3 scripts/check_site.py`.

## The exact wire

```
POST /v1/workflows/instances/{workId}/material/replace
{
  "actor": "platform",              // or "actorId"; two different ones → 400 ACTOR_CONFLICT
  "commandId": "replace-1",
  "expectedVersion": 17,
  "requestVersion": 1,              // any other value → 400 MATERIAL_WAIT_VERSION_UNSUPPORTED
  "node": "s00",                    // the source node
  "sourceReference": {              // the frozen manifest, ≤ 4 KiB
    "kind": "business-material-snapshot",
    "referenceId": "REF-2", "workflowId": "W-1", "sourceNode": "s00",
    "documentDigest": "…", "snapshotDigest": "…", "scope": "records"
  },
  "reason": "the archive was refreshed",
  "waitingNode": "n03",             // optional
  "waitingTicket": "…"              // optional; must still be current
}
```

`200` the instance view with:

* `materialReplacement: {node, attestation, affected, generation, resultStateVersion}`,
* `materialRevalidation: {state, generation, attestation, affected, queue}`,
* `attestation: {kind, adoptedBy, adoptedAt, sourceNode, sourceAttempt, object, from{revision,digest}, to{revision,digest}, claim, reason}`,
* `nodes[].trigger` (`initial` / `quality` / `material`),
  `nodes[].materialGeneration`, `nodes[].inputGeneration`.

Refusals: `400` MATERIAL_REPLACE_INVALID / MATERIAL_WAIT_VERSION_UNSUPPORTED
/ ACTOR_REQUIRED / ACTOR_CONFLICT / WORK_MISMATCH / COMMAND_ID_REQUIRED /
EXPECTED_VERSION_REQUIRED; `403` AUTHORITY_DENIED; `404` WORK_UNKNOWN /
WORKFLOW_NODE_UNKNOWN; `409` STATE_VERSION_CONFLICT / COMMAND_ID_REUSED /
CANCELLATION_ACTIVE / WORKFLOW_FINALIZED / WORKFLOW_SOURCE_NOT_PRODUCER /
WORKFLOW_SOURCE_NOT_COMPLETED / WORKFLOW_WAITING_TICKET_STALE /
WORKFLOW_REVALIDATION_EFFECT_PRESENT /
WORKFLOW_REVALIDATION_BUDGET_EXHAUSTED / WORKFLOW_REVALIDATION_NO_CONSUMERS
/ WORKFLOW_REVALIDATION_PENDING; `422` WORKFLOW_SOURCE_REFERENCE_INVALID /
WORKFLOW_SOURCE_REFERENCE_TOO_LARGE.

## The scope boundary (corrected)

An earlier summary of this slice said that the "pre-effect transitive
revalidation" was still to be dispatched. That was **wrong**: the
pre-effect revalidation **is implemented** — it is this slice, and it is
what the coordinator reviews next.

What is intentionally **not** built is a **post-effect amendment**: a
replacement of the material of a branch that has already produced a
business effect. Such a branch is refused
(`WORKFLOW_REVALIDATION_EFFECT_PRESENT`) — the effect is never replayed
under its old operation key, and the effect is never rewritten. There is
no after-effect change workflow in this design, and none is planned
here: the safety of the effect boundary is the reason the refusal
exists, not a gap to be filled later.

## The remaining risks

* **The revalidation re-runs agents, not effects.** The affected
  consumers are agent nodes here; a branch that contains an effect is
  refused, so no effect is ever produced twice. A revalidated *agent*
  may produce a new candidate that passes the validator — that is the
  point of the revalidation, and the manager owns the decision.
* **The material reference is opaque.** The core never resolves it and
  never fetches anything: the platform acquires the archive, the core
  records the manifest. The core does not check that the archive holds
  the material the manifest names.
* **The one-generation allowance is per workflow.** A second replacement
  in the same workflow is refused, whatever the reason; a workflow that
  needs two refreshes needs a new work.
* **The closure is data-driven.** It follows what the nodes judged, not
  what the graph says. A node that will consume the material later, and
  that has no history yet, is not invalidated — it runs normally on the
  new material.
* **The source node's own acceptance is not re-derived.** The
  replacement does not re-run the source read, so the source node's
  accepted revision 1 remains the fact it was; the new revision is the
  manager's attestation, and the two are never merged.

## The commits

| commit | content |
|---|---|
| `9e73f30` | feat: a manager replaces the source material under an attestation |
| `2656341` | feat: a revalidated node runs on a material attempt, not a quality one |
| `3d51368` | fix: the material budget is a fixed core allowance the definition may tighten |
| `6dd8dd2` | test: the closure, the effects and the legacy definition |
| `154969c` | test: the old review, the old acknowledgement and the restart |
| `1d73419` | feat: the bridge exposes the controlled source replacement |
| `dcd5f05` | docs: the controlled replacement, the material budget and the limits |

Nothing was merged and nothing was pushed: the branch is left for the
integration worker.
