# S1 Runtime Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the E1/S1 dispatch–reconciliation boundary: make repeated recovery idempotent, pin malformed/mismatched adapter-result quarantine and no-redispatch guarantees with regressions, and document them in `docs/runtime-boundaries.md`.

**Architecture:** One minimal behavior change in `work_runtime/runtime.py` (early-return guards in the three reconciliation write paths when persisted state already equals the target state), one new regression suite `tests/test_boundaries.py`, one new boundary document. No changes to `work_runtime/adapters.py` (audit found no adapter defect), policy, or existing tests.

**Tech Stack:** Python >=3.9 standard library only, `unittest`, SQLite.

**Spec:** `docs/superpowers/sprints/2026-10-13-S1-plan.md` (S1 stories wave 1, scenarios S1/S2/S5), `docs/RFC-003-runtime-protocol.md` §7 (persisted dispatch boundary), §9 P06/P07/P13. Coordinator dispatch messages 2026-10-13 (scoped boundary bugs only; adapter exceptions/malformed responses must leave inspectable uncertainty and never redispatch the same operation on recover; honest RED/GREEN; `docs/runtime-boundaries.md` committed together with every runtime/adapters change).

## Audit Findings (verified by throwaway probe, 2026-10-13, Python 3.9.6)

| area | finding | disposition |
|---|---|---|
| Malformed/mismatched adapter results | `_resolve` already validates shape (dict, `digest == operation document_digest`, `status in {accepted, rejected}`, nonempty string `external_id`) and quarantines violations as `outcome_unknown`/`ADAPTER_RESULT_INVALID` + `needs_attention`; recoverable when the adapter later returns a valid result | pin with passing regressions |
| Unsafe resend | `dispatch` requires `status == prepared`; uncertain/resolved operations are never re-executed; business-key dedup returns the existing operation across replays and recovery (probe: 1 `execute` call, 1 accepted application across dispatch/recover/reconcile loops) | pin with passing regressions |
| Recovery idempotency | **DEFECT** — repeated `reconcile`/`recover` on an unresolved operation re-appends events and re-bumps `state_version` on every call: lookup→None path (probe P1: 1→2 events, version 8→9), lookup-raises path (P2: 2→3), invalid-result path (P3: 1→3). A supervisor restart loop with a dead adapter grows history without bound and inflates versions | fix minimally (Task 2) |

## Global Constraints

- Python >= 3.9 (dev machine 3.9.6): no 3.10+ syntax (`match`, `X | Y` unions) in runtime code.
- Zero runtime dependencies; tests use standard-library `unittest` only.
- Ownership: `work_runtime/runtime.py`, `tests/test_boundaries.py` (new), `docs/runtime-boundaries.md` (new), this plan and the evidence report. Do NOT edit `work_runtime/adapters.py`, `work_runtime/policy.py`, `tests/test_runtime.py`, README, scripts, verification docs, sprint/epic ledgers.
- `docs/runtime-boundaries.md` must be committed in the same commit as the `runtime.py` change.
- Baseline: 35 tests pass; suite must stay green throughout except during observed RED steps.
- No merge, no push; `worker_done` after the final commit.
- Record RED/GREEN command output verbatim in the evidence report.

## Review Focus

- Non-dict adapter results (`execute`/`lookup` returning a string or `None`-shaped junk) must be quarantined, not crash `_resolve` → Task 3 malformed-variants test.
- A well-formed result carrying another content's digest must never confirm this operation → Task 3 mismatch test.
- Supervisor loops re-running `recover()` with a persistently broken adapter must not grow events/versions unboundedly → Task 1 tests (the defect).
- An adapter with no authoritative answer (`lookup` → None or raises) must yield inspectable `needs_attention` uncertainty, never a silent redispatch → Task 3 no-resend tests.
- Real process death after the external effect must still converge to exactly one external application across repeated recovery and command replays → Task 3 real-crash test.
- A *changed* failure reason between reconciles must still be recorded (guard must not over-suppress) → Task 3 reason-change test.

---

### Task 1: RED — reconciliation idempotency regressions

**Files:**
- Create: `tests/test_boundaries.py`

**Interfaces:**
- Consumes: `work_runtime.Runtime` (`dispatch`, `reconcile`, `recover`, `get_operation`, `get_work`, `events`), `work_runtime.demo` helpers (`demo_grants`, `document`, `initialize`, `prerequisites`, `action`, `send`).
- Produces: `BoundaryTests(unittest.TestCase)` with helper adapters used again by Task 3: `SilentAdapter` (execute raises `TimeoutError`, lookup → `None`), `FailingAdapter(exc)` (both raise), `MalformedAdapter(result)` (returns a configurable dict from execute and lookup, counts `execute_calls`), `CountingAdapter(inner)` (delegates to a real adapter, counts `executed`/`looked_up`).

- [ ] **Step 1: Write the three failing tests**

```python
def test_repeated_reconcile_without_authoritative_result_is_idempotent(self):
    op = self.submit()
    self.runtime.dispatch(op, SilentAdapter())
    first = self.runtime.reconcile(op, SilentAdapter())
    self.assertEqual((first["status"], first["reason"]),
                     ("outcome_unknown", "NO_AUTHORITATIVE_RESULT"))
    version = self.runtime.get_work("demo")["state_version"]
    events = len(self.runtime.events("demo"))
    second = self.runtime.reconcile(op, SilentAdapter())
    self.assertEqual(second, first)
    self.assertEqual(self.runtime.get_work("demo")["state_version"], version)
    self.assertEqual(len(self.runtime.events("demo")), events)
```

Same shape for `test_repeated_reconcile_with_failing_lookup_is_idempotent` (adapter `FailingAdapter(ConnectionError())`; assert one `OutcomeUnknown` event total and stable version across the second call) and `test_repeated_malformed_result_reconcile_is_idempotent` (`MalformedAdapter({"status": "accepted", "external_id": "OA-1"})` — digest missing; dispatch, then reconcile twice; assert reason `ADAPTER_RESULT_INVALID`, one `OperationResolved` event total, stable version).

- [ ] **Step 2: Run to verify RED**

Run: `python3 -m unittest tests.test_boundaries -v`
Expected: 3 failures — version/event counts differ on the second reconcile (observed probe: +1 event, +1 `state_version` per repeat).

### Task 2: Minimal idempotency guards in `runtime.py`

**Files:**
- Modify: `work_runtime/runtime.py` (`_unknown`, `reconcile` lookup-None path, `_resolve` invalid-result branch)

**Interfaces:**
- Produces: unchanged public signatures; new internal guarantee — reconciliation write paths perform no write and emit no event when persisted state already equals the target state (`status`+`reason` for the operation; `needs_attention` for the work where applicable).

- [ ] **Step 1: Guard `_unknown`** — after `_get_op`, return `op` unchanged when `op["status"] == "outcome_unknown" and op.get("reason") == reason`; else record as today.

- [ ] **Step 2: Guard `reconcile`'s lookup-None path** — load `work` via `self._work(db, op["work_id"])` before writing; return `op` unchanged when `op["status"] == "outcome_unknown" and op.get("reason") == "NO_AUTHORITATIVE_RESULT" and work["status"] == "needs_attention"`; else escalate as today (work stays sticky in `needs_attention` because `_evaluate` never exits it, so the guard cannot strand a re-escalation).

- [ ] **Step 3: Guard `_resolve`'s invalid-result branch** — `work` is already loaded before the validation `if`; inside the branch return `op` unchanged when `op["status"] == "outcome_unknown" and op.get("reason") == "ADAPTER_RESULT_INVALID" and work["status"] == "needs_attention"`; else quarantine as today. A *changed* reason still writes (transition recorded).

- [ ] **Step 4: Run to verify GREEN**

Run: `python3 -m unittest tests.test_boundaries tests.test_runtime -v`
Expected: 38 tests OK (3 new + baseline 35).

- [ ] **Step 5: Commit behavior only after Task 4 docs exist** (same-commit rule; see Task 4 Step 3).

### Task 3: Characterization regressions for quarantine and no-resend

**Files:**
- Modify: `tests/test_boundaries.py` (append tests; reuse Task 1 adapters)

**Interfaces:**
- Consumes: Task 1 adapters; `work_runtime.adapters.FakeOA` including `timeout_after_commit=True`; subprocess worker `python3 -m work_runtime worker --crash-after-effect` (exit 73).

- [ ] **Step 1: Write the pinning tests** (all expected GREEN immediately — these record existing correct behavior; report them as such)

> Deviation (2026-10-13, whole-branch review): `test_new_reconcile_failure_reason_is_recorded`
> is **not** green-on-base — it fails on 798d3c7 (3 `OutcomeUnknown` events vs the asserted 2)
> and enforces the Task 2 guards' no-over-suppress semantics, making it a fourth RED→GREEN
> regression. The other eight pins were green-on-base. The malformed-variants test was also
> strengthened post-review (per-variant fresh runtime + `execute_calls == 1`, RED `0 != 1`
> observed on three variants first) after the review showed a shared-business-key collision
> made three variants vacuous.

- `test_malformed_adapter_results_leave_inspectable_uncertainty` — subTests over non-dict result (`"ok"`), missing `digest`, bad `status` (`"pending"`), empty `external_id`: dispatch → `outcome_unknown`/`ADAPTER_RESULT_INVALID`, work `needs_attention`, attempt stays `outcome_unknown`, no `external_id` on the op.
- `test_mismatched_digest_result_is_quarantined` — valid shape, wrong digest: not confirmed, no OA evidence adopted, `request_completion` rejected `OUTCOME_UNRESOLVED`, E08 unsatisfied.
- `test_adapter_recovering_with_valid_result_confirms_operation` — wrong-digest adapter then corrected lookup result: `confirmed_succeeded`, `external_id` recorded, evidence row exists (probe P4).
- `test_recover_never_redispatches_uncertain_operation` — `CountingAdapter(FakeOA(..., timeout_after_commit=True))`: dispatch → `outcome_unknown` with `executed == 1`; `recover()` ×3 → `executed` stays 1, `confirmed_succeeded`; explicit `dispatch` again → still 1 (coordinator-requested regression).
- `test_execute_exception_then_recover_calls_adapter_once_and_escalates` — `FailingAdapter(ConnectionError())`: reason `ConnectionError`, attempts length 1; `recover(SilentAdapter())` ×2 → `execute_calls == 1`, `NO_AUTHORITATIVE_RESULT`, work `needs_attention`.
- `test_new_reconcile_failure_reason_is_recorded` — reconcile with `TimeoutError` then `ConnectionError`: two `OutcomeUnknown` events, final reason `ConnectionError` (guard does not over-suppress).
- `test_recover_with_nothing_to_do_is_idempotent` — prepared+dispatched-and-resolved mix, no pending evidence/waits: second `recover` adds no events and no version bumps.
- `test_real_crash_recovery_yields_exactly_one_external_application` — subprocess worker `--crash-after-effect` exits 73 with `oa.accepted_count() == 1`, local status `dispatched`; then `recover()` ×3 plus an explicit `dispatch` plus a replayed `propose_action` under a new command id → `confirmed_succeeded`, same `operation_id`, `accepted_count() == 1` (S1 acceptance scenario S2 evidence inside the suite).
- `test_recovery_business_dedup_returns_existing_operation` — after recovery, a fresh `propose_action` (new command id, current revisions) returns the existing operation id and `operation_status_at_decision="confirmed_succeeded"`; no second `OperationPrepared` event.

- [ ] **Step 2: Run to verify GREEN**

Run: `python3 -m unittest tests.test_boundaries -v`
Expected: 12 tests OK.

### Task 4: Boundary document and the scoped behavior commit

**Files:**
- Create: `docs/runtime-boundaries.md`
- Modify: none beyond Task 2/3 outputs

**Interfaces:**
- Consumes: final behavior of Tasks 2–3.
- Produces: the doc the supervibe `doc_sync_map` owes for `work_runtime/runtime.py`.

- [ ] **Step 1: Write `docs/runtime-boundaries.md`** — sections: trust model (local trusted code, principal names ≠ authentication, single coordinator); identity & dedup (command fingerprint → receipt replay, business key → operation identity, external idempotency key owned by the adapter); dispatch boundary (persisted attempt before the external call; staleness/authority re-checks; `held`/`cancelled` semantics); adapter result contract (exact validation rules and the `outcome_unknown`/`ADAPTER_RESULT_INVALID` + `needs_attention` quarantine; recovery when the adapter later answers correctly); recovery contract (`recover()` sequence verify → expire → reconcile → dispatch-safe; never redispatch uncertain operations; **idempotence: repeated reconciliation with unchanged findings performs no writes**); recorded limitations (crash between the attempt commit and the call stays conservatively `needs_attention`; in-flight calls cannot be cancelled and a late document revision leaves an old-content external effect that satisfies only the old digest; `P13` distributed-lease semantics deferred; single-process coordinator; no distributed exactly-once claim). Reference test names in `tests/test_boundaries.py`.

- [ ] **Step 2: Verify gates**

Run: `python3 -m unittest discover -s tests -v` → 47 OK; `python3 -m work_runtime demo` → crash demo prints recovery with "external applications created: 1"; `python3 -m compileall -q work_runtime tests` → silent.
Note: `scripts/check_docs.py` does not exist in this worktree (parallel contributor ownership); record in the report that the contracts gate must run at integration.

- [ ] **Step 3: Commit runtime + tests + docs together**

```bash
git add work_runtime/runtime.py tests/test_boundaries.py docs/runtime-boundaries.md
git commit -m "fix: make repeated reconciliation idempotent and pin boundary guarantees"
```

### Task 5: Evidence report and wrap-up

**Files:**
- Create: `.agents/notes/2026-10-13-S1-runtime-boundaries-report.md`

- [ ] **Step 1: Write the evidence report** — 3-sentence executive summary style expanded with: audit table (probe evidence), verbatim RED output (Task 1 Step 2) and GREEN output (Task 2 Step 4, Task 4 Step 2), full test names (3 fixed-behavior + 9 pinned), risks/limitations, commit hashes, explicitly-not-run gates (docs checker deferred to integration), no adapters.py change (no defect found).

- [ ] **Step 2: Final verification and commits**

```bash
python3 -m unittest discover -s tests -v   # 47 OK
git add .agents/notes/2026-10-13-S1-runtime-boundaries-report.md docs/superpowers/plans/2026-10-13-s1-runtime-boundaries.md
git commit -m "docs: S1 runtime-boundaries plan and evidence report"
```

(The plan file is committed first or together with the report — both are docs-only; the behavior commit in Task 4 must contain only runtime + tests + boundary doc.)

- [ ] **Step 3: Report to coordinator** — `orca orchestration send --type worker_done` with 3-sentence summary, `--files-modified`, `--report-path`, then idle.

## Self-Review

- Spec coverage: S1 wave-1 runtime story (failing regressions + minimal fixes + `docs/runtime-boundaries.md`) → Tasks 1–4; scenario S1 (RED/GREEN evidence) → Tasks 1–2 steps 2/4 + Task 5 report; scenario S2 (one external application after real crash) → Task 3 real-crash test + Task 4 demo gate; coordinator's never-redispatch regression → Task 3. RFC P06/P07 pinned by crash tests; P13 explicitly deferred in docs.
- Step scan: each step is one action with a checkable result; test snippets pin exact assertions only where they define the contract; fix steps give exact guard predicates rather than bodies.
- Type consistency: adapter helper names match between Tasks 1 and 3; guard predicates match the state labels emitted by current code (`outcome_unknown`, `NO_AUTHORITATIVE_RESULT`, `ADAPTER_RESULT_INVALID`, `needs_attention`).
- Review Focus: each line maps to a named test.
- Proportion: plan is comparable in length to the change it describes.
