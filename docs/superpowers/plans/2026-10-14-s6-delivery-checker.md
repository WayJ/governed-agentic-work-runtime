# S6 Delivery Owner — Site Checker, CI/Pages, Docs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A bounded stdlib website checker with fixture tests, CI/Pages wiring and honest preview/publish documentation, exactly per ratified D29 — with no website-asset edits and no fake pass while the assembled site is unavailable on this carrier.

**Architecture:** `scripts/check_site.py` (offline `html.parser` scan of `website/`) exposes the pinned D29 API; `tests/test_check_site.py` proves every check against temp HTML fixtures only (the real site is not assembled in this checkout, so the live site gate is reported as pending, never silently skipped). `ci.yml` gains one site-gate step; a new official-shape `pages.yml` builds/uploads/deploys `website/` with exact pinned action releases but is never executed by this development owner. `docs/website.md` plus README link entries document local preview, subpath rehearsal, the planned-not-published Pages URL and the packaging boundary.

**Tech Stack:** Python >= 3.9 standard library only (`argparse`, `html.parser`, `os`, `pathlib`, `re`, `urllib.parse`, `typing`); stdlib `unittest`; GitHub Actions YAML (no local build tooling).

**Spec:** [D29 ratification](../specs/2026-10-14-s6-developer-website-design.md#builder-ratification--2026-10-14-before-code), [S6 sprint](../sprints/2026-10-14-S6-plan.md), [supervision Task 2](2026-10-14-s6-supervision.md), [builder review §Bounded checker pin / §Pages deployment pin](../../../.agents/notes/2026-10-14-S6-website-design-review.md), [AGENTS.md](../../../AGENTS.md), DESIGN.md (read; no visual change in this slice — its offline/no-CDN constraints are enforced by the checker itself).

## Global Constraints

- Python >= 3.9, zero runtime dependencies, stdlib `unittest`; `scripts/` is compileall-gated so the checker must stay 3.9-clean (typing imports, no new syntax).
- Ownership is exactly: `scripts/check_site.py`, `tests/test_check_site.py`, `.github/workflows/pages.yml`, `.github/workflows/ci.yml`, `docs/website.md`, README.md/README.zh-CN.md link entries, AGENTS.md site-gate + doc-sync rows, this plan and its report. **No website asset edits, no engine/GUI changes, no unrelated refactors.**
- Development worker never merges main, never pushes, never enables/deploys Pages. `pages.yml` is authored only; integration owns first publication after review (Q2 open).
- The checker never fetches: offline file checks only. Structural findings are never claimed as behavioral/visual evidence (browser checks stay required).
- A missing/unassembled `website/` must produce findings and exit 1 — never a fake PASS, never a silent skip.
- D29 API pinned: `Finding = NamedTuple(file, line, kind, detail)`, `scan(root: Path) -> List[Finding]`, `main(argv=None) -> int`, CLI `python3 scripts/check_site.py [--root website]`, exit 0 clean / 1 findings, deterministic (file, line, kind) order.
- AGENTS.md gate row `site: python3 scripts/check_site.py` and doc_sync_map row `scripts/check_site.py -> docs/website.md` land in the same commit as the checker (D29: with code, not before existence).
- Pages action versions pinned from primary sources verified 2026-10-14: `actions/checkout@v6` (v6.0.0 latest; also the docs.example tag), `actions/configure-pages@v6` (v6.0.0 latest; docs example shows v5), `actions/upload-pages-artifact@v5` (v5.0.0 latest; docs example v4, starter v3), `actions/deploy-pages@v5` (v5.0.1 latest; starter v5, docs example v4). Sources: docs.github.com custom-workflows page, actions/starter-workflows `pages/static.yml`, each action's `/releases` page.
- Baseline before change: 603 tests OK (skipped=1); docs gate, demo gate, syntax gate all green; `website/` absent in this checkout.

## Review Focus

- Percent-encoded traversal (`%2e%2e/`) and literal `../..` escaping the root while the file exists outside it — must be `out-of-root`, not a pass: pinned in Task 1 (`test_out_of_root_literal_and_encoded`).
- Entity-escaped URLs (`href="a&amp;b.html"`) double- or under-unescaped — must resolve to `a&b.html` exactly once: Task 1 (`test_entity_escaped_attribute_resolves`).
- `srcset` multi-candidate lists where only one candidate is missing — per-candidate resolution, not first-token-only: Task 1 (`test_srcset_candidates_checked_individually`).
- Fragment pointing into another document (`zh/index.html#id`) after percent-decoding — cross-document id resolution: Task 1 (`test_fragment_in_other_document`).
- Non-https/mailto navigation schemes (`http:`, `ftp:`) and any schemed asset URL (even `https:`) — `disallowed-scheme` / `external-asset`, never silently skipped: Task 1 (`test_insecure_and_non_https_navigation_schemes`, `test_external_asset_urls_rejected`).

---

### Task 1: `scripts/check_site.py` checker + fixture tests + AGENTS rows

**Files:**
- Create: `scripts/check_site.py`
- Test: `tests/test_check_site.py`
- Modify: `AGENTS.md` (gates list + doc_sync_map only)

**Interfaces:**
- Produces: `Finding(NamedTuple)` with fields `file: str` (root-relative posix path of the source page; the missing path itself for `missing-required`), `line: int` (0 for file-level findings), `kind: str`, `detail: str`; `scan(root: Path) -> List[Finding]` sorted by `(file, line, kind)`; `main(argv=None) -> int` (0 clean / 1 findings); default `--root` = `<checkout>/website`.
- Kind vocabulary (exact strings): `missing-required`, `missing-lang-link`, `leading-slash`, `out-of-root`, `missing-target`, `dangling-fragment`, `external-asset`, `disallowed-scheme`, `missing-alt`.
- Checks: required files `index.html`, `zh/index.html`, `assets/styles.css`, `assets/site.js`; every `*.html` under root is scanned for `a[href]`, `link[href]`, `script[src]`, `img[src]`/`img[srcset]`/alt presence, `source[src]`/`source[srcset]`; local URLs percent-decoded (and `?query`/`#fragment` stripped) then resolved against the page and required to exist and stay lexically inside root; leading-`/` local URLs are findings (subpath rule); fragments must match an `id` in the target document (same page for pure `#frag`); navigation hrefs allow only `https:`/`mailto:` externally; asset URLs must be scheme-less local paths; `img` requires an `alt` attribute; `index.html` must reference `zh/index.html` and `zh/index.html` must reference `../index.html`.

- [ ] **Step 1: Write the failing tests** — `tests/test_check_site.py`, stdlib unittest, temp-dir fixtures loaded via `importlib.util.spec_from_file_location` (pattern of `tests/test_docs.py`). Cases: clean bilingual fixture with nested zh page, srcset, cross-fragments, mailto/https nav, percent-encoded and entity-escaped URLs (scan → `[]`, CLI exit 0); broken link; missing asset; leading-slash; dangling fragment (same doc and cross-doc); missing zh page; missing styles/JS; http:// and ftp: navigation; external asset (https stylesheet/script); img without alt; out-of-root literal and `%2e%2e`-encoded; srcset candidates individually; crosslink missing either direction; absent root (4 × `missing-required`, CLI exit 1 — the no-fake-pass pin); deterministic (file,line,kind) ordering.

- [ ] **Step 2: Run to observe RED**

Run: `python3 -m unittest tests.test_check_site -v` (or discover)
Expected: FAIL/ERROR immediately — `scripts/check_site.py` does not exist (`FileNotFoundError` at module load).

- [ ] **Step 3: Implement `scripts/check_site.py` minimally**

Single-pass parser subclassing `html.parser.HTMLParser` collecting per-file `(refs, ids)`; second pass classifies refs into findings; `sorted(findings, key=(file, line, kind))`. `HTMLParser` already unescapes attribute values — no extra unescape. Containment via `os.path.normpath` on the joined absolute path (lexical, no symlink resolution). No network, no writes.

- [ ] **Step 4: Run to verify GREEN**

Run: `python3 -m unittest tests.test_check_site -v`
Expected: PASS, all new cases.

- [ ] **Step 5: AGENTS.md rows (same commit as checker)** — add `- site: python3 scripts/check_site.py` to the gates list and `| scripts/check_site.py | docs/website.md |` to doc_sync_map. Nothing else in AGENTS.md changes.

- [ ] **Step 6: Repo gates**

Run: `python3 -m compileall -q work_runtime tests scripts` → clean; `python3 -m unittest discover -s tests -v` → 603 + new, 0 failures; `python3 scripts/check_docs.py` → 0 broken.
Also run `python3 scripts/check_site.py` → expected exit 1 with exactly the 4 `missing-required` findings (site not assembled on this carrier) — capture output as the honest pending-gate evidence.

- [ ] **Step 7: Commit** — `git add scripts/check_site.py tests/test_check_site.py AGENTS.md` → `feat(site): add stdlib website checker with fixture tests and AGENTS site gate`

### Task 2: CI site gate + official Pages workflow

**Files:**
- Modify: `.github/workflows/ci.yml` (one step; matrix, installed-UI checks and everything else untouched)
- Create: `.github/workflows/pages.yml`

**Interfaces:**
- Consumes: Task 1 CLI (`python3 scripts/check_site.py`, exit 0/1).

- [ ] **Step 1: ci.yml** — add `- run: python scripts/check_site.py` directly after the `check_docs.py` step (matching existing `python` invocation style). No other edit.

- [ ] **Step 2: pages.yml** — official custom-workflow shape: `name`, `on: push: branches: [main] paths: ['website/**', 'scripts/check_site.py', '.github/workflows/pages.yml']` + `workflow_dispatch`; top-level `permissions: contents: read`; `concurrency: group "pages", cancel-in-progress: false` (official starter); `build` job: `actions/checkout@v6` → `actions/configure-pages@v6` → `run: python3 scripts/check_site.py` (deploy strictly depends on the site gate; ubuntu runners ship python3) → `actions/upload-pages-artifact@v5` with `path: website`; `deploy` job: `needs: build`, `permissions: pages: write, id-token: write, contents: read`, `environment: name: github-pages, url: ${{ steps.deployment.outputs.page_url }}`, step `id: deployment` `actions/deploy-pages@v5`. Header comment: first publication requires the one-time repo-admin Pages enable (Source: GitHub Actions); URL stays planned until integration verifies live HTTPS.

- [ ] **Step 3: Sanity checks** — `python3 -c "import yaml"` if available to parse both workflows (else structural review only, disclosed); confirm packaging boundary: `pyproject.toml` `include = ["work_runtime*"]` excludes `website/` (no pyproject change needed); confirm no push/deploy/enable executed locally.

- [ ] **Step 4: Commit** — `git add .github/workflows/ci.yml .github/workflows/pages.yml` → `ci(site): gate site in CI and add pinned official Pages workflow`

### Task 3: `docs/website.md` + README link entries

**Files:**
- Create: `docs/website.md`
- Modify: `README.md:7`, `README.zh-CN.md:7` (link rows only)

- [ ] **Step 1: Write `docs/website.md`** — sections: what the site is and who owns what; local preview `python3 -m http.server --directory website` (site only, not the production runtime); subpath rehearsal (serve a temp parent whose child copy is named `governed-agentic-work-runtime/`); the site gate command, exactly what it checks structurally and what it does not prove (browser checks remain required); Pages publishing via `pages.yml` with the pinned/verified action versions, triggers, and the one-time admin enable; planned URL `https://wayj.github.io/governed-agentic-work-runtime/` explicitly NOT published yet (integration owns publication after acceptance; Q2 open); packaging boundary (website stays out of the wheel, verified via `include = ["work_runtime*"]`, no pyproject change).

- [ ] **Step 2: README links** — EN link row gains `· [Website](docs/website.md)`; ZH row gains `· [网站](docs/website.md)`. No other README text changes (the "Verify a checkout" gate list stays untouched — disclosed as a post-assembly integration docs step, since the command cannot pass on main before the site exists).

- [ ] **Step 3: Verify docs gate** — `python3 scripts/check_docs.py` → 0 broken (new local links resolve; https links skipped).

- [ ] **Step 4: Commit** — `git add docs/website.md README.md README.zh-CN.md` → `docs(site): website preview/publish guide and README site links`

### Task 4: Report, final gates, worker_done

**Files:**
- Create: `.agents/notes/2026-10-14-S6-delivery-report.md`

- [ ] **Step 1: Run all gates fresh** — contracts, full tests (record exact count), demo, syntax, plus `python3 scripts/check_site.py` expected-fail evidence (4 × missing-required, exit 1) as the disclosed pending assembled-website check.

- [ ] **Step 2: Write the report** — exact immutable tip SHA and per-task commit hashes; RED/GREEN evidence summary for the checker; test counts (baseline 603 → actual); the pending live site gate (fixtures only prove the checker; the assembled site check happens at integration); pinned action versions with their verified sources; packaging boundary verification; residual risks (docs-example vs latest-release version choice recorded, README gate-list update deferred to integration, workflows unverified until final-SHA CI).

- [ ] **Step 3: Commit** — `git add .agents/notes/2026-10-14-S6-delivery-report.md` → `docs(site): S6 delivery owner report`

- [ ] **Step 4: Check inbox, then `worker_done`** — `orca orchestration check` once more immediately before reporting; send `worker_done` exactly once with the 3-sentence summary, `--files-modified`, `--report-path`, then idle.

---

Self-review: every D29 checker requirement maps to a Task 1 test; AGENTS same-commit rule carried in Task 1 Step 5; CI/Pages constraints in Task 2; docs/README/link scope in Task 3; no-fake-pass and pending-site evidence in Task 1 Step 6 and Task 4 Step 1; all five Review Focus lines have named Task 1 tests; types (`Finding` fields, kind strings, signatures) used consistently across tasks; plan length proportionate to the spec slice.
