# S5 integration report — 2026-10-14

S5 wave 2, independent integration (task_14f51c6944fa / ctx_aeb00f9dee7d, terminal
term_f61161e4-f9b6-419e-9903-151e48e8ae8c). Scope: source review of both owner tips,
assembly into the carrier, independent scenario verification (real browser, real HTTP,
real SQLite reconciliation, installed-module proof), acceptance, merge/push/CI.
Product corrections were routed to the original owners through the master; this session
wrote no product code.

## Assembly

- Carrier `WayJ/sprint-s5-gui` from master doc tip `60311fb` (base `8d4cfac`).
- Merged backend `fad5e01` (reader + loopback HTTP + Origin correction) and frontend
  `138d6b4` (assets/CLI/seed/packaging/verifier) — conflict-free, assembled `dd4b00e`.
- First full-suite run found 5 assembly-state test failures (4 backend static-asset
  expectations inverted by assembly, 1 frontend `sys.modules` assertion impossible
  under discovery); owner-corrected tips backend `7ab432f` (correction `7b6281c`) and
  frontend `e14798f` (subprocess port-gate proof `33af1ca`) merged → `44de1d9`,
  suite green `Ran 603 tests ... OK (skipped=1)`.
- Browser verification found the blocking first-render stuck-loading defect plus the
  tab-focus drop; frontend corrected tip `a9db96e` (with actual-browser RED/GREEN and a
  committed regression artifact) merged last → pre-acceptance carrier `770d516`.

## Independent review findings (all routed through the master)

1. **Blocking — frontend first-render stuck loading list** (4 reproductions incl. real
   Chrome): `refresh()` rendered the works list before setting `state.loadedOnce`, so
   the first successful response showed the loading placeholder forever (unchanged-
   payload guard then skipped re-renders); also masked the empty-store message.
   Corrected by the owner in `a9db96e`; independently re-verified here with zero
   interaction: demo store 5 items, probe store 6 items, empty message, narrow 390
   first load.
2. Backend `test_static_assets_bounded_404_without_files` encoded the pre-assembly
   state; corrected with a fixture-isolated no-web package copy plus a real
   present-asset serving test (byte-equal, MIME, GET/HEAD length).
3. Frontend port-gate test asserted global `sys.modules` purity; corrected with a
   fresh-subprocess probe (exit codes 10/11/12 name the violated property,
   mutation-tested).
4. Minor: tab roving focus fell to `<body>` after arrow switches (detached closure);
   fixed in `a9db96e`; re-verified with trusted CDP key events at both viewports.
5. Minor (doc nuance, backend owner): stdlib `http.server` collapses leading `//`
   before the handler, so `//app.js` serves the whitelisted asset; no traversal
   possible (byte-equal to the packaged asset; all traversal forms 404).
6. Assessed per master request: client TCP reset mid-response prints a stdlib
   `handle_error` `BrokenPipeError` traceback on server stderr; no data leak, server
   healthy, access log stays method+status. Non-blocking; a `handle_error` override
   could bound it.
7. Unreproduced observation: one long-lived tab kept the disconnected banner after
   server restart until a manual refresh; controlled instrumented reproduction showed
   correct automatic recovery. Recorded for monitoring.
8. Owner's regression artifact has a flaky empty-store check (`items==0` ambiguous
   before the first fetch); its two failures here were disproven by a deterministic
   settle-wait first-load check (×2 green). Artifact-race, not product.

## Verification evidence (fresh, at `770d516`)

- Unit: `Ran 603 tests ... OK (skipped=1)` = 512 baseline + 37 `test_inspection` +
  27 `test_ui_server` + 13 `test_ui_demo` + 14 `test_ui_cli`; the skip is the
  frontend's disclosed backend-assembled guard (skipped ≠ tested, not counted).
- Rehearsal separate: `python3 -m unittest discover -s examples/rehearsal` →
  `Ran 14 tests ... OK`. Contracts: `checked 54 markdown files, 189 local links,
  0 broken`. Syntax: compileall clean. Demos: `demo`, `publish-demo`,
  `intervention-demo`, `adoption-demo` exit 0.
- Installed: `python3 scripts/verify_install.py` → `=== PASS ===`; the installed-UI
  stages ran for real (no skip): module and console `ui-demo` plus console `ui`
  served real HTTP outside the checkout, assets byte-equal to packaged bytes, five
  seeded works over the API, tables unchanged before/after, SIGINT → exit 0.
- S1 probe: 28/28 — metrics reconcile with direct SQL (incl. `counts.attempts` = stored
  attempt entries), works order, unicode/slash/quote id round-trip, `state_raw`
  byte-equality, exact big integers, multi-page keyset walk == SQL, read-only snapshot
  equality.
- S2/S3 probe: 70/70 — reader failure fixtures, WAL live-writer read, rollback-journal
  exclusive lock → 503 `DB_BUSY`, corrupt JSON bounded 500 without leaks, full method/
  target/query/Host/Origin boundary, zero CORS, client-RST liveness.
- Browser (Orca embedded browser; screenshots in the acceptance record's
  `s5-screenshots/` and `/tmp/s5-acceptance/shots/`): first load without interaction
  (post-fix), empty state, bilingual default+toggle, keyboard list navigation and Enter
  (real CDP keys), tab arrows with live focus (real CDP keys, desktop+narrow), filter/
  search/no-match, manual refresh, poll pause freezing the sampling clock and resume,
  live external writer visible after refresh with Load-more 50→64, disconnected banner
  with automatic recovery, stored XSS text-only (`window.__pwned` undefined, zero
  injected elements), huge integer exact, same-origin-only network, clean console.
- Narrow (labeled substitution — Orca browser has no viewport control, no emulator
  devices installed): real headless Chrome CDP at 390×844 and 320×700 —
  `horizontalOverflow: false`, stacked layout, usable detail/events, first load
  renders without workaround.

## Ownership

Backend product code/tests/docs by the backend owner (corrections included); frontend
assets/CLI/seed/packaging/verifier/docs and both browser corrections by the frontend
owner; master docs by the master. This session owned review, assembly, scenario
verification, acceptance, merge, push and CI verification only. Developer worktrees
preserved and clean at validation time; no nested agents; no local approval UI.
