# Report — the atomic workflow-success acceptance

Task `task_72ec39bfdfc5`, dispatch `ctx_82a2b5f1fddc`.
Branch `WayJ/gawr-mixed-node-design`, baseline `457e3be`.

## What was built

| id | deliverable | outcome |
|---|---|---|
| F1 | `work_runtime/workflow.py` — the command `finalize_workflow_success`, its gate, the frozen final snapshot and the freeze of the routing pass | shipped |
| F2 | `work_runtime/workflow_server.py` — `POST /v1/workflows/instances/{workId}/finalize` and the immutable `GET /v1/workflows/instances/{workId}/completion` | shipped |
| F3 | `tests/test_workflow_finalization.py` — 24 tests, written before the implementation | shipped |
| F3b | `work_runtime/workflow_demo.py` — the acceptance as the demonstration's last chapter | shipped |
| F4 | docs — `docs/workflow-runtime.md` (§12), `docs/workflow-api-contract.md`, `docs/runtime-boundaries.md`, `docs/verification.md` (W79–W91) | shipped |

## The behaviour, in one paragraph each

**The acceptance is a command, not a read.** `workflow_status = finished`
says that the routing stopped; it never said that the work was delivered,
and it was mutable — the manager could still revise the object, the plan or
the document, or cancel the work. `finalize_workflow_success` is an
ordinary runtime command (CAS on `state_version`, receipt dedup under
`(actor, commandId)`, one transaction) issued by the **trusted runner** the
engine was configured with. An agent, a reviewer or the work owner is
refused (`WORKFLOW_RUNNER_MISMATCH`); a runtime without a runner fails
closed (`WORKFLOW_RUNNER_UNCONFIGURED`).

**The gate verifies before it freezes.** Under one transaction it checks:
a bound workflow whose definition still resolves; no cancellation; a
recorded terminal with no current node; a terminal node that **completed**
with a successful verdict (`completed` for an automatic node, `approved` for
a human one);
a terminal the published definition declares; every effect settled (no
prepared, dispatched or unknown operation); every obligation settled; every
node settled and completed; every declared quality `validated`; every
required criterion passed, including the definition's `required_checks`;
no pending intent; and a snapshot that names every object and every node.
Each refusal names what is not settled and writes nothing. Success is never
inferred from `finished` alone, and the generic `request_completion` is not
the acceptance path.

**The freeze is authoritative.** An accepted workflow closes its work as
`succeeded`, so the runtime's own closed-work rule refuses every later
mutation — a revised object, a revised plan, a revised document, a
cancellation, a new result, a new decision, a new effect — and the routing
pass is frozen, so no node opens and no effect is produced. The snapshot is
written once and never rewritten; it names the template digest, the
contract revision, the plan revision, the document revision and digest,
every object revision and digest, every node attempt with its judgment,
every effect, every obligation and the verified evidence.

**The receipt is durable and idempotent.** The receipt is the runtime's
ordinary command receipt: it replays identically across a restart with the
same command id and the same expected version, it is readable with
`GET /v1/workflows/commands/{commandId}?workId=&actor=`, and a *different*
command key after the freeze creates no second acceptance
(`WORK_NOT_ACTIONABLE`).

**What the freeze does not claim.** The runtime admits late evidence and
late revocation on a closed work — its own documented correction rule. The
freeze is about the workflow: a late proof or revocation is recorded in the
ledger, but it can neither change the accepted snapshot nor reopen the
accepted workflow, because the routing pass is frozen and the node
instances are not re-settled. The work's state version may still move; the
**accepted workflow proof** does not, and `snapshot.evidence` is the
verified set at the moment of the acceptance and never grows.

## What the demonstration shows

The demonstration (`python3 -m work_runtime workflow-demo`) ends with the
acceptance: the trusted runner accepts the finished workflow, the exact
final snapshot is frozen, and the demo shows the two consequences — a later
revision of the material is refused and a second acceptance with a new
command key creates no second finalization.

The demo also corrected the acceptance itself: a human node that approves
completes with the verdict of its kind (`approved`), not with the
`completed` of an automatic node. The acceptance therefore reads the
**state** of the terminal node and requires a successful verdict
(`completed` or `approved`); a rejected, failed, expired or cancelled
terminal is refused. The first version of the gate compared the outcome
with `completed` and refused the demonstration's own successful workflow —
the demo caught it, and the fix is covered by `HumanTerminalTests`.

## The disclosed engine change

A **finished workflow is not routed again.** The routing pass used to walk
the completed chain of a finished workflow and open a fresh attempt of its
last node (the fixture's terminal node was re-opened, its effect was
refused as already applied, and the workflow fell to `needs_attention`), so
`finished` was not a fact a reader could rely on — and an acceptance would
have raced with the bridge's ticker. The pass now finds the recorded
terminal and changes nothing (`test_a_finished_workflow_is_not_routed_again`).
This is the one behaviour change outside the new command, and it is
recorded in `docs/runtime-boundaries.md` and in the W-matrix.

## RED/GREEN evidence

| step | RED | GREEN |
|---|---|---|
| the new tests | `tests/test_workflow_finalization.py` (24 tests) run against the pre-change core (`git show 457e3be:work_runtime/workflow.py`): **23 of 24 failed** — the command was `COMMAND_UNSUPPORTED`, the routes did not exist, and the finished workflow had already been re-opened | `PYTHONPATH=.:tests python3 -m unittest test_workflow_finalization` → **24 tests, OK** |
| the workflow suites | — | `PYTHONPATH=.:tests python3 -m unittest test_workflow_engine test_workflow_http test_workflow_recovery test_workflow_review test_workflow_effect_policy test_workflow_node_quality test_workflow_action_context test_workflow_authority test_workflow_participants test_workflow_create_resume test_workflow_demo` → **224 tests, OK** |
| the whole suite | — | `python3 -m unittest discover -s tests` → **1411 tests, OK (skipped=2)** |

The gates at the end of the slice:

```
python3 -m unittest discover -s tests            →  1411 tests, OK (skipped=2)
python3 -m compileall -q work_runtime tests scripts   →  clean
python3 scripts/check_docs.py                    →  127 markdown files, 682 local links, 0 broken
python3 scripts/check_site.py                    →  2 pages, 0 findings
python3 -m work_runtime demo                     →  the six chapters, 1 external application
```

## The frozen files

`work_runtime/runtime.py` and `work_runtime/adapters.py` are **byte
unchanged** by this slice: no freeze exception was needed and none was
taken. The command rides the existing workflow command dispatch
(`WORKFLOW_COMMANDS`), the existing compare-and-swap, the existing command
dedup and the existing closed-work rule; the engine keeps the acceptance,
the snapshot and the routing freeze in `work_runtime/workflow.py`, and the
bridge keeps the two routes in `work_runtime/workflow_server.py`.

## The wire contract sent to the platform

Sent as `msg_6e5be70ba2ac` before the final suite run: the command kind
`finalize_workflow_success`, `POST /v1/workflows/instances/{workId}/finalize`
with `commandId` / `expectedVersion` / optional `actor`, the 200 body (the
instance view plus `finalization`), the native receipt fields
(`command_id`, `decision`, `result_state_version`, `observed_state_version`),
the immutable `GET .../completion` read, every refusal code with its HTTP
status, and the frozen semantics of late evidence.

Luna's independent finding — that `objects[:MAX_FINALIZATION_OBJECTS]` and
`nodes[:MAX_VIEW_NODES]` silently truncated the accepted proof — is
**fixed**: the acceptance is now refused with `WORKFLOW_SNAPSHOT_UNBOUNDED`
when the workflow names more material than a snapshot may hold
(`test_an_unbounded_snapshot_is_refused_instead_of_truncated`, 67 objects).

## Remaining boundaries

* The acceptance is a **local, trusted** decision: the runner is a
  principal in the grants map, not an authenticated identity. The bridge
  refuses a body that names anybody but the configured runner; it does not
  authenticate the caller.
* The generic `request_completion` still closes a workflow-bound work that
  is finished but not accepted. It is the generic work path, unchanged; the
  acceptance is the verified path, and the platform is told to use it.
  Closing that hole would need a change to the frozen `runtime.py` and was
  therefore not taken here.
* The acceptance is **not** a distributed exactly-once: the receipt is
  idempotent under `(actor, commandId)` in one store, and the platform's own
  task transaction remains responsible for re-enumerating the bindings.
* The snapshot is bounded (64 objects, 64 nodes); a workflow above the
  bound is refused rather than partly frozen.
* The material stays readable as the object revision the snapshot names; the
  snapshot itself carries no body.
