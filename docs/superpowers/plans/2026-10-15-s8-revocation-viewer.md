# S8 Revoked-Evidence Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Coordinator owns dispatch; no extra workers.

**Goal:** D37 read-only derived revocation fields plus a bilingual closed-work correction notice in the operations viewer, with real-browser RED/GREEN and zero writes.

**Architecture:** `ReadOnlyInspector.work_detail` derives `evidence[].id`, top-level `revoked_evidence` and `completion_revoked_evidence_ids` inside its existing short read-only snapshot (no schema, no persistence, no Runtime). The vanilla frontend renders a neutral bilingual notice for closed works with revoked evidence from those DTO fields only — never parsing `*_raw` — plus a revoked chip on existing measured error tokens. Docs and browser automation follow the established S5–S7 patterns.

**Tech Stack:** Python>=3.9 stdlib/unittest, SQLite read-only connections, vanilla offline JS/CSS, actual Chrome via the S7 CDP client (`docs/superpowers/acceptances/assets/S7/s7_gui_audit.py`, stdlib-only).

**Spec:** [Ratified design D37](../specs/2026-10-14-s8-evidence-revocation-design.md) · [S8 sprint](../sprints/2026-10-14-S8-plan.md) · [S8 execution plan Task4](2026-10-14-s8-revocation.md) · [core integration review](../../../.agents/notes/2026-10-14-S8-core-integration-review.md) · [DESIGN.md](../../../DESIGN.md).

## Global Constraints

- Exact D37 fields: `evidence[].id` (valid string else `null`, raw retained); top-level `revoked_evidence` entries `{id, source, event_id, kind, status}`; top-level `completion_revoked_evidence_ids` = intersection of valid string `completion.evidence` citations with valid string revoked ids, same snapshot.
- Cancellation completions record acknowledged operations — never fabricate proof citations.
- Preserve raw completion/payload bytes and exact huge integers; the frontend NEVER `JSON.parse`s any `*_raw` field.
- No persisted annotations, no Runtime construction/evaluation, no write endpoint, no schema/policy changes, no summary tile, no lifecycle controls, no timeline pastels, no imaginary lifecycle stages.
- Ownership: `work_runtime/inspection.py`, `work_runtime/web/app.js`, `work_runtime/web/app.css`, viewer reader/UI/API tests, `docs/gui.md`, `docs/gui-api.md`, this plan and the report. NOT: runtime.py, policies, adapters, cli.py, revocation_demo.py, verify_install.py, README, core/demo docs, ledgers.
- DESIGN.md tokens only (warm cream/ink, white cards, hairlines, no shadows, 4px scale, 8px controls/12px cards, local fonts/CJK fallback); keyboard/visible focus/loading/empty/error/disconnected/polling states preserved; meaning stays in text independent of color.
- Real stores built through public Runtime commands only (no direct SQL to fake business state; direct SQL corruption is allowed only for malformed-store reader robustness tests, per existing `test_inspection.py` pattern).

## Review Focus

- Malformed stores: non-string/missing evidence `id`, non-list or non-string `completion.evidence` must degrade to `null`/skipped — never crash, never fabricate, raw always retained.
- Stale/other-surface regressions: `summary`, `list_works`, `events` shapes unchanged; all-table byte equality after every read; works with no revoked evidence gain empty arrays, not new keys-that-vary.
- Notice discipline: shown only for closed works with non-empty `revoked_evidence`; count only when `completion_revoked_evidence_ids` is a non-empty array; open works with revoked evidence and clean closed works show nothing.
- Interaction regressions: polling re-render must keep the notice and not steal focus; disconnect/recovery banner unaffected; tab/keyboard navigation still works with two new buttons in the detail DOM.
- Bilingual exactness: EN and ZH strings both distinguish historical closure (unchanged) from current proof status (corrected); ZH display tracking stays zero.

---

### Task 1: Reader derived fields (TDD)

**Files:**
- Modify: `work_runtime/inspection.py` (`work_detail` only)
- Test: `tests/test_revocation_viewer.py` (new)

**Interfaces:**
- Consumes: schema-1 stores built with the real `Runtime` public API (`demo` helpers + `revoke_evidence` command, per `tests/test_evidence_revocation.py` grants pattern).
- Produces: `work_detail()` returns `{"work": ..., "evidence": [...], "operations": ..., "commands": ..., "revoked_evidence": [{id, source, event_id, kind, status}], "completion_revoked_evidence_ids": [str]}`; each evidence item gains `"id"` (nonempty string or `None`) while keeping `body_raw`/`data_raw` unchanged.

- [ ] **Step 1: Write the failing tests** — `tests/test_revocation_viewer.py`, `RevocationViewerTests` (fixture: temp store, `revocation_grants()` clone of the core test grants, `succeeded_store`/`cancelled_store`/unbound fixtures driven through real commands):

  - `test_closed_succeeded_revoked_cited_evidence_derived`: revoke the cited approval proof after `request_completion` accepted; assert `evidence[].id` equals the stored body ids (compare with `json.loads(body_raw)["id"]`), `revoked_evidence == [{"id": approval_id, "source": "finance", "event_id": ..., "kind": "approval", "status": "revoked"}]`, `completion_revoked_evidence_ids == [approval_id]`, and `completion_raw` still equals the canonical stored completion.
  - `test_closed_cancelled_revoked_evidence_has_no_citations`: cancelled store (acknowledged effect) + revoke → `revoked_evidence` non-empty, `completion_revoked_evidence_ids == []` (acknowledged operations, no invented citations).
  - `test_unbound_closed_work_revoked_derivation`: unbound work → record/verify approval → `request_cancel` → `finalize_cancel` (empty ack) → revoke → derived fields present, completion citations empty, `work.status == "closed"`.
  - `test_open_work_with_revoked_evidence_lists_without_citations`: revoke on an active work → `revoked_evidence` lists it, citations empty, `evidence[].id` present.
  - `test_clean_works_have_empty_derived_arrays`: succeeded store without revocation → `revoked_evidence == []`, `completion_revoked_evidence_ids == []`, every evidence item still has an `id` key (valid strings).
  - `test_malformed_evidence_id_degrades_to_null`: direct-SQL corrupt one evidence body id to `7` and another to absent → `"id" is None` for both, `body_raw` retained verbatim, a corrupted revoked row appears in `revoked_evidence` with `id: None` and is excluded from citations.
  - `test_malformed_completion_citations_ignored`: direct-SQL set `completion.evidence` to `[valid_revoked_id, 7, null, "", valid_revoked_id]` → citations `[valid_revoked_id]` (valid strings only, order preserved, deduped); also a non-list `completion.evidence` variant → `[]`, no raise.
  - `test_exact_raw_and_huge_integers_survive`: succeeded store with `amount=10000000000000001` + revoke → `"10000000000000001"` in `document_raw`/`state_raw`, revoked proof `data_raw` equals its pre-revocation canonical data (identity preserved), `completion_raw` exact.
  - `test_full_read_pass_writes_nothing`: revoked-closed store + clean store in one file; snapshot all six tables; run `summary`, `list_works`, `work_detail` per work, `events` per work; assert byte-identical snapshots.

- [ ] **Step 2: Run to verify RED**

  Run: `python3 -m unittest tests.test_revocation_viewer -v`
  Expected: FAIL/ERROR on missing keys (`KeyError: 'revoked_evidence'`, `evidence[0]['id']`).

- [ ] **Step 3: Implement minimally in `work_detail`**

  Module helper `_valid_id(value)` → `value if type(value) is str and value else None`; in the existing evidence loop add `"id": _valid_id(proof.get("id"))` to each item and append `{id, source, event_id, kind, status}` to a local `revoked_evidence` list when `proof.get("status") == "revoked"`; after the loop compute `completion_revoked_evidence_ids` from `state["completion"]["evidence"]` (only when dict/list; valid strings; citation order; dedup) intersected with revoked valid ids collected in the same transaction; return both top-level. No other method touched.

- [ ] **Step 4: Run to verify GREEN**

  Run: `python3 -m unittest tests.test_revocation_viewer tests.test_inspection -v`
  Expected: PASS (both files).

- [ ] **Step 5: Commit** `git add work_runtime/inspection.py tests/test_revocation_viewer.py && git commit -m "feat: derive revoked-evidence reader fields in work_detail (D37)"`

### Task 2: HTTP API pass-through pin

**Files:**
- Test: `tests/test_revocation_viewer.py` (append `ApiWorkDetailTests`)

**Interfaces:** Consumes `work_runtime.ui_server.make_ui_server` (lazy import, same pattern as `tests/test_ui_server.py`); no server change — the envelope is generic JSON.

- [ ] **Step 1: Write the failing-capable test then confirm it passes with Task 1 code**

  `test_api_work_returns_derived_revocation_fields`: real revoked-closed store; `GET /api/work?id=...` over a loopback ephemeral server → 200, `revoked_evidence`/`completion_revoked_evidence_ids`/`evidence[].id` present with correct values and JSON types (strings/arrays, `id` string), plus one malformed-id corruption variant asserting `id: null` over HTTP.

- [ ] **Step 2: Run** `python3 -m unittest tests.test_revocation_viewer -v` → PASS.

- [ ] **Step 3: Commit** `git commit -m "test: pin /api/work revoked-evidence fields over HTTP"` (append to Task 1 files as one commit if still uncommitted work).

### Task 3: Browser RED → notice/chip implementation → GREEN

**Files:**
- Create: `.agents/notes/2026-10-15-S8-viewer-browser.py` (scoped automation, imports the S7 CDP client; not in unittest discovery)
- Modify: `work_runtime/web/app.js`, `work_runtime/web/app.css`

**Interfaces:** Consumes Task 1 DTO keys `revoked_evidence`, `completion_revoked_evidence_ids`, `evidence[].id` (never `*_raw`). Produces `.revoked-notice` block under the detail head (after the cancellation banner), i18n keys `revoke.*`, CSS `.chip-st-revoked` on existing error tokens.

- [ ] **Step 1: Write the browser script** — seed one real store through public commands with five works: `succeed-closed` (cited approval revoked), `cancel-closed` (acknowledged effect + revoked proof), `unbound-closed` (D-1 family, revoked), `open-revoked` (active, revoked — no notice), `clean-closed` (no revocation — no notice). Serve it with `make_ui_server` on an ephemeral loopback port; drive actual Chrome via the S7 CDP client; snapshot all tables before/after the whole session. Checks (phase-parameterized):
  - detail readiness awaited per work (`wait_detail`), notice present on the three closed-revoked works with citation count only on `succeed-closed` (equals derived ids), absent on `open-revoked`/`clean-closed`;
  - RED phase: assert the notice is ABSENT on closed-revoked works (demonstrates the missing feature; exit 0 = RED shown) and record the neutral revoked chip;
  - GREEN phase: notice text (EN), ZH toggle strings, citation line lists exact ids as text, revoked chip computed styles on error tokens, notice computed styles (tokens, radius, hairline) + measured contrast ≥4.5:1 for notice text and chip text, screenshots at 1440×900, 390×844 and 320×700 (notice work + one no-notice work), keyboard path (work list → Enter → Tab to notice buttons → Enter switches to Evidence/Events tab), polling survival (≥5 s re-render keeps notice and list focus), disconnect banner on server shutdown + recovery on restart, and all-table zero-write equality.
- [ ] **Step 2: Run RED** `python3 .agents/notes/2026-10-15-S8-viewer-browser.py --phase red --out <tmpdir>` → notice confirmed missing (RED recorded: checks expecting absence pass; report quotes it).
- [ ] **Step 3: Implement app.js/app.css minimally**

  `renderRevokedNotice(payload)` (returns `null` unless `work.status === "closed"` and `Array.isArray(revoked_evidence) && revoked_evidence.length`); title/body text keys EN+ZH distinguishing historical closure/outcome (unchanged) from current proof status (corrected); citation line only when `completion_revoked_evidence_ids` is a non-empty array (count + exact id strings via textContent); two navigation buttons activating the `evidence`/`events` tabs; insert after the cancellation banner in `renderDetail`. CSS: `.revoked-notice*` on cream-soft/ink/hairline tokens (12px card radius) and `.chip-st-revoked` added to the existing error-token chip selector. No `innerHTML`, no parsing of raw strings, no new endpoints.

- [ ] **Step 4: Run GREEN** `--phase green --out <tmpdir>` → all checks pass, screenshots + computed styles + contrast + zero-write evidence written to the out dir.
- [ ] **Step 5: Commit** `git add work_runtime/web/app.js work_runtime/web/app.css .agents/notes/2026-10-15-S8-viewer-browser.py && git commit -m "feat: bilingual closed-work revoked-evidence notice and revoked chip (D37)"`

### Task 4: Docs

**Files:**
- Modify: `docs/gui-api.md`, `docs/gui.md`

- [ ] **Step 1:** gui-api.md — extend the `/api/work` DTO paragraph with `evidence[].id` (valid string or `null`, raw retained), `revoked_evidence` entries and `completion_revoked_evidence_ids` semantics (same-snapshot derivation; intersection of valid-string citations; cancellation completions carry acknowledged operations, so no citations are invented); note ids are exact strings, no numeric coercion.
- [ ] **Step 2:** gui.md — "Reading the screen": the closed-work revoked-evidence notice (historical vs current distinction, citation count only when derived); "What the GUI deliberately does not do": the count comes from the derived API field, `completion_raw` is never parsed. Refresh the Updated line to S8.
- [ ] **Step 3: Verify links** `python3 scripts/check_docs.py` → 0 broken; Commit `docs: D37 reader DTO and viewer notice`.

### Task 5: Gates, report, worker_done

- [ ] Five AGENTS gates: `python3 scripts/check_docs.py`; `python3 -m unittest discover -s tests -v`; `python3 -m work_runtime demo`; `python3 -m compileall -q work_runtime tests scripts`; `python3 scripts/check_site.py` — all green with exact counts/skips recorded.
- [ ] Write `.agents/notes/2026-10-15-S8-viewer-report.md`: commands, RED/GREEN evidence (reader + browser), screenshots list, computed contrast, zero-write proof, limits (no whole-S8 release claim). Commit.
- [ ] `orca orchestration send --type worker_done` with hashes/counts/risks; then idle.

## Self-review

D37 fields map to Task 1 (exact shapes, malformed degradation, same-snapshot semantics), cancellation non-fabrication to Tasks 1–2, notice discipline and bilingual current/historical distinction to Task 3, raw/huge exactness and zero writes to Tasks 1 and 3, DESIGN token use to Task 3, docs to Task 4. No task touches forbidden ownership; UI changes carry actual-browser RED/GREEN; no release claim beyond this slice.
