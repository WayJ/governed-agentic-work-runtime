# S14 W2 demo report — publish-demo retraction chapter + installer stages + docs

Worker: S14 W2 demo/docs development, worktree `s14-compensation-demo`
(`WayJ/s14-compensation-demo`), dispatched off the sprint carrier
`WayJ/sprint-s14-publishing-compensation` at exact
`2181471f7ae92db56a579bcdb442f3decf421ceb` (verified by `git rev-parse`,
tree clean; the worktree branch carries that baseline commit verbatim).
Scoped plan committed before code at `1a314d5`
([plan](../docs/superpowers/plans/2026-10-16-s14-demo.md)); executed
task-by-task with observed RED before minimal implementation. Read the W1
MUSTREADs before coding (core integration review stable-W2-API section and
core report incl. the option-A supersession record); design MASTER
ratification D80–D91 read in full, D90 SETTLED structure (b) implemented.

## Commits (this branch, newest last)

| commit | content |
|---|---|
| `1a314d5` | docs: S14 W2 scoped implementation plan |
| `8543164` | feat: publish-demo retraction chapter (D90 b) with demo grants, focused tests and truth docs |
| `d0c09fa` | feat: verify_install publish-demo module-stage update + NEW console stage (new coverage, disclosed) |
| (this commit) | test/docs: S14 W2 demo report + verification coverage section |

Changed files `2181471..HEAD`: exactly 9 — `work_runtime/publishing_demo.py`,
`tests/test_publishing_compensation_demo.py` (new, 18 tests),
`tests/test_publishing.py` (two authorized in-place demo-test updates),
`scripts/verify_install.py`, `README.md`, `README.zh-CN.md`,
`docs/interventions.md`, `docs/verification.md`, the plan.
`git diff 2181471 -- work_runtime/publishing.py work_runtime/publication.py
work_runtime/runtime.py work_runtime/adapters.py
work_runtime/file_adapter.py work_runtime/policy.py work_runtime/cli.py
work_runtime/publication_demo.py work_runtime/demo.py` → **empty** (W1
frozen surface untouched, verified).

## RED/GREEN evidence per task

- **Task 1 (demo chapter)** — RED: `python3 -m unittest
  tests.test_publishing_compensation_demo -v` → `Ran 12 tests … FAILED
  (failures=11)` with exactly the predicted natures (`FINAL_LINE … not
  found` against the six-line work-one-only output; `0 != 2` operations for
  article-2; publication/retraction counts 1/0 vs 2/1; grants set without
  `content.unpublish`). The single passing test was
  `test_secrets_never_printed` — a pre-existing-invariant guard that pins
  behavior the old demo already had. GREEN after the minimal chapter +
  grants widening: 12/12; `tests.test_publishing` +
  `tests.test_publishing_compensation_demo` → `Ran 55 tests … OK`; full
  battery `Ran 1071 tests … OK (skipped=2)` (1059 + 12).
- **Task 2 (installer)** — RED: `VerifyInstallPublishingProofTests` →
  `Ran 6 tests … FAILED (errors=6)`, all
  `AttributeError: module 'verify_install' has no attribute
  'require_publishing_proof'`. GREEN: 18/18 with the six mutation tests
  proving the proof reads stores, not stdout (deleted retraction row,
  deleted ART-002 publication, flipped withdrawn→accepted proof kind,
  forged single-id closure ack, stripped final line each rejected); battery
  `Ran 1077 tests … OK (skipped=2)`; serial verifier `=== PASS ===`.

## Final verification battery (verbatim counts)

- `python3 -m unittest discover -s tests -v` → **`Ran 1077 tests … OK
  (skipped=2)`** (baseline 1059 + 18 new). Exact skips, names unchanged from
  the W1-assembled baseline:
  `test_file_adapter.FilePublisherConformanceTests.
  test_opted_in_action_context_replay_returns_identical_receipt` (designed
  skip — D88 FilePublisher stays forward-only) and
  `test_ui_cli.AbsentBackendTests.
  test_absent_backend_is_a_bounded_startup_error` (pre-existing).
- Five AGENTS gates VERBATIM, command list unchanged: committed-tree
  `python3 scripts/check_docs.py` (run from a `git archive HEAD` extraction)
  → **`checked 115 markdown files, 584 local links, 0 broken`**; the
  unittest gate → OK (skipped=2); `python3 -m work_runtime demo` → exit 0;
  `python3 -m compileall -q work_runtime tests scripts` → clean (run in the
  working tree and the committed extraction); `python3 scripts/check_site.py`
  → `checked 2 pages, 0 findings`.
- Eight demos exit 0: `demo`, `publish-demo` (now including the retraction
  chapter), `intervention-demo`, `adoption-demo`, `revocation-demo`,
  `compensation-demo`, `rotation-demo`, `publication-demo`.
- Rehearsals `python3 -m unittest discover -s examples/rehearsal` →
  `Ran 15 tests … OK (skipped=1)` (pre-existing generic opt-in conformance
  skip).
- `python3 scripts/verify_install.py` serial → **`=== PASS ===`**, exit 0,
  **zero SKIPPED lines**; both new stages present — `=== module publish-demo
  outside the checkout ===` (prints `independent check: published artifacts
  = 2, retraction effects = 1; recomputed keys, immutable link,
  withdrawn-kind proof, exact two-id closure and both printed inspect
  commands re-run verbatim`) and `=== console publish-demo outside the
  checkout ===` with the same independent store proof; the installed UI
  stages ran (no backend skip). Python ≥ 3.9 (developed and verified on
  3.9), stdlib only, zero runtime dependencies, runtime store schema 1.

## What shipped (ratified mapping)

- **D90 SETTLED structure (b)** — work one's printed steps 1–6 stay
  byte-identical (the succeeded-completion story, asserted by name in the
  tests and by the installer proof via article-1 `closed/succeeded`); the
  chapter APPENDS on the same store pair as steps 7–12 plus a one-line
  chapter header: second document `ART-002` as work `article-2` through the
  same signed gateway → clean confirmed publish (publications 2); owner
  `request_cancel` (window opens; the confirmed publication untouched);
  linked `content.unpublish` proposal (five-key payload, immutable
  `{operation_id, external_id, capability}` snapshot, D6 key
  `digest(["content-publish", "content.unpublish", target])` recomputed
  independently by tests and installer); a real grants-carrying child
  subprocess dispatches with `fault=lambda: os._exit(73)` — the external
  retraction commits (`RTR-…`) and the child dies before recording (the
  shipped `worker` CLI cannot take this step: expense demo grants + FakeOA
  adapter); restart + `recover()` confirms in exactly one attempt; the
  withdrawn proof appends at source `publisher` while the original
  publication, receipt and accepted proof stay intact (C04 still satisfied);
  `finalize_cancel` with the exact two-id ack → `closed`/`cancelled` with
  the compensation disposition carrying `compensates` + `adapter_result`.
  Closing counts **`published_count == 2, retracted_count == 1`** asserted
  in-demo by direct `sqlite3` reads (plus the withdrawn-proof row), never
  parsed from stdout; final line `2 works; published artifacts: 2;
  retraction effects: 1; bounded in-window retraction, not reversal`; two
  printed `inspect` commands (both works) re-run verbatim by tests and the
  installer (per-work outcome markers succeeded/cancelled).
- **D83 demo grants** — `publishing_grants()` agent set gains
  `content.unpublish` (owner authority; `request_cancel`/`finalize_cancel`
  by the owner under `work.manage`, no new actor).
- **Installer same-commit** — `PUBLISH_FINAL_LINE` updated; module stage now
  `require_publishing_proof` (both stores read directly: counts 2/1,
  document ids ART-001/ART-002, tagged retraction receipt with recomputed
  link digest, retraction row bound to the original, recomputed keys,
  one-attempt PUB-/RTR- operations, accepted + withdrawn proofs, exact
  two-id closure, disposition shapes) + `run_printed_publish_inspects`;
  **NEW console stage** `work-runtime publish-demo` with the same proof,
  disclosed as new coverage in the stage docstring (stages renumbered 1–23)
  and the `=== PASS ===` summary. `count_retractions` added.
- **Bilingual README + truth docs** — publish-demo section (chapter
  narrative, story lines, counts 2/1, limits: bounded active-window
  retraction not reversal; trusted-local principals not authentication;
  re-publish-after-retraction unreachable through the governed flow, binds
  the adapter model), the now-stale "publishing compensation …
  unimplemented" phrases fixed in the compensation section, features bullet,
  limits paragraph and milestone paragraph (en + zh mirrors); zh verifier
  paragraph drops "`publish-demo` 没有控制台阶段"; `docs/interventions.md`
  names the chapter in the S10/S14 compensation-exception paragraph;
  `docs/verification.md` demo sentence, installer sentence and S14 coverage
  section updated. No `doc_sync_map` row fires (D91 — truth updates only).
- Protected scope untouched (see commit census above); no UI/site/AGENTS/
  roadmap/sprint change; `roadmap.md` 0.3 stays master-owned close-out
  (MD-4).

## Disclosures

1. **Two authorized in-place updates in `tests/test_publishing.py`:** the
   demo story test gains the chapter markers (`published artifacts: 2`,
   `retraction effects: 1`, `exit code 73`) and its store reads change 1 →
   2 publications + 1 retraction; the repeatability test reads 2/1 per run.
   No other line in that file changed; its CLI test asserting `published
   artifacts: 1` still passes because work one's step-6 line prints
   verbatim (that is work one's story at that point, not the final line).
2. **Grant widening ripple:** `publishing_grants()` is imported by
   `work_runtime/adoption_demo.py`, `work_runtime/cli.py` (`inspect
   --policy content-publish`) and four test modules — behaviorally inert
   there (nothing proposes `content.unpublish` in those flows), proven by
   the untouched full battery passing and the installed verifier's
   adoption/revocation/intervention stages re-running green from a fresh
   install.
3. **`alias` receipts and `ORIGINAL_ABSENT` are not probed in the chapter**
   (the dispatch listed them as "if probed"): both are unreachable through
   the governed flow — the D6 business key admits exactly one governed
   retraction per original (an alias needs a second, different key), and a
   known-absent original needs a second store that never saw the forward
   receipt. They stay pinned where they are reachable: W1
   `RetractionExecutionTests` (store level) and the compensation-demo
   refusal scenario. Demonstrating them here would require direct adapter
   calls, which the demo deliberately never makes.
4. **Final whole-branch review is a documented self-review** (executed
   against the plan's Review Focus list): the dispatch forbids extra
   agents, so no fresh-context subagent reviewer ran — the sprint's
   independent review/acceptance waves remain the independent eyes on this
   work, as in W1.
5. **Honest counts:** the committed-tree `check_docs` number is 115 files /
   584 links / 0 broken (measured from `git archive HEAD`, avoiding the
   W1 mi-1 working-tree overcount); the working tree with untracked notes
   reports more files, the gate passes either way.

## Remaining risks / honest limits

- Bounded slice only: active-cancellation-window retraction, not reversal;
  post-closure compensation, chains, cross-work compensation, intervener
  authority and a public abandon command remain unimplemented. The original
  publication, receipt, accepted proof and closure history are never
  rewritten.
- Re-publish-after-retraction is unreachable through the governed flow
  (permanent-intent `CANCELLATION_ACTIVE` same-work; store-global forward
  business key `OPERATION_CONTENT_CONFLICT` cross-work) — the interplay
  binds the fake-publisher adapter model only (RF4 reachability note).
- Trusted-local only: principals are grants configuration, not
  authentication; no tenant model, TLS, KMS, network or distributed
  exactly-once claim; the fake publisher remains a local stand-in; no
  secrets are printed (synthetic ephemeral material, fresh keys per run,
  `assertNotRegex("[0-9a-f]{64}")` on the demo output).
- The `content.unpublish` (content family) vs `sop.withdraw` (SOP authoring
  family) naming distinction is kept everywhere (F10).
- No main merge, no push, no sprint flip, no release claim — independent
  final acceptance and the integration-owned main merge are the next
  master dispatches. `roadmap.md` 0.3 close-out note is master-owned
  (MD-4).
