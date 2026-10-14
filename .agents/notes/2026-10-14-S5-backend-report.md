# S5 read-only backend report — 2026-10-14

Worker: s5-readonly-backend worktree (branch `WayJ/s5-readonly-backend`). Scope held to
backend ownership only: `work_runtime/inspection.py`, `work_runtime/ui_server.py`,
`tests/test_inspection.py`, `tests/test_ui_server.py`, `docs/gui-api.md`, the scoped
plan and this report. No CLI/webasset/pyproject/verifier/engine/policy files touched; no
`work_runtime/web/` directory created; no merges or pushes.

## Immutable result

Code tip `2e5a912` on `WayJ/s5-readonly-backend` (base `8d4cfac`), 10 commits (this
report commits on top of `2e5a912` and touches docs only):

| commit | content |
|---|---|
| `795266c` | docs(plan): scoped S5 read-only backend plan |
| `e798c98` | feat(inspection): read-only store validation with bounded GuiReaderError |
| `3e4bfc7` | feat(inspection): summary metrics and work list envelope |
| `4f64e6d` | feat(inspection): work detail with verbatim and reconstructed raw payloads |
| `432d7cf` | feat(inspection): keyset event paging, INVALID_STORE and DB_BUSY bounded failures |
| `cdf2c01` | docs(plan): fix S5 supervision relative link (found by full-suite discovery) |
| `206eb12` | feat(ui-server): loopback whitelist HTTP API over the read-only inspector |
| `315f5d7` | feat(ui-server): Host/Origin loopback boundary and hostile-target rejection |
| `3d5732e` | docs(gui): public read-only API contract for the S5 GUI |
| `2e5a912` | fix(inspection): review fixes — honest schema check, DB_BUSY constructor, INVALID_STORE contract |

Public contract: [docs/gui-api.md](../../docs/gui-api.md) — settled shape was sent to the
master for the frontend owner before this report (message `msg_7c711b548266`); no silent
renames will follow.

## Interfaces delivered (D25)

- `ReadOnlyInspector(path)`: constructor validates an existing schema-1 store (percent-
  encoded absolute URI, `mode=ro`, `PRAGMA query_only=ON`, per-call short `BEGIN DEFERRED`);
  `summary()`, `list_works(limit=100, offset=0)`, `work_detail(work_id)`,
  `events(work_id, after=0, limit=100)`.
- `GuiReaderError(code, message)` bounded; codes `DB_NOT_FOUND | DB_NOT_READABLE |
  NOT_A_DATABASE | UNSUPPORTED_SCHEMA | INVALID_STORE | DB_BUSY | BAD_QUERY | UNKNOWN_WORK`.
- `make_ui_server(db_path, port=0)`: loopback `ThreadingHTTPServer` (`127.0.0.1`, ephemeral
  default), startup validation raising `GuiReaderError` (backs CLI exit 2), exact route
  whitelist `/`, `/app.js`, `/app.css`, `/api/summary`, `/api/works`, `/api/work`,
  `/api/events`; GET/HEAD only (405 + `Allow: GET, HEAD`); Host/Origin loopback boundary
  (403), absolute-form/traversal/unknown targets 404, duplicate/unknown/malformed queries
  400; accurate Content-Length incl. HEAD, nosniff/no-store/CSP on every response, no CORS
  ever; JSON error envelope with no stack traces, file contents, paths or raw-URL logs;
  DB_BUSY → 503, INVALID_STORE/others → 500 bounded.
- Precision: `seq/version/state_version/revisions/deadline/after/next_after` decimal
  strings; `state_raw/body_raw/receipt_raw` exact stored column text; `document_raw/
  plan_raw/completion_raw/data_raw/blockers_raw` canonical Python reconstruction with
  exact integers (`10000000000000001` verified byte-exact in raw text); summary maps
  dynamically discovered and sorted; `counts.attempts` counts stored operation attempt
  entries; list envelope key `works`.

## TDD evidence

Every task observed RED then GREEN (unittest, Python 3.9.6):

- Task 1 RED: `ModuleNotFoundError: No module named 'work_runtime.inspection'` → GREEN 7/7.
- Task 2 RED: 9 × `AttributeError: 'ReadOnlyInspector' object has no attribute 'summary'` → GREEN 16/16.
- Task 3 RED: 6 × `AttributeError: ... no attribute 'work_detail'` → GREEN 22/22.
- Task 4 RED: 12 errors (missing `events`, raw `OperationalError` on locked store, raw
  parse errors) → GREEN 34/34.
- Task 5 RED: module import failure → GREEN 13/13 (after adding the missing `Allow`
  header to 405s).
- Task 6 RED: 17 failures (Host/Origin unenforced) → GREEN 25/25.
- Review fix pass RED: 3 failing regression tests (schema fabrication vacuously covered by
  the constructor at first — test corrected to construct-then-degrade, then properly RED)
  → GREEN 37/37 module.

Fixture truth: all reader tests drive real `Runtime` stores through public commands
(`initialize`, `prerequisites`, `action`, `dispatch` with `FakeOA`, `request_cancel`,
`finalize_cancel`), plus targeted SQL corruption solely as reader-robustness fixtures.
Covered per D25: missing/unreadable/non-SQLite/schema-2/empty stores (never creating a
file), WAL reads during a live `BEGIN IMMEDIATE` writer, `BEGIN EXCLUSIVE` lock →
`DB_BUSY` (503 over HTTP), chmod-444 store still readable, full-table snapshot equality
after a complete read pass, Unicode/slash/quote work ids round-tripped through query
encoding, huge-integer precision, keyset event paging with unchanged tail cursor,
malformed JSON/types in every table → `INVALID_STORE`.

## Gates (fresh, final tip `2e5a912`)

- `python3 scripts/check_docs.py` → `checked 54 markdown files, 182 local links, 0 broken`
- `python3 -m unittest discover -s tests` → `Ran 574 tests ... OK` (baseline 512 + 62 new:
  37 inspection, 25 ui_server)
- `python3 -m work_runtime demo` → exit 0
- `python3 -m compileall -q work_runtime tests scripts` → clean

Doc-sync map: no `work_runtime/runtime.py`, `work_runtime/adapters.py` or
`scripts/check_docs.py` changes — no row owed.

## Rulings and deviations

- Missing-Host behavior: plan expected HTTP/1.1-without-Host to answer 400 via the base
  parser; CPython 3.9 `http.server` does not enforce Host, so the request reaches
  `_check_host` and both HTTP/1.0 and HTTP/1.1 missing-Host answer `403 BAD_HOST`
  (uniform, stricter). Documented in `docs/gui-api.md`.
- Request-time store-unavailability codes (`DB_NOT_FOUND` etc. after startup) map to
  bounded 500 per D25's "unavailable/unsupporteddb startup2, otherbounded500"; only
  `DB_BUSY` is 503.

## Limitations (honest)

- WAL visibility during a concurrent writer is an environment fact of this machine's
  SQLite (readable `-wal`/`-shm`), not a distributed guarantee — stated in the doc.
- Read timeout is 1.0 s: a genuinely contended store answers `DB_BUSY` after that wait.
- Static routes answer bounded `404 UNKNOWN_ROUTE` ("static asset not available") until
  the frontend owner ships `work_runtime/web/`; the backend deliberately created no
  placeholder files.
- Deferred minors (review, not fixed): `_split_authority` accepts unicode-digit ports
  (still loopback host + correct numeric port to match); `ui_server._API_LIMIT_MAX` is a
  dead constant (range enforced by the reader).

## Handoff

Frontend owner consumes `docs/gui-api.md` @ `3d5732e`+ (tip `2e5a912`); integration owns
review, assembly, acceptance and all merges/pushes. Nothing in this slice claims
production service safety, tenant authentication, or distributed exactly-once semantics.

## Addendum — 2026-10-14 original-owner correction: Origin must match the request Host origin

The master accepted the task settlement but rejected this behavior at sprint level: an
actual HTTP reproducer (request `Host: 127.0.0.1:<port>` with
`Origin: http://localhost:<port>`) returned **200**; D25 requires **403 BAD_ORIGIN**
because the Origin must match the *request's own* local origin, not merely be either
loopback alias with the right port. Earlier guidance (`msg_e0551f6f0977`) had not been
reflected in the final tip.

**Root cause** (`work_runtime/ui_server.py`, `_check_origin`): the check validated the
Origin independently — host ∈ {127.0.0.1, localhost} and port == the *bound* port —
so either alias was accepted regardless of which authority the request's Host named.
The pre-correction tests encoded the same wrong behavior: the old
`test_origin_accepted_when_matching` paired the fixed `Host: 127.0.0.1` with *both*
alias origins, which is why 62 tests passed while the boundary was wrong.

**Correction** (commit `622fc5e`): `_check_host` now returns the validated request's
normalized `(host, port)` and `_check_origin` requires the Origin's normalized
`(host, port)` to equal it exactly — the other alias is a different origin. Minimal
change; same-alias positives, absent Origin, duplicate/foreign/null/https/port-mismatch
rejection and the default-HTTP-port-80 normalization (both sides via the unchanged
`_split_authority`) are all retained.

**RED (actual HTTP, observed before the fix)**:
`python3 -m unittest tests.test_ui_server.BoundaryTests.test_origin_cross_alias_rejected -v`
→ `FAILED (failures=2)`, e.g. `AssertionError: 200 != 403 : ('Host: localhost:53269',
'http://127.0.0.1:53269')` — both cross-alias pairs returned 200.

**GREEN (after the fix)**: same test → 2 subTests pass; module
`tests.test_ui_server` 26/26 OK (the same-alias test now pairs each alias with itself);
full suite `Ran 575 tests ... OK` (574 prior + 1 new test); `python3 scripts/check_docs.py`
→ 54 files, 182 links, 0 broken; `python3 -m compileall -q work_runtime tests scripts`
clean. Live reproducer re-run over real HTTP recorded both cross-alias pairs →
`403 BAD_ORIGIN` and both same-alias pairs → `200`.

**Scope/VCS evidence**: correction confined to `work_runtime/ui_server.py`,
`tests/test_ui_server.py`, `docs/gui-api.md` (commit `e0eb120`: Origin bullet now states
the request-Host match and cross-alias rejection) and this addendum. Branch
`WayJ/s5-readonly-backend`: `7c0d4ae` (prior tip) → `622fc5e` (fix) → `e0eb120` (doc) →
this addendum commit. No engine/frontend/masterdoc edits, no nested agents, no local
approval UI, no merges or pushes. Sprint acceptance remains with integration; the
prior report's claims above describe the pre-correction tip and stand only as history.
