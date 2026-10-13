# S2 foundation integration report

Date: 2026-10-13. Session: Claude Code release-control session acting as independent S2 foundation
integration session (Orca dispatch `task_569a5b4d610b`). Carrier:
`/Users/jiangwei/orca/workspaces/governed-agentic-work-runtime/sprint-s2-trusted-boundaries`,
branch `WayJ/sprint-s2-trusted-boundaries`. Scope: foundation integration only — no S2 acceptance,
no main merge, no push, no carrier removal; the publication wave and final release are later tasks.

## Inputs reviewed against the merge base

All three source branches fork at `7dd96a3` (verified); every review diff is base→branch, so no
inherited-policy rollback misconception applies.

| branch | merged tip | content |
|---|---|---|
| `WayJ/s2-release-control` | `8fc97fc` | builder design-review report (this session's earlier dispatch) |
| `WayJ/s2-adapter-contract` | `5af1adc` | Foundation A: `4da9e16` behavior+docs, `88a73d6` plan/report, `5af1adc` review-correction fix |
| `WayJ/s2-signed-evidence` | `711851b` | Foundation B: `dfd81f3` signer, `078e8ce` gateway, `d3a4862` surrogate fix, `7d21109` docs/report, `711851b` cyclic-data fix |

Carrier pre-merge tip `67a926a` carries master's D8 decisions (`32de295`), ADR-table pin (`b54b1d7`)
and D9 publication pin (`67a926a`); D8/D9 authority was binding throughout, and both developer
reports confirm coding against the carrier D8 copy, not the stale local `7dd96a3` spec.

### Integration-sequence note (process, recorded for transparency)

My first merge pass (design review + original tips `88a73d6`/`7d21109`) completed before I read
master's WAIT message (msg_97b691f9a0a8, 10:19:31Z) announcing owner follow-ups. On processing it I
reset the carrier to `67a926a` (nothing had been pushed; the interim merges existed only locally),
verified master's three findings against the original tips, and held until master's go
(msg_94217db51221, 10:26:56Z) confirmed corrected tips `5af1adc`/`711851b`. All merges in the final
carrier were then made from the corrected tips.

### D8 conformance (code-level review, `git diff 7dd96a3..<branch>`)

- **B1** — `record()` catches `TypeError/ValueError/RecursionError` around envelope opening +
  canonicalization → `EVIDENCE_ENVELOPE_INVALID` (lone-surrogate UTF-8 and cyclic/deep-nesting
  cases both pinned); unknown source, wrong key, wrong signature → `EVIDENCE_AUTHENTICATION_FAILED`;
  validly-signed out-of-window → `EVIDENCE_EXPIRED`; schema precedes authentication (test-pinned);
  `sign_evidence` raises `ValueError` for bad key/shape/canonicalization/cycles, returns a detached
  copy (repeated acyclic references detach too), never mutates input; JSON-native strictness rejects
  NaN/±Inf, tuples, sets, non-string keys; `max_age` nonnegative int (bool rejected); keys distinct
  bytes ≥32, copied at construction.
- **B2** — `_accepted_source()` raises `CommandError` on missing/non-string/empty accepted source;
  called in `dispatch` before attempt/external call, in `reconcile` before querying (after the
  terminal no-op early return), in `_resolve` before adopting a receipt (slightly stricter than
  D8's letter — also guards rejected results — developer-disclosed, conservative, transactional,
  pinned via a mid-flight config break).
- **B3** — mixin checks metadata invariants only; capability exclusion lives in the domain test
  files; malformed descriptor → `CommandError` before any external call; **only an absent
  `contract` attribute is legacy** — a present `None` or an incomplete `AdapterContract` instance
  (`object.__new__` bypass) fails closed (`valid_contract` returns `False` on `AttributeError`,
  `_declared_contract` uses a `_MISSING_CONTRACT` sentinel).
- **M1** — reserved `accepted` kind refused with `EVIDENCE_KIND_UNSUPPORTED` *after*
  signature+freshness even for a granted key-configured source; duplicate key material across
  sources → `ValueError` at construction.
- **M2/M3/M4/M5** — replay/conflict semantics and preflight ordering implemented and test-pinned;
  M5's PublishingPolicy side correctly untouched (publication wave).

Ownership footprints match the spec exactly and are disjoint (Foundation A: adapter_contract.py,
runtime.py, adapters.py, 2 test files, 2 docs; Foundation B: ingress.py, 1 test file, 1 doc; no
Runtime changes). No unowned edits found in either diff.

### Independent RED verification (isolated `/tmp` base checkouts; no user worktree touched)

- Base `7dd96a3` + adapter tests only → `ModuleNotFoundError` (matches reported Task-1 RED).
- Base + `adapter_contract.py`/`adapters.py` + tests with the **original** `runtime.py` → exactly
  the 10 reported behavior failures (6×B2, 4×B3) with 17 characterization pins green — the
  `runtime.py` change is what turns them green; no vacuous GREEN.
- Base + ingress tests only → import RED (matches cycles 1/2).
- **Correction fixes independently RED-verified on the original tips**: new DescriptorPresenceTests
  over `88a73d6` → `FAIL` (present-None, CommandError not raised) + `ERROR` (incomplete instance,
  AttributeError); new cyclic/deep-nesting tests over `7d21109` → 2 errors (RecursionError instead
  of ValueError). Corrected tips green in isolation: adapter branch 90 tests, ingress branch 103.

## Merges (this session owns all merges; master merged nothing)

Clean `ort` merges from `67a926a`, zero conflicts (disjoint file sets): `16256b9` (design-review
report), `cfc2e3a` (adapter foundation, corrected tip `5af1adc`), `dfa2de5` (signed-evidence
foundation, corrected tip `711851b`). D8/D9 spec/roadmap content untouched; the merge diffs are
purely additive over `67a926a` plus the two owner fixes. No integration-owned doc corrections were
needed. Sprint Wave-1 checkboxes were deliberately left for master's acceptance flow.

## Gates on the merged carrier (run in the carrier worktree)

| gate | result |
|---|---|
| `python3 -m unittest discover -s tests` | **130 tests OK** — matches master's expected 63+27+40 exactly |
| `python3 -m work_runtime demo` | all 6 steps; crash recovery; `external applications created: 1` |
| `python3 scripts/check_docs.py` | 27 markdown files, 84 local links, **0 broken** |
| `python3 -m compileall -q work_runtime tests scripts` | clean |

## Targeted verification matrix (master's checklist → named green tests on the assembled carrier)

- Receipt policy source non-oa: `test_policy_owned_accepted_source_is_adopted` (source `oa-gateway`,
  no `oa` row, E08 satisfied, completion accepted).
- Unknown-source/auth failure zero writes: `test_unknown_source_has_no_key_and_fails_authentication`,
  `test_cross_source_key_cannot_impersonate`, `test_every_signed_field_tampering_fails_authentication`
  (each asserts all six runtime tables unchanged).
- Reserved accepted kind + shared key config: `test_reserved_accepted_kind_is_refused_after_authentication`,
  `test_short_non_bytes_or_duplicate_key_material_is_invalid`, `test_key_map_is_copied_at_construction`.
- Unsupported/None descriptor conditions: `test_unsupported_declared_capability_holds_with_zero_attempts_or_calls`,
  `test_present_none_descriptor_fails_closed_before_external_call`,
  `test_incomplete_contract_instance_is_invalid_and_fails_closed`,
  `test_absent_descriptor_keeps_legacy_dispatch`, `test_legacy_adapter_without_contract_still_dispatches`.
- Detached signed payload / ValueError cycle handling: `test_input_message_is_never_mutated_and_envelope_is_detached`,
  `test_repeated_acyclic_references_sign_and_detach`,
  `test_rejects_self_referencing_data_with_value_error`,
  `test_rejects_excessively_deep_nesting_with_value_error`,
  `test_cyclic_or_deeply_nested_envelope_data_is_envelope_invalid`.
- Authentic business vs no-intake rejection distinction: `test_source_grant_refusal_follows_runtime_persistence`
  (persisted rejection receipt) vs `test_source_without_grants_is_rejected_without_writes` and every
  pre-intake failure test (zero writes) — exactly the D8 clarification.
- Reusable conformance evidence: `FakeOAConformanceTests` (5 mixin tests) green.

**Cross-foundation end-to-end (independent, throwaway fixture):** present-`None` contract →
`CommandError`; gateway-signed approval recorded pending → verified → local evidence → dispatch →
policy-owned accepted receipt (`oa` for expense) → `request_completion` accepted with exactly one
external effect.

## Findings (none blocking; no product code patched by this session)

1. Developer reports cite their own final docs commits by pre-amend hashes (`49331f4`, `9fdb883`);
   the reachable commits are `88a73d6` and `5af1adc`. Cosmetic self-reference inaccuracy; all other
   hashes and claims verified exact.
2. `tests/test_adapter_contract.py` places `if __name__ == "__main__": unittest.main()` mid-file;
   harmless under `discover` (the configured gate) and the shimmed invocations. Cosmetic.
3. Developer-disclosed, design-consistent behaviors accepted: reconcile-only path does not re-check
   the adapter descriptor (lookup only, never an effect); validly-signed unknown `work_id` raises
   `CommandError` (trusted-local semantics, zero writes, pinned and documented).
4. Timing side channel between unknown-source (fast reject) and known-source (HMAC) paths is out of
   scope for a local shared-key prototype boundary; noted for the record only.

## Verdict and handover

Both foundations are implemented per D8, independently RED-verified including the correction fixes,
merged conflict-free from the master-confirmed corrected tips, and fully green on the assembled
carrier at the merge commits above plus this report's commit. **The publication dispatch should
branch from the merged carrier tip (including this report's commit). Real interfaces for the
publication worker:** `work_runtime.adapter_contract.AdapterContract` / `receipt_is_valid` /
`valid_contract` (module-path import; not re-exported from `work_runtime`), the
`AdapterConformanceMixin` in `tests/adapter_conformance.py` (import via the existing try/except
shim), policy `evidence_sources["accepted"]` fail-closed semantics, `work_runtime.ingress` for the
demo, and the D9 publication pins (FakePublisher schema, `inspect --policy`, publisher.sqlite,
installed verification). S2 acceptance, main merge, push and carrier cleanup remain open for the
final integration task after the publication wave.
