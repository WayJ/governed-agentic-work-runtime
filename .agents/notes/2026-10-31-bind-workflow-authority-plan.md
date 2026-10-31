# Plan — binding a workflow is the owner's act, on the fresh path too

Coordinator plan for the fix of the confirmed access-control defect found by the
2026-10-31 whole-repository security review.

Baseline: `main` at `28ba9ae` (`merge: the material-wait, revalidation and rework
slices - branch tip 623ad4b (1706 tests OK)`).
`python3 -m unittest discover -s tests` → **1706 tests, OK (skipped=2)**.

## The defect

`bind_workflow` is a management mutation — binding a published definition *is*
the work owner's authorization of that definition's action nodes
(`docs/workflow-runtime.md` §"Action nodes"; `docs/workflow-runtime.md:405-408`).
Every other management-class command enforces that. `bind_workflow` does not.

The runtime routes the workflow commands to the engine **before** its own
manager gate, so the gate never applies to them:

- `work_runtime/runtime.py:416-421` — `_apply` returns
  `engine.apply_command(...)` for every kind in `WORKFLOW_COMMANDS`
  (`work_runtime/workflow.py:35-39`), and `bind_workflow` is one of them. The
  manager gate `if not self._manager(actor, work)` sits *after* that return
  (`work_runtime/runtime.py:432-433`), so it is unreachable for this kind.
- `work_runtime/workflow.py:644-715` — `_bind` never reads `actor`. Its checks
  are all template-versus-policy checks: shape, already-bound, contract active,
  template existence, family, parameters, validators, effect policies,
  authorities, required checks, capabilities, participants. None of them
  concerns *who* is asking.

The engine therefore contradicts itself:

- the **replay** path requires the owner's authority —
  `work_runtime/workflow.py:582-585`, `replay_allowed` lists `bind_workflow`
  first among the kinds that need `self.runtime._manager(actor, work)`;
- every **sibling** manager-class handler checks it on the fresh path —
  `_revise_object` (`workflow.py:899`), `_request_material_wait` (`:3327`),
  `_adopt_material` (`:3409`), `_resume_material_wait` (`:3608`),
  `_replace_material` (`:3702`), `_authorize_rework` (`:3902`);
- only the fresh path of `bind_workflow` omits it.

A principal that is in `grants` but is not the owner — in the shipped
configuration, `agent-executor`, which holds exactly `{"workflow.execute"}`
(`work_runtime/workflow_demo.py:150-164`) — may therefore bind a published
template onto the owner's work. The consequences are not cosmetic:

* `work_runtime/workflow.py:1614-1642` — `_start_action` proposes the
  template's action-node operations as
  `actor = work.get("owner") or self.runner`. The worker causes operations to be
  proposed **in the owner's name** — capabilities (`work.dispatch`,
  `work.deliver`) the worker does not hold and could never propose itself.
* the binding is then closed: `WORKFLOW_ALREADY_BOUND` (`workflow.py:652-653`)
  refuses the owner's own choice.
* the binder's `participants` map becomes the assignment snapshot for
  `{"assigned": true}` decision nodes (`workflow.py:717-737`, `752-754`), so the
  binder also steers who may decide them.

## The behavior after the fix

* A principal that is not the work's manager cannot bind a workflow. The
  command is refused `AUTHORITY_DENIED`, exactly as the sibling management
  commands refuse it, and the work is left byte-for-byte unchanged: no
  binding, no `WorkflowBound` event, no state-version bump.
* The owner binds exactly as before. Every existing flow is unchanged:
  the HTTP bridge creates the work with the same actor that then binds it
  (`work_runtime/workflow_server.py:519-572`; `create_work` sets
  `work["owner"] = actor`, `work_runtime/runtime.py:405`), the demonstration
  binds as `coordinator` (`work_runtime/workflow_demo.py:853`), and
  `transfer_owner` moves the owner to a principal that holds `work.manage`
  (`work_runtime/runtime.py:611-623`).
* The fresh path and the replay path now agree: both require the manager.

## Deliverables

| id | deliverable | owns | acceptance |
|---|---|---|---|
| D1 | `work_runtime/workflow.py` — the owner gate in `_bind` | `_bind` only | the refused command leaves the work unchanged |
| D2 | `tests/test_workflow_bind_authority.py` — the new regression file | new file | RED before D1, GREEN after |
| D3 | `docs/workflow-runtime.md` — §2 states the binding authority | §2 and the action-node paragraph | the doc states the rule the code enforces |
| D4 | `docs/runtime-boundaries.md` — the ownership boundary states the binding rule | the ownership-boundary section | same |
| D5 | `docs/tech-debt-tracker.md` — TD-2, the `workflow_server` Host/Origin hardening item | the tracker's table | the residual is recorded, not silently dropped |
| D6 | `.agents/notes/2026-10-31-bind-workflow-authority-report.md` — the report | new file | RED/GREEN evidence, commits, residual risks |

## The exact change

One gate, in `_bind` (`work_runtime/workflow.py:644`), placed where the sibling
handlers place theirs — after the payload-shape validation and before every
state-dependent rejection:

```python
        if not self.runtime._manager(actor, work):
            return self.runtime._reject("AUTHORITY_DENIED", version)
```

`_manager` (`work_runtime/runtime.py:528-533`) is the predicate the replay path
already uses for this exact command, so the two paths cannot drift again. It is
the *owner* predicate, not a bare capability test: `actor == work["owner"]`
**and** `"work.manage" in grants[actor]`; for a legacy work with no owner it
falls back to the grant alone, as everywhere else in the runtime.

Nothing else changes. In particular this slice does **not** touch
`work_runtime/runtime.py`, `work_runtime/adapters.py`,
`work_runtime/file_adapter.py` or `work_runtime/policy.py` — those four are
SHA-pinned by `tests/test_publishing_compensation.py`
(`BoundaryPins.PINNED`) and this fix needs none of them.

## The tests (TDD, RED first)

`tests/test_workflow_bind_authority.py`, standard-library `unittest`, using the
existing fixtures in `tests/workflow_support.py` (`build`, `send`,
`version_of`, `scenario_template`):

1. **RED — a non-owner is refused.** A work created and owned by `coordinator`
   (contract bound, no workflow yet); `agent-executor` — which holds only
   `{"workflow.execute"}` — issues `bind_workflow` with the published
   template. Expect `{"decision": "rejected", "code": "AUTHORITY_DENIED"}`.
   Before the fix this is accepted, so the test fails.
2. **The refusal changes nothing.** After the refused command: the work still
   has no `workflow` binding, its `state_version` is unchanged, and no
   `WorkflowBound` event exists for it.
3. **The owner is unaffected.** The same bind by `coordinator` is accepted and
   the binding is present.
4. **The engine's own replay rule agrees.** `replay_allowed` for
   `bind_workflow` is `False` for the non-owner and `True` for the owner — the
   fresh path and the replay path are the same predicate.
5. **The owner may be transferred.** After `transfer_owner` to a principal
   holding `work.manage`, that principal may bind and the previous owner may
   not.
6. **The HTTP bridge refuses it too.** Over the real loopback socket
   (`tests/test_workflow_http.py` patterns), a bind attempt by a non-owner is
   refused with `AUTHORITY_DENIED`, and the owner still succeeds.

The worker records the RED output before touching D1 and the GREEN output
after, both verbatim, in the report.

## Gates (all of them, from the slice branch)

```
python3 -m unittest discover -s tests -v      # 1706 + the new tests, OK
python3 scripts/check_docs.py                 # contracts
python3 -m compileall -q work_runtime tests scripts
python3 -m work_runtime demo                  # demo
python3 scripts/check_site.py                 # site
```

The `BoundaryPins` digest test must stay green without editing the pin — the
four pinned files are untouched.

## Out of scope, and why

* **The `workflow_server.py` Host/Origin gap.** The 2026-10-31 review found
  that `workflow_server` validates neither `Host` nor `Origin` and does not
  require a `Content-Type` (`work_runtime/workflow_server.py:1780-1809`),
  while its sibling `ui_server.py:191-225` enforces exactly that. The review's
  own false-positive filter dropped it (confidence 7): nothing in the
  repository starts `workflow_server.serve()` outside the test suite, blind
  CSRF cannot complete without a rebinding step, and the module documents a
  reachability-based trust boundary. It is a **hardening item, not a
  confirmed vulnerability**, and it is recorded as TD-2 in D5 rather than
  silently fixed here — it deserves its own slice, because the guard has to be
  designed against a real launcher.
* **The participants assignment map.** Once only the owner may bind, the
  owner's own `participants` map is legitimate. No separate change.
* **`publish_template`.** Publication is a host authoring act and creates no
  binding; with D1 in place, an unauthorized publication still cannot reach a
  work. No change.

## Risks and the honest residual

* A work whose owner is `None` (a legacy work) keeps the grant-only rule:
  any principal holding `work.manage` may bind it. This is the runtime's
  existing `_manager` semantics, unchanged, and it is what the replay path
  already enforced.
* The fix does not change the trust model: principal names are configuration,
  not authentication (`docs/runtime-boundaries.md` §"Trust model and scope").
  It restores the one boundary the code itself claimed and did not enforce.
* The identity of the *publisher* of a template is still recorded but not
  authority-checked. That is unchanged and is not part of this defect.
