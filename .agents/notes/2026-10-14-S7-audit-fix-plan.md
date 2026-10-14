# S7 F1 Audit-Tool Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close integration-review finding F1 — make `s7_gui_audit.py` unable to silently skip a required contrast measurement (missing element must fail loudly) and make the events-tab neutral-chip measurement wait for the asynchronously rendered event cards, with real-Chrome RED/GREEN evidence on unique `s7-f1-*` paths.

**Architecture:** Two minimal edits inside the existing audit artifact (a guard in `measure_contrast`, a `wait_true` before the `.chip-st-evt` measurement mirroring the xss step's `pre.raw` wait), proven by a standalone regression script that imports the audit module and drives real headless Chrome over CDP (same pattern as `.agents/notes/2026-10-14-S7-integration-capture.py`), plus one full before/after re-run of the audit itself.

**Tech Stack:** Python >=3.9 standard library only; actual headless Chrome via CDP; real `ui-demo` stdlib server. No runtime dependencies, no unittest wiring — the regression is an audit artifact under `.agents/notes/`.

**Spec:** F1 in [.agents/notes/2026-10-14-S7-gui-integration-review.md](2026-10-14-S7-gui-integration-review.md); [S7 sprint](../../docs/superpowers/sprints/2026-10-14-S7-plan.md); [DESIGN.md](../../DESIGN.md); [AGENTS.md](../../AGENTS.md).

## Global Constraints

- Ownership ONLY: `docs/superpowers/acceptances/assets/S7/s7_gui_audit.py`, the standalone regression + evidence under `.agents/notes/`, and `.agents/notes/2026-10-14-S7-audit-fix-report.md`. NO CSS/JS/index.html/API/runtime/website/ledger/main/acceptance-record changes; no merge, no push, no extra workers, no local approval UI.
- Committed S7 evidence under `docs/superpowers/acceptances/assets/S7/` is historical: new outputs go to temp dirs and only retained authentic artifacts land under `.agents/notes/assets/s7-f1-*` unique paths — never overwrite old reports.
- Python >=3.9, zero runtime dependencies; the regression script is an audit artifact, not a package module and not added to unittest discovery.
- Verified root cause (source + committed evidence): `measure_contrast` records `"element missing"` and returns with **no** `check()` (s7_gui_audit.py:296-301); the events step measures `.chip-st-evt` right after `open_tab` (s7_gui_audit.py:1030-1034) which returns once the tabpanel has *any* child — the events panel renders a loading note first and loads cards async (app.js:710-757, `activateTab` comment app.js:876). Committed before/after results both contain exactly one `"element missing"` (the neutral chip) and no corresponding check among 199/34.
- Scoped gates: `python3 -m compileall -q work_runtime tests scripts` and `python3 scripts/check_docs.py`; actual-Chrome regression probe + full after-phase audit. No full core/demo/install repeats (artifact-only fix; `s7_gui_audit.py` matches no `doc_sync_map` row).

## Review Focus

- Missing selector in **after** phase silently skips a required measurement → must append a FAILing check (regression P1).
- Missing selector in **before** phase would equally false-pass → guard must fire in both phases (regression P1b).
- Guard must not false-fail or double-report when the element IS present → exactly one new check per present-element probe (regression P0, P2).
- The events race must stay fixed inside the audit's own flow, not just in a helper → full after-phase GREEN run contains a real neutral-chip ratio check (≈12.78 ≥ 4.5) and zero `"element missing"` measurements.
- New evidence must not shadow committed history → all retained artifacts under unique `s7-f1-*` names.

---

### Task 1: Standalone real-Chrome regression (RED first)

**Files:**
- Create: `.agents/notes/2026-10-14-S7-audit-fix-regression.py`
- Evidence out: temp dir; retain transcripts/JSON under `.agents/notes/assets/s7-f1-red/`

**Interfaces:**
- Consumes: `s7_gui_audit` module loaded via `importlib.util.spec_from_file_location` from `docs/superpowers/acceptances/assets/S7/s7_gui_audit.py` — helpers `UiServer`, `CdpPage`, `settle_list`, `select_work`, `open_tab`, `wait_true`, `measure_contrast`; module globals `RESULTS`, `RECORD`.
- Produces: exit 0 iff every assertion holds; prints `PASS/FAIL` lines and a `s7-f1-regression-results.json` record into `--out`.

- [ ] **Step 1: Write the regression script with probes P0/P1/P1b/P2**

  Real `ui-demo` server + real headless Chrome (copy the launch block from `2026-10-14-S7-integration-capture.py`), 1440×900, navigate, `settle_list`, `select_work(page, "wait-1")`. Local `check()` into a script-local RESULTS (do not count audit-internal checks as script assertions):

  - **P0 present-element control (overview, sync surface):** snapshot `len(audit.RESULTS)`, call `audit.measure_contrast(page, "P0 waiting warn chip", ".chip-st-waiting", 4.5, "after")`; assert exactly one new check appended and it is ok, and the `RECORD` measurement is a dict with `ratio >= 4.5`.
  - **P2 events race:** `audit.open_tab(page, "events")`; immediately record (no assertion) whether `.chip-st-evt` exists — this is the observed race; then `audit.wait_true(page, "!!document.querySelector('#detail-body .chip-st-evt')")`; assert chip present; snapshot and call `audit.measure_contrast(page, "P2 events neutral chip", ".chip-st-evt", 4.5, "after")`; assert exactly one new ok check and a dict measurement with `ratio >= 4.5` (expected ≈12.78, ink on `#eceae4`).
  - **P1 missing-selector negative (after):** snapshot, call `audit.measure_contrast(page, "P1 negative control absent selector", ".s7-f1-definitely-not-present", 4.5, "after")`; assert exactly one new check appended AND it is NOT ok (loud failure), AND the measurement is recorded as `"element missing"`.
  - **P1b missing-selector negative (before):** same with `phase="before"`; assert the loud failing check also fires in the baseline phase.

- [ ] **Step 2: Run pre-fix → observe RED**

  Run: `python3 .agents/notes/2026-10-14-S7-audit-fix-regression.py --out /tmp/s7-f1-red`
  Expected: **exit 1** — P1/P1b FAIL with "no check appended" (the silent-skip bug); P0/P2 may pass. Save the transcript.

- [ ] **Step 3: Reproduce the committed false pass pre-fix (full audit, real Chrome)**

  Run: `python3 docs/superpowers/acceptances/assets/S7/s7_gui_audit.py --phase after --out /tmp/s7-f1-red-full`
  Expected: result line `s7 audit (after): 199 checks, 0 failed` (exit 0 — the false pass), with `after-results.json` containing `"contrast base chip (unknown/extra classes neutral)": "element missing"` and no matching check. Retain `after-results.json` → `.agents/notes/assets/s7-f1-red/s7-f1-red-after-results.json` (plus `view-events.png` from the RED run as the loading-state artifact).

### Task 2: Minimal fix in the audit artifact

**Files:**
- Modify: `docs/superpowers/acceptances/assets/S7/s7_gui_audit.py:296-301` (guard) and `:1030-1035` (events wait)

**Interfaces:**
- Consumes: existing `measure`, `check`, `wait_true`, `page_pair`.
- Produces: `measure_contrast` appends a FAILing `check("contrast <label> >= <min>", False, "element missing — selector ... matched nothing")` in **every** phase when `page_pair` returns None; the events step waits for `#detail-body .chip-st-evt` before measuring.

- [ ] **Step 1: Guard `measure_contrast`** — keep the existing `measure("contrast " + label, "element missing")`, then add the `check(...)` with ok=False and a message naming the selector, then `return`. One comment line citing F1.

- [ ] **Step 2: Wait for the event chip in the events step** — between `open_tab(page, "events")` and the `measure_contrast(... ".chip-st-evt" ...)` call, insert `wait_true(page, "!!document.querySelector('#detail-body .chip-st-evt')")` with a comment mirroring the xss step's rationale (panel renders a loading note first, cards load async). No other call sites change — decisions/operations/evidence/documents render synchronously from the preloaded `/api/work` payload.

- [ ] **Step 3: Run regression → observe GREEN**

  Run: `python3 .agents/notes/2026-10-14-S7-audit-fix-regression.py --out /tmp/s7-f1-green`
  Expected: **exit 0**, all P0/P1/P1b/P2 assertions pass.

### Task 3: GREEN full audit, scoped gates, evidence, report, commit

**Files:**
- Evidence: retain under `.agents/notes/assets/s7-f1-after/`
- Create: `.agents/notes/2026-10-14-S7-audit-fix-report.md`

- [ ] **Step 1: Full after-phase audit post-fix (real Chrome)**

  Run: `python3 docs/superpowers/acceptances/assets/S7/s7_gui_audit.py --phase after --out /tmp/s7-f1-after`
  Expected: exit 0; result line reports the actual count (expected 200 — 199 + the now-real neutral-chip check; report the exact observed number), 0 failed. From `after-results.json` verify: neutral-chip measurement is a dict with ratio ≈12.78 ≥ 4.5 and a matching ok check; **zero** `"element missing"` measurements; the three six-table equality checks ok; matrix capture count unchanged.

- [ ] **Step 2: Retain authentic GREEN artifacts** — `after-results.json` → `.agents/notes/assets/s7-f1-after/s7-f1-after-results.json`; `view-events.png` (event cards + neutral chips in frame) → `.agents/notes/assets/s7-f1-after/s7-f1-view-events.png`; regression GREEN transcript + JSON. No committed S7 asset path is touched.

- [ ] **Step 3: Scoped gates** — `python3 -m compileall -q work_runtime tests scripts` → silent; `python3 scripts/check_docs.py` → 0 broken. (No doc-sync arrears: changed paths match no `doc_sync_map` row.)

- [ ] **Step 4: Write `.agents/notes/2026-10-14-S7-audit-fix-report.md`** — verified F1 claims, root cause with file:line, RED/GREEN evidence (commands, exit codes, exact counts, neutral ratio), evidence path inventory, limitations (F2 native-select arrows and F3 vision reads unchanged; historical committed evidence intentionally preserved), commit hash.

- [ ] **Step 5: Commit scoped changes** — one commit: `s7_gui_audit.py` + regression script + `s7-f1-*` evidence + report note. Then a single `worker_done` with the exact hash, counts, RED/GREEN summary and limitations; idle.

## Self-review

Every F1 requirement maps to a task: loud missing-element failure (T1 P1/P1b → T2 guard), events-chip wait (T1 P2 → T2 wait), full required-check re-run with actual counts + neutral 12.78 ≥ 4.5 + no unexpected missing measurements + six-table/interaction re-proof (T3 full run), unique evidence paths preserving history (T1/T3 retention steps), scoped gates (T3), report + single worker_done (T3). No step touches files outside the ownership list; no plan line decides nothing.
