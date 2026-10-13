# S1 runtime boundaries — developer evidence report (2026-10-13)

Worker: runtime developer (dispatch task_5e0d0cded01e, context ctx_b18401368c6f).
Scope honored: `work_runtime/runtime.py`, `tests/test_boundaries.py` (new),
`docs/runtime-boundaries.md` (new), this report and
[the plan](../../docs/superpowers/plans/2026-10-13-s1-runtime-boundaries.md).
`work_runtime/adapters.py` is **unchanged** — the audit found no adapter-side
defect. No edits to policy, `tests/test_runtime.py`, README, scripts,
verification docs or sprint/epic ledgers. Branch `WayJ/s1-runtime-boundaries`;
no merge, no push.

## Executive summary

I audited the dispatch/reconciliation/recovery boundary against sprint S1 and
RFC-003 §7/§9, confirmed the findings with a throwaway probe, then fixed one
real defect with TDD: repeated `reconcile`/`recover` on an unresolved operation
re-appended events and re-bumped `state_version` on every call, so supervisor
restart loops grew history without bound. Malformed and digest-mismatched
adapter results were already correctly quarantined (`outcome_unknown` /
`ADAPTER_RESULT_INVALID` + `needs_attention`, recoverable), and unsafe resend
was already prevented (uncertain operations are never re-dispatched; exactly
one external application across crash, repeated recovery and replays) — both
are now pinned by regressions and documented with their limitations in
`docs/runtime-boundaries.md`. Full suite is green (47 tests = 35 baseline + 12
new), the real-crash demo still converges to one FakeOA application, and the
remaining risk is the deliberately conservative behavior: adapters that cannot
answer lookups stop at `needs_attention` instead of re-sending (P13 deferred).

## Audit findings (probe-verified, Python 3.9.6)

| # | area | observed before the change | disposition |
|---|---|---|---|
| A1 | recovery, `lookup` → None | every `reconcile` re-appended `ReconciliationRequired` and bumped `state_version` (probe: events 1→2, version 8→9 per repeat) | **defect, fixed** |
| A2 | recovery, `lookup` raises | every call re-appended `OutcomeUnknown` (probe: 2→3 events, version +1) | **defect, fixed** |
| A3 | malformed adapter result re-observed | every re-observation re-appended `OperationResolved` (probe: 1→3 events, version 7→9); `execute` itself was called once — metadata churn, not effect duplication | **defect, fixed** |
| B1 | malformed results (non-dict, missing/empty fields) | quarantined `outcome_unknown`/`ADAPTER_RESULT_INVALID`, work `needs_attention`, no `external_id` recorded; recoverable when the adapter later answers correctly (probe P4) | correct, pinned |
| B2 | digest mismatch (result for other content) | never confirms this operation; completion blocked `OUTCOME_UNRESOLVED`; E08 unsatisfied | correct, pinned |
| C1 | unsafe resend | `dispatch` requires `prepared`; recover/reconcile never call `execute` for uncertain ops; business-key dedup returns the existing operation; probe P5: 1 `execute`, 1 accepted across dispatch/recover/reconcile loops | correct, pinned |

Fix (minimal): early-return guards in `runtime.py` `_unknown`, `reconcile`
(lookup-None path) and `_resolve` (invalid-result branch) that skip the write
when the persisted state already equals the target state. Changed failure
reasons still transition and are still recorded; the valid-result and
terminal-status paths are untouched.

## RED/GREEN evidence (verbatim)

RED — `python3 -m unittest tests.test_boundaries -v` on the failing suite
(before the fix; the three tests were written first and observed failing):

```
FAIL: test_malformed_result_reconcile_is_idempotent (tests.test_boundaries.BoundaryTests)
  File ".../tests/test_boundaries.py", line 127, in test_malformed_result_reconcile_is_idempotent
    self.assertEqual(self.runtime.get_work("demo")["state_version"], version)
AssertionError: 9 != 7

FAIL: test_repeated_reconcile_with_failing_lookup_is_idempotent (tests.test_boundaries.BoundaryTests)
AssertionError: 9 != 8

FAIL: test_repeated_reconcile_without_authoritative_result_is_idempotent (tests.test_boundaries.BoundaryTests)
AssertionError: 9 != 8

Ran 3 tests in 0.106s
FAILED (failures=3)
```

Base-run cross-check (whole-branch review): running the complete final suite
against base `798d3c7` yields **4** failures — the three above plus
`test_new_reconcile_failure_reason_is_recorded` (3 `OutcomeUnknown` events vs
the asserted 2), which was written after the fix and is therefore counted as a
fourth RED→GREEN regression rather than a characterization.

GREEN — after the minimal fix:

```
python3 -m unittest tests.test_boundaries tests.test_runtime -v
Ran 38 tests in 0.964s
OK

python3 -m unittest tests.test_boundaries -v        # after Task 3 pins
Ran 12 tests in 0.558s
OK

python3 -m unittest discover -s tests -v            # final gate
Ran 47 tests in 7.013s
OK
```

Demo gate — `python3 -m work_runtime demo` (real worker process exits 73
after external acceptance, recovery recovers the receipt):

```
4. OA accepts → worker exits before saving the response (real process crash)
5. Restart → query original operation → existing OA receipt recovered
6. Evidence-backed completion → SUCCEEDED; external applications created: 1
```

Syntax gate — `python3 -m compileall -q work_runtime tests` → clean.

## Tests added (tests/test_boundaries.py)

Fixed-behavior regressions (RED→GREEN — each observed failing on the
unfixed code):

1. `test_repeated_reconcile_without_authoritative_result_is_idempotent`
2. `test_repeated_reconcile_with_failing_lookup_is_idempotent`
3. `test_repeated_malformed_result_reconcile_is_idempotent`
4. `test_new_reconcile_failure_reason_is_recorded` (guards must not
   over-suppress; fails on base — see RED evidence note below)

Characterization regressions (green by design — they pin already-correct
behavior; the coordinator explicitly accepted green tests where no bug
exists):

5. `test_malformed_adapter_results_leave_inspectable_uncertainty`
   (strengthened in the review fix pass: a fresh runtime per variant plus an
   `execute_calls == 1` assertion, after the review showed three of the four
   variants were re-inspecting variant 1's operation instead of exercising
   their own — that assertion was observed RED `0 != 1` on the three variants
   before the restructure, then GREEN)
6. `test_mismatched_digest_result_is_quarantined`
7. `test_adapter_recovering_with_valid_result_confirms_operation`
8. `test_recover_never_redispatches_uncertain_operation` (coordinator-requested)
9. `test_execute_exception_then_recover_calls_adapter_once_and_escalates`
10. `test_recover_with_nothing_to_do_is_idempotent`
11. `test_real_crash_recovery_yields_exactly_one_external_application` (S2)
12. `test_recovery_business_dedup_returns_existing_operation`

Classification note: test 4 was initially reported as a green-by-design pin
(written after the fix, so it passed in-session on first run). The
whole-branch review ran the entire suite against base `798d3c7` and found it
fails there (3 `OutcomeUnknown` events vs the asserted 2; 4 failures total on
base). It is behavior-on-base that classifies, not in-session observation
order — corrected here and in the ledger.

## Risks and limitations

- Conservative by design: an adapter that cannot answer lookups (or a crash
  between the attempt commit and the external call) ends at `needs_attention`
  with no automatic resend; operators must resolve externally. P13
  (distributed lease takeover) remains deferred — single-coordinator claims
  only, no distributed exactly-once.
- In-flight external calls cannot be cancelled; a late document revision can
  leave an old-content external effect that satisfies only the old digest.
- The new guards suppress writes only when status, reason and work status all
  already match the target; a changed reason still records (pinned by test 9).
  If a future change makes `needs_attention` non-sticky, the reconcile guard
  must be revisited (currently safe because `_evaluate` never exits it).
- `scripts/check_docs.py` does not exist in this worktree (contributor's
  parallel deliverable): the configured docs/contracts gate could not run here
  and must be executed in the integration worktree.

## Whole-branch review

Independent fresh-context reviewer dispatched over 798d3c7..ca53169 (plan,
spec, Review Focus and ledger rulings supplied). The reviewer independently
reran the suite (47 OK), the demo gate, compileall, reproduced the pre-fix
RED state against the base commit, and probed claims the suite makes only
indirectly. Verdict: **With fixes** — 0 Critical, 2 Important, 2 Minor.

- Important 1 (fixed): three of four malformed-variant subTests were vacuous
  (shared business key → `execute` never called for variants 2-4). Fixed with
  a per-variant fresh runtime and the `execute_calls == 1` assertion, verified
  RED→GREEN.
- Important 2 (fixed): the evidence misclassification of test 4, corrected
  above.
- Minor 3-4 (re-graded to fix-now because accurate boundary documentation is
  an explicit S1 acceptance criterion; fixed): the "unqueryable adapters stop
  at `needs_attention`" limitation overclaimed — a persistently *raising*
  `lookup` records operation-level uncertainty without changing work status;
  and the in-flight limitation now states the `OUTCOME_UNRESOLVED` gate before
  new content can be prepared.
- Deferred (recorded, not fixed — pre-existing or cosmetic): `_unknown` lacks
  a terminal-status guard, a theoretical overwrite only reachable outside the
  documented single-coordinator model (candidate for a future sprint next to
  the P13 deferral); a double blank line in the test class; `FailingAdapter`
  uses `TimeoutError` where the plan snippet said `ConnectionError`.

No Critical findings; the reviewer confirmed the behavior change correct,
minimal, well-pinned, and within ownership.

## Commits

| commit | content |
|---|---|
| `ca53169` | fix: make repeated reconciliation idempotent and pin boundary guarantees (`work_runtime/runtime.py`, `tests/test_boundaries.py`, `docs/runtime-boundaries.md` — same commit per the sync rule) |
| `9923d11` | review fix pass: malformed-variant test strengthening + doc precision (`tests/test_boundaries.py`, `docs/runtime-boundaries.md`) |
| (this commit) | plan + this evidence report |

Reported via worker_done; worker idle thereafter.
