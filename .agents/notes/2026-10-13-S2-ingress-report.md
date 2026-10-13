# S2 signed evidence ingress — developer evidence report (2026-10-13)

Worker: S2 signed evidence ingress developer (Orca dispatch task_a823ee54f385).
Scope: `work_runtime/ingress.py`, `tests/test_ingress.py`, `docs/signed-evidence.md`,
this plan `docs/superpowers/plans/2026-10-13-s2-signed-evidence-ingress.md` and this
report. No Runtime/policy/adapter/publishing/README/ledger edits; no merge, no push.

## Design inputs

Spec Foundation B in `docs/superpowers/specs/2026-10-13-s2-trusted-boundaries.md`
(local copy 7dd96a3), superseded where underspecified by carrier D8 addendum at
32de295 (read from the carrier worktree) and coordinator mail of 2026-10-13:
B1 error-code mapping, JSON-native strictness, distinct copied keys, nonnegative
int max_age; M1 reserved `accepted` kind refused after signature+freshness;
M2 replay semantics incl. cross-work `SOURCE_EVENT_CONFLICT`; detached verified
snapshot (canonicalize once, HMAC those bytes, forward `json.loads` of them,
each envelope field read exactly once); plan proportion.

## TDD evidence (commands run from the worktree, Python 3.9.6)

Baseline before any change: `python3 -m unittest discover -s tests` →
`Ran 63 tests ... OK`.

### Cycle 1 — sign_evidence (RED → GREEN)

RED (`python3 -m unittest discover -s tests -p test_ingress.py -v`, verbatim):

```
    from work_runtime.ingress import SIGNED_FIELDS, sign_evidence
ModuleNotFoundError: No module named 'work_runtime.ingress'


----------------------------------------------------------------------
Ran 1 test in 0.000s

FAILED (errors=1)
```

GREEN after implementing the signer (8 tests):

```
test_envelope_has_exact_fields_and_lowercase_hex_signature ... ok
test_input_message_is_never_mutated_and_envelope_is_detached ... ok
test_known_answer_vector_pins_hmac_sha256 ... ok
test_rejects_invalid_field_types ... ok
test_rejects_non_json_native_data ... ok
test_rejects_short_or_non_bytes_secret ... ok
test_rejects_wrong_field_sets ... ok
test_signature_depends_on_every_field ... ok

Ran 8 tests in 0.001s

OK
```

Full suite after cycle 1: `Ran 71 tests ... OK`. Commit `dfd81f3`.

### Cycle 2 — SignedEvidenceGateway (RED → GREEN)

RED after writing the 27 gateway contract tests against a real SQLite Runtime:

```
ImportError: cannot import name 'SignedEvidenceGateway' from 'work_runtime.ingress'
```

GREEN after implementing `record` (35 tests total in the file):

```
Ran 35 tests in 0.386s

OK
```

Full suite: `Ran 98 tests ... OK`; `python3 -m compileall -q work_runtime tests` clean.
Commit `078e8ce`.

### Cycle 3 — final-review fix (RED → GREEN)

Whole-branch self-review found that a lone-surrogate string passes the str type
check, then `canonical(...).encode("utf-8")` raises `UnicodeEncodeError`, which
`record` did not catch — a stacktrace leak at the untrusted boundary, violating
B1. RED (`python3 -m unittest tests.test_ingress.SignedEvidenceGatewayTests.test_utf8_encoding_failure_is_envelope_invalid`):

```
  File ".../work_runtime/ingress.py", line 70, in _canonical_bytes
    return canonical(message).encode("utf-8")
UnicodeEncodeError: 'utf-8' codec can't encode character '\ud800' in position 180: surrogates not allowed
```

Fix: `record` catches `(TypeError, ValueError, RecursionError)` around envelope
opening + canonicalization. GREEN: `Ran 36 tests ... OK` in the file,
`Ran 99 tests ... OK` full suite. Commit `d3a4862`.

## What the tests pin (named)

`SignEvidenceTests`: exact envelope fields + lowercase hex signature; published
non-secret HMAC known-answer vector (key bytes 00..1f); input never mutated and
returned envelope fully detached (nested mutation included); signature depends on
every signed field and the key; short/non-bytes secrets; wrong field sets incl.
`actor` alias; invalid field types incl. boolean/float/string `issued_at`;
non-JSON-native data (NaN, ±Inf, tuple, int keys, set) rejected.

`SignedEvidenceGatewayTests` (real Runtime + `initialize`, fixed injectable clock):
accepted evidence stays `pending_verification` until `verify_pending` (E05 pending →
satisfied), default `time.time` clock acceptance; persisted evidence body carries
exactly `{id, source, event_id, kind, data, status}` — no signature/timestamp;
freshness boundaries at ±max_age and `EVIDENCE_EXPIRED` at ±(max_age+1); exact
replay inside freshness returns the stored receipt (commands/evidence +1 only);
expired replay refused before Runtime; timestamp refresh under a new command id
keeps the same `evidence_id`; event-id reuse across works → `SOURCE_EVENT_CONFLICT`;
same command id with different content → `COMMAND_ID_REUSED`; grant-holder signing
another kind → `AUTHORITY_DENIED` with persisted receipt; source outside grants →
`AUTHORITY_DENIED` with zero writes; validly signed unknown work raises
`CommandError` with zero writes; reserved `accepted` kind refused with
`EVIDENCE_KIND_UNSUPPORTED` even for a granted, key-configured `oa` source;
all seven signed fields' tampering → `EVIDENCE_AUTHENTICATION_FAILED` with real
table counts unchanged; cross-source key and unknown source → authentication
failure; rejection receipts are exactly `{decision, code}` and disclose no
signature/key material; non-dict/wrong-field/wrong-type/non-JSON-native envelopes
→ `EVIDENCE_ENVELOPE_INVALID`; schema precedes authentication (string timestamp,
NaN data); envelope mutation after record cannot affect persisted evidence and
fails replay authentication; constructor rejects non-dict keys, short/non-bytes
values, duplicate key material, bad names, negative/bool/str max_age, non-callable
clock; key map copied at construction; empty key map authenticates nothing.

## Gates (after final commit state)

- `python3 -m unittest discover -s tests -v` → `Ran 99 tests ... OK` (63 baseline preserved; 36 in tests/test_ingress.py)
- `python3 scripts/check_docs.py` → `checked 30 markdown files, 75 local links, 0 broken`
- `python3 -m work_runtime demo` → all six steps, `external applications created: 1`
- `python3 -m compileall -q work_runtime tests scripts` → clean

## Commits

- `a655b3c` docs(plan): scoped S2 signed evidence ingress plan
- `dfd81f3` feat(ingress): strict sign_evidence signer with JSON-native canonical HMAC envelopes
- `078e8ce` feat(ingress): SignedEvidenceGateway authenticated intake before record_evidence
- `d3a4862` fix(ingress): treat UTF-8 canonicalization failures as invalid envelopes
- docs commit: `docs(ingress): signed evidence boundary document and RED/GREEN report`

## Limitations and residual risks

- Shared-key HMAC: any key holder can sign as that source; no rotation, key ids or
  revocation (documented in `docs/signed-evidence.md`). Freshness bounds replay in
  time; durable identity dedup only covers accepted events.
- The gateway authenticates sources, not humans/tenants; business authorization
  remains Runtime grants. A granted key-configured source signing another source's
  kind is rejected by Runtime and *does* persist a rejection receipt — by design.
- `CommandError` propagation for validly signed unknown `work_id` is documented
  trusted-local behavior, not a receipt.
- Verified-snapshot forwarding is by construction (single-read envelope opening +
  canonical-bytes snapshot); the black-box regressions pin detachment and
  no-alias behavior, not every hostile mapping subclass.
- Deferred minors from final review: no explicit signer-side pin that surrogate
  input raises ValueError (already true via UnicodeEncodeError inheritance);
  `_json_native` accepts int/float subclasses that canonicalize
  value-preservingly (e.g. IntEnum) — coercion is value-preserving only.
- Tests were written against the S1 baseline Runtime (63 tests); Foundation A
  (adapter contract) merges separately in the integration session, which owns
  re-running this suite on the assembled carrier.

## Addendum — review correction: signer RecursionError on cyclic/deep data (2026-10-13)

Coordinator follow-up task_995607a53a7e: at 7d21109 `sign_evidence` calls
`_message_problem` (recursive `_json_native`) and `_canonical_bytes` with no
conversion, so self-referencing or pathologically deep `data` surfaced as
`RecursionError` instead of the D8 B1 `ValueError` local-misuse contract.
`Gateway.record` already converted the same input correctly.

Systematic-debugging Phase 1 probes (verbatim outcomes):

```
probe 1: cyclic data at signer      -> RecursionError (DEFECT: not ValueError)
  deepest frames: sign_evidence:92 -> _message_problem:60 -> _json_native:45
probe 2: 10000-deep acyclic nesting -> RecursionError (DEFECT)
probe 3: repeated acyclic shared reference -> signed ok, detached: True (control)
probe 4: cyclic data at gateway.record -> {'decision': 'rejected', 'code': 'EVIDENCE_ENVELOPE_INVALID'} (control)
```

### RED (tests written first; `python3 -m unittest ... -v`, verbatim tail)

```
RecursionError: maximum recursion depth exceeded while calling a Python object
RecursionError: maximum recursion depth exceeded while calling a Python object
Ran 2 tests in 0.004s
FAILED (errors=2)
```

`test_rejects_self_referencing_data_with_value_error` and
`test_rejects_excessively_deep_nesting_with_value_error` error with
RecursionError; the two control pins
(`test_repeated_acyclic_references_sign_and_detach`,
`test_cyclic_or_deeply_nested_envelope_data_is_envelope_invalid`) already pass.

### GREEN (minimal localized conversion in `sign_evidence`, mirroring `record`)

```
Ran 40 tests in 0.322s

OK
```

Full suite `Ran 103 tests ... OK`; `compileall` clean. The fix wraps exactly
`_message_problem` + `_canonical_bytes` in `try/except RecursionError` and
raises `ValueError("message contains a reference cycle or exceeds the
serialization depth")`. No change to `_json_native`, the gateway, HMAC vector,
schema/key/source/freshness/snapshot/reserved-kind behavior (all still green).

New pins: gateway rejects cyclic and 10000-deep envelope `data` with
`EVIDENCE_ENVELOPE_INVALID` and all six Runtime tables unchanged; repeated
acyclic references sign successfully and detach (no shared sub-objects remain
in the returned envelope). docs/signed-evidence.md gains one paragraph stating
both behaviors.

Gates after the correction: 103/103 tests, `check_docs` 25 files/75 links/0
broken, `python3 -m work_runtime demo` all six steps, compileall clean.
