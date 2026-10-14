# S6 website design — bounded builder review, 2026-10-14

Read-only check of the S6 draft spec/roadmap for implementability before
ratification. Base `7d3645d` (clean, branch `WayJ/s6-developer-website-plan`);
only this note is committed — no epic/spec/AGENTS/DESIGN/site edits, no code,
no merge/push. Examined: spec `2026-10-14-s6-developer-website-design.md`,
roadmap `2026-10-14-developer-website.md`, main-checkout user-saved `DESIGN.md`
and `AGENTS.md` UI agreement (planning base lacks that section — master syncs
it to the future carrier), README + README.zh-CN, S5 acceptance record and
screenshots, `.github/workflows/ci.yml`, `scripts/check_docs.py`,
`pyproject.toml`, CLI help; official GitHub Pages custom-workflow doc (fetched
read-only). No external message or deployment.

## Verdict

Implementable as planned: stdlib-free static site, bounded stdlib checker,
official Pages custom workflow. **No blocking gaps found.** Computed contrast
forces 4 concrete DESIGN adaptations (below); 8 defaults/nonblocking choices
need master ratification; Pages enabling needs repo-admin action at
integration time (Q2 stays open).

## Findings by assessment axis

1. **Bilingual static — feasible.** `README.zh-CN.md` and the bilingual GUI
   prove copy exists; structure is two files (`index.html`, `zh/index.html`)
   with relative cross-links (en→`zh/index.html`, zh→`../index.html`). JS
   language suggestion stays optional; default entry is always the English
   `index.html`, never hidden.
2. **Subpath base path — pinned rule.** No local URL may start with `/`; all
   `href`/`src` relative, anchors fragment-only, external links absolute
   `https:`; zh page shares `../assets/`. This is exactly what
   `/governed-agentic-work-runtime/` serving requires; the checker enforces
   it structurally and integration verifies on the live URL.
3. **noJS — feasible.** All sections (incl. the six recovery stages, which
   match the actual `demo` output verbatim) render as static source-ordered
   HTML; `site.js` only enhances (progression focus, copy buttons). Content
   is never hidden behind JS.
4. **Clipboard failure — feasible.** Code blocks remain selectable text;
   copy button guards `navigator.clipboard`, announces success/failure via
   `aria-live`, fails soft when denied/insecure/noJS. Browser check with
   denied permission is part of the regression artifact.
5. **Browser verification — feasible, S5 pattern reuses directly.** Orca
   embedded browser for interaction + headless Chrome CDP for narrow 390/320
   (`Emulation.setDeviceMetricsOverride`), noJS via script-execution-disabled,
   clipboard denial via permission override; computed styles + screenshots as
   evidence, never keyword-only scans (spec rule upheld).
6. **License fonts — clean default: bundle nothing.** System sans stack with
   Chinese fallbacks + locally-referenced `'JetBrains Mono', monospace`; no
   CDN, no font files, so no redistribution/license obligations. (If bundling
   is ever wanted: JetBrains Mono is OFL-1.1 and would ship a license file —
   deferred, unnecessary for v1.)
7. **DESIGN adaptation — computed WCAG ratios (this review, not the
   reference's labels):** fails AA for normal text: white on `#f54e00` 3.52
   (and ink 4.37 — also short); `muted` on canvas 3.84 / white 4.12;
   `muted-soft` 2.55; white on gold `#c08532` 3.16; success on white 4.30.
   Passes: ink/canvas 14.33, body/canvas 6.63, body/white 7.11, white on
   `#d04200` 4.71, ink on gold 4.86, ink on all five pastels 7.2–8.3, error
   5.04, orange focus ring vs canvas 3.28 (non-text ≥3 ✓). Adaptations:
   primary CTA uses ink bg + canvas text (the reference's own
   `button-download`, 14.33) — orange stays scarce on wordmark/focus/large
   display only; `muted` restricted to large text or darkened to body; gold
   pill would need ink text; success as icon/badge or darkened for text.
8. **Original brand — no conflict.** Text wordmark "Governed Work Runtime";
   DESIGN.md/main-AGENTS explicitly token-reference-only; no Cursor
   names/logos/copy/pricing/testimonials, no invented metrics/stars.
9. **Demo/GUI screenshot truth — verified against reality.** `demo`,
   `ui-demo`, `ui` all present in CLI help; README's six-stage story is the
   demo's real output; S5 screenshots show the real five-work bilingual GUI
   with honest demo data. Two notes: the current GUI is *pre*-DESIGN restyle
   (restyle is a separate later task), so site screenshots must show the
   actual current GUI labeled "sample"; and the public set should be a fresh
   sanitized capture from `ui-demo` — acceptance shot `02` (intentional
   `<script>` payloads) must not be reused publicly.

## Bounded checker pin (delivery owner, TDD)

- `scripts/check_site.py`: stdlib only (`argparse`, `html.parser`, `pathlib`,
  `urllib.parse`, `re`), Python ≥3.9, offline file-based (never fetches),
  exit 0/1; modeled on `scripts/check_docs.py`.
- API: `Finding = NamedTuple(file, line, kind, detail)`;
  `scan(root: Path) -> List[Finding]`; `main(argv) -> int`;
  CLI `python3 scripts/check_site.py [--root website]`.
- Structural checks only (never claimed as behavioral evidence): required
  files exist (`index.html`, `zh/index.html`, `assets/styles.css`); every
  local `href`/`src`/`srcset` target resolves under root; no local URL with a
  leading `/`; fragment anchors resolve to an `id` in the target document;
  external refs `https:`/`mailto:` only; `<img>` elements carry `alt`;
  language cross-links exist in both pages.
- `tests/test_check_site.py` (unittest, tmp fixture tree, ~8 cases):
  clean-fixture pass; broken internal link; leading-slash local URL; missing
  asset; dangling anchor; missing zh page; `http://` resource; `img` without
  alt. RED observed before implementation, GREEN after.
- Wiring: add `python scripts/check_site.py` to `ci.yml`; `website/` stays
  out of the wheel (`include = ["work_runtime*"]` verified) so packaging and
  `verify_install` are untouched. `scripts/` is compileall-gated — checker
  must stay 3.9-clean.

## Pages deployment pin (integration-owned; nothing executed now)

- `.github/workflows/pages.yml` per the official custom-workflows doc:
  `permissions: pages: write, id-token: write, contents: read`; deploy job
  `environment: github-pages` and `needs:` the build job; steps checkout →
  `actions/configure-pages@v5` → `actions/upload-pages-artifact`
  (`path: website`) → `actions/deploy-pages`; trigger push-to-main +
  `workflow_dispatch`; pin exact action versions at implementation time.
- One-time enable (repo admin): Settings → Pages → Source "GitHub Actions",
  or API `POST /repos/WayJ/governed-agentic-work-runtime/pages` with
  `build_type: "workflow"`.
- Permission/verification evidence to record: `gh api repos/WayJ/
  governed-agentic-work-runtime/pages` (200 + `build_type=workflow`; 403/404
  = honest blocker → keep workflow + local preview, report the exact external
  action, never switch paid hosts or claim deployment); successful run URL;
  live HTTPS checks of `/`, `/zh/` and one asset byte-equal to local;
  optional repo homepage PATCH. Target URL stays labeled "planned" until
  those pass. No custom domain (Q1 closed default).
- Local rehearsal: `python3 -m http.server --directory website` for the site;
  subpath rehearsal by serving a temp parent containing a copy of `website/`
  named `governed-agentic-work-runtime/`.

## Defaults and nonblocking choices (master ratifies)

| # | choice | default | alternative |
|---|---|---|---|
| 1 | Primary CTA style | ink bg + canvas text (14.33) | `#d04200` bg + white (4.71) |
| 2 | `muted` small text | darken to body color | only ≥18.66px-bold/24px |
| 3 | Timeline pastels | off (no real stage mapping today) | on only with documented mapping |
| 4 | `site.js` scope | minimal: copy buttons + enhancement | none in v1 |
| 5 | Screenshot set | fresh sanitized EN/ZH desktop + 390 from `ui-demo` | reuse acceptance shots (never `02`) |
| 6 | Image format | png only | png+webp pairs (checker verifies both) |
| 7 | `check_site.py` in CI | add step to `ci.yml` | local gate only |
| 8 | AGENTS sync | master adds gates row + `doc_sync_map` `scripts/check_site.py → docs/website.md` and syncs saved DESIGN/AGENTS UI section to the carrier | as drafted (no gate row) |

## Risks / open

- `has_pages=false`/`homepage=null` observed at planning via gh API; re-verify
  at integration; Q2 (account permission) remains open until then.
- Checker is structural by design; every behavioral/visual claim still needs
  the browser regression artifact + independent integration review.
- S6 starts only after S5 remote+CI completes and master ratifies this review
  (planning handover); GUI restyle to DESIGN stays a separate later task.
