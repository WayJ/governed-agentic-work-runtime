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
