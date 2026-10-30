# Material waiting implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A trusted-local manager can pause the workflow's current agent node for
business material (`waiting`), adopt externally provided material revisions, and
resume the same attempt without spending quality retry allowance — with a
fail-closed dependency gate instead of transitive invalidation.

**Architecture:** Three ordinary runtime command kinds (`request_material_wait`,
`adopt_material`, `resume_material_wait`) dispatched through the existing
`WORKFLOW_COMMANDS` seam (CAS + dedup + receipts + replay re-authorization), a
new node-instance state `waiting` that the routing pass treats as stable, and a
wait record on the instance body that tracks the accepted dependency set. No
`runtime.py`/`adapters.py` edit; no schema change; no new tables.

**Tech Stack:** Python ≥3.9, stdlib `unittest`, SQLite store as-is.

**Spec:** Coordinator dispatch `task_9d95016be745` (brief in the run), read with
`docs/workflow-runtime.md`, `docs/workflow-api-contract.md`, RFC-002 (waiting
policy, T12), `.agents/notes/2026-10-22-workflow-cancellation-http-report.md`.

## Global Constraints

- Zero runtime dependencies, Python ≥3.9, stdlib unittest only.
- `work_runtime/runtime.py` and `work_runtime/adapters.py` untouched (S15 freeze;
  byte pin in `tests/test_publishing_compensation.py` must stay valid).
- Domain-neutral vocabulary; no city/safety/business-specific words in code.
- Never: silently rerun a side-effect node, alter an unknown/confirmed operation,
  raise a configured `max_attempts`, force completion, mutate the DB out-of-band.
- Wait targets only the workflow's **current agent node** in state `running`,
  pinned by exact node/attempt/`input_digest` plus the command CAS
  (`expectedVersion`).
- Business-material waiting is distinct from candidate-quality rework (no new
  attempt is opened) and from the human `request_material` decision verdict.
- Transitive invalidation is **out of scope**: resume rejects with
  `INPUT_DEPENDENCIES_REQUIRE_REVALIDATION` and the limitation is documented.
- `revise_object`'s `_supersede_pinned` only cancels running/blocked/submitted
  instances — a waiting node is untouched by it; the resume gate catches the drift.
- Bounded payload: adopted object body ≤ 64 KiB canonical (`MAX_OUTPUT_BYTES`),
  reason ≤ 512 chars, ≤ 16 adoptions per wait, findings bounded by `_bounded`.

## Review Focus

1. A refused wait/adopt/resume must mutate nothing (node rows, intents, objects,
   events, state version) — the a1bc07d lesson. → Task 1/2/3 refusal tests.
2. A waiting node must survive a restart and a routing pass unchanged. → Task 1.
3. A result submitted while waiting is refused precisely, not as stale. → Task 1.
4. A dependency revised during the wait (via `revise_object`) must not be
   silently reused at resume. → Task 3 gate test.
5. A waiting node must block finalization and be cancellable, and its deadline
   must not expire it. → Task 3 edge tests.

---

### Task 1: The waiting state and `request_material_wait`

**Files:** Modify `work_runtime/workflow.py` (WORKFLOW_COMMANDS, `apply_command`,
`replay_allowed`, `_step`, `_submit_result`, new `_request_material_wait`).
Test: `tests/test_workflow_material_wait.py` (new, uses `tests/workflow_support.py`).

**Interfaces (produces):**
- Command `request_material_wait` payload `{node, attempt, input_digest, reason,
  request_version}` (`request_version` must be `1`).
- Instance state `"waiting"`; `instance["material_wait"] = {state, request_version,
  requested_by, reason, requested_at, input_digest, dependencies: [refs],
  adoptions: [], resumed: None}`; `work["workflow_status"] = "waiting"`.
- Codes: `WORKFLOW_NODE_UNKNOWN`, `WORKFLOW_NODE_NOT_CURRENT`,
  `WORKFLOW_NODE_NOT_WAITABLE` (not an agent node / not running),
  `WORKFLOW_NODE_WAITING` (already waiting; also the result-suppression code),
  `WORKFLOW_ATTEMPT_STALE`, `WORKFLOW_INPUT_STALE`, `AUTHORITY_DENIED`,
  `CANCELLATION_ACTIVE`.

- [x] RED: tests — manager requests wait (state/intent/status/event/wait record);
  refusals (authority, unknown node, not current, stale attempt, stale digest,
  non-agent, already waiting, bad `request_version`, cancellation active) each
  mutate nothing byte-for-byte; waiting persists across a fresh engine
  (`advance` no-op, version unchanged); `submit_node_result` while waiting →
  `WORKFLOW_NODE_WAITING`, nothing stored.
- [x] GREEN: implement minimal command + `_step` explicit waiting branch (stop the
  pass) + waiting check in `_submit_result` before the generic state check.
- [x] Commit `feat: the engine owns a manager-requested material wait`.

### Task 2: `adopt_material` — adopting external material revisions

**Files:** Modify `work_runtime/workflow.py` (`apply_command`, new
`_adopt_material`). Test: same test file.

**Interfaces:** payload `{node, attempt, name, object, request_version}`; writes a
new immutable revision via `_write_object` (no `_supersede_pinned`); updates the
wait record's dependency entry and appends `{name, revision, digest, adopted_by,
adopted_at}`. Codes: `WORKFLOW_NOT_WAITING`, `WORKFLOW_MATERIAL_NOT_DEPENDENCY`,
`WORKFLOW_MATERIAL_TOO_LARGE`, `WORKFLOW_ADOPTION_LIMIT_EXCEEDED`.

- [x] RED: adopt happy path (new revision, old row intact, wait record updated,
  adoptions logged); non-dependency name refused; oversized body refused;
  adopt without a wait refused; adoption cap; refusals mutate nothing.
- [x] GREEN: implement.
- [x] Commit `feat: a manager adopts external material under an active wait`.

### Task 3: `resume_material_wait` — the dependency gate and same-attempt resume

**Files:** Modify `work_runtime/workflow.py` (`apply_command`, `replay_allowed`,
new `_resume_material_wait`; `_write_intent` gains `reissue`; `cancel_in_transaction`
and the finalization unsettled set gain `"waiting"`; `instance()` view gains
`materialWait`). Test: same test file.

**Interfaces:** payload `{node, attempt, request_version}`. Gate: every
dependency the wait accepted must still be the object's current revision/digest,
else reject `INPUT_DEPENDENCIES_REQUIRE_REVALIDATION` with findings
`[{name, accepted:{revision,digest}, current:{revision,digest}|null}]`. On
accept: instance → `blocked`, wait `resumed={by,at}`, `workflow_status="active"`,
then `_activate` re-resolves inputs (re-judging declared validators — failing
material blocks fail-closed), recomputes `input_digest` + `deadline_at`, and
re-issues the `agent_task` intent (cancelled/acknowledged row → pending, fresh
body); attempt number unchanged.

- [x] RED: resume after adopt (running again, attempt unchanged, new
  input_digest, intent pending, status active; a valid candidate with the new
  digest completes attempt 1; a candidate with the old digest →
  `WORKFLOW_INPUT_STALE`); drift case (`revise_object` during wait → resume
  rejected with precise findings, nothing mutated, waiting instance not
  superseded; manager then adopts the new revision and resumes); adopted
  material failing the declared input validator → node blocked with findings;
  cancellation while waiting cancels the node (`WORK_CANCELLED`) and does not
  restart; finalization refuses a waiting node; deadline suspended while
  waiting; view carries `materialWait`.
- [x] GREEN: implement.
- [x] Commit `feat: the wait resumes the same attempt behind a dependency gate`.

### Task 4: The HTTP bridge surface

**Files:** Modify `work_runtime/workflow_server.py` (`request_material_wait`,
`adopt_material`, `resume_material_wait` service methods + `_route` entries).
Test: `tests/test_workflow_material_wait_http.py` (new, real service on a real
store, mirrors `test_workflow_cancellation_http.py`).

**Interfaces:** `POST …/material/wait|adopt|resume` bodies carry `actor`,
`commandId`, `expectedVersion`, `requestVersion: 1` (+ per-route fields,
camelCase wire names). 200 answers the instance view + a result block; refusals
map through `_status_for`; receipts readable via `GET /v1/workflows/commands/…`.

- [x] RED: happy paths over HTTP (view shows `materialWait` + `workflowStatus
  "waiting"`); CAS conflict 409; dedup replay identical / `COMMAND_ID_REUSED`;
  re-authorization after `transfer_owner` → 403 on replay; non-manager 403
  mutating nothing; result submission while waiting refused; unknown work 404;
  finalized 409; `requestVersion` unsupported 400; oversized object refused;
  adopted revision read back via `GET …/objects/{name}/revisions/{n}`.
- [x] GREEN: implement.
- [x] Commit `feat: the bridge exposes the material wait lifecycle`.

### Task 5: Docs and gates

**Files:** Modify `docs/workflow-runtime.md` (new § material waiting + routing
table rows + limits), `docs/workflow-api-contract.md` (wire contract),
`docs/verification.md` (W-numbers per house style). No demo change (documented).

- [x] Document: semantics, codes, the no-transitive-invalidation limitation and
  why (`revise_object` ≠ invalidation; side-effect nodes never re-run), deadline
  suspension, restart persistence, bounded payload.
- [x] Gates: `python3 scripts/check_docs.py`;
  `python3 -m unittest discover -s tests` (baseline 1477 OK, skipped=2);
  `python3 -m compileall -q work_runtime tests scripts`; demo + site gates;
  byte pin of `runtime.py`/`adapters.py` still valid.
- [x] Commit `docs: the material wait surface and its limits`.
