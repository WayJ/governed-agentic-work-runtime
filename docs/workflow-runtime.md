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
| `human` | `evidence_kind`, `subject` | `authority` (a principal or `{"assigned": true}`), `distinct_from`, `on_reject`, `max_attempts`, `checks`, `output`, `inputs`, `deadline_s`, `description` |
| `action` | `capability`, `subject` | `output`, `checks`, `inputs`, `on_failure`, `deadline_s`, `description` |
| `wait` | `match`, `deadline_s` | `output`, `checks`, `on_timeout`, `description` |

An `output` is `{object, evidence_kind?, validation}`: the named object the
node produces, the kind of the event it constitutes (optional) and the
validation that judges it. A `subject` is `{object, validation?}`: a
subject that declares a validation is a protected input. A `wait` `match`
declares exactly one of `evidence_kind`, `node_completed` or `timeout`, and
may additionally declare `subject` and `bind`.

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
`SHAPE_TYPE_UNKNOWN`, `SHAPE_FIELD_UNKNOWN`, `SHAPE_TOO_DEEP`,
`NODE_JUDGE_MISSING`.

`NODE_JUDGE_MISSING` is the orphan-judge rule: a **required** criterion
whose judge is `AGENT` needs a declared review path, and a **required**
criterion whose judge is `PROGRAM` needs an output validator — the program
is the only judge that runs in the input/output phase. A criterion with no
judge that can actually run is refused at publication, so it can never
become a completed node that triggers effects.

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

### Declared criteria

A node's `checks` are **declarations**, not identifiers:

```json
{"id": "N04-2",
 "criterion": "The proposal covers every applicable requirement.",
 "method": "HUMAN", "criterion_version": "1",
 "validator": "safety-review", "validator_version": "1",
 "required": true, "allow_not_applicable": false}
```

The `method` names the judge the definition expects (`PROGRAM`, `AGENT` or
`HUMAN`), so a reader can show who checks a criterion before any report
exists. A criterion that is first checked by a program and then reviewed
by a model keeps two declarations with two identifiers and therefore two
independent records; a node may not declare the same identifier twice.

The criterion text is part of the protected definition: a binding pins the
digest, so the text a reviewer read is the text that is enforced. The
optional `validator` binding names the judge of that criterion and must
resolve at its exact version, or the definition is not publishable
(`WORKFLOW_VALIDATOR_UNKNOWN`).

Every declared criterion needs a **verdict**, a reason and its evidence,
and the verdict is persisted on the node instance — the read model returns
the full report (`checkResults`), never only the identifier:

| source | who judged it | where the verdict comes from |
|---|---|---|
| `validator` | the configured, version-pinned validator | the validator's per-criterion report; a declared criterion without a verdict refuses the candidate (`WORKFLOW_CHECK_RESULT_MISSING`) |
| `decision` | the human who decided | the decision's `items`; a declared criterion without a verdict leaves the node waiting (`WORKFLOW_CHECK_RESULT_MISSING`) |

### Agent nodes

An agent node delegates execution to the configured `executor`. The engine
writes a durable `agent_task` intent (see §6) and waits. The executor
submits a candidate with `submit_node_result {node, attempt, object, result}`:

* the actor must hold `workflow.execute` **and** be the node's `executor`;
* the attempt must be the node's current attempt (`WORKFLOW_ATTEMPT_STALE`);
* the candidate must be bound to the **input digest** the node currently
  pins (`WORKFLOW_INPUT_STALE`): a candidate produced from a superseded
  input is refused;
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
  `decision` (`approved` / `rejected` / `request_material`), the **exact
  digest and revision of the subject object**, the **node and attempt** it
  was made for, the **actor** who decided, and the itemized `items`;
* a decision of an earlier attempt never satisfies a later one, even when
  the content digest is identical: the attempt is part of the binding;
* the **actor** must be the node's effective authority: a static
  `authority`, or — when the definition says `{"assigned": true}` — the
  principal the trusted participant resolver currently resolves. A decision
  from anyone else is refused (`WORKFLOW_AUTHORITY_MISMATCH`), and the
  assignment is re-resolved at settlement, so a withdrawn assignment stops
  a decision that was already written;
* the proof's **source** is the platform ingress. It is never the actor:
  the source says which channel carried the decision, and the separation
  rules are checked against the actor;
* a decision of `request_material` keeps the node waiting. It is neither an
  approval nor a rejection: it does not complete the node and it opens no
  rework attempt. The request is persisted on the instance;
* an **executor may never approve** (`WORKFLOW_EXECUTOR_MAY_NOT_APPROVE`) and
  a reviewer may not repeat another reviewer's role
  (`WORKFLOW_ROLE_ISOLATION`, declared per node with `distinct_from`). A
  violating decision does not advance the node; it is recorded as a bounded
  finding and the node keeps waiting.

A stale decision never satisfies a node: after a rework the subject has a
new revision and digest, so the previous approval stays on the record but no
longer covers the current version.

### Human nodes

A human node may also declare the **named record** its decision carries:

```json
"n04": {"kind": "human", "evidence_kind": "safety_review",
        "authority": "reviewer-a", "subject": {"object": "proposal"},
        "output": {"object": "safety_approval",
                   "validation": {"shape": {"…": "…"},
                                  "validator": "record", "validator_version": "1"}},
        "checks": [{"id": "N04-2", "method": "HUMAN", "criterion": "…"},
                   {"id": "N04-3", "method": "PROGRAM", "criterion": "…"}]}
```

The record travels **with the decision**: `record_decision` accepts an
optional `result`, and the core judges it against the declared shape and the
pinned validator and writes it as the named object **inside the same
compare-and-swap guarded command**. There is no separate object write that
could rebase the caller's version.

The decision itself is never lost. A record that fails its quality is not
written — the previous revision of the object is untouched — the node does
not complete, and the findings say why (`WORKFLOW_OUTPUT_MISSING`, the
validator's own codes). A node that declares an output and whose decision
carries no record keeps waiting: the declared record is part of the node's
completion contract.

The binding the record was made under is persisted with it: the actor who
decided, the ingress source it came through, the node and attempt, the
subject's revision and digest, the input digest and the digest of the
record itself (`outputBinding`).

A human node that declares **no** output keeps its previous behaviour, and
the record says so: `quality.declared` is `false` and `quality.mode` is
`undeclared`. No quality is implied for it.

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

### Automatic node quality

An action node may declare the same two things an agent node declares:

```json
"n06": {"kind": "action", "capability": "work.dispatch",
        "subject": {"object": "proposal"},
        "output": {"object": "order", "evidence_kind": "dispatch_receipt",
                   "validation": {"shape": {"…": "…"},
                                  "validator": "effect", "validator_version": "1"}},
        "checks": [{"id": "N06-1", "method": "PROGRAM",
                    "criterion": "The dispatch receipt names the order it created.",
                    "criterion_version": "1",
                    "validator": "effect", "validator_version": "1"}]}
```

* **Inputs are judged before the effect.** A node's declared input
  validation runs the pinned validator, not only the shape descriptor. A
  failing input blocks the node, and a blocked action node never proposes an
  operation: no external effect is authorized. A subject that declares its
  own validation is a protected input and is judged the same way. Every
  judgment is reported: the node instance carries `input_report` with the
  object, its role, the exact revision and digest that was judged, the
  pinned validator and its version, and the verdict; a finding carries the
  same provenance. The `input_digest` covers exactly the declared
  `inputs`; the subject is pinned separately in `subject`, and a decision
  must cover the subject's exact revision and digest. The two digests mean
  two different things and neither is presented as the other.
* **The receipt is the material.** The engine wraps the adapter it calls and
  keeps the receipt the external system really returned, bounded (8 KiB for
  the transport fields, 64 KiB for the business payload), together with its
  origin: the operation id, the capability, the business key, the external
  id, the document digest and the adapter class. The receipt schema and the
  digest and action linkage stay authoritative: a receipt that does not
  match the operation's document digest, or that names another action, is
  refused (`WORKFLOW_RECEIPT_INVALID`, `WORKFLOW_RECEIPT_ACTION_MISMATCH`).
  A receipt that does not match is quarantined by the runtime itself — the
  operation becomes `outcome_unknown`, never a confirmed effect. An
  operation that was confirmed outside the engine (a host that dispatched it
  itself) is back-filled from the authoritative **lookup** of the same
  business key — never from a second effect.
* **The payload is judged, then adopted.** The business payload the receipt
  carries is validated against the declared shape and the pinned validator,
  and the per-criterion report is persisted with the method, the criterion
  version, the validator id and version, the reviewed input and output
  digests, the reason and the evidence. Only then is the payload written as
  the named object and the node completed.
* **A rejected output is not a false external failure.** The effect stays
  recorded as what it was (`effect.status = "succeeded"`, with its external
  id and operation id), the node fails with `WORKFLOW_OUTPUT_INVALID`, the
  workflow reports `needs_attention`, and the effect is **never produced a
  second time**: routing back into the same node is refused and a second
  attempt fails closed with `WORKFLOW_EFFECT_ALREADY_APPLIED`.

When the output validates and the definition declares an `evidence_kind`,
the engine writes its **own** proof of the external event under the source
`workflow-engine` (never the ingress source of a signed evidence kind) with
the event id `wf:<operationId>`. The proof binds the work, the node, the
attempt, the object revision and digest and the payload.

**Compatibility.** A node that declares neither an `output` nor `checks`
keeps the previous behaviour: the confirmed effect completes the node and no
output object is written. The read model says so explicitly —
`quality.declared` is `false` and `quality.mode` is `undeclared` — so no
quality is implied for a node that never asked for it, and the stored check
report stays empty.

### Review nodes

A node may declare a review: `{"evidence_kind": …, "reviewer": …, "rubric":
{"validator": …, "validator_version": …}}`. The rubric must resolve at its
exact version, or the definition is not publishable.

When the candidate is accepted, the engine writes a durable `review_task`
intent that pins the rubric, the criteria, the candidate revision, the
input digest and the independent producer. The review proof must bind the
exact instance — node, attempt, input digest and output digest — and its
producer must be the declared reviewer and must not be the node's executor.
A same-digest review of an earlier attempt therefore never satisfies the
current one.

### Wait nodes

A wait node matches on a verified proof (`evidence_kind`, optionally scoped
to an object subject), on a completed node, or on a timeout. A proof that
does not cover the object's current revision does not match.

A wait may declare a **binding**:

```json
"match": {"evidence_kind": "dispatch_receipt",
          "subject": {"object": "order"},
          "bind": {"node": "n06"}}
```

* `bind.node` names the node whose output the wait awaits. Without an
  explicit `bind.attempt` the wait accepts the proof of that node's
  **current** attempt; with one it accepts exactly that attempt. A proof of
  an earlier attempt therefore never satisfies a new attempt.
* `subject` pins the proof to the **current revision and digest** of the
  object it covers: a superseded object is not covered.
* The matched binding is persisted on the node instance and readable:
  `waitMatch` carries the work, the node, the attempt, the bound node and
  attempt, the object revision and digest, and the provenance of the event
  (its source and event id).

A wait may also declare an `output` and `checks`, exactly like an action
node. The candidate is the business payload the matched proof carries (or
the evidence record itself when it carries no payload); it is validated
against the declared shape and the pinned validator before the workflow
routes on, and the validated payload becomes the named object.

**Compatibility.** A wait that declares neither a binding nor a subject
keeps the previous rule — any verified proof of the kind in this work
satisfies it — and the record says so plainly: `waitMatch.mode` is
`kind_only` (`bound` for a bound wait, `node` for a node match). No binding
is implied for it.

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
| a declared input fails its validator | the node is `blocked` before the effect; no operation is proposed |
| the receipt does not match the operation | the operation is quarantined by the runtime (`outcome_unknown`); the node keeps waiting and is never confirmed |
| the declared output fails its validator or shape | the node fails with `WORKFLOW_OUTPUT_INVALID`; the effect stays recorded as succeeded, no output object is written and the effect is never repeated |
| predicate unknown | the edge is blocked; the work reports `needs_attention` |
| last node terminal | the workflow is `finished` — a **precondition**, never an automatic close; `request_completion` and its full gate remain the only success path. "Finished" says the routing stopped: the read model also carries `terminalNode` and `terminalOutcome`, so a caller never reads it as a delivery |

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

The exact wire contract, with the request and response fixtures, is
[workflow-api-contract.md](workflow-api-contract.md).

| method | path | purpose |
|---|---|---|
| `GET` | `/v1/workflows` | health: the coordinator model and the workflow count |
| `GET`/`POST` | `/v1/workflows/templates` | list / publish a definition |
| `GET` | `/v1/workflows/templates/{id}/{version}` | the published definition and its digest |
| `POST` | `/v1/workflows/instances` | instantiate: work, contract, plan, binding |
| `GET` | `/v1/workflows/instances/{workId}` | the bounded read model |
| `POST` | `/v1/workflows/instances/{workId}/results` | submit an agent candidate |
| `POST` | `/v1/workflows/instances/{workId}/decisions` | record a human decision (CAS-guarded) |
| `POST` | `/v1/workflows/instances/{workId}/objects` | revise a named object |
| `GET` | `/v1/workflows/instances/{workId}/objects/{name}/revisions/{revision}` | read one exact object revision |
| `GET` | `/v1/workflows/instances/{workId}/intents` | the durable intents |
| `GET` | `/v1/workflows/instances/{workId}/events` | the event history |
| `GET` | `/v1/workflows/instances/{workId}/nodes/{nodeId}/attempts` | the attempt history of one node, with its stored judgments |
| `GET` | `/v1/workflows/commands/{commandId}?workId=&actor=` | the stored receipt of one command, read-only |
| `POST` | `/v1/workflows/intents/{intentId}/ack` | acknowledge an intent |
| `POST` | `/v1/workflows/instances/{workId}/advance` | settle on demand |

The read model is bounded: at most 64 nodes, 32 intents and 16 findings per
node, and it never returns payload bodies. Errors are
`{"error": {"code", "message", "findings"}}` with the engine's code verbatim.

Two properties matter to a client:

* **the bridge never trusts the body about identity.** The approving
  principal is resolved from the published node and the policy's source
  registry, and the decision's `actorId` is checked against it. The body
  says who acted; the protected definition says who was allowed to.
* **every mutation carries a stable `commandId`** and, on an existing work,
  the `expectedVersion` the client observed. The bridge never substitutes
  its own current version for the caller's, and it never invents a command
  id. A decision is admitted by the workflow command `record_decision`, so
  the compare-and-swap, the evidence intake and the decision admission are
  one atomic step under the runtime's own command dedup.
* **the instance creation validates the submitted contract** against the
  registered immutable policy (`WORKFLOW_POLICY_MISMATCH`) and uses the
  submitted plan as given; the trusted platform create snapshot supplies
  the session, the parameters and the participant assignment.
* **progress does not need a client to poll.** Every mutating call settles
  the workflow before it answers, and a background ticker advances and
  recovers the store on its own schedule. The bridge logs the method and the
  path only: a credential in a body never reaches the log, and fields that
  look like credentials are stripped from every response.
* **a receipt can be read back without re-sending anything.**
  `GET /v1/workflows/commands/{commandId}?workId=&actor=` returns the
  stored receipt of one command, scoped to its work and actor. It is
  read-only: it never re-runs the command, so a platform can recover an
  accepted fact after a lost response or a withdrawn authority without
  turning an executed command into a rejected one.

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

`python3 -m work_runtime workflow-demo` runs the scenario on a fresh store:

| node | kind | what it shows |
|---|---|---|
| N01 | agent | material intake, accepted only by the registered validator |
| N02 | agent | analysis against the accepted input |
| N03 | agent | the proposal, frozen as an object revision |
| N04 | human | the safety review; its approval creates N05's task with **no agent turn** |
| N05 | human | the project approval; it dispatches **exactly one** idempotent external action |
| N06 | action | the external dispatch, performed by a worker that **really dies** after the effect; the receipt it returned is validated and becomes the **order** |
| N06W | wait | the dispatch wait: it matches only the proof of the attempt it is bound to |
| N07 | human | the responsible person's report **on the order** |
| N08 | human | the independent review of the same order; its approval queues the **original session**'s agent work |
| N09 | agent | the report, completed only after the independent review evidence arrives |
| N10 | action | the delivery; its receipt is validated the same way |

The external effects are counted in the business system's own store, never
in the process that produced them: after the crash and the restart the count
is one dispatch and one delivery. The order the dispatch receipt produced is
the object N07 and N08 judge, and the wait accepts only the proof of the
attempt that produced it.

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

* No authentication, no tenant isolation, no distributed leases or fencing.
  Principals are trusted local configuration.
* No distributed exactly-once. The bridge offers **stable idempotent
  effects** (a stable operation business key, an adapter-level idempotency
  key and a lookup) and **unknown-effect reconciliation** (an unknown
  outcome is looked up, never repeated). It does not claim exactly-once
  delivery between GAWR and an external system.
* No arbitrary dynamic graph at instance time, no workflow revision command,
  no `migrate`/`revise` shortcut for a running instance: a changed
  definition is a new published version, and a running instance keeps the
  digest it pinned.
* No GUI: the read model is a read model. The read-only GUI wave is a
  separate slice.
* No semantic validation of a model's judgement. A review is durable
  evidence, and a program check never claims to have proved meaning.
* No guarantee that an external system returns a usable business record. A
  receipt that does not match its operation is quarantined by the runtime,
  and a receipt that carries no payload cannot produce a named object: the
  node keeps waiting or fails with the reason it really has.
* The obligation layer of a family is kind-level; the *exact version* of an
  approval is an engine guarantee, not an obligation.
