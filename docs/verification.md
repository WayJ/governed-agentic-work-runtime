# Verification coverage

Updated: 2026-10-15 (S12 core wave: governed SOP publication core; S11 demo wave: rotation-demo harness, CLI entry point, installed module+console verifier stages; S11 core: configured source signing-key rotation and authenticated key identity; S9 core: accepted-source operation-id reservation and acceptance-proof collision recovery; S8 demo wave: revocation-demo harness, CLI entry point, installed module+console verifier stages; S8 core: evidence revocation command, permanent revoked status, D-1 unbound closed guard; S5 frontend/CLI slice: GUI sample seed, ui commands, packaged assets; S4 adoption: static SOP lint, file adapter, adoption harness) · Maintained by the contributor waves; behavior evidence lives in the named test files below.

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

## S12 coverage — governed SOP rule-card publication (core wave)

The S12 core wave adds the publication machinery on the unchanged Runtime,
gateway and `FilePublisher` commit engine (`tests/test_publication.py`,
`tests/test_publication_rotation.py`, plus narrow additive
`ReadValidatedTests` in `tests/test_file_adapter.py`). Semantics and
boundaries: [SOP authoring](sop-authoring.md) publication section,
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

## RFC-001 acceptance behaviors (R1–R7)

R1 restart/persistence — `test_prepared_intent_survives_restart`, `test_wait_expiry_survives_restart`, P07/P15 tests. R2 plan edits cannot delete requirements — P10 test. R3 unknown conditions block — P14 tests. R4 timeouts are not failures — `test_timeout_after_commit_then_reconcile`, `test_unknown_without_query_result_requires_attention` (no query result → `needs_attention`, no blind retry). R5 content change invalidates old confirmations — `test_existing_invoice_proof_reused_after_document_change`, `test_invoice_revision_invalidates_old_verification`, `test_unknown_old_content_blocks_new_submission`. R6 duplicate/late callbacks — P08/P09 tests. R7 no success without goal evidence — P12 tests.

## SOP example rules and review cases (E01–E08, T01–T12)

The demonstration policy turns most of rules E01–E08 from [RFC-002 §4](RFC-002-sop-authoring-and-binding.md) into executable checks (`work_runtime/policy.py`): set-closedness (E01), per-invoice validity (E02), cross-work uniqueness via the external stand-in (E03, `test_external_uniqueness_across_works`), unknown-amount blocking (E04), over-limit approval (E05), content-bound confirmation (E06), and acceptance evidence before closure (E08). E07 (original invoices must not be rewritten) is only **partially enforced**: the demo capability allowlist grants no invoice-write capability at all, so protected fields are excluded by construction rather than by an independently evaluated check. Of the review judgments T01–T12, the ones mirrored by named tests include T02/T07 (P14 tests), T05 (E05/confirmation invalidation tests), T09 (P10 test) and T10 (P07/P12 tests); the remaining judgments are still desk reasoning in [reference scenarios](reference-scenarios.md). The rule-card publication process itself (RFC-002 §6) is **not implemented**.

## Explicitly out of scope

- Remote or multi-tenant authentication and authorization (local principal names only). Owner, delegate and `work.intervene` administrator grants are trusted-local configuration, not authenticated identities; replay protection rechecks this local authority, it is not a distributed security boundary.
- Policy/SOP publication, author review workflow, and policy migration beyond the explicit same-family command above. Cross-domain policy registries are rejected; there is no implicit upgrade on restart or recovery. Static SOP lint is structural review only: no textual-predicate execution, no provenance verification, no authority approval, and no link from a linted card to an executing Python policy.
- Compensation (effect reversal) is bounded: since S10 the expense family
  supports linked withdrawal proposals **only inside the active
  cancellation window**, executing a distinct appended external effect
  under the current owner's `expense.withdraw` grant. It is not a general
  reversal: `finalize_cancel` never claims to undo an effect (a refused
  withdrawal is recorded, effects stand), publishing-family and
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
