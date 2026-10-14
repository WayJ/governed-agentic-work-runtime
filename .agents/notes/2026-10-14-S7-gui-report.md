# S7 Task1 — GUI design tokens, accessible responsive CSS — worker report

Worker: s7-gui-interface checkout (`WayJ/s7-gui-interface`), dispatch
`task_e21614f18f74` / `ctx_a087ed20fd35`, base commit `2f76f7f`. Scope held to
`work_runtime/web/app.css`, `docs/gui.md`, the scoped plan, audit artifact and
evidence under `docs/superpowers/acceptances/assets/S7/`. **No changes to
`index.html`, `app.js`, backend, API, policy, schema, CLI, website, gates,
roadmap or ledger; no merge, no push, no extra workers.** Superpowers
writing-plans + executing-plans followed
(plan: `docs/superpowers/plans/2026-10-14-s7-task1-gui-tokens.md`, ledger in
`.superpowers/sdd/2026-10-14-s7-task1-gui-tokens/progress.md`).

## What changed

`work_runtime/web/app.css` (only product file): full token-based rewrite.
Central `:root` custom properties (`--color-*`, `--radius-control|card|chip`,
`--space-xxs..lg` 4px scale, `--font-sans|mono`, `--tracking-display-md|sm`,
`--content-max: 1200px`); warm cream canvas `#f7f7f4`, ink `#26251e`, body
`#5a5852`, white cards with 1px `#e6e5e0` hairlines, `#cfcdc4` control
outlines, no `box-shadow` anywhere; orange `#f54e00` scarce and non-text only
(brand mark + 2px `:focus-visible` ring, offset 2px); primary refresh control
ink/canvas; selected tab ink/canvas; selected work item ink border +
`#fafaf7`; display 26px/22px at weight 400 with Latin-only negative tracking
(`:lang(zh)` → 0); labels 16px/600; body 15px; small/code/table 13px; mono =
locally referenced `'JetBrains Mono'` first, system mono fallback, no
bundling; chips pill with neutral `#eceae4`+ink base (unknown runtime chip
classes can never render unstyled) and measured semantic tints as enhancement;
`min-height: 44px` on buttons/tabs/work-items/inputs/raw disclosures;
`.layout` capped 1200px, single column `<1024px`, `<640px` stacking with
45vh list pane; removed `html, body { max-width: 100%; overflow-x: hidden }`
(long data now wraps/scrolls inside its own surfaces only).

`docs/gui.md`: new "Visual contract (S7)" section documenting tokens,
measured deviations and the no-pastels/no-orange-text rationale.

## Browser evidence (actual Chrome over CDP, trusted input)

Artifact: `docs/superpowers/acceptances/assets/S7/s7_gui_audit.py` (stdlib
only; audit artifact, not a runtime dependency). It seeds a **real** ui-demo
store, serves empty/huge+hostile/gone **labeled fixture copies** via the real
`ui` server, drives real headless Chrome (CDP `Input.dispatchKeyEvent` /
`dispatchMouseEvent` / `Input.insertText` / `Emulation.setDeviceMetricsOverride`
/ `Network.emulateNetworkConditions`), and fixes the known S5 empty-readiness
race (empty state asserted only after `#list-status` settles to non-loading
text). Keyboard evidence never uses DOM `.click()`; the S5 race and first-load
and tab-arrow regressions are re-asserted at 1440/390/320.

- **Before phase** (pristine `2f76f7f` CSS; new CSS stashed during capture):
  `python3 docs/superpowers/acceptances/assets/S7/s7_gui_audit.py --phase
  before --out docs/superpowers/acceptances/assets/S7` → **34 checks, 0
  failed** + baseline visual measurements recorded (blue theme, 35–37px
  targets, tokens empty, `overflow-x: hidden`).
- **After phase** (new CSS): same command with `--phase after` → **199
  checks, 0 failed** — behavior/integrity (first load, empty/loading/gone/
  disconnected, arrows/Enter/tab-arrows//-search/filter, language, refresh,
  pause/resume, XSS inert, huge-integer exactness, 30-shot matrix ×2, three
  six-table no-writes snapshot equalities) **plus** all ratified visual
  assertions (tokens, radii, no shadows, 44px targets, single-column <1024,
  1200px cap, `overflow-x: visible`, orange 2px focus ring, zh zero tracking)
  and measured contrast.
- Matrix: **60 PNGs total** — `{1440,390,320} × {en,zh} × {wait-1,
  uncertain-1, transfer-1, succeed-1, cancel-1}`, 30 before + 30 after, plus
  12+12 view captures (blockers decision, uncertain operations, cancel
  acknowledgment, raw documents, neutral event chips, focus ring, XSS
  overview/events, empty, loading, gone, disconnected) and
  `before-results.json` / `after-results.json`.
- Pixel-level sanity on the committed PNGs (BMP conversion + sampling):
  after page canvas is exactly `#f7f7f4`, before `#f5f7fa` — the captures are
  genuinely distinct themes. (Note: an earlier image-analysis read of an
  after PNG returned the before theme — a stale cached CDN copy under a
  shared upload basename; local hashes and pixel sampling refute it.)

**RED→GREEN (the one defect the audit caught):** after-run 1 failed
`primary control ink/canvas` (observed white bg + ink text) — the ratified
`#refresh` ink/canvas rule was missing from the CSS. Added it; after-run 2
passes 199/199. This is a visual requirement RED/GREEN, per the spec's rule
that visual changes use visual/computed proof, not source tests. No
`index.html`/`app.js` behavior fix was needed anywhere: every audit failure
traced to audit-harness mechanics (documented below), so the anticipated
RED/GREEN path for JS stayed unused.

**Measured contrast (Chrome computed styles on actual surfaces, WCAG):**
ink/canvas 14.33 · ink/`#eceae4` 12.78 · body/white 7.11 · body/`#eceae4`
5.91 · success `#146c4e` on `#e8f2ec` 5.58 (DESIGN `#1f8a65` is 4.30 on
white — darkened) · warn `#8a5400` on `#faf0df` 5.55 · error `#b32449` on
`#f9e8ec` 5.45 (DESIGN `#cf2d56` drops to 4.27 on tints) · selected tab and
primary control 14.33–15.38 · focus ring orange on white 3.52 (non-text ≥3).
All text pairs ≥4.5. Ratios were computed from computed fg/bg pairs in the
audit script (validated against the builder review's figures to 2 decimals).

**No writes:** the real demo store plus the empty and XSS fixture stores had
all six tables (`works, commands, evidence, operations, events, metadata`)
digest-identical after every read, interaction, poll cycle and HTTP fetch.
The gone fixture is harness-mutated by design (work deleted while selected to
reach UNKNOWN_WORK) and is excluded from that proof, as documented in the
script.

## Regression, gates, demos (all actual runs)

- `python3 -m unittest discover -s tests` → **622 tests, OK (skipped=1)**
  (baseline before work: identical 622/1).
- Gates: `python3 scripts/check_docs.py` → 70 markdown files, 248 local
  links, 0 broken (includes the new scoped plan) · `python3 -m compileall -q
  work_runtime tests scripts` → OK · `python3 scripts/check_site.py` → 2
  pages, 0 findings · `python3 -m work_runtime demo` → exit 0 (crash and
  recovery) · `publish-demo`, `intervention-demo`, `adoption-demo` → exit 0.
- `python3 -m unittest discover -s examples/rehearsal` → **14 tests OK**
  (standalone14).
- `python3 scripts/verify_install.py` → **PASS**: fresh venv install, no
  third-party runtime dependencies, packaged web assets ship and are served
  byte-equal to the packaged files (module + console entry points), five
  seeded works over real HTTP, store tables unchanged.

## Coordinator interaction

Plan-review feedback applied before implementation (links `../../../`,
30+30=60 matrix wording, before-phase visual checks record-only, contrast
recomputed on actual surfaces — no copied 12.19 for `#eceae4`, which
measures 12.78 with ink). No blocking question; no local approval UI.

## Audit-harness iterations (disclosed, no product involvement)

Six before runs / two after runs total; failures 1–5 were harness mechanics:
repo-path depth, `ORDER BY` range on 2-column tables, headless Chrome
defaulting to the machine's zh locale (now locale-agnostic `ensure_lang`),
CDP Enter needing `text:"\r"` to activate buttons, native `<select>` ignoring
CDP arrow keys on this Chrome build (status filter exercised via the native
type-to-jump letter key — still a trusted key event), events-tab async load
race (wait for rendered card), missing tab focus call at 1440, and Chrome
computing `letter-spacing: 0` as `"normal"`. Final before evidence (34/34)
predates three script refinements that only affect after-phase assertions
(`pre.raw` assertion moved to the documents step; zh-tracking accepts
computed `normal` and ensures a detail is open); before-phase check logic is
unchanged by them.

## Remaining risks / limitations

- Screenshot pairs are evidence of layout/contrast at the tested widths on
  this Chrome build; other engines were not tested (offline stdlib toolchain
  drives Chromium only).
- The status-filter keyboard path relies on type-to-jump because this Chrome
  ignores CDP arrow keys on native selects; a physical-keyboard user pressing
  arrows is expected to work (standard Chrome behavior) but was not
  machine-provable here.
- `--lang=en-US` does not override `navigator.language` on this machine; the
  audit is locale-agnostic instead (documented in-script).
- Independent integration still owns: combined-branch browser re-checks,
  full acceptance, main merge/push, remote/CI/Pages proofs, and the
  separately-dispatched website image refresh (not touched here).
