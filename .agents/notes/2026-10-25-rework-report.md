# Report — the owner's one controlled candidate rework

Task `task_cad6f2a27cb8`, dispatch `ctx_5e6129138e41`.
Branch `WayJ/gawr-material-wait`, baseline `573193e`. Plan:
[2026-10-25-rework-plan.md](2026-10-25-rework-plan.md).

## What was built

After a terminal **agent quality failure** — in the deployed shape, the
exhausted quality allowance and a failed material attempt behind a
pending revalidation queue — the trusted work manager may authorize
**one** controlled candidate rework per workflow. The old failure stays
on the record; a new monotonic attempt (trigger `rework`) opens with its
own ticket, the same pinned inputs and rules, and the original bound
session's agent intent; nothing is reset; the revalidation queue
continues through the ordinary routing when the reworked attempt
completes; and a failed reworked attempt is terminal.

| id | deliverable | outcome |
|---|---|---|
| C1 | `work_runtime/workflow.py` — the command `authorize_rework`, the `rework` trigger honoured by the routing, the `candidateRework` projection | shipped |
| C2 | `work_runtime/workflow_server.py` — `POST /v1/workflows/instances/{workId}/rework` + the `rework` reply block | shipped |
| C3 | `tests/test_workflow_rework.py` — 14 tests over a real store in the deployed terminal shape | shipped |
| C4 | `tests/test_workflow_rework_http.py` — 4 tests over a real service on a real store | shipped |
| C5 | docs — `workflow-runtime.md` (§14), `workflow-api-contract.md`, `verification.md` (W176–W177) | shipped |

`work_runtime/runtime.py` and `work_runtime/adapters.py` are untouched:
the command rides the existing `WORKFLOW_COMMANDS` seam.

## The exact wire (one correction to the early contract)

`POST /v1/workflows/instances/{workId}/rework` with
`{actor|actorId, commandId, expectedVersion, node, attempt, inputDigest,
reason}` — **no `requestVersion`** (the early contract matched the
final shape here). The reply adds `rework: {node, attempt, state,
inputDigest, grant, resultStateVersion}`.

**Correction:** the early contract named the authorization block
`authorization`. The bridge's credential hygiene strips every key whose
name contains `authorization` (`SECRET_FIELDS`), so the wire field is
**`grant`** — `grant: {authorizedBy, authorizedAt, reason, node,
fromAttempt, toAttempt, sessionId, terminal}`. Also, `WORKFLOW_INPUT_STALE`
answers **422** per the existing status table, not 409 as the early note
said; everything else matches.

Every instance view (GET too) carries the projection:
`candidateRework: {cap: 1, used: 0|1, eligible, failed: {node, attempt,
outcome, reason, inputDigest}|null, grant: {…}|null}` — the
eligibility, the count and the failed ticket a workbench needs before
anybody acts.

New refusal codes: `WORKFLOW_REWORK_ALREADY_AUTHORIZED` (409),
`WORKFLOW_REWORK_INELIGIBLE` (409), `WORKFLOW_REWORK_EFFECT_PRESENT`
(409), `REWORK_INVALID` (400 at the bridge). Reused family codes:
`AUTHORITY_DENIED`, `CANCELLATION_ACTIVE`, `WORKFLOW_FINALIZED`,
`WORKFLOW_NODE_UNKNOWN`, `WORKFLOW_ATTEMPT_STALE`,
`WORKFLOW_INPUT_STALE`, `STATE_VERSION_CONFLICT`, `COMMAND_ID_REUSED`.

## RED/GREEN evidence

RED against `573193e` (before the implementation): `test_workflow_rework`
answered **11 failures + 1 error** — every authorization attempt
`COMMAND_UNSUPPORTED` — and `test_workflow_rework_http` answered **3
failures + 1 error** — the route `404 ROUTE_UNKNOWN` and no projection.

GREEN after the minimal implementation:

| suite | result |
|---|---|
| `test_workflow_rework` | **14 tests, OK** |
| `test_workflow_rework_http` | **4 tests, OK** |
| `test_workflow_material_revalidation`, `…_http`, `test_workflow_material_wait`, `…_http`, `test_workflow_spec` | **161 tests, OK** |
| `test_workflow_engine`, `test_workflow_finalization`, `test_workflow_http`, `test_workflow_recovery` | **121 tests, OK** |

Gates: `python3 scripts/check_docs.py` (127 files, 682 links, 0 broken);
`python3 -m compileall -q work_runtime tests scripts`; `python3 -m
work_runtime demo` — all clean. The full suite moves 1607 → 1625
(18 new tests); the byte pin of `runtime.py` still holds.

## The shape the tests reproduce

The isolated regression reproduces the deployed instance exactly: three
spent quality attempts (two rejected candidates, one accepted), the
manager's replacement while the third consumer waited (`sources`
revision 2, generation 1, queue `[n01, n02, n03]`), the material
attempt 4 failing the published validation, and the terminal
`finished` / failed `n01` / `WORKFLOW_RESULT_INVALID` with
`material_revalidation` still `revalidating`. No live store was touched.

## What is deliberately not here (explicit limitations)

* **One authorization per workflow, ever.** A second — new key, later
  retry, another manager — is refused; there is no caller-supplied
  budget and no way to raise the cap.
* **The rework passes nothing.** The new candidate faces the original
  published validation, the declared PROGRAM checks and any declared
  independent review, exactly as every earlier attempt did. The root
  platform's metadata corrections do not excuse the candidate.
* **The rework spends no allowance.** It is neither a quality attempt
  nor a material attempt: `max_attempts`, the spent attempts, the
  material generation and every published revision are what they were.
* **Only the terminal failed agent node.** A genuine wait, a running
  node, an expiry, an unknown result, a cancellation, a success, a
  human node and an automatic node are never eligible.
* **The effect/human-judgement guard is defensive depth.** In a legal
  history the replacement that produced the terminal failure has
  already refused a branch carrying an effect or a human judgement, so
  the rework's own `WORKFLOW_REWORK_EFFECT_PRESENT` guard cannot be
  reached by a legal sequence; it is tested by crafting the legacy row
  in the test store only.
* **No replay of anything.** The source read, the replacement, the
  adoption, the old candidate, the old review and the old
  acknowledgement are never re-run; old tickets cannot reach the new
  attempt.
* **The projection is not an authority.** `candidateRework` is an
  observation for the workbench; only the command, under the owner's
  authority and a compare-and-swap, authorizes anything.

## The commits

| commit | content |
|---|---|
| `fa12ab1` | feat: the owner may authorize one controlled candidate rework after a terminal failure |

Nothing was merged and nothing was pushed: the branch is left for the
integration worker.
