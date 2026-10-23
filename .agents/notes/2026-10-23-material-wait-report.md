# Report — the material wait on the current agent node

Task `task_9d95016be745`, dispatch `ctx_499309a8a851`.
Branch `WayJ/gawr-material-wait`, baseline `4ccd36f`.

## What was built

Business-material waiting is a **core lifecycle state** in GAWR, distinct
from candidate-quality rework. A trusted-local manager parks the
workflow's current agent node because the material it needs is missing,
adopts the supplemented material, and resumes — without spending the
node's quality allowance and without re-running anything.

| id | deliverable | outcome |
|---|---|---|
| C1 | `work_runtime/workflow.py` — the node state `waiting`, the three commands, the dependency gate, the input generation | shipped |
| C2 | `work_runtime/workflow_server.py` — the three routes, the status table, the `materialWait` view | shipped |
| C3 | `tests/test_workflow_material_wait.py` — 60 tests over a real store | shipped |
| C4 | `tests/test_workflow_material_wait_http.py` — 19 tests over a real service on a real store | shipped |
| C5 | docs — `workflow-runtime.md` (§13), `workflow-api-contract.md`, `verification.md` (W132–W148) | shipped |

`work_runtime/runtime.py` and `work_runtime/adapters.py` are **untouched**
(`git diff --quiet` on both): the three commands ride the existing
`WORKFLOW_COMMANDS` seam, so no schema change and no new table were
needed. The byte pin in `tests/test_publishing_compensation.py` is
unchanged and still valid.

## The three commands

Ordinary runtime commands: a compare-and-swap on `state_version`, a
durable receipt under `(actor, commandId)`, one transaction, and a replay
admitted only while the manager authority still holds. The manager is the
work's owner with `work.manage` — the same trusted-local configuration
every other management mutation uses. The transport grants nothing.

| command | payload | effect |
|---|---|---|
| `request_material_wait` | `{node, attempt, input_digest, reason, request_version}` | the node instance enters `waiting` |
| `adopt_material` | `{node, attempt, name, object, request_version}` | a **new immutable revision**; the wait accepts it |
| `resume_material_wait` | `{node, attempt, request_version}` | the same attempt continues behind the gate |

`request_version` is `1`; another version is refused rather than
half-understood.

## What the wait does

* Parks the **current** node, and only an **agent** node in the state
  `running`, pinned to the exact attempt and `input_digest` the caller
  observed.
* **Keeps the attempt**: no rework attempt, no raised `max_attempts`, no
  spent quality allowance. A workflow that waited may still complete on
  the attempt it started with.
* **Withdraws the agent's intent** and refuses result acceptance
  (`WORKFLOW_NODE_WAITING`); nothing is stored.
* **Persists across a restart**: the routing pass is a no-op for a
  waiting node — no version bump, no event, no re-opened node.
* **Suspends the deadline**: a waiting node does not expire; the deadline
  is recomputed from the resume.
* The work reports `workflowStatus: "waiting"`; the view names the
  reason, the requester, the accepted dependencies and the adoptions.

## The gate, and the two corrections

The resume is admitted only when **every dependency the wait accepted is
still the object's current revision and digest** (the drift check) *and*
**a completed upstream node's acceptance still covers the material** (the
upstream check). Either failure refuses with
`INPUT_DEPENDENCIES_REQUIRE_REVALIDATION` and the exact drift as
findings, and **the wait is retained** — nothing is mutated.

The coordinator's two corrections are in, and they changed the design:

1. **An adoption may not bless a completed upstream's accepted output.**
   A node that completed accepted one exact revision of its output;
   writing a new revision of that object would be material no completed
   node ever accepted. Such an adoption is refused with the same code and
   the same findings, and no revision is written. Material that **no**
   completed node accepted — material supplied from outside the workflow —
   may be adopted. This is why the demonstration family (every object it
   names is produced by one of its own nodes) refuses the adoption, and
   why the focused family in the tests supplies its material from
   outside: the two families exercise the two sides of the rule.
2. **A same-input resume issues a new identity.** The `input_digest`
   (the result ticket) of a **resumed** node covers the declared inputs
   **and the node's input generation**; the generation increments on
   every resume, so a ticket issued before the wait is refused
   `WORKFLOW_INPUT_STALE` even when the object values are equal. A node
   that **never waited** keeps exactly the ticket it was given — the
   digest of its pinned inputs, unchanged — so the upgrade over a live
   instance never invalidates a pinned ticket or a review that bound it.
   The resumed prompt is a **new intent**
   (`wf:<work>:<node>:<attempt>:<kind>:<generation>`; generation 0 keeps
   the old id), so an old acknowledgement cannot swallow it.
3. **The guard is not producer-only.** It inspects the completed nodes
   that **pinned** a changed object, not only the one that produced it,
   and walks the chain of production behind the wait's dependencies: a
   node that judged material that moved on holds an acceptance that no
   longer covers what it judged, and everything it produced rests on it.
   So a change at the head of the chain (`sources` produced by S00, read
   by N01 and N02) refuses the reuse of the stale `intake` and `analysis`
   that were derived from it.
4. **The platform envelope is accepted.** The material routes take the
   principal as `actor` or `actorId`, and a `workId` in the body when it
   names the work of the path. A body that names two different actors
   (`ACTOR_CONFLICT`) or another work (`WORK_MISMATCH`) is refused
   rather than guessed at.

## RED/GREEN evidence

| step | RED | GREEN |
|---|---|---|
| the wait | 8 tests fail against the pre-change core (`COMMAND_UNSUPPORTED` — the command kinds did not exist) | `PYTHONPATH=.:tests python3 -m unittest test_workflow_material_wait` → the file is **60 tests, OK** |
| the adoption | 6 failures (`COMMAND_UNSUPPORTED`) | included in the 51 |
| the resume | 8 failures + 1 error (`COMMAND_UNSUPPORTED`; the cancellation path did not cancel a waiting node) | included in the 51 |
| the coordinator's corrections | the adopt of a completed upstream's output was **accepted** (the engine blessed a stale output); the ticket did **not** move on a same-input resume; the intent kept its old identity — 7 failures | pinned by `test_the_adoption_of_a_completed_upstream_output_is_refused`, `test_the_resume_moves_the_input_ticket_even_for_equal_material`, `test_the_resume_asks_again_under_a_new_intent_identity` |
| the second correction round | the ticket formula was global, so a generation-zero ticket changed on upgrade; the guard was producer-only, so the stale `intake`/`analysis` derived from a changed `sources` would have been reused — 3 failures | pinned by `test_the_generation_zero_ticket_is_legacy_compatible`, `test_a_node_persisted_before_the_upgrade_keeps_its_ticket`, `test_a_resumed_node_stale_raises_the_pre_upgrade_ticket`, `test_a_material_read_by_a_completed_node_stale_raises_the_resume` |
| the bridge | the three routes answered 404 | `PYTHONPATH=.:tests python3 -m unittest test_workflow_material_wait_http` → **19 tests, OK** |
| the full suite | baseline `1477 tests, OK (skipped=2)` before this slice | **1600 tests, OK (skipped=2)** after it (1477 + 51 + 16 new; the byte pin of `runtime.py` still holds) |

The gates: `python3 scripts/check_docs.py` (127 files, 682 links, 0
broken); `python3 -m compileall -q work_runtime tests scripts`;
`python3 -m work_runtime demo`; `python3 scripts/check_site.py`.

## The exact wire

```
POST /v1/workflows/instances/{workId}/material/wait
  {actor, commandId, expectedVersion, requestVersion: 1, node, attempt, inputDigest, reason}
POST /v1/workflows/instances/{workId}/material/adopt
  {actor, commandId, expectedVersion, requestVersion: 1, node, attempt, name, object}
POST /v1/workflows/instances/{workId}/material/resume
  {actor, commandId, expectedVersion, requestVersion: 1, node, attempt}
```

`200` answers the instance view plus `materialWait` / `materialAdoption` /
`materialResume`. The view carries `nodes[].materialWait` (state,
requestVersion, requestedBy, reason, requestedAt, inputDigest,
dependencies, adoptions, resumed) and `nodes[].inputGeneration`; while a
node waits, `allowedActions` offers `resume_material_wait` and **no**
`submit_node_result`.

Refusals: `400` MATERIAL_WAIT_VERSION_UNSUPPORTED / MATERIAL_WAIT_INVALID /
MATERIAL_ADOPT_INVALID / MATERIAL_RESUME_INVALID / ACTOR_REQUIRED /
COMMAND_ID_REQUIRED / EXPECTED_VERSION_REQUIRED; `403` AUTHORITY_DENIED;
`404` WORK_UNKNOWN / WORKFLOW_NODE_UNKNOWN; `409` STATE_VERSION_CONFLICT /
COMMAND_ID_REUSED / CANCELLATION_ACTIVE / WORKFLOW_FINALIZED /
WORKFLOW_NODE_WAITING / WORKFLOW_NODE_NOT_CURRENT /
WORKFLOW_NODE_NOT_WAITABLE / WORKFLOW_ATTEMPT_STALE / WORKFLOW_NOT_WAITING;
`422` INPUT_DEPENDENCIES_REQUIRE_REVALIDATION / WORKFLOW_INPUT_STALE /
WORKFLOW_MATERIAL_NOT_DEPENDENCY / WORKFLOW_MATERIAL_TOO_LARGE /
WORKFLOW_ADOPTION_LIMIT_EXCEEDED.

## The remaining boundaries

* **No transitive invalidation and no rewind.** When the material of a
  completed upstream moved on, the wait stays refused and the upstream
  needs the separate, bounded pre-effect revalidation the coordinator
  asked for as the follow-up slice. This slice does not rewind a
  completed node, does not grant it a new attempt, and does not raise any
  configured `max_attempts`.
* `revise_object` is **not** invalidation: it cancels the instances that
  are `running`, `blocked` or `submitted`, so a **waiting** instance is
  untouched — the wait stays in place and the gate, not the revision,
  decides the resume.
* A wait never opens an attempt and a resume never opens one; a
  side-effect node is never re-entered by a wait, and an unknown or
  confirmed operation is never altered.
* The adoption is bounded: 64 KiB of canonical JSON and sixteen
  adoptions per wait; only the material the wait is about may be adopted.
* The wait is refused on a cancelling work, and a cancellation cancels
  the waiting node (`WORK_CANCELLED`) instead of restarting it.
* The workflow acceptance refuses a waiting workflow: a waiting node is
  never terminal, so the workflow is not finished.

## Commits

| commit | content |
|---|---|
| `cb2e320` | feat: the engine owns a manager-requested material wait |
| `8eda82a` | feat: a manager adopts external material under an active wait |
| `29f979b` | feat: the wait resumes the same attempt behind a dependency gate |
| `fe78fe8` | feat: the bridge exposes the material wait lifecycle |
| `2d2c32a` | docs: the material wait surface and its limits |
| `b6c0acd` | fix: an untouched node keeps its ticket, and the guard reads the whole chain |
| `2b8fbc6` | feat: the bridge accepts the trusted platform envelope |
| `996aca9` | docs: the legacy ticket, the transitive guard and the platform envelope |

Nothing was merged and nothing was pushed: the branch is left for the
integration worker.
