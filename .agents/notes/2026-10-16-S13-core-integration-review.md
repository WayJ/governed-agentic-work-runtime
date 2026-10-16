# S13 W1 core integration review — PASS, assembled — 2026-10-16

Independent Orca review/assembly of the S13 published-card withdrawal
core, distinct from the owner's internal review recorded in
[the core report](2026-10-16-S13-core-report.md). Reviewer checkout:
`s13-release-control` (control branch `WayJ/s13-release-control`, base
`b445fc16b1fb2cca69a192ce4efa4e20b9005a2e` = carrier baseline, clean at
start, before the merge and after assembly). No product file was modified
by this review; every gate, demo, rehearsal, installer run, RED replay
and independent probe ran from `git archive` extractions of the accepted
source `2d29c15` and the baseline `b445fc1` into disposable `/tmp`
directories, plus fresh `/tmp` stores with synthetic ephemeral keys
(secrets generated in-process, never printed). Verdict: **PASS — no
material finding**; two minor observations recorded below (mi-1, mi-2),
neither blocking, neither requiring a product fix. This review proves the
**local S13 W1 core only** — the demo chapter, installer stage, bilingual
README mention, docs demo refresh, final acceptance and the main merge
are W2+ and remain owed.

## Scope and source

- Accepted source: `WayJ/s13-withdrawal-core` tip
  **`2d29c150118d9dad10d81ab1c632811db4f516c2`** (`git rev-parse` verified
  equal to the branch tip), **8 commits** `f05ca62^..2d29c15` inclusive on
  base `b445fc1` — plan `f05ca62`, key/record/wrapper `69f4666`, loader
  `be75a2f`, governed flow `6a31eec`, composition+rotation `6787872`,
  evidence-level isolation pin `2a26d38`, near-miss admission fix
  `ab8235d`, report `2d29c15` — matching the dispatch and the owner's
  commit table exactly (`rev-list --count f05ca62..2d29c15` = 7, plus
  `f05ca62` itself = 8).
- Carrier baseline: `WayJ/sprint-s13-sop-withdrawal`
  `b445fc16b1fb2cca69a192ce4efa4e20b9005a2e`, worktree clean (asserted
  before the fast-forward).
- Changed files: **7** (`git diff --name-status b445fc1..2d29c15`
  verified): `work_runtime/publication.py` (+272/−33),
  `tests/test_publication_withdrawal.py` (new, 956),
  `tests/test_publication_withdrawal_rotation.py` (new, 294),
  `docs/sop-authoring.md`, `docs/verification.md`, the core plan, the core
  report — exactly the core plan's ownership list. **mi-2:** the dispatch
  said "exactly 8 changed files incl. report"; the committed tree has 7.
  The 8 is the commit count; the file set matches the ratified ownership
  scope exactly, so this is a dispatch-text off-by-one, not a scope issue.
- **Protected paths byte-identical** `b445fc1..2d29c15`: the changed-file
  list is exhaustive, and an explicit `git diff` over `file_adapter.py`,
  `runtime.py`, `ingress.py`, `authoring.py`, `policy.py`, `adapters.py`,
  `cli.py`, every demo module, `scripts/verify_install.py`, both READMEs,
  the UI/site assets and `pyproject.toml` is empty. The withdrawal demo
  chapter is correctly absent (verified again at runtime: zero "withdraw"
  lines in `publication-demo` output; W2 owes it).
- **Same-commit doc pairing holds on every `publication.py` commit**
  (D78, zero new doc_sync_map rows, workers never touched AGENTS.md):
  `69f4666`, `be75a2f`, `6a31eec`, `ab8235d` each also touch
  `docs/sop-authoring.md`; every test-adding commit (`69f4666`,
  `be75a2f`, `6a31eec`, `6787872`, `2a26d38`) also touches
  `docs/verification.md`. `ab8235d` strengthened an existing test's
  assertion without a verification touch; the clarifying verification
  phrase rode with the report commit `2d29c15` as the owner disclosed —
  no `doc_sync_map` row covers test files, so no arrears.

## Review against D67–D79 and the RV/R probes

- **D68 (withdrawal key):** `withdrawal_key = "sop-withdrawn:" +
  digest([policy_id, policy_version])` — the D56 form verbatim on the same
  identity basis, prefix-namespace distinct from `"sop-pub:"`, bounded
  identity `ValueError` naming the requirement. Owner pins
  delimiter-hostile non-collision and ≠ publication key; my probe A1
  reproduced the derived business key end-to-end through the governed
  proposal.
- **D69 (closed record, effective immutability):** exactly
  `{discriminator, policy_id, policy_version, published_digest}`,
  discriminator `"sop.withdrawal"`, nonempty strings, no free text;
  `is_withdrawal_request` never raises. The id-less shape's effective
  immutability under `revise_document` is disclosed in
  `docs/sop-authoring.md` twice (request admission + summary) with the S12
  IR-F2 wording, and pinned by the owner's `revise_document` test.
- **D74 (rejected-receipt refusal — the amended channel):**
  `SopWithdrawalStore` wraps an unchanged `FilePublisher` (delegate
  `execute`/`lookup` verbatim; own contract
  `actions=("sop.withdraw",)`, `uniqueness=("withdrawal.key",)`); absent
  target or digest mismatch returns a deterministic
  `{"status": "rejected", …}` receipt whose `digest` binds the operation
  and whose `external_id` embeds the reason
  (`SOP-WITHDRAWAL-REFUSED-TARGET_PUBLICATION_ABSENT-…` /
  `…_TARGET_DIGEST_MISMATCH-…`). **No ValueError refusal channel exists
  anywhere in the wrapper.** Probes A2–A8 proved end-to-end on a real
  Runtime: dispatch resolves `confirmed_failed` directly (never
  `outcome_unknown`), the work lands `needs_attention`, W03 stays pending
  so completion refuses `REQUIREMENT_UNSATISFIED` (not
  `OUTCOME_UNRESOLVED`), `reconcile` re-reads the settled operation and
  stays `confirmed_failed` — the R2 stranding outcome
  (`NO_AUTHORITATIVE_RESULT` with completion AND cancel refusing
  `OUTCOME_UNRESOLVED`) is **unreachable on this channel** — and
  `request_cancel` + `finalize_cancel([])` close the work
  `closed/cancelled` with the census unchanged.
- **D72/RV-F5 (loader):** the withdrawal check sits after the
  stored-identity check and before return; six bounded distinguishable
  classes hold — my probe matrix B1–B17 reproduced every cell on real
  directories: exact `WITHDRAWN_MESSAGE` distinct from absent; corrupt
  record bytes, a foreign identity's record and a stale-digest record all
  map by explicit catch-and-re-raise onto the one
  `WITHDRAWAL_RECORD_INVALID_MESSAGE` (adapter vocabulary never leaked in
  any run); absent-artifact precedence over a standing record; a missing
  directory is never created by `withdrawal_record()` or the loader;
  `pinned_card` raises the withdrawn error before any pin judgment
  (correct and wrong pins alike); `withdrawal_record()` returns the exact
  record post-withdrawal and `None` pre-withdrawal; no override keyword
  is accepted on any read function; `published_card_matches` stays the
  pure structural (id, version, goal) check.
- **D70/D71 (governed flow, both directions):** W02/W03 chosen by
  document shape in one family/database; `card_withdrawal` added to
  `evidence_sources` under `sop-owner` only. Probes C1–C11: a signed
  `card_approval` on a withdrawal work turns `invalid` and W02 stays
  pending; a `card_withdrawal` on a card work turns `invalid` and S02
  stays pending (MD-4 both directions, evidence level); a tampered
  envelope is refused `EVIDENCE_AUTHENTICATION_FAILED` with **zero intake
  writes** (six-table counts identical); a wrong-digest approval verifies
  but leaves W02 pending; a wrong-version candidate turns `invalid`;
  capability × document-shape pairing rejects `sop.publish`-on-withdrawal
  and `sop.withdraw`-on-card with the bounded `CAPABILITY_UNSUPPORTED`
  blocker (never an unpersisted error); a withdrawal intent dispatched
  through `SopPublicationStore` holds `ADAPTER_ACTION_UNSUPPORTED` with
  zero attempts and zero store writes, and re-dispatch through
  `SopWithdrawalStore` commits the record. Near-miss admission (dict with
  a `discriminator` key but wrong shape) raises the bounded
  `WITHDRAWAL_REQUEST_MESSAGE` naming the closed-shape requirement (the
  `ab8235d` review fix, owner-pinned).
- **D75 (D66 order):** requirement blockers before the business-key
  branch, inherited from the unchanged `_propose`; pinned by the owner's
  `test_second_withdrawal_conflicts_only_after_its_own_approval`
  (`REQUIREMENT_UNSATISFIED` first, persisted
  `OPERATION_CONTENT_CONFLICT` only after the second work's own verified
  approval) — code path re-read, unchanged from the F20-verified runtime.
- **D73/D76 (read-surface validity, no un-withdrawal):** re-publication
  of a withdrawn version in the same database is refused by the proposal
  layer (`OPERATION_CONTENT_CONFLICT` after its own approval) with the
  store census unchanged — pinned by the owner's
  `test_republication_of_a_withdrawn_version_conflicts_census_unchanged`;
  no un-withdrawal, reinstatement or override surface exists anywhere in
  the module (grep + API review); no Runtime wiring (the Runtime still
  never reads the store).
- **D79 (S8 composition, pinned):** probes D1–D9 on a real Runtime with
  an admin principal: the owner and the source without `evidence.revoke`
  are denied `AUTHORITY_DENIED`; a `work.intervene` administrator revokes
  the `card_approval` AND the runtime-written `accepted` proof on the
  **closed/succeeded** publication work — completion snapshot
  byte-identical, S02/S03 pending, two `EvidenceRevoked` events, artifact
  bytes unchanged; afterwards a governed withdrawal still commits and the
  loader answers withdrawn — proof revocation never reaches the store and
  the withdrawal record never revokes proofs (no coupling either
  direction).
- **Rotation (S11 semantics):** probes E1–E8 with a real `SourceKey`
  keyring: retired old key → `EVIDENCE_KEY_RETIRED`, dropped old key →
  `EVIDENCE_AUTHENTICATION_FAILED` (selector-less and cited), each with
  all six tables byte-identical (ordered rowid dumps); the same
  `command_id` re-signed under the new current key replays the original
  receipt **verbatim** with zero writes; a new `command_id` on the same
  event reports the candidate's current status under the original
  `evidence_id` with exactly `commands +1`; after a completed withdrawal
  both refusal kinds leave the six tables AND both artifact byte dumps
  identical.

## Fresh battery on the extracted committed tree (`2d29c15`)

- `python3 -m unittest discover -s tests` → **`Ran 997 tests … OK
  (skipped=3)`** (43.4s) = 944 baseline + **53 new**; skip names exact and
  pre-existing (identical on the `b445fc1` extraction, which ran
  `944 … OK (skipped=3)`):
  `test_opted_in_action_context_replay_returns_identical_receipt`
  (`test_file_adapter.FilePublisherConformanceTests`),
  `test_opted_in_action_context_replay_returns_identical_receipt`
  (`test_publishing.FakePublisherConformanceTests`),
  `test_absent_backend_is_a_bounded_startup_error`
  (`test_ui_cli.AbsentBackendTests`).
- Five gates verbatim: `check_docs.py` → `checked 108 markdown files, 532
  local links, 0 broken` (exit 0); full discover (above);
  `python3 -m work_runtime demo` → exit 0; `compileall -q work_runtime
  tests scripts` → clean; `check_site.py` → `checked 2 pages, 0 findings`.
- Demo set exits 0: `demo`, `publish-demo`, `intervention-demo`,
  `adoption-demo`, `revocation-demo`, `compensation-demo`,
  `rotation-demo`, `publication-demo`; withdrawal chapter absent.
- Rehearsals `python3 -m unittest discover -s examples/rehearsal` →
  `Ran 15 tests … OK (skipped=1)` (pre-existing opt-in conformance skip).
- `python3 scripts/verify_install.py` serial → `=== PASS ===`, exit 0,
  **zero SKIPPED**, unchanged stage set (no withdrawal stage — W2 owes
  it).
- **mi-1 (report accuracy, non-blocking):** the core report records the
  contracts gate as `checked 113 markdown files`; the **committed tree
  measures 108** (baseline 107 + the plan doc; `.agents/` is excluded by
  `check_docs.py`, so the report note itself is not counted). The link
  count (532) and result (0 broken) match exactly; the file count was
  evidently measured with untracked working-tree files present. The gate
  passes either way; the honest committed-tree number is 108.

## Independent probes (public API, /tmp stores)

55 assertions across five sections (IP-A refusal channel, IP-B loader
matrix, IP-C discrimination, IP-D composition, IP-E rotation), **all
passing** on the extracted source. Three first-run failures were probe
expectation errors, corrected and disclosed: the resolved refusal surfaces
its reason inside the deterministic `external_id` (the store-level
receipt carries a `reason` field; the runtime operation view carries
`external_id`), and `published_card_matches` takes a policy object
(`getattr` access), not a dict. No product change was wanted or made.
Probe stores and scripts live under `/tmp/s13w1-*` and are deleted with
this report.

## Observed RED replay on the parent tree

With the two new test modules copied onto the `b445fc1` extraction:
`tests.test_publication_withdrawal` → `ImportError: cannot import name
'WITHDRAWAL_DISCRIMINATOR'` and `tests.test_publication_withdrawal_rotation`
→ `ImportError: cannot import name 'SopWithdrawalStore'` — reproducing the
owner's recorded Task-1/2 RED exactly (the implementation names do not
exist on the parent tree; nothing but the new modules' own imports fails).

## Assembly (post-PASS)

- Control `WayJ/s13-release-control`: ordinary `--no-ff` merge of
  `2d29c15` → **`b2380bd7e5a615baea68dc841a76c16deb805ac5`**
  (`merge: assemble S13 withdrawal core 2d29c15 into release control`),
  tree identical to the source (7 files, +2036/−33), worktree clean.
- Carrier `WayJ/sprint-s13-sop-withdrawal`: **fast-forward only**
  `b445fc1 → b2380bd` in its own worktree (asserted clean before).
- This note is the only post-merge commit on control; no main merge, no
  push, no acceptance flip, no self-teardown — integration owns the main
  release after W2 and final acceptance.
- Post-assembly gates re-verified on the assembled control tree: five
  gates green, full suite `997 … OK (skipped=3)` (see below).

## Stable surface handed to W2

`work_runtime/publication.py` public names W2 builds on (stable, reviewed
here): `WITHDRAWAL_KEY_PREFIX`, `WITHDRAWAL_DISCRIMINATOR`,
`WITHDRAWAL_REQUEST_KEYS`, `WITHDRAWAL_IDENTITY_MESSAGE`,
`WITHDRAWAL_REQUEST_MESSAGE`, `WITHDRAWN_MESSAGE`,
`WITHDRAWAL_RECORD_INVALID_MESSAGE`, `WITHDRAWAL_TARGET_ABSENT`,
`WITHDRAWAL_TARGET_DIGEST`, `is_withdrawal_request`, `withdrawal_key`,
`SopWithdrawalStore` (contract `actions=("sop.withdraw",)`),
`withdrawal_record`, plus the extended `SopPublicationPolicy`
(`card_withdrawal` evidence source, W02/W03 shape discrimination,
`sop.withdraw` grants, withdrawal operation key) and the six-class loader
chain. W2 owes: the `publication-demo` withdrawal chapter with updated
census/counts, the `verify_install.py` stage (existing evidence, no new
global gate), the bilingual README mention, and the sop-authoring demo
refresh — none of which exist yet, correctly.

## Remaining risks / honest limits

- Crash window on refusals (disclosed by the owner, accepted by the
  design review §5): a process death between the rejected receipt and
  `_resolve` leaves an operation `reconcile` cannot resolve better than
  `NO_AUTHORITATIVE_RESULT` — the designed path itself never strands.
- Withdrawal fences no running consumer (D62 unchanged); no un-withdrawal
  while the record stands; config rollback revives old approver keys for
  future acts (S11 limits); cross-database shared directories remain the
  accepted MD-4 operator boundary; raw adapter use can commit records the
  loader then honors or refuses fail-closed.
- Trusted-local principals only; no authentication, TLS, KMS,
  revocation-propagation or distributed exactly-once claim (and none
  claimed in code or docs).
- This review is single-reviewer, one machine, synthetic ephemeral
  stores; no hostile-filesystem, power-loss or multi-process stress
  (inherited file-adapter boundaries, unchanged by S13).
