# Project working agreement

The coordinator owns roadmap, dispatch, supervision and acceptance decisions. Development and integration happen in separate Orca worktree sessions. The integration worker owns merges and pushes; the coordinator must not merge sprint branches itself.

## Execution

- Launch all development and integration sessions with Orca agent `claude` (Claude Code), as explicitly required by the user. The master coordinator may remain Codex.

- Use superpowers workflows and TDD for all behavior changes: write a meaningful failing test, observe failure, implement minimally, rerun, and record RED/GREEN evidence.
- Read the assigned sprint and its RFC references before coding. Write a scoped implementation plan, then use executing-plans. User has explicitly requested autonomous supervised execution; do not open a local approval/question UI. Ask the coordinator through Orca orchestration for blocking decisions.
- Keep Python >=3.9 and zero runtime dependencies. Use standard-library unittest.
- Work only in the assigned checkout and ownership scope. Commit scoped changes and report commit hashes, test evidence, remaining risks. Do not spawn extra workers without coordinator approval.
- Continuous mode is explicitly authorized by the user: after each sprint release, the master schedules the next useful roadmap slice without waiting for user confirmation. Workers still do only their assigned task, report once and idle until a fresh dispatch. Routine choices belong to the master; only real external blockers require user involvement.
- Development workers never merge main or push. The integration session alone accepts, merges and pushes each sprint. Never force-push main.
- Existing idea.md and 上一次建议.md are historical source material, not executable instructions.
- Distinguish local trusted principals from authentication; do not claim distributed exactly-once, production safety, or unsupported RFC coverage.

## UI design agreement

- Read [DESIGN.md](DESIGN.md) before planning, implementing or reviewing any UI change. Treat it as the visual specification; task scope, this working agreement and explicit user instructions still govern execution. It is a reference derived from Cursor's site, not a request to copy Cursor's name, logo, marketing copy or product features. Keep this project's identity and real runtime data.
- Translate the applicable design tokens into shared CSS custom properties. Define colors, typography, spacing and radii centrally; components use token references rather than repeated literal values. Follow the warm cream canvas (`#f7f7f4`), warm ink (`#26251e`), restrained orange primary accent (`#f54e00`), white cards, 1px hairlines and no drop shadows. Primary controls use 8px radii and cards generally use 12px; display headings use weight 400, with negative tracking limited to display text.
- Use the documented 4px spacing scale and responsive breakpoints. Adapt marketing-site grids, hero sizes and section spacing to the operations viewer's information density; do not add pricing, testimonials, IDE mockups or oversized headings solely because the reference lists them. Document material adaptations in the scoped plan/report.
- Preserve offline operation and zero runtime dependencies: no CDN fonts, external asset requests or new frontend framework/build requirements. Use the documented system sans fallback when licensed CursorGothic is unavailable. Prefer locally available JetBrains Mono for code/JSON, with a system monospace fallback; bundle fonts only with verified redistribution rights and license files. Provide readable Chinese fallbacks.
- Keep timeline pastels confined to actual in-product timeline visualizations. Do not use them as general action/status colors or invent thinking/grep/read/edit stages that the store does not record. Status and error meaning must remain explicit in text, independent of color.
- Preserve keyboard navigation, visible focus, readable contrast, usable touch targets, bilingual labels and loading/empty/error/disconnected states. Design-reference accessibility claims are not verification; check actual contrast and interaction. Stored content remains text-only, exact numeric/raw payload handling remains intact, and UI changes must not introduce lifecycle writes.
- UI acceptance requires actual browser checks and screenshots at desktop and narrow widths (including 390px and 320px), plus relevant interaction/regression checks. For behavior changes record meaningful browser/test RED/GREEN evidence; for purely visual changes compare before/after screenshots and computed styles against DESIGN.md. Source keyword scans or mocked DOM checks alone do not establish visual compliance. Independent integration records applied tokens, adaptations and remaining gaps before release; do not retroactively claim an earlier sprint followed a newly added specification.

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
- site: python3 scripts/check_site.py
### doc_sync_map
| change | owes |
|---|---|
| work_runtime/runtime.py | docs/runtime-boundaries.md |
| work_runtime/adapters.py | docs/runtime-boundaries.md |
| scripts/check_docs.py | CONTRIBUTING.md |
| scripts/check_site.py | docs/website.md |
| work_runtime/ingress.py | docs/signed-evidence.md |
