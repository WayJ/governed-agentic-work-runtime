# S15 Wave 2 — support-ticket demo, installer stages, truth docs plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship the support-ticket family demo (forward + crash-recovery chapters), additive installer module+console stages, and same-commit truth docs carrying the freeze verdict.

**Architecture:** New `work_runtime/support_demo.py` following `compensation_demo`/`publishing_demo` conventions; `cli.py` entry wiring (`support-demo` subcommand + `inspect --policy support-ticket` choice, the all-demos convention); `scripts/verify_install.py` stages 24/25 (module + NEW console, D90 disclosure); truth docs (`adapter-contract.md`, `verification.md`, `runtime-boundaries.md`) + bilingual README sections.

**Spec:** S15 plan Wave-2 stories/DoD/S4 (read from `main`), recon D4, Wave-1 plan note, `docs/verification.md`, `scripts/verify_install.py` D90 precedent.

## Global Constraints

- `work_runtime/runtime.py` (`80bf721b…`) and `work_runtime/adapters.py` (`ce132f24…`) byte-unchanged; any needed lifecycle edit = stop and `ask`.
- No doc_sync_map row fires: mapped files (runtime.py, adapters.py, check_docs.py, check_site.py, ingress.py, publication*.py, file_adapter.py) stay untouched. cli.py / verify_install.py / support_demo.py / tests / docs are unmapped.
- One release commit for the whole wave (demo + cli + installer + docs + README + tests land together — the S14 demo-commit precedent); RED/GREEN evidence recorded in ledger/worker_done.
- TDD for demo/installer/CLI behavior; Python >=3.9, stdlib, unittest.
- No compensation, no rule-card changes, no UI/website redesign (website.md/website/ untouched — disclosed gap); bilingual README only.
- Baseline: 1123 tests OK (skipped=2); final counts exact, skip delta explained.

## Family recap used by demo/docs (from Wave 1, commits 5defdfc..5135947)

SupportPolicy `support-ticket`/`demo-1`, goal `ticket.dispatched`; document `{id= ticket reference, summary, severity∈{critical,high,normal}|None, category∈{billing,technical,account}|None}`; rules T01 severity / T02 category (None ⇒ unknown, blocks), T03 urgent SLA (critical ≤60, high ≤240; unknown severity ⇒ unknown), T04 tracker acceptance; capability `ticket.dispatch`; grants `agent{work.manage, ticket.dispatch}`, `support-desk{evidence.write}`, `lead{work.intervene}`; business key `digest([family, capability, ticket_reference])` (digest-free, version-stable; changed content under a used reference ⇒ `OPERATION_CONTENT_CONFLICT`); FakeIssueTracker: one issue per reference (#N), alias reuse, `TICKET_REFERENCE_CONTENT_CONFLICT` business rejection, `timeout_after_commit`; `run_crash_worker` (exit 73).

---

### Task 1: Demo module — RED `tests/test_support_demo.py` (story, independent store counts, repeatability, hygiene, no-secrets) → implement `work_runtime/support_demo.py` (forward chapter steps 1-5, crash chapter steps 6-9, FINAL_LINE, store-read closing truth, printed `inspect --policy support-ticket`).

Chapter 1: TCK-1001 critical/billing — propose blocked `APPLICABILITY_UNRESOLVED` (unresolved severity+category) → triage revise → blocked `REQUIREMENT_UNSATISFIED` (no SLA) → SLA 45min recorded/verified → propose `dispatch-once` → dispatch → `#1` confirmed → completion closed/succeeded.
Chapter 2: TCK-1002 high/technical — SLA 120 → propose → real `run_crash_worker` (exit 73, issue committed) → restart `recover()` → confirmed `#2`, one attempt, no re-send → completion.
FINAL_LINE = "2 works; issues filed: 2; crash-recovered receipts: 1; effects re-sent: 0".

### Task 2: CLI wiring — RED CLI tests (`support-demo` unknown command; `inspect --policy support-ticket` invalid choice) → add subparser + inspect choice + imports in `cli.py` → GREEN.

### Task 3: Installer stages — RED `SupportInstallerProofTests` (import `scripts/verify_install.py`, `require_support_proof` missing) → add `SUPPORT_FINAL_LINE`, `require_support_proof(stdout, source)` (independent store proof: recomputed business keys, one issue per reference, receipts 2 all accepted, crashed op one attempt, tracker-source accepted proofs event_id = operation ids, both works closed/succeeded) + main() stages 24 (module) / 25 (console, NEW-coverage disclosure) + docstring stage list. Proof tests: real demo stdout passes; tampered/short stdout raises.

### Task 4: Truth docs + freeze verdict + README (same commit): adapter-contract.md S15 section (FakeIssueTracker contract/store, reference-keyed document identity, conflict semantics, no-compensation link refusal); verification.md S15 coverage section + `support-demo` in How-to-verify; runtime-boundaries.md family sentence + freeze verdict (zero lifecycle edits, pins `80bf721b`/`ce132f24`, two disclosed constraints: document identity keyed on the ticket reference; one reference = one governed dispatch, changed content dead-ends `OPERATION_CONTENT_CONFLICT`); README.md + README.zh-CN.md sections. reference-scenarios.md: no edit (expense-domain推演 doc) — disclosed.

### Task 5: Full verification — five gates + support-demo run + `scripts/verify_install.py` (needs pip index access; if the environment is offline, disclose as environment-limited with the stage-level proof tests as evidence), byte pins, single release commit, worker_done.

## Review Focus

1. Demo must not trust stdout for state — closing truth read from SQLite directly. → Task 1 tests.
2. No secrets/credentials; output contains no 64-hex digests. → Task 1 test (`assertNotRegex` 64-hex).
3. The installer proof must fail on doctored output (a proof that cannot fail proves nothing). → Task 3 tests.
4. Console stage disclosed as new coverage, docstring stage list consistent with main(). → Task 3 + Task 5 (grep).
5. Bilingual parity: README sections say the same thing in both files. → Task 5 (read-back).
