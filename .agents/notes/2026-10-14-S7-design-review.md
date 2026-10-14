# S7 operations-viewer restyle — design-only builder review, 2026-10-14

Reviewer: s7 planning worktree (`WayJ/s7-gui-design-plan`). Design and roadmap read at
`4187e0c`; the coordinator's draft plan
[`docs/superpowers/plans/2026-10-14-s7-gui-design-alignment.md`](../../docs/superpowers/plans/2026-10-14-s7-gui-design-alignment.md)
at `8d99080` was also read after the coordinator's status message. Examined: S7 design
spec, E7 roadmap, [DESIGN.md](../../DESIGN.md), AGENTS.md UI agreement, S5 design +
[gui-api.md](../../docs/gui-api.md) + [gui.md](../../docs/gui.md), actual
`work_runtime/web/{app.css,index.html,app.js}`, `tests/test_ui_server.py`,
`scripts/verify_install.py`, `pyproject.toml`, `work_runtime/cli.py`, S5/S6 design-review
and acceptance notes, `website/assets/`. Grounding is static source reading plus
independently computed WCAG contrast (Python, this review); no server was started, no
browser driven, no product file touched — design-only dispatch. Only this note is
committed.

## Verdict

**Implementable exactly as scoped, and no important unanswered questions remain** — the
design's own claim "No unresolved external decision is needed for this visual scope"
survives grounding. Ranked question list: **empty** (nothing important left). The plan-
shaping finding behind that emptiness: every named accessibility/layout requirement is
reachable **purely in `app.css`** while keeping `app.js`'s runtime-generated class
contract, so the anticipated implementation needs **no `index.html`/`app.js` edits at
all** and the RED/GREEN path likely stays unused unless a real reproduced defect surfaces.

## Why no question survives (materiality test applied)

- The known traps are pre-decided in the design: orange text contrast (3.52/4.37) with
  ink/canvas primary controls and the white/`#d04200` 4.71 alternative; muted `#807d72`
  banned for small text; ≥44px targets; `<1024` single column; no timeline pastels for
  status; evidence rules (screenshots/computed styles, trusted keyboard, no keyword
  scans); ownership chain. Each checks out against the actual code and math below.
- Remaining choices are explicitly pre-delegated to the builder in the design's
  Ownership section (semantic shades, token names, table overflow strategy, minor panel
  sizing, audit machinery) with safe defaults — listed at the end for traceability, not
  as questions.

## Grounded coverage by acceptance axis

1. **Design tokens.** Current `:root` (`app.css:3-19`) is blue/gray (`--bg #f5f7fa`,
   `--accent #2456c6`, 6/8/10/16px radii, weight 650, 12px raw mono, collapse at
   899px, blue `.tab[aria-selected]`/summary/hover accents) → all replaced by the
   documented token set (canvas/ink/body, hairlines, scarce orange, 8/12 radii, 4px
   scale, display 26/22 @400, labels 16/18 @600, body 14–16, code 13, `<1024` single
   column, 1200px cap). **Constraint a plan must keep:** `chipClass()`
   (`app.js:211-214`) generates `chip-st-<status>`/`chip-decision-*`/`chip-st-<code>`
   class names at runtime from **stored, dynamically discovered** strings — CSS must
   style the base `.chip` neutrally and treat every specific status selector as an
   enhancement, so unknown store statuses can never render unstyled. Event types are
   always the static `chip-st-evt` (`app.js:744`). `applyI18n` sets
   `documentElement.lang` (`app.js:241`), so Chinese zero-tracking is reachable with
   `:lang(zh)` — CSS-only. Font stacks merge to system sans + CJK fallbacks with
   locally referenced `'JetBrains Mono'` first (S6 precedent, no bundling).
2. **Contrast — independently recomputed this review** (method: WCAG relative
   luminance; values match the design's and S6's figures): white/`#f54e00` 3.52 and
   ink/`#f54e00` 4.37 (both fail AA normal text — design's ban is correct);
   white/`#d04200` 4.71 ✓ alternative; ink/canvas 14.33 ✓ default primary control;
   body `#5a5852` 6.63 canvas / 7.11 white ✓ small text; muted `#807d72` 3.84/4.12 ✗
   (correctly banned); ink on `#e6e5e0` badge 12.19 ✓ neutral chips safe; DESIGN
   success `#1f8a65` on white 4.30 ✗ small text (needs the delegated darker shade),
   error `#cf2d56` 5.04 white / 4.70 canvas ✓. Orange focus outline as non-text:
   3.28 on canvas, 3.52 on white ✓ (≥3:1), but 2.21 against `#cfcdc4` — never a
   background in this UI; the builder rule "orange outline only where the surrounding
   surface keeps ≥3:1, ink outline otherwise" covers it.
3. **Narrow widths (320/390).** Walked the actual DOM: topbar flex-wraps (brand +
   4 meta chips + 3 controls); tiles use `auto-fill minmax(160px,1fr)`; single column
   applies below 1024 (a 900–1024px stretch currently two-pane becomes one column —
   visual only); `.table-wrap` scrolls and `td` caps at 340px with
   `overflow-wrap:anywhere`; `pre.raw` wraps anywhere; ≥44px targets are plain CSS
   `min-height` on `button`/`.tab`/`.work-item`/`details summary`/inputs. **One real
   trap:** `html, body { overflow-x: hidden }` (`app.css:30-31`) currently hides
   document-level overflow — the design's "never hide document overflow to make
   broken layouts appear to pass" implies dropping it and proving at 320/390 that
   surfaces self-contain; default: remove (see choices).
4. **Exact data.** The text-only pipeline stays untouched: `el()`/`textContent`
   everywhere (`app.js:200-205`), `rawBlock` never parses (`app.js:486-493`),
   `fetchJSON` parses only the envelope (`app.js:221-236`), seq/version/revisions
   render as exact strings (e.g. `app.js:363,694-697`). A CSS restyle does not cross
   any of these; no `app.js` change is anticipated (44px, focus, tracking, breakpoints
   are all CSS — verified above). If a browser check does expose a defect, the
   design's observed-RED-then-GREEN rule governs that fix.
5. **No writes.** "All six persisted table snapshots" grounds to the actual schema —
   `works, commands, evidence, operations, events, metadata` — snapshotted before/
   after reads, interactions and raw HTTP fetches; `verify_install.py` already
   byte-compares tables around serving (S5/S6 pattern). Existing tests are style-
   agnostic: `StaticAssetServingTests` serves the real packaged files without pinning
   content (`tests/test_ui_server.py:395+`); `verify_install` compares installed vs
   packaged bytes, not fixed bytes (`scripts/verify_install.py:368,611`); wheel ships
   `work_runtime/web/*` (`pyproject.toml:28`) — a pure CSS change passes the suite
   untouched.
6. **Browser evidence.** The concrete matrix exists in reality: five `ui-demo` works
   (`wait-1, uncertain-1, transfer-1, succeed-1, cancel-1` per `docs/gui.md`);
   blockers = `wait-1`'s rejected decision `blockers_raw` (Decisions tab); uncertain
   effects = `uncertain-1` + `cancel-1`'s acknowledged-effect banner; raw data =
   Documents tab / `evd.data` / `evt.body`. Driver precedent: S5/S6 CDP artifacts
   (`.agents/notes/2026-10-14-S5-browser-regression.py`, `...S6-website...py`) with
   `Emulation.setDeviceMetricsOverride` for 390/320 and trusted keys via the CDP
   Input domain — the draft plan's "DOM `.click` is not physical delivery" is already
   the established bar. Gates vocabulary grounds too: four demos =
   `demo`/`publish-demo`/`intervention-demo`/`adoption-demo` (`cli.py:43-52`);
   "standalone14" = `python3 -m unittest discover -s examples/rehearsal` (14 tests,
   S6 acceptance).
7. **Release ownership.** Consistent end-to-end (design §Ownership = draft plan
   Tasks 1–3 = AGENTS.md): GUI developer owns `web/` files, `docs/gui.md`, focused
   tests and browser artifacts, never merges/pushes; a separately dispatched
   documentation owner refreshes exactly the four existing images
   (`website/assets/gui-{en,zh}-{desktop,390}.png` — all four verified present) plus
   `docs/website.md`, only after acceptance; integration alone accepts, merges,
   pushes non-force, verifies remote SHA/CI/Pages byte equality and the main preview.
   No retroactive S5 compliance claim (D30); S5 stays accepted against its own spec.

## Delegated builder choices (defaults; pre-delegated by design, listed for traceability)

| # | choice | default |
|---|---|---|
| 1 | Status/error semantic shades | 2–3 measured families, text ≥4.5:1 at small sizes, meaning in text; success darkened below `#1f8a65`'s 4.30 |
| 2 | Chip surfaces | neutral `#e6e5e0`-family badges (12.19 with ink) + measured semantic tints only where they pass |
| 3 | Token names | `--color-*/--space-*/--radius-*` mirroring DESIGN vocabulary |
| 4 | Table overflow | keep `.table-wrap` per-surface scroll + 340px cell cap + `anywhere` wrap |
| 5 | Focus outline | 2px orange where surrounding surface ≥3:1, ink otherwise |
| 6 | Document overflow | remove `html,body{overflow-x:hidden}`; prove no page-level horizontal scroll at 320/390 |
| 7 | Heading mapping | detail title 22px/400, section labels 16px/600, tile values 26px/400; identifiers stay mono |
| 8 | Audit artifact home | `docs/superpowers/acceptances/assets/S7/` per draft plan Task 1 (S5/S6 kept scripts in `.agents/notes/`; either satisfies "audit artifact, not runtime dependency") |

## Watch items (non-blocking, defaults exist)

- The literal screenshot reading (before/after × {1440,390,320} × {en,zh} × 5 works)
  is 60 captures plus tab-coverage shots — scripted and bounded; default is the full
  cross-product, which satisfies every stricter reading. Shrink only by coordinator
  instruction at dispatch.
- The draft plan requires the new audit artifact to fix the known S5 empty-list
  readiness race; that is inherited scope, not new ambiguity.
