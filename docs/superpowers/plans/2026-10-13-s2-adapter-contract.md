# S2 Adapter Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Foundation A of E2/S2 — frozen `AdapterContract` + `receipt_is_valid`, a reusable `AdapterConformanceMixin`, a declared FakeOA descriptor, and a Runtime whose accepted-receipt evidence source is owned by policy with a declared-capability preflight that holds unsupported operations before any attempt or external call.

**Architecture:** One new module `work_runtime/adapter_contract.py` (dataclass + validators), one test-library module `tests/adapter_conformance.py` (mixin over four fixture hooks), FakeOA gains a class-level `contract`, and `work_runtime/runtime.py` gains two pre-attempt gates (policy accepted-source configuration, declared capability) plus policy-owned proof identity in `_resolve`. No ingress, publishing, CLI, policy-module, README or ledger changes.

**Tech Stack:** Python >=3.9 standard library only, `unittest`, SQLite.

**Spec:** `docs/superpowers/specs/2026-10-13-s2-trusted-boundaries.md` (local copy; **authoritative carrier copy with the D8 builder decisions B2/B3/M3–M5 and the D9 clarification was read from `../sprint-s2-trusted-boundaries/` — it postdates this checkout's copy and governs where the local text is underspecified**).

## Global Constraints

- Python >= 3.9; zero runtime dependencies; standard-library `unittest` only.
- Preserve all 63 S1 tests and existing expense CLI/API behavior; legacy adapters without a `contract` attribute keep working unchanged.
- Ownership: ONLY `work_runtime/adapter_contract.py`, `work_runtime/runtime.py`, `work_runtime/adapters.py`, `tests/adapter_conformance.py`, `tests/test_adapter_contract.py`, `docs/adapter-contract.md`, `docs/runtime-boundaries.md`, this plan and its report. No ingress/publishing/cli/policy/README/verification/ledger/baseline-test edits.
- Any commit touching `work_runtime/runtime.py` or `work_runtime/adapters.py` must include the owed `docs/runtime-boundaries.md` update in the SAME commit.
- Public interfaces pinned by design: `AdapterContract` fields `actions/idempotency_scope/retention/lookup_consistency/uniqueness`; `receipt_is_valid(result, expected_digest) -> bool`; mixin hooks `make_adapter()/sample_document()/changed_document()/effect_count(adapter)`; hold reason `ADAPTER_ACTION_UNSUPPORTED`. No speculative DSL/authserver.
- No merge, no push. No nested agents. Coordinator mail before a new file, after tests, before worker_done.
- TDD: every behavior change has observed RED then GREEN; record verbatim commands/output in the report.

## Review Focus

- A declared contract that excludes the capability must hold BEFORE any attempt or external call — zero `attempts` entries, zero `execute` invocations, zero effects (a hold-after-call would double-apply when re-dispatched) → Task 4 Step 1 `test_unsupported_declared_capability_holds_with_zero_attempts_or_calls`.
- A malformed descriptor (string/dict instead of `AdapterContract`) must fail closed with `CommandError`, never be silently treated as missing (which would dispatch) → Task 4 Step 1 `test_malformed_descriptor_fails_closed_before_external_call`.
- Invalid accepted-source configuration must fail closed even mid-flight — a config broken between the external effect and proof adoption must never adopt a proof, and must recover once fixed → Task 3 Step 1 `test_resolve_fails_closed_and_never_adopts_proof_under_broken_config`.
- Over-strict receipt validation would quarantine compatible adapters: extra receipt fields must remain valid, and `rejected` status must remain a *valid* (resolvable, non-quarantined) result → Task 1 Step 1 `test_valid_accepted_and_rejected_receipts` (extra-fields case).
- Legacy adapters without a descriptor must dispatch exactly as before (S1 compatibility) → Task 4 Step 1 `test_legacy_adapter_without_contract_still_dispatches` plus the 63 baseline tests.

---

### Task 1: `adapter_contract.py` — frozen AdapterContract and receipt_is_valid

**Files:**
- Create: `work_runtime/adapter_contract.py`
- Test: `tests/test_adapter_contract.py` (new)

**Interfaces:**
- Produces: `AdapterContract` frozen dataclass, fields in order `actions: Tuple[str, ...]`, `idempotency_scope: str`, `retention: str`, `lookup_consistency: str`, `uniqueness: Tuple[str, ...]`, all required, `__post_init__` validates invariants (nonempty tuple of unique nonempty-string actions; the three scalar fields nonempty strings; `uniqueness` a tuple of nonempty strings — an empty tuple means no additional uniqueness promise) raising `ValueError`; `valid_contract(value: object) -> bool` (isinstance + invariant recheck, never raises); `receipt_is_valid(result: object, expected_digest: str) -> bool` with the exact truth table of the current inline `_resolve` check (dict; `digest == expected_digest`; `status in ("accepted","rejected")`; `external_id` nonempty string; extra fields allowed).

- [ ] **Step 1: Write the failing tests** — in `tests/test_adapter_contract.py`: `ReceiptIsValidTests` (valid accepted; valid rejected; extra fields still valid; each malformed variant built as its own fresh dict — non-dict `"ok"`/`None`/`42`; missing `digest`/`status`/`external_id`; wrong digest; status `"pending"`; empty and non-string `external_id`) and `AdapterContractTests` (valid construction round-trips fields; `dataclasses.FrozenInstanceError` on attribute mutation; `ValueError` per invalid construction — empty/duplicate/non-string/empty-string actions, non-tuple actions, empty or non-string scalars, non-tuple uniqueness, empty-string uniqueness entry; empty `uniqueness=()` accepted). Dual import shim for the mixin (Task 2) can land now: `try: from adapter_conformance import AdapterConformanceMixin / except ImportError: from tests.adapter_conformance import ...`.

```python
def test_valid_accepted_and_rejected_receipts(self):
    digest = "d" * 64
    self.assertTrue(receipt_is_valid(
        {"status": "accepted", "external_id": "OA-1", "digest": digest}, digest))
    self.assertTrue(receipt_is_valid(
        {"status": "rejected", "external_id": "OA-2", "digest": digest,
         "extra": {"note": "extra fields remain allowed"}}, digest))
```

- [ ] **Step 2: Run to verify RED**

Run: `python3 -m unittest discover -s tests -p test_adapter_contract.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'work_runtime.adapter_contract'`.

- [ ] **Step 3: Implement `work_runtime/adapter_contract.py`** — module docstring states: fields are adapter assertions, not remotely verified guarantees; metadata does not authenticate an adapter. Private `_check_invariants(contract)` raises `ValueError` with a specific message per rule; `__post_init__` calls it; `valid_contract` wraps isinstance + `_check_invariants` in try/except `ValueError`; `receipt_is_valid` is the extracted `_resolve` condition (uses `result.get(...)`, `bool(result["external_id"])`).

- [ ] **Step 4: Run to verify GREEN**

Run: `python3 -m unittest discover -s tests -p test_adapter_contract.py -v`
Expected: all `ReceiptIsValidTests`/`AdapterContractTests` OK.

### Task 2: FakeOA descriptor and the reusable conformance mixin

**Files:**
- Create: `tests/adapter_conformance.py`
- Modify: `work_runtime/adapters.py` (FakeOA class attribute)
- Test: `tests/test_adapter_contract.py` (`FakeOAConformanceTests`)

**Interfaces:**
- Consumes: Task 1 (`AdapterContract`, `receipt_is_valid`, `valid_contract`); `work_runtime.policy.digest`.
- Produces: `tests/adapter_conformance.py::AdapterConformanceMixin` — plain class (NOT a `TestCase`) with four hooks `make_adapter()`, `sample_document() -> dict`, `changed_document() -> dict` (must digest differently from `sample_document()`), `effect_count(adapter) -> int`, each raising `NotImplementedError` with a docstring stating the disposable-fixture requirement; five `test_*` methods (below). FakeOA gains `contract = AdapterContract(actions=("expense.submit",), idempotency_scope="adapter-store:key", retention="lifetime-of-store", lookup_consistency="authoritative-by-key", uniqueness=("invoice.id",))`.

- [ ] **Step 1: Write the failing tests** — `FakeOAConformanceTests(AdapterConformanceMixin, unittest.TestCase)` in `tests/test_adapter_contract.py`: setUp makes a `tempfile.TemporaryDirectory`; `make_adapter` returns `FakeOA(<fresh unique path under the temp dir>)`; `sample_document` = `document()`; `changed_document` = `document(amount=130000)`; `effect_count` = `adapter.accepted_count()`. Mixin tests (all in `tests/adapter_conformance.py`): `test_declared_contract_meets_metadata_invariants` (contract present, `isinstance`/`valid_contract`, mutation raises `FrozenInstanceError`); `test_same_key_replay_returns_identical_receipt_with_one_effect` (`first == second`, `receipt_is_valid(first, digest(document))`, `effect_count == 1`); `test_same_key_different_content_raises_without_new_effect` (`assertRaises(ValueError)` on `execute(key, changed, digest(changed))`, `effect_count` stays 1); `test_lookup_existing_key_returns_committed_receipt`; `test_lookup_missing_key_returns_none`.

- [ ] **Step 2: Run to verify RED**

Run: `python3 -m unittest discover -s tests -p test_adapter_contract.py -v`
Expected: collection/`ImportError` for `adapter_conformance`, or (with the shim bypassed) `test_declared_contract_meets_metadata_invariants` failing — FakeOA has no `contract` attribute.

- [ ] **Step 3: Implement the mixin and the FakeOA descriptor** — mixin module docstring: tests mutate the adapter's store, so hooks must return explicit disposable fixtures; domain-specific uniqueness is tested separately by each adopting domain. The replay/mismatch/lookup tests pin FakeOA's existing behavior — record them as characterization pins if already green once the descriptor exists.

- [ ] **Step 4: Run to verify GREEN**

Run: `python3 -m unittest discover -s tests -p test_adapter_contract.py -v` → all OK.
Run: `python3 -m unittest discover -s tests -v` → 63 baseline + new tests OK (FakeOA descriptor must not disturb the S1 suites; `adapters.py` touched — docs owed in the Task 5 same commit, so no commit before then).

### Task 3: Runtime — policy-owned accepted receipt source, fail-closed configuration (B2)

**Files:**
- Modify: `work_runtime/runtime.py` (`_resolve`, `dispatch`, `reconcile`, new `_accepted_source`)
- Test: `tests/test_adapter_contract.py`

**Interfaces:**
- Consumes: `receipt_is_valid` (Task 1); `Policy.evidence_sources` (existing protocol attr).
- Produces: `Runtime._accepted_source(self) -> str` — `CommandError` when `policy.evidence_sources.get("accepted")` is missing, non-string or empty; called (a) in `dispatch` after the authority/blockers hold, immediately before attempt creation, (b) in `reconcile` after the status early-return, before `adapter.lookup`, (c) in `_resolve` at the top of the valid-result branch, before adopting an accepted proof. `_resolve` replaces its inline validation with `receipt_is_valid(result, op["document_digest"])` and replaces the hard-coded `"oa"` proof source (dict field + evidence-row source) with `self._accepted_source()`.

- [ ] **Step 1: Write the failing tests** — local policies in `tests/test_adapter_contract.py` (fresh class-level dicts, never mutate `ExpensePolicy.evidence_sources` in place): `GatewayAcceptedPolicy` (accepted → `"oa-gateway"`), `MissingAcceptedPolicy`/`EmptyAcceptedPolicy`/`NonStringAcceptedPolicy` (key absent / `""` / `None`), all else inherited (same id/version so `_work` accepts them). Tests:
  - `test_policy_owned_accepted_source_is_adopted` — full expense flow under `GatewayAcceptedPolicy` → dispatch confirms; white-box `sqlite3` read of the runtime DB: the `kind == "accepted"` evidence row for the operation has `source == "oa-gateway"` and no row has `source == "oa"`; E08 satisfied; `request_completion` accepted.
  - `test_dispatch_fails_closed_without_accepted_source` — subTest over the three broken policies: `assertRaises(CommandError)` on dispatch; persisted op still `prepared`/`ready` with `attempts == []`; `oa.accepted_count() == 0`.
  - `test_reconcile_fails_closed_before_querying` — dispatch under `ExpensePolicy` with `FakeOA(timeout_after_commit=True)` → `outcome_unknown`; swap `runtime.policy = MissingAcceptedPolicy()`; reconcile with a counting FakeOA wrapper → `CommandError`, wrapper `looked_up == 0`.
  - `test_resolve_fails_closed_and_never_adopts_proof_under_broken_config` — dispatch under `ExpensePolicy` with `fault=lambda: setattr(runtime, "policy", MissingAcceptedPolicy())` → `CommandError`; `oa.accepted_count() == 1` (external effect already happened), persisted op `dispatched` with exactly one `outcome_unknown` attempt, **no `kind == "accepted"` evidence row**; then `runtime.policy = GatewayAcceptedPolicy()` and `reconcile` → `confirmed_succeeded` with the accepted row under `oa-gateway`.
  - `test_terminal_operation_early_returns_stay_config_independent` — after a confirmed dispatch under `ExpensePolicy`, swap in `MissingAcceptedPolicy`; `reconcile` and `dispatch` on the terminal op both return it unchanged without raising (B2 pin; expected green-on-base, report as pin).

- [ ] **Step 2: Run to verify RED**

Run: `python3 -m unittest discover -s tests -p test_adapter_contract.py -v`
Expected: the four behavior tests fail (source `"oa"` ≠ `"oa-gateway"`; dispatch/reconcile/resolve succeed instead of raising `CommandError`); the terminal-early-return pin passes.

- [ ] **Step 3: Implement minimally in `runtime.py`** — add `_accepted_source`; insert the three call sites; swap the inline `_resolve` condition for `receipt_is_valid`; use the configured source in the proof dict and the evidence INSERT. Import `receipt_is_valid` from `.adapter_contract`.

- [ ] **Step 4: Run to verify GREEN**

Run: `python3 -m unittest discover -s tests -p test_adapter_contract.py -v` → OK.
Run: `python3 -m unittest discover -s tests -v` → full suite OK (63 baseline preserved — ExpensePolicy still configures `accepted: "oa"`).

### Task 4: Runtime — declared-capability preflight (M3/M4, B3 malformed descriptor)

**Files:**
- Modify: `work_runtime/runtime.py` (`dispatch`, module-level `_declared_contract`)
- Test: `tests/test_adapter_contract.py`

**Interfaces:**
- Consumes: `valid_contract` (Task 1); `AdapterContract` (Task 1).
- Produces: module-level `_declared_contract(adapter) -> Optional[AdapterContract]` — `None` when `getattr(adapter, "contract", None)` is `None` (legacy trusted adapter); `CommandError` when present but `not valid_contract(descriptor)`; else the descriptor. In `dispatch`, immediately after the accepted-source check and before attempt creation: if a contract is declared and `op["capability"] not in contract.actions`, set `dispatch_state="held"`, `reason="ADAPTER_ACTION_UNSUPPORTED"`, save op, emit `DispatchHeld`, return op.

- [ ] **Step 1: Write the failing tests** — in `tests/test_adapter_contract.py`: `ExportCapablePolicy(ExpensePolicy)` overriding only `action_blockers` to allow `("expense.submit", "expense.export")` (inherited `operation_key` already keys on capability); grants add `expense.export` to the agent; local `export_action(runtime)` helper proposing `capability="expense.export"`. Local adapters: `CountingFakeOA` (wraps a FakeOA, `contract = FakeOA.contract`, counts `executed`/`looked_up`), `ExportCapableOA(FakeOA)` (contract actions `("expense.submit", "expense.export")`, same other fields), `StringContractOA(FakeOA)`/`DictContractOA(FakeOA)` (`contract = "expense.submit"` / a dict). Tests:
  - `test_unsupported_declared_capability_holds_with_zero_attempts_or_calls` — prerequisites + `export_action` accepted → `dispatch(op, CountingFakeOA(FakeOA(...)))` → `dispatch_state == "held"`, `reason == "ADAPTER_ACTION_UNSUPPORTED"`, `executed == looked_up == 0`, persisted `attempts == []`, `oa.accepted_count() == 0`, a `DispatchHeld` event with that reason, work not `needs_attention`.
  - `test_held_operation_dispatches_with_compatible_adapter` — continue from held: `dispatch(op, ExportCapableOA(same oa path))` → `confirmed_succeeded`, `oa.accepted_count() == 1`.
  - `test_malformed_descriptor_fails_closed_before_external_call` — subTest string/dict descriptor: `assertRaises(CommandError)`; `attempts == []`; `accepted_count() == 0`.
  - `test_legacy_adapter_without_contract_still_dispatches` — normal expense.submit op dispatched through a counting wrapper with NO `contract` attribute → `confirmed_succeeded`, wrapper `executed == 1` (pin; expected green-on-base, report as pin).

- [ ] **Step 2: Run to verify RED**

Run: `python3 -m unittest discover -s tests -p test_adapter_contract.py -v`
Expected: the three behavior tests fail (current code dispatches `expense.export` straight through: `in_flight`/`executed == 1`, no `CommandError`); the legacy pin passes.

- [ ] **Step 3: Implement minimally in `runtime.py`** — `_declared_contract` + the held branch in `dispatch` between the accepted-source check and attempt creation (M3/M4: after grant/rule checks, immediately before attempt creation).

- [ ] **Step 4: Run to verify GREEN**

Run: `python3 -m unittest discover -s tests -p test_adapter_contract.py -v` → OK.
Run: `python3 -m unittest discover -s tests -v` → full suite OK.

### Task 5: documentation and the scoped behavior commit

**Files:**
- Create: `docs/adapter-contract.md`
- Modify: `docs/runtime-boundaries.md`
- Commit: all Task 1–4 code + both docs in ONE commit (same-commit doc rule).

**Interfaces:**
- Consumes: final behavior of Tasks 1–4.
- Produces: the adapter-contract reference (pinned public surfaces, trust statement, preflight semantics, mixin contract, FakeOA values, test-name table) and the owed `docs/runtime-boundaries.md` update (receipt validation now via `receipt_is_valid`; dispatch boundary gains the accepted-source `CommandError` gate and the `ADAPTER_ACTION_UNSUPPORTED` hold; accepted proof source owned by `policy.evidence_sources['accepted']`, expense keeps `oa`).

- [ ] **Step 1: Write `docs/adapter-contract.md`** — sections: purpose and trust statement (assertions, not verification; metadata does not authenticate); `AdapterContract` field table + invariants; `receipt_is_valid` rules (extra fields allowed; invalid → quarantine per runtime-boundaries); optional metadata / legacy adapters; declared-capability preflight (order: after authority/blockers, config check first, then capability; hold semantics; compatible-adapter re-dispatch; malformed descriptor `CommandError`); policy-owned accepted source and the three B2 call sites; `AdapterConformanceMixin` (four hooks, five tests, disposable fixtures, domain uniqueness separate); FakeOA's declared values; verification table with exact test names. Link `docs/runtime-boundaries.md` and the spec; every local link must resolve (`scripts/check_docs.py` gate).

- [ ] **Step 2: Update `docs/runtime-boundaries.md`** — dispatch-boundary numbered list gains the two pre-attempt gates; adapter-result-contract section names `receipt_is_valid`; the accepted-receipt paragraph states the source is `policy.evidence_sources["accepted"]` (was hard-coded `oa`); verification section points at `tests/test_adapter_contract.py` for the new guarantees.

- [ ] **Step 3: Run all four gates**

Run: `python3 scripts/check_docs.py` → 0 broken.
Run: `python3 -m unittest discover -s tests -v` → full suite OK (record exact count).
Run: `python3 -m work_runtime demo` → crash demo succeeds, prints "external applications created: 1".
Run: `python3 -m compileall -q work_runtime tests scripts` → silent.

- [ ] **Step 4: Commit behavior + docs together**

```bash
git add work_runtime/adapter_contract.py work_runtime/runtime.py work_runtime/adapters.py \
        tests/adapter_conformance.py tests/test_adapter_contract.py \
        docs/adapter-contract.md docs/runtime-boundaries.md
git commit -m "feat: adapter contract, conformance mixin, policy-owned receipt source"
```

### Task 6: evidence report, final commit, worker_done

**Files:**
- Create: `.agents/notes/2026-10-13-S2-adapter-contract-report.md`

- [ ] **Step 1: Write the evidence report** — executive summary; verbatim RED/GREEN command output per task (including which mixin/legacy tests were pins green-on-base); full test names grouped per guarantee; total suite count (baseline 63 + new); gates output; scope limits and remaining risks (e.g., descriptor not checked on reconcile-only path by design; conformance replay/mismatch are characterization pins); commit hashes.

- [ ] **Step 2: Final verification and docs commit**

```bash
python3 -m unittest discover -s tests -v
git add docs/superpowers/plans/2026-10-13-s2-adapter-contract.md \
        .agents/notes/2026-10-13-S2-adapter-contract-report.md
git commit -m "docs: S2 adapter-contract plan and evidence report"
```

- [ ] **Step 3: Report and idle** — coordinator `check`, then `orca orchestration send --type worker_done` (exactly once) with the 3-sentence summary, `--files-modified`, `--report-path`; then idle.

## Self-Review

- Spec coverage: Foundation A bullets map to Tasks 1–4 (module+descriptor, mixin, policy-owned source+B2, preflight+M3/M4+B3); docs/adapter-contract.md + same-commit runtime-boundaries → Task 5; RED/GREEN reporting → Tasks 1–4 step 2/4 + Task 6. Ingress/publishing untouched (Foundation B / wave-2 ownership).
- Step scan: test steps carry exact assertions; code steps carry exact signatures, call-site positions and pinned values; no placeholder steps.
- Type consistency: `valid_contract`/`receipt_is_valid`/`AdapterContract` names match across Tasks 1–4; mixin hook names match the design verbatim; hold reason string `ADAPTER_ACTION_UNSUPPORTED` matches design and docs.
- Review Focus: all five lines name their owning test.
- Proportion: plan length is comparable to the S1 plan for a similar-magnitude change.
