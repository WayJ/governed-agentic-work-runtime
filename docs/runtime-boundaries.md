# Runtime boundaries

This document records the externally observable guarantees of the dispatch,
reconciliation and recovery boundaries in `work_runtime/runtime.py`, and their
known limitations. It is the reference for reviewing changes to that file; the
regressions that pin each guarantee live in `tests/test_boundaries.py`.

## Trust model and scope

- Only trusted local application code instantiates the runtime. Principal
  names in `grants` are configuration, **not authentication**; anyone who can
  call the runtime in-process is trusted. Do not expose these methods as an
  unauthenticated API.
- Exactly **one coordinator process** dispatches operations. The guards below
  make accidental re-sends hard, but they do not fence a second dispatcher;
  distributed lease semantics (RFC-003 P13) are deferred.
- Claims are local and single-process: **no distributed exactly-once, no
  production-safety claim**. RFC coverage is partial (see
  [RFC-003](RFC-003-runtime-protocol.md)); this document records what the code
  actually does.

## Three identity layers

| layer | identity | effect |
|---|---|---|
| command receipt | fingerprint of `(work_id, kind, payload, expected_version)` under `(actor, command_id)` | replays return the original receipt verbatim; a reused id with different content is rejected `COMMAND_ID_REUSED`; rejected decisions are replayed as rejected |
| operation | business key derived by the policy (expense demo: policy id + capability + document id + document revision) | a new command proposing the same logical effect re-associates the existing operation instead of creating a second one; same key with different content is rejected `OPERATION_CONTENT_CONFLICT` |
| external effect | idempotency key = the operation's business key, enforced by the adapter | the external system deduplicates repeated calls with the same key and content |

## Policy registry and per-work binding

`Runtime(path, policy, grants, *, policies=None)` accepts an optional
keyword-only registry of explicitly loaded policy versions. The registry is
validated **before** any filesystem or database write and raises
`CommandError` on malformed input: it must be a dict keyed by nonempty
version strings where each key equals `value.version`, every value must
expose nonempty `id`/`version`/`goal` strings, a dict `evidence_sources`
and the five callable `Policy` methods, and every entry must share the
default policy's family (`id`) and `goal` — a cross-domain registry is not
a supported shared-database runtime. The mapping is copied; the default
version always resolves to the default policy object.

Every Work resolves its policy through its pinned contract binding
(`contract.policy_version`) in **all** validation, evaluation,
source-lookup, blocker, key, receipt and recovery paths. Unbound works use
the default policy. A work pinned to a version that is not loaded fails
closed with `CommandError` on access; migration is never implicit. Works
pinned to the default version track the live default slot, so
trusted-local reconfiguration of the default policy keeps its existing
fail-closed semantics; works pinned to other versions resolve through the
registry fixed at construction.

## The dispatch boundary

`dispatch(operation_id, adapter)` is the only path to an external effect.

1. Inside one transaction it re-checks the intent is still actionable: the
   operation is `prepared` and not `cancelled`; the work is not closed; the
   document digest and plan revision still match (otherwise the intent is
   `cancelled`/`STALE_INTENT`, never a fake external failure); authority and
   requirement blockers are re-evaluated (otherwise `held` with a reason —
   accepted commands are never retroactively rejected).
2. Immediately before the attempt is created it fails closed on policy
   configuration: the accepted receipt source (below) must be a nonempty
   string, else `CommandError` — no attempt, no external call. It then runs the
   declared-capability preflight: an adapter that declares an
   [`AdapterContract`](adapter-contract.md) excluding the operation's
   capability is `held` with reason `ADAPTER_ACTION_UNSUPPORTED` — again zero
   attempts and zero external calls — and stays dispatchable by a compatible
   adapter. A malformed descriptor raises `CommandError` before an external
   call; only a missing `contract` attribute keeps the legacy trusted
   duck-typed path — a descriptor that is present but invalid (a non-contract
   value, an explicit `None`, or an incomplete `AdapterContract` instance) is
   malformed, never silently legacy.
3. It persists `status="dispatched"`, `dispatch_state="in_flight"` and a new
   attempt with `outcome_unknown` **before** the external call. A process death
   anywhere after this commit is therefore treated as "the effect may have
   happened" and must be reconciled, never assumed absent.
4. `adapter.execute(business_key, document, document_digest)` then runs outside
   the transaction; a crash between commit and call still leaves an inspectable
   uncertain state (see limitations).

## Adapter result contract

A result returned by `execute` or `lookup` is authoritative for the operation
only if it is a dict with:

- `digest` exactly equal to the operation's `document_digest`,
- `status` one of `accepted` / `rejected`,
- `external_id` a nonempty string.

This check is `receipt_is_valid` in `work_runtime/adapter_contract.py`
(see [adapter-contract.md](adapter-contract.md)); extra receipt fields remain
allowed. An accepted result is recorded as verified evidence — kind
`accepted`, event id = the operation id — under the source configured at
`policy.evidence_sources["accepted"]` (the expense demo keeps `oa`). That
configuration fails closed with `CommandError` in `dispatch` (before an
attempt or external call), in `reconcile` (before querying) and in `_resolve`
(before adopting an accepted receipt): a missing, non-string or empty accepted
source can never become an accepted proof. Terminal and cancelled-operation
early returns are unaffected.

Anything else — non-dict payload, another content's digest, unknown status,
empty or missing `external_id` — is quarantined: the operation becomes
`outcome_unknown` with reason `ADAPTER_RESULT_INVALID`, the work becomes
`needs_attention`, the attempt stays `outcome_unknown`, and no `external_id` is
recorded. The quarantine is recoverable: once the adapter answers correctly,
`reconcile` confirms the operation from the corrected result.

An adapter exception during `execute` or `lookup` never fabricates a business
rejection; it records `outcome_unknown` with the exception's type name as the
reason.

## Recovery contract

`recover(adapter)` is the restart entry point and performs, in order:

1. `verify_pending` for every work (atomic candidate evaluation),
2. `expire_waits` for every work,
3. `reconcile` every `dispatched`/`outcome_unknown` operation through
   `adapter.lookup`,
4. `dispatch` every still-`prepared`, `ready` intent — after re-running the
   full dispatch checks above.

Guarantees:

- **Uncertain operations are never re-dispatched.** `dispatch` requires
  `prepared`; reconcile-only adapters cannot trigger `execute`; a resolved
  operation is returned as-is. Across crash, repeated `recover()`, explicit
  `dispatch` retries and command replays, a single operation produces exactly
  one external call (pinned end-to-end by the real-crash test).
- **No authoritative answer is an explicit escalation.** A `lookup` that
  returns `None` marks the operation `outcome_unknown`/`NO_AUTHORITATIVE_RESULT`
  and the work `needs_attention`; a `lookup` that raises records the failure
  reason. Neither is silently retried as a new external call.
- **Repeated reconciliation is idempotent.** Re-running `reconcile`/`recover`
  while findings are unchanged performs no writes: no new events, no
  `state_version` bump, no operation mutation (reason transitions are still
  recorded — a *changed* failure reason writes a new event). A supervisor may
  loop `recover()` safely.

## Recorded limitations

- **Unqueryable adapters never trigger a resend — and not every uncertainty
  reaches the work status.** A `lookup` returning `None`, a malformed result
  and a business rejection all escalate the work to `needs_attention`; a
  `lookup` that keeps raising records only operation-level
  `outcome_unknown`/`<ExceptionName>` plus an `OutcomeUnknown` event while the
  work status itself stays unchanged, so the operation, not the work status,
  is the authoritative signal there. If the process dies between the attempt
  commit and the external call, recovery likewise escalates or records instead
  of re-sending; there is no automatic resend path. RFC-003 P06's "recoverable
  dispatch" is met only through reconciliation, and only when the adapter can
  answer.
- **In-flight calls cannot be cancelled.** A document revision that lands after
  the external call started cannot revoke it; the old operation confirms
  against the old digest, which satisfies only that revision's requirements.
  While that operation is still unresolved, `propose_action` for new content
  is rejected `OUTCOME_UNRESOLVED`: the uncertain operation must be reconciled
  first, and only then can new content be prepared as a new operation (new
  business key), still subject to the external system's own uniqueness
  constraints.
- **Evidence receipts are immutable.** Re-submitting the same source event id
  with different content is `SOURCE_EVENT_CONFLICT`; an `invalid` candidate is
  never overwritten by a corrected re-submission under the same event id.
- **`needs_attention` is sticky** until the work closes; reconciliation cannot
  automatically clear it.
- **Directly re-`dispatch`ing a `held` intent re-runs the checks** and may
  dispatch if authority and blockers now pass; `recover` never auto-dispatches
  `held` intents — they are re-admitted explicitly through `propose_action`.
- **One policy family per database; versions are pinned per Work.** A work
  whose pinned version is not in the loaded registry raises on access, and
  switching versions is never implicit — an explicit migration command is
  required. Business-key stability across same-family versions is a
  policy-author obligation; the runtime does not rewrite keys.

## Verification

`tests/test_boundaries.py` (run with `python3 -m unittest discover -s tests`):

| guarantee | test |
|---|---|
| reconcile without authoritative answer is idempotent | `test_repeated_reconcile_without_authoritative_result_is_idempotent` |
| reconcile with failing lookup is idempotent | `test_repeated_reconcile_with_failing_lookup_is_idempotent` |
| malformed-result quarantine is idempotent | `test_repeated_malformed_result_reconcile_is_idempotent` |
| malformed results leave inspectable uncertainty | `test_malformed_adapter_results_leave_inspectable_uncertainty` |
| mismatched digest is quarantined, not confirmed | `test_mismatched_digest_result_is_quarantined` |
| corrected adapter result recovers the operation | `test_adapter_recovering_with_valid_result_confirms_operation` |
| uncertain operations are never redispatched | `test_recover_never_redispatches_uncertain_operation` |
| exception then recover calls the adapter once and escalates | `test_execute_exception_then_recover_calls_adapter_once_and_escalates` |
| changed failure reasons are still recorded | `test_new_reconcile_failure_reason_is_recorded` |
| recovery with nothing to do writes nothing | `test_recover_with_nothing_to_do_is_idempotent` |
| real crash converges to exactly one external application | `test_real_crash_recovery_yields_exactly_one_external_application` |
| business dedup survives recovery | `test_recovery_business_dedup_returns_existing_operation` |

The real-crash demo (`python3 -m work_runtime demo`) exercises the same
boundary end to end: a worker process dies after external acceptance and
recovery produces exactly one FakeOA application.

Adapter-contract guarantees (declared-capability hold with zero attempts and
calls, malformed descriptors, policy-owned accepted source, conformance
replay/uniqueness behavior) are pinned in `tests/test_adapter_contract.py`,
which adopts the reusable mixin in `tests/adapter_conformance.py`; the exact
test-name table lives in [adapter-contract.md](adapter-contract.md).
