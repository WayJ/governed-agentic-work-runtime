# S7 F1 audit-tool correction — 2026-10-14

Dispatched correction of integration-review finding F1
([review](2026-10-14-S7-gui-integration-review.md)), executed by the
original GUI owner in a fresh isolated checkout `s7-gui-audit-fix` at
`600c7aa` (branch `WayJ/s7-gui-audit-fix`) so the user-owned original GUI
terminal was preserved. Scoped plan:
[2026-10-14-S7-audit-fix-plan.md](2026-10-14-S7-audit-fix-plan.md).

## F1 claims verified against source before fixing

- `measure_contrast` recorded `"element missing"` and returned **without
  creating a check** (s7_gui_audit.py:296-301 pre-fix), so an omitted
  required measurement could never fail the run.
- The events step measured `.chip-st-evt` immediately after
  `open_tab(page, "events")` (s7_gui_audit.py:1030-1034 pre-fix), but
  `open_tab` only waits for the tabpanel to have *any* child: the events
  panel first renders a loading note (app.js:722) and loads its cards
  asynchronously (`renderEventsPanel` → `loadEvents`, app.js:710-757;
  `activateTab`'s own comment, app.js:876). The other detail panels render
  synchronously from the preloaded `/api/work` payload, which is why only
  this measurement raced.
- Committed evidence confirmed: both `before-results.json` and
  `after-results.json` under `docs/superpowers/acceptances/assets/S7/`
  contain exactly one `"element missing"` (the neutral chip) and **no**
  `contrast base chip … >= 4.50` check among the 34/199 checks — the
  required neutral-fallback contrast was silently never asserted while the
  after run exited 0.

## Fix (minimal, audit artifact only)

`docs/superpowers/acceptances/assets/S7/s7_gui_audit.py`, +13/−1:

1. `measure_contrast` now appends a **failing** check
   (`contrast <label> >= <min>` → `element missing — selector … matched
   nothing`) in **every phase** when its element is missing, in addition
   to the existing measurement record, so no phase can falsely pass with
   a required measurement omitted.
2. The events step now waits for a rendered event chip
   (`wait_true(page, "!!document.querySelector('#detail-body
   .chip-st-evt')")`) before measuring — the same wait pattern the xss
   step already used for `pre.raw`. The `view-events.png` capture now
   follows the rendered cards too.

No product file changed (CSS/JS/index/API/runtime/website untouched); no
acceptance record, ledger, merge or push. `s7_gui_audit.py` matches no
`doc_sync_map` row, so no doc arrears.

## RED → GREEN evidence (actual Chrome/CDP this checkout)

Standalone regression (audit artifact, imports the audit module):
`.agents/notes/2026-10-14-S7-audit-fix-regression.py` — probes P0
(present-element control), P2 (events race + measured chip), P1/P1b
(missing-selector negatives, after/before phases).

| run | command | result | exit |
|---|---|---|---|
| RED regression | `python3 .agents/notes/2026-10-14-S7-audit-fix-regression.py --out /tmp/s7-f1-red` | `14 assertions, 3 failed` — P1/P1b append **no** check (silent skip); live race observed: `.chip-st-evt` absent immediately after `open_tab` | 1 |
| RED full audit (false pass reproduced) | `python3 docs/superpowers/acceptances/assets/S7/s7_gui_audit.py --phase after --out /tmp/s7-f1-red-full` | `199 checks, 0 failed`, neutral chip `"element missing"`, zero `base chip` checks | 0 |
| GREEN regression (post-fix) | `…-regression.py --out /tmp/s7-f1-green` | `14 assertions, 0 failed`; the audit's own check now FAILs loudly on the missing selector | 0 |
| GREEN full audit (post-fix) | `…s7_gui_audit.py --phase after --out /tmp/s7-f1-after` | **`200 checks, 0 failed`** (199 + the now-real neutral-chip check) | 0 |

GREEN full-audit verification from `after-results.json`: neutral chip
measured `rgb(38, 37, 30)` on `rgb(236, 234, 228)` = **12.78 ≥ 4.5**
(matches the review's one-off); **zero** `"element missing"` measurements;
six-table no-writes equality 3/3 (demo/empty/xss); matrix captures 30/30
pngs — all required current checks and interactions re-proven in this run.

Scoped gates: `python3 -m compileall -q work_runtime tests scripts` → OK;
`python3 scripts/check_docs.py` → 73 markdown files, 249 local links,
0 broken. Full core/demo/install suites not rerun (artifact-only fix;
product tree byte-identical to `600c7aa`).

## Evidence inventory (unique F1 paths; committed S7 evidence untouched)

- `.agents/notes/assets/s7-f1-red/` — regression RED transcript+JSON,
  full-run RED transcript+results, RED `view-events.png` (loading-state
  artifact), regression events-chip capture.
- `.agents/notes/assets/s7-f1-after/` — GREEN full-audit
  transcript+results, GREEN regression transcript+JSON, GREEN
  `view-events.png` (event cards with neutral chips in frame).

## Limitations / unchanged

- F2 (native-select arrow keys unprovable on this Chrome build) and F3
  (vision reads hallucinate shadows; computed styles remain the only
  visual acceptance basis) are unchanged review notes, not addressed here.
- The committed before/after evidence under
  `docs/superpowers/acceptances/assets/S7/` is preserved as historical
  (its neutral-chip gap is now documented here and closed going forward);
  a before-phase rerun with the fixed tool was not required by the
  dispatch and was not run.
- Integration owns merge/review of this fix and the final release after
  the website owner completes.
