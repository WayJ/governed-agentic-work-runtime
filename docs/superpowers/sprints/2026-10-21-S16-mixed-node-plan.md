# S16 (provisional id) — Mixed-node workflow runtime: core engine + integration surface

Status: **executed — the scoped plan and its sprint report.** Sprint id is
provisional: the coordinator owns epic/sprint allocation and the ledger. This
plan is the scoped implementation plan required by the dispatch; it executes
the ratified core additive direction of
[2026-10-21-mixed-node-workflow-runtime-design.md](../specs/2026-10-21-mixed-node-workflow-runtime-design.md)
phases 1–7, including the disclosed `work_runtime/runtime.py` freeze exception.
The **Sprint report** at the end of this file records what was actually built,
the RED/GREEN evidence, the wire shapes and the remaining risks.

Baseline: branch `WayJ/gawr-mixed-node-design` at `222d857`, `python3 -m unittest
discover -s tests` → **1132 tests, OK (2 skipped)**, `scripts/check_docs.py` clean.
Frozen-file SHA before this sprint:

| file | SHA-256 before |
|---|---|
| `work_runtime/runtime.py` | `80bf721b3369a6fb865fd6aba0e57804a69eb8587431f8fa6edf1183fc53f4b3` |
| `work_runtime/adapters.py` | `ce132f24d84c17a083bcf0b61bf90e1c62ff75faf2ec52fe2c7348ab86b6985e` |

`work_runtime/adapters.py` is **not** modified by this sprint.

## Scope

Build the smallest complete durable mixed-node engine on top of the existing
Work / Evidence / Operation / Wait / command-dedup / CAS machinery, plus a
versioned Python and HTTP integration surface the dsh-saas platform client can
call in parallel. No hardcoded construction domain in the core engine: node
kinds, predicates, validators, authorities and capabilities are declared by
published data and host configuration.

Out of scope: GUI wave (separate slice), dsh-saas edits, authentication or
multi-coordinator work, `migrate`/`revise` shortcuts that are not implemented.

## Deliverables

| id | deliverable | owns | acceptance |
|---|---|---|---|
| D1 | `work_runtime/workflow_spec.py` — published definition lint, canonical digest, three-valued predicate evaluator, closed shape descriptor, version-pinned validator registry | new file | W-spec rows |
| D2 | `work_runtime/workflow.py` — engine: template publication, pinned binding, named objects, node instances, routing/advance pass, agent result submission, human decision evidence, action dispatch, bounded rework, durable intents, cancel/revoke composition, restart recovery | new file + additive `runtime.py` hooks | W01–W25 subset |
| D3 | `work_runtime/workflow_server.py` — generic `/v1/workflows` HTTP surface (separate from the dsh `/v1/deliveries` route, which is untouched) + single-coordinator lock and periodic advance/recover loop | new file | W-http rows |
| D4 | `work_runtime/workflow_demo.py` — the N01–N10 safety scenario end to end on a fresh store, with a real crash/restart chapter and independently counted external effects | new file + CLI subcommand | end-to-end |
| D5 | docs: `docs/workflow-runtime.md`, `docs/runtime-boundaries.md`, `docs/verification.md`, `CONTRIBUTING.md`, README/README.zh-CN, AGENTS.md doc-sync rows | docs | `check_docs.py` clean |

## Frozen-file exception (disclosed)

`work_runtime/runtime.py` changes are additive and behaviour-preserving for
non-workflow works:

1. `_apply` dispatches the workflow command kinds to the engine.
2. `_evaluate` honours the engine-managed workflow status when a workflow is bound.
3. `_propose` / `dispatch` accept an **object-bound** operation payload
   (`{"object": {"name", "revision", "digest"}}`) so an action node can dispatch a
   named object through the existing adapter, operation, attempt, receipt and
   reconcile machinery instead of a second effect path.

The after-SHA is recorded in the sprint report and in
`docs/runtime-boundaries.md`. Non-workflow works keep byte-identical behaviour
(the existing 1132-test suite is the regression net).

## TDD sequence

Every step is RED → GREEN with the command recorded.

1. `tests/test_workflow_spec.py` — lint diagnostics, digest stability, predicate
   three-valuedness, shape validation, validator resolution.
2. `tests/test_workflow_engine.py` — publication, binding, routing determinism,
   unknown-blocks, exact-version human decision, role isolation, executor
   self-approval rejection, agent result validation, self-certification
   rejection, bounded rework, action dispatch idempotence, unknown-effect
   reconcile, cancel, revoke, late callback.
3. `tests/test_workflow_http.py` — route whitelist, wire shapes, bounded
   findings, allowed actions, durable intent ids, no credentials in logs.
4. `tests/test_workflow_recovery.py` — crash before dispatch, crash after
   external effect, restart resume, no duplicate side effect, no completed node
   re-executed.
5. `work_runtime/workflow_demo.py` — the business scenario (D4).

## Business acceptance mapping

N01/N02/N03/N09 agent nodes, N04/N05/N07/N08 human nodes, N06/N10 action nodes,
plus a wait node — all expressed in published template data. A's approval
creates B's task with no agent turn; B's approval dispatches one idempotent
external action; D's approval queues original-session agent work through a
durable intent.

# Sprint report (S16 — mixed-node workflow runtime)

## What was built

| id | deliverable | outcome |
|---|---|---|
| D1 | `work_runtime/workflow_spec.py` | shipped: lint, canonical digest, three-valued predicates, closed shape descriptors, the version-pinned validator registry |
| D2 | `work_runtime/workflow.py` | shipped: publication, pinned binding, named objects, node instances, routing, agent results, human decisions, automatic actions, bounded rework, durable intents, cancellation, recovery |
| D3 | `work_runtime/workflow_server.py` | shipped: the generic `/v1/workflows` bridge, the single-coordinator file lock and the periodic advance/recover ticker |
| D4 | `work_runtime/workflow_demo.py` | shipped: the ten-node demonstration family, the crash/restart harness and the `workflow-demo` / `workflow-worker` CLI subcommands |
| D5 | docs | shipped: `docs/workflow-runtime.md`, the boundary section in `docs/runtime-boundaries.md`, the W-matrix in `docs/verification.md`, `CONTRIBUTING.md`, `README.md`, `README.zh-CN.md` and the AGENTS.md doc-sync rows |

Phase 8 (the read-only GUI wave) is **not** part of this slice.

## The frozen-file exception, as executed

`work_runtime/runtime.py` was edited additively, as disclosed:

| file | SHA-256 before | SHA-256 after |
|---|---|---|
| `work_runtime/runtime.py` | `80bf721b3369a6fb865fd6aba0e57804a69eb8587431f8fa6edf1183fc53f4b3` | `49a8864b49d4b91ceeb456e1d4d5567c0a15b6d66815c576daf31dc700df1247` |
| `work_runtime/adapters.py` | `ce132f24d84c17a083bcf0b61bf90e1c62ff75faf2ec52fe2c7348ab86b6985e` | unchanged |

The five edits: four workflow tables under the existing schema version; the
dispatch of the workflow command kinds; the workflow status in `_evaluate`;
the object binding of a proposal; the cancellation hook. The byte pin in
`tests/test_publishing_compensation.py` was updated **consciously** (the
pin test fails loudly on any further change). Non-workflow works keep their
previous behaviour — the 1132-test baseline is the regression net and stayed
green throughout.

## RED/GREEN evidence

| step | RED | GREEN |
| the third round (the follow-up corrections) | `test_workflow_participants.py` (16) and `test_workflow_review.py` (8) written first; the first RED run showed 22 errors and 1 failure — the assigned authority was not resolvable, the criterion report was not checked, no review intent existed and the review proof did not bind the instance | `PYTHONPATH=.:tests python3 -m unittest test_workflow_participants test_workflow_review` → 24 tests, OK; the whole suite → 1268 tests, OK (2 skipped) |
| the second round (the coordinator's corrections) | `test_workflow_authority.py` — 11 tests written first; the first RED run showed 3 failures (a decision without a node/attempt binding still matched, a candidate without an input digest was accepted, a stale input reported the wrong code) | `PYTHONPATH=.:tests python3 -m unittest test_workflow_authority` → 11 tests, OK; the whole suite → 1234 tests, OK (2 skipped) |
|---|---|---|
| the definition language | `test_workflow_spec.py` — 31 tests, written before `work_runtime/workflow_spec.py` existed | `python3 -m unittest discover -s tests` → 1163 tests, OK |
| the engine | `test_workflow_engine.py` — 26 tests; the first RED was `AssertionError: 'rejected' != 'accepted'` because the lint rejected the `authority` node field (`NODE_FIELD_UNKNOWN`), then 4 failures and 3 errors as the authority selection, the change-detection of a routing pass, the decision-selection and the action actor were implemented | `PYTHONPATH=.:tests python3 -m unittest test_workflow_engine` → 26 tests, OK |
| the HTTP bridge | `test_workflow_http.py` — 11 tests; the first RED was a hang (the socket was never served) and then a dropped connection (a `_connection()` context manager used as a connection) and a `400` from a route that returned a bare dict | `PYTHONPATH=.:tests python3 -m unittest test_workflow_http` → 11 tests, OK |
| recovery | `test_workflow_recovery.py` — 7 tests; the first RED was the cancelled work reporting `needs_attention` where the test expected `active` | `PYTHONPATH=.:tests python3 -m unittest test_workflow_recovery` → 7 tests, OK |
| the demonstration | `test_workflow_demo.py` — 2 tests | `python3 -m work_runtime workflow-demo` → the ten chapters, one dispatch and one delivery counted in the business system's own store |

The gates at the end of the slice:

```
python3 -m unittest discover -s tests   →  1210 tests, OK (skipped=2)
python3 -m compileall -q work_runtime tests scripts   →  clean
python3 scripts/check_docs.py           →  124 markdown files, 670 local links, 0 broken
python3 -m work_runtime workflow-demo   →  the ten chapters, 2 external effects
```

## The wire shapes (as implemented)

The HTTP surface is `GET/POST /v1/workflows/…` and is separate from the
product's `/v1/deliveries` route, which this slice does not touch. The
authoritative description is [docs/workflow-runtime.md](../../workflow-runtime.md);
the coordinator received the same shapes as an early API proposal before the
surface grew.

| method | path | request | response |
|---|---|---|---|
| `GET` | `/v1/workflows` | — | `{"status","workflows","coordinator","api"}` |
| `POST` | `/v1/workflows/templates` | `{"spec": {...}}` | `201 {"templateId","templateVersion","digest"}` |
| `GET` | `/v1/workflows/templates` | — | `{"templates":[{templateId,templateVersion,digest}]}` |
| `GET` | `/v1/workflows/templates/{id}/{version}` | — | `{templateId,templateVersion,digest,spec,publishedBy,publishedAt}` |
| `POST` | `/v1/workflows/instances` | `{workId,document,templateId,templateVersion,parameters,sessionId?}` | `201` the instance view |
| `GET` | `/v1/workflows/instances/{workId}` | — | `{workId,status,workflowStatus,stateVersion,currentNode,workflow,nodes[],checks[],allowedActions[],intents[]}` |
| `POST` | `/v1/workflows/instances/{workId}/results` | `{node,attempt,object,result,actor,commandId?}` | `200 {result:{node,attempt,output,state,resultStateVersion}}` |
| `POST` | `/v1/workflows/instances/{workId}/decisions` | `{node,decision,digest,revision,eventId?}` | `200 {node,outcome,state,workflowStatus,currentNode,resultStateVersion}` |
| `POST` | `/v1/workflows/instances/{workId}/objects` | `{name,object,actor,commandId?}` | `200 {decision,object:{name,revision,digest},supersededNodes[]}` |
| `GET` | `/v1/workflows/instances/{workId}/intents` | `?kind=&sessionId=&status=&limit=` | `{"intents":[{id,kind,node,attempt,status,sessionId,executor,authority,subject,inputs,checks,deadlineAt,createdAt}]}` |
| `POST` | `/v1/workflows/intents/{intentId}/ack` | `{actor}` | `200 {intentId,status}` |
| `GET` | `/v1/workflows/instances/{workId}/events` | `?after=` | `{"events":[…]}` |
| `POST` | `/v1/workflows/instances/{workId}/advance` | — | `200 {decision,currentNode,workflowStatus,resultStateVersion}` |

Errors are `{"error":{"code","message","findings"}}` with the engine's code
verbatim; the status mapping lives in `work_runtime/workflow_server.py`.

The durable intent id is `wf:<workId>:<node>:<attempt>:<kind>` and is stable
across restarts; it is the request id a bridge uses for the original
session.

## Second round — the coordinator's corrections

The coordinator reviewed the first slice and required corrections before
the surface could be frozen. They are implemented here; the RED evidence is
in `tests/test_workflow_authority.py` (11 tests) and in the new mutation
contract cases of `tests/test_workflow_http.py`.

| correction | implementation | evidence |
|---|---|---|
| a decision must bind the node **and** the attempt, so a same-digest approval of an earlier attempt is refused | the decision evidence carries `node` and `attempt`; the lookup matches both | `test_a_same_digest_approval_of_an_earlier_attempt_is_refused` |
| the **actor** is the asserted principal; the ingress source is not the actor | the decision evidence carries `actor`; the authority check and the separation rules compare the actor | `test_the_actor_of_a_decision_is_not_the_ingress_source` |
| every declared criterion needs a persisted verdict, a reason and its evidence | a node's `checks` are declarations (`id`, `criterion`, optional `validator`/`validator_version`); the validator's per-criterion report and the decision's `items` are persisted as `checkResults` and returned by the read model | `test_the_check_report_is_persisted_and_readable`, `test_every_declared_criterion_carries_a_verdict` |
| asynchronous review evidence, not self-certification | unchanged and extended: the candidate's declared criteria are judged by the registered validator, the agent node waits for the review proof, and the decision's items are the human's verdicts | `test_a_review_evidence_is_required_before_an_agent_node_completes` |
| `REQUEST_MATERIAL` as waiting evidence | a third decision value: the node keeps waiting, no outcome, no rework attempt, the request persisted | `test_a_request_for_more_material_keeps_the_node_waiting` |
| a candidate binds the current `inputDigest` | the node instance pins the digest of its inputs; a mismatch is `WORKFLOW_INPUT_STALE` | `test_the_input_digest_follows_the_pinned_input` |
| a stable `commandId` and `expectedVersion` on every mutation | the bridge refuses a mutation without them and passes the caller's version through; it never invents an id or substitutes a version | `test_a_mutation_without_a_command_id_is_refused`, `test_a_result_without_an_expected_version_is_refused`, `test_a_stale_expected_version_is_refused` |
| the exact content of one object revision is readable | `GET /v1/workflows/instances/{workId}/objects/{name}/revisions/{revision}` | `test_an_object_revision_is_readable` |
| the global intent listing is scoped | `GET /v1/workflows/intents?workIds=…` | `test_the_global_intent_listing_is_scoped_by_work` |
| the root instance view is returned | every mutation answers with the instance view | `test_a_mutation_returns_the_root_instance_view` |
| the protected template carries the criterion text and the validator version | the criterion declaration is part of the definition, and its validator must resolve at publication | `test_the_published_definition_carries_the_criterion_text` |
| the participant and authority mapping | documented in [docs/workflow-api-contract.md](../../workflow-api-contract.md): GAWR knows a principal per node, the platform maps a node to a workspace role and asserts the actor id, and the core enforces the assigned actor per node and attempt |
| no exactly-once across systems | the docs now say *stable idempotent effects and unknown-effect reconciliation* |

## Third round — the follow-up corrections

The coordinator reviewed the second slice and named six gaps in the
committed source. They are implemented here; the RED evidence is in
`tests/test_workflow_participants.py` (16 tests), `tests/test_workflow_review.py`
(8 tests) and the new contract cases of `tests/test_workflow_http.py`.

| gap | implementation | evidence |
|---|---|---|
| the decision wrote evidence without a compare-and-swap | the decision is a workflow command, `record_decision`: the runtime's CAS on `state_version` runs in the same transaction as the evidence intake, and the command is deduplicated under (ingress source, `commandId`). The HTTP route requires the caller's `expectedVersion` | `test_a_decision_without_an_expected_version_is_refused`, `test_a_stale_expected_version_is_refused` |
| a static authority cannot represent a role-assigned user per instance | a published definition may declare `"authority": {"assigned": true}`; a trusted, injected `ParticipantResolver` answers who currently holds the assignment and fails closed without one. The ingress source and the actual actor stay separate, and the separation rules compare the actual actors | `test_without_a_resolver_an_assigned_node_fails_closed`, `test_the_resolved_assignee_may_decide`, `test_the_assignment_is_rechecked_when_the_node_settles`, `test_two_roles_held_by_one_person_is_refused` |
| a criterion report was only checked for coverage | the report is checked at the core boundary (unknown, repeated, blank reason, empty evidence, unknown verdict) and at settlement a required criterion must be passed; a not-applicable verdict counts only under a protected rule; a shortfall stops an approval and is kept in a rejection | `test_an_unknown_criterion_is_refused` … `test_a_rejection_keeps_the_shortages` |
| the report did not record how and against what it was judged | every entry records the method (PROGRAM, AGENT, HUMAN), the criterion version, the bound validator, the reviewed input and output digests, the real verdict, the reason, the evidence, the actor and the time | `test_the_report_records_the_judgment_context` |
| no durable asynchronous review intent | a node that declares a review gets a `review_task` intent pinning the rubric, the criteria, the candidate revision, the input digest and the independent producer; the proof binds the work, node, attempt and both digests, and the executor may not review its own candidate | `test_a_review_node_creates_a_durable_review_intent`, `test_a_review_of_another_attempt_does_not_satisfy`, `test_the_executor_may_not_review_its_own_candidate` |
| the create ignored the caller's contract and plan | the submitted contract is checked against the registered immutable policy (`WORKFLOW_POLICY_MISMATCH`), the submitted plan is used as given, and the trusted platform create snapshot supplies the session, the parameters and the participant assignment | `test_a_policy_that_is_not_the_registered_one_is_refused`, `test_the_submitted_plan_is_used`, `test_the_trusted_snapshot_carries_the_session_and_the_participants` |

The exact wire contract of this round is
[docs/workflow-api-contract.md](../../workflow-api-contract.md).

## Deviations from the plan, and the open items

* The plan's phase 1–7 shape was kept; phase 8 (the GUI) was not part of
  the dispatch and is not shipped.
* The plan said "no timers, threads, leases or background processes". The
  dispatch requires a **periodic advance/recover without an Agent polling**
  and a **single-coordinator lock**, so the bridge owns one daemon thread
  (the ticker) and one operating-system file lock. The engine itself still
  has no thread and no timer: `now` is a parameter everywhere.
* The reserved `"document"` object bridge (design U2) is **not**
  implemented; the demonstration uses named objects only.
* `revise_workflow`, `migrate` and any other revision shortcut are **not**
  implemented and are not offered.
* `scripts/verify_install.py` was **not** extended with a workflow stage.
* The participant resolver is a **port**, not an implementation: the
  enterprise adapter that resolves a member against the platform's current
  membership, department and role state lives in dsh-saas. The default is
  no resolver, and an assigned authority then fails closed.
* The obligation layer of the demonstration family is kind-level; the exact
  version of an approval is an engine guarantee.

## Remaining risks

* The single-coordinator lock is an operating-system file lock: it stops a
  second coordinator on one machine, and it is not a distributed lease.
* The bridge resolves the approving principal from the published node and
  the policy's source registry, but the principal names remain trusted
  local configuration — this is not authentication.
* The demonstration's stand-in business system is a local SQLite store, not
  a real external system.
* The engine's advance pass is O(nodes) per work; a very large graph would
  need a different scheduling strategy.
