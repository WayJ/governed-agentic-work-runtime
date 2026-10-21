# Durable multi-stage CREATE replay/resume — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `POST /v1/workflows/instances` (and the native
`WorkflowService.create_instance`) resumable: a replay of the same create
body after a crash at any stage boundary completes the creation instead of
answering `409 COMMAND_ID_REUSED`, and a changed body conflicts instead of
being silently ignored.

**Architecture:** The creation is four runtime commands
(`<commandId>:create`, `:contract`, `:plan`, `:bind`), each guarded by a
compare-and-swap on the work's `state_version`. The bug is that the bridge
*recomputes* that version on every attempt, so a replay of an already
committed stage builds a different fingerprint and the runtime refuses it
(`COMMAND_ID_REUSED`). The fix adds a **durable preparation**: before a
stage's command is issued, the exact command identity, body and CAS version
of that stage are written to a `workflow_creates` row in the runtime store;
a resume re-issues the recorded command instead of recomputing one. A
**request identity digest** over the normalized request (actor, work,
document, template, instance, plan) is stored with it, so a changed request
under the same command id conflicts explicitly instead of being dropped.

**Tech Stack:** Python >= 3.9, standard library only (`sqlite3`, `json`,
`hashlib`), `unittest`. No runtime dependency is added.

**Spec:** the dispatch brief for `task_cc206de0d4d9`; the bridge contract
in [docs/workflow-api-contract.md](../../workflow-api-contract.md); the
engine and bridge description in
[docs/workflow-runtime.md](../../workflow-runtime.md); the mixed-node design
[2026-10-21-mixed-node-workflow-runtime-design.md](../specs/2026-10-21-mixed-node-workflow-runtime-design.md)
§10 (identity and idempotency composition).

## Global Constraints

- Python >= 3.9, zero runtime dependencies, standard-library `unittest` only.
- `work_runtime/runtime.py` and `work_runtime/adapters.py` stay byte-identical
  (SHA-pinned by `tests/test_publishing_compensation.py`). The durable
  preparation therefore lives in a `workflow_creates` table that the bridge
  creates in the runtime store — the runtime's own DDL is not touched.
- The creation keeps its four derived command ids
  (`<commandId>:create|:contract|:plan|:bind`); the binding receipt stays
  `<commandId>:bind` and is still reported as `bindingCommandId`.
- No reset, no new command key, no second effect to hide a first one.
- The bridge stays a trusted-local surface: principals are names in the
  grants map, not authenticated identities.
- TDD: a meaningful failing test, the observed failure, the minimal
  implementation, the rerun, and recorded RED/GREEN evidence.

## Review Focus

Five input classes the brief implies that a naive fix gets wrong — each one
gets a test in the task that owns the code:

1. **A changed body under the same command id** (different document, plan,
   template, parameters, session or participants) must answer `409`, never
   silently re-use the first request's stages.
2. **A changed actor or work id** under the same command id must conflict
   too — a receipt's existence is never proof that the request is the same.
3. **A crash exactly between two stages** (after `create`, after `contract`,
   after `plan`, after `bind`) must resume to a complete instance, not to a
   half-created one and not to a second creation.
4. **A replay after the creation completed** must add no revision, no
   intent, no external effect and no event — only the same answer.
5. **A lost response** (the client never saw the answer) must be
   recoverable by replaying the same body, and the final `:bind` receipt
   must be readable for the platform that probes only that one.

---

### Task 1: The durable preparation of a creation

**Files:**
- Modify: `work_runtime/workflow_server.py` (new `CreatePreparations` class,
  module-level DDL constant, import of `canonical`)
- Test: `tests/test_workflow_create_resume.py` (new file)

**Interfaces:**
- Consumes: `work_runtime.policy.digest` (already imported as
  `content_digest`), `work_runtime.policy.canonical` (new import),
  `runtime._connection()` / `runtime._transaction()` (private runtime
  accessors the engine already uses).
- Produces:
  - `CreatePreparations(runtime)` with
    `load(command_id: str, work_id: str) -> Optional[dict]` returning
    `{"actor", "request_digest", "stages"}` or `None`, and
    `save(command_id: str, work_id: str, actor: str, request_digest: str,
    stages: dict) -> None`.
  - Table `workflow_creates(command_id, work_id, actor, request_digest,
    stages)` with primary key `(command_id, work_id)`, created lazily by the
    bridge.

- [ ] **Step 1: Write the failing test**

```python
def test_the_preparation_survives_a_restart(self):
    service = self.service()
    self.create(service)                       # a complete creation
    reopened = self.reopen()                   # a new service over the same store
    row = reopened.preparations.load("create-1", "W-1")
    self.assertIsNotNone(row)
    self.assertEqual(row["actor"], "coordinator")
    self.assertEqual(sorted(row["stages"]),
                     ["bind", "contract", "create", "plan"])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest tests.test_workflow_create_resume -v`
Expected: FAIL — `AttributeError: 'WorkflowService' object has no attribute
'preparations'`.

- [ ] **Step 3: Implement `CreatePreparations` in `work_runtime/workflow_server.py`**

The class owns the table, creates it once with
`CREATE TABLE IF NOT EXISTS workflow_creates (...)` through
`runtime._connection()`, reads through `runtime._connection()` and writes
through `runtime._transaction()` with `INSERT OR REPLACE`. `stages` is
stored as the canonical JSON of the stage map.

- [ ] **Step 4: Run it to verify it passes**

Run: `python3 -m unittest tests.test_workflow_create_resume -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add work_runtime/workflow_server.py tests/test_workflow_create_resume.py
git commit -m "feat: the preparation of a creation is durable"
```

---

### Task 2: The staged creation resumes exactly

**Files:**
- Modify: `work_runtime/workflow_server.py` (`WorkflowService.create_instance`)
- Test: `tests/test_workflow_create_resume.py`

**Interfaces:**
- Consumes: `CreatePreparations` from Task 1.
- Produces: `create_instance(body)` unchanged in shape — `201` with the
  instance view, `400`/`409`/`422` as before — but resumable and
  conflict-explicit. New: the answer `409 COMMAND_ID_REUSED` when the
  command id was used for a different request.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_replay_after_the_creation_completed_returns_the_same_answer(self):
    status, first = self.create(self.service())
    self.assertEqual(status, 201)
    status, second = self.create(self.service())
    self.assertEqual(status, 201)
    self.assertEqual(second["stateVersion"], first["stateVersion"])

def test_a_crash_after_the_contract_resumes_the_creation(self):
    self.fail_after(2)                         # crash after :contract
    self.create(self.service())                # -> the crash
    status, body = self.create(self.reopen())  # the resume
    self.assertEqual(status, 201, body)
    self.assertEqual(body["workflow"]["templateId"], ...)

def test_a_changed_document_conflicts(self):
    self.create(self.service())
    status, body = self.create(self.service(), document={"id": "H-002"})
    self.assertEqual(status, 409)
    self.assertEqual(body["error"]["code"], "COMMAND_ID_REUSED")
```

The failure injection wraps `runtime.command` so the n-th call raises
`RuntimeError` after the command it wrapped committed — the crash is
between two stages, not inside one.

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tests.test_workflow_create_resume -v`
Expected: FAIL — the replay answers `409 COMMAND_ID_REUSED`.

- [ ] **Step 3: Implement the staged creation in `create_instance`**

1. Validate the request as before, but resolve and validate the plan and
   the optional `templateDigest` **before** any command is issued (fail
   fast: a refused request creates nothing).
2. Compute the request identity digest over the normalized request:
   actor, work id, document, template id/version/digest, parameters,
   session id, participants, the normalized submitted plan and the
   submitted instance snapshot.
3. Load the preparation. If one exists and its actor or request digest
   differs → `409 COMMAND_ID_REUSED`.
4. For each stage in order (`create`, `contract`, `plan`, `bind`): take the
   recorded stage if the preparation has one, otherwise prepare it — the
   command id `<commandId>:<stage>`, the payload and the current
   `state_version` as the CAS — and write the preparation **before**
   issuing the command.
5. Issue each stage with its recorded identity, body and CAS version.

- [ ] **Step 4: Run them to verify they pass**

Run: `python3 -m unittest tests.test_workflow_create_resume -v`
Expected: PASS.

- [ ] **Step 5: Run the workflow regression net**

Run: `python3 -m unittest tests.test_workflow_http tests.test_workflow_engine tests.test_workflow_recovery tests.test_workflow_node_quality tests.test_workflow_participants tests.test_workflow_authority tests.test_workflow_review tests.test_workflow_spec -v`
Expected: all OK.

- [ ] **Step 6: Commit**

```bash
git add work_runtime/workflow_server.py tests/test_workflow_create_resume.py
git commit -m "fix: the creation resumes instead of reusing a command id"
```

---

### Task 3: The bridge contract, the HTTP surface and the truth docs

**Files:**
- Modify: `tests/test_workflow_http.py` (bridge-level replay and conflict
  tests over a real loopback socket)
- Modify: `docs/workflow-runtime.md` (§7 — the preparation, the resume and
  the new conflict), `docs/workflow-api-contract.md` (the create route's
  replay contract), `docs/verification.md` (the verification rows)

**Interfaces:**
- Consumes: the `create_instance` contract from Task 2.
- Produces: the documented wire behaviour and the verification rows that
  name the tests that pin it.

- [ ] **Step 1: Write the failing HTTP test**

```python
def test_a_replay_over_http_returns_the_same_instance(self):
    status, first = self.call("POST", API_PREFIX + "/instances", self.body())
    self.assertEqual(status, 201, first)
    status, second = self.call("POST", API_PREFIX + "/instances", self.body())
    self.assertEqual(status, 201, second)
    self.assertEqual(second["stateVersion"], first["stateVersion"])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest tests.test_workflow_http -v`
Expected: FAIL — `409 COMMAND_ID_REUSED`.

- [ ] **Step 3: Update the docs**

Document: the four derived command ids and their durable preparation; the
resume rule; the `409 COMMAND_ID_REUSED` for a changed request; the fact
that the `:bind` receipt stays the platform's probe point. Add the
verification rows that name the new tests.

- [ ] **Step 4: Run the gates**

Run: `python3 -m unittest discover -s tests -v` — Expected: all OK.
Run: `python3 scripts/check_docs.py` — Expected: clean.
Run: `python3 -m compileall -q work_runtime tests scripts` — Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add tests/test_workflow_http.py docs/
git commit -m "docs: the creation is resumable and says so"
```
