# Acceptance record — sprint S14, 2026-10-16

Independent Orca final acceptance of the assembled S14 publishing-family
linked-compensation release (`content.unpublish`). Baseline asserted exact
before anything ran: carrier `WayJ/sprint-s14-publishing-compensation` at
`2181471f7ae92db56a579bcdb442f3decf421ceb` (worktree clean, 0 dirty files),
W2 accepted demo source `WayJ/s14-compensation-demo` at
`6dd72a094fffa0d26a83375fa6f8e77a55567da1` (`git rev-parse` verified equal
to the branch tip and to the checkout HEAD, worktree clean, exactly **4
commits** `2181471..6dd72a0` = `1a314d5..6dd72a0` inclusive — plan `1a314d5`,
demo chapter `8543164`, installer stages `d0c09fa`, report+coverage `6dd72a0`
— merge-base `2181471`), control `WayJ/s14-release-control` at `2181471`
(clean). Assembly performed by this review as an ordinary `--no-ff` merge of
`6dd72a0` onto `2181471` in the acceptance worktree branch
`WayJ/s14-final-accept`: merge commit
`f9a2a5c0a865b22f0ae3f5bc6623e12018672c37` (no conflict — exactly the 10
W2-owned files, +1170/−66, tree clean after). **Before any scenario ran**,
both the carrier `WayJ/sprint-s14-publishing-compensation` and the control
`WayJ/s14-release-control` were fast-forwarded `2181471 → f9a2a5c`
(`--ff-only`, no force anywhere; both asserted clean first); `git rev-parse`
of carrier, control and the acceptance HEAD all equal `f9a2a5c` and all three
tree hashes equal `c0d1a67256d890020ab5b2f02a6b8bba7fe0a2a5` — every scenario
below ran fresh in the **actual assembled carrier worktree**
(`sprint-s14-publishing-compensation`), not a tmp or stale tree. No main
merge, no push, no force, no extra agents. Base main
`678d7b4` (S13 close-out published; the roadmap 0.3 close-out sentence, E14
status, ledger flip, closing note and teardown are master-owned close acts,
and the integration-owned ordinary main merge/non-force push is the next
master dispatch after this pass). Python 3.9.6 (system `python3`); zero
runtime dependencies (re-verified by the fresh venv install: only
`governed-work-runtime` `0.1.0a1` plus venv tooling, no third-party
packages). Review inputs read in full: AGENTS.md (incl. the supervibe gates
and the `doc_sync_map`), the ratified design spec with **MASTER ratification
D80–D91** incl. the D87 amended behavior-level pin, the D90 additive demo
structure (b) with counts 2/1 + new console stage, and the D82 byte pins with
the escalation rule
([§1–§10 + ratification](../specs/2026-10-16-beyond-window-compensation-design.md)),
the [E14 roadmap](../roadmaps/2026-10-16-publishing-compensation.md), the
active [S14 sprint plan](../sprints/2026-10-16-S14-plan.md), the [W1 core
report](../../../.agents/notes/2026-10-16-S14-core-report.md), the [W1 core
integration review](../../../.agents/notes/2026-10-16-S14-core-integration-review.md)
(mi-1/mi-2, obs-1, the option-A supersession record) and the [W2 demo
report](../../../.agents/notes/2026-10-16-S14-demo-report.md); the
[S13 acceptance record](2026-10-16-S13-acceptance.md) was the house-format
precedent. This acceptor made **no product fix**; every check ran against the
assembled carrier tree as committed.

## Verdict

**pass** — all four scenarios green on fresh runs in the actual assembled
carrier tree (`f9a2a5c`, carrier and control verified at that SHA, identical
tree hashes, before the runs), with independent live assertions beyond the
test suite (direct SQLite reads of both demo stores, sha256 equality of the
four pinned files against `BoundaryPins.PINNED`, source-level location of the
single disclosed INSERT edit and of the absent withdraw-by-store-state
branch, RF4 both-legs verification, no-secrets scans of module and console
demo output); every DoD item checked with evidence; the doc-drift audit over
the dispatch range `2181471..f9a2a5c` (with the W1 context
`7f547cb..2181471` re-verified quickly and the full sprint range
`7f547cb..f9a2a5c` asserted) shows **no `doc_sync_map` row fires** — all
eight mapped files are byte-identical over the full sprint range and every
row owes nothing, while the D91 truth docs were delivered same-commit on
every behavior commit. This record and the sprint-doc state flip are written
in one same-commit act and precede the integration-owned ordinary main
merge/non-force push; final remote equality and exact-SHA CI are the close
act's items per the S7–S13 precedent.

## Scenario Results

| id | command | expected | actual | pass |
|---|---|---|---|---|
| S1 | in the assembled carrier worktree: `python3 -m unittest tests.test_publishing_compensation.PolicyPairingTests tests.test_publishing_compensation.FakePublisherMigrationTests tests.test_publishing_compensation.ForwardIdentityTests tests.test_publishing_compensation.RetractionExecutionTests tests.test_publishing_compensation.RetractionAppendOnlyTests -v` | D46 pattern exact; no legacy-store break; append-only | **`Ran 18 tests in 0.031s / OK`** (exit 0). Ordered contract: `test_contract_order_and_optin` (actions `("content.publish", "content.unpublish")`, forward FIRST, `supports_action_context=True`), `test_file_publisher_stays_forward_only`; migration: `test_old_publisher_store_migrates_additively`, `test_concurrent_first_open_serializes`, `test_fresh_store_is_schema_current`; forward identity rows: `test_forward_rows_stay_null_action_and_replay_identically`, `test_same_content_dedup_identity`; retraction surface: `test_retraction_executes_once_and_is_idempotent_by_key`, `test_same_key_different_link_conflicts_even_with_equal_digest` (digest-conflict bounded), `test_different_key_same_original_returns_alias_and_lookup_is_authoritative` (alias receipts reusing the `RTR-` id), `test_missing_original_is_bounded_business_rejection` (`ORIGINAL_ABSENT` stored rejection), `test_original_existence_via_scan_and_short_circuit` (forward-receipt scan + publications short-circuit), `test_retraction_is_append_only_and_forward_still_dedups` — all observed `ok` in `-v` | yes |
| S2 | in the assembled carrier worktree: `python3 -m unittest tests.test_publishing_compensation.PublishingCompensationAdmissionTests tests.test_publishing_compensation.PublishingCompensationAuthorityTests tests.test_publishing_compensation.PublishingDispatchTests tests.test_publishing_compensation.PublishingResolutionTests tests.test_publishing_compensation.PublishingClosureTests tests.test_publishing_compensation.PublishingRecoveryTests -v` | S10 semantics verbatim in the publishing family; no new codes | **`Ran 25 tests in 1.073s / OK`** (exit 0). Window admission: `test_linked_retraction_proposal_accepted_during_window`, `test_linked_retraction_requires_active_cancellation`, `test_forward_proposal_still_rejected_in_window`; immutable snapshot: `test_retraction_link_snapshot_is_immutable`; D6 key: `test_retraction_business_key_stable_and_distinct`; targets: `test_retraction_target_must_be_confirmed_succeeded_same_work`, `test_retraction_target_must_not_be_compensation`; authority/grant-loss: `test_retraction_authority_is_current_owner_with_grant`, `test_retraction_replay_and_authority`, `test_dispatch_holds_retraction_on_grant_loss`; RF4 both legs: `test_republish_after_retraction_unreachable_governed` (test body read this run — same-work forward re-publish → `("rejected", "CANCELLATION_ACTIVE")`, cross-work identical content → `("rejected", "OPERATION_CONTENT_CONFLICT")`); FilePublisher hold: `test_file_publisher_holds_at_actions_preflight` (zero attempts); withdrawn proof: `test_accepted_retraction_writes_withdrawn_proof_at_publisher`, `test_withdrawn_kind_never_satisfies_c04`; resolution: `test_retraction_resolution_stores_adapter_result`, `test_binding_mismatch_is_quarantined`; closure: `test_finalize_ack_includes_original_and_retraction` (exact two-id ack), `test_refused_retraction_closure_ack_is_original_only`, `test_unresolved_retraction_blocks_finalize`; recovery: `test_response_loss_recovers_once_by_lookup` and **`test_real_crash_after_retraction_recovers_once`** (real child killed after the retraction commits) — all observed `ok` | yes |
| S3 | live in the assembled carrier worktree: `git diff 7f547cb f9a2a5c -- work_runtime/runtime.py work_runtime/adapters.py work_runtime/file_adapter.py work_runtime/policy.py`; `shasum -a 256` of the four files vs `BoundaryPins.PINNED`; `python3 -m unittest tests.test_publishing_compensation.BoundaryPins tests.test_publishing_compensation.ForwardIdentityTests -v`; `grep -n 'INSERT INTO receipts' work_runtime/publishing.py`; `grep -c 'retractions'` over the `_execute_forward` body | D87/D82/D88 pins hold with the single disclosed INSERT edit | Diff **empty** (0 lines) — the four files byte-unchanged `7f547cb..assembled`, asserted live. sha256 at `f9a2a5c` = `BoundaryPins.PINNED` exactly: `80bf721b3369a6fb865fd6aba0e57804a69eb8587431f8fa6edf1183fc53f4b3` (`runtime.py`), `ce132f24d84c17a083bcf0b61bf90e1c62ff75faf2ec52fe2c7348ab86b6985e` (`adapters.py`), `7044a92b97af266df896704ab84eb842d2e4754a204b54377649da93c0b476e2` (`file_adapter.py`), `76d4e9c605855ba19580591988cadc1d33ab81dd3672ddf84559eeb28cffdc82` (`policy.py`); `BoundaryPins` + `ForwardIdentityTests` → **`Ran 4 tests … OK`**. The single disclosed column-naming INSERT edit is located at `work_runtime/publishing.py:243` inside `_execute_forward` (`INSERT INTO receipts (key,digest,result) VALUES (?,?,?)`) with its in-code disclosure comment; the retraction INSERT at `publishing.py:272` is the new retraction path's own statement. No withdraw-by-store-state branch: the `_execute_forward` body references `retractions` **0 times** — the only references in the module are the migration DDL (`:161`), `_execute_retraction` (`:255, :264`) and `retracted_count()` (`:317`). Same-content dedup identical receipt/store state: `test_same_content_dedup_identity` + `test_forward_rows_stay_null_action_and_replay_identically` ok (S1 run); retraction append-only: `test_retraction_is_append_only_and_forward_still_dedups` ok (S1); FilePublisher holds at the actions preflight (S2 run); RF4 both legs probed green (S2 run) | yes |
| S4 | module `python3 -m work_runtime publish-demo --directory /tmp/s14-accept-demo/run` and console `work-runtime publish-demo` outside the checkout (fresh venv), both printed inspect command pairs re-run verbatim; direct SQLite reads of both stores; `python3 scripts/verify_install.py` serial; the five AGENTS gates verbatim; eight demos; `python3 -m unittest discover -s examples/rehearsal`; full suite `python3 -m unittest discover -s tests -v`; no-secrets scans | Chapter appended with crash exit-73, one-attempt recovery, exact two-id closure, counts 2/1 from both stores; installer module stage updated + NEW console stage, serial zero SKIPPED; five gates verbatim; eight demos exit 0; rehearsals 15 OK 1 pre-existing skip; full suite 1077 OK skipped=2 exact names; no secrets | Module demo **exit 0**: work-one steps 1–6 verbatim (succeeded completion, `published artifacts: 1` at step 6), chapter header, steps 7–12 (ART-002 confirmed publish, `request_cancel`, linked retraction five-key payload with immutable `{operation_id, external_id, capability}` snapshot, grants-carrying child dies **`exit code 73`** after the retraction commits, restart `recover()` **`confirmed_succeeded in exactly one attempt`**, withdrawn proof appended while publication/receipt/accepted proof stay intact, finalize with the **exact two-id ack** → `closed`/`cancelled`), final line `2 works; published artifacts: 2; retraction effects: 1; bounded in-window retraction, not reversal`; both printed inspect commands re-run **verbatim, exit 0** (`article-1` closed/succeeded, `article-2` closed/cancelled, its closure JSON shows `acknowledged_operations = [{PUB-a23a85c7b314, 4657fc3e…}, {RTR-772bbf3a4741, b621258a…}]` and the compensation disposition carrying `compensates` + `adapter_result`). **Both stores read directly by this review**: `publisher.sqlite` → `publications` rows = **2**, `retractions` rows = **1**; `runtime.sqlite` → 2 works (`article-1`, `article-2`), 3 operations (publish/publish/retraction), article-2 evidence carries **both** the intact `accepted` and the appended `withdrawn` proof at source `publisher` (event_id = the retraction operation id). Console demo **outside the checkout** (fresh venv at `/tmp/s14-accept-venv`, install exit 0, only `governed-work-runtime==0.1.0a1`): `work-runtime publish-demo` from `/tmp` **exit 0** with the same narrative and counts; both console-printed inspect commands re-run verbatim (venv `python3 -m work_runtime`, outside the checkout) **exit 0** (`succeeded`/`cancelled`). Installer **serial**: **`=== PASS ===`, exit 0, zero `SKIPPED` lines**, 23 stages — `=== module publish-demo outside the checkout ===` and the **NEW** `=== console publish-demo outside the checkout ===` both present with the independent check `published artifacts = 2, retraction effects = 1; recomputed keys, immutable link, withdrawn-kind proof, exact two-id closure and both printed inspect commands re-run verbatim`. Five gates verbatim (carrier worktree asserted clean first): contracts `checked 115 markdown files, 584 local links, 0 broken`; tests **`Ran 1077 tests in 46.593s / OK (skipped=2)`**; `demo` exit 0; `compileall -q work_runtime tests scripts` clean; site `checked 2 pages, 0 findings`. **Eight demos exit 0** (`demo`, `publish-demo`, `intervention-demo`, `adoption-demo`, `revocation-demo`, `compensation-demo`, `rotation-demo`, `publication-demo`; the seven `--directory` demos after the documented mkdir precondition — obstacles log). Rehearsals **`Ran 15 tests … OK (skipped=1)`** (pre-existing generic opt-in conformance skip). Full-suite skips, exact names: `test_opted_in_action_context_replay_returns_identical_receipt` (`test_file_adapter.FilePublisherConformanceTests`, reason `'adapter does not opt into action/link execution context'` — designed skip, D88 FilePublisher forward-only; the `test_publishing.FakePublisherConformanceTests` variant now runs and passes) and `test_absent_backend_is_a_bounded_startup_error` (`test_ui_cli.AbsentBackendTests`, reason `'backend assembled: absent-install path unreachable'` — pre-existing). Demo test module `tests.test_publishing_compensation_demo` → **`Ran 18 tests … OK`** incl. `test_secrets_never_printed`; this review's own scans: **0** matches of `[0-9a-f]{64}` and 0 secret keywords in the module and console demo stdout (only public 32-hex operation ids and named `PUB-`/`RTR-` external ids appear; probe keys synthetic, never printed) | yes |

## Independent live assertions (fresh this run, beyond the test suite)

- Direct SQLite reads of both demo stores (module run) confirming counts
  2/1, three operations, two works, and the `accepted`+`withdrawn` proof
  pair at source `publisher` (S4 row above).
- sha256 equality of the four D82/D88-pinned files against
  `BoundaryPins.PINNED`, and the empty `git diff 7f547cb f9a2a5c` over them
  (S3 row).
- Source-level location of the single disclosed INSERT edit
  (`publishing.py:243`, in `_execute_forward`, with its disclosure comment)
  and of the absent withdraw-by-store-state branch (`_execute_forward`
  references `retractions` 0 times).
- RF4 both-legs verification by reading the test body this run
  (`CANCELLATION_ACTIVE` same-work; `OPERATION_CONTENT_CONFLICT` cross-work)
  after its green run.
- No-secrets scans of the module and console demo stdout (0 64-hex matches).
- The W1 per-task RED granularity was independently replayed by the [W1 core
  integration review](../../../.agents/notes/2026-10-16-S14-core-integration-review.md)
  on the same core SHAs this release carries (`76988d2` merged via `b04aac2`);
  the W2 RED evidence (`Ran 12 tests … FAILED (failures=11)` and
  `AttributeError: module 'verify_install' has no attribute
  'require_publishing_proof'`) is recorded in the [W2 demo
  report](../../../.agents/notes/2026-10-16-S14-demo-report.md) — GREEN is
  the assembled-tree evidence of this run (the 18 demo-wave tests inside the
  1077-run, plus the demo/installer runs above).

## DoD Checklist

- [x] A current owner holding `content.unpublish` can propose a linked retraction of a published document inside the active cancellation window; the immutable original snapshot, D6 business key, replay/conflict semantics and `withdrawn` proof kind behave exactly as S10 pinned, with `runtime.py`/`adapters.py` byte-unchanged (escalation rule: any needed edit stops and asks the master) — S2: all 25 governed tests green on the real Runtime + SQLite (window split both variants, immutable snapshot, D6 key stable+distinct, replay/re-admission, grant-loss denial at proposal/replay/dispatch, `withdrawn` proof at source `publisher`, C04 inertness, binding-mismatch quarantine, exact two-id ack, dispositions with `compensates`+`adapter_result`, unresolved-blocking-finalize, real child crash recovered once); S3: `git diff 7f547cb f9a2a5c -- work_runtime/runtime.py work_runtime/adapters.py` empty (and `file_adapter.py`/`policy.py` too), sha256 = `BoundaryPins.PINNED`, no new codes anywhere; the escalation rule was never triggered (no runtime need discovered — W1 core report + review concur)
- [x] The forward publishing path is behavior-identical (no withdraw-by-store-state branch; same-content dedup to the same receipt; identical dispositions/store state) with the single disclosed column-naming INSERT edit; retraction is append-only; `FilePublisher` is untouched and holds at the actions preflight — S3: `_execute_forward` references `retractions` 0 times; `test_same_content_dedup_identity` + `test_forward_rows_stay_null_action_and_replay_identically` green (forward rows keep NULL `action`/`link_digest`); the single INSERT edit located at `publishing.py:243` with its disclosure comment (the W1 review's obs-1 read-side counterpart — the widened replay SELECT — is recorded there and behavior-identical by its cross-tree probe); `test_retraction_is_append_only_and_forward_still_dedups` green; `FilePublisher` byte-unchanged (sha256 pinned) and `test_file_publisher_holds_at_actions_preflight` green with zero attempts
- [x] FakePublisher gains the paired action behind the documented contract ordering (`content.publish` first), additive receipts `action`/`link_digest` migration, a `retractions` table, alias receipts, `ORIGINAL_ABSENT` and the forward-receipt original-existence scan — the verified D46 pattern — S1: 18/18 store-surface tests green (`test_contract_order_and_optin`, `test_old_publisher_store_migrates_additively`, `test_concurrent_first_open_serializes`, `test_fresh_store_is_schema_current`, `test_different_key_same_original_returns_alias_and_lookup_is_authoritative`, `test_missing_original_is_bounded_business_rejection`, `test_original_existence_via_scan_and_short_circuit`, idempotent replay and bounded digest-conflict); the W1 review additionally probe-verified legacy row bytes unchanged through migration and idempotent reopen on its own legacy store
- [x] The re-publish-after-retraction limit is documented with its reachability note (unreachable through the governed flow; binds the adapter model) — `docs/adapter-contract.md:369-374` "**Adapter-model limit — re-publish after retraction (RF4 note)**" states the interplay is unreachable (same-work permanent-intent refusal; cross-work store-global forward business-key collision) and that it binds the adapter model; carried in `docs/runtime-boundaries.md` (compensation boundary section) and both READMEs; both governed refusal legs pinned green by `test_republish_after_retraction_unreachable_governed` (S2)
- [x] `publish-demo` keeps its succeeded-completion story and appends the cancellation+retraction chapter (counts 2/1) with the exact two-id closure; the installer stage is updated same-commit and a new console stage is added; no secrets printed; the five gates, full suite, demo set, rehearsals and serial installed verification pass with exact counts/skips — S4: work-one steps 1–6 verbatim + chapter 7–12 + final line 2/1 (module and console, exit 0); counts asserted by this review's direct reads of both stores and independently by the demo tests and the installer proof; exact two-id closure observed in the inspect JSON; installer serial `=== PASS ===` zero SKIPPED with the updated module stage and the NEW console stage (same commit `d0c09fa` as the demo chapter's follow-up — the stage assertions updated in `d0c09fa`, same-commit with `docs/verification.md` per the diff-tree); five gates verbatim 115/584/0 · 1077 OK (skipped=2, exact names above) · demo 0 · compileall clean · site 2/0; eight demos exit 0; rehearsals 15 OK (skipped=1, pre-existing); zero 64-hex/secret matches in demo output
- [x] Independent acceptance precedes integration-owned ordinary main merge/non-force push with same-commit truthfulness docs and the master-owned roadmap 0.3 close-out note — this record + the sprint `state: acceptance` flip are one same-commit act written before any merge (no main merge, no push performed by this review; main still `678d7b4`); same-commit doc pairing audited per-commit over the whole release range (below); `docs/roadmap.md` untouched in `7f547cb..f9a2a5c` (0 bits changed — master-owned close-out, MD-4); final remote equality and exact-SHA CI are the close act's items per the S7–S13 precedent

## Obstacles (verbatim)

- 2026-10-16 — first pass over the seven `--directory` demos created only the
  parent directory (`mkdir -p /tmp/s14-accept-demo/demos`) and ran e.g.
  `python3 -m work_runtime publish-demo --directory /tmp/s14-accept-demo/demos/publish-demo`
  → exit 1, `FileNotFoundError: [Errno 2] No such file or directory:
  '/tmp/s14-accept-demo/demos/publish-demo/governed-publish-pbx2e92h'`
  (traceback through `tempfile.mkdtemp`). Notes searched first by keyword
  (`mkdtemp`/`FileNotFoundError` over `.agents/notes/` and the acceptance
  records): the canonical prior workaround is the [S12 acceptance
  record](2026-10-15-S12-acceptance.md) obstacles log, repeated by the [S13
  acceptance record](2026-10-16-S13-acceptance.md) — an existing
  `--directory` is every demo's contract (the identical `mkdtemp(dir=…)`
  pattern). Workaround reused with citation: `mkdir -p` each exact
  `--directory`, re-run → all seven demos exit 0. No product issue; no
  substitution (the re-run is the specified module command).
- 2026-10-16 — my console-inspect re-run loop first mangled the printed
  command lines through `sed`/parameter-expansion surgery, producing the
  argparse usage dump and `inspect-1 exit=2` / `inspect-2 exit=2`. Direct
  verbatim re-run of both printed commands (`/tmp/s14-accept-venv/bin/python3
  -m work_runtime inspect --db … --work article-N --policy content-publish`
  from `/tmp`) → exit 0, exit 0. Probe/shell error only; product unchanged.
- 2026-10-16 — my first direct SQLite evidence query guessed the schema
  (`SELECT kind, source, status … FROM evidence` → `sqlite3.OperationalError:
  no such column: kind`; a second attempt hit `no such column: outcome` on
  `works`). Fixed by reading `PRAGMA table_info` first, then re-querying the
  actual columns (`source, event_id, work_id, fingerprint, body`; `works` is
  `id, state`) — the S4 store evidence above is from the corrected reads.
  Probe error only; product unchanged.
- 2026-10-16 — cosmetic only: the fresh-venv `pip install` of the checkout
  emitted pip 21.2.4 deprecation/upgrade notices; install succeeded, zero
  third-party packages, console demo exit 0. Not a blocker (same notices as
  S12/S13).
- No other blocker, failure or substitution occurred. No evidence item in
  this record is substituted: every scenario ran its specified proving
  command for real on the actual assembled carrier tree.

## Doc-Drift Audit

Ranges audited: the dispatch-named W2 wave `2181471..f9a2a5c` (the
assembly), the W1 context `7f547cb..2181471` (audited by the W1 core
integration review; re-verified quickly this run), and the full sprint range
`7f547cb..f9a2a5c`. Per-commit pairing was checked with
`git diff-tree --no-commit-id --name-only -r <sha>` on every commit of both
waves. Changed files `2181471..f9a2a5c`: exactly 10, all W2-owned
(`work_runtime/publishing_demo.py`, `tests/test_publishing_compensation_demo.py`
new, `tests/test_publishing.py` two authorized in-place demo-test updates,
`scripts/verify_install.py`, `README.md`, `README.zh-CN.md`,
`docs/interventions.md`, `docs/verification.md`, the W2 plan, the W2 demo
report). Changed files `7f547cb..f9a2a5c` overall: 17 — none is a
`doc_sync_map` path.

| map row (change, owes) | matched this sprint | doc state | detail |
|---|---|---|---|
| work_runtime/runtime.py → docs/runtime-boundaries.md | no — byte-identical `7f547cb..f9a2a5c` (explicit diff empty; sha256 pinned, S3) | n/a | row owes nothing; D82 held, escalation rule never triggered |
| work_runtime/adapters.py → docs/runtime-boundaries.md | no — byte-identical over the full sprint range (S3) | n/a | row owes nothing |
| scripts/check_docs.py → CONTRIBUTING.md | no — unchanged over the full sprint range (not in the changed-path list) | n/a | row owes nothing |
| scripts/check_site.py → docs/website.md | no — unchanged over the full sprint range | n/a | row owes nothing |
| work_runtime/ingress.py → docs/signed-evidence.md | no — unchanged over the full sprint range | n/a | row owes nothing |
| work_runtime/publication.py → docs/sop-authoring.md | no — unchanged over the full sprint range | n/a | row owes nothing (S13 surface untouched; `content.unpublish` kept distinct from `sop.withdraw`, F10) |
| work_runtime/publication_demo.py → docs/sop-authoring.md | no — unchanged over the full sprint range | n/a | row owes nothing |
| work_runtime/file_adapter.py → docs/file-adapter.md | no — byte-identical over the full sprint range (sha256 pinned, S3; D88) | n/a | row owes nothing |

Beyond the map (recorded, not enforced): `work_runtime/publishing.py` — the
W1 product surface — has **no** map row (design F11, ratified D91): its four
truth docs were owed for truth and delivered same-commit on every behavior
commit (`5e7b483` → runtime-boundaries + interventions + verification;
`c636954` → adapter-contract + runtime-boundaries; `b23ccb4` →
adapter-contract; test-only commits `7dd69a8`/`5813349` owe no doc). W2's
behavior commits pair same-commit too: `8543164` (`publishing_demo.py` +
tests) → README ×2 + interventions + verification; `d0c09fa`
(`verify_install.py` + tests) → verification + README ×2 (the installer has
no map row; its evidence contract is `docs/verification.md`). No worker
touched AGENTS.md (zero new rows) or `docs/roadmap.md` (0 bits changed —
the 0.3 close-out sentence, E14 status and any ledger flip are master-owned
close acts, MD-4). Truth docs re-read this run and current:
`runtime-boundaries.md` compensation-boundary section headed
"(S10/S14 — expense and publishing families, active-cancellation window)"
with the `content.unpublish` pairing; `adapter-contract.md` FakePublisher
contract/store/retraction sections incl. the RF4 note at `:369-374`;
`interventions.md` S10/S14 compensation-exception paragraph naming the
chapter; `verification.md` S14 coverage sections (W1 core `:239`, W2 demo
`:268`) and the demo/installer sentences (`:59-61`); both READMEs' chapter,
limits and milestone passages (en+zh).

**No unpaid drift on any row this sprint triggered.**
