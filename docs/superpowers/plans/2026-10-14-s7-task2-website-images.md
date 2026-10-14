# S7 Task2 — actual GUI website-image refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the four static website showcase images with fresh, sanitized, actual captures of the accepted S7 GUI (design tokens from `41bae0e` via `c8138fe`, source tree `600c7aa`) and document their provenance in `docs/website.md`.

**Architecture:** No behavior change and no product change. A stdlib-only CDP capture script (reusing the committed S7 audit module) drives real headless Chrome over a real `ui-demo` stdlib server at exact website viewports; a stdlib PNG pixel scan proves authenticity and token colors locally (no CDN-based reads as acceptance basis); the existing S6 website browser-regression artifact re-verifies the site under the Pages subpath after the image swap.

**Tech Stack:** Python ≥3.9 standard library only; actual headless Chrome over CDP; vanilla HTML/CSS website (untouched).

**Spec:** [S7 plan Task2](2026-10-14-s7-gui-design-alignment.md) · [S7 design](../specs/2026-10-14-s7-gui-design-alignment-design.md) · [AGENTS.md](../../../AGENTS.md) · [DESIGN.md](../../../DESIGN.md) · [docs/website.md](../../website.md) · [integration review note](../../../.agents/notes/2026-10-14-S7-gui-integration-review.md)

## Global Constraints

- Modify only `website/assets/gui-en-desktop.png`, `gui-zh-desktop.png`, `gui-en-390.png`, `gui-zh-390.png` and `docs/website.md`. Scoped plan/report/capture-verify artifacts and fresh evidence under unique `s7img-*` paths are permitted additions.
- Product CSS/JS/API/backend/pages (`index.html`, `zh/index.html`, `styles.css`, `site.js`), checker (`scripts/check_site.py`), workflow, ledger: **unmodified**. Existing four image paths, dimensions 1280×900 / 390×844 and page identity preserved.
- Screenshots are actual sanitized captures of `python3 -m work_runtime ui-demo` output — truthful sample labels/data, no invented customers/stages/data, no XSS-fixture views, no user-home paths. Need-attention / uncertain / acknowledged-effect semantics must render correctly.
- Transient content policy: the UI's `sampled-at` chip always shows the capture moment's clock (structurally unavoidable without product edits) — record and disclose it; seed the store under a stated neutral demo root (no `/Users/` segment); keep polling active so the paused chip stays hidden.
- Purely visual change: no TDD (no behavior change); evidence = actual-browser before/after images + computed styles + local pixel verification. Vision-model reads are supplementary only, never the acceptance basis.
- No merge/push, no extra workers, no local approval UI; one `worker_done` then idle. Final integration owns merge/push/Pages proof.

## Review Focus

- Stale-CDN image reads: never inspect a capture under a shared basename; use unique `s7img-*` names and rest authenticity on the local stdlib pixel scan.
- Dimensions/layout drift: PNGs must be exactly 1280×900 and 390×844 (dsf=1), or the site's `width`/`height` attributes and grid layout break.
- Language truth: headless Chrome follows the OS locale (first load may be zh); every shot must be proven in the intended language via `document.documentElement.lang`.
- Framing usefulness: shots must show the new topbar/controls and real five-work records (desktop additionally a real detail with correct acknowledged-effect content), not a placeholder-only detail pane.
- Subpath asset breakage: re-serve under `/governed-agentic-work-runtime/` and re-run the static/visual/nojs browser checks including lazy-image loads at 1280/390/320 × EN/ZH.

---

### Task 1: Pre-flight verification

**Files:** none (read-only checks).

- [ ] Verify `git rev-parse HEAD` = `600c7aa…`, clean tree, branch `WayJ/s7-website-images`; record old image dimensions/hashes.
- [ ] Verify Chrome binary exists; baseline `python3 scripts/check_site.py` and `python3 scripts/check_docs.py` pass at the source tree.

### Task 2: Capture script and fresh GUI captures

**Files:**
- Create: `.agents/notes/2026-10-14-S7-task2-website-capture.py` (imports `docs/superpowers/acceptances/assets/S7/s7_gui_audit.py`)
- Create: fresh captures under a unique out dir (basenames `s7img-{en,zh}-{desktop,390}.png`)

**Interfaces:** Consumes audit helpers `CdpPage`, `UiServer`, `settle_list`, `ensure_lang`, `select_work`, `wait_true`, `measure_contrast`. Produces four PNGs (1280×900 / 390×844, dsf=1) + `s7img-capture.json` evidence record.

- [ ] Script flow per width/lang: navigate → `settle_list` → `ensure_lang` → desktop: `select_work("cancel-1")` + overview detail wait; 390: no selection → `scrollY=0` → settle → `Page.captureScreenshot`.
- [ ] In-browser assertions per shot: topbar fully in viewport at scrollY 0 (white card, `#e6e5e0` hairline); all controls present ≥44px, no box-shadow; refresh ink/canvas tokens; five works present with exact ids `wait-1, uncertain-1, transfer-1, succeed-1, cancel-1`; desktop: `cancel-1` selected + detail head + cancellation acknowledged-effect banner + tab row; store-source chip starts with the stated demo root and contains no `/Users/` segment; `sampled-at` text recorded; poll-state chip hidden; no horizontal overflow.
- [ ] Seed store via `ui-demo --directory /tmp/s7img-gui-store` (fresh per run; real commands only). Exit 0 only if every assertion passes.

### Task 3: Authenticity and before/after verification (local, stdlib)

**Files:**
- Create: `.agents/notes/2026-10-14-S7-task2-png-verify.py` (stdlib PNG decode via zlib, filters 0–4)

- [ ] Assert each new PNG: exact dimensions; presence of new-theme pixels `#f7f7f4` (canvas), `#ffffff` (cards), `#26251e` (ink), `#f54e00` (brand mark); absence of old-theme `#f5f7fa`, `#2456c6`, `#eef1f6`, `#1c2433`.
- [ ] Assert the OLD (pre-replacement) images carry the old theme (`#f5f7fa` present, `#f7f7f4` absent) and identical dimensions — a genuine before/after record.
- [ ] Vision-inspect the four captures via freshly uploaded unique basenames (supplementary): correct language per file, five-work list, desktop detail is `cancel-1` with acknowledged-effect banner, 390 wrapped controls, no clipping.

### Task 4: Swap images and update provenance docs

**Files:**
- Modify: the four `website/assets/gui-*.png` (byte replacement, same paths)
- Modify: `docs/website.md` (new "Showcase screenshot provenance" content)

- [ ] Copy the four verified captures over `website/assets/gui-{en,zh}-{desktop,390}.png`; re-run `python3 scripts/check_site.py`.
- [ ] Add to `docs/website.md`: provenance section stating render source (tree `600c7aa` carrying accepted GUI `41bae0e` via merge `c8138fe`), capture command (`ui-demo`, stated demo root), five-work sample semantics, viewports/dsf, language via the viewer's own toggle, desktop framing (cancel-1 selected, acknowledged external effect retained), sampled-at transience disclosure, capture tooling (headless Chrome CDP, artifact path), and the prospective S7 scope note: DESIGN.md governs the GUI from S7 onward; S5-era output predates it and no retroactive S5 compliance is claimed.

### Task 5: Gates and actual subpath browser verification

- [ ] Run `python3 scripts/check_docs.py` and `python3 scripts/check_site.py` (exit 0 both).
- [ ] Assemble temp subpath copy (`/governed-agentic-work-runtime/`), serve with `python3 -m http.server` on a unique port, run `.agents/notes/2026-10-14-S6-website-browser-regression.py --sections static,visual,nojs` against EN/ZH URLs at 1280/390/320 with screenshots to a unique dir; confirm 0 failed (includes lazy-image load, layout tokens, noJS, no external deps).
- [ ] Compare before/after page screenshots: layout structure unchanged; only the four showcase images differ.

### Task 6: Report, commits, worker_done

**Files:**
- Create: `.agents/notes/2026-10-14-S7-task2-website-images-report.md`
- Create: evidence under `.agents/notes/assets/` with unique `s7img-*` names (capture JSON, verify JSON, page screenshots)

- [ ] Write report: exact source hash, image hashes/dimensions, browser commands + observed results, before/after comparison, risks (e.g. sampled-at transience, one-engine Chromium, vision supplementary).
- [ ] Commit scoped changes (plan+artifacts; images+docs; report+evidence), record hashes; `orca orchestration check` then exactly one `worker_done` (outcome, task/dispatch ids, report path), then idle.

## Self-review

Task2→Task5 cover the plan's capture/verify/swap/gates requirements; every Global Constraint maps to a step (scope in Task 4, transience in Task 2 assertions + Task 4 doc, subpath in Task 5, idle in Task 6). No code interfaces change; no TDD is applicable to a purely visual artifact swap, per AGENTS and the S7 design's evidence rules. Review Focus items are pinned as explicit assertions in Tasks 2, 3 and 5.
