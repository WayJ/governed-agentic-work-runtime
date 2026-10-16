# S14 W1 core report — publishing compensation core (store surface + policy/governed flow + boundary pins)

Worker: S14 W1 core development, worktree `s14-compensation-core`
(`WayJ/s14-compensation-core`), dispatched off the sprint carrier
`WayJ/sprint-s14-publishing-compensation` at exact `7f547cb` (verified by
`git rev-parse`, tree clean). Scoped plan committed before code at
`091b27b` ([plan](../docs/superpowers/plans/2026-10-16-s14-core.md));
executed task-by-task with observed RED before minimal implementation.

## Commits (this branch, newest last)

| commit | content |
|---|---|
| `091b27b` | docs: S14 W1 scoped implementation plan |
| `5e7b483` | feat: PublishingPolicy content.unpublish pairing attribute (D81/D89) + S10 pin supersession + family truth docs |
| `c636954` | feat: FakePublisher action-context opt-in, additive store migration and forward identity (D86/D87) |
| `b23ccb4` | feat: FakePublisher content.unpublish retraction with alias receipts and ORIGINAL_ABSENT (D86) |
| `7dd69a8` | test: governed admission, authority, key/replay and RF4 reachability coverage (D80-D84) |
| `5813349` | test: governed dispatch, resolution, closure and crash recovery coverage (D85/D88) |
| (this commit) | test: D82/D88 boundary byte pins; verification.md S14 coverage section; this report |

## RED/GREEN evidence per task

- **Task 1 (pairing)** — RED: `test_paired_capability_attribute_and_empty_blockers`
  errored `AttributeError: 'PublishingPolicy' object has no attribute
  'compensation_capabilities'`; after the minimal attribute + blockers branch,
  the two S10 publishing-asset pins failed as predicted (supersession RED:
  `test_unpaired_and_publishing_capabilities_stay_unsupported`,
  `test_publishing_family_and_assets_unchanged`). GREEN: 5/5 new +
  `tests.test_compensation` 57/57 after the authorized in-place pin updates.
- **Task 2 (opt-in + migration + forward identity)** — RED: 4 failures + 2
  errors (3-column receipts, missing `retractions`, `retracted_count`
  absent, kwargs `TypeError`, contract tuple mismatch). GREEN: 11/11; full
  battery `1020 → 1026 OK, skipped 3 → 2` — the FakePublisher conformance
  opt-in test ACTIVATED exactly as designed (F6; observed in `-v`: it now
  runs, only `test_file_adapter.FilePublisherConformanceTests` still skips).
- **Task 3 (retraction execution)** — RED: 6 errors (`ValueError: Unknown
  action: content.unpublish`) + 1 guard-message failure. GREEN: 18/18;
  battery `1033 OK (skipped=2)`.
- **Task 4 (governed admission/authority/key/replay/RF4)** — GREEN pins of
  the shipped S10 machinery (feature REDs were Tasks 1-3, per plan). The run
  caught two TEST-fixture defects (see findings); product unchanged.
- **Task 5 (dispatch/resolution/closure/recovery)** — GREEN pins; the same
  fixture trap surfaced twice more and was fixed in the tests.
- **Task 6 (boundary pins + battery)** — `BoundaryPins` pass; final battery
  below.

**Test-fixture findings (no product change):** three tests initially assumed
two forward proposals of the same document produce two operations — the
store-global forward business key (`digest([policy.id, capability,
document.id, document_digest])`, embeds no work id) re-admits one operation
by design. Each accidental probe actually re-verified re-admission and the
D6 key; fixtures now use distinct document revisions. One second-work
fixture lacked a cancellation intent (correctly
`CANCELLATION_NOT_REQUESTED`).

## Final verification battery (verbatim counts)

- `python3 -m unittest discover -s tests -v` → **`Ran 1059 tests … OK
  (skipped=2)`** (baseline 1015 + 44 new). Exact skips:
  `test_opted_in_action_context_replay_returns_identical_receipt`
  (`test_file_adapter.FilePublisherConformanceTests` — designed skip, D88
  FilePublisher stays forward-only) and
  `test_absent_backend_is_a_bounded_startup_error`
  (`test_ui_cli.AbsentBackendTests` — pre-existing). The baseline's third
  skip (`test_publishing.FakePublisherConformanceTests` opt-in skip) is
  gone: that test now runs and passes (F6 activation, by design).
- Five AGENTS gates VERBATIM: `python3 scripts/check_docs.py` → `checked
  121 markdown files, 578 local links, 0 broken`; the unittest gate → OK
  (skipped=2); `python3 -m work_runtime demo` → exit 0;
  `python3 -m compileall -q work_runtime tests scripts` → clean;
  `python3 scripts/check_site.py` → `checked 2 pages, 0 findings`.
- Eight existing demos exit 0: `demo`, `publish-demo`,
  `intervention-demo`, `adoption-demo`, `revocation-demo`,
  `compensation-demo`, `rotation-demo`, `publication-demo`; the retraction
  chapter is correctly absent from `publish-demo` until W2 (zero
  "retract" matches in its output).
- Rehearsals `python3 -m unittest discover -s examples/rehearsal` →
  `Ran 15 tests … OK (skipped=1)` (pre-existing generic opt-in conformance
  skip).
- `python3 scripts/verify_install.py` serial → **`=== PASS ===`**, exit 0,
  unchanged stage set (no S14 stages — W2 adds them same-commit with the
  demo chapter per D90).
- Protected scope: `git diff --stat 7f547cb..HEAD` touches only
  `work_runtime/publishing.py`, `tests/test_publishing_compensation.py`
  (new), the two authorized sites in `tests/test_compensation.py`, two
  mechanical `**kwargs` fixes in `tests/test_publishing.py`, four truth
  docs (`runtime-boundaries.md`, `interventions.md`, `verification.md`,
  `adapter-contract.md`), the plan and this report.
  `git diff 7f547cb -- work_runtime/runtime.py work_runtime/adapters.py
  work_runtime/file_adapter.py work_runtime/policy.py` → **empty** (D82
  strict + D88, also hash-pinned in `BoundaryPins`). Python ≥3.9, stdlib
  only, runtime store schema `1`.

## What shipped (ratified mapping)

- **D81/D89** — `PublishingPolicy.compensation_capabilities =
  {"content.unpublish": "content.publish"}`; paired capability → empty
  blockers (admission through the link check); off-family capabilities
  degrade to `CAPABILITY_UNSUPPORTED`; version stays `demo-1` (no new
  version).
- **D86+MD-2** — FakePublisher contract
  `actions=("content.publish", "content.unpublish")` (forward FIRST),
  `uniqueness=("document.id+content_digest",
  "retraction.original_external_id")`, `supports_action_context=True`;
  additive `BEGIN IMMEDIATE` migration (PRAGMA-probed `receipts.action`/
  `link_digest`, new `retractions` table, race-free concurrent first-open,
  idempotent reopen, no legacy row rewritten); retraction execution with
  one effect per original, `RTR-` id prefix (pinned deterministically),
  requesting-digest alias receipts reusing the retraction id,
  authoritative stored `ORIGINAL_ABSENT` rejection, forward-receipt
  original-existence scan with publications short-circuit; `retracted_count()`
  added, `published_count()` unchanged (effects never counted away).
- **D87 (as amended)** — forward path behavior-identical: no
  withdraw-by-store-state branch; same-content dedup returns the identical
  receipt with identical store state; forward rows keep NULL
  action/link_digest; retraction append-only. **Disclosed edit:** the
  single mechanical column-naming change to the forward receipts INSERT
  (`INSERT INTO receipts (key,digest,result) VALUES (?,?,?)`).
- **D80/D82/D83/D84/D85/D88** — governed flow verified on the real Runtime
  + SQLite (S10 semantics verbatim: window split, immutable snapshot, D6
  key `digest(["content-publish", "content.unpublish", target])`,
  replay/re-admission, grant-loss denial at proposal/replay/dispatch,
  cross-work same-content `OPERATION_CONTENT_CONFLICT` + same-work
  `CANCELLATION_ACTIVE` (RF4 legs), `withdrawn` proof at source
  `publisher`, C04 inertness, import denial, admin-only revoke,
  `adapter_result`, binding-mismatch quarantine, exact two-id
  closed/cancelled ack with compensation dispositions, unresolved-blocking-
  finalize, response-loss reconcile and real child crash recovered once);
  `runtime.py`/`adapters.py` byte-unchanged with the D82 escalation rule
  never triggered; `FilePublisher` untouched, holds at the actions
  preflight with zero attempts.
- **D91** — same-commit truth docs on every behavior change (family
  heading/sentence in runtime-boundaries.md incl. the pairing-arm
  parenthetical and the WD-/E08-or-C04 generalization; interventions
  deferred-scope list; verification out-of-scope sentence + S14 coverage
  section; adapter-contract FakePublisher contract/store/retraction
  sections with the RF4 reachability note). No `doc_sync_map` row fires;
  `docs/roadmap.md` 0.3 stays master-owned close-out (MD-4).

## Disclosures (beyond the INSERT edit)

1. **S10 pin supersession (master-authorized option A, 2026-10-16):** the
   two publishing-asset pin tests in `tests/test_compensation.py` were
   updated in place to the S14 truth (PublishingPolicy paired; FakePublisher
   opt-in with `content.publish` first); all expense-family assertions in
   that file are byte-identical. The clauses were updated in the task whose
   behavior made them true (pairing at `5e7b483`, contract at `c636954`) so
   every commit stays green.
2. **`tests/test_publishing.py` mechanical fixes:** `CountingPublisher` and
   the `MalformedResultTests` `Tampered` wrapper gained `**kwargs`
   passthrough — they inherit `FakePublisher.contract`, so the runtime's
   opted-in kwargs call would have raised `TypeError`. No assertion changes;
   design §8 W1 names `tests/test_publishing.py` additions as legitimate W1
   test surface.
3. **File-location clarification (master-confirmed):** FakePublisher lives
   in `work_runtime/publishing.py`; ALL FakePublisher surface work happened
   there and BOTH `runtime.py` and `adapters.py` stayed byte-unchanged
   (stricter than the dispatch phrasing required).
4. **W1 grants are test-local grant dicts** (`publishing_compensation_grants`
   in the new test file); `publishing_demo.py` demo grants belong to W2 and
   were not touched.

## Remaining risks / open items

- W2 is pending and required for release: publish-demo retraction chapter
  (additive structure (b), counts 2/1, exact two-id closure), installer
  module-stage update + NEW console stage (disclosed as new coverage),
  README/README.zh entries; roadmap 0.3 close-out note is master-owned.
- The re-publish-after-retraction interplay is reachable only through
  direct adapter calls; through the governed flow both refusal legs are
  pinned (RF4). The limit binds the adapter model, not the governed flow.
- The FilePublisher conformance opt-in skip remains by design (D88).
- `content.unpublish` (content family) vs S13's `sop.withdraw` (SOP
  authoring family) naming kept distinct everywhere (F10).
- Trusted-local only: no authentication, tenant, fencing,
  distributed-exactly-once or production-safety claim; the fake publisher
  remains a local stand-in.

## Honest limits of this report

- No main merge, no push, no sprint flip, no release claim (integration is
  a separate owned wave). No extra agents were spawned (dispatch
  constraint); the plan's final whole-branch review was therefore performed
  as a documented self-review, and the sprint's independent core review /
  final acceptance waves remain the independent eyes on this work.
- All test material is synthetic and ephemeral (temp directories, throwaway
  SQLite stores); signing keys are fresh `secrets.token_bytes(32)` per test
  and never printed.
