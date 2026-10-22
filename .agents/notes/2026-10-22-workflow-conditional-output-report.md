# Report — a human node's named output, declared for some decisions only

Task `task_6d7b0be8295a`, dispatch `ctx_471d2171bdf5`.
Branch `WayJ/gawr-mixed-node-design`, baseline `f5d097e` (the `1ca8560`
materials commit and the `f5d097e` not-applicable commit are untouched).

## The gap the dsh-saas integration found

A human node that declares a named acceptance output needs the record for
**every** decision today. A rejection, which has no business effect and no
acceptance record by design, therefore leaves the node running with
`WORKFLOW_OUTPUT_MISSING` and never reaches its `on_reject` branch — the
platform had to set a bounded self-reject with `max_attempts=1` to enter
`needs_attention` instead of the rework it declared.

## The declaration

`output.on_decisions` names the decisions for which the node's named output
is **required**:

```json
"n07a": {"kind": "human", "evidence_kind": "safety_review",
          "authority": "reviewer-a", "subject": {"object": "order"},
          "on_reject": "n07b",
          "output": {"object": "order_acceptance",
                     "on_decisions": ["approved"],
                     "validation": {"shape": {"…": "…"}, "validator": "record",
                                    "validator_version": "1"}}}
```

* It is **protected material**: it lives in the published definition, is
  pinned by its digest at binding, and is never caller data. A decision
  payload that carries the field is a malformed payload and is refused.
* It is **human-only**: any other kind that declares it is refused at
  publication (`NODE_FIELD_UNKNOWN`). The list must be nonempty and may
  name only `approved`, `rejected` or `request_material` (`SPEC_FIELD_TYPE`).
* The **default is unchanged**: without the declaration, a declared output
  is required for every decision, exactly as before.

## What each decision does

| decision | named output | result |
|---|---|---|
| `approved` | always required | the record is validated against the declared shape and the pinned validator, written, and bound to the exact subject and inputs (`outputBinding`); without it the node keeps waiting (`WORKFLOW_OUTPUT_MISSING`) |
| `rejected` | required unless the declaration exempts it | exempt: the decision is admitted and settles the node with the outcome `rejected`, **no** acceptance record is written, the quality record says `exempt`, the decision proof and the check report are preserved, and the routing continues — the `on_reject` branch is taken |
| `request_material` | required unless the declaration exempts it | exempt: the node keeps waiting and no record is written, exactly as before |

An **approval is never exempt**: whatever the list says, an `approved`
decision requires the named record — the record is what says the work was
accepted.

## The supplied record when the output is disabled

Decided and implemented: a record supplied for an exempt decision is
**refused** (`WORKFLOW_OUTPUT_NOT_REQUIRED`). It would be an acceptance
output for a decision that must not have one, so nothing is written: no
object row, no decision proof, and the node keeps waiting. The caller
re-sends the decision without the record. This matches the existing
`WORKFLOW_OUTPUT_UNDECLARED` rule for a record a node does not declare:
the record is refused loudly, never smuggled through.

## What is prevented

* **Skipped-output result smuggling** — a supplied record for an exempt
  decision is refused and nothing is written.
* **A stale attempt, a stale compare-and-swap and a foreign actor** — the
  decision path's own checks are untouched and still refuse
  (`WORKFLOW_ATTEMPT_STALE`, `STATE_VERSION_CONFLICT`,
  `WORKFLOW_AUTHORITY_MISMATCH`).
* **Bypassing the required human checks** — the settlement still requires
  a verdict for every human criterion of the node, and the exemption
  changes nothing about that.
* **Finalizing a rejection** — a workflow that ended on a rejection is
  refused by `finalize_workflow_success`
  (`WORKFLOW_TERMINAL_NOT_COMPLETED`), and the acceptance still requires
  every node's latest attempt to carry a successful verdict.

## RED/GREEN evidence

| step | RED | GREEN |
|---|---|---|
| the new tests | `tests/test_workflow_conditional_output.py` (16 tests) run against the pre-change core (`git checkout -- work_runtime/workflow.py work_runtime/workflow_spec.py`): **13 of 16 failed** — the declaration was refused by the lint, the rejection still needed the output, and the supplied record was neither refused nor kept out | `PYTHONPATH=.:tests python3 -m unittest test_workflow_conditional_output` → **16 tests, OK** |
| the workflow suites | — | the workflow suites plus the finalization, materials and conditional files → **327 tests, OK** |

No full repository run was repeated: the previous full run is already
recorded, and this slice touches the workflow engine and its lint only.

## The frozen files

`work_runtime/runtime.py` and `work_runtime/adapters.py` are byte
unchanged by this slice; the change is in `work_runtime/workflow.py` and
`work_runtime/workflow_spec.py`.

## Remaining boundaries

* The exemption is a *narrowing*: it can only remove the named output's
  requirement from a decision, never add one, and never from an approval.
* A node whose latest attempt is a rejection is never part of an accepted
  workflow — the acceptance refuses it — so a rejection that routes to a
  branch which does not re-run the node keeps the workflow unaccepted. A
  rework that re-runs the node (the usual shape) is unaffected.
* The declaration says which decisions need the record; it says nothing
  about what the record means. The host's validator still judges it.
