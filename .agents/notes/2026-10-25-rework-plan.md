# Plan — the responsible owner authorizes one controlled candidate rework

Task `task_cad6f2a27cb8`, dispatch `ctx_5e6129138e41`, branch
`WayJ/gawr-material-wait`, baseline `573193e`. User product decision
2026-10-25; dsh-saas design §责任人授权一次受控返工; GAWR
`docs/interventions.md` command discipline.

## The behavior

After a terminal **Agent quality failure** (a failed
`WORKFLOW_RESULT_INVALID` terminal, in practice the exhausted
material-attempt failure), the trusted work manager may authorize **one**
controlled candidate rework per workflow:

* the old failure, its candidate report and the terminal record stay
  byte-for-byte on the record;
* a new monotonic attempt opens with trigger `rework`, its own ticket
  (`input_generation + 1`), the same pinned inputs and spec, and the
  original bound session's agent intent;
* neither the quality allowance, the material generation nor any
  published revision is reset — the rework spends no allowance;
* the pending `material_revalidation` queue is untouched: when the
  reworked attempt completes, the queue continues N02/N03 normally;
* the new attempt must pass honestly (original PROGRAM validators and
  the independent review, exactly as declared); if it fails, it fails
  terminally with no automatic retry and no second authorization.

## Deliverables

| id | deliverable |
|---|---|
| C1 | `work_runtime/workflow.py` — the command `authorize_rework` (dispatch, replay authority, `_authorize_rework`), the `rework` trigger honoured by `_quality_attempts` and `_successor`, the `candidateRework` projection in `instance()` |
| C2 | `work_runtime/workflow_server.py` — `POST /v1/workflows/instances/{workId}/rework` + the `rework` reply block |
| C3 | `tests/test_workflow_rework.py` — the live shape (n01 attempts 1–3, material attempt 4 failed terminally) plus authorization, continuation, termination, cap, guards, late-old-result refusals |
| C4 | `tests/test_workflow_rework_http.py` — the private route: happy path with the original session, replay, cap/CAS/actor conflicts, the projection |
| C5 | docs — `workflow-runtime.md` (§14 addition), `workflow-api-contract.md`, `verification.md`, a dated report note |

`work_runtime/runtime.py` and `work_runtime/adapters.py` stay untouched
(the command rides `WORKFLOW_COMMANDS`).

## The exact wire (sent to the coordinator before implementation)

`POST /v1/workflows/instances/{workId}/rework` with
`{actor|actorId, commandId, expectedVersion, node, attempt, inputDigest,
reason}`; reply adds `rework: {node, attempt, state, inputDigest,
authorization{authorizedBy, authorizedAt, reason, fromAttempt,
toAttempt, terminal}, resultStateVersion}`; every instance view carries
`candidateRework: {cap: 1, used, eligible, failed{node, attempt,
outcome, reason, inputDigest}|null, authorization|null}`. New refusal
codes: `WORKFLOW_REWORK_ALREADY_AUTHORIZED`,
`WORKFLOW_REWORK_INELIGIBLE`, `WORKFLOW_REWORK_EFFECT_PRESENT`
(+ `REWORK_INVALID` at the bridge); everything else reuses the existing
family.

## Task order

1. RED: C3/C4 over the real store — authorization, continuation,
   termination, cap, guards, late results, HTTP surface.
2. Minimal implementation of C1/C2 until GREEN.
3. Adjacent regressions: material revalidation/wait, engine,
   finalization, http, spec; gates: contracts, syntax, demo.
4. C5 docs + report; scoped commits; report to the coordinator.

## Guards (from the design)

Finalized/frozen, cancelling, closed, unknown node, non-agent node, a
terminal that is not a failed `WORKFLOW_RESULT_INVALID` (succeeded,
expired, cancelled), a genuine waiting workflow, a stale attempt or
ticket, an unauthorized actor, an already-authorized workflow, and a
downstream branch that carries a prepared/unknown/confirmed effect or a
settled human judgement — each refused with **no state write**. No SQL
repair, no new workflow, no source/replace/adopt replay, no
caller-supplied budget or rule override.
