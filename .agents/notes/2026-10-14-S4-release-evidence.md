# S4 release evidence — 2026-10-14

Publication record for sprint S4 (close-out `7673977`), matching the S3 release-evidence
pattern.

- **HTTPS refusal (exact)**: `git push origin main` → `! [remote rejected] main -> main
  (refusing to allow an OAuth App to create or update workflow \`.github/workflows/ci.yml\`
  without \`workflow\` scope)` — triggered by the S4 harness's CI step additions. The
  pre-authorized same-origin SSH fallback was used; no scope was widened, no secrets handled.
- **SSH push (ordinary, non-force)**: `git push git@github.com:WayJ/governed-agentic-work-runtime.git main`
  → `525ad7e..7673977  main -> main`.
- **Remote SHA equality**: `git ls-remote origin main` → `76739772494b72537ebc668ed4ed65c60ea20fad`
  == local `git rev-parse HEAD` (origin refreshed by the fetch/push itself).
- **Actual CI success at the published SHA**: run
  [38498357743](https://github.com/WayJ/governed-agentic-work-runtime/actions/runs/38498357743)
  — `{"conclusion":"success","headSha":"76739772494b72537ebc668ed4ed65c60ea20fad","status":"completed"}`.
  The workflow ran the full matrix (3.9/3.11/3.12 jobs): unit suite, four demos, lint-sop exit
  trio, console demo, fresh-venv `verify_install` with independent artifact parses.

Evidence chain: acceptance record `docs/superpowers/acceptances/2026-10-14-S4-acceptance.md`
(pass, assembled tip `9d4f188`) → pre-merge carrier tip / `merged-commit` `be6f977` → merge
`f938201` → close-out `7673977` (state `merged`, closing note
`.agents/notes/2026-10-14-S4-close.md`) → this record. Carrier worktree torn down via Orca;
developer/controller worktrees preserved. Master proceeds to S5 GUI autonomously per the
continuous authorization.
