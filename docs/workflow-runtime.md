# Mixed-node workflow runtime

This document records what the mixed-node workflow runtime actually does
today: the definition language, the engine, the HTTP bridge and the
demonstration. It is the reference for reviewing changes to
`work_runtime/workflow.py`, `work_runtime/workflow_spec.py`,
`work_runtime/workflow_server.py` and `work_runtime/workflow_demo.py`.

The system is a **local, single-coordinator, trusted-local** runtime. It
composes the primitives that already existed — Work, CAS on `state_version`,
command dedup under `(actor, command_id)`, Evidence, Wait, Operation/Attempt,
adapter dispatch and reconcile — into a workflow that may mix agent nodes,
human approval nodes, automatic action nodes and wait nodes. It adds no
network service of its own beyond the optional loopback bridge, and it
claims **no distributed exactly-once, no tenant isolation, no authentication
and no production-safety property**.

Nothing in the core knows a business domain. Node kinds, authorities,
capabilities, validators, checks and routing predicates are declared by a
*published definition* and by host configuration. The construction-shaped
scenario in [the demonstration](#the-demonstration) is data, not code.

## 1. The definition language

A workflow definition is data. It is linted, digested and published like a
rule card, and it never executes: the engine is fixed code and the
definition only parameterizes it.

```json
{
  "id": "inspection-review-delivery",
  "version": "test-1",
  "policy_family": "workflow-demo",
  "entry": "n01",
  "terminal": ["n10"],
  "required_checks": ["N01-1", "N04-2"],
  "parameters_schema": {"type": "object", "properties": {"subject": {"type": "string"}},
                         "required": ["subject"]},
  "nodes": {
    "n03": {"kind": "agent", "executor": "agent-executor", "max_attempts": 2,
            "inputs": [{"object": "analysis"}],
            "output": {"object": "proposal",
                       "validation": {"shape": {"type": "object", "required": ["measures"]},
                                      "validator": "proposal", "validator_version": "1"}},
            "checks": ["N03-1"]},
    "n04": {"kind": "human", "evidence_kind": "safety_review",
            "authority": "reviewer-a", "subject": {"object": "proposal"},
            "on_reject": "n03", "max_attempts": 3},
    "n06": {"kind": "action", "capability": "work.dispatch",
            "subject": {"object": "proposal"}}
  },
  "edges": [{"from": "n03", "to": "n04"}, {"from": "n04", "to": "n05"},
            {"from": "n05", "to": "n06"}]
}
```

Top level: `id`, `version`, `policy_family`, `nodes`, `edges` are required;
`entry`, `terminal`, `parameters_schema`, `required_checks` and `description`
are optional. `entry` is a single node id (not a list). Advance edges must
form a DAG; rework branches (`on_reject`, `on_failure`, `on_timeout`) may
point backwards and are not part of that check.

Per node kind:

| kind | required | optional |
|---|---|---|
| `agent` | `executor`, `output`, `max_attempts` | `inputs`, `checks`, `on_failure`, `deadline_s`, `max_attempts`, `description` |
| `human` | `evidence_kind`, `subject` | `authority`, `distinct_from`, `on_reject`, `max_attempts`, `checks`, `deadline_s`, `description` |
| `action` | `capability`, `subject` | `on_failure`, `deadline_s`, `description` |
| `wait` | `match`, `deadline_s` | `on_timeout`, `description` |

`authority` names the principal that may decide a human node. It is checked
against the proof's source; the proof itself can only be written by the
policy's configured source for the node's `evidence_kind`.

### Lint

`work_runtime.workflow_spec.lint_template(value)` returns a bounded list of
`{code, path, message}` diagnostics and never executes anything, never
coerces a value and never echoes payload content. The codes are:

`SPEC_NOT_OBJECT`, `SPEC_FIELD_MISSING`, `SPEC_FIELD_UNKNOWN`,
`SPEC_FIELD_TYPE`, `SPEC_TOO_LARGE`, `NODE_ID_INVALID`, `NODE_KIND_UNKNOWN`,
`NODE_FIELD_MISSING`, `NODE_FIELD_UNKNOWN`, `NODE_FIELD_TYPE`,
`EDGE_REFERENCE_UNKNOWN`, `EDGE_SELF`, `ENTRY_AMBIGUOUS`,
`ENTRY_HAS_INBOUND`, `TERMINAL_HAS_OUTBOUND`, `GRAPH_CYCLE`,
`PREDICATE_INVALID`, `PREDICATE_TOO_DEEP`, `SHAPE_INVALID`, `SHAPE_TYPE`,
`SHAPE_TYPE_UNKNOWN`, `SHAPE_FIELD_UNKNOWN`, `SHAPE_TOO_DEEP`.

`template_digest(spec)` is the canonical content digest of a definition; it
is stable across key order.

### Shapes and validators

Two closed, bounded languages describe what an output may contain. Neither
executes anything and neither accepts user code.

* **Shape descriptor** — exact key sets, JSON types, enums, string length and
  integer bounds. `validate_shape(descriptor, value)` returns bounded
  findings (`SHAPE_TYPE`, `SHAPE_MISSING_FIELD`, `SHAPE_UNEXPECTED_FIELD`,
  `SHAPE_RANGE`, `SHAPE_LENGTH`, `SHAPE_ENUM`). `additionalProperties`
  defaults to `false`, so an undeclared field is a finding.
* **Registered validator** — a host-registered, version-pinned callable
  `validate(work, node_ref, value) -> list[finding]`. Registering one is a
  host trust decision; a workflow participant can never grant itself a
  validator. An unknown id *or* an unknown version fails closed at
  publication and again at binding.

### Predicates

Routing edges may carry a `when` predicate. The evaluator is three-valued:
`true`, `false` or `unknown`, and **unknown blocks the edge** exactly like
an unresolved obligation blocks an action. Operators: `always`,
`node_completed`, `field`, `evidence_verified`, `requirement`, `all`, `any`.
There is no negation, no user expression and no natural-language predicate.

## 2. Publication, binding and provenance

* `publish_template(actor, spec)` lints the definition, resolves every
  referenced validator at its exact version, and stores it content-addressed.
  Re-publishing the same id and version with different content is refused
  (`WORKFLOW_TEMPLATE_IMMUTABLE`); the same content is accepted idempotently.
* `bind_workflow` pins `{template_id, template_version, digest}` on the work.
  It fails closed when the published definition is unknown
  (`WORKFLOW_TEMPLATE_UNKNOWN`), the policy family differs
  (`WORKFLOW_FAMILY_MISMATCH`), the parameters do not match the declared
  schema (`WORKFLOW_PARAMETERS_INVALID`), a validator does not resolve
  (`WORKFLOW_VALIDATOR_UNKNOWN`), an authority is not a configured evidence
  source (`WORKFLOW_AUTHORITY_UNKNOWN`), a required check is not covered by
  any node (`WORKFLOW_REQUIRED_CHECKS_MISSING`) or a capability is not
  supported by the policy (`WORKFLOW_CAPABILITY_UNSUPPORTED`).
* A binding is therefore always checkable against the exact bytes it pinned:
  a mutable runtime cannot weaken a published definition, because the
  definition that was bound is immutable and the binding records its digest.
* **Arbitrary dynamic graphs are not supported.** A work binds one published
  definition; there is no endpoint that accepts a graph at instance time.
  The only instance-time freedom is `parameters`, validated against
  `parameters_schema`.

## 3. Nodes

### Agent nodes

An agent node delegates execution to the configured `executor`. The engine
writes a durable `agent_task` intent (see §6) and waits. The executor
submits a candidate with `submit_node_result {node, attempt, object, result}`:

* the actor must hold `workflow.execute` **and** be the node's `executor`;
* the attempt must be the node's current attempt (`WORKFLOW_ATTEMPT_STALE`);
* the payload's `object` must be the node's declared output object
  (`WORKFLOW_OBJECT_MISMATCH`);
* the result is validated by the shape descriptor and by the registered
  validator. A rejection is a persisted business rejection
  (`WORKFLOW_RESULT_INVALID`) carrying the validator id, its version and a
  bounded finding list. **Nothing is stored**: no object revision is written,
  the node does not complete and downstream routing stays blocked.

**Self-certification is not a validation path.** A payload that claims
`"validated": true` is an undeclared field (a shape finding) or a payload
the registered validator rejects. Model self-assessment is never validation
output; the acceptance of a candidate means "stored and validated by the
configured validator".

When the node declares `review: {evidence_kind: …}`, the accepted candidate
moves the node to `submitted` and waits for a **verified review proof whose
digest covers the candidate**. The review is asynchronous durable evidence:
the node stays pending until the proof arrives, and a program check never
pretends to have proved a model's semantic judgement.

### Human nodes

A human node waits for a decision proof:

* the proof must be `verified`, of the node's `evidence_kind`, and carry
  `decision` (`approved` / `rejected`), the **exact digest and revision of
  the subject object**;
* the source must be the node's `authority` (or the policy's source for the
  kind). A decision from anyone else is refused
  (`WORKFLOW_AUTHORITY_MISMATCH`);
* an **executor may never approve** (`WORKFLOW_EXECUTOR_MAY_NOT_APPROVE`) and
  a reviewer may not repeat another reviewer's role
  (`WORKFLOW_ROLE_ISOLATION`, declared per node with `distinct_from`). A
  violating decision does not advance the node; it is recorded as a bounded
  finding and the node keeps waiting.

A stale decision never satisfies a node: after a rework the subject has a
new revision and digest, so the previous approval stays on the record but no
longer covers the current version.

### Action nodes

An action node prepares an **operation** through the existing proposal path,
so the policy's admission checks (obligations, authority, contract and plan
revisions) still decide whether the effect may leave. The operation is
object-bound: it names the exact object revision and digest, so the business
key is stable and a replay re-associates the existing operation instead of
creating a second one.

The action is proposed by the work **owner** — binding a published definition
is the owner's authorization of its action nodes — and the configured
`runner` is recorded on the node instance for audit. The external call
happens outside the routing transaction, exactly like every other dispatch.

An operation whose outcome is unknown is **looked up, never repeated**
(`runtime.reconcile`).

### Wait nodes

A wait node matches on a verified proof (`evidence_kind`, optionally scoped
to an object subject), on a completed node, or on a timeout. A proof that
does not cover the object's current revision does not match.

## 4. Routing, rework and the failure table

`advance(work_id, now)` is one deterministic routing pass over the stored
state. It is idempotent: a pass that changes nothing writes nothing — no
version bump, no event.

| situation | behaviour |
|---|---|
| node ready | the node instance opens, its inputs and subject are resolved and pinned, and its kind-specific work starts |
| input or subject missing | the node is `blocked` with a bounded finding (`INPUT_MISSING`, `SUBJECT_MISSING`); it re-resolves on the next pass |
| a decision or a candidate is missing | the node keeps waiting; a deadline turns it into `expired` |
| human decision `rejected` | the node's `on_reject` branch is taken |
| agent candidate invalid | the node fails with `WORKFLOW_RESULT_INVALID` and the same node is re-opened as a **new attempt**; the bounded `max_attempts` decides when the work escalates to `needs_attention` (`WorkflowReworkLimitExceeded`) |
| operation confirmed failed | the node fails; `on_failure` is taken |
| operation cancelled | the node fails with `OPERATION_CANCELLED`; `on_failure` is taken |
| predicate unknown | the edge is blocked; the work reports `needs_attention` |
| last node terminal | the workflow is `finished` — a **precondition**, never an automatic close; `request_completion` and its full gate remain the only success path |

Rework increments the attempt, keeps the old attempt and its evidence on the
record, and invalidates the affected approval by exact version. A callback
for a completed, superseded or cancelled attempt is refused
(`WORKFLOW_ATTEMPT_STALE`): it can never revive a finished instance.

## 5. Obligations stay authoritative

A workflow is an execution *organization*, not authority:

* routing to a node never satisfies an obligation, confers a grant or
  shortens an acceptance check. The policy's `action_blockers` still decide
  whether an effect may leave;
* the obligation rules of the family are evaluated from the work document
  and the evidence ledger, exactly as they are without a workflow. The
  demonstration family's rules are **kind-level** gates (a verified project
  approval exists); the *exact version* of every approval is enforced by the
  engine, not by the obligation layer;
* the contract stays the goal owner, the pinned policy version stays pinned,
  and completion stays an acceptance decision.

## 6. Durable intents and the platform bridge

The engine writes an **intent** whenever a node needs something from
outside: an `agent_task` for an executor, a `human_task` for a reviewer.
An intent is durable, has a stable id
(`wf:<workId>:<node>:<attempt>:<kind>`) and is readable and acknowledgeable
by a bridge:

```python
engine.intents(kind="agent_task", session_id=..., status="pending")
engine.acknowledge_intent(actor, intent_id)
```

The agent task carries the **original session** id, so a platform bridge can
deliver the work back to the session that started it, with a stable request
id, without a second session and without a poll loop.

Intents are cancelled when their node is cancelled, when the object they
pinned is superseded, or when the work is cancelled.

## 7. The HTTP bridge

`work_runtime/workflow_server.py` exposes a **generic** `/v1/workflows`
surface. It is separate from any product-specific delivery route: the
existing `/v1/deliveries` contract of the embedding platform is untouched,
and the bridge never becomes a task-delivery shortcut.

| method | path | purpose |
|---|---|---|
| `GET` | `/v1/workflows` | health: the coordinator model and the workflow count |
| `GET`/`POST` | `/v1/workflows/templates` | list / publish a definition |
| `GET` | `/v1/workflows/templates/{id}/{version}` | the published definition and its digest |
| `POST` | `/v1/workflows/instances` | instantiate: work, contract, plan, binding |
| `GET` | `/v1/workflows/instances/{workId}` | the bounded read model |
| `POST` | `/v1/workflows/instances/{workId}/results` | submit an agent candidate |
| `POST` | `/v1/workflows/instances/{workId}/decisions` | record a human decision |
| `POST` | `/v1/workflows/instances/{workId}/objects` | revise a named object |
| `GET` | `/v1/workflows/instances/{workId}/intents` | the durable intents |
| `GET` | `/v1/workflows/instances/{workId}/events` | the event history |
| `POST` | `/v1/workflows/intents/{intentId}/ack` | acknowledge an intent |
| `POST` | `/v1/workflows/instances/{workId}/advance` | settle on demand |

The read model is bounded: at most 64 nodes, 32 intents and 16 findings per
node, and it never returns payload bodies. Errors are
`{"error": {"code", "message", "findings"}}` with the engine's code verbatim.

Two properties matter to a client:

* **the bridge never trusts the body about identity.** The approving
  principal is resolved from the published node and the policy's source
  registry. A request may state the authority, but only to be checked
  against it.
* **progress does not need a client to poll.** Every mutating call settles
  the workflow before it answers, and a background ticker advances and
  recovers the store on its own schedule. The bridge logs the method and the
  path only: a credential in a body never reaches the log, and fields that
  look like credentials are stripped from every response.

The bridge is **single-coordinator**: `CoordinatorLock` takes an operating
system file lock over the store, so a second coordinator fails fast instead
of racing the command dedup.

## 8. Recovery

`engine.recover(adapter, now)` runs, in order: evidence verification, wait
expiry, cancellation of a cancelling work, a routing pass, the runtime's
reconcile-and-dispatch pass, and a final routing pass so a node that was
waiting for a confirmed operation settles.

`engine.pump(adapter, now)` is the steady-state loop: route, dispatch the
actions the routing created, route again. The dispatch is outside the
routing transaction.

A crash never means "the exception was caught and ignored": the
demonstration kills a real worker process after the external effect and
restarts.

## 9. The demonstration

`python3 -m work_runtime workflow-demo` runs the ten-node scenario on a
fresh store:

| node | kind | what it shows |
|---|---|---|
| N01 | agent | material intake, accepted only by the registered validator |
| N02 | agent | analysis against the accepted input |
| N03 | agent | the proposal, frozen as an object revision |
| N04 | human | the safety review; its approval creates N05's task with **no agent turn** |
| N05 | human | the project approval; it dispatches **exactly one** idempotent external action |
| N06 | action | the external dispatch, performed by a worker that **really dies** after the effect |
| N07 | human | the responsible person's report |
| N08 | human | the independent review; its approval queues the **original session**'s agent work |
| N09 | agent | the report, completed only after the independent review evidence arrives |
| N10 | action | the delivery |

The external effects are counted in the business system's own store, never
in the process that produced them: after the crash and the restart the count
is one dispatch and one delivery.

The scenario is data: `work_runtime/workflow_demo.py` holds a demonstration
*family* (policy, validators, template, stand-in system). Replacing it with
another family does not touch the engine.

## 10. The `runtime.py` freeze exception (disclosed)

The S15 verdict froze `work_runtime/runtime.py` for new families. Generic
mixed-node support cannot be built as family-only code, so this slice edits
that file additively, with the before/after digests recorded here and in
[the sprint report](superpowers/sprints/2026-10-21-S16-mixed-node-plan.md):

| file | SHA-256 before | SHA-256 after |
|---|---|---|
| `work_runtime/runtime.py` | `80bf721b3369a6fb865fd6aba0e57804a69eb8587431f8fa6edf1183fc53f4b3` | see the sprint report |
| `work_runtime/adapters.py` | `ce132f24d84c17a083bcf0b61bf90e1c62ff75faf2ec52fe2c7348ab86b6985e` | unchanged |

The edits are: four workflow tables under the existing schema version, the
dispatch of the workflow command kinds, the workflow status in `_evaluate`,
the object binding of a proposal, and the cancellation hook. **Non-workflow
works keep their previous behaviour**: the existing suite is the regression
net, and the byte pin in `tests/test_publishing_compensation.py` is updated
consciously, never silently.

## 11. What is deliberately not here

* No authentication, no tenant isolation, no distributed leases or fencing,
  no distributed exactly-once. Principals are trusted local configuration.
* No arbitrary dynamic graph at instance time, no workflow revision command,
  no `migrate`/`revise` shortcut for a running instance: a changed
  definition is a new published version, and a running instance keeps the
  digest it pinned.
* No GUI: the read model is a read model. The read-only GUI wave is a
  separate slice.
* No semantic validation of a model's judgement. A review is durable
  evidence, and a program check never claims to have proved meaning.
* The obligation layer of a family is kind-level; the *exact version* of an
  approval is an engine guarantee, not an obligation.
