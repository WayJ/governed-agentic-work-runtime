# Verification coverage

Updated: 2026-10-22 (S17 slice: the workflow-success acceptance and the disclosed generic-completion guard — the atomic `finalize_workflow_success` command, the frozen final snapshot, the immutable completion read and the disclosed "a finished workflow is not routed again" engine fix; S15 waves: support-ticket family, support-demo with forward + crash-recovery chapters, installed module+console verifier stages, third-family freeze verdict; S13 demo wave: publication-demo withdrawal chapter, installed verifier publication-stage extension; S13 core wave: published-card withdrawal surface; S12 demo wave: publication-demo harness, CLI entry point incl. the `inspect --policy sop-publish` choice, installed module+console verifier stages; S12 core wave: governed SOP publication core; S11 demo wave: rotation-demo harness, CLI entry point, installed module+console verifier stages; S11 core: configured source signing-key rotation and authenticated key identity; S9 core: accepted-source operation-id reservation and acceptance-proof collision recovery; S8 demo wave: revocation-demo harness, CLI entry point, installed module+console verifier stages; S8 core: evidence revocation command, permanent revoked status, D-1 unbound closed guard; S5 frontend/CLI slice: GUI sample seed, ui commands, packaged assets; S4 adoption: static SOP lint, file adapter, adoption harness) · Maintained by the contributor waves; behavior evidence lives in the named test files below.

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
- **Content publication domain** (`tests/test_publishing.py`, 43 tests): document strictness (`requires_review` bool or None); per-kind evidence shapes incl. `accepted` = `{digest, external_id}`; C02 applicability true/false/unknown with unknown blocking (`APPLICABILITY_UNRESOLVED`); digest-bound approval/confirmation and publisher-source-only accepted proofs; plan revision cannot remove review; content revision invalidates prior approval/confirmation and cancels stale intents; conformance mixin adopted for `FakePublisher` with `(document id, digest)` artifact uniqueness (duplicate identical content under another key reuses the external id; changed content adds a version); malformed adapter results quarantined per isolated fixture with the real `execute` asserted; timeout-after-commit recovered by lookup without resend; deterministic demo (`publish-demo`) asserted end-to-end incl. independent `SELECT COUNT(*) FROM publications` = 2 and `FROM retractions` = 1 (the S14 retraction chapter, `tests/test_publishing_compensation_demo.py`) and both printed `inspect --policy content-publish` commands re-run verbatim.

The publication harness integrates the common command protocol without credentials; it is not a claim of integration with any model framework or server. The installed verifier additionally runs `publish-demo` outside the checkout through both the module and (new coverage since S14) the console entry point, and re-verifies both stores independently: two publications across both works, exactly one retraction effect bound to the original, the recomputed forward and compensation keys, the withdrawn-kind proof and the exact two-id closure.

## S3 coverage — interventions, ownership and pinned policy versions

The S3 wave added the intervention lifecycle on the runtime (`tests/test_interventions.py`, foundation wave) and its demonstration surface (`tests/test_intervention_demo.py`, this wave). Semantics and boundaries: [interventions](interventions.md).

- **Cancellation with uncertain effects** (`request_cancel` / `finalize_cancel`): the intent is immutable once stored; waits and never-dispatched prepared intents are cancelled; an attempt already durable when cancellation is requested stays uncertain until queried (no external fence). Finalize refuses unresolved operations (`OUTCOME_UNRESOLVED`), requires the exact set of confirmed-succeeded operation ids (`CANCEL_ACKNOWLEDGEMENT_MISMATCH`) and stores every disposition plus external ids in the closure — acknowledgement, never reversal. Named: `test_cancel_before_dispatch_makes_zero_external_calls`, `test_finalize_after_timeout_requires_exact_acknowledgement`, `test_finalize_after_real_process_death` (real subprocess exit after the external commit), `test_missing_lookup_cannot_finalize`, `test_malformed_result_cannot_finalize`, `test_cancellation_survives_evaluation_expiry_and_recovery`.
- **Ownership transfer** (`transfer_owner`): the creator becomes the work's owner; transfer persists actor/old/new owner and reason, reassigns outstanding waits, invalidates prepared intents (`OWNERSHIP_TRANSFERRED`), and gates management mutations, proposals and dispatch on current ownership; stored receipts are replayed only while current authority holds, otherwise a fresh unpersisted `AUTHORITY_DENIED` is returned and the stored receipt stays intact. Owners and `work.intervene` administrators are trusted local principals, not authenticated identities; legacy ownerless works stay grant-only until an administrator adopts them. Named: `test_former_owner_loses_management_proposal_and_dispatch`, `test_intervention_replay_after_transfer_denied`, `test_new_owner_reproposes_same_operation_and_dispatches`, `test_in_flight_operation_survives_transfer_and_reconciles`, `test_legacy_ownerless_work_stays_grant_only_until_admin_adoption`.
- **Explicit same-family policy migration** (`migrate_policy` + constructor registry): the registry is validated before any filesystem/database write, including the default for any explicit dict (D16, `test_malformed_default_rejected_for_any_explicit_registry`); works stay pinned to their bound version and restarts fail closed until it is loaded (`test_missing_pinned_version_fails_closed`, `test_restart_without_pinned_version_fails_closed`); migration is administrator-only, refuses uncertain effects, revalidates every verified proof under the target policy — an old approval bound to demo-1 does not survive (`test_strengthened_rule_revalidates_approval_and_keeps_key`) — increments the actual contract revision and rolls back atomically on target failure (`test_migration_rolls_back_atomically_on_target_failure`); two works may be pinned to different versions of one family (`test_two_works_pinned_to_different_versions`). Business-key stability across same-family versions is a policy-author obligation, documented, not a runtime rewrite.
- **Demonstration surface** (`tests/test_intervention_demo.py`): the deterministic no-credentials `intervention-demo` runs the three scenarios on separate fresh stores with independently counted external effects — zero while an intent is only prepared or cancelled, exactly one accepted application per store after each external acceptance (`test_each_store_independently_holds_exactly_one_accepted_application`, `test_transfer_state_old_owner_denied_operation_preserved`, `test_cancel_state_closed_cancelled_with_retained_effect`, `test_migration_state_pinned_demo2_same_operation`); the printed `inspect` commands run verbatim, the migrated one carrying `--policy-versions demo-1,demo-2` (`test_printed_inspect_commands_run_correctly`); the strict `inspect --policy-versions` flag rejects empty, duplicate, unknown and cross-family inputs while the flag-free expense and content-publish defaults are pinned unchanged (`InspectPolicyVersionsTests`). The installed verifier runs module and console `intervention-demo` outside the checkout and, for both entry points, counts each scenario store independently — exactly three distinct, correctly ordered stores with exactly one accepted application each — and exercises the installed flag against the migrated store.

The P01–P15 matrix above is unchanged by this wave: intervention behaviors are deliberately not blanket-mapped onto protocol acceptance cases, and the matrix still names only its own evidence. Intervention commands travel the same deduplicating command path as every other command (`test_duplicate_cancel_commands_share_one_receipt`, `test_cancel_intent_is_immutable_and_replay_returns_original`), which is protocol machinery, not a new matrix row.

## S4 coverage — static SOP lint, file adapter, adoption harness

The S4 wave added two foundations (authoring, file adapter) with their own reviewed evidence — `tests/test_authoring.py` (146 tests: exactly-14 diagnostics, iterative preflight/SCC graph boundary, digest key-order neutrality) and `tests/test_file_adapter.py` (57 loader-counted tests — 51 in-file plus the six inherited conformance-mixin cases: conformance over real directories, corruption matrix, subprocess races and real process death) — and the dependent adoption surface in `tests/test_adoption_demo.py` (this wave). Semantics and boundaries: [SOP authoring](sop-authoring.md), [file adapter](file-adapter.md), [contributor guide](contributor-guide.md).

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

## S10 coverage — expense compensation during active cancellation

The S10 core wave adds linked compensation proposals, opt-in adapter
action/link execution, the FakeOA withdrawal store, the `withdrawn` proof
kind, stored adapter results and truthful closure
(`tests/test_compensation.py`, plus contract/mixin additions in
`tests/test_adapter_contract.py` and `tests/adapter_conformance.py`) on the
unchanged Runtime schema 1, both demo policy families and the unchanged
publishing family. Semantics and boundaries:
[runtime boundaries](runtime-boundaries.md),
[adapter contract](adapter-contract.md), [interventions](interventions.md).

| guarantee | test (all in `tests/test_compensation.py` unless noted) |
|---|---|
| paired capability admitted, unpaired/publishing degrade | `PolicyPairingTests` |
| additive serialized store migration, legacy replay, named writes, counters | `AdapterStoreMigrationTests`, `ForwardWriteAndCounterTests` |
| withdrawal execution: one effect, alias receipts, link fingerprint, ORIGINAL_ABSENT, guards | `WithdrawalExecutionTests` |
| window/windowless admission, exact payload, target status matrix, pairing, stable key, immutable snapshot, authority, revoked-proof orthogonal, both versions | `CompensationAdmissionTests` |
| dispatch carve-out, belt-and-braces legs, context hold (zero attempts/effects then re-dispatch), kwargs/legacy call shapes, link revalidation, grant loss | `CompensationDispatchTests` |
| revision matrix binding, one effect + original intact, binding mismatch quarantine (accepted+rejected, idempotent), withdrawn proof never satisfies E08, stored adapter_result, refused closure, S9 conflict over withdrawal identity | `CompensationResolutionTests` |
| exact two-id ack, failed-withdrawal ack/disposition, unresolved blockers, replay/authority | `CompensationClosureTests` |
| recover inside window, re-admission/transfer re-admits, outside-window/closed codes, real child crash (one original + one withdrawal, attempts 1), execute-exception truth, read-only inspector zero-write | `CompensationRecoveryTests` |
| contract field invariants incl. bool-only opt-in | `tests/test_adapter_contract.py` (`AdapterContractTests`) |
| generic opt-in conformance replay (action from `contract.actions[0]`, skipped without the opt-in) | `tests/adapter_conformance.py` |

The S10 demo wave (W2) adds the no-credentials `compensation-demo` harness
(`tests/test_compensation_demo.py`, 21 tests), each scenario on its own
fresh stores with every count asserted against the scenario's SQLite
directly: scenario A crashes a real grants-carrying child subprocess
(exit 73) after the external withdrawal commits and recovers with exactly
one attempt per effect (exact `compensates` snapshot, separate stable
business keys recomputed locally, withdrawn-kind proof with the retained
E08 truth, unchanged receipts/invoices, exact two-id closure ack with the
compensation disposition); scenario B records the authoritative
`ORIGINAL_ABSENT` refusal (`confirmed_failed`, single-id ack, zero
effects, queryable refusing receipt). The shipped `worker` CLI boundary is
pinned: its demo grants hold no `expense.withdraw`, so routing a
withdrawal through it holds `AUTHORITY_DENIED` with zero attempts and zero
effects. The five AGENTS gates, their command list and the existing five
demos are unchanged — `compensation-demo` is explicit S10 validation, not
a gate — and the read-only inspector renders compensations generically
with zero writes (pinned). `scripts/verify_install.py` gains module and
console `compensation-demo` stages outside the checkout; their independent
proof recomputes business keys and fingerprints with the standard library
only and rejects deleted withdrawal rows, wrong linked targets, swapped
link digests, forged receipts, flipped proof kinds and refusal-store
effects, each exercised by a named negative test.

## S14 coverage — publishing-family linked retraction (W1 core)

The S14 core wave adds the publishing family's in-window linked
retraction on the unchanged S10 machinery: the `PublishingPolicy` pairing
attribute, the `FakePublisher` paired action with its additive store
migration, and the governed flow end to end
(`tests/test_publishing_compensation.py`), with
`work_runtime/runtime.py` and `work_runtime/adapters.py` byte-unchanged
(D82, hash-pinned in `BoundaryPins` together with the untouched
`file_adapter.py`/`policy.py`), runtime schema 1 and zero dependencies.
Semantics and boundaries:
[runtime boundaries](runtime-boundaries.md),
[adapter contract](adapter-contract.md), [interventions](interventions.md).

| guarantee | test (all in `tests/test_publishing_compensation.py`) |
|---|---|
| pairing attribute, empty paired blockers, off-family degrade, unchanged version, FilePublisher forward-only | `PolicyPairingTests` |
| additive serialized migration, no legacy row rewritten, idempotent reopen, concurrent first-open, fresh schema | `FakePublisherMigrationTests` |
| forward identity: NULL-tagged rows, positional/kwargs replay, same-content dedup, contract order (`content.publish` first) and opt-in | `ForwardIdentityTests` |
| retraction execution: one effect, RTR- prefix, input guards before any write, alias receipts, link-fingerprint conflict, cross-action replay, ORIGINAL_ABSENT, scan + short-circuit existence | `RetractionExecutionTests` |
| append-only retraction, truthful counts, re-publish-after-retraction artifact-id reuse (adapter-model limit, RF4) | `RetractionAppendOnlyTests` |
| window/windowless admission, forward CANCELLATION_ACTIVE, exact payload, target matrix incl. chain, stable D6 key, immutable snapshot | `PublishingCompensationAdmissionTests` |
| owner+grant authority, transfer re-admission, replay after grant loss, both RF4 reachability legs (CANCELLATION_ACTIVE / cross-work OPERATION_CONTENT_CONFLICT) | `PublishingCompensationAuthorityTests` |
| FilePublisher hold at the actions preflight, context hold, kwargs call shape, dispatch grant loss, link revalidation holds | `PublishingDispatchTests` |
| withdrawn proof at `publisher`, C04 inertness, import denial, admin-only revoke, adapter_result legs, binding mismatch quarantine | `PublishingResolutionTests` |
| exact two-id ack, compensation dispositions, refused-not-reversed closure, unresolved blockers | `PublishingClosureTests` |
| response-loss reconcile, real child crash (exit 73) recovered once, one publication + one retraction effect | `PublishingRecoveryTests` |
| D82/D88 byte pins at the sprint baseline | `BoundaryPins` |

The S14 demo wave (W2) delivers the publish-demo retraction chapter
(`tests/test_publishing_compensation_demo.py`, 18 tests): work one's
succeeded-completion story verbatim, the appended cancellation + linked
retraction across a real grants-carrying worker crash, recovery in one
attempt and the exact two-id closure with closing counts 2/1 asserted from
both SQLite stores, the widened demo grants, the installer's updated module
stage plus the NEW console publish-demo stage (disclosed as new coverage)
and the bilingual README entries; the five AGENTS gates and their command
list are unchanged.

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

## S11 coverage — configured source signing-key rotation (core wave)

The S11 core wave adds per-source `SourceKey` keyrings, the optional
authenticated `key_id` envelope field, strict verification-key selection,
inclusive key validity windows on a single finite clock sample, and
cache-first replay pins on the unchanged Runtime (`tests/test_key_rotation.py`,
real SQLite stores; `tests/test_ingress.py` stays the untouched legacy pin).
Semantics and boundaries: [signed-evidence](signed-evidence.md); the ratification
is the D49–D53 section of the
[S11 design](superpowers/specs/2026-10-15-source-key-rotation-design.md).

- **Keyring configuration (D50)**: exact ring types (list/tuple of `SourceKey`
  only; str/bytes/generator/set values are shape errors, never iterated),
  nonempty rings, `SourceKey`-only entries, exact field types (`key_id`
  nonempty str, `secret` bytes ≥32, `current` exactly bool, bounds `None` or
  exact int — bool traps rejected), `not_before <= not_after`, unique key ids
  per ring, exactly one `current` entry, secret material distinct across the
  entire configuration (ring-vs-ring and ring-vs-legacy), normalized immutable
  per-source tuples immune to caller dict/list mutation after construction, and
  legacy bytes validation unchanged beside rings. Named:
  `test_valid_rings_and_mixed_configs_construct`, `test_ring_must_be_list_or_tuple`,
  `test_ring_must_not_be_empty`, `test_ring_entries_must_be_sourcekey_instances`,
  `test_ring_entry_field_types_are_exact`, `test_ring_key_ids_unique_within_source`,
  `test_ring_requires_exactly_one_current_entry`, `test_ring_window_order_validated`,
  `test_secret_material_distinct_across_entire_config`,
  `test_configuration_is_copied_at_construction`,
  `test_legacy_bytes_validation_is_unchanged_beside_rings`
  (all in `tests/test_key_rotation.py`, class `KeyringConfigTests`).
- **Authenticated key selection (D49/D51)**: optional `key_id` inside the
  signed canonical bytes (selector swap breaks the signature — no unsigned
  downgrade), unknown `key_id` and wrong-secret-with-known-`key_id` rejected
  with zero writes, `key_id` envelopes against legacy `bytes` sources
  rejected, legacy-format envelopes authenticating against the `current`
  entry only in **both** directions (non-current key under the old
  configuration, and the retained old key under a rotated configuration —
  never silently served on the legacy path),
  current-entry happy path accepted, record-level immunity to caller
  dict/list mutation after construction, cross-material impersonation across
  sources rejected, signer round-trip of the optional field with
  signature dependence, and non-str/empty `key_id` rejected by both the
  signer (`ValueError`) and the gateway shape check
  (`EVIDENCE_ENVELOPE_INVALID`). Named: `test_key_id_envelope_accepted_against_keyring`,
  `test_key_id_is_signed_content_and_tampering_fails`, `test_unknown_key_id_rejected`,
  `test_wrong_secret_with_known_key_id_rejected`,
  `test_key_id_envelope_against_legacy_bytes_source_rejected`,
  `test_legacy_envelope_authenticates_against_current_entry_only`,
  `test_legacy_envelope_current_entry_happy_path_accepted`,
  `test_ring_configuration_mutations_cannot_reach_verification`,
  `test_cross_material_cannot_impersonate_across_sources`
  (`KeySelectionTests`); `test_envelope_carries_optional_key_id_and_signature_depends_on_it`,
  `test_signer_rejects_bad_key_id_values`,
  `test_gateway_rejects_bad_key_id_shape_as_envelope_invalid`
  (`SignerKeyFieldTests`).
- **Single finite clock and key windows (D51)**: inclusive window edges on
  both envelope formats, retired/not-yet-valid codes with zero writes,
  window precedence over freshness, verification-time (never `issued_at`)
  window evaluation in both directions (no backdating), window codes gated
  behind a valid signature (no oracle), current-entry-outside-window on the
  legacy path, retained-expired vs dropped-entry distinct codes, the full
  invalid-clock matrix (non-finite floats, wrong types incl. bool, raising
  clock → minimal `EVIDENCE_CLOCK_INVALID` with zero writes on both source
  shapes; `BaseException` propagates), huge-integer samples compared
  exactly without overflow, exactly one shared clock sample per record
  (zero calls before successful HMAC, sequence-based single-sample proof in
  both directions), and legacy ±`max_age` freshness semantics unchanged.
  Named (class `WindowClockTests`): `test_window_bounds_inclusive_at_edges`,
  `test_retired_key_rejected_after_not_after`, `test_not_yet_valid_key_rejected`,
  `test_window_precedes_freshness`, `test_window_uses_verification_time_not_issued_at`,
  `test_window_codes_require_valid_signature`,
  `test_current_entry_outside_window_on_legacy_path`,
  `test_dropped_and_retained_expired_keys_have_distinct_codes`,
  `test_clock_invalid_samples_fail_closed`,
  `test_clock_raising_ordinary_exception_fails_closed`,
  `test_clock_base_exception_propagates`,
  `test_huge_int_clock_sample_is_finite_and_safe`,
  `test_single_clock_sample_shared_by_window_and_freshness`,
  `test_clock_not_sampled_until_hmac_succeeds`,
  `test_legacy_freshness_semantics_unchanged`.
- **Cache-first replay, resend branches and history (D52)**: authentication
  ahead of the command cache (retired-key replay of an accepted original →
  `EVIDENCE_KEY_RETIRED`, all six tables byte-identical incl. metadata),
  same-`command_id` re-sign under the new key returning the original receipt
  verbatim with zero writes (including after trusted-local revocation),
  new-`command_id` resends reporting current status (`revoked` after
  revocation) with exactly `commands +1`, grant loss as a fresh unpersisted
  `AUTHORITY_DENIED` with the stored receipt intact, changed content as
  `SOURCE_EVENT_CONFLICT`, per-act history preservation (pure reconstruction
  and every denial class byte-equal across all six tables; legitimate new
  ingress prefix-equal on the append-only tables with `works`/`metadata`
  untouched by a pending insertion), deterministic same-config/same-clock
  restart decisions, minimal receipts for every new code without key echo,
  reserved `accepted` and mapping-denied `withdrawn` kinds unchanged for a
  keyring source, legacy bytes semantics beside a keyring, and the published
  known-answer vector unchanged. Named: `test_resign_same_event_new_command_under_new_key_dedupes`,
  `test_resign_same_command_under_new_key_returns_original_receipt`,
  `test_revoked_evidence_preserves_original_receipt_and_reports_status`,
  `test_grant_loss_is_fresh_unpersisted_authority_denied`,
  `test_changed_content_same_event_is_source_event_conflict`,
  `test_retired_key_replay_cannot_reach_cached_receipt`,
  `test_history_six_tables_preserved_across_rotation_acts`,
  `test_deterministic_restart_same_config_same_decisions`,
  `test_new_code_receipts_are_minimal_without_key_echo`,
  `test_reserved_and_withdrawn_kinds_unchanged_for_keyring_source`
  (`ReplayHistoryTests`); `test_legacy_bytes_source_semantics_beside_a_keyring`,
  `test_known_answer_vector_unchanged` (`LegacyCompatTests`).
  `tests/test_ingress.py` remains the untouched 40-test legacy pin (KAT
  included).

### S11 demo wave — demonstration and installed verification

The demo wave added the public no-credentials demonstration on top of the
accepted frozen core (`tests/test_rotation_demo.py`;
`work_runtime/rotation_demo.py`; reference in
[signed-evidence](signed-evidence.md)). The demo drives the core through its
stable public API with an injected deterministic clock
(`T0 = 2000000000`, `grace = 300 == max_age`) and ephemeral in-memory keys
(`secrets.token_bytes(32)`, never printed — only key ids): dual-key window
accept (both ring keys authenticate), `verify_pending`, rotate (the old key
retained with `not_after` at the inclusive grace boundary — reconstructing the
gateway writes nothing), boundary replay returning the original cached receipt
verbatim, retired refusal `EVIDENCE_KEY_RETIRED` one second past grace with the
cached receipt unreachable, same-`command_id` re-sign under the new key
returning the original receipt byte-verbatim with no new command row, a new
`command_id` resend reporting the current status with exactly `commands +1`,
and a six-table history digest. Named tests: `test_demo_creates_fresh_store`,
`test_store_evidence_rows_statuses_and_fingerprints`,
`test_store_command_rows_exact_with_original_cached_receipt`,
`test_store_table_counts_and_work_state`,
`test_six_table_digest_matches_printed_final_digest`,
`test_output_pins_narrative_without_secret_material`,
`test_demo_runs_are_repeatable` (`RotationDemoTests`) — every count, status,
fingerprint and digest re-derived from the SQLite store, never from stdout.
The CLI surface runs the harness end to end (`test_cli_rotation_demo_module_runs`,
`RotationDemoCliTests`: exit 0, final line, one printed inspect path); the
installed `work-runtime rotation-demo` console entry point ships through the
existing packaging. The installed verifier proves both entry points
independently of printed text (`scripts/verify_install.py` stages 19–20:
`require_rotation_proof` reads the real store — the six-table digest
recomputed locally and matched against the printed digest, evidence
statuses/fingerprints/document digest recomputed with the standard library,
exactly one command row per rotation command id with the original cached
receipt still `pending_verification`, zero operations, schema 1 — and re-runs
the printed inspect command verbatim); rejection paths (missing final line,
flipped evidence status, deleted evidence row, forged duplicate command row,
tampered cached receipt, digest-only store mutation) are pinned by
`VerifyInstallRotationProofTests`.

## S12 coverage — governed SOP rule-card publication (core and demo waves)

The S12 core wave adds the publication machinery on the unchanged Runtime,
gateway and `FilePublisher` commit engine (`tests/test_publication.py`,
`tests/test_publication_rotation.py`, plus narrow additive
`ReadValidatedTests` in `tests/test_file_adapter.py`); the demo wave adds
the `publication-demo` harness, its CLI entry point and the installed
module+console proof stages (`tests/test_publication_demo.py`,
`work_runtime/publication_demo.py`). Semantics and boundaries:
[SOP authoring](sop-authoring.md) publication section,
[file adapter](file-adapter.md); design
[S12](superpowers/specs/2026-10-15-sop-publication-design.md) ratified
D54–D66.

- **Additive validated read surface (D61)** (`ReadValidatedTests`):
  `FilePublisher.read_validated(key)` returns `None` for an absent key
  (mirroring `lookup`, keeping absence distinguishable from corruption),
  the full validated artifact for a committed key — detached from caller
  and storage, stable across fresh instances — and refuses corrupt bytes
  and tampered documents with bounded `ValueError`s while never rewriting
  the file; the key gate applies unchanged.
- **Digest-based publication key and store wrapper (D55/D56/D60)**
  (`PublicationKeyTests`, `SopPublicationStoreTests`): the key equals
  `"sop-pub:" + digest([policy id, version])` with the 64-hex tail;
  delimiter-hostile lint-clean identities (`("collide:one","v1")` vs
  `("collide","one:v1")`, IR-P16) do **not** collide; identity changes
  change the key and malformed identities raise bounded errors; the wrapper
  commits exactly one hash-named artifact per publication key (bare card as
  document, `content_digest == sop_digest`), replays the byte-identical
  receipt across instances, refuses same-key changed content without
  overwriting, and delegates `lookup` (committed receipt / `None`).
- **Fail-closed loader and pin (D62)** (`LoaderPinTests`): round trip
  returns the published card with `sop_digest` equal to the stored
  `content_digest` and receipt digest; absent version and missing store
  directory raise the same bounded absent error (distinguishable from every
  corruption class, directory never created by a read); corrupt bytes,
  tampered documents with stale digests and doctored key fields raise
  bounded errors; foreign card or non-card content committed under a
  publication key by raw adapter use fails closed (MD-4 discipline);
  `pinned_card` requires the exact pin (wrong pin or malformed pin
  argument refused); `published_card_matches` compares `(id, version,
  goal)` only — True for the packaged expense card against `ExpensePolicy`,
  False on version/goal drift and non-card shapes.
- **Governed flow on the real Runtime (D54/D57–D59/D66)**
  (`GovernedFlowTests`, real SQLite + real directory + ephemeral never-printed
  approver key): dirty cards are refused at admission with a bounded
  unpersisted `ValueError` (zero `works` rows, nothing committed); clean
  cards carry `document_digest == sop_digest`; proposals without approval
  are persisted `REQUIREMENT_UNSATISFIED` with an `S02` blocker; tampered
  approvals are refused `EVIDENCE_AUTHENTICATION_FAILED` with unchanged
  evidence rows (zero intake writes); wrong-source intake is
  `AUTHORITY_DENIED`; wrong-version approvals stay candidates then turn
  `invalid` at verification; correctly-signed wrong-digest approvals verify
  on shape but keep S02 unsatisfied; the valid version-bound approval
  verifies and the accepted proposal's `business_key` is exactly the
  publication key; dispatch through the response-loss wrapper commits one
  hash-named artifact (bare card as document, zero `.stage`) and the
  restart reconcile recovers `confirmed_succeeded` with exactly one
  attempt; the `accepted` proof is runtime-written (`sop-store` source
  absent from grants, `event_id` = operation id, digest-bound, verified);
  completion closes `succeeded`; exact command replay returns the stored
  receipt verbatim with one operation; cross-work same-card and doctored
  same-version proposals are first `REQUIREMENT_UNSATISFIED` (D66 order)
  and only after the second work's own verified approval persist
  `OPERATION_CONTENT_CONFLICT` with the winning artifact byte-unchanged.
- **Approver-key rotation battery (S11 semantics unchanged)**
  (`tests/test_publication_rotation.py`, `PublicationRotationTests`): the
  approver configured as a `SourceKey` keyring and rotated mid-flow — an
  old-key envelope is refused `EVIDENCE_KEY_RETIRED` (retained past its
  window) or `EVIDENCE_AUTHENTICATION_FAILED` (dropped, both selector-less
  and cited-selector forms) with all six runtime tables byte-identical
  (ordered rowid dumps); the same `command_id` re-signed under the new
  current key replays the original receipt verbatim with zero writes; a new
  `command_id` on the same `(source, event_id)` reports the candidate's
  current status with exactly `commands +1`; after a completed publication,
  every post-rotation refusal leaves the six tables and the committed
  artifact bytes untouched (publication history is rotation-invariant); a
  pre-rotation approval still verifies after rotation (key-agnostic
  fingerprints) and carries its work to completion while a legitimate new
  card version publishes under the rotated key. All secrets synthetic,
  ephemeral, never printed.
- **Demonstration surface (demo wave, D64)** (`tests/test_publication_demo.py`):
  the deterministic no-credentials `publication-demo` runs the whole §11 story
  on one fresh store — dirty-card lint diagnostics, the packaged
  `publishing.json` card published with its pinned digest, the blocked
  proposal, the tampered approval refused with zero intake writes, the valid
  version-bound approval, the response-loss dispatch and one-attempt
  reconcile, the runtime-written accepted proof, completion, the D66
  doctored-card conflict order with the winner bytes unchanged, the
  fail-closed loader matrix (absent vs tampered, distinguishable) and the
  retired-key refusal with tables and artifact untouched. Tests re-derive
  every count, key, digest and receipt from the SQLite store and the
  artifact directory (works/commands/evidence/operations/events pinned:
  2/11/3/1/11), re-run the printed `inspect --policy sop-publish` command
  verbatim through the real CLI (the choice was added with master
  authorization after a probe showed the pre-existing choices fail closed on
  a sop-publish-family database), and prove secret hygiene by planted marker
  (patched key generator: neither marker bytes, their hex, nor a locally
  computed envelope signature ever reach the output). Hygiene: parent
  contents survive, two runs use two fresh folders, the demo runs with the
  working directory outside the checkout.
- **Installed verification (demo wave, D64 — existing installer evidence,
  no new global gate)** (`scripts/verify_install.py` stages 21/22): module
  AND console `publication-demo` entry points run outside the checkout and
  are verified independently of stdout — the artifact directory enumerated
  (exactly one hash-named `.json`, zero `.stage`), the artifact parsed with
  the standard library only (bare packaged card, recomputed content digest,
  digest-based publication key, `sha256(key)` file name, accepted `FILE-`
  receipt), the runtime store read directly (pub-1 closed/succeeded, pub-2
  active, one `confirmed_succeeded` operation with one attempt and the
  matching business key, three evidence rows incl. the runtime-written
  `sop-store` accepted proof with `event_id` = the operation id and the
  receipt's `external_id`, the `OPERATION_CONTENT_CONFLICT` and both
  `REQUIREMENT_UNSATISFIED` receipts), and the printed inspect command
  re-run verbatim; the printed absent/tampered loader lines must stay
  distinguishable. Rejection tests mutate the real store (flipped accepted
  status, deleted evidence row, tampered artifact bytes, forged duplicate
  command row, rewritten conflict receipt) and require the proof to fail.

## RFC-001 acceptance behaviors (R1–R7)

R1 restart/persistence — `test_prepared_intent_survives_restart`, `test_wait_expiry_survives_restart`, P07/P15 tests. R2 plan edits cannot delete requirements — P10 test. R3 unknown conditions block — P14 tests. R4 timeouts are not failures — `test_timeout_after_commit_then_reconcile`, `test_unknown_without_query_result_requires_attention` (no query result → `needs_attention`, no blind retry). R5 content change invalidates old confirmations — `test_existing_invoice_proof_reused_after_document_change`, `test_invoice_revision_invalidates_old_verification`, `test_unknown_old_content_blocks_new_submission`. R6 duplicate/late callbacks — P08/P09 tests. R7 no success without goal evidence — P12 tests.

## SOP example rules and review cases (E01–E08, T01–T12)

The demonstration policy turns most of rules E01–E08 from [RFC-002 §4](RFC-002-sop-authoring-and-binding.md) into executable checks (`work_runtime/policy.py`): set-closedness (E01), per-invoice validity (E02), cross-work uniqueness via the external stand-in (E03, `test_external_uniqueness_across_works`), unknown-amount blocking (E04), over-limit approval (E05), content-bound confirmation (E06), and acceptance evidence before closure (E08). E07 (original invoices must not be rewritten) is only **partially enforced**: the demo capability allowlist grants no invoice-write capability at all, so protected fields are excluded by construction rather than by an independently evaluated check. Of the review judgments T01–T12, the ones mirrored by named tests include T02/T07 (P14 tests), T05 (E05/confirmation invalidation tests), T09 (P10 test) and T10 (P07/P12 tests); the remaining judgments are still desk reasoning in [reference scenarios](reference-scenarios.md). The rule-card publication process (RFC-002 §6) is implemented since S12 as governed trusted-local publication — signed version-bound approvals and an immutable hash-named artifact store (see the S12 section); external author review and feedback collection remain unimplemented.

## Explicitly out of scope

- Remote or multi-tenant authentication and authorization (local principal names only). Owner, delegate and `work.intervene` administrator grants are trusted-local configuration, not authenticated identities; replay protection rechecks this local authority, it is not a distributed security boundary.
- Author review workflow, external author feedback, and policy migration beyond the explicit same-family command above. SOP publication withdrawal/tombstones (D63: the store is append-only; a corrected card ships as a new version) and multi-approver quorum are separately designed future work. Cross-domain policy registries are rejected; there is no implicit upgrade on restart or recovery. Static SOP lint is structural review only: no textual-predicate execution, no provenance verification, and no link from a linted card to an executing Python policy — authority approval exists only in the governed publication flow (S12), as trusted-local signed evidence rather than authentication, and published cards never execute.
- Compensation (effect reversal) is bounded: since S10 the expense family
  (`expense.withdraw`) and since S14 the publishing family
  (`content.unpublish`) support linked withdrawal proposals **only inside
  the active cancellation window**, executing a distinct appended external
  effect under the current owner's paired-capability grant. It is not a
  general
  reversal: `finalize_cancel` never claims to undo an effect (a refused
  withdrawal is recorded, effects stand),
  post-closure compensation, chains and a public abandon command are
  unimplemented, and evidence revocation (S8) remains withdrawal of a
  proof's current validity only — not compensation, no fencing of
  in-flight calls, no rewriting of historical receipts, closure snapshots
  or confirmed effects.
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

## S13 coverage — publication withdrawal (core wave)

The S13 core wave adds the withdrawal surface additively to
`work_runtime/publication.py` on the unchanged Runtime, gateway and
`FilePublisher` (`tests/test_publication_withdrawal.py`, plus the rotation
battery in `tests/test_publication_withdrawal_rotation.py`). Semantics and
boundaries: [SOP authoring](sop-authoring.md) withdrawal section; design
[S13](superpowers/specs/2026-10-16-sop-publication-withdrawal-design.md)
ratified D67–D79.

- **Digest-based withdrawal key, closed record and store wrapper
  (D67/D68/D69/D74)** (`WithdrawalKeyTests`, `WithdrawalRequestTests`,
  `SopWithdrawalStoreTests`): the withdrawal key equals
  `"sop-withdrawn:" + digest([policy id, version])` with the 64-hex tail;
  delimiter-hostile identities do not collide; identity changes change the
  key and the withdrawal key differs from the publication key for the same
  identity; malformed identities raise bounded errors.
  `is_withdrawal_request` admits exactly the closed four-field
  `{discriminator, policy_id, policy_version, published_digest}` record
  shape and refuses cards, extra/free-text fields, wrong discriminators and
  malformed values without raising. The wrapper commits exactly one second
  hash-named artifact (record document verbatim,
  `content_digest == digest(request)`), replays the byte-identical receipt
  across instances with the census unchanged, refuses an absent target or a
  digest mismatch with a deterministic **rejected receipt** (`status:
  "rejected"`, `digest` binding the operation, `reason` code) at zero store
  writes, refuses a same-key changed record without overwrite (bounded
  `ValueError` at the raw delegate), and delegates `lookup` verbatim.
- **Fail-closed loader withdrawal check and audit read (D72/RV-F5)**
  (`LoaderWithdrawalTests`): the round trip loads unchanged pre-withdrawal;
  after a committed withdrawal `load_published_card` raises the exact
  withdrawn message (distinct from absent/corrupt/digest/identity) and
  `pinned_card` raises it before any pin judgment (correct and wrong pins
  alike); corrupt bytes, a tampered stale-digest record, a foreign
  identity's record and a same-identity record binding a different
  `published_digest` each raise the one invalid-record message by explicit
  catch-and-re-raise (the adapter's parse/shape/digest vocabulary never
  leaks); a digest-mismatching record is refused by the governed path
  (rejected receipt) and, if committed by raw adapter use, fails closed
  instead of withdrawing; an absent artifact reads absent even with a
  record standing; a missing store directory is never created by
  `withdrawal_record` or the loader; `withdrawal_record()` returns `None`
  pre-withdrawal and the validated record post-withdrawal; no loader
  function accepts an override keyword (TypeError on `allow_withdrawn`);
  `published_card_matches` stays pure and never matches a withdrawal
  record.
- **Governed sop.withdraw flow (D70/D71/D74/D75)** (`GovernedWithdrawalFlowTests`,
  real Runtime + SQLite + directory, one database holding the publication
  and the withdrawal): malformed requests are refused unpersisted at
  admission (zero works rows) while the well-formed request carries
  `document_digest == digest(request)` and is effectively immutable under
  `revise_document` (id-less shape); proposals block on `W02` before any
  approval; a valid `card_approval` never satisfies W02 (turns `invalid`);
  tampered `card_withdrawal` is refused `EVIDENCE_AUTHENTICATION_FAILED`
  with zero intake writes; wrong-source intake is `AUTHORITY_DENIED`;
  wrong-digest approvals verify on shape but keep W02 pending and
  wrong-version approvals turn `invalid`; the valid version-bound approval
  accepts with `business_key == withdrawal_key`; capability × document-shape
  pairing holds in both directions (`sop.publish` on a withdrawal work and
  `sop.withdraw` on a card work each yield the bounded
  `CAPABILITY_UNSUPPORTED` blocker); the wrong adapter holds
  `ADAPTER_ACTION_UNSUPPORTED` with zero attempts and zero writes before a
  correct re-dispatch confirms; the full story commits exactly one second
  artifact with publication bytes unchanged, recovers a lost response via
  one-attempt reconcile on a restarted Runtime, carries the runtime-written
  `accepted` proof under `sop-store` (`event_id` = operation id, digest =
  request digest), completes `succeeded`, and flips the loader to the
  withdrawn error with `withdrawal_record()` returning the record; an
  absent target and a digest-mismatch target both resolve
  `confirmed_failed` with the work `needs_attention`, completion refused,
  and the work closable `cancelled` via acknowledged-empty finalize
  (cancellable — the D74 channel); a second withdrawal work hits
  `REQUIREMENT_UNSATISFIED` first and `OPERATION_CONTENT_CONFLICT` only
  after its own approval (D75); re-publication of a withdrawn version
  conflicts after its own approval with the census unchanged (no
  un-withdrawal); a publication work completes unchanged in the same
  family/database (the F18 regression).
- **S8 revocation composition pinned (D79)** (`RevocationCompositionTests`):
  on the closed publication work the owner and the configured source
  without `evidence.revoke` are refused `AUTHORITY_DENIED`; a
  `work.intervene` administrator revokes both the `card_approval` and the
  runtime-written `accepted` proof (`sop-store`, `event_id` = the
  operation id) with `prior_status "verified"`; the work stays
  `closed/succeeded` with the completion snapshot byte-identical, S02/S03
  turn pending, exactly two `EvidenceRevoked` events land, and the
  committed artifact is untouched; and revoking the publication proofs
  after a standing withdrawal never touches the withdrawal record — the
  loader keeps answering withdrawn (the two truths stay separate, D71/D79).
- **Withdrawal approver-key rotation battery (S11 semantics)**
  (`tests/test_publication_withdrawal_rotation.py`,
  `WithdrawalRotationTests`): the `card_withdrawal` approver configured as
  a `SourceKey` keyring and rotated mid-flow — an old-key envelope is
  refused `EVIDENCE_KEY_RETIRED` (retained past its window) or
  `EVIDENCE_AUTHENTICATION_FAILED` (dropped, both selector forms) with all
  six runtime tables byte-identical (ordered rowid dumps); the same
  `command_id` re-signed under the new current key replays the original
  receipt verbatim with zero writes; a new `command_id` on the same
  `(source, event_id)` reports the candidate's current status with exactly
  `commands +1`; after a completed withdrawal every post-rotation refusal
  leaves the six tables and BOTH artifact byte dumps untouched (the
  publication and withdrawal artifacts are rotation-invariant); a
  pre-rotation approval still verifies after rotation (key-agnostic
  fingerprints), carries the withdrawal to `closed/succeeded`, and a
  legitimate new version's withdrawal proceeds under the rotated key. All
  secrets synthetic, ephemeral, never printed.
- **Cross-shape evidence isolation, both directions (D70/MD-4)**: a
  `card_withdrawal` recorded on a card-shaped work turns `invalid` at
  verification (never a `KeyError` through the card-only field access) and
  leaves S02 pending — mirroring the `card_approval`-never-satisfies-W02
  pin in `GovernedWithdrawalFlowTests`; a near-miss withdrawal attempt at
  admission (any discriminator-bearing document that is not well-formed)
  is refused with the dedicated closed-shape requirement message, while
  non-withdrawal documents fall to the card lint.
- **Demonstration surface (S13 demo wave, D77)**
  (`tests/test_publication_withdrawal_demo.py`,
  `WithdrawalChapterTests`): the deterministic no-credentials
  `publication-demo` chapter continues the standing publication story in
  the same store — the withdrawal work blocked on W02 first (D66 order),
  the signed `card_withdrawal` from the rotated current key, the dispatch
  committing exactly one second hash-named artifact with the publication
  bytes unchanged, W03 satisfied by the runtime-written `accepted` proof,
  completion `succeeded`, the loader's distinct withdrawn error (pairwise
  distinguishable from absent and tampered, equal to the module's
  `WITHDRAWN_MESSAGE`), the `withdrawal_record()` audit read, the
  re-publication of the withdrawn version refused
  `OPERATION_CONTENT_CONFLICT` after its own approval with the census
  unchanged, and the retired-key `card_withdrawal` refusal with six tables
  and both artifacts untouched. Tests re-derive every count, key, digest
  and receipt from the SQLite store and the artifact directory
  (works/commands/evidence/operations/events pinned: 4/22/6/2/21), run
  both printed `inspect --policy sop-publish` commands verbatim through
  the real CLI, and pin the closed record document, the exact command-id
  census with actors, and both persisted D66 conflict receipts. The S12
  demo tests (`tests/test_publication_demo.py`) pin the same extended
  store from the publication side.
- **Installed verification (S13 demo wave, D77 — existing installer
  evidence, no new global gate)** (`scripts/verify_install.py`
  publication stage): the SAME module AND console `publication-demo` runs
  are now verified deeper, never stdout-only — the withdrawn loader line
  required and pairwise distinguishable, the store census exactly two
  hash-named artifacts (publication + withdrawal record) with zero
  `.stage`, the withdrawal record located by its printed path AND its
  `sha256(withdrawal key)` name and parsed with the standard library only
  (exact FilePublisher shape, closed four-field document binding the
  published content digest, recomputed digests, accepted `FILE-`
  receipt), `wd-1` closed/succeeded and `pub-3` active, the withdrawal
  operation `confirmed_succeeded` with one attempt under the withdrawal
  key, the verified version-bound `card_withdrawal` evidence row, the
  second runtime-written `sop-store` accepted proof bound to the record,
  the extended command census with both blocked codes and the
  `cmd-propose-pub3` `OPERATION_CONTENT_CONFLICT` receipt; every printed
  inspect command re-run verbatim (both works). Rejection tests mutate
  the real store (deleted or tampered withdrawal record, flipped
  `card_withdrawal` status, rewritten re-publication receipt) and require
  the proof to fail.

## S15 coverage — support-ticket family (third-family command-surface freeze)

The S15 waves added the third business family as new code only — policy,
GitHub-issue-shaped tracker, demo and installer stages — while
`work_runtime/runtime.py` and `work_runtime/adapters.py` stayed byte-identical
(SHA-256 `80bf721b…` / `ce132f24…`, asserted at both wave boundaries). The
freeze verdict and the two disclosed family constraints (document identity
keyed on the ticket reference; one reference = one governed dispatch, changed
content dead-ends `OPERATION_CONTENT_CONFLICT`) are recorded in
[runtime-boundaries.md](runtime-boundaries.md); the family contract and store
in [adapter-contract.md](adapter-contract.md).

- **Family core** (`tests/test_support.py`, 46 tests): document admission
  (exact fields; severity/category vocabularies with `None` = unresolved
  triage, out-of-vocabulary strings rejected at validation); evidence shapes
  (`sla` = `{digest, response_target_minutes}` with a positive integer;
  `accepted` reserved shape); rules T01/T02 (unresolved ⇒ unknown, blocks),
  T03 urgent SLA (critical ≤ 60 / high ≤ 240 minutes, V2 tightens critical
  to ≤ 30; an unresolved severity keeps SLA applicability unknown — the
  unknown-blocking rule propagates to dependent rules), T04 tracker
  acceptance; blockers exclude T04; the ticket-reference business key
  (content-independent, version-stable, V1→V2 migration readmits the SAME
  operation on the stable key); `FakeIssueTracker` passes the reusable
  conformance mixin (six cases including the opt-in action-context replay)
  plus domain tests (one issue per reference across keys with alias reuse,
  content-conflict business rejection, digest mismatch, timeout-after-commit,
  link refusal); the governed flow through the real Runtime (unknown blocks
  `APPLICABILITY_UNRESOLVED`; missing or wrong-budget SLA blocks
  `REQUIREMENT_UNSATISFIED`; business-key dedupe/replay returns the same
  operation; late proposals on a closed work refused `WORK_NOT_ACTIONABLE`;
  cross-work and same-work reference conflicts `OPERATION_CONTENT_CONFLICT`);
  timeout reconciliation recovered by lookup without a resend; and a real
  grants-carrying subprocess dying (exit 73) after tracker acceptance,
  recovered by `recover()` with exactly one attempt, one issue and one
  receipt — nothing re-sent.
- **Demo + installer** (`tests/test_support_demo.py`, 9 tests): the
  deterministic no-credentials `support-demo` (forward chapter: unknown
  blocks, triage revision, in-budget SLA, issue `#1`, closure; crash
  chapter: real subprocess death after acceptance, restart recovery by
  ticket reference, closure) asserted against the stores directly
  (issue/receipt counts, recomputed business keys, tracker-source accepted
  proofs binding `event_id` = operation id, both works closed/succeeded),
  repeatably, with parent-directory contents surviving and no 64-hex digests
  in the output; the CLI subcommand plus `inspect --policy support-ticket`;
  and the installed verifier's `require_support_proof` pinned in-repo — real
  demo output passes it, doctored counts and a missing final line fail it.
  The installed verifier runs module AND console `support-demo` outside the
  checkout (stages 24/25, both disclosed as NEW coverage since S15, D90
  pattern) with the same independent store proof and verbatim re-runs of the
  printed inspect commands.

No protocol matrix row is added: the family reuses the already-covered
command, dispatch, reconciliation and migration machinery — that reuse under
byte-pinned lifecycle files is the freeze result itself.

## S16 coverage — mixed-node workflow runtime (core wave)

The mixed-node engine (`work_runtime/workflow.py`,
`work_runtime/workflow_spec.py`), the generic HTTP bridge
(`work_runtime/workflow_server.py`) and the ten-node demonstration
(`work_runtime/workflow_demo.py`) are a new execution organization over the
existing Work/Evidence/Operation/Wait machinery. The language, the engine and
the bridge are described in [workflow-runtime.md](workflow-runtime.md); this
section records what is verified and what is not.

The **workflow-success acceptance** (`finalize_workflow_success`) is part of
this wave: the command the trusted platform runner issues when it closes its
task, the exact final snapshot it freezes and the immutable completion read
it answers with. `work_runtime/runtime.py` and `work_runtime/adapters.py`
are byte-unchanged by that slice; the boundary rows are in
[runtime-boundaries.md](runtime-boundaries.md).

### Workflow matrix (W01–W112)

| Case | Behaviour | Status | Evidence |
|---|---|---|---|
| W01 | One routing pass changes nothing twice | covered | `test_a_second_pass_writes_nothing` — two further passes leave the state version untouched |
| W02 | The entry node opens and waits for its executor | covered | `test_the_entry_node_opens_and_waits_for_the_executor` — one `agent_task` intent with a stable id |
| W03 | Only the configured executor may submit a candidate | covered | `test_only_the_configured_executor_may_submit` — `AUTHORITY_DENIED` |
| W04 | A candidate is accepted only by the registered, version-pinned validator | covered | `test_an_invalid_candidate_is_rejected_and_stores_no_object` — `WORKFLOW_RESULT_INVALID`, no object row, node not completed |
| W05 | A self-certifying payload is not a validation path | covered | `test_a_self_certifying_claim_is_not_accepted` — the `validated` field is an undeclared field |
| W06 | An approval creates the next human task with no agent turn | covered | `test_an_approval_creates_the_next_human_task_without_an_agent_turn` — the `n05` task appears, the agent intents do not change |
| W07 | A decision must cover the subject's exact revision and digest | covered | `test_a_stale_decision_does_not_satisfy_a_node` — a wrong digest and a wrong revision both leave the node waiting |
| W08 | An executor may not approve; a reviewer may not repeat a role | covered | `test_an_executor_may_not_approve`, `test_a_reviewer_may_not_repeat_another_reviewers_role` — bounded findings, the node does not advance |
| W09 | A rejection takes the declared rework branch | covered | `test_a_rejection_routes_back_to_the_rework_branch` — `n03` runs again as attempt 2 |
| W10 | Rework is bounded and escalates | covered | `test_bounded_rework_escalates_to_needs_attention` — `WorkflowReworkLimitExceeded` |
| W11 | Rework invalidates the approval of the previous version | covered | `test_rework_invalidates_the_approval_of_the_previous_version` — the old proof stays on the record, the new attempt waits |
| W12 | A late callback cannot revive a completed node | covered | `test_a_late_result_cannot_revive_a_completed_node` — `WORKFLOW_ATTEMPT_STALE`, one object revision |
| W13 | The same command replays; changed content conflicts | covered | `test_the_same_command_replays_and_a_changed_body_conflicts` — the original receipt, then `COMMAND_ID_REUSED` |
| W14 | An approval dispatches exactly one external action | covered | `test_an_approval_creates_exactly_one_external_action` — one operation, one effect, still one after a second pump |
| W15 | An unknown effect is looked up, never repeated | covered | `test_an_unknown_effect_is_looked_up_and_never_repeated` — a real crash between the effect and the record, then one effect and a confirmed operation |
| W16 | Publication and binding fail closed | covered | `PublicationAndBindingTests` — an immutable definition, an unknown validator version, a family mismatch, an incomplete required check, a double binding |
| W17 | A decision binds the node and the attempt | covered | `test_a_decision_must_name_the_node_and_the_attempt`, `test_a_same_digest_approval_of_an_earlier_attempt_is_refused` — an approval of attempt 1 never satisfies attempt 2, even with the identical digest |
| W18 | The actor is the asserted principal, not the ingress source | covered | `test_the_actor_of_a_decision_is_not_the_ingress_source` — `WORKFLOW_AUTHORITY_MISMATCH`; the isolation rules in `test_an_executor_may_not_approve` and `test_a_reviewer_may_not_repeat_another_reviewers_role` compare the actor |
| W19 | A request for more material keeps the node waiting | covered | `test_a_request_for_more_material_keeps_the_node_waiting` — the node stays running, no outcome, the request is on the record |
| W20 | Every declared criterion carries a verdict, a reason and its evidence | covered | `test_every_declared_criterion_carries_a_verdict`, `test_the_check_report_is_persisted_and_readable` — `WORKFLOW_CHECK_RESULT_MISSING`; the persisted report is readable |
| W21 | A candidate is bound to the input digest | covered | `test_a_candidate_must_be_bound_to_the_current_input_digest`, `test_the_input_digest_follows_the_pinned_input` — `WORKFLOW_INPUT_STALE` |
| W22 | The published definition carries the criterion text and its validator | covered | `test_the_published_definition_carries_the_criterion_text`, `test_a_criterion_validator_must_resolve_at_publication` — `WORKFLOW_VALIDATOR_UNKNOWN` |
| W23 | A decision is admitted under the caller's compare-and-swap | covered | `test_a_decision_without_an_expected_version_is_refused`, `test_a_stale_expected_version_is_refused` — `EXPECTED_VERSION_REQUIRED`, `STATE_VERSION_CONFLICT`; the write is the workflow command `record_decision`, so the version check and the evidence intake are one transaction |
| W24 | An assigned authority fails closed without a resolver | covered | `test_without_a_resolver_an_assigned_node_fails_closed` — `WORKFLOW_AUTHORITY_MISMATCH` |
| W25 | The resolved assignee may decide; nobody else may | covered | `test_the_resolved_assignee_may_decide`, `test_someone_else_may_not_decide` — the actor is checked against the trusted resolution |
| W26 | The assignment is rechecked when the node settles | covered | `test_the_assignment_is_rechecked_when_the_node_settles` — a withdrawn assignment stops an already written decision |
| W27 | Separation of duties compares the actual actors | covered | `test_two_roles_held_by_one_person_is_refused` — `WORKFLOW_ROLE_ISOLATION` |
| W28 | A participant must name a declared node | covered | `test_a_participant_must_name_a_declared_node` — `WORKFLOW_PARTICIPANT_UNKNOWN` |
| W29 | A criterion report is checked at the core boundary | covered | `test_an_unknown_criterion_is_refused`, `test_a_repeated_criterion_is_refused`, `test_a_blank_reason_is_refused`, `test_empty_evidence_is_refused`, `test_an_unknown_verdict_is_refused` — `WORKFLOW_CHECK_REPORT_INVALID` |
| W30 | A required criterion that failed stops an approval | covered | `test_a_failing_required_criterion_stops_an_approval`, `test_a_not_applicable_verdict_needs_a_protected_rule`, `test_a_not_applicable_verdict_is_accepted_when_the_rule_allows_it`, `test_a_rejection_keeps_the_shortages` — `WORKFLOW_CHECK_SHORTFALL`; the report keeps the real verdict |
| W31 | The judgment context is persisted with the report | covered | `test_the_report_records_the_judgment_context` — the method, the criterion version, the reviewed digests, the actor and the time |
| W32 | A review node creates a durable review intent | covered | `test_a_review_node_creates_a_durable_review_intent` — the rubric, the criteria, the candidate and the input digest are pinned |
| W33 | A review binds the exact instance | covered | `test_a_review_of_another_attempt_does_not_satisfy`, `test_a_review_of_another_input_does_not_satisfy`, `test_a_review_of_another_candidate_does_not_satisfy`, `test_a_same_digest_review_of_an_earlier_attempt_does_not_satisfy` |
| W34 | The executor may not review its own candidate | covered | `test_the_executor_may_not_review_its_own_candidate`, `test_only_the_declared_reviewer_may_review` |
| W41 | The exact material read is never silently altered | covered | `test_the_exact_read_returns_the_material_the_digest_covers`, `test_a_material_with_a_credential_is_never_silently_altered` — the default read returns the body the digest covers; a credential-bearing material is refused (`WORKFLOW_OBJECT_CONTAINS_SECRETS`) and the declared `?redact=true` form says what it returned |
| W37 | A stored command receipt is readable without resending | covered | `test_a_stored_command_receipt_is_readable_without_resending`, `test_a_receipt_of_another_work_or_actor_is_not_found`, `test_a_receipt_lookup_needs_its_scope` — the lookup is read-only and work-scoped |
| W38 | The published template can be pinned by digest | covered | `test_a_pinned_template_digest_is_checked` — `WORKFLOW_TEMPLATE_MISMATCH` |
| W39 | A shortage may carry no evidence; a pass may not | covered | `test_a_shortage_may_carry_no_evidence`, `test_a_pass_always_needs_its_evidence` |
| W40 | A criterion names its judge, and the stages keep their own records | covered | `test_a_complete_review_completes_the_node` — the program check and the review keep different identifiers and both records |
| W36 | The judgment history is readable per attempt | covered | `test_the_judgment_history_is_readable_per_attempt`, `test_the_attempt_history_of_a_node_is_readable` — a judgment belongs to the attempt that produced it |
| W35 | The create validates the contract, the plan and the snapshot | covered | `test_a_policy_that_is_not_the_registered_one_is_refused`, `test_the_registered_policy_is_accepted`, `test_the_submitted_plan_is_used`, `test_a_malformed_plan_is_refused`, `test_the_trusted_snapshot_carries_the_session_and_the_participants`, `test_a_participant_must_name_a_declared_node` — `WORKFLOW_POLICY_MISMATCH`, `PLAN_INVALID`, `WORKFLOW_PARTICIPANT_UNKNOWN` |
| W42 | An automatic node's input is judged before the effect | covered | `test_an_input_validator_failure_prevents_the_external_effect` — the node is `blocked`, no operation is prepared, the effect count is 0 |
| W43 | An automatic node's output is judged by the pinned validator | covered | `test_a_validated_payload_becomes_a_named_object`, `test_the_output_report_names_the_judge_of_every_criterion` — the payload becomes the named object; the report names the method, the criterion version, the validator and version, the reviewed digests, the reason and the evidence |
| W44 | A failed output is not a false external failure | covered | `test_the_external_effect_stays_recorded_when_the_output_fails` — the operation stays `confirmed_succeeded`, the instance records the effect as succeeded |
| W45 | A failed output is never produced again | covered | `test_a_rejected_output_is_never_dispatched_again`, `test_a_rejected_output_is_never_routed_back_into_the_same_node` — one effect in the business system's own store across the rejection and the recovery |
| W46 | The receipt is the adapter's, and its linkage is authoritative | covered | `test_a_receipt_that_names_another_action_is_refused`, `test_a_receipt_that_does_not_match_the_document_is_never_accepted` — `WORKFLOW_RECEIPT_ACTION_MISMATCH`; a digest that does not match is quarantined by the runtime (`outcome_unknown`) |
| W47 | A missing per-check verdict is a refusal, not a pass | covered | `test_a_missing_per_check_verdict_is_refused` — `WORKFLOW_CHECK_RESULT_MISSING`, no object written |
| W48 | A wait binds the proof it matched | covered | `test_a_wait_binds_the_proof_it_matched` — the work, the node, the attempt, the bound node and attempt, the object revision and digest and the event provenance are on the record |
| W49 | An old proof never satisfies a new attempt | covered | `test_a_proof_of_another_attempt_does_not_satisfy_the_wait` — the wait keeps waiting |
| W50 | A wait is bound to the current revision of its subject | covered | `test_a_proof_of_a_superseded_revision_does_not_satisfy_the_wait`, `test_a_proof_of_another_digest_does_not_satisfy_the_wait` |
| W51 | A wait's output is judged before the workflow routes on | covered | `test_a_wait_writes_its_validated_output`, `test_a_wait_output_failure_stops_the_downstream_node` — the validated payload becomes the named object; a rejected output stops the next node |
| W52 | A node that asked for no quality is not implied to have it | covered | `test_a_node_without_a_declaration_is_not_implied_to_be_checked` — `quality.declared` is `false`, `quality.mode` is `undeclared`, the report stays empty |
| W53 | A creation is resumable after a crash at any stage | covered | `test_a_crash_after_the_work_was_created_resumes_the_creation`, `test_a_crash_after_the_contract_resumes_the_creation`, `test_a_crash_after_the_plan_resumes_the_creation`, `test_a_crash_after_the_binding_resumes_the_creation` — the resume completes the creation (`tests/test_workflow_create_resume.py`) |
| W54 | A replay adds no revision, no intent and no event | covered | `test_a_replay_adds_no_revision_no_intent_and_no_event`, `test_a_replay_does_not_issue_an_accepted_stage_again`, `test_the_resume_issues_an_accepted_stage_only_once` — each accepted stage appears exactly once in the event history |
| W55 | A command id belongs to one request | covered | `test_a_changed_document_conflicts`, `test_a_changed_template_conflicts`, `test_a_changed_instance_conflicts`, `test_a_changed_session_conflicts`, `test_a_changed_plan_conflicts`, `test_a_changed_actor_conflicts`, `test_a_changed_work_conflicts` — `COMMAND_ID_REUSED`, never a silent reuse of the first request's stages |
| W56 | The binding receipt is the platform's probe point | covered | `test_the_binding_receipt_is_readable_after_a_crash`, `test_the_binding_receipt_is_readable_after_a_replay` — the receipt is absent before the binding and accepted after it |
| W57 | Two callers of one creation never truncate each other | covered | `test_two_concurrent_creations_of_the_same_body_keep_one_creation`, `test_two_concurrent_creations_with_different_bodies_conflict`, `test_two_concurrent_preparations_keep_every_stage`, `test_two_concurrent_preparations_keep_one_prepared_version` — the second caller waits its turn, one body wins and the other conflicts, every prepared stage survives |
| W58 | A prepared stage is never re-prepared | covered | `test_a_recorded_stage_is_never_overwritten`, `test_another_request_under_the_same_command_id_conflicts` — the prepared version and the recorded request digest are immutable |
| W59 | A native business key resolves to the action it names | covered | `test_the_context_is_readable_inside_the_adapter_execute` — the adapter reads the context inside its own `execute`: the operation, the node, the attempt, the capability, the contract and plan revision, the input digest, the pinned template and the bound subject (`tests/test_workflow_action_context.py`) |
| W60 | The context survives a restart | covered | `test_the_context_survives_a_process_reopen_and_is_readable_through_lookup` — a fresh process reads the same context from the same store; the adapter's `lookup` path reads the same context |
| W61 | The same capability in two nodes never confuses the mapping | covered | `test_two_nodes_of_the_same_capability_map_to_their_own_action` — two action nodes of one capability on two subjects, each with its own operation, node and subject |
| W62 | A historical attempt keeps its own action | covered | `test_a_historical_attempt_keeps_its_own_action` — a superseded attempt keeps its operation, its subject revision and its attempt number; the live attempt has its own |
| W63 | An unknown key and a manual operation are not a context | covered | `test_an_unknown_key_is_a_documented_absence`, `test_a_manual_operation_is_refused` — `ACTION_CONTEXT_ABSENT`; an operation no node proposed is `ACTION_CONTEXT_REFUSED` / `OPERATION_NOT_WORKFLOW_BOUND` |
| W64 | A broken linkage is refused, never guessed | covered | `test_two_node_instances_of_one_operation_are_refused`, `test_a_link_of_another_kind_is_refused`, `test_a_subject_that_does_not_match_the_operation_is_refused`, `test_an_object_with_a_broken_digest_is_refused`, `test_a_capability_that_does_not_match_the_node_is_refused` — `OPERATION_LINK_AMBIGUOUS`, `OPERATION_LINK_WRONG_KIND`, `OPERATION_SUBJECT_MISMATCH`, `OPERATION_OBJECT_DIGEST_MISMATCH`, `OPERATION_CAPABILITY_MISMATCH` |
| W65 | The answer is a copy and the read changes nothing | covered | `test_a_mutated_answer_does_not_change_the_store`, `test_the_read_writes_no_event_and_changes_no_state_version` — a mutated answer leaves the rows untouched; the read writes no event and moves no state version |
| W66 | A cancelled work keeps its context and grants no execution | covered | `test_a_cancelled_work_keeps_its_context_and_grants_no_execution` — the context still resolves, `current.cancelled` is true, the dispatch state is `cancelled` and the business system records no effect |
| W67 | A migrated contract keeps the historical action readable | covered | `test_a_migrated_contract_keeps_the_historical_action_readable` — after `migrate_policy` the action still resolves with the contract it was proposed under (`context.contract.source` is `ledger`), and the contract in force now is an observation under `current` |
| W68 | A row that disagrees with its body is refused | covered | `test_an_operation_row_that_disagrees_with_its_body_is_refused`, `test_a_node_row_that_disagrees_with_its_body_is_refused` — `OPERATION_ROW_INCONSISTENT`, `NODE_ROW_INCONSISTENT`; the answer never carries a self-contradictory relation |
| W69 | The stable context does not move when the work does | covered | `test_the_stable_context_survives_a_migration_and_an_owner_transfer` — after a real `migrate_policy` **and** a real `transfer_owner` the complete `context` of the action is equal to the one captured before; only `current` moves (the contract in force, the owner, the provenance of the historical contract) |
| W70 | The effect policy is declared in the published definition | covered | `test_an_action_node_may_declare_the_per_revision_policy`, `test_an_unknown_effect_policy_is_refused`, `test_the_per_revision_policy_needs_a_second_attempt`, `test_the_effect_policy_is_an_action_node_field`, `test_the_policy_is_part_of_the_published_digest` — `NODE_EFFECT_POLICY_UNKNOWN`, `NODE_EFFECT_POLICY_ATTEMPTS`, `NODE_FIELD_UNKNOWN`; the policy is part of the pinned digest (`tests/test_workflow_effect_policy.py`) |
| W71 | A new subject version produces a new effect | covered | `test_a_new_proposal_produces_a_new_draft_and_one_final_effect`, `test_the_new_effect_is_a_new_operation_with_a_new_business_key`, `test_the_original_receipt_is_retained` — agent proposal v1, automatic draft v1, human rejection, reworked and independently reviewed proposal v2, automatic draft v2, two approvals, one formal final action: two version drafts, one final effect, the first receipt retained |
| W72 | The default stays once per node | covered | `test_a_node_without_the_policy_never_repeats_its_effect`, `test_the_explicit_once_policy_never_repeats_its_effect` — `WORKFLOW_EFFECT_ALREADY_APPLIED`, one effect in the business system's own store |
| W73 | A new revision of the same content is not a new version | covered | `test_the_same_digest_under_a_new_revision_is_refused` — `WORKFLOW_EFFECT_SUBJECT_UNCHANGED` |
| W74 | An unsettled effect is reconciled before any new write | covered | `test_an_unresolved_prior_effect_is_not_rewritten` — `WORKFLOW_EFFECT_UNRESOLVED`; the node waits and no second operation is prepared |
| W75 | A failed output is not bypassed | covered | `test_a_failed_output_is_not_bypassed_by_a_new_subject` — `WORKFLOW_EFFECT_OUTPUT_INVALID`; the effect really happened and stays |
| W76 | A new admission owns a new operation and an exact linkage | covered | `test_an_operation_already_linked_to_another_node_is_refused` — `WORKFLOW_EFFECT_REUSED`; the native context of a business key stays unambiguous |
| W77 | Both business keys resolve after a restart | covered | `test_both_business_keys_resolve_after_a_restart` — the old key names attempt 1, the new key attempt 2 |
| W78 | An unknown policy is refused at publication and at binding | covered | `test_an_unknown_policy_is_refused_at_publication`, `test_an_unknown_policy_is_refused_at_binding`, `test_a_pinned_template_cannot_be_changed_under_the_same_version` — `WORKFLOW_SPEC_INVALID`, `WORKFLOW_EFFECT_POLICY_UNKNOWN`, `WORKFLOW_TEMPLATE_IMMUTABLE` |
| W79 | A successful workflow is accepted and frozen by the trusted runner | covered | `test_a_successful_workflow_is_accepted_and_frozen` — the work is closed as `succeeded`, the event `WorkflowFinalized` is written, the snapshot names the terminal (`tests/test_workflow_finalization.py`) |
| W80 | The acceptance names the exact identities it accepted | covered | `test_the_snapshot_names_the_exact_identities_it_accepted` — the template digest, the contract revision, the plan revision, the document revision and digest, both object revisions and digests, the node attempts, the operation and the obligation |
| W81 | The receipt of an acceptance replays after a restart | covered | `test_the_receipt_replays_after_a_restart` — a new runtime over the same store replays the identical receipt; one finalization, one `WorkflowFinalized` event |
| W82 | A new command key after the freeze creates no second acceptance | covered | `test_a_new_command_key_after_the_freeze_creates_no_second_finalization` — `WORK_NOT_ACTIONABLE`; the snapshot keeps its `finalizationId` |
| W83 | A stale version is refused before the closure | covered | `test_a_stale_version_is_refused_before_the_closure` — `STATE_VERSION_CONFLICT`; nothing is frozen, no event is written |
| W84 | Only the trusted runner may accept a workflow | covered | `test_only_the_trusted_runner_may_accept_the_workflow`, `test_a_runtime_without_a_trusted_runner_fails_closed` — `WORKFLOW_RUNNER_MISMATCH` for an agent, the owner and a reviewer; `WORKFLOW_RUNNER_UNCONFIGURED` when no runner is configured |
| W92 | A human terminal node is accepted on its own verdict | covered | `HumanTerminalTests` — an approved human terminal completes with the verdict of its kind ("approved"), and the acceptance reads the *state* of the terminal node; a rejected terminal is refused (`WORKFLOW_TERMINAL_NOT_COMPLETED`) |
| W85 | Only a verifiably successful workflow is frozen | covered | `test_a_failed_terminal_cannot_be_accepted`, `test_an_output_invalid_terminal_cannot_be_accepted`, `test_a_cancelled_workflow_cannot_be_accepted`, `test_an_unknown_effect_cannot_be_accepted`, `test_an_outstanding_requirement_cannot_be_accepted`, `test_a_running_workflow_cannot_be_accepted` — `WORKFLOW_TERMINAL_NOT_COMPLETED`, `WORKFLOW_CANCELLED`, `WORKFLOW_NOT_FINISHED`, `WORKFLOW_REQUIREMENT_UNSATISFIED` |
| W86 | Nothing may change an accepted workflow | covered | `test_nothing_may_change_the_accepted_workflow` — a revised object, a new result, a revised plan, a revised document, a cancellation and a new effect are all refused; the events, the object rows and the external effect count do not move |
| W87 | Late evidence and late revocation cannot reopen an accepted workflow | covered | `test_a_late_proof_cannot_reopen_the_accepted_workflow`, `test_a_revocation_cannot_reopen_the_accepted_workflow` — the proof is admitted by the runtime's own correction rule, the snapshot does not change, the workflow is not routed again and no effect is produced |
| W88 | The acceptance and a competing mutation do not both win | covered | `test_the_acceptance_and_a_mutation_do_not_both_win` — two threads, one version: exactly one command is accepted, the other is `STATE_VERSION_CONFLICT` |
| W89 | The bridge exposes the acceptance and the immutable completion read | covered | `HttpFinalizationTests` — `POST /v1/workflows/instances/{workId}/finalize` answers the instance view and the snapshot; `GET /v1/workflows/instances/{workId}/completion` answers the same snapshot every time; a stale version is `409`, a foreign actor is `403` |
| W101 | An output validator receives the material the attempt pinned | covered | `tests/test_workflow_materials.py` — `CoverageValidationTests`: the agent candidate is judged against the pinned input; an unknown, a missing and a duplicated identifier are each refused with the validator's own code |
| W102 | The material is the pinned revision, never the latest | covered | `test_the_materials_are_the_pinned_revision_not_the_latest`, `test_a_candidate_covering_the_latest_revision_is_refused` — a newer revision in the store does not change what the attempt pinned |
| W103 | Every output-producing kind hands over the material | covered | `MaterialsPerKindTests` — the agent candidate, the human record, the automatic output and the waited material each receive the pinned input (and the subject where the node declares one) |
| W110 | An explicitly permitted not-applicable verdict is accepted | covered | `tests/test_workflow_finalization.py` — `NotApplicableCriterionTests`: a human terminal whose declaration sets `allow_not_applicable` completes on a `not_applicable` verdict and the acceptance freezes the workflow, exactly as the node's own settlement does |
| W111 | A not-applicable verdict without the permission cannot pass | covered | `test_a_not_applicable_verdict_without_the_permission_cannot_pass` — the node never completes (the criterion is a genuine shortfall) and nothing is frozen |
| W112 | A globally required check still demands a pass | covered | `test_a_globally_required_check_still_demands_a_pass` — the node completes under its own declaration, the acceptance refuses `WORKFLOW_CHECK_UNSATISFIED`, and the refusal names the global requirement, not a node |
| W109 | A node that pins no input compares against its protected subject | covered | `SubjectCoverageTests` — the material carries the subject the node decided on, and a record that does not cover it is refused while the decision itself is never lost |
| W104 | A refused automatic output keeps the real effect | covered | `test_a_rejected_automatic_output_keeps_the_effect` — the effect stays `succeeded`, the node fails with `WORKFLOW_OUTPUT_INVALID`, and no second effect is produced |
| W105 | A validator cannot change the stored material | covered | `test_a_mutating_validator_cannot_change_the_stored_material` — the stored object, the stored document and the stored requirements are unchanged |
| W106 | A missing or corrupt pinned object fails closed | covered | `test_a_missing_pinned_object_fails_closed`, `test_a_corrupt_pinned_object_fails_closed` — a specific `WorkflowError`, nothing stored, the node does not complete |
| W107 | The material survives a restart | covered | `test_the_materials_survive_a_restart` — the settlement after a restart resolves the same pinned material |
| W108 | An existing validator without the new key still works | covered | `test_an_existing_validator_without_the_materials_still_works` — a validator that ignores the context is unaffected |
| W94 | The generic completion cannot close an unfinalized workflow | covered | `GenericCompletionGuardTests` — an active workflow and a finished but unfinalized workflow are both refused `WORKFLOW_ACCEPTANCE_REQUIRED`; a bare `Runtime` over the same store, with no engine in the process, refuses it too; the refusal is a stored receipt |
| W95 | An ordinary work still completes the generic way | covered | `test_an_ordinary_work_still_completes_the_generic_way` — a work without a workflow closes `succeeded` with its completion record |
| W96 | The generic completion stays refused after the acceptance | covered | `test_the_generic_completion_stays_refused_after_the_acceptance` — `WORK_NOT_ACTIONABLE`, one finalization, one `WorkflowFinalized` event |
| W97 | The canonical text hashes to the stored digest | covered | `CanonicalProofTests`, `test_the_completion_read_carries_the_canonical_text` — the text is the canonical JSON of the snapshot without its `digest`, SHA-256 over its UTF-8 is the stored digest, and parsing it yields the snapshot without its digest |
| W98 | The canonical text survives an exponent and Unicode | covered | `test_the_canonical_text_carries_an_exponent_and_unicode` — `1e+30` is emitted as it stands and a non-ASCII character is emitted as itself, never as an escape sequence |
| W99 | A proof that needs redaction is not emitted | covered | `test_a_proof_that_needs_redaction_is_not_emitted` — `409 WORKFLOW_COMPLETION_PROOF_UNAVAILABLE`, no canonical text, no hash of a redacted proof, and the credential never appears in the answer |
| W100 | A proof that does not match its digest is refused | covered | `test_a_proof_that_does_not_match_its_digest_is_refused` — `409 WORKFLOW_COMPLETION_PROOF_UNVERIFIED` |
| W93 | A revision before the acceptance is visible in the snapshot | covered | `test_a_revision_before_the_acceptance_is_visible_in_the_snapshot` — the node keeps the revision it judged (1), the object list carries the current revision (2), and the revision is refused from the acceptance on |
| W90 | An unbounded snapshot is refused instead of truncated | covered | `test_an_unbounded_snapshot_is_refused_instead_of_truncated` — 67 named objects, `WORKFLOW_SNAPSHOT_UNBOUNDED`, nothing is frozen |
| W91 | A finished workflow is not routed again | covered | `test_a_finished_workflow_is_not_routed_again` — the routing pass and the recovery pass find the recorded terminal and write nothing: no new attempt, no new event, the same state version |

### Bridge, recovery and demonstration

- **HTTP bridge** (`tests/test_workflow_http.py`, 47 tests, real loopback
  socket): the route whitelist (the product's `/v1/deliveries` route is not
  part of this surface and answers 404 here), a published template read
  back including every criterion's text, an instance created and read back,
  the bounded read model (≤64 nodes, ≤32 intents, ≤16 findings and ≤16
  check results per node), a candidate accepted and a bad one refused with
  findings, the exact content of one object revision readable, the durable
  intent ids and their acknowledgement, the global intent listing scoped by
  `workIds`, a body carrying a credential absent from the log, and
  **progress without a client poll** — the ticker dispatches the authorized
  action on its own.
- **The mutation contract** (same file): a mutation without a stable
  `commandId` is refused, a mutation without the `expectedVersion` the
  client observed is refused, a stale `expectedVersion` is a
  `STATE_VERSION_CONFLICT`, a result without an `inputDigest` is refused, a
  result bound to a stale input digest is `WORKFLOW_INPUT_STALE`, a
  decision without an `actorId` or without per-criterion items is refused, a
  decision from an actor who is not the assigned authority is
  `WORKFLOW_AUTHORITY_MISMATCH`, a decision for another attempt is
  `WORKFLOW_ATTEMPT_STALE`, a request for more material keeps the node
  waiting, and every mutation answers with the root instance view.
- **The workflow-success acceptance** (`tests/test_workflow_finalization.py`,
  21 tests, real `Runtime` and real `WorkflowEngine`): a successful workflow
  is accepted and frozen by the configured runner only; the snapshot names
  the exact template digest, contract revision, plan revision, document
  revision and digest, object revisions and digests, node attempts,
  operation and obligation it accepted; the receipt replays identically
  after a restart; a new command key after the freeze creates no second
  acceptance; a stale version is refused before the closure; a failed, an
  output-invalid, a cancelled, an unknown-effect, an unsettled-requirement
  and a running workflow are never frozen; nothing may change an accepted
  workflow; late evidence and late revocation cannot reopen it; the
  acceptance and a competing mutation do not both win; and the bridge
  exposes both routes over a real loopback socket.
- **Participant assignment and criterion quality**
  (`tests/test_workflow_participants.py`, 16 tests): an assigned authority
  fails closed without a resolver; the resolved assignee may decide and
  nobody else may; the assignment is re-resolved when the node settles; two
  roles held by one person are refused; a participant must name a declared
  node; a criterion report that names an undeclared criterion, repeats one,
  carries a blank reason, empty evidence or an unknown verdict is refused at
  the boundary; a required criterion that failed stops an approval; a
  not-applicable verdict counts only when the protected declaration allows
  it; a rejection keeps the shortages; and the report records the judgment
  context.
- **The asynchronous review** (`tests/test_workflow_review.py`, 8 tests): the
  review intent pins the rubric, the criteria, the candidate and the input
  digest; a review of another attempt, another input or another candidate
  does not satisfy the node; a same-digest review of an earlier attempt does
  not satisfy the current one; the executor may not review its own
  candidate; and only the declared reviewer may.
- **Authority, attempt binding and criterion reports**
  (`tests/test_workflow_authority.py`, 11 tests): a decision without a node
  and attempt binding never matches; a same-digest approval of an earlier
  attempt is refused; the actor is checked against the assigned authority
  while the ingress source is never used as the actor; a request for more
  material keeps the node waiting; a decision without a verdict for every
  declared criterion is refused; the criterion report is persisted and
  readable; a candidate is bound to the input digest it was produced from;
  the published definition carries the criterion text and its validator
  binding, and a criterion validator that does not resolve fails closed at
  publication.
- **Per-node IO and quality** (`tests/test_workflow_node_quality.py`, 24
  tests): an automatic node's input is judged by the pinned validator before
  any effect is authorized; the receipt the external system really returned
  is persisted with its origin and is refused when it names another action
  or does not match the document; the validated payload becomes a named
  object and the per-criterion report names the judge of every criterion; a
  rejected output is not a false external failure and is never produced
  again — one effect in the business system's own store across the rejection
  and the recovery; a missing per-check verdict is a refusal; a declared
  input and a declared subject are judged by their pinned validator before
  any effect; a human decision writes the named record it carries in the
  same command, and a record that fails its quality is never written over a
  good one; an orphan judge declaration is refused at publication; a
  revised candidate or subject supersedes the node that pinned it; a wait binds
  the work, node, attempt, object revision and digest and event provenance
  of the proof it matched, and an old proof never satisfies a new attempt; a
  wait's output is judged before the workflow routes on; and a node that
  declared no quality says so plainly.
- **The action effect policy** (`tests/test_workflow_effect_policy.py`, 18
  tests): the default stays one effect per node; the opt-in
  `per_revision` is declared in the immutable published definition and
  admits a new effect only for a new revision with a new digest of the
  subject and only after the previous effect is settled; the same subject
  never repeats an effect, an unsettled operation is reconciled before any
  new write, and a succeeded effect whose output failed validation is never
  bypassed; the new admission owns a new operation with a new business key
  and an exact node linkage, and both keys resolve after a restart; an
  unknown policy is refused at publication and at binding, and a pinned
  template cannot be changed under the same version.
- **Recovery** (`tests/test_workflow_recovery.py`, 7 tests): a prepared
  action dispatched once after a restart, an effect committed before a real
  crash looked up rather than repeated, a restart that resumes without
  re-running a completed node, a pending human task that survives a
  restart, a cancellation with an in-flight effect that is neither closed
  nor declared failed, a late callback that cannot revive a cancelled
  instance, and a cancelled work that dispatches nothing further.
- **Demonstration** (`tests/test_workflow_demo.py`, 2 tests): the scenario end
  to end on a fresh store, with a real worker process that dies
  after the external effect, a restart that recovers the original operation,
  the external effects counted in the business system's own store (one
  dispatch, one delivery), every operation `confirmed_succeeded` with
  exactly one attempt, and a stale decision that does not advance a node.
  The dispatch receipt becomes the named order the field report and the
  independent review judge, and the dispatch wait matches only the bound
  proof of the attempt that produced it.

### Explicitly not covered

- **No authentication and no tenant isolation.** The bridge resolves the
  approving principal from the published node and the policy's source
  registry, not from the request body, but the principal names remain
  trusted local configuration. Nothing here is distributed authentication.
- **No distributed exactly-once, no leases, no fencing.** The bridge takes
  a single-coordinator file lock; a second coordinator fails fast instead
  of being fenced.
- **No semantic proof.** A review is durable evidence from a named
  authority; a program check never claims that a model's judgement is
  correct, and a passing shape never stands in for a business review.
- **No arbitrary dynamic graph.** Only published, immutable definitions may
  be bound, with constrained instance parameters.
- **The installed verifier was not extended** with a workflow stage in this
  slice: `scripts/verify_install.py` still exercises the previous
  demonstrations only.
