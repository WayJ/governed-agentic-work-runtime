# Adapter contract

How an external adapter declares what it does, how the runtime validates the
results it returns, and which evidence source owns an accepted receipt. The
interfaces live in `work_runtime/adapter_contract.py`; the runtime-side gates
live in `work_runtime/runtime.py` (see [runtime-boundaries.md](runtime-boundaries.md)
for the surrounding dispatch/reconciliation guarantees).

**These are trust-boundary statements, not security claims.** Contract fields
are assertions the adapter's owner makes about the external system —
configuration for trusted local code, not remotely verified guarantees.
Declaring metadata does not authenticate an adapter: anyone who can hand the
runtime an adapter object is already trusted local code.

## The `AdapterContract` dataclass

A frozen dataclass with five required fields:

| field | meaning |
|---|---|
| `actions` | tuple of capability names the adapter claims to execute |
| `idempotency_scope` | what the external idempotency key is scoped to |
| `retention` | how long the external system remembers receipts |
| `lookup_consistency` | what a key lookup is authoritative for |
| `uniqueness` | tuple of external uniqueness promises beyond key replay |

Construction validates the invariants (`ValueError`): `actions` is a nonempty
tuple of unique nonempty strings; `idempotency_scope`, `retention` and
`lookup_consistency` are nonempty strings; `uniqueness` is a tuple of nonempty
strings. An empty `uniqueness` tuple is valid and asserts no additional
uniqueness promise beyond idempotent replay. `valid_contract(value)` re-checks
everything and returns `bool` — the runtime uses it to fail closed on
malformed descriptors.

## Receipt validation

`receipt_is_valid(result, expected_digest) -> bool` is the single check the
runtime applies to every result returned by `execute` or `lookup`. A result
counts only when it is a dict whose `digest` equals the operation's document
digest, whose `status` is `accepted` or `rejected`, and whose `external_id` is
a nonempty string. **Extra fields remain allowed** so compatible adapters can
enrich receipts without being quarantined. Anything else is quarantined as
`outcome_unknown`/`ADAPTER_RESULT_INVALID` with the work in `needs_attention`
(the quarantine and its recovery are documented in
[runtime-boundaries.md](runtime-boundaries.md)).

## Optional metadata and legacy adapters

Only an **absent** `contract` attribute is the legacy path: adapters without
one (all S1 test adapters, and any trusted duck-typed adapter) get no
capability gating, identical pre-S2 dispatch behavior. A descriptor that is
**present** but is not a valid `AdapterContract` — a string, a dict, an
explicit `None`, or an incomplete/tampered instance (including
`object.__new__` bypasses that never set fields) — fails closed with
`CommandError` **before** any external call: garbage metadata is never
silently treated as "no metadata", and `contract = None` is a malformed
declaration, not an opt-out.

## Declared-capability preflight

Inside `dispatch`, after the authority and requirement re-checks and
immediately before the attempt is created, the runtime consults the declared
contract (M3/M4 ordering — grant/rule checks run first):

- If a declared `actions` tuple **excludes** the operation's capability, the
  prepared operation is **held** with `dispatch_state="held"` and
  `reason="ADAPTER_ACTION_UNSUPPORTED"` — zero `attempts` entries, zero
  external calls, zero effects — and the work stays out of `needs_attention`.
- The held operation remains dispatchable: calling `dispatch` again with a
  **compatible** adapter (one whose contract includes the capability) runs the
  same checks and dispatches normally. `recover` never auto-dispatches held
  intents, matching the existing hold semantics.
- The preflight is a local claim check only: it does not verify that the
  external system actually performs the capability.

## Policy-owned accepted receipt source

When a result is accepted, the runtime records verified evidence (kind
`accepted`, event id = the operation id) under the source configured at
`policy.evidence_sources["accepted"]` — replacing the S1 hard-coded `"oa"`.
The expense demo keeps `"oa"`, so all S1 behavior is unchanged.

The configuration fails closed (`CommandError`) when the accepted source is
missing, non-string or empty, checked in three places:

| call site | when |
|---|---|
| `dispatch` | before an attempt or external call is started |
| `reconcile` | before querying the adapter |
| `_resolve` | before adopting an accepted receipt as a proof |

Invalid policy configuration is a local misuse, never an invalid adapter
result: it can never become an accepted proof. If the configuration breaks
between the external effect and the resolution, the proof is not written, the
operation stays `dispatched` with its `outcome_unknown` attempt, and fixing
the configuration lets `reconcile` adopt the receipt normally. Terminal and
cancelled-operation early returns are unaffected by the check.

## FakeOA's declared contract

```python
AdapterContract(actions=("expense.submit",),
                idempotency_scope="adapter-store:key",
                retention="lifetime-of-store",
                lookup_consistency="authoritative-by-key",
                uniqueness=("invoice.id",))
```

| value | assertion |
|---|---|
| `actions=("expense.submit",)` | executes only the expense submit capability |
| `idempotency_scope="adapter-store:key"` | idempotency keys are scoped to its own SQLite store |
| `retention="lifetime-of-store"` | receipts persist as long as the store file exists |
| `lookup_consistency="authoritative-by-key"` | a key lookup returns the committed receipt |
| `uniqueness=("invoice.id",)` | one external acceptance per invoice id across all keys |

## Reusable conformance tests

`tests/adapter_conformance.py` provides `AdapterConformanceMixin`, a plain
class (not a `TestCase`) that a domain adopts next to `unittest.TestCase`,
implementing four fixture hooks:

| hook | requirement |
|---|---|
| `make_adapter()` | a fresh **disposable** adapter instance — the tests mutate its store |
| `sample_document()` | a valid document for a declared action |
| `changed_document()` | a valid document with a **different digest** |
| `effect_count(adapter)` | external effects committed so far |

The mixin runs five tests: declared metadata invariants (frozen valid
`AdapterContract`); same-key/same-payload replay returns the identical receipt
with exactly one effect and a `receipt_is_valid` shape; same key with different
content raises `ValueError` without a second effect; `lookup` of the committed
key matches the receipt; `lookup` of a missing key returns `None`.

Domain-specific uniqueness (FakeOA's invoice-id uniqueness, a publisher's
`(document.id, digest)` uniqueness) is deliberately **not** in the mixin — each
domain tests its own external constraints separately.

## Verification

`tests/test_adapter_contract.py` (run with
`python3 -m unittest discover -s tests -p test_adapter_contract.py -v`):

| guarantee | test |
|---|---|
| accepted/rejected receipts valid, extra fields allowed | `test_valid_accepted_and_rejected_receipts` |
| non-dict results invalid | `test_non_dict_results_are_invalid` |
| missing fields invalid | `test_missing_fields_are_invalid` |
| wrong digest invalid | `test_wrong_digest_is_invalid` |
| bad status / external_id invalid | `test_invalid_status_or_external_id_is_invalid` |
| construction invariants + frozen | `AdapterContractTests` |
| FakeOA adopts the conformance mixin | `FakeOAConformanceTests` (five mixin tests) |
| accepted source is policy-owned | `test_policy_owned_accepted_source_is_adopted` |
| missing/empty/non-string source fails closed in dispatch | `test_dispatch_fails_closed_without_accepted_source` |
| reconcile fails closed before querying | `test_reconcile_fails_closed_before_querying` |
| resolution never adopts a proof under broken config | `test_resolve_fails_closed_and_never_adopts_proof_under_broken_config` |
| terminal early returns stay config-independent | `test_terminal_operation_early_returns_stay_config_independent` |
| unsupported capability holds with zero attempts/calls | `test_unsupported_declared_capability_holds_with_zero_attempts_or_calls` |
| held operation dispatches with a compatible adapter | `test_held_operation_dispatches_with_compatible_adapter` |
| malformed descriptor fails closed before effects | `test_malformed_descriptor_fails_closed_before_external_call` |
| present `None` / incomplete instance fail closed; absent stays legacy | `DescriptorPresenceTests` (three tests) |
| legacy adapters without a descriptor keep dispatching | `test_legacy_adapter_without_contract_still_dispatches` |

Design source: [S2 spec](superpowers/specs/2026-10-13-s2-trusted-boundaries.md)
(Foundation A; builder decisions B2/B3/M3/M4 in the D8 addendum).
