# S13 W1 withdrawal-core development report — 2026-10-16

Worker: S13 W1 withdrawal-core owner (`WayJ/s13-withdrawal-core`,
started EXACT `b445fc16b1fb2cca69a192ce4efa4e20b9005a2e`, clean; branch
remains unmerged, no push — integration owns the merge). Scoped plan
committed before code:
[f05ca62](../../docs/superpowers/plans/2026-10-16-s13-core.md).
Implementation follows the ratified design D67–D79 exactly, including the
SWD-8 amendment (rejected-receipt refusal channel; the drafted
`ValueError` channel is not implemented anywhere).

## Commits (in order)

| commit | content |
|---|---|
| `f05ca62` | docs: S13 W1 withdrawal-core scoped implementation plan |
| `69f4666` | feat: withdrawal key, closed record shape and SopWithdrawalStore wrapper (S13 D68/D69/D74) |
| `be75a2f` | feat: fail-closed loader withdrawal check with distinct bounded errors and audit read (S13 D72) |
| `6a31eec` | feat: governed sop.withdraw flow with W02/W03 document-shape discrimination (S13 D70/D71/D74/D75) |
| `6787872` | test: pin S8 revocation composition and card_withdrawal keyring rotation battery (S13 D79) |
| `2a26d38` | test: pin card_withdrawal isolation on card works at the evidence level (S13 D70) |
| `ab8235d` | feat: near-miss withdrawal admission names the closed-shape requirement (S13 D70 review fix) |

Same-commit doc pairing held on every commit (publication.py ⇒
sop-authoring.md; tests ⇒ verification.md; no AGENTS.md edits, zero new
doc_sync_map rows per D78).

## RED/GREEN evidence (TDD, observed)

- **Task 1** — RED: `python3 -m unittest tests.test_publication_withdrawal
  -v` → `ImportError: cannot import name 'WITHDRAWAL_DISCRIMINATOR'`.
  GREEN after the additive surface: 14/14 OK. Full discover 958 OK
  skipped=3.
- **Task 2** — RED: `LoaderWithdrawalTests` →
  `ImportError: cannot import name 'withdrawal_record'`. GREEN: 26/26 OK
  (two initial test-design errors were mine — a second raw commit under an
  occupied key is correctly refused by the store's immutability, so the
  doctored-record scenarios commit the bad record first; production code
  unchanged for them). Full discover 970 OK skipped=3.
- **Task 3** — RED: `GovernedWithdrawalFlowTests` → 16 errors, first:
  `create_work` refuses the withdrawal shape
  (`ValueError: SOP is not lint-clean … MISSING_FIELD`) and
  `card_withdrawal` intake has no source. GREEN after the five policy
  changes: 44/44 OK; card-flow regression (`tests.test_publication`,
  `tests.test_publication_rotation`, `tests.test_publication_demo`) 64/64
  OK; full discover 988 OK skipped=3.
- **Task 4** — pins on probe-verified S8/S11 machinery; two test-harness
  fixes (state version for `revoke_evidence` in the helper; real evidence
  event ids for the admin revocations). GREEN: 8/8 OK; full discover 996
  OK skipped=3.
- **Review fixes** — cross-shape evidence isolation second direction
  (card_withdrawal on a card work turns `invalid`, S02 pending): new pin
  GREEN, full discover 997 OK skipped=3. Near-miss admission message:
  strengthened test RED (`assertEqual` message mismatch observed), then
  `validate_document` names `WITHDRAWAL_REQUEST_MESSAGE`; GREEN, full
  discover 997 OK skipped=3.

## Gates and batteries (final tree, ab8235d)

- `python3 scripts/check_docs.py` → `checked 113 markdown files, 532
  local links, 0 broken`.
- `python3 -m unittest discover -s tests -v` → `Ran 997 tests in 45.440s /
  OK (skipped=3)`; exact skips (all pre-existing):
  `test_opted_in_action_context_replay_returns_identical_receipt`
  (test_file_adapter.FilePublisherConformanceTests),
  `test_opted_in_action_context_replay_returns_identical_receipt`
  (test_publishing.FakePublisherConformanceTests),
  `test_absent_backend_is_a_bounded_startup_error`
  (test_ui_cli.AbsentBackendTests).
- `python3 -m work_runtime demo` → exit 0.
- `python3 -m compileall -q work_runtime tests scripts` → clean.
- `python3 scripts/check_site.py` → `checked 2 pages, 0 findings`.
- Demo set exit 0: `demo`, `publish-demo`, `intervention-demo`,
  `adoption-demo`, `revocation-demo`, `compensation-demo`,
  `rotation-demo`, `publication-demo`; the withdrawal chapter is
  correctly absent from `publication-demo` until W2.
- Rehearsals `python3 -m unittest discover -s examples/rehearsal` →
  `Ran 15 tests … OK (skipped=1)` (pre-existing generic opt-in
  conformance skip).
- `python3 scripts/verify_install.py` serial (nothing concurrent) →
  `=== PASS ===`, exit 0, zero SKIPPED, unchanged stage set.
- Protected scope: `git diff --stat b445fc1..HEAD` touches only
  `work_runtime/publication.py`, the two new test files,
  `docs/sop-authoring.md`, `docs/verification.md`, the plan doc. No
  runtime/ingress/authoring/policy/adapters/file_adapter/cli/demo/
  installer/README/UI/site/AGENTS diffs. No secrets printed anywhere
  (ephemeral `secrets.token_bytes(32)` keys only).

## What the surface does (ratified mapping)

- **D67/D68/D69** — second immutable hash-named record artifact per
  withdrawn version; `withdrawal_key = "sop-withdrawn:" +
  digest([policy_id, policy_version])`; closed four-field deterministic
  record (`discriminator "sop.withdrawal"`), no free text, id-less
  (effectively immutable under `revise_document`).
- **D74** — `SopWithdrawalStore` wraps `FilePublisher` unchanged; absent
  target or digest mismatch returns a deterministic **rejected receipt**
  (`status: "rejected"`, digest binding the operation) resolving
  `confirmed_failed`, work `needs_attention` and **cancellable**
  (pinned end-to-end: completion refuses, cancel+finalize closes
  `cancelled`). No `ValueError` refusal channel exists.
- **D72/RV-F5** — loader step after full validation: distinct withdrawn
  vs invalid-record bounded errors, explicit catch-and-re-raise mapping
  for corrupt records, `withdrawal_record()` audit read, absent-artifact
  precedence, `pinned_card` inherits before pin judgment, no override
  keyword on any read function.
- **D70/D71/D75** — same family/database; W02/W03 chosen by document
  shape; capability×shape pairing both directions at the blocker level
  AND the evidence level; signed `card_withdrawal`
  `{digest, policy_version}` with D58-mirror refusals (tamper →
  `EVIDENCE_AUTHENTICATION_FAILED` zero intake writes; wrong digest →
  verified-but-pending; wrong version → `invalid`); no admin bypass;
  D66 order pinned for second withdrawal works; wrong-adapter dispatch
  holds `ADAPTER_ACTION_UNSUPPORTED` with zero attempts.
- **D73/D76** — re-publication of a withdrawn version refused by the
  governed proposal's target checks (`OPERATION_CONTENT_CONFLICT` after
  own approval) with census unchanged; no un-withdrawal; no Runtime
  wiring; publication works complete unchanged (F18 regression pinned).
- **D79** — S8 composition pinned: admin revokes `card_approval` +
  runtime-written `accepted` proof on the closed work; completion
  byte-identical; two `EvidenceRevoked` events; artifacts untouched;
  revocation never touches the withdrawal record and vice versa.
- **Rotation** — `card_withdrawal` battery on S11 semantics:
  retired/dropped codes with six-table byte dumps, verbatim
  same-command-id replay, current-status resend, both-artifact byte
  invariance after a completed withdrawal, pre-rotation approval still
  completes, new-key continuation.

## Remaining risks / honest limits

- **Crash window on refusals (accepted by the review §5):** if a process
  dies after the wrapper returns a rejected receipt but before `_resolve`
  commits, `reconcile` finds `lookup → None` and lands
  `NO_AUTHORITATIVE_RESULT` (`needs_attention`) — genuinely ambiguous
  after a crash; teaching reconcile a failed-lookup resolution would be a
  `runtime.py` change the design forbids itself. The designed path is
  pinned; the window is disclosed.
- Withdrawal fences no running consumer (the Runtime never consults the
  store); there is no un-withdrawal — the loader's withdrawn answer is
  permanent while the record stands; a configuration rollback can revive
  approver keys for future acts (S11 limits); cross-database shared
  directories remain the accepted MD-4 operator boundary; raw adapter use
  can commit records the loader then honors or refuses fail-closed.
- Trusted-local principals only; no authentication, TLS, KMS,
  revocation-propagation or distributed exactly-once claim.
- Owed by W2: the `publication-demo` withdrawal chapter, installer stage,
  bilingual README mention, and the sop-authoring demo-section refresh
  (the current text already states the demo chapter arrives with the S13
  demo wave).

## Verification rows note

The S13 coverage section in `docs/verification.md` names each new test
class and behavior; a clarifying phrase for the near-miss admission
message rides with this report commit (commit `ab8235d` strengthened an
existing test's assertion without a verification touch — corrected here).
