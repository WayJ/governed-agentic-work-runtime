# S5 GUI design review (independent read-only builder check)

Reviewer: s4-release-control worktree (WayJ/s4-release-control); design read in carrier
`sprint-s4-adoption` @ `bdfa1bc` (`docs/superpowers/specs/2026-10-14-s5-gui-design.md`). No S5
code/scaffolding started; S4 harness WIP untouched. All storage claims below were grounded
empirically against the **current carrier Runtime** (byte-identical to main's engine — S4
verified zero lifecycle diffs): probe scripts drove real commands/demos in `/tmp` and read the
resulting SQLite files with read-only URI connections. No product changes; no suite rerun
(docs-only dispatch).

## Verdict

**Implementable** as a stdlib-only read-only viewer. No blocking defects in the design. Four
small ratify-before-code choices (B1–B4, defaults suggested); everything else below is a
builder pin grounded in actual store shapes — including three wording corrections where the
design's summary names keys that do not exist in state (C1–C3), which the DTO must follow the
*implementation* on.

## Grounded storage truth (what inspection.py actually reads)

Schema (metadata `schema_version='1'`, WAL journal mode): `works(id, state)` with `state` =
canonical JSON; `commands(actor, id, fingerprint, work_id, receipt)` PK(actor,id); 
`evidence(source, event_id, work_id, fingerprint, body)`; `operations(id, business_key UNIQUE,
work_id, body)`; `events(seq INTEGER AUTOINCREMENT, work_id, version, type, body)`; `metadata`.

Actual work-state keys (observed): `id, status, state_version, contract{goal, policy_id,
policy_version, revision}, document, document_digest, document_revision, plan, plan_revision,
requirements[{id, rule_id, subject, applicability, fulfillment, explanation}], waits[{id,
deadline(epoch int), owner, requirement_id, status}], owner?, outcome?, completion?,
cancellation?{reason, requested_by}`. Optional keys are simply **absent** when never set.

- **C1 — there is no `closure` state key.** `finalize_cancel` writes the closure record into
  `work["completion"]` = `{cancellation, acknowledged_operations[{operation_id, external_id}],
  operation_dispositions[{operation_id, status, dispatch_state}]}` with a `WorkCancelled`
  event; a succeeded close writes `completion` = `{contract, document_digest, evidence[event
  ids], …}` with `WorkCompleted`. The GUI must read `completion` + `outcome`, not `closure`.
- **C2 — cancellation intent is `{reason, requested_by}`** (no actor/timestamp fields).
- **C3 — policy migration is not a state key**: it is the `PolicyMigrated` event body (the
  migrated work's binding changes live in `contract`). Render it from the event timeline.
- Operations body keys: `id, business_key, work_id, capability, actor, status, dispatch_state,
  reason, attempts[{id, status}], external_id?, document, document_digest, plan_revision,
  contract_revision`. Command receipts (persisted, per DB): `{command_id, decision,
  result_state_version}` and rejected variants with `code`/`blockers` — **admissions, not
  effects** (design already says so). Evidence body: `{id, source, event_id, kind, status,
  data}`. Event types observed: WorkCreated, ContractBound, PlanRevised, EvidenceEvaluated,
  OperationPrepared, AttemptStarted, OutcomeUnknown, OperationResolved, WorkCompleted,
  WorkCancelled, PolicyMigrated — the reader must **enumerate `SELECT DISTINCT type`
  dynamically**, never a hardcoded enum. Requirements carry the actual business `subject`
  (e.g. `ART-001`) and `rule_id`; no timestamps exist anywhere — ordering is `seq`/`version`
  only, as the design states.

Read-path verification: `sqlite3.connect("file:<percent-encoded-abs>?mode=ro", uri=True)` +
`PRAGMA query_only=ON` read committed WAL data **while a writer held `BEGIN IMMEDIATE`** —
live-writer read-only access works on this machine (reader needs the `-wal`/`-shm` readable;
this is an environment fact, not a guarantee). `works.state` bytes are `policy.canonical`
output (sort_keys, tight separators, `ensure_ascii=False`) — pass them through **verbatim**;
round-tripping through `json.dumps` with default settings is *not* byte-stable, and a
10000000000000001 amount survives exactly in the stored text (JS `Number` would render
10000000000000002 — hence raw text, never client-side `JSON.parse` of payload fields).

## Pinned reader/API contract (backend and frontend develop against this)

### inspection.py (pure reader)

- `open_read_only(path)`: reject missing/unreadable (`DB_NOT_FOUND`, `DB_NOT_READABLE`),
  non-SQLite (`NOT_A_DATABASE`), metadata `schema_version != '1'` (`UNSUPPORTED_SCHEMA`) —
  bounded `GuiReaderError(code, message)`; never create/initialize; one short
  `BEGIN DEFERRED` read transaction per call (snapshot consistency), then close.
- Methods: `summary()`, `list_works(limit, offset)`, `work_detail(work_id)` (joins evidence +
  operations for the work), `events(work_id, after, limit)`. All SQL parameterized; work ids
  are opaque TEXT values end-to-end.

### DTOs (exact; every `raw` field is the stored canonical JSON **string**, verbatim)

```
GET /api/summary → {"source": "<basename>", "schema_version": "1",
  "counts": {"works": N, "events": N, "operations": N, "evidence": N, "commands": N},
  "work_statuses": {status: N}, "closed_outcomes": {outcome: N},
  "operation_statuses": {status: N},   // incl. the uncertain dispatched/outcome_unknown count
  "evidence_statuses": {status: N}, "command_decisions": {decision: N},
  "event_types": {type: N}}            // dynamic keys, sorted
GET /api/works?limit=100&offset=0 → {"total": N, "limit": L, "offset": O, "works": [
  {"id", "status", "state_version": "s", "owner", "outcome",
   "contract": {policy_id, policy_version, revision: "s"} | null,
   "cancellation_requested": bool}]}   // ORDER BY id ASC (immutable key ⇒ stable offsets)
GET /api/work?id=… → {"work": {envelope fields as in /api/works item, plus
   "plan_revision", "document_revision", "document_digest",
   "waits": [{id, requirement_id, owner, status, deadline: "s"}],
   "cancellation": {reason, requested_by} | null,
   "requirements": [{rule_id, subject, applicability, fulfillment, explanation}],
   "document_raw": "<verbatim state document JSON>", "plan_raw": "<…>",
   "completion_raw": "<…>" | null},
  "evidence": [{source, event_id, kind, status, "data_raw"}],
  "operations": [{id, business_key, capability, actor, status, dispatch_state, reason,
   "attempts": [{id, status}], "external_id", "document_raw"}]}
GET /api/events?work_id=…&after=0&limit=100 → {"events": [
  {"seq": "s", "work_id", "version": "s", "type", "body_raw"}],   // ascending seq
  "next_after": "s", "has_more": bool}
```

- **Precision rule (B1 default)**: `seq`, `version`, `state_version`, `revision`, `deadline`,
  cursors and `after` are decimal **strings** in envelopes; tile counts are plain numbers.
  All `*_raw` fields are verbatim stored text rendered via `textContent` only — the frontend
  never `JSON.parse`s them (big-int documents survive exactly). No amount/currency inference.
- Pagination: `limit` 1..200 (default 100), `offset` ≥ 0; events keyset by `after` seq;
  `has_more` = fetched limit+1 rows. Invalid/duplicate/unknown query keys → 400.
- Error body everywhere: `{"error": {"code": "<CODE>", "message": "<bounded, basename only>"}}`
  with codes `DB_NOT_FOUND|DB_NOT_READABLE|NOT_A_DATABASE|UNSUPPORTED_SCHEMA|BAD_QUERY|
  UNKNOWN_WORK|UNKNOWN_ROUTE|METHOD_NOT_ALLOWED|BAD_HOST|BAD_ORIGIN|INTERNAL`; no stack
  traces, no file contents beyond the source basename.

### HTTP server (ui_server.py)

- `ThreadingHTTPServer` on `127.0.0.1` only, port default **0** (ephemeral; actual URL printed
  immediately). Routes exactly: `GET/HEAD /`, `/app.js`, `/app.css`, `/api/summary`,
  `/api/works`, `/api/work`, `/api/events`. Everything else 404; non-GET/HEAD 405 with
  `Allow: GET, HEAD`.
- Host must be exactly `127.0.0.1:<actual>` or `localhost:<actual>`; Origin, when present,
  must be the same local origin (`http://127.0.0.1:<port>` / `http://localhost:<port>`);
  foreign or `null` origin → 403; **no CORS headers ever**. Loopback is not authentication.
- Headers on every response: correct `Content-Length`, safe `Content-Type`, `X-Content-Type-
  Options: nosniff`, `Cache-Control: no-store`, CSP `default-src 'self'; frame-ancestors
  'none'`; static assets only from packaged `work_runtime/web/` (whitelist match, no path
  traversal, no directory listing, no external requests). Assets: vanilla HTML/CSS/JS, no
  inline script, no CDN, bilingual strings packaged with the app.

### CLI and seed fixture

- `work-runtime ui --db <existing> [--port N]` (and `python3 -m work_runtime ui …`): prints
  the bound URL, serves until interrupted; startup failures exit **2** (house convention).
- `ui-demo [--directory]` (B4 default): seeds ONE fresh temp folder + one expense-family DB
  (`runtime.sqlite` + FakeOA `oa.sqlite`) through **real commands/adapters only** — five
  works with distinct invoice ids: `wait-1` (registered wait → status waiting), `uncertain-1`
  (dispatch → outcome_unknown + needs_attention), `transfer-1` (owner transferred to a
  delegate), `succeed-1` (verified evidence → confirmed_succeeded + completed), `cancel-1`
  (request_cancel → finalize_cancel with acknowledged op → closed/cancelled) — then starts
  the same GUI server on that DB and prints inspect commands. Never deletes user data.
- Packaging: `pyproject` package-data gains `work_runtime/web/*` alongside S4's
  `data/sop/*.json`; installed module AND console entrypoint must serve and read correct
  records outside the checkout (verifier extends the S4 pattern: real HTTP fetches of
  HTML/JS/CSS/API, read-only table-snapshot equality before/after, clean subprocess shutdown).

## Ratify-before-code choices (defaults suggested)

- **B1 — envelope integer encoding**: default above (decimal strings for seq/version/
  revision/deadline/cursors; numbers only for small counts). Alternative: everything strings.
- **B2 — payload rendering**: default **verbatim stored text** server-side, `textContent`
  client-side (no server re-indent, no client parse). "Pretty" rendering would force a parse
  somewhere and re-opens the precision/formatting question.
- **B3 — events scope**: default work-scoped `/api/events` only (no global event list);
  global demand is served by `/api/summary.event_types` counts.
- **B4 — ui-demo shape**: default the five-work single-DB fixture above (work ids and
  distinct invoice ids pinned); alternative is reusing the three intervention stores, which
  would not exercise one-directory browsing.

## Boundaries (unchanged, agreed)

Read-only local tool; no write API, no tenant/production auth, no engine/Policy changes, no
new dependencies/CDN/framework, no CORS, no invented timestamps/metrics (none exist in the
store to show); loopback binding is convenience, not a security claim. Design's stdlib
references (http.server, sqlite3 URI mode=ro) are the right primary sources and are already
linked in the spec.
