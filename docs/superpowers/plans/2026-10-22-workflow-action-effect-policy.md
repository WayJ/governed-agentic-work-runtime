# Action-node effect policy — a pinned, opt-in second effect for a new subject revision

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:executing-plans to
> implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Let an action node produce a *second* external effect for a **new
revision of its subject**, when — and only when — the published definition
opts in explicitly and the previous effect is settled. The default stays
**one effect per node**.

**Why:** A host integration needs its automatic draft save to run again after
a human rejected the first draft and the agent genuinely reworked the
proposal. Today `_effect_already_applied` blocks *every* later attempt of the
node once an effect happened, so the controlled rework has no way to produce
the new version.

**Architecture:** the policy is **data in the published definition**, not
engine configuration: an action node may declare `effect_policy`. The
definition is linted, digested, published immutably and pinned by digest at
binding, so the opt-in is explicit, versioned and auditable. The engine
evaluates it in `_start_action`, before any operation is proposed: the
previous attempts of the node are read from the store, and a new effect is
admitted only when every previous effect of the node is *settled* and the
new subject is a **new revision with a new digest** of the same object. The
admission then goes through the ordinary proposal path, so the runtime
creates an actual **new operation with a new business key**; the new node
instance stores that operation id, and the old business key keeps resolving
through `action_context`.

**Tech Stack:** Python >= 3.9, standard library only, `unittest`. No runtime
dependency is added.

**Files:** `work_runtime/workflow_spec.py` (the definition language),
`work_runtime/workflow.py` (the engine), `tests/test_workflow_effect_policy.py`
(the new focused tests), `docs/workflow-runtime.md`,
`docs/runtime-boundaries.md`, `docs/verification.md`.

**Frozen:** `work_runtime/runtime.py` and `work_runtime/adapters.py` stay
byte-identical. The engine reads the operation rows it needs; it never
changes the runtime.

## The API (final)

| name | value | meaning |
|---|---|---|
| node field | `effect_policy` | only allowed on an `action` node |
| value | `"once"` | the default: the node's effect happens once; a later attempt never repeats it |
| value | `"per_revision"` | a later attempt may produce a new effect for a **new revision with a new digest** of the node's subject, after the previous effect is settled |
| lint | `NODE_EFFECT_POLICY_UNKNOWN` | the value is not one of the two |
| lint | `NODE_EFFECT_POLICY_ATTEMPTS` | `per_revision` without `max_attempts >= 2` can never open a second attempt |
| bind | `WORKFLOW_EFFECT_POLICY_UNKNOWN` | the pinned definition declares a policy this engine does not know |
| engine | `WORKFLOW_EFFECT_ALREADY_APPLIED` | the previous effect happened for the **same** subject (same revision and digest) |
| engine | `WORKFLOW_EFFECT_SUBJECT_UNCHANGED` | the subject revision is new but its digest is not — the content did not change |
| engine | `WORKFLOW_EFFECT_UNRESOLVED` | a previous operation of the node is unknown, in flight or never settled: it must be reconciled before a new write |
| engine | `WORKFLOW_EFFECT_OUTPUT_INVALID` | a previous effect succeeded but its output failed validation: it is not bypassed by a new subject or a manual retry |

## The exact semantics of `per_revision`

For attempt *N* of an action node with subject *S* (the pinned
`{name, revision, digest}`), every earlier attempt of the same node that
proposed an operation is examined:

1. the operation row is missing, or its status is not terminal
   (`prepared`, `dispatched`, `outcome_unknown`) → **deny**
   (`WORKFLOW_EFFECT_UNRESOLVED`): the outcome must be reconciled first, and
   nothing is written.
2. the operation is `confirmed_failed` → no effect happened → it does not
   constrain the new attempt.
3. the operation is `confirmed_succeeded`:
   * the attempt did not complete with a validated output →
     `WORKFLOW_OUTPUT_INVALID` → **deny** (`WORKFLOW_EFFECT_OUTPUT_INVALID`);
     any other unsettled state → **deny** (`WORKFLOW_EFFECT_UNRESOLVED`).
   * the attempt completed → the subject is compared with the subject the
     effect was produced for:
     * same revision and same digest → **deny**
       (`WORKFLOW_EFFECT_ALREADY_APPLIED`);
     * a newer revision with a different digest → **admit**;
     * anything else (same digest, or not newer) → **deny**
       (`WORKFLOW_EFFECT_SUBJECT_UNCHANGED`).

After the admission the engine proposes through the ordinary path and
verifies that the operation it received is **not** an operation this node
already used: the new attempt must own a new operation id and a new business
key. Otherwise the attempt fails closed.

Everything else stays as it is: the node's declared input and output
validators, the required independent review, the order dispatch, the final
close and the `action_context` linkage rules (the node is never inferred from
the capability or from the work's cursor).

## Tasks

- [ ] **T1 — the definition language.** `effect_policy` on an action node,
      the two lint codes, the docs of the field. RED: the lint tests.
- [ ] **T2 — the engine.** The admission in `_start_action`, the four denial
      codes, the new-operation verification. RED: the engine tests.
- [ ] **T3 — the real path.** Agent proposal v1 → automatic draft v1 →
      human rejection → reworked and independently reviewed proposal v2 →
      automatic draft v2 → human A/B approval → one formal final action:
      two version drafts, one final effect, the original receipt retained.
- [ ] **T4 — the negative paths.** The default node is unchanged; the same
      digest under a new revision is denied; an unknown prior effect is not
      rewritten; a failed output is not bypassed; both business keys resolve
      after a restart; an invalid or unknown policy is refused at
      publication and at binding; a pinned template cannot be changed under
      the same version.
- [ ] **T5 — the docs.** `docs/workflow-runtime.md` (the field, the codes,
      the exact semantics), `docs/runtime-boundaries.md` (the boundary row),
      `docs/verification.md` (the W-matrix rows and the test list).
- [ ] **T6 — the review and the final suite.** An independent read of the
      diff against this plan, then one full `python3 -m unittest discover -s
      tests -v` run.

## Global Constraints

- Python >= 3.9, zero runtime dependencies, standard-library `unittest` only.
- `work_runtime/runtime.py` and `work_runtime/adapters.py` stay
  byte-identical.
- No UI change, no merge, no push: this worker only commits.
- The names in the core are generic (`once`, `per_revision`); no domain
  vocabulary enters the engine.
- TDD: a meaningful failing test, the observed failure, the minimal
  implementation, the rerun, and recorded RED/GREEN evidence.

## Review Focus

1. **The default must not move.** A node without the policy keeps exactly
   the `WORKFLOW_EFFECT_ALREADY_APPLIED` behaviour, byte for byte.
2. **A settled effect is not the same as a validated effect.** An effect
   whose output failed validation is not bypassed, and an operation that was
   never reconciled is never written over.
3. **A new subject is not a new effect.** The subject comparison is on the
   revision *and* the digest of the same object, never on the capability and
   never on the cursor.
4. **The new admission is a real operation.** The new attempt owns a new
   operation id and a new business key, and the old key still resolves.
