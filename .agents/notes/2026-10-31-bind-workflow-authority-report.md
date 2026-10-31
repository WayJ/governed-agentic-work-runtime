# Report — binding a workflow is the owner's act, on the fresh path too

Slice: the scoped security fix planned in
`.agents/notes/2026-10-31-bind-workflow-authority-plan.md`.

* Baseline: `5265332` (`docs: the plan for the bind_workflow owner authority`),
  branch `WayJ/fix-bind-workflow-owner`. Baseline suite: 1706 tests, OK
  (skipped=2).
* Python >=3.9, standard-library `unittest` only, zero runtime dependencies.
* This worker did not merge, push, rebase or open a pull request.

## 1. The defect, and the trace that confirms it

`bind_workflow` is a management mutation: binding a published definition *is*
the work owner's authorization of that definition's action nodes
(`docs/workflow-runtime.md` §2, §"Action nodes"). Every other management-class
command enforces that. `bind_workflow` did not.

The chain, from the security review and confirmed here in the code:

* `work_runtime/runtime.py:416-421` — `_apply` returns
  `engine.apply_command(...)` for every kind in `WORKFLOW_COMMANDS`
  (`work_runtime/workflow.py:35-39`), and `bind_workflow` is one of them. The
  runtime's own manager gate (`work_runtime/runtime.py:432-433`) sits *after*
  that return, so it is unreachable for this kind.
* `work_runtime/workflow.py:644` — `_bind` never read `actor`. Every check it
  made was template-versus-policy: shape, already-bound, contract active,
  template existence, family, parameters, validators, effect policies,
  authorities, required checks, capabilities, participants. None of them
  concerned *who* was asking.
* The engine contradicted itself: the **replay** path requires the owner's
  authority for this exact command (`work_runtime/workflow.py:582-585`, the
  first entry of the `replay_allowed` manager list), and every **sibling**
  manager-class handler checks it on the fresh path (`_revise_object`
  `:907`, `_request_material_wait` `:3335`, `_adopt_material` `:3417`,
  `_resume_material_wait` `:3616`, `_replace_material` `:3710`,
  `_authorize_rework` `:3910`). Only the fresh path of `_bind` omitted it.

The consequences were not cosmetic:

* `work_runtime/workflow.py:1622-1650` — `_start_action` proposes the
  template's action-node operations as `actor = work.get("owner") or
  self.runner`. A non-owner therefore caused capabilities
  (`work.dispatch`, `work.deliver`) to be proposed **in the owner's name** —
  capabilities the binder does not hold and could never propose itself.
* The binding was then closed: `WORKFLOW_ALREADY_BOUND`
  (`workflow.py:660-661`) refused the owner's own choice.
* The binder's `participants` map became the assignment snapshot for
  `{"assigned": true}` decision nodes (`workflow.py:726-745`, `760-762`), so
  the binder also steered who was allowed to decide them.

(The line numbers above are those of the file **after** this change; the
plan cited the pre-change numbers, eight lines lower, because the gate and
its comment were added above them.)

In the shipped configuration the principal that could do this is
`agent-executor`, which holds exactly `{"workflow.execute"}`
(`work_runtime/workflow_demo.py:150-164`).

## 2. The change (D1)

One gate in `_bind`, placed where the sibling handlers place theirs — after
the payload-shape validation and before every state-dependent rejection
(`work_runtime/workflow.py:652-659`):

```python
        if not self.runtime._manager(actor, work):
            return self.runtime._reject("AUTHORITY_DENIED", version)
```

`runtime._manager` (`work_runtime/runtime.py:528-533`) is the predicate the
replay path already uses for this exact command, so the fresh path and the
replay path cannot drift apart again. It is the *owner* predicate, not a bare
capability test: `actor == work["owner"]` **and** `"work.manage" in
grants[actor]`; for a legacy work with no owner it falls back to the grant
alone, exactly as everywhere else in the runtime.

Nothing else in `work_runtime/workflow.py` changed. In particular
`work_runtime/runtime.py`, `work_runtime/adapters.py`,
`work_runtime/file_adapter.py` and `work_runtime/policy.py` were **not**
touched — the four files that `tests/test_publishing_compensation.py`
(`BoundaryPins.PINNED`) pins by SHA-256. The pin test passes unchanged (see
§5).

The trust model, the grants model, the replay semantics, the effect policies,
the participants rules and every wire shape are unchanged.

## 3. The tests (D2) — RED first

`tests/test_workflow_bind_authority.py`, six cases on the existing fixtures
of `tests/workflow_support.py` (`build`, `send`, `version_of`,
`scenario_template`, `document`, `RecordingAdapter`):

1. `test_a_non_owner_cannot_bind_a_published_definition` — `agent-executor`
   binds the owner's work: refused `AUTHORITY_DENIED`.
2. `test_a_refused_binding_leaves_the_work_unchanged` — no binding, no
   `workflow_status`, no state-version bump, no `WorkflowBound` event.
3. `test_the_owner_binds_the_definition` — the owner binds, and the binding
   is on the work.
4. `test_the_replay_rule_is_the_fresh_rule` — `replay_allowed` is `False`
   for the non-owner and `True` for the owner: the two paths are one
   predicate.
5. `test_the_new_owner_binds_and_the_previous_owner_may_not` — after
   `transfer_owner` to a principal holding `work.manage`, the new owner
   binds and the previous owner is refused.
6. `test_the_bridge_binds_for_the_owner_and_refuses_a_non_owner` — over the
   real loopback socket, the owner's creation binds and a non-owner's
   attempt on the owner's work is refused `AUTHORITY_DENIED` (403) with the
   work unchanged.

### RED — before the change

```
$ python3 -m unittest tests.test_workflow_bind_authority -v
test_the_bridge_binds_for_the_owner_and_refuses_a_non_owner (tests.test_workflow_bind_authority.HttpBindAuthorityTestCase) ... ok
test_a_non_owner_cannot_bind_a_published_definition (tests.test_workflow_bind_authority.NonOwnerBindingTests) ... FAIL
test_a_refused_binding_leaves_the_work_unchanged (tests.test_workflow_bind_authority.NonOwnerBindingTests) ... FAIL
test_the_owner_binds_the_definition (tests.test_workflow_bind_authority.NonOwnerBindingTests) ... ok
test_the_replay_rule_is_the_fresh_rule (tests.test_workflow_bind_authority.NonOwnerBindingTests) ... ok
test_the_new_owner_binds_and_the_previous_owner_may_not (tests.test_workflow_bind_authority.TransferredOwnershipBindingTests) ... FAIL

======================================================================
FAIL: test_a_non_owner_cannot_bind_a_published_definition (tests.test_workflow_bind_authority.NonOwnerBindingTests)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/Users/jiangwei/orca/workspaces/governed-agentic-work-runtime/gawr-bind-authority/tests/test_workflow_bind_authority.py", line 105, in test_a_non_owner_cannot_bind_a_published_definition
    self.assertEqual(receipt["decision"], "rejected", receipt)
AssertionError: 'accepted' != 'rejected'
- accepted
+ rejected
 : {'command_id': 'b3fad88fc2224a75988b25fdd5da7dfc', 'decision': 'accepted', 'result_state_version': 4, 'template_id': 'inspection-review-delivery', 'template_version': 'test-1', 'workflow_digest': 'fc5c0f1899a33c7ba8a31f3ba0692ae29fad34bbdd8097def976e31f67ed865c'}

======================================================================
FAIL: test_a_refused_binding_leaves_the_work_unchanged (tests.test_workflow_bind_authority.NonOwnerBindingTests)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/Users/jiangwei/orca/workspaces/governed-agentic-work-runtime/gawr-bind-authority/tests/test_workflow_bind_authority.py", line 113, in test_a_refused_binding_leaves_the_work_unchanged
    self.assertEqual(receipt["decision"], "rejected", receipt)
AssertionError: 'accepted' != 'rejected'
- accepted
+ rejected
 : {'command_id': '3587d7045ee441bbb2603b49afc7cb7e', 'decision': 'accepted', 'result_state_version': 4, 'template_id': 'inspection-review-delivery', 'template_version': 'test-1', 'workflow_digest': 'fc5c0f1899a33c7ba8a31f3ba0692ae29fad34bbdd8097def976e31f67ed865c'}

======================================================================
FAIL: test_the_new_owner_binds_and_the_previous_owner_may_not (tests.test_workflow_bind_authority.TransferredOwnershipBindingTests)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/Users/jiangwei/orca/workspaces/governed-agentic-work-runtime/gawr-bind-authority/tests/test_workflow_bind_authority.py", line 158, in test_the_new_owner_binds_and_the_previous_owner_may_not
    self.assertEqual(refused["decision"], "rejected", refused)
AssertionError: 'accepted' != 'rejected'
- accepted
+ rejected
 : {'command_id': '63e7cd15ce624bbdbf2e2de53f943350', 'decision': 'accepted', 'result_state_version': 5, 'template_id': 'inspection-review-delivery', 'template_version': 'test-1', 'workflow_digest': 'fc5c0f1899a33c7ba8a31f3ba0692ae29fad34bbdd8097def976e31f67ed865c'}

----------------------------------------------------------------------
Ran 6 tests in 0.768s

FAILED (failures=3)
```

The defect is visible in the RED output: the non-owner's bind is
**accepted** (`'decision': 'accepted'`, `result_state_version` 4), and the
same happens after the ownership was transferred.

### GREEN — after the change

```
$ python3 -m unittest tests.test_workflow_bind_authority -v
test_the_bridge_binds_for_the_owner_and_refuses_a_non_owner (tests.test_workflow_bind_authority.HttpBindAuthorityTestCase) ... ok
test_a_non_owner_cannot_bind_a_published_definition (tests.test_workflow_bind_authority.NonOwnerBindingTests) ... ok
test_a_refused_binding_leaves_the_work_unchanged (tests.test_workflow_bind_authority.NonOwnerBindingTests) ... ok
test_the_owner_binds_the_definition (tests.test_workflow_bind_authority.NonOwnerBindingTests) ... ok
test_the_replay_rule_is_the_fresh_rule (tests.test_workflow_bind_authority.NonOwnerBindingTests) ... ok
test_the_new_owner_binds_and_the_previous_owner_may_not (tests.test_workflow_bind_authority.TransferredOwnershipBindingTests) ... ok

----------------------------------------------------------------------
Ran 6 tests in 0.803s

OK
```

## 4. The documents (D3, D4, D5)

* **D3** `docs/workflow-runtime.md` §2 now states the binding authority: only
  the work's manager (the current owner holding `work.manage`) may bind, any
  other principal is refused `AUTHORITY_DENIED`, the refusal leaves the work
  untouched, the replay of a stored binding receipt asks the same question,
  and a legacy owner-less work keeps the grant-only rule. The "Action nodes"
  paragraph now points at that rule (§2) instead of restating it.
* **D4** `docs/runtime-boundaries.md`, the ownership-boundary section, states
  the binding rule and why it is the owner's act (the operations are
  proposed in the owner's name; the binder's `participants` map becomes the
  decision assignment snapshot), and records that the engine routes the
  workflow commands before the runtime's own manager gate, which is why the
  check lives in the engine's binding handler.
* **D5** `docs/tech-debt-tracker.md` gains a **TD-2** row in the existing
  table's format: the `workflow_server` Host/Origin (and `Content-Type`)
  hardening item. It is recorded as **open**, not repaid, with repayment
  criteria that state the work honestly — the guard has to be designed
  against a real launcher, and the bridge is only reachable over loopback in
  this repository, so the item is a hardening item and not a confirmed
  vulnerability.

## 5. The gates — real output

Every gate was run on the slice branch, after the change.

**The suite** — `python3 -m unittest discover -s tests -v`:

```
test_the_bridge_binds_for_the_owner_and_refuses_a_non_owner (test_workflow_bind_authority.HttpBindAuthorityTestCase) ... ok
test_a_non_owner_cannot_bind_a_published_definition (test_workflow_bind_authority.NonOwnerBindingTests) ... ok
test_a_refused_binding_leaves_the_work_unchanged (test_workflow_bind_authority.NonOwnerBindingTests) ... ok
test_the_owner_binds_the_definition (test_workflow_bind_authority.NonOwnerBindingTests) ... ok
test_the_replay_rule_is_the_fresh_rule (test_workflow_bind_authority.NonOwnerBindingTests) ... ok
test_the_new_owner_binds_and_the_previous_owner_may_not (test_workflow_bind_authority.TransferredOwnershipBindingTests) ... ok
...
----------------------------------------------------------------------
Ran 1712 tests in 214.730s

OK (skipped=2)
```

1712 = the 1706 baseline tests plus the six new ones. (The plain
`python3 -m unittest discover -s tests` run before it reported the same
result: `Ran 1712 tests in 256.587s` / `OK (skipped=2)`.)

**The pinned surface** — the four SHA-pinned files were not edited, so the
digest test stays green without any pin change:

```
$ python3 -m unittest tests.test_publishing_compensation.BoundaryPins -v
test_protected_surface_is_byte_unchanged_at_baseline (tests.test_publishing_compensation.BoundaryPins) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.007s

OK
```

`git diff --name-only 5265332..HEAD` lists exactly six files:
`work_runtime/workflow.py`, `tests/test_workflow_bind_authority.py`,
`docs/workflow-runtime.md`, `docs/runtime-boundaries.md`,
`docs/tech-debt-tracker.md` and this report,
`.agents/notes/2026-10-31-bind-workflow-authority-report.md`.
`work_runtime/runtime.py`, `work_runtime/adapters.py`,
`work_runtime/file_adapter.py` and `work_runtime/policy.py` are untouched,
and so is `work_runtime/workflow_server.py`.

**The contracts** — `python3 scripts/check_docs.py`:

```
checked 127 markdown files, 682 local links, 0 broken
```

(The file count is 127 at every commit of the slice and in a clean
checkout: `scripts/check_docs.py` excludes `.agents/`, so this report is
never counted. An earlier run of this gate during the slice reported 128
because the worker's own untracked scratch ledger —
`.superpowers/sdd/.../progress.md`, outside the excluded directories — was
still on disk; the scratch directory was deleted at the end of the run, and
the count is 127 again.)

**The site** — `python3 scripts/check_site.py`:

```
checked 2 pages, 0 findings
```

**The syntax** — `python3 -m compileall -q work_runtime tests scripts`:

```
(no output; exit status 0)
```

**The demonstration** — `python3 -m work_runtime demo`:

```
1. Agent proposes submission → BLOCKED by E05 (approval missing)
2. Work waits durably; no model session needs to stay alive
3. Finance approves current content → submission intent accepted
4. OA accepts → worker exits before saving the response (real process crash)
5. Restart → query original operation → existing OA receipt recovered
6. Evidence-backed completion → SUCCEEDED; external applications created: 1

Inspect the durable history:
  python3 -m work_runtime inspect --db "..." --work demo
```

(exit status 0; the demonstration binds its definition as `coordinator`, the
owner of the work it creates, so the gate does not touch it.)

## 6. The commits

| commit | content |
|---|---|
| `ad162bf` | `fix(workflow): binding a definition is the owner's own act` — D1 (the gate in `work_runtime/workflow.py`), D2 (`tests/test_workflow_bind_authority.py`), D3 (`docs/workflow-runtime.md`), D4 (`docs/runtime-boundaries.md`), D5 (`docs/tech-debt-tracker.md`, the TD-2 row) |
| `d837746` | `docs: the report on the bind_workflow owner authority` — D6 (this report) |
| `b81a617` | `docs: the refusal order, precisely` — the measured payload-shape order of §7 |
| this commit | `docs: the contracts count and the changed-file list, corrected` — the two factual corrections of §5 |

Branch `WayJ/fix-bind-workflow-owner`, based on `5265332`. Nothing was
merged, pushed or rebased; `main` is still at `5265332`.


## 7. The remaining risks and the honest residuals

* **Principal names are configuration, not authentication.** This fix does
  not change the trust model
  (`docs/runtime-boundaries.md` §"Trust model and scope"): anyone who can
  call the runtime in-process is trusted, and `grants` is a configuration
  map. What the fix restores is the one boundary the code itself claimed and
  did not enforce.
* **A legacy owner-less work keeps the grant-only rule.** `_manager` falls
  back to `"work.manage" in grants[actor]` when the work has no owner, so
  any principal holding `work.manage` may bind such a work. This is the
  runtime's existing `_manager` semantics, unchanged, and it is exactly what
  the replay path already enforced.
* **The publisher of a template is still recorded, not authority-checked.**
  Publication creates no binding, and with this gate an unauthorized
  publication still cannot reach a work. Unchanged, and not part of this
  defect.
* **The HTTP bridge cannot express a fresh bind by a non-owner.** The bridge
  binds a definition inside the creation flow
  (`work_runtime/workflow_server.py:565`), and every earlier stage of that
  flow (`bind_contract`, `revise_plan`) already asks the same owner
  question through `_manager`. A non-owner is therefore refused
  `AUTHORITY_DENIED` at the bridge boundary *before* the binding stage is
  reached — the observable outcome is the refusal the plan asked for, but
  the fresh bind gate is exercised at the engine level by cases 1-5, not
  through the socket. The socket case therefore passes before the change as
  well; it is a boundary characterization, not the RED evidence.
* **The refusal precedes the state-dependent refusals.** The gate sits
  before `WORKFLOW_ALREADY_BOUND`, `CONTRACT_NOT_ACTIVE` and the template
  checks, so a non-owner learns that the work exists and that it is not
  theirs, but not whether a definition was already bound. That ordering is
  what the sibling handlers use, and it is what the plan prescribed. The
  **payload-shape** validation still comes first, exactly as in the sibling
  handlers: a malformed payload is answered with the same `WorkflowError`
  for the owner and for a non-owner, and the message says nothing about
  the work. Measured on this branch: a non-owner with a malformed payload
  gets `WorkflowError: bind_workflow requires exactly template_id,
  template_version and parameters ...`, the owner with the same payload gets
  the identical error, and the non-owner with a well-formed payload gets
  `AUTHORITY_DENIED`.
* **`workflow_server.py`'s Host/Origin gap is untouched** (TD-2, D5). It is
  a hardening item with its own slice, out of scope here.
* **No claim of distributed exactly-once or production safety** is made or
  implied by this slice; RFC coverage remains partial.

## 8. The final review

The working agreement does not allow this worker to spawn another worker
without the coordinator's approval, so the whole-branch review was done
here, against the committed diff (`5265332..HEAD`) and the plan's Review
Focus.

* **Scope.** The diff is one gate, one test file and three documents. The
  four SHA-pinned files, `workflow_server.py`, the trust model, the grants
  model, the replay semantics, the effect policies, the participants rules
  and every wire shape are untouched. The plan's "out of scope" list is
  respected: the `workflow_server` Host/Origin gap is recorded as TD-2, the
  participants assignment map and `publish_template` are unchanged.
* **Placement.** The gate sits exactly where the sibling handlers put theirs
  (`_revise_object:907`, `_request_material_wait:3335`,
  `_adopt_material:3417`, `_resume_material_wait:3616`,
  `_replace_material:3710`, `_authorize_rework:3910`): after the
  payload-shape validation, before every state-dependent rejection. A
  malformed payload still raises `WorkflowError` rather than being answered
  with an authority code, exactly as before.
* **One predicate.** The gate calls `runtime._manager`, the same predicate
  `replay_allowed` already applies to `bind_workflow`; the fresh path and
  the replay path therefore cannot drift apart again. The test file pins
  that agreement explicitly (`test_the_replay_rule_is_the_fresh_rule`).
* **No information the work's owner did not already know.** The refusal
  carries the observed state version, like every other rejection in the
  runtime.
* **No new dependencies, no new syntax.** Python >=3.9, standard-library
  `unittest` only.

One finding was raised and **deferred** rather than fixed: the HTTP case
cannot be RED, because the bridge binds inside the creation flow and its
earlier stages refuse the non-owner first (§7). Fixing that would mean
changing the bridge's shape, which is out of scope for this slice.

Final review: self-review (no subagent dispatched — the working agreement
forbids spawning workers without the coordinator's approval).
