# Worker report — durable multi-stage CREATE replay/resume

Task: `task_cc206de0d4d9` (dispatch `ctx_d59847c9a906`).
Checkout: `/Users/jiangwei/orca/workspaces/governed-agentic-work-runtime/gawr-mixed-node-design`
(branch `WayJ/gawr-mixed-node-design`), base `8fac70b`, no merge, no push.

## What was wrong

`POST /v1/workflows/instances` is four runtime commands —
`<commandId>:create`, `:contract`, `:plan`, `:bind` — each a compare-and-swap
on the work's `state_version`. The bridge recomputed that version on every
attempt, so the fingerprint of an already committed stage differed on the
retry and the runtime refused it: `409 COMMAND_ID_REUSED`. A creation that
crashed after the contract or the plan could not be resumed, and the
platform — which probes only the final `:bind` receipt — could not recover.

## What was built

* `work_runtime/workflow_server.py`
  * `CreatePreparations` — the durable preparation of one creation, stored in
    the bridge-owned `workflow_creates` table of the runtime store. The
    exact command identity, body and CAS version of every stage are written
    ahead of the stage; a resume re-issues the recorded command and the
    runtime recognises it.
  * `prepare()` — a transactional read-or-insert: it never overwrites a
    recorded stage, never replaces the row from a stale snapshot, and keeps
    the recorded actor and request digest immutable.
  * `create_instance()` — the four stages are prepared and issued through
    that record, and the creation of one instance is serialized by its
    command id.
  * A request identity digest (actor, work, document, template, instance,
    plan, session, participants) binds a command id to one request: a
    changed request answers `409 COMMAND_ID_REUSED` instead of silently
    reusing the first request's stages.
  * The plan, the optional `templateDigest` and the submitted policy are
    now checked before the first command, so a refused request creates
    nothing.
* `tests/test_workflow_create_resume.py` (new, 26 tests) — the preparation
  store, the crash-and-resume at every stage boundary, the replay that adds
  nothing, every conflict case, and the concurrent same-body and
  changed-body creations.
* `tests/test_workflow_http.py` — four bridge tests over a real loopback
  socket (replay, conflict, lost response, receipt read-back).
* Docs: `docs/workflow-runtime.md` (§7 — the creation is resumable),
  `docs/workflow-api-contract.md` (the create route's replay contract),
  `docs/verification.md` (rows W53–W58), `docs/runtime-boundaries.md` (the
  bridge's boundary row).

## Commits

| sha | subject |
|---|---|
| `032a9a1` | feat: the preparation of a creation is durable |
| `7b9b7d8` | fix: the creation resumes instead of reusing a command id |
| `2c369f9` | docs: the creation is resumable and says so |
| `a3315e1` | fix: a refused creation keeps its verdict and its own answer |
| `1f1e6ec` | fix: two callers of one creation never truncate each other |

Plan: `docs/superpowers/plans/2026-10-22-workflow-create-resume.md`.

## RED/GREEN evidence

| step | RED | GREEN |
|---|---|---|
| the preparation store | `AttributeError: 'WorkflowService' object has no attribute 'preparations'` | 2/2 |
| the resume | 9 failures, all `409 COMMAND_ID_REUSED` where `201` was expected (replay after completion, crash after contract/plan/bind, the binding receipt) | 19/19 |
| the bridge surface | the four new HTTP tests re-run against `032a9a1`: `409 COMMAND_ID_REUSED` where `201` was expected | 47/47 |
| the dropped guard | `CommandError` escaped instead of `400 DOCUMENT_INVALID` | restored |
| the coordinator's blocking review (concurrent CREATE) | `test_two_concurrent_creations_of_the_same_body_keep_one_creation` → `409 COMMAND_ID_REUSED` at `a3315e1`; the two store-level tests fail (no `prepare`) | 26/26 |

The coordinator's own scenario was re-run after the fix: two concurrent
same-key creates both answer `201`, the preparation keeps all four stages
with the original CAS versions `None/1/2/3`, all four receipts are
`accepted`, and the serial replay answers `201` with no new event.

## Gates

| gate | result |
|---|---|
| `python3 -m unittest discover -s tests` | 1349 tests, OK (2 skipped) |
| `python3 scripts/check_docs.py` | 127 files, 679 links, 0 broken |
| `python3 -m compileall -q work_runtime tests scripts` | clean |
| `python3 -m work_runtime demo` | clean |
| `python3 scripts/check_site.py` | 2 pages, 0 findings |
| `work_runtime/runtime.py`, `adapters.py`, `file_adapter.py`, `policy.py` | byte-identical (SHA-pinned, unchanged) |

## Rulings

1. The preparation lives in a bridge-owned `workflow_creates` table in the
   runtime store — `runtime.py` is SHA-pinned and must stay byte-identical;
   a sidecar file would lose the preparation when the store is copied. Cost
   if wrong: one table the runtime's schema does not declare.
2. The plan and the optional `templateDigest` are validated before any
   command is issued (fail fast) — a refused request must create nothing,
   and a corrected retry must not be blocked by a half-created work. Cost if
   wrong: a rejected request now leaves no work behind.
3. The request identity digest covers actor, work, document, template
   id/version/digest, parameters, session, participants, the normalized
   submitted plan and the submitted instance snapshot; the policy contract
   is not part of it, so a changed default policy keeps the contract the
   first attempt bound. Cost if wrong: a policy change under the same
   command id is not reported as a conflict.
4. The preparation schema did not change, so no migration case is needed. A
   row already truncated by the pre-fix bug stays truncated and needs an
   operator repair, because the runtime's stored receipt is the only
   authority on what was committed.

## Remaining risks

1. **A business refusal is final for its command id.** A stage refused on
   business grounds (`WORKFLOW_TEMPLATE_UNKNOWN`,
   `WORKFLOW_PARAMETERS_INVALID`, …) is a verdict the runtime remembers, so
   the same body replays the same refusal and never a second attempt. The
   earlier stages' work stays on the store — the bridge never resets a work
   to hide an effect — so a corrected request needs a fresh work. This is
   the runtime's dedup semantics and is pre-existing; the change makes the
   answer truthful (the real refusal instead of a misleading
   `COMMAND_ID_REUSED`) but does not make the creation completable.
   Disclosed in `docs/workflow-runtime.md`.
2. **The resume keeps the original CAS.** A stage prepared against a version
   that has moved on is refused `STATE_VERSION_CONFLICT` instead of being
   re-issued at the current version. That is the requested behaviour
   ("preserve the original immutable command identity/body/CAS"), and it is
   the reason the preparation is durable rather than recomputed.
3. **A store damaged by the pre-fix concurrency bug needs a repair** — a
   truncated preparation cannot be recovered, because the runtime's stored
   receipt is the only authority on what was committed.
4. **The creation is serialized per command id inside one coordinator
   process.** Two coordinators over one store remain prevented by
   `CoordinatorLock`, not by this lock.
5. **An invalid document still raises `ValueError` out of the native
   `create_instance`** (the `DOCUMENT_INVALID` guard catches `CommandError`
   only); the HTTP layer answers `400 BAD_REQUEST`. Pre-existing, unchanged.
