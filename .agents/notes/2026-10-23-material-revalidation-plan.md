# Controlled material replacement and transitive revalidation — plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A trusted manager can replace the archived source material of a
running workflow and revalidate the affected consumers — in the same
workflow and session — without re-running the source read, without
replaying any business effect, without raising `max_attempts`, and without
an unbounded number of material generations.

**Architecture:** One new runtime command, `replace_material`, that adopts a
small frozen `sourceReference` as a new revision of the source object,
computes the **consumer/transitive closure** of that object, refuses when
the affected branch carries business effects, and then opens one bounded
**material attempt** per affected node. Material attempts are counted by a
separate budget (`material_generations` in the published definition), never
by the quality rework allowance. Attempt identities stay monotonic: the
attempt number only ever grows, and every attempt records the **trigger**
that opened it (`initial`, `quality`, `material`).

**Tech Stack:** Python ≥3.9, stdlib `unittest`, SQLite store as-is.

**Spec:** Coordinator dispatch `task_cd5a605af6fc` and its status message
("Exact wire needed early for platform integration"), read with
`docs/workflow-runtime.md` §13, `docs/workflow-api-contract.md`,
`.agents/notes/2026-10-23-material-wait-report.md`.

## Global Constraints

- Zero runtime dependencies, Python ≥3.9, stdlib unittest only.
- `work_runtime/runtime.py` and `work_runtime/adapters.py` untouched.
- **The source read is never re-run.** The core never re-runs the source
  node, never re-dispatches its operation, never reuses its operation key.
  The platform acquires the archive; the core receives only a small
  immutable `sourceReference`.
- **No raw object, URL or authority** crosses the core boundary: the body
  carries a frozen `sourceReference` only.
- The accepted historical version of the source node is **preserved**, and
  the replacement never claims the old acceptance covers the new revision.
- The revalidation is refused when the affected branch has a prepared,
  unknown or confirmed business effect, or the work is finalized or
  cancelling.
- `max_attempts` (the quality allowance) is never raised and never reset;
  a material attempt is counted against `material_generations` instead.
- Attempt numbers are monotonic and never reused; every attempt records
  its trigger.
- Stale tickets, stale reviews and stale acknowledgements are rejected
  (the attempt identity and the input generation move).
- Domain-neutral vocabulary; no city/safety/business-specific words.
- No direct DB edits, no new workflow bypass, no new worker.

## Review Focus

1. A refused replacement must mutate nothing — no object revision, no
   attempt, no event, no state version. → Task 2.
2. The source node's accepted attempt, effect and receipts must survive a
   replacement untouched. → Task 2.
3. A branch that already produced an effect must be refused, not
   re-run. → Task 3.
4. The material budget must be exhausted by the second replacement, and
   the quality allowance must be unchanged by it. → Task 3.
5. A material attempt that fails on quality must not open another
   attempt (no infinite retry through the material path). → Task 3.

---

### Task 1: The definition of a material budget

**Files:** Modify `work_runtime/workflow_spec.py` (`material_generations` as
an optional node field, linted), `work_runtime/workflow.py`
(`_material_generations`). Test: `tests/test_workflow_material_revalidation.py`
(new), `tests/workflow_support.py` (the revalidation family).

**Interfaces (produces):**
- Node field `material_generations` (integer ≥ 0, default 0): the number
  of material attempts (revalidations) the node may ever have. Published,
  digested and pinned by the binding like every other declared field.
- `WorkflowEngine._material_generations(spec, node_id) -> int`.

- [ ] RED: lint refuses a negative or non-integer `material_generations`
  (`NODE_FIELD_TYPE`), accepts 0 and a positive integer, and refuses the
  field on a node kind that has no material (none — all kinds may
  declare it, the material is judged by every kind).
- [ ] GREEN: implement the lint and the accessor.
- [ ] Commit `feat: the definition declares a bounded material budget`.

### Task 2: `replace_material` — the controlled replacement

**Files:** Modify `work_runtime/workflow.py` (the command, the closure,
the attestation, the invalidation). Test: the new test file.

**Interfaces:**
- Command `replace_material` payload
  `{node, source_reference, reason, request_version, waiting_node,
  waiting_ticket}`.
- `node` names the **source node** — the node whose completed attempt
  produced the material. The core derives the object from that node; a
  caller cannot name an arbitrary object.
- `source_reference` is a small immutable object: a dict with a `kind`
  string and bounded fields, at most 4 KiB of canonical JSON. The core
  never resolves it.
- `waiting_ticket` is the input ticket of the waiting node the manager
  observed; it must still be the current one (`WORKFLOW_INPUT_STALE`).
- The attestation (persisted on the work):
  `work["material_revalidation"] = {state, generation, attestation:
  {kind, adopted_by, adopted_at, source_node, object, from: {revision,
  digest}, to: {revision, digest}, claim}, affected: [{node, attempt,
  reason}], queue: [nodes], started_at}`.
- Codes: `AUTHORITY_DENIED`, `CANCELLATION_ACTIVE`, `WORKFLOW_FINALIZED`,
  `WORKFLOW_NOT_BOUND`, `WORKFLOW_NODE_UNKNOWN`,
  `WORKFLOW_SOURCE_NOT_PRODUCER` (the node did not produce material),
  `WORKFLOW_SOURCE_NOT_COMPLETED`, `WORKFLOW_SOURCE_REFERENCE_INVALID`,
  `WORKFLOW_SOURCE_REFERENCE_TOO_LARGE`, `WORKFLOW_WAITING_TICKET_STALE`,
  `WORKFLOW_REVALIDATION_EFFECT_PRESENT`,
  `WORKFLOW_REVALIDATION_BUDGET_EXHAUSTED`,
  `WORKFLOW_REVALIDATION_NO_CONSUMERS`.

- [ ] RED: the happy path (a new revision of the source object, the old
  revision retained, the attestation written, the affected closure
  computed, the affected nodes marked, the source node's attempt, effect
  and receipts untouched); every refusal above; a refused replacement
  mutates nothing.
- [ ] GREEN: implement.
- [ ] Commit `feat: a manager replaces the source material under an attestation`.

### Task 3: The material attempt — a bounded, separate allowance

**Files:** Modify `work_runtime/workflow.py` (`_open_attempt`, the trigger,
  the quality count, the routing queue). Test: the new test file.

**Interfaces:**
- The instance carries `trigger` (`initial` | `quality` | `material`) and
  `material_generation` (the budget it consumed).
- The quality allowance counts the **non-material** attempts; the attempt
  number is monotonic and may exceed `max_attempts` because of the
  material attempts.
- The revalidation queue on the work drives the cursor: the affected
  nodes are re-run in dependency order, one material attempt each.

- [ ] RED: the affected chain re-runs in order (N01, then N02, then
  N03), each with a material attempt, the attempt numbers monotonic, the
  old attempts, checks, intents and receipts retained; the quality
  allowance is unchanged; a second replacement is refused
  (`WORKFLOW_REVALIDATION_BUDGET_EXHAUSTED`); a material attempt that
  fails on quality opens no further attempt; a stale ticket, an old
  review and an old acknowledgement are all rejected.
- [ ] GREEN: implement.
- [ ] Commit `feat: a revalidated node runs on a material attempt, not a quality one`.

### Task 4: The HTTP surface

**Files:** Modify `work_runtime/workflow_server.py` (the route, the
  service method, the status table, the view). Test:
  `tests/test_workflow_material_revalidation_http.py` (new).

- [ ] RED: the route over a real service on a real store: the happy path
  (the view carries the attestation and the affected nodes), the CAS
  conflict, the dedup replay, the `COMMAND_ID_REUSED` conflict, the
  re-authorization after an ownership change, the restart, the refusal
  codes, the effects-blocked case, and the platform envelope (`actor`
  only — no `actorId`).
- [ ] GREEN: implement.
- [ ] Commit `feat: the bridge exposes the material replacement`.

### Task 5: Docs, gates and the report

- [ ] Document the semantics, the wire, the codes, the budget, the
  limits (no rewind of the source read, no effect replay, no raised
  `max_attempts`) in `docs/workflow-runtime.md`,
  `docs/workflow-api-contract.md` and `docs/verification.md`.
- [ ] Gates: `python3 scripts/check_docs.py`; the full suite with the
  authoritative count; `python3 -m compileall -q work_runtime tests
  scripts`; the demo and site gates; the byte pin of `runtime.py`.
- [ ] Commit `docs: the controlled replacement and the transitive revalidation`.
