# Report — the material an output validator is given

Task `task_0cde8b8d3db6`, dispatch `ctx_3203a6fa25e7`.
Branch `WayJ/gawr-mixed-node-design`, baseline `647033c`.

## What was built

| id | deliverable | outcome |
|---|---|---|
| M1 | `work_runtime/workflow.py` — the additive `materials` context key for output validator callbacks, resolved from the attempt's own pinned references | shipped |
| M2 | `tests/test_workflow_materials.py` — 17 tests, written before the implementation | shipped |
| M3 | docs — `docs/workflow-runtime.md` (§1: the validator API, the exact schema and the limits), `docs/verification.md` (W101–W108) | shipped |

## The behaviour, in one paragraph each

**A shape cannot prove coverage.** A structural shape proves the *form* of
an output; it cannot prove that the output covers the input it was
produced from — whether every identifier of the pinned input appears,
exactly once, in the output. That comparison needs the input itself, so an
**output** validator now receives it: the context (`node_ref`) gains one
additive key, `materials`.

**The schema.** `materials` is an ordered list; every entry is
`{role: "input"|"subject", reference: {name, revision, digest}, object:
<the exact full stored object>}`. The inputs come first, in the order the
node pinned them, and the subject last. The `object` is the full stored
body of that exact revision — the engine never truncates it.

**The rules the engine keeps.** The entries are resolved from the
**attempt's own references** — the inputs it pinned and the subject it
holds — and never from the latest revision of an object: a node judges the
material it was given. They are read in the **same transaction** as the
judgement, and each stored body is verified against the digest its
reference names. A missing, unreadable or corrupt reference fails closed
with a specific `WorkflowError`: the list is never partial, never
truncated and never silently shortened. The work the callback receives is
an **isolated copy** and the materials are **deep copies**, so a validator
that changes what it is given cannot change the stored work, the stored
instance or a stored object.

**The four kinds.** The agent candidate, the human record, the automatic
output and the waited material each receive it. The input admission path
keeps its current context and its current API. The context is not exposed
in any HTTP read model; it never leaves the callback.

**A node that pins no input** compares against its protected subject: the
material carries the subject the node decided on, so a record that does not
cover it is refused — and, as the engine has always done, the decision
itself is never lost: the record is refused, the decision stands and the
node keeps waiting.

**What did not change.** The freeze, the compare-and-swap, the command
idempotency and the action side-effect semantics are untouched, and
`work_runtime/runtime.py` and `work_runtime/adapters.py` are byte
unchanged by this slice. An output that fails its check **after** an
effect still keeps the real effect and fails closed: the effect stays
recorded as `succeeded`, the node fails with `WORKFLOW_OUTPUT_INVALID`,
and the effect is never produced a second time.

## RED/GREEN evidence

| step | RED | GREEN |
|---|---|---|
| the new tests | `tests/test_workflow_materials.py` (17 tests) run against the pre-change core (`git checkout -- work_runtime/workflow.py`): **16 of 17 failed** — the context carried no materials, so the coverage validator had nothing to compare and every identifier case was accepted or mis-reported | `PYTHONPATH=.:tests python3 -m unittest test_workflow_materials` → **17 tests, OK** |
| the workflow suites | — | the workflow suites plus the finalization file and the new file → **278 tests, OK** |

The one test that passed at RED is the one that must keep passing: a
refused automatic output keeps the real effect (`WORKFLOW_OUTPUT_INVALID`,
one effect, never repeated) — that behaviour predates this slice.

No full repository run was repeated: the previous full run (1412 tests, OK)
is already recorded, and this slice touches the workflow engine only.

## The coverage validator of the fixture

The core stays domain-neutral. The fixture registers a generic validator:
every identifier of the pinned input must appear exactly once in the
output. It refuses an unknown identifier (`COVERAGE_UNKNOWN_ID`), a
missing one (`COVERAGE_MISSING_ID`) and a repeated one
(`COVERAGE_DUPLICATE_ID`).

## The pinned revision, not the latest

The runtime's own revision path supersedes the node that pinned an object,
so the fixture writes the newer revision straight into the store — the way
a concurrent writer would. The attempt keeps the revision it pinned, and
the material carries it: a candidate that covers the pinned identifiers is
accepted, and a candidate that covers the *latest* identifiers is refused.

## Remaining boundaries

* The material is available to **output** validators only; the input
  admission path keeps its current context and its current API.
* The context is rebuilt for every output judgement, so a validator that
  keeps a reference to it must copy what it wants to keep.
* The `object` is the full stored body: the engine never truncates it, so
  a node with large inputs hands a large context to its validator. The
  host that registers the validator decides what it accepts.
* A missing or corrupt pinned object fails closed with an exception, not
  with a business refusal: in a command path the caller sees a server
  fault (the store is corrupt), and in a settlement path the advance
  failure is recorded durably and the node keeps waiting. Nothing is
  stored and no effect is repeated.
* The acceptance, the canonical proof and the generic-completion guard of
  the earlier slices are untouched.
