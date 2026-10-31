# Close-out — the bind_workflow owner-authority fix

## The slice

`bind_workflow` is a management mutation: binding a published definition *is*
the work owner's authorization of that definition's action nodes. The
engine's replay path already required the owner's authority for this exact
command, and every sibling manager-class handler already checked it on the
fresh path — but the fresh path of `_bind` never read `actor`. The runtime
routes the workflow commands to the engine *before* its own manager gate, so
the runtime gate never applied to them. A principal that was in `grants` but
was not the owner could therefore bind a published template onto the owner's
work; the action nodes' operations were then proposed **in the owner's name**,
and the binder's `participants` map became the assignment snapshot of the
decision nodes.

The fix is one gate in `work_runtime/workflow.py::_bind`, calling the same
predicate the replay path uses:

```python
        if not self.runtime._manager(actor, work):
            return self.runtime._reject("AUTHORITY_DENIED", version)
```

It sits where the sibling handlers put theirs — after the payload-shape
validation, before every state-dependent rejection — so the fresh path and
the replay path cannot drift apart again. The slice changed nothing else in
`work_runtime/`: `runtime.py`, `adapters.py`, `file_adapter.py` and
`policy.py` (the four files pinned by SHA-256 in
`tests/test_publishing_compensation.py::BoundaryPins`) and
`work_runtime/workflow_server.py` are byte-unchanged.

Plan: [the coordinator's plan](2026-10-31-bind-workflow-authority-plan.md).
Report: [the slice report](2026-10-31-bind-workflow-authority-report.md).

## The merge

| what | value |
|---|---|
| accepted tip | `82702eb` (`docs: the contracts count and the changed-file list, corrected`) |
| branch | `WayJ/fix-bind-workflow-owner` |
| base of main | `5265332` (`docs: the plan for the bind_workflow owner authority`) |
| merge commit | `2385c7f` — `merge: the bind_workflow owner authority - branch tip 82702eb (1712 tests OK)` |
| parents | `5265332` and `82702eb` — a true `--no-ff` merge, both lines visible |
| origin/main | `2385c7f` |

The four slice commits stay visible in main's history, in order:

```
2385c7f merge: the bind_workflow owner authority - branch tip 82702eb (1712 tests OK)
82702eb docs: the contracts count and the changed-file list, corrected
b81a617 docs: the refusal order, precisely
d837746 docs: the report on the bind_workflow owner authority
ad162bf fix(workflow): binding a definition is the owner's own act
```

**Disclosure of who performed what.** The merge commit `2385c7f` and its push
to `origin/main` were already present when this integration pass began — an
earlier dispatch of this same task in this Orca run had created the merge
(ordinary `--no-ff`, `ort` strategy) and pushed it plain. This pass did not
re-merge and did not rewrite history: re-merging would have required a
force-push, which the working agreement forbids. This pass **verified** the
merge and the push independently, from the primary checkout, and recorded
the results below. The push performed by this pass returned
`Everything up-to-date`; the authoritative remote state was read with
`git ls-remote`, not inferred from the local remote-tracking ref.

## The verification this pass performed

**The diff is exactly the accepted slice.** `git diff 5265332..82702eb --stat`
lists six files: `work_runtime/workflow.py` (8 added lines), the new
`tests/test_workflow_bind_authority.py`, `docs/workflow-runtime.md`,
`docs/runtime-boundaries.md`, `docs/tech-debt-tracker.md` and the slice
report. `git diff 5265332..82702eb -- work_runtime/` shows only the one
gate and its comment. The four SHA-pinned files and
`work_runtime/workflow_server.py` show an empty diff. `git diff 82702eb main`
is empty — main's tree is the branch tip's tree.

**The merge is a true merge.** `git log -1 --format=%P 2385c7f` gives two
parents, `5265332` and `82702eb`. `git merge-base --is-ancestor 82702eb
main` succeeds, so the branch tip is a real ancestor of main and the
lineage is preserved. No rebase, no squash.

**The push landed.** `git ls-remote origin main` returns
`2385c7f4c5c25586839daa9e3640577b7d46d602` for `refs/heads/main`, and
`git merge-base --is-ancestor 82702eb origin/main` succeeds (exit 0) — the
branch tip is an ancestor of the pushed main.

## The gates — real output, run on the merged main

**The suite** — `python3 -m unittest discover -s tests -v`:

```
----------------------------------------------------------------------
Ran 1712 tests in 163.137s

OK (skipped=2)
```

1712 against the 1706 baseline: the six new bind-authority tests, no
regression. The focused file alone:

```
$ python3 -m unittest tests.test_workflow_bind_authority -v
test_the_bridge_binds_for_the_owner_and_refuses_a_non_owner (tests.test_workflow_bind_authority.HttpBindAuthorityTestCase) ... ok
test_a_non_owner_cannot_bind_a_published_definition (tests.test_workflow_bind_authority.NonOwnerBindingTests) ... ok
test_a_refused_binding_leaves_the_work_unchanged (tests.test_workflow_bind_authority.NonOwnerBindingTests) ... ok
test_the_owner_binds_the_definition (tests.test_workflow_bind_authority.NonOwnerBindingTests) ... ok
test_the_replay_rule_is_the_fresh_rule (tests.test_workflow_bind_authority.NonOwnerBindingTests) ... ok
test_the_new_owner_binds_and_the_previous_owner_may_not (tests.test_workflow_bind_authority.TransferredOwnershipBindingTests) ... ok

----------------------------------------------------------------------
Ran 6 tests in 0.677s

OK
```

**The contracts** — `python3 scripts/check_docs.py`:

```
checked 127 markdown files, 682 local links, 0 broken
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
```

(exit status 0; the demonstration binds as `coordinator`, the owner of the
work it creates, so the gate does not touch it.)

**The site** — `python3 scripts/check_site.py`:

```
checked 2 pages, 0 findings
```

**The arrears check** — the branch changed `work_runtime/workflow.py`, whose
`doc_sync_map` row owes `docs/runtime-boundaries.md`; the slice paid it
same-commit, and `docs/workflow-runtime.md` (the §2 authority statement and
the action-node paragraph) went with it. No other mapped file was touched,
so no other row fired. The tracker row this slice owed — TD-2 — is in the
tracker's own table in the accepted slice.

## The RED/GREEN evidence

Recorded by the slice worker and re-verified by the coordinator; the RED run
is against the pre-fix base `5265332`, the GREEN run against the branch tip.

**RED** — `python3 -m unittest tests.test_workflow_bind_authority -v`:

```
Ran 6 tests in 0.768s

FAILED (failures=3)
```

The defect is visible in the failure text: the non-owner's bind was
**accepted**, not refused.

```
AssertionError: 'accepted' != 'rejected'
- accepted
+ rejected
 : {'command_id': 'b3fad88fc2224a75988b25fdd5da7dfc', 'decision': 'accepted', 'result_state_version': 4, ...}
```

The same held after the ownership was transferred
(`'decision': 'accepted', 'result_state_version': 5`).

**GREEN** — the same command after the one-gate change:

```
Ran 6 tests in 0.803s

OK
```

The six cases cover: the non-owner is refused `AUTHORITY_DENIED`; the
refusal leaves the work unchanged (no binding, no state-version bump, no
`WorkflowBound` event); the owner still binds; `replay_allowed` agrees with
the fresh path for both principals; after `transfer_owner` the new owner
binds and the previous owner may not; and over the real loopback socket the
owner binds while a non-owner is refused with the work unchanged.

## The remaining residuals

Recorded honestly, not silently dropped:

* **The trust model is unchanged — principal names are configuration, not
  authentication.** Anyone who can call the runtime in-process is trusted,
  and `grants` is a configuration map
  (`docs/runtime-boundaries.md` §"Trust model and scope"). This fix restores
  the one boundary the code itself claimed and did not enforce; it adds no
  authentication of any kind.
* **A legacy owner-less work keeps the grant-only rule.** `_manager` falls
  back to `"work.manage" in grants[actor]` when the work has no owner, so
  any principal holding `work.manage` may bind such a work. That is the
  runtime's existing `_manager` semantics, unchanged, and it is exactly what
  the replay path already enforced.
* **The publisher of a template is still recorded, not authority-checked.**
  Publication creates no binding, and with this gate an unauthorized
  publication still cannot reach a work. Unchanged, and not part of this
  defect.
* **The HTTP bridge refuses a non-owner before the binding stage**, so the
  socket case is a boundary characterization rather than RED evidence: the
  bridge binds a definition inside the creation flow, and every earlier
  stage of that flow already asks the same owner question through
  `_manager`, so a non-owner is refused at the bridge boundary before the
  binding stage is reached. The socket case therefore also passed before
  the change; the fresh bind gate is exercised at the engine level by cases
  1–5, not through the socket.
* **`workflow_server.py`'s Host/Origin gap stays open as TD-2.** It is
  recorded in `docs/tech-debt-tracker.md` with status **open**, not repaid:
  a hardening item with its own slice, whose guard must be designed against
  a real launcher. This close-out does not mark it repaid.
* **No claim of distributed exactly-once or production safety** is made or
  implied by this slice; RFC coverage remains partial.

## The ledger

No epic/sprint ledger row is flipped by this close-out. The slice carries no
sprint allocation — the coordinator's plan
([2026-10-31-bind-workflow-authority-plan.md](2026-10-31-bind-workflow-authority-plan.md))
and the slice report are the record, and the epic/sprint allocation and the
`docs/superpowers/roadmaps/` files remain the coordinator's. The public
`docs/roadmap.md` is likewise untouched: this was a confirmed access-control
defect repaired in the already-shipped workflow runtime, not a new milestone
wave, and no acceptance record or milestone link exists to cite there.

What this close-out does leave behind, in the repository's own format:

| record | where |
|---|---|
| the plan | `.agents/notes/2026-10-31-bind-workflow-authority-plan.md` (on main at `5265332`) |
| the slice report, with the RED/GREEN evidence | `.agents/notes/2026-10-31-bind-workflow-authority-report.md` (on main at `d837746`) |
| the accepted tip | `82702eb` |
| the merge | `2385c7f` on main and on `origin/main` |
| the open hardening item | TD-2 in `docs/tech-debt-tracker.md`, status open |
| this close-out | `.agents/notes/2026-10-31-bind-workflow-authority-close.md` |

## The lessons

* **An engine that contradicts itself finds its own bug.** The replay path
  already applied `runtime._manager` to `bind_workflow`, and every sibling
  manager-class handler applied it on the fresh path. One handler out of
  eight did not, and the runtime's own gate could not catch it because the
  workflow commands are routed to the engine before that gate. The cheapest
  durable repair was to call the same predicate the replay path already
  used, so the two paths cannot drift apart a second time.
* **A boundary characterization is not RED evidence.** The socket-level case
  refused the non-owner *before* the change, because the bridge's earlier
  stages already asked the owner question. Reporting it as a boundary
  characterization — rather than as evidence the fix was needed — kept the
  RED claim honest.
* **The order of the refusals is part of the contract.** The gate sits
  before `WORKFLOW_ALREADY_BOUND`, `CONTRACT_NOT_ACTIVE` and the template
  checks, so a non-owner learns the work exists and is not theirs, but not
  whether a definition was already bound. That is the sibling handlers'
  order and the plan's prescription; the payload-shape validation still
  comes first, so a malformed payload gets the same `WorkflowError` for the
  owner and for a non-owner.

## The handover

No handover clauses were registered for this slice. Deferred with recorded
evidence: the `workflow_server` Host/Origin (and `Content-Type`) hardening
(TD-2, open, needs its own slice and a guard designed against a real
launcher); the trust model stays trusted-local — principal names are
configuration, not authentication; the legacy owner-less work keeps the
grant-only rule; the template publisher is still recorded rather than
authority-checked.
