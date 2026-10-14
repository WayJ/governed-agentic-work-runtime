# S8 Task1 core lifecycle — developer report

Worker: S8 TASK1 core lifecycle (checkout `s8-revocation-core` @ `7282c25`).
Scope: `work_runtime/runtime.py`, revocation/intervention tests, mapped docs.
Date: 2026-10-14.

## Commits (scoped core/tests/docs only; no merge/push)

| commit | subject |
|---|---|
| `1188afe` | fix: unbound evaluation cannot overwrite a finalized closed status (S8 D-1) |
| `97a0452` | feat: durable revoke_evidence command with D33 authority and codes |
| `a233039` | feat: EvidenceRevoked event with actual requirement/wait dispositions and closed-work correction |
| `4e6e41c` | feat: revoke replay reauthorization, resend evidence_status and permanence invariants |
| `3f56336` | test: pin D35 waits, dispatch hold, readmission and retained effects |
| `04ac56a` | test: revoke transaction rollback and real process death |
| (docs commit) | docs: evidence revocation boundary, D-1 limit, S8 verification section, core report |

Plan: `docs/superpowers/plans/2026-10-14-s8-task1-core.md` (scoped plan,
executed with superpowers executing-plans; ledger in
`.superpowers/sdd/2026-10-14-s8-task1-core/progress.md`).

## Baseline and reproduction

- Baseline at `7282c25`: 622 tests OK (skipped=1).
- D-1 reproduced before coding (probe outside checkout): create unbound work
  → record pending approval → request_cancel → finalize accepted → stored
  status `establishing`, outcome `cancelled`, completion present.

## RED/GREEN evidence (observed, per behavior)

- **D-1 guard**: `test_finalize_cancel_on_unbound_work_persists_closed` and
  `test_unbound_closed_work_stays_closed_under_late_verification_and_recovery`
  RED `AssertionError: 'establishing' != 'closed'` (both) → GREEN after the
  `_evaluate` unbound closed guard. Suite 624 OK.
- **Command core (D33)**: 15 tests RED — 19 failures + 1 error with the kind
  routed into the manager gate (`AUTHORITY_DENIED`/`COMMAND_UNSUPPORTED`
  instead of revocation semantics) → GREEN after routing beside
  `record_evidence` plus `_revoke`/`_revoke_authority`. 15/15, suite 639 OK.
- **Event dispositions + closure (D34)**: 6 new tests, 4 RED against the
  placeholder empty `affected_requirements`/`wait_dispositions` → GREEN with
  the actual before/after diffs (pure `_evaluate` pre-run; `_save` still bumps
  exactly once). 22/22, suite 646 OK.
- **Replay + resend + permanence (D33/D36)**: 16 new tests, 6 RED (5 errors
  `KeyError: 'evidence_status'`-class + replay returning stored receipts
  without reauthorization) → GREEN after the `_replay_denial.revoke_evidence`
  branch and the additive `_receive` dedup `evidence_status`. 38/38,
  suite 662 OK.
- **Waits/dispatch/effects (D35)**: 13 new pin-only tests, **zero production
  change** (existing machinery proven). 51/51, suite 675 OK. During authoring,
  6 test-side mistakes were corrected against real behavior (wait-state
  reachability, missing `article` helper, wrong revoker authority) — the
  product denied correctly in each case.
- **Crash atomicity**: 3 new pin-only tests (exception in `_save`, real
  `os._exit(75)` child inside the revoke transaction, external-acceptance
  death exit 73 then revoke+recover). 54/54, suite 678 OK (skipped=1).

## Test counts and gates

- New: `tests/test_evidence_revocation.py` 55 tests (all passing; 54 at review + 1 review-fix pin); +2 D-1
  tests in `tests/test_interventions.py` (80 total there).
- Full suite after the review fix pass: **679 tests, OK, skipped=1** (the
  pre-existing installed-UI backend skip, unchanged).
- All five AGENTS gates pass: contracts (`check_docs.py`: 79 files, 299
  links, 0 broken), tests (above), demo (`work_runtime demo` real crash
  recovery), syntax (`compileall` clean), site (`check_site.py` 0 findings).
- Prior demos re-run green: `publish-demo`, `intervention-demo`,
  `adoption-demo`. No `revocation-demo` exists yet — later owner scope
  (nothing added or invoked).

## Effect proofs (actual adapter stores, counted)

- Dispatch hold: `FakeOA` receipts table count 0 and `accepted_count()` 0
  (direct dispatch and restart+recover); `FakePublisher.published_count()` 0.
- Replacement readmission: same `operation_id`/business key, then exactly one
  accepted application (expense) / one publication (publishing).
- In-flight: `outcome_unknown` after timeout-after-commit, reconcile →
  `confirmed_succeeded` with retained `external_id`, exactly one effect,
  accepted proof under the operation id, revoked approval still revoked.
- Confirmed-effect retention: revoke accepted → op unchanged
  (`confirmed_succeeded`), `accepted_count()` stays 1, exactly one evidence
  row for the operation event, re-proposal returns the confirmed operation.
- Rollback: full-store snapshot equality (works/evidence/fingerprint/events/
  commands) after injected exception and after real process death; retry then
  succeeds.

## Interface conformance (D33–D37)

- Public: `Runtime.command(..., "revoke_evidence", {source, event_id,
  reason}, expected_version)`; receipt `{command_id, decision,
  result_state_version, evidence_id, evidence_status: "revoked",
  prior_status}`; codes `EVIDENCE_UNKNOWN`, `EVIDENCE_SCOPE_MISMATCH`,
  `EVIDENCE_ALREADY_REVOKED`, `EVIDENCE_NOT_REVOKABLE`, `AUTHORITY_DENIED`,
  `STATE_VERSION_CONFLICT` (envelope). Event `EvidenceRevoked` with the
  eleven ratified fields. New-command resends carry current
  `evidence_status`; original cached receipts verbatim.
- Authority: admin OR current configured source for the stored kind with
  `evidence.revoke`; owner/`work.manage`/`evidence.write` alone denied;
  unknown-proof commands use only the conservative preliminary check (fresh
  and replay); replay reauthorization for accepted and rejected receipts.
- Non-goals honored: schema stays `1`; zero runtime deps; Python>=3.9;
  unittest only; no policy/protocol/adapters/CLI/demo/verifier/reader/web/
  README/AGENTS/roadmap/sprint-ledger changes; no new public fault
  parameter (test-owned subclasses/private hooks only); D37 read-only
  surfaces untouched (Task4-of-sprint owner); D-4 stays TD-1 deferred.
- Internal plumbing (builder-owned per dispatch): `_revoke`,
  `_revoke_authority`, the `_replay_denial` branch, `_receive` dedup status,
  `_evaluate` unbound closed guard.

## Rulings (recorded in the SDD ledger)

1. Wait dispositions record only reachable transitions: at revoke time a
   wait on a satisfied requirement is already `triggered` (every
   satisfaction path runs the evaluator), so revoke can never *newly*
   trigger a wait; dispositions truthfully show `unchanged` and never demote
   `triggered`/`cancelled`/`expired` or reset deadlines. Documented in
   `docs/evidence-revocation.md`.
2. The retired-source correction scenario uses a **pending** old-source
   candidate (migration revalidates verified proofs, which would make them
   `invalid` = not revocable) — matches the ratification's old-source
   candidate wording.

## Docs (doc-sync)

- New `docs/evidence-revocation.md` (full reference + test-name table).
- `docs/runtime-boundaries.md`: new "Evidence revocation boundary" section;
   migration paragraph updated (revoked→revoked disposition); immutability
   limitation notes revoked permanence; verification table pointer.
- `docs/interventions.md`: command-table row, compensation paragraph,
   rejection codes, limits.
- `docs/verification.md`: updated header, S8 named-test section, out-of-scope
   rewrite (revocation supported; compensation still out).

## Remaining risks / limits (truthful)

- Pre-existing persisted erroneous unbound-finalize snapshots (created before
  this fix) are not rewritten retroactively — documented limit, no silent
  migration.
- Revocation does not fence in-flight external calls (unchanged residual
  race, RFC-001 §5.2); it is not compensation.
- TD-1 / D-4 privileged accepted-source event-id collision: deferred with
  owner/repayment criteria in the debt tracker; not fixed, not claimed.
- Wait-disposition reachability (ruling 1) means the event's
  `wait_dispositions` will show `unchanged` for triggered waits — explicit
  and truthful, but reviewers should not expect a "resurrection-prevented"
  transition to appear.
- Decision codes reveal row **existence** (never status) to actors passing
  the preliminary check — the ratified two-phase order; the later demo/viewer
  owners should not claim stronger confidentiality than that.
- Later owners consume: D37 reader fields and revocation-demo are not
  implemented here; integration (Task2-of-plan) pins this branch before
  those clients.

## Independent whole-branch review (fresh context) and fix pass

Reviewer verdict: no Critical findings; "With fixes" for one Important
finding, all re-verified here:

- **Important — replay of a cached unknown-proof rejection**: the
  `_replay_denial` branch applied the exact stored-kind check once the row
  later appeared, while binding D33 mandates admission's conservative
  preliminary check for receipts decided as unknown-proof. Fixed by threading
  the cached receipt into `_replay_denial` and keeping the preliminary check
  for `EVIDENCE_UNKNOWN` receipts:
  `test_cached_unknown_rejection_keeps_preliminary_check_after_row_appears`
  RED (fresh `AUTHORITY_DENIED` instead of the stored rejection) → GREEN;
  suite green throughout.
- **Minor (fixed as doc truthfulness)**: the verification table in
  `docs/evidence-revocation.md` named a nonexistent test (renamed during
  authoring); corrected to `test_cancelled_wait_stays_terminal_across_revocation`.
- **Minor (fixed)**: added the reviewer-suggested reconcile pin on a
  confirmed operation after revoking its accepted proof (op unchanged, one
  effect) to `test_confirmed_operation_never_reruns_to_regen_accepted_proof`.
- **Minor (deferred)**: `_receive`'s dedup path parses the stored body twice
  (`id`, then `status`) — cosmetic; left for the next owner touching that
  path.

Reviewer sanity checks independently reproduced: suite 678-then-679 OK
(skipped=1), 54/54→55/55 revocation tests, all five AGENTS gates green,
pin-only commits test-only, every doc-named test cross-checked (the one
mismatch was the corrected name above).
