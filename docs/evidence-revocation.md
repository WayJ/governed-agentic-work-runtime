# Evidence revocation

This document is the reference for the trusted-local `revoke_evidence`
command and the permanent `revoked` proof status in
`work_runtime/runtime.py` (ratified design D33–D37). It rides the ordinary
command protocol — compare-and-swap on `expected_version`, durable
deduplication under `(actor, command_id)`, immutable receipts and the
append-only event history. Everything here is trusted-local: principal names
and grants are configuration, **not authentication**. Machine-level dispatch
and recovery guarantees live in [runtime-boundaries.md](runtime-boundaries.md);
the intervention commands live in [interventions.md](interventions.md).

## Intent and boundary

A business proof can cease to authorize future actions while its original
source event, verification decision, already accepted external effects and
all historical receipts remain traceable. Revocation changes **current
validity**; it never edits history and never compensates an external effect.

Out of scope (unchanged): external fencing of an in-flight call (the residual
race of RFC-001 §5.2 stands), compensation/reversal execution, distributed
exactly-once claims, and the privileged accepted-source event-id collision
recorded as TD-1 in the [tech debt tracker](tech-debt-tracker.md).

## Command

`Runtime.command(actor, command_id, work_id, "revoke_evidence", payload,
expected_version)` with payload exactly `{source, event_id, reason}` — three
nonempty strings. `source`/`event_id` identify the stored proof row
(globally keyed `(source, event_id)`); `reason` is recorded in the event.
Malformed fresh payloads raise `CommandError` (API misuse) and persist
nothing. The command is version-bound like every kind except
`create_work`/`record_evidence`: stale use is `STATE_VERSION_CONFLICT`
before any work happens. Ordinary command fingerprinting, cached-receipt
precedence and `COMMAND_ID_REUSED` are unchanged.

It is routed beside `record_evidence`, before the closed-work guard, so it
is accepted on closed works, on unbound (establishing) works and while a
cancellation intent is active — the evidence lifecycle keeps running under
cancellation.

## Authority

- A `work.intervene` administrator, **or**
- the actor who is the work's **currently configured source for the stored
  proof's kind** (per the work's pinned policy) **and** holds the
  `evidence.revoke` grant.

Work ownership, `work.manage` and `evidence.write` alone grant no revoke
right. The current source may correct an old-source candidate of the same
kind; a source retired by a policy migration loses the right as soon as the
pinned mapping changes. Administrators still obey scope, status and version
checks.

For commands whose target row does not exist, authority is checked
conservatively **before** any lookup (administrator, or `evidence.revoke`
plus membership in the pinned policy's configured source set), so an
unauthorized caller cannot probe evidence existence through decision codes.

**Replay reauthorization.** A stored receipt — accepted or rejected —
replays only while the same authority still holds: the replay branch
re-runs the identical predicate (for accepted receipts the stored kind is
available because rows are never deleted; for cached unknown-proof
rejections the same conservative preliminary check as admission applies — a
cached rejection never acquires mutation rights). A replay after authority
loss returns a fresh, unpersisted `AUTHORITY_DENIED` with the currently
observed state version; the stored receipt is never modified.

## Decisions

| condition | receipt |
|---|---|
| malformed payload | `CommandError` (nothing persisted) |
| stale `expected_version` | `STATE_VERSION_CONFLICT` |
| authority failed | `AUTHORITY_DENIED` |
| no row `(source, event_id)` | `EVIDENCE_UNKNOWN` |
| row belongs to another Work | `EVIDENCE_SCOPE_MISMATCH` |
| status already `revoked` | `EVIDENCE_ALREADY_REVOKED` |
| status `invalid` (or other) | `EVIDENCE_NOT_REVOKABLE` |
| status `pending_verification` or `verified` | accepted |

An accepted receipt is `{"command_id", "decision": "accepted",
"result_state_version": <the single new Work version>, "evidence_id",
"evidence_status": "revoked", "prior_status"}`.

## Effect — one transaction

1. The proof row's body is **updated in place**, changing only `status` to
   `"revoked"`; `id`, `source`, `event_id`, `kind`, `data` and the
   source-event fingerprint column are preserved byte-for-byte. Rows are
   never deleted — permanence depends on it.
2. Current requirements are recomputed (the policies select proofs by
   `status == "verified"`, so a revoked proof stops satisfying rules by
   construction).
3. The Work's `state_version` bumps exactly once and exactly one
   `EvidenceRevoked` event is appended.

An exception anywhere inside the transaction (including an injected fault)
rolls back the proof update, the Work row and the event together; a real
process death mid-transaction leaves the previous state byte-identical.

### Event fields

`actor, evidence_id, source, event_id, kind, prior_status, reason,
work_was_closed, completion_cites_evidence, affected_requirements,
wait_dispositions`

- `affected_requirements` — the **actual** per-requirement diffs of the
  re-evaluation (`{id, before, after}` with applicability/fulfillment), not
  a hard-coded assumption. A second sufficient proof keeping the rule
  satisfied yields an empty list.
- `wait_dispositions` — `{id, prior_status, status, disposition}` for every
  stored wait, `disposition` being `"unchanged"` or the new status. These
  record what the evaluator really did: a historical `triggered` wait is
  never demoted when its rule becomes pending, `cancelled`/`expired` waits
  are terminal, deadlines are never reset, and a wait cannot be *newly*
  triggered by a revocation (every path that satisfies a rule already ran
  the evaluator, so a wait on a satisfied rule was already triggered).

## Closed-work correction

On a closed Work, revocation keeps `status`, `outcome` and the `completion`
snapshot byte-identical — there is no implicit reopen and no automatic
`needs_attention`. Correction is visible in current data only: the revoked
proof status, the recomputed requirements (the affected rule shows
`pending`) and the `EvidenceRevoked` event, whose `work_was_closed` and
`completion_cites_evidence` flags distinguish the historical decision from
current validity. `completion_cites_evidence` is true only when the
completion snapshot's evidence citation list really contains the revoked
proof id; a cancellation completion acknowledges operations, never evidence
citations, and none are invented.

Unbound works may be revoked (their proofs already admit and verify
unbound); since the S8 D-1 fix, a finalized unbound work keeps its `closed`
status under later evaluation. That fix guards new transitions only:
already-persisted erroneous snapshots from before the fix are not rewritten
retroactively — this is a recorded limit, not a silent migration.

## Waits, prepared intents and external effects

Revocation performs **no eager wait or operation mutation**:

- The next `dispatch`/`recover` re-runs the blockers and holds the prepared
  intent with `REQUIREMENT_UNSATISFIED` — zero attempts, zero external
  calls.
- A fresh replacement proof (new event id from the currently configured
  source, carrying the policy-required current digest) re-admits the same
  operation under the same business key.
- In-flight and outcome-unknown operations keep their attempts, business
  key and results and reconcile normally; their confirmation writes a **new**
  accepted proof under the operation id. Revoking the accepted proof of a
  confirmed operation never re-executes it and never regenerates the proof:
  re-proposal returns the confirmed operation unchanged and the retained
  external effect stays counted exactly once. Revocation is not
  compensation.

## Permanence and replacement

- `verify_pending` adopts only `pending_verification` candidates and policy
  migration revalidates only `verified` ones, so a revoked row is skipped by
  both; restart and `recover()` never revive it.
- Old-command replays return their stored receipts verbatim. A **new**
  `record_evidence` command resending the same source event returns the
  existing `evidence_id` plus the candidate's **current**
  `evidence_status` (verified/invalid/revoked/pending_verification) — no new
  row; changed content is still `SOURCE_EVENT_CONFLICT`.
- The runtime never synthesizes a replacement accepted proof: replacement
  acceptance is a new acceptance event from the accepted source or a new
  operation under new content.

## Verification

`tests/test_evidence_revocation.py` (plus the D-1 pair in
`tests/test_interventions.py`):

| guarantee | tests |
|---|---|
| malformed/stale/authority matrix incl. retired source | `test_malformed_payloads_raise_and_persist_nothing`, `test_stale_version_is_rejected_before_any_work`, `test_owner_and_write_grant_alone_cannot_revoke`, `test_current_source_and_admin_may_revoke`, `test_retired_source_loses_revoke_right_after_migration` |
| decision codes and eligibility | `test_unknown_evidence_is_rejected`, `test_cross_work_evidence_is_scope_mismatch`, `test_double_revoke_is_already_revoked`, `test_invalid_proof_is_not_revocable`, `test_pending_and_verified_are_both_revocable` |
| atomicity and preservation | `test_accepted_receipt_and_atomic_single_version_single_event`, `test_revocation_preserves_candidate_identity_and_fingerprint` |
| admin scope/status/version obedience, unbound/cancellation allowance | `test_admin_obeys_scope_status_and_version`, `test_revoke_allowed_on_unbound_work`, `test_revoke_allowed_during_active_cancellation` |
| event dispositions | `test_event_has_exactly_the_ratified_fields_with_real_diffs`, `test_partial_revocation_with_second_sufficient_proof_changes_nothing`, `test_revoked_rule_keeps_historical_trigger_without_demotion_or_reset`, `test_unrelated_waiting_wait_is_untouched_by_revocation` |
| closed-work correction | `test_revoked_accepted_on_closed_work_preserves_completion`, `test_revoked_approval_on_cancelled_closure_never_invents_citations`, `test_revocation_on_unbound_closed_work_keeps_closure_stable` |
| replay reauthorization | `test_replay_returns_stored_receipt_verbatim_without_new_writes`, `test_replay_with_changed_content_is_command_id_reused`, `test_replay_after_revoke_grant_loss_denies_without_mutating_receipt`, `test_replay_after_admin_grant_loss_denies`, `test_replay_after_source_retirement_denies`, `test_cached_unknown_rejection_replays_verbatim_after_proof_exists`, `test_cached_unknown_rejection_replay_after_authority_loss_denies` |
| permanence and replacement | `test_revoked_pending_proof_cannot_verify_later`, `test_restart_and_recover_never_revive_revoked_proof`, `test_migration_records_revoked_disposition_and_keeps_it`, `test_resend_under_new_command_reports_current_status`, `test_resend_of_invalid_proof_reports_invalid`, `test_resend_with_changed_content_is_source_event_conflict`, `test_original_record_command_replay_stays_verbatim`, `test_replacement_proof_restores_rule_under_new_event`, `test_confirmed_operation_never_reruns_to_regen_accepted_proof` |
| waits terminality | `test_cancelled_wait_stays_terminal_across_revocation`, `test_expired_wait_keeps_state_and_deadline_without_reset` |
| dispatch hold / readmission / blocks (expense) | `test_prepared_intent_holds_at_dispatch_with_zero_attempts_and_calls`, `test_recover_holds_prepared_intent_with_zero_calls`, `test_replacement_readmits_same_operation_key_and_dispatches_once`, `test_proposal_blocked_after_revoking_approval`, `test_completion_blocked_after_revoking_accepted_evidence`, `test_inflight_operation_reconciles_after_revocation_with_one_effect` |
| publishing family | `test_revoked_approval_blocks_publication_admission`, `test_prepared_publication_holds_with_zero_published_artifacts`, `test_replacement_readmits_and_publishes_exactly_once`, `test_closed_publication_correction_preserves_completion`, `test_publishing_permanence_across_resend_and_restart` |
| crash atomicity | `test_revoke_transaction_exception_rolls_back_everything`, `test_real_process_death_inside_revoke_rolls_back`, `test_external_death_then_revoke_reconciles_one_retained_effect` |
| D-1 closed guard | `test_finalize_cancel_on_unbound_work_persists_closed`, `test_unbound_closed_work_stays_closed_under_late_verification_and_recovery` |

## Demonstration and installed verification

The no-credentials `revocation-demo` runs the behaviors above end to end on
fresh stores in both policy families (`work_runtime/revocation_demo.py`;
tests in `tests/test_revocation_demo.py`):

```bash
python3 -m work_runtime revocation-demo        # module entry point
work-runtime revocation-demo                   # installed console entry point
```

- **Scenario A (expense, store `hold/`)** — a verified finance approval is
  revoked by its current source; re-proposal is rejected
  `REQUIREMENT_UNSATISFIED`, the prepared intent is held at dispatch with
  zero attempts and zero external calls, the revoke command replays
  verbatim, a resend of the same source event reports
  `evidence_status "revoked"` with the same evidence id, and a replacement
  approval under a new event id re-admits the SAME operation on the same
  business key (`test_hold_store_shows_revoked_approval_readmission_and_single_call`).
- **Scenario B (expense, store `uncertain/`)** — a dispatch that loses its
  response after the external commit is reconciled by the original business
  key (exactly one retained effect, never resent); the confirmed acceptance
  is then revoked by an administrator and the approval by finance, after
  which re-proposal returns the already-confirmed operation unchanged
  (never re-executed) and completion stays blocked on both revoked proofs
  (`test_uncertain_store_retains_one_effect_with_two_revoked_proofs`).
- **Scenario C (publishing, store `publish/`)** — a revoked reviewer approval
  holds publication with zero artifacts, a replacement approval re-admits
  the same operation, the work closes succeeded, and the administrator's
  revocation of the acceptance preserves the completion byte-identically
  while C04 turns pending and the resend reports `revoked`
  (`test_publish_store_closed_correction_preserves_completion`).

Every printed count is asserted in-module against the adapters, and the
final line — `3 scenarios; retained external effects: 2 accepted
applications, 1 published artifact; effects reversed: 0` — is a counted
fact: revocation never reverses an accepted effect.

`scripts/verify_install.py` stages 13–14 run the module and console
`revocation-demo` entry points outside the checkout in a fresh install and
verify them independently of the printed text: each of the three stores is
parsed directly — evidence statuses, source-event fingerprints recomputed
locally (the acceptance fingerprint still matches the original verified
acceptance, proving only the status changed), the stable business key of
the single readmitted operation recomputed from the policy family and
document identity, the closed completion still citing the revoked
acceptance, and exactly one retained external effect per store
(`VerifyInstallRevocationProofTests`, including rejection paths for
tampered stores).
