# S14 W1 core integration review — PASS, assembled — 2026-10-16

Independent Orca review/assembly of the S14 publishing-compensation core
(`content.unpublish` linked retraction), distinct from the owner's
self-review recorded in [the core report](2026-10-16-S14-core-report.md).
Reviewer checkout: `s14-release-control` (control branch
`WayJ/s14-release-control`, base `7f547cb9c41ee900e48571dea6235cf7ec2f6cdc`
= carrier baseline, clean before the merge and after assembly). No product
file was modified by this review; every gate, demo, rehearsal, installer
run, RED replay and independent probe ran from `git archive` extractions
of the accepted source `76988d2` and the baseline `7f547cb` into
disposable `/tmp` directories, plus fresh `/tmp` SQLite stores with
synthetic ephemeral material only (no secrets printed). Verdict:
**PASS — no material finding**; two minor observations (mi-1, mi-2) and
one disclosure observation (obs-1) recorded below, none blocking, none
requiring a product fix (material findings would have routed to the
master per the dispatch; none arose). This review proves the **local S14
W1 core only** — the publish-demo retraction chapter (D90 structure (b),
counts 2/1), installer module-stage update + NEW console stage, bilingual
README entries, final acceptance and the main merge are W2+ and remain
owed.

## Scope and source

- Accepted source: `WayJ/s14-compensation-core` tip
  **`76988d28de7ab3a827c4ab673bc7be55c51b712d`** (`git rev-parse` verified
  equal to the branch tip), **8 commits** `7f547cb..76988d2` =
  `091b27b..76988d2` inclusive — plan `091b27b`, pairing `5e7b483`,
  opt-in/migration/forward-identity `c636954`, retraction execution
  `b23ccb4`, governed admission/authority/RF4 `7dd69a8`, governed
  dispatch/resolution/closure/recovery `5813349`, boundary pins + coverage
  docs + report `1812c9b`, verification.md count fix `76988d2` — matching
  the dispatch and the owner's commit table exactly.
- Carrier baseline: `WayJ/sprint-s14-publishing-compensation` =
  `7f547cb9c41ee900e48571dea6235cf7ec2f6cdc`, worktree clean (asserted
  before the fast-forward).
- Changed files: **10** (`git diff --name-status 7f547cb..76988d2`
  verified): `work_runtime/publishing.py` (+187/−61 net section),
  `tests/test_publishing_compensation.py` (new, 1315), the two authorized
  sites in `tests/test_compensation.py` (26), the two mechanical
  `**kwargs` fixes in `tests/test_publishing.py` (8), four truth docs
  (`runtime-boundaries.md`, `interventions.md`, `verification.md`,
  `adapter-contract.md`), the core plan, the core report — exactly the
  core plan's ownership list. **No `doc_sync_map` row fires** (AGENTS.md:
  `publishing.py` is not a mapped row); the doc changes are owed for
  truth per D91, delivered same-commit (see pairing below).
- **D82 byte pins hold and are real:** `git diff 7f547cb 76988d2 --
  work_runtime/runtime.py work_runtime/adapters.py
  work_runtime/file_adapter.py work_runtime/policy.py` is **empty**, and
  the sha256 values at `76988d2` equal the baseline values equal the
  `BoundaryPins.PINNED` assertions
  (`80bf721b…`, `ce132f24…`, `7044a92b…`, `76d4e9c6…`). The pin test
  reads the files relative to the repo root and fails on mismatch
  (re-run live post-assembly: OK). The escalation rule was never
  triggered (no runtime need discovered).
- Same-commit doc pairing on every behavior commit: `5e7b483` →
  runtime-boundaries + interventions + verification; `c636954` →
  adapter-contract + runtime-boundaries; `b23ccb4` → adapter-contract;
  test-only governed-coverage commits (`7dd69a8`, `5813349`) owe no doc
  (runtime-owned behavior pinned, not changed); the coverage section and
  report ride with `1812c9b`.

## Review against D80–D91

- **D81/D89 (pairing attribute only):** `PublishingPolicy.
  compensation_capabilities = {"content.unpublish": "content.publish"}`;
  the paired branch mirrors the S10 `policy.py:133-139` shape exactly
  (paired → `[]`, admitted through the link check; off-family keeps
  `CAPABILITY_UNSUPPORTED`); `version` stays `"demo-1"` — no new version,
  no other class change.
- **D86+MD-2 (contract):** `actions=("content.publish",
  "content.unpublish")` with the forward action **FIRST** (asserted;
  the conformance mixin derives forward context from `actions[0]`),
  `uniqueness=("document.id+content_digest",
  "retraction.original_external_id")`, `supports_action_context=True`.
  `adapter_contract.py` untouched.
- **D86 (store):** one `BEGIN IMMEDIATE` migration with in-transaction
  `PRAGMA table_info` probe; additive nullable `receipts.action`/
  `link_digest`; `retractions(original_external_id PRIMARY KEY,
  external_id, key, digest)`; legacy rows never rewritten (my probe
  snapshotted row bytes before/after — identical); reopen idempotent;
  concurrent first-open serialized (owner test; S10 pattern). Alias
  receipts reuse the existing `RTR-…` retraction id under the requesting
  key/digest with `lookup` authoritative; `ORIGINAL_ABSENT` is an
  authoritative stored business rejection (receipt row only, no effect
  row, replayable); original existence is decided by an accepted forward
  **receipt scan** with a publications short-circuit (both lost-row legs
  probed). The `RTR-` prefix is pinned deterministically (tests + docs).
- **D87 (as amended — behavior-level forward identity):** no
  withdraw-by-store-state branch exists (`_execute_forward` never reads
  `retractions`; no store state can turn a forward call into a
  retraction); same-content dedup returns the identical receipt with
  identical store state; retraction is append-only. **The single
  disclosed column-naming INSERT edit is located and mechanical**:
  `INSERT INTO receipts (key,digest,result) VALUES (?,?,?)` in
  `_execute_forward`, forward rows keep NULL `action`/`link_digest`.
  **obs-1 (disclosure observation):** the replay read was necessarily
  widened in the same migration (`SELECT digest,action,link_digest,result`
  with legacy NULL action normalized to the forward action) — a
  read-side counterpart of the same mechanical edit, behavior-identical
  (probe-proven below), within the ratified behavior-level pin; recorded
  here for completeness since the report names only the INSERT.
- **D80/D83/D84/D85 (governed flow, S10 verbatim):** window split
  (linked requires the intent `CANCELLATION_NOT_REQUESTED`; forward under
  the intent `CANCELLATION_ACTIVE`), immutable
  `{operation_id, external_id, capability}` snapshot never rebound on
  re-admission, business key exactly
  `digest(["content-publish", "content.unpublish", target])` (my probe
  recomputed it), distinct from the forward key, one operations row per
  key; current-owner + `content.unpublish` grant with grant-loss denial
  at proposal/replay/dispatch and transfer re-admission; cross-work
  same-content `OPERATION_CONTENT_CONFLICT` (store-global forward key
  `digest([policy.id, capability, document.id, document_digest])` embeds
  no work id); `withdrawn` proof at the family accepted source
  `"publisher"` with data `{digest, external_id, original_external_id}`,
  C04 kind-literal inertness, import denial, admin-only revocation;
  binding-mismatch quarantine idempotent; `adapter_result` on
  compensations only; exact two-id ack closes `closed`/`cancelled` with
  the compensation disposition carrying `compensates` + `adapter_result`
  and the forward disposition keeping the three-field shape; unresolved
  retraction blocks `finalize_cancel`; refused retraction is
  `confirmed_failed`, recorded, never reversed. No new codes, no new
  proof kind, runtime schema `1`.
- **D88 (FilePublisher):** byte-unchanged (hash pin); holds at the
  actions preflight `ADAPTER_ACTION_UNSUPPORTED` with zero attempts and
  an empty directory; its conformance opt-in skip remains a designed
  skip.
- **RF4:** the re-publish-after-retraction limit is documented as an
  adapter-model statement **with the reachability note**
  (adapter-contract.md; also carried in runtime-boundaries), and **both
  governed refusal legs were independently probed** (same-work
  `CANCELLATION_ACTIVE`; cross-work `OPERATION_CONTENT_CONFLICT`).
- **D90 (demo):** correctly NOT in this slice — all eight demos exit 0
  with the retraction chapter correctly absent from `publish-demo`
  (zero "retract" matches in its output); `publishing_demo.py`,
  `scripts/verify_install.py`, READMEs untouched (not in the diff).
- **D91 (truth docs):** all four named docs updated same-commit;
  `roadmap.md` 0.3 stays master-owned close-out (MD-4) — correctly
  untouched.

## The three scrutinized deltas

1. **Skip count 3 → 2 — cause proven, not a deletion/rename.** Baseline
   `7f547cb` battery re-run on the parent extraction: `Ran 1015 tests …
   OK (skipped=3)` with exactly `test_opted_in_action_context_replay_
   returns_identical_receipt` under `test_publishing.
   FakePublisherConformanceTests` AND `test_file_adapter.
   FilePublisherConformanceTests`, plus `test_absent_backend_is_a_
   bounded_startup_error (test_ui_cli.AbsentBackendTests)`. Source
   battery: `1059 … OK (skipped=2)`; the `FakePublisherConformanceTests`
   opt-in test now **runs and passes** (observed `ok` in `-v`), the
   mixin (`tests/adapter_conformance.py`) and the test class are
   untouched by the diff — the skip disappeared because
   `supports_action_context=True` activated it (F6), exactly as designed.
   The **two remaining skips, exact names**:
   `test_file_adapter.FilePublisherConformanceTests.
   test_opted_in_action_context_replay_returns_identical_receipt`
   (designed skip — D88 FilePublisher stays forward-only) and
   `test_ui_cli.AbsentBackendTests.test_absent_backend_is_a_
   bounded_startup_error` (pre-existing).
2. **`tests/test_compensation.py` option A:** exactly 2 hunks at the two
   authorized sites; all 4 removed lines are publishing clauses (the
   `PublishingPolicy` entry leaving the unpaired loop; the
   `FakePublisher … is False` opt-in assertion); **zero expense-family
   lines touched** (grep of removed lines: 0 expense mentions); the
   updated clauses assert the S14 truth (paired attribute, actions order,
   opt-in `True`, FilePublisher untouched) with the supersession comment.
3. **`tests/test_publishing.py`:** exactly 2 hunks — `CountingPublisher.
   execute` and `MalformedResultTests`'s `Tampered.execute` gain
   `**kwargs` passthrough (they inherit `FakePublisher.contract`, so the
   opted-in kwargs call would have raised `TypeError`); no assertion
   changed. **`76988d2` verification.md count fix:** isolated single-
   character docs commit (`42`→`43`); the doc had said 42 since the S2
   commit `19f6e14` while the module has had 37 own `def test_` + 6
   mixin methods = 43 — a pre-existing off-by-one truth fix, not scope
   creep (S14 added no tests to that file).

## Fresh battery on the extracted source (verbatim)

- `python3 -m unittest discover -s tests -v` → **`Ran 1059 tests in
  47.357s / OK (skipped=2)`** (baseline 1015 + 44 new), skips exactly as
  named above.
- Five AGENTS gates VERBATIM: `check_docs.py` → `checked 114 markdown
  files, 578 local links, 0 broken` (see mi-1); the unittest gate → OK
  (skipped=2); `python3 -m work_runtime demo` → exit 0;
  `python3 -m compileall -q work_runtime tests scripts` → clean;
  `check_site.py` → `checked 2 pages, 0 findings`.
- Eight existing demos exit 0 (`demo`, `publish-demo`,
  `intervention-demo`, `adoption-demo`, `revocation-demo`,
  `compensation-demo`, `rotation-demo`, `publication-demo`); retraction
  chapter correctly absent from `publish-demo`.
- Rehearsals `python3 -m unittest discover -s examples/rehearsal` →
  `Ran 15 tests … OK (skipped=1)` (pre-existing generic opt-in skip).
- `python3 scripts/verify_install.py` serial → **`=== PASS ===`**, exit
  0, **zero SKIPPED lines**, stage set byte-identical to the baseline
  run's stage set (diffed `===` stage headers between the parent and
  source runs: identical — no S14 stage, correctly W2 same-commit).

## Independent probes (public API, /tmp stores, my own construction)

33 assertions, **all passing** on the extracted source:
- **Migration on a legacy store I built myself** (3 legacy forward rows,
  raw-SQL 3-column schema): columns added in order, `retractions`
  created, legacy receipt and publication **row bytes identical** after
  migration, NULL identity on legacy rows, legacy receipt replays by
  key+digest through the new code, double reopen idempotent, retraction
  of a legacy original accepted (scan treats NULL action as forward),
  publications-row-lost existence still decided present, unknown original
  → `ORIGINAL_ABSENT` with no effect row, `published_count()` never
  counts an effect away (13 checks).
- **Governed end-to-end with a real child crash:** real Runtime + SQLite
  harness written for this review — linked proposal admitted in window,
  immutable snapshot shape, D6 compensation key recomputed, child process
  killed `os._exit(73)` via the dispatch fault after the retraction
  committed → operation `dispatched`, store holds exactly (1, 1);
  restarted runtime `recover()` confirms once (single attempt), still
  (1, 1); `withdrawn` verified proof at source `publisher` with the exact
  `{digest, external_id, original_external_id}` data; exact two-id ack
  accepted → `closed`/`cancelled`, closure lists both external ids
  (`PUB-` + `RTR-`), compensation disposition carries `compensates` +
  `adapter_result`, forward disposition keeps the three-field shape
  (14 checks).
- **RF4 both legs** through my own harness: same-work forward re-publish
  under the permanent intent → `CANCELLATION_ACTIVE`; cross-work
  identical content → `OPERATION_CONTENT_CONFLICT` (2 checks; one
  first-run failure was a probe-expectation error — the second work's
  requirements had to be satisfied before the proposal reaches the
  business-key branch — corrected and disclosed; no product issue).
- **Cross-tree D87 store-state identity:** the same deterministic
  forward-only call sequence (key replay, same-content dedup, new
  version, digest conflict) run against the parent (`7f547cb`) and source
  (`76988d2`) FakePublisher stores produces **byte-identical normalized
  receipt and publication rows** (uuid suffixes normalized) — the
  strongest form of the behavior-level forward pin (4 checks + the diff
  itself).
- `BoundaryPins` re-run live: OK.

## Observed RED replay on the parent tree

With the new test module copied onto the `7f547cb` extraction:
`PolicyPairingTests` + `ForwardIdentityTests` + `RetractionExecutionTests`
→ **9 errors + 1 failure** with exactly the predicted natures
(`AttributeError: 'PublishingPolicy' object has no attribute
'compensation_capabilities'`; `TypeError: execute() got an unexpected
keyword argument 'action'`; contract-order mismatch), and the governed
admission test fails `rejected` vs `accepted` (today's
`REQUIREMENT_UNSATISFIED`). The copied module was then removed; the
parent extraction is untouched otherwise.

## Minor observations (non-material)

- **mi-1:** the core report's check_docs line reads "checked **121**
  markdown files, 578 local links, 0 broken"; the committed tree at
  `76988d2` measures **114 files, 578 links, 0 broken** (baseline 113 /
  573; +1 file = the plan doc, +5 links; 114 = 235 tree .md − 119
  `.agents` (excluded dir) − 2 historical files). The link count and the
  result match; the file count was evidently measured with untracked
  working-tree notes present — the same pattern the S13 review recorded.
  The gate passes either way; the honest committed-tree number is 114.
- **mi-2:** `import secrets` in `tests/test_publishing_compensation.py`
  is unused (the final harness records evidence directly, no signing
  gateway). Cosmetic; no gate covers it; no behavior impact.
- **obs-1:** recorded above under D87 (replay-SELECT widening, the
  mechanical read-side counterpart of the disclosed INSERT edit;
  behavior-identical, cross-tree proven).

## Assembly (post-PASS)

- Control `WayJ/s14-release-control`: ordinary `--no-ff` merge of
  `76988d2` → **`b04aac275a235b691b4aa919dd6524a282b4bdf8`**
  (`merge: assemble S14 publishing compensation core 76988d2 into release
  control`), tree identical to the source (10 files, +2056/−61),
  worktree clean; this note is the only post-merge commit on control.
- Carrier `WayJ/sprint-s14-publishing-compensation`: **fast-forward
  only** `7f547cb → <this note's commit>` in its own worktree (asserted
  clean before).
- No main merge, no push, no acceptance flip, no self-teardown —
  integration owns the main release after W2 and final acceptance.
- Post-assembly gates re-verified on the assembled control tree (see
  below).

## Stable surface handed to W2

Public names W2 builds on (stable, reviewed here):
`PublishingPolicy.compensation_capabilities` (pairing attribute, version
`demo-1` unchanged); `FakePublisher.contract`
(`actions=("content.publish", "content.unpublish")` order-pinned,
`uniqueness=("document.id+content_digest",
"retraction.original_external_id")`, `supports_action_context=True`);
`FakePublisher.execute(key, document, content_digest, *, action=None,
compensates=None)` with the three `ValueError` guards;
`FakePublisher.retracted_count()` alongside the unchanged
`published_count()`; the `retractions` table shape and the deterministic
`RTR-` prefix; the test-local grants pattern
`{"agent": {"work.manage", "content.publish", "content.unpublish"}, …}`.
`publishing_demo.py` is untouched (succeeded-completion ending intact,
forward-only grants) — W2 appends the cancellation+retraction chapter
per D90 structure (b) with asserted counts `published_count == 2,
retracted_count == 1` and the exact two-id closure, updates the
installer's publish-demo module-stage assertions in the SAME commit,
adds the NEW console stage (disclosed as new coverage), and adds the
bilingual README mention. `roadmap.md` 0.3 remains master-owned
close-out (MD-4).

## Remaining risks / honest limits

- W2 is pending and required for release (demo chapter, installer
  stages, READMEs); no acceptance flip was made here.
- The re-publish-after-retraction interplay is reachable only through
  direct adapter calls; through the governed flow both refusal legs are
  pinned and probed (RF4). The limit binds the adapter model.
- The FilePublisher conformance opt-in skip remains by design (D88);
  `content.unpublish` (content family) is kept distinct from S13's
  `sop.withdraw` everywhere (F10).
- Trusted-local only: no authentication, tenant, fencing,
  distributed-exactly-once or production-safety claim; the fake
  publisher remains a local stand-in.
- This review is single-reviewer, one machine, synthetic ephemeral
  stores under `/tmp`; probe scripts and stores are throwaway and were
  not committed.
