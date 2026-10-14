# S8 Evidence Revocation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task. Coordinator owns dispatch; no extra workers.

**Goal:** Explicit durable revocation changes current proof authority while preserving original closure/receipts/accepted effects.

**Architecture:** Add a command and terminal proof status inside existing schema1 transactions; existing policy verified filters and dispatch revalidation remain. Independent core integration pins the consumed branch before parallel visible/demo clients. Final integration alone publishes.

**Tech Stack:** Python>=3.9 stdlib/unittest, SQLite, vanilla offline UI/actual Chrome; zero dependencies.

**Spec:** [Ratified design](../specs/2026-10-14-s8-evidence-revocation-design.md), [sprint](../sprints/2026-10-14-S8-plan.md), RFC001/003 and AGENTS.md.

## Global Constraints

- D33–D37 public command/event/DTO fields exact; zero schema/new dependency/tenantauth/writeUI changes.
- Immutable candidate data/fingerprints/old receipts/completion; no implicit reopen/re-execution/compensation.
- Current source+evidence.revoke or work.intervene administrator; explicit replay revalidation.
- Runtime edits owe runtime-boundaries; exact raw values/no *_raw browser parsing, DESIGN actualbrowser proof for client changes.
- One core owner first; independent integration control owns all merges/pushes, never remove its active checkout.

## Review Focus

- Cached accepted revoke after grant/source loss must deny without mutating stored receipt; owner/manage/write alone cannot revoke.
- Multiple sufficient proofs and unrelated waits must not create false changed-rule/deadline-reset events.
- Unbound cancellation closure remains closed under late verification/recovery; old snapshots are not silently rewritten.
- Revoked accepted proof never regenerates by repeating confirmed operation; real uncertain acceptance still reconciles once.
- Reader additions derive only valid real IDs/citations, cancellation completion never invents proof citations; actual async browser notice/read must stay text-only/exact.

### Task1: Durable command, permanent proof and closure invariant

**Files:** runtime.py; tests/test_evidence_revocation.py and focused interventions tests; runtime-boundaries/interventions/verification/evidence-revocation docs. Policies untouched unless a proven blocker is routed to coordinator.

**Interfaces:** Consume existing Runtime.command envelope and policy.evaluate/action_blockers; produce exact D33 revoke payload/receipt and D34 event plus stable proofstatusrevoked, additive new-command resend evidence_status. Private plumbing builder-owned, no new public fault API.

- [ ] Read full ratification and write scoped plan. Run622 baseline; reproduce D-1 via create-unbound/request_cancel/finalize with accepted receipt but wrong status.
- [ ] Write failing tests before handler: source/admin authorization/replay loss, stale/cross-work/unknown/malformed/status codes and one-version/one-event SQL atomicity.
- [ ] Implement minimal command routing, replay predicate/status UPDATE and actual recomputed requirement/wait event dispositions; preserve source fingerprint/data/old receipts.
- [ ] RED/GREEN pending/verified revocation, invalid/double rejection, new-command resend status, cached original receipt, fresh replacement, migration/restart/partial proofs in expense/publishing.
- [ ] RED/GREEN dispatch held REQUIREMENT_UNSATISFIED with zero attempts/calls; replacement readmits same key; all wait states/deadlines/cancelled terminality; confirmed/in-flight retain actual effects.
- [ ] RED/GREEN closed-bound/unbound/outcomes/completion equality; fix unbound _evaluate closed guard. Inject exception/process death inside revoke transaction using test-owned hooks/subclass, assert all table rollback; actual external-acceptance process death then revoke/reconcile proves one effect.
- [ ] Run meaningful core/previous tests and gates applicable to current slice, update mapped/public command docs; no unsupported coverage claims. Commit/report hashes/REDGREEN/counters/risks and idle.

### Task2: Independent core review/assembly

**Files:** separate integration control/carrier, scoped report; no product fixes.

- [ ] Compare actual core implementation with D33–D37, independently reproduce material invariants and validate test evidence/counters; original owner fixes material findings.
- [ ] Integration merges accepted core into carrier and reports exact source commit/API for clients; no main release yet.

### Task3: Real reproducible demo and installed entrypoints (after Task2)

**Files:** revocation_demo.py,cli.py,verify_install.py, focused demo/CLI tests, README EN/ZH/demo docs and final current-scope docs. No Runtime or viewer changes.

**Interfaces:** Consume accepted Task1 command/receipt/status and real adapters; produce python3 -m work_runtime revocation-demo / work-runtime revocation-demo on fresh stores, both families and counted effects.

- [ ] Write actual failing demo/CLI checks, implement deterministic predispatch hold/replacement, uncertain/confirmed retained effect and closed correction scenarios; no direct SQL fake states.
- [ ] Print real current/historical facts and inspect paths, not invented metrics. Add installed verifier actual module+console trials outside checkout, assert counts/state/fingerprint/operation keys.
- [ ] Update truthful bilingual public docs/current deferred lists only for verified delivered behavior; prior4demos remain, no key-rotation/distributed promise. Commit/report and idle.

### Task4: Derived reader and visible current/historical correction (parallel Task3)

**Files:** inspection.py,web/app.js/app.css, relevant reader/UI tests and gui/gui-api docs; no Runtime/CLI/verifier changes.

**Interfaces:** D37 work_detail top-level revoked_evidence/completion_revoked_evidence_ids and evidence[].id, raw fields unchanged.

- [ ] Failing reader tests for real revoked proofs/closed success/cancel completion/exact huge/raw/zero writes, then derive inside existing read-only snapshot. No new persisted flags.
- [ ] Actual Chrome RED missing closed-revoked notice, then bilingual explicit notice/citation count and readable revoked chips using DESIGN tokens. Never parse *_raw or introduce writes.
- [ ] Actual desktop390/320 screenshots/keyboard/poll/error regression, current versus historical proof/outcome distinctions and full-table equality; contract/docs checks. Commit/report and idle.

### Task5: Independent final acceptance and release

- [ ] Integration combines scoped client/core commits, independently checks complete S1–S6 scenarios and every DoD item; re-run all5AGENTS gates, all prior4+newdemo, core+newtests, standalone14, installed verifier and actualbrowser/reader invariants. Disclose counts/skips/engine limits/TD-1.
- [ ] supervibe accept before main integration; doc-sync/coverage claims current. Then supervibe merge, ordinary main push, exact remote/head/actualfinalCI success; primarycheckout sync only if clean, preserve userassets/worktrees/livepreviews. No force push/self-teardown.
- [ ] Publish exact release/acceptance/effect/GUI proof once and idle; root verifies, then schedules next remaining roadmap slice.

## Self-review

All6DoD lines map to command/history/effect tests, public visible/installed clients and independent release. Public payload/event/DTO names match ratification. Review Focus cases owned by Task1/Task4; no policy rewrite or new global missing-command gate. Scoped owners expand concrete test names/actions before coding, observe RED then GREEN and report real effects.
