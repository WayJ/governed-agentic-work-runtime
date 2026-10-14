# S6 Website Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. No nested workers; all sessions Orca Claude Code.

**Goal:** A truthful bilingual (EN default `/`, complete `/zh/`) static developer site for Governed Work Runtime under `website/`, using DESIGN.md tokens with documented adaptations, progressive enhancement only, and real sanitized GUI screenshots.

**Architecture:** Two static HTML pages sharing one CSS (tokens as custom properties) and one minimal JS (copy buttons + six-stage recovery stepping injected at runtime). Verification: a committed stdlib CDP browser-regression artifact (real headless Chrome, trusted key events) plus Orca embedded-browser interactive checks.

**Tech Stack:** Native HTML/CSS/JS (no build, no dependencies); stdlib Python ≥3.9 for the regression artifact (S5 CDP pattern).

**Spec:** [Ratified D29 design](../specs/2026-10-14-s6-developer-website-design.md) · [S6 sprint](../sprints/2026-10-14-S6-plan.md) · [Supervision](2026-10-14-s6-supervision.md) · root DESIGN.md / AGENTS.md UI agreement.

## Global Constraints

- Own ONLY: `website/index.html`, `website/zh/index.html`, `website/assets/styles.css`, `website/assets/site.js`, `website/assets/gui-*.png`; this plan; `.agents/notes/2026-10-14-S6-website-interface-report.md`; the regression artifact + evidence screenshots under `.agents/notes/`. No engine/GUI product changes; no edits to AGENTS, scripts, workflows, README, other docs, core tests. No merges/pushes (integration owns them).
- Zero runtime/build dependencies; no CDN, no external fonts/assets, no analytics/backend/fetch. All local URLs relative (never leading `/`); zh page uses `../assets/`; anchors fragment-only; external links absolute `https:` only.
- ALL sections visible without JS (no CSS that hides content awaiting enhancement). JS only: copy buttons (exact visible text, `aria-live` success/failure, selectable text always remains) and recovery stepping (keyboard-operable, all six stages stay visible).
- Truthful pre-alpha copy from README/README.zh-CN; no fabricated users/stars/metrics/agents/live engine; recovery story labeled illustrated sample; GUI shots labeled sample; site never connects to any local UI.
- Design tokens: cream canvas `#f7f7f4`, ink `#26251e`, body `#5a5852`, orange `#f54e00` scarce (wordmark mark, focus ring, large accent only), white cards, 1px hairlines, no shadows; 4px spacing scale; 8px controls / 12px cards; display weight 400; content cap ~1200px; 80px desktop section rhythm.
- Ratified adaptations (D29): primary CTA = ink bg + canvas text (14.33:1); small text uses body color (6.63:1), never `muted` below large sizes; no timeline pastels (no real mapping); system font stack with CJK fallbacks + locally-referenced `'JetBrains Mono', monospace`; zh display sizes reduced and tracking 0 for Chinese legibility (documented); nav wraps at narrow widths instead of a JS hamburger (noJS/keyboard-safe, documented).
- Gates: `python3 scripts/check_docs.py`, `python3 -m compileall -q work_runtime tests scripts`, `python3 -m work_runtime demo`; core suite run once as baseline. Delivery owner's site checker not yet available → report as pending, never claim it passed.

## Review Focus

1. **Subpath/nested-zh paths** — assets must resolve under `/governed-agentic-work-runtime/` and `…/zh/`; browser test serves a temp parent copy named `governed-agentic-work-runtime/` and asserts stylesheet applied + images `naturalWidth>0` + crosslinks `zh/index.html` / `../index.html`.
2. **Clipboard failure silence** — on an insecure origin (real non-localhost HTTP; `navigator.clipboard` undefined) the copy click must announce failure via `aria-live` and leave text selectable; asserted in a real browser, no stubs.
3. **CSS hiding awaiting JS** — with script execution disabled (CDP `Emulation.setScriptExecutionDisabled`), every section and all six stages must be visible and no injected controls exist.
4. **Narrow overflow** — at 390px and 320px on both languages, `document.documentElement.scrollWidth <= clientWidth` (code uses `pre-wrap` + `overflow-wrap: anywhere`, grids collapse 1-up).
5. **Token/contrast drift** — computed styles from the real pages must match tokens (body bg `rgb(247,247,244)`, CTA ink/cream pair, radii 8/12, no `box-shadow`, hero 72px desktop/32px mobile EN, 52/30 ZH) and WCAG ratios recomputed in-script ≥4.5 for text pairs (ink/canvas 14.33, body/canvas 6.63, body/white 7.11, cream/ink CTA 14.33).

---

### Task 1: Static bilingual pages + token CSS (noJS-complete, no `<script>` yet)

**Files:** Create `website/index.html`, `website/zh/index.html`, `website/assets/styles.css`.
**Interfaces:** Page ids consumed by nav/anchors/tests: `main` (tabindex -1), `why`, `how`, `demo`, `start`, `contribute`; stage list `ol#recovery-stages > li.stage` ×6; copyable blocks `pre[data-copyable]`; skip link `a[href="#main"]`; language links `zh/index.html` (EN page) / `../index.html` (ZH page). Showcase images reference `assets/gui-en-desktop.png` etc. (Task 4 provides files).

- [ ] Write `website/index.html` — 8 ratified sections: nav (wordmark ◆ Governed Work Runtime; Why/How it works/Demo/Start/Docs→repo docs tree/GitHub/中文), hero (exact promise "Let agents plan. Make every business action accountable.", sub from README line 5, visible status "Status: local reference prototype, pre-alpha · Python 3.9+ · Apache-2.0 · zero runtime dependencies", primary CTA →`#start`, secondary →repo), value (3 cards + 3 distinctions from README), architecture (HTML flow: Proposer → Version-bound command → Policy gate → Durable operation → Adapter / effect → Receipt / evidence, each with one truthful line; blockers/rejected decisions and same-key query recovery named; links RFC-001/RFC-003), recovery story (six stages verbatim from `python3 -m work_runtime demo` output; prominent "Illustrated sample — recorded stages of the real demo output, not a running engine or live agent"), GUI showcase (4 `<img>` + alt + `python3 -m work_runtime ui-demo` command block labeled sample), quick start (clone/cd/demo block + notes + optional publish-demo/intervention-demo/adoption-demo/ui-demo commands + README/RFC/verification links), contribute/footer (adapter + rule-card guides, issues, CONTRIBUTING, Apache-2.0 LICENSE, roadmap; no invented numbers).
- [ ] Write `website/zh/index.html` — complete Chinese mirror; copy from README.zh-CN.md; hero "让 Agent 自主规划，让每次业务行动都有依据。"; six stages from README.zh-CN §一条命令体验真实崩溃恢复; all labels bilingual-appropriate (nav 为什么/工作原理/演示/快速开始/文档/GitHub/English); `lang="zh-CN"`.
- [ ] Write `website/assets/styles.css` — `:root` custom properties for all DESIGN tokens (colors, 4px spacing scale, radii, fonts: `system-ui, -apple-system, "Helvetica Neue", Helvetica, Arial, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif`; code `'JetBrains Mono', 'SF Mono', Menlo, Consolas, monospace`), type ramp (display 400, negative tracking EN display only; `html[lang="zh-CN"]` display tracking 0 and sizes 52/40/30), components (nav 64px + hairline; wrap below 768px; cards 12px radius hairline no shadow; `.btn-primary` ink/canvas 44px hero / 40px; `.btn-secondary` white + hairline-strong; code blocks `pre-wrap` + `overflow-wrap:anywhere`; `.skip-link`; `:focus-visible` 2px `--primary` outline + offset), responsive 640/768/1024 (hero 72/56/32 EN; grids 3→2→1), 80px section rhythm (48px narrow), 1200px cap.
- [ ] Serve `python3 -m http.server --directory website` and confirm both pages load with stylesheet applied (manual browser spot check); fix any relative-path mistakes.
- [ ] Commit 1: `git add website/ docs/superpowers/plans/2026-10-14-s6-website-interface.md && git commit` ("feat(website): bilingual static pages with DESIGN tokens (noJS-complete)").

### Task 2: Browser regression artifact — observe RED (behavior absent)

**Files:** Create `.agents/notes/2026-10-14-S6-website-browser-regression.py` (stdlib CDP client, S5 `2026-10-14-S5-browser-regression.py` pattern; real Chrome; `Input.dispatchKeyEvent` trusted keys; `Emulation.setDeviceMetricsOverride` viewports; `Browser.grantPermissions` clipboard read for the equality assertion).
**Interfaces:** CLI `website_browser_regression.py --en-url URL --zh-url URL [--insecure-url URL] [--sections behavior|static|visual|all] [--shot-dir DIR]`; exit 0 pass / 1 fail; prints each observed value.

- [ ] Implement checks: **behavior** (copy button injected per `pre[data-copyable]`, click → `aria-live` success + granted-permission clipboard text equals block text; recovery Prev/Next exist, click/Enter advances `aria-current="step"` 1→2→1 and all 6 stages stay visible; Tab from body → skip link first; skip-link Enter moves focus to `#main`); **static** (required ids/sections/crosslinks/img alt present both languages; all external hrefs `https:`; no leading-`/` local URLs); **visual** (computed tokens per Review Focus 5 at 1280/390/320; `scrollWidth<=clientWidth` both pages; optional screenshots via `Page.captureScreenshot`).
- [ ] Run `--sections behavior` against Task-1 pages (no JS): observe and record RED — copy-button/live-region/clipboard-equality and recovery-control checks FAIL while stage/section static presence holds. Paste verbatim output into the report draft.
- [ ] Commit 2: artifact + recorded RED note in report draft ("test(website): CDP regression artifact, behavior RED observed pre-JS").

### Task 3: site.js — GREEN in the real browser

**Files:** Create `website/assets/site.js`; Modify both pages: add `<script src="…" defer></script>` (relative: `assets/site.js` / `../assets/site.js`).
**Interfaces:** No globals required by pages; enhancement keys off existing markup (`pre[data-copyable]`, `#recovery-stages`); messages selected by `document.documentElement.lang` (`zh*` → Chinese); single `div[aria-live="polite"]` created by JS.

- [ ] Implement minimal JS: inject copy buttons (`aria-label` per block, e.g. "Copy quick start commands"), guard `navigator.clipboard && window.isSecureContext`, on success/failure announce exact localized message (failure names the manual-select fallback); inject recovery toolbar (Prev/Next `<button>`, "Stage N of 6" counter in the live region, `aria-current="step"` moves; ArrowLeft/ArrowRight on the stage list move stages), never hiding stages.
- [ ] Rerun `--sections behavior` → all GREEN (record verbatim). Run `--sections static` → GREEN.
- [ ] Commit 3: "feat(website): progressive copy + recovery controls, behavior GREEN".

### Task 4: Fresh sanitized GUI screenshots + showcase

**Files:** Create `website/assets/gui-en-desktop.png`, `gui-zh-desktop.png`, `gui-en-390.png`, `gui-zh-390.png` (Task 1 pages already reference them).

- [ ] Run own `python3 -m work_runtime ui-demo` (unchanged Python, own checkout, fresh store; never touch root preview :59619); capture via a temp headless-Chrome CDP script (documented in report, not committed): EN default view and ZH via the page's lang toggle, desktop 1280×900 and 390×844; wait for tiles/list render.
- [ ] Inspect each PNG (Read tool) — must show the seeded five-work sample; no XSS-fixture detail views, no user data; crop is fine. Alt text + `width`/`height` attrs + `loading="lazy"` already in pages; verify rendered `naturalWidth>0` in Task 5.
- [ ] Rerun `--sections static` (images now resolve). Commit 4: "feat(website): real sanitized ui-demo GUI showcase shots (EN/ZH, desktop/390)".

### Task 5: Full actual-browser verification + evidence screenshots

**Files:** Create `.agents/notes/assets/s6-*.png` evidence shots (desktop/390/320 EN+ZH, noJS, insecure-clipboard, subpath).

- [ ] `--sections visual` at 1280/390/320 with `--shot-dir .agents/notes/assets` (computed tokens + no-overflow + screenshots both languages).
- [ ] noJS: script-execution-disabled pass — every section + 6 stages visible, zero injected buttons (fold into artifact or a documented CDP one-liner; record output).
- [ ] Insecure origin: serve on the machine LAN IP over plain HTTP → copy click announces failure, text selectable (Review Focus 2).
- [ ] Subpath: temp parent `…/governed-agentic-work-runtime/` copy + `http.server` → EN/ZH load, stylesheet applied, all 4 images render, crosslinks correct (Review Focus 1).
- [ ] Orca embedded browser (page affinity `--page`, trusted keys): `goto` → `snapshot` → click Copy → `keypress Tab` focus walk on the served EN and ZH pages; record snapshot/eval outputs as interactive evidence.
- [ ] Commit 5: evidence screenshots ("test(website): actual-browser visual/noJS/subpath/clipboard evidence").

### Task 6: Gates, audit, report, final commit

- [ ] `python3 scripts/check_docs.py`; `python3 -m compileall -q work_runtime tests scripts`; `python3 -m work_runtime demo` (final evidence). Baseline core suite result recorded once (started pre-code).
- [ ] Audit: grep website sources — no `http:` external assets, no CDN/analytics/fetch, no invented numbers/testimonials; file headers note Apache-2.0 project assets.
- [ ] Write `.agents/notes/2026-10-14-S6-website-interface-report.md`: immutable tip SHA, exact RED/GREEN outputs, screenshot list, token/adaptation table, subpath/noJS/insecure results, pending items (site checker not yet available from delivery owner; Pages/deployment pending integration; acceptance pending).
- [ ] Final scoped commit; `orca orchestration check` for redirects; `worker_done` with 3-sentence summary; idle.
