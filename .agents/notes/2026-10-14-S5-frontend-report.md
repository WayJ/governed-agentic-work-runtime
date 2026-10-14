# S5 frontend/CLI report — 2026-10-14

S5 wave 1, frontend/CLI owner. Worker: `s5-browser-interface` (Claude Code, Orca
dispatch task_00bd446e8a53 / ctx_ed8f26588ffa). Base: `8d4cfac` (512 tests, docs
gate clean, demos green — all recorded before the plan commit). Worked isolated on
top of the base, no rebase/merge/push, no nested workers. Spec:
[S5 GUI design + D25](../../docs/superpowers/specs/2026-10-14-s5-gui-design.md)
(D25 overrides the builder report; backend owner concurrently owns
`inspection.py`/`ui_server.py`/`docs/gui-api.md`, absent in this checkout),
[sprint S5](../../docs/superpowers/sprints/2026-10-14-S5-plan.md) wave-1 frontend
story, [supervision Task 2](../../docs/superpowers/plans/2026-10-14-s5-supervision.md),
[S5-open](2026-10-14-S5-open.md) / [S4-close](2026-10-14-S4-close.md) lessons.
Plan: [2026-10-14-s5-frontend.md](../../docs/superpowers/plans/2026-10-14-s5-frontend.md).

## Commits (base 8d4cfac → tip 729a66b)

| sha | subject |
|---|---|
| `c3f9681` | docs(gui): scoped S5 frontend/CLI plan |
| `4b0e9cb` | feat(gui): five-work real-command seed for UI trials |
| `656a1d4` | feat(gui): ui and ui-demo CLI commands with lazy backend serve loop |
| `3f45463` | feat(gui): offline bilingual browser assets over the read-only API |
| `54a370f` | build(gui): package web assets; installed module+console UI verification stages |
| `158e3d6` | docs(gui): user guide, verifier coverage and bilingual READMEs |
| `729a66b` | fix(gui): error surfacing and focus stability in poll refreshes (review pass) |

Owned files changed: `work_runtime/ui_demo.py` (new: `seed_ui_demo`, documented
`UnavailableLookup` composition, `serve_ui`, `run_ui_demo`), `work_runtime/web/`
(new: index.html/app.js/app.css, no inline script/style, no CDN/framework/network),
`work_runtime/cli.py` (+2 lazy subcommands only), `tests/test_ui_demo.py` (new,
13 tests), `tests/test_ui_cli.py` (new, 14 tests), `pyproject.toml` (package-data
`web/*`), `scripts/verify_install.py` (2 new stages + helpers; no prior stage
changed), `docs/gui.md` (new), `README.md`, `README.zh-CN.md`, `CONTRIBUTING.md`,
`docs/verification.md`, own plan + this report. CI unchanged (existing
`verify_install.py` step exercises the new stages; no blocking `ui-demo` CI step —
it serves until interrupted). **Boundary audit:** `git diff --name-only
8d4cfac..HEAD` over engine/policy/adapter/ingress/authoring/file-adapter/demo
modules, every pre-existing test, `scripts/check_docs.py`, `.github/`,
`inspection.py`/`ui_server.py`/`docs/gui-api.md` is **empty**.

## RED → GREEN evidence (observed verbatim)

1. **Seed** — RED: `python3 -m unittest tests.test_ui_demo -v` →
   `ModuleNotFoundError: No module named 'work_runtime.ui_demo'`. GREEN:
   `Ran 13 tests ... OK`; full suite `Ran 525 tests ... OK`.
2. **CLI/serve loop** — RED: `python3 -m unittest tests.test_ui_cli -v` →
   `ImportError: cannot import name 'run_ui_demo' from 'work_runtime.ui_demo'`.
   GREEN: `Ran 14 tests ... OK`; full suite `Ran 539 tests ... OK`. One test
   corrected during the cycle (its own setUp polluted the seeded parent
   directory; moved to a dedicated subdirectory — test bug, not product).
3. **Packaging/verifier** — baseline `python3 scripts/verify_install.py` →
   `=== PASS ===` (prior build unchanged). RED for the new stage:
   `FAILED: the install ships no packaged web asset index.html`. GREEN after
   package-data: `web assets: index.html, app.js, app.css` real, then
   `=== installed UI (module and console) over real HTTP ===` →
   `SKIPPED: read-only UI backend (work_runtime.ui_server) is not present in
   this build; installed UI HTTP verification runs once the backend is
   assembled.` Final line discloses
   `SKIPPED stages: installed-UI HTTP (backend not assembled)`.
4. **Browser assets** — no unit tests by plan (browser RED/GREEN belongs to
   assembled integration; no fake-DOM/source-keyword tests written).
   `node --check app.js` clean; en/zh dictionaries verified complete (114/114
   keys, none undefined); invariant scan: no `innerHTML`/`eval`/`JSON.parse`,
   `Number()` only on numeric count fields.

## Final gate evidence (tip 729a66b)

- `python3 -m unittest discover -s tests` → `Ran 539 tests ... OK`
  (512 baseline + 27 new).
- `python3 scripts/check_docs.py` → `checked 53 markdown files, 183 local
  links, 0 broken`.
- `python3 -m compileall -q work_runtime tests scripts` clean;
  `python3 --version` → 3.9.6.
- All four prior demos exit 0 (`demo`, `publish-demo`, `intervention-demo`,
  `adoption-demo`).
- `python3 scripts/verify_install.py` → `=== PASS ===` with all prior stages
  intact, packaged web assets verified, installed-UI HTTP stage explicitly
  SKIPPED (backend not assembled) and disclosed in the summary line.
- CLI probes: `ui --db /nonexistent` → bounded stderr + exit 2;
  `ui-demo --port 70000` → bounded stderr + exit 2; `demo` still exit 0.

## What was built (key works)

- **Seed** (`seed_ui_demo(directory=None) -> str`): one fresh
  `governed-ui-*` folder, one runtime + one shared FakeOA store, five works
  (`wait-1` waiting with a pending-verification approval and a persisted
  rejected proposal; `uncertain-1` needs_attention via post-commit timeout +
  `UnavailableLookup` reconcile → `NO_AUTHORITATIVE_RESULT` with the accepted
  effect retained; `transfer-1` agent→delegate with the invalidated-then-
  readmitted operation confirmed; `succeed-1` closed/succeeded;
  `cancel-1` closed/cancelled acknowledging the exact recovered external
  effect). Distinct `EXP-UI-00x`/`INV-UI-00x` ids; exactly 4 accepted
  applications; no direct SQL state writes; never deletes user data.
- **CLI**: `ui --db <existing> [--port 0..65535]` and `ui-demo [--directory]
  [--port]`; port/db validation exits 2 with bounded messages BEFORE any
  backend import; actual URL printed flushed; `KeyboardInterrupt` → clean
  `server_close()` + exit 0; backend import is lazy, so every prior command
  works in installs without the read-only backend (subprocess-isolated test).
- **Assets**: offline bilingual (EN/中文) light "Governed Work" UI — five
  definition-carrying metric tiles, dynamic record-count chips (incl.
  `counts.attempts` when the backend provides it), search/status filter with
  keyboard list navigation (`↑/↓/Home/End`, `/` to search), tabbed detail
  (overview/requirements/evidence/operations/decisions/events/documents) with
  `←/→` tab roving focus, keyset event pagination (`after` cursor passed
  unchanged, `has_more` → load more), manual refresh + pausable 5 s polling,
  loading/empty/error/disconnected states, refresh/detail epochs + selection
  guards against stale responses, everything through `createElement`/
  `textContent`, `*_raw` payloads never parsed, string numerics never through
  `Number()`, external ids as text (never links), cancellation banner
  independent of presentation status with the retained-effect note derived
  from structured operation fields, responsive narrow layout without page
  overflow.
- **Packaging/verification**: `web/*` ships as package data; verifier stage 13
  (assets inside a fresh install, always-on) and stage 14 (module AND console
  `ui-demo`/`ui` as real subprocesses outside the checkout: real HTTP fetches,
  served assets byte-equal to packaged bytes, five seeded works over the API,
  store tables identical before/after, SIGINT → clean exit 0) with loud,
  summary-disclosed skip when the backend is absent.

## PENDING (explicitly not verified here)

- **Assembled-backend HTTP verification** — stage 14's real path first runs
  when the backend owner's `ui_server` is assembled into an install. Its
  helper logic was smoke-tested against a scratch stand-in server in `/tmp`
  (URL read, asset byte-equality, API shape checks, read-only snapshots, clean
  SIGINT exit) — recorded as smoke only, not assembled verification.
- **Actual browser verification** — desktop/narrow layout, bilingual toggle,
  keyboard navigation, filter/refresh/poll pause, stored-XSS non-execution,
  exact big-integer rendering, disconnected/error states, stale-response races
  in a real browser: independent integration wave (supervision Task 3).
- **DTO drift risk** — the assets consume the D25-pinned DTO shapes; the
  backend owner's `docs/gui-api.md` is the settling document and integration
  must reconcile any drift.

## Limitations / honest-language notes

- Loopback binding is convenience, not authentication; the viewer is a local
  read-only tool, not a service. Sampling time in the header is observation
  time, never business-event time. Command receipts are rendered as
  admissions, not effects; requirements vs historic decision blockers are
  visually and textually separated. Cancellation shows acknowledged retained
  effects, never reversal. The `UnavailableLookup` wrapper is a documented
  demonstration composition, not a FakeOA behavior change.
- Serve-lifecycle unit tests use an interface-conforming stub server — a CLI
  lifecycle test, not an HTTP or browser claim; no console/browser coverage
  beyond the verifier's actual stages is claimed anywhere in the docs.
- Deferred minor: `serve_ui` does not special-case `Ctrl-C` during server
  construction (before `serve_forever`), which exits with a standard
  traceback; cosmetic edge, no data risk.

Self-review (no nested reviewers per AGENTS.md): plan Review-Focus classes
re-checked; five defects found and fixed in one pass (`729a66b`): null-summary
crash in the status filter, poll-driven list focus loss, silent API-error
swallowing, stuck loading list on persistent `/api/works` failure, events
re-render on unchanged poll. Fixes verified by `node --check`, the invariant
scan and the green suite; DOM-level verification remains integration's.
