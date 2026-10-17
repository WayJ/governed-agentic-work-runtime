# S15 independent core review — third-family command-surface freeze

Review-only, fresh independent context. Target: worktree `s15-third-family-freeze`,
branch `WayJ/s15-third-family-freeze`, diff `3e3ab7e..90483cb` (11 commits) against
main. Reviewed against `docs/superpowers/sprints/2026-10-17-S15-plan.md` (read from
`main`; the worktree predates the sprint doc) plus the recon and wave notes.
No file was edited, nothing committed (this report is a new untracked note).

## Overall verdict: **pass-with-findings**

One medium docs-truthfulness regression (runtime-boundaries.md:42, expense key
wording), one low test-pin gap, three info notes. Freeze claim verified byte-exact;
all DoD lines met (DoD-5's post-review tail — independent acceptance, merge, push,
roadmap note — pending by design at review time); all four scenarios pass; all five
gates, the full suite, rehearsals, the demo set and the serial installed verifier
rerun fresh and pass with exact counts.

## Findings (severity-ranked)

1. **MEDIUM — docs truthfulness regression: expense business-key wording made wrong.**
   `docs/runtime-boundaries.md:42` — the S15 edit of the `| operation | business key`
   row changed the expense description from "policy id + capability + document id +
   **document revision**" to "… + **document digest**". The expense family's key
   embeds the integer `document_revision` counter (`work_runtime/policy.py:147-149`;
   counter born at 1 in `work_runtime/runtime.py:358`, incremented at
   `runtime.py:408`), not the digest. The digest-embedding key belongs to the
   publishing family (`work_runtime/publishing.py:111-113`, correctly described in
   `docs/adapter-contract.md:377-378`). The row was accurate before this sprint;
   the sprint's edit made it factually wrong about the expense demo. No gate
   catches it (`check_docs.py` checks links). Suggested one-line fix at close-out:
   restore "document revision" for expense (and optionally name publishing's digest
   shape explicitly alongside the support-ticket clause).
2. **LOW — test pin gap: empty ticket reference (`id=""`) is never rejected by any test.**
   `tests/test_support.py:45-51` (`test_identity_strings_must_be_nonempty`) iterates
   `("ticket_reference", "summary")`, but the document field is `id`. The
   `ticket_reference` iterations construct a document with an *extra* field, so they
   raise via the exact-field-set rule (support.py:45-47) for the wrong reason; no
   test feeds `{"id": "", …}`. Deleting the nonempty check for `id` at
   `work_runtime/support.py:48-50` would not fail any test. The implementation is
   correct; only the pin is misdirected (the `summary` branch is meaningful).
3. **INFO — cross-work conflict test: second `admit()` is inert.**
   `tests/test_support.py:480-488`: `commands` dedupes on `PRIMARY KEY(actor, id)`
   globally (`work_runtime/runtime.py:113-116`) and the replay fingerprint embeds
   `work_id` (`runtime.py:262-268`), so the second `admit()` (command id
   `dispatch-once` reused on `ticket-2`) returns `COMMAND_ID_REUSED` and creates
   nothing. The cross-work conflict is genuinely exercised — and asserted — only by
   the final `dispatch-second` propose. Assertion set is meaningful (decision +
   `OPERATION_CONTENT_CONFLICT`); the dropped assertion removed in commit `5135947`
   was indeed a no-op. No product issue; a comment or a distinct command id would
   make the test read as intended.
4. **INFO — cosmetic.** Unused `folder` variable in two installer-proof tests
   (`tests/test_support_demo.py:163-165`, `172-174`); trailing whitespace at
   `tests/test_support.py:306`.
5. **INFO — coverage note.** Cross-work conflict pins the propose-time rejection
   (no second operation can exist — `runtime.py:689-690` rejects before creation);
   the tracker-level one-issue-per-reference constraint is separately pinned
   (`tests/test_support.py:318-337`) and by the installer proof. Together the two
   disclosed constraints are fully covered; no test asserts nothing (every test
   method in both new files carries real assertions).

## Dimension 1 — freeze evidence: VERIFIED

- `shasum -a 256` on the worktree: `work_runtime/runtime.py` =
  `80bf721b3369a6fb865fd6aba0e57804a69eb8587431f8fa6edf1183fc53f4b3`,
  `work_runtime/adapters.py` =
  `ce132f24d84c17a083bcf0b61bf90e1c62ff75faf2ec52fe2c7348ab86b6985e` —
  byte-identical to `main` (same hashes via `git show main:…`) and equal to the
  pins recorded in the wave-1 plan. `git diff --name-only 3e3ab7e..HEAD --
  work_runtime/runtime.py work_runtime/adapters.py` → empty.
- No lifecycle semantics moved or duplicated: `work_runtime/__main__.py` has a
  zero-line diff; `cli.py` diff is presentation-only (subparser `support-demo`,
  `inspect --policy support-ticket` choice, Runtime construction for inspect —
  `work_runtime/cli.py` diff hunks at the import block, subparser block, choice
  list, dispatch elif, inspect elif); `support_demo.py` drives only the public
  Runtime API (create_work / bind_contract / revise_plan / record_evidence /
  verify_pending / propose_action / dispatch / request_completion / recover);
  `support.py` is family-owned plugin code (policy + adapter) — its
  `TICKET_REFERENCE_CONTENT_CONFLICT` business rejection is adapter-domain
  semantics mirroring FakePublisher's `ORIGINAL_ABSENT`
  (`work_runtime/publishing.py:271`), not lifecycle duplication. No freeze-gap
  escalation was needed; the freeze verdict in `docs/runtime-boundaries.md`
  ("zero lifecycle edits") matches the observed diff.

## Dimension 2 — family correctness: VERIFIED

- **Unknown-blocking admission**: `None` severity/category ⇒ T01/T02 applicability
  `unknown` (`work_runtime/support.py:95-104`) ⇒ blockers ⇒ runtime rejects
  `APPLICABILITY_UNRESOLVED` (`runtime.py:668-672`); unknown severity also keeps
  T03 (SLA) applicability `unknown` (`support.py:105-111`) — unknown propagates to
  the dependent rule and blocks. Out-of-vocabulary strings are document
  `ValueError`s at validation (`support.py:51-55`), so an unknown string can never
  enter as within-policy. Tested: `tests/test_support.py:133-156`, `424-436`.
- **Ticket-reference business key, version-stable**:
  `operation_key = digest([id, capability, document["id"]])` (`support.py:141-147`)
  — no digest, no version; `SupportPolicyV2` inherits it untouched
  (`support.py:150-158`). Migration readmits the SAME operation id
  (`tests/test_support.py:559-581`); key recomputed independently in
  `tests/test_support.py:538-543`, `tests/test_support_demo.py:59-66` and the
  installer proof.
- **Conformance mixin**: `FakeIssueTrackerConformanceTests` — all six mixin cases
  run and pass, including the opt-in action-context replay (the tracker declares
  `supports_action_context=True`, `support.py:175-181`); fresh-run suite log shows
  6/6 `ok`, none skipped.
- **Crash recovery — original receipt by reference, never re-sent**: timeout-after-
  commit (`support.py:265-266`) → `outcome_unknown`; `reconcile` recovers via
  `adapter.lookup(business_key)` (`runtime.py:1105-1116`); real child process death
  (exit 73) after tracker commit via the runtime's own `fault` injection point
  (`runtime.py:1066-1067`), restart `recover()` → `confirmed_succeeded` with
  exactly one attempt, one issue, one receipt row: `tests/test_support.py:506-536`,
  `598-631`; demo chapter 2 and the installer store proof re-verify the same
  counts from SQLite.
- **One reference = one governed dispatch**: business-key collision with changed
  digest or different work ⇒ `OPERATION_CONTENT_CONFLICT` at propose time
  (`runtime.py:688-690`); same-work content revision (`tests/test_support.py:490-500`)
  and cross-work same reference (`480-488`) both pinned.

## Dimension 3 — test quality: 55 meaningful new tests

40 local in `tests/test_support.py` + 6 inherited conformance-mixin +
9 in `tests/test_support_demo.py` = 55; suite delta 1077 → 1132 confirms the
count. The two disclosed constraints are pinned at three independent layers
(unit key-shape, governed-flow conflict tests, installer store proof with
recomputed keys). Demo tests read SQLite directly rather than trusting stdout
(`tests/test_support_demo.py:35-75`), pin no-secrets via
`assertNotRegex(output, "[0-9a-f]{64}")` (line 42), and prove the installer
proof can fail on doctored output (lines 155-177). Findings 2 and 3 above are
the only quality gaps; no test asserts nothing.

## Dimension 4 — DoD conformance (each line, evidence)

- **DoD-1 (family end-to-end, byte-unchanged)**: MET. Forward flow
  propose→admit→dispatch→receipt→closure `tests/test_support.py:452-478`;
  unknown-blocking 424-450; result-unknown fencing 506-536, 598-631; hashes and
  diff evidence under Dimension 1.
- **DoD-2 (conformance mixin without lifecycle edits; unknown semantics)**: MET.
  6/6 mixin cases ok; family code all-new; unknown severity/category can never
  pass as within-policy (Dimension 2). "Unknown amount … within-limit" is the
  expense phrasing; the family equivalent holds and is tested.
- **DoD-3 (clean-clone demo, no secrets, installer stages same-commit, counts,
  skip deltas)**: MET. `support-demo` exit 0 in-checkout and via module+console
  stages in a fresh venv outside the checkout (`verify_install.py` PASS); output
  contains zero 64-hex digests and no credentials; stages 24/25 additive with
  "NEW coverage since S15" disclosed in the docstring and the final summary;
  demo+installer+docs+README+tests landed in one release commit `90483cb`; suite
  skips stay 2 (no delta) and the installer reported zero SKIPPED stages.
- **DoD-4 (deferrals hold, D94)**: MET. No `compensation_capabilities`
  (`support.py:42`; runtime gates pairing on it at `runtime.py:725`) ⇒ no
  compensation, hence no chains; link-carrying call refused (`support.py:222-224`,
  tested `tests/test_support.py:359-368`); runtime.py/`__main__.py` byte-unchanged
  ⇒ no new lifecycle commands; cli.py adds presentation wiring only.
- **DoD-5 (gates/suite/demo set/rehearsals/installed verification; acceptance
  precedes merge; truth docs + roadmap note)**: MET up to the review boundary.
  All rerun fresh, results below. Truth docs landed same-commit (`90483cb`).
  Independent acceptance = this review; the integration-owned ordinary merge,
  non-force push and the master-owned roadmap 0.2 note follow it by design
  (sprint D4). The doc-sync audit is clean: no `doc_sync_map` row fired (none of
  the mapped files appear in the sprint diff).

## Dimension 4b — scenarios S1–S4 (each, verdict)

- **S1 Family admission: PASS.** Unknown severity/category blocks
  (`APPLICABILITY_UNRESOLVED`, blockers T01/T03 resp. T02 —
  `tests/test_support.py:424-436`); resolved-but-no-SLA and wrong-budget SLA
  block `REQUIREMENT_UNSATISFIED` (438-450); business-key dedupe/replay returns
  the same operation id (459-463); standard dispositions include
  `WORK_NOT_ACTIONABLE` after closure (475-478). No new rejection codes —
  structurally guaranteed by the byte-identical runtime; the codes used all
  pre-exist in it. "Unknown never passes" appears verbatim in the demo chapter
  and the T01/T02 explanations.
- **S2 Dispatch, reconcile, crash recovery: PASS.** Forward dispatch to the
  GitHub-issue-shaped tracker (receipt `#1`, `issue_state "open"`), closure ack
  (452-478); crash-after-acceptance: real exit-73 child, restart recovers by
  ticket reference, original receipt, never re-sent (598-631; attempts/issues/
  receipts all exactly 1); timeout reconcile equivalent (506-536); result-unknown
  machinery semantics unchanged (byte pin).
- **S3 Boundary pins: PASS.** Hashes equal across the sprint and to main (above);
  conformance mixin 6/6; no lifecycle-edit need arose, so no freeze-gap record
  was required — the zero-edit outcome is the disclosed verdict in
  runtime-boundaries.md.
- **S4 Demo, docs, release: PASS** (with Finding 1 noted). Exact counts
  (FINAL_LINE) asserted from both stores; skip deltas explained (none in suite,
  none in installer); no secrets; installer stages additive + NEW disclosure;
  five gates verbatim; full suite; rehearsals; serial installed verification;
  doc-sync audit clean; this acceptance precedes the push.

## Dimension 5 — docs truthfulness

- `docs/adapter-contract.md` S15 section: every claim matches code (contract
  tuple, store schema, alias reuse, `TICKET_REFERENCE_CONTENT_CONFLICT` carrying
  the owning issue number, link refusal, key shape) — verified line-by-line
  against `work_runtime/support.py`.
- `docs/verification.md`: counts accurate (46 + 9 tests, 1132 total, stages
  24/25, NEW disclosure); "no protocol matrix row is added" consistent with the
  byte-identical runtime.
- `docs/runtime-boundaries.md`: freeze verdict and the two disclosed constraints
  are accurate; **except Finding 1** (expense key wording regression in the same
  edited row).
- README bilingual parity: en/zh sections carry the same facts (ninth demo,
  freeze verdict with pins referenced, both chapters, one-reference-one-dispatch,
  `TICKET_REFERENCE_CONTENT_CONFLICT`/`OPERATION_CONTENT_CONFLICT`, no
  credentials), same links. No secrets anywhere in the new docs/tests.
- Installer: stages 24/25 purely additive (no existing stage modified apart from
  the appended summary sentence); docstring stage list consistent with `main()`.

## Dimension 6 — gates rerun (actual outputs)

| gate | command | result |
|---|---|---|
| contracts | `python3 scripts/check_docs.py` | `checked 118 markdown files, 596 local links, 0 broken`, exit 0 |
| tests | `python3 -m unittest discover -s tests -v` | `Ran 1132 tests in 43.332s` / `OK (skipped=2)`, exit 0 (baseline 1077/2 + 55 new; skip delta zero: the 2 skips are the pre-existing non-opted-in conformance context test and the ui absent-backend test) |
| demo | `python3 -m work_runtime demo` | exit 0, recovery chapter ends `SUCCEEDED; external applications created: 1` |
| syntax | `python3 -m compileall -q work_runtime tests scripts` | silent, exit 0 |
| site | `python3 scripts/check_site.py` | `checked 2 pages, 0 findings`, exit 0 |
| (convention) rehearsals | `python3 -m unittest discover -s examples/rehearsal` | `Ran 15 tests in 0.054s` / `OK (skipped=1)` |
| (convention) demo set | demo, publish-demo, publication-demo, revocation-demo, compensation-demo, rotation-demo, support-demo in-checkout | all OK |
| installed verification | `python3 scripts/verify_install.py` | `=== PASS === … (9.6s)`, exit 0, zero SKIPPED stages; stages 24/25 ran module+console support-demo with the independent store proof and verbatim printed-inspect re-runs; summary discloses "BOTH stages are NEW coverage since S15" |

`support-demo` stdout: `2 works; issues filed: 2; crash-recovered receipts: 1;
effects re-sent: 0`; `grep -cE "[0-9a-f]{64}"` on the output = 0 (no digests, no
credentials). Worktree left clean (`git status --porcelain` empty after all runs).
