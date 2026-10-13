# S2 Foundation A — adapter contract evidence report

Worker: S2 adapter foundation developer (Orca dispatch `task_6d3f71c9e93d`, Claude Code session in `s2-adapter-contract`). Date: 2026-10-13.

**Executive summary.** Implemented Foundation A of the S2 design: frozen `AdapterContract` + `receipt_is_valid` in a new `work_runtime/adapter_contract.py`, a reusable `AdapterConformanceMixin` over four fixture hooks with FakeOA adopting it and declaring its contract, and Runtime changes making the accepted-receipt evidence source policy-owned (`evidence_sources["accepted"]`, fail-closed `CommandError` in dispatch/reconcile/_resolve per B2) and holding unsupported declared capabilities with `ADAPTER_ACTION_UNSUPPORTED` before any attempt or external call (M3/M4/B3). Every behavior change has observed RED→GREEN evidence; the full suite is 87 tests OK (63 S1 baseline preserved + 24 new), all four configured gates pass including the expense crash demo with exactly one external application, and both docs landed in the same commit as the runtime/adapters change. Nothing left in scope; commits `4da9e16` (behavior+docs) and `9f8a1e4`-pending (this plan/report) — final hashes below.

## Scope and ownership

Owned files touched (nothing else): `work_runtime/adapter_contract.py` (new), `work_runtime/runtime.py`, `work_runtime/adapters.py`, `tests/adapter_conformance.py` (new), `tests/test_adapter_contract.py` (new), `docs/adapter-contract.md` (new), `docs/runtime-boundaries.md`, `docs/superpowers/plans/2026-10-13-s2-adapter-contract.md` (new, this sprint's plan), this report. No ingress/publishing/cli/policy/README/verification/ledger/baseline-test edits. No merge, no push.

Authoritative design: carrier copy `../sprint-s2-trusted-boundaries/docs/superpowers/specs/2026-10-13-s2-trusted-boundaries.md` including D8 (B2/B3/M1–M5) and D9 addenda — the local checkout's spec copy (7dd96a3) predates them; coordinator confirmed D8 is authoritative before start.

## RED/GREEN evidence (verbatim commands and output)

### Task 1 — `adapter_contract.py` module

Command: `python3 -m unittest discover -s tests -p test_adapter_contract.py -v`

RED (before implementation):

```
    from work_runtime.adapter_contract import AdapterContract, receipt_is_valid, valid_contract
ModuleNotFoundError: No module named 'work_runtime.adapter_contract'
----------------------------------------------------------------------
Ran 1 test in 0.000s

FAILED (errors=1)
```

GREEN (after implementing the dataclass, `_check_invariants`, `valid_contract`, `receipt_is_valid`): `Ran 10 tests in 0.000s` — `OK`.

### Task 2 — FakeOA descriptor + conformance mixin

Same command. RED (mixin written, FakeOA descriptor missing):

```
FAIL: test_declared_contract_meets_metadata_invariants (test_adapter_contract.FakeOAConformanceTests)
AssertionError: unexpectedly None : adapter must declare a contract
----------------------------------------------------------------------
Ran 15 tests in 0.008s

FAILED (failures=1)
```

GREEN (after adding `FakeOA.contract`): `Ran 15 tests in 0.008s` — `OK`; full suite `Ran 78 tests in 1.799s` — `OK`.

**Pins (green-on-base once the module existed, by design):** the four mixin behavior tests (`test_same_key_replay_returns_identical_receipt_with_one_effect`, `test_same_key_different_content_raises_without_new_effect`, `test_lookup_existing_key_returns_committed_receipt`, `test_lookup_missing_key_returns_none`) characterize FakeOA's pre-existing replay/mismatch/lookup behavior with real SQLite effects; the design asked for these as reusable conformance coverage, and the RED was carried by the missing descriptor.

### Task 3 — policy-owned accepted source + fail-closed configuration (B2)

Same command. RED: `FAILED (failures=6)` —

```
FAIL: test_dispatch_fails_closed_without_accepted_source (...variant='missing')
FAIL: test_dispatch_fails_closed_without_accepted_source (...variant='empty')
FAIL: test_dispatch_fails_closed_without_accepted_source (...variant='non-string')
FAIL: test_policy_owned_accepted_source_is_adopted (...)
FAIL: test_reconcile_fails_closed_before_querying (...)
FAIL: test_resolve_fails_closed_and_never_adopts_proof_under_broken_config (...)
AssertionError: CommandError not raised
```

(`test_policy_owned_accepted_source_is_adopted` failed on the stored accepted-proof source being `"oa"` instead of `"oa-gateway"` — the M3/M4-required non-oa test-local policy.)

GREEN (after 7 runtime.py replacements: `_accepted_source` helper; call sites in dispatch before the attempt, in reconcile before lookup, in `_resolve`'s valid-result branch; inline validation replaced by `receipt_is_valid`; proof source/INSERT use the configured source): `Ran 20 tests in 0.265s` — `OK`; full suite `Ran 83 tests in 2.104s` — `OK`.

**Pin:** `test_terminal_operation_early_returns_stay_config_independent` was green-on-base and pins B2's "terminal/cancelled early returns remain no-ops".

### Task 4 — declared-capability preflight (M3/M4, B3)

Same command. RED: `FAILED (failures=4)` —

```
FAIL: test_unsupported_declared_capability_holds_with_zero_attempts_or_calls (...)
FAIL: test_held_operation_dispatches_with_compatible_adapter (...)
FAIL: test_malformed_descriptor_fails_closed_before_external_call (...variant='string')
FAIL: test_malformed_descriptor_fails_closed_before_external_call (...variant='dict')
```

GREEN (after `_declared_contract` gate + the held branch between the config check and attempt creation): `Ran 24 tests in 0.348s` — `OK`; full suite `Ran 87 tests in 1.990s` — `OK`.

**Pin:** `test_legacy_adapter_without_contract_still_dispatches` was green-on-base and pins "missing descriptor preserves trusted legacy adapters" (the 63 baseline tests pin the same via every S1 adapter).

## Test inventory (24 new; suite 63 → 87)

- `ReceiptIsValidTests` (5): valid accepted/rejected + extra fields; non-dict; missing fields; wrong digest; bad status/external_id. Each malformed variant is a fresh dict (S1 lesson).
- `AdapterContractTests` (4): valid round-trip; frozen mutation raises; 12 invalid-construction variants raise `ValueError`; empty uniqueness allowed; `valid_contract` rejects non-contract values.
- `FakeOAConformanceTests` (5, via `AdapterConformanceMixin`): metadata invariants; identical-receipt/one-effect replay; same-key different-content `ValueError` without a second effect; lookup-existing matches receipt; lookup-missing `None`.
- `PolicyReceiptSourceTests` (5): policy-owned source adopted (white-box evidence-row source `oa-gateway`, no `oa` row, E08 satisfied, completion accepted); dispatch fails closed (missing/empty/non-string, fresh fixture per variant, zero attempts/effects); reconcile fails closed before querying (lookup count 0); resolution never adopts a proof under mid-flight broken config and recovers after fix; terminal early returns config-independent.
- `DeclaredCapabilityTests` (4): unsupported capability holds with zero attempts/calls/effects + `DispatchHeld` event + work not `needs_attention`; held op dispatches with a compatible adapter; malformed descriptor (string/dict, fresh fixtures) `CommandError` before any effect; legacy no-contract adapter dispatches unchanged.

## Gates (all four configured gates, post-commit state)

```
python3 scripts/check_docs.py
  checked 26 markdown files, 80 local links, 0 broken
python3 -m unittest discover -s tests -v
  Ran 87 tests in 2.259s — OK
python3 -m work_runtime demo
  1..6 all asserts pass; "Evidence-backed completion → SUCCEEDED; external applications created: 1"
python3 -m compileall -q work_runtime tests scripts
  (silent — clean)
```

## Commits

- `4da9e16` — `feat: adapter contract, conformance mixin, policy-owned receipt source` (7 files: both modules + runtime + adapters + both test files + both docs; `docs/runtime-boundaries.md` in the SAME commit as the `runtime.py`/`adapters.py` changes per the doc_sync_map).
- `49331f4` — `docs: S2 adapter-contract plan and evidence report` (plan + this report).

## Judgment calls (rulings)

1. **Pre-attempt gate order:** accepted-source config check runs *before* the capability preflight (design pinned both "immediately before attempt creation" but not their relative order). Config errors are hard local failures and take precedence over the soft `held` state.
2. **`_resolve` guard breadth:** `_accepted_source()` guards the whole valid-result branch, so a *rejected* result under broken config also raises instead of recording `confirmed_failed`. Stricter than B2's letter ("before adopting an accepted receipt"), conservative in the same direction, recoverable via reconcile after the config is fixed; never blocks proof adoption.
3. **`_resolve` config break is transactional:** the check runs inside `_resolve`'s transaction, so a raise rolls back — no half-recorded resolution (verified by the mid-flight fault test).
4. **Import shim:** `tests/test_adapter_contract.py` imports the mixin via `try: from adapter_conformance ... except ImportError: from tests.adapter_conformance ...` so both `discover -s tests` (the configured gate and acceptance-scenario form) and `python3 -m unittest tests.test_adapter_contract` invocations work.
5. **Conformance/pin labeling:** mixin behavior tests, the terminal-early-return test and the legacy-adapter test are characterization pins (green-on-base), reported as such; all behavior changes proper (module, descriptor, source ownership, fail-closed gates, preflight) have RED evidence above.

## Remaining risks and scope limits

- Descriptor claims are adapter assertions, not remotely verified guarantees; declaring metadata does not authenticate an adapter (documented in module docstring and `docs/adapter-contract.md`).
- The descriptor is validated at dispatch; the reconcile-only path does not re-check it (design pins the dispatch gate). An adapter swapped between dispatch and reconcile could be queried — lookup only, never an effect.
- `AdapterContract` is not re-exported from `work_runtime/__init__.py` (design pins the module path; the publishing worker imports from `work_runtime.adapter_contract` the same way the ingress boundary owns its own module).
- One policy per runtime database remains a prototype constraint; no distributed exactly-once or production-safety claim (unchanged from S1).
- Deferred minors from the final self-review: `_declared_contract`'s `Optional[object]` return annotation could name `AdapterContract`; one verification-table row in `docs/adapter-contract.md` references the `AdapterContractTests` class rather than per-method rows.

## Process notes

Superpowers workflow used inline as dispatched: brainstorming (design-understanding pass against the authoritative carrier spec), writing-plans (`docs/superpowers/plans/2026-10-13-s2-adapter-contract.md`), executing-plans + test-driven-development (four RED→GREEN cycles above), final whole-branch review performed as a **self-review** because the dispatch forbids nested agents (weaker than a fresh reviewer; the integration session's independent review is the compensating control). Plan workspace ledger deleted after this report; git history + this report are the record.

## Review correction addendum (second dispatch, 2026-10-13, task_6363aef31a62)

**Correction.** Two defects in the descriptor gate, found by integration review at tip 88a73d6: (1) `_declared_contract` used `getattr(adapter, "contract", None)`, conflating an absent attribute with an explicitly present `contract = None`, so a present `None` silently took the legacy path and dispatched; (2) `valid_contract` caught only `ValueError`, so an incomplete `AdapterContract` created via `object.__new__` (fields never set) leaked `AttributeError` from `_check_invariants` instead of returning `False` — and dispatch crashed with `AttributeError` rather than failing closed with `CommandError`. D8/master review: only a missing attribute is legacy; a present `None` or broken instance is malformed.

**Why the first self-review missed it.** The review pass validated the gates against the design bullets but read `getattr(..., None)` as a faithful implementation of "metadata is optional" without distinguishing the two sources of `None`; the malformed-value probe matrix covered wrong types (string, dict) but never a construction-bypass instance, so `valid_contract`'s `except ValueError` was assumed complete from `_check_invariants`' documented error contract. Presence-vs-value conflation and construction-bypass inputs are exactly the input classes a metadata gate needs explicit tests for.

**Fix (TDD, tests first).** RED — `python3 -m unittest discover -s tests -p test_adapter_contract.py -v` → `FAILED (failures=1, errors=1)` of 27: `FAIL: test_present_none_descriptor_fails_closed_before_external_call` (`AssertionError: CommandError not raised`) and `ERROR: test_incomplete_contract_instance_is_invalid_and_fails_closed` (`AttributeError: 'AdapterContract' object has no attribute 'actions'`); `test_absent_descriptor_keeps_legacy_dispatch` was green-on-base (pin). Minimal fix: a `_MISSING_CONTRACT` sentinel in `runtime.py::_declared_contract` (absent → legacy; present `None` → malformed → `CommandError` before any attempt/external call) and `valid_contract` catching `(ValueError, AttributeError)`. GREEN — same command: `Ran 27 tests ... OK`; full suite `Ran 90 tests ... OK`; gates: `check_docs` 0 broken, expense demo success line "external applications created: 1", `compileall` clean. Both docs updated to state that only an absent attribute is legacy and a present `None`/incomplete instance is malformed; `docs/runtime-boundaries.md` committed in the same commit as `runtime.py`.

**Commit.** `9fdb883` (code + tests + both docs + this addendum; `docs/runtime-boundaries.md` in the same commit as `runtime.py`).
