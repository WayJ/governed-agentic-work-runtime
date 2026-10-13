# S2 design review — read-only builder check before implementation

Date: 2026-10-13. Checkout: `s2-release-control` @ `7dd96a3` (branch `WayJ/s2-release-control`).
Scope: S2 spec (`docs/superpowers/specs/2026-10-13-s2-trusted-boundaries.md`), S2 sprint plan, and the
Runtime surfaces they touch (`command`/`_receive`/`dispatch`/`_resolve`, Policy protocol, FakeOA, CLI/demo/CI/docs
gates). No historical corpus reread, no architecture redesign. Baseline gates run in this checkout:
63/63 tests green, `scripts/check_docs.py` 0 broken links.

## Verdict

Implementable as specified at the architecture level: the wave ownership split is genuinely disjoint, the
dependency order (foundations → carrier merge → publishing) is sound, and the S1 baseline survives the planned
`_resolve` change (no existing test pins the literal `"oa"` evidence source — only FakeOA `external_id`
prefixes). The blocking items below are decision gaps that would make two wave-1 workers guess differently,
not design flaws; each has a one-line suggested default.

## Blocking — settle before wave-1 RED tests

### B1. Gateway error taxonomy gaps: HMAC canonicalization failure and unknown source
`canonical()` is `json.dumps(..., allow_nan=False)` (`work_runtime/policy.py:8-10`): it raises `TypeError` on
non-JSON-serializable values and `ValueError` on NaN/Infinity — and Python's `json.loads` accepts
`NaN`/`Infinity` literals, so a parsed envelope can carry uncanonicalizable `data` into
`SignedEvidenceGateway.record()`. The spec lists three codes
(EVIDENCE_ENVELOPE_INVALID / EVIDENCE_AUTHENTICATION_FAILED / EVIDENCE_EXPIRED) and six failure modes but never
maps (a) a canonicalization raise at verification time or (b) an unknown/unconfigured source to a code.
Suggested defaults: record() catches `TypeError/ValueError` from canonicalizing the candidate →
EVIDENCE_ENVELOPE_INVALID, before any runtime call; unknown source → EVIDENCE_AUTHENTICATION_FAILED;
`sign_evidence` validates first and raises `ValueError` (caller misuse) rather than signing uncanonicalizable
content.

### B2. "Fail closed on invalid configuration" for the policy-owned accepted source names no mechanism
Foundation A replaces the hard-coded `"oa"` proof source in `_resolve` (`work_runtime/runtime.py:481-485`) with
`policy.evidence_sources['accepted']` and says "fail closed … before accepting results", but specifies no
check site, error class, or definition of "effect-using policy" (the Policy protocol has no such flag; the
evidence PK is `(source, event_id)`, so an empty source must never reach INSERT). Suggested default:
`dispatch()` and `reconcile()` require `evidence_sources.get("accepted")` to be a nonempty string before the
external call / result adoption and raise `CommandError` (the established local-API-misuse class,
`runtime.py:18-19`); do not quarantine a valid adapter result as ADAPTER_RESULT_INVALID. The publishing wave
depends on this shape being fixed in wave 1.

### B3. Conformance mixin's "declared actions" test cannot be behavioral
The mixin owns only adapter-level hooks (`make_adapter`/`sample_document`/`changed_document`/`effect_count`),
and `execute(key, document, content_digest)` (`work_runtime/runtime.py:22-24`) carries no capability — an
adapter cannot be asked to attempt an unsupported action; only `Runtime.dispatch` can produce
ADAPTER_ACTION_UNSUPPORTED. Every other listed mixin test is adapter-level; this one reads as dispatch-level.
Suggested default: the mixin asserts contract metadata invariants (frozen `AdapterContract` fields present;
`actions` a nonempty tuple of unique nonempty strings; `uniqueness` entries nonempty); the
zero-attempts/zero-effects exclusion test stays in each domain's `test_*` file where a Runtime exists.

## Minor — builder-decidable, flag for the record

- **M1. `accepted` evidence is ingestible through the gateway.** `evidence_sources` maps kind→source, so a
  holder of the accepted source's key (publisher) can sign `kind='accepted'` and mint C04-satisfying evidence
  with zero external dispatch; holding all configured keys could close a work with no operations at all.
  Within the shared-key boundary that is "authentic", but docs must not claim accepted evidence only
  originates from dispatch. Suggest gateway refusal of kinds mapping to the accepted-receipt source, or an
  explicit key-custody constraint in `docs/signed-evidence.md`. Related: the gateway's `keys` dict should
  reject identical key material configured for two sources (silent cross-source impersonation); "invalid
  configuration fails clearly" should cover >=32-byte length and distinctness.
- **M2. Replay semantics to document, not change.** Exact-envelope replay is honored only within `max_age`
  (a once-valid envelope re-sent later → EVIDENCE_EXPIRED); durable identity comes from source/event dedup
  across command IDs — the fingerprint `digest([work_id, payload])` excludes the timestamp
  (`runtime.py:348`), matching the spec. Also `(source, event_id)` is unique per database across works: the
  same event id delivered against another work is SOURCE_EVENT_CONFLICT, not dedup. One sentence each in
  `docs/signed-evidence.md`.
- **M3. ADAPTER_ACTION_UNSUPPORTED ordering.** Suggest checking the contract after grants/blockers,
  immediately before marking dispatched/in_flight: no attempt appended, `status` stays `prepared`,
  `dispatch_state='held'`. Verified compatible with re-dispatch and readmission (`runtime.py:323` treats
  `held`; `dispatch` short-circuits only non-prepared or cancelled), satisfying "a compatible adapter can
  later dispatch that same held operation".
- **M4. Policy-owned-source adoption test must not be vacuous.** ExpensePolicy keeps `accepted='oa'`, so
  asserting source == `evidence_sources['accepted']` also passes against the old hard-coded `'oa'`.
  `tests/test_adapter_contract.py` should use a small test-local policy whose accepted source is not `'oa'`
  (adapter-worker scope; sprint D4 vacuous-GREEN lesson).
- **M5. PublishingPolicy needs an `accepted` branch in `validate_evidence`.** The runtime-generated proof is
  kind `accepted`, data `{digest, external_id}`, born verified (`runtime.py:481-483`); without a matching
  branch every publication result is marked invalid and C04 never satisfies. Make it explicit in the
  publishing plan; C01–C04 otherwise fit the evaluate/action_blockers/operation_key protocol, and the
  digest-based operation key (vs expense's document_revision key, `policy.py:136-138`) is fine — the
  `operations.business_key` UNIQUE constraint enforces one operation per content.

## Verified consistent (no action needed)

- Ownership partition is disjoint and feasible: adapter worker (`runtime.py`, `adapters.py`,
  `adapter_contract.py`, two test files, `docs/adapter-contract.md`, `docs/runtime-boundaries.md`), ingress
  worker (no Runtime changes — the gateway needs only the public `command()`/`verify_pending()` surface;
  runtime itself rejects ungranted sources), publishing worker (everything else). Wave order matches the
  dependency: publishing needs both the mixin and the gateway, and the spec mandates it start from the merged
  carrier (D3).
- `doc_sync_map` (`runtime.py`, `adapters.py` → `docs/runtime-boundaries.md`, same commit) matches Foundation
  A; `check_docs.py` excludes `.agents` notes and validates links in newly added docs.
- Same Runtime class with separate databases is directly supported (`Runtime(path, policy, grants)`); the
  contract check (`runtime.py:92-93`) catches cross-policy works while evidence carries no policy marker —
  one-policy-per-DB remains a documented prototype constraint, as the spec states.
- CI additions fit the existing `ci.yml` step list; sprint scenarios S1–S6 reference gates/commands that
  exist or are specified; the publishing demo flow maps onto existing API (propose → dispatch(fault) →
  outcome_unknown → reconcile → request_completion).
- Sprint metadata consistent: worktree branch `WayJ/sprint-s2-trusted-boundaries` exists; baseline is the
  merged S1 state (`0d39af9`).

## Bounded questions for the coordinator

1. **B1**: Confirm gateway code mapping — canonicalization failure → EVIDENCE_ENVELOPE_INVALID, unknown
   source → EVIDENCE_AUTHENTICATION_FAILED, `sign_evidence` raises ValueError on invalid/uncanonicalizable
   input — or state the preferred mapping to fold into the ingress dispatch brief.
2. **B2**: Confirm fail-closed site/mechanism — `dispatch()`/`reconcile()` raise CommandError when
   `evidence_sources.get('accepted')` is not a nonempty string, before any external call/adoption — versus
   the alternative of validating once in `Runtime.__init__`.
3. **M1**: Should the gateway refuse evidence kinds that map to the policy's accepted-receipt source, or is
   documenting the key-custody constraint in `docs/signed-evidence.md` sufficient for S2?
