# Source signing-key rotation — candidate design (DRAFT)

Status: **DRAFT, pending master ratification and independent review.** This is
a candidate design for the roadmap 0.2 source-key-rotation gap. It allocates
no epic, sprint, ADR or ledger entry; the master owns roadmap and
ratification. Nothing here is implemented. Local decision numbering is
`SKR-1…SKR-12` (no collision with global `D`/MASTER numbers, currently up to
D48 from S10). Grounding evidence — fresh baseline gates, code cites and the
throwaway public-API probes P1–P13/P9b on `b594d757` — is recorded in the
[recon note](../../../.agents/notes/2026-10-15-source-key-rotation-recon.md);
every code reference below was read on that tree.

## 1. Problem (grounded, with line-level citations)

Roadmap 0.2 still owes *"source-key rotation semantics (rotating a source's
signing key is distinct from withdrawing an already-accepted proof — the
latter, evidence revocation, shipped in S8)"* — the last named 0.2 gap
([roadmap.md](../../roadmap.md), 0.2 paragraph). The shipped trust gate:

- pins **exactly one HMAC secret per source** — `SignedEvidenceGateway(runtime,
  keys: Dict[str, bytes], max_age=300, clock=time.time)`
  (`ingress.py:137-156`), material distinct across sources, map copied at
  construction, never persisted;
- authenticates envelopes with an **exact seven-field signed set** —
  `command_id, data, event_id, issued_at, kind, source, work_id` plus
  `signature` (`ingress.py:20-21`) — canonical sorted-key compact JSON,
  HMAC-SHA256, `hmac.compare_digest` (`policy.py:8-10`, `ingress.py:80-81,
  158-176`), pinned by a published known-answer vector
  (`test_ingress.py:40-47`);
- then checks freshness and the reserved `accepted` kind **before**
  `runtime.command(actor=source, kind="record_evidence", …)`
  (`ingress.py:177-184`).

The doc states the gap verbatim: *"Rotation/revocation is out of scope:
replacing a key takes effect for new envelopes only and there is no key id or
revocation list"* ([signed-evidence.md](../../signed-evidence.md), Key
handling). Consequences, probe-confirmed on `b594d757` (recon §3):

| gap | probe evidence |
|---|---|
| Rollover is a hard cutover: reconstructing the gateway with a new key instantly `EVIDENCE_AUTHENTICATION_FAILED`s every in-flight old-key envelope — no dual-key window | P1 |
| No key identity: an operator cannot name which key signed, retire one key of several, or distinguish "unknown key" from "retired key" | P1, P2 |
| An extra `key_id` field is `EVIDENCE_ENVELOPE_INVALID` under the exact-field-set rule — there is today no in-band place for a selector, so any naive addition is unsigned or rejected | P6 |
| Mutating the caller's key map after construction changes nothing (no live rotation surface at all) | P11 |

What already works and must not change (recon §4): the cached command receipt
is unreachable behind a failed gateway authentication (P2 —
`ingress.py:158-184` always runs before `runtime.py:263-272`); re-signing the
same `(source, event_id)` content under a different key dedupes to the same
proof/status because runtime fingerprints are key-agnostic (P3,
`runtime.py:778-787`); changed content stays `SOURCE_EVENT_CONFLICT` (P5);
pure rotation writes nothing and history rows are byte-preserved (P9/P9b);
authority is name-based, so a rotated key inherits exactly the source's
existing grants and a new key grants nothing (P10).

## 2. Goals and non-goals

**Goal (smallest useful 0.2 slice):** a source can hold several named signing
keys with explicit validity windows and an explicit current key; envelopes
can opt in to an *authenticated* key selector; an operator can rotate
(old→new) and retire (cut off) deterministically from configuration, without
store changes and without touching any historical proof, receipt, operation,
closure or compensation record.

**Non-goals (unchanged boundaries):** not tenant authentication or
authorization, not transport security (TLS), not an external key service/KMS,
not asymmetric signatures, not distributed revocation or federated key
distribution, not a live managed registry with its own commands and store
(deferred — §4.1 Option B), not production key management or any security
certification, no UI change, no claim that principal names authenticate
anything. A key still proves only *source authentication within a configured
shared-key boundary* (`signed-evidence.md` Trust model).

## 3. Scope recommendation (one bounded coherent slice)

Deliver **Option A only** (§4.1): configuration-supplied per-source keyring +
optional authenticated `key_id` envelope field + explicit current-key and
validity-window semantics, in `work_runtime/ingress.py` alone, plus docs and
a no-credentials demo. Rationale: it is config-shaped exactly like every
other trust boundary in this codebase (grants, policies, `evidence_sources`
are all trusted-local configuration), needs no schema change, no new command
kind, no new authority model, and every required downstream behavior
(dedupe, conflict, cache authority, history preservation, admission) already
exists and is pinned by tests. Option B (managed registry) is a strictly
larger slice with a real authority question of its own (who may rotate?) and
is deferred (SKR-1).

## 4. Design

### 4.1 Externally supplied keyring (A, recommended) vs live managed key registry (B)

| | A — config keyring (recommended) | B — managed registry commands/store |
|---|---|---|
| surface | constructor parameter, additive | new command kind(s) + store table + CLI |
| rotation act | rebuild gateway from new config (restart or reconstruct) | `rotate_source_key` command persisted in the ledger |
| authority | trusted-local configuration (same as grants) | needs a new grant/authority design (who may rotate which source?) |
| audit trail | operator's config management (documented limitation) | runtime event log |
| replay/dedup interactions | none — authentication layer only | new receipts, replay precedence, migration rules |
| schema | unchanged (`1`) | new table or schema version |
| blast radius | `ingress.py` + docs + tests | runtime core + boundaries doc + RFC semantics |

B is genuinely useful later (rotation as a governed, audited act fits this
project's philosophy) but every piece of machinery it needs is new; A
completes the 0.2 promise with zero new runtime semantics. **Recommend A
now, B as explicit future work** (SKR-1).

### 4.2 Envelope — optional authenticated `key_id`

- `SIGNED_FIELDS` is unchanged (the same seven-field tuple, so the KAT
  vector and legacy canonicalization are untouched); a new constant names the
  one **optional** member `key_id` (nonempty string). A message/envelope has
  either exactly the seven legacy fields or those seven plus `key_id` —
  nothing else (`_message_problem`/`_open_envelope` accept both shapes; any
  other field set stays `EVIDENCE_ENVELOPE_INVALID`).
- `key_id` is **inside the signed content**: the canonical bytes forwarded to
  HMAC include it, so swapping the selector breaks the signature — no
  unsigned selector downgrade (today's exact-field rule already rejects any
  naive extra field, probe P6).
- `key_id` is authentication-envelope data, exactly like `signature` and
  `issued_at`: it is **never persisted** in the business payload and never
  enters the command/evidence fingerprint (`ingress.py:179-184` forwards only
  `{event_id, kind, data}`; fingerprints at `runtime.py:259,778` remain
  key-agnostic — probe P3).
- Old gateways reject 8-field envelopes as `EVIDENCE_ENVELOPE_INVALID`
  (schema); new gateways accept both. Compat is one-directional by design:
  a signer targeting an old gateway omits `key_id`.

### 4.3 Source keyring configuration (types, validation, immutability)

```python
# work_runtime/ingress.py — additive, Python >=3.9 stdlib only
from typing import NamedTuple, Optional, Sequence

class SourceKey(NamedTuple):
    key_id: str                 # nonempty; unique within its source's keyring
    secret: bytes               # >= 32 bytes (MIN_SECRET_BYTES unchanged)
    current: bool = False       # exactly one entry per keyring must be current
    not_before: Optional[int] = None  # inclusive epoch-second bounds,
    not_after: Optional[int] = None   # same clock domain as freshness
```

`SignedEvidenceGateway(runtime, keys, max_age=300, clock=time.time)` —
signature unchanged; `keys` accepts **either** shape per source (a source
must use exactly one shape):

- `Dict[str, bytes]` — legacy: unchanged semantics, no `key_id` envelopes
  (a `key_id` envelope for a legacy source is `EVIDENCE_AUTHENTICATION_FAILED`).
- `Dict[str, Sequence[SourceKey]]` — keyring.

Construction validation (all `ValueError`, before anything else, extending
`ingress.py:139-152`): source names nonempty; per keyring — nonempty
sequence, unique `key_id`s, **exactly one `current` entry**, secrets ≥32
bytes, `not_before <= not_after` when both present; globally — secret
material distinct across the **entire configuration** (every source, every
entry — extends the existing per-source rule, probe P8). The configuration
is copied at construction and is immutable thereafter: rotation means
constructing a new gateway; mutating the caller's structures afterwards has
no effect (existing discipline, probe P11). No artificial keyring-size cap
(configuration is trusted-local, like `grants`).

### 4.4 Verification key selection and decision precedence (codes)

`record(envelope)` order (each step's code in bold; steps 1–7 write nothing —
the existing intake-failure contract):

1. **shape/types** — 7-field legacy or 8-field `key_id` envelope, JSON-native
   data, integer `issued_at`, well-formed signature →
   `EVIDENCE_ENVELOPE_INVALID`
2. **known source** → `EVIDENCE_AUTHENTICATION_FAILED`
3. **key selection** (public-data lookup, deterministic by construction):
   envelope has `key_id` → that entry in the source's keyring; absent entry →
   `EVIDENCE_AUTHENTICATION_FAILED`. No `key_id` → the source's legacy key,
   or the keyring's **`current` entry** (and only it — a retired key never
   silently serves the legacy path, SKR-7)
4. **HMAC** — `hmac.compare_digest(_signature(secret, encoded), signature)`
   over the exact canonical bytes being forwarded (single-read snapshot
   discipline unchanged; `key_id` included when present) →
   `EVIDENCE_AUTHENTICATION_FAILED`
5. **key window** — `not_before <= clock() <= not_after` (inclusive, when the
   bound is configured) → `EVIDENCE_KEY_NOT_YET_VALID` /
   `EVIDENCE_KEY_RETIRED`. Checked **after** HMAC so the codes are reachable
   only by a genuine key holder (no oracle for strangers); receipts stay
   exactly `{"decision": "rejected", "code": …}` — no key echo (B1
   minimalism preserved)
6. **freshness** — `abs(clock() - issued_at) <= max_age` (unchanged,
   inclusive) → `EVIDENCE_EXPIRED`
7. **reserved kind** — `accepted` → `EVIDENCE_KIND_UNSUPPORTED` (unchanged)
8. `runtime.command(…)` — unchanged: its own `(actor, command_id)` dedup,
   authority recheck on replay, `(source, event_id)` evidence dedup and CAS
   precedence all apply exactly as today.

Window before freshness (5 before 6): retirement is the more specific fact
and stays observable after the freshness window would also have failed
(SKR-4). Two new codes instead of folding into
`EVIDENCE_AUTHENTICATION_FAILED` (SKR-3, recommendation: keep both — they
are post-authentication and operator-actionable: "your signer is still using
the retired key").

### 4.5 Rollover windows — deterministic configured time on the existing clock

Key validity bounds are **configuration-declared epoch seconds evaluated
against the same injectable `clock` callable that already drives freshness**
(`ingress.py:137-138,175`). No store timestamps, no persisted key state, no
second time domain: decisions are a pure function of `(envelope, config,
clock())`, so tests inject one deterministic clock and restarts replay
identically (SKR-6). Documented rollover ladder (every step a config act;
each gateway reconstruction writes nothing — probe P9b):

1. **add**: `{K1(current), K2}` — K2 authenticates via `key_id` envelopes;
   legacy envelopes still hit K1.
2. **signers switch** to `key_id: K2` envelopes (both keys valid).
3. **rotate**: flip `current` to K2 and set `K1.not_after = now + grace`
   (grace ≥ `max_age` recommended, so in-flight envelopes land inside it).
   Within grace, correctly signed K1 envelopes pass; after it they get
   `EVIDENCE_KEY_RETIRED`; legacy-format envelopes now authenticate only
   against K2 (a legacy envelope signed with K1 fails HMAC at step 4 —
   explicit, never silent).
4. **retire**: drop K1 from the config, or keep it listed with its expired
   `not_after` — verification outcome is identical.

Truthful notes: wall-clock trust is the operator's (same as freshness
today); nothing protects a *currently compromised* key until rotation lands
(inherent to shared-key HMAC); changing secrets in memory after construction
does nothing (probe P11) — protection comes from the deployed configuration,
never from in-process mutation.

### 4.6 Replay, dedup and cache authority (unchanged machinery — probe-cited)

- **Fresh gateway authentication precedes every `Runtime.command`** (steps
  1–7 before step 8). A cached command receipt can never be returned for an
  envelope whose key no longer authenticates — probe P2 returned
  `EVIDENCE_AUTHENTICATION_FAILED` for the *accepted original* envelope under
  the rotated gateway with its receipt cached and zero writes. The design
  forbids moving dedup ahead of authentication (RFC-003 §3 D16: replays must
  not bypass identity verification).
- **Replay denial never mutates**: gateway steps 1–7 write nothing; runtime
  replay denials are fresh and unpersisted (`runtime.py:270-272`); old
  receipts, evidence rows and versions stay verbatim.
- **Re-sign under the new key dedupes**: same `(source, event_id)`, same
  content, any valid key → same evidence id and current status, one new
  command row, no artificial business row (probe P3 — fingerprints exclude
  key/selector/timestamp material). Changed content stays
  `SOURCE_EVENT_CONFLICT` (probe P5).

### 4.7 Admission, authority and source-confusion boundaries (unchanged)

Approved kinds only: `accepted` reserved at the gateway (probe P12); the S10
`withdrawn` kind stays refused by the authority mapping
(`evidence_sources` has no such kind) as an authenticated, persisted
`AUTHORITY_DENIED`; `OPERATION_ID_RESERVED` protection unchanged
(`runtime.py:793-797`). Grants, revoke authority and evidence-source mapping
are keyed by **source name** — a rotated key inherits exactly the source's
existing rights, a new key alone grants nothing, and no key can bypass,
revoke or impersonate another source's proofs: that requires that source's
distinct material (global distinctness, §4.3; probe P10). The gateway remains
`record_evidence`-only; dispatch, reconciliation and completion stay
trusted-local.

### 4.8 History preservation (byte-identical)

Rotation is authentication-layer-only: no new store writes, schema stays
`1`, and every pre-rotation row of `works`/`commands`/`evidence`/
`operations`/`events` stays byte-identical across cutover and subsequent
activity (probes P9/P9b — append-only tables; the `works` row changes only
when new evidence evaluation legitimately bumps `state_version`). Verified
proofs, confirmed operations, closure snapshots and compensation receipts
are never rewritten by anything here — the same invariant S8/S10 established
for revocation and compensation.

### 4.9 Legacy compatibility (explicit per-source)

- A source configured as legacy bytes keeps today's behavior **unchanged** —
  same envelopes, same single key, `key_id` envelopes rejected.
- A source configured as a keyring authenticates legacy (no-`key_id`)
  envelopes against its **current entry only** — the migration bridge that
  lets signers stay on the legacy format while the keyring rolls out, and the
  rule that guarantees a retired old key is never silently accepted on the
  legacy path (SKR-7).
- Which key authenticated an envelope is **not** recorded in the store —
  consistent with signatures/timestamps never being persisted
  (`signed-evidence.md` Gateway checks); the operator's keyring
  configuration is the only place key identity lives (truthful limitation,
  §12).

### 4.10 Signer surface

`sign_evidence(secret, message)` — signature unchanged. The message may now
carry the optional `key_id` (validated like the other identity fields:
nonempty string when present; included in the signed canonical bytes; the
returned envelope is the usual detached copy). The signer does not know
keyrings — it signs with whatever secret it is handed, so rotating signers
means handing them the new secret plus its `key_id`, nothing else.

### 4.11 Store, schema and dependency posture

Schema stays `1`; zero new runtime dependencies (stdlib `hmac`, `hashlib`,
`typing`); Python ≥3.9; all changes additive to `work_runtime/ingress.py`
(+ new demo module/CLI in the demo wave). The published KAT vector
(`test_ingress.py:40-47`) must keep passing verbatim — it pins the legacy
7-field canonicalization, which is untouched.

### 4.12 Read-only visibility (no UI change)

No viewer, GUI or website change; no timeline stage invented. The design
adds no store rows, so existing read surfaces are unaffected by
construction.

## 5. Public API summary (builder-ready)

```python
from typing import NamedTuple, Optional, Sequence

class SourceKey(NamedTuple):
    key_id: str
    secret: bytes
    current: bool = False
    not_before: Optional[int] = None
    not_after: Optional[int] = None

# keys: Dict[str, bytes] | Dict[str, Sequence[SourceKey]]  (per-source, one shape)
SignedEvidenceGateway(runtime, keys, max_age: int = 300,
                      clock: Callable = time.time)
# record(envelope) receipt codes (additive):
#   EVIDENCE_ENVELOPE_INVALID | EVIDENCE_AUTHENTICATION_FAILED
#   | EVIDENCE_KEY_NOT_YET_VALID | EVIDENCE_KEY_RETIRED   (new, post-HMAC)
#   | EVIDENCE_EXPIRED | EVIDENCE_KIND_UNSUPPORTED
sign_evidence(secret: bytes, message: dict) -> dict   # message may add key_id
SIGNED_FIELDS       # unchanged seven-field tuple
OPTIONAL_KEY_FIELD  # new: "key_id", the single admitted extra signed field
```

## 6. Proposed tests (RED → GREEN; named, public API, real stores)

New file `tests/test_key_rotation.py` (SKR-8); every existing test in
`test_ingress.py` must keep passing unchanged. RED = fails on the current
tree (no keyring parameter, no `key_id` field, no new codes); GREEN = the
designed behavior. Deterministic clocks throughout (`clock=lambda`); real
SQLite runtimes; synthetic ephemeral keys.

| # | test | RED → GREEN |
|---|---|---|
| T1 | `test_keyring_requires_unique_key_ids_and_secrets` | ValueError on duplicate id/secret within a keyring |
| T2 | `test_keyring_requires_exactly_one_current_entry` | ValueError on zero or multiple `current` |
| T3 | `test_keyring_validates_windows_and_secret_length` | ValueError on `not_before > not_after`, short secret |
| T4 | `test_secret_material_distinct_across_entire_config` | ValueError when any two entries (any source) share bytes |
| T5 | `test_key_id_envelope_accepted_against_keyring` | accepted; `key_id` present in signed bytes |
| T6 | `test_tampered_key_id_fails_authentication` | any `key_id` mutation → `EVIDENCE_AUTHENTICATION_FAILED`, zero writes |
| T7 | `test_unknown_key_id_rejected` | `EVIDENCE_AUTHENTICATION_FAILED`, zero writes |
| T8 | `test_bad_key_signature_rejected` | wrong secret, known `key_id` → `EVIDENCE_AUTHENTICATION_FAILED` |
| T9 | `test_retired_key_rejected_after_not_after` | correct signature, past window → `EVIDENCE_KEY_RETIRED`, zero writes |
| T10 | `test_not_yet_valid_key_rejected` | → `EVIDENCE_KEY_NOT_YET_VALID` |
| T11 | `test_window_bounds_inclusive_at_edges` | `clock()==not_before` / `==not_after` accepted |
| T12 | `test_window_precedes_freshness_code` | retired + stale envelope reports `EVIDENCE_KEY_RETIRED` |
| T13 | `test_retired_code_requires_valid_signature` | garbage signature + retired window → `EVIDENCE_AUTHENTICATION_FAILED` (no oracle) |
| T14 | `test_key_id_envelope_against_legacy_source_rejected` | legacy bytes source → `EVIDENCE_AUTHENTICATION_FAILED` |
| T15 | `test_legacy_envelope_authenticates_against_current_entry_only` | legacy envelope signed with non-current key → `EVIDENCE_AUTHENTICATION_FAILED` (never silent acceptance) |
| T16 | `test_legacy_bytes_source_behavior_unchanged` | legacy config passes today's semantics verbatim |
| T17 | `test_resign_same_event_under_new_key_dedupes` | same `(source, event_id)` + same content under K2 → same evidence id/status, commands +1 (probe P3 as regression) |
| T18 | `test_retired_key_replay_cannot_reach_cached_receipt` | accepted original, then rotate past window: exact replay → `EVIDENCE_KEY_RETIRED`, tables unchanged (probe P2) |
| T19 | `test_history_rows_byte_identical_across_rotation` | row-prefix equality over all five tables (probes P9/P9b) |
| T20 | `test_deterministic_restart_same_config_same_decisions` | fresh gateway from same config + same clock → identical receipts |
| T21 | `test_clock_injection_drives_windows_and_freshness_together` | one injected clock moves both boundaries |
| T22 | `test_config_copied_at_construction_keyring` | post-construction mutation of keyring structures changes nothing (probe P11) |
| T23 | `test_receipts_remain_minimal_no_key_echo` | every new-code receipt is exactly `{decision, code}` |
| T24 | `test_signer_accepts_and_signs_optional_key_id` | signer round-trip; wrong-type/empty `key_id` → ValueError |
| T25 | `test_known_answer_vector_legacy_unchanged` | `84ba6259…c04ec08` still reproduced (must pass before AND after) |

## 7. Demonstration and installed verification (no new global gate)

A no-credentials `python3 -m work_runtime rotation-demo` (name: SKR-10),
deterministic via an injected clock and ephemeral in-memory keys (never
printed — only key ids): dual-key window accept → rotate + grace boundary →
retired refusal with `EVIDENCE_KEY_RETIRED` while the cached receipt stays
unreachable → re-sign under the new key deduping to the same evidence id →
history digest byte-identical before/after → closing PASS line; runs with
the working directory outside the checkout (existing demo discipline).
`scripts/verify_install.py` gains a rotation-demo stage (module + console,
outside the checkout) **as part of the existing installer evidence, not a
new global gate** (SKR-10). The five supervibe gates and the six existing
demos stay exactly as they are; the rehearsal set is untouched.

## 8. Documentation ownership and same-commit rules

- `work_runtime/ingress.py` changes owe `docs/signed-evidence.md` in the same
  commit (envelope table, gateway precedence incl. the two new codes, key
  handling/rotation section, limitations). The AGENTS `doc_sync_map` has no
  ingress row today — adding one is a working-agreement change the master
  owns (SKR-9; recommended: add at ratification).
- The test file owes a coverage paragraph in `docs/verification.md`
  (S-wave coverage section) in the same commit.
- README/README.zh-CN demo list entry rides with the demo wave;
  `docs/roadmap.md` 0.2 note and any ledger flip are master-owned close acts.

## 9. Delivery waves and dependencies

- **W1 — ingress core + docs**: `ingress.py` + `tests/test_key_rotation.py`
  (+ `test_ingress.py` untouched) + `signed-evidence.md` + `verification.md`;
  TDD with recorded RED/GREEN; baseline 809/3-skips preserved and grown
  additively.
- **W2 — independent review + demo**: fresh independent design/code review
  session (the review this DRAFT explicitly awaits), then
  `rotation_demo.py` + CLI + README + installer stage + demo tests/reports.
- **W3 — integration**: the integration session alone merges and pushes
  (ordinary `--no-ff`, never force-push main); workers never merge/push.

## 10. Alternatives considered

- **Try-every-key verification without a selector**: rejected — a retired key
  would keep authenticating legacy envelopes (silent acceptance), selection
  becomes order-dependent, and every intake costs N HMACs.
- **Envelope version field (`envelope_v: 2`)**: rejected — strictly more
  envelope machinery than one optional signed field; the exact-field-set
  discipline admits `key_id` cleanly.
- **Numeric `epoch` in addition to/instead of `key_id`**: rejected — a second
  authenticated selector with ordering rules to define and enforce; a
  disciplined `key_id` namespace (operator convention, e.g. dates or counters)
  subsumes it without runtime enforcement (SKR-11).
- **Asymmetric signatures (ed25519)**: rejected — stdlib-only constraint and
  the shared-key trust boundary is the documented model; changing crypto
  agility is a different, larger promise.
- **Live managed key registry (Option B)**: deferred, §4.1/SKR-1.
- **Store-clock key state (persisted activation times)**: rejected — creates
  a second time authority, store writes on rotation, and restart-ordering
  questions; configuration + the existing injectable clock is deterministic
  and write-free.

## 11. Unresolved master decisions (each with recommendation)

| # | decision | recommendation |
|---|---|---|
| SKR-1 | Option A config keyring vs Option B managed registry | **A now**; B as separately designed future work |
| SKR-2 | Selector field: optional signed `key_id` vs versioned envelope | **optional signed `key_id`** (§4.2) |
| SKR-3 | Fold window rejections into `EVIDENCE_AUTHENTICATION_FAILED` vs two post-HMAC codes | **keep `EVIDENCE_KEY_RETIRED` + `EVIDENCE_KEY_NOT_YET_VALID`** (operator-actionable, no stranger oracle) |
| SKR-4 | Window check before vs after freshness | **before** (retirement is the more specific fact; T12) |
| SKR-5 | Current-entry designation: exactly-one `current` flag vs ordered-last | **`current` flag** (explicit > positional, matches codebase style) |
| SKR-6 | Window time domain | **same injectable `clock` as freshness**, inclusive bounds, no store time |
| SKR-7 | Legacy envelope against a keyring source | **authenticate against the `current` entry only** (migration bridge; retired never silent) |
| SKR-8 | Tests: new `tests/test_key_rotation.py` vs extend `test_ingress.py` | **new file**; keep `test_ingress.py` as the untouched legacy pin |
| SKR-9 | Add AGENTS `doc_sync_map` row `ingress.py → signed-evidence.md` | **add at ratification** (working-agreement change is the master's) |
| SKR-10 | Demo name + installer stage vs new global gate | **`rotation-demo` + `verify_install.py` stage; no new global gate** |
| SKR-11 | Retired `key_id` reuse after removal from config | **documented operator discipline** (uniqueness enforced within one config only; no history store to enforce across configs — truthful) |
| SKR-12 | Any convenience rotation helper API | **none** — configuration is the only rotation surface (no invented in-memory protection, probe P11) |

## 12. Explicit future work and truthful limitations (carried, not pre-decided)

- Option B managed/audited key registry (rotation as a governed command with
  its own authority design); rotation audit rows in the event log.
- Config distribution/consistency across multiple gateway processes;
  federated revocation; hot reload.
- A compromised **current** key is forgeable until rotation lands and grace
  expires — inherent to shared-key HMAC; wall-clock trust is the operator's
  (injectable in tests; `recover`'s default `time.time()` use is unrelated
  and unchanged).
- Which key authenticated an envelope is not persisted (authentication-layer
  data, like signatures); the store cannot answer "was this proof admitted
  under K1 or K2".
- `key_id` namespaces are per-source; no global registry, no cross-source
  id coordination; retired-id reuse after removal is operator discipline
  (SKR-11).
- No tenant auth, TLS, KMS, distributed exactly-once, or production-safety
  claim anywhere in this design; every principal remains trusted-local
  configuration.

## 13. Designer self-check (grounded vs recommendation)

Grounded (code/probe-cited at `b594d757`): §1 gaps and invariants (P1–P13,
P9b); the unchanged-machinery claims of §4.6–§4.8; baseline gates (recon
§0); KAT vector; admission behavior. Recommendations, not facts: §3 scope,
Option A (SKR-1), the envelope/API shapes of §4.2/§4.3/§5, code choices
(SKR-3/4), wave split. Open until ratification + independent review: every
SKR row; the demo's exact printed narrative; installer stage wording. This
document claims no implementation, no sprint allocation and no acceptance.

## MASTER ratification - 2026-10-15 D49-D53 (before implementation)

Master owns these choices under user autonomous authorization. This section overrides conflicting DRAFT text. Independent [ce07781 review](../../../.agents/notes/2026-10-15-source-key-rotation-independent-design-review.md) supplies F1-F4/M1-M4 corrections; original draft1ef6735 remains history. SKR1-SKR12 recommendations ratified as amended below.

- **D49 scope/format:** Option A config-only rotation, no managed/audited live registry or schema changes. SourceKey NamedTuple fields/signature and optional signed key_id from draft. Seven-field SIGNED_FIELDS and old KAT unchanged; key_id participates canonical HMAC bytes when present, never business fingerprint/store. No try-all-keys. Legacy bytes source rejects key_id envelopes; keyring no-key_id selects CURRENT only, including valid happy path and inactive-current denial tests. Same source rights remain name-configured; accepted gateway-reserved/withdrawn mapping-denied unchanged.
- **D50 configuration:** keys remains dict; legacy validation behavior preserved. Ring accepts list or tuple ONLY, nonempty, every entry isinstance(SourceKey), normalized per-source tuple copied at construction; no generators/strings/bytes-as-sequence or alias to caller list. Ring key_id type exactly str/nonempty, secret exactly bytes/min32, current exactly bool, windows None or exact int (bool forbidden), lower<=upper if both; exactly one current, unique IDs per source, secret bytes globally unique across ALLentries/sources. Legacy source name/secret compatibility unchanged. Caller outermap/innerlist mutation never changes normalized gateway config. This is copying user-supplied config, not protection against arbitrary direct mutation of Python gateway internals or deployment config rollback.
- **D51 auth/time:** shape/source/selector/HMAC first, single clock sample shared by window+freshness AFTER successfulHMAC, then keywindow beforefreshness beforeacceptedkind/runtime. Clock sample exact int/float (notbool), finite epoch seconds; nonfinite/wrongtype or clock raising ordinary Exception returns minimal {decision:rejected,code:EVIDENCE_CLOCK_INVALID}, zero runtime calls/writes. Do not catch BaseException; invalid runtime clock is operator configuration failure, not bad signature/expired evidence. Validate finiteness safely on hugeints without leaking overflow; single call only, no retry/second sample. Window current VERIFICATION time, never issued_at, inclusivebounds; futureissued_at cannotbackdate retirement. Existing max_age semantics and legacyfiniteclock behavior preserved, NaN fail-open intentionally fixed. Newclock code plus post-HMAC EVIDENCE_KEY_NOT_YET_VALID/EVIDENCE_KEY_RETIRED exactminimalno keyecho. Unknown/dropped key AUTHENTICATION_FAILED vs retained expired key KEY_RETIRED; both deny but CODEdiffers. Old K1 no-key_id failsHMACagainstcurrentK2 regardlessretainedentry. Grace>=max_age onlyoperatorrecommendation, no distribution/compromise guarantee.
- **D52 replay/history:** everyrequestauthenticates beforeRuntimecache. Samecommand_id/payload re-signed byvalidnewkey returnsORIGINALcachedreceipt/status/version byte-verbatim zero writes, including evidence-now-revoked; NEWcommand_id/sameevent content returnssameproofid/CURRENTstatus with one extra commandrow, oldreceiptunchanged. Grantloss freshunpersistedAUTHORITY_DENIED. Changedpayloadsameevent SOURCE_EVENT_CONFLICT unchanged. Gatewayreconstruction/denial allSIXtables unchanged inclmetadata; legitimateingress followsnormal businessmutation, no universal works-rowprefix equalityclaim. Rotation neverrevokes evidence/effects/closure/compensation. Retired key_id reuse/configrollback canrevivekey because no persistentrevocationmemory; record explicitly. Retaining expiredmaterial preservespostHMAC retirementobservability, droppingremoves it. No key-auth provenance persisted.
- **D53 execution/release:** new keyrotation tests T1-T25 plus F1-F4/M2positivelegacy/currentwindow/type/innercopy/singleclock/nonfinite/error/samplecount/re-signcache/revoked/grantloss cases. Original40 ingress tests/KAT untouched. One ingresscore owner scopedplan/TDD/samecommit signed-evidence docs andcurrentverification; independent core review/assembly thenrotation-demo+CLI/README/installactualmoduleconsole outsidecheckout, fiveexistinggates unchanged/seven demosexplicit. Full809baseline3skips/15rehearsal1skip andinstalledverifyserial; no UI/sourcebusinessauthority/schema change. Master adds AGENTdoc_sync ingress.py->signed-evidence.md now, worker never changes agreement. Independent acceptance then integrationordinarymainmerge/nonforcepush/exactfinalremoteCI andpreservedtrees/preview. No tenants/TLS/KMS/distributedrevocation/securitycertification claim.

All review amendments resolved before code. Clock invalid result is new bounded configuration-failure code, deliberately extends legacy trusted-clock failure handling with fail-closed evidence.
