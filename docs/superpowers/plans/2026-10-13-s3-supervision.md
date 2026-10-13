# S3 supervised execution plan

> Execution owner: Orca Claude Code worktree sessions using superpowers inline + TDD; master coordinates only. Authoritative behavior is [S3 design](../specs/2026-10-13-s3-intervention-design.md), D15 is ratified before code. Sprint contract remains [S3](../sprints/2026-10-13-S3-plan.md).

## Files and ownership

- Master: E3 epic, S3 sprint scaffold, design/decisions and this supervision plan in sprint carrier; no product coding, merging or pushing.
- Core developer (s3-intervention-core): runtime.py, optional focused helper, ExpensePolicyV2 in policy.py, test_interventions.py, interventions.md and same-commit runtime-boundaries.md; only baseline unsupported-kind probe amendment permitted.
- Integration (s3-release-control): independent reviews, report merges into carrier, acceptance/ledger/closing evidence, main merge and push. No lifecycle fixes; original developer owns corrections.
- Dependent demo developer (fresh tree from reviewed carrier): intervention_demo.py, cli.py, test_intervention_demo.py, verify_install.py/CI, READMEs/CONTRIBUTING/verification/roadmap and own report. No runtime edits.

## Task 1 — builder check and ratification

Report c84ac61 confirms baseline172 and implementation feasibility. Root fe81e98 records B1/B2, constructor policies signature, source-aware migration/verification, exact errors, demo v2 and explicit inspection registry. Complete before developer dispatch.

## Task 2 — core TDD

Worker writes a scoped bite-sized plan: one observed RED test group then minimal GREEN per registry/owner/cancel/migration unit, frequent owned commits. Test actual SQLite transaction rollback and adapter count rather than implementation mirrors. Use current baseline for intentional failure evidence. Each runtime.py change owes runtime-boundaries.md in SAME commit. Output includes test names, count, commands/results, SHA and scope limits. Never merge/push.

## Task 3 — foundation review/integration

Integration reviews against fe81e98, reproduces meaningful failures without modifying baseline expectations, verifies sanctioned probe amendment only, merges c84ac61 report and accepted corrected core tip into carrier, fresh gates and both existing demos. Output foundation report and stable interface tip. Developer fixes any actual defects via new scoped Dispatch, no competing editors.

## Task 4 — dependent demo TDD

Only after Task3 succeeds, create Claude Code child from assembled carrier. Use settled command/policy registry interfaces. Add no-credentials intervention-demo exercising owner transfer, ambiguous external acceptance followed by query and exact acknowledgement before cancellation close, and stronger demo-2 migration with old proof invalidation/new approval. Verify independent external count1. Add strict opt-in inspect --policy-versions for expense family, preserving defaults; test installed outside checkout in fresh venv and actual independent effect counts. Publish honest boundary docs and observed RED/GREEN report.

## Task 5 — release review/accept/merge

Integration independently reviews demo, merges into carrier, executes ALL six scenarios and VERBATIM epic DoD, configured gates plus three demos and fresh installed verification. Record append-only acceptance; active→acceptance only on pass. Ordered merge follows gate/verdict/capture-tip/main merge/clean merged carrier teardown/ledger/closing note. Preserve external-owned developer/controller worktrees. Ordinary non-force push, existing SSH same-origin fallback if recorded HTTPS workflow-scope refusal, ls-remote equality plus origin refresh, actual GitHub CI for published SHA before delivery.

## Verification commands

`python3 scripts/check_docs.py`; `python3 -m unittest discover -s tests -v`; `python3 -m work_runtime demo`; `python3 -m work_runtime publish-demo`; `python3 -m compileall -q work_runtime tests scripts`; `python3 scripts/verify_install.py`. After harness exists add `python3 -m work_runtime intervention-demo` and printed inspection command with explicit registry. Run in actual carrier/main as appropriate, record true exits and counts. Root independently checks final main and remote evidence after integration-owned publication.
