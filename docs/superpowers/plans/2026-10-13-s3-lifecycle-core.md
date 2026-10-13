# S3 Intervention Lifecycle Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the ratified S3 lifecycle foundation — cancellation, owner transfer, same-family policy migration and the policy registry — in `work_runtime` with meaningful TDD.

**Architecture:** All lifecycle state lives in the existing Work JSON (schema_version stays 1); four new command kinds ride the existing command protocol (CAS + durable dedup + receipts); per-work policy resolution replaces single-policy lookup everywhere. Ownership is a Work-scoped gate in front of management mutations, proposals and dispatch; replay rechecks current authority before returning a stored receipt (D15 B2).

**Tech Stack:** Python >=3.9 standard library only, SQLite, unittest, real `FakeOA` effects.

**Spec:** `docs/superpowers/specs/2026-10-13-s3-intervention-design.md` (authoritative carrier copy: `/Users/jiangwei/orca/workspaces/governed-agentic-work-runtime/sprint-s3-intervention/docs/superpowers/specs/2026-10-13-s3-intervention-design.md`) — includes the D15 builder-check ratification, which pins the constructor, replay-authority and evidence-revalidation contracts this plan follows.

## Global Constraints

- Python >=3.9, zero runtime dependencies, standard-library unittest only.
- Ownership scope: `work_runtime/runtime.py`, `work_runtime/policy.py` (ExpensePolicyV2 only), `tests/test_interventions.py` (new), `docs/interventions.md` (new), `docs/runtime-boundaries.md`, this plan and `.agents/notes/2026-10-13-S3-lifecycle-core-report.md`. Sole baseline edit: `tests/test_runtime.py` unsupported-kind probe `request_cancel` → `request_refund`, keeping the `COMMAND_UNSUPPORTED` assertion and test count. No edits to ingress/adapters/CLI/demos/README/CI/other tests.
- Every commit that touches `runtime.py` updates `docs/runtime-boundaries.md` in the SAME commit (doc_sync_map).
- All 172 baseline tests must pass after every task; no merge, no push.
- New rejection codes only from the ratified list: `CANCELLATION_ALREADY_REQUESTED`, `CANCELLATION_NOT_REQUESTED`, `CANCEL_ACKNOWLEDGEMENT_MISMATCH`, `CANCELLATION_ACTIVE`, `TRANSFER_SAME_OWNER`, `MIGRATION_TARGET_UNCHANGED`, `MIGRATION_TARGET_UNREGISTERED`, `MIGRATION_FAMILY_MISMATCH`; reuse `AUTHORITY_DENIED`, `WORK_NOT_ACTIONABLE`, `OUTCOME_UNRESOLVED`, `CONTRACT_NOT_ACTIVE`, `COMMAND_UNSUPPORTED`, `COMMAND_ID_REUSED`, `STATE_VERSION_CONFLICT`, revision/scope codes. Malformed payloads raise `CommandError`.
- Cancelled prepared-operation reasons: `WORK_CANCELLED`, `POLICY_MIGRATED`, `OWNERSHIP_TRANSFERRED`; existing `STALE_INTENT` unchanged for plan/document revisions.
- No compensation execution, no evidence revocation status, no distributed claims, no cross-domain registry support — label as limitations in docs.

## Settled contracts (from D15; implementers copy these exactly)

- Constructor: `Runtime(path, policy, grants, *, policies: Optional[Dict[str, Policy]] = None)`. Registry default `{policy.version: policy}`. Explicit registry: dict, nonempty-str keys equal to `value.version`, each value has nonempty-str `id`/`version`/`goal`, dict `evidence_sources`, the five callable Policy methods, `id`/`goal` equal to the default policy's; the default version must map to the SAME default object if present (the runtime always merges the default in). Validation raises `CommandError` BEFORE `mkdir`/DB writes; the mapping is copied. Missing pinned version fails closed with the existing `CommandError` message; unbound Work uses the default policy.
- Replay (B2): after the actor-exists and fingerprint checks, recheck current authority for the kind — `create_work` needs `work.manage`; `record_evidence` needs current source identity for the payload kind plus `evidence.write`; `propose_action` needs current owner plus requested capability; management mutations need current owner + `work.manage` (legacy ownerless works stay grant-only); `request_cancel`/`finalize_cancel`/`transfer_owner` accept current owner + `work.manage` or `work.intervene` admin; `migrate_policy` exclusively `work.intervene`. A denied replay returns a fresh UNPERSISTED `AUTHORITY_DENIED` receipt with the current observed state version; the stored receipt is untouched. Fingerprint mismatch stays `COMMAND_ID_REUSED`. Closed-work actionability follows replay as before (stored receipt returned while authority holds).
- Intervener authority (fresh path): `request_cancel`/`finalize_cancel`/`transfer_owner` → `work.intervene` admin OR (work has owner AND actor is owner AND actor holds `work.manage`); ownerless legacy works: admin only for the new commands. `migrate_policy` → admin only.
- Cancellation state: `work["cancellation"] = {"requested_by", "reason"}` — set once, never cleared by transfer, evaluation, expiry, resolution or recovery. Closure: `work["status"]="closed"`, `work["outcome"]="cancelled"`, `work["completion"] = {"cancellation", "acknowledged_operations": [{"operation_id","external_id"}], "operation_dispositions": [{"operation_id","status","dispatch_state"}]}`. Events: `CancellationRequested`, `WorkCancelled` (details = closure), `OwnerTransferred` (actor/from/to/reason/reassigned_waits/invalidated_operations), `PolicyMigrated` (actor/reason/from/to/evidence dispositions/invalidated_operations).
- During cancellation (work not closed): `propose_action`, `bind_contract`, `revise_plan`, `revise_document`, `register_wait`, `request_completion`, `migrate_policy` → `CANCELLATION_ACTIVE`; second `request_cancel` under a new id → `CANCELLATION_ALREADY_REQUESTED`; `record_evidence`, `verify_pending`, `reconcile`, `expire_waits`, `transfer_owner`, `finalize_cancel` proceed; original intent immutable.
- `finalize_cancel` resolves ops like `request_completion` does (unresolved = status not in `confirmed_succeeded`/`confirmed_failed` AND `dispatch_state != "cancelled"` → `OUTCOME_UNRESOLVED` with ids); then `acknowledged_operations` must equal exactly the set of `confirmed_succeeded` operation ids (`CANCEL_ACKNOWLEDGEMENT_MISMATCH` with the succeeded ids as blockers).
- `transfer_owner` target must exist in `grants` with `work.manage` (else rejected `AUTHORITY_DENIED`); same-owner → `TRANSFER_SAME_OWNER`; reassigns `waiting`/`expired` waits owned by the prior owner; invalidates never-dispatched prepared intents (`OWNERSHIP_TRANSFERRED`); preserves in-flight ops untouched; legacy adoption (owner absent) is admin-only and sets the first owner.
- Migration order: admin → closed check (generic `WORK_NOT_ACTIONABLE`) → payload shape (`CommandError`) → `CONTRACT_NOT_ACTIVE` → `CANCELLATION_ACTIVE` → payload `policy_id` != default policy id → `MIGRATION_FAMILY_MISMATCH` (before lookup) → version not registered → `MIGRATION_TARGET_UNREGISTERED` → target id/goal vs contract → `MIGRATION_FAMILY_MISMATCH` → same version → `MIGRATION_TARGET_UNCHANGED` → any `dispatched`/`outcome_unknown` op → `OUTCOME_UNRESOLVED` → target `validate_document(current)` with `ValueError` re-raised as `CommandError`, nothing persisted. Then atomically: bind target contract (revision = old + 1), revalidate every `verified` proof (`target.evidence_sources[kind] == proof.source` AND `target.validate_evidence(newly-bound work, proof)`, else → `invalid`; `pending_verification` and `invalid` unchanged), cancel waits + prepared intents (`POLICY_MIGRATED`), `_save` (requirements evaluated by target), record dispositions. Any exception rolls back binding, evidence, operations and events together.
- `verify_pending` verifies a pending candidate only when the per-work policy's `evidence_sources[kind] == candidate["source"]` AND `validate_evidence` passes; otherwise `invalid`.
- `propose_action` stores/updates `contract_revision = work["contract"]["revision"]` (actual revision, not 1) on prepare and re-admission; `dispatch` cancels as `STALE_INTENT` when `op["contract_revision"] != work["contract"]["revision"]` and holds (`AUTHORITY_DENIED`) when the work has an owner different from `op["actor"]`.
- `ExpensePolicyV2(ExpensePolicy)` in `policy.py`: `version = "demo-2"`; same id/goal/evidence_sources/capability/`operation_key` (inherit); E05 applicability `unknown` when amount unknown else always `applicable` (override the `approval_applicability(known, over)` hook; v1 keeps `unknown`/`applicable`/`not_applicable`); `validate_evidence` for kind `approval` requires data exactly `{"digest", "policy_version"}` with `policy_version == "demo-2"`, all other kinds inherit demo-1. Not exported from `work_runtime/__init__.py` (outside ownership).

## Review Focus

1. Replay of an accepted intervention command after the work closed — must return the stored receipt while authority holds (closed actionability follows replay). Test: `test_replay_after_close_returns_stored_receipt` (Task 4).
2. Reused acknowledge-ids or non-list acknowledgement shapes are API misuse, not business rejections — `CommandError`, nothing persisted. Test: `test_finalize_payload_malformed_raises` (Task 4).
3. Interventions are CAS commands — stale `expected_version` yields `STATE_VERSION_CONFLICT`, and concurrent duplicate `request_cancel` ids share one receipt. Tests: `test_cancel_respects_cas` + `test_duplicate_cancel_single_receipt` (Task 3).
4. `migrate_policy` on an establishing (unbound) work and on a work pending verification must not half-apply — `CONTRACT_NOT_ACTIVE` before any mutation; pending proofs neither verified nor lost. Tests: Task 7 (`..._requires_bound_contract`, `..._keeps_pending_pending`).
5. Legacy ownerless DBs keep grant-only behavior for existing commands and reject non-admin intervention — no owner is ever guessed. Tests: `test_legacy_work_stays_grant_only` + `test_legacy_transfer_requires_admin` (Task 5).

---

### Task 1: Policy registry constructor and per-work resolution

**Files:**
- Modify: `work_runtime/runtime.py` (`__init__`, `_work`, new `_policy_for`; switch `self.policy` → per-work policy in `_evaluate`, `_apply` bind/revise_document, `_propose`, `_receive`, `verify_pending`, `dispatch`, `reconcile`, `_resolve`, `_accepted_source` signature)
- Test: `tests/test_interventions.py` (new file, class `RegistryContractTests`)
- Modify: `docs/runtime-boundaries.md` (registry + per-work resolution sections; update the "Single policy version per database" limitation)

**Interfaces:**
- Produces: `Runtime(path, policy, grants, *, policies=None)`; `runtime.policies` (copied dict); `ExpensePolicyV2` usable in a registry in later tasks; every later task relies on `self._policy_for(work)` for policy access.

- [ ] **Step 1: Write failing tests** — `RegistryContractTests`: default registry equals `{ExpensePolicy().version: policy-object}` semantics (two-default runtimes still work — covered by baseline); keyword-only call (`TypeError` when `policies` passed positionally); malformed registries raise `CommandError` BEFORE creating the parent directory (assert `not Path(parent).exists()` after the raise): non-dict, non-str key, empty key, key != `value.version`, missing `evidence_sources` dict, non-callable method, id/goal mismatch vs default, default version mapped to a different object; a valid `{}` registry is accepted and keeps defaults working; mutating the caller's dict after construction cannot change resolution (copy). Also: a work pinned (by direct DB edit of the contract version to an unloaded version) fails closed with `CommandError` on `get_work` — pin the fail-closed path without migration.
- [ ] **Step 2: RED** — `python3 -m unittest tests.test_interventions -v` → new tests FAIL (`TypeError: __init__() got an unexpected keyword argument` / no CommandError); baseline 172 still pass.
- [ ] **Step 3: Implement** — `_validated_registry(policy, policies)` module function per the settled contract; reorder `__init__` to validate before `mkdir`; add `_policy_for(work)` and call it in `_work` (missing pinned version keeps the existing raise); replace `self.policy` at every work-scoped call site.
- [ ] **Step 4: GREEN** — new tests pass; `python3 -m unittest discover -s tests` → 172 + new all pass.
- [ ] **Step 5: Commit** — runtime.py + tests/test_interventions.py + docs/runtime-boundaries.md: `feat(runtime): validated same-family policy registry with per-work resolution`.

### Task 2: ExpensePolicyV2

**Files:**
- Modify: `work_runtime/policy.py` (add `approval_applicability` hook to `ExpensePolicy`, add `ExpensePolicyV2`; demo-1 behavior unchanged)
- Test: `tests/test_interventions.py` (class `ExpensePolicyV2Tests`)

**Interfaces:**
- Produces: `from work_runtime.policy import ExpensePolicyV2` — `version == "demo-2"`, same `id`/`goal`/`evidence_sources` as v1; used by Tasks 5–7 registries.

- [ ] **Step 1: Write failing tests** — E05 under v2: known low amount → `applicable` (and submission blocked without approval), unknown amount → `unknown`; v1 unchanged: low amount → `not_applicable` (mirror assertions for v1); v1 approval `{"digest"}` is invalid under v2 `validate_evidence`, v2 approval exactly `{"digest", "policy_version": "demo-2"}` valid, `{"digest","policy_version":"demo-1"}` invalid; `operation_key` equal for v1/v2 on the same work; approval evidence satisfying E05 under v2 end-to-end via a registry runtime.
- [ ] **Step 2: RED** — `ImportError: cannot import name 'ExpensePolicyV2'`.
- [ ] **Step 3: Implement** — per settled contract (hook override + `validate_evidence` override).
- [ ] **Step 4: GREEN** — full suite passes.
- [ ] **Step 5: Commit** — `feat(policy): ExpensePolicyV2 with version-bound approval requirement`.

### Task 3: request_cancel

**Files:**
- Modify: `work_runtime/runtime.py` (`_apply` intervention dispatch, `_request_cancel`, `_cancel_prepared(reason=...)` refactor, cancellation gates in `_propose`/`_apply`/`dispatch`, `_create` stores `owner`)
- Modify: `tests/test_runtime.py:326-328` (probe → `request_refund`)
- Test: `tests/test_interventions.py` (class `CancellationRequestTests`)
- Modify: `docs/runtime-boundaries.md`

**Interfaces:**
- Consumes: Task 1 registry.
- Produces: `work["cancellation"]` set-once intent; `work["owner"] = creator` (Task 5 builds on it); event `CancellationRequested`; `CANCELLATION_ACTIVE`/`CANCELLATION_ALREADY_REQUESTED` rejections; prepared ops cancelled with `WORK_CANCELLED`.

- [ ] **Step 1: Write failing tests** — zero-effect cancellation (prepared op → cancel → dispatch makes zero `FakeOA` calls, op `cancelled`/`WORK_CANCELLED`, waits cancelled); prohibitions during cancellation (`propose_action`, `revise_plan`, `revise_document`, `register_wait`, `bind_contract` on establishing work, `request_completion` → `CANCELLATION_ACTIVE`); second request new id → `CANCELLATION_ALREADY_REQUESTED` and original intent unchanged; replay of the original command id returns the stored accepted receipt; cancellation of an establishing work accepted; intent survives `verify_pending`/`expire_waits`/`recover`; malformed payload variants raise `CommandError` and persist nothing; authority: actor without grants → `AUTHORITY_DENIED`, `work.intervene` admin accepted; CAS conflict → `STATE_VERSION_CONFLICT`; concurrent same command id → one receipt, one `CancellationRequested` event; evidence intake still accepted during cancellation; Review-Focus tests from Task 3 lines.
- [ ] **Step 2: RED** — new tests fail with `COMMAND_UNSUPPORTED` (kind not yet routed).
- [ ] **Step 3: Implement** — route the four kinds in `_apply` to `_intervene`; `_request_cancel` per settled contract; `_cancel_prepared` gains `reason` parameter (default `STALE_INTENT`); cancellation gates in `_propose` (after owner+capability), management kinds (after owner gate), and defensive dispatch guard; `_create` adds `"owner": actor`; update `tests/test_runtime.py` probe in the same change.
- [ ] **Step 4: GREEN** — full suite passes (baseline probe amended).
- [ ] **Step 5: Commit** — runtime.py + test_runtime.py + test_interventions.py + docs: `feat(runtime): request_cancel stops new work durably`.

### Task 4: finalize_cancel

**Files:**
- Modify: `work_runtime/runtime.py` (`_finalize_cancel`)
- Test: `tests/test_interventions.py` (class `FinalizeCancelTests`)
- Modify: `docs/runtime-boundaries.md`

**Interfaces:**
- Consumes: `work["cancellation"]` from Task 3.
- Produces: terminal `closed`/`cancelled` with `completion` closure record; events `WorkCancelled`; `CANCELLATION_NOT_REQUESTED`, `CANCEL_ACKNOWLEDGEMENT_MISMATCH`, `OUTCOME_UNRESOLVED` behavior.

- [ ] **Step 1: Write failing tests** — finalize without request → `CANCELLATION_NOT_REQUESTED`; zero-effect finalize with `[]` closes cancelled (never `succeeded`, closure records empty acknowledgement + dispositions); timeout path: dispatch with `timeout_after_commit` (one real effect) → finalize `[]` → `OUTCOME_UNRESOLVED` → `reconcile` recovers the one effect → finalize `[]` → `CANCEL_ACKNOWLEDGEMENT_MISMATCH` (blockers list the succeeded id) → finalize `[op]` accepted, closure stores `external_id`, outcome `cancelled`, `oa.accepted_count() == 1`; real process death via `python3 -m work_runtime worker --crash-after-effect` then same reconciliation+acknowledgement flow; missing lookup (`lookup → None`) and malformed lookup result cannot finalize (`OUTCOME_UNRESOLVED`); malformed payload variants (non-list, dup ids, empty string id, extra keys) raise `CommandError`; fresh finalize after close → `WORK_NOT_ACTIONABLE`; replay after close returns stored receipt (Review Focus 1); admin finalize accepted.
- [ ] **Step 2: RED** — fails `COMMAND_UNSUPPORTED`.
- [ ] **Step 3: Implement** — `_finalize_cancel` per settled contract.
- [ ] **Step 4: GREEN** — full suite passes.
- [ ] **Step 5: Commit** — `feat(runtime): finalize_cancel closes on exact succeeded-effect acknowledgement`.

### Task 5: Ownership gating and transfer_owner

**Files:**
- Modify: `work_runtime/runtime.py` (`_manager`/`_intervener`/`_is_admin` helpers; owner gates in `_apply` management kinds, `_propose`, `dispatch`; `_transfer_owner`)
- Test: `tests/test_interventions.py` (class `OwnershipTests`)
- Modify: `docs/runtime-boundaries.md`

**Interfaces:**
- Consumes: `work["owner"]` from Task 3.
- Produces: event `OwnerTransferred`; `TRANSFER_SAME_OWNER`; legacy adoption semantics; owner gates later mirrored by Task 6 replay.

- [ ] **Step 1: Write failing tests** — new work stores owner=creator; transfer to valid target accepted, persists actor/from/to/reason; old owner: `revise_plan`/`revise_document`/`register_wait`/`request_completion`/`propose_action` → `AUTHORITY_DENIED` (fresh), prepared intents invalidated `OWNERSHIP_TRANSFERRED`, dispatch of a still-prepared old-owner op → `cancelled` (never an external call); in-flight op preserved across transfer (attempts/actor/key unchanged) and reconcilable after the old owner's grants are fully revoked; waiting/expired waits owned by prior owner reassigned; new owner re-proposes → same operation id (business key stable), dispatch succeeds; evidence writers unaffected (source authority kept); same-owner → `TRANSFER_SAME_OWNER`; unknown target or target without `work.manage` → `AUTHORITY_DENIED`; transfer during cancellation accepted and intent retained; legacy ownerless work (owner key stripped via direct DB edit): grant-only mutations still work, non-admin transfer denied, admin transfer adopts ownership and afterwards grant-only non-owner mutations denied (Review Focus 5); malformed payload raises.
- [ ] **Step 2: RED** — `COMMAND_UNSUPPORTED`.
- [ ] **Step 3: Implement** — helpers + gates + `_transfer_owner` per settled contract.
- [ ] **Step 4: GREEN** — full suite passes.
- [ ] **Step 5: Commit** — `feat(runtime): accountable owner transfer with current-authority gating`.

### Task 6: Replay requires current authority (B2)

**Files:**
- Modify: `work_runtime/runtime.py` (`_replay_denial`, `_observed_version`, hook into `command()` after fingerprint match)
- Test: `tests/test_interventions.py` (class `ReplayAuthorityTests`)
- Modify: `docs/runtime-boundaries.md`

**Interfaces:**
- Consumes: authority helpers from Task 5.
- Produces: fresh unpersisted `AUTHORITY_DENIED` with current observed version; stored receipts never modified on denial.

- [ ] **Step 1: Write failing tests** — `create_work` replay after `work.manage` revoked → fresh `AUTHORITY_DENIED` (observed version = current work version), `get_command` still returns the original accepted receipt; `record_evidence` replay after `evidence.write` revoked or source identity changed → denied; `propose_action` replay by former owner after transfer → denied with current version, stored receipt untouched; capability revoked → denied; management replay after `work.manage` revoked → denied; intervention replay after owner transfer → denied; `migrate_policy` replay by non-admin → denied; authority intact → stored receipt returned verbatim even after close; fingerprint mismatch still `COMMAND_ID_REUSED`; denial persists nothing (no new events/state_version bump).
- [ ] **Step 2: RED** — replay currently returns stored receipt despite lost authority.
- [ ] **Step 3: Implement** — `_replay_denial` per settled contract; call between fingerprint match and stored-receipt return.
- [ ] **Step 4: GREEN** — full suite passes.
- [ ] **Step 5: Commit** — `feat(runtime): command replay rechecks current authority before returning receipts`.

### Task 7: migrate_policy, actual contract revisions, verify_pending source check

**Files:**
- Modify: `work_runtime/runtime.py` (`_migrate`, `_propose` actual `contract_revision` on prepare/re-admission, `dispatch` revision check, `verify_pending` source check)
- Test: `tests/test_interventions.py` (classes `MigrationTests`, `PendingSourceTests`)
- Modify: `docs/runtime-boundaries.md`

**Interfaces:**
- Consumes: registry (Task 1), `ExpensePolicyV2` (Task 2).
- Produces: event `PolicyMigrated`; migration rejection codes; per-work pinned versions observable by restart.

- [ ] **Step 1: Write failing tests** — authority (owner and manager denied, admin accepted); establishing work → `CONTRACT_NOT_ACTIVE`; cancelled work → `CANCELLATION_ACTIVE`; payload family id mismatch → `MIGRATION_FAMILY_MISMATCH` before lookup; unregistered version → `MIGRATION_TARGET_UNREGISTERED`; same version → `MIGRATION_TARGET_UNCHANGED`; dispatched/unknown op → `OUTCOME_UNRESOLVED` and nothing mutated; strengthened requirement: low-amount v1 work with verified v1 approval migrates to v2 → E05 `applicable`/`pending`, old `{digest}` approval becomes `invalid` (disposition recorded), new v2 approval re-satisfies, re-propose re-admits the SAME operation id (stable key) with `contract_revision` now 2, old revision 1 proposal → `CONTRACT_REVISION_MISMATCH`; accepted external evidence survives migration (source+verifier revalidation) and E08 stays satisfied; pending stays pending through migration, then `verify_pending` under a same-family custom policy whose approval source differs invalidates the old-source pending proof without verifying it (never "reappears"); invalid stays invalid (no resurrection); two works pinned to different versions in one runtime both loadable and independently evaluable; restart with same registry keeps the pin, restart without the pinned version raises (no implicit migration either direction); old command receipts byte-identical after migration; atomic rollback: custom target whose `evaluate` raises (and one whose `validate_evidence` raises) → exception propagates, binding/revision/evidence/ops/events all unchanged, no `PolicyMigrated` event; document invalid under target (custom policy rejecting the document) → `CommandError`, nothing persisted; plan/document revisions preserved; Review Focus 4 tests.
- [ ] **Step 2: RED** — `COMMAND_UNSUPPORTED`.
- [ ] **Step 3: Implement** — `_migrate` per settled contract order; `_propose`/`dispatch` actual-revision changes; `verify_pending` source check.
- [ ] **Step 4: GREEN** — full suite passes.
- [ ] **Step 5: Commit** — `feat(runtime): explicit admin policy migration with evidence revalidation and actual revisions`.

### Task 8: docs/interventions.md

**Files:**
- Create: `docs/interventions.md`

- [ ] **Step 1: Write the reference** — the four commands (exact payloads, CAS, dedup), authority matrix (owner/manager/admin/legacy), cancellation lifecycle (intent → prohibitions → resolution → exact acknowledgement → closure; acknowledgement ≠ compensation), transfer semantics (invalidation, reassignment, legacy adoption, replay), registry + migration (validation, revalidation, revision, rollback, no implicit upgrade), the new rejection codes, and honest limitations (deferred: revocation, distributed fencing, cross-domain). Link `runtime-boundaries.md`; every link must resolve (`scripts/check_docs.py`).
- [ ] **Step 2: Verify** — `python3 scripts/check_docs.py` exits 0; `python3 -m unittest tests.test_docs -v` passes.
- [ ] **Step 3: Commit** — `docs: intervention lifecycle reference`.

### Task 9: Gates, demos, report

- [ ] **Step 1: Full gates** — `python3 scripts/check_docs.py`; `python3 -m unittest discover -s tests -v` (all green, count = 172 baseline + new, baseline intent preserved); `python3 -m work_runtime demo`; publishing demo via `python3 -m work_runtime publish-demo` (or the cli's documented subcommand); `python3 -m compileall -q work_runtime tests scripts`.
- [ ] **Step 2: Write `.agents/notes/2026-10-13-S3-lifecycle-core-report.md`** — exact RED/GREEN commands and test names per task, commit hashes, baseline count evidence, remaining risks/limits.
- [ ] **Step 3: Commit** — `docs: S3 lifecycle core worker report`; then send `worker_done` with the summary and commit range.

## Self-Review

- Spec coverage: cancellation (Tasks 3–4), responsibility (5–6), registry + migration (1, 7), V2 (2), tests/verification list from the spec's Verification section mapped into test classes (S2→Cancellation/Finalize, S3→Ownership/Replay, S4→Migration), docs (8), gates/report (9). Deferred items are labeled, not implemented — matches scope.
- Step scan: each step names files, signatures and exact codes; no TBDs.
- Type consistency: `_policy_for(work)`, `_intervener(actor, work)`, `_manager(actor, work)`, `_is_admin(actor)`, `_cancel_prepared(db, work_id, reason=...)`, `_replay_denial(db, actor, work_id, kind, payload)` used consistently.
- Review Focus: five lines, each with an owning task test.
- Proportion: plan is decision-dense, code-free except settled contracts quoted from D15.
