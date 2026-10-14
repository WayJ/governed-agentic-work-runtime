# S5 release evidence — 2026-10-14

Publication record for sprint S5 (close-out `cd61c24`), matching the S3/S4 release-evidence
pattern. Recovery context: the authoritative integration run `ctx_aeb00f9dee7d` was
interrupted after its merge landed but before close-out/push (it removed its own carrier
during teardown and its terminal closed, `operator_close` 2026-10-14T04:13:19Z); this
recovery session (`run_3cfa469282e2`, worktree `s5-release-recovery` based on main, task
`task_14f51c6944fa` dispatch `ctx_ef0256f5d63b`) completed the ledger close and this
publication without re-merging product or re-running the preserved acceptance evidence
(`.agents/notes/2026-10-14-S5-release-recovery.md`).

- **Ordinary push (HTTPS accepted, non-force)**: `git push origin main` → `33e657b..cd61c24
  main -> main`. No scope refusal occurred this time — the pushed range touches no
  `.github/workflows/` file (S4's SSH fallback was needed only for workflow-file changes);
  the pre-authorized same-origin SSH fallback was not required.
- **Remote SHA equality**: `git ls-remote origin main` → `cd61c242ea9042b2b1bc7deed30a5667431fe37c`
  == local `git rev-parse main` == `git rev-parse HEAD` (origin refreshed by the push itself).
- **Actual CI success at the published close-out SHA**: run
  [38514926943](https://github.com/WayJ/governed-agentic-work-runtime/actions/runs/38514926943)
  — `{"conclusion":"success","head_sha":"cd61c242ea9042b2b1bc7deed30a5667431fe37c","status":"completed"}`.
  The workflow ran the full matrix (Python 3.9/3.12/3.13): docs contract check, compileall,
  editable install, the 603-test unit suite, four demos, the lint-sop exit trio, the console
  entry point and fresh-venv `verify_install`.
- **Concurrent main-checkout observation (factual, no action taken)**: while this recovery
  ran, the user made live uncommitted edits in the main checkout — an added "UI design
  agreement" section in `AGENTS.md`, a new untracked `DESIGN.md`, and the user's own removal
  of their untracked asset `小蓝智能体平台品牌标志.png` (observed 2026-10-14 13:03–13:04
  local). None were staged, stashed, committed or modified by this session; the pushes above
  are commit-scoped and nonoverlapping with them. The new agreement explicitly does not
  apply retroactively to earlier sprints.

Evidence chain: acceptance record `docs/superpowers/acceptances/2026-10-14-S5-acceptance.md`
(pass, assembled carrier tip `770d516`, all six scenarios + five E5 DoD bullets green) →
pre-merge carrier tip / `merged-commit` `a073f72` → merge into main `591ff50` (parents
`33e657b` + `a073f72`) → recovery pin `d61349d` → close-out `cd61c24` (state `merged`,
closing note `.agents/notes/2026-10-14-S5-close.md`) → this record. Carrier worktree already
removed by the interrupted session after its merge landed; developer worktrees
(`s5-readonly-backend` @ `7ab432f`, `s5-browser-interface` @ `a9db96e`) preserved; the
recovery worktree is retained until `worker_done` and handed back to the coordinator.
Actual CI at this evidence commit's final published SHA is verified and reported in the
integration `worker_done` — no recursive CI-proof commit.

Main-checkout preview (exact, reproducible): `python3 -m work_runtime ui-demo` (seeds the
five-work sample store and serves it, printing the actual loopback URL — ephemeral port
unless `--port` is given), `python3 -m work_runtime ui --db <store.sqlite> [--port N]` for an
existing store, console `work-runtime ui-demo`/`ui` behave the same. Honest limits: loopback
binding is a local-trust convenience, not authentication; read-only, no write API, no tenant
model, no remote hosting.
