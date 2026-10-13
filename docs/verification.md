# Verification coverage

Updated: 2026-10-13 (S2 signed evidence and content publication) · Maintained by the contributor waves; behavior evidence lives in the named test files below.

This report states what the local reference prototype actually verifies, and what it explicitly does not. Coverage below refers to the acceptance matrix in [RFC-003 §9](RFC-003-runtime-protocol.md); it is not a claim that RFC-001 or RFC-002 as a whole is implemented.

## Scope of the verified system

- A **local, single-process reference prototype**: an in-process Python library over SQLite. There is no server, no remote protocol transport, and no multi-tenant authorization; protocol commands are library calls.
- **Local trust, not authentication.** Actor names (`agent`, `finance`, …) come from a grants map supplied by the embedding application. They distinguish trusted local principals; they do not authenticate remote callers. RFC-003 §2.1 (identity from trusted connections) is deferred. The S2 signed ingress (`work_runtime/ingress.py`) authenticates *evidence sources* with per-source HMAC keys within a configured shared-key boundary — it is not transport security, tenant authorization, or proof of business truth, and the reserved `accepted` receipt kind cannot be supplied through it. Direct Runtime methods remain trusted-local.
- **The external systems are stand-ins.** `FakeOA` is a separate local SQLite database modeling an external service with idempotent submit, lookup, and invoice uniqueness; `FakePublisher` likewise models a publishing service with idempotent submit, lookup, and one artifact per `(document id, content digest)`. No real external system integration exists yet. Adapter contracts are declared claims for trusted local configuration, not remotely verified guarantees.
- **One policy per runtime database.** The expense and content-publication domains run the same `Runtime` class in separate databases; policy migration is out of scope.
- **Concurrency model**: SQLite serializes command submission across multiple `Runtime` instances sharing one work database (verified by concurrent duplicate-command tests), while operation dispatch assumes a single coordinator. Distributed worker leases are not implemented (P13 below).

## How to verify

```bash
python3 -m unittest discover -s tests -v          # tests gate (all cases below)
python3 scripts/check_docs.py                     # contracts gate (local doc links)
python3 -m work_runtime demo                      # demo gate (real crash recovery)
python3 -m work_runtime publish-demo              # demo gate (signed-evidence publication)
python3 -m compileall -q work_runtime tests scripts  # syntax gate
python3 scripts/verify_install.py                 # fresh-venv install + demos outside the checkout
```

## Protocol acceptance matrix (P01–P15)

Definitions: [RFC-003 §9](RFC-003-runtime-protocol.md). All evidence tests are in `tests/test_runtime.py` (the 35 baseline tests); the S1 runtime wave additionally pins the dispatch/reconciliation boundary guarantees in `tests/test_boundaries.py` ([runtime boundaries](runtime-boundaries.md)).

| Case | Injected condition | Status | Evidence |
|---|---|---|---|
| P01 | Same command arrives concurrently | covered | `test_duplicate_commands_concurrently_have_one_receipt` — 4 threads, identical receipts, exactly one `OperationPrepared` event |
| P02 | Same command ID, changed parameters | covered | `test_changed_content_with_same_command_id_rejected` — `COMMAND_ID_REUSED` |
| P03 | Two plan revisions from the same state version | partial | `test_conflicting_plan_revisions_use_compare_and_swap` — sequential two-command CAS proof only; genuinely concurrent plan revisions are not separately tested |
| P04 | Receipt lost, command resent | partial | `test_duplicate_commands_concurrently_have_one_receipt`, `test_rejected_command_replay_remains_rejected` — resend returns the original receipt; transport loss is simulated by re-invocation, not a dropped socket |
| P05 | Same submission re-proposed under a new command ID | covered | `test_new_command_same_business_operation_reuses_identity` — same Operation identity; two dispatches → exactly 1 accepted OA application |
| P06 | Crash between intent commit and dispatch | partial | `test_prepared_intent_survives_restart` — recovery is exercised through a clean restart, not a crash injected at that exact point; real process deaths are injected for P07 and P15 |
| P07 | External success, local result lost to a crash | covered | `test_actual_process_crash_after_external_commit` — worker subprocess exits 73 after the OA commit; recovery queries the same business key; still exactly 1 accepted application |
| P08 | Approval arrives before the wait is registered | covered | `test_early_approval_and_duplicate_callback_do_not_lose_wakeup` — stored event triggers the wait; duplicate callback is a no-op |
| P09 | Old-version approval and duplicate callbacks | partial | `test_existing_invoice_proof_reused_after_document_change` — an approval bound to the old document digest no longer satisfies E05 after the content changes (obsolete-approval invalidation); `test_conflicting_source_event_preserves_original` — same event ID with different content is a `SOURCE_EVENT_CONFLICT` (source conflicts); `test_late_event_does_not_reopen_closed_work` (callbacks cannot resurrect closed work). These are local subsets: obsolete-approval invalidation, source conflicts and closed-work callbacks are tested separately; the complete P09 scenario (duplicate delivery of one approval event against arbitrary version relations) is not exercised as a whole |
| P10 | Plan revision deletes the approval step | covered | `test_missing_approval_cannot_be_deleted_with_plan` — the E05 obligation survives; submission blocked |
| P11 | Authority revoked after acceptance, before dispatch | covered | `test_authority_revoked_before_dispatch_holds_intent` — dispatch held, zero external calls |
| P12 | `request_completion` without acceptance evidence | covered | `test_completion_needs_business_evidence` (E08 blocker), `test_timeout_after_commit_then_reconcile` (`OUTCOME_UNRESOLVED` until reconciled) |
| P13 | Worker lease expires while an old call still runs | **deferred** | Requires distributed leases/fencing with external enforcement. The prototype has a single local coordinator; no distributed lease semantics are implemented or claimed, and no distributed exactly-once guarantee is asserted. Planned under roadmap 0.4. |
| P14 | Amount unknown / invoice set not closed | covered | `test_unknown_amount_blocks` (`APPLICABILITY_UNRESOLVED`), `test_empty_and_unsealed_invoice_sets_block` (E01 pending blocks submission) |
| P15 | Evaluation process crashes after evidence adoption | covered | `test_verification_crash_rolls_back_adoption_and_evaluation`, `test_real_process_death_during_evidence_adoption` — real `os._exit(74)`; re-evaluation succeeds after restart |

Net: **local subsets of 14 protocol cases have named-test evidence, with partial coverage or caveats on P03, P04, P06 and P09; P13 is explicitly deferred.** Single-process recovery (restart, subprocess death) is real; "crash" never means an exception was caught and ignored.

## S2 coverage — signed evidence, adapter contracts, content publication

The S2 wave added three foundations with their own gate-visible evidence:

- **Signed evidence ingress** (`tests/test_ingress.py`, real Runtime behind the gateway): strict envelope schema and JSON-native strictness; HMAC-SHA256 known-answer vector; every signed field's tampering, cross-source impersonation and unknown sources rejected with zero intake writes; freshness boundaries incl. boolean timestamps; exact replay, timestamp refresh under a new command id, and cross-work `SOURCE_EVENT_CONFLICT`; reserved `accepted` kind refused after authentication; signed success stays `pending_verification` until `verify_pending`. Boundary and key-handling guidance: [signed-evidence.md](signed-evidence.md).
- **Adapter contracts and policy-owned receipts** (`tests/test_adapter_contract.py`, `tests/adapter_conformance.py`): receipt validation matrix; frozen declared contracts; reusable conformance mixin adopted over disposable fixtures (same-key replay → one effect; same key/different content → `ValueError` without a new effect; lookup authoritative by key); declared-capability preflight holds unsupported operations with zero attempts/calls; malformed or present-`None` descriptors fail closed before external calls; missing accepted-source configuration fails closed in dispatch/reconcile/resolve. See [adapter-contract.md](adapter-contract.md).
- **Content publication domain** (`tests/test_publishing.py`, 42 tests): document strictness (`requires_review` bool or None); per-kind evidence shapes incl. `accepted` = `{digest, external_id}`; C02 applicability true/false/unknown with unknown blocking (`APPLICABILITY_UNRESOLVED`); digest-bound approval/confirmation and publisher-source-only accepted proofs; plan revision cannot remove review; content revision invalidates prior approval/confirmation and cancels stale intents; conformance mixin adopted for `FakePublisher` with `(document id, digest)` artifact uniqueness (duplicate identical content under another key reuses the external id; changed content adds a version); malformed adapter results quarantined per isolated fixture with the real `execute` asserted; timeout-after-commit recovered by lookup without resend; deterministic demo (`publish-demo`) asserted end-to-end incl. an independent `SELECT COUNT(*) FROM publications` = 1 and the printed `inspect --policy content-publish` command.

The publication harness integrates the common command protocol without credentials; it is not a claim of integration with any model framework or server. The installed verifier additionally runs `publish-demo` outside the checkout and counts the publications table independently.

## RFC-001 acceptance behaviors (R1–R7)

R1 restart/persistence — `test_prepared_intent_survives_restart`, `test_wait_expiry_survives_restart`, P07/P15 tests. R2 plan edits cannot delete requirements — P10 test. R3 unknown conditions block — P14 tests. R4 timeouts are not failures — `test_timeout_after_commit_then_reconcile`, `test_unknown_without_query_result_requires_attention` (no query result → `needs_attention`, no blind retry). R5 content change invalidates old confirmations — `test_existing_invoice_proof_reused_after_document_change`, `test_invoice_revision_invalidates_old_verification`, `test_unknown_old_content_blocks_new_submission`. R6 duplicate/late callbacks — P08/P09 tests. R7 no success without goal evidence — P12 tests.

## SOP example rules and review cases (E01–E08, T01–T12)

The demonstration policy turns most of rules E01–E08 from [RFC-002 §4](RFC-002-sop-authoring-and-binding.md) into executable checks (`work_runtime/policy.py`): set-closedness (E01), per-invoice validity (E02), cross-work uniqueness via the external stand-in (E03, `test_external_uniqueness_across_works`), unknown-amount blocking (E04), over-limit approval (E05), content-bound confirmation (E06), and acceptance evidence before closure (E08). E07 (original invoices must not be rewritten) is only **partially enforced**: the demo capability allowlist grants no invoice-write capability at all, so protected fields are excluded by construction rather than by an independently evaluated check. Of the review judgments T01–T12, the ones mirrored by named tests include T02/T07 (P14 tests), T05 (E05/confirmation invalidation tests), T09 (P10 test) and T10 (P07/P12 tests); the remaining judgments are still desk reasoning in [reference scenarios](reference-scenarios.md). The rule-card publication process itself (RFC-002 §6) is **not implemented**.

## Explicitly out of scope

- Remote or multi-tenant authentication and authorization (local principal names only).
- Policy/SOP publication, migration tooling and author review workflow.
- Evidence revocation workflows, cancellation and compensation (`request_cancel` is rejected explicitly: `test_unsupported_command_explicitly_rejected`).
- Distributed execution: worker leases, fencing, cross-node coordination (P13).
- Any real external system adapter; `FakeOA` is a local demonstration.
- General natural-language rule formalization.

## Related

- [Runtime boundaries](runtime-boundaries.md) — transaction and dispatch boundary internals, produced by the parallel S1 runtime work and integrated with this document in the S1 carrier. Before that integration this link was the one recorded pending link in the contracts gate; with both branches assembled the gate requires zero broken links.
- [Adapter contract](adapter-contract.md) — declared adapter metadata, receipt validation and the reusable conformance mixin.
- [Signed evidence](signed-evidence.md) — ingress trust model, envelope semantics, replay handling and key guidance.
- [RFC-001](RFC-001-core-semantics.md) · [RFC-002](RFC-002-sop-authoring-and-binding.md) · [RFC-003](RFC-003-runtime-protocol.md) · [Reference scenarios](reference-scenarios.md) · [Roadmap](roadmap.md)
