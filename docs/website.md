# Developer website

This repository ships a static, bilingual (English/Chinese) introduction and
showcase website under `website/`. It explains the project to
developers: what it is, the six-stage crash-recovery story, real (sample)
GUI screenshots, quick-start commands that reproduce the actual demos, and
contribution paths. It is a separate artifact from the runtime — the site
never connects to a local UI or database, has no backend, and tracks
nothing.

## Preview locally

The site is plain HTML/CSS/JS with no build step or dependencies. To
preview it the way a browser serves it (rather than opening files
directly):

```bash
python3 -m http.server --directory website
```

This serves *only the website*; it is a convenience for previewing, not a
way to run the production runtime.

The public site is served under this repository's Pages subpath
(`/governed-agentic-work-runtime/`), so every page and asset URL is
relative — including from the nested Chinese page
(`zh/index.html` uses `../assets/...`). To rehearse that layout exactly:

```bash
tmp=$(mktemp -d)
mkdir "$tmp/governed-agentic-work-runtime"
cp -R website/* "$tmp/governed-agentic-work-runtime/"
python3 -m http.server --directory "$tmp"
# open http://localhost:8000/governed-agentic-work-runtime/
```

## Site gate

[`scripts/check_site.py`](../scripts/check_site.py) is the structural gate
over `website/`:

```bash
python3 scripts/check_site.py            # checks <checkout>/website
python3 scripts/check_site.py --root website
```

It is standard library only and never fetches anything. It verifies:
required files exist (`index.html`, `zh/index.html`, `assets/styles.css`,
`assets/site.js`); every local `href`/`src`/`srcset` target resolves to a
file inside the site root (percent-decoded, query/fragment stripped); no
local URL starts with `/`; fragment anchors match an `id` in the target
document; navigation links may leave the site only via `https:` or
`mailto:`; asset URLs must be local (no external fonts, scripts, styles or
images); `img` elements carry `alt`; the English and Chinese pages
cross-link each other. Findings print deterministically ordered by
(file, line, kind); the command exits 0 when clean and 1 otherwise. A
missing or unassembled `website/` directory is reported as four
`missing-required` findings — it can never silently pass.

These are structural checks. They do **not** prove browser behavior,
contrast, keyboard access or visual layout — those require actual browser
verification, which stays part of acceptance.

## Showcase screenshot provenance

The four `assets/gui-{en,zh}-{desktop,390}.png` images are actual captures
of the real operations viewer, not mockups. Current set:

- **Rendered source:** the accepted S7 GUI — design-token restyle
  `41bae0e`, carried through merge `c8138fe` — captured at source tree
  `600c7aa` on 2026-10-14 with headless Chrome over CDP (capture artifact:
  [`.agents/notes/2026-10-14-S7-task2-website-capture.py`](../.agents/notes/2026-10-14-S7-task2-website-capture.py),
  72/72 assertions; local pixel verification:
  [`.agents/notes/2026-10-14-S7-task2-png-verify.py`](../.agents/notes/2026-10-14-S7-task2-png-verify.py)).
- **Sample data:** a fresh store seeded by `python3 -m work_runtime
  ui-demo` — the five-work sample (waiting, needs-attention, transferred,
  succeeded, cancelled) built by real runtime commands, never fabricated
  rows. The desktop shots select `cancel-1` so the detail pane shows a
  real record, including the banner that acknowledges the confirmed
  external effect is retained, not reversed.
- **Viewports:** 1280×900 and 390×844 at deviceScaleFactor 1, matching the
  `width`/`height` attributes on the page's `img` elements; language is
  set through the viewer's own toggle (headless Chrome follows the OS
  locale on first load).
- **Transient content:** the sampling-time chip shows the capture
  moment's clock (the live viewer refreshes it) and the store chip shows
  only the demo database's basename (`runtime.sqlite`); no user-specific
  paths, timestamps beyond that chip, or private data appear. At the
  top-of-page framing, the accepted design's denser metric tiles mean the
  1280×900 viewport shows the first three to four of the five works and
  the 390×844 viewport shows the wrapped topbar/controls, tiles, filters
  and the start of the list — the full list is one scroll away in the
  real viewer.

[DESIGN.md](../DESIGN.md) governs the GUI's visual contract from S7
onward, and these screenshots are the first set captured under it. The
S5-era GUI (and the screenshot set S6 shipped with) predates that
specification; nothing on this site claims retroactive S5/DESIGN
compliance for it.

## Publishing

The website is published by [`.github/workflows/pages.yml`](../.github/workflows/pages.yml),
which follows the official GitHub Pages custom-workflow shape: a `build`
job (checkout, configure Pages, run the site gate, upload `website/` as
the Pages artifact) and a `deploy` job (`github-pages` environment,
`pages: write` + `id-token: write` + `contents: read`, deploy). It runs on
pushes to `main` that touch `website/`, the checker or the workflow
itself, and manually via `workflow_dispatch`. Action releases are pinned
and were verified against primary sources on 2026-10-14:
`actions/checkout@v6`, `actions/configure-pages@v6`,
`actions/upload-pages-artifact@v5`, `actions/deploy-pages@v5`.

The planned public URL is
`https://wayj.github.io/governed-agentic-work-runtime/` — **not published
yet**. First publication requires a one-time repository-admin action
(Settings → Pages → Source "GitHub Actions"); it is owned by the
integration step after independent acceptance, together with the actual
deployment and live HTTPS verification of the English page, the Chinese
page and at least one asset. Until those checks pass, this URL is a target,
not a claim.

## Packaging boundary

The website is documentation, not package content.
[`pyproject.toml`](../pyproject.toml) builds the wheel from
`include = ["work_runtime*"]`, so `website/` is excluded from the runtime
package and no `pyproject.toml` change is needed. `scripts/verify_install.py`
and the installed UI are unaffected.
