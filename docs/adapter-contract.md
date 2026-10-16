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

A frozen dataclass with five required fields plus one defaulted opt-in:

| field | meaning |
|---|---|
| `actions` | tuple of capability names the adapter claims to execute |
| `idempotency_scope` | what the external idempotency key is scoped to |
| `retention` | how long the external system remembers receipts |
| `lookup_consistency` | what a key lookup is authoritative for |
| `uniqueness` | tuple of external uniqueness promises beyond key replay |
| `supports_action_context` | `bool`, default `False`: the adapter opts into receiving the explicit action and compensation link at execution (see [opt-in action/link execution](#opt-in-actionlink-execution-context)) |

Construction validates the invariants (`ValueError`): `actions` is a nonempty
tuple of unique nonempty strings; `idempotency_scope`, `retention` and
`lookup_consistency` are nonempty strings; `uniqueness` is a tuple of nonempty
strings; `supports_action_context` is a `bool` (an `int` is rejected). An
empty `uniqueness` tuple is valid and asserts no additional uniqueness
promise beyond idempotent replay. `valid_contract(value)` re-checks
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

## Opt-in action/link execution context (S10)

An adapter whose contract asserts `supports_action_context=True` receives the
explicit action and compensation link at execution:

```python
def execute(self, key, document, content_digest, *, action=None, compensates=None)
```

- The runtime calls an opted-in adapter as
  `execute(key, document, digest, action=op_capability,
  compensates=op_link_or_None)`: forward operations pass the forward
  capability and `compensates=None`; compensations pass the paired capability
  and the immutable `{operation_id, external_id, capability}` snapshot.
- Every other adapter — no declared contract, or a contract without the
  opt-in — is invoked with **exactly the pre-S10 three positional
  arguments**. The dispatch decision reads the declared contract only: no
  signature introspection, no `inspect`, no TypeError fallback (a TypeError
  probe could fire only after an effect committed — forbidden).
- A compensation dispatched to an adapter whose effective contract does not
  assert the opt-in is held `ADAPTER_ACTION_CONTEXT_UNSUPPORTED` after the
  declared-actions preflight and before any attempt is persisted — zero
  attempts, zero external calls, work stays out of `needs_attention`,
  re-dispatchable with an opted-in adapter. Declaring the action without the
  opt-in is not enough: the adapter could not receive the binding link.
- The action is derived solely from the operation's capability and the link
  solely from the runtime-validated operation body; nothing in `document`
  can select or influence the action. `action=None` meaning "forward" is
  FakeOA-side normalization for its own legacy direct callers, not a
  protocol rule.

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
AdapterContract(actions=("expense.submit", "expense.withdraw"),
                idempotency_scope="adapter-store:key",
                retention="lifetime-of-store",
                lookup_consistency="authoritative-by-key",
                uniqueness=("invoice.id", "withdrawal.original_external_id"),
                supports_action_context=True)
```

| value | assertion |
|---|---|
| `actions=("expense.submit", "expense.withdraw")` | executes the expense submit capability and its paired withdrawal |
| `idempotency_scope="adapter-store:key"` | idempotency keys are scoped to its own SQLite store |
| `retention="lifetime-of-store"` | receipts persist as long as the store file exists |
| `lookup_consistency="authoritative-by-key"` | a key lookup returns the committed receipt |
| `uniqueness=("invoice.id", "withdrawal.original_external_id")` | one external acceptance per invoice id and one withdrawal effect per original across all keys |
| `supports_action_context=True` | opts into explicit action/link execution context |

The policy side of the pairing (`ExpensePolicy.compensation_capabilities`
maps `expense.withdraw` to `expense.submit`, inherited by `ExpensePolicyV2`)
lives in `work_runtime/policy.py`; admission semantics are specified in
[runtime-boundaries.md](runtime-boundaries.md).

## FakeOA store schema, migration and counters (S10)

`receipts` is the per-key call/lookup surface for both actions; `withdrawals`
is the per-original effect surface. Opening a store runs one `BEGIN IMMEDIATE`
transaction that creates any missing table, probes
`PRAGMA table_info(receipts)` **inside the transaction**, and adds the two
nullable identity columns when absent — concurrent first-open and re-open are
therefore race-free (no duplicate-column error), and pre-S10 stores open
unchanged:

```sql
-- legacy columns, unchanged shape for old rows
CREATE TABLE IF NOT EXISTS receipts (
    key TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL);
-- additive identity columns (NULL = legacy forward row / no link)
ALTER TABLE receipts ADD COLUMN action TEXT;
ALTER TABLE receipts ADD COLUMN link_digest TEXT;
CREATE TABLE IF NOT EXISTS withdrawals (
    original_external_id TEXT PRIMARY KEY, external_id TEXT NOT NULL,
    key TEXT NOT NULL, digest TEXT NOT NULL);
```

Every receipts write uses named columns. New forward rows store the explicit
action `"expense.submit"`; legacy rows keep `NULL`, normalized to the forward
action on read (FakeOA-side policy for its own legacy direct callers — a
legacy three-positional `execute(key, document, digest)` call behaves exactly
as before). Replay of an existing row — forward or withdrawal — validates the
digest, the normalized action and the link fingerprint (`digest(compensates)`
for withdrawals, `NULL` for forward); any mismatch raises
`ValueError("Idempotency key reused with different content")` with zero new
effects, so a key can never be replayed across actions or links.

**Counters (both derived from the SQLite store, never stdout):**
`accepted_count()` is the number of **distinct accepted forward effects** —
receipt rows with `status == "accepted"` whose action is `NULL` (legacy) or
`"expense.submit"`, counted by distinct `external_id` (direct zero-invoice
acceptances included; withdrawal and alias receipts excluded).
`withdrawn_count()` is the `withdrawals` row count — exactly one withdrawal
effect per withdrawn original. Original `receipts`/`invoices` rows are never
deleted or rewritten.

### Withdrawal execution (per-key receipts + per-original effects)

An opted-in withdrawal call carries the runtime-validated immutable link
(`compensates` = `{operation_id, external_id, capability}`); nothing in the
document can select or influence the action. Input guards run before any
write (`ValueError`): unknown action; a withdrawal without a well-formed
three-field link; a forward call carrying a link. Then, inside one
`BEGIN IMMEDIATE` transaction:

1. **Existing receipts row under the key** → replay only when the digest,
   the normalized action and the link fingerprint (`digest(compensates)`)
   all match; any mismatch is the established
   `ValueError("Idempotency key reused with different content")` with zero
   new effects — a key can never be replayed across actions or links, in
   either direction.
2. **No row, effect already exists** for the original (possibly created
   under a different key in a shared store) → insert an **alias** receipts
   row under the requesting key carrying the requesting digest/action/link
   fingerprint and the **same** `WD-…` effect id: the returned receipt is
   digest-valid for the requesting call and `lookup(requesting key)` stays
   authoritative. No second `withdrawals` row can exist.
3. **No row, no effect** → original existence is decided by an accepted
   **forward receipt** (`action` NULL/`"expense.submit"`) for that
   `external_id` — a receipts scan with the invoices table as a
   short-circuit, so direct zero-invoice acceptances count (an
   invoices-only probe would fabricate known absence for them). Present →
   create the one effect (new `WD-…` id, `withdrawals` row plus the
   receipts row) and return the accepted receipt. Absent → store a
   **queryable business rejection** receipt
   (`status:"rejected"`, `reason:"ORIGINAL_ABSENT"`) with no effect row:
   known absence is authoritative. A genuine store failure raises and the
   whole transaction rolls back — unavailability is never reported as
   absence.
4. The forward path never consults `withdrawals`: duplicate-invoice
   submits are always business-rejected, and no store state can turn a
   forward call into a withdrawal.

`timeout_after_commit` applies to the withdrawal path too, so a lost
response after a committed withdrawal recovers through `lookup` with the
digest-valid receipt.

Withdrawal receipts carry `original_external_id` (and, on refusal, a
`reason` such as `ORIGINAL_ABSENT`); `receipt_is_valid` accepts the extra
fields unchanged. The runtime-side binding check, the stored `adapter_result`
and the `withdrawn` proof kind are specified in
[runtime-boundaries.md](runtime-boundaries.md).

Caller-side example — the process that dispatches a prepared withdrawal
must itself hold the compensating capability; the shipped demo worker
grants deliberately do not (`work_runtime.demo.demo_grants`), so a
withdrawal-dispatching worker carries its own grants, as the compensation
demo's crash child does:

```python
from work_runtime.compensation_demo import compensation_grants, withdrawal

runtime = Runtime(db_path, ExpensePolicy(), compensation_grants())
proposal = withdrawal(runtime, "expense", forward_operation_id,
                      command_id="withdraw-once")
assert proposal["decision"] == "accepted"
resolved = runtime.dispatch(proposal["operation_id"], FakeOA(oa_path))
# The opted-in FakeOA receives execute(key, document, digest,
# action="expense.withdraw", compensates=<immutable link snapshot>).
```

## FakePublisher's paired contract and store (S14)

`FakePublisher` adopts the same D46 pattern for the publishing family's
linked retraction (`content.unpublish`), keeping the forward action FIRST
(the conformance mixin derives forward context from `actions[0]`):

```python
AdapterContract(actions=("content.publish", "content.unpublish"),
                idempotency_scope="adapter-store:key",
                retention="lifetime-of-store",
                lookup_consistency="authoritative-by-key",
                uniqueness=("document.id+content_digest",
                            "retraction.original_external_id"),
                supports_action_context=True)
```

| value | assertion |
|---|---|
| `actions=("content.publish", "content.unpublish")` | executes the publish capability and its paired retraction, forward action first |
| `uniqueness=("document.id+content_digest", "retraction.original_external_id")` | one artifact per document content and one retraction effect per original across all keys |
| `supports_action_context=True` | opts into explicit action/link execution context |

### Store schema, migration and counters

`receipts` is the per-key call/lookup surface for both actions;
`publications` keeps immutable `(document_id, digest)` artifacts; `retractions`
is the per-original effect surface. Opening a store — including any pre-S14
one — runs one `BEGIN IMMEDIATE` transaction that creates any missing table,
probes `PRAGMA table_info(receipts)` **inside the transaction**, adds the two
nullable identity columns when absent and creates `retractions`, so
concurrent first-open and re-open are race-free and pre-S14 stores open
unchanged (no row rewritten or deleted):

```sql
-- legacy columns, unchanged shape for old rows
CREATE TABLE IF NOT EXISTS receipts (
    key TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS publications (
    document_id TEXT, digest TEXT, external_id TEXT NOT NULL,
    document TEXT NOT NULL, PRIMARY KEY(document_id, digest));
-- additive identity columns (NULL = legacy/forward row, no link)
ALTER TABLE receipts ADD COLUMN action TEXT;
ALTER TABLE receipts ADD COLUMN link_digest TEXT;
CREATE TABLE IF NOT EXISTS retractions (
    original_external_id TEXT PRIMARY KEY, external_id TEXT NOT NULL,
    key TEXT NOT NULL, digest TEXT NOT NULL);
```

Forward rows keep `NULL` `action`/`link_digest`: the forward INSERT is the
single mechanical column-naming edit disclosed in the S14 ratification (D87
as amended) — identical inputs produce identical receipt rows and store
state before and after the migration, and same-content dedup still reuses
the publication id. Replay of an existing row validates the digest, the
normalized action (legacy `NULL` reads as `content.publish`) and the link
fingerprint; any mismatch raises `ValueError("Idempotency key reused with
different content")` with zero new effects, so a key can never be replayed
across actions or links.

**Counters (both derived from the SQLite store, never stdout):**
`published_count()` is unchanged — the `publications` row count; a
retraction never counts an effect away. `retracted_count()` is the
`retractions` row count — exactly one retraction effect per retracted
original.

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

The mixin runs six tests: declared metadata invariants (frozen valid
`AdapterContract`); same-key/same-payload replay returns the identical receipt
with exactly one effect and a `receipt_is_valid` shape; same key with different
content raises `ValueError` without a second effect; `lookup` of the committed
key matches the receipt; `lookup` of a missing key returns `None`; and — for
adapters that declare the action/link opt-in — an explicit-context replay
(`action` derived from the adapter's own `contract.actions[0]`,
`compensates=None`) returns the identical receipt with one effect, skipped
when the opt-in is absent (no hardcoded domain capability in generic
conformance code).

Domain-specific uniqueness (FakeOA's invoice-id uniqueness, a publisher's
`(document.id, digest)` uniqueness, and FakeOA's per-original withdrawal
uniqueness) is deliberately **not** in the mixin — each
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
