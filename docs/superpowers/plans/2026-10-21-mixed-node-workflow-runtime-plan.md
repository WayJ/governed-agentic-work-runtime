# Mixed-node workflow runtime — scoped implementation plan (CANDIDATE)

Status: **CANDIDATE — not an execution instruction.** No phase below starts
until the coordinator ratifies the companion design
[2026-10-21-mixed-node-workflow-runtime-design.md](../specs/2026-10-21-mixed-node-workflow-runtime-design.md)
and allocates sprint ids; the master owns epic/sprint allocation, dispatch
and acceptance. This plan exists so the design review can judge scope,
sequencing and blast radius. It assumes the working agreement: TDD for all
behavior changes (meaningful failing test → observed RED → minimal
implementation → GREEN, evidence recorded), Python ≥ 3.9, stdlib only,
zero runtime dependencies, work only in the assigned checkout, and the
doc-sync map debts below.

Freeze-gap note: phases 3–5 edit `work_runtime/runtime.py`, which the S15
verdict froze. That edit is the design's disclosed freeze-gap finding; the
first phase that touches the file must record the before/after SHA-256 in
its sprint evidence, and `docs/runtime-boundaries.md` gains the workflow
boundary sections in the same commit.

## Phase map

| phase | deliverable | owns (new) files | edits existing? | acceptance rows |
|---|---|---|---|---|
| 1 | workflow spec language + static lint + digest (pure functions) | `work_runtime/workflow_spec.py`, `tests/test_workflow_spec.py` | no | W24 |
| 2 | named objects + shape validation + `revise_object` | runtime additive paths, `tests/test_workflow_objects.py` | yes (additive) | W25, W20 |
| 3 | binding, node instances, `advance` core, wait/approval nodes | runtime additive paths, `tests/test_workflow_advance.py` | yes (additive + admission-helper refactor) | W01, W02, W06, W07, W08, W13, W14, W16 |
| 4 | action nodes + runner principal + machine proposals + recovery ordering | runtime, `tests/test_workflow_action.py` | yes | W09–W12, W15, W21, W23 |
| 5 | agent nodes + executor protocol (`submit_node_result`, task outbox) | runtime, `tests/test_workflow_agent.py` | yes | W04, W05, W11 |
| 6 | interactions: cancel/revise/migrate/revoke composition sweeps | `tests/test_workflow_interactions.py` | yes (mostly composing) | W03, W17–W19, W22 |
| 7 | demo family + truth docs + installer/CI stages | `work_runtime/workflow_demo.py`, docs, `scripts/verify_install.py` stage | docs + scripts only | end-to-end + W20 |
| 8 (separate wave) | read-only GUI additive reads | `work_runtime/inspection.py`, web assets | yes (per DESIGN.md + browser evidence rules) | W26 |

Phases 1–2 are independently valuable and lowest-risk; phase 3 is the
irreversible commitment point (first runtime edit + storage addition) and
the natural review gate; nothing in 4–6 makes sense to reorder across 3.

## Phase 1 — spec language, lint, digest (pure, no runtime edits)

- TDD: write `tests/test_workflow_spec.py` first — exact-schema diagnostics
  (unknown/missing fields, non-DAG cycle, dangling node/executor/kind
  references, bad predicate operators, depth/integer/unicode preflight
  parity with `authoring.py`), clean-spec digest stability, key-order
  neutrality. RED before any implementation; record evidence.
- Implement `work_runtime/workflow_spec.py`: JSON-native preflight,
  exactly-N diagnostic codes (count decided by the test set; document them
  like the 14-code table in `docs/sop-authoring.md`), three-valued
  predicate evaluator `eval_predicate(spec, state) -> true/false/unknown`,
  `validate_shape(descriptor, value) -> list[finding]`, `workflow_digest`.
- No CLI, no store, no runtime import. Gates: full suite, compileall,
  check_docs. Doc debt: none yet (module ships user-invisible in this
  phase); `docs/workflow-runtime.md` starts in phase 7 or earlier at the
  master's choice.

## Phase 2 — named objects (additive store, additive command)

- TDD: `tests/test_workflow_objects.py` — `revise_object` happy path
  (append-only revisions, canonical digest, `ObjectRevised` event,
  `state_version` bump), malformed payloads raise `CommandError` with
  nothing persisted, CAS `STATE_VERSION_CONFLICT`, reserved name
  `"document"` read-only bridge resolves to the work document's current
  revision/digest, non-workflow works byte-identical (W20), schema stays
  additive under `metadata.schema_version = "1"` (U9 assumption; flip the
  tests if the master chooses a bump).
- Implement: `objects` table in the constructor script, `revise_object`
  command branch, replay-authority entry (`_manager`), reads on
  `get_work`/snapshot. Admission helpers untouched.
- Evidence: before/after SHA of `runtime.py` recorded (freeze-gap ledger).

## Phase 3 — binding, node instances, advance core (the commitment point)

- Refactor first, behavior-preserving: extract the admission/re-evaluation
  helpers `_propose`/`_evaluate`/`_save` call graph so a trusted-local pass
  can call the same code the `command()` path calls (no duplicate logic).
  The existing suite is the regression net — zero behavioral edits.
- TDD: `tests/test_workflow_advance.py` — W01 determinism (two passes,
  zero writes), W02 unknown-blocks, W06 approval-exact-digest, W07 early
  arrival, W08 disapproval branch, W13 wait timeout, W14 early event,
  W16 conditional routing; `bind_workflow`/`revise_workflow` family and
  lint rejections (`WORKFLOW_FAMILY_MISMATCH`, `WORKFLOW_SPEC_INVALID`,
  already-bound/unchanged); node instance lifecycle events and version
  bumps; `advance` inside `recover` ordering; approval/wait nodes only
  (agent results submitted by hand in tests through the phase-5 command
  shape, stubbed).
- Implement: `node_instances` table, workflow binding fields, `advance`
  pure router + transactional persistence, generalized wait match,
  `_evaluate` extension for runnable/waiting/blocked status.

## Phase 4 — action nodes, runner, machine proposals

- TDD: `tests/test_workflow_action.py` — W09 policy blockers hold with
  zero external calls, W10 authority hold, W11 crash-after-commit → one
  effect, W12 response loss → reconcile, W15 parallel branches, W21
  restart + idempotent recover, W23 machine-command replay; object-bound
  operations (staleness against the object binding, business-key
  extension, `OPERATION_CONTENT_CONFLICT` parity); compensation-family
  non-interference (a compensation proposal path untouched).
- Implement: runner proposal path reusing `_propose`, deterministic
  command ids `wf:<id>:<node>:<attempt>`, object-bound operation fields,
  dispatch/recover integration, receipt→object adoption with shape
  validation.

## Phase 5 — agent nodes, executor protocol

- TDD: `tests/test_workflow_agent.py` — W04 validator rejection persisted
  with validator id/version + bounded findings, W05 dedup/reuse, task
  outbox atomicity (activation + task one transaction), executor authority
  (`workflow.execute` + configured name), deadline escalation,
  `max_attempts` fresh-attempt ids, cancelled-task marker visibility.
  Validator-binding pins per design §4.1: structural shape checks;
  registered business-rule cross-field validators (pure
  `validate_output`, version-pinned); provenance checks route through
  verified evidence/digest equality, never payload text; executor
  self-certification attempts never accepted (a result plus the agent's
  own "validated: true" claim is still only validator-admissible);
  failed validation blocks completion and downstream routing with no
  object revision; an unregistered or wrong-version validator id fails
  closed at bind time.
- Implement: `submit_node_result` command, task outbox records, executor
  read surface (task listing on the work snapshot), the registered
  validator interface (host-configured registry, id+version resolution,
  pinned binding recorded on the node instance).

## Phase 6 — interaction sweeps

- TDD: `tests/test_workflow_interactions.py` — W03 object-revision
  supersession, W17 cancellation, W18 revise-with-uncertain-operation,
  W19 migration + fail-closed version pinning, W22 revocation re-opens an
  approval node. Mostly composing existing interventions with the router;
  each test must count external effects and assert stored truth, not
  return values.

## Phase 7 — demo, truth docs, packaging

- New small demo family (U14 decision recorded) exercising one workflow of
  each node kind end-to-end with a real worker crash chapter, on fresh
  stores; `work_runtime/workflow_demo.py` + CLI subcommand mirroring the
  existing demo harness style; installer stage in
  `scripts/verify_install.py` counting external effects independently.
- Truth docs in the same commits (doc-sync): new
  `docs/workflow-runtime.md` (spec schema, lint codes, predicate
  semantics, advance boundary, failure table), updates to
  `docs/runtime-boundaries.md` (advance boundary, machine identity layer,
  freeze-gap SHA record), `docs/verification.md` (W-matrix with named
  tests), `CONTRIBUTING.md` structure table, README/README.zh-CN entries,
  AGENTS.md doc-sync rows for the new modules (master's ledger).

## Phase 8 — GUI additive reads (separate UI wave)

Per the working agreement: read DESIGN.md first, token-based additions
only, browser evidence at desktop/390px/320px, loading/empty/error states,
no lifecycle writes from the reader. `ReadOnlyInspector` gains node/object
reads (W26); any timeline visualization keeps pastels confined to real
stored node state.

## Cross-phase rules

- Every phase: RED/GREEN evidence in the sprint report; side effects
  counted against the external stand-in stores; existing 1132-test
  baseline (plus later phases' additions) stays green; five gates run.
- New rejection codes only as persisted business rejections; `CommandError`
  stays malformed-input-only.
- No timers, threads, leases or background processes anywhere; `now` is a
  parameter.
- One policy family per database still holds; the workflow demo runs in
  its own store.
- Honest-coverage rule: the W-matrix in `docs/verification.md` records
  partial/deferred rows exactly like the P-matrix does today; nothing is
  marked covered without a named test.

## Risk register

| risk | mitigation |
|---|---|
| Admission-helper refactor destabilizes the frozen surface | behavior-preserving extraction gated by the untouched existing suite; review-list the diff; record SHA transition |
| `advance` re-derivation cost grows with graph size | per-work finite DAG, lint-bounded predicates; measure in phase 3 tests; no cross-work global pass |
| Predicate unknowns silently default to false | three-valued evaluator with W02 pinning block-on-unknown; no negation (U6) |
| Scope creep toward a generic graph engine | H3 stands: workflows stay optional organization; no generic-engine claim; every new capability needs a W-row |
| Schema drift breaks existing readers | additive-only tables under version "1" (U9); GUI compatibility asserted each phase |
| Machine proposals bypassing human review of payloads | runner holds only explicitly granted capabilities; every machine command is a stored receipt replayable by audit |
| Agent/model self-certification of outputs | acceptance flows only through host-registered, version-pinned validators (design §4.1); model self-assessment is never validation output; failed validation blocks completion and downstream routing |

## What this plan deliberately does not include

No multi-coordinator or lease work (P13 stays deferred); no network or
authentication additions; no LLM integration requirement (executors are
pluggable and deterministic in tests); no UI work before phase 8's own
wave; no migration of the three existing families to workflows; no commit
of this plan or the design doc before coordinator ratification.
