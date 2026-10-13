# S2 content publication developer report — 2026-10-13

Orca dispatch `task_b0d48106cc6d` (ctx_e6b30c619164), worktree `s2-content-publication`,
branch `WayJ/s2-content-publication`. Scope plan:
`docs/superpowers/plans/2026-10-13-s2-content-publication.md` (commit 62db94d). Baseline:
foundation-integrated carrier `9c493cc` (130 tests, docs 27/84/0, demo green) — verified
before any edit. No merge, no push; integration session owns them.

## Ownership confirmation

Changed files (all inside the dispatch ownership list):
`work_runtime/publishing.py` (new), `work_runtime/publishing.py` → also contains FakePublisher,
`work_runtime/publishing_demo.py` (new), `work_runtime/cli.py`, `tests/test_publishing.py` (new),
`README.md`, `README.zh-CN.md`, `CONTRIBUTING.md`, `docs/verification.md`, `docs/roadmap.md`,
`scripts/verify_install.py`, `.github/workflows/ci.yml`, the scoped plan and this report.
No Runtime/adapter_contract/adapters/ingress/demo edits, no baseline-test edits, no
`work_runtime/__init__.py` change (module-path imports only), no sprint/epic edits.

## RED/GREEN evidence (observed, Python 3.9.6)

### Task 2 — PublishingPolicy

RED (`python3 -m unittest discover -s tests -p test_publishing.py -v`):

```
    from work_runtime.publishing import PublishingPolicy
ModuleNotFoundError: No module named 'work_runtime.publishing'
Ran 1 test in 0.000s
FAILED (errors=1)
```

GREEN after implementing the policy: `Ran 16 tests ... OK`; full suite `Ran 146 tests ... OK`.
One intermediate failure was a wrong test expectation, not a code defect:
`test_action_blockers_track_applicability_and_exclude_accepted_rule` expected `['C02']` where
`['C02','C03']` is correct (C03 blocks without confirmation); expectation fixed, code unchanged.

### Task 3 — FakePublisher

RED:

```
ImportError: cannot import name 'FakePublisher' from 'work_runtime.publishing'
```

GREEN: `Ran 27 tests ... OK` (16 policy + 5 mixin + 6 domain); full suite `Ran 157 tests ... OK`.

### Task 4 — Runtime flow tests

Integration characterization: all flow tests green on first run — the underlying behaviors had
their RED in the Task 2/3 module cycles, and the Runtime foundation needed no change (no
interface defects found; nothing escalated). `Ran 36 tests ... OK`; full `Ran 166 ... OK`.

### Task 5 — publishing demo

RED:

```
ModuleNotFoundError: No module named 'work_runtime.publishing_demo'
```

One intermediate failure: the story-line test expects the literal rejection code; fixed by
printing `EVIDENCE_AUTHENTICATION_FAILED` on demo line 2 (inspectability; logic unchanged).
GREEN: `Ran 38 tests ... OK`; full `Ran 168 ... OK`.

### Task 6 — CLI

RED (subprocess, exit 2):

```
__main__.py: error: argument command: invalid choice: 'publish-demo' (choose from 'demo', 'inspect', 'worker')
__main__.py: error: unrecognized arguments: --policy content-publish
```

GREEN: `Ran 42 tests ... OK`; full `Ran 172 ... OK`; `python3 -m work_runtime demo` still green
(expense demo/worker unchanged; `inspect` default policy byte-equivalent path).

### Task 7 — installed verification (RED against the base, GREEN here)

Modified `scripts/verify_install.py` first added the publication stage, then was run against a
`git archive 9c493cc` extraction of the unmodified carrier (temp dir, disposed after):

```
independent check: fake OA accepted applications = 1
=== module publish-demo outside the checkout ===
FAILED (exit 2): .../venv/bin/python -m work_runtime publish-demo
```

i.e. the new stage genuinely detects a missing publication demo (non-vacuous check). On this
checkout: full `=== PASS ===` including `independent check: published artifacts = 1`.
CI gains `python -m work_runtime publish-demo` after the expense demo step.

## Final gates (all observed on the final tree, 2c7ab72)

| gate | command | result |
|---|---|---|
| tests | `python3 -m unittest discover -s tests` | Ran 172 tests, OK |
| contracts | `python3 scripts/check_docs.py` | 29 markdown files, 93 local links, 0 broken |
| demo | `python3 -m work_runtime demo` | all 6 steps, `external applications created: 1` |
| publication demo | `python3 -m work_runtime publish-demo` | all 6 steps, `published artifacts: 1` |
| syntax | `python3 -m compileall -q work_runtime tests scripts` | clean |
| installed | `python3 scripts/verify_install.py` | PASS; OA accepted = 1 and publications = 1, both counted independently of printed output |
| printed inspect | exact command from publish-demo output + `--policy content-publish` | JSON: goal `content.published`, status `closed`, 9 events |

(A clean checkout reports 28 markdown files for the contracts gate: file 29 locally is the
git-ignored SDD ledger; it contains no links and CI never sees it.)

## Named behavior evidence (tests/test_publishing.py, 42 tests)

- Unknown review blocks: `test_review_rule_applicability_matrix` (policy) +
  `test_unknown_review_state_blocks_with_applicability_unresolved` (runtime, `APPLICABILITY_UNRESOLVED`).
- Plan edits cannot remove review: `test_plan_content_cannot_remove_review_requirement` +
  `test_plan_revision_cannot_remove_review_requirement`.
- Content revisions invalidate approval/confirmation: policy `test_old_digest_evidence_leaves_rules_pending`;
  runtime `test_content_revision_invalidates_approval_and_confirmation` (requirements pending again,
  old-digest re-approval still pending, stale prepared operation cancelled `STALE_INTENT`).
- Non-publisher proof does not satisfy the goal: `test_wrong_source_does_not_satisfy_rules`
  (evaluate-level source binding for C02/C03/C04, including accepted-kind proofs from non-publisher sources).
- Tampered signed approval rejected before intake: `test_tampered_signed_approval_is_rejected_before_intake`
  (all six runtime tables unchanged); demo line 2 shows it live.
- Signed evidence stays candidate until `verify_pending`: `test_signed_evidence_stays_pending_until_verification`,
  `test_full_goal_completion_with_one_publication`.
- Timeout-after-commit recovery, never resend: `test_timeout_after_commit_recovers_by_lookup_without_resend`
  (execute called once, reconcile by lookup only, one attempt, one publication, completion accepted).
- Malformed responses: `MalformedResultTests` — six variants (None, string, missing/empty
  `external_id`, wrong digest, bad status), each on an isolated runtime+publisher fixture with a
  counting wrapper asserting the real `execute` ran once, the artifact committed, the operation
  quarantined `outcome_unknown`/`ADAPTER_RESULT_INVALID`, work `needs_attention`, no accepted proof.
- Conformance: `FakePublisherConformanceTests` adopts the shared `AdapterConformanceMixin` with
  real disposable per-test SQLite fixtures; `effect_count` = `published_count`.
- Uniqueness/versions: `test_duplicate_content_under_another_key_reuses_external_id_and_one_artifact`
  (2 receipts, 1 publication, same external id), `test_changed_content_under_another_key_adds_a_publication_version`,
  `test_same_key_different_content_raises_without_new_effect` (counts unchanged after the raise).
- Demo/CLI: `PublishingDemoTests` (story lines, independent `SELECT COUNT(*) FROM publications` = 1,
  repeatability, no 64-hex secret/signature material in output), `PublishingCliTests`
  (publish-demo exit 0; `inspect --policy content-publish` reads the closed work; default policy
  unchanged on an expense database; unknown choice exits 2).

## Commits (this dispatch)

| sha | subject |
|---|---|
| 62db94d | docs(plan): scoped S2 content publication plan |
| a555a3f | feat(publishing): PublishingPolicy document/evidence/rules for content publication |
| f9dad46 | feat(publishing): FakePublisher with (document_id,digest) artifact uniqueness |
| a4cf914 | test(publishing): runtime flow, malformed-result quarantine and timeout recovery |
| 9f8bbf2 | feat(publishing): deterministic signed-evidence publication demo harness |
| 5ce43c7 | feat(cli): publish-demo command and policy-aware inspect |
| c711e18 | feat(verify): installed publication demo verification and CI smoke |
| 19f6e14 | docs(publishing): S2 publication coverage in READMEs, contributing, verification and roadmap |
| 2c7ab72 | test(publishing): move unittest main block to end of file (self-review fix) |

## Remaining risks / limitations (stated, not hidden)

- Wrong-source accepted proofs are pinned at the policy-evaluate level with synthetic proof lists;
  through the real Runtime the path is unreachable by construction (intake enforces the configured
  source per kind). This mirrors the spec's defense-in-depth intent.
- C01 is structurally always satisfied because document validation already enforces nonempty
  title/body; it is kept as a displayed defense-in-depth rule (same pattern as E01 for sealed sets).
- `FakePublisher` raises `TimeoutError` on replay too when constructed with
  `timeout_after_commit=True` — identical to FakeOA's established semantics; recovery uses lookup.
- The installed verifier's publication stage covers the module entry point (plus independent DB
  count); the console entry point is exercised for the expense demo as before.
- `verify_install.py` still needs pip index access for the build backend (pre-existing constraint).
- Docs describe tested scope only: HMAC authenticates evidence sources within a shared-key
  boundary (not business truth/TLS/tenant auth), `accepted` kind is refused at ingress, adapter
  descriptors are claims, direct Runtime is trusted-local, one policy per database, P13 deferred,
  and the harness is a command-protocol integration example, not a model-framework/server claim.

## Self-review note

Inline execution without nested agents (dispatch constraint): one deliberate self-review pass
over the whole branch diff was performed (ownership footprint, transaction logic, review-focus
coverage). The independent review belongs to the queued S2 integration session.
