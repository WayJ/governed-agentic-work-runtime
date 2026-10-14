# S7 GUI integration review — 2026-10-14 (independent, technical pass only)

Independent integration owner: control checkout `s7-release-control`
(`WayJ/s7-release-control`). **Technical GUI review result: PASS.** This is
NOT sprint acceptance: no acceptance record written, no sprint-doc state
change, no main merge/push, no release or publication claim. The dependent
website-image refresh (Task2) and final integration (Task3) are still owed.

## What was combined

- Base `2f76f7f` + master strategic docs through `c36b30d` (resume/dispatch,
  public roadmap, next-core recon, audit-status binding — preserved verbatim).
- Scoped GUI branch `WayJ/s7-gui-interface` `41bae0e` merged as an ordinary
  merge → merge commit `c8138fe` on `WayJ/s7-release-control`.
- Scope verified by `git diff --name-only 2f76f7f..41bae0e`: product change is
  **only** `work_runtime/web/app.css`. `index.html`, `app.js`, backend, API,
  policy, schema, tests, scripts, website and packaging configs
  (`pyproject.toml`/`setup.py` absent from the diff) are untouched — CSS-only
  product change as claimed; no API/state-change surface exists in the diff.
- This review commit adds only this note, the supplementary capture script
  and fresh evidence under unique `s7-integration-*` paths in
  `.agents/notes/assets/`.

## Independent browser evidence (actual Chrome/CDP, this checkout, this run)

All commands run in `s7-release-control` at merge `c8138fe` (report written
before the review commit; final commit SHA recorded below).

1. **Full after-phase audit, rerun independently at the actual source:**

   ```
   python3 docs/superpowers/acceptances/assets/S7/s7_gui_audit.py \
       --phase after --out /tmp/s7-integration-after
   ```

   Result line: `s7 audit (after): 199 checks, 0 failed`, real script exit
   code **0** captured as `$?` immediately after the python process (no outer
   echo/pipeline masking). Fresh evidence: 30 matrix PNGs + 12 view PNGs +
   `after-results.json` regenerated in `/tmp` (kept copy:
   `.agents/notes/assets/s7-integration-after-results.json`).

   Coverage independently re-proven on the combined tree: first-load 5 works
   and S5 empty-readiness race fix, keyboard ArrowDown×2+Enter selection, list
   arrows, `/` search focus + filter + clear, status-filter keyboard select,
   language toggle both directions, manual refresh, polling pause/resume
   (including while disconnected), tab-arrow live focus at 1440/390/320,
   loading state under emulated latency, empty store, UNKNOWN_WORK gone state
   with retry, disconnect banner after server kill, hostile markup inert
   (goal/events/evidence surfaces, `window.__xssEvil` undefined), huge
   `2**53+1` and 30-digit integer exactness, six-table digest equality on the
   demo/empty/xss stores after all reads/interactions, tokens/typography/
   radii/no-shadows/44px/1200px-cap/single-column-<1024/`overflow-x: visible`
   visual assertions, measured contrast (all text pairs ≥4.5, focus ring
   3.52 non-text ≥3), zh zero display tracking.

   Measured contrast in this run (matches builder report to 2 decimals):
   body/canvas 14.33 · primary control and selected tab 14.33 · selected work
   14.70 · body on white 7.11 · body on `#eceae4` 5.91 · success chip 5.58 ·
   warn chip 5.55 · error chip/banner 5.45 · focus ring 3.52 (non-text).

2. **Supplementary topbar/controls capture (new, closes the matrix gap):**
   the committed matrix scrolls `.detail-body` into view before each shot, so
   narrow-viewport captures cannot standalone prove the header. Script
   `.agents/notes/2026-10-14-S7-integration-capture.py` (reuses the audit's
   CDP client; audit artifact only):

   ```
   python3 .agents/notes/2026-10-14-S7-integration-capture.py \
       --out /tmp/s7-integration-capture
   ```

   Result: **51 assertions, 0 failed**, exit 0. At 1440/390/320 × en/zh:
   topbar inside the viewport at scrollY 0 (white card, 1px `#e6e5e0`
   hairline), all controls present with heights ≥44px (refresh measured 44px
   at every width), no box-shadow on any topbar control, refresh control
   ink/canvas tokens, meta-chip small text 5.91:1, trusted-Tab keyboard focus
   lands on `#refresh` with the 2px `#f54e00` ring (offset 2), and no
   page-level horizontal overflow with a detail open at 390/320.
   Screenshots committed under unique paths: `s7-integration-top-{w}-{lang}`
   (header/controls proof), `s7-integration-detail-{w}-{lang}` (scrolled
   detail, events tab), `s7-integration-focus-{w}-en` (topbar focus ring).

3. **Neutral fallback chip actually measured (see finding F1):** one-off
   check waiting for async event cards, then reading `.chip-st-evt`: ink
   `#26251e` on `#eceae4`, pill radius 9999px, **12.78:1** — the unknown/
   unanticipated status class renders legibly neutral, now with real
   measured evidence.

## Screenshot authenticity (no CDN-mapped/stale reads)

Harness image reads map local PNGs to a CDN cache; the builder already
caught one stale read under a shared basename. All conclusions here rest on
local, reproducible checks instead:

- Full-pixel stdlib scan (PNG decoded via zlib, no dependencies) of all 15
  fresh captures: cream canvas `#f7f7f4`, white cards, ink text present in
  every shot; orange `#f54e00` present in every top shot (brand mark, 84px)
  and every focus shot (brand mark + 2px ring, 562px) and absent in detail
  shots (no brand/focus in frame) — exact expected distribution.
- Committed builder evidence re-verified the same way: `before-matrix`
  captures show the old theme (`#f5f7fa` bg, `#eef1f6` neutral), `after`
  captures the new one (`#f7f7f4` canvas, `#eceae4` neutral) — genuinely
  distinct before/after records.
- Two supplementary vision reads of freshly uploaded, never-before-used
  basenames described the expected layout (topbar contents, 4-line clean
  wrap at 320px, dark refresh control, orange brand mark, no clipping) but
  hallucinated "drop shadows" on cards — computed `box-shadow: none`
  assertions from the CDP runs are authoritative; vision reads are
  supplementary only and are not the acceptance basis.

## Audit-validity inspection (routed-correction follow-ups)

- **ORDER BY**: `snapshot()` uses `ORDER BY 1, 2` — valid for the actual
  two-column works/metadata schema (the original `ORDER BY 3` failure is
  gone from source; master's reproduced fixture failure and the real
  baseline `EXIT=1` are consistent with history).
- **Invalid JSON**: hostile markup now lives inside valid JSON string values
  (`make_xss_fixture` writes `json.dumps(...)` bodies); no literal-`<script>`
  prefix before an object is parsed anywhere.
- **Root depth**: repo root is derived from the script's own location, so
  the rerun served the merged tree of *this* checkout (proven: it ran here
  with no GUI worktree involvement).
- **Quoted JS / Enter**: CDP Enter carries `text:"\r"`; tab-arrow and select
  interactions use trusted `Input.dispatchKeyEvent`, never DOM `.click()`.
- **Locale**: `--lang=en-US` does not override `navigator.language` on this
  machine; audit is locale-agnostic via `ensure_lang` (documented in-script).
- **Physical-key limitation (open, disclosed)**: this Chrome build ignores
  CDP arrow keys on the native status `<select>`; the filter is exercised by
  the native type-to-jump letter key (still a trusted CDP key). A physical
  arrow press remains expected-but-unproven, as the builder disclosed.
- **Real exit code**: observed directly as the python process exit status in
  both runs above (0), not an outer wrapper echo.

## Gates run here (scoped; full core/demo/install rerun at final integration)

- `python3 -m unittest tests.test_ui_cli tests.test_ui_demo
  tests.test_ui_server -v` → **54 tests OK (skipped=1)** (GUI scope).
- `python3 scripts/check_docs.py` → 69 markdown files, 249 local links,
  **0 broken** (rerun after this commit below).
- `python3 scripts/check_site.py` → 2 pages, **0 findings**.
- `python3 -m compileall -q work_runtime tests scripts` → OK.
- Packaging scope: `pyproject.toml` unchanged; fresh-venv `pip install .` →
  installed `work_runtime/web/app.css` **byte-equal** (sha256 match) to the
  checkout restyle; packaged web dir exactly `[app.css, app.js, index.html]`
  (no new assets, no scope change). `verify_install.py` itself reruns at
  final integration per plan.
- Doc-sync map: no changed path matches any `doc_sync_map` row
  (runtime.py/adapters.py/check_docs.py/check_site.py all untouched);
  `docs/gui.md` (self-documenting, not a mapped doc) updated by the GUI
  branch. **No doc-sync arrears.**

## Material findings (route to original GUI owner; none block this pass)

- **F1 (audit artifact, not product)**: `measure_contrast(page, "base chip
  (unknown/extra classes neutral)", ".chip-st-evt", ...)` runs immediately
  after `open_tab(page, "events")` without waiting for the asynchronously
  rendered event cards, and `measure_contrast` records `"element missing"`
  and returns **without creating a check**. Both the committed after run and
  my independent rerun therefore contain that measurement as
  `element missing` — the claimed neutral-fallback contrast was silently
  never asserted inside the 199 checks. I closed the gap with a waiting
  one-off (12.78:1, above), so the requirement is met, but the audit tool
  should get the same `wait_true` the xss step already uses, and
  `measure_contrast` should fail (or loudly record) when its element is
  missing, so future runs cannot silently skip a required measurement.
- **F2 (disclosed limitation, unchanged)**: native-select arrow keys remain
  machine-unprovable on this Chrome build (type-to-jump fallback used).
- **F3 (note)**: vision-model reads hallucinate card shadows on hairline
  cards; keep computed styles as the only visual acceptance basis (already
  the project rule).

## Applied tokens / adaptations / gaps (cross-checked against DESIGN.md)

Tokens applied centrally (`--color-*`, `--radius-control|card|chip`,
`--space-xxs..lg`, `--font-sans|mono`, `--tracking-display-*`,
`--content-max`) and asserted computed in-browser: canvas `#f7f7f4`, ink
`#26251e`, body `#5a5852`, white cards, hairlines `#e6e5e0`/`#cfcdc4`,
orange `#f54e00` scarce non-text only, 8px controls / 12px cards / pill
chips, display 26/22px weight 400 (zh tracking 0), labels 16/600, body 15,
small/code/table 13, mono JetBrains-Mono-first with system fallback, no
shadows, 44px targets, 1200px cap, single column <1024, no document
overflow hiding. Documented, ratified adaptations: measured semantic shades
(success `#146c4e`, warn `#8a5400`, error `#b32449` on their tints, all
≥4.5), neutral chip base instead of DESIGN muted `#807d72` (fails 4.5),
no timeline pastels (no such stages exist in this store), operations
density instead of marketing rhythm, touch targets 44px over the reference
40px. No gaps found beyond F1–F3 above; one engine (Chromium) tested, as
disclosed by the builder.

## Carrier status (BASE for the separately-dispatched screenshot owner)

Combined branch = merge commit `c8138fe` (base `2f76f7f` + master `c36b30d`
+ GUI `41bae0e`) plus this review commit (branch tip). Carrier
`WayJ/sprint-s7-gui` (worktree `sprint-s7-gui`, was `c36b30d`) is
fast-forwarded to the review tip — exact SHA reported in `worker_done` and
visible as `git rev-parse WayJ/sprint-s7-gui`. Local only; nothing pushed
(no main merge/push, no release). Suitable as the base for Task2 (four
website screenshot refreshes + `docs/website.md`) and Task3 (final
integration, full gates, acceptance, main merge, CI/Pages proofs).

## Verdict

**Technical GUI review: PASS** — independent 199/199 audit + 51/51
supplementary assertions + neutral-chip 12.78:1 + scoped gates + packaging
byte-equality on the combined control branch. Sprint acceptance, release,
publication and any F1 audit-tool fix remain with their owners.
