# S5 Read-Only Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose existing schema-1 work stores through a read-only `ReadOnlyInspector` and a loopback-only whitelisted HTTP API, exactly per D25.

**Architecture:** `work_runtime/inspection.py` opens per-call short `mode=ro`/`query_only` SQLite read transactions over the percent-encoded absolute file URI (never constructing `Runtime`); `work_runtime/ui_server.py` wraps it in a `ThreadingHTTPServer` bound to 127.0.0.1 with an exact route/method/Host/Origin whitelist. Whole-column JSON stays verbatim (`*_raw`), nested payloads are reconstructed with `policy.canonical` (exact integers), and every precision-bearing integer crosses the wire as a decimal string.

**Tech Stack:** Python >= 3.9 standard library only (`sqlite3`, `http.server`, `urllib.parse`), `unittest`, zero runtime dependencies.

**Spec:** [D25 design](../specs/2026-10-14-s5-gui-design.md), [S5 sprint](../sprints/2026-10-14-S5-plan.md), [S5 supervision](2026-10-14-s5-supervision.md), [builder check](../../../.agents/notes/2026-10-14-S5-design-review.md) — D25 overrides the builder report where they differ (goal in contract, requirement `id`, commands list, `counts.attempts`, whole-column `state_raw`/`body_raw`/`receipt_raw`).

## Global Constraints

- Python >= 3.9, standard library only, `unittest`, zero runtime dependencies.
- Backend ownership only: `work_runtime/inspection.py`, `work_runtime/ui_server.py`, `tests/test_inspection.py`, `tests/test_ui_server.py`, `docs/gui-api.md`, this plan, `.agents/notes/2026-10-14-S5-backend-report.md`. Do not touch CLI, `work_runtime/web/`, pyproject, verifier, engine or policies. Do not create `work_runtime/web/` or any placeholder asset.
- No merges, no pushes, no nested workers; blocking decisions go to the master through Orca orchestration.
- Every behavior change: meaningful failing test observed, minimal implementation, GREEN, evidence recorded.
- Error bodies: `{"error": {"code": ..., "message": ...}}` — bounded, no stack traces, no file contents, no raw paths; source basename appears only inside `summary().source`.
- Reader never creates, initializes, migrates or writes any store; no `Runtime` import in `inspection.py`/`ui_server.py`.

## Review Focus

1. **Malformed stored JSON/types + legacy absent owner + lock** — broken JSON in any table, non-dict `state`, non-int `state_version`/`version`, absent `owner`/`contract` keys, writer-held exclusive lock: bounded `INVALID_STORE`/`DB_BUSY`, never a skipped record, fabricated metric or crash. (Task 2/3/4 tests)
2. **Opaque Unicode/slash/quote Work IDs, huge integers, keyset event paging** — exact round-trip through query encoding and SQL, `10000000000000001` preserved verbatim in raw text, decimal-string seq/version/revision/deadline/cursors, stable `after` chaining. (Task 3/4/5 tests)
3. **Duplicate Host/Origin/query, unexpected method, absolute/traversal targets** — safe bounded rejection (403/405/400/404) with accurate `Allow`/`Content-Length` and no CORS. (Task 5/6 tests)
4. **No leaks** — error bodies and access logs never contain the raw URL, file paths or stack traces. (Task 6 tests)
5. **Read-only truth** — no file creation on missing DB, table snapshots unchanged after full read pass, WAL commits visible while a writer holds `BEGIN IMMEDIATE`, chmod-444 store still readable. (Task 1/4 tests)

---

### Task 1: Reader construction and store validation

**Files:**
- Create: `work_runtime/inspection.py`, `tests/test_inspection.py`
- Modify: none

**Interfaces:**
- Produces: `GuiReaderError(code, message)` with `.code`/`.message`; `ReadOnlyInspector(path)` raising `GuiReaderError` with codes `DB_NOT_FOUND` (path absent; path stays absent), `DB_NOT_READABLE` (exists, `os.access` R_OK false), `NOT_A_DATABASE` (`sqlite3.DatabaseError` mentioning "not a database"/"malformed"), `UNSUPPORTED_SCHEMA` (`no such table: metadata`, missing row, or value != "1"). Attribute `inspector.path` = the resolved absolute path.

- [ ] **Step 1: Commit this plan**

```bash
git add docs/superpowers/plans/2026-10-14-s5-backend-plan.md
git commit -m "docs(plan): scoped S5 read-only backend plan"
```

- [ ] **Step 2: Write failing tests** in `tests/test_inspection.py` — `_store()` helper builds a real `Runtime` store (`ExpensePolicy`, `demo_grants`, `initialize`); tests: `test_missing_db_raises_and_never_creates`, `test_unreadable_db_raises` (chmod 0o000, skip when `os.geteuid() == 0`), `test_text_file_is_not_a_database`, `test_empty_sqlite_file_is_unsupported_schema`, `test_wrong_schema_version_is_unsupported` (sqlite3-written `schema_version` "2"), `test_valid_store_constructs`. Assert `.code` exactly; assert `GuiReaderError` is an `Exception` subclass.

- [ ] **Step 3: RED** — Run: `python3 -m unittest tests.test_inspection -v`; expect ImportError/module failures.

- [ ] **Step 4: Implement** `GuiReaderError` and `ReadOnlyInspector.__init__` in `work_runtime/inspection.py`: resolve path; classify per Interfaces; open via `sqlite3.connect("file:" + urllib.parse.quote(resolved, safe="/") + "?mode=ro", uri=True, timeout=1.0)` inside a helper `_read_connection()` context manager that also sets `PRAGMA query_only=ON` and closes. Constructor validation runs one short deferred read transaction (`SELECT value FROM metadata WHERE key='schema_version'`) and closes it.

- [ ] **Step 5: GREEN** — `python3 -m unittest tests.test_inspection -v` all pass.

- [ ] **Step 6: Commit** — `git add work_runtime/inspection.py tests/test_inspection.py && git commit -m "feat(inspection): read-only store validation with bounded GuiReaderError"`

### Task 2: `summary()` and `list_works()`

**Files:**
- Modify: `work_runtime/inspection.py`, `tests/test_inspection.py`

**Interfaces:**
- Consumes: Task 1 constructor/`_read_connection`.
- Produces: `summary() -> dict` with keys `source` (basename), `schema_version`, `counts` {`works`,`events`,`operations`,`evidence`,`commands`,`attempts`} (plain ints; `attempts` = total stored operation attempt entries), and sorted count maps `work_statuses`, `closed_outcomes` (closed works only), `operation_statuses`, `evidence_statuses`, `command_decisions` (by receipt `decision`), `event_types` (dynamic `SELECT type, COUNT(*) … GROUP BY type`). `list_works(limit=100, offset=0) -> {"total", "limit", "offset", "works": [...]}` — `works` items: `id`, `status`, `state_version` (decimal string), `owner` (null when absent), `outcome` (null unless closed), `contract` null or `{policy_id, policy_version, goal, revision}` with `revision` decimal string, `cancellation_requested` bool; `ORDER BY id ASC`; invalid `limit`/`offset` (non-int, limit not 1..200, offset < 0) → `GuiReaderError("BAD_QUERY", …)`. Malformed stored state → `GuiReaderError("INVALID_STORE", …)`.

- [ ] **Step 1: Write failing tests** — `test_summary_counts_match_sql_reality` (seed: succeeded work incl. dispatch + verified evidence + one rejected receipt; compare each count/map against direct SQL/canonical parses, incl. `counts.attempts` == 1, `command_decisions` == {"accepted": …, "rejected": 1}, `event_types` contains only observed types sorted), `test_summary_maps_keys_sorted`, `test_list_works_envelope_and_order` (multi-work store, id ASC, envelope fields incl. contract `goal`, `revision` str, `state_version` str, owner, outcome), `test_list_works_absent_owner_contract_null` (SQL-crafted legacy row with owner/contract keys removed — reader fixture, not an engine claim), `test_list_works_pagination_and_defaults` (limit/offset slicing vs total), `test_list_works_rejects_bad_limit_offset` (0, 201, -1, "5", None), `test_summary_malformed_state_raises_invalid_store`.

- [ ] **Step 2: RED** — `python3 -m unittest tests.test_inspection -v`; new tests fail with AttributeError.

- [ ] **Step 3: Implement** both methods, each one short read transaction; parse every `works.state`/`operations.body` (INVALID_STORE on non-JSON or non-dict); maps built `dict(sorted(...))`; decimals via `str(int)` with `INVALID_STORE` when a version field is not `int`.

- [ ] **Step 4: GREEN** — rerun; all pass.

- [ ] **Step 5: Commit** — `git commit -am "feat(inspection): summary metrics and work list envelope"`

### Task 3: `work_detail()` with raw verbatim/reconstructed payloads

**Files:**
- Modify: `work_runtime/inspection.py`, `tests/test_inspection.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces: `work_detail(work_id) -> {"work": …, "evidence": […], "operations": […], "commands": […]}`; unknown id → `UNKNOWN_WORK`. `work` = list-item fields plus `plan_revision`, `document_revision` (decimal strings), `document_digest`, `waits` [{id, requirement_id, owner, status, deadline decimal string}], `cancellation` `{reason, requested_by}`|null, `requirements` [{id, rule_id, subject, applicability, fulfillment, explanation}], `state_raw` (exact `works.state` column text), `document_raw`/`plan_raw` (canonical reconstruction), `completion_raw` canonical|null. `evidence` items (PK order source, event_id): `source, event_id, kind, status, body_raw` (exact column), `data_raw` (canonical of `data`). `operations` items (id ASC): `id, business_key, capability, actor, status, dispatch_state, reason`(null absent), `attempts` [{id, status}], `external_id`(null absent), `document_digest, plan_revision, contract_revision` (decimal strings), `document_raw`, `body_raw` (exact column). `commands` items: `actor, id, decision, code`(null absent), `result_state_version`/`observed_state_version` (decimal string|null), `receipt_raw` (exact column), `blockers_raw` (canonical|null) — sorted by available decision version (`result` else `observed`, missing → -1) then actor, id.

- [ ] **Step 1: Write failing tests** — `test_work_detail_full_shape` (seeded succeeded work; assert every field above incl. `state_raw ==` the exact SQL column string, `document_raw` contains `10000000000000001` (huge-amount document), `completion_raw` has contract/document_digest/evidence, waits deadline is str), `test_work_detail_requirements_carry_id_and_rule_id`, `test_work_detail_commands_sorted_with_raws` (seed accepted + rejected receipts incl. blockers; assert ordering, `receipt_raw` byte-equal to column, `blockers_raw` == `canonical(blockers)`, null `code`/`result_state_version` on rejected), `test_work_detail_cancelled_work` (request_cancel + finalize_cancel with acknowledged op: `cancellation_requested` true pre-finalize; post-finalize `outcome` "cancelled", `completion_raw` contains cancellation/acknowledged_operations/operation_dispositions, `cancellation` {reason, requested_by}), `test_unicode_slash_quote_id_roundtrip` (work id `订单/"A"&1` created through real Runtime; list shows exact id; detail/events by exact id), `test_work_detail_unknown_raises`.

- [ ] **Step 2: RED** — run; AttributeError failures.

- [ ] **Step 3: Implement** — parameterized joins per work; canonical reconstruction via `from .policy import canonical`.

- [ ] **Step 4: GREEN** — rerun.

- [ ] **Step 5: Commit** — `git commit -am "feat(inspection): work detail with verbatim and reconstructed raw payloads"`

### Task 4: `events()` paging and reader failure modes

**Files:**
- Modify: `work_runtime/inspection.py`, `tests/test_inspection.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: `events(work_id, after=0, limit=100) -> {"events": [{seq, work_id, version, type, body_raw}], "next_after", "has_more"}` — `seq`/`version` decimal strings, `body_raw` exact column, ascending seq, keyset `seq > after`; `has_more` via limit+1 fetch; `next_after` = last returned seq, else `after` unchanged (returned as decimal string); unknown work → `UNKNOWN_WORK`; bad after/limit → `BAD_QUERY`; non-int `seq`/`version` rows → `INVALID_STORE`. `sqlite3.OperationalError` "database is locked" during a read → `GuiReaderError("DB_BUSY", …)` (reader connection `timeout=1.0`).

- [ ] **Step 1: Write failing tests** — `test_events_keyset_paging` (work with >200 events via repeated real `revise_plan` commands; page with limit 3 chaining `next_after`; ascending; `has_more` flips false at end; final `next_after` equals last seq), `test_events_default_and_validation` (defaults; after/limit bounds; unknown work), `test_events_version_must_be_integer` (SQL-inserted text version row → INVALID_STORE), `test_malformed_json_raises_invalid_store` (broken JSON in each of works/operations/evidence/commands/events in turn, each read surface raises INVALID_STORE, never silently skips), `test_nondict_state_raises`, `test_db_busy_on_exclusive_lock` (real store switched to `journal_mode=DELETE`, second connection `BEGIN EXCLUSIVE`, reader → DB_BUSY; release lock → read works again), `test_wal_reader_sees_commits_during_immediate_writer` (writer holds `BEGIN IMMEDIATE` on WAL store; reader still reads; new committed row visible), `test_full_read_pass_writes_nothing` (snapshot every table before/after summary+list+detail+events on multi-work store; identical), `test_read_only_file_permissions` (chmod 0o444 on store file, reader still reads).

- [ ] **Step 2: RED** — run; failures.

- [ ] **Step 3: Implement** events() + wrap read paths: `OperationalError` with "locked" → DB_BUSY; JSON/type guards per Interfaces.

- [ ] **Step 4: GREEN** — rerun.

- [ ] **Step 5: Commit** — `git commit -am "feat(inspection): keyset event paging, INVALID_STORE and DB_BUSY bounded failures"`

### Task 5: `make_ui_server` core routing, methods, headers, static assets

**Files:**
- Create: `work_runtime/ui_server.py`, `tests/test_ui_server.py`

**Interfaces:**
- Consumes: `ReadOnlyInspector` (constructed at factory time — startup validation).
- Produces: `make_ui_server(db_path, port=0) -> ThreadingHTTPServer` bound `("127.0.0.1", port)` with `daemon_threads = True`; raises `GuiReaderError` on invalid store (backs the frontend CLI's exit 2). Whitelist: GET/HEAD `/`, `/app.js`, `/app.css`, `/api/summary`, `/api/works`, `/api/work`, `/api/events`. Query rules: `/api/summary` none; `/api/works` {limit?, offset?}; `/api/work` exactly {id} nonempty; `/api/events` {work_id nonempty, after?, limit?}; manual split on `&`, decode `unquote_plus`, duplicate/unknown/empty-token/malformed keys or non-`^[0-9]+$` values or out-of-range → 400 `BAD_QUERY`; static routes reject any query. Responses JSON `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`; headers on every response: exact `Content-Length`, `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`, CSP `default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'none'`, `Content-Type: application/json; charset=utf-8` (API) or `text/html; charset=utf-8` / `text/javascript; charset=utf-8`… use `application/javascript; charset=utf-8` for `/app.js`, `text/css; charset=utf-8` for `/app.css`. HEAD mirrors GET status/headers (Content-Length of the GET body) with no body. Non-GET/HEAD → 405 `METHOD_NOT_ALLOWED` + `Allow: GET, HEAD`. Unknown path → 404 `UNKNOWN_ROUTE`. Static assets read dynamically from `Path(__file__).parent / "web"` at request time; missing → bounded 404 `UNKNOWN_ROUTE`; never create files. `GuiReaderError` → HTTP: `BAD_QUERY` 400, `UNKNOWN_WORK` 404, `DB_BUSY` 503, everything else (`DB_*`, `NOT_A_DATABASE`, `UNSUPPORTED_SCHEMA`, `INVALID_STORE`, `INTERNAL`) 500. Never emit CORS headers. `send_error` overridden to the JSON error envelope (no base-class HTML/raw-line logging).

- [ ] **Step 1: Write failing tests** in `tests/test_ui_server.py` — `_server()` helper: real seeded store, `make_ui_server(path, 0)`, `serve_forever` thread, cleanup `shutdown()`/`server_close()`; client via `http.client.HTTPConnection("127.0.0.1", port)`. Tests: `test_factory_binds_loopback_ephemeral` (`server_address[0] == "127.0.0.1"`, port > 0), `test_startup_invalid_store_raises` (missing DB → `GuiReaderError`), `test_api_routes_json_and_security_headers` (each API route 200; JSON parses; exact CSP/nosniff/no-store; `Content-Length == len(body)`; no `Access-Control-*`), `test_head_mirrors_get` (HEAD `/api/summary`: 200, headers equal GET's incl. Content-Length, empty body), `test_methods_rejected` (POST/PUT/DELETE/OPTIONS/PATCH on `/api/summary` → 405, `Allow: GET, HEAD`, code `METHOD_NOT_ALLOWED`), `test_unknown_routes_404` (`/api/nope`, `/foo`, `/app.js.bak`), `test_static_assets_bounded_404_without_files` (`/`, `/app.js`, `/app.css` → 404 bounded; assert `work_runtime/web` does not exist after), `test_query_validation_400` (unknown key; duplicate `limit=1&limit=2`; `limit=abc`, `limit=0`, `limit=201`, `offset=-1`, `after=-1`, `after=x`; missing/empty `id`; empty `work_id`; static route with query; empty query token `&&`), `test_unicode_work_id_via_query_encoding` (`quote`-encoded `订单/"A"&1` → exact id in response), `test_events_route_paging` (`after`/`limit` chain across HTTP), `test_shutdown_clean`.

- [ ] **Step 2: RED** — `python3 -m unittest tests.test_ui_server -v` import failures.

- [ ] **Step 3: Implement** `ui_server.py`: `_UiHandler(BaseHTTPRequestHandler)` (protocol_version "HTTP/1.1", overridden `log_request`/`log_message` sanitized, overridden `send_error`), route dispatch table, `_respond(status, payload_or_bytes, content_type)` writer applying HEAD suppression, `_parse_query(raw)` validator returning dict or raising `BAD_QUERY`, static loader, `make_ui_server`.

- [ ] **Step 4: GREEN** — rerun both test modules; also `python3 -m unittest tests.test_inspection -v` still green.

- [ ] **Step 5: Commit** — `git add work_runtime/ui_server.py tests/test_ui_server.py && git commit -m "feat(ui-server): loopback whitelist HTTP API over the read-only inspector"`

### Task 6: Host/Origin boundary, hostile targets, log hygiene

**Files:**
- Modify: `work_runtime/ui_server.py`, `tests/test_ui_server.py`

**Interfaces:**
- Consumes: Task 5 server.
- Produces: Host required exactly once (duplicates → 403), value `127.0.0.1` or `localhost` (case-insensitive) with port equal to the actual bound port (absent port means default 80; only matches when bound to 80) else 403 `BAD_HOST`. Origin optional; if present exactly once it must equal `http://127.0.0.1:<port>` or `http://localhost:<port>` (default-port-80 normalization; scheme must be `http`; no path/userinfo; `null` or foreign → 403 `BAD_ORIGIN`). Request target must be origin-form (starts with `/`; absolute/authority/asterisk forms → 404 `UNKNOWN_ROUTE`); percent-decoded traversal segments never resolve outside the whitelist (404). Access log lines contain only the method, the matched route label and the status — never the raw URL, body or control characters; error bodies never contain filesystem paths.

- [ ] **Step 1: Write failing tests** — `test_host_accepts_loopback_authority_with_actual_port` (`127.0.0.1:p` and `localhost:p` and `LOCALHOST:p` → 200), `test_host_rejected` (missing Host via raw socket; `evil.com:p`; `127.0.0.1:other-port`; `127.0.0.1` without port while bound ≠ 80; duplicate Host lines → all 403 `BAD_HOST`), `test_origin_accepted_when_matching` (`http://127.0.0.1:p`, `http://localhost:p` → 200; absent Origin → 200), `test_origin_rejected` (foreign `https://evil.com`, `http://null`, literal `null`, duplicate Origin, `http://127.0.0.1:p/` trailing slash → 403 `BAD_ORIGIN`), `test_absolute_form_target_rejected` (raw socket `GET http://127.0.0.1:p/api/summary HTTP/1.1` → 404 bounded, connection survives), `test_traversal_targets_rejected` (`/%2e%2e/`, `/..%2fapp.js`, `/app.js/../../etc/passwd` → 404), `test_error_bodies_have_no_paths` (hostile id/path error messages contain no `/`-joined filesystem paths, no store path), `test_access_log_never_echoes_raw_url` (capture `sys.stderr` during requests with hostile URLs/ids; assert raw URL and id absent, no control characters), `test_db_busy_maps_503` (DELETE-journal + `BEGIN EXCLUSIVE` while server runs → `/api/summary` 503 `DB_BUSY`; after release → 200), `test_invalid_store_maps_500` (corrupt `works.state` post-startup → `/api/works` 500 `INVALID_STORE` bounded).

- [ ] **Step 2: RED** — run; failures.

- [ ] **Step 3: Implement** `_check_host()`, `_check_origin()`, origin-form target guard before routing, sanitized logging, `GuiReaderError` → status mapping incl. 503/500.

- [ ] **Step 4: GREEN** — rerun full `python3 -m unittest discover -s tests` (expect baseline 512 + new tests, all OK).

- [ ] **Step 5: Commit** — `git commit -am "feat(ui-server): Host/Origin loopback boundary and hostile-target rejection"`

### Task 7: Public API docs, gates, settled-shape handoff, report

**Files:**
- Create: `docs/gui-api.md`, `.agents/notes/2026-10-14-S5-backend-report.md`
- Modify: none (code frozen after Task 6)

**Interfaces:**
- Consumes: Tasks 1–6 final shapes.
- Produces: `docs/gui-api.md` documenting `ReadOnlyInspector` signatures, every DTO with exact fields and decimal-string/precision rules, the full error-code → HTTP-status table, query validation rules, static-asset behavior, CSP/headers, no-CORS statement, and the three D25 distinctions (requirements vs historical admission blockers; current evidence eligibility vs historical decision validity; observation sampling time vs business event time). Report with immutable hashes, commands, evidence, limitations.

- [ ] **Step 1: Write `docs/gui-api.md`** from the implemented shapes (only local links that exist — `scripts/check_docs.py` must stay green).
- [ ] **Step 2: Run all four gates fresh** — `python3 scripts/check_docs.py`; `python3 -m unittest discover -s tests -v` (record count); `python3 -m work_runtime demo` (exit 0); `python3 -m compileall -q work_runtime tests scripts`. All must pass.
- [ ] **Step 3: Commit docs** — `git add docs/gui-api.md && git commit -m "docs(gui): public read-only API contract for the S5 GUI"`
- [ ] **Step 4: Send settled DTO shape to coordinator** through `orca orchestration send` (early handoff for the frontend owner; reference `docs/gui-api.md` and commit hash).
- [ ] **Step 5: Write `.agents/notes/2026-10-14-S5-backend-report.md`** — immutable tip hash, per-task commit hashes, RED/GREEN evidence lines, gate outputs, deviations from D25 (none expected), known limitations (WAL reader environment fact, static assets pending Task 2 owner, lock timeout 1.0 s). Commit: `git commit -am "docs(report): S5 read-only backend report and evidence"`.
- [ ] **Step 6: Check inbox, then exactly one `worker_done`** with task/dispatch ids and outcome; then idle.

## Self-Review

- Spec coverage: reader (Tasks 1–4), HTTP boundary (5–6), docs/handoff (7); D25 corrections (goal, requirement id, commands, counts.attempts, whole-column raws, decimal strings, INVALID_STORE/DB_BUSY) each land in a task; CLI/ui-demo/packaging deliberately excluded (frontend owner, Task 2 of supervision plan).
- Steps name exact tests/assertions; implementations leave bodies to the executor with pinned values only.
- Types consistent: `GuiReaderError(code, message)` everywhere; reader returns plain dicts consumed by the server.
- Review Focus lines each map to tests in Tasks 2–6.
- Proportion: plan is smaller than the code it describes.
