# Acceptance record — sprint S12, 2026-10-15

Independent Orca final acceptance of the assembled S12 governed SOP rule-card
publication release. Baseline asserted exact before anything ran: carrier
`WayJ/sprint-s12-sop-publication` at
`05264d4b21520493aaf3f0b992cd2f2e0ac08854` (worktree clean), W2 accepted demo
source `WayJ/s12-publication-demo` at
`129d477500f17e72b90a7d42087ba3357f3146e5` (`git rev-parse` verified equal to
the branch tip, exactly **4 commits** `a2b8f5e..129d477` on `05264d4`,
merge-base `05264d4`, worktree clean), control `WayJ/s12-release-control` at
`05264d4` (clean). Assembly performed by this review as an ordinary `--no-ff`
merge of `129d477` onto `05264d4` in the acceptance worktree branch
`WayJ/s12-final-accept`: merge commit
`1eddbeaaa683be23e8f9455ce50c28f8587e0bb4` (no conflict, by construction —
10 files, +1791/−19, all W2-owned), tree clean after. **Before any scenario
ran**, both the carrier `WayJ/sprint-s12-sop-publication` and the control
`WayJ/s12-release-control` were fast-forwarded `05264d4 → 1eddbea`
(`--ff-only`, no force anywhere); `git rev-parse` of carrier, control and the
acceptance HEAD all equal `1eddbea`, and the carrier tree hash equals this
checkout's (`8edbe180c1370f7481675b5837218f974f0ea275`) — every scenario below
ran fresh in this actual assembled carrier tree, not a tmp or stale tree. No
main merge, no push, no force, no extra agents. Base main
`56a7f2eaa35693d77bd60bdadf799a0ff9097973` (S11 close; the roadmap 0.4 note,
E12 status, ledger flip, closing note and teardown are master-owned close
acts, and the integration-owned ordinary main merge/non-force push is the next
master dispatch after this pass). Python 3.9.6 (system `python3`); zero
runtime dependencies (re-verified by fresh venv install: the venv holds only
`governed-work-runtime` `0.1.0a1`, no third-party packages); runtime store
schema stays `1`. Review inputs read in full: AGENTS.md (incl. the supervibe
gates and the ratification-added `doc_sync_map` publication rows), the
ratified design spec with **MASTER D54–D66** incl. the IR-F1 amended digest
key and the IR-F2 §8 re-frame
([§1–§14 + ratification](../specs/2026-10-15-sop-publication-design.md)), the
[E12 roadmap](../roadmaps/2026-10-15-sop-publication.md), the active
[S12 sprint plan](../sprints/2026-10-15-S12-plan.md), the [W1 core
report](../../../.agents/notes/2026-10-15-S12-core-report.md), the [W1 core
integration review](../../../.agents/notes/2026-10-15-S12-core-integration-review.md)
(W2 stable API, mi-1…mi-3) and the [W2 demo
report](../../../.agents/notes/2026-10-15-S12-demo-report.md) (incl. the
master-authorized `inspect --policy sop-publish` addition and its motivating
probe). This acceptor made **no product fix**; every check ran against the
assembled tree as committed.

## Verdict

**pass** — all four scenarios green on fresh runs in the actual assembled
carrier tree (`1eddbea`, carrier and control verified at that SHA before the
runs), backed by an independent adapter-level probe (16/16) and independent
RED replays of both waves on their parent trees; every DoD item checked with
evidence; the doc-drift audit over the full sprint range `56a7f2e..1eddbea`
(and per-wave `24dd14c..05264d4`, `05264d4..1eddbea`) shows every triggered
`doc_sync_map` row paid with same-commit pairing (`publication.py` ×3,
`publication_demo.py` ×1 → `docs/sop-authoring.md`; `file_adapter.py` ×1 →
`docs/file-adapter.md`) and the mapped docs' content current — no unpaid drift
on any triggered row; the five untouched rows owe nothing. This record and the
sprint-doc state flip are written in one same-commit act and precede the
integration-owned ordinary main merge/non-force push; final remote equality
and exact-SHA CI are the close act's items per the S7–S11 precedent.

## Scenario Results

| id | command | expected | actual | pass |
|---|---|---|---|---|
| S1 | `python3 -m unittest tests.test_publication -v`; `python3 -m unittest tests.test_file_adapter -v`; independent adapter probe `/tmp/s12-accept-probe/probe_s1.py` (public API only, disposable store) | Digest-key uniqueness incl. delimiter-hostile ids, verbatim replay, same-key-changed-content bounded `ValueError`, `read_validated` None-on-absent/corrupt-bounded; exactly one hash-named artifact per (id, version); corrupt vs absent distinguishable | Module **`Ran 33 tests … OK`**: `PublicationKeyTests` 4/4 (exact digest key for the packaged card; `test_delimiter_hostile_ids_do_not_collide` — the IR-P16 pair `("collide:one","v1")` vs `("collide","one:v1")` stays distinct; identity changes change the key; malformed identity bounded `ValueError`); `SopPublicationStoreTests` 5/5 (contract declares `sop.publish` + keyed uniqueness; execute commits exactly one hash-named artifact; `test_replay_returns_the_identical_receipt`; `test_same_key_changed_content_refused_without_overwrite`; lookup delegates); `LoaderPinTests` 11/11; `GovernedFlowTests` 13/13. File-adapter module **`Ran 57 tests … OK (skipped=1)`** (the pre-existing opt-in conformance skip) incl. `ReadValidatedTests` 6/6: None-on-absent, full validated artifact on hit, fresh-instance stability, key gate without files, corrupt bytes bounded and **never rewritten**, tampered-document-with-stale-digest refusal. My probe **16/16 PASS, exit 0**: hostile pair both lint-clean → distinct `sop-pub:`+64-hex keys, distinct `sha256(key)` file names, both published (exactly two `.json`, zero `.stage`), receipt digest == `sop_digest`, verbatim replay, changed lint-clean content under the same key → bounded `ValueError` `idempotency key is already committed with different content` with winner bytes unchanged and still two artifacts; `read_validated` full artifact / None on absent; garbage bytes → bounded `ValueError` `committed artifact is not valid UTF-8 JSON`, bytes never rewritten; loader corrupt vs absent messages differ (`no published card is committed for this policy version` on absent) | yes |
| S2 | `python3 -m unittest tests.test_publication -v` (GovernedFlowTests, real Runtime + SQLite + directory); `python3 -m work_runtime publication-demo --directory <fresh>` | Full RFC-002 §6 story: dirty bounded unpersisted; blocked proposal; tampered approval `EVIDENCE_AUTHENTICATION_FAILED` zero intake writes; valid approval; dispatch ONE artifact; response loss → one-attempt reconcile; accepted proof runtime-written, `event_id` = operation id; completion; doctored same-version ⇒ persisted `OPERATION_CONTENT_CONFLICT` only after its own approval (D66 order), winner bytes unchanged | `GovernedFlowTests` 13/13 green, one named test per beat: `test_dirty_card_is_refused_unpersisted_at_admission`; `test_clean_card_document_digest_equals_sop_digest`; `test_proposal_before_approval_is_blocked_pending_s02`; `test_tampered_approval_rejected_before_any_intake_write`; `test_wrong_version_approval_is_candidate_then_unsatisfied` (+ wrong-digest shape-verified/S02-pending, wrong-source `AUTHORITY_DENIED`); `test_valid_signed_approval_verifies_and_proposal_accepts`; `test_dispatch_response_loss_then_one_attempt_reconcile`; `test_accepted_proof_is_runtime_written_under_the_store_source` (source `sop-store` absent from grants, `event_id` = operation id); `test_completion_closes_the_work_succeeded`; `test_command_replay_returns_the_stored_receipt_verbatim`; **D66 pinned order** by `test_cross_work_same_card_conflicts_only_after_its_own_approval` and `test_doctored_same_version_card_conflicts_after_its_own_approval`. Demo **exit 0** running the identical story on one fresh store: narrative lines 3–11 match beat-for-beat (blocked S02; tampered refusal “six tables unchanged”; dispatch commits exactly ONE hash-named artifact; response lost AFTER commit → restart reconcile of the ORIGINAL key → `confirmed_succeeded`, one attempt, nothing resent; accepted proof under `sop-store`; SUCCEEDED; doctored card `REQUIREMENT_UNSATISFIED` first, then persisted `OPERATION_CONTENT_CONFLICT` after its own approval with winner bytes unchanged, still exactly one `.json`); closing counts `1 published card version; committed artifacts: 1; doctored same-version conflicts: 1 (after its own approval); loader fail-closed refusals: 2; retired-key refusals: 1 (zero writes); history rewritten: 0` | yes |
| S3 | `python3 -m unittest tests.test_publication_rotation -v` | Retained `EVIDENCE_KEY_RETIRED` / dropped `EVIDENCE_AUTHENTICATION_FAILED`; same `command_id` re-sign → original receipt verbatim; new `command_id` → current status; six tables AND artifact bytes preserved | **`Ran 6 tests … OK`**: `test_retired_old_key_refused_with_zero_writes` (retained ring, window closed → `EVIDENCE_KEY_RETIRED`, `table_dump` unchanged); `test_dropped_old_key_refuses_authentication` (dropped → `EVIDENCE_AUTHENTICATION_FAILED`, selector-less and cited forms, dump unchanged); `test_same_command_id_resign_replays_original_receipt_verbatim` (re-sign under the new key, same `command_id` → receipt equal to the original, zero writes); `test_new_command_id_same_event_reports_current_status` (same `(source, event_id)` → same `evidence_id`, current status, exactly `commands +1`, `evidence` unchanged); `test_rotation_untouches_publication_history` — after a **completed** publication (work closed, one dispatched artifact), both denial classes leave the six tables (`works`, `commands`, `evidence`, `operations`, `events`, `metadata` — ordered rowid dumps) and the committed artifact **bytes** untouched; `test_mid_flow_rotation_continues_with_old_and_new_keys`. All secrets synthetic `secrets.token_bytes(32)`, never printed | yes |
| S4 | Loader matrix (S1 module run); `python3 -m work_runtime publication-demo --directory /tmp/s12-accept-demo`; console `work-runtime publication-demo` outside the checkout via a fresh venv; the printed `inspect` command re-run verbatim; `python3 scripts/verify_install.py` serial; the five AGENTS gates verbatim; seven prior demos + `publication-demo`; `python3 -m unittest discover -s examples/rehearsal`; full suite `python3 -m unittest discover -s tests -v`; doc-sync audit | Fail-closed matrix absent/corrupt/tampered distinguishable; installed module+console proof; `verify_install` serial zero SKIPPED; gates verbatim with correct counts; eight demos exit 0; rehearsals 15/1; full suite 944 OK skipped=3 exact names; no secrets printed; no new global gate; independent accept before push | Loader matrix green (S1: `LoaderPinTests` 11/11 — absent version, missing directory never created, corrupt bytes, tampered document/stale digest, doctored `key` field, foreign card and non-card under the key each refuse bounded; `pinned_card` exact pin; `published_card_matches` compares `(id, version, goal)` only). Module demo **exit 0**; console: fresh venv installed the checkout (`governed-work-runtime 0.1.0a1`, **zero third-party packages**; pip emitted only routine deprecation/upgrade notices) and `work-runtime publication-demo` from `/tmp` **exit 0** with the same narrative and the **same deterministic artifact hash name** `334096d0…f9897.json` as the module run. Printed inspect command re-run **verbatim** (`python3 -m work_runtime inspect --db … --work pub-1 --policy sop-publish`): **exit 0**, `work.outcome: "succeeded"`, `status: "closed"`, S02/S03 `satisfied`, full event story `WorkCreated → ContractBound → EvidenceEvaluated → OperationPrepared → AttemptStarted → OutcomeUnknown → OperationResolved(confirmed_succeeded) → WorkCompleted` — the master-authorized `--policy sop-publish` choice verified in real CLI use. Installed verifier **serial, nothing else running**: **`=== PASS ===`, exit 0, zero `SKIPPED` lines**, stages 21/22 run module and console `publication-demo` outside the checkout with independent publication proofs (recomputed bare-card digest and digest-based publication key, one confirmed operation with the runtime-written accepted proof, D66 conflict receipt, distinguishable loader failures). Five gates verbatim: contracts `checked 103 markdown files, 492 local links, 0 broken` (committed tree — `check_docs.py` excludes `idea.md`/`上一次建议.md` and `.agents/`; = 102 post-W1 + the W2 plan doc); tests **`Ran 944 tests in 52.636s / OK (skipped=3)`**; `demo` exit 0; `python3 -m compileall -q work_runtime tests scripts` clean; site `checked 2 pages, 0 findings`. **Eight demos exit 0**: `demo`, `publish-demo`, `intervention-demo`, `adoption-demo`, `revocation-demo`, `compensation-demo`, `rotation-demo`, `publication-demo`. Rehearsals **`Ran 15 tests … OK (skipped=1)`** (pre-existing generic opt-in conformance skip). Full-suite skips, exact names: 2× `test_opted_in_action_context_replay_returns_identical_receipt` (`test_file_adapter.FilePublisherConformanceTests`, `test_publishing.FakePublisherConformanceTests`, reason `'adapter does not opt into action/link execution context'`) and `test_absent_backend_is_a_bounded_startup_error` (`test_ui_cli.AbsentBackendTests`, reason `'backend assembled: absent-install path unreachable'`) — all three pre-existing. No secrets printed (only key ids `sop-owner-2026-08`/`sop-owner-2026-10`, 16-hex ids and public content digests; the planted-marker hygiene tests are green in the suite). Gate list unchanged — `publication-demo` deliberately not a gate (D64), rehearsal set untouched. Doc-sync audit below | yes |

## Independent RED replays (fresh this run, parent trees via `git archive`)

- **W1 RED A**: `git archive 24dd14c` extraction + committed
  `tests/test_publication.py` → `python3 -m unittest tests.test_publication` →
  `FAILED (errors=1)` — `ModuleNotFoundError: No module named
  'work_runtime.publication'` (exit 1; the W1 report Task 2 RED).
- **W1 RED B**: same extraction + committed `tests/test_file_adapter.py` →
  `python3 -m unittest tests.test_file_adapter.ReadValidatedTests` →
  `FAILED (errors=6)` — every case `AttributeError: 'FilePublisher' object
  has no attribute 'read_validated'` (exit 1; the W1 report Task 1 RED).
- **W2 RED**: `git archive 05264d4` extraction + committed
  `tests/test_publication_demo.py` → `python3 -m unittest
  tests.test_publication_demo` → `FAILED (errors=1)` — `ModuleNotFoundError:
  No module named 'work_runtime.publication_demo'` (exit 1; the W2 report
  Task 1 RED).
- GREEN for all three is the assembled-tree evidence above (33/57/25-test
  modules inside the 944-run, plus the demo/installer runs). The W1 per-task
  RED granularity was independently replayed by the
  [W1 core integration review](../../../.agents/notes/2026-10-15-S12-core-integration-review.md)
  on the same core SHAs this release carries (`9baa86d` merged via `1a83725`).

## DoD Checklist

- [x] Lint-clean cards publish through the governed flow with exact digests end-to-end (`sop_digest` == `document_digest` == stored `content_digest`); dirty cards fail bounded and unpersisted at admission — S1/S2: `test_clean_card_document_digest_equals_sop_digest` and `test_dirty_card_is_refused_unpersisted_at_admission` green; the chain observed end-to-end three ways: the demo's pinned digest `56c85d32…be000` equals the inspect `document_digest` and the stored artifact's `content_digest` (installer stage 21 recomputes it independently; my probe A asserts receipt digest == `sop_digest`); dirty demo card → 2 diagnostics, first `EMPTY_VALUE` at `/policy/goal`, zero store writes
- [x] Version-bound signed approvals `{digest, policy_version}` verify through the existing gateway (tampered/wrong-version refused, zero intake writes); approver-key rotation interacts exactly as S11 pinned (retired/dropped codes, verbatim cached receipts, current-status resend) — S2: `test_tampered_approval_rejected_before_any_intake_write` (six-table equality), `test_wrong_version_approval_is_candidate_then_unsatisfied`, wrong-digest shape-verified/S02-pending, valid approval accepted; S3: rotation battery 6/6 with zero-write `table_dump` equality after every denial, verbatim same-`command_id` replay, `commands +1` current-status resend
- [x] The store stays immutable and collision-free: exactly one hash-named artifact per `(policy_id, version)` under the digest-based key; same-version doctored content ⇒ persisted `OPERATION_CONTENT_CONFLICT` after the second work's own approval; response loss after commit recovers the original in one attempt — S1 store tests + probe A (two hostile-id cards → two distinct hash names; changed content refused, winner bytes unchanged; verbatim replay); S2 D66 tests pin the order (`REQUIREMENT_UNSATISFIED` first, conflict only after the second work's own verified approval) with the winner artifact unchanged; `test_dispatch_response_loss_then_one_attempt_reconcile` + demo restart narrative (one attempt, original key, nothing resent)
- [x] The loader fails closed: absent version and corrupt artifact are bounded, distinguishable errors; no Runtime wiring, no card→policy compilation — published cards never execute — S1/S4: `LoaderPinTests` 11/11 and `ReadValidatedTests` 6/6 (absent vs corrupt distinguishable — probe A observed the two distinct messages verbatim; corruption never rewritten); no Runtime wiring re-verified on the assembled tree: `grep` over `work_runtime/` and `scripts/` finds the only importer of `work_runtime.publication` is `cli.py`'s master-authorized `inspect --policy sop-publish` choice (an inspection surface, not the Runtime), `runtime.py`/`policy.py` contain no publication reference and were byte-identical over the whole sprint range; no withdrawal surface exists (D63)
- [x] `publication-demo` proves the whole story with installed module+console trials outside the checkout without printing secrets; full tests, the five configured gates, the existing demo set plus `publication-demo`, rehearsals and serial installed verification pass with exact counts/skips — S4: module and fresh-venv console demos both exit 0 outside the checkout (zero third-party deps), printed inspect command re-run verbatim (exit 0, `outcome: succeeded`), serial `verify_install.py` `=== PASS ===` with **zero SKIPPED** and independent publication-proof stages 21/22; gates verbatim 103/492/0 · 944 OK (skipped=3, exact names above) · demo 0 · compileall clean · site 2 pages/0 findings; eight demos exit 0; rehearsals 15 OK (skipped=1, pre-existing)
- [x] Independent acceptance precedes integration-owned ordinary main merge/non-force push with same-commit doc pairing, honest operator-discipline boundaries (cross-database store sharing, config-only trust, rollback limits) and exact final remote equality/CI — this record + the sprint `state: acceptance` flip are one same-commit act written before any merge (no main merge, no push performed by this review; main still `56a7f2e`); same-commit doc pairing re-verified per-commit over the whole release range (audit below); the operator-discipline boundaries are stated in the mapped docs (sop-authoring.md publication sections incl. foreign-content loader refusal and rollback-is-versioned-forward, README/README.zh-CN eighth-demo sections: trusted-local principals not authentication, config-only trust, no withdrawal this slice, published cards never execute); final remote equality and exact-SHA CI are the close act's items, recorded at push time per the S7–S11 precedent

## Obstacles (verbatim)

- 2026-10-15 — first `publication-demo` invocation passed a `--directory`
  whose parent did not exist
  (`rm -rf /tmp/s12-accept-demo && python3 -m work_runtime publication-demo
  --directory /tmp/s12-accept-demo`) →
  `FileNotFoundError: [Errno 2] No such file or directory:
  '/tmp/s12-accept-demo/governed-publication-3g7ia905'` (traceback through
  `publication_demo.py:149 tempfile.mkdtemp`). Notes searched first (obstacle
  protocol: S12/S11 demo reports, keyword `mkdtemp`/`FileNotFoundError`) — no
  prior hit for this failure; the motivating fact is house-wide:
  `rotation_demo.py:76` and `compensation_demo.py:235` use the identical
  `tempfile.mkdtemp(prefix=…, dir=directory)` form, i.e. an existing parent
  is every demo's contract. Improvised workaround: `mkdir -p` the parent,
  re-run → exit 0. The same first attempt also printed `DEMO-EXIT:0` because
  `$?` after a `| tee` pipe captured `tee`'s status — all later exit codes
  captured without pipe pollution. No product issue; no substitution (the
  re-run is the specified module command).
- 2026-10-15 — my independent probe A initially asserted refusal-message
  substrings I had guessed (`artifact` for the changed-content refusal;
  `corrupt`/`parse`/`decode` for the corruption refusal); both checks FAILED
  while the accompanying behavior checks (exception raised as `ValueError`,
  winner bytes unchanged, never-rewrite) PASSED. Printing the actual messages
  showed both refusals correct and bounded: `idempotency key is already
  committed with different content` and `committed artifact is not valid
  UTF-8 JSON`. Probe-side assertions corrected to the actual message
  semantics; re-run → 16/16 PASS, exit 0. Product unchanged.
- 2026-10-15 — cosmetic only: the fresh-venv `pip install` of the checkout
  emitted pip 21.2.4 deprecation/upgrade notices (`A future pip version will
  change local packages…`, `You are using pip version 21.2.4…`); install
  succeeded, zero third-party packages, console demo exit 0. Not a blocker.
- No other blocker, failure or substitution occurred. No evidence item in
  this record is substituted: every scenario ran its specified proving
  command for real on the assembled carrier tree.

## Doc-Drift Audit

Ranges audited: the dispatch-named W2 wave `05264d4..1eddbea` (the assembly),
the W1 context `24dd14c..05264d4`, and the full sprint range
`56a7f2e..1eddbea` (merge-base with main; subsumes both waves and the
design/ratification assembly). Per-commit pairing was checked with
`git log -- <path>` + `git diff-tree --no-commit-id --name-only -r <sha>` on
every triggering commit.

| map row (change, owes) | matched this sprint | doc state | detail |
|---|---|---|---|
| work_runtime/publication.py → docs/sop-authoring.md | **yes** — W1 commits `e95884d`, `c7dc3d0`, `0ea9a99`; untouched in `05264d4..1eddbea` | current; same-commit pairing **re-verified** | Each of the three commits whose diff touches `work_runtime/publication.py` also touches `docs/sop-authoring.md` in the same commit (diff-tree shown per commit); doc re-read this run: full publication sections (store + keyed uniqueness, governed flow with the D66 pinned order and the IR-F2 card-immutability framing, loader/pin fail-closed incl. foreign content under a publication key, rotation) plus the `publication-demo` demonstration subsection |
| work_runtime/publication_demo.py → docs/sop-authoring.md | **yes** — W2 commit `b21ab0c` (creates the module); file absent in W1 | current; same-commit pairing **re-verified** | `b21ab0c`'s diff-tree contains both `work_runtime/publication_demo.py` and `docs/sop-authoring.md` (plus the narrow `cli.py` wiring and its plan/tests); the module has no other commit; the assembly merge `1eddbea` brings both sides together |
| work_runtime/file_adapter.py → docs/file-adapter.md | **yes** — W1 commit `460bbc8`; untouched in `05264d4..1eddbea` | current; same-commit pairing **re-verified** | `460bbc8`'s diff-tree contains both paths; doc carries the `### read_validated (additive, S12 D61)` section (line 138) |
| work_runtime/ingress.py → docs/signed-evidence.md | no — unchanged `56a7f2e..1eddbea` (no commit touches it) | n/a | row owes nothing this sprint, exactly as dispatched |
| work_runtime/runtime.py → docs/runtime-boundaries.md | no — unchanged both waves (byte-identical `56a7f2e..1eddbea`) | n/a | row owes nothing |
| work_runtime/adapters.py → docs/runtime-boundaries.md | no — unchanged both ranges | n/a | row owes nothing |
| scripts/check_docs.py → CONTRIBUTING.md | no — unchanged both ranges | n/a | row owes nothing |
| scripts/check_site.py → docs/website.md | no — unchanged both ranges | n/a | row owes nothing |

Beyond the map (recorded, not enforced): every test-adding commit of both
waves pairs with `docs/verification.md` (`e95884d`, `c7dc3d0`, `0ea9a99`,
`460bbc8`, `e4242a5` — diff-tree verified); `docs/verification.md` now
carries the IR-F5 correction verbatim (line 76: **57 loader-counted
file-adapter tests — 51 in-file plus the six inherited conformance-mixin
cases**) and the S12 core+demo coverage sections, and the stale RFC-002 §6
“not implemented” phrasing is repaired; the bilingual README demo entries
rode with the demo wave (`129d477`); `AGENTS.md` carries the master-owned
`doc_sync_map` publication rows added at ratification (D65 — the worker never
changed the agreement; the AGENTS.md change sits in the design/ratification
assembly inside the sprint range); `docs/roadmap.md` 0.4 note, E12 status and
any ledger flip are master-owned close acts and are correctly absent from
this acceptance.

**No unpaid drift on any row this sprint triggered.**
