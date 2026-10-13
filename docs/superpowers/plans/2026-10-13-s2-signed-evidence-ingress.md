# S2 Signed Evidence Ingress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]` syntax for tracking.

**Goal:** Add an HMAC-SHA256 authenticated ingress (`work_runtime/ingress.py`) that converts strict signed envelopes into existing `record_evidence` commands, rejecting all forgery classes before any Runtime write.

**Architecture:** One new module with two public surfaces — a trusted-side signer `sign_evidence(secret, message)` and an untrusted-side `SignedEvidenceGateway.record(envelope)` that validates schema, authenticates the source, checks freshness, refuses the reserved `accepted` kind, and only then calls `runtime.command(kind="record_evidence")` forwarding a detached JSON-native snapshot of exactly what was verified. No Runtime/policy/adapter changes; one new test file; one new boundary document.

**Tech Stack:** Python >= 3.9 standard library only (`hmac`, `hashlib`, `json`, `time`), `unittest`, real SQLite Runtime in tests.

**Spec:** `docs/superpowers/specs/2026-10-13-s2-trusted-boundaries.md` Foundation B (local copy; carrier D8 addendum at 32de295 takes precedence where underspecified), `docs/superpowers/sprints/2026-10-13-S2-plan.md` wave 1, `docs/RFC-003-runtime-protocol.md` §4–5 (record_evidence acceptance ≠ verification). Coordinator dispatch + mail 2026-10-13 (D8 decisions, detached verified snapshot, plan proportion).

## Global Constraints

- Python 3.9.6 on this machine: no 3.10+ syntax; `typing.Dict`/`Callable` spellings.
- Zero runtime dependencies; standard-library `unittest` only.
- Ownership: `work_runtime/ingress.py`, `tests/test_ingress.py`, `docs/signed-evidence.md`, this plan and the evidence report in `.agents/notes/`. Do NOT touch Runtime/policy/adapters/publishing/README/ledgers/`__init__.py` (tests import `work_runtime.ingress` directly).
- Baseline: 63 S1 tests green before and after; suite green except during observed RED steps.
- No merge, no push; commit owned paths only; `worker_done` after final commit.
- No secrets in code/docs/tests except clearly-labeled non-secret known-answer vectors; no secret persistence/printing anywhere.
- Record RED/GREEN command output verbatim in the evidence report.
- Coordinator mail is read before each new file, after test runs, and before `worker_done`.

## Pinned contract (decisions the implementer cannot choose)

- Signed fields, exactly: `source, command_id, work_id, event_id, kind, data, issued_at`; envelope adds exactly `signature`. No actor/alias field.
- Canonical form: `work_runtime.policy.canonical` (sorted-key compact JSON, `ensure_ascii=False`, `allow_nan=False`), UTF-8 bytes; HMAC-SHA256, lowercase 64-hex signature, `hmac.compare_digest`.
- JSON-native strictness (B1): data allows only `dict`(string keys)/`list`/`str`/`bool`/`int`/finite `float`/`None` recursively; tuple→array and int-key→string coercions, NaN/±Inf, non-str dict keys are rejected. `issued_at` is `type(...) is int` (bool rejected). Identity fields are nonempty `str`. `signature` is a `str` of exactly 64 chars from `[0-9a-f]`.
- `sign_evidence(secret: bytes, message: dict) -> dict`: validates secret (`bytes`, `len >= 32`) and message (above), raises `ValueError` on any invalid input/key/canonicalization (UnicodeEncodeError from lone surrogates is a ValueError and propagates as such), never mutates input, and returns its own detached JSON-native copy plus `signature`.
- `SignedEvidenceGateway(runtime, keys: Dict[str, bytes], max_age: int = 300, clock: Callable = time.time)`; constructor validates: `keys` a `dict` of nonempty `str` → distinct `bytes` values each `>= 32` bytes (duplicate key material across sources → `ValueError`), copied at construction; `max_age` a nonnegative `int` (bool rejected); `clock` callable. No default/global secret ever.
- `record(envelope: dict) -> dict` check order: (1) shape/type/JSON-native/canonicalization (incl. caught `TypeError`/`ValueError`/`RecursionError`) → `{"decision": "rejected", "code": "EVIDENCE_ENVELOPE_INVALID"}`; (2) known source → else `EVIDENCE_AUTHENTICATION_FAILED`; (3) signature over the canonical snapshot → `EVIDENCE_AUTHENTICATION_FAILED`; (4) `abs(clock() - issued_at) <= max_age` → else `EVIDENCE_EXPIRED`; (5) reserved `kind == "accepted"` → `EVIDENCE_KIND_UNSUPPORTED` (M1); (6) `runtime.command(actor=snapshot source, command_id, work_id, kind="record_evidence", payload={event_id, kind, data}, expected_version=None)`.
- Rejection receipts are exactly `{"decision": "rejected", "code": ...}` — no secret, signature, or candidate body. Authentication/schema/freshness/reserved failures leave all Runtime tables unchanged. Authenticated business rejections (grant refusal, command/event conflicts) keep Runtime receipt persistence.
- Verified-snapshot forwarding (coordinator mail): canonicalize once, HMAC those exact bytes, `json.loads` them, and build the `runtime.command` payload only from that detached snapshot; the gateway retains no mutable alias of the input envelope or the caller's key map.
- Replay (M2): exact replay inside freshness returns the stored receipt; timestamp refresh under a new command id resolves to the same durable `(source, event_id)` evidence identity; event-id reuse across work ids → `SOURCE_EVENT_CONFLICT`; expired replay is refused before Runtime.

## Review Focus

1. Non-JSON-native coercions (tuple values, int dict keys, NaN/Inf) canonicalize ambiguously and would let two different payloads share a signature → rejected as `EVIDENCE_ENVELOPE_INVALID` even before signature checks (Task 3 `test_non_json_native_or_nonfinite_data_is_invalid`, `test_schema_precedes_authentication`).
2. A key holder forging Runtime-written completion evidence via `kind='accepted'` → `EVIDENCE_KIND_UNSUPPORTED` after auth+freshness with zero writes, even for a configured, grant-holding source (Task 3 `test_reserved_accepted_kind_is_refused_after_authentication`).
3. Event-id reuse across works silently duplicating evidence → `SOURCE_EVENT_CONFLICT` receipt, evidence count unchanged (Task 3 `test_event_id_reused_across_works_is_source_event_conflict`).
4. Verify-then-reread integrity gap: forwarding mutable caller data instead of the verified snapshot → detached snapshot by construction, pinned by signer-detachment and post-record mutation regressions (Task 2 `test_input_message_is_never_mutated_and_envelope_is_detached`, Task 3 `test_envelope_mutation_after_record_cannot_affect_persisted_evidence`).
5. Secret or candidate leakage through rejection receipts or persistence → exact two-key receipt dicts and evidence-body purity assertions; empty key map authenticates nothing (Task 3 `test_rejection_receipts_disclose_no_secret_or_candidate`, `test_accepted_evidence_forwards_verified_snapshot_only`, `test_empty_key_map_authenticates_nothing`).

---

### Task 1: Baseline and plan

**Files:** Create: this plan.
- [x] Record baseline: `python3 -m unittest discover -s tests` → `Ran 63 tests ... OK` (Python 3.9.6, observed 2026-10-13).
- [x] Commit plan: `git add docs/superpowers/plans/2026-10-13-s2-signed-evidence-ingress.md && git commit -m "docs(plan): scoped S2 signed evidence ingress plan"`

### Task 2: `sign_evidence` signer (RED → GREEN)

**Files:** Create `work_runtime/ingress.py`, `tests/test_ingress.py`.
**Interfaces:** Produces `sign_evidence(secret: bytes, message: dict) -> dict`, constants `SIGNED_FIELDS`, rejection-code names, per Pinned contract.

- [ ] **Step 1: Write failing signer tests** — `tests/test_ingress.py`, class `SignEvidenceTests` with per-test keys from `secrets.token_bytes(32)`:
  - `test_envelope_has_exact_fields_and_lowercase_hex_signature` — result keys == signed fields + `signature`; `^[0-9a-f]{64}$`.
  - `test_known_answer_vector_pins_hmac_sha256` — fixed 32-byte non-secret vector key/message, precomputed expected hex.
  - `test_input_message_is_never_mutated_and_envelope_is_detached` — deep-compare input copy; mutate `message["data"]` after signing, envelope still carries signed content.
  - `test_signature_depends_on_every_field` — each of the 7 fields changed → different signature.
  - `test_rejects_short_or_non_bytes_secret` — `ValueError` for `str`, 31 bytes.
  - `test_rejects_wrong_field_sets` — missing field, extra field, `actor` alias field.
  - `test_rejects_invalid_field_types` — `issued_at` `True`/`"x"`/`2000000000.0`; `data` non-dict; empty/`None` identity strings.
  - `test_rejects_non_json_native_data` — NaN, ±Inf (nested), tuple value, int dict key, set member → `ValueError`.
- [ ] **Step 2: RED** — `python3 -m unittest discover -s tests -p test_ingress.py -v` → all error with `ModuleNotFoundError: No module named 'work_runtime.ingress'`. Record verbatim.
- [ ] **Step 3: Implement** `ingress.py`: module docstring (trust model), constants, `_json_native(value)` recursive check, `_message_problem(message)`, `_canonical_bytes(message)`, `sign_evidence` returning `{**json.loads(canonical), "signature": hmac hex}`.
- [ ] **Step 4: GREEN** — same command, 8 tests pass; full discover → 71 tests OK.
- [ ] **Step 5: Commit** — `feat(ingress): strict sign_evidence signer with JSON-native canonical HMAC envelopes` (ingress.py + test_ingress.py).

### Task 3: Gateway contract tests (RED)

**Files:** Modify `tests/test_ingress.py`.
**Interfaces:** Consumes `sign_evidence`; produces test rig: temp-dir real `Runtime` + `ExpensePolicy` + `demo_grants()`, `initialize()`, keys `{finance, invoice-service}` (+ per-test variants), fixed `clock=lambda: self.now` (`2_000_000_000`), helpers `signed(**overrides)`, `table_counts()` (all 6 tables via sqlite3 on `runtime.path`), `evidence_bodies()`.

- [ ] **Step 1: Write failing gateway tests** — class `SignedEvidenceGatewayTests`; message defaults: source `finance`, `command_id "cmd-1"`, `work_id "demo"`, `event_id "evt-1"`, `kind "approval"`, `data {"digest": work document_digest}`, `issued_at self.now`. Tests (names are the contract):
  - `test_signed_evidence_is_accepted_and_pending_until_verification` — accepted receipt with `evidence_status "pending_verification"`; E05 requirement still `pending`; `verify_pending("demo")` → `satisfied`; also one acceptance through the default `time.time` clock.
  - `test_accepted_evidence_forwards_verified_snapshot_only` — persisted evidence body keys exactly `{id, source, event_id, kind, data, status}`; no `signature`/`issued_at` in body or receipt.
  - `test_freshness_boundaries` — `issued_at = now ± max_age` accepted (default 300).
  - `test_stale_and_future_timestamps_are_expired` — `now ± (max_age+1)` validly signed → `EVIDENCE_EXPIRED`; all table counts unchanged.
  - `test_exact_replay_inside_freshness_returns_existing_receipt` — identical receipt object equality; commands 1, evidence 1.
  - `test_expired_replay_is_refused_before_runtime` — advance `self.now` past window → `EVIDENCE_EXPIRED`, counts unchanged.
  - `test_timestamp_refresh_under_new_command_keeps_event_identity` — new `command_id`, fresh `issued_at`, same event → same `evidence_id`; evidence 1, commands 2.
  - `test_event_id_reused_across_works_is_source_event_conflict` — second work via trusted `create_work`; same source+event_id on `work_id "demo2"` → `SOURCE_EVENT_CONFLICT`; evidence stays 1.
  - `test_same_command_id_with_different_content_is_command_id_reused` — fresh signature, same `command_id`, different `event_id` → `COMMAND_ID_REUSED`.
  - `test_source_grant_refusal_follows_runtime_persistence` — `invoice-service` (grant-holder, wrong kind owner) signs `kind "approval"` → `AUTHORITY_DENIED` receipt, commands +1, evidence +0.
  - `test_source_without_grants_is_rejected_without_writes` — `observer` key outside grants → runtime `AUTHORITY_DENIED`, all counts unchanged.
  - `test_valid_signature_for_unknown_work_raises_command_error` — `assertRaises(CommandError)`; counts unchanged (documented trusted-local propagation).
  - `test_reserved_accepted_kind_is_refused_after_authentication` — runtime variant with `oa` granted `evidence.write` and key configured: fresh signed `source "oa"`, `kind "accepted"` → `EVIDENCE_KIND_UNSUPPORTED`, zero writes.
  - `test_every_signed_field_tampering_fails_authentication` — loop all 7 fields with same-type replacements → `EVIDENCE_AUTHENTICATION_FAILED`; counts unchanged.
  - `test_cross_source_key_cannot_impersonate` — invoice-service key over `source "finance"` → `EVIDENCE_AUTHENTICATION_FAILED`.
  - `test_unknown_source_has_no_key_and_fails_authentication` — `source "attacker"` → `EVIDENCE_AUTHENTICATION_FAILED`.
  - `test_rejection_receipts_disclose_no_secret_or_candidate` — crypto/schema/freshness/reserved receipts exactly `{"decision","code"}`; dumps contain no signature hex or key material.
  - `test_non_dict_envelopes_are_invalid`, `test_wrong_envelope_field_sets_are_invalid`, `test_invalid_field_types_are_invalid` (incl. bool/str/float `issued_at`, malformed signatures), `test_non_json_native_or_nonfinite_data_is_invalid`, `test_schema_precedes_authentication` (string `issued_at` and NaN data with garbage signature → `EVIDENCE_ENVELOPE_INVALID`, not auth/expired) — all `EVIDENCE_ENVELOPE_INVALID`, counts unchanged.
  - `test_envelope_mutation_after_record_cannot_affect_persisted_evidence` — mutate envelope data post-success; persisted body keeps signed digest; replay of mutated envelope → `EVIDENCE_AUTHENTICATION_FAILED`.
  - `test_short_non_bytes_or_duplicate_key_material_is_invalid`, `test_invalid_max_age_or_clock_is_invalid` — constructor `ValueError`s.
  - `test_empty_key_map_authenticates_nothing` — `keys={}` → valid envelope `EVIDENCE_AUTHENTICATION_FAILED`.
- [ ] **Step 2: RED** — `python3 -m unittest discover -s tests -p test_ingress.py -v` → all gateway tests error with `ImportError: cannot import name 'SignedEvidenceGateway'`. Record verbatim.

### Task 4: Gateway implementation (GREEN)

**Files:** Modify `work_runtime/ingress.py`.
- [ ] **Step 1: Implement** `SignedEvidenceGateway` per the Pinned contract ordering, forwarding only the `json.loads` snapshot; constructor validation per Pinned contract; `_reject(code)` exact two-key receipts.
- [ ] **Step 2: GREEN** — `python3 -m unittest discover -s tests -p test_ingress.py -v` → all pass; `python3 -m unittest discover -s tests` → 63 + signer + gateway tests OK; `python3 -m compileall -q work_runtime tests scripts`.
- [ ] **Step 3: Commit** — `feat(ingress): SignedEvidenceGateway authenticated intake before record_evidence`.

### Task 5: Documentation, gates, report

**Files:** Create `docs/signed-evidence.md`, `.agents/notes/2026-10-13-S2-ingress-report.md`.
- [ ] **Step 1: Write `docs/signed-evidence.md`** — purpose and trust model (untrusted ingress vs trusted-local Runtime); envelope field table; check order and receipt codes incl. `EVIDENCE_KIND_UNSUPPORTED`; persistence semantics (intake failures write nothing; authenticated business rejections may persist receipts); replay semantics incl. cross-work `SOURCE_EVENT_CONFLICT` (M2); freshness/clock; key-handling guidance (per-source distinct ≥32 random bytes, stored outside repo/DB, never logged; no default secret); explicit non-goals: HMAC authenticity ≠ business truth (verification stays separate), ≠ TLS/transport confidentiality, ≠ tenant authentication/authorization, no key rotation/revocation, no distributed exactly-once; test map naming the suite. Links only to existing files.
- [ ] **Step 2: Gates** — `python3 scripts/check_docs.py`; `python3 -m unittest discover -s tests -v`; `python3 -m work_runtime demo`; `python3 -m compileall -q work_runtime tests scripts`.
- [ ] **Step 3: Report** — `.agents/notes/2026-10-13-S2-ingress-report.md`: verbatim RED/GREEN outputs, named tests, commit hashes, limitations/risks.
- [ ] **Step 4: Commit** — `docs(ingress): signed evidence boundary document and RED/GREEN report`.
- [ ] **Step 5:** Final coordinator mail check, then `worker_done` with 3-sentence summary.
