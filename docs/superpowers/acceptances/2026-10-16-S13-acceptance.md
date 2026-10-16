# Acceptance record — sprint S13, 2026-10-16

Independent Orca final acceptance of the assembled S13 published-card
withdrawal release. Baseline asserted exact before anything ran: carrier
`WayJ/sprint-s13-sop-withdrawal` at
`da9d2def14ecd0bdbb55971acdc88cc141cb839a` (worktree clean), W2 accepted demo
source `WayJ/s13-withdrawal-demo-2` at
`52cc9166de837dcac194e9f35f096950a5c2b225` (`git rev-parse` verified equal
to the branch tip, exactly **4 commits** `f50b05d..52cc916` on `da9d2de`,
merge-base `da9d2de`, worktree clean; the `-2` suffix is the real W2 branch —
the plain-named predecessor was a failed-start residual, removed), control
`WayJ/s13-release-control` at `da9d2de` (clean). Assembly performed by this
review as an ordinary `--no-ff` merge of `52cc916` onto `da9d2de` in the
acceptance worktree branch `WayJ/s13-final-accept`: merge commit
`ce6ecde10340828a6160c360906c1b1e3be6b3fd` (no conflict — 10 files,
+1277/−153, all W2-owned), tree clean after. **Before any scenario ran**,
both the carrier `WayJ/sprint-s13-sop-withdrawal` and the control
`WayJ/s13-release-control` were fast-forwarded `da9d2de → ce6ecde`
(`--ff-only`, no force anywhere; both asserted clean first); `git rev-parse`
of carrier, control and the acceptance HEAD all equal `ce6ecde`, and the
carrier tree hash equals this checkout's (`5ecc69b3f4f867f611bb9bc5de806bb0c3d023bf`)
— every scenario below ran fresh in this actual assembled carrier tree, not
a tmp or stale tree. No main merge, no push, no force, no extra agents. Base
main `860571c5c89b7dd22dc2be2567d7870c9b093f66` (S12 close; the roadmap 0.4
wording update incl. withdrawal shipped, E13 status, ledger flip, closing
note and teardown are master-owned close acts, and the integration-owned
ordinary main merge/non-force push is the next master dispatch after this
pass). Python 3.9.6 (system `python3`); zero runtime dependencies
(re-verified by the fresh venv install: only `governed-work-runtime`
`0.1.0a1` plus venv tooling, no third-party packages). Review inputs read in
full: AGENTS.md (incl. the supervibe gates and the `doc_sync_map` whose
existing `publication.py`/`publication_demo.py` → `docs/sop-authoring.md`
rows cover the withdrawal surface per D78), the ratified design spec with
**MASTER D67–D79** incl. the D74 amended rejected-receipt refusal channel
([§1–§14 + ratification](../specs/2026-10-16-sop-publication-withdrawal-design.md)),
the [E13 roadmap](../roadmaps/2026-10-16-sop-publication-withdrawal.md), the
active [S13 sprint plan](../sprints/2026-10-16-S13-plan.md), the [W1 core
report](../../../.agents/notes/2026-10-16-S13-core-report.md), the [W1 core
integration review](../../../.agents/notes/2026-10-16-S13-core-integration-review.md)
(stable W2 API, mi-1/mi-2) and the [W2 demo
report](../../../.agents/notes/2026-10-16-S13-demo-report.md). This acceptor
made **no product fix**; every check ran against the assembled tree as
committed.

## Verdict

**pass** — all four scenarios green on fresh runs in the actual assembled
carrier tree (`ce6ecde`, carrier and control verified at that SHA before the
runs), backed by an independent public-API probe (**95/95 PASS**, exit 0:
22 adapter-surface, 18 loader-matrix, 55 governed-flow checks on real
Runtime + SQLite + directories) and a fresh independent RED replay of the W2
module on the parent tree; every DoD item checked with evidence; the
doc-drift audit over the dispatch range `da9d2de..ce6ecde` (with the W1
context `b445fc1..da9d2de` and the full sprint range
`860571c..ce6ecde` re-verified) shows every triggered `doc_sync_map` row
paid with same-commit pairing (`publication.py` ×4 W1 commits,
`publication_demo.py` ×1 W2 commit → `docs/sop-authoring.md`) and the mapped
doc's content current — no unpaid drift on any triggered row; the five
untouched rows owe nothing. This record and the sprint-doc state flip are
written in one same-commit act and precede the integration-owned ordinary
main merge/non-force push; final remote equality and exact-SHA CI are the
close act's items per the S7–S12 precedent.

## Scenario Results

| id | command | expected | actual | pass |
|---|---|---|---|---|
| S1 | `python3 -m unittest tests.test_publication_withdrawal -v`; independent probe `/tmp/s13-accept-probe/probe.py` part A (public API only, disposable stores) | Second hash-named artifact under the digest withdrawal key; publication bytes unchanged; idempotent replay; same-key-changed-digest bounded refusal; exactly-one-record census | Module **`Ran 47 tests … OK`**: `WithdrawalKeyTests` 5/5 (exact `"sop-withdrawn:"`+64-hex digest form; delimiter-hostile `("collide:one","v1")` vs `("collide","one:v1")` distinct; ≠ publication key; malformed identity bounded `ValueError`); `WithdrawalRequestTests` 2/2 (exact closed four-field shape; no free text); `SopWithdrawalStoreTests` 7/7 (`test_execute_commits_exactly_one_second_record_artifact` — census exactly the two hash names, zero `.stage`, raw record pins key/document/digest/receipt; `test_replay_returns_the_identical_receipt` incl. a restarted store; `test_same_key_changed_record_is_refused_without_overwrite` — wrapper rejected bounded + raw `ValueError`, winner unchanged; absent-target and digest-mismatch rejected receipts, deterministic on replay; `lookup` delegates). Probe part A **22/22**: withdrawal accepted → census exactly `[sha256(pub-key), sha256(withdrawal-key)].json`; publication artifact **bytes byte-identical** before/after; replay receipt identical, census still two; changed-digest under the occupied key → wrapper `rejected`/`TARGET_DIGEST_MISMATCH` **and** raw `FilePublisher` `ValueError` (`idempotency key …` message, single line) with winner bytes and census unchanged; ghost target → `rejected`/`TARGET_PUBLICATION_ABSENT` with `SOP-WITHDRAWAL-REFUSED-…` external id, deterministic, **zero commits** | yes |
| S2 | same module (`LoaderWithdrawalTests`); probe part B | Valid/absent/withdrawn/invalid-record/pin matrix; distinct bounded errors; withdrawn ≠ absent; fail-closed everywhere; `withdrawal_record()` audit read; no override | `LoaderWithdrawalTests` 12/12: `test_after_withdrawal_the_loader_raises_the_exact_withdrawn_error`; `test_pinned_card_raises_withdrawn_before_any_pin_judgment` (correct and wrong pins alike); corrupt bytes, tampered stale-digest record and foreign record each map onto `WITHDRAWAL_RECORD_INVALID_MESSAGE`; digest-mismatched record invalid, never silently served; absent artifact reads absent even with a record standing; missing directory never created; `withdrawal_record()` returns the stored record; loaders accept no override keyword; `published_card_matches` stays pure and refuses records. Probe part B **18/18**: exact `WITHDRAWN_MESSAGE` (“this published version is withdrawn; corrected content requires a new version”) observed **pairwise distinct** from `ABSENT_MESSAGE` and from the invalid-record error; corrupt record bytes **never rewritten**; foreign-identity record, stale-digest record (audit read still exposes it), absent-artifact precedence, missing-directory never created, `TypeError` on `allow_withdrawn=True` for `load_published_card` | yes |
| S3 | same module (`GovernedWithdrawalFlowTests`, `RevocationCompositionTests`); probe part C (real Runtime + SQLite + directory) | W02/W03 discrimination both directions; tamper/wrong-digest/wrong-version zero-intake-write refusals; dispatch commits the record; response loss one-attempt reconcile; D66 order; cross-approval isolation; wrong-adapter hold; completion-gate regression; refused withdrawal `confirmed_failed` cancellable, `NO_AUTHORITATIVE_RESULT` unreachable | `GovernedWithdrawalFlowTests` 19/19 green, one named test per beat (malformed request bounded unpersisted; request digest canonical; `revise_document` refuses the id-less shape; proposal blocked pending W02; `card_approval` never satisfies W02; tampered approval `EVIDENCE_AUTHENTICATION_FAILED` with six-table equality; wrong source `AUTHORITY_DENIED`; wrong digest verifies-but-pending; wrong version `invalid`; valid approval → business key = withdrawal key; capability×shape both directions `CAPABILITY_UNSUPPORTED`; `card_withdrawal` never satisfies S02; wrong adapter holds then redispatch succeeds; full story with response loss + one-attempt reconcile + `sop-store` accepted proof `event_id` = operation id + completion succeeded + loader withdrawn; absent target and digest mismatch `confirmed_failed` + cancellable; second withdrawal conflicts only after its own approval; re-publication conflicts census unchanged; publication works complete unchanged). `RevocationCompositionTests` 2/2 (D79). Probe part C **55/55** on one continuous real-Runtime story: governed publication of v1 (business key = publication key, completes `closed/succeeded`), withdrawal work blocked W02 with census unchanged, tampered approval zero intake writes (six-table counts identical), both isolation directions (evidence `invalid` + requirement still pending), wrong-adapter dispatch `held`/`ADAPTER_ACTION_UNSUPPORTED` with zero attempts and zero store writes, correct dispatch `confirmed_succeeded` → census two, publication bytes unchanged, loader withdrawn, audit record exact, accepted proof `sop-store`/`event_id` = operation id/`verified`, completion succeeded; D66 order for a second withdrawal (blocked first, `OPERATION_CONTENT_CONFLICT` only after own approval); re-publication of the withdrawn version refused with **zero store writes** (census and publication bytes unchanged); v2 publication completes unchanged in the same family; response loss after commit → restart reconcile `confirmed_succeeded`, **one attempt**, census stable, v2 loader withdrawn; refused ghost withdrawal resolves `confirmed_failed` **directly** with `SOP-WITHDRAWAL-REFUSED-TARGET_PUBLICATION_ABSENT-…` external id, work `needs_attention`, completion refuses `REQUIREMENT_UNSATISFIED` (never `OUTCOME_UNRESOLVED`), a fresh-runtime `reconcile` re-reads the settled operation and **stays `confirmed_failed`** (the `NO_AUTHORITATIVE_RESULT` stranding outcome is unreachable on this channel), `request_cancel` + `finalize_cancel` close `closed/cancelled` with census unchanged | yes |
| S4 | `python3 -m unittest tests.test_publication_withdrawal_rotation -v`; `python3 -m work_runtime publication-demo --directory /tmp/s13-accept-demo/run`; console `work-runtime publication-demo` outside the checkout via a fresh venv; both printed inspect commands re-run verbatim (module and console); `python3 scripts/verify_install.py` serial; the five AGENTS gates verbatim; eight demos; `python3 -m unittest discover -s examples/rehearsal`; full suite `python3 -m unittest discover -s tests -v`; doc-sync audit | Rotation battery on S11 semantics incl. retired-key withdrawal refusal and six-table AND artifact-byte invariance; demo chapter module+console outside checkout without secrets; `verify_install` serial zero SKIPPED; five gates verbatim; eight demos exit 0; rehearsals 15 OK 1 pre-existing skip; full suite 1015 OK skipped=3 exact names; no new global gate; independent accept before push | Rotation **`Ran 6 tests … OK`**: retired `EVIDENCE_KEY_RETIRED` and dropped `EVIDENCE_AUTHENTICATION_FAILED` refusals with zero writes; same `command_id` re-sign replays the original receipt verbatim; new `command_id` reports current status; `test_rotation_untouches_completed_withdrawal_history` (six tables and both artifact byte dumps identical after a completed withdrawal); pre-rotation approval still verifies and completes. Module demo **exit 0** with the withdrawal chapter (beats 14–20) and closing counts `1 published card version; withdrawal records: 1; committed artifacts: 2; doctored same-version conflicts: 1 (after its own approval); re-publication of the withdrawn version refused: 1 (zero store writes); loader fail-closed refusals: 3; retired-key refusals: 2 (zero writes); history rewritten: 0`, asserted inside the demo against the real SQLite and artifact census; printed inspect commands (`pub-1`, `wd-1`) re-run **verbatim, exit 0**, both `closed/succeeded` with `confirmed_succeeded` operations. Console: fresh venv installed the checkout (**zero third-party packages**; only routine pip 21.2.4 deprecation/upgrade notices) and `work-runtime publication-demo` from `/tmp` **exit 0** with the same narrative and the **same deterministic artifact hash names** (`334096d0…f9897.json` publication, `6f5bde58…d414.json` withdrawal record); both console-printed inspect commands re-run verbatim (venv `python3`, outside the checkout): **exit 0**, `pub-1`/`wd-1` `closed/succeeded`. Installed verifier **serial, nothing else running**: **`=== PASS ===`, exit 0, zero `SKIPPED` lines**; the existing publication stage (module AND console, outside the checkout) now independently re-verifies the chapter — “recomputed bare-card artifact digest and digest-based publication key, the closed withdrawal record binding the published digest, two confirmed operations with runtime-written accepted proofs, both D66 conflict receipts, distinguishable loader failures incl. the withdrawn error” — no new stage, no new gate. Five gates verbatim: contracts `checked 109 markdown files, 534 local links, 0 broken` (the committed-tree count; `.agents/` excluded by `check_docs.py`); tests **`Ran 1015 tests in 52.848s / OK (skipped=3)`**; `demo` exit 0; `compileall -q work_runtime tests scripts` clean; site `checked 2 pages, 0 findings`. **Eight demos exit 0**: `demo`, `publish-demo`, `intervention-demo`, `adoption-demo`, `revocation-demo`, `compensation-demo`, `rotation-demo`, `publication-demo`. Rehearsals **`Ran 15 tests … OK (skipped=1)`** (pre-existing generic opt-in conformance skip). Full-suite skips, exact names: 2× `test_opted_in_action_context_replay_returns_identical_receipt` (`test_file_adapter.FilePublisherConformanceTests`, `test_publishing.FakePublisherConformanceTests`, reason `'adapter does not opt into action/link execution context'`) and `test_absent_backend_is_a_bounded_startup_error` (`test_ui_cli.AbsentBackendTests`, reason `'backend assembled: absent-install path unreachable'`) — all three pre-existing, identical to the S12 record. No secrets printed (only key ids `sop-owner-2026-08`/`sop-owner-2026-10`, 16-hex ids and public content digests; probe keys synthetic `secrets.token_bytes(32)`, never printed). Gate list unchanged — no new global gate (D77). Doc-sync audit below | yes |

## Independent probe and RED replay (fresh this run)

- **Probe** `/tmp/s13-accept-probe/probe.py` — public API only (no test
  helpers imported), disposable `/tmp` stores, synthetic ephemeral keys:
  **95/95 PASS, exit 0** (part A 22, part B 18, part C 55; first-run probe
  expectation errors corrected and disclosed in the obstacles log below —
  product unchanged).
- **W2 RED replay**: `git archive da9d2de` extraction + committed
  `tests/test_publication_withdrawal_demo.py` → `python3 -m unittest
  tests.test_publication_withdrawal_demo` → `FAILED (errors=1)` —
  `ImportError: cannot import name 'REPUBLICATION_WORK_ID' from
  'work_runtime.publication_demo'` (exit 1; the W2 report's RED 1). GREEN is
  the assembled-tree evidence above (the 18 demo-wave tests inside the
  1015-run plus the demo/installer runs).
- The W1 per-task RED granularity was independently replayed by the [W1 core
  integration review](../../../.agents/notes/2026-10-16-S13-core-integration-review.md)
  on the same core SHAs this release carries (`2d29c15` merged via `b2380bd`).

## DoD Checklist

- [x] Withdrawing a published version commits exactly one second hash-named record artifact in the same directory under the digest-based withdrawal key; publication artifacts stay byte-identical; replay is idempotent; same-key-changed-digest is refused bounded — S1: `test_execute_commits_exactly_one_second_record_artifact`, `test_replay_returns_the_identical_receipt`, `test_same_key_changed_record_is_refused_without_overwrite` green; probe A3/A4/A5 observed the second hash name `sha256(withdrawal_key)`, byte-identical publication artifact, identical replay receipt across a restarted store, and both refusal channels (wrapper `rejected` + raw bounded `ValueError`) with winner bytes and census unchanged
- [x] The loader fails closed with distinct bounded errors for withdrawn vs absent vs invalid record; `pinned_card` and `published_card_matches` respect withdrawal; `withdrawal_record()` exposes the audit record; no override exists — S2: `LoaderWithdrawalTests` 12/12 + probe B (exact three-way-distinct messages observed verbatim; `pinned_card` raises withdrawn before any pin judgment for correct and wrong pins; `published_card_matches` refuses records; `TypeError` on any override keyword; absent-artifact precedence; missing directory never created)
- [x] The governed flow (W02/W03 shape discrimination, `sop.withdraw` grants, signed `{digest, policy_version}` withdrawal approval, D66 order) runs through the real Runtime with cross-approval isolation and the completion gate for publication works unchanged; a refused withdrawal (absent target / digest mismatch) resolves `confirmed_failed` and the work stays cancellable — S3: `GovernedWithdrawalFlowTests` 19/19 + probe C on a real Runtime/SQLite/directory (tampered approval zero intake writes six-table-verified; both isolation directions; D66 order for second withdrawal works; wrong-adapter hold; publication works complete unchanged twice; ghost and digest-mismatch refusals resolve `confirmed_failed` directly, completion refuses `REQUIREMENT_UNSATISFIED`, reconcile stays `confirmed_failed`, cancel+finalize closes `cancelled`)
- [x] Re-publication of a withdrawn version is refused by the governed proposal's target checks with zero store writes; there is no un-withdrawal; S8 `revoke_evidence` composes on the sop-publish family with artifacts untouched, pinned by tests — S3/S4: `test_republication_of_a_withdrawn_version_conflicts_census_unchanged` + probe C11 (blocked first, `OPERATION_CONTENT_CONFLICT` only after its own approval, census and publication bytes unchanged) + demo beat 19; no un-withdrawal surface anywhere (grep over `work_runtime/`+`scripts/`: zero hits for `allow_withdrawn`/`reinstate`/`un_withdraw`/`unwithdraw`; the only `"withdrawn"` kind is the pre-existing S10 compensation proof, `runtime.py:942-961`, and `runtime.py` is byte-identical over the whole sprint range); `RevocationCompositionTests` 2/2 (D79: admin revokes `card_approval` and the runtime-written `accepted` proof on the closed work, completion byte-identical, artifacts untouched; revoking publication proofs never touches the withdrawal and vice versa)
- [x] Approver-keyring rotation interacts exactly as S11 pinned (retired/dropped codes, verbatim cached receipts, current-status resend); six-table and artifact-byte preservation hold — S4: `WithdrawalRotationTests` 6/6 incl. `test_rotation_untouches_completed_withdrawal_history`; demo beat 20 shows the retired-key `card_withdrawal` refusal with six tables, the publication artifact and the withdrawal record all untouched
- [x] The withdrawal demo chapter proves the story with installed module+console trials outside the checkout without printing secrets; full tests, the five configured gates, the demo set, rehearsals and serial installed verification pass with exact counts/skips — S4: module and fresh-venv console demos both exit 0 outside the checkout (zero third-party deps, identical deterministic artifact hash names), both printed inspect command pairs re-run verbatim (exit 0, `closed/succeeded`), serial `verify_install.py` `=== PASS ===` with **zero SKIPPED** and the extended independent publication/withdrawal proof; gates verbatim 109/534/0 · 1015 OK (skipped=3, exact names above) · demo 0 · compileall clean · site 2 pages/0 findings; eight demos exit 0; rehearsals 15 OK (skipped=1, pre-existing)
- [x] Independent acceptance precedes integration-owned ordinary main merge/non-force push with same-commit doc pairing and honest limits (no un-withdrawal, no distributed revocation, config-rollback key revival) — this record + the sprint `state: acceptance` flip are one same-commit act written before any merge (no main merge, no push performed by this review; main still `860571c`); same-commit doc pairing audited per-commit over the whole release range (below); the honest limits are stated in the mapped docs (sop-authoring.md withdrawal sections incl. no un-withdrawal/forward-only correction, rollback limits and shared-directory discipline; README/README.zh-CN withdrawal passages name *un-withdrawal* as the not-implemented item with trusted-local-principles and config-only-truth limits); final remote equality and exact-SHA CI are the close act's items, recorded at push time per the S7–S12 precedent

## Obstacles (verbatim)

- 2026-10-16 — first `publication-demo` invocation passed a `--directory`
  that did not itself exist (`mkdir -p /tmp/s13-accept-demo` then
  `python3 -m work_runtime publication-demo --directory /tmp/s13-accept-demo/run`)
  → `FileNotFoundError: [Errno 2] No such file or directory:
  '/tmp/s13-accept-demo/run/governed-publication-w4wfhnkc'` (traceback
  through `publication_demo.py:169 tempfile.mkdtemp`). Notes searched first
  by keyword (`mkdtemp`/`FileNotFoundError` over `.agents/notes/`): the
  hits found were unrelated (the S1 scaffold `FileNotFoundError`; the S11
  report mentions `mkdtemp` only in passing); the canonical prior
  workaround is the [S12 acceptance record](2026-10-15-S12-acceptance.md)
  obstacles log — the identical failure with the identical `mkdtemp(dir=…)`
  contract at `publication_demo.py:169`/`rotation_demo.py:76` (an existing
  directory is every demo's contract). Improvised workaround: `mkdir -p`
  the exact `--directory`, re-run → exit 0. No product issue; no
  substitution (the re-run is the specified module command).
- 2026-10-16 — my independent probe's first run FAILED 4 checks and crashed
  (logged, not silent): (a) the `evidence_status` helper returned the
  **first** evidence of a kind where the story records several, so it read
  pub-0's valid `card_approval` instead of wd-1's invalidated one and
  pub-1's invalidated `card_withdrawal` instead of wd-1's verified one;
  (b) the accepted-proof check asserted exactly one `accepted` proof where
  the story legitimately produces two (pub-0's publication proof plus wd-1's
  withdrawal proof) — corrected to locate the withdrawal operation's proof
  by `event_id`; (c) I proposed pub-1's v2 publication without recording its
  `card_approval`, correctly refused `REQUIREMENT_UNSATISFIED` (a probe
  story bug, product behavior correct); (d) stored evidence bodies carry no
  top-level `work_id` (`KeyError`) — adopted last-match-per-kind semantics,
  the same dict-comprehension semantics the owner's tests use. After the
  fixes: **95/95 PASS, exit 0**. Product unchanged. The same first
  invocation also captured `$?` after a `| tail` pipe (zsh `PIPESTATUS`
  vs bash) so the reported exit was wrong once; all later runs redirect to a
  log file and read the real exit code — the S12 record's `tee` pitfall,
  repeated and corrected here.
- 2026-10-16 — cosmetic only: the fresh-venv `pip install` of the checkout
  emitted pip 21.2.4 deprecation/upgrade notices (`DEPRECATION: A future
  pip version will change local packages…`, `WARNING: You are using pip
  version 21.2.4…`); install succeeded, zero third-party packages, console
  demo exit 0. Not a blocker (same notices as S12).
- No other blocker, failure or substitution occurred. No evidence item in
  this record is substituted: every scenario ran its specified proving
  command for real on the assembled carrier tree.

## Doc-Drift Audit

Ranges audited: the dispatch-named W2 wave `da9d2de..ce6ecde` (the
assembly), the W1 context `b445fc1..da9d2de` (re-verified quickly per the
dispatch), and the full sprint range `860571c..ce6ecde` (merge-base with
main; subsumes design/ratification, W1 and W2). Per-commit pairing was
checked with `git diff-tree --no-commit-id --name-only -r <sha>` on every
commit of both waves.

| map row (change, owes) | matched this sprint | doc state | detail |
|---|---|---|---|
| work_runtime/publication.py → docs/sop-authoring.md | **yes** — W1 commits `69f4666`, `be75a2f`, `6a31eec`, `ab8235d` (the only `publication.py` commits in `860571c..ce6ecde`); untouched in `da9d2de..ce6ecde` | current; same-commit pairing **re-verified** | Each of the four commits whose diff touches `work_runtime/publication.py` also touches `docs/sop-authoring.md` in the same commit (diff-tree shown per commit); doc re-read this run: full withdrawal sections (store record surface D67–D69, `SopWithdrawalStore` D74, loading-after-withdrawal fail-closed D72 with `pinned_card`/`published_card_matches`/audit-read/no-override notes, governed flow, rotation, honest limits) |
| work_runtime/publication_demo.py → docs/sop-authoring.md | **yes** — W2 commit `3946f38` (the only commit touching the module) | current; same-commit pairing **re-verified** | `3946f38`'s diff-tree contains both `work_runtime/publication_demo.py` and `docs/sop-authoring.md` (plus `docs/verification.md`, `scripts/verify_install.py`, the two demo test files); the Demonstration section (line 413) carries the withdrawal chapter narrative and both inspect commands (`pub-1`, `wd-1`); `cli.py` needed no change (existing subcommand) |
| work_runtime/file_adapter.py → docs/file-adapter.md | no — unchanged `860571c..ce6ecde` (not in the changed-path list) | n/a | row owes nothing this sprint, exactly as dispatched |
| work_runtime/ingress.py → docs/signed-evidence.md | no — unchanged over the full sprint range | n/a | row owes nothing |
| work_runtime/runtime.py → docs/runtime-boundaries.md | no — byte-identical `860571c..ce6ecde` (explicit diff empty) | n/a | row owes nothing; the only "withdraw" mentions in runtime.py are the pre-existing S10 compensation vocabulary (`runtime.py:720,942-961` and the D45 disposition comment at 522) — no S13 Runtime wiring |
| work_runtime/adapters.py → docs/runtime-boundaries.md | no — unchanged over the full sprint range | n/a | row owes nothing |
| scripts/check_docs.py → CONTRIBUTING.md | no — unchanged over the full sprint range | n/a | row owes nothing |
| scripts/check_site.py → docs/website.md | no — unchanged over the full sprint range | n/a | row owes nothing |

Beyond the map (recorded, not enforced): every test-adding commit of both
waves pairs with `docs/verification.md` (`69f4666`, `be75a2f`, `6a31eec`,
`6787872`, `2a26d38`, `3946f38` — diff-tree verified; `ab8235d` strengthened
an existing assertion and its clarifying verification phrase rode with the
W1 report commit `2d29c15` exactly as the owner disclosed); no
`doc_sync_map` row covers `scripts/verify_install.py` (changed by
`3946f38`; the installer's own evidence contract is in
`docs/verification.md`, updated same-commit); the bilingual README
withdrawal passages rode with `35b4cf3`; no worker touched AGENTS.md (zero
new rows, D78 as ratified). `docs/roadmap.md` 0.4 wording, E13 status and
any ledger flip are master-owned close acts and are correctly absent from
this acceptance.

**No unpaid drift on any row this sprint triggered.**
