# S6 delivery owner report — 2026-10-14

Worker: delivery owner (this session, Orca `claude`). Branch
`WayJ/s6-website-delivery`, immutable tip at report time: `58abd66`
(base `ada7ecc`, clean tree before work; only this report follows).

## Commits (scoped, in order)

| commit | content |
|---|---|
| `8141b10` | `scripts/check_site.py` + `tests/test_check_site.py` + AGENTS.md site gate & `scripts/check_site.py → docs/website.md` doc-sync row (same commit, per D29) |
| `46a86ac` | `ci.yml` site-gate step + new `.github/workflows/pages.yml` (pinned official Pages workflow) |
| `3c84a2b` | `docs/website.md` + README.md / README.zh-CN.md link-row entries |
| `ff020ff` | review fix: only stylesheet/icon `link` rels are local-only assets |
| `58abd66` | scoped implementation plan (`docs/superpowers/plans/2026-10-14-s6-delivery-checker.md`) |

Ownership respected: no `website/` asset edits (directory does not exist on
this carrier), no engine/GUI/pyproject changes, no merges/pushes, no Pages
enable/deploy, no nested workers.

## TDD evidence (behavior changes)

- RED: `python3 -m unittest tests.test_check_site` failed at module load —
  `FileNotFoundError: scripts/check_site.py` (feature absent), before any
  implementation existed.
- GREEN: after the minimal stdlib implementation, 18/18 passed; full suite
  603 → 621, OK (skipped=1).
- Review fix (TDD): `test_non_asset_link_rels_ignored` observed RED
  (`rel=canonical` https link falsely reported `external-asset`), then GREEN
  after restricting `link` asset checking to rel tokens
  {stylesheet, icon}; suite 603 → **622, OK (skipped=1)** (final count
  includes 19 checker tests).

## Gate evidence (final runs at tip)

- contracts: `python3 scripts/check_docs.py` → 63 markdown files, 222 local
  links, 0 broken.
- tests: `python3 -m unittest discover -s tests` → **Ran 622 tests, OK
  (skipped=1)** (baseline before work: 603 OK skipped=1).
- demo: `python3 -m work_runtime demo` → stage 6 SUCCEEDED, external
  applications created: 1 (unchanged recovery behavior).
- syntax: `python3 -m compileall -q work_runtime tests scripts` → clean
  (local interpreter is Python 3.9, matching the floor).
- **site (PENDING, honest fail — not a fake pass):** `python3
  scripts/check_site.py` on this carrier exits **1** with exactly:

  ```text
  missing-required: assets/site.js:0 required file missing: assets/site.js
  missing-required: assets/styles.css:0 required file missing: assets/styles.css
  missing-required: index.html:0 required file missing: index.html
  missing-required: zh/index.html:0 required file missing: zh/index.html
  checked 0 pages, 4 findings
  ```

  The assembled website belongs to the page owner's separate tip and is not
  present in this checkout. The checker is proven by the 19 fixture tests
  only; the first real-site gate run happens when integration assembles both
  owners' tips. Likewise `ci.yml`'s new site step (and `pages.yml`'s) can only
  pass after assembly — expected and by design; development workers never
  push, so no CI run occurs on the unassembled carrier.

## Checker API (exactly as pinned by D29)

`Finding = NamedTuple(file, line, kind, detail)`;
`scan(root: Path) -> List[Finding]`; `main(argv=None) -> int`;
`python3 scripts/check_site.py [--root website]` (default
`<checkout>/website`); exit 0 clean / 1 findings; deterministic
(file, line, kind) order. Kinds: `missing-required`, `missing-lang-link`,
`leading-slash`, `out-of-root`, `missing-target`, `dangling-fragment`,
`external-asset`, `disallowed-scheme`, `missing-alt`. Checks: required files
(index.html, zh/index.html, assets/styles.css, assets/site.js); local
href/src/srcset existence with percent-decoding, query/fragment stripping and
lexical root containment; no leading-`/` local URLs; fragments resolve to ids
in the target document; navigation external only via https/mailto; assets
local-only (stylesheet/icon `link`, `script`, `img`, `source`, srcset
candidates individually); `img` alt presence; en↔zh crosslinks. Offline,
never fetches; structural only — no behavioral/visual claims.

## CI and Pages wiring

- `ci.yml`: single added step `- run: python scripts/check_site.py` after
  `check_docs.py`; matrix (3.9/3.12/3.13), install, demos and installed-UI
  verification untouched.
- `pages.yml`: official custom-workflow shape — `build` (checkout →
  configure-pages → `python3 scripts/check_site.py` gate → upload-pages-artifact
  `path: website`) and `deploy` (`needs: build`, environment `github-pages`
  with `page_url`, permissions `pages: write` / `id-token: write` /
  `contents: read`, deploy-pages); top-level `permissions: contents: read`;
  `concurrency: group "pages", cancel-in-progress: false`; triggers: push to
  `main` with paths `website/**`, `scripts/check_site.py`, the workflow
  itself, plus `workflow_dispatch`. Header documents the one-time
  repository-admin Pages enable (Settings → Pages → Source "GitHub Actions")
  and that `https://wayj.github.io/governed-agentic-work-runtime/` stays a
  **planned, not published** URL until integration verifies live HTTPS
  EN/ZH/asset equality. Both YAMLs parse (ruby YAML; pyyaml unavailable —
  stdlib-only machine).
- Action versions pinned from primary sources verified 2026-10-14:
  `actions/checkout@v6` (v6.0.0 latest release; also the docs example tag),
  `actions/configure-pages@v6` (v6.0.0 latest; docs example shows v5),
  `actions/upload-pages-artifact@v5` (v5.0.0 latest; docs example v4, starter
  v3), `actions/deploy-pages@v5` (v5.0.1 latest; starter v5, docs example
  v4). Sources: docs.github.com "Using custom workflows with GitHub Pages",
  actions/starter-workflows `pages/static.yml`, each action's `/releases`
  page. Ruling recorded: latest stable releases chosen over the docs
  example's lagging tags; integration can bump a tag at publication if
  desired.

## Packaging boundary

`pyproject.toml` builds from `include = ["work_runtime*"]` — `website/` is
excluded from the wheel; no pyproject change needed or made.
`scripts/verify_install.py` and installed-UI behavior are untouched and were
not run beyond the repo's normal gates.

## Remaining risks / pending (for integration)

1. Real-site gate run pending assembly (evidence above); `website/` checks at
   integration must not be waived.
2. Workflows unverified until the final-SHA CI run on GitHub (no local
   runner); YAML parsed locally only.
3. Pages first-publication admin enable + live URL verification remain open
   (roadmap Q2); this worker performed none of it.
4. README's "Verify a checkout" list still says "first seven commands" — an
   eighth gate (`python3 scripts/check_site.py`) now exists in AGENTS.md but
   was deliberately not added to the README block: on current main the
   command would fail until the site is assembled. Post-assembly docs step
   for integration.
5. Declined-to-judge (integration may revisit): `base`/`iframe`/`area` hrefs
   are not scanned (outside the D29 pin); actions pinned by release tag, not
   commit SHA (matches repo convention in `ci.yml`); root containment is
   lexical, like `check_docs.py` (symlinks inside the site are not resolved).

## Verdict

Delivery-owner scope complete: checker + meaningful failing-first tests,
CI/Pages wiring, honest preview/publish docs, AGENTS gate/doc-sync rows in
the same commit as the checker. Nothing claims the site itself is built,
deployed or visually verified.

## Addendum — 2026-10-14 README gate-list follow-up (task_be26affa69e9)

Coordinator-ordered docs-only closeout of this report's remaining item 4:
`python3 scripts/check_site.py` was added as the eighth gate command in the
"Verify a checkout" (EN) and 本地验证 (ZH) blocks of README.md and
README.zh-CN.md, with the stale "first seven commands" wording corrected to
"first eight" and a pointer to docs/website.md. The new prose states the
gate needs the website pages assembled to pass and does not prove browser
behavior — it does not claim the public site is deployed or that the site
gate has passed (the assembled-site run still pends integration). The
verify_install module/console coverage sentences and all local-trust claims
are untouched. Scope: both READMEs plus this addendum only; no
checker/tests/workflow/AGENTS/website/core changes, no new tests (prose
change), no merge/push. Verification: `python3 scripts/check_docs.py` → 0
broken links; `git diff --check` clean; `git status` shows only the two
READMEs and this report.
