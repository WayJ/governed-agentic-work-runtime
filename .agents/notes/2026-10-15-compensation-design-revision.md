# Compensation design DRAFT v2 revision note — 2026-10-15

## Scope and evidence

Dispatched DRAFT-REVISION-ONLY task (task_7c99fb7cec45) on this
compensation-design checkout at tip `d683429` (clean). Master preliminary
choices received with the dispatch (explicitly **not** product implementation
authorization): expense-only active-cancellation scope; `propose_action`
current-owner+capability linked variant; alternative **B** (explicit opt-in
action/link execution context) with legacy three-positional-args adapter
behavior preserved. Inputs read as truth: the entire independent builder-check
report (copied verbatim to
[2026-10-15-compensation-independent-design-review.md](2026-10-15-compensation-independent-design-review.md),
source `00833d8` — copy verified byte-identical below its provenance header),
the candidate
[design](../../docs/superpowers/specs/2026-10-15-compensation-execution-design.md)
at `d683429`, its [recon](2026-10-15-compensation-design-recon.md), and the
product sources re-verified line-by-line at this SHA (`runtime.py`,
`policy.py`, `adapters.py`, `adapter_contract.py`, `ingress.py`, `demo.py`,
`cli.py`, `interventions.md`, `adapter-contract.md`, `verification.md`,
`runtime-boundaries.md`, `tests/adapter_conformance.py`,
`tests/test_adapter_contract.py`). This note and the revision implement
nothing, allocate no epic/sprint/ADR id, and mutate no ledger; ownership was
docs-only (spec revision, this note, the copied review).

## What changed

1. **Copied review** — `.agents/notes/2026-10-15-compensation-independent-design-review.md`
   (verbatim from `00833d8` + provenance header; diff-verified).
2. **Spec revision** — appended **DRAFT v2 (§14)** to
   `docs/superpowers/specs/2026-10-15-compensation-execution-design.md`
   (original v1 text and history preserved; one pointer sentence added to the
   Status block; supersession list §14.14 itemizes every overridden v1
   statement). The v2 section is the builder-ready amended public contract:
   - **§14.2 (F1/F2)**: `AdapterContract.supports_action_context: bool =
     False` (keyword-only constructions repo-wide verified → backward
     compatible; bool invariant added); opted-in
     `execute(key, document, content_digest, *, action=None,
     compensates=None)`; legacy adapters never receive kwargs — no
     introspection, no try/TypeError-after-effect; runtime passes explicit
     capability + runtime-validated immutable link; forward default action
     (`expense.submit`) for legacy direct FakeOA callers (kwargs default
     `None`); withdrawal without the context opt-in held **before**
     attempts/execute as `ADAPTER_ACTION_CONTEXT_UNSUPPORTED` even when
     `actions` claims withdraw; FakeOA-side wrong action/link guards; no
     document-field action selection; all four digest touchpoints stay as
     v1 drafted (current frozen work document/digest; binding only via the
     snapshot).
   - **§14.3 (F3)**: distinct runtime proof kind `withdrawn` (data
     `{digest, external_id, original_external_id}`) at the accepted source —
     never kind `accepted`, E08 can never be satisfied at any digest,
     including after S8 revocation of the original proof; **no** `withdrawn`
     evidence-source mapping (S9 reservation covers it automatically; no
     trusted imports — admission denies the kind for every actor;
     admin-only revocation; signed ingress unchanged); S9 conflict path
     preserves the actual result/kind, never a falsely-forward accepted
     proof; `AcceptanceProofConflict` name kept and clarified.
   - **§14.4 (F4/F5)**: per-key `receipts` (additive `action`/`link_digest`
     columns, explicit ALTER migration — ADAPTER-store evolution, runtime
     schema stays 1) + per-original `withdrawals(original_external_id PK)`;
     different-key/same-original alias rows under the requesting key with
     the requesting digest and same `WD-…` id; link fingerprint idempotency
     (same key + different target conflicts even with equal document
     digest); ORIGINAL external-id verification by store query (actual
     forward acceptance), never current-document inference; known-absent
     original = stored authoritative business rejection `ORIGINAL_ABSENT`
     (bounded, queryable); real lookup unavailability stays
     `outcome_unknown`; duplicate-invoice forward always rejected, no
     automatic withdraw branch by store state; `accepted_count()` = distinct
     forward-accepted external ids (zero-invoice edge verified: counter is
     receipts-based, not invoices-based), `withdrawn_count()` = effect rows.
   - **§14.5**: resolution-time link binding check (`original_external_id`
     must equal the snapshot) → `ADAPTER_RESULT_INVALID` quarantine, never
     false confirmation; `receipt_is_valid` unchanged (backwards
     compatible).
   - **§14.6 (F6)**: window exemption covers fresh **and** re-admission
     (single gate before the re-admission branch); full dispatch
     revalidation (link/grant/window/contract/plan/digest) with
     belt-and-braces branches; prepared/held dispositions and finalize
     exact-ack unchanged; failed withdrawal excluded from ack with explicit
     refusal-not-guaranteed-reversal description; `interventions.md`
     same-commit sentence owed.
   - **§14.7 (F7/F8 under B)**: single-adapter worker/CLI/`recover`
     byte-compatible; D18 dropped.
   - **§14.8–§14.9**: consolidated rejection-code precedence and stored-truth
     tables; `op.external_id` = `WD-…` while the snapshot keeps the original
     `OA-…` id.
   - **§14.10**: TDD matrix additions 16–27 (revision wrong/missing/multiple-
     invoice binding, forward duplicate, distinct-proof-never-E08 incl.
     revoked original, alias lookup different digest/key, link conflicts,
     legacy no-kwargs/false-marker held with zero effects, missing-target
     business failure vs uncertain true absence, re-admission/transfer,
     real-crash one-withdrawal/one-original counts, old-store migration,
     mixin preservation + opt-in coverage).
   - **§14.11–§14.13**: W1 core ownership (`adapter_contract.py` + mixin/
     tests + runtime/policy/adapters + same-commit boundary docs) then
     independent assembly and W2 demo/install — design text only; D1–D13
     confirmed/amended, review D14–D18 resolved, local D19–D24 introduced;
     remaining master ratification items listed explicitly.
3. **This note** (file 3 of 3).

## Verification on this checkout (post-revision)

All five AGENTS gates re-run green after the docs-only changes — contracts
(`check_docs.py`: spec links to the copied review resolve), tests (726 OK,
skipped=1, byte-untouched battery), syntax, site, demo. No product file
changed: `git status` shows only the three documentation paths.

## Handover / remaining master choices

Final ratification is still the master's, after the independent **second
review** of the amended contract: confirm the preliminary choices plus local
D19–D24 names/decisions (contract field name, hold code, `ORIGINAL_ABSENT`
receipt reason, no-`withdrawn`-source-mapping ruling, adapter-store
migration/counter semantics), the D11 residual wording, and the W1/W2
dispatch. No implementation is authorized by anything here.
