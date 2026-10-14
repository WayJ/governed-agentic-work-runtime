# S7 Task1 — GUI design tokens and accessible responsive CSS (scoped plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the ratified S7 visual contract (DESIGN.md tokens, D30/D31) to the existing bilingual offline read-only operations viewer via a centralized `work_runtime/web/app.css`, with actual-browser before/after evidence and zero writes.

**Architecture:** CSS-only restyle expected (ratified builder review: no `index.html`/`app.js` edits anticipated). A stdlib-only CDP audit script (adapted from the S5 artifact, with its known empty-list readiness race fixed) captures the full before/after matrix on a real `ui-demo` store and asserts interactions, contrast, geometry and no-writes in actual Chrome.

**Tech Stack:** Python >=3.9 stdlib/unittest, vanilla CSS, real headless Chrome over CDP (trusted key/mouse events), SQLite snapshots.

**Spec:** [S7 design](../specs/2026-10-14-s7-gui-design-alignment-design.md) · [coordinator plan Task1](2026-10-14-s7-gui-design-alignment.md) · [builder review](../../../.agents/notes/2026-10-14-S7-design-review.md) · [DESIGN.md](../../../DESIGN.md) · AGENTS.md UI agreement.

## Global Constraints

- Python >=3.9, zero runtime dependencies; no CDN/fonts/build/bundled assets; offline.
- Preserve read-only API, Host/Origin boundary, polling state machine, exact raw text rendering, all six persisted tables; UI introduces no writes.
- Ownership: `work_runtime/web/app.css` primarily; `index.html`/`app.js` only for reproduced defects with observed browser RED/GREEN; `docs/gui.md`; evidence under `docs/superpowers/acceptances/assets/S7/`.
- Tokens (ratified D30/D31): canvas #f7f7f4, ink #26251e, body #5a5852, white cards, hairlines #e6e5e0/#cfcdc4, scarce orange #f54e00 (non-text only), active #d04200; no shadows; controls 8px / cards 12px radius; 4px spacing scale; display weight 400 with negative tracking (zero for zh); labels 16px/600; body 14–16px; code 13px; >=44px actionable targets; single column <1024px; 1200px content cap; semantic text contrast >=4.5:1 measured; unknown chip classes render neutral; no timeline pastels; remove document `overflow-x:hidden` and prove no page-level horizontal overflow at 390/320.
- No merge/push, no extra workers; report once through `orca orchestration` and idle.

## Decisions locked (builder defaults ratified in the review)

- Token names `--color-*`, `--space-*`, `--radius-*`, `--font-*`, `--text-*` / `--tracking-*`.
- Primary control (`#refresh`): ink background, canvas text (14.33:1). Orange never used for text.
- Selected work item: 1px ink border + `--color-canvas-soft` background. Selected tab: ink background, canvas text.
- Focus: `:focus-visible` 2px orange outline, offset 2px (non-text 3.52:1 on white / 3.28:1 on canvas — both >=3:1; outline sits on card/canvas surfaces, never on #cfcdc4). Ratio verified by measurement in the audit, not copied.
- Status chips: base `.chip` neutral (`#eceae4` family + ink; exact ratio measured on the actual surface, not copied from the #e6e5e0 figure) so runtime-generated unknown `chip-st-*` classes can never render unstyled; known status/decision chips get measured semantic tints (success darkened below DESIGN #1f8a65's 4.30; warn; error #cf2d56 kept at 5.04/4.70) as enhancement only.
- Table overflow: keep `.table-wrap` per-surface scroll, 340px cell cap, `overflow-wrap: anywhere`.
- Type mapping: tile values 26px/400, detail title 22px/400 (identifiers stay mono), section labels 16px/600, body 15px, small/code/table 13px; `:lang(zh)` display tracking forced to 0.
- Audit artifact: `docs/superpowers/acceptances/assets/S7/s7_gui_audit.py` + screenshots/computed-style JSON under `assets/S7/{before,after}/`.
- Empty store and hostile/huge-value stores are clearly-labeled harness fixtures: file copies of the real seeded store (rows emptied / hostile rows inserted via stdlib sqlite3 by the harness, never served as runtime-seeded data). The no-writes proof runs on the real seeded store.

## Review Focus

1. Long CJK identifiers and huge raw JSON at 320px must not clip the document — audit asserts `documentElement.scrollWidth <= clientWidth` (content-width proof valid even where old CSS hid overflow) plus internal wrap.
2. First-load rendering and repeated tab-arrow focus must target the live DOM — audit re-runs the S5 regressions at 1440/390/320 in both phases.
3. Normal/selected/focus/status/error text pairs must each measure >=4.5:1 — audit dumps computed fg/bg pairs and Python-computed WCAG ratios.
4. Loading/empty/error/disconnected must keep usable controls — audit uses CDP network latency for loading, UNKNOWN_WORK for gone, server kill for disconnect; pause/resume/refresh exercised.
5. Packaged assets must match the restyle — `scripts/verify_install.py` byte-compares installed vs packaged web assets (Task 3 runs it fresh).

---

### Task 1: Browser audit tool and BEFORE evidence on baseline CSS

**Files:**
- Create: `docs/superpowers/acceptances/assets/S7/s7_gui_audit.py`, `docs/superpowers/acceptances/assets/S7/before/` (captures)
- No product files.

**Interfaces:** Consumes `python3 -m work_runtime ui-demo --directory D` / `ui --db P` subprocesses and their printed URLs. Produces `{phase}-results.json` (checks + computed styles + contrast ratios), `{phase}-matrix/*.png` (30 captures per phase — {1440,390,320} x {en,zh} x 5 works; 60 total across both phases), `{phase}-views/*.png` (blockers/uncertain/raw/tab extras), and a six-table snapshot equality result.

- [x] **Step 1: Write `s7_gui_audit.py`** — stdlib CDP client (adapted from `.agents/notes/2026-10-14-S5-browser-regression.py`), args `--phase before|after --out DIR [--chrome PATH]`. It must: seed a real ui-demo store in a fresh temp dir; snapshot all six tables (`works, commands, evidence, operations, events, metadata`, `SELECT *` ordered) before and after the run and compare; build the empty and hostile/huge fixture stores as labeled copies; drive trusted `Input.dispatchKeyEvent`/`dispatchMouseEvent` (never DOM `.click()` as keyboard evidence) and `Emulation.setDeviceMetricsOverride`; fix the S5 empty-readiness race by waiting for a settled `#list-status` text (non-empty and not loading) before asserting the empty state; capture the matrix and view screenshots; dump computed tokens/geometry/contrast JSON. Assert in BOTH phases the unchanged behavioral/integrity checks: first-load 5 items, empty message, tab-arrow live focus, list arrows + Enter select, `/` search focus, filter, language toggle, refresh, pause/resume, loading text under emulated latency, UNKNOWN_WORK gone state, disconnect banner after server kill, XSS inertness (`window.__xss` undefined; hostile text rendered), huge-integer exactness, page-overflow proof at 390/320. Visual measurements (tokens, typography, radii, shadows, 44px targets, contrast ratios) are recorded in both phases but asserted only when `--phase after` — baseline visual gaps are measurements, not behavior regressions.
- [x] **Step 2: Run `--phase before`** on the untouched checkout (2f76f7f). Expected: interaction/integrity checks PASS; token assertions skipped; captures + JSON recorded as the baseline. — Result: 34 checks, 0 failed (run 6, /tmp/s7-before-run.log; earlier runs were audit-harness debugging, no product changes involved).
- [x] **Step 3: Verify evidence files** exist (60 matrix PNGs + views + JSON) and spot-inspect two images; commit the audit tool with before evidence only if sizes are sane (<2 MB per file). — 30+30 matrix PNGs (60), 12+12 views, 2 results JSON; largest file <160 KB; spot inspection + pixel sampling confirmed distinct before/after themes.

### Task 2: Central tokens and responsive CSS in `app.css`

**Files:**
- Modify: `work_runtime/web/app.css` (full rewrite of `:root` + component rules)
- Modify (only if a reproduced defect demands it): `work_runtime/web/index.html`, `work_runtime/web/app.js`

**Interfaces:** Consumes the existing DOM contract (`chipClass()` runtime class names, element ids, `:lang(zh)` switching). Produces the token set named in Decisions locked; no id/class renames.

- [x] **Step 1: Measure and lock semantic shades.** Compute WCAG ratios in Python for candidate pairs (success/warn/error text on white, canvas, `#eceae4`, and their tints); lock shades with text pairs >=4.5 and record exact ratios for the report.
- [x] **Step 2: Implement the token set and component mapping** exactly as locked above (tokens, radii, spacing, typography, chips, selected/tab/primary states, focus, banners, tables, raw blocks, footer; media queries <1024 single column with 1200px cap, <640 stacking; min-height 44px on button/.tab/.work-item/inputs/`details summary`; remove `html,body{max-width:100%;overflow-x:hidden}`; `:lang(zh)` zero display tracking; no `box-shadow`).
- [x] **Step 3: Run `--phase after`** with the same seeded store directory. Expected: every assertion PASS (tokens, contrast, geometry, 44px, overflow proof, interactions, XSS/huge values, six-table equality).
- [x] **Step 4: Diff evidence.** Compare before/after captures and computed-style JSON; record applied tokens, adaptations and any residual gaps for the report.
- [x] **Step 5 (conditional): reproduced defect** — if any check fails for an HTML/JS reason CSS cannot fix, capture the failing browser check (RED), fix minimally (systematic-debugging), rerun to GREEN, and disclose; otherwise skip with an explicit note.

### Task 3: Regression, gates, demos

**Files:** none created (runs only).

- [x] **Step 1:** `python3 -m unittest discover -s tests -v` — expect 622 tests, OK, skipped=1.
- [x] **Step 2:** AGENTS gates: `python3 scripts/check_docs.py`; `python3 -m work_runtime demo`; `python3 -m compileall -q work_runtime tests scripts`; `python3 scripts/check_site.py`; plus the other three demos (`publish-demo`, `intervention-demo`, `adoption-demo`).
- [x] **Step 3:** `python3 -m unittest discover -s examples/rehearsal` (standalone14) and fresh `python3 scripts/verify_install.py`; record exact counts/skips.

### Task 4: Documentation, report, commit

**Files:**
- Modify: `docs/gui.md` (applied visual contract, adaptations, measured contrast)
- Create: `.agents/notes/2026-10-14-S7-gui-report.md` (commands, RED/GREEN-or-visual evidence, hashes, risks)

- [x] **Step 1:** Update `docs/gui.md` — tokens applied, density/responsive adaptations documented, contrast table, what deliberately did not change (data pipeline, boundaries).
- [x] **Step 2:** Write the scoped report with exact commands, screenshot inventory, measured ratios, adaptations, remaining risks.
- [x] **Step 3:** Commit scoped changes (`work_runtime/web/app.css`, audit assets, docs, plan, report); record the hash; check coordinator messages; send one `worker_done` with task/dispatch IDs; idle.

## Self-review

Spec coverage: every ratified D30/D31 clause maps to Task 2 Step 2 or the audit assertions; evidence rules map to Tasks 1–2; no-write proof and gates to Tasks 1/3; docs/report to Task 4. Steps leave no choice open where the spec or review fixed one; semantic shades are the only measured choice and their acceptance criterion (>=4.5 measured) is unambiguous.
