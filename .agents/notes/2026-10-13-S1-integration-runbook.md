# S1 integration runbook — 2026-10-13

Owner: the independent integration session (E1/S1). Scope: assemble the two
developer branches into the carrier `WayJ/sprint-s1-preview`, run acceptance,
merge into `main`, publish, and clean up. This runbook is binding for the S1
release: every step below is executed in order, and no step may be skipped or
reordered without a coordinator decision recorded in this directory.

## Hard requirements

1. **Acceptance before main merge.** The sprint may be merged into `main` only
   after a passing `supervibe:accept` run has written an acceptance record under
   `docs/superpowers/acceptances/` and flipped the sprint frontmatter
   `state: active → acceptance`. No record, no merge. A blocked verdict returns
   the sprint to execution; it never proceeds to merge.
2. **Never force-push.** `main` is published only with a normal
   `git push origin main`. Before pushing, `git fetch origin` and compare
   `origin/main` with the local `main`: if the remote moved, integrate the
   upstream change first (merge or rebase the local work onto it) and re-run
   the ordered gates before pushing. `--force` is never used on any branch.
3. **Remote SHA verification.** Immediately after the push,
   `git ls-remote origin refs/heads/main` must print exactly the SHA of the
   local published `main` HEAD. Release completion is reported only after this
   evidence exists; a push that cannot be shown in the remote ref is treated as
   not pushed.
4. **Ordered gates before acceptance** (run in the carrier, fresh):
   `python3 scripts/check_docs.py` (zero findings required in the assembled
   tree — the pre-integration pending-link allowance is gone),
   `python3 -m unittest discover -s tests -v` (63 tests expected: 35 baseline +
   12 boundaries + 16 docs), `python3 -m work_runtime demo` (exit 0, exactly one
   external application), `python3 -m compileall -q work_runtime tests scripts`,
   and `python3 scripts/verify_install.py` (fresh venv, real install, module and
   console demos outside the checkout).
5. **Same-commit doc_sync.** Every commit touching `work_runtime/runtime.py` or
   `work_runtime/adapters.py` must also touch `docs/runtime-boundaries.md`;
   every commit touching `scripts/check_docs.py` must also touch
   `CONTRIBUTING.md`. Verified per developer branch before merging; the
   integration session's own commits obey the same map.
6. **Cleanup only after publication is verified.** Developer worktrees and
   terminals are retained (Orca user/external ownership — recorded here as the
   reason they are not torn down by this session). The integration session does
   not remove its own active checkout before `worker_done`; if that makes the
   carrier impossible to remove safely, the removal is deferred and reported to
   the coordinator for after settlement.

## Steps

0. **Preconditions.** Carrier clean at the sprint tip; both developer branches
   reviewed inline (scoped plan, RED/GREEN report, full diff, ownership
   disjoint, no out-of-scope edits); merge-base confirmed against the sprint
   line.
1. **Commit this runbook** to the carrier.
2. **Assemble:** `git merge --no-ff WayJ/s1-runtime-boundaries` then
   `git merge --no-ff WayJ/s1-contributor-preview` into the carrier. Any
   conflict is a stop-and-escalate event, not something to resolve silently.
3. **Post-assembly coherence pass** (docs-only, no behavior edits, no invented
   TDD): fix prose that the integration itself made stale; re-run the contracts
   gate.
4. **Gates:** all five commands from hard requirement 4, fresh, in the carrier.
5. **Accept:** `supervibe:accept S1` — every scenario S1–S5 run for real, DoD
   checked against fresh evidence, doc-drift audit against `### doc_sync_map`,
   obstacles recorded verbatim; acceptance record written; state flipped to
   `acceptance` only on proven pass.
6. **Merge:** `supervibe:merge S1` — ordered gates re-run, same-commit doc_sync
   check, sprint tip captured, carrier merged into `main` in the main checkout
   (`git -C /Users/jiangwei/projects/governed-agentic-work-runtime`, clean tree
   required, `git fetch origin` first, upstream handled per hard requirement 2),
   sprint frontmatter finalized (`merged-commit`, closing note in main).
7. **Publish:** `git push origin main` from the main checkout; then
   `git ls-remote origin refs/heads/main` must equal local `main` HEAD. Record
   SHA and repository URL as publication evidence.
8. **Settle:** cleanup per hard requirement 6, `orca orchestration check`, then
   `worker_done` with the report and explicit success/failure.
