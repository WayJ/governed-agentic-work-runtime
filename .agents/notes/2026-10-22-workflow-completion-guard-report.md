# Report — the generic-completion guard and the canonical proof

Task `task_c60421167133`, dispatch `ctx_c0c4e0cba15b`.
Branch `WayJ/gawr-mixed-node-design`, baseline `058de69` (the acceptance
slice: `bb140b8`, `530c7ad`, `058de69`).

## What was built

| id | deliverable | outcome |
|---|---|---|
| G1 | `work_runtime/runtime.py` — the disclosed, additive, family-neutral guard: `request_completion` refuses a workflow-bound work that carries no accepted finalization | shipped |
| G2 | `work_runtime/workflow.py` — `WorkflowEngine.finalization_canonical(snapshot)`: the canonical text of an accepted proof, verified against the stored digest | shipped |
| G3 | `work_runtime/workflow_server.py` — the completion read answers `finalizationCanonical`, and refuses instead of emitting an unreduced or redacted proof | shipped |
| G4 | `tests/test_workflow_finalization.py` — 12 new tests (37 in the file) | shipped |
| G5 | docs — `docs/runtime-boundaries.md` (the disclosed exception with the digests), `docs/workflow-api-contract.md`, `docs/workflow-runtime.md`, `docs/verification.md` (W94–W100) | shipped |

## The two changes, in one paragraph each

**The generic completion may not close an unfinalized workflow.** The
generic `request_completion` sees the requirements and the operations of a
work, but not the workflow's terminal, its quality or its effects — so on a
workflow-bound work it closed the work *without* the workflow proof, which
is exactly the bypass the acceptance exists to close. The guard is three
lines in `Runtime._apply`: a work that has a workflow binding and no
accepted finalization is refused with `WORKFLOW_ACCEPTANCE_REQUIRED`. Both
facts are read from the **stored work**, so the refusal survives a restart
and holds in a process that carries no workflow engine at all — an
in-memory hook would have left the same bypass open behind a restart
(`test_a_bare_runtime_over_the_same_store_still_refuses_it`). A work
without a workflow keeps its previous completion path exactly
(`test_an_ordinary_work_still_completes_the_generic_way`), the refusal is an
ordinary stored receipt, and the generic completion stays refused after the
acceptance (`WORK_NOT_ACTIONABLE`, one finalization, one
`WorkflowFinalized` event).

**The completion read carries the canonical text of the proof.**
`GET /v1/workflows/instances/{workId}/completion` now answers with
`finalizationCanonical`: the canonical JSON of the finalization **without
its `digest` entry**. Its SHA-256 over UTF-8 is exactly the digest the
acceptance recorded, and parsing the text yields exactly the finalization
without its digest entry — a reader never has to reimplement this canonical
form. The text is emitted only when the stored proof needs no redaction
(`redact(snapshot) == snapshot`) **and** the stored digest still matches
the stored content. Otherwise the read refuses and emits neither the text
nor a hash of a redacted proof: `409 WORKFLOW_COMPLETION_PROOF_UNAVAILABLE`
(the proof carries something that looks like a credential) and `409
WORKFLOW_COMPLETION_PROOF_UNVERIFIED` (the proof does not match its own
digest). The native command receipt is unchanged: it carries the snapshot
and no canonical text.

## RED/GREEN evidence

| step | RED | GREEN |
|---|---|---|
| the new tests | the 12 new tests run against the pre-change core (`git checkout -- work_runtime/runtime.py work_runtime/workflow.py work_runtime/workflow_server.py`): **10 of them failed** (6 failures, 4 errors) — the generic completion *accepted* an active workflow-bound work, an unfinalized finished one and a bare-runtime one (`{'decision': 'accepted', 'result_state_version': 6}`), the completion read carried no canonical text, and `finalization_canonical` did not exist (`AttributeError`). The two that passed are the two that must keep passing: the ordinary completion and the refusal after the acceptance | `PYTHONPATH=.:tests python3 -m unittest test_workflow_finalization` → **37 tests, OK** |
| the completion-path suites | — | the 14 suites that exercise `request_completion` (`test_runtime`, `test_interventions`, `test_publication*`, `test_publishing`, `test_support`, `test_evidence_revocation`, `test_accepted_evidence_collision`, `test_adapter_contract`, `test_boundaries`, `test_inspection`, `test_revocation_viewer`, plus the finalization file) → **496 tests, OK** |
| the workflow suites | — | `test_workflow_engine`, `test_workflow_http`, `test_workflow_recovery`, `test_workflow_review`, `test_workflow_effect_policy`, `test_workflow_node_quality`, `test_workflow_action_context`, `test_workflow_authority`, `test_workflow_participants`, `test_workflow_create_resume`, `test_workflow_demo` → **224 tests, OK** |
| the gates | — | `python3 -m compileall -q work_runtime tests scripts` clean; `python3 scripts/check_docs.py` → 127 files, 682 links, 0 broken; `python3 scripts/check_site.py` → 2 pages, 0 findings |

The whole suite was **not** re-run: the previous full run (1412 tests, OK)
is already recorded, and this slice is an additive wire change plus one
guarded command; the focused suites above cover every path the change
touches (every suite that calls `request_completion`, plus every workflow
suite).

## The frozen files

| file | SHA-256 before | SHA-256 after |
|---|---|---|
| `work_runtime/runtime.py` | `19555fcfe1e602ae6598d5ef7392536c3bc19171129686516c53fcda63d8c7ac` | `1b9c73e639ffa9a6facf3d092c07c12e4cf84639c0d2ea8ccecce14b6cb3d075` |
| `work_runtime/adapters.py` | `ce132f24d84c17a083bcf0b61bf90e1c62ff75faf2ec52fe2c7348ab86b6985e` | unchanged |

The `runtime.py` edit is the coordinator-approved exception, disclosed in
`docs/runtime-boundaries.md` with the digests: one guard in the
`request_completion` branch, no other line of the lifecycle touched, and
the behaviour of a work without a workflow is bit for bit the previous one.

## The exact wire format

`GET /v1/workflows/instances/{workId}/completion` → `200`

```json
{"workId": "W-1",
 "finalization": {"finalizationId": "…", "…": "…", "digest": "<sha256 hex>"},
 "finalizationCanonical": "{\"finalizationId\":\"…\",\"…\":\"…\"}"}
```

* `finalizationCanonical` = `policy.canonical(finalization without "digest")`
  = `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
  allow_nan=False)`.
* `SHA-256(finalizationCanonical encoded as UTF-8)` == `finalization.digest`.
* `json.loads(finalizationCanonical)` == `finalization` without its `digest`
  entry.
* Non-ASCII is emitted as itself (never `\uXXXX`); a float keeps Python's
  form (`1e+30`).

Refusals: `404 WORKFLOW_NOT_FINALIZED` (no acceptance), `404 WORK_UNKNOWN`
(no such work), `409 WORKFLOW_COMPLETION_PROOF_UNAVAILABLE` (the stored
proof needs redaction — no text and no hash are emitted), `409
WORKFLOW_COMPLETION_PROOF_UNVERIFIED` (the stored proof does not match its
digest).

The native command receipt is unchanged:
`{command_id, decision, result_state_version, finalization}` for an
acceptance, `{command_id, decision, code, observed_state_version,
blockers}` for a refusal.

## Remaining boundaries

* The acceptance is a **trusted-local** decision: the runner is a principal
  in the grants map, not an authenticated identity.
* `request_completion` is refused on a workflow-bound work, so such a work
  is closed **only** by `finalize_workflow_success`. A host that wants a
  different success path for a workflow-bound work must add one in the
  engine, not in the generic lifecycle.
* The canonical text is emitted only for a proof that needs no redaction; a
  proof with a credential-like field is deliberately unreadable in full
  (`WORKFLOW_COMPLETION_PROOF_UNAVAILABLE`) rather than readable in part.
* The snapshot stays bounded (64 objects, 64 nodes) and names revisions and
  digests, never bodies.
* The idempotency of the acceptance is the runtime's own: the receipt
  replays under `(actor, commandId)`, and the generic completion's refusal
  is a stored receipt like every other.
