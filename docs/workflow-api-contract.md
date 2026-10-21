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
            "intentId": "wf:W-1:n04:1:human_task", "checks": [{"id": "N04-2", "criterion": "…", "validator": "safety-review", "validator_version": "1"}]}],
 "checks": [{"checkId": "N04-2", "node": "n04", "criterion": "…", "validator": "safety-review", "validatorVersion": "1"}],
 "allowedActions": [{"action": "submit_node_result", "node": "n04", "attempt": 1, "required": ["result"]}],
 "intents": [{"id": "wf:W-1:n04:1:human_task", "kind": "human_task", "node": "n04", "attempt": 1, "status": "pending", "sessionId": "session-original-1"}]}
```

Bounded: at most 64 nodes, 32 intents, 16 findings and 16 check results per
node. The view never carries a payload body.

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
`WORKFLOW_PARTICIPANT_UNKNOWN` (422).

## What the bridge does not do

* It does not authenticate: the principals are trusted local configuration,
  and the platform's authorization assertion is what the decision records.
* It does not decide business truth: a review is durable evidence from a
  named actor, and a passing shape never stands in for a business review.
* It does not accept a dynamic graph: only a published, immutable
  definition with constrained instance parameters.
* It does not promise exactly-once across systems: it promises stable
  idempotent effects and unknown-effect reconciliation.
