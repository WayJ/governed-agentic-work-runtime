# Workflow API contract (version 1)

This is the exact wire contract of the mixed-node bridge, written for the
platform client that calls it. It is normative for `v1`: the fields below
are required where marked, and the responses are the ones the bridge
returns today.

The surface is `http://127.0.0.1:<port>/v1/workflows`. It is **separate
from** the product's `/v1/deliveries` route: the bridge is a governance
surface, not a task-delivery shortcut.

## The trusted platform create snapshot

The create request carries a snapshot produced by the platform's own create
path. It is not arbitrary caller input, and it is the only source of the
participant assignment.

```json
{"workId": "W-1",
 "commandId": "create-1",
 "document": {"id": "H-001", "subject": "east parapet"},
 "policy": {"policyId": "workflow-demo", "policyVersion": "demo-1", "goal": "workflow.completed"},
 "plan": {"steps": ["n01"], "openRequirements": ["R01"], "replanWhen": ["a reviewer rejects"]},
 "instance": {
   "workspaceId": "ws-1",
   "taskId": "task-1",
   "ownerUserId": "user-1",
   "sessionId": "session-original-1",
   "parameters": {"subject": "east parapet"},
   "participants": {"n04": "member-123", "n05": "member-456"}
 }}
```

* `templateId` and `templateVersion` name the published definition, and
  the optional `templateDigest` pins it: a definition with another digest
  is `409 WORKFLOW_TEMPLATE_MISMATCH`.
* The submitted `policy` is checked against the **registered** immutable
  policy: a mismatch is `422 WORKFLOW_POLICY_MISMATCH`. The contract that
  is bound is never silently replaced.
* The submitted `plan` is used as given (both `open_requirements` and
  `openRequirements` are accepted) and is shape-validated; when it is
  absent the steps are derived from the pinned template's node ids.
* The `instance` snapshot supplies the session, the instance parameters and
  the participant assignment. `parameters` are validated against the
  template's `parameters_schema`; every `participants` key must be a node
  the pinned definition declares, else `422 WORKFLOW_PARTICIPANT_UNKNOWN`.
* The read model returns the stored snapshot under `workflow`:
  `{"templateId", "templateVersion", "digest", "revision", "parameters", "sessionId", "participants"}`.

## What the platform owns and what GAWR owns

| concern | owner |
|---|---|
| authenticating the human, the executor and the service | the platform |
| mapping a workspace role to the GAWR principal that may act | the platform's operator-published policy (node → role) |
| the published workflow definition and its protected parts | GAWR, published once and pinned by digest |
| the instance, its node states, its attempts and its evidence | GAWR |
| the external effect and its true result | the external business system, queried through the adapter |
| the business record the effect produced | the external business system; GAWR adopts it as a named object only after the declared validator accepts it |
| the platform's own task, approval and artifact records | the platform |

**The participant and authority mapping.** A published definition names, per
node, the GAWR-side principal that may act: `executor` for an agent node,
`authority` for a human node, `capability` for an action node. The platform
maps a node to the workspace role that may hold that principal
(`node → roleId`) in its own operator-published policy, checks the caller's
current membership and enabled roles, and then asserts the **actor id** of
the decision. GAWR never learns a workspace role id: it enforces that the
asserted actor is the principal the protected definition assigned to that
node, for that node and that attempt. A caller cannot claim a role in the
request body and be believed: the body says who acted, and the protected
definition says who was allowed to.

**Source is not actor.** The evidence *source* is the platform ingress that
carries a decision; it says nothing about who decided. The *actor* is the
asserted principal, and the separation rules (an executor may never
approve; two roles may not be held by the same person) are checked against
the actor.

**The participant port.** The core knows a *principal* per node and asks a
trusted, injected resolver who currently holds the assignment:

```python
class ParticipantResolver:
    def resolve(self, work, node_id, member_id) -> Optional[str]:
        """The GAWR principal of the member, or None when the member is not
        currently assigned, not enabled, or out of scope. An enterprise
        adapter resolves only from the trusted snapshot plus the platform's
        current check."""
```

A published definition declares the authority in one of two closed forms:

```json
"authority": "reviewer-a"          // a static GAWR principal
"authority": {"assigned": true}    // whoever the platform assigns now
```

With no resolver injected, `{"assigned": true}` **fails closed**: no
decision is ever admitted for that node and the node keeps waiting. The
assignment is re-resolved at settlement, so a withdrawn assignment stops a
decision that was already written.

**No exactly-once across systems.** The bridge offers *stable idempotent
effects* (a stable operation business key, an adapter-level idempotency key
and a lookup) and *unknown-effect reconciliation* (an unknown outcome is
looked up, never repeated). It does not claim exactly-once delivery
between GAWR and an external system.

**The receipt is the adapter's, not GAWR's.** Where the engine calls the
adapter it keeps the receipt that came back — bounded, with the operation,
capability, business key, external id and document digest it belongs to —
and the business payload that came with it. GAWR never invents the content
of an external record: the payload is what the external system returned,
and it is adopted as a named object only after the declared validator
accepts it. The digest and action linkage of the receipt stay
authoritative; a receipt that does not match the operation is refused and
quarantined by the runtime.

## Mutation rules (every one of them)

* Every mutation carries a **stable `commandId`**: the client's own
  idempotency key. A retry with the same id returns the original receipt.
  There is no server-side random id.
* Every mutation on an existing work carries **`expectedVersion`**: the
  `stateVersion` the client observed. The bridge never substitutes its own
  current version for the caller's; a stale version is `409
  STATE_VERSION_CONFLICT`.
* An agent result carries **`inputDigest`**: the digest of the inputs the
  node currently pins (`GET` the instance, read `nodes[].inputDigest`). A
  candidate produced from a superseded input is refused.
* A human decision carries **`node` + `attempt`**: the decision is bound to
  one attempt of one node. An approval of an earlier attempt never
  satisfies a later one, even when the content digest is identical.
* A human decision carries **`actorId`** and **`items`**: the authenticated
  actor and one verdict per declared criterion.

## Routes

### `POST /v1/workflows/templates`

```json
{"spec": {"id": "inspection-review-delivery", "version": "test-1", "policy_family": "workflow-demo", "entry": "n01", "terminal": ["n10"], "required_checks": ["N01-1"], "nodes": {"n04": {"kind": "human", "evidence_kind": "safety_review", "authority": "reviewer-a", "subject": {"object": "proposal"}, "checks": [{"id": "N04-2", "criterion": "The proposal covers every applicable requirement.", "validator": "safety-review", "validator_version": "1"}]}}, "edges": [{"from": "n03", "to": "n04"}]}}
```

`201 {"templateId": "inspection-review-delivery", "templateVersion": "test-1", "digest": "…"}`
`422 {"error": {"code": "WORKFLOW_SPEC_INVALID", "findings": [{"code", "path", "message"}]}}`
`422 {"error": {"code": "WORKFLOW_VALIDATOR_UNKNOWN"}}` — an unknown validator id or version
`409 {"error": {"code": "WORKFLOW_TEMPLATE_IMMUTABLE"}}` — a published definition never changes

### `GET /v1/workflows/templates/{templateId}/{templateVersion}`

`200 {"templateId", "templateVersion", "digest", "spec", "publishedBy", "publishedAt"}` — the whole
protected definition, including every criterion's text and its validator binding.

### `GET /v1/workflows/commands/{commandId}?workId={workId}&actor={actor}`

`200 {"commandId", "workId", "actor", "receipt": {…}}` — the stored receipt
of one command, or `404 COMMAND_RECEIPT_UNKNOWN`.

It is a **read-only** lookup: it never re-suns the command and never
decides anything. The `workId` and `actor` scope it, so two tasks that
share a command id stay apart. It answers "was this command accepted?"
after a lost response or a withdrawn authority, so a platform can read
back an accepted fact without re-sending an approval and without turning
an executed command into a rejected one.

The multi-step creation derives its command ids from the top-level one, so
a retry finds the same receipts: `<commandId>:create`, `<commandId>:contract`,
`<commandId>:plan` and `<commandId>:bind`. The **binding** receipt is
`<commandId>:bind`; the create response returns it as `bindingCommandId`
and lists the rest under `commandIds`.

### `POST /v1/workflows/instances`

See [the trusted create snapshot](#the-trusted-platform-create-snapshot).
`201` the instance view. The document, contract and plan are constructed by
the host policy, not by arbitrary caller input. `parameters` are validated
against the definition's `parameters_schema`; an arbitrary dynamic graph is
refused.

The creation is four commands — `<commandId>:create`, `:contract`, `:plan`
and `:bind` — and it is **resumable**:

* **Send the same body again** after a crash or a lost response. The
  already accepted stages are not issued a second time, the creation is
  completed where it stopped, and the answer is the same `201` with the
  same instance view. A replay adds no revision, no intent, no event and
  no external effect.
* **A changed body conflicts.** A `commandId` belongs to one request. A
  different document, template, instance, plan, session, work or actor
  under the same `commandId` is `409 COMMAND_ID_REUSED`; the first
  request's stages are never silently reused for a second one.
* **A refused request creates nothing.** The plan, the pinned
  `templateDigest` and the submitted `policy` are checked before the first
  command, so a `400` or a `422` leaves no half-created work behind.
* **A concurrent duplicate is serialized.** Two requests with the same
  `commandId` take turns: the second one waits for the first to finish and
  then replays the finished creation, so both answer `201` with the same
  instance view and the durable preparation keeps every stage.

The **binding** receipt is `<commandId>:bind`; the response returns it as
`bindingCommandId` and lists the four ids under `commandIds`. A platform
that lost the response reads it back with
`GET /v1/workflows/commands/{commandId}?workId=&actor=`: the receipt is
present when the creation was bound and absent when it was not.

### `GET /v1/workflows/instances/{workId}`

```json
{"workId": "W-1", "status": "active", "workflowStatus": "active", "stateVersion": 7, "currentNode": "n04",
 "terminalNode": null, "terminalOutcome": null,
 "workflow": {"templateId": "inspection-review-delivery", "templateVersion": "test-1", "digest": "…", "revision": 1, "parameters": {}},
 "nodes": [{"node": "n04", "kind": "human", "state": "running", "attempt": 1, "outcome": null,
            "inputs": [{"name": "proposal", "revision": 1, "digest": "…"}],
            "subject": {"name": "proposal", "revision": 1, "digest": "…"},
            "inputDigest": "…", "actor": null,
            "outputs": [], "findings": [], "blockers": [], "checkResults": [],
            "quality": null, "effect": null, "waitMatch": null, "receipt": null,
            "intentId": "wf:W-1:n04:1:human_task", "checks": [{"id": "N04-2", "criterion": "…", "validator": "safety-review", "validator_version": "1"}]}],
 "checks": [{"checkId": "N04-2", "node": "n04", "criterion": "…", "validator": "safety-review", "validatorVersion": "1"}],
 "allowedActions": [{"action": "submit_node_result", "node": "n04", "attempt": 1, "required": ["result"]}],
 "intents": [{"id": "wf:W-1:n04:1:human_task", "kind": "human_task", "node": "n04", "attempt": 1, "status": "pending", "sessionId": "session-original-1"}]}
```

Bounded: at most 64 nodes, 32 intents, 16 findings and 16 check results per
node. The view never carries a payload body.

### The quality record of a node

An automatic or wait node carries four additive fields. They say what was
judged, never that something was checked when it was not.

```json
{"node": "n06", "kind": "action", "state": "completed", "attempt": 1,
 "quality": {"declared": true, "mode": "validated", "validator": {"id": "effect", "version": "1"}},
 "effect": {"status": "succeeded", "externalId": "EXT-…", "operationId": "…",
            "capability": "work.dispatch", "documentDigest": "…"},
 "waitMatch": null,
 "receipt": {"externalId": "EXT-…", "status": "accepted", "digest": "…",
             "action": "work.dispatch", "operationId": "…",
             "capability": "work.dispatch", "adapter": "DemoBusinessSystem"}}
```

* `quality.declared` is `false` and `quality.mode` is `undeclared` for a
  node whose definition declares neither an output nor checks: such a node
  keeps its previous behaviour and **no quality is implied for it**.
  `mode` is `validated` when the declared output passed and `rejected` when
  it did not.
* `effect` is the external fact: `status` is `succeeded` only when the
  external system really accepted the effect. A node whose output was
  rejected keeps `effect.status = "succeeded"` — the effect happened — and
  fails with `WORKFLOW_OUTPUT_INVALID`; the effect is never produced again.
* `receipt` carries the transport facts of the receipt the external system
  returned and the origin that links it to its operation. The business
  payload is **not** in the view: it is read as the named object the node
  wrote.
* `waitMatch` is the binding a wait matched on: `mode` (`bound`, `node` or
  `kind_only`), the evidence kind, the source and event id of the proof,
  the work, the node and attempt, the bound node and attempt, and the
  object revision and digest. `kind_only` says plainly that the wait
  matched any verified proof of its kind.
* `outputBinding` is the binding a human node's named record was made
  under: the actor who decided, the ingress source it came through, the
  node and attempt, the subject's revision and digest, the input digest
  and the digest of the record itself.

The criterion report is ordered by the definition's declared criteria and
keeps the judges apart: a `HUMAN` entry names the person who decided
(`decidedBy`), a `PROGRAM` entry names the validator that judged it
(`validator`, `validatorVersion`) and has no `decidedBy`.

The same `quality`, `effect` and `waitMatch` records are returned per
attempt by `GET /v1/workflows/instances/{workId}/nodes/{nodeId}/attempts`.

### `POST /v1/workflows/instances/{workId}/results`

```json
{"node": "n01", "attempt": 1, "object": "intake", "result": {"records": [{"id": "REC-1", "source": "inspection-log"}], "standard": "STD-2026-01"}, "actor": "agent-executor", "inputDigest": "…", "commandId": "submit-1", "expectedVersion": 7}
```

`200` the instance view with `result: {node, attempt, output, state, resultStateVersion}`.
`400 SUBMISSION_INVALID` — no `inputDigest`; `400 COMMAND_ID_REQUIRED`;
`400 EXPECTED_VERSION_REQUIRED`; `409 STATE_VERSION_CONFLICT`;
`409 WORKFLOW_ATTEMPT_STALE`; `422 WORKFLOW_INPUT_STALE`;
`422 WORKFLOW_RESULT_INVALID` with the bounded findings — nothing is stored
and the node does not complete.

### `POST /v1/workflows/instances/{workId}/decisions`

The body may carry an optional `result`: the named record the human's
submission produced (the signed external approval-record reference, the
feedback, the verification). When the node declares an `output`, the core
judges the record against the declared shape and the pinned validator and
writes it as the named object **in this same command** — the caller's
`expectedVersion` covers the record as well as the decision. A record that
fails its quality is not written (the previous revision of the object is
untouched), the decision itself is still admitted, and the node does not
complete.


```json
{"node": "n04", "attempt": 1, "decision": "approved", "digest": "…", "revision": 1,
 "actorId": "reviewer-a",
 "items": [{"check": "N04-2", "verdict": "passed", "reason": "every applicable requirement is covered", "evidence": ["proposal#revision-1"]}],
 "commandId": "decision-1", "eventId": "platform-event-1"}
```

`decision` is `approved`, `rejected` or `request_material`. A request for
more material keeps the node waiting: it is neither an approval nor a
rejection and it opens no rework attempt.

The write is the workflow command `record_decision`: the runtime's own
compare-and-swap on `state_version` runs in the same transaction as the
evidence intake, and the command is deduplicated under (ingress source,
`commandId`). The command's actor is the **ingress source** — the platform
channel configured for the node's evidence kind — and the actual decider
travels in `actorId`.

A human node may declare, in its published definition, which decisions
need its named record: `output.on_decisions: ["approved"]`. The default is
that **every** decision needs it. A decision outside the list is admitted
and settles the node without a record — a rejection now reaches its
`on_reject` branch — while an approval always needs the record, whatever
the list says. A record supplied for an exempt decision is refused:
`409 WORKFLOW_OUTPUT_NOT_REQUIRED`, nothing is written, and the caller
re-sends the decision without the record. The declaration is protected
material (published, digest-pinned) and never caller data.

`200` the instance view with `decision: {node, attempt, outcome, actorId, resultStateVersion}`.
`400 ACTOR_ID_REQUIRED`; `400 DECISION_INVALID` — no `items`;
`400 COMMAND_ID_REQUIRED`; `400 EXPECTED_VERSION_REQUIRED`;
`403 WORKFLOW_AUTHORITY_MISMATCH` — the actor is not the resolved assignment;
`409 STATE_VERSION_CONFLICT` — the caller's version is stale;
`409 WORKFLOW_ATTEMPT_STALE`; `409 WORKFLOW_DECISION_STALE` — the digest or
revision is not the current subject; `422 WORKFLOW_CHECK_REPORT_INVALID` —
the criterion report is malformed.

### `POST /v1/workflows/instances/{workId}/objects`

```json
{"name": "intake", "object": {"records": []}, "actor": "coordinator", "commandId": "object-1", "expectedVersion": 9}
```

`200` the instance view with `object: {name, object, supersededNodes, resultStateVersion}`.

### `POST /v1/workflows/instances/{workId}/finalize`

The acceptance of a successful workflow. It is issued by the **trusted
runner** the bridge was configured with; the body may name that runner, but
it may never name anybody else.

```json
{"commandId": "final-1", "expectedVersion": 42, "actor": "workflow-runner"}
```

* `commandId` is the caller's own idempotency key: a retry with the same id
  and the same `expectedVersion` replays the identical receipt, across a
  restart.
* `expectedVersion` is the `stateVersion` the caller observed. A stale
  version is `409 STATE_VERSION_CONFLICT`, and nothing is frozen.
* `actor` is optional; when it is present it must be the configured runner
  (`403 WORKFLOW_RUNNER_MISMATCH`). When no runner is configured the route
  answers `422 WORKFLOW_RUNNER_UNCONFIGURED`.

`200` the instance view with `finalization` — the snapshot the acceptance
froze:

```json
{"workId": "W-1", "status": "closed", "workflowStatus": "finished",
 "stateVersion": 43, "currentNode": null, "terminalNode": "n02",
 "terminalOutcome": "completed",
 "finalization": {"finalizationId": "…", "workId": "W-1",
                  "finalizedBy": "workflow-runner", "finalizedAt": 1760000000,
                  "stateVersion": 43, "workflowStatus": "finished",
                  "terminal": {"node": "n02", "attempt": 1,
                               "state": "completed",
                               "outcome": "completed", "reason": null},
                  "template": {"id": "…", "version": "…", "digest": "…",
                               "revision": 1},
                  "contract": {"policyId": "workflow-demo",
                               "policyVersion": "demo-1",
                               "goal": "workflow.completed", "revision": 1},
                  "plan": {"revision": 1, "steps": [], "openRequirements": [],
                           "replanWhen": []},
                  "document": {"revision": 1, "digest": "…"},
                  "objects": [{"name": "order", "revision": 1, "digest": "…"}],
                  "nodes": [{"node": "n02", "attempt": 1, "state": "completed",
                             "outcome": "completed", "quality": {"…": "…"},
                             "effect": {"…": "…"},
                             "checks": [{"checkId": "N02-1",
                                         "verdict": "passed",
                                         "method": "PROGRAM"}]}],
                  "operations": [{"id": "…", "capability": "work.dispatch",
                                  "businessKey": "…",
                                  "status": "confirmed_succeeded",
                                  "dispatchState": "finished",
                                  "externalId": "EXT-…"}],
                  "requirements": [{"id": "R01:H-001", "ruleId": "R01",
                                    "applicability": "applicable",
                                    "fulfillment": "satisfied"}],
                  "evidence": ["…"], "digest": "…"}}
```

The refusal codes are the ones the acceptance gate uses:
`409 WORKFLOW_NOT_FINISHED` (the routing did not stop), `409
WORKFLOW_TERMINAL_NOT_COMPLETED` (the terminal failed, expired, was
cancelled or its output was invalid), `409 WORKFLOW_TERMINAL_NOT_DECLARED`,
`409 WORKFLOW_EFFECT_UNRESOLVED` (an effect is prepared, dispatched or
unknown), `409 WORKFLOW_REQUIREMENT_UNSATISFIED` (an obligation is
outstanding), `409 WORKFLOW_NODE_UNSETTLED`, `409
WORKFLOW_NODE_NOT_COMPLETED`, `409 WORKFLOW_QUALITY_UNSETTLED`, `409
WORKFLOW_CHECK_UNSATISFIED`, `409 WORKFLOW_INTENT_UNSETTLED`, `409
WORKFLOW_CANCELLED`, `403 WORKFLOW_RUNNER_MISMATCH`, `422
WORKFLOW_RUNNER_UNCONFIGURED`.

### `GET /v1/workflows/instances/{workId}/completion`

The **immutable** read of an accepted workflow.

```json
{"workId": "W-1", "finalization": {"…": "…"},
 "finalizationCanonical": "{\"finalizationId\":\"…\",…}"}
```

`404 WORKFLOW_NOT_FINALIZED` when the workflow was not accepted. The
snapshot is written once by the acceptance and never rewritten: every reader
sees the same bytes, and no route changes them.

**`finalizationCanonical`** is the exact text a reader hashes. It is the
canonical JSON of the finalization **without its `digest` entry**, so:

* `SHA-256(finalizationCanonical as UTF-8)` is exactly the `digest` the
  acceptance recorded;
* parsing the text yields exactly the finalization without its `digest`
  entry — a reader that compares the parsed value with the finalization it
  received never has to reimplement this canonical form;
* the text is UTF-8: a non-ASCII character is emitted as itself, never as
  an escape sequence, and the bytes are the bytes that are hashed.

The text is emitted only when the proof needs no redaction and when the
stored digest still matches the stored content. Otherwise the read refuses
and emits **neither** the text nor a hash of a redacted proof:
`409 WORKFLOW_COMPLETION_PROOF_UNAVAILABLE` (the stored proof carries
something that looks like a credential) and `409
WORKFLOW_COMPLETION_PROOF_UNVERIFIED` (the stored proof does not match its
own digest).

The native command receipt is unchanged: the acceptance's receipt carries
the snapshot and no canonical text.

### `POST /v1/workflows/instances/{workId}/cancel`

Request the cancellation of the work. The command is the runtime's own
`request_cancel`: it runs in the work's transaction, cancels the
workflow's active nodes and its durable intents, cancels every
never-dispatched prepared operation and stores an immutable receipt under
the caller's `commandId`. The `actor` must be the work's owner or a
`work.intervene` administrator — the core decides that, and a request
that reaches this route grants nothing by itself.

```json
{"actor": "coordinator", "reason": "duplicates found",
 "commandId": "cancel-1", "expectedVersion": 7}
```

* `reason` is required and nonempty: a cancellation says why.
* `expectedVersion` is the `stateVersion` the caller observed; a stale
  version is `409 STATE_VERSION_CONFLICT` and nothing is cancelled.
* A retry with the same `commandId` **and the same body** replays the
  original receipt; a different body under the same id is
  `409 COMMAND_ID_REUSED`; a second request under a **new** id while the
  intent is active is `409 CANCELLATION_ALREADY_REQUESTED`.

`200` the instance view with `cancellation: {requested: true, requestedBy,
reason, resultStateVersion}`. An effect that was already dispatched or of
unknown outcome is **not** rolled back: it stays on the work and is
resolved by the ordinary lookup and recovery.

### `POST /v1/workflows/instances/{workId}/material/wait`

Park the workflow's **current agent node** for business material. The
command is the runtime's own `request_material_wait`: it is admitted
against the version the caller observed, under the caller's own
`commandId`, in one transaction.

```json
{"actor": "coordinator", "requestVersion": 1, "node": "n02", "attempt": 1,
 "inputDigest": "…", "reason": "the referenced record is missing a page",
 "commandId": "wait-1", "expectedVersion": 7}
```

* `node` is the **current** node and `attempt` its current attempt; a
  node that is not current is `409 WORKFLOW_NODE_NOT_CURRENT`, a stale
  attempt is `409 WORKFLOW_ATTEMPT_STALE` and an `inputDigest` the node
  does not hold is `422 WORKFLOW_INPUT_STALE`.
* `reason` is required: the wait says why it waits.
* `requestVersion` is `1`; any other value is
  `400 MATERIAL_WAIT_VERSION_UNSUPPORTED`.
* The `actor` must be the work's owner with `work.manage`; anybody else
  is `403 AUTHORITY_DENIED` and nothing changes.

`200` the instance view with `materialWait: {node, attempt, wait,
resultStateVersion}`. The node's own `materialWait` in the view names the
reason, the requester, the dependencies the wait accepted and the
adoptions that followed. The work reports `workflowStatus: "waiting"`.

While the node waits: a result submitted for it is `409
WORKFLOW_NODE_WAITING` and nothing is stored; the node's durable intent
is withdrawn; the wait survives a restart; the deadline is suspended.

### `POST /v1/workflows/instances/{workId}/material/adopt`

Adopt externally provided material under an active wait. The command is
the runtime's own `adopt_material`: the adopted material becomes a **new
immutable revision** of the named object, the historical revisions and
the decisions made on them stay on the record, and nothing is re-run.

```json
{"actor": "coordinator", "requestVersion": 1, "node": "n02", "attempt": 1,
 "name": "intake", "object": {"records": [], "standard": "STD-1"},
 "commandId": "adopt-1", "expectedVersion": 8}
```

* `name` must be one of the dependencies the wait accepted; anything else
  is `422 WORKFLOW_MATERIAL_NOT_DEPENDENCY` — an adoption of anything
  else would be a silent write.
* `object` is at most 64 KiB of canonical JSON; a larger body is `422
  WORKFLOW_MATERIAL_TOO_LARGE`. A wait carries at most sixteen
  adoptions (`422 WORKFLOW_ADOPTION_LIMIT_EXCEEDED`).
* Adopting without a wait is `409 WORKFLOW_NOT_WAITING`.
* **An adoption may not bless a completed upstream's accepted output**: a
  node that completed accepted one exact revision of its output, and a
  new revision of that object would be material no completed node ever
  accepted. Such an adoption is `422
  INPUT_DEPENDENCIES_REQUIRE_REVALIDATION` with the upstream node, its
  attempt and both revisions as the findings.

`200` the instance view with `materialAdoption: {node, attempt, adoption,
wait, resultStateVersion}`. The node keeps waiting: the adoption supplies
the material, the resume starts the work.

### `POST /v1/workflows/instances/{workId}/material/resume`

Resume the waiting node behind the dependency gate. The command is the
runtime's own `resume_material_wait`.

```json
{"actor": "coordinator", "requestVersion": 1, "node": "n02", "attempt": 1,
 "commandId": "resume-1", "expectedVersion": 9}
```

* The **same attempt** continues: no rework attempt is opened and no
  quality allowance is spent.
* The gate: every dependency the wait accepted must still be the
  object's current revision and digest, and the **completed upstream
  nodes** must still cover the material. The guard inspects the completed
  nodes that *pinned* a changed object, not only the one that produced
  it: a node that judged material that moved on, and everything it
  produced, is stale. Otherwise the resume is `422
  INPUT_DEPENDENCIES_REQUIRE_REVALIDATION` with the exact drift as the
  findings, and **the wait is retained** — the node keeps waiting.
* Material that no longer passes its declared validator **blocks** the
  node (`200` with `materialResume.state: "blocked"` and the findings on
  the node) instead of running on it.

`200` the instance view with `materialResume: {node, attempt, state,
inputDigest, wait, resultStateVersion}`. Two things move on a resume even
when the material did not change: the **input ticket** (a resumed node
carries its input generation in the digest, so a ticket issued before the
wait never satisfies the node after it — a node that never waited keeps
exactly the ticket it was given) and the **intent identity** (the node
asks again under `wf:<work>:<node>:<attempt>:<kind>:<generation>`, so an
old acknowledgement can never swallow the resumed prompt).

**The platform envelope.** The three routes accept the extra fields the
trusted platform wire already carries: the principal may be named
`actor` or `actorId` (a body that names **two different** ones is
`400 ACTOR_CONFLICT`, and a body that names neither is
`400 ACTOR_REQUIRED`), and a `workId` in the body is accepted when it
names the work of the path (a body that names another work is
`400 WORK_MISMATCH` — the path is authoritative, and a request is never
applied to a work it does not name).

### `POST /v1/workflows/instances/{workId}/material/replace`

Replace the archived source material and revalidate the consumers that
judged it, in the same workflow and session. The command is the runtime's
own `replace_material`: a compare-and-swap against the version the
caller observed, under the caller's own `commandId`, in one transaction.

```json
{"actor": "platform", "requestVersion": 1, "node": "s00",
 "sourceReference": {"kind": "business-material-snapshot",
                     "referenceId": "REF-2", "workflowId": "W-1",
                     "sourceNode": "s00", "documentDigest": "…",
                     "snapshotDigest": "…", "scope": "records"},
 "reason": "the archive was refreshed",
 "waitingNode": "n03", "waitingTicket": "…",
 "commandId": "replace-1", "expectedVersion": 17}
```

* `node` is the **source node** — the node whose completed attempt
  produced the material. The core derives the object from that node, so
  a caller cannot name an arbitrary object
  (`409 WORKFLOW_SOURCE_NOT_PRODUCER`, `409 WORKFLOW_SOURCE_NOT_COMPLETED`).
* `sourceReference` is the **frozen reference** the platform acquired: a
  manifest, never the material. The core checks that it names its kind,
  the work and the source it belongs to, and refuses a raw location, a
  credential or the raw material (`422
  WORKFLOW_SOURCE_REFERENCE_INVALID`). It is at most 4 KiB (`422
  WORKFLOW_SOURCE_REFERENCE_TOO_LARGE`). The core wraps it in the same
  envelope the source output carries and writes it as a new revision;
  the historical revision is retained.
* The reference stays opaque — the core never resolves it — but the
  **published validation** of the source output judges it before anything
  is written: a manifest that does not satisfy the declared shape or the
  pinned validator is refused (`422 WORKFLOW_SOURCE_REFERENCE_REJECTED`),
  and no revision, no invalidation and no material generation is spent on
  it.
* `waitingNode` and `waitingTicket` are the node that waits and the
  ticket the manager observed. When given, the node must be the
  **current** node and it must really wait for material (`409
  WORKFLOW_WAITING_NODE_NOT_CURRENT`), and the ticket must still be its
  current one (`409 WORKFLOW_WAITING_TICKET_STALE`). The pair may be
  left out — the manager may replace the material of a workflow that
  waits for nothing — but a platform that replaces material on a waiting
  work always sends both.
* `requestVersion` is `1`; any other value is `400
  MATERIAL_WAIT_VERSION_UNSUPPORTED`.
* The `actor` must be the work's owner with `work.manage`; anybody else
  is `403 AUTHORITY_DENIED` and nothing changes. The trusted platform
  wire may name it `actor` or `actorId`; a body that names **two
  different** ones is `400 ACTOR_CONFLICT`, and a body that names
  neither is `400 ACTOR_REQUIRED`. A `workId` in the body is accepted
  when it names the work of the path (`400 WORK_MISMATCH` otherwise).

`200` the instance view with `materialReplacement: {node, attestation,
affected, generation, resultStateVersion}` and the plan in
`materialRevalidation: {state, generation, attestation, affected, queue}`.

**The source read is never re-run**: the source node keeps its attempt,
its effect, its receipts and its accepted revision. The attestation says
so explicitly — `claim: "… the previous acceptance does not cover this
revision …"`.

**The revalidation is bounded.** The core allowance is one material
replacement generation per workflow; a definition may only tighten it.
The affected consumers are revalidated in dependency order, each on one
**material attempt**, whose attempt number is the next one and whose
ticket carries the node's input generation. A material attempt that
fails on quality opens no further attempt.

**Nothing settles an invalidated attempt.** While the revalidation is
pending, a candidate for an invalidated attempt is refused (`409
WORKFLOW_NODE_INVALIDATED`), a candidate for a node the workflow is not
working on is refused (`409 WORKFLOW_NODE_NOT_CURRENT`), and a decision
for an invalidated attempt is refused (`409 WORKFLOW_NODE_INVALIDATED`).
The old attempt keeps its history; nothing of it is stored.

Refusals: `409 WORKFLOW_REVALIDATION_EFFECT_PRESENT` (the affected
branch carries a business effect or a human judgement),
`409 WORKFLOW_REVALIDATION_BUDGET_EXHAUSTED`,
`409 WORKFLOW_REVALIDATION_NO_CONSUMERS`, `409
WORKFLOW_WAITING_TICKET_STALE`, `409 WORKFLOW_WAITING_NODE_NOT_CURRENT`,
`409 WORKFLOW_NODE_INVALIDATED`, `409 WORKFLOW_NODE_NOT_CURRENT`,
`409 WORKFLOW_SOURCE_NOT_PRODUCER`, `409 WORKFLOW_SOURCE_NOT_COMPLETED`,
`409 CANCELLATION_ACTIVE`, `409 WORKFLOW_FINALIZED`, `409
WORKFLOW_REVALIDATION_PENDING` (the acceptance), `422
WORKFLOW_SOURCE_REFERENCE_INVALID`, `422
WORKFLOW_SOURCE_REFERENCE_REJECTED`, `422
WORKFLOW_SOURCE_REFERENCE_TOO_LARGE`.

### `POST /v1/workflows/instances/{workId}/rework`

Authorize the responsible owner's **one** controlled candidate rework
after a terminal agent quality failure. The command is the runtime's own
`authorize_rework`: same transaction, same compare-and-swap, same
command receipts and the same replay rules as every other mutation.
There is no `requestVersion` and no caller-supplied budget, force or
rule override — the cap is a fixed core bound of one per workflow.

```json
{"actor": "coordinator", "node": "n01", "attempt": 4,
 "inputDigest": "…", "reason": "the owner authorizes one controlled rework",
 "commandId": "rework-1", "expectedVersion": 42}
```

The envelope is **exact**: the accepted fields are `actor` (or
`actorId`), `workId`, `commandId`, `expectedVersion`, `node`, `attempt`,
`inputDigest` and `reason` — nothing else. There is no `requestVersion`
on this route, and any unknown field — a caller `budget`, `maxAttempts`,
`forcePass`, a rule override, or a stray `requestVersion` — is a `400
REWORK_INVALID` naming the refused fields, **before any command is
issued and before anything is written**. A whitespace-only `reason` is
`400 REWORK_INVALID` the same way: the owner's own words are required.

* `node`, `attempt` and `inputDigest` name exactly the terminally
  failed agent attempt — the values the `candidateRework` projection of
  the instance view already publishes. A wrong attempt is `409
  WORKFLOW_ATTEMPT_STALE`, a digest the failed attempt does not hold is
  `422 WORKFLOW_INPUT_STALE`, another node is `409
  WORKFLOW_REWORK_INELIGIBLE` and an unknown node is `404
  WORKFLOW_NODE_UNKNOWN`.
* `reason` is required: the owner's own words, bounded.
* The `actor` must be the work's owner with `work.manage` — the agent,
  a poller and a review may not authorize their own rework (`403
  AUTHORITY_DENIED`).

`200` the instance view with `rework: {node, attempt, state,
inputDigest, grant{authorizedBy, authorizedAt, reason, node,
fromAttempt, toAttempt, sessionId, terminal}, resultStateVersion}` —
the new attempt's ticket, not the failed one. The view's
`candidateRework` now reports `used: 1, eligible: false`, and exactly
one new `agent_task` intent is pending under the workflow's original
bound `sessionId`.

The rework changes no standard: the old failure, its report and the
terminal record stay byte for byte; the new candidate must pass the
original validation and review honestly; nothing is reset (quality
allowance, attempts, material generation, revisions, revalidation
queue); a reworked-attempt failure is terminal. An exact duplicate
replays the stored receipt, a reused key with another body is `409
COMMAND_ID_REUSED`, a second authorization under any new key is `409
WORKFLOW_REWORK_ALREADY_AUTHORIZED`, and a second approval on the same
observed version is `409 STATE_VERSION_CONFLICT`. A cancelling work is
`409 CANCELLATION_ACTIVE`; a waiting work, a non-agent terminal, an
expiry, an unknown result and a success are `409
WORKFLOW_REWORK_INELIGIBLE`; a business effect or a settled human
judgement behind the failed node is `409 WORKFLOW_REWORK_EFFECT_PRESENT`.
A frozen work is refused before any of this (`409 WORKFLOW_FINALIZED` at
the bridge; the runtime's own closed-work boundary answers a direct
command).

### `GET /v1/workflows/instances/{workId}/cancellation`

The safe cancellation state of one work — no payload body, no credential.

```json
{"workId": "W-1", "state": "requested", "status": "needs_attention",
 "outcome": null, "stateVersion": 8,
 "requestedBy": "coordinator", "reason": "duplicates found",
 "unresolvedOperations": ["<operation id>"],
 "requiredAcknowledgements": ["<operation id>"],
 "operations": [{"operationId": "<operation id>", "externalId": "EXT-…",
                 "status": "confirmed_succeeded",
                 "dispatchState": "finished"}]}
```

* `state` is `none`, `requested` (an intent is active) or `cancelled`
  (the work is closed with the outcome `cancelled`).
* `unresolvedOperations` are the operations that are neither confirmed
  nor cancelled: they block the closure.
* `requiredAcknowledgements` are **exactly** the successful operation ids
  the acknowledgement of `finalize` must name (an empty list is correct
  only when there were no succeeded effects).
* `operations` names every operation of the work with its status and
  dispatch state, so a reader can show what really happened.

### `POST /v1/workflows/instances/{workId}/cancel/finalize`

Close a cancelled work. The command is the runtime's own
`finalize_cancel`: it refuses while any operation is unresolved
(`409 OUTCOME_UNRESOLVED`) and requires the acknowledgement to equal
**exactly** the set of `confirmed_succeeded` operation ids
(`409 CANCEL_ACKNOWLEDGEMENT_MISMATCH`, with the required ids as the
error's findings). An accepted closure closes the work as `cancelled`
(never `succeeded`), keeps every operation's disposition and the
acknowledged external ids, and is **not** a success completion proof.

```json
{"actor": "coordinator", "acknowledgedOperations": ["<operation id>"],
 "commandId": "cancel-final-1", "expectedVersion": 9}
```

`200` the instance view with `cancellation: {finalized: true,
requestedBy, acknowledgedOperations, resultStateVersion}`. A retry with
the same `commandId` and the same body replays the original receipt; a
new command key after the closure is `409 WORK_NOT_ACTIONABLE`.
`409 CANCELLATION_NOT_REQUESTED` when no intent is active.

#### Cancellation against an in-flight creation

A platform may hold an immutable work id before the four-stage creation
confirmed. The rules that keep that safe:

* **The routes never create anything.** Cancelling an unknown work answers
  `404 WORK_UNKNOWN` and stores nothing: no work, no receipt, no effect.
* **A work may be cancelled between its stages.** A work that exists but
  whose workflow is not bound yet (the creation stopped after `create` or
  `contract`) is cancelled exactly like any other work: the command is
  accepted and the answer carries the cancellation summary with
  `"instanceView": "unavailable"` — the instance view needs a bound
  workflow — and never reports an accepted cancellation back as a missing
  work.
* **The receipt is the truth, not the view.** A platform that lost an
  answer reads the immutable command receipt
  (`GET /v1/workflows/commands/{commandId}?workId=&actor=`) first; an
  accepted receipt is the fact regardless of any view.
* **A `404` is a missing work, never a fact about effects.** A store that
  cannot answer fails unavailable (`500`), not missing: a transient error
  is never readable as "there is nothing here", and an unknown-work `404`
  says only that this store holds no such work.
* **An already-completed work stays completed.** Cancelling or finalizing
  a closed work is refused (`WORK_NOT_ACTIONABLE`); a factual prior
  completion never reopens a task.
* **An in-flight effect is never rolled back.** A dispatched or
  unknown-outcome operation stays on the work and is resolved by the
  ordinary lookup and recovery; it blocks `finalize` until it is resolved.

### `GET /v1/workflows/instances/{workId}/objects/{name}/revisions/{revision}`

`200 {"workId", "name", "revision", "digest", "originalDigest", "redacted", "object"}`

The default read is **exact**: the stored body is returned unchanged and
`digest` covers exactly what was returned, so a reviewer approves the
material the digest names. The body is not silently altered.

If the stored material contains a field that looks like a credential, the
exact read refuses (`422 WORKFLOW_OBJECT_CONTAINS_SECRETS`) rather than
returning something the digest does not cover. The caller may then ask for
the declared alternative, `?redact=true`, which returns the redacted body
with `redacted: true`, the digest of **what was returned** in `digest`, and
the stored digest in `originalDigest`. A platform must not use a redacted
fragment as complete approval material.

### `GET /v1/workflows/instances/{workId}/intents?kind=&sessionId=&status=&limit=`

`GET /v1/workflows/intents?workIds=W-1,W-2&kind=agent_task&sessionId=…&status=pending&limit=32`

`200 {"intents": [{"id", "kind", "node", "attempt", "status", "sessionId", "executor", "authority", "subject", "inputs", "checks", "deadlineAt", "createdAt", "acknowledgedBy"}]}`

The intent id is `wf:<workId>:<node>:<attempt>:<kind>` and is stable across
restarts; it is the request id a bridge uses for the original session.

### `POST /v1/workflows/intents/{intentId}/ack`

`{"actor": "coordinator"}` → `200 {"intentId", "status": "acknowledged"}`;
`404 WORKFLOW_INTENT_UNKNOWN`; `409 WORKFLOW_INTENT_CANCELLED`.

### `GET /v1/workflows/instances/{workId}/nodes/{nodeId}/attempts`

`200 {"workId", "node", "attempts": [{"attempt", "state", "outcome", "reason", "actor", "inputDigest", "output", "checkResults", "createdAt"}]}`

The attempt history of one node, with the judgments each attempt produced.
A judgment belongs to the attempt that produced it: the history is what a
reader consults, not the current state of the node.

### `GET /v1/workflows/instances/{workId}/events?after=`

`200 {"events": [{"seq", "version", "type", "body"}]}`

### `POST /v1/workflows/instances/{workId}/advance`

`200 {"decision", "currentNode", "workflowStatus", "resultStateVersion}` — the
client rarely needs this: every mutation settles the workflow, and the
bridge advances and recovers on its own schedule.

## The criterion report

A node's `checks` are protected declarations:

```json
{"id": "N04-2", "criterion": "<the text the reviewer read>",
 "method": "HUMAN", "criterion_version": "1",
 "validator": "safety-review", "validator_version": "1",
 "required": true, "allow_not_applicable": false}
```

`method` names the judge the definition expects — `PROGRAM`, `AGENT` or
`HUMAN` — so a reader can show who checks a criterion *before* any report
exists; the node's kind is never used to guess it. A criterion that is
first checked by a program and then reviewed by a model keeps **two**
declarations with two identifiers (`N09-2` with `PROGRAM` and `N09-2-review`
with `AGENT`) and therefore two independent records; a node may not
declare the same identifier twice.

A decision's `items` are refused at admission (`422
WORKFLOW_CHECK_REPORT_INVALID`) when an item names an undeclared criterion,
repeats one, carries a blank reason, carries empty evidence, or a verdict
outside `{passed, failed, insufficient, conflict, not_applicable}`.

At settlement every **required** criterion of that judge must be passed; a
`not_applicable` verdict counts only when the protected declaration sets
`allow_not_applicable`. A required criterion that is failed, insufficient or
in conflict is a genuine shortfall: an `approved` decision does **not**
complete the node, the shortage is persisted with its real verdict, and the
node keeps waiting. A `rejected` or `request_material` decision keeps the
shortages in the report — nothing is turned into a pass.

**The acceptance follows the same rule, and one list is stricter.** The
workflow acceptance (`finalize_workflow_success`) accepts a required
criterion that was judged `not_applicable` **only** when the protected
declaration sets `allow_not_applicable` — the same rule the node's
settlement applies, so a workflow that legitimately completed is not
refused by its own acceptance. The definition's `required_checks` list is
different: it is a bare list of identifiers with no declaration attached,
so there is no `allow_not_applicable` to map and only a `passed` verdict
satisfies it. A `not_applicable` verdict never satisfies a globally
required check.

The evidence of a **pass** is required; a shortage may carry none, because
its reason *is* the missing fact and inventing a reference would be a lie.

Every persisted report entry carries, at judgment time:

```json
{"checkId": "N04-2", "verdict": "passed", "reason": "...", "evidence": ["..."],
 "method": "HUMAN", "criterionVersion": "1",
 "validator": "safety-review", "validatorVersion": "1",
 "reviewedInputDigest": "...", "reviewedOutputDigest": "...",
 "decidedBy": "user-1", "at": 1760000000}
```

`method` is `PROGRAM` (a registered validator), `AGENT` (an independent
review) or `HUMAN` (a decision). The report is returned in the read model
under `nodes[].checkResults`, so a historical judgment is reconstructible
from the stored record and not from the current state of the node.

The automatic and wait nodes produce the same kind of report from the
validator that judged their output. The report is checked at the core
boundary before it counts: it may name declared criteria only, a **pass**
must carry its evidence, and a verdict must come from the validator the
criterion was bound to (`WORKFLOW_CHECK_VALIDATOR_MISMATCH`). A declared
criterion with no verdict is a refusal, not a pass
(`WORKFLOW_CHECK_RESULT_MISSING`); a required criterion that is not
satisfied is a genuine shortfall (`WORKFLOW_CHECK_SHORTFALL`) and the node
fails with `WORKFLOW_OUTPUT_INVALID`. Nothing is marked passed by
default.

`workflowStatus: "finished"` says that the **routing** stopped, never that
the work was delivered. The read model therefore also carries
`terminalNode` and `terminalOutcome` — the last node and what it decided
(`approved`, `rejected`, `failed`, `expired`) — so a caller never reads
"finished" as a successful delivery.

## The asynchronous review

A node that declares a review gets a durable `review_task` intent (id
`wf:<workId>:<node>:<attempt>:review_task`) with the same dedup, recovery and
acknowledgement discipline as the agent and human intents:

```json
{"node": "n09", "attempt": 1, "evidence_kind": "agent_review",
 "reviewer": "reviewer-v", "rubric": {"validator": "review-rubric", "validator_version": "1"},
 "criteria": [{"id": "N09-2", "criterion": "...", "criterion_version": "1", "required": true}],
 "candidate": {"name": "report", "revision": 1, "digest": "..."},
 "input_digest": "...", "inputs": [...], "deadline_at": null, "created_at": 1760000000}
```

The node's review declaration is
`{"evidence_kind": "agent_review", "reviewer": "reviewer-v", "rubric": {"validator": "review-rubric", "validator_version": "1"}}`.
The rubric must resolve at its exact version or the definition is not
publishable.

The review proof binds the exact instance:

```json
{"kind": "agent_review",
 "data": {"node": "n09", "attempt": 1,
          "input_digest": "<the node's pinned input digest>",
          "output_digest": "<the candidate's digest>",
          "producer": "reviewer-v", "verdict": "passed",
          "items": [{"check": "N09-2", "verdict": "passed", "reason": "...", "evidence": ["..."]}]}}
```

The proof's source must be the configured source for the kind; the producer
must be the declared reviewer and must **not** be the node's executor; the
node, the attempt and both digests must match the current attempt, so a
same-digest review of a previous attempt cannot satisfy the current one.
The reviewer's verdicts are persisted with `method` `AGENT`. Which model
actually produced the review is an enterprise adapter matter, not core.

## Errors

Every error is `{"error": {"code": "...", "message": "...", "findings": [...]}}` with
the engine's code verbatim. The status mapping is in
`work_runtime/workflow_server.py`; the codes a client should branch on are
`AUTHORITY_DENIED` (403), `STATE_VERSION_CONFLICT`, `WORKFLOW_ATTEMPT_STALE`,
`WORKFLOW_DECISION_STALE`, `WORKFLOW_INPUT_STALE` (409),
`WORKFLOW_RESULT_INVALID`, `WORKFLOW_AUTHORITY_MISMATCH`,
`WORKFLOW_CHECK_RESULT_MISSING`, `WORKFLOW_CHECK_REPORT_INVALID`,
`WORKFLOW_CHECK_SHORTFALL`, `WORKFLOW_POLICY_MISMATCH`,
`WORKFLOW_PARTICIPANT_UNKNOWN` (422), `WORKFLOW_RUNNER_MISMATCH` (403),
`WORKFLOW_NOT_FINISHED`, `WORKFLOW_TERMINAL_NOT_COMPLETED`,
`WORKFLOW_TERMINAL_NOT_DECLARED`, `WORKFLOW_EFFECT_UNRESOLVED`,
`WORKFLOW_REQUIREMENT_UNSATISFIED`, `WORKFLOW_NODE_UNSETTLED`,
`WORKFLOW_NODE_NOT_COMPLETED`, `WORKFLOW_QUALITY_UNSETTLED`,
`WORKFLOW_CHECK_UNSATISFIED`, `WORKFLOW_INTENT_UNSETTLED`,
`WORKFLOW_CANCELLED`, `WORKFLOW_SNAPSHOT_UNBOUNDED`, `WORKFLOW_FINALIZED`,
`WORKFLOW_ACCEPTANCE_REQUIRED`, `WORKFLOW_COMPLETION_PROOF_UNAVAILABLE`,
`WORKFLOW_COMPLETION_PROOF_UNVERIFIED`, `WORKFLOW_OUTPUT_NOT_REQUIRED`,
`CANCELLATION_NOT_REQUESTED`, `CANCEL_ACKNOWLEDGEMENT_MISMATCH` (409).

A workflow that was accepted is frozen: the bridge answers `409
WORKFLOW_FINALIZED` to every later mutation of it — a revised object, a new
result, a new decision — and the core refuses it as well.

## What the bridge does not do

* It does not authenticate: the principals are trusted local configuration,
  and the platform's authorization assertion is what the decision records.
* It does not decide business truth: a review is durable evidence from a
  named actor, and a passing shape never stands in for a business review.
* It does not accept a dynamic graph: only a published, immutable
  definition with constrained instance parameters.
* It does not promise exactly-once across systems: it promises stable
  idempotent effects and unknown-effect reconciliation.
