# S8 Task4 viewer report — derived revoked-evidence reader + notice — 2026-10-15

Scoped owner slice on branch `WayJ/s8-revocation-viewer`, base carrier
`41583e2` (exact asserted; clean tree). Implements **D37 only** — the
read-only derived DTO fields and the visible closed-work correction notice.
No whole-S8 release claim: demo (Task3) and final acceptance/release
(Task5) belong to their owners.

## Commits (41583e2 → beac5d8, then docs/report)

| commit | content |
|---|---|
| `50bee8b` | feat: derive revoked-evidence reader fields in work_detail (D37) — `work_runtime/inspection.py`, new `tests/test_revocation_viewer.py` (9 reader tests), `tests/test_inspection.py` full-shape set gains `"id"` |
| `542db87` | test: pin /api/work revoked-evidence fields over HTTP (2 API tests) |
| `beac5d8` | feat: bilingual closed-work revoked-evidence notice + revoked chip — `work_runtime/web/app.js`, `app.css`, browser script `.agents/notes/2026-10-15-S8-viewer-browser.py` |
| `e2cc0cc` | docs: D37 reader DTO fields and notice (`docs/gui-api.md`, `docs/gui.md`) |
| (this) | scoped plan `docs/superpowers/plans/2026-10-15-s8-revocation-viewer.md`, evidence assets, this report |

Changed-file boundary: `inspection.py`, `web/app.js`, `web/app.css`,
`tests/test_revocation_viewer.py`, `tests/test_inspection.py`, `docs/gui.md`,
`docs/gui-api.md`, `.agents/notes/*` only. No runtime.py, policies,
adapters, cli.py, revocation_demo.py, verify_install.py, README, core/demo
docs or ledgers. `index.html` untouched (notice is rendered by `app.js`).

## What was built

- **Reader (D37 exact):** `ReadOnlyInspector.work_detail` now also returns
  `evidence[].id` (nonempty stored string, else `null`; `body_raw`/`data_raw`
  unchanged), top-level `revoked_evidence` (`{id, source, event_id, kind,
  status}` for every stored `revoked` row of the work, same (source,
  event_id) order), and `completion_revoked_evidence_ids` (intersection of
  the **valid string** entries of `completion.evidence` with the revoked
  rows' valid ids — stored citation order, deduplicated). All derived inside
  the existing single short read-only snapshot; nothing persisted, no
  Runtime constructed, no policy evaluated. Cancellation completions
  acknowledge operations and contribute no citations — never fabricated.
- **Notice (viewer):** for a **closed** work with non-empty `revoked_evidence`,
  a neutral bilingual notice renders under the detail header: the historical
  closure and outcome stay exactly as recorded (nothing reopened/rewritten)
  while the revoked evidence only changes current status (no longer valid
  proof for current requirements). When `completion_revoked_evidence_ids`
  is a non-empty array it shows the derived count and exact id strings;
  otherwise no citation line. Two buttons jump to the Evidence/Events tabs.
  The revoked status chip joins the measured error tokens
  (`.chip-st-revoked`: `#f9e8ec`/`#b32449`). `*_raw` is never parsed; every
  string reaches the DOM via `textContent`.

## Reproduce

```bash
python3 -m unittest tests.test_revocation_viewer tests.test_inspection -v   # 46 tests
python3 -m unittest discover -s tests                                       # 690, skip 1
python3 .agents/notes/2026-10-15-S8-viewer-browser.py --phase red   --out /tmp/s8vr
python3 .agents/notes/2026-10-15-S8-viewer-browser.py --phase green --out /tmp/s8vg
```

The browser script seeds one real store through **public lifecycle APIs
only** (`create_work`/`bind_contract`/`record_evidence`/`verify_pending`/
`propose_action`/`dispatch`/`request_completion`/`request_cancel`/
`finalize_cancel`/`revoke_evidence`) with five works: `succeed-closed`
(cited approval revoked after closure, document amount `10000000000000001`),
`cancel-closed` (acknowledged external effect + revoked proof),
`unbound-closed` (D-1 family), `open-revoked` (active — no notice),
`clean-closed` (no revocation — no notice). It serves the real
`python3 -m work_runtime ui` subprocess on its own ephemeral loopback port
(the user preview at `http://127.0.0.1:52719/` was never touched) and drives
actual Chrome over CDP (S7's stdlib client).

## RED → GREEN evidence

**Reader TDD** (`tests/test_revocation_viewer.py`): first run **RED — 10
errors**, all `KeyError: 'revoked_evidence'` / `'id'` /
`'completion_revoked_evidence_ids'` (feature missing, no fixture errors).
After the minimal `work_detail` change: viewer+inspection **46/46 OK**, full
suite **690/690 skip 1** (679 baseline + 13 new tests; skip = pre-existing
root-chmod test).

**Browser RED** (committed assets, derived API already present): 8/8 —
`/api/work` carries `revoked_evidence` + cited ids, the notice is **missing
on all five works** (including the three closed-revoked works that must show
it — the demonstrated gap), the revoked chip renders on the neutral base
(`#eceae4`/ink, recorded), all six store tables byte-identical after the
session. `s8-viewer-red-results.json`.

**Browser GREEN** (after `beac5d8`): **30/30** —
`s8-viewer-green-results.json`:

- Notice shown on `succeed-closed`/`cancel-closed`/`unbound-closed`, absent
  on `open-revoked`/`clean-closed`; EN and ZH copy both distinguish
  historical closure (unchanged) from current proof status (corrected);
  citation count + exact id text only on `succeed-closed` (derived), no
  fabricated citation line on the cancelled/unbound closures.
- Computed DESIGN styles: notice `rgb(250,250,247)` cream-soft, `1px solid
  rgb(207,205,196)` hairline-strong, `12px` radius, `box-shadow: none`,
  title ink `rgb(38,37,30)`, body `rgb(90,88,82)`; revoked chip
  `rgb(249,232,236)`/`rgb(179,36,73)`.
- Measured contrast: notice-title **15.38:1**, notice-body **7.11:1**,
  revoked chip **5.45:1** (all ≥4.5:1; loud-missing guard active).
- Keyboard: Enter on notice button 1 → Evidence tab, button 2 → Events tab;
  tab ArrowRight navigation intact with the notice present.
- Polling (≥5.6 s with the work selected): notice retained, list focus
  retained. Disconnect: server killed → banner; restarted on the same port
  → banner cleared, notice intact.
- Raw exactness: `10000000000000001` present as exact text in the Documents
  tab (probed with a JS *string* literal — a numeric literal would itself
  round, the exact hazard under test).
- Viewports 1440×900 / 390×844 / 320×690: no horizontal overflow; 7
  screenshots in `.agents/notes/assets/s8-viewer-green-*.png` (desktop,
  390, 320, clean-closed no-notice desktop/390, ZH, evidence tab).
- Zero writes: all-six-table digest equal before/after the whole browser
  session in **both** phases (plus the reader-level
  `test_full_read_pass_writes_nothing`).

**PNG corroboration** (`s8-viewer-png-verify.json`, stdlib decode): declared
dimensions on every capture; canvas `#f7f7f4` + white cards + ink everywhere
(no blanks); the cream-soft `#fafaf7` notice surface appears in the
succeed-closed captures (124k px desktop) and is nearly absent in
clean-closed (17.8k px — only the raw-code blocks); the error-soft
`#f9e8ec` chip pixels present in the evidence capture (1035 px).

## Gates (this checkout, after all commits)

| gate | result |
|---|---|
| contracts `python3 scripts/check_docs.py` | 84 markdown files, 305 local links, **0 broken** |
| tests `python3 -m unittest discover -s tests` | **690 ran, OK, skipped=1** (pre-existing) |
| demo `python3 -m work_runtime demo` | exit 0 |
| syntax `python3 -m compileall -q work_runtime tests scripts` | clean |
| site `python3 scripts/check_site.py` | 2 pages, 0 findings |

Prior demos untouched by this slice; `revocation-demo` remains the demo
owner's scope.

## Material adaptations (DESIGN.md → operations viewer)

- The notice is a **neutral** cream-soft card (hairline-strong border, 12px
  card radius, no shadow, body 13.5px) — deliberately not an error surface:
  it corrects current proof status without dramatizing an unchanged
  historical closure; meaning is carried by text in both languages,
  independent of color.
- The revoked chip reuses the S7 **measured error tokens** (`#b32449` on
  `#f9e8ec`, 5.45:1) — the neutral base still covers unanticipated status
  strings; no timeline pastels anywhere.
- Notice buttons inherit the global ≥44px touch target; tab-navigation
  only, no write controls, no summary tile.
- No display-size typography introduced (title 14px/600, no tracking);
  CJK renders with the existing system font fallback and zero tracking rule
  untouched.

## Final review

Self-review pass performed in-session over the whole branch diff (no
subagent dispatched — the working agreement forbids extra workers without
coordinator approval; the sprint's independent integration review is Task5).
Checked: D37 field shapes exact; malformed-id/citation degradation with raw
retained; notice discipline (closed-only, count-only-when-derived); EN/ZH
current-vs-historical wording; no `*_raw` parsing; graceful notice absence
when an older backend lacks the keys; token-only CSS; no ownership
violations. Findings: none unresolved.

## Limits / risks

- No claim beyond D37: revocation-demo, CLI/installed verifier, README and
  the whole-S8 release are other owners' slices; S8 is **not** declared
  released here.
- The browser run used this machine's actual Chrome (headless, CDP); stores
  seeded fresh per run into temp dirs. TD-1 and all core limits from the
  integration review remain unchanged.
- Contrast ratios are computed from real DOM computed styles (fg/bg pair of
  the element); the notice title/body background is the notice's own
  cream-soft surface (rgba(0,0,0,0) transparency resolves to it — the
  measured fg/bg pair is title/body color on #fafaf7).
