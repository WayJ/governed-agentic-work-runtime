# S8 Task4 viewer integration review — PASS, assembled — 2026-10-15

Independent Orca integration acceptance of the S8 viewer slice (D37), on the
same control checkout as the core review (base `41583e2`). Distinct from the
owner's in-session self-review in
[the viewer report](2026-10-15-S8-viewer-report.md). No product files modified
by this review; browser/probe outputs live under `/tmp`.

## Scope and source

- Source: `WayJ/s8-revocation-viewer` tip `37ef814` (exact SHA verified),
  merge-base `41583e2` (= accepted core + my Task2 review), **5 scoped
  commits**; files: `work_runtime/inspection.py`, `web/app.js`, `web/app.css`,
  `tests/test_revocation_viewer.py` (new), `tests/test_inspection.py`,
  `docs/gui-api.md`, `docs/gui.md`, scoped plan, report/browser script/evidence
  assets. **No runtime/policy/adapters/CLI/demo/verifier/README changes; D37
  read-only only; index.html untouched.**
- Assembly: `git merge --no-ff 37ef814` → control merge commit `38914f7`.
- Preview `127.0.0.1:52719` untouched (script serves ephemeral loopback ports
  only); demo owner's branch/worktree (task `cd10a7c66925`) untouched.

## Static review (D37 + DESIGN.md, read in full)

- **Reader**: `evidence[].id` = valid nonempty stored string else `null`
  (strict `type(x) is str`; `body_raw`/`data_raw` unchanged); top-level
  `revoked_evidence` `{id, source, event_id, kind, status}` for stored
  `revoked` rows in the same (source, event_id) order;
  `completion_revoked_evidence_ids` = valid-string citations ∩ valid revoked
  ids, stored citation order, deduplicated; cancellation completions
  (acknowledged operations) contribute nothing. All derived inside the single
  existing read-only snapshot; nothing persisted; no Runtime/policy built.
- **Viewer**: notice gated on `work.status === "closed"` AND non-empty
  `revoked_evidence`; citation line only when the API actually derived cited
  ids; EN/ZH copy distinguishes unchanged historical closure from corrected
  current status; buttons jump to Evidence/Events tabs; older backends without
  the keys render no notice. `el()`/`t()` are `textContent`/string-split only —
  no `*_raw` parsing, no `innerHTML`, exact ids via `String()`.
- **DESIGN tokens**: cream-soft `#fafaf7` surface, 1px `#cfcdc4`
  hairline-strong, 12px card radius, no shadow, ink/body text colors, 4px-scale
  spacing, ≥44px touch-target button base with `:focus-visible`; revoked chip
  joins the pre-existing measured error tokens (`#b32449` on `#f9e8ec`) — not
  timeline pastels; no new action color, no display typography. Material
  adaptations (neutral non-error notice surface; meaning in text, both
  languages) documented by the owner and consistent with D37's wording.
- `docs/gui-api.md`/`gui.md` document the new fields truthfully (shapes,
  valid-string-or-null rule, current-vs-historical distinction, no numeric
  coercion). doc_sync_map rows (runtime/adapters/check_docs/check_site) not
  triggered by this slice; reader docs updated regardless.

## Fresh verification on assembled control `38914f7`

| item | command | actual result |
|---|---|---|
| viewer tests | `python3 -m unittest tests.test_revocation_viewer -v` | **11 tests OK** (9 reader + 2 HTTP — counted independently) |
| reader regression | `tests.test_inspection` | 37 OK (shape set extended with `id`; no new test) |
| UI regressions | `tests.test_ui_cli tests.test_ui_demo tests.test_ui_server` | 54 OK, skipped=1 (pre-existing backend skip) |
| full suite | `python3 -m unittest discover -s tests` | **Ran 690 tests … OK (skipped=1)** |
| contracts | `python3 scripts/check_docs.py` | **79 markdown files, 305 links, 0 broken** |
| syntax / site | `compileall` / `check_site.py` | clean / 2 pages 0 findings |
| demos | `demo`, `publish-demo`, `intervention-demo`, `adoption-demo` | all exit 0 |

### Count reconciliation (reported, not reproduced)

- Actual discovered total **690** (skip 1) = 679 base + **11** new. The
  owner's prose "679 baseline + 13 new tests" is arithmetically wrong
  (679+13=692 ≠ 690); their own gate table and this fresh run agree on 690.
  The 11 are exactly the viewer file's 9 reader + 2 HTTP tests;
  `test_inspection.py` adds assertions, not tests.
- Contracts 79 files here vs the owner's 84: links (305) and broken (0)
  identical; the extra 5 files were untracked worktree-local markdown in the
  owner's checkout (same class as the core owner's 79-vs-78). 79 = previous
  78 + 1 new plan file.

## Browser evidence (actual Chrome/CDP, this machine)

- **Fresh GREEN on the assembled tree**: `python3
  .agents/notes/2026-10-15-S8-viewer-browser.py --phase green --out
  /tmp/s8vg-fresh` → **30/30 checks, exit 0**: notice shown on
  succeed/cancel/unbound-closed, absent on open-revoked/clean-closed; EN+ZH
  history/current wording; derived citation count + exact id only on
  succeed-closed; computed styles exactly the DESIGN tokens above;
  keyboard Enter/ArrowRight; ≥5.6 s poll retention with list focus;
  disconnect banner + same-port recovery; huge integer `10000000000000001`
  exact text (string-literal probe); no horizontal overflow at 1440/390/320;
  **all six store tables byte-identical** before/after the session.
- **Contrast**: script-measured 15.38:1 (title), 7.11:1 (body), 5.45:1
  (revoked chip); my independent WCAG recomputation against `#fafaf7`:
  14.7:1 / 6.8:1 / 5.45:1 — all ≥4.5:1 under either arithmetic (chip exact).
  Missing-element contrast checks fail loudly (S7 guard); async readiness is
  explicit (`settle_list`/`wait_detail`/`wait_true` timeouts), and a missing
  notice selector makes `present=false`, which fails GREEN — verified by the
  RED run below.
- **Independent RED reproduction**: extracted pre-notice commit `542db87`
  (reader API present, notice absent) via `git archive` into `/tmp` (no
  worktree) and ran the same script `--phase red` → **8/8, exit 0**: derived
  API present, notice missing on all five works (the demonstrated gap), chip
  still on the neutral base, six-table equality. The committed
  `s8-viewer-red-results.json` (8 checks, ok) is therefore genuine
  before-fix evidence, not a missing test; reinterpreted on the fixed tree it
  correctly fails, which is why GREEN is the fresh phase here.
- **Screenshots**: 7 fresh captures at exact 1440×900 / 390×844 / 320×690
  (+ clean-closed, ZH, evidence tab). This harness could not render images
  (`[Unsupported Image]` for PNG and JPEG), so no visual eyeball claim is
  made; instead stdlib pixel forensics (own decoder, exact-match):
  committed succeed-closed desktop has **124,471** cream-soft `#fafaf7`
  pixels vs **17,804** on clean-closed (notice surface present only where
  the notice exists — corroborates the owner's JSON exactly), chip
  `#f9e8ec` **1,035** px in the evidence capture (owner: 1035), canvas
  `#f7f7f4` + white cards + ink present everywhere (no blanks); fresh
  captures match committed within ±60 px (antialias noise).

## Findings

**No material findings; PASS.** Reconciliation notes only (no owner
correction required): the +13-vs-11 new-test prose slip; the 84-vs-79
contracts file count (worktree-local files); the S7 contrast helper's
title/body ratios (15.38/7.11) sit ~4% above the textbook recomputation
(14.7/6.8) — both far above threshold, chip exact at 5.45.

## Carrier and interfaces

- Carrier `WayJ/sprint-s8-revocation` fast-forwarded to the control tip
  (= merge `38914f7` + this note; exact SHA in the worker report). No
  main/root merge or push, no sprint acceptance flip — final S8 acceptance
  waits for the demo owner (task `cd10a7c66925`, still running) and a fresh
  final dispatch.
- Public surface added for consumers: `work_detail`/`GET /api/work` now
  carry `evidence[].id` (valid string or `null`), `revoked_evidence[]`
  (`{id, source, event_id, kind, status}`) and
  `completion_revoked_evidence_ids[]` — additive, read-only, documented in
  `docs/gui-api.md`.

## Risks / limits (truthful)

- Browser evidence used this machine's headless Chrome via CDP; stores seeded
  fresh per run into temp dirs; the user preview was never touched.
- Screenshot verification is programmatic (dimensions + exact pixel
  structure + fresh-vs-committed comparison) because this session's harness
  cannot display images; the live CDP session is the first-hand visual
  evidence source.
- TD-1 and all core limits from the Task2 review remain unchanged; no
  compensation/fencing/key-rotation claims; viewer writes nothing (six-table
  equality in both browser phases + reader zero-write test).
