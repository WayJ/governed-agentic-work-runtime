# Mixed-node workflow runtime — candidate design (DRAFT)

Status: **RATIFIED AND IMPLEMENTED (phases 1–7), S16.** The coordinator
ratified the core additive direction of phases 1–7, including the disclosed
`work_runtime/runtime.py` freeze exception, and dispatched the
implementation. The engine, the definition language, the generic HTTP bridge
and the ten-node demonstration now exist; §20 records exactly what was
built, what was renamed, and what was deliberately left out. The *design*
below is preserved as written: the labels [exists]/[new]/[open] still mark
what the design proposed, while §20 is the authority on what shipped. The
implemented behaviour is documented in
[docs/workflow-runtime.md](../../workflow-runtime.md). This document
remains the disclosed **freeze-gap finding** owed by the S15 command-surface
freeze: generic mixed-node workflow support cannot be built as family-only
code, because it needs lifecycle edits in `work_runtime/runtime.py` (see
§14).

Scope marker throughout, per the dispatching brief:

- **[exists]** — implemented today at the stated revision, with file evidence.
- **[new]** — proposed addition this design would introduce; not present in
  any form today.
- **[open]** — unresolved design decision the coordinator must settle (§17
  collects them; each carries a recommendation).

Baseline when this document was written: worktree branch
`WayJ/gawr-mixed-node-design` at `222d857` (= published main, clean tree),
`python3 -m unittest discover -s tests` → **1132 tests, OK (2 skipped)**,
`python3 scripts/check_docs.py` → clean. Primary sources read before
proposing anything: [AGENTS.md](../../../AGENTS.md),
[RFC-001](../../../docs/RFC-001-core-semantics.md),
[RFC-002](../../../docs/RFC-002-sop-authoring-and-binding.md),
[RFC-003](../../../docs/RFC-003-runtime-protocol.md),
[runtime boundaries](../../../docs/runtime-boundaries.md),
[interventions](../../../docs/interventions.md),
[evidence revocation](../../../docs/evidence-revocation.md),
[adapter contracts](../../../docs/adapter-contract.md),
[signed evidence](../../../docs/signed-evidence.md),
[SOP authoring](../../../docs/sop-authoring.md),
[verification coverage](../../../docs/verification.md),
[reference scenarios](../../../docs/reference-scenarios.md),
[GUI API](../../../docs/gui-api.md), the runtime implementation
(`work_runtime/runtime.py`, `policy.py`, `adapters.py`,
`adapter_contract.py`, `ingress.py`, `publishing.py`, `support.py`,
`authoring.py`, `publication.py`, `file_adapter.py`, `demo.py`) and the test
suite. Domain examples below reuse only the repository's own demo families
(expense, content publication, support ticket); the design itself is generic
— node kinds, predicates and authorities are named by capability, not by any
product or domain.

## 1. The product model being designed for

The user's accepted product model: a Work's execution may be organized as a
**mixed-node workflow** in which

- **agent nodes** — delegated execution units (an LLM-backed executor is one
  possible executor; a script or a human acting as an operator is another)
  that produce a validated result object,
- **approval nodes** — a designated human authority must approve an exact
  object version,
- **action nodes** — an automatic external effect the runtime itself
  dispatches when the node is ready,
- **wait nodes** — durable waits on events, evidence or time,

progress under **deterministic automatic routing**: which node may run next
is a pure function of stored state — no LLM, no polling heuristic, no
scheduler improvisation. Every node declares **explicit versioned
input/output contracts**, and every produced object is validated before it
can satisfy anything downstream.

That model is *additive*, not a replacement: RFC-001 H3 already holds that a
plan is an optional execution organization and a single action is the
minimal plan. Non-workflow works must keep working unchanged (§14).

## 2. What exists today — and what does not

Honesty first: nothing workflow-shaped exists in the runtime today. The
tables below are the ground truth this design composes with.

### 2.1 Implemented primitives [exists]

| primitive | evidence |
|---|---|
| Command protocol: CAS on whole-Work `state_version` (`expected_version`), durable dedup under `(actor, command_id)` with content fingerprint, immutable receipts, replay re-authorization, `COMMAND_ID_REUSED` | `runtime.py:250-296`, [runtime boundaries](../../../docs/runtime-boundaries.md) three-identity-layers table |
| Command set: `create_work`, `bind_contract`, `revise_plan`, `revise_document`, `register_wait`, `propose_action`, `record_evidence`, `revoke_evidence`, `request_completion`, `request_cancel`, `finalize_cancel`, `transfer_owner`, `migrate_policy` | `runtime.py:366-443` and `_apply` dispatch; [interventions](../../../docs/interventions.md) |
| Requirements (obligation projections) with four-valued applicability `unknown/applicable/not_applicable/conflict` and `pending/satisfied` fulfillment; unknown blocks admission (`APPLICABILITY_UNRESOLVED`) | `policy.py` `evaluate`/`action_blockers`; RFC-001 D3; tests `test_runtime.py` |
| Per-Work pinned policy versions, explicit same-family registry, admin-only `migrate_policy`, fail-closed on missing version | `runtime.py:62-100,171-186,565-624` |
| Evidence lifecycle: source+kind authority at intake, `pending_verification → verified/invalid`, trusted verifier `verify_pending`, permanent `revoked` with requirement re-evaluation, signed ingress with per-source HMAC keys | `runtime.py:768-855,889-912`; [signed evidence](../../../docs/signed-evidence.md); [evidence revocation](../../../docs/evidence-revocation.md) |
| Wait records `{requirement_id, deadline, owner}` with `waiting/triggered/expired/cancelled`, early-arrival matching through evidence-triggered evaluation, expiry escalation to `needs_attention` | `runtime.py:413-421,913-925` |
| Operations: policy-derived `business_key` dedup (`OPERATION_CONTENT_CONFLICT` on same key/different content), `prepared/dispatched/outcome_unknown/confirmed_succeeded/confirmed_failed`, separate `dispatch_state`, attempts, linked compensation variant | `runtime.py:625-718,930-1080` |
| Dispatch boundary: one transaction re-checking staleness/authority/blockers/adapter contract, attempt persisted before the external call, external call outside the transaction; held/cancelled never fabricate failures | `runtime.py:930-1008`; [runtime boundaries](../../../docs/runtime-boundaries.md) dispatch boundary |
| Recovery: `recover()` = `verify_pending` → `expire_waits` → reconcile uncertain via `adapter.lookup` → dispatch still-prepared; uncertain operations never re-dispatched; idempotent repeats | `runtime.py:1140-1194` |
| Cancellation intent + exact-acknowledgement finalize; compensation window with paired capabilities | [interventions](../../../docs/interventions.md); `runtime.py:473-540` |
| Ownership: creator-owned works, `transfer_owner`, dispatch holds non-owner intents | `runtime.py:541-564` |
| Adapter contracts: declared `actions`/idempotency/lookup/uniqueness, capability preflight with zero attempts, receipt validation (`digest`, `status`, `external_id`) | `adapter_contract.py`; [adapter contracts](../../../docs/adapter-contract.md) |
| Three policy families on one frozen Runtime class (expense, content publication, support ticket) | `policy.py`, `publishing.py`, `support.py`; S15 freeze verdict in [runtime boundaries](../../../docs/runtime-boundaries.md) |
| Static SOP rule-card lint + governed immutable publication (cards never execute) | `authoring.py`, `publication.py`; [SOP authoring](../../../docs/sop-authoring.md) |
| Read-only GUI inspection over schema-1 SQLite, exact stored text | `inspection.py`; [GUI API](../../../docs/gui-api.md) |
| Trusted-local boundary: grants map is configuration, not authentication; single coordinator; no distributed exactly-once claim | [runtime boundaries](../../../docs/runtime-boundaries.md) trust model |

### 2.2 Not implemented today — this design must not claim current support

| absent capability | today's nearest behaviour |
|---|---|
| Any node/edge graph structure | `revise_plan` stores opaque step-name lists `{steps, open_requirements, replan_when}`; no dependencies, no branches (`runtime.py:394-401`) |
| Per-node versioned input/output contracts | one work-global `document` with `document_revision`/`document_digest`; policies validate that single document |
| Deterministic automatic routing/progression | the runtime is reactive: state changes only through client commands or trusted-local passes (`verify_pending`, `expire_waits`, `recover`); nothing computes "what runs next" |
| Runtime-initiated proposals | every `propose_action` today is a client command; there is no machine proposer |
| Multiple named business objects per work | exactly one `work["document"]`; `revise_document` is example-specific (`runtime.py:402-412`) |
| Agent executor protocol (task handoff, result submission, validation) | none; agents exist only as grant-holding principals issuing ordinary commands |
| Waits matching anything but a requirement id | `register_wait` keys on `requirement_id` only |
| Node instance storage, workflow versioning, workflow revision commands | none |

## 3. Position: workflows are versioned execution organization; obligations stay authoritative

The design keeps RFC-001's separation of powers intact:

- **A workflow is a Plan-form artifact, not authority.** Routing to a node
  never satisfies an obligation, confers a grant, or shortens an acceptance
  check. Policy admission (`action_blockers`), evidence validation, scope
  and authority checks all run unchanged on every node-initiated effect. A
  workflow whose graph routes to "submit" while the over-limit approval
  obligation is unsatisfied is blocked by the same check that pins P10
  today (plan revision deleting the approval step does not remove E05).
- **Contract stays the goal owner.** `bind_contract` semantics, pinned
  policy versions and `migrate_policy` are untouched; a workflow binds
  *beside* the contract and declares the policy family it expects.
- **Completion stays an acceptance decision.** All terminal nodes is a
  *precondition* visible to the owner, never an automatic close
  (`request_completion` and its full gate remain the only success path,
  RFC-001 D9). **[open U1]** whether a workflow may declare
  `auto_request_completion` — recommendation: no in v1.
- **Unknown never passes** (RFC-001 P3): routing predicates are three-valued
  and `unknown` blocks an edge exactly as `unknown` applicability blocks
  admission today.

## 4. Named versioned business objects [new]

Mixed-node workflows need more than one business object per work (an agent
node's extracted result, an approval subject, an action's external receipt).
The design generalizes today's single document into **named objects**:

- New additive store table `objects(work_id, name, revision, digest, body)`
  where `body` is canonical JSON and `digest = digest(body)` reusing
  `policy.digest` — the same canonicalization already used for documents,
  operations and fingerprints.
- An **object reference** is the exact tuple
  `{work_id, name, revision, digest}`. References are how node input
  contracts, approval subjects and action bindings name data; a reference
  without a matching digest never resolves (§6, readiness).
- New owner command `revise_object {name, object}` (CAS, exact-schema
  payload, `CommandError` on malformed input) appends revision
  *n+1* with a recomputed digest and an `ObjectRevised` event. Revisions
  are append-only, like evidence rows; nothing is ever overwritten.
- **The work-global document is not migrated.** `work["document"]`,
  `revise_document`, and every existing family keep today's semantics
  byte-for-byte. A workflow-bound work may *also* carry named objects; a
  node input contract may reference either an object or the legacy
  document (the legacy document is addressed as the reserved object name
  `"document"`, read-only). **[open U2]** whether v1 lets action nodes bind
  to the legacy document at all — recommendation: yes, as the bridge that
  lets an existing family gain a workflow without rewriting its policy;
  object-bound dispatch then reuses the existing `document_digest`
  admission path unchanged for that case.
- **Structural shape validation** [new]: a small fixed descriptor language
  for output contracts — exact key sets (required/optional), JSON types,
  enums, string length and integer bounds — evaluated by a pure function
  `validate_shape(descriptor, value) -> list[finding]`. It is deliberately
  *not* a programming language; it mirrors the philosophy of
  `validate_evidence` shape checks and the static rule-card lint (never
  executes, never coerces). **[open U3]** descriptor expressiveness
  (no `oneOf`, no regex in v1 — recommendation: keep the closed set and
  grow it only with a lint + test pair).

### 4.1 Validator binding and the self-certification boundary [new]

Every node output is accepted only through a **configured trusted
validator**, resolved by identity and version — never by evaluating
arbitrary natural-language predicates or expression code, and never by
trusting the producing principal's own judgement about its output.

A node's `output.validation` descriptor names
`{validator, validator_version, checks}` and binds three layers:

| layer | what checks it | where it lives |
|---|---|---|
| structural schema | the closed shape-descriptor language above (§4) — exact keys, types, enums, bounds; no user code, no regex, no natural language | fixed pure function in `workflow_spec` |
| business-rule cross-field | a **registered validator object** — trusted local code, configured by the embedding host like a `Policy` today — implementing `validate_output(work, node_ref, value) -> list[finding]`: pure, deterministic, version-pinned | validator registry in runtime configuration |
| trusted evidence/identity | provenance claims (an approval covers this digest, a receipt belongs to this operation) route through the existing machinery: verified proof status, source mapping in `evidence_sources`, digest equality against the pinned reference | existing evidence/operation paths |

Payload text never derives trust: an `approved_by` string carries no
authority; only source-bound, verified evidence does (the standing P5/D14
rule, applied to node outputs).

**Binding precision.** The descriptor pins the validator id **and version**
plus the target object reference `{name, revision, digest}` — the digest
recomputed by the runtime from the submitted body, never taken from the
producer's claim. The pinned tuple (validator id, validator version, node,
attempt, output digest) is recorded on the node instance, so the exact code
version that judged an output stays auditable beside the digest it judged —
the same discipline by which operation admission records bind the inputs
they checked.

**Self-certification boundary.** An executor (agent/model) submits results;
it never certifies them. An accepted `submit_node_result` means "stored and
validated by the configured validator", never "judged correct by its
producer". Whether agent work is good enough is exactly one of: (a)
structurally checkable (closed descriptors), (b) business-checkable
(registered validator code), or (c) checkable only by a human authority —
in which case the workflow must route through an **approval node** binding
that authority's evidence kind. Model self-assessment (confidence,
self-report, reasoning text) is never validation output. An
LLM-as-evaluator exists, if at all, only as a **registered trusted
validator** with an explicit id/version whose acceptance criteria were
themselves host-reviewed — registration is a host trust decision an agent
cannot grant itself (**[open U15]**).

**Failure path.** A failed validation is a persisted business rejection
`WORKFLOW_RESULT_INVALID` carrying the validator id, validator version,
node id, attempt and a bounded finding list (rule/validator ids, static
messages, no content echo — the lint-message discipline). The output is
**not accepted**: no object revision is written, the node does not
complete, downstream routing stays blocked (readiness derives only from
accepted objects, §6), and the node's `on_failure` path runs (default
`escalate` → `needs_attention`). Bounded: no auto-retry, no partial writes.

**Where principals and ACL live.** GAWR remains trusted-local and accepts
only the registered validator interface and configured principal names.
Tenant/workspace principal resolution, authentication and access control
live in the embedding application host — exactly as `grants`, signed-ingress
keys and adapters do today. Validator, policy, executor and runner
registries are host configuration; registering a validator is a host trust
decision, never derivable from workflow data or claimed by a workflow
participant.

## 5. Workflow specification schema [new]

A workflow specification is data, lintable like a rule card and never
executed directly (same precedent as published SOP cards, D62: published
cards never execute — here the *engine* is fixed code and the spec only
parameterizes it). Skeleton (illustrative, not final JSON Schema):

```json
{
  "id": "expense-flow",
  "version": "v1",
  "policy_family": "expense-submit",
  "entry": ["collect"],
  "defaults": {"on_unknown": "block", "on_conflict": "escalate",
               "on_failure": "escalate"},
  "nodes": {
    "collect": {"kind": "agent",
      "executor": "worker-1",
      "inputs": [{"object": "expense_report"}],
      "output": {"object": "expense_report",
                 "validation": {"validator": "expense-shapes", "validator_version": "1",
                                 "shape": {"type": "object", "required": ["id", "amount", "invoices"]}}},
      "max_attempts": 2, "deadline_s": 3600},
    "approve": {"kind": "approval",
      "authority": {"evidence_kind": "approval"},
      "subject": {"object": "expense_report"},
      "on_reject": "escalate", "deadline_s": 259200},
    "submit": {"kind": "action",
      "capability": "expense.submit",
      "subject": {"object": "expense_report"},
      "on_failure": "escalate"},
    "await_receipt": {"kind": "wait",
      "match": {"evidence_kind": "accepted", "subject": {"object": "expense_report"}},
      "deadline_s": 86400, "on_timeout": "escalate"}
  },
  "edges": [
    {"from": "collect", "to": "approve"},
    {"from": "approve", "to": "submit"},
    {"from": "submit", "to": "await_receipt"}
  ],
  "terminal": ["await_receipt"]
}
```

Schema rules (enforced by a new pure lint, §5.1): exact field sets; node ids
unique; every `from`/`to`/`executor`/`evidence_kind`/`capability` reference
declared; `entry` nodes have no inbound edges; `terminal` nodes have no
outbound edges; the graph is a **DAG** in v1 (a cycle is a lint diagnostic —
loops are expressed as an explicit workflow revision, §13; **[open U4]**
whether cycles containing a wait node are admitted later); predicate
expressions bounded in depth; JSON-native preflight and integer-range
checks mirroring `authoring.py` so the same 14-code discipline applies.

Per-kind required fields:

| kind | required fields | meaning |
|---|---|---|
| `agent` | `executor`, `output` (object + validator-bound validation, §4.1), `max_attempts` | delegated execution producing a validated object revision |
| `approval` | `authority.evidence_kind`, `subject`, `on_reject` | a configured evidence source must verify a proof covering the subject's exact digest |
| `action` | `capability`, `subject`, `on_failure` | an automatic external effect through an adapter |
| `wait` | `match`, `deadline_s`, `on_timeout` | durable wait on evidence/node/requirement/time |

All nodes additionally carry optional `deadline_s` (except `wait`, where it
is required) and inherit `defaults` handling for `on_unknown`/`on_conflict`/
`on_failure`.

### 5.1 Static lint and versioning [new]

`workflow_spec.lint(value)` — a new pure module in the `authoring.py`
style: deterministic diagnostics over any Python value, never executes
predicates, never echoes content, bounded messages. Clean specs get a
canonical `workflow_digest(value)` tying every later binding to exact
content (the `sop_digest` pattern). **[open U5]** whether workflow specs
ride the governed SOP publication flow (`publication.py`) — recommendation:
v1 binds specs through an explicit reviewed payload (below) and publication
integration is a follow-up slice, so this design adds no new authority
claims.

Binding commands [new], both owner-gated (`_manager`) and CAS-guarded like
every other mutation:

- `bind_workflow {workflow}` — lint-clean spec digest recorded on the Work
  (`work["workflow"] = {id, version, digest, revision: 1}`); rejected if a
  workflow is already bound, if the contract is absent, or if
  `policy_family` ≠ the bound contract's family (`WORKFLOW_FAMILY_MISMATCH`).
- `revise_workflow {workflow, reason}` — same lint and family checks,
  bumps `workflow.revision`, cancels non-terminal node instances and their
  never-dispatched intents (reason `WORKFLOW_REVISED`), preserves completed
  node outputs, and re-derives readiness from current state (§13).

## 6. Deterministic readiness and routing [new]

`advance(work_id, now)` is a new trusted-local pass (the `verify_pending` /
`expire_waits` / `recover` family — not a client command, no actor). It is
the **only** place node instances change state, and it is a pure
re-derivation over stored state:

```text
route(work) -> {ready: [...], blocked: [{node, reason}], completed: [...]}
```

1. **Readiness of node N**: every inbound edge's predicate evaluates `true`
   (§6.1), and every input reference resolves to a stored object revision
   with a matching digest. Inputs are **snapshotted at activation**: the
   node instance records `{name, revision, digest}` per input, and a later
   object revision does not silently flow into a running node (§13.3).
2. **Completion of node N** is *derived from stored evidence*, not blindly
   stored: an approval node is completed exactly while a `verified` proof
   of its kind covers its pinned subject digest — so a later
   `revoke_evidence` re-opens it (§13.4) with the same mechanism that
   re-opens obligations today.
3. **Routing after completion**: outgoing edges of a completed node are
   evaluated; a node with an unsatisfied-inbound state stays `blocked`
   with a reason object (never skipped, never failed).
4. **No LLM anywhere in `route()`**: predicates are the closed operator set
   of §6.1 over stored objects, evidence statuses, requirement projections
   and node instance states. Executors (which may contain an LLM) sit
   behind node activation, never inside routing.
5. **Termination and determinism**: the graph is finite and acyclic (lint),
   predicates are finite expressions over finite state, and `advance`
   takes `now` as a parameter (the `expire_waits` model — no timers, no
   threads; time-driven transitions are evaluated when a pass runs). Two
   `advance` calls over unchanged state produce byte-identical decisions
   and perform zero writes (pinned by W01).

### 6.1 Predicate language [new]

Closed operator set, three-valued (`true/false/unknown`), JSON-native:

| operator | evaluates |
|---|---|
| `{"op": "always"}` | true |
| `{"op": "node_completed", "node": id}` | terminal-success state of a node instance |
| `{"op": "field", "object": name, "path": [...], "cmp": "eq/ne/gt/ge/lt/le", "value": scalar}` | comparison over a stored object revision's field |
| `{"op": "evidence_verified", "evidence_kind": k, "subject": {...}}` | a verified proof covers the subject digest |
| `{"op": "requirement", "rule": id, "subject": s, "state": "satisfied/not_applicable"}` | a requirement projection's current value |
| `{"op": "all"/"any", "of": [predicates]}` | three-valued conjunction/disjunction |

`unknown` blocks; there is no `not` in v1 (negation over `unknown` invites
default-true mistakes — **[open U6]**, recommendation: omit). Missing
fields, missing objects, `unknown` requirements and `conflict` projections
all evaluate `unknown`. The evaluator is a pure function in the new
`workflow_spec`-adjacent module with its own tests; a predicate that
lint accepts can never loop or read outside the work store.

## 7. The four node kinds

### 7.1 Approval nodes [new, composed from existing evidence machinery]

An approval node names an **authority** — an evidence kind whose configured
source (in the bound policy's `evidence_sources`) is the human authority —
and a **subject** — an object reference. Completion requires a `verified`
proof of that kind whose data covers the subject's **exact digest**
(the E05/E06 discipline: an approval of content H1 never satisfies a node
pinned to H2; T05 pins this today for obligations, W06 pins it for nodes).

- Proof arrival, verification, source authority, dedup by
  `(source, event_id)`, `SOURCE_EVENT_CONFLICT` and signed ingress all ride
  the existing `record_evidence`/`verify_pending` path unchanged.
- The node's `deadline_s` materializes as an ordinary wait record
  (generalized match, §7.4) so expiry escalates through the existing
  `expire_waits` → `needs_attention` path; early-arriving approvals are
  matched because completion is derived from stored evidence (P08
  semantics).
- **Disapproval** is recorded as evidence (the policy's shape decides which
  kind/data expresses rejection); the node routes to `on_reject` — a named
  branch or `escalate`. A rejected approval is a business decision, never a
  technical failure, and never auto-retries (**[open U7]** standardizing a
  disapproval shape across families — recommendation: leave the shape
  policy-owned in v1, as `validate_evidence` is today).

### 7.2 Action nodes [new, composed from existing operation machinery]

An action node declares a `capability` and a `subject` object. When
`advance` finds it ready, the runtime admits the effect **through the
ordinary proposal path** under a dedicated **runner principal**:

- The runner is a configured principal in `grants` holding exactly the
  capabilities the deployment wants machine-dispatched. It is
  configuration, not authentication (the standing trusted-local rule).
- Machine proposals use deterministic command ids
  `wf:<workflow_id>:<node>:<attempt>` so a crash between commit and
  dispatch replays into the stored receipt (D16 command identity; P01/P04
  mechanics verbatim).
- Admission reuses the existing `_propose` checks in order — authority and
  capability, cancellation window, contract/plan/digest matches, policy
  blockers, pending-different-digest guard, business-key dedup and
  re-admission — so a blocked obligation holds the node with
  `REQUIREMENT_UNSATISFIED`/`APPLICABILITY_UNRESOLVED` and **zero external
  calls**, exactly as a client proposal would be held (W09, W10).
- **Object-bound operations** [new]: an operation created for an action
  node carries `{name, revision, digest}` in place of the work-global
  document digest; the staleness checks (admission, dispatch, re-admission)
  compare against that binding instead of `work["document_digest"]`. The
  policy's `operation_key` gains an object-aware form (policy-protocol
  extension; families that never bind workflows are untouched). This is
  the deepest lifecycle edit in the design and the main freeze-gap cost.
- Dispatch, attempt-before-call, receipt validation, quarantine,
  `outcome_unknown`, reconcile-by-business-key, `recover` ordering: all
  existing machinery, unchanged. On `confirmed_succeeded`, the validated
  receipt (e.g. `{status, external_id, digest}`) is adopted as a new object
  revision under the node's declared output object **after the node's
  configured validator accepts it (§4.1)** and the node completes;
  `confirmed_failed` routes to `on_failure`. One external effect per
  (node, attempt, subject revision) across crashes is inherited from the
  business-key discipline (W11, W12).

### 7.3 Agent nodes [new]

An agent node delegates execution to a configured **executor** principal
(the trusted-local component that may host an LLM, a script or a human
operator). The runtime never calls the executor inline; it persists a task
and the executor completes it by command:

- Activation writes a **task outbox record** (node id, attempt, pinned
  input references, output contract descriptor, deadline) — the same
  transactional-outbox shape as dispatch intents, consumed by the
  single-coordinator loop after commit.
- The executor reads the work snapshot (existing `get_work` plus a node
  task read), does its work — including issuing ordinary
  `propose_action`/`revise_object` commands as itself when it holds the
  grants, all normally admitted — and then submits
  `submit_node_result {node, attempt, object, result}` [new]:
  CAS-guarded, deduplicated under `(executor, command_id)`, authority =
  the node's configured executor holding `workflow.execute`.
- The result is validated by the node's configured validator (§4.1);
  the executor's own assessment of its output is never acceptance
  evidence — agent self-certification is structurally impossible because
  acceptance flows only through the registered validator. Invalid results
  are **persisted rejections** (`WORKFLOW_RESULT_INVALID` with validator
  id/version and the finding list) — the node stays incomplete, nothing
  partial is stored (W04). A valid result becomes an object revision; the
  node completes.
- Executor loss is detected by the deadline wait (escalate, no
  auto-restart); bounded `max_attempts` admits a fresh deterministic
  attempt id explicitly. Non-deterministic work is never silently retried
  (the P13 discipline: no invented recovery).

### 7.4 Wait nodes [new, generalizing existing waits]

A wait node declares `match` — `evidence_verified` on a kind/subject,
`node_completed`, `requirement` state, or pure timeout — plus `deadline_s`,
`on_timeout`. It materializes as a wait record whose match key generalizes
today's `requirement_id` to the node's derived condition. Early-arriving
evidence is already durably stored and re-evaluated by `_evaluate`, so
"event before registration" cannot lose the wakeup (P08). Expiry follows
`expire_waits` → `on_timeout` (`escalate` default). Wait nodes never send
requests; a wait that needs an external request pairs with an action node
upstream (the RFC-003 rule that `register_wait` never sends anything).

## 8. Node instance lifecycle [new]

New additive table `node_instances(work_id, node, attempt, state, pinned_inputs,
pinned_subject, outcome, reason)` — **[open U8]** table vs. work JSON
(recommendation: table; the work row keeps only the workflow binding, and
instance churn stays out of the CAS blob). One row per (node, attempt);
attempts are monotonic integers, never reused, never deleted.

```text
blocked → ready → running → completed
                         ↘ failed (reason: validated rejection | on_failure branch)
                         ↘ cancelled (WORKFLOW_REVISED | WORK_CANCELLED | object superseded)
```

Action nodes mirror their operation's status in `outcome` (prepared/
dispatched/outcome_unknown/…) without duplicating it — the operation stays
the truth, the instance points at the operation id. Every transition bumps
`state_version` and appends one event (`NodeActivated`, `NodeCompleted`,
`NodeFailed`, `NodeCancelled`) — D15 unchanged: business state changes bump,
pure re-derivations that change nothing write nothing.

## 9. The advance pass — durable transaction / outbox boundary [new]

`advance(work_id, now)` runs inside **one `BEGIN IMMEDIATE` transaction**
(the `_transaction` context, `runtime.py:151-161`):

1. load work, workflow binding, node instances, objects, evidence,
   requirements, waits, operations;
2. compute `route(...)` (pure, §6);
3. persist, atomically: node instance transitions + events; machine
   command receipts for runner proposals (deterministic ids, §7.2) and the
   operations they admit; agent task outbox records; wait records; any
   work-status change (`_evaluate` extended to account for runnable/
   waiting/blocked node sets — `active` when a node is runnable, `waiting`
   when only waits pend, `needs_attention` when blocked-with-unknown or
   escalated, mirroring today's rules).
4. commit. **Outside** the transaction, the coordinator loop performs the
   existing `dispatch()` for admitted operations and hands agent tasks to
   the executor — external calls never happen inside the transaction
   (the dispatch boundary's standing rule).

Crash semantics: mid-transaction → rollback → the next `advance` recomputes
identically (pure function, deterministic ids); after commit before
dispatch → `recover()` finds `prepared` intents and dispatches them
(existing step 4); repeated `advance` performs zero writes on unchanged
state (W01, W21). `recover()` becomes
`verify_pending → expire_waits → advance → reconcile → dispatch`
(advance before reconcile so newly-ready nodes create intents; reconcile
resolves uncertain ones; dispatch sends prepared ones) — still one
coordinator process, no leases, no threads; the P13 deferral is unchanged.

## 10. Identity and idempotency composition

| layer | identity | existing? |
|---|---|---|
| command receipt | `(actor, command_id)` + content fingerprint; replay re-authorization | [exists] — reused by every new command and by machine proposals |
| operation | policy `business_key` (+ object binding for workflow action nodes) | [exists] / [new] binding |
| attempt | operation attempt rows; "may have happened" persisted before the call | [exists] |
| external effect | adapter idempotency by business key, declared contract | [exists] |
| node attempt | `(work_id, node, attempt)`, monotonic, deterministic ids | [new] |
| machine command id | `wf:<workflow_id>:<node>:<attempt>` | [new] — rides existing dedup |
| object revision | `(work_id, name, revision)` + digest, append-only | [new] |
| workflow revision | `work["workflow"].revision` + spec digest | [new] |

Event idempotency: every new transition appends to the existing
`events` table; `advance` idempotence (W01/W21) keeps repeated passes from
duplicating events, exactly as repeated `reconcile` writes nothing today.

## 11. Authority model additions [new, on the existing trusted-local model]

| principal/grant | holds | acts |
|---|---|---|
| runner (configured name) | machine-dispatched capabilities only | auto-admits action nodes; replay re-authorization applies to its receipts like any actor |
| executor (per-node configured name) | `workflow.execute` + whatever business grants its work needs | reads tasks, issues ordinary commands, submits `submit_node_result` |
| owner / `work.intervene` admin | today's grants unchanged | `bind_workflow`, `revise_workflow`, cancellation, migration |

No new authentication claim: all three are grants-map configuration. The
approval authority remains the policy's `evidence_sources` mapping — a
workflow cannot name an authority the bound policy does not configure
(`WORKFLOW_AUTHORITY_UNKNOWN` at bind time).

## 12. Unknown, conflict and failure semantics

| situation | observed behaviour | mapping |
|---|---|---|
| predicate `unknown` on an edge | node blocked with reason; work `needs_attention` when nothing else runnable | R3/P14 discipline |
| requirement `conflict` | same as today: blocks dependent admission; escalation | [exists] |
| evidence intake conflict (same source event, different content) | `SOURCE_EVENT_CONFLICT`, nothing overwritten | [exists] |
| agent result fails the configured validator | persisted `WORKFLOW_RESULT_INVALID` with validator id/version + finding list; node incomplete; no object revision; downstream blocked | [new] W04 |
| same executor command resent / id reused with new content | stored receipt / `COMMAND_ID_REUSED` | [exists] W05 |
| adapter exception or malformed receipt | `outcome_unknown` quarantine; work `needs_attention`; recoverable via reconcile | [exists] W12 |
| adapter business rejection (`status: "rejected"`) | node routes `on_failure` (a business decision, recorded, never retried as if technical) | [new] on existing resolution |
| executor deadline exceeded | node failed/escalated via wait expiry; no auto-restart | [new] W13 |
| object revised under a running node | node's pinned inputs stale → instance superseded/cancelled; deterministic re-entry under the new revision; in-flight operations keep the `OUTCOME_UNRESOLVED` guard | [new] W03 |
| approval revoked after completion | node re-opens (derived completion), downstream blocks | [exists] revoke + [new] derivation W22 |

New rejection codes (all persisted business rejections, never `CommandError`
misuse labels): `WORKFLOW_NOT_BOUND`, `WORKFLOW_ALREADY_BOUND`,
`WORKFLOW_FAMILY_MISMATCH`, `WORKFLOW_SPEC_INVALID`, `WORKFLOW_NODE_UNKNOWN`,
`WORKFLOW_ATTEMPT_STALE`, `WORKFLOW_RESULT_INVALID`,
`WORKFLOW_AUTHORITY_UNKNOWN`. `CommandError` stays reserved for malformed
envelopes (API misuse), preserving the existing split.

## 13. Cancellation, replan, migration, object revision

1. **Cancellation** [composed]: `request_cancel` cancels non-terminal node
   instances (reason `WORK_CANCELLED`), never-dispatched machine intents
   (existing `_cancel_prepared`), and waits — all in the existing
   transaction. In-flight attempts stay uncertain until reconciled; the
   compensation window and `finalize_cancel`'s exact-acknowledgement gate
   apply verbatim (W17). Executor tasks carry a cancelled marker the
   executor observes; no external fence is claimed for work already sent
   into an executor.
2. **Replan** (`revise_workflow`) [new]: lint + family checks, CAS, bump
   `workflow.revision`, cancel non-terminal instances and prepared intents
   (`WORKFLOW_REVISED`), keep completed outputs, re-derive readiness. An
   uncertain operation still blocks new-content proposals through the
   existing `OUTCOME_UNRESOLVED` guard, so a revision cannot route past an
   unresolved effect (W18). Completed node outputs whose pinned revisions
   still match the new spec's input contracts are reused — the evidence
   reuse discipline of T06/T12 (no forced re-execution).
3. **Object revision** [new]: `revise_object` cancels/supersedes node
   instances pinned to the previous revision of that object (deterministic
   re-entry under the new digest); evidence bound to the old digest stops
   satisfying nodes (the E05/T05 rule generalized). The existing
   `revise_document` behaviour is unchanged for non-workflow works.
4. **Policy migration** [composed]: `migrate_policy` keeps its current
   semantics (rebind, revalidate verified proofs, cancel waits and prepared
   intents, `OUTCOME_UNRESOLVED` gate); the next `advance` re-derives node
   readiness under the new policy's requirements and evidence sources. An
   approval node whose kind's source changed under the target policy
   re-derives accordingly (W19).
5. **Restart**: `recover()` ordering of §9; nothing re-executes completed
   nodes; uncertain operations reconcile; prepared machine intents
   dispatch (W21).

## 14. Compatibility, storage migration and the freeze-gap disclosure

- **Non-workflow works are untouched.** No workflow bound → no node
  instances, no objects required, no `advance` effect (it returns after
  one read), no new commands accepted beyond today's set being extended.
  The full existing suite must stay green with zero behavioural edits
  (W20); the design budget is additive code paths plus the minimal
  refactor that lets `advance` call the same admission helpers `command()`
  calls (shared code, not a duplicate).
- **Storage**: additive tables (`objects`, `node_instances`, task outbox)
  created `IF NOT EXISTS` beside the existing schema; recommendation
  **[open U9]**: keep `metadata.schema_version = "1"` (the GUI inspector
  and every existing store keep working; additive tables are invisible to
  old readers, the FakeOA S10 D46 precedent) — the alternative bump to "2"
  buys a cleaner story for future tooling at the cost of breaking every
  current reader; decide at ratification.
- **Freeze-gap finding (owed by this design)**: the S15 verdict froze
  `work_runtime/runtime.py` and `work_runtime/adapters.py` byte-identical
  and required the next family needing a lifecycle edit to disclose a
  freeze-gap instead of absorbing it. This design **is** that finding:
  generic mixed-node support requires lifecycle edits (new commands,
  object-bound operations, the `advance` pass, generalized wait matches,
  admission-helper refactor). No implementation starts before the
  coordinator ratifies this protocol; when it does, integration must
  record the SHA transition of the previously frozen files.
- **GUI** [later slice]: the read-only inspector gains additive node/
  object reads; per the working agreement any actual UI change follows
  DESIGN.md and needs browser evidence — out of scope here, listed in the
  plan as a separate wave.
- **Doc-sync debts** (the AGENTS.md map, extended at implementation time):
  `work_runtime/workflow_spec.py` → new `docs/workflow-runtime.md`;
  `work_runtime/runtime.py` → `docs/runtime-boundaries.md` (already owed);
  `work_runtime/workflow_demo.py` → `docs/workflow-runtime.md`.

## 15. Trust boundary — restated, not extended

Everything stays trusted-local: principals (runner, executor, owners,
sources) are grants-map configuration, never authentication; one
coordinator process dispatches; no distributed lease, fencing or
exactly-once claim is made or implied (P13 stays deferred). Predicates and
shape descriptors are data interpreted by fixed code — no arbitrary code
execution enters the runtime with this design. Workflow specs never
execute, exactly like published SOP cards. The design adds no network,
service, credential or tenant capability.

## 16. TDD acceptance matrix [new]

Concrete, injectable, side-effect-counting — the P-matrix discipline
(observe external effects, receipts and events, never just a return
value). Proposed ids W01–W26; existing mappings reuse the P/T/R ids.

| id | injected condition | must observe | mapping |
|---|---|---|---|
| W01 | `advance` twice over unchanged state | byte-identical routing decisions; zero writes; zero external calls | determinism, P-matrix style |
| W02 | predicate evaluates `unknown` (missing field / unknown requirement) | edge blocked with reason; work `needs_attention` when nothing runnable; no routing around | R3, P14 |
| W03 | object revised after node activation | pinned inputs stale → instance superseded; new attempt binds new digest; old approval does not satisfy | T05, T12 |
| W04 | agent submits result the configured validator rejects | persisted `WORKFLOW_RESULT_INVALID` carrying validator id/version + bounded findings; node incomplete; no object revision; downstream blocked | §4.1 |
| W05 | executor result command resent / id reused with new content | stored receipt verbatim / `COMMAND_ID_REUSED` | P01, P02 |
| W06 | approval proof covers subject v1 while node pinned v2 | node not completed; blocked with digest mismatch reason | E05, T05 |
| W07 | approval arrives before node activation | stored evidence satisfies node on first derivation; no lost wakeup | P08 |
| W08 | disapproval evidence recorded | `on_reject` branch or escalation; work never auto-closed; no retry | business-rejection discipline |
| W09 | action node ready while policy blocker unsatisfied | node held with `REQUIREMENT_UNSATISFIED`/`APPLICABILITY_UNRESOLVED`; zero external calls | P10, P14 |
| W10 | runner principal lacks the node capability | machine proposal denied `AUTHORITY_DENIED`; zero external calls; node visible-blocked | P11 |
| W11 | crash after `advance` commit, before dispatch; then `recover` | exactly one operation, one external effect; node completes once | P05, P06, P07 |
| W12 | adapter timeout after external commit | `outcome_unknown` → reconcile by business key → node completes once | P04, P07 |
| W13 | wait deadline exceeded | wait expired, `on_timeout` escalation, `needs_attention`; no auto-retry | wait boundary |
| W14 | matched event arrives before wait registration | durable intake; wait completes on derivation | P08 |
| W15 | two independent action branches ready | both admitted and dispatched (serialized single coordinator); both complete; two effects | concurrency model |
| W16 | conditional edge on numeric object field | deterministic branch; same decision across replays | §6.1 |
| W17 | `request_cancel` mid-workflow | nodes cancelled; prepared intents `WORK_CANCELLED`; finalize still gates on unresolved operations | interventions |
| W18 | `revise_workflow` with an in-flight uncertain operation | revision accepted or deferred per `OUTCOME_UNRESOLVED` (never routed past); completed outputs reused when digests match | plan revision, T09 |
| W19 | `migrate_policy` on a workflow-bound work | existing migration semantics; next `advance` re-derives; fail-closed on unloaded version | policy migration |
| W20 | non-workflow work on a migrated store | behaviour byte-identical; full existing suite green | compatibility |
| W21 | restart mid-everything; `recover` twice | node states restored; no completed node re-executed; second `recover` writes nothing | recovery contract |
| W22 | `revoke_evidence` on a completed approval node's proof | node re-opens; downstream blocks; closed-work correction rules apply | evidence revocation |
| W23 | machine proposal replay after crash | stored receipt returned; no second operation | D16 |
| W24 | workflow spec lint: cycle, unknown ref, bad predicate, depth | exact diagnostics, exit-shape parity with `lint-sop`; clean digest stable | authoring discipline |
| W25 | `revise_object` malformed/CAS-stale/mismatched shape | `CommandError`/`STATE_VERSION_CONFLICT`/rejection as specified; append-only history | command protocol |
| W26 | read-only inspector over a workflow store | additive node/object reads; zero writes; exact stored text | GUI API contract |

W26 belongs to the GUI wave and may be delivered after the core waves; the
core matrix for ratification is W01–W25.

## 17. Unresolved design decisions [open]

| id | question | recommendation |
|---|---|---|
| U1 | automatic completion request when all terminal nodes complete | no in v1; completion stays an explicit owner decision (D9) |
| U2 | action nodes binding the legacy work document | allow as the family bridge; object binding is the general path |
| U3 | shape-descriptor expressiveness | closed minimal set (types, keys, enums, bounds); grow only with lint+test pair |
| U4 | cycles in the workflow graph | DAG only in v1; loops = explicit `revise_workflow`; revisit cycles-with-wait later |
| U5 | workflow specs through governed SOP publication | defer; v1 binds reviewed payloads explicitly |
| U6 | negation operator in predicates | omit in v1 (unknown-negation hazard) |
| U7 | standardized disapproval evidence shape | policy-owned in v1, like `validate_evidence` |
| U8 | node instances in a table vs. work JSON | table (keeps CAS blob small; instances churn) |
| U9 | `schema_version` bump vs. additive-under-1 | additive-under-1 with disclosure; decide at ratification |
| U10 | multiple executors per node / executor pools | single configured executor per node in v1 |
| U11 | agent-node heartbeats vs. deadline-only | deadline-only in v1 (wait machinery); heartbeats later |
| U12 | bounded machine retry of transient action failures | no auto-retry; fresh attempt is an explicit workflow/attempt-policy act |
| U13 | whether `advance` also runs opportunistically after every accepted command (in-process hook) vs. only in `recover`/explicit loop | run inside `recover` plus after accepted commands that touch workflow state; keep it a pure pass either way |
| U14 | first adopting family for the demo (new fourth family vs. extending an existing one) | new small family keeps the three existing stores byte-stable; extending the support family exercises the legacy-document bridge (U2) — master's call |
| U15 | admitting LLM-as-evaluator as a registered trusted validator | permitted only as a host-registered, version-pinned validator whose acceptance criteria were reviewed like any trusted-local code; never registered by a workflow participant, never self-certifying |

## 18. Implementation plan

A scoped, phased plan — TDD-first, one phase per reviewable increment — is
at [2026-10-21-mixed-node-workflow-runtime-plan.md](../plans/2026-10-21-mixed-node-workflow-runtime-plan.md).
It starts only after the coordinator ratifies this design; it changes no
source until then.

## 19. What this document does not claim

No current workflow support of any kind (§2.2 is exhaustive); no
implementation started; no distributed, multi-process, authenticated,
tenant, production-safety or LLM-reliability claim; no claim that the
three existing demo families adopt workflows; no UI change. Every
existing primitive is cited to code or docs, and every proposed element is
labelled [new] or [open] — where this document is silent, today's
behaviour stands.


## 20. Implementation status (S16, after ratification)

The coordinator ratified the core additive direction of phases 1–7,
including the disclosed `runtime.py` freeze exception. The implementation
lives in `work_runtime/workflow_spec.py`, `work_runtime/workflow.py`,
`work_runtime/workflow_server.py` and `work_runtime/workflow_demo.py`; the
shipped behaviour is documented in
[docs/workflow-runtime.md](../../workflow-runtime.md) and the evidence in
[docs/verification.md](../../verification.md).

What the implementation settled, against this design:

| question | design said | implementation |
|---|---|---|
| `entry` in the definition | `"entry": ["collect"]` (§5 sketch) | a single node id; the lint rejects a list (`EDGE_REFERENCE_UNKNOWN`) |
| the approving principal of a human node | `authority.evidence_kind` (§5) | the kind selects the source; an explicit `authority` field additionally pins the principal, and a decision from anyone else is refused (`WORKFLOW_AUTHORITY_MISMATCH`) |
| node kinds | `approval` (§5 table) | `human` — the same role under the name the engine and the demonstration use |
| named objects | `objects(work_id, name, revision, digest, body)` (§4) | as designed, under the table name `workflow_objects`; the reserved `"document"` bridge to the legacy work document (U2) is **not** implemented in this slice |
| an automatic action | machine proposal (§7) | the existing proposal path, object-bound, proposed by the work owner; the configured runner is recorded for audit |
| `revise_workflow` / `migrate` | listed as later phases | **not** implemented and **not** offered as a shortcut: a changed definition is a new published version, and a running instance keeps the digest it pinned |
| the advance pass | a transaction with an outbox (§9) | one transactional routing pass; the external dispatch stays outside the transaction, exactly like every other dispatch |
| `advance` after a command | U13 | yes, and also after a *rejected* command that changed stored state (a rejected candidate fails its node and opens a rework attempt) |

Deliberately not shipped, and not claimed: authentication, tenant
isolation, distributed leases or exactly-once, an arbitrary dynamic graph at
instance time, a workflow revision command, a GUI, and any semantic proof
that a model's judgement is correct.

## 19. What this document does not claim