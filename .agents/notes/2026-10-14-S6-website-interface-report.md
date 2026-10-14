# S6 website interface — owner report (2026-10-14)

Worker: S6 website page owner (dispatch task_0a416f2410cf, Orca Claude Code).
Scope owned: `website/index.html`, `website/zh/index.html`,
`website/assets/{styles.css,site.js,gui-*.png}`,
`docs/superpowers/plans/2026-10-14-s6-website-interface.md`, this report, the
browser-regression artifact and evidence screenshots. No engine/GUI product
changes; no edits to AGENTS, scripts, workflows, README, other docs or core
tests; no merges/pushes.

## Commits (scoped, this branch only)

| commit | content |
|---|---|
| fd221c0 | static bilingual pages + DESIGN-token CSS + scoped plan (noJS-complete, no script yet) |
| c0814c1 | progressive `site.js` (copy + recovery stepping) + regression artifact; behavior RED→GREEN |
| 8aa7e0f | fresh sanitized `ui-demo` GUI shots (EN/ZH × desktop/390) + showcase; crosslink-check fix |
| 6978a0b | evidence screenshots + two computed-check-driven CSS fixes (zh hero base, `.badge`) |
| (this) | report only |

Content tip referenced below: **6978a0b**. Core suite baseline before any
code: `Ran 603 tests … OK (skipped=1)` (run once, not repeated).

## Behavior evidence — observed RED then GREEN in a real browser

Artifact: `.agents/notes/2026-10-14-S6-website-browser-regression.py`
(stdlib-only CDP client; real headless Chrome 155; trusted
`Input.dispatchMouseEvent`/`dispatchKeyEvent`; `Emulation.setDeviceMetricsOverride`
viewports; labeled **actual browser** evidence, never fake DOM).

RED (pages at fd221c0, no JS — `--sections behavior`):

```text
FAIL EN copy buttons injected for every code block — blocks=2 buttons=0
FAIL EN copy click lands — no .copy-btn to click
FAIL EN recovery Prev/Next controls injected — buttons=0
FAIL ZH copy buttons injected for every code block — blocks=2 buttons=0
FAIL ZH copy click lands — no .copy-btn to click
FAIL ZH recovery Prev/Next controls injected — buttons=0
website regression: 14 checks, 6 failed
```

(Static-HTML behavior already passed pre-JS: six stages present, first Tab →
skip link, orange focus ring, skip-link Enter → `#main`.)

GREEN (after c0814c1, same command): `website regression: 26 checks, 0 failed`
— includes, per language: copy button per code block; aria-live success
(`Copied: GUI demo command.` / `已复制：GUI 演示命令.`); **clipboard read-back
byte-equal to the visible block text** (granted permission); trusted Next
click 1→2; Enter key on Next → 3; Prev → 2; all six stages visible throughout;
skip-link Tab/Enter path.

Clipboard failure path — REAL insecure origin (site copy served at
`http://192.168.100.3:8733/`, `navigator.clipboard` undefined there):

```text
PASS EN insecure insecure origin announces copy failure — navigator.clipboard=False live='Copy failed — select the command text and copy manually.'
PASS EN insecure command text remains selectable after failure — 'python3 -m work_runtime ui-demo'
```

Full behavior with insecure checks: 28/28.

## Visual / noJS / subpath evidence (computed styles + screenshots)

`--sections visual,nojs --shot-dir .agents/notes/assets` → **60/60 PASS**,
both languages at 1280/390/320:

- canvas `rgb(247,247,244)` on body; primary CTA ink/canvas pair recomputed
  **14.33**; body 6.63; footer links 6.63; stage titles 15.38; badge 5.64 —
  all ≥4.5; control radius 8px; card radius 12px + `box-shadow: none`;
  hero computed sizes EN 72px→32px, ZH 52px→30px (desktop→narrow);
  `scrollWidth-clientWidth ≤ 0` at every width (no horizontal overflow);
  all images load (after real scroll; they are `loading="lazy"`).
- noJS (`Emulation.setScriptExecutionDisabled`): zero injected controls, all
  six stages and all top sections visible, stylesheet still applied — EN+ZH.

Subpath rehearsal (temp parent copy served as
`/governed-agentic-work-runtime/`): `static,visual,nojs` **74/74** and
`behavior` **26/26** — including nested `…/zh/index.html` with `../assets/`.

Evidence screenshots (full page, real Chrome):
`.agents/notes/assets/s6-{en,zh}-{1280,390,320}.png`.

Two product bugs the computed checks caught and I fixed (6978a0b): the ZH base
hero size rule was missing (72px leaked to zh desktop) and `.badge` had no CSS
(plain text). Both re-verified GREEN after the fix.

## GUI showcase truth

`python3 -m work_runtime ui-demo --port 8732 --directory /tmp/s6-gui-store`
(own checkout, unchanged Python; root preview :59619 untouched). Capture:
headless Chrome via CDP, waiting for the five-work list, using the GUI's own
language toggle (first load renders zh — headless Chrome 155 hardwires
`navigator.language` to the OS locale; `--lang=en-US`, locale override and a
`navigator.language` property injection all failed, so the toggle is the
honest path). All four PNGs inspected by vision analysis: correct language
per file, exactly the seeded sample (`wait-1, uncertain-1, transfer-1,
succeed-1, cancel-1`), **no XSS-fixture views, no private/user data**, narrow
shots usable. Files: `website/assets/gui-{en,zh}-{desktop,390}.png`.

## Orca embedded browser (guide-conformant use)

`goto`/`snapshot`/`eval`/`focus` with `--page` affinity: a11y snapshot shows
nav/sections/stages/buttons; eval confirms 2 copy buttons, secure context on
127.0.0.1; a direct clipboard probe rejected with `NotAllowedError`;
`focus` moved `document.activeElement` to the labeled copy button. Its
`click`/`keypress` did **not** dispatch to this client-hosted page (click
marker listener stayed 0 while commands returned ok), so interactive
trusted-event evidence stands on the CDP real-Chrome runs above — no fake
Orca interaction is claimed.

## DESIGN.md tokens and documented adaptations (D29-ratified)

Tokens implemented centrally in `:root` (colors incl. hairlines/semantic,
4px spacing scale, 8px/12px radii, type ramp, system-sans + CJK fallbacks,
`'JetBrains Mono', monospace` by local reference only). Adaptations, all
ratified or recorded per AGENTS:

| adaptation | decision |
|---|---|
| Primary CTA | ink bg + canvas text (14.33) instead of orange (3.52 fails AA) |
| Small muted text | body color everywhere; `--muted` only for large/decorative counters |
| Timeline pastels | absent — no real stage mapping on this site |
| ZH display | 52/40/30px ramp, tracking 0 (CJK legibility; EN keeps −0.03em) |
| Nav at narrow | links wrap (no JS hamburger) — noJS/keyboard-safe |
| Fonts | no bundles/CDN; system stack + named JetBrains Mono fallback |
| Architecture | HTML numbered flow (text-native, screen-reader legible) instead of svg |

Status/pre-alpha disclosure visible in hero + footer on both languages; the
six-stage story is labeled an illustrated sample of the demo's real output;
the showcase is labeled sample data and states the site never connects to a
local UI/database.

## Gates

- `python3 scripts/check_docs.py` → `checked 62 markdown files, 215 local links, 0 broken`.
- `python3 -m compileall -q work_runtime tests scripts` → clean.
- `python3 -m work_runtime demo` → six stages, `SUCCEEDED; external applications created: 1`.
- Audit: external refs https-only (GitHub navigation), no `http:` assets, no
  fetch/analytics/tracking, no fabricated stars/users/testimonials; zh page
  links README.zh-CN.md.

## Pending — not done by this owner, honestly

- **`scripts/check_site.py` site checker does not exist yet** (delivery
  owner, other session). I could not run it; no checker pass is claimed.
- Pages workflow/deployment/public URL: integration-owned; nothing enabled or claimed.
- Independent integration acceptance of all six S6 scenarios: pending.
- GUI restyle to DESIGN.md is a separate later task (screenshots show the
  current pre-restyle GUI, labeled sample).
