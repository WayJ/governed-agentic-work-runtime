# S7 Task2 website image refresh — owner report (2026-10-14)

Worker: S7 dependent screenshot owner (dispatch task_5f4df68c187f, Orca
Claude Code). Scope owned: the four website showcase PNGs and
`docs/website.md`, plus this report, the scoped plan, the two audit
artifacts and fresh evidence under unique `s7img-*` names. No product
CSS/JS/API/backend change, no page copy/stylesheet/checker/workflow/ledger
edit, no merge/push, no extra workers.

## Source verification

- Checkout `s7-website-images` at **`600c7aa49bcf73307afcfdcc240660a8e392fcd6`**
  (clean tree before work), the integration-review tip carrying the
  independently accepted S7 GUI restyle `41bae0e` via merge `c8138fe`.
- Rendered source of the screenshots is therefore exactly the accepted
  GUI — verified again in-capture (topbar white card + `#e6e5e0` hairline,
  refresh ink `rgb(38,37,30)`/canvas, no shadows, ≥44px controls).

## What was produced

| file | dims | sha256 (new) |
|---|---|---|
| `website/assets/gui-en-desktop.png` | 1280×900 | `7389112447887df3a1b2698db18dffce90a5573bf0b23821eea2e5749d48c7ca` |
| `website/assets/gui-zh-desktop.png` | 1280×900 | `96566cbf254ec7511055912cfeeabf93c76b7814030d530fa1e7e5a753a812da` |
| `website/assets/gui-en-390.png` | 390×844 | `f6bd8becc9aae6bdd39903b8d8c6711181416686fcccda6f41efe7173e84bb26` |
| `website/assets/gui-zh-390.png` | 390×844 | `ee7360c65c349265c1c13f7d5b193e3352f60677133d8e4e8461060ce6a63350` |

Paths, filenames, dimensions and the pages' `width`/`height` attributes
are unchanged (byte replacement only). Replaced (old → new):
`21f57a4e…/1add25af…/24e47cb1…/3d42861b…` → table above.

## Capture procedure (actual commands, actual results)

```
python3 .agents/notes/2026-10-14-S7-task2-website-capture.py \
    --out /tmp/s7img-captures
→ website image capture: 72 assertions, 0 failed   (exit 0)
```

Real headless Chrome over CDP against `python3 -m work_runtime ui-demo
--directory /tmp/s7img-gui-store` (fresh seeded five-work store, real
commands only). Language set through the viewer's own toggle
(`ensure_lang`; first load follows the OS locale). Desktop shots select
`cancel-1` (Overview tab: real record with the banner "the acknowledged
external effect is retained, not reversed: <op> → OA-<id>", verified in
both languages); 390 shots are top-of-page with no selection. In-browser
assertions per shot: five works with exact seeded statuses
(wait-1/waiting, uncertain-1/needs_attention, transfer-1/active,
succeed-1/closed, cancel-1/closed), topbar/controls in frame at scrollY 0
with token colors, ≥44px targets, no shadows, no horizontal overflow,
polling active (paused chip hidden), cancel-1 selected on desktop with
the banner fully in frame, filters fully in frame on 390.

## Authenticity verification (local, stdlib, no CDN basis)

```
python3 .agents/notes/2026-10-14-S7-task2-png-verify.py \
    --new /tmp/s7img-captures --old website/assets
→ png verify: all dimension/token checks passed   (exit 0)
```

Full-pixel stdlib decode of every PNG: new captures contain the accepted
tokens in bulk (canvas `#f7f7f4` 78k–307k px, white cards 203k–634k, ink
`#26251e` 4.6k–13k, orange brand mark `#f54e00` 65 px each) and **zero**
pixels of the pre-S7 theme (`#f5f7fa`, `#2456c6`, `#eef1f6`, `#1c2433`).
The old images are the exact inverse (old bg 706k–718k px, old blue mark
72 px, zero new-canvas px) at identical dimensions — a genuine
before/after record. Vision-model reads of freshly-uploaded unique
basenames (`s7imgv2-*`) confirmed language, framing, banner and wrapped
controls per file — supplementary only, per project rule.

## Website verification under the Pages subpath

```
tmp=/tmp/s7img-subpath; mkdir $tmp/governed-agentic-work-runtime
cp -R website/* $tmp/governed-agentic-work-runtime/
python3 -m http.server --directory $tmp 8791
python3 .agents/notes/2026-10-14-S6-website-browser-regression.py \
    --en-url http://127.0.0.1:8791/governed-agentic-work-runtime/ \
    --zh-url http://127.0.0.1:8791/governed-agentic-work-runtime/zh/ \
    --sections static,visual,nojs --shot-dir /tmp/s7img-site-shots
→ website regression: 74 checks, 0 failed   (exit 0)
```

74/74 including, per language at 1280/390/320: all four images actually
loaded after scroll (lazy), canvas/CTA/radius/no-shadow tokens, contrast,
no horizontal overflow, noJS completeness, https-only externals. Gates:
`python3 scripts/check_site.py` → 2 pages, 0 findings;
`python3 scripts/check_docs.py` → 71 files, 258 links, 0 broken. Full
core suite/install verification intentionally not rerun (image/docs-only
change; owned by final integration per plan Task3).

## Before/after page comparison and change isolation

Row-level pixel diff of full-page screenshots (committed S6 evidence vs
fresh captures of this branch):

- Every difference below the fold maps to the showcase figures (e.g.
  en-1280 changed rows 3431..5097 inside grid 3429..5127; figure-only
  clusters 2×~800 rows at 1280, 2×237+2×729 rows at 390).
- Small pre-grid band differences (85–359 rows) also appear when
  re-capturing the **unchanged old-image site** in a control serve
  (port 8792, images from git HEAD): they are pre-existing capture
  nondeterminism in the recovery-stages area, not caused by this change.
  Cleanest proof: on zh-390 two fresh captures rendered that area
  identically, and old-image vs new-image pages differ **only** at rows
  4599..6682 — exactly inside the showcase grid (4596..6712).

## Framing decisions and disclosed transience

- Top-of-page framing at both widths: the brief's first-listed framing
  requirement (new topbar/controls) owns the frame. The accepted design's
  denser metric tiles make the page taller than one viewport, so at
  1280×900 the fold shows the first 3–4 of the five works (needs_attention
  chip in frame; en: 3 full + 1 partial, zh: 4 full + 1 partial) and at
  390×844 the wrapped topbar/controls, tiles, counts, filters and the
  start of the list (zh: cancel-1 complete; en: its id/chip row). The
  full list is one scroll away in the real viewer; alt/caption text stays
  truthful. This fold is asserted, not assumed (capture checks), and is a
  real consequence of the accepted restyle — the pre-S7 GUI happened to
  fit because its tiles were more compact.
- Transient content: the sampling-time chip always shows the capture
  moment's clock (recorded per shot in `s7img-capture.json`:
  22:13:38/22:13:39/22:13:40/22:13:41) — structurally unavoidable without
  product edits this task must not make, and disclosed here and in
  `docs/website.md`. The store chip renders only the demo DB basename
  (`runtime.sqlite`; the API serves `os.path.basename`), so no directory
  or user path exists in any shot. No user data, no XSS-fixture views, no
  invented content; need-attention/uncertain/acknowledged-effect
  semantics render from the real seeded store.

## docs/website.md

Added a "Showcase screenshot provenance" section (rendered source commits,
seed command, viewports, language mechanism, transient-content
disclosure, fold note) and the prospective scope statement: DESIGN.md
governs the GUI from S7 onward and these are the first captures under it;
the S5-era GUI/S6 screenshot set predates the spec and no retroactive
S5/DESIGN compliance is claimed.

## Risks / limitations

- One rendering engine (Chromium headless), consistent with all prior
  site/GUI evidence on this machine.
- The sampled-at clock time in the images will not match a later viewer
  run (by design of the real UI; disclosed).
- Pre-existing capture nondeterminism in the pages' stage-list area
  (above) means byte-identical page re-captures are not generally
  achievable; computed checks and the isolated grid diff carry the
  layout-unchanged claim.
- F1 (audit-tool contrast-skip) belongs to the parallel audit owner; not
  touched here.

## Artifacts

Plan `docs/superpowers/plans/2026-10-14-s7-task2-website-images.md`;
capture/verify artifacts `.agents/notes/2026-10-14-S7-task2-website-capture.py`,
`.agents/notes/2026-10-14-S7-task2-png-verify.py`; evidence
`.agents/notes/assets/s7img-*` (capture JSON+log, pixel-verify JSON+log,
six page screenshots + one control capture, regression log, page-diff
log). Pending for Task3 integration alone: merge, push, CI, Pages
deployment and public byte-equality proof.
