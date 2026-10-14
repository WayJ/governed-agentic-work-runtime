# GUI read-only API contract

The S5 GUI backend exposes **existing** work stores for local inspection only.
`work_runtime.inspection` reads a schema-1 SQLite store through `mode=ro`/
`query_only` connections — it never creates, initializes, migrates or writes a
store, and it never constructs a `Runtime` or evaluates policy. Binding to
loopback is convenience for a local tool; it is **not** authentication of any
principal, and this module makes no production-service claim. Design source:
[D25](superpowers/specs/2026-10-14-s5-gui-design.md); boundaries shared with
[runtime-boundaries.md](runtime-boundaries.md).

## Reader — `work_runtime.inspection`

```python
ReadOnlyInspector(path)                      # validates an existing schema-1 store
  .summary()                                 # counts and dynamic status maps
  .list_works(limit=100, offset=0)           # stable id-ascending work envelopes
  .work_detail(work_id)                      # one work plus its records
  .events(work_id, after=0, limit=100)       # ascending keyset-paged events

GuiReaderError(code, message)                # bounded failure; .code and .message
```

The constructor rejects, without creating or touching any file:
`DB_NOT_FOUND` (absent path), `DB_NOT_READABLE` (unreadable file), `NOT_A_DATABASE`
(not a SQLite image), `UNSUPPORTED_SCHEMA` (no readable schema version 1).
Every method opens one short `BEGIN DEFERRED` read transaction on a fresh
`mode=ro` connection with `PRAGMA query_only=ON` and closes it. A writer-held
exclusive lock observed past the read timeout raises `DB_BUSY`; malformed stored
JSON or record types raise `INVALID_STORE` — never a silently skipped record and
never a fabricated metric. Reading a WAL store during a concurrent writer's open
`BEGIN IMMEDIATE` transaction shows committed data (an environment fact of this
machine's SQLite, not a distributed claim).

### Precision rules

`seq`, `version`, `state_version`, `revision` (contract/plan/document/operation),
`deadline` and the event cursor `after`/`next_after` are **decimal strings**;
small counts are plain numbers. Whole stored JSON columns (`state_raw`,
`body_raw`, `receipt_raw`) are the **exact stored text**; nested payload fields
(`document_raw`, `plan_raw`, `completion_raw`, `data_raw`, `blockers_raw`) are
**reconstructed** canonical JSON (sorted keys, tight separators, exact Python
integers) — honestly not byte-identical subfragments, and guaranteed to preserve
integers beyond the JavaScript safe range, such as `10000000000000001`. No
amount/currency inference is performed.

## HTTP server — `work_runtime.ui_server`

```python
make_ui_server(db_path, port=0)   # loopback ThreadingHTTPServer; port 0 = ephemeral
```

Binds `127.0.0.1` only. Construction validates the store through
`ReadOnlyInspector` and raises `GuiReaderError` on failure — the `ui` CLI maps
that to startup exit 2. Route whitelist, nothing else:

| Route | Method | Query |
|---|---|---|
| `/` | GET/HEAD | none |
| `/app.js`, `/app.css` | GET/HEAD | none |
| `/api/summary` | GET/HEAD | none |
| `/api/works` | GET/HEAD | `limit` (1..200, default 100), `offset` (≥ 0, default 0) |
| `/api/work` | GET/HEAD | `id` (required, nonempty) |
| `/api/events` | GET/HEAD | `work_id` (required, nonempty), `after` (≥ 0, default 0), `limit` (1..200, default 100) |

- **Query validation**: split on `&`, percent-decoded with `+` as space; unknown,
  duplicate or malformed keys, empty tokens, or non-ASCII-decimal values answer
  `400 BAD_QUERY`. Static routes accept no query string at all.
- **Methods**: GET and HEAD only; every other method answers `405` with
  `Allow: GET, HEAD`. `HEAD` mirrors GET's status and headers (including
  `Content-Length` of the body GET would send) and sends no body.
- **Host**: exactly one `Host` header whose authority is `127.0.0.1` or
  `localhost` (case-insensitive) with the actual bound port (an authority
  without a port means the HTTP default 80). Anything else — foreign host,
  wrong port, duplicate, missing — answers `403 BAD_HOST`.
- **Origin**: optional; when present, exactly one, and it must equal the
  request's **own** local origin — the same alias (`127.0.0.1` or `localhost`)
  and the same port the validated `Host` names (default-port-80 normalization
  applies to both sides; scheme must be `http`; no path, userinfo, query or
  fragment). The *other* loopback alias with the right port is still a
  different origin: foreign, `null`, duplicated, cross-alias or malformed
  origins all answer `403 BAD_ORIGIN`.
- **Targets**: origin-form only. Absolute-form, authority-form and asterisk
  targets and any path outside the whitelist (including percent-encoded
  traversal) answer `404 UNKNOWN_ROUTE`. There is no directory listing and no
  generic file serving.
- **CORS**: none. No `Access-Control-*` header is ever emitted.
- **Every response** carries an accurate `Content-Length`,
  `X-Content-Type-Options: nosniff`, `Cache-Control: no-store` and
  `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src
  'self'; connect-src 'self'; base-uri 'none'; object-src 'none';
  frame-ancestors 'none'; form-action 'none'`. API bodies are
  `application/json; charset=utf-8`.
- **Errors** are always `{"error": {"code": "...", "message": "..."}}` — bounded,
  no stack traces, no file contents, no raw paths or request echoes. Access logs
  record only the method and status, never the raw URL or body. The only store
  detail any payload reveals is the source basename inside `summary().source`.

| `code` | HTTP | meaning |
|---|---|---|
| `BAD_QUERY` | 400 | malformed/duplicate/unknown/out-of-range query or request |
| `BAD_HOST` | 403 | Host authority is not this loopback server with its port |
| `BAD_ORIGIN` | 403 | Origin present but not this local origin |
| `UNKNOWN_ROUTE` | 404 | path (or static asset) outside the whitelist |
| `UNKNOWN_WORK` | 404 | no work with the given id |
| `METHOD_NOT_ALLOWED` | 405 | not GET/HEAD (`Allow: GET, HEAD`) |
| `DB_BUSY` | 503 | store locked by a writer past the read timeout |
| `DB_NOT_FOUND`, `DB_NOT_READABLE`, `NOT_A_DATABASE`, `UNSUPPORTED_SCHEMA` | 500 at request time | store unavailable or unsupported after startup (startup raises instead) |
| `INVALID_STORE`, `INTERNAL` | 500 | malformed stored records / unexpected bounded failure |

Static assets (`/`, `/app.js`, `/app.css`) are frontend-owned and read at request
time from the packaged `work_runtime/web/` directory. Until that owner assembles
them, the bounded answer is `404 UNKNOWN_ROUTE` with message "static asset not
available"; the backend never creates placeholder files.

## DTOs

`GET /api/summary` →

```json
{"source": "<basename>", "schema_version": "1",
 "counts": {"works": 0, "events": 0, "operations": 0, "evidence": 0,
            "commands": 0, "attempts": 0},
 "work_statuses": {}, "closed_outcomes": {}, "operation_statuses": {},
 "evidence_statuses": {}, "command_decisions": {}, "event_types": {}}
```

`counts.attempts` is the number of stored operation attempt entries. Every
status map counts **stored records** with dynamically discovered, sorted keys —
no hardcoded enums, no invented rates, durations or model activity. `closed_outcomes`
counts outcomes among closed works only.

`GET /api/works` → `{"total": n, "limit": n, "offset": n, "works": [...]}` with
each item (id-ascending, stable for immutable ids):

```json
{"id": "...", "status": "...", "state_version": "12", "owner": "agent",
 "outcome": null, "cancellation_requested": false,
 "contract": {"policy_id": "...", "policy_version": "...", "goal": "...",
              "revision": "3"}}
```

`owner` is `null` for legacy stores that never stored one; `contract` is `null`
before binding; `outcome` is `null` until closed.

`GET /api/work?id=...` → `{"work": {}, "evidence": [], "operations": [],
"commands": [], "revoked_evidence": [], "completion_revoked_evidence_ids":
[]}`. `work` extends the list item with `plan_revision`,
`document_revision` (decimal strings), `document_digest`, `waits`
(`[{id, requirement_id, owner, status, deadline}]`, deadline a decimal string),
`cancellation` (`{reason, requested_by}` or `null`), `requirements`
(`[{id, rule_id, subject, applicability, fulfillment, explanation}]`), plus the
raw payloads `state_raw` (exact column), `document_raw`, `plan_raw`,
`completion_raw` (reconstructed; `completion_raw` is `null` until closure —
closure **is** `completion` + `outcome`, there is no separate closure key).
`evidence` items are `{id, source, event_id, kind, status, body_raw,
data_raw}` in (source, event_id) order: `id` is the stored record id as a
nonempty string, or `null` when the stored body carries no valid string id —
the raw text always remains available and nothing is fabricated.
`operations` items are `{id, business_key, capability,
actor, status, dispatch_state, reason, attempts: [{id, status}], external_id,
document_digest, plan_revision, contract_revision, document_raw, body_raw}`
(id-ascending); `reason`/`external_id` are `null` when never stored. `commands`
items are `{actor, id, decision, code, result_state_version,
observed_state_version, receipt_raw, blockers_raw}` sorted by the receipt's
available decision version (`result_state_version`, else
`observed_state_version`, else last) then actor and id — a stable order that
implies no wall-clock claim. Persisted receipts are **admissions, not external
effects**; fresh unpersisted replay-denials are not in the store, and no command
kind, creation actor or timestamp is invented.

The two revocation fields (S8, [D37](superpowers/specs/2026-10-14-s8-evidence-revocation-design.md))
are **derived inside the same read-only snapshot** as the rest of the payload —
never persisted annotations:

- `revoked_evidence`: `{id, source, event_id, kind, status}` for every stored
  proof row of this work whose status is `revoked`, in the same
  (source, event_id) order as `evidence`; `id` follows the same
  valid-string-or-`null` rule.
- `completion_revoked_evidence_ids`: the intersection of the **valid string**
  entries of `completion.evidence` with the valid string ids of the revoked
  rows above — stored citation order, deduplicated. A successful completion
  cites verified proof ids; a cancellation completion records acknowledged
  operations instead and never has citations, so this list is empty there and
  citations are never invented. Ids stay exact strings; no numeric coercion.

These fields report **current** stored status. They say nothing about the
historical completion decision, which remains byte-stable in `completion_raw`;
a viewer must keep the two distinctions separate (the reader never re-parses
`completion_raw` to derive the count).

`GET /api/events?work_id=...` →

```json
{"events": [{"seq": "41", "work_id": "...", "version": "7", "type": "...",
             "body_raw": "<exact column>"}],
 "next_after": "41", "has_more": true}
```

Ascending `seq`, keyset-paged by `after` (fetched with limit+1 to compute
`has_more`); `next_after` is the last returned seq, or the unchanged `after`
cursor when the page is empty. Event types are discovered dynamically
(`PolicyMigrated` and every other type appear only if stored).

## Reading distinctions this API keeps

- **Requirements are not admission blockers.** `work.requirements` is the
  current contract evaluation (applicability/fulfillment per rule). A goal-rule
  like E08 being unsatisfied is not automatically an action blocker; the
  *historical* admission decisions live in `commands` receipts with their own
  recorded blockers. The two are rendered from separate fields and never merged.
- **Evidence status is not decision validity.** `evidence[].status` says whether
  a proof currently verifies under the current contract's sources; it says
  nothing about whether an old decision was valid when made — that is only in
  the persisted receipts.
- **Sampling time is not event time.** The store records no wall-clock
  timestamps anywhere; ordering is `seq`/`version` only. Any refresh time a
  viewer shows is its own sampling moment, never a business-event time.

## Ownership

Backend-owned surfaces: `work_runtime/inspection.py`,
`work_runtime/ui_server.py`, `tests/test_inspection.py`,
`tests/test_ui_server.py`, this document. Web assets, `ui`/`ui-demo` CLI,
packaging and installation verification are owned by the frontend slice and are
not altered here.
