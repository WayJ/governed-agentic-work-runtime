# Report — a criterion that is not applicable at the acceptance

Task `task_8d2a81527bfb`, dispatch `ctx_68e8f108637b`.
Branch `WayJ/gawr-mixed-node-design`, baseline `1ca8560`.

## The defect Luna proved

The engine's own settlement has always accepted a `not_applicable` verdict
when the protected declaration sets `allow_not_applicable`: the node
completes, a human node approves, the workflow finishes. The **acceptance**
did not: its node-level check demanded a `passed` verdict for every
required criterion, so a workflow that legitimately completed was refused
by its own acceptance with `WORKFLOW_CHECK_UNSATISFIED`. The acceptance
contradicted the settlement it was supposed to agree with.

## The fix

One rule, in one place: the finalization's node-level check now accepts a
required criterion that is `passed` **or** `not_applicable` with
`allow_not_applicable` set on the protected declaration — the same rule
`_criterion_shortfalls` applies when the node settles. Nothing else moved:
a `failed`, an `insufficient` or a `conflict` verdict, and a missing
verdict, still refuse the acceptance, and no other criterion is relaxed.

The definition's own `required_checks` list stays **strictly passed-only**.
It is a bare list of identifiers with no per-criterion declaration, so
there is no `allow_not_applicable` to map onto it: a `not_applicable`
verdict never satisfies a globally required check. A node may therefore
complete under its own declaration while the acceptance refuses the
workflow — and the refusal says so: it names the global requirement
(`checkId`, no `node`), not a node.

## RED/GREEN evidence

| step | RED | GREEN |
|---|---|---|
| the new tests | `tests/test_workflow_finalization.py` — `NotApplicableCriterionTests` (3 tests) run against the pre-change core (`git checkout -- work_runtime/workflow.py`): **2 of the 3 failed** — the explicitly permitted not-applicable verdict was refused by the acceptance, and the globally required check was refused by the *node-level* rule instead of the global one | `PYTHONPATH=.:tests python3 -m unittest test_workflow_finalization` → **40 tests, OK** |
| the focused regressions | — | `test_workflow_finalization`, `test_workflow_participants`, `test_workflow_authority`, `test_workflow_engine`, `test_workflow_node_quality`, `test_workflow_review` → **144 tests, OK** |

No full suite was run: the previous full run (1412 tests, OK) is already
recorded and this slice changes one comparison in one method.

## What the three tests prove

1. `test_an_explicitly_permitted_not_applicable_verdict_is_accepted` — a
   human terminal whose declaration sets `allow_not_applicable` completes
   on a `not_applicable` verdict, the workflow finishes and the acceptance
   freezes it; the snapshot keeps the verdict.
2. `test_a_not_applicable_verdict_without_the_permission_cannot_pass` —
   the same verdict without the permission is a genuine shortfall: the
   node never completes, the workflow never finishes and nothing is
   frozen.
3. `test_a_globally_required_check_still_demands_a_pass` — the criterion
   is in the definition's `required_checks` **and** locally allowed: the
   node completes, the acceptance refuses `WORKFLOW_CHECK_UNSATISFIED`,
   and the refusal names the global requirement, not a node.

A PROGRAM or AGENT case was not added: the acceptance's criterion check
is judge-agnostic — it reads the verdict persisted on the node instance,
whatever judge produced it — so there is no second code path to cover.

## The frozen files

`work_runtime/runtime.py` and `work_runtime/adapters.py` are byte
unchanged by this slice; the change is one comparison in
`work_runtime/workflow.py`.

## Remaining boundaries

* The acceptance is stricter than the settlement in exactly one place, on
  purpose: the definition's `required_checks` list demands a pass. A host
  that wants a not-applicable criterion to satisfy a *global* requirement
  needs a declaration to map onto that list — the bare list carries no
  such rule.
* The materials context, the canonical proof, the generic-completion guard
  and the acceptance itself are untouched by this slice.
