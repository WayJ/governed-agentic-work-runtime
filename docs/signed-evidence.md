# Signed evidence ingress

`work_runtime/ingress.py` adds an authenticated intake path for external
evidence: a trusted-side signer (`sign_evidence`) and an untrusted-facing
`SignedEvidenceGateway` that verifies HMAC-SHA256 signed envelopes and
forwards them to the existing `record_evidence` command. Nothing about the
Runtime changes — direct Runtime methods remain trusted-local APIs for code
that already holds local trust (see [runtime boundaries](runtime-boundaries.md)).

## Trust model

- **What the signature proves:** the envelope was produced by someone holding
  the configured secret for the named source, and its signed content was not
  modified afterwards. That is source authenticity and content integrity
  within a configured shared-key trust boundary.
- **What it does not prove:** business truth. Signed evidence is still a
  *candidate* — it lands as `pending_verification` and only becomes verified
  through the Runtime's separate `verify_pending` step and policy
  `validate_evidence`. It is also not transport security (use TLS where
  relevant), not tenant authentication or authorization, and not a
  non-repudiation mechanism: the secret is shared, so any key holder can sign
  as that source.
- **Who is authenticated:** the *source* named in the envelope (for example
  `finance`), never a human or tenant principal. The Runtime's grants still
  decide what an authenticated source may do.

## Envelope

`sign_evidence(secret: bytes, message: dict) -> dict` validates the message,
returns a detached copy of it plus a `signature` field, and never mutates the
input. It raises `ValueError` for an invalid key, message shape, or
canonicalization failure.

| field | type | notes |
|---|---|---|
| `source` | nonempty str | must be a configured key name at the gateway |
| `command_id` | nonempty str | persistent command identity (replay/dedup) |
| `work_id` | nonempty str | target work |
| `event_id` | nonempty str | durable source-event identity |
| `kind` | nonempty str | evidence kind owned by the source in policy |
| `data` | JSON-native object | finite values, string keys, no tuple/set/coercions |
| `issued_at` | int (not bool) | epoch seconds |
| `key_id` | nonempty str (optional) | authenticated keyring selector (S11); never persisted |
| `signature` | 64 lowercase hex | HMAC-SHA256 of the canonical message UTF-8 |

Canonical form is sorted-key compact JSON (`policy.canonical`, `allow_nan=False`).
The signature covers exactly the seven signed fields, plus `key_id` when the
optional selector is present — an envelope carries either exactly the seven
legacy fields or those seven plus `key_id`, nothing else. `signature` itself is
never signed, and there is no actor/alias field. `SIGNED_FIELDS` (the legacy
seven-field tuple) and the published known-answer vector are unchanged; old
gateways reject 8-field envelopes as `EVIDENCE_ENVELOPE_INVALID`, so a signer
targeting one omits `key_id`.

Reference cycles and pathologically deep nesting are invalid input on both
surfaces: the signer raises `ValueError` (local misuse contract) and the
gateway rejects with `EVIDENCE_ENVELOPE_INVALID`. Repeated *acyclic*
references inside `data` are fine — the returned envelope is a fully detached
copy, so shared sub-objects do not stay shared.

## Gateway checks and receipts

`SignedEvidenceGateway(runtime, keys, max_age=300, clock=time.time).record(envelope)`
checks, in order:

1. **Envelope shape/types** — exact field set, JSON-native finite `data`,
   integer (non-bool) `issued_at`, well-formed signature string. Canonicalization
   or UTF-8 encoding failures are caught and treated the same way.
   → `EVIDENCE_ENVELOPE_INVALID`
2. **Known source** — the `source` must have a configured key or keyring.
   → `EVIDENCE_AUTHENTICATION_FAILED`
3. **Key selection** (deterministic, no try-all, no fallback) — an envelope
   citing `key_id` selects that entry in the source's keyring (an absent
   entry is rejected, indistinguishable from an attacker's key); a keyring
   envelope without `key_id` selects the ring's **`current` entry only** —
   the migration bridge that keeps legacy-format signers working and
   guarantees a retired key is never silently accepted on the legacy path; a
   legacy `bytes` source has one key and rejects `key_id` envelopes.
   → `EVIDENCE_AUTHENTICATION_FAILED`
4. **Signature** — HMAC-SHA256 over the canonical UTF-8 snapshot (including
   `key_id` when present), compared with `hmac.compare_digest`. Tampering
   with any signed field — including swapping the selector — fails here.
   → `EVIDENCE_AUTHENTICATION_FAILED`
5. **Freshness** — `abs(now - issued_at) <= max_age`, covering future skew.
   → `EVIDENCE_EXPIRED`
6. **Reserved kind** — `kind == "accepted"` is reserved for Runtime-written
   adapter receipts; signed ingress refuses it even for an authorized,
   key-configured source. → `EVIDENCE_KIND_UNSUPPORTED`
7. Only then `runtime.command(actor=source, kind="record_evidence", ...)`
   with the business payload `{event_id, kind, data}` taken from the same
   detached JSON snapshot whose bytes were authenticated. The signature,
   timestamp and `key_id` are authentication-envelope data and are never
   persisted in the business payload or part of any evidence fingerprint.

Rejection receipts for steps 1–6 are exactly `{"decision": "rejected",
"code": ...}` and leave **all** Runtime tables unchanged: no command, evidence,
event or work rows are written for unauthenticated input. Authenticated
business rejections are different and follow normal Runtime semantics — a
source signing another kind's identity (`AUTHORITY_DENIED`), reusing a command
id with different content (`COMMAND_ID_REUSED`) or conflicting with an existing
source event (`SOURCE_EVENT_CONFLICT`) may persist a rejection receipt. A
validly signed envelope for an unknown work raises `CommandError` (trusted
local misuse), writing nothing.

## Freshness, replay and dedup

- An exact replay inside the freshness window returns the stored receipt and
  writes nothing new. An expired replay is refused with `EVIDENCE_EXPIRED`
  before the Runtime is involved.
- Refreshing the timestamp under a **new** command id still resolves to the
  same durable `(source, event_id)` evidence identity: the timestamp is not
  part of the business fingerprint.
- Reusing an event id with different content — including on a different work —
  is `SOURCE_EVENT_CONFLICT`, never a silent second insert. The gateway adds
  no retry guarantee beyond what Runtime lookup/reconciliation provides.

The clock is injectable for tests; `max_age` defaults to 300 seconds and must
be a nonnegative integer.

## Key handling

- Generate one distinct random secret per source (`secrets.token_bytes(32)` or
  equivalent); 32 bytes is the enforced minimum. Duplicate key material
  across the entire configuration — every source, every keyring entry — is
  rejected at construction.
- Keys live outside this repository and outside the runtime database; the
  gateway copies the configuration at construction and never persists, logs or
  echoes key material. Rejection receipts contain no secret, signature or
  candidate content.
- There is **no default or global secret**: an empty key map simply fails all
  authentication.

### Source keyrings (S11)

Each source is configured either as legacy `bytes` (unchanged single-key
semantics) or as a keyring — a nonempty `list`/`tuple` of
`work_runtime.ingress.SourceKey` entries (`key_id`, `secret`, `current`,
`not_before`, `not_after`), never both shapes for one source. Construction
validation is exact (D50): `key_id` a nonempty `str`, `secret` `bytes` of at
least 32 bytes, `current` exactly `bool`, validity bounds each `None` or an
integer epoch second (bools rejected) with `not_before <= not_after` when both
are present; `key_id`s unique within the ring; exactly one `current` entry; and
secret material distinct across the whole configuration. The ring is
normalized to an immutable per-source tuple copied at construction: mutating
the caller's dict or list afterwards changes nothing, and rotation means
constructing a new gateway from new configuration — there is no in-process
rotation surface. Verification-key selection for keyring sources is specified
under [Gateway checks](#gateway-checks-and-receipts); key validity windows are
evaluated on the gateway clock and land with the S11 clock work on this branch.

## Limitations

Shared-key HMAC is symmetric — trust extends to everyone who holds a key.
Freshness bounds (not prevents) replay; durable identity dedup handles the
rest only after acceptance. One policy per runtime database still applies, and
this ingress covers `record_evidence` only: dispatch, reconciliation and
completion remain trusted-local operations. This is an implementation-spec
boundary for S2, not a production security claim.

## Tests

`tests/test_ingress.py` (real SQLite Runtime, no mocks): signer strictness and
known-answer vector; every signed field's tampering; cross-source impersonation
and unknown sources; freshness boundaries incl. boolean timestamps; reserved
`accepted` kind; schema-before-authentication ordering; real table counts
unchanged on every intake failure; signed success staying pending until
`verify_pending`; exact replay, timestamp refresh and cross-work conflict;
source grant refusal persistence; envelope-detachment regressions; and
constructor configuration validation.
