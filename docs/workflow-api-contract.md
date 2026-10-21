# Workflow API contract (version 1)

This is the exact wire contract of the mixed-node bridge, written for the
platform client that calls it. It is normative for `v1`: the fields below
are required where marked, and the responses are the ones the bridge
returns today.

The surface is `http://127.0.0.1:<port>/v1/workflows`. It is **separate
from** the product's `/v1/deliveries` route: the bridge is a governance
surface, not a task-delivery shortcut.

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

### `POST /v1/workflows/instances`

```json
{"workId": "W-1", "document": {"id": "H-001", "subject": "east parapet"}, "templateId": "inspection-review-delivery", "templateVersion": "test-1", "parameters": {"subject": "east parapet"}, "sessionId": "session-original-1", "commandId": "create-1"}
```

`201` the instance view. The document, contract and plan are constructed by
the host policy, not by arbitrary caller input. `parameters` are validated
against the definition's `parameters_schema`; an arbitrary dynamic graph is
refused.

### `GET /v1/workflows/instances/{workId}`

```json
{"workId": "W-1", "status": "active", "workflowStatus": "active", "stateVersion": 7, "currentNode": "n04",
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

`200` the instance view with `decision: {node, attempt, outcome, actorId, resultStateVersion}`.
`400 ACTOR_ID_REQUIRED`; `400 DECISION_INVALID` — no `items`;
`400 COMMAND_ID_REQUIRED`; `403 WORKFLOW_AUTHORITY_MISMATCH` — the actor is
not the principal the definition assigned; `409 WORKFLOW_ATTEMPT_STALE`;
`409 WORKFLOW_DECISION_STALE` — the digest or revision is not the current
subject; `422 WORKFLOW_CHECK_RESULT_MISSING` — a declared criterion has no
verdict.

### `POST /v1/workflows/instances/{workId}/objects`

```json
{"name": "intake", "object": {"records": []}, "actor": "coordinator", "commandId": "object-1", "expectedVersion": 9}
```

`200` the instance view with `object: {name, object, supersededNodes, resultStateVersion}`.

### `GET /v1/workflows/instances/{workId}/objects/{name}/revisions/{revision}`

`200 {"workId", "name", "revision", "digest", "object"}` — the exact stored
content of one object revision, for a workbench or an agent that restores
its context.

### `GET /v1/workflows/instances/{workId}/intents?kind=&sessionId=&status=&limit=`

`GET /v1/workflows/intents?workIds=W-1,W-2&kind=agent_task&sessionId=…&status=pending&limit=32`

`200 {"intents": [{"id", "kind", "node", "attempt", "status", "sessionId", "executor", "authority", "subject", "inputs", "checks", "deadlineAt", "createdAt", "acknowledgedBy"}]}`

The intent id is `wf:<workId>:<node>:<attempt>:<kind>` and is stable across
restarts; it is the request id a bridge uses for the original session.

### `POST /v1/workflows/intents/{intentId}/ack`

`{"actor": "coordinator"}` → `200 {"intentId", "status": "acknowledged"}`;
`404 WORKFLOW_INTENT_UNKNOWN`; `409 WORKFLOW_INTENT_CANCELLED`.

### `GET /v1/workflows/instances/{workId}/events?after=`

`200 {"events": [{"seq", "version", "type", "body"}]}`

### `POST /v1/workflows/instances/{workId}/advance`

`200 {"decision", "currentNode", "workflowStatus", "resultStateVersion}` — the
client rarely needs this: every mutation settles the workflow, and the
bridge advances and recovers on its own schedule.

## Errors

Every error is `{"error": {"code": "...", "message": "...", "findings": [...]}}` with
the engine's code verbatim. The status mapping is in
`work_runtime/workflow_server.py`; the codes a client should branch on are
`AUTHORITY_DENIED` (403), `STATE_VERSION_CONFLICT`, `WORKFLOW_ATTEMPT_STALE`,
`WORKFLOW_DECISION_STALE`, `WORKFLOW_INPUT_STALE` (409),
`WORKFLOW_RESULT_INVALID`, `WORKFLOW_AUTHORITY_MISMATCH`,
`WORKFLOW_CHECK_RESULT_MISSING` (422).

## What the bridge does not do

* It does not authenticate: the principals are trusted local configuration,
  and the platform's authorization assertion is what the decision records.
* It does not decide business truth: a review is durable evidence from a
  named actor, and a passing shape never stands in for a business review.
* It does not accept a dynamic graph: only a published, immutable
  definition with constrained instance parameters.
* It does not promise exactly-once across systems: it promises stable
  idempotent effects and unknown-effect reconciliation.
