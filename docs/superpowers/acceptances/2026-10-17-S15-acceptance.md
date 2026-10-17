# Acceptance record — sprint S15, 2026-10-17

Independent Orca final acceptance (fresh context, verdict-only) of the
assembled S15 third-family command-surface freeze release (support-ticket
family). Baseline asserted exact before anything ran: worktree
`s15-third-family-freeze`, branch `WayJ/s15-third-family-freeze` at
`49aa79779f364bd07f39efa1af9b162c00469d97` (`git rev-parse` = branch tip =
checkout HEAD), worktree clean with exactly one untracked file — the
[reviewer's note](../../../.agents/notes/2026-10-17-s15-independent-core-review.md),
committed unchanged by this acceptance as cited evidence (separate commit
`64ce0db` before this record's commit; byte-identical to the
reviewed original, `git add` without modification). Merge-base with `main`
is `3e3ab7e2906f3b4e7082675b9c7a71456a138a05`; the sprint range
`3e3ab7e..49aa797` is exactly **12 commits** (wave-1 behavior commits
`5defdfc`, `9db3d0b`, `304459a`, `edbf15f`, `c56cba6`, `201db14`,
`126099b`, `df63277`; wave-1 plan note `996aeac`; test-only `5135947`;
wave-2 release `90483cb`; review-fix `49aa797`), all `support:`-prefixed on
this branch only — no merge, no push performed by this review, and `main`
was only ever read. The sprint plan and the E15 roadmap are **not present
in this worktree** (the branch was cut at `3e3ab7e`, before they
materialized on `main` at `c1064a7`/`d18685f`); both were read in full from
`main` via `git show` — the same source the independent review used (its
note records the same): the active sprint plan
`docs/superpowers/sprints/2026-10-17-S15-plan.md` (DoD verbatim, scenarios
S1–S4; sprint-doc `state: active` at `main` `d18685f`) and the E15 roadmap
`docs/superpowers/roadmaps/2026-10-17-third-family-command-surface-freeze.md`
(D92–D95; its DoD is verbatim identical to the sprint doc's five lines,
compared this run). Both are referenced here as paths, not links, because
they exist only on `main` in this branch's state. Review inputs additionally read in full: the
[independent core review note](../../../.agents/notes/2026-10-17-s15-independent-core-review.md)
(verdict **pass-with-findings**: one MEDIUM docs-truthfulness finding, one
LOW test-pin finding, three INFO notes), `git log 3e3ab7e..HEAD`, and the
[S14 acceptance record](2026-10-16-S14-acceptance.md) as the house-format
precedent. Environment: Python 3.9.6 (system `python3`); zero runtime
dependencies re-verified by the fresh-venv install (only
`governed-work-runtime` `0.1.0a1` plus venv tooling `pip`/`setuptools`, no
third-party packages, no pip deprecation notices this run). This acceptor
made **no product fix** — verdict-only per the dispatch: the only writes
are this record and committing the reviewer's note unchanged; every check
below ran fresh against the assembled tree at `49aa797` as committed.

## Verdict

**pass** — all four scenarios green on fresh runs in this worktree at
`49aa797`, every DoD line checked with evidence, and both independent-review
findings verified **actually resolved at `49aa797`** (the docs fix read
against the three policy `operation_key` implementations; the empty-id test
pin re-proved by this review's own RED/GREEN probe in a scratch copy —
disable `support.py:48-50` → `FAILED (failures=1)`, `AssertionError:
ValueError not raised`; at HEAD → `OK`). The freeze claim re-verified
byte-exact: `work_runtime/runtime.py` SHA-256
`80bf721b3369a6fb865fd6aba0e57804a69eb8587431f8fa6edf1183fc53f4b3` and
`work_runtime/adapters.py`
`ce132f24d84c17a083bcf0b61bf90e1c62ff75faf2ec52fe2c7348ab86b6985e`,
equal to `main` via `git show` and to the pins recorded in the sprint
evidence, with `git diff 3e3ab7e..HEAD` empty over both files. All five
gates, the full suite (1132, `OK (skipped=2)`, skip delta zero with the two
pre-existing names), all nine demos, the rehearsals (15, `OK (skipped=1)`,
pre-existing) and the serial installed verification (`=== PASS ===`, **25
stages, zero SKIPPED**, 13.1s) rerun fresh and pass with exact counts; the
doc-drift audit over `3e3ab7e..49aa797` shows **no `doc_sync_map` row
fires** (all eight mapped files byte-unchanged over the full sprint range).
This record precedes the integration-owned ordinary `main` merge and
non-force push. One structural disclosure: the sprint-doc `state: active →
acceptance` flip could not be performed by this acceptance — the sprint
doc exists only on `main`, which this branch must not merge — so the flip
plus evidence link is a master-owned act on `main` after this record,
recorded here so the omission is visible rather than silent.

## Scenario Results

| id | command | expected | actual | pass |
|---|---|---|---|---|
| S1 | in this worktree: `python3 -m unittest tests.test_support -v` (fresh) plus the named admission tests inside the full-suite run | severity/category rules incl. unknown-blocking verbatim; ticket-reference key dedupe/replay; standard dispositions; no new rejection codes | **`Ran 46 tests in 0.281s / OK`** (exit 0), all 46 observed `ok`. Unknown-blocking: `test_unresolved_severity_and_category_block_with_unknown_applicability`, `test_unresolved_severity_blocks_acceptance`, `test_unresolved_category_blocks_acceptance` (proposal blocked `APPLICABILITY_UNRESOLVED`; unresolved severity also keeps the SLA rule unknown — `test_urgent_sla_applicability_follows_severity`); resolved-but-no-SLA and wrong-budget block `REQUIREMENT_UNSATISFIED` (`test_resolved_urgent_ticket_without_sla_is_blocked`, `test_wrong_budget_sla_still_blocks`); out-of-vocabulary strings are document `ValueError`s, so an unknown string can never enter as within-policy (`test_severity_and_category_use_the_vocabulary_or_none`). Key: `test_operation_key_is_ticket_reference_bound`, `test_business_key_is_the_ticket_reference_digest`, migration readmits the same operation id on the stable key (`test_migration_readmits_the_same_operation_on_the_stable_key`, `SupportPolicyV2` inherits `operation_key` untouched); dedupe/replay in `test_forward_flow_dispatches_and_closes_the_work`; dispositions incl. `WORK_NOT_ACTIONABLE` after closure (same test). No new rejection codes — structurally guaranteed by the byte-identical runtime (S3); every code used (`APPLICABILITY_UNRESOLVED`, `REQUIREMENT_UNSATISFIED`, `OPERATION_CONTENT_CONFLICT`, `COMMAND_ID_REUSED`) pre-exists in it. "Unknown never passes as within-policy" appears verbatim in the demo chapters (S4) and the T01/T02 rule explanations | yes |
| S2 | in this worktree: `python3 -m unittest tests.test_support.SupportCrashRecoveryTests.test_crash_after_acceptance_recovers_by_ticket_reference -v` (fresh, individually) inside the 46-test run; forward flow and timeout-reconcile covered by the named tests in the same fresh run; machinery semantics pinned by the byte pin | result-unknown fencing; crash-after-acceptance restart reconciles by ticket reference, recovers the original receipt, never re-sends | Individual fresh run: **`Ran 1 test in 0.060s / OK`** — a real grants-carrying child process dies (`exit code 73`) after the tracker accepted the write; restart `recover()` → `confirmed_succeeded` with exactly one attempt, one issue, one receipt row (assertions in the test body; the demo chapter and the installer store proof re-verify the same counts from SQLite — S4). Forward dispatch to the GitHub-issue-shaped fake tracker (receipt `#1`, `issue_state "open"`) and closure ack in `test_forward_flow_dispatches_and_closes_the_work` (ok); timeout-after-commit → `outcome_unknown` → reconcile by `lookup(business_key)` without re-send in `test_timeout_after_commit_recovers_by_lookup_without_resend` (ok); unknown-outcome recovery and version stability in `test_migration_refuses_uncertain_outcomes`, `SupportRecoveryTests`/`SupportMigrationTests` (all ok). Result-unknown machinery semantics unchanged: `runtime.py` byte-identical across the sprint (S3) | yes |
| S3 | in this worktree: `shasum -a 256 work_runtime/runtime.py work_runtime/adapters.py`; `git show main:work_runtime/runtime.py \| shasum -a 256` (and adapters); `git diff --name-only 3e3ab7e..HEAD -- work_runtime/runtime.py work_runtime/adapters.py`; `python3 -m unittest tests.test_support.FakeIssueTrackerConformanceTests -v` (inside the fresh 46-run); `git diff 3e3ab7e..HEAD -- work_runtime/cli.py` read hunks; freeze-verdict section read in `docs/runtime-boundaries.md` | zero lifecycle edits or a disclosed freeze gap; conformance mixin passes without lifecycle edits | Hashes equal to `main` and to the recorded pins: `80bf721b3369a6fb865fd6aba0e57804a69eb8587431f8fa6edf1183fc53f4b3` (`runtime.py`), `ce132f24d84c17a083bcf0b61bf90e1c62ff75faf2ec52fe2c7348ab86b6985e` (`adapters.py`); diff over both files across the sprint range → **empty**. Conformance mixin: all six `FakeIssueTrackerConformanceTests` cases `ok` in the fresh run, including `test_opted_in_action_context_replay_returns_identical_receipt` — which **runs** (not skipped) because the tracker opts into action context. `work_runtime/__main__.py` absent from the changed-path list (zero-line diff); the `cli.py` diff read this run is presentation-only (imports, `support-demo` subparser, `inspect --policy support-ticket` choice + its `--policy-versions` guard error, dispatch/inspect elifs). No lifecycle-edit need arose, so no stop-and-ask freeze-gap record was required — the zero-edit outcome is the disclosed verdict: `docs/runtime-boundaries.md` "Third-family command-surface freeze (S15)" states **"Freeze verdict: zero lifecycle edits"** with both SHA pins and the two disclosed family constraints (identity keyed on the ticket reference; one reference = one governed dispatch) | yes |
| S4 | in this worktree: the five AGENTS gates verbatim; `python3 -m unittest discover -s tests -v`; nine demos (`demo` + eight `--directory` runs incl. `python3 -m work_runtime support-demo --directory …`); `python3 -m unittest discover -s examples/rehearsal`; serial `python3 scripts/verify_install.py`; no-secrets scans; doc-sync audit | exact counts/skips; no secrets; installer stages additive with disclosed deltas; five gates verbatim; doc-sync audit clean; this acceptance precedes any push | Five gates verbatim (worktree asserted clean first): contracts `checked 118 markdown files, 596 local links, 0 broken` (exit 0); tests **`Ran 1132 tests in 45.008s / OK (skipped=2)`** (exit 0; baseline 1077 + 55 new = 46 in `tests/test_support.py` incl. 6 inherited conformance-mixin cases + 9 in `tests/test_support_demo.py`; skip delta zero — the two skips are the pre-existing `test_opted_in_action_context_replay_returns_identical_receipt` (`test_file_adapter.FilePublisherConformanceTests`, 'adapter does not opt into action/link execution context' — the support-tracker variant runs and passes) and `test_absent_backend_is_a_bounded_startup_error` (`test_ui_cli.AbsentBackendTests`, 'backend assembled: absent-install path unreachable')); demo exit 0 ending `6. Evidence-backed completion → SUCCEEDED; external applications created: 1`; `compileall -q work_runtime tests scripts` silent exit 0; site `checked 2 pages, 0 findings`. **Nine demos exit 0** (`demo`, `publish-demo`, `intervention-demo`, `adoption-demo`, `revocation-demo`, `compensation-demo`, `rotation-demo`, `publication-demo`, `support-demo` — the eight `--directory` runs after the documented mkdir precondition, obstacles log). `support-demo` final line `2 works; issues filed: 2; crash-recovered receipts: 1; effects re-sent: 0`; this review's scan: **0** matches of `[0-9a-f]{64}` and no credential words in its output. Rehearsals **`Ran 15 tests in 0.056s / OK (skipped=1)`** (pre-existing generic opt-in conformance skip). Installer **serial**: **`=== PASS ===`, exit 0, 13.1s, zero `SKIPPED` lines, 25 stages** — `=== module support-demo outside the checkout ===` (stage 24) and `=== console support-demo outside the checkout ===` (stage 25) both present and **disclosed "BOTH stages are NEW coverage since S15"** in the final summary, with the independent store proof: "both works closed/succeeded with T04 satisfied, two confirmed operations on recomputed ticket-reference business keys with exactly one attempt each, runtime-written tracker accepted proofs, one issue per reference and two accepted receipts — nothing re-sent"; import origin inside the fresh venv; zero third-party runtime dependencies. Doc-sync audit: no row fires (below). README bilingual parity read: en/zh ninth-demo sections carry the same facts (freeze verdict with pins referenced, both chapters, one-reference-one-dispatch, `TICKET_REFERENCE_CONTENT_CONFLICT`/`OPERATION_CONTENT_CONFLICT`, no credentials). No merge, no push, no force performed; this record precedes the integration-owned ordinary `main` merge/non-force push | yes |

## Review-findings resolution (verified this run at `49aa797`)

- **Finding 1 (MEDIUM, docs truthfulness — expense key wording): RESOLVED.**
  `docs/runtime-boundaries.md:42` now reads "… expense demo: policy id +
  capability + document id + **document revision**; publishing family:
  policy id + capability + document id + **document digest**; support-ticket
  family: policy id + capability + the ticket reference alone …". Verified
  against the code this run: `work_runtime/policy.py:147-149`
  (`operation_key` embeds `work["document_revision"]`),
  `work_runtime/publishing.py:111-113` (embeds `work["document_digest"]`),
  `work_runtime/support.py:141-147` (embeds `work["document"]["id"]` — the
  ticket reference, no digest, no version). All three families now read
  truthfully in the one row the sprint edited.
- **Finding 2 (LOW, test pin — empty ticket reference never rejected by any
  test): RESOLVED.** `tests/test_support.py:45-51` now iterates
  `("id", "summary")` — the real document fields — so `{**ticket(), "id":
  ""}` reaches the nonempty-string rejection at `work_runtime/support.py:48-50`
  instead of tripping the exact-field-set rule for the wrong reason.
  Independent RED/GREEN probe by this review (scratch copy via
  `git archive HEAD`, so the verdict-only no-edit constraint holds): with
  the check disabled (`sed` → `if False:` at `support.py:49`),
  `python3 -m unittest
  tests.test_support.SupportDocumentTests.test_identity_strings_must_be_nonempty -v`
  → **`Ran 1 test … FAILED (failures=1)`, `AssertionError: ValueError not
  raised`** at the `field: ""` line; at HEAD the same command → **`OK`**.
  The fix commit `49aa797` message itself records the fix worker's
  equivalent probe ("RED/GREEN verified by disabling the check"); this
  review's fresh probe is the independent confirmation, so the fix worker's
  trail was not needed as the sole evidence.
- **Findings 3–5 (INFO: inert second `admit()` in the cross-work conflict
  test; cosmetic unused variable/trailing whitespace; coverage note):**
  recorded in the committed review note; no product issue; no action
  required for acceptance. The `5135947` no-op-assertion drop the reviewer
  re-verified is history this run confirms (assertion set in
  `test_cross_work_same_ticket_reference_conflicts` is decision +
  `OPERATION_CONTENT_CONFLICT`).

## DoD Checklist

- [x] A third business family runs end-to-end over the unchanged command protocol — proposal admission (including an unknown-applicability blocking rule), dispatch with result-unknown fencing, receipt reconciliation and business closure — with `work_runtime/runtime.py` and `work_runtime/adapters.py` byte-unchanged (hash-pinned; escalation rule: any required lifecycle edit stops and asks the master, recorded as a disclosed freeze-gap finding, never silently absorbed) — S1/S2: the 46-test fresh run covers admission (unknown-blocking both fields, SLA gating), forward propose → admit → dispatch → receipt → closure, timeout-reconcile and the real exit-73 crash recovery (one attempt, one issue, one receipt, never re-sent); S3: hashes `80bf721b…`/`ce132f24…` equal to `main` and the recorded pins, `git diff 3e3ab7e..HEAD` empty over both files; the escalation rule was never triggered (no runtime need discovered — the wave reports, the review and this run concur)
- [x] The family adapter passes the public conformance mixin without lifecycle edits; family policy rules are new code preserving unknown semantics (an unknown amount can never pass as within-limit) — S3: all six `FakeIssueTrackerConformanceTests` cases `ok` fresh, incl. the opted-in action-context replay (runs, not skipped); family code is all-new (`work_runtime/support.py` is family-owned plugin code; its `TICKET_REFERENCE_CONTENT_CONFLICT` is adapter-domain semantics mirroring `FakePublisher`'s `ORIGINAL_ABSENT`, not lifecycle duplication); unknown semantics preserved and tested: unresolved severity/category ⇒ `APPLICABILITY_UNRESOLVED` blockers (and unknown severity keeps the SLA rule unknown), out-of-vocabulary strings are `ValueError`s at validation so an unknown value can never enter as within-policy — the family equivalent of "an unknown amount can never pass as within-limit" (`test_severity_and_category_use_the_vocabulary_or_none`, `test_unresolved_severity_blocks_acceptance`, `test_unresolved_category_blocks_acceptance`, `test_urgent_sla_applicability_follows_severity`, all `ok` fresh)
- [x] The family demo runs from a clean clone without credentials or services, prints no secrets, and the installer module/console stages are updated same-commit with exact counts and every skip delta explained — S4: `support-demo` exit 0 in-checkout and via both installer stages outside the checkout in the fresh venv; final line `2 works; issues filed: 2; crash-recovered receipts: 1; effects re-sent: 0`; **0** matches of `[0-9a-f]{64}` and no credential words in the output; installer stages 24/25 purely additive (23 → 25) with "BOTH stages are NEW coverage since S15" disclosed in the docstring and the final summary; demo + installer + truth docs + both READMEs + tests landed in one release commit `90483cb`; suite skips stay 2 (zero delta, exact pre-existing names) and the installer reported zero SKIPPED; demo set grew 8 → 9 with the ninth demo disclosed in `docs/verification.md` and both READMEs
- [x] Deferrals hold: no post-closure compensation, no compensation chains, no new lifecycle commands (D94) — `work_runtime/support.py:42` declares no `compensation_capabilities` (so the runtime's pairing gate cannot fire for this family), link-carrying calls refused at `support.py:223` and tested (`test_link_carrying_calls_and_unknown_actions_raise`, `ok` fresh); `runtime.py` byte-unchanged and `__main__.py` zero-diff ⇒ no new lifecycle commands; the `cli.py` diff is presentation-only (subparser, choice, elifs — read this run); no compensation chain can exist without the first compensation
- [x] The five gates, full suite, demo set, rehearsals and serial installed verification pass with exact counts/skips; independent acceptance precedes the integration-owned ordinary main merge and non-force push, with truth docs and the roadmap note same-commit — all rerun fresh this run: contracts 118/596/0 · tests **1132 `OK (skipped=2)`** (1077 baseline + 55 new; both skip names pre-existing) · demo exit 0 (`SUCCEEDED; external applications created: 1`) · compileall silent · site 2/0; nine demos exit 0; rehearsals 15 `OK (skipped=1)`; installer serial `=== PASS ===` 13.1s, **25 stages, zero SKIPPED** (24/25 the new module+console support-demo stages, disclosed); truth docs landed same-commit in the release `90483cb` (`docs/adapter-contract.md`, `docs/runtime-boundaries.md` incl. the freeze verdict, `docs/verification.md`, both READMEs) and the fix `49aa797` pairs its docs edit with its test edit; `docs/roadmap.md` untouched over the whole range (0 lines — the 0.2 close-out note is master-owned at close-out, sprint D4). This record is the independent acceptance and precedes any merge/push (none performed; `main` untouched). The sprint-doc `state: acceptance` flip is a master-owned act on `main` after this record — the sprint doc materialized on `main` after this branch was cut, and this branch must not merge `main` (disclosed in Verdict)

## Obstacles (verbatim)

- 2026-10-17 — the dispatch's READ-FIRST sprint plan and E15 roadmap are
  absent from this worktree (`ls docs/superpowers/sprints/2026-10-17*` →
  `no matches found`; the branch was cut at `3e3ab7e` before the docs
  materialized on `main`). Notes searched by keyword first; the
  [review note](../../../.agents/notes/2026-10-17-s15-independent-core-review.md)
  records the same situation and the same workaround. Reused with citation:
  read both verbatim from `main` via `git show
  main:docs/superpowers/sprints/2026-10-17-S15-plan.md` and `git show
  main:docs/superpowers/roadmaps/2026-10-17-third-family-command-surface-freeze.md`
  (DoD compared line-by-line — the sprint doc's five DoD lines are verbatim
  the epic's). No proving command was substituted; only the read source.
- 2026-10-17 — the eight `--directory` demo runs require the documented
  precondition that each exact `--directory` exists (the demos `mkdtemp`
  inside it). Source: the S12 acceptance record's obstacles log, repeated
  by S13/S14 — reused with citation: `mkdir -p` each exact directory under
  `/tmp/s15-accept-demo/demos/`, then all eight exit 0. No product issue.
- 2026-10-17 — the finding-2 RED probe needed `work_runtime/support.py`
  temporarily disabled, which the verdict-only edit constraint forbids in
  this worktree. Narrowest workaround: scratch copy (`git archive HEAD |
  tar -x -C /tmp/s15-accept-probe`), `sed` disabling exactly the
  nonempty-string condition there, probe run there, scratch directory
  removed afterwards; `git status --porcelain` in the worktree re-asserted
  to show only the untracked review note. Product tree unchanged.
- 2026-10-17 — structural, not a failure: the sprint-doc
  `state: active → acceptance` flip cannot be performed here (the sprint
  doc lives only on `main`; this branch must not merge or push). Left to
  the master as a close act with this record as the evidence link;
  disclosed in Verdict rather than silently omitted.
- No other blocker, failure or substitution occurred. No evidence item in
  this record is substituted: every scenario ran its specified proving
  command for real in this worktree at `49aa797` (the one scratch-copy
  excursion is the RED half of the finding-2 probe, disclosed above).

## Doc-Drift Audit

Range audited: the full sprint range `3e3ab7e..49aa797` (superset of the
review's `3e3ab7e..90483cb` plus the fix commit). Per-commit pairing was
checked with `git diff-tree --no-commit-id --name-only -r <sha>` on all 12
commits. Changed files `3e3ab7e..49aa797`: exactly 13 —
`.agents/notes/2026-10-17-s15-wave1-family-plan.md` (new),
`.agents/notes/2026-10-17-s15-wave2-demo-plan.md` (new), `README.md`,
`README.zh-CN.md`, `docs/adapter-contract.md`, `docs/runtime-boundaries.md`,
`docs/verification.md`, `scripts/verify_install.py`,
`tests/test_support.py` (new), `tests/test_support_demo.py` (new),
`work_runtime/cli.py`, `work_runtime/support.py` (new),
`work_runtime/support_demo.py` (new). None is a `doc_sync_map` path.

| map row (change, owes) | matched this sprint | doc state | detail |
|---|---|---|---|
| work_runtime/runtime.py → docs/runtime-boundaries.md | no — byte-identical `3e3ab7e..49aa797` (explicit diff empty; SHA-256 pinned and equal to `main`, S3) | n/a | row owes nothing; the freeze held, escalation rule never triggered |
| work_runtime/adapters.py → docs/runtime-boundaries.md | no — byte-identical over the full sprint range (S3) | n/a | row owes nothing |
| scripts/check_docs.py → CONTRIBUTING.md | no — unchanged over the full sprint range (not in the changed-path list) | n/a | row owes nothing |
| scripts/check_site.py → docs/website.md | no — unchanged over the full sprint range | n/a | row owes nothing |
| work_runtime/ingress.py → docs/signed-evidence.md | no — unchanged over the full sprint range | n/a | row owes nothing |
| work_runtime/publication.py → docs/sop-authoring.md | no — unchanged over the full sprint range | n/a | row owes nothing |
| work_runtime/publication_demo.py → docs/sop-authoring.md | no — unchanged over the full sprint range | n/a | row owes nothing |
| work_runtime/file_adapter.py → docs/file-adapter.md | no — unchanged over the full sprint range | n/a | row owes nothing |

Beyond the map (recorded, not enforced): the S15 product surfaces
(`work_runtime/support.py`, `work_runtime/support_demo.py`,
`work_runtime/cli.py`, `scripts/verify_install.py`) have **no** map rows —
unlike S14's publishing.py, no per-behavior-commit doc pairing was
committed to in the S15 design; the sprint's own D4 requires docs
same-commit with the release, which the single release commit `90483cb`
satisfies: it carries the demo module, the installer stages, the truth
docs (`adapter-contract.md` family example, `runtime-boundaries.md` freeze
verdict + family sentence, `verification.md` S15 coverage), both READMEs,
the CLI wiring and the demo tests together. Wave-1 commits are code+test
pairs (`support.py` + `test_support.py` in the same commit each;
`126099b` test-only, `996aeac`/`5135947` note/test-only — no doc owed by
map or design); the fix `49aa797` pairs its `runtime-boundaries.md` edit
with its `test_support.py` edit. `docs/roadmap.md` and `AGENTS.md` are
untouched over the whole range (0 lines; the 0.2 close-out note and any
ledger flip are master-owned close acts). Truth docs re-read this run and
current: the `runtime-boundaries.md` freeze section (verdict, pins, both
disclosed constraints, the three-family business-key row corrected by
`49aa797`); `docs/verification.md` S15 coverage (46 + 9 tests, 1132 total,
stages 24/25 with the NEW disclosure); `docs/adapter-contract.md` S15
family section; both READMEs' ninth-demo sections (en+zh parity).

**No unpaid drift on any row this sprint triggered.**
