# S3 lifecycle core worker report (2026-10-13)

Worker: s3-intervention-core (WayJ/s3-intervention-core), base fe81e98, plan
`docs/superpowers/plans/2026-10-13-s3-lifecycle-core.md`, spec
`docs/superpowers/specs/2026-10-13-s3-intervention-design.md` incl. D15.
Scope held: runtime.py, policy.py (ExpensePolicyV2 only), tests/test_interventions.py,
docs/interventions.md, docs/runtime-boundaries.md (same commit as every runtime.py edit),
plan + this report; sole baseline edit = unsupported-kind probe request_cancel →
request_refund in tests/test_runtime.py (assertion and count kept).

## Commits

| commit | content |
|---|---|
| 5184739 | scoped implementation plan |
| a56283b | policy registry + per-work resolution (Task 1) |
| e496b0e | ExpensePolicyV2 (Task 2) |
| 7f28335 | request_cancel (Task 3) — boundaries doc edit here accidentally dropped the "## Recovery contract" heading, repaired at 7686963 |
| 8e39d00 | finalize_cancel (Task 4) |
| 7686963 | transfer_owner + owner gating (Task 5; amended same-commit to repair the doc heading and carry the ownership section) |
| 6879a19 | replay authority recheck (Task 6) |
| 44b5bb9 | migrate_policy + actual contract revisions + verify_pending source check (Task 7) |
| 308154f / d51856e / 6b9cb70 | docs/interventions.md (+ class-name fix, boundaries cross-link) |

## RED/GREEN evidence (all runs in this session, from this checkout)

| task | RED (observed) | GREEN |
|---|---|---|
| 1 registry | `python3 -m unittest tests.test_interventions -v` → 6 errors `TypeError: __init__() got an unexpected keyword argument 'policies'` (7th test pins pre-existing fail-closed raise) | 179/179 OK |
| 2 V2 | `python3 -m unittest tests.test_interventions.ExpensePolicyV2Tests` → `ImportError: cannot import name 'ExpensePolicyV2'` | 185/185 OK |
| 3 request_cancel | `...CancellationRequestTests` → 9/11 fail (COMMAND_UNSUPPORTED / wrong codes) | 196/196 OK |
| 4 finalize_cancel | `...FinalizeCancelTests` → 9/9 fail (COMMAND_UNSUPPORTED) | 205/205 OK |
| 5 transfer_owner | `...OwnershipTests` → 9/12 fail | 217/217 OK |
| 6 replay authority | `...ReplayAuthorityTests` → 7/8 fail (stored receipts returned despite lost authority) | 225/225 OK |
| 7 migration | `...MigrationTests ...PendingSourceTests` → 19/19 fail (COMMAND_UNSUPPORTED) | 244/244 OK |

New tests: 72 in `tests/test_interventions.py` (RegistryContractTests 7,
ExpensePolicyV2Tests 6, CancellationRequestTests 11, FinalizeCancelTests 9,
OwnershipTests 12, ReplayAuthorityTests 8, MigrationTests 17,
PendingSourceTests 2). Real SQLite + FakeOA throughout, including a real
subprocess crash (`work_runtime worker --crash-after-effect`) in
`test_finalize_after_real_process_death`.

## Final gates (Task 9)

- `python3 scripts/check_docs.py` → 43 markdown files, 107 local links, 0 broken.
- `python3 -m unittest discover -s tests` → **244 tests OK** (172 baseline preserved in
  intent and count + 72 new; baseline probe rename only).
- `python3 -m work_runtime demo` → all 6 steps, exactly 1 external application.
- `python3 -m work_runtime publish-demo` → all steps, 1 published artifact.
- `python3 -m compileall -q work_runtime tests scripts` → clean.

## Decisions taken (rulings, with cost-if-wrong)

1. Works pinned to the **default** version resolve through the live
   `self.policy` slot; non-default pins resolve through the frozen registry.
   Required to preserve the S2 fail-closed contract under trusted-local
   `runtime.policy` swaps (pinned by two baseline adapter-contract tests).
   Cost if wrong: a default swap would silently stop affecting default-version works.
2. Legacy ownerless works: existing commands stay grant-only; all four new
   intervention commands are admin-only until an admin adopts ownership via
   transfer (spec says "current owner … or admin"; an ownerless work has no
   current owner). Documented in docs/interventions.md.
3. `verify_pending` invalidates (never verifies) a pending proof whose kind's
   configured source no longer matches under the current per-work policy —
   extends S2 semantics, required by D15's old-source-no-reappearance rule,
   pinned by `test_pending_old_source_proof_cannot_reappear_after_migration`.
4. Task 5 commit was amended locally (never pushed) to repair the boundaries
   doc heading dropped by the Task 3 edit and to carry the ownership section
   in the same commit as the runtime.py edit.

## Verification-map coverage (spec §Verification)

Cancellation before dispatch zero calls ✓ (`test_cancel_before_dispatch_makes_zero_external_calls`);
timeout + real process death one-effect recovery with explicit acknowledgement ✓
(`test_finalize_after_timeout_requires_exact_acknowledgement`,
`test_finalize_after_real_process_death`); missing/malformed lookup cannot
finalize ✓ (two tests); stale versions ✓ (`test_missing_pinned_version_fails_closed`,
`test_restart_without_pinned_version_fails_closed`); authority loss/replay ✓
(ReplayAuthorityTests); transfer with waiting and uncertain work ✓
(OwnershipTests); migration strengthened requirement + invalid prior approval ✓
(`test_strengthened_rule_revalidates_approval_and_keeps_key`); missing registry
version ✓; unchanged/cross-family ✓; in-flight refusal + atomic rollback ✓
(`test_migration_refuses_uncertain_effects`, `test_migration_rolls_back_atomically_on_target_failure`);
two works pinned to different versions ✓; reopen/recover without implicit
migration ✓.

## Remaining risks / limits

- Compensation/reversal execution, evidence revocation, distributed leases and
  cross-domain registries remain deferred and are labeled in
  docs/interventions.md and runtime-boundaries.md (roadmap scope, not this slice).
- Business-key stability across same-family versions is a policy-author
  obligation (demo policies share one key function); the runtime does not
  rewrite keys — documented.
- Final code review was a **self-review** (dispatch brief forbids nested
  agents): no Critical/Important findings; three minors ledgered (handler
  check-order inconsistency, unreachable-by-design dispatch guard, one long
  line). Wave-2 integration performs the independent review next.
- No merge, no push (integration session owns both).

## D16 review correction addendum (post-b6adae8)

Integration review found (root reproduced by coordinator and re-reproduced
here): a structurally malformed default policy — e.g.
`ExpensePolicy().operation_key = "not-callable"` — was accepted by
`Runtime(..., policies={})` (and with additional versions) and created the
database. Root cause: `_validated_registry` structurally validated only
explicit entries; the default was merged with an identity check alone.
This was a gap my self-review missed: I tested the default-version
*identity* mismatch but never probed a malformed default with an explicit
registry — admitted as the self-review blind spot D16 calls out.

Fix (per D16, minimal and localized): structural checks extracted to
`_validated_policy_structure` and applied to the default for ANY explicit
`policies` dict including `{}`, before mkdir/DB writes. Additive versions
may omit the default key; a supplied default key must identity-match;
`policies=None` legacy behavior preserved.

- RED: `python3 -m unittest tests.test_interventions.RegistryContractTests`
  → `test_malformed_default_rejected_for_any_explicit_registry` FAILED
  ("CommandError not raised: {}"); pin test
  `test_valid_additive_registry_and_none_legacy_are_preserved` passed pre-fix as designed.
- GREEN: same command → 9/9 OK; full `python3 -m unittest discover -s tests`
  → 246 tests OK (244 + 2 new).
- Gates: `python3 scripts/check_docs.py` 0 broken; `python3 -m compileall -q
  work_runtime tests scripts` clean; `python3 -m work_runtime demo` (1 external
  application) and `python3 -m work_runtime publish-demo` (1 artifact) green.
- tests/test_interventions.py, work_runtime/runtime.py and
  docs/runtime-boundaries.md committed together (same commit).

## Post-merge defect fix: cancelled waits must stay cancelled (after 7afaf19)

Integration review found (reproduced here with real Runtime/SQLite/FakeOA
evidence before any fix): `_evaluate` unconditionally flipped any wait to
`triggered` when its requirement was satisfied, so (a) `request_cancel`
cancelling an already-triggered wait had its cancellation immediately
undone by its own `_save`→`_evaluate`, and (b) a wait cancelled while its
requirement was unsatisfied was resurrected by later valid evidence (and
likewise by policy migration when the requirement stayed satisfied under
the target). Root cause: the wait-triggering loop in `_evaluate` had no
guard for terminal `cancelled` waits. This was a second miss of my
S3 self-review: I asserted waits were cancelled at decision time but never
re-read them after a subsequent evaluation.

Fix: one localized guard in `_evaluate` — `status == "cancelled"` waits are
skipped, so cancellation/migration invalidation is terminal while the
existing waiting→triggered wakeup and expired-wait behavior are untouched.

- RED: `python3 -m unittest tests.test_interventions.CancelledWaitTests -v`
  → 3/3 FAILED (`triggered != cancelled`) for
  `test_cancelled_triggered_wait_stays_cancelled`,
  `test_cancelled_wait_stays_cancelled_after_late_evidence`,
  `test_migration_cancelled_wait_stays_cancelled_when_requirement_satisfied`.
- GREEN: same command → 3/3 OK; full `python3 -m unittest discover -s tests`
  → 249 tests OK (246 + 3).
- Gates: `python3 scripts/check_docs.py` 0 broken; `python3 -m compileall -q
  work_runtime tests scripts` clean; `python3 -m work_runtime demo` and
  `publish-demo` green with exact effect counts.
- runtime.py, tests/test_interventions.py, docs/runtime-boundaries.md in the
  same commit; no other lifecycle or gate semantics changed.

## Diagnostics fix: v2 E05 explanation (after 8715151)

Master observed in migrated inspect output that ExpensePolicyV2 inherited
v1's E05 explanation ("Over-limit submissions require approval...") while
requiring approval for every known amount, so a correctly blocked
under-limit migrated work showed a misleading reason (reproduced here
before the fix: under-limit v2 work, REQUIREMENT_UNSATISFIED, explanation
"Over-limit submissions require approval of the current content").

Fix: `ExpensePolicyV2.evaluate` overrides only the E05 requirement's
explanation in the result of `super().evaluate()` — "Every known amount
requires version-bound approval of the current content". Admission logic,
v1 explanation (pinned byte-exact in the new test), unknown applicability
(existing pin), Runtime, demo and docs are untouched.

- RED: `python3 -m unittest tests.test_interventions.ExpensePolicyV2Tests.test_v2_blocker_explains_all_known_amount_approval`
  → FAILED (`'known amount' not found in 'over-limit submissions require approval of the current content'`).
- GREEN: same test passes; full `python3 -m unittest discover -s tests` →
  250 tests OK (249 + 1).
- Gates: check_docs 0 broken; compileall clean; demo and publish-demo green.
- Files: work_runtime/policy.py (V2.evaluate only), tests/test_interventions.py,
  this addendum — one commit.
