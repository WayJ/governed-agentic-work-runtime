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
| command receipt | fingerprint of `(work_id, kind, payload, expected_version)` under `(actor, command_id)` | replays return the original receipt verbatim **while current authority holds** (see below); a reused id with different content is rejected `COMMAND_ID_REUSED`; rejected decisions are replayed as rejected |

**Replay rechecks current authority.** Before returning a stored receipt
the runtime re-evaluates the command's authority against the *current*
grants, ownership and policy configuration: `create_work` needs
`work.manage`; `record_evidence` needs the current source identity for
the payload kind plus `evidence.write`; `propose_action` needs the
current owner plus the requested capability; management mutations need
the current owner plus `work.manage` (legacy ownerless works stay
grant-only); intervention commands accept the current owner with
`work.manage` or a `work.intervene` administrator. A replay whose
authority was lost returns a **fresh, unpersisted** `AUTHORITY_DENIED`
receipt carrying the currently observed state version — the stored
receipt is never modified, and a later replay under restored authority
returns it again. Closed-work actionability follows replay as before: a
stored receipt is returned for a closed work while authority holds.
| operation | business key derived by the policy (expense demo: policy id + capability + document id + document revision; publishing family: policy id + capability + document id + document digest; support-ticket family: policy id + capability + the ticket reference alone) | a new command proposing the same logical effect re-associates the existing operation instead of creating a second one; same key with different content is rejected `OPERATION_CONTENT_CONFLICT` |
| external effect | idempotency key = the operation's business key, enforced by the adapter | the external system deduplicates repeated calls with the same key and content |

## Mixed-node workflow boundary (S16 — the disclosed freeze exception)

The S15 verdict froze `work_runtime/runtime.py` for new *families*. Generic
mixed-node workflow support cannot be built as family-only code, so S16 edits
that file additively and records the digests here. The full description of
the language, the engine and the bridge lives in
[workflow-runtime.md](workflow-runtime.md).

| file | SHA-256 before | SHA-256 after |
|---|---|---|
| `work_runtime/runtime.py` | `80bf721b3369a6fb865fd6aba0e57804a69eb8587431f8fa6edf1183fc53f4b3` | `19555fcfe1e602ae6598d5ef7392536c3bc19171129686516c53fcda63d8c7ac` |
| `work_runtime/adapters.py` | `ce132f24d84c17a083bcf0b61bf90e1c62ff75faf2ec52fe2c7348ab86b6985e` | unchanged |

The runtime edits are: four workflow tables under the existing schema
version, the dispatch of the workflow command kinds, the workflow status in
`_evaluate`, the **object binding** of a proposal, and the cancellation hook.
Non-workflow works keep their previous behaviour; the byte pin in
`tests/test_publishing_compensation.py` is updated consciously.

New boundaries that the workflow adds:

| boundary | guarantee | evidence |
|---|---|---|
| definition provenance | a binding pins the digest of an immutable published definition; an unknown validator, an unknown version, an incomplete required check or a family mismatch fails closed at publication and at binding | `tests/test_workflow_engine.py` — `PublicationAndBindingTests` |
| candidate acceptance | a candidate is stored only after the shape descriptor and the registered, version-pinned validator accept it; a rejection stores nothing and completes nothing; a self-certifying payload is an undeclared field, not a validation | `tests/test_workflow_engine.py` — `RoutingTests` |
| approval | a decision counts only when it is verified, of the node's kind, from the declared authority and covers the subject's exact revision and digest; an executor may not approve; a reviewer may not repeat a role | `tests/test_workflow_engine.py` — `RoleIsolationTests` |
| automatic action | one prepared operation per node, proposed through the ordinary admission path, dispatched outside the routing transaction; an unknown effect is looked up, never repeated | `tests/test_workflow_engine.py` — `ActionTests`; `tests/test_workflow_recovery.py` |
| automatic node quality | the receipt the external system really returned is persisted with its origin and judged by the declared, version-pinned validator before the node completes; the effect and the output are two facts: a rejected output is never a false external failure and never a second effect; a node that declared no quality says so | `tests/test_workflow_node_quality.py` — `ActionNodeQualityTests` |
| wait binding | a wait that matches verified evidence records the work, node, attempt, object revision and digest and event provenance it matched on; a bound wait accepts only the bound attempt, so an old proof never satisfies a new attempt | `tests/test_workflow_node_quality.py` — `WaitBindingTests` |
| declared material | a declared input and a declared subject are judged by their pinned validator before any intent and before any external effect; the judgment carries the pinned validator, its version and the reviewed revision and digest | `tests/test_workflow_node_quality.py` — `InputValidationTests` |
| human named record | a human node may declare the record its decision carries; the record travels with the decision, is judged by the pinned validator and is written in the same compare-and-swap guarded command; a record that fails its quality is never written and the decision is never lost | `tests/test_workflow_node_quality.py` — `HumanOutputTests` |
| orphan judges | a required criterion whose judge cannot run — an `AGENT` criterion without a declared review, a `PROGRAM` criterion without an output validator — is refused at publication | `tests/test_workflow_node_quality.py` — `DefinitionLanguageTests` |
| superseded material | a new revision of the inputs, the subject or the candidate a node pinned supersedes that node, so a review of a superseded candidate cannot complete it | `tests/test_workflow_node_quality.py` — `SupersedeTests` |
| action effect policy | the default is one effect per node; the opt-in `per_revision` is declared in the immutable published definition and pinned by digest, and admits a new effect only for a new revision with a new digest of the subject and only after the previous effect is settled; the same subject never repeats an effect, an unsettled operation is reconciled before any new write, and a succeeded effect whose output failed validation is never bypassed; a new admission owns a new operation with a new business key and an exact node linkage | `tests/test_workflow_effect_policy.py` — `PerRevisionPathTests`, `RefusalTests`, `DefaultPolicyTests` |
| routing | one deterministic pass; a pass that changes nothing writes nothing; rework increments the attempt and invalidates the affected approval by exact version; a late callback is refused | `tests/test_workflow_engine.py` — `RoutingTests` |
| bridge | a generic `/v1/workflows` surface with bounded read models, durable intent ids, a single-coordinator file lock and a log that never carries a body | `tests/test_workflow_http.py` |
| creation resume | the bridge owns one `workflow_creates` table in the runtime store; the preparation of every stage is written ahead of the stage in one transaction, so a replay re-issues the identical command instead of recomputing a compare-and-swap version; a command id belongs to one request, and two callers of one creation are serialized | `tests/test_workflow_create_resume.py` — `CreateReplayTests`, `PreparationStoreTests`; `tests/test_workflow_http.py` — `CreateReplayTests` |
| workflow acceptance | `finalize_workflow_success` is issued by the protected runner only; under one transaction it verifies the recorded terminal, the completed nodes, the validated quality, the passed criteria, the settled effects and the settled obligations, and only then freezes the work and writes the exact final snapshot; a failed, expired, cancelled, output-invalid, unfinished, unsettled or cancelled workflow is never frozen; the frozen work accepts no later revision, cancellation, result, decision or effect, and the frozen workflow is never routed again | `tests/test_workflow_finalization.py` — `SuccessfulAcceptanceTests`, `RefusalTests`, `FrozenStateTests`, `HttpFinalizationTests` |
| frozen snapshot | the snapshot is written once and never rewritten; it names the template digest, the contract revision, the plan revision, the document revision and digest, every object revision and digest, every node attempt with its judgment, every effect, every obligation and the verified evidence; late evidence and late revocation are still admitted by the runtime's own correction rules, but they can neither change the accepted snapshot nor reopen the accepted workflow, because the routing pass is frozen | `tests/test_workflow_finalization.py` — `test_a_late_proof_cannot_reopen_the_accepted_workflow`, `test_a_revocation_cannot_reopen_the_accepted_workflow` |

### The workflow-success acceptance: one disclosed lifecycle edit

The acceptance of a successful workflow (`finalize_workflow_success`) is
**family-neutral**. The command itself needed no change to the frozen
lifecycle files: it rides the existing workflow command dispatch
(`WORKFLOW_COMMANDS`), the existing compare-and-swap, the existing command
dedup and the existing closed-work rule, and the freeze of an accepted
workflow is the runtime's own "a closed work accepts no command" rule. The
engine keeps the acceptance, the snapshot and the routing freeze in
`work_runtime/workflow.py`, and the bridge keeps the two routes in
`work_runtime/workflow_server.py`.

**One lifecycle edit follows it, and it is disclosed here.** The generic
`request_completion` could close a workflow-bound work that was finished but
not accepted: the generic path sees the requirements and the operations, but
not the workflow's terminal, its quality or its effects, so a platform could
still close its task through it without the workflow proof. The guard is the
smallest additive change that closes the bypass:

| file | SHA-256 before | SHA-256 after |
|---|---|---|
| `work_runtime/runtime.py` | `19555fcfe1e602ae6598d5ef7392536c3bc19171129686516c53fcda63d8c7ac` | `1b9c73e639ffa9a6facf3d092c07c12e4cf84639c0d2ea8ccecce14b6cb3d075` |
| `work_runtime/adapters.py` | `ce132f24d84c17a083bcf0b61bf90e1c62ff75faf2ec52fe2c7348ab86b6985e` | unchanged |

`request_completion` on a work that has a workflow binding now refuses with
`WORKFLOW_ACCEPTANCE_REQUIRED` unless the work carries an accepted
finalization. The two facts are read from the **stored work**, so the
refusal holds after a restart and in a process that carries no workflow
engine at all — an in-memory hook would have left the same bypass open
behind a restart. A work without a workflow keeps its previous completion
path exactly, and the refusal is an ordinary receipt: it is deduplicated,
readable and replayed like every other.

| boundary | guarantee | evidence |
|---|---|---|
| generic completion | a workflow-bound work is closed by its acceptance, never by the generic completion; a non-workflow work is untouched | `tests/test_workflow_finalization.py` — `GenericCompletionGuardTests` |

One engine behaviour changed with it, and it is disclosed here: **a
finished workflow is not routed again.** The routing pass used to walk the
completed chain of a finished workflow and open a fresh attempt of its last
node, so "finished" was not a fact a reader could rely on. The pass now
finds the recorded terminal and changes nothing.

## Third-family command-surface freeze (S15)

The support-ticket family (`work_runtime/support.py`, tests
`tests/test_support.py` + `tests/test_support_demo.py`) runs end-to-end over
the unchanged command surface: proposal admission with an unknown-blocking
rule (unresolved severity or category ⇒ `APPLICABILITY_UNRESOLVED`, and an
unresolved severity keeps the SLA rule's applicability unknown too),
SLA/dispatch rules, dispatch with result-unknown fencing, receipt
reconciliation by the ticket-reference business key and business closure.
**Freeze verdict: zero lifecycle edits** — `work_runtime/runtime.py` and
`work_runtime/adapters.py` stayed byte-identical through S15 (SHA-256
`80bf721b…` / `ce132f24…`, asserted at the wave boundaries in the sprint
evidence); no freeze-gap escalation was needed. Two family constraints are
disclosed, both consequences of designing inside the frozen surface and
tested same-work and cross-work:

- **Document identity is keyed on the ticket reference.** The frozen
  `revise_document` command reads `document["id"]` for object identity, so
  the family document carries `id` = the external ticket reference; id
  stability under revision is exactly reference stability.
- **One reference = one governed dispatch.** The business key embeds the
  reference and no content digest, so changed content under an already-used
  reference is rejected `OPERATION_CONTENT_CONFLICT` — never a second
  operation, never a second external issue.

## Compensation boundary (S10/S14 — expense and publishing families, active-cancellation window)

`propose_action` gains one **linked compensation variant** (D43): a payload
carrying `compensates` (the original operation id, a nonempty string) plus
exactly `capability`, `contract_revision`, `plan_revision` and
`document_digest` — anything else is an unpersisted `CommandError`. Ordinary
payloads (no `compensates` key) keep the pre-S10 lenient handling unchanged.
The variant exists for the expense family (`expense.withdraw`, paired by
`ExpensePolicy.compensation_capabilities`) and, since S14, the publishing
family (`content.unpublish`, paired by
`PublishingPolicy.compensation_capabilities`) — always and only while a
cancellation intent is active. Executing a linked compensation additionally
requires an adapter that declares the action and opts into action/link
context (see [adapter-contract.md](adapter-contract.md)); `FilePublisher`
stays forward-only and holds at the actions preflight.

Admission precedence (each step a persisted business rejection unless marked
misuse):

```text
exact payload shape (CommandError, nothing persisted)
→ authority: current owner + capability in grants            AUTHORITY_DENIED
→ window split: forward payload + active intent              CANCELLATION_ACTIVE
              compensation variant + no intent               CANCELLATION_NOT_REQUESTED
→ contract/plan/digest matches (unchanged codes)             CONTRACT_REVISION_MISMATCH /
                                                              PLAN_REVISION_MISMATCH / EVIDENCE_SCOPE_MISMATCH
→ link validation: target exists, same work,
   confirmed_succeeded, not itself a compensation,
   policy pairing matches                                     COMPENSATION_TARGET_INVALID, blockers [target id]
→ policy blockers for the capability (empty when paired)     REQUIREMENT_UNSATISFIED / APPLICABILITY_UNRESOLVED
→ pending different-digest guard (unchanged)                 OUTCOME_UNRESOLVED
→ business-key lookup → re-admitted (free) /                 OPERATION_CONTENT_CONFLICT
→ insert compensation operation + events
```

- **Window split covers fresh AND re-admission**: the single gate sits before
  the business-key branch, so inside the window a compensation re-proposal
  under a new command id re-admits the existing operation (re-preparing a
  cancelled/held one, updating the actor) exactly like an ordinary
  re-admission outside the window; re-admission never rebinds the link. The
  in-window document freeze (`revise_document` is `CANCELLATION_ACTIVE`)
  keeps the re-admission digest guard unreachable from drift.
- **Link validation is admission-time truth on terminal facts**: the target
  must be `confirmed_succeeded` (an uncertain target must be reconciled
  first; a failed target has no effect to withdraw), in the same work, and
  not itself a compensation (no chains). Requirement/proof state is
  orthogonal: a revoked accepted proof does not undo the effect and does not
  block compensation. The pairing arm applies only when the capability is in
  the policy's pairing map; an unpaired capability degrades to the ordinary
  `CAPABILITY_UNSUPPORTED` blocker (how a family without a declared pairing
  stays out of scope without a runtime flag — publishing before S14, SOP
  authoring today).
- **Business key** (runtime-owned, D6): `digest([policy.id, capability,
  target_operation_id])` — stable across same-family policy versions,
  structurally distinct from every forward key (the store-global
  `business_key UNIQUE` then gives at most one compensation per (family,
  capability, original)), and embedding the original operation id. The
  forward `operation_key` is never consulted for compensation proposals.
- **Operation body** adds one immutable snapshot
  `"compensates": {"operation_id", "external_id", "capability"}` — terminal
  facts of the target at proposal, never rewritten afterwards (terminal
  operations are immutable). `OperationPrepared`/`OperationReadmitted`
  events carry the same additive `compensates` object for compensations
  only; generic readers treat an absent `compensates` as an ordinary
  operation. The operation's `document`/`document_digest` remain the current
  frozen work state, so every existing digest touchpoint (admission scope,
  pending guard, dispatch staleness, adapter digest check) applies unchanged.

Dispatch, resolution, proofs and closure are covered in
[the dispatch boundary](#the-dispatch-boundary) below (compensation
carve-out), [adapter result contract](#adapter-result-contract) (binding
check, stored adapter result, `withdrawn` proof) and
[interventions.md](interventions.md) (finalization). **Reconcile stays
caller-trusted** under the single two-action adapter (B): `reconcile`/
`recover` accept one adapter and `lookup` by business key regardless of
action; wiring a wrong adapter to a compensation's reconcile is a caller
error outside the product surface (unchanged from the pre-S10 trust model —
principal names and adapters are trusted-local configuration, never
authentication).

## Policy registry and per-work binding

`Runtime(path, policy, grants, *, policies=None)` accepts an optional
keyword-only registry of explicitly loaded policy versions. The registry is
validated **before** any filesystem or database write and raises
`CommandError` on malformed input: it must be a dict keyed by nonempty
version strings where each key equals `value.version`, every value must
expose nonempty `id`/`version`/`goal` strings, a dict `evidence_sources`
and the five callable `Policy` methods, and every entry must share the
default policy's family (`id`) and `goal` — a cross-domain registry is not
a supported shared-database runtime. For **any** explicit registry,
including the empty dict, those structural checks apply to the default
policy object itself as well (it is a registry entry; the `policies=None`
legacy constructor path stays as-is). An explicit registry may omit the
default version — the `policy` constructor argument supplies it — but if
the default key is supplied it must map to that identical default object.
The mapping is copied; the default version always resolves to the default
policy object.

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
   document digest, plan revision and contract revision still match
   (otherwise the intent is `cancelled`/`STALE_INTENT`, never a fake
   external failure); authority (including current Work ownership) and
   requirement blockers are re-evaluated (otherwise `held` with a reason —
   accepted commands are never retroactively rejected). **Compensation
   carve-out (S10)**: an operation carrying `compensates` is *not*
   auto-cancelled by an active cancellation intent — it was structurally
   admitted only inside that window — while every forward prepared intent
   keeps `WORK_CANCELLED`. Two belt-and-braces branches (unreachable via
   public API, pinned by crafted-store tests) mirror the carve-out: a
   compensation without an active intent cancels `STALE_INTENT`, and a
   compensation whose stored link no longer re-validates against the stored
   target (exists, same work, `confirmed_succeeded`, not itself a
   compensation, snapshot `external_id`/`capability` equality, current
   policy pairing) is `held` with reason `COMPENSATION_TARGET_INVALID` —
   visible, never auto-cancelled, never dispatched.
2. Immediately before the attempt is created it fails closed on policy
   configuration: the accepted receipt source (below) must be a nonempty
   string, else `CommandError` — no attempt, no external call. It then runs the
   declared-capability preflight: an adapter that declares an
   [`AdapterContract`](adapter-contract.md) excluding the operation's
   capability is `held` with reason `ADAPTER_ACTION_UNSUPPORTED` — again zero
   attempts and zero external calls — and stays dispatchable by a compatible
   adapter. A **compensation** additionally requires an adapter whose declared
   contract asserts `supports_action_context=True`: without the opt-in it is
   `held` with reason `ADAPTER_ACTION_CONTEXT_UNSUPPORTED` (zero attempts,
   zero calls, work stays out of `needs_attention`, re-dispatchable) — even
   when the contract's `actions` claims the withdraw capability, because a
   non-opted-in adapter cannot receive the binding link. A malformed
   descriptor raises `CommandError` before an external
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
   uncertain state (see limitations). An opted-in adapter is called instead as
   `execute(business_key, document, document_digest, action=capability,
   compensates=link_or_None)` — the dispatch decision reads the declared
   contract only (no signature introspection, no TypeError probing), so legacy
   adapters keep the exact three-positional-argument call.

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
`policy.evidence_sources["accepted"]` (the expense demo keeps `oa`); when
that `(source, event_id)` row already exists, the acceptance resolves
through the collision path instead (see
[acceptance-proof collision recovery](#acceptance-proof-collision-recovery)).
That configuration fails closed with `CommandError` in `dispatch` (before an
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

**Compensation resolution binding, stored results and `withdrawn` proofs
(S10 D45).** For an operation carrying `compensates`, `_resolve` adds one
check after `receipt_is_valid` and **before** the accepted/rejected split:
`result["original_external_id"]` must be a nonempty string equal to the
immutable snapshot's `external_id`. A malformed or mismatched receipt —
accepted or rejected alike — is quarantined
(`outcome_unknown`/`ADAPTER_RESULT_INVALID`, work `needs_attention`,
idempotent on repeat), never a confirmation against the wrong original. A
valid compensation result additionally stores the full validated receipt
additively as `op["adapter_result"]` (refusal reasons included); ordinary
operations never carry the field. An accepted withdrawal resolves
`confirmed_succeeded` with `external_id` = the compensation's own external id
(`WD-…` in the expense demo) and inserts the
runtime-owned proof with **kind `"withdrawn"`** (data
`{digest, external_id, original_external_id}`) at the same accepted-source
identity — never a forward `accepted` proof, so it can never satisfy an
`accepted`-kind rule such as E08 or C04 at any digest. A rejected withdrawal
resolves `confirmed_failed` with the work `needs_attention`. The S9
collision path covers withdrawal resolutions verbatim: an occupied
`(accepted source, operation id)` identity records the actual withdrawal
result plus the conflict snapshot and inserts no proof of any kind.

**No `withdrawn` evidence-source mapping (deliberate).** Withdrawn proofs
ride the accepted-source identity space only: `record_evidence` rejects kind
`withdrawn` for every actor (no configured source can authorize it), signed
ingress is denied at `record_evidence`, imports are impossible, and
revocation of a withdrawn proof is administrator-only. Runtime-observed
withdrawal effects are not source-claimable.

**External stand-in store compatibility (S10/S14).** `FakeOA`'s own SQLite store
migrated additively: opening any store — including pre-S10 ones — runs one
`BEGIN IMMEDIATE` transaction that adds the nullable `receipts.action` /
`receipts.link_digest` identity columns and the per-original `withdrawals`
effect table exactly once (schema, migration, withdrawal execution and
counter semantics: [adapter-contract.md](adapter-contract.md)). `FakePublisher`
adopts the identical pattern since S14 (additive `receipts` identity columns
plus a `retractions` effect table; forward rows keep `NULL`
action/link_digest under the disclosed column-named INSERT). The runtime
store schema stays `1`; forward adapter behavior (duplicate-invoice
rejection, key replay, counters) is preserved, with the forward INSERT on
named columns.

## Accepted-evidence reservation (operation-id intake)

`record_evidence` admission gains one persisted rejection, placed after the
unchanged shape, source+kind authority and existing-row branches:

```text
shape/identity checks → source+kind authority → existing row
(fingerprint match → dedup resend with current status; mismatch →
SOURCE_EVENT_CONFLICT) → OPERATION_ID_RESERVED → insert pending candidate
```

A fresh `record_evidence` whose `event_id` exactly equals a stored operation
id is rejected `OPERATION_ID_RESERVED` — a persisted business rejection with
`blockers == [operation_id]` that replays verbatim under the stored command
id while current authority holds (a new command id gets a fresh rejection) —
**when the actor is the configured accepted source of any currently loaded
policy version**. The union is recomputed on every intake from the live
registry: never cached at construction, never assuming a policy-object
default fallback or immutability, so a renamed accepted source travels with
configuration. A runtime serving both V1 (`oa`) and V2 (`oa2`) reserves both
actors, because V1-pinned works still resolve — and insert accepted proofs —
under `oa`; a registry that does not load V1 keeps the existing fail-closed
rule for V1-pinned works. No source authority is broadened or reduced, and
command CAS/fingerprint/version mechanics and replay reauthorization are
untouched.

Why this predicate: `_resolve` inserts accepted proofs only under the
accepted source of a loaded policy, so every source in the union could
otherwise create a row occupying the `(source, event_id)` primary key the
runtime itself must later write under that operation id — the collision
would fail every later `reconcile`/`recover` of the operation forever. The
reservation is therefore global: any stored operation id, across works and
across proof kinds, permanently (operations rows are permanent, so a
reservation never expires). It is scoped to the accepted-source union, not
to kind `accepted` (an overlapping kind mapping lets the same actor poison
through an ordinary kind) and not to the same work (the stored id is
store-global).

Disclosed consequences:

- **Conservative over-block:** an accepted source importing an operation id
  that belongs to a work whose own policy resolves under a *different*
  accepted source is still rejected. The rejection receipt says why; such
  content would be dubious anyway.
- **Unrelated sources are never blocked** — only an accepted source of a
  loaded version can ever occupy a future proof identity, so no one else is
  checked, and fresh-event imports by accepted sources remain valid. Real
  external event ids are externally generated and never alias runtime
  `uuid4` operation ids except by 2^-122 coincidence (stated, not handled).
- **Dedup/conflict precedence is unchanged:** an *existing* row under the
  same `(source, event_id)` is answered by the old-row branch first — an
  exact resend still returns the candidate's current status and changed
  content is still `SOURCE_EVENT_CONFLICT`, including rows that predate
  this guard.
- Signed ingress already excludes kind `accepted` and is untouched.

## Acceptance-proof collision recovery

Prevention cannot heal a store poisoned before the reservation existed: an
imported candidate already occupies `(accepted_source, operation_id)`, the
external acceptance is real, and the plain INSERT would fail every
reconcile/recover of that operation forever. In `_resolve`'s accepted
branch, one exact primary-key probe (`source` + operation id) runs before
the proof INSERT, inside the same transaction as every other resolution
write. On a hit the resolution records the actual accepted external truth
and an additive conflict snapshot instead of a proof:

- **Operation**: `status="confirmed_succeeded"`, `dispatch_state="finished"`,
  `external_id` from the validated adapter result, the existing attempt's
  terminal status — exactly the normal resolution fields — plus one
  additive `proof_conflict` object with exactly nine fields:

  | field | source |
  |---|---|
  | `source`, `event_id` | the collision primary key (accepted source, operation id) |
  | `evidence_id`, `evidence_kind`, `evidence_status` | the conflicting row's stored body; counted only when a nonempty string, else `null` (missing/wrong-type/non-object bodies degrade; nothing is coerced from candidate data) |
  | `evidence_work_id`, `evidence_fingerprint` | the conflicting row's SQL columns, verbatim |
  | `external_id` | the actual validated adapter result |
  | `document_digest` | the operation's digest — never the candidate's `data.digest` |

- **Work**: `needs_attention` — set only when the work was not closed. A
  closed work (only constructible as a custom/direct-SQL store: both public
  closure paths gate on `OUTCOME_UNRESOLVED`) keeps
  `status`/`outcome`/`completion` unchanged, and the event records
  `work_was_closed: true`.
- **Event**: one `AcceptanceProofConflict` with exactly eleven fields (the
  nine snapshot fields plus `operation_id` and `work_was_closed`), in place
  of `OperationResolved` for this resolution only. Exactly one work version
  bump; requirements are recomputed honestly from the actual stored
  evidence — the acceptance rule stays satisfiable only through a verified
  proof, which here can only be the conflicting import itself or a later
  replacement import.

Nothing is deleted, overwritten, converted to `revoked`/`invalid` or
revived, and no authoritative proof is synthesized: the conflicting
candidate keeps its identity, raw body, fingerprint and SQL columns
byte-identical (it remains independently revocable and inspectable through
the S8 commands if a human decides so), and the operation's
`proof_conflict` plus the durable event keep the two truths distinguishable
in public stored truth.

Crash atomicity and idempotence:

- The whole transition is one `_transaction`; an exception or a real
  process death mid-transaction rolls back operation, work and event
  together, leaving the operation `dispatched` — the next
  reconcile/recover redoes it deterministically (the probe is a read; a
  dispatched operation is never re-executed).
- After resolution the operation is terminal, so repeated
  `reconcile`/`recover` performs **no writes to that operation or its
  conflict event and no adapter call for it** — while `recover` still
  verifies and expires other records and reaches later operations. The
  idempotence claim is operation-scoped: whole-store no-write equality does
  not hold across `recover` cycles because unrelated
  `EvidenceEvaluated`/`WaitExpired` events may fire.
- A lost accepted response (adapter timeout after commit) recovers through
  `reconcile`'s lookup with the same one-shot conflict resolution and one
  retained external effect.

Completion and cancellation are unchanged (**no new blocker**): a trusted
accepted source could always satisfy `accepted`-kind requirements by
importing a shape-valid proof under a fresh event id — the documented
trusted-local synthetic-acceptance boundary below — so the conflict case
grants no new capability. `request_completion` still requires the normal
requirements plus no unresolved operations; `finalize_cancel`
acknowledgement must still include the conflicted operation's id because
its confirmed effect is real; a replacement proof is recorded as a new
event under the currently configured source. A conflict never silently
revokes or transfers proof authority.

**Trusted-local synthetic-acceptance boundary (explicit).** The accepted
source is a trusted local principal; any proof it imports that passes the
policy's shape validation can satisfy `accepted`-kind requirements without
any external effect. The reservation prevents only the *collision*
consequence (operation-id aliasing), not the general capability. This is a
limit of the local trust model, not an authentication claim.

**Out of scope.** A conflicting-row body that is not valid JSON is a
corrupted store: the parse error propagates, the resolution transaction
rolls back, and no repair is attempted (malformed-but-valid-JSON bodies
degrade to `null` snapshot fields as above).

## Cancellation boundary

Full command reference, authority matrix and rejection codes:
[interventions.md](interventions.md).

`request_cancel` (payload exactly `reason`, a nonempty string) records a
cancellation **intent** in the Work's own JSON (`cancellation.requested_by`
/ `reason`), deliberately separate from presentation status so
evaluation, expiry, malformed-receipt quarantine and reconciliation can
never clear it. Accepted by the current owner holding `work.manage` or a
local `work.intervene` administrator. The intent is set once: a second
request under a new command id is rejected `CANCELLATION_ALREADY_REQUESTED`
and can never overwrite the original; replays under the original command
id return the stored receipt. Establishing (unbound) works can be
cancelled too.

While the intent is active the work stops: `propose_action` (including
re-admission), `bind_contract`, `revise_plan`, `revise_document`,
`register_wait`, `request_completion` and explicit policy migration are
rejected `CANCELLATION_ACTIVE`; waiting/triggered waits become `cancelled`
— terminally: later evaluation (late evidence, verification, migration)
can never re-trigger a cancelled wait — and never-dispatched prepared
intents are cancelled with reason
`WORK_CANCELLED` — a prepared operation is never relabeled as an external
`confirmed_failed`. Evidence intake, the internal verifier, expiry and
reconciliation keep running: an attempt that was already durable when
cancellation was requested remains uncertain until queried through the
original key — cancellation is an internal stop, not an external fence.
There is no automatic close: an explicit `finalize_cancel` always records
the terminal decision.

`finalize_cancel` (payload exactly `acknowledged_operations`, a list of
distinct nonempty operation ids; same authority as `request_cancel`)
refuses to close while any operation is unresolved (`OUTCOME_UNRESOLVED`,
including `dispatched`/`outcome_unknown` ones — a missing or malformed
lookup answer can never be finalized past). Once every effect is resolved,
the acknowledgement must equal **exactly** the set of
`confirmed_succeeded` operation ids — an empty list is correct only when
there were no succeeded effects; anything else is
`CANCEL_ACKNOWLEDGEMENT_MISMATCH` with the succeeded ids as blockers. An
accepted finalize closes the work as `cancelled` (never `succeeded`) and
records an immutable closure snapshot: the original cancellation intent,
the acknowledged succeeded operations with their external ids, and every
operation's disposition. Acknowledgement is an explicit admission that
the external effects exist — it is not, and never claims to be,
compensation or reversal. Closed-work semantics are unchanged: fresh
management commands on the closed work are `WORK_NOT_ACTIONABLE`, replays
under the original command id still return the stored receipt while
authority holds.

## Ownership boundary

Every new Work records `owner = creator` in its own JSON. Management
mutations (`bind_contract`, `revise_plan`, `revise_document`,
`register_wait`, `request_completion`) require the **current owner**
holding `work.manage`; `propose_action` requires the current owner holding
the requested capability, so a former owner's global grant does not retain
this Work's execution rights; `dispatch` additionally holds
(`AUTHORITY_DENIED`) an intent whose actor is no longer the Work's owner.
Evidence writers keep their existing source-specific authority — ownership
never gates evidence intake. Authorization is principal *configuration*,
still not authentication.

`transfer_owner` (payload exactly `owner` and `reason`, both nonempty
strings; accepted by the current owner with `work.manage` or a
`work.intervene` administrator) reassigns accountability atomically: it
persists actor, previous/next owner and reason in an `OwnerTransferred`
event, reassigns outstanding `waiting`/`expired` waits owned by the prior
owner, and invalidates never-dispatched prepared intents with reason
`OWNERSHIP_TRANSFERRED` so the new owner must re-propose. In-flight
operations keep their actor, key, attempts and results, and reconciliation
never requires the old execution authority. The target must exist in
`grants` with `work.manage` (else `AUTHORITY_DENIED`); a same-owner
transfer is `TRANSFER_SAME_OWNER`. Transfer is possible while a
cancellation intent is active, never erases it, and grants no capabilities.

**Legacy databases** whose Works predate ownership stay readable and keep
grant-only behavior for existing commands — no owner is ever guessed from
historical receipt shapes. Ownership is adopted explicitly: only a
`work.intervene` administrator may transfer an ownerless Work, and from
that point the Work is owner-gated like any other.

## Policy migration boundary

`migrate_policy` (payload exactly `policy_id`, `policy_version`, `reason`;
**exclusively** a `work.intervene` administrator) rebinds a bound, open,
uncancelled Work to another registered version of the same family and
goal. It is rejected — before any mutation — for an unbound work
(`CONTRACT_NOT_ACTIVE`), an active cancellation intent
(`CANCELLATION_ACTIVE`), another family (`MIGRATION_FAMILY_MISMATCH`,
checked before registry lookup), an unregistered version
(`MIGRATION_TARGET_UNREGISTERED`), the currently bound version
(`MIGRATION_TARGET_UNCHANGED`), and any `dispatched`/`outcome_unknown`
effect (`OUTCOME_UNRESOLVED`): uncertain effects are never migrated past.
The target must accept the current document — a `ValueError` from the
target's document validation surfaces as `CommandError` with nothing
persisted.

The rebind itself is one transaction. The target contract replaces the
binding with `revision = old + 1`; every previously `verified` proof is
revalidated under the target — its kind's configured source must match
the proof's source **and** the target's verifier must accept it, else the
proof becomes `invalid` (previously invalid proofs stay invalid, nothing
resurrects); `revoked` proofs stay revoked — migration records a
revoked→revoked disposition and never revives them (see the evidence
revocation boundary below); `pending_verification` proofs
stay pending, and `verify_pending` applies the same source check before
target validation so an old-source pending proof can never reappear as
verified after a migration. Prepared intents are cancelled with reason
`POLICY_MIGRATED`, waits are cancelled, requirements are re-evaluated by
the target, and an event records actor, reason, old/new binding, evidence
dispositions and invalidated operations. Any exception (including a
target `evaluate`/`validate_evidence` failure) rolls back binding,
evidence, operations and events together. Old command receipts and
external results are retained untouched; restart never implicitly
migrates — the pinned version resolves from the registry or fails closed.
Business-key stability across same-family versions is the policy author's
obligation (the demo policies keep one key function), which is what lets
a cancelled intent re-admit under the same operation identity after
migration.

## Evidence revocation boundary

`revoke_evidence` (payload exactly `source`, `event_id`, `reason` —
nonempty strings; version-bound like every kind except
`create_work`/`record_evidence`) durably withdraws a proof's current
validity. Full command reference, authority model, codes, receipt/event
fields and replacement semantics:
[evidence-revocation.md](evidence-revocation.md).

- It is routed beside `record_evidence`, before the closed-work guard, so
  it is accepted on closed works, unbound works and during an active
  cancellation intent. Authority is a `work.intervene` administrator or the
  currently configured source for the stored proof kind holding
  `evidence.revoke`; unknown-proof commands pass only a conservative
  preliminary check (admin, or `evidence.revoke` plus current-source
  membership) before any lookup, so decision codes never leak evidence
  existence to unauthorized callers.
- The effect is one transaction: the proof body's `status` becomes
  `"revoked"` (rows are never deleted; `id`/`source`/`event_id`/`kind`/
  `data` and the source-event fingerprint column are preserved),
  requirements are recomputed, `state_version` bumps once and one
  `EvidenceRevoked` event records the actual requirement/wait dispositions.
  An exception or a real process death mid-transaction rolls back every
  table together (pinned by snapshot-equality tests).
- Replay reauthorization follows the shared rule: stored receipts —
  accepted or rejected — replay only while current authority holds, else a
  fresh unpersisted `AUTHORITY_DENIED`; the stored receipt is immutable.
- A revoked proof stops satisfying policy rules by construction (both demo
  policies select `status == "verified"`), `verify_pending` and policy
  migration skip it, and restart/recovery never revives it. A **new**
  `record_evidence` command resending the same source event returns the
  existing `evidence_id` plus the candidate's current `evidence_status`
  (additive field; original stored command receipts stay verbatim);
  changed content is still `SOURCE_EVENT_CONFLICT`.
- Closed works keep `status`/`outcome`/`completion` byte-identical — no
  implicit reopen or `needs_attention`; correction is visible only in the
  recomputed requirements, the revoked status and the event. Prepared
  intents are not mutated eagerly: the next `dispatch`/`recover` holds with
  `REQUIREMENT_UNSATISFIED` (zero attempts, zero external calls), and
  in-flight/confirmed operations retain their effects — revocation is not
  compensation and never re-executes a confirmed operation.
- Since the S8 D-1 fix, `_evaluate`'s unbound branch no longer overwrites
  a finalized `closed` status: an unbound work cancelled and finalized
  stays closed under late verification and recovery. The fix guards new
  transitions only — pre-existing persisted erroneous snapshots are not
  rewritten retroactively (recorded limit).

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
- **Poisoned stores recover.** An acceptance whose proof identity is
  already occupied resolves through the collision path above (actual
  confirmed result plus additive snapshot); `recover` no longer aborts on
  such an operation and reaches every later operation.
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
  the external call started cannot revoke it, and neither can a cancellation
  intent: the old operation confirms against the old digest, which satisfies
  only that revision's requirements.
  While that operation is still unresolved, `propose_action` for new content
  is rejected `OUTCOME_UNRESOLVED`: the uncertain operation must be reconciled
  first, and only then can new content be prepared as a new operation (new
  business key), still subject to the external system's own uniqueness
  constraints.
- **Evidence receipts are immutable.** Re-submitting the same source event id
  with different content is `SOURCE_EVENT_CONFLICT`; an `invalid` candidate is
  never overwritten by a corrected re-submission under the same event id, and
  a revoked row is permanent (see the evidence revocation boundary above).
- **`needs_attention` is sticky** until the work closes; reconciliation cannot
  automatically clear it.
- **Corrupted evidence bodies abort only their own resolution.** Conflict
  recovery degrades malformed body fields to `null` snapshots, but a
  conflicting-row body that is not valid JSON is out of scope: the
  resolution fails and rolls back until the store is repaired; the runtime
  offers no such repair.
- **Directly re-`dispatch`ing a `held` intent re-runs the checks** and may
  dispatch if authority and blockers now pass; `recover` never auto-dispatches
  `held` intents — they are re-admitted explicitly through `propose_action`.
- **One policy family per database; versions are pinned per Work.** A work
  whose pinned version is not in the loaded registry raises on access;
  switching versions happens only through the explicit admin
  `migrate_policy` command above. Business-key stability across
  same-family versions is a policy-author obligation; the runtime does not
  rewrite keys.

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

Evidence-revocation guarantees (authority/codes/atomicity, replay
reauthorization, permanence, closed-work correction, crash rollback, both
policy families) are pinned in `tests/test_evidence_revocation.py`; the
test-name table lives in [evidence-revocation.md](evidence-revocation.md).

Accepted-evidence collision guarantees are pinned in
`tests/test_accepted_evidence_collision.py`:

| guarantee | test |
|---|---|
| accepted-source operation-id intake rejected with blockers | `test_operation_id_intake_rejected_for_accepted_source` |
| reservation is global across works | `test_reservation_is_global_across_works` |
| reservation is source-scoped, not kind-scoped | `test_reservation_is_source_scoped_not_kind_scoped` |
| union spans loaded versions and follows reconfiguration | `test_registry_union_spans_loaded_versions`, `test_reservation_union_recomputed_per_intake` |
| publishing family reservation mirror | `test_publishing_operation_id_intake_rejected` |
| legacy poisoned store resolves with actual result and snapshot | `test_legacy_poisoned_store_resolves_with_proof_conflict` |
| snapshot records the row's status at resolution | `test_conflict_snapshot_records_row_status_at_resolution` |
| recover reaches later operations after a conflict | `test_recover_liveness_after_conflict` |
| conflict resolution is crash-atomic (exception) | `test_conflict_resolution_crash_atomic_exception` |
| conflict resolution is crash-atomic (real process death) | `test_conflict_resolution_real_process_death` |
| lost accepted response recovers exactly once | `test_accepted_lost_response_conflict_recovery_confirms_once` |
| closed work keeps closure under conflict | `test_closed_work_conflict_preserves_closure` |
| malformed body fields degrade to null snapshots | `test_malformed_conflict_body_degrades_to_null` |
| publishing family conflict mirror | `test_publishing_legacy_conflict_resolves` |
