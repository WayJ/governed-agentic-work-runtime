# Verification coverage

Updated: 2026-10-15 (S9 core: accepted-source operation-id reservation and acceptance-proof collision recovery; S8 demo wave: revocation-demo harness, CLI entry point, installed module+console verifier stages; S8 core: evidence revocation command, permanent revoked status, D-1 unbound closed guard; S5 frontend/CLI slice: GUI sample seed, ui commands, packaged assets; S4 adoption: static SOP lint, file adapter, adoption harness) · Maintained by the contributor waves; behavior evidence lives in the named test files below.

This report states what the local reference prototype actually verifies, and what it explicitly does not. Coverage below refers to the acceptance matrix in [RFC-003 §9](RFC-003-runtime-protocol.md); it is not a claim that RFC-001 or RFC-002 as a whole is implemented.

## Scope of the verified system

- A **local, single-process reference prototype**: an in-process Python library over SQLite. There is no server, no remote protocol transport, and no multi-tenant authorization; protocol commands are library calls.
- **Local trust, not authentication.** Actor names (`agent`, `finance`, …) come from a grants map supplied by the embedding application. They distinguish trusted local principals; they do not authenticate remote callers. RFC-003 §2.1 (identity from trusted connections) is deferred. The S2 signed ingress (`work_runtime/ingress.py`) authenticates *evidence sources* with per-source HMAC keys within a configured shared-key boundary — it is not transport security, tenant authorization, or proof of business truth, and the reserved `accepted` receipt kind cannot be supplied through it. Direct Runtime methods remain trusted-local.
- **The external systems are stand-ins — plus one real local adapter.** `FakeOA` is a separate local SQLite database modeling an external service with idempotent submit, lookup, and invoice uniqueness; `FakePublisher` likewise models a publishing service with idempotent submit, lookup, and one artifact per `(document id, content digest)`. The S4 `FilePublisher` is a real effect, not a stand-in: one immutable hash-named JSON artifact per idempotency key on a trusted local directory. No remote or networked external system integration exists yet. Adapter contracts are declared claims for trusted local configuration, not remotely verified guarantees.
- **One policy family per runtime database, with an explicit version registry.** A runtime may additionally load same-family policy versions through the keyword-only `policies` registry; every Work stays pinned to its bound version (no implicit upgrade), a restart fails closed until the pinned version is loaded, and `migrate_policy` is the only explicit, transactional, evidence-revalidating migration path. Cross-family registries are rejected; the expense and content-publication domains still run the same `Runtime` class in separate databases.
- **Concurrency model**: SQLite serializes command submission across multiple `Runtime` instances sharing one work database (verified by concurrent duplicate-command tests), while operation dispatch assumes a single coordinator. Distributed worker leases are not implemented (P13 below).

## How to verify

```bash
python3 -m unittest discover -s tests -v          # tests gate (all cases below)
python3 scripts/check_docs.py                     # contracts gate (local doc links)
python3 -m work_runtime demo                      # demo gate (real crash recovery)
python3 -m work_runtime publish-demo              # demo gate (signed-evidence publication)
python3 -m work_runtime intervention-demo         # demo gate (transfer, cancel, migrate)
python3 -m work_runtime adoption-demo             # demo gate (lint + file-adapter adoption)
python3 -m work_runtime revocation-demo           # demo gate (evidence revocation, both families)
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

## S3 coverage — interventions, ownership and pinned policy versions

The S3 wave added the intervention lifecycle on the runtime (`tests/test_interventions.py`, foundation wave) and its demonstration surface (`tests/test_intervention_demo.py`, this wave). Semantics and boundaries: [interventions](interventions.md).

- **Cancellation with uncertain effects** (`request_cancel` / `finalize_cancel`): the intent is immutable once stored; waits and never-dispatched prepared intents are cancelled; an attempt already durable when cancellation is requested stays uncertain until queried (no external fence). Finalize refuses unresolved operations (`OUTCOME_UNRESOLVED`), requires the exact set of confirmed-succeeded operation ids (`CANCEL_ACKNOWLEDGEMENT_MISMATCH`) and stores every disposition plus external ids in the closure — acknowledgement, never reversal. Named: `test_cancel_before_dispatch_makes_zero_external_calls`, `test_finalize_after_timeout_requires_exact_acknowledgement`, `test_finalize_after_real_process_death` (real subprocess exit after the external commit), `test_missing_lookup_cannot_finalize`, `test_malformed_result_cannot_finalize`, `test_cancellation_survives_evaluation_expiry_and_recovery`.
- **Ownership transfer** (`transfer_owner`): the creator becomes the work's owner; transfer persists actor/old/new owner and reason, reassigns outstanding waits, invalidates prepared intents (`OWNERSHIP_TRANSFERRED`), and gates management mutations, proposals and dispatch on current ownership; stored receipts are replayed only while current authority holds, otherwise a fresh unpersisted `AUTHORITY_DENIED` is returned and the stored receipt stays intact. Owners and `work.intervene` administrators are trusted local principals, not authenticated identities; legacy ownerless works stay grant-only until an administrator adopts them. Named: `test_former_owner_loses_management_proposal_and_dispatch`, `test_intervention_replay_after_transfer_denied`, `test_new_owner_reproposes_same_operation_and_dispatches`, `test_in_flight_operation_survives_transfer_and_reconciles`, `test_legacy_ownerless_work_stays_grant_only_until_admin_adoption`.
- **Explicit same-family policy migration** (`migrate_policy` + constructor registry): the registry is validated before any filesystem/database write, including the default for any explicit dict (D16, `test_malformed_default_rejected_for_any_explicit_registry`); works stay pinned to their bound version and restarts fail closed until it is loaded (`test_missing_pinned_version_fails_closed`, `test_restart_without_pinned_version_fails_closed`); migration is administrator-only, refuses uncertain effects, revalidates every verified proof under the target policy — an old approval bound to demo-1 does not survive (`test_strengthened_rule_revalidates_approval_and_keeps_key`) — increments the actual contract revision and rolls back atomically on target failure (`test_migration_rolls_back_atomically_on_target_failure`); two works may be pinned to different versions of one family (`test_two_works_pinned_to_different_versions`). Business-key stability across same-family versions is a policy-author obligation, documented, not a runtime rewrite.
- **Demonstration surface** (`tests/test_intervention_demo.py`): the deterministic no-credentials `intervention-demo` runs the three scenarios on separate fresh stores with independently counted external effects — zero while an intent is only prepared or cancelled, exactly one accepted application per store after each external acceptance (`test_each_store_independently_holds_exactly_one_accepted_application`, `test_transfer_state_old_owner_denied_operation_preserved`, `test_cancel_state_closed_cancelled_with_retained_effect`, `test_migration_state_pinned_demo2_same_operation`); the printed `inspect` commands run verbatim, the migrated one carrying `--policy-versions demo-1,demo-2` (`test_printed_inspect_commands_run_correctly`); the strict `inspect --policy-versions` flag rejects empty, duplicate, unknown and cross-family inputs while the flag-free expense and content-publish defaults are pinned unchanged (`InspectPolicyVersionsTests`). The installed verifier runs module and console `intervention-demo` outside the checkout and, for both entry points, counts each scenario store independently — exactly three distinct, correctly ordered stores with exactly one accepted application each — and exercises the installed flag against the migrated store.

The P01–P15 matrix above is unchanged by this wave: intervention behaviors are deliberately not blanket-mapped onto protocol acceptance cases, and the matrix still names only its own evidence. Intervention commands travel the same deduplicating command path as every other command (`test_duplicate_cancel_commands_share_one_receipt`, `test_cancel_intent_is_immutable_and_replay_returns_original`), which is protocol machinery, not a new matrix row.

## S4 coverage — static SOP lint, file adapter, adoption harness

The S4 wave added two foundations (authoring, file adapter) with their own reviewed evidence — `tests/test_authoring.py` (146 tests: exactly-14 diagnostics, iterative preflight/SCC graph boundary, digest key-order neutrality) and `tests/test_file_adapter.py` (50 tests: conformance over real directories, corruption matrix, subprocess races and real process death) — and the dependent adoption surface in `tests/test_adoption_demo.py` (this wave). Semantics and boundaries: [SOP authoring](sop-authoring.md), [file adapter](file-adapter.md), [contributor guide](contributor-guide.md).

- **Strict `lint-sop` CLI loader** (`LintCleanTests`, `LintDefectTests`, `LoaderExit2Tests`, `SecretEchoTests`): exit 0 clean with the exact `{valid, digest, diagnostics, scope:"static-only"}` JSON envelope and pinned packaged-card digests; exit 1 for lint diagnostics incl. syntactically valid escaped-surrogate **values and keys** (`INVALID_UNICODE`), with JSON output ASCII-escaped so diagnostics can never crash stdout and human lines surrogate-safe; exit 2 for duplicate object keys (top-level and nested), `NaN`/`Infinity` literals, malformed JSON, invalid UTF-8 bytes, unreadable files/directories, files strictly over 1 MiB and unparseably deep nesting (caught `RecursionError`, no traceback) — with bounded static messages that never echo file contents or secrets (planted-marker tests). Exactly-1 MiB files still load (boundary pinned).
- **Packaged single-source cards** (`PackagedResourceTests`): `work_runtime/data/sop/{expense,publishing}.json` read via `importlib.resources.files`, lint-clean with the recorded digests; `pyproject.toml` ships them as package data, and a fresh non-editable install is verified below.
- **Adoption demo** (`ResponseLossWrapperTests`, `AdoptionDemoTests`, `AdoptionDemoHygieneTests`, `AdoptionCliTests`): the composition wrapper delegates to the real `FilePublisher` (contract surfaced, `TimeoutError` raised only after the durable commit); the demo blocks on C02, rejects a tampered signed approval before any intake write, keeps valid candidates pending until verification, commits exactly one hash-named artifact, recovers the lost response by reconciling the original business key after restart (one attempt, nothing resent) and closes the work `succeeded` — asserted against the artifact file itself, the runtime database and the printed `inspect`/artifact paths run verbatim. Fresh stores per run; parent-directory contents survive; runs work with the working directory outside the checkout.
- **Installed verification** (`scripts/verify_install.py` stages, exercised fresh per run): the packaged cards resolve inside the venv and the installed `lint-sop` reproduces the pinned digest; module AND console `adoption-demo` entry points run outside the checkout with the artifact directory independently enumerated (exactly one hash-named `.json`, zero `.stage` leftovers) and the artifact independently parsed with the standard library only — exact keys, `artifact_version` 1, key equal to the operation's business key, recomputed document digest, accepted `FILE-` receipt — plus the work read directly from SQLite as `closed/succeeded` and the printed inspect command re-run verbatim. CI additionally runs the exit-0/1/2 `lint-sop` trio.

The adoption harness adds no protocol matrix row: it reuses the same command/dispatch/reconcile machinery already covered above, on the unchanged Runtime and `PublishingPolicy`.

## S5 coverage — local operations GUI (frontend/CLI slice)

The S5 frontend slice added the five-work sample seed, the `ui`/`ui-demo` CLI surface and the offline bilingual browser assets (`tests/test_ui_demo.py`, `tests/test_ui_cli.py`). The read-only HTTP backend and the assembled browser verification belong to other owners/waves; this section states exactly what this slice verifies. Guide: [GUI](gui.md).

- **Sample seed** (`tests/test_ui_demo.py`, all assertions read stored SQLite truth directly): the five pinned works (`wait-1` waiting with pending-verification approval evidence and a persisted rejected proposal; `uncertain-1` needs_attention with `NO_AUTHORITATIVE_RESULT` while the external store retains its accepted effect; `transfer-1` owned by the delegate with the invalidated-then-readmitted operation confirmed; `succeed-1` closed/succeeded with completion; `cancel-1` closed/cancelled acknowledging the exact recovered external effect, not a reversal); unique invoice ids; real command history (events and command receipts persisted, including the cancel acknowledgement decision); exactly four accepted applications in the shared external store; hygiene — parent-directory contents survive, two runs create two distinct folders; the `UnavailableLookup` composition wrapper reports no authoritative result while the wrapped store keeps its committed receipt. No protocol matrix row: the seed reuses already-covered command machinery.
- **CLI serve surface** (`tests/test_ui_cli.py`): importing `work_runtime.cli` never imports the read-only backend (subprocess-isolated check), prior subcommands keep working without it; port out of range, missing database and directory-as-database exit 2 with bounded messages before any backend import; an install without the backend is a bounded exit-2 startup error (skip-guarded so it keeps passing once the backend is assembled); the serve lifecycle prints the actual loopback URL flushed, enters `serve_forever`, and on interrupt closes the server and exits cleanly (unit-tested with an interface-conforming stub server — a lifecycle test, not an HTTP claim).
- **Packaging and installed verification** (`scripts/verify_install.py`): the packaged web assets must ship inside a fresh install (always-on stage); the installed-UI HTTP stage — real subprocess `ui-demo`/`ui` runs outside the checkout, byte-equality of served assets, the five seeded works over the API, store tables byte-identical before/after serving, clean interrupt exit — executes only when the read-only backend module is part of the install and otherwise prints an explicit SKIPPED line that the final summary discloses. In this slice's checkout the backend is absent, so that stage's evidence is SKIPPED; its helper logic was additionally smoke-tested against a scratch stand-in server (not recorded as assembled verification).
- **Explicitly pending (assembled backend/browser verification, independent integration wave)**: real HTTP serving against the actual read-only backend, and actual browser behavior — desktop/narrow layout, bilingual toggle, keyboard navigation, filter/refresh/poll pause, stored-XSS non-execution, exact big-integer rendering, disconnected/error states and stale-response races in a real browser. No DOM mock or source-keyword test is recorded as browser coverage.



## S8 coverage — evidence revocation core

The S8 core wave added the trusted-local `revoke_evidence` command and the
permanent `revoked` proof status on the unchanged Runtime and both demo
policies (`tests/test_evidence_revocation.py`, 55 tests, plus the D-1 pair
appended to `tests/test_interventions.py`). Semantics and boundaries:
[evidence-revocation.md](evidence-revocation.md); the command rides the same
deduplicating command path as every other command, so no protocol matrix row
is added.

- **Command authority and codes (D33)**: exact `{source, event_id, reason}`
  payload (`CommandError` with nothing persisted on malformed input),
  version binding, admin/current-source-with-`evidence.revoke` authority
  (owner/`work.manage`/`evidence.write` alone denied), retired-source loss
  after a relabeling migration, `EVIDENCE_UNKNOWN`/`EVIDENCE_SCOPE_MISMATCH`/
  `EVIDENCE_ALREADY_REVOKED`/`EVIDENCE_NOT_REVOKABLE`, pending+verified
  eligibility, one-version/one-event/one-receipt atomicity with preserved
  candidate identity and source-event fingerprint. Named:
  `test_malformed_payloads_raise_and_persist_nothing`,
  `test_stale_version_is_rejected_before_any_work`,
  `test_owner_and_write_grant_alone_cannot_revoke`,
  `test_current_source_and_admin_may_revoke`,
  `test_retired_source_loses_revoke_right_after_migration`,
  `test_accepted_receipt_and_atomic_single_version_single_event`,
  `test_revocation_preserves_candidate_identity_and_fingerprint`.
- **Replay reauthorization and permanence (D33/D36)**: stored receipts
  replay verbatim while authority holds; grant/admin/source-retirement loss
  yields a fresh unpersisted `AUTHORITY_DENIED` with the stored receipt
  immutable; cached unknown rejections never acquire mutation rights;
  revoked proofs skip `verify_pending`, migration (revoked→revoked
  disposition) and restart/recover; new-command resends report the current
  `evidence_status` while original receipts stay verbatim and changed
  content stays `SOURCE_EVENT_CONFLICT`; replacement proofs use a new event
  id and confirmed operations never re-execute or regenerate their accepted
  proof. Named: the `RevokeReplayTests` and `RevokePermanenceTests` classes
  (test-name table in [evidence-revocation.md](evidence-revocation.md)).
- **Closure, waits, effects and crashes (D34/D35)**: actual
  requirement/wait dispositions in the single `EvidenceRevoked` event;
  closed bound (succeeded), cancelled-closure and unbound-closed correction
  with byte-identical completion snapshots and no invented citations; no
  cancelled/expired wait resurrection or deadline reset; prepared intents
  held at dispatch/recover with `REQUIREMENT_UNSATISFIED` and **counted**
  zero external calls in both families (expense `FakeOA` receipts,
  publishing `FakePublisher.published_count()`); replacement readmission on
  the same business key; in-flight reconciliation and confirmed-effect
  retention with exactly one effect; transaction-exception and real
  process-death rollback by store snapshot equality. Named: the
  `RevokeEventTests`, `ClosedWorkCorrectionTests`, `RevokeWaitsTests`,
  `RevokeDispatchTests`, `PublishingRevokeTests` and `RevokeCrashTests`
  classes.
- **D-1 fix**: `test_finalize_cancel_on_unbound_work_persists_closed` and
  `test_unbound_closed_work_stays_closed_under_late_verification_and_recovery`
  (both RED on the pre-S8 store: `establishing` != `closed`).

### S8 demo wave — demonstration and installed verification

The demo wave (this slice) added the public no-credentials demonstration
and the installed-verifier stages on top of the accepted core
(`tests/test_revocation_demo.py`, 12 tests; `work_runtime/revocation_demo.py`,
the `revocation-demo` CLI subcommand, `scripts/verify_install.py` stages
13–14; reference in [evidence-revocation.md](evidence-revocation.md)):

- **Deterministic scenarios on fresh stores**: three scenarios (expense
  hold/readmission, expense uncertain-retained-effect with two revoked
  proofs, publishing hold/readmission/closed-work correction), each owning
  its own store pair, every state built through public commands and real
  adapters, every printed count asserted in-module and re-asserted by the
  tests against the SQLite stores and external databases — never from
  stdout (`RevocationDemoTests`: separate fresh stores, revoked approval +
  verified replacement + single-call hold store, one retained effect with
  E05/E08 pending, closed completion preserving the cited revoked
  acceptance, exact final line, three printed inspect commands, repeatable
  runs).
- **CLI surface**: `python3 -m work_runtime revocation-demo` runs the
  harness end to end (exit 0, final line asserted —
  `RevocationDemoCliTests`); the installed `work-runtime revocation-demo`
  console entry point ships through the existing packaging.
- **Installed verification**: `scripts/verify_install.py` runs the module
  and console `revocation-demo` entry points outside the checkout in a
  fresh venv and proves them independently of printed text — revoked/
  verified statuses, preserved source-event fingerprints recomputed with
  the standard library (acceptance fingerprints still match the original
  verified acceptance), the stable business key of the single readmitted
  operation recomputed per policy family, the closed completion still
  citing the revoked acceptance, and exactly one retained external effect
  per store; rejection paths (missing final line, swapped store order,
  deleted external receipt, flipped revoked status) are pinned by
  `VerifyInstallRevocationProofTests`. The full script (all stages
  including the installed UI over real HTTP) passed end to end on this
  slice's checkout.

The read-only viewer surfaces (derived revoked identities, closed-work
notice) remain the later S8 owner wave recorded in the sprint plan; this
slice adds no viewer claim.

## S9 coverage — accepted-evidence collision prevention and recovery

The S9 core wave added the accepted-source operation-id reservation and
acceptance-proof conflict resolution on the unchanged Runtime, schema 1 and
both demo policy families (`tests/test_accepted_evidence_collision.py`,
24 tests). Semantics and boundaries:
[runtime boundaries](runtime-boundaries.md); the reservation rides the same
deduplicating command path as every other command, so no protocol matrix
row is added.

- **Intake reservation (D39)**: `OPERATION_ID_RESERVED` persisted rejection
  with `blockers == [operation_id]` after unchanged authority and old-row
  dedup/conflict precedence; the accepted-source union is recomputed per
  intake across loaded policy versions (renamed accepted source across a
  migration, mutated live policy object, missing-version fail-closed
  unchanged); reservation is global across works and kinds
  (overlapping-mapping poison), unrelated sources are never blocked and
  fresh-id imports stay valid; publishing-family mirror. Named: the
  `IntakeReservationTests` and `PublishingReservationTests` classes.
- **Legacy conflict resolution (D40/D41)**: pre-fix poisoned stores, built
  only by clearly labelled direct-SQL fixtures with the canonical
  `_receive` row shape from accepted original inputs (no product bypass),
  resolve to the actual accepted external result
  (`confirmed_succeeded`/`finished`/`external_id`/existing attempt status,
  exactly one retained external effect) plus the exact nine-field
  `proof_conflict` snapshot and eleven-field `AcceptanceProofConflict`
  event replacing `OperationResolved` on that path only; the conflicting
  row stays byte-identical across pending/verified/invalid/revoked and
  malformed-body variants (null snapshots, nothing coerced from candidate
  data); closed custom stores keep `status`/`outcome`/`completion` with
  `work_was_closed: true`; publishing-family mirror. Named: the
  `LegacyConflictTests` and `PublishingLegacyConflictTests` classes.
- **Crashes, lost responses and liveness**: the resolution is one
  transaction — exception injection and a real `os._exit(76)` child dying
  inside the conflict transaction roll back and redo deterministically with
  one external effect; a lost accepted response
  (`timeout_after_commit`) recovers exactly once through lookup;
  `recover()` reaches later operations after a conflict instead of
  aborting on the poisoned one.
- **Preservation and idempotence pins**: an exact resend of a pre-fix
  poisoning payload dedups with the candidate's current status and changed
  content stays `SOURCE_EVENT_CONFLICT`; post-confirmation imports keep
  conflict semantics; stored rejections replay verbatim with unchanged
  replay reauthorization (fresh `AUTHORITY_DENIED` on authority loss);
  completion gains no new blocker (a verified conflicting import satisfies
  the acceptance rule like any trusted import, an unverified one blocks on
  the normal requirements), replacement proofs work through new events,
  and `finalize_cancel` acknowledges the confirmed conflict effect with
  its real external id; repeated `recover()` is operation-scoped
  idempotent (zero writes and zero adapter calls for the settled
  operation while other records still verify/expire and later operations
  dispatch); the generic read-only inspector exposes the event and
  `proof_conflict` without reader changes and without writes. Named: the
  `PreservationAndIdempotenceTests` class.

## RFC-001 acceptance behaviors (R1–R7)

R1 restart/persistence — `test_prepared_intent_survives_restart`, `test_wait_expiry_survives_restart`, P07/P15 tests. R2 plan edits cannot delete requirements — P10 test. R3 unknown conditions block — P14 tests. R4 timeouts are not failures — `test_timeout_after_commit_then_reconcile`, `test_unknown_without_query_result_requires_attention` (no query result → `needs_attention`, no blind retry). R5 content change invalidates old confirmations — `test_existing_invoice_proof_reused_after_document_change`, `test_invoice_revision_invalidates_old_verification`, `test_unknown_old_content_blocks_new_submission`. R6 duplicate/late callbacks — P08/P09 tests. R7 no success without goal evidence — P12 tests.

## SOP example rules and review cases (E01–E08, T01–T12)

The demonstration policy turns most of rules E01–E08 from [RFC-002 §4](RFC-002-sop-authoring-and-binding.md) into executable checks (`work_runtime/policy.py`): set-closedness (E01), per-invoice validity (E02), cross-work uniqueness via the external stand-in (E03, `test_external_uniqueness_across_works`), unknown-amount blocking (E04), over-limit approval (E05), content-bound confirmation (E06), and acceptance evidence before closure (E08). E07 (original invoices must not be rewritten) is only **partially enforced**: the demo capability allowlist grants no invoice-write capability at all, so protected fields are excluded by construction rather than by an independently evaluated check. Of the review judgments T01–T12, the ones mirrored by named tests include T02/T07 (P14 tests), T05 (E05/confirmation invalidation tests), T09 (P10 test) and T10 (P07/P12 tests); the remaining judgments are still desk reasoning in [reference scenarios](reference-scenarios.md). The rule-card publication process itself (RFC-002 §6) is **not implemented**.

## Explicitly out of scope

- Remote or multi-tenant authentication and authorization (local principal names only). Owner, delegate and `work.intervene` administrator grants are trusted-local configuration, not authenticated identities; replay protection rechecks this local authority, it is not a distributed security boundary.
- Policy/SOP publication, author review workflow, and policy migration beyond the explicit same-family command above. Cross-domain policy registries are rejected; there is no implicit upgrade on restart or recovery. Static SOP lint is structural review only: no textual-predicate execution, no provenance verification, no authority approval, and no link from a linted card to an executing Python policy.
- Compensation (effect reversal) execution: `finalize_cancel` acknowledges external effects with their external ids and records every disposition — it never claims to reverse an effect. Evidence revocation (S8) withdraws a proof's current validity durably but is likewise not compensation, does not fence an in-flight external call, and does not rewrite historical receipts, closure snapshots or confirmed effects.
- Distributed execution: worker leases, fencing, cross-node coordination (P13). An attempt already durable when cancellation is requested remains uncertain until reconciled; there is no external fence. `FilePublisher`'s per-key artifact uniqueness is adapter-local, not a distributed exactly-once claim.
- Automatic repair of corrupted stores. Conflict recovery degrades malformed-but-valid-JSON evidence bodies to `null` snapshot fields; a body that is not valid JSON aborts only that operation's resolution (rolled back, retried) and is never repaired by the runtime.
- Any real external system adapter beyond the local filesystem; `FakeOA` and `FakePublisher` are local demonstrations, and `FilePublisher` targets trusted local directories only (hardlink support required, best-effort directory fsync, no power-loss/hostile-filesystem/symlink guarantee).
- General natural-language rule formalization.
- Collected external human adoption feedback: the planned guide-only rehearsal is an AI-agent exercise recorded as such, not human validation.

## Related

- [Runtime boundaries](runtime-boundaries.md) — transaction and dispatch boundary internals, produced by the parallel S1 runtime work and integrated with this document in the S1 carrier. Before that integration this link was the one recorded pending link in the contracts gate; with both branches assembled the gate requires zero broken links.
- [Adapter contract](adapter-contract.md) — declared adapter metadata, receipt validation and the reusable conformance mixin.
- [Signed evidence](signed-evidence.md) — ingress trust model, envelope semantics, replay handling and key guidance.
- [SOP authoring](sop-authoring.md) — rule-card schema, the exactly-14 diagnostic codes and digest semantics.
- [File adapter](file-adapter.md) — `FilePublisher` contract, artifact shape and platform boundaries.
- [GUI](gui.md) — the local read-only operations viewer: commands, sample store, tile definitions and limits.
- [Contributor guide](contributor-guide.md) — adapter and rule-card tutorials over the public interfaces.
- [RFC-001](RFC-001-core-semantics.md) · [RFC-002](RFC-002-sop-authoring-and-binding.md) · [RFC-003](RFC-003-runtime-protocol.md) · [Reference scenarios](reference-scenarios.md) · [Roadmap](roadmap.md)
