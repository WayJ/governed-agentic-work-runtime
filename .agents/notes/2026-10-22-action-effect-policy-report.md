# Worker report — the action-node effect policy

Task: `task_ecf41edeeeb2`, dispatch `ctx_fb4f525fb9d0`.
Branch: `WayJ/gawr-mixed-node-design`, baseline `4c3ff5a`.
Plan: [2026-10-22-workflow-action-effect-policy.md](../../docs/superpowers/plans/2026-10-22-workflow-action-effect-policy.md).

Commits (development branch only — nothing was merged or pushed):

| commit | what |
|---|---|
| `550f916` | `feat: an action node may produce a new effect for a new subject revision` — the policy in `work_runtime/workflow_spec.py` and `work_runtime/workflow.py`, the tests, the plan and the docs |

## What was built

A **published, pinned, opt-in** policy for the external effect of an
automatic node. The opt-in is data in the immutable published definition —
an action node may declare `effect_policy` — so it is linted, digested,
published and pinned by digest at binding: explicit, versioned, auditable.

| value | meaning |
|---|---|
| `once` | the default, unchanged: the node's effect happens once and a later attempt never repeats it |
| `per_revision` | a later attempt may produce a new effect for a **new revision with a new digest** of the node's subject, and only after the previous effect of the node is settled |

The exact admission of `per_revision`, for an attempt with the pinned
subject *S*, reading every earlier attempt of the same node from the store:

| the previous operation | the previous attempt | the new attempt |
|---|---|---|
| the row is missing, or the status is not terminal (prepared, dispatched, unknown outcome) | — | **refused**: `WORKFLOW_EFFECT_UNRESOLVED`; the node waits (blocked) and nothing is written until the operation is reconciled |
| `confirmed_failed` | — | admitted: the effect did not happen |
| `confirmed_succeeded` | the output failed validation | **refused**: `WORKFLOW_EFFECT_OUTPUT_INVALID` — a new subject does not bypass it and a manual retry does not either |
| `confirmed_succeeded` | the output was accepted | the same revision **and** digest → **refused**: `WORKFLOW_EFFECT_ALREADY_APPLIED`; a newer revision with a different digest → **admitted**; anything else → **refused**: `WORKFLOW_EFFECT_SUBJECT_UNCHANGED` |

The comparison is on the **revision and the digest of the same object**. It
never looks at the capability, at the work's cursor or at the node's place
in the graph.

After the admission the engine proposes through the ordinary path, so the
runtime creates an **actual new operation with a new business key** (the
key of an object-bound operation names the subject revision) and the node
instance stores that operation id. An operation this node already used, or
one another node instance already links, is refused
(`WORKFLOW_EFFECT_REUSED`): the linkage of an operation stays exact, so the
native action context of the **old** business key remains resolvable and
the new one names the new attempt.

The definition language gained two lint codes (`NODE_EFFECT_POLICY_UNKNOWN`,
`NODE_EFFECT_POLICY_ATTEMPTS`) and the binding one rejection
(`WORKFLOW_EFFECT_POLICY_UNKNOWN`). `effect_policy` is an action-node
field; another node kind that declares it is refused
(`NODE_FIELD_UNKNOWN`), and a `per_revision` node needs `max_attempts` of
at least two — the policy promises a second attempt the definition's own
allowance could never open.

## The real path the test drives

`tests/test_workflow_effect_policy.py` runs the real runtime, not a mock:

1. the agent produces proposal v1, and the **independent review** of the
   candidate arrives before the node completes;
2. the automatic node saves **draft v1** — one effect in the business
   system's own store;
3. the human **rejects** the draft;
4. the agent produces proposal v2 (new content, new digest) and it is
   independently reviewed again;
5. the automatic node saves **draft v2** — a second effect, a second
   operation, a second business key;
6. the human A and the human B approve draft v2;
7. the **one formal final action** runs.

Two version drafts, one final effect, and the receipt of the first draft
is still on its own attempt. The negative paths are refused with the exact
code: the default node (unchanged), the same digest under a new revision,
an unknown prior effect (a real crash between the effect and the record),
a failed output (a real refused receipt), an operation another node links,
an unknown policy at publication and at binding, and a pinned template
that cannot be changed under the same version.

## RED / GREEN evidence

| step | RED | GREEN |
|---|---|---|
| the definition language | `tests/test_workflow_effect_policy.py`: 14 failures, 3 passes, 0 errors — the lint knew no `effect_policy` (`NODE_FIELD_UNKNOWN`) | the five definition-language tests pass |
| the engine | the same run: the per-revision path, the three refusals and the binding rejection all failed | 18 tests pass |
| the whole workflow slice | — | `python3 -m unittest discover -s tests -p "test_workflow*.py"` → **255 tests, OK** |
| the final full suite | — | `python3 -m unittest discover -s tests -v` → **1387 tests, OK (skipped=2)** — both skips pre-existing (`adapter does not opt into action/link execution context`, `backend assembled: absent-install path unreachable`) |
| the other gates | — | `python3 scripts/check_docs.py` → 127 files, 680 links, 0 broken; `python3 -m compileall -q work_runtime tests scripts` → clean; `python3 -m work_runtime demo` → exit 0; `python3 scripts/check_site.py` → 2 pages, 0 findings |

`work_runtime/runtime.py` and `work_runtime/adapters.py` are **not**
modified; their byte pins are untouched.

## The independent review of the diff, and what it changed

The review read the diff against the plan and the brief, line by line. It
found five things; all five are fixed in `550f916`:

1. **An unknown operation status was unconstrained.** The first version
   treated every status that was neither `confirmed_succeeded` nor
   `confirmed_failed` as "no effect happened" and admitted a new attempt.
   That is a fail-open reading of a store that does not say what it means.
   Now every non-terminal status — and every status the engine does not
   know — is *unresolved*: the node waits for the reconciliation.
2. **The reuse check skipped the reused operation itself.** The loop
   compared the admitted operation with the *other* operations of the node
   and skipped the case where the ids were equal — which is exactly the
   case that matters. The same operation id is now refused.
3. **The link check refused the node's own pending operation.** The check
   "the operation is already linked to another node instance" did not
   exclude the instance that is being admitted, so a re-activated node
   could have refused its own operation. The exclusion is now exact: the
   current attempt's own link is allowed, every other link is refused.
4. **The lint checked the policy on every node kind.** A human node that
   declared `effect_policy` produced two findings (the unknown field and
   the missing allowance). The policy is now linted for action nodes only.
5. **The refusal message was inaccurate.** "The admitted operation is one
   this node already used" claimed an effect behind a *failed* operation.
   The message now says what is true: the operation belongs to an earlier
   attempt of this node.

## Remaining risks and disclosed limitations

* **The policy judges the revision, not its provenance.** It requires a
  new revision with a new digest of the pinned object; it does not and
  cannot say *who* produced that revision. In the demonstrated path the
  new revision is the agent's reviewed candidate (the declared output
  validator and the independent review gate it), but a manager's
  `revise_object` on the same object would also produce a new revision
  and a new digest, and the effect would then be admitted. Deciding which
  origin may produce a new version is the definition's business, not the
  core's.
* **A refusal that waits keeps the node blocked**, and a blocked node's
  deadline is re-armed on every re-activation (the pre-existing behaviour
  of blocked nodes). The recovery pass reconciles the unknown outcome; an
  operator who never reconciles it sees the workflow wait rather than
  fail. Every other refusal fails the node closed.
* **The default policy is untouched, including its edges.** A default
  node that retries after a *failed* operation adopts the same operation,
  which then links two node instances and makes the native action context
  ambiguous (`OPERATION_LINK_AMBIGUOUS`). That is a pre-existing edge of
  the default path; the per-revision path refuses it
  (`WORKFLOW_EFFECT_REUSED`). The default was left exactly as it was,
  because the brief requires it to stay.
* **A host that overrides the object business key** with a
  revision-independent key makes the runtime refuse the second proposal
  with `OPERATION_CONTENT_CONFLICT`; the node is then blocked and no
  second effect is produced. The effect is never repeated.
* **No distributed exactly-once is claimed.** The engine guarantees one
  *admission* per subject revision and an idempotency key per effect; the
  external system's own idempotency is still the host's responsibility for
  a call that is retried after an unknown outcome.
* **Nothing else moved.** The declared input and output validators, the
  required independent review, the order of the dispatch and the final
  close are unchanged, the policy is never a permission for a participant
  to certify its own work, and the core names are generic (`once`,
  `per_revision`).
