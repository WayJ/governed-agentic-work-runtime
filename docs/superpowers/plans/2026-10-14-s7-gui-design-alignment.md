# S7 GUI Design Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. No nested workers; coordinator dispatches each ownership scope.

**Goal:** Apply the user visual specification to the actual offline operations viewer and publish independently verified GUI and showcase images.

**Architecture:** Keep existing read-only API, state machine and stored-truth renderers. Centralize visual tokens in the existing CSS and adapt responsive panels; browser checks use actual Chrome and real stdlib HTTP servers. Integration assembles isolated scoped commits, accepts and owns main publication.

**Tech Stack:** Python>=3.9 standard library/unittest, vanilla HTML/CSS/JavaScript, SQLite, actual Chrome CDP; zero runtime dependencies and no frontend build.

**Spec:** [S7 design](../specs/2026-10-14-s7-gui-design-alignment-design.md); read [AGENTS.md](../../../AGENTS.md), [DESIGN.md](../../../DESIGN.md), [GUI API](../../gui-api.md), RFC-003 and assigned sprint before coding. Builder01d149e ratified before implementation; execute after S7 materialization.

## Global Constraints

- Python >=3.9, zero runtime dependencies, no frontend build/CDN/external assets or bundled licensed fonts.
- Preserve existing read-only API, loopback Host/Origin validation, exact raw values, real metrics, state-machine/polling behavior and all six persisted tables.
- Central tokens: canvas #f7f7f4, ink #26251e, body #5a5852, white cards, hairlines #e6e5e0/#cfcdc4, scarce orange #f54e00 and active #d04200; no shadows; controls8px/cards12px; spacing4px; display400.
- Font fallback system sans/CJK and locally available JetBrains Mono/system mono. No fabricated agent stages or Cursor identity/copy.
- Actual browser at1440/390/320, EN/ZH, before/after evidence, measured contrast and >=44px actionable targets. Behaviors require observed failing then passing checks; purely visual changes require visual/computed proof.
- Developer never merges/pushes; separate integration control checkout owns every merge/push and retains its own checkout through worker_done.

## Review Focus

- Long CJK/Unicode identifiers and huge raw JSON at320px must remain readable without clipping the whole document; verify viewport and internal panel geometry.
- Fresh initial /api/works rendering and repeated detail-tab arrow focus must target connected live DOM; preserve S5 first-load/focus fixes.
- Selected/status/error/focus surfaces must each satisfy actual contrast with explicit meaning independent of color; verify computed foreground/background pairs.
- Loading, empty, failed detail and disconnected polling must preserve visible retry/pause controls and layout under slow/failing HTTP responses.
- Packaged assets outside checkout and refreshed public images must match accepted GUI; verify actual installed HTTP assets and deployed bytes, not source paths alone.

---

### Task 1: GUI tokens, responsive layout and actual browser evidence

**Files:** Modify work_runtime/web/app.css; index.html/app.js only if justified. Modify docs/gui.md. Create scoped execution plan/report under docs/superpowers/plans/ and .agents/notes/, browser audit artifact and screenshots under docs/superpowers/acceptances/assets/S7/. Focused tests only for actual behavior fixes.

**Interfaces:** Consumes current /api/summary,/api/works,/api/work,/api/events DTOs unchanged; seed via ui-demo and existing Runtime commands. Produces same HTML/CSS/JS whitelist and interactions with documented visual tokens; reviewed commit/report plus actual image files.

- [ ] Read sprint, design/RFC and previous S5 focus/firstload regression and S6 contrast/release lessons. Verify baseline tests; no dependency installation is required.
- [ ] Capture baseline rendered screenshots/computed styles on real sample store in EN/ZH at1440/390/320, selecting all five work records and representative blockers/uncertain effects/raw views. Capture table snapshots before browser reads.
- [ ] Write scoped plan naming CSS token map and adaptations. Any behavior/accessibility change first gets a browser regression asserting actual rendered/interacted result; observe it fail on baseline. Do not create source-mirroring tests for visual changes.
- [ ] Implement central tokens and applicable responsive/density adaptations in app.css. Keep raw text renderers and state machine intact; minimal HTML/JS corrections only for reproduced defects.
- [ ] Capture matching after screenshots and computed styles, inspect actual images, compare to DESIGN and measure real text/focus/control contrast, geometry, target sizes and no shadows. Verify all five work states at each required language/width.
- [ ] Drive trusted keyboard/list/tab/language/filter/refresh/poll interactions; exercise loading/empty/error/disconnection and stored-XSS/huge numeric payloads. Reuse or adapt stdlib CDP code from S5/S6 audit artifacts; record actual commands and before/after results. New artifact must fix known old empty-list readiness race rather than inherit it.
- [ ] Assert complete six-table snapshot equality after interactions; run existing relevant GUI tests, all configured AGENTS gates and demos. Document exact tests/skips and browser limitations; no false lifecycle/production guarantee claims.
- [ ] Update docs/gui.md with applied visual contract and adaptations, commit scoped changes and evidence, report hash and idle. Route independent findings back to this owner in fresh dispatches.

### Task 2: Actual GUI showcase image refresh (dependent, separate dispatch)

**Files:** Modify only website/assets/gui-en-desktop.png,gui-zh-desktop.png,gui-en-390.png,gui-zh-390.png and docs/website.md; scoped report/audit artifact permitted.

**Interfaces:** Consumes accepted Task1 GUI commit served locally over actual ui-demo. Produces same four static image paths and real sanitized sample records, with render source commit/dimensions documented.

- [ ] Verify Task1 accepted source/real demo before capture; use isolated checkout at exact commit (integration/worker owns authorized branch synchronization).
- [ ] Capture EN/ZH at desktop and390 matching website framing; preserve truthful sample labels/data. Inspect images visually and verify files contain actual accepted browser UI.
- [ ] Run check_site/docs and actual website browser at subpath with loaded images atdesktop390/320, confirm original static paths/layout and no external dependencies.
- [ ] Commit four image updates/docs/report, send source hash and evidence, then idle. No page-copy/style redesign or backend edits.

### Task 3: Independent acceptance and release

**Files:** Separate release carrier and integration control; acceptance record, ledger state and closing note. Product fixes remain original owner via coordinator.

**Interfaces:** Consumes scoped Task1+Task2 commits and reports. Produces accepted carrier then main ordinary push, actual final SHA CI/Pages/public asset proof and fresh usable GUI preview.

- [ ] Assemble carrier with integration-owned merges and inspect scopes/diff for unauthorized state-machine/API/backend changes. Independently run actual browser at1440/390/320 including first-load/focus and exact-data/no-write checks, and inspect screenshots/tokens/adaptations/gaps.
- [ ] Run AGENTS gates, four demos, standalone14 rehearsal cases and fresh scripts/verify_install.py; record exact entrypoint coverage/counts/skips. Acceptance is technical pre-merge; do not claim publication yet.
- [ ] On pass, write acceptance and use supervibe merge to integrate main and close sprint ledger/note. Never remove active control checkout or force-push. Preserve user worktrees/assets/previews.
- [ ] Ordinary push; verify actual remote SHA matches final main, exact-SHA CI success; dispatch Pages at final SHA if needed, verify actual deploy success and HTTPS static byte equality. Report final evidence without recursive CI-doc commits.
- [ ] Start or verify main GUI preview with real demo and usable URL, send one worker_done, idle. Coordinator verifies before scheduling next roadmap slice.

## Self-review

Every design requirement maps to Task1 visual/data proofs, Task2 real website capture and Task3 independent installation/release proof. No API signatures change. Review Focus cases are included in the corresponding browser/packaging steps. This plan preserves the user's existing Orca Claude/TDD/integration workflow; routine visual choices belong to coordinator/builder, no local approval UI.
