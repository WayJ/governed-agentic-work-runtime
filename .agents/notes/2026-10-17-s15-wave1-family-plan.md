# S15 Wave 1 — support-ticket family implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the support-ticket business family (policy + GitHub-issue-shaped fake adapter + crash machinery) as new code, proving the frozen command surface with `runtime.py`/`adapters.py` byte-unchanged.

**Architecture:** One family module `work_runtime/support.py` mirroring `work_runtime/publishing.py` (policy + fake external adapter + grants + crash-worker helper), one test module `tests/test_support.py` mirroring `tests/test_publishing.py` (document/evidence/evaluate units, conformance mixin, domain adapter tests, governed flow through the real Runtime, recovery and crash tests).

**Tech Stack:** Python >=3.9 standard library only, `unittest` only, SQLite stores.

**Spec:** `docs/superpowers/sprints/2026-10-17-S15-plan.md` (read from `main` — the worktree predates it), `.agents/notes/2026-10-17-s15-design-recon.md` (same), `docs/adapter-contract.md`, `docs/RFC-001-core-semantics.md`, AGENTS.md.

## Global Constraints

- `work_runtime/runtime.py` and `work_runtime/adapters.py` byte-unchanged. SHA-256 pins recorded at task start: `runtime.py` = `80bf721b3369a6fb865fd6aba0e57804a69eb8587431f8fa6edf1183fc53f4b3`, `adapters.py` = `ce132f24d84c17a083bcf0b61bf90e1c62ff75faf2ec52fe2c7348ab86b6985e`. Asserted again at end; any needed lifecycle edit = STOP and `orca orchestration ask` (freeze-gap finding), never edit silently.
- New code files only: `work_runtime/support.py`, `tests/test_support.py`. No compensation for this family, no rule-card/publication changes, no UI/README/website/AGENTS/roadmap edits, no doc_sync row fires.
- Python >=3.9, zero runtime dependencies, stdlib `unittest`.
- TDD per AGENTS.md: meaningful failing test first, record RED evidence, minimal implementation, GREEN.
- Work only in this worktree; commit on `WayJ/s15-third-family-freeze`; never merge main or push.
- Baseline suite: 1077 tests, OK (skipped=2). Final run must state exact counts and explain any skip delta.

## Family design (locked by sprint D1–D5 + recon)

- **Policy** `SupportPolicy`: `id="support-ticket"`, `version="demo-1"`, `goal="ticket.dispatched"`, `evidence_sources={"sla": "support-desk", "accepted": "tracker"}`. No `compensation_capabilities` (D94: no compensation).
- **Document** (exact fields): `{"ticket_reference", "summary", "severity", "category"}` — `ticket_reference`/`summary` nonempty strings; `severity` ∈ `{"critical","high","normal"}` or `None`; `category` ∈ `{"billing","technical","account"}` or `None`. `None` = triage-unresolved (unknown). An out-of-vocabulary string is a document `ValueError`, never admissible.
- **Rules** (evaluate):
  - `T01` severity resolved: applicability `unknown` when `severity is None` else `applicable`; satisfied iff resolved (vocabulary enforced at validation).
  - `T02` category resolved: same shape for `category`.
  - `T03` urgent SLA: applicability from severity — `None` → `unknown` (unknown propagates to the dependent rule), `critical`/`high` → `applicable`, `normal` → `not_applicable`. When applicable, satisfied iff a verified `sla` evidence from `support-desk` covers the current document digest with `response_target_minutes` within the severity budget (V1: critical ≤ 60, high ≤ 240).
  - `T04` tracker acceptance (goal evidence, produced by dispatch): always `applicable`, satisfied iff verified `accepted` evidence from `tracker` covering the current digest.
- **action_blockers**: only capability `"ticket.dispatch"` is supported; blockers = requirements except `T04` that are unknown/conflict or applicable-unsatisfied (publishing's C04 pattern). Unknown-blocking surfaces as `APPLICABILITY_UNRESOLVED` through the unchanged runtime.
- **operation_key** = `digest([self.id, capability, document["ticket_reference"]])` — the ticket-reference business key: no document digest (distinct family shape per recon), stable across policy versions (id constant, version excluded). Consequence (tested, disclosed): a changed document under an already-used ticket reference is `OPERATION_CONTENT_CONFLICT`, never a second operation/issue.
- **SupportPolicyV2(SupportPolicy)**: `version="demo-2"`, tightens the critical SLA budget to ≤ 30 minutes (a V1-compliant 31–60 min critical SLA no longer satisfies). Inherits `operation_key` unchanged.
- **FakeIssueTracker**: SQLite store, tables `receipts(key PRIMARY KEY, digest, result)` (per-key call/lookup surface) and `issues(ticket_reference PRIMARY KEY, issue_number UNIQUE, digest, document)` — one issue per ticket reference, GitHub-issue-shaped. Receipts: `{"status":"accepted","external_id":"#<n>","digest":…,"ticket_reference":…,"issue_number":<int>,"issue_state":"open"}`. Contract: `AdapterContract(actions=("ticket.dispatch",), idempotency_scope="adapter-store:key", retention="lifetime-of-store", lookup_consistency="authoritative-by-key", uniqueness=("ticket.reference",), supports_action_context=True)`. Behaviors: digest mismatch → `ValueError` before writes; same-key replay validates digest (mismatch → `ValueError("Idempotency key reused with different content")`); fresh key + existing reference + same digest → alias receipt reusing the same issue number (no second issue); fresh key + existing reference + different digest → queryable business rejection `{"status":"rejected","reason":"TICKET_REFERENCE_CONTENT_CONFLICT", …}` with zero new effects; fresh reference → new sequential issue number. `timeout_after_commit=True` raises `TimeoutError` after the store commit. Helpers: `lookup(key)`, `issue_count()`, `issue_for_reference(ref)`. `action`/`compensates` kwargs accepted (opt-in): action must be `ticket.dispatch` (None normalizes to it), a link-carrying call raises `ValueError` (no compensation exists).
- **support_grants()**: `{"agent": {"work.manage", "ticket.dispatch"}, "support-desk": {"evidence.write"}, "lead": {"work.intervene"}}` — trusted-local configuration, not authentication.
- **Crash machinery**: `crash_worker_script(runtime_path, tracker_path, operation_id)` + `run_crash_worker(...)` in `support.py` (publishing_demo pattern): a real child process dispatches the prepared operation with `fault=lambda: os._exit(73)` — death after the tracker committed, before the outcome is recorded.

## Review Focus

1. Out-of-vocabulary severity/category strings must fail `validate_document` — an unknown value never enters as within-policy. → Task 1 test.
2. Unknown severity must make T03 (SLA) `unknown` too — unknown propagates to dependent rules, and proposal is refused `APPLICABILITY_UNRESOLVED`. → Tasks 3/6 tests.
3. Same ticket reference + changed content must conflict (`OPERATION_CONTENT_CONFLICT`), same-work and cross-work — never a second issue. → Tasks 5/6 tests.
4. After acceptance, recovery must never re-send: attempts stay 1, one issue, one receipt row, through both timeout-reconcile and real process-death recovery. → Tasks 7/8 tests.
5. A wrong-budget SLA (or wrong source / stale digest) must not satisfy T03. → Task 3 tests.

---

### Task 1: Policy document validation + module skeleton

**Files:** Create `work_runtime/support.py` (SupportPolicy skeleton: id/version/goal/evidence_sources/validate_document), `tests/test_support.py`.

- [ ] RED: `SupportDocumentTests` — valid documents cover all severity/category values and both None; exact field set enforced; nonempty `ticket_reference`/`summary`; out-of-vocabulary severity/category strings raise `ValueError`; `severity`/`category` may be None.
- [ ] Run: `python3 -m unittest discover -s tests -p test_support.py -v` → module/class missing (RED evidence).
- [ ] Implement minimal `SupportPolicy.validate_document`.
- [ ] GREEN + commit `support: add support-ticket policy document admission shape`.

### Task 2: Evidence shapes

**Files:** same.

- [ ] RED: `SupportEvidenceShapeTests` — `sla` requires exactly `{digest, response_target_minutes}` with positive int minutes; `accepted` requires `{digest, external_id}` nonempty string; unknown kinds invalid.
- [ ] Implement `validate_evidence` minimal. GREEN + commit `support: add SLA and acceptance evidence shapes`.

### Task 3: Requirement evaluation (T01–T04)

- [ ] RED: `SupportEvaluateTests` — severity/category None ⇒ T01/T02 unknown+pending; resolved ⇒ applicable+satisfied; T03 matrix (None→unknown, critical/high→applicable, normal→not_applicable); T03 satisfied only by verified `sla` from `support-desk` at current digest within budget (critical 60 ok / 61 not, high 240 ok / 241 not); wrong source / stale digest / unverified do not satisfy; T04 satisfied by verified `accepted` from `tracker` at current digest.
- [ ] Implement `evaluate`. GREEN + commit `support: add ticket requirement rules with unknown-blocking SLA`.

### Task 4: Blockers, business key, V2

- [ ] RED: tests — `action_blockers("ticket.dispatch")` excludes T04, blocks unknown/pending others, empty when all satisfied; unsupported capability blocked; `operation_key` reference-bound (same reference across different documents ⇒ same key; different reference ⇒ different key; V2 inherits identical key); `SupportPolicyV2` critical budget 30 (30 ok / 31 not).
- [ ] Implement `action_blockers`, `operation_key`, `SupportPolicyV2`. GREEN + commit `support: add dispatch blockers, ticket-reference business key, policy V2`.

### Task 5: FakeIssueTracker (conformance + domain)

**Files:** same two files.

- [ ] RED: `FakeIssueTrackerConformanceTests(AdapterConformanceMixin, unittest.TestCase)` with the four hooks (fresh temp-dir store; `effect_count=issue_count`) — six mixin tests fail on missing class. Plus `FakeIssueTrackerDomainTests`: digest mismatch `ValueError` zero writes; one issue per reference across different keys (alias receipt, same issue number); same reference + different digest under fresh key → rejected `TICKET_REFERENCE_CONTENT_CONFLICT`, zero new issues; `timeout_after_commit` raises after commit with the issue persisted; `lookup` missing key `None`; `issue_for_reference` returns the stored issue; link-carrying call and unknown action raise `ValueError`.
- [ ] Implement `FakeIssueTracker` minimal. GREEN + commit `support: add GitHub-issue-shaped fake tracker adapter`.

### Task 6: Governed forward flow through the real Runtime

- [ ] RED: `SupportFlowTests` — helper `support_grants()` + initialize (create/bind/plan). Unknown-blocking: severity None → propose rejected `APPLICABILITY_UNRESOLVED` with T01/T03 blockers; category None likewise; resolved severity but missing SLA → `REQUIREMENT_UNSATISFIED`; wrong-budget SLA still blocked. Admission+flow: record in-budget SLA (actor `support-desk`), verify, propose accepted, replay propose (same command id and fresh command id) ⇒ same operation id (business-key dedupe), dispatch → `confirmed_succeeded`, `external_id "#1"`, accepted proof from `tracker`; `request_completion` ⇒ closed/succeeded (business closure); tracker `issue_count()==1`. Cross-work: second work with same ticket_reference → `OPERATION_CONTENT_CONFLICT`. Same-work content revision after a prepared op → re-propose `OPERATION_CONTENT_CONFLICT` (disclosed family limit).
- [ ] Implement `support_grants()` (flow wiring only; no lifecycle edits). GREEN + commit `support: run support-ticket family end-to-end on the frozen runtime`.

### Task 7: Timeout recovery + policy-version key stability

- [ ] RED: `SupportRecoveryTests` — `timeout_after_commit` dispatch → `outcome_unknown`, issue exists; new Runtime `reconcile` → `confirmed_succeeded`, attempts 1, receipts 1, `issue_count` 1 (nothing re-sent). `SupportMigrationTests` — registry `{demo-1, demo-2}`, propose under V1, `migrate_policy` by admin `lead` → prepared op invalidated (`POLICY_MIGRATED`), re-propose under V2 returns the SAME operation id (readmit on the stable business key); a V1-budget critical SLA (45 min) satisfies V1 T03 but leaves V2 T03 pending after migration.
- [ ] No new production code expected (runtime machinery already covers it) — if a lifecycle edit seems needed, STOP and ask (freeze gap). GREEN + commit `support: recover unknown outcomes and keep the business key stable across policy versions`.

### Task 8: Crash-after-acceptance recovery (process death)

- [ ] RED: `SupportCrashRecoveryTests` — real child `run_crash_worker` (exit 73) after tracker commit; parent restarts `Runtime` and `recover(FakeIssueTracker)` → operation `confirmed_succeeded`, exactly one attempt, one issue, one receipt row (original receipt recovered, never re-sent); work completes after recovery.
- [ ] Implement `crash_worker_script`/`run_crash_worker` in `support.py`. GREEN + commit `support: recover a crashed dispatch by ticket reference without re-sending`.

### Task 9: Full verification

- [ ] `python3 -m unittest discover -s tests -v` — exact counts, skip delta explained (baseline 1077/2).
- [ ] `python3 -m compileall -q work_runtime tests scripts` clean.
- [ ] Gates unchanged: `python3 scripts/check_docs.py`, `python3 scripts/check_site.py` (no doc edits — verify still pass).
- [ ] Byte pins re-asserted (`shasum -a 256` equals start pins; the two files absent from the commit diff).
- [ ] Final commit (if anything pending) + worker_done with hashes, RED/GREEN evidence, remaining risks.
