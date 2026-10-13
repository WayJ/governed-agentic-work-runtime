# S3 foundation integration report (2026-10-13)

Integration session: s3-release-control (this carrier, `WayJ/sprint-s3-intervention`).
Scope per supervision plan Task 3 and dispatch ctx_5b400231b1d1: independent review of the
lifecycle core against true merge-base fe81e98, merge of the accepted corrected tip plus the
builder report, fresh gates/demos, this report. No accept, no main merge, no push, no teardown —
the dependent demo wave consumes the assembled tip below.

## Verdict

Foundation **accepted for demo consumption**. Independent review found no substantive defects
after the D16 correction; all mutation probes confirm the new suite is meaningful; the assembled
carrier passes every configured gate and both existing demos with actual SQLite/adapter counts.

## Merge proof

| step | sha | content |
|---|---|---|
| carrier base | ca9187c | D15/D16 ratifications + supervision plan (preserved) |
| core tip (reviewed) | 7afaf19 | corrected lifecycle foundation (b6adae8 + D16 fix) |
| foundation merge | 9fecae4 | `merge WayJ/s3-intervention-core` into ca9187c (clean, ort) |
| builder report merge | 5a66892 | `merge c84ac61` (S3 design review note) — **assembled tip** |

Both merges are ordinary non-force merges on the carrier branch; working tree clean after;
`git status` empty. Baseline test file delta is exactly the D15-sanctioned probe rename
(`request_cancel` → `request_refund` in `tests/test_runtime.py:327`, assertion unchanged).

## Independent review evidence

- **D16 gap reproduced then verified fixed.** On b6adae8: `ExpensePolicy()` with
  `operation_key="not-callable"` + `policies={}` constructed and created the DB. On 7afaf19:
  `CommandError: Registry policies require a callable operation_key` before any filesystem/DB
  write (no directory created); `policies=None` legacy path preserved and pinned by
  `test_valid_additive_registry_and_none_legacy_are_preserved`.
- **Mutation RED probes** (fresh archive of the branch per probe; pristine tip stays GREEN,
  each mutation goes RED): replay-authority removal → 8-test class, 6 errors; pending-source
  check removal → PendingSourceTests failure; dispatch contract-revision check removal →
  `test_dispatch_respects_actual_contract_revision` failure; exact-acknowledgement set
  comparison weakened to subset → `test_finalize_after_timeout_requires_exact_acknowledgement`
  error; migration evidence-revalidation bypassed → `test_strengthened_rule_revalidates...`
  failure; propose owner-gate removal → `test_former_owner_loses_management_proposal_and_dispatch`
  error.
- **D15 conformance on the named axes**: cancellation intent stored as a separate
  `work["cancellation"]` JSON field that `_evaluate`/expiry/quarantine/reconciliation never
  touch; `finalize_cancel` requires the exact `confirmed_succeeded` set with external ids in the
  immutable closure; uncertain effects are preserved and must reconcile before finalize
  (AttemptStarted = no external fence); the full replay-authority matrix incl. fingerprint-first
  ordering and fresh unpersisted `AUTHORITY_DENIED`; legacy ownerless works grant-only with
  admin-only adoption; per-work registry resolution in every validation/evaluation/source/
  blocker/key/receipt/recovery path; all-kind target-source + verifier revalidation with the
  same source check applied to pending proofs at `verify_pending`; actual contract revisions on
  new/readmitted operations enforced at propose CAS and dispatch; migration atomicity proven by
  exploding-target rollback tests.
- Minor ledgered items (owner's report, cosmetic, no action required): handler check-order
  inconsistency; unreachable-by-design belt-and-braces dispatch guard. Process note: the
  Task-3 commit 7f28335 briefly dropped a boundaries-doc heading, repaired in 7686963.

## Fresh assembled-carrier gates (at tip 5a66892)

- `python3 scripts/check_docs.py` → 34 markdown files, 110 local links, 0 broken.
- `python3 -m unittest discover -s tests` → **246 tests OK**
  (172 baseline preserved in intent and count + 74 new: 72 intervention tests + 2 D16 tests).
- `python3 -m compileall -q work_runtime tests scripts` → clean.
- `python3 -m work_runtime demo` → all 6 steps, exactly 1 external application.
- `python3 -m work_runtime publish-demo` → all steps, 1 published artifact.

## Stable interface for the demo wave (consume tip 5a66892)

- **Constructor**: `Runtime(path, policy, grants, *, policies=None)`. Keyword-only registry,
  validated before any filesystem/DB write; any explicit dict (including `{}`) structurally
  validates the default too (D16); additive registries may omit the default key; supplied
  default key must map to the identical default object; entries must share the default's
  family (`id`) and `goal`; mapping is copied; `policies=None` keeps legacy semantics
  (`{policy.version: policy}`, unvalidated).
- **New commands** (payloads exact, malformed raises `CommandError`; all under
  `(actor, command_id)` dedup and `expected_version` CAS):
  `request_cancel {reason}` / `finalize_cancel {acknowledged_operations}` /
  `transfer_owner {owner, reason}` / `migrate_policy {policy_id, policy_version, reason}`.
- **Authority**: interventions (request/finalize/transfer) = current owner with `work.manage`
  or `work.intervene` admin (ownerless legacy: admin only); `migrate_policy` = admin
  exclusively; management mutations = current owner with `work.manage` (ownerless legacy:
  grant-only); `propose_action`/dispatch = current owner plus capability.
- **Rejection codes added (8)**: `CANCELLATION_ALREADY_REQUESTED`, `CANCELLATION_NOT_REQUESTED`,
  `CANCEL_ACKNOWLEDGEMENT_MISMATCH`, `CANCELLATION_ACTIVE`, `TRANSFER_SAME_OWNER`,
  `MIGRATION_TARGET_UNCHANGED`, `MIGRATION_TARGET_UNREGISTERED`, `MIGRATION_FAMILY_MISMATCH`.
  **Prepared-op reasons added (3)**: `WORK_CANCELLED`, `POLICY_MIGRATED`,
  `OWNERSHIP_TRANSFERRED`. Reused: `AUTHORITY_DENIED`, `WORK_NOT_ACTIONABLE`,
  `OUTCOME_UNRESOLVED`, `CONTRACT_NOT_ACTIVE`, `COMMAND_UNSUPPORTED`, `COMMAND_ID_REUSED`,
  `STATE_VERSION_CONFLICT`, revision/scope codes.
- **Events added**: `CancellationRequested`, `WorkCancelled`, `OwnerTransferred`,
  `PolicyMigrated`.
- **Work JSON fields added**: `owner`, `cancellation {requested_by, reason}`,
  `completion` closure snapshot on finalize, contract `revision` increments on migration.
  Schema stays `schema_version=1`; registry is constructor state, never persisted.
- **Published v2 policy**: `work_runtime.policy.ExpensePolicyV2` — version `demo-2`, same
  family/goal/capability/business-key as demo-1, approval required for every known amount,
  valid approval data exactly `{digest, policy_version:"demo-2"}`; other validators inherit.
- **Demo-wave hook**: CLI `inspect --policy-versions` (explicit registry, expense family only,
  strict parsing) is the demo wave's to add; core `inspect` behavior is unchanged and fails
  closed on unloaded pinned versions by design.

## Remaining for later waves

Wave 3 (demo): `intervention_demo.py`, CLI registry flag, `tests/test_intervention_demo.py`,
installed verification/CI smoke, public docs. Wave 4 (release/integration): acceptance, main
merge, push, remote/CI evidence. Compensation execution, evidence revocation, distributed
leases and cross-domain registries remain deferred and labeled.

## Correction appendix — cancelled-wait terminal invalidation (2026-10-13, dispatch ctx_8e8481136739)

Master reproduced a resurrection defect on assembled tip 236ac14: a wait registered on a
satisfied requirement (`triggered`) was returned to `triggered` by `_save` → `_evaluate`
after `request_cancel` had cancelled it — `_evaluate` re-triggered every wait whose
requirement was satisfied, regardless of the wait's terminal `cancelled` state (same latent
path for `migrate_policy` and late evidence after cancel).

- **Independent RED observation** (owner correction 8715151 vs base 7afaf19): the corrected
  tip's `CancelledWaitTests` (3 tests) applied to the un-fixed 7afaf19 runtime →
  `Ran 3 tests ... FAILED (failures=3)` — exactly the three scenarios: triggered-wait cancel,
  late evidence after cancel, migration retaining cancellation. A plain `-k` run on 7afaf19
  runs 0 tests (class absent) and is not evidence; the tests must be laid onto the old code.
- **GREEN on corrected tip 8715151**: `Ran 3 tests ... OK`; fix is a two-line terminal guard
  in `_evaluate` (`cancelled` waits are skipped, never re-triggered) with the same-commit
  `docs/runtime-boundaries.md` amendment ("terminally: later evaluation (late evidence,
  verification, migration) can never re-trigger a cancelled wait"). No other runtime change.
- **Semantics preserved**: waiting waits still trigger on satisfaction (baseline
  `test_early_approval_and_duplicate_callback` green), expiry only flips `waiting` waits,
  cancelled is now terminal everywhere (including `revise_document`-cancelled waits — no
  baseline test relied on resurrection; full suite confirms).
- **Merge proof**: carrier 236ac14 + core 8715151 → **b25cf66** (clean `ort` merge; root
  design/master docs untouched; working tree clean).
- **Fresh assembled-carrier gates at b25cf66**: `python3 -m unittest discover -s tests` →
  **249 tests OK** (172 baseline + 77 intervention incl. 3 new); `compileall` clean;
  `check_docs.py` → 34 markdown files, 110 local links, 0 broken; `demo` and `publish-demo`
  both pass. No demo merge, no main merge, no push, no acceptance, no teardown; the demo
  wave consumes tip **b25cf66**.

