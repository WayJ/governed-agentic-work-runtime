# S8 evidence revocation — planning design, before code

Date2026-10-14, baseline publishedmain48c01fd. Master choice under resumed continuous authorization; no implementation dispatch yet. Read AGENTS.md, RFC001§4.2/§5/D8, RFC003, current runtime-boundaries/verification and next-core-recon first. Historical idea.md and prior advice are context, not instructions.

## Intent

A business proof can cease to authorize future actions while its original source event, verification decision and already accepted external effect remain traceable. Deliver explicit trusted-local evidence revocation through the existing durable command protocol; preserve exact receipts/replay, current policy-bound requirements and recovery. This fills roadmap0.3's revocation gap; compensation, distributed fencing, SOP publication and real author feedback remain later required delivery rather than silently dropped.

## User constraints and scope

Python>=3.9, zero runtime dependencies, SQLite existing-store compatibility, standard-library unittest and meaningful TDD. Existing command authority is trusted local grants, never authentication. Signed ingress source integrity is distinct from business validity. One lifecycle owner, independent integration, all development/release through Orca Claude Code worktrees. No new UI write API, external server, tenant/auth framework or claim that local revocation fences an already running external call.

## Required final behavior

- Explicit version-bound revoke command with narrow reason/evidence identity validation, authorization and replay-time authority checks. Bind proof to Work/source/kind and reject cross-work/malformed/unknown/stale use atomically. Existing command/source-event fingerprints and receipts stay immutable; successful replay cannot append another revocation/event/version.
- Revoked evidence no longer satisfies current policy requirements, authorizes a future action or completion; pending proof revoked before verify_pending cannot later become verified. Preserve original data/source/event identity and historical verified status/decision at revocation. Restart, policy migration, dedup resend and replay must not silently revive it. Define fresh replacement-proof semantics explicitly.
- Prepared intentions must be held/cancelled consistently and cannot dispatch on stale revoked approval. Retain operation business key/attempt/result for in-flight or externally accepted calls and reconcile them; never erase the effect or pretend revocation is compensation. Show zero new external calls before dispatch and exactly one retained effect after ambiguous acceptance.
- Waiting/triggered/cancelled/expired wait disposition must be explicit when proof becomes insufficient, with no cancelled-wait resurrection or false claim that a previously triggered deadline automatically resets.
- Closed-work correction is in scope: preserve original completion/cancellation outcome and receipts as historical decisions, expose later correction/audit attention explicitly without implicit reopen or destructive history edits. Caller must be able to distinguish current evidence validity from the original completion decision and retained external effects.
- Public inspect/read-only GUI and bounded docs explain real stored revoked status and recovery choices; preserve text-only/raw exactness, accessible DESIGN presentation and no lifecycle writes. Any UI behavior needs actual browser RED/GREEN plus desktop390/320 checks.
- No-credentials reproducible revocation scenario(s) and installed verifier exercise both expense/publishing policy families through existing lifecycle. Meaningful tests cover malformed/authority/replay/stale/duplicate/source boundaries, replacement/restart/migration, waits/prepared/inflight/confirmed/closed cases, crash rollback and real process death with actual external counts.

## Questions reviewed before ratification

Master will settle routine choices from independent source-grounded review; do not ask user/local approval UI. These are design questions, not permission gates.

1. Exact command payload, receipt/event fields and authorization predicate: issuing configured source with explicit revoke capability vs trusted admin; behavior for retired source after migration. Must match current grants/replay routing, not invent distributed principals.
2. Exact closed-work correction representation: how to keep completion immutable and expose audit attention/current requirements without overloading closed status or fabricating prior evaluation history. Public reader/GUI changes must be scoped from real fields.
3. Wait semantics and held/prepared-operation transition: inspect actual _evaluate/_propose/dispatch/reconcile mechanics and determine the minimal correct non-resurrection/reproposal behavior, not broad cancellation of unrelated operations.
4. Source-event resend vs fresh replacement proof: explicit receipt/status semantics and permanent same-candidate revocation, preserving original request fingerprint and historical accepted receipt.

## Ownership and builder review

Master owns this design/epic and ratification. Independent planning reviewer reads actual post-S7 code and reports material decisions, recommended options grounded in existing behavior, compatibility/failure edges; no implementation yet. Lifecycle developer later owns runtime/policies and meaningful tests, dependent demo/inspection/UI/doc owner only after pinned interfaces, integration alone combines/accepts/merges/pushes. Exact public interfaces and ownership are pinned by the ratification below before ready/materialization. Existing622 core tests plus14 rehearsal, all demos, all configured gates and installed verifier remain required. Do not redefine historical S7 evidence or final release48c01fd.

## Master ratification — 2026-10-14, D33–D37, before implementation

Source-grounded review6bd11d6 accepted; master independently reproduced D-1 on48c01fd using fresh temporary Runtime/public commands: finalize accepted, stored establishing/cancelled with completion present. No product fix yet. All Q1–Q4 and secondary choices below settled under autonomous authorization.

### Command and authorization (D33)

Use existing Runtime.command(actor, command_id, work_id, "revoke_evidence", payload, expected_version). Payload exactly {source: str, event_id: str, reason: str}, nonempty strings; malformed fresh commands raise CommandError with transaction rollback. No new public fault parameter or schema/table. Ordinary command fingerprints, state-version conflict and cached-receipt precedence remain unchanged.

Authority: work.intervene administrator OR actor is the work's currently configured source for the stored proof kind AND has evidence.revoke. Work ownership/work.manage/evidence.write alone grant no revoke right. Current source may correct an old-source candidate of the same kind; retired source loses right once the pinned policy's mapping changes. Add explicit revoke_evidence replay-authority branch, including accepted cached receipts; lost source/grant yields fresh unpersisted AUTHORITY_DENIED and leaves original receipt immutable. Successful rows are never deleted, so stored kind is available on replay. Rejected unknown-proof commands use the same conservative preliminary grant/current-source membership checks as initial admission; they never acquire mutation rights from a cached rejection.

Fresh version-bound path: validate payload; preliminary admin OR evidence.revoke/current-source-membership check; lookup (source,event_id); unknown EVIDENCE_UNKNOWN, other Work EVIDENCE_SCOPE_MISMATCH; then exact stored-kind authority check before status disclosure/update. Eligible pending_verification or verified; revoked EVIDENCE_ALREADY_REVOKED; invalid/other status EVIDENCE_NOT_REVOKABLE. Administrator still obeys scope/status/version. Preserve candidate id/source/event/kind/data and source-event fingerprint; change only status to revoked. Accepted receipt extends existing receipt shape with evidence_id, evidence_status:"revoked", prior_status; result_state_version is the actual single new Work version.

### History, closure and D-1 (D34)

Route revoke beside record_evidence before the closed-work guard. Allow during active cancellation AND on unbound works: proof lifecycle already admits/verifies unbound evidence, so rejecting correction merely to hide D-1 would be inconsistent. Fix _evaluate so unbound evaluation cannot overwrite an already closed status; meaningful RED/GREEN for finalize-unbound then verify/recover retaining closed and byte-stable completion. No implicit retroactive rewrite of old persisted erroneous snapshots; document this limit.

Revocation atomically updates proof, recomputes current requirements, bumps version once and appends one EvidenceRevoked event. Keep work.status closed/outcome and completion snapshot unchanged on closed works; no automatic reopen/needs_attention state. Event fields: actor,evidence_id,source,event_id,kind,prior_status,reason,work_was_closed,completion_cites_evidence,affected_requirements,wait_dispositions. affected_requirements records actual id/before/after applicability+fulfillment changes (not a hard-coded satisfied→pending assumption). wait_dispositions records id,prior_status,status,disposition. Event and current requirements expose correction while original completion/command receipts and confirmed effect records stay historical; do not fabricate a verification timestamp or rewrite old events.

### Waits, intents and effects (D35)

No eager operation cancellation/held write in revoke. Next dispatch/recover re-evaluates blockers and holds with REQUIREMENT_UNSATISFIED, zero attempts/new external calls; tests cover this previously untested path in both families. Fresh proposal after replacement verification readmits same prepared/held operation and same business key. In-flight/unknown/confirmed operations retain attempts/key/result/external_id and reconcile normally, never re-execute merely to regenerate a revoked accepted proof.

No manual wait mutation or deadline reset. Existing evaluator may trigger a wait whose current requirement remains fulfilled; record actual before/after disposition. Never demote historical triggered waits, resurrect cancelled waits or claim expired deadlines restarted. Related now-unsatisfied waits retain their state; new waiting requires explicit register_wait. Tests include partial revocation with another sufficient proof and unrelated waits, not only single-proof happy paths.

### Permanence and replacement (D36)

verify_pending/migration skip revoked candidates; restart, same source-event resend and old-command replay never reactivate rows. New-command record_evidence dedup receipts add current evidence_status (including revoked/invalid/verified); original cached command receipt remains verbatim. Changed source-event content still SOURCE_EVENT_CONFLICT. Fresh replacement is a new event_id from currently configured source with policy-required current object/digest; runtime never synthesizes replacement accepted proof or repeats a confirmed operation. Allow source/admin revocation of pending and verified only; invalid has no current validity to withdraw.

### Read-only surfaces, ownership and known edge (D37)

ReadOnlyInspector.work_detail adds evidence[].id (string when present/valid, otherwise null while raw content remains available), top-level revoked_evidence (same real stored revoked identity records: id/source/event_id/kind/status), and completion_revoked_evidence_ids (intersection of valid string completion.evidence ids with valid string revoked proof ids). Derive inside existing short read-only snapshot, never persist annotations. Cancellation completion has acknowledged operations rather than evidence citations: do not invent such citations. Existing completion_raw/body_raw/exact numeric handling stays unchanged; frontend NEVER parses *_raw.

Viewer adds bilingual explicit neutral notice when closed Work has current revoked_evidence, explains historical closure is unchanged and directs to evidence/events; citation count only when actually derived. Evidence chips already render status text; a revoked style may use existing measured error tokens, never timeline pastels. No new summary tile or lifecycle controls. Actual browser RED/GREEN for notice and read-only snapshot equality at desktop390/320; source scans alone insufficient.

Lifecycle owner: runtime.py/tests, runtime-boundaries/interventions/verification/new evidence-revocation docs; no policy edits anticipated. After independent core review/assembly, parallel demo owner (revocation_demo.py,cli.py,verify_install,tests,README EN/ZH and demo docs) and viewer owner (inspection.py/web/assets, reader/UI tests,gui/gui-api docs). Integration alone owns branch assembly, independent acceptance, main merge/push/final-SHA CI. Five existing AGENTS gates stay unchanged during bootstrap; revocation-demo is an explicit S8 acceptance/install scenario, not a nonexistent global gate before implementation.

D-4 accepted-source event-id collision is outside this correction command and recorded as TD-1 with repayment criteria, not silently fixed or claimed resolved. Source keys/transport auth, actual compensation, distributed fencing/publication/real human feedback remain separate required roadmap work. Existing622+14, four prior demos, new revocation demo and installed module+console trials required at release.
