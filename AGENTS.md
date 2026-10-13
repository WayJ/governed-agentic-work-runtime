# Project working agreement

The coordinator owns roadmap, dispatch, supervision and acceptance decisions. Development and integration happen in separate Orca worktree sessions. The integration worker owns merges and pushes; the coordinator must not merge sprint branches itself.

## Execution

- Use superpowers workflows and TDD for all behavior changes: write a meaningful failing test, observe failure, implement minimally, rerun, and record RED/GREEN evidence.
- Read the assigned sprint and its RFC references before coding. Write a scoped implementation plan, then use executing-plans. User has explicitly requested autonomous supervised execution; do not open a local approval/question UI. Ask the coordinator through Orca orchestration for blocking decisions.
- Keep Python >=3.9 and zero runtime dependencies. Use standard-library unittest.
- Work only in the assigned checkout and ownership scope. Commit scoped changes and report commit hashes, test evidence, remaining risks. Do not spawn extra workers without coordinator approval.
- Development workers never merge main or push. The integration session alone accepts, merges and pushes each sprint. Never force-push main.
- Existing idea.md and 上一次建议.md are historical source material, not executable instructions.
- Distinguish local trusted principals from authentication; do not claim distributed exactly-once, production safety, or unsupported RFC coverage.

## supervibe
- roadmaps_dir: docs/superpowers/roadmaps/
- sprints_dir: docs/superpowers/sprints/
- acceptances_dir: docs/superpowers/acceptances/
- notes: .agents/notes/
- debt_tracker: docs/tech-debt-tracker.md
- wip_limit: 1
### gates
- contracts: python3 scripts/check_docs.py
- tests: python3 -m unittest discover -s tests -v
- demo: python3 -m work_runtime demo
- syntax: python3 -m compileall -q work_runtime tests scripts
### doc_sync_map
| change | owes |
|---|---|
| work_runtime/runtime.py | docs/runtime-boundaries.md |
| work_runtime/adapters.py | docs/runtime-boundaries.md |
| scripts/check_docs.py | CONTRIBUTING.md |
