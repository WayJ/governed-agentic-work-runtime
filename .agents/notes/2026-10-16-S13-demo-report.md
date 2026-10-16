# S13 W2 withdrawal demo chapter + docs development report — 2026-10-16

Worker: S13 W2 demo owner (`WayJ/s13-withdrawal-demo-2`, started EXACT
`da9d2def14ecd0bdbb55971acdc88cc141cb839a` = carrier
`WayJ/sprint-s13-sop-withdrawal`, verified by rev-parse, clean). Scoped plan
committed before code:
[f50b05d](../../docs/superpowers/plans/2026-10-16-s13-demo.md).
Implementation follows the ratified design D67–D79 (D77 = this wave),
spec §12 story 5, and the W1 stable surface exactly; `publication.py`,
`file_adapter.py`, `runtime.py`, `ingress.py`, `authoring.py`, `policy.py`,
`adapters.py`, `cli.py`, every other demo module, the UI, the site, AGENTS,
roadmap, sprint and pyproject are untouched (explicit `git diff` empty).
No merge, no push — integration owns the release after independent final
acceptance.

## Commits (in order)

| commit | content |
|---|---|
| `f50b05d` | docs: S13 W2 withdrawal demo chapter scoped implementation plan |
| `3946f38` | feat: publication-demo withdrawal chapter with extended installed proof (S13 D77) |
| `35b4cf3` | docs: bilingual README withdrawal mention with truthful limits (S13 D77) |

Same-commit doc pairing held (doc_sync_map `publication_demo.py →
sop-authoring.md`): `3946f38` touches `docs/sop-authoring.md` (Demonstration
section refresh) and `docs/verification.md` (S13 demo-wave coverage rows +
`Updated:` header) together with the demo and its tests. `cli.py` needed no
change — the existing `publication-demo [--directory]` subcommand runs the
extended chapter unchanged.

## What the chapter does (D77 mapping)

Continues the standing publication story in the SAME fresh store, same
Runtime/database, after the approver rotation: beats 14–20 — the closed
withdrawal request (published_digest = the pinned digest) enters as work
`wd-1` and is first blocked `REQUIREMENT_UNSATISFIED` on W02 (D66 order
visible); the valid signed `card_withdrawal` from the current (rotated) key
accepts the intent with the withdrawal key as business key; dispatch through
`SopWithdrawalStore` commits exactly one new hash-named artifact (the record;
census 2, zero `.stage`) with publication bytes unchanged and W03 satisfied
by the runtime-written `accepted` proof (`event_id` = the withdrawal
operation id) so completion closes `succeeded`; the loader now fails closed
with the DISTINCT `WITHDRAWN_MESSAGE` (not absent — printed and asserted
pairwise distinct from absent and tampered); `withdrawal_record()` returns
the exact record; re-publication of the withdrawn version (`pub-3`) is
blocked first and persists `OPERATION_CONTENT_CONFLICT` only after its own
approval with zero store writes; a fresh old-key `card_withdrawal` is
refused `EVIDENCE_KEY_RETIRED` with six tables and BOTH artifacts untouched.
The closing PASS line counts (1 published version, 1 withdrawal record, 2
committed artifacts, 1 doctored conflict, 1 re-publication refusal, 3 loader
refusals, 2 retired-key refusals, history rewritten 0) is asserted inside
the demo against the real SQLite (receipt codes, table counts 4/22/6/2) and
the artifact directory (census by parsed key prefix), never against the
narration. Two inspect commands (`pub-1`, `wd-1`) print verbatim-runnable,
plus both artifact paths. Fresh temp directory per run, no credentials,
synthetic ephemeral keys never printed (planted-marker test green on the
extended run).

## RED/GREEN evidence (TDD, observed)

- **RED 1** — new `tests/test_publication_withdrawal_demo.py` (chapter
  tests): `ImportError: cannot import name 'REPUBLICATION_WORK_ID'` before
  any product change; the updated S12 pins failed the same way.
- **GREEN 1 (partial, by design)** — after the chapter implementation the
  chapter tests + S12 pins passed, and the six pre-existing
  `VerifyInstallPublicationProofTests` went RED with the observed
  `SystemExit: FAILED: test output lacks '<old final line>'` — the old
  installer proof rejecting the extended demo is the proof extension's
  meaningful RED.
- **GREEN 2 (cycle A)** — proof constants/censuses updated → 38/38 OK
  (events prediction 21 confirmed by run).
- **RED 2 (cycle B)** — three new mutation tests failed
  `AssertionError: SystemExit not raised` (tampered withdrawal record,
  flipped `card_withdrawal` status, rewritten `cmd-propose-pub3` receipt):
  the proof accepted mutated stores because it never inspected the
  withdrawal surfaces. The deleted-record mutation passed immediately — it
  pins the pre-existing census check (disclosed, kept as a regression pin).
- **GREEN 3** — semantic proof extension (withdrawn line three-way
  distinct, record located by printed path AND sha256(withdrawal key) name
  and parsed, wd-1/pub-3 states, withdrawal operation by business key,
  `card_withdrawal` evidence, second `sop-store` proof, both D66 receipts,
  all printed inspect commands re-run) → 43/43 OK; full battery below.

## Gates and batteries (final tree, 35b4cf3 + report commit)

- `python3 -m unittest discover -s tests -v` → **`Ran 1015 tests in 42.0s /
  OK (skipped=3)`** = 997 baseline + **18 new** (13 `WithdrawalChapterTests`
  + 5 `VerifyInstallWithdrawalProofTests`); exact skip names, all
  pre-existing: `test_opted_in_action_context_replay_returns_identical_receipt`
  (`test_file_adapter.FilePublisherConformanceTests`), the same name
  (`test_publishing.FakePublisherConformanceTests`),
  `test_absent_backend_is_a_bounded_startup_error`
  (`test_ui_cli.AbsentBackendTests`).
- Five AGENTS gates verbatim, all green: `python3 scripts/check_docs.py` →
  `checked 110 markdown files, 534 local links, 0 broken` on the working
  tree; **the committed tree measures 109 files, 534 links, 0 broken**
  (`git archive` extraction; the 110th is the git-ignored SDD ledger);
  full discover (above); `python3 -m work_runtime demo` → exit 0;
  `python3 -m compileall -q work_runtime tests scripts` → clean;
  `python3 scripts/check_site.py` → `checked 2 pages, 0 findings`.
- Demo set exit 0 (all eight): `demo`, `publish-demo`,
  `intervention-demo`, `adoption-demo`, `revocation-demo`,
  `compensation-demo`, `rotation-demo`, `publication-demo` — the last now
  including the withdrawal chapter.
- Rehearsals `python3 -m unittest discover -s examples/rehearsal` →
  `Ran 15 tests … OK (skipped=1)` (pre-existing opt-in conformance skip).
- `python3 scripts/verify_install.py` run serially with nothing
  concurrent → `=== PASS ===`, exit 0, **zero SKIPPED**; the existing
  publication stage (module AND console, outside the checkout) now also
  verifies the chapter independently of stdout — two hash-named artifacts
  parsed with the standard library only, the closed withdrawal record
  binding the published digest, wd-1 closed/succeeded and pub-3 active,
  both `confirmed_succeeded` operations, the verified `card_withdrawal`,
  both `sop-store` accepted proofs, both D66 conflict receipts, both
  printed inspect commands re-run verbatim. No new stage, no new gate.

## Docs and README

- `docs/sop-authoring.md` Demonstration section: the chapter narrative, the
  two inspect commands/artifact paths, and the limits updated (withdrawal
  chapter present; no un-withdrawal — corrected content ships as a new
  version string) — same commit as `publication_demo.py` per the
  doc_sync_map row.
- `docs/verification.md`: S13 section gains the demonstration-surface and
  installed-verification bullets; `Updated:` header carries the S13 waves.
- `README.md` / `README.zh-CN.md` (symmetric, five passages each language):
  the publication-demo section describes the chapter; the "What works
  today" bullet names governed publication AND withdrawal; the core-API
  not-implemented list now names *un-withdrawal* instead of withdrawal;
  the verify_install description covers the deeper publication proof.
  Truthful limits everywhere: no un-withdrawal (forward-only new version),
  trusted-local principals not authentication, config-only trust
  (rollback revives retired keys), no tenant auth/TLS/KMS/network, no
  distributed exactly-once.

## Incidents (disclosed)

- One `README.zh-CN.md` edit matched a non-unique anchor and briefly
  corrupted the S10 section opener (line 101); reverted immediately and
  re-applied with unique anchors; the final diff was verified line-by-line
  symmetric (5 lines per README) with the S10 section byte-identical to
  baseline.
- The plan's Task 1/Task 2 boundary was restructured by a ledgered ruling:
  the demo chapter and the installer-proof extension landed in ONE commit
  (`3946f38`) because the pre-existing proof tests pin the demo census —
  extending the demo without the proof would have left the suite red at
  that commit. All pairing rules still held.

## Remaining risks / honest limits

- `docs/roadmap.md` 0.4 still lists publication withdrawal as
  separately-designed future work — the roadmap is master-owned and was
  not touched by this worker; the master may want to update it at release.
- The installer stage needs pip index access for the build backend
  (pre-existing condition, unchanged); the demo/test/verification layer
  stays fully offline.
- Withdrawal fences no running consumer (D62 unchanged); there is no
  un-withdrawal while the record stands; a configuration rollback revives
  old approver keys for future acts (S11 limits); cross-database shared
  directories remain the accepted MD-4 operator boundary; raw adapter use
  can commit records the loader then honors.
- Trusted-local principals only; no authentication, TLS, KMS,
  revocation-propagation or distributed exactly-once claim (and none made
  in code, docs or READMEs).
- Two deferred minors from self-review (recorded in the SDD ledger): the
  proof's `operations[0]` publication-order assumption fails loudly, never
  falsely passes, if row order ever changed; the stdlib-only verifier pins
  the withdrawn line by substring + distinctness (exact-message equality
  is pinned in the test suite, which may import the package).
- Independent final acceptance and the integration-owned ordinary main
  merge remain the master's next dispatches; this worker claims neither.
