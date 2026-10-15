# SOP publication withdrawal — candidate design (DRAFT)

Status: **DRAFT, pending master ratification and the independent design
review the master dispatches next.** This is the candidate design for the
ratified D63 deferral: *design publication withdrawal on the S8
evidence-revocation model — withdraw current validity, never rewrite
history* ([sop-authoring.md](../../sop-authoring.md) D63;
[roadmap.md](../../roadmap.md) 0.4). It allocates no epic, sprint, ADR or
ledger entry; the master owns roadmap and ratification. Nothing here is
implemented. Local decision numbering is `SWD-1…SWD-13` (no collision with
global `D`/MASTER numbers, currently up to D66 from S12 — recon F22; next
free D67). Grounding evidence — fresh baseline gates at
`860571c5c89b7dd22dc2be2567d7870c9b093f66`, code cites and public-API
probes P1–P2 — is recorded in the
[recon note](../../../.agents/notes/2026-10-16-s13-design-recon.md);
findings F1–F25 live there and the load-bearing subset is cited inline.

## 1. Problem (grounded)

S12 shipped governed publication: one immutable hash-named artifact per
`(policy_id, version)`, behind a signed version-bound approval, with a
fail-closed loader and no Runtime wiring (D54–D66). What S12 deliberately
did not ship is any way for a published version's **current validity** to
end:

- The store is append-only with no delete or rewrite path at all (F4);
  "rolling back" a publication means publishing a corrected new version
  (D63, [sop-authoring.md](../../sop-authoring.md) 186–188).
- S8 `revoke_evidence` already withdraws the current validity of the
  publication work's **runtime proofs** on this very family — but never
  reaches the store: the committed artifact stands (S12 design §10;
  probe P1/F15).
- The loader answers only "absent / corrupt / mismatched / valid" — it has
  no concept of a version that was published and then withdrawn (F6).

So an operator who must stop a published card version from being treated
as the card of record has, today, no truthful mechanism short of
filesystem surgery (which the loader turns into fail-closed errors, not
into validity). Roadmap 0.4 names this as separately-designed future work
(F2). The design question is what "withdrawal" can honestly mean for an
immutable, hash-named, directory-scoped store — answered on the S8 model:
change **current validity**, preserve **history and artifacts**, expose
the correction in current data, and claim nothing distributed.

## 2. Goals and non-goals

**Goal (smallest useful slice):** the current validity of one published
`(policy_id, version)` can be withdrawn through the same governed command
protocol every other external effect uses, behind a signed, version-bound
approval — producing a **second immutable hash-named artifact** (the
withdrawal record) in the same trusted-local store directory that the
fail-closed loader honors with a **distinct bounded error**, while every
committed artifact, receipt, proof and event remains byte-identical. Zero
changes to `runtime.py`, `ingress.py`, `authoring.py` or `FilePublisher`
semantics; publication.py grows additively (key, wrapper, policy
extension, loader step).

**Non-goals (explicit):**

- **No deletion, no un-publish, no mutation.** Artifacts are never
  removed or edited; withdrawal adds a record, it never rewrites the
  store (F4 makes anything else structurally illegal anyway).
- **No history rewrite anywhere:** receipts, proofs, events, closure
  snapshots stay immutable (S8/S12 discipline, unchanged).
- **No un-withdrawal / reinstatement of the same version.** Correction is
  forward-only: publish a new version (RFC-002 §6, F23; S12 §10's
  "there is no un-publish" extended symmetrically).
- **No fencing of already-bound consumers.** The Runtime never consults
  the store (D62): executing policies, pinned cross-checks already done,
  and in-flight works are unaffected by a withdrawal — the analog of S8's
  "no external fencing of an in-flight call" limit, stated not hidden.
- **No compensation semantics.** Withdrawal is not an S10 reversal: the
  published artifact stands, no `compensates` link, no `"withdrawn"` proof
  kind (F13 terminology disambiguation).
- **No distributed revocation, no tenant authentication, no TLS/KMS/
  network, no revocation-propagation or freshness protocol.** Trusted
  local configuration only, exactly as S8/S11/S12.
- **No approval quorum or approval-identity envelopes** (separately
  designed 0.4 future work, roadmap line 37); **no UI change** (F25);
  **no new global gate**; **no card→policy compilation** (D62 unchanged).

## 3. What withdrawal IS

A withdrawal is **one committed withdrawal-record artifact in the same
append-only store directory**, identified in the same three aspects:

| aspect | definition | grounding |
|---|---|---|
| artifact identity | `withdrawal_key(policy_id, policy_version) = "sop-withdrawn:" + digest([policy_id, policy_version])` — the D56 digest form verbatim on the same identity basis; committed path `sha256(key)` hex as always | `publication.py:35-45` pattern (F3); SWD-2 |
| content identity | the record document is a **closed, deterministic** shape: exactly `{discriminator, policy_id, policy_version, published_digest}` — an explicit discriminator field (e.g. `"sop.withdrawal"`), the target identity, and the `content_digest` of the publication artifact being withdrawn. Deterministic given the target, so the same withdrawal is byte-idempotent; **reason/free text never enters the record** (it would break replay stability) | `FilePublisher.execute` replay/refusal (F4); D59's audit-in-the-runtime precedent; SWD-3 |
| version | the withdrawn `(policy_id, policy_version)`; one withdrawal identity per version per directory, one per version per database (business key = the withdrawal key) | D66 mechanics (F20); SWD-4 |

What a withdrawal is *not*: it is not a tombstone in the publication
artifact (impossible — F4), not a registry entry in any database (the
loader must see it without a Runtime), not a revocation of the publication
work's proofs (independent acts, §7), and not a compensation (§2).

**Semantics, on the S8 model:** withdrawal changes the **current
validity** of the version as the read surface reports it; the artifact,
the publication receipts, the approval and acceptance proofs and all
events remain exactly as they were. As with S8's closed-work correction,
the historical decision (this version was published, approved, accepted)
stays true; what changes is that the version is no longer the card of
record to serve.

## 4. Who may withdraw

Trusted-local principals, two surfaces — deliberately not merged:

- **Governed write path (SWD-5):** a `sop.withdraw` capability Work in the
  same `sop-publish` family and database, admitted only behind a signed,
  version-bound **`card_withdrawal`** envelope whose `data` is exactly
  `{"digest": <published content digest>, "policy_version": <version>}` —
  D58's shape and discipline verbatim (approval is evidence, not a grant
  check), from the configured authority source. `evidence_sources` gains
  `"card_withdrawal": "sop-owner"`. The `digest` binds the withdrawal to
  the **exact published content** (the target artifact's
  `content_digest`), so the authority approves withdrawing precisely what
  was published — the operator's request document must carry the same
  digest, and a wrong-digest approval leaves the requirement pending
  exactly as S02 does today.
- **Runtime-side correction (existing, unchanged):** the S8
  `revoke_evidence` admin/source path already reaches this family's
  proofs (probe P1/F15: a `work.intervene` administrator can revoke the
  `card_approval` and even the runtime-written `accepted` proof on the
  closed publication work). That withdraws *runtime* current validity —
  requirement satisfaction — and never the store version (S12 §10).

**Default posture (SWD-5, open Q2):** there is **no admin bypass of the
signed approval** on the governed write path. Requirements are
evidence-driven only; satisfying W02 by grants would contradict the
ratified D58 discipline ("the approval is evidence, not a grant check").
The administrator's store-side reach is operational (they hold the
configuration), not protocol-level. The asymmetry with S8 — where
`work.intervene` may revoke evidence directly — is intentional: S8
revokes a runtime-internal row, while S13 commits a new external artifact
through the governed effect path every external effect uses.

**Terminology (SWD-10):** "withdrawal" names the publication act;
S10's `"withdrawn"` proof kind keeps its compensation meaning
(`runtime.py:942-961`, F13). No `withdrawn` proof kind is created; the
withdrawal operation is a plain forward effect with no `compensates`
link, and its store acceptance is recorded as an ordinary `accepted`
proof under the family's `sop-store` source.

## 5. What the loader does post-withdrawal (fail-closed, D62 extended)

`_read_publication_artifact`'s validation chain
(`publication.py:108-134`) gains exactly one step, **after** full
artifact validation and **before** returning (SWD-6):

1. Read the withdrawal record: `read_validated(withdrawal_key)` (absent →
   `None`, F5).
2. `None` → the version is valid; return (today's behavior, unchanged).
3. A record that validates and whose `(policy_id, policy_version)` match
   the request and whose `published_digest` equals the artifact's
   `content_digest` → raise the **new distinct bounded error**
   (`WITHDRAWN_MESSAGE`, class wording: *this published version is
   withdrawn; corrected content requires a new version*).
4. A withdrawal record that is **corrupt or does not bind this artifact**
   (parse/shape failure, identity mismatch, digest mismatch) → a distinct
   bounded fail-closed error (`WITHDRAWAL_RECORD_INVALID_MESSAGE`): the
   version is under dispute and is **never silently served as valid** —
   the same refuse-don't-guess posture as MD-4's foreign-content refusal
   (F6).

The bounded, distinguishable error classes become six: absent (including
missing directory), corrupt artifact, digest mismatch, identity mismatch,
**withdrawn**, **invalid withdrawal record**. Nothing degrades, nothing
falls back.

- **`pinned_card`** inherits: the load itself raises the withdrawal error
  before the pin comparison runs (`publication.py:160-162` order) — a
  withdrawn version fails closed regardless of pin match.
- **Audit read (SWD-6):** an additive `withdrawal_record(directory,
  policy_id, policy_version)` returns the validated record or `None` so an
  operator can see *that* (and, via the governed ledger, who/when) a
  version was withdrawn. There is deliberately **no `allow_withdrawn`
  override** on `load_published_card`/`pinned_card` — current validity is
  not negotiable at the loader; audit uses the dedicated function.
- **Order note:** a version whose artifact is absent reads **absent**
  even if a withdrawal record exists (the artifact read comes first) —
  deleting files is already outside the trust boundary (§9).
- **No Runtime wiring change:** the Runtime still never consults the
  store (D62); withdrawal fences no executing policy or in-flight work.

## 6. The governed flow (write path, same family, second capability)

**Why the same family and database (SWD-4, open Q1):** one policy family
per database (F19); a second family would split the publication ledger —
the withdrawal audit belongs beside the publication audit in the same
evidence store, the same event history and the same inspect surface.

**The completion-gate constraint (F18) forces document-shape
discrimination:** `request_completion` blocks on every unsatisfied
requirement of the work, capability-blind (`runtime.py:422-433`), and
works carry no capability. So the family's `evaluate`/`validate_document`
discriminate on the **work document's shape**:

- **Card document** (today, unchanged — D57): S02 approval / S03
  acceptance. Publication works behave exactly as shipped; nothing about
  their admission, blockers, keys or completion changes.
- **Withdrawal request document** (new closed shape): exactly
  `{discriminator, policy_id, policy_version, published_digest}` (§3).
  `validate_document` accepts a lint-clean card **or** a well-formed
  withdrawal request; anything else is a bounded, unpersisted
  `ValueError` (the house document-gate convention,
  `runtime.py:354`, `policy.py` Protocol). `evaluate` produces only:
  - **W02** — the configured authority must have signed a
    `card_withdrawal` whose `data.digest` equals the request's
    `published_digest` and whose `policy_version` equals the request's
    version (D58 mirror; wrong-digest/wrong-version approvals leave it
    pending);
  - **W03** — the store must have accepted the withdrawal record
    (runtime-written `accepted` proof, `event_id` = the withdrawal
    operation id), **excluded from blockers exactly like S03**
    (`publication.py:251-257` pattern).
- `action_blockers` keeps its current shape — exclude the
  store-acceptance rule (S03/W03) — and the disjoint requirement sets
  make capability cross-talk impossible: a `card_approval` never
  satisfies W02 and a `card_withdrawal` never satisfies S02 (pinned by
  tests, §12).
- **`operation_key("sop.withdraw", work)` = the withdrawal key (SWD-4):**
  one withdrawal identity per version per database. The **D66 pinned
  order is inherited verbatim** (F20: blockers before business-key,
  `runtime.py:668-690`): a second withdrawal work is first refused
  `REQUIREMENT_UNSATISFIED` while its own approval is missing, and only
  after it records and verifies its own approval does the persisted
  `OPERATION_CONTENT_CONFLICT` surface (SWD-9; tests pin this).
- **Grants:** the proposing actor needs `sop.withdraw` in grants
  (`runtime.py:640-643`); the approver principal stays `sop-owner` with
  `evidence.write` (demo grants extend the agent's set only).

**Store adapter (SWD-8):** an additive `SopWithdrawalStore` wrapper over
the **same** `FilePublisher(directory)` — the D55 blast-radius pattern,
not an extension of the shipped `SopPublicationStore` contract —
declaring `actions=("sop.withdraw",)`, keyed uniqueness on the withdrawal
key, and one withdrawal-specific refusal: `execute` refuses bounded when
the **target publication artifact is absent** or its `content_digest`
does not equal the record's `published_digest` (withdrawing nothing
published, or something other than what was published, is refused before
any commit). `lookup` delegates verbatim. Replay semantics are
FilePublisher's: same key + same deterministic record → byte-identical
winner receipt.

The end-to-end flow is the governed spine unchanged: `create_work`
(withdrawal request as document) → `bind_contract` → signed
`card_withdrawal` through the unchanged `SignedEvidenceGateway`
(`ingress.py:270-325`; `"card_withdrawal"` is an ordinary signed kind —
`RESERVED_KIND` is only `"accepted"`, F21) → `verify_pending` →
`propose_action("sop.withdraw")` → `dispatch` through
`SopWithdrawalStore` → `reconcile` on uncertainty → `request_completion`.
A response lost after the record commits reconciles the original
withdrawal key in one attempt, never resending (the S12 story verbatim on
a second key).

## 7. Interaction with the accepted proof and evidence store

The task question — runtime command reusing revoke machinery,
publication-store operation, or both — answers **store operation, with
existing revoke machinery composing unchanged beside it**:

- **Withdrawal is a governed store operation** (§6): the external effect
  is the withdrawal-record artifact; the runtime evidence it produces is
  an ordinary `accepted` proof under `sop-store` (`event_id` = the
  withdrawal operation id) satisfying W03. This is the only act that
  changes what the **loader** reports.
- **S8 revocation remains available and independent** (probe P1/F15): an
  administrator may revoke the original work's `card_approval` (S02
  pending) or `accepted` proof (S03 pending, closed-work correction with
  completion byte-identical). These acts never reach the store, and
  withdrawal never auto-revokes them: the publication *happened* — its
  history stands (S8's "never edits history" applied symmetrically).
- **No automatic coupling in either direction** (SWD-7): withdrawing a
  version does not touch the publication work's proofs; revoking proofs
  does not withdraw the store version (S12 §10's stated seam, now
  bounded by the record). An operator who wants both truths changed
  performs both acts; each is separately receipted and auditable.
- The composition is currently **unpinned by tests** (F16: zero `revoke`
  coverage in `tests/test_publication*.py`) — the sprint pins it (SWD-13,
  §12).

## 8. Replay, re-resubmission and re-publication after withdrawal

Three existing layers compose; withdrawal adds **no new write-path
machinery** (SWD-7):

1. **Within one database — re-publish the same version:** a new work
   proposing the same `(policy_id, version)` hits the existing
   business-key rule: the publication operation exists under the same
   key from another work → persisted `OPERATION_CONTENT_CONFLICT`
   *after* the second work's own approval (the D66 order,
   `runtime.py:668-690`; pinned by `tests/test_publication.py:563, 579`).
   Withdrawal changes nothing here and needs to: the version's validity
   question is a **read-surface** question, and the loader stays closed.
2. **Cross-database / shared directory:** probe P2 (F16/F17) proves a
   store-layer `execute` refusal **cannot fence** re-publication —
   `reconcile` resolves `confirmed_succeeded` from the standing artifact
   via `lookup` (`runtime.py:1105-1115`), and poisoning `lookup` would
   violate authoritative-by-key. Therefore no such refusal is attempted:
   a re-publish after withdrawal commits **nothing new** (FilePublisher
   replays the winner, F4) and the loader still fails closed on the
   withdrawal record. The only new artifact is the redundant governed
   receipt in the second database's own ledger — visible there, harmless
   to the store. This is an honest operator-discipline boundary, not a
   gap an adapter trick should "fix".
3. **Re-withdrawal / withdrawal replay:** same withdrawal key +
   deterministic record → byte-identical winner receipt across processes
   and restarts (idempotent; this is why the record carries no reason).
   A second withdrawal work in the same database → `REQUIREMENT_UNSATISFIED`
   first, then persisted `OPERATION_CONTENT_CONFLICT` (D66 order, SWD-9).
   A withdrawal request with a different `published_digest` under the
   same identity → the wrapper's target-binding refusal (§6) and, at the
   raw adapter, the same-key-changed-content `ValueError` — zero
   overwrite either way.
4. **Command dedup:** `(actor, command_id)` replay returns the stored
   receipt while authority holds; changed content under the same command
   id is `COMMAND_ID_REUSED` (`runtime.py:263-272`) — unchanged.

**Un-withdrawal is a non-goal (§2):** a withdrawn version is never
reinstated under the same version string; corrected content publishes as
a new version (RFC-002 §6). Reinstatement machinery would also make the
loader's withdrawal answer non-monotonic for no governed gain (open Q6
records the default).

## 9. Keyring rotation and rollback limits (honest)

- **Rotation (unchanged S11/S12 semantics):** `card_withdrawal` envelopes
  are signed by the `sop-owner` keyring; rotating by reconstruction
  refuses an old-key envelope `EVIDENCE_KEY_RETIRED` (retained, past its
  window) or `EVIDENCE_AUTHENTICATION_FAILED` (dropped) with zero intake
  writes; the same `command_id` re-signed under the new key replays the
  original receipt verbatim; rotation acts never touch store artifacts or
  runtime history (F21; `ingress.py:304-311`). A pre-rotation withdrawal
  approval still verifies after rotation (key-agnostic fingerprints).
- **What a configuration rollback revives (SWD-10):** only *authority for
  future acts* — a rolled-back keyring can sign new `card_withdrawal`
  approvals, and a rolled-back grants set re-admits `sop.withdraw`
  proposals on replay (replay reauthorization, `runtime.py:298-338`).
  It cannot delete or alter any committed withdrawal record or artifact
  (the store is append-only), cannot un-write a receipt, and cannot make
  the loader serve a withdrawn version while the record stands. This is
  the S11 "config-only trust" limit restated for withdrawal.
- **Filesystem rollback is operator misuse, outside the boundary:**
  deleting the withdrawal record makes the loader serve the version as
  valid again; deleting the artifact makes it read absent; editing either
  turns into fail-closed errors (F4/F6). The directory is trusted local
  configuration — no tamper-evidence, no power-loss or hostile-filesystem
  claim (inherited [file-adapter.md](../../file-adapter.md) boundaries).
- **Shared-directory discipline (MD-4 adjacent):** a withdrawal record
  committed by raw adapter use, or by a database that did not publish the
  version, is honored by the loader — the directory is the shared truth
  and the loader cannot distinguish authors. Each database's ledger
  records its own acts; two databases reconciling one directory keep
  failing closed exactly as MD-4 pinned. Recorded as an accepted
  operator-discipline boundary, mirroring the S12 ratification's MD-4.

## 10. Alternatives considered (rejected options)

| alternative | why rejected |
|---|---|
| Delete or truncate the publication artifact | destroys the content of record and the audit; the loader would read "absent" — indistinguishable from never-published; structurally outside FilePublisher's pinned semantics (F4) |
| In-place tombstone field / receipt status change in the artifact | not a legal state of the store: `_validated_artifact` pins `artifact_version == 1`, exact shape and `receipt.status == "accepted"` (`file_adapter.py:181-199`); mutation is rewrite |
| Non-hash sidecar file or subdirectory beside the artifact | a second naming scheme outside the hash discipline; weaker race/crash semantics; no governed write-path fit (FilePublisher commits hash-named artifacts only) |
| Separate withdrawal-registry directory | splits truth across two configured directories; doubles the trust boundary and the demo/install surface for no guarantee gain |
| Runtime-database registry (table) as the withdrawal truth | invisible to the pure loader and to other databases sharing the directory (D62 keeps the loader Runtime-free); probe P1 shows proof revocation already fails to reach the store this way |
| Store-layer `execute` refusal as re-publication fencing | proven unenforceable: `reconcile` resolves from `lookup` (probe P2/F16); poisoning `lookup` violates authoritative-by-key |
| Reuse S8 `revoke_evidence` as the withdrawal itself | it mutates runtime rows only; the store version stays valid to every reader (S12 §10); revocation has no artifact to show the loader |
| Withdrawal as S10 compensation (`compensates` link, `"withdrawn"` proof) | wrong semantics: compensation reverses an effect inside a cancellation window; withdrawal withdraws validity, the artifact stands, no window exists (F13) |
| A second policy family (and database) for withdrawal | splits the publication/withdrawal ledger across databases (F19); two runtime stores to run and inspect for one story |
| Capability-keyed requirement sets without document discrimination | breaks the capability-blind completion gate (F18): a W02 requirement on card works would block publication completion forever |
| Reason/free text inside the withdrawal record | breaks determinism → re-withdrawal with a different reason becomes same-key-changed-content conflict instead of idempotent replay; the audit belongs to the runtime ledger (D59 parallel) |
| `allow_withdrawn` override on the loader | makes current validity negotiable at the read surface; audit gets a dedicated function instead (SWD-6) |
| Un-withdraw / reinstate machinery | non-monotonic loader validity for no governed gain; forward-only correction is the ratified RFC-002 §6 discipline (open Q6 default) |

## 11. Open questions (each with a default recommendation)

| # | question | default |
|---|---|---|
| Q1 | Same `sop-publish` family/database with a second capability, or a separate withdrawal family? | **Same family** — one ledger, one inspect surface, one demo store; document-shape discrimination is explicit and testable (F18). |
| Q2 | Should a `work.intervene` administrator bypass the signed approval on the governed path (S8 precedent)? | **No** — requirements stay evidence-driven (D58 discipline); the admin's runtime-side reach via `revoke_evidence` already exists (P1/F15). Master may still ratify an admin path as a follow-up authority-model change. |
| Q3 | Distinct withdrawal authority (separation of duties) instead of `sop-owner`? | **`sop-owner` now** — single configured source per kind (S12 Q2 precedent); a distinct principal is a config/authority-model change, separately designed. |
| Q4 | Embed approver/actor identity or timestamp in the record (envelope v2)? | **Defer** — determinism governs the record; the runtime evidence/command ledger is the audit (D59 parallel, S12 Q1 defer ratified). |
| Q5 | Loader override to read withdrawn content? | **No override**; additive `withdrawal_record()` audit function only (SWD-6). |
| Q6 | Reinstatement (un-withdraw) of a same version? | **Non-goal** — forward-only; corrected content is a new version (RFC-002 §6). |
| Q7 | Extend `SopPublicationStore.contract` in place vs a separate `SopWithdrawalStore`? | **Separate wrapper** — D55 blast-radius precedent; the shipped contract and its tests stay untouched. |
| Q8 | Pin the S8 × sop-publish revocation composition now? | **Yes** — real, load-bearing, currently unpinned (F16); cheap tests, high honesty value (SWD-13). |
| Q9 | Exact key prefix (`"sop-withdrawn:"`), discriminator field name and message wordings? | **As drafted**; master may reword at ratification without semantic change. |
| Q10 | Does the sprint owe a UI/demo surface? | **Demo chapter in `publication-demo`, no UI change** — works/evidence/operations already render generically, including revoked statuses (F25, D64 precedent). |

## 12. Proposed sprint shape (pending master ratification)

One bounded sprint, two waves (S11/S12 precedent), `wip_limit 1`, TDD with
recorded RED/GREEN evidence per AGENTS/supervibe. Master assigns global
D-numbers (**next free: D67**) to the ratified SWD subset.

**Decisions pending ratification:** SWD-1 withdrawal = second immutable
hash-named record artifact in the same directory · SWD-2 withdrawal key =
`"sop-withdrawn:" + digest([policy_id, policy_version])` · SWD-3
deterministic closed record document, no free text · SWD-4 same family /
second capability `sop.withdraw`, document-shape-discriminated W02/W03,
operation key = withdrawal key · SWD-5 signed version-bound
`card_withdrawal` `{digest, policy_version}`, no admin bypass · SWD-6
loader: distinct `WITHDRAWN` bounded error, invalid-record fail-closed
error, `withdrawal_record()` audit read, no override · SWD-7 no write-path
fencing; validity lives at the read surface · SWD-8 `SopWithdrawalStore`
wrapper with target-exists/target-digest refusal · SWD-9 D66 order
inherited and pinned for withdrawal works · SWD-10 no un-withdrawal, no
compensation semantics, no Runtime wiring, no UI change · SWD-11 demo
chapter + installer stage, no new global gate · SWD-12 doc set +
master-added doc_sync_map rows · SWD-13 pin the S8 × sop-publish
composition.

**Story breakdown:**

1. **Withdrawal store surface:** `withdrawal_key`, the record shape,
   `SopWithdrawalStore` (target refusal, delegation); adapter-level
   tests: idempotent replay, same-key-changed-digest refusal, absent
   target refusal, exactly-one-record census.
2. **Loader integration:** the withdrawal check + two new bounded errors,
   `withdrawal_record()`; fail-closed matrix tests (valid / absent /
   withdrawn / invalid record / pin interaction).
3. **Governed flow:** document shapes in `validate_document`, W02/W03,
   capability grants, dispatch/reconcile/completion, response-loss
   recovery, D66-order tests for withdrawal works, cross-approval
   isolation (`card_approval` ≠ W02, `card_withdrawal` ≠ S02),
   completion-gate regression (publication works complete unchanged).
4. **Composition + rotation:** pin S8 `revoke_evidence` on the sop-publish
   family (approval + accepted proof, closed-work correction, artifact
   untouched — SWD-13); keyring rotation battery for `card_withdrawal`
   (retired/dropped codes, verbatim replay, history invariance).
5. **Demo wave:** `publication-demo` withdrawal chapter (counts, FINAL_LINE
   fact, inspect pointer), `verify_install.py` stage, bilingual README
   mention.
6. **Docs:** [sop-authoring.md](../../sop-authoring.md) withdrawal
   sections, [verification.md](../../verification.md) coverage rows,
   file-adapter note only if needed; master adds doc_sync_map rows at
   ratification (workers never edit the agreement — SKR-9/D65 precedent).

**Acceptance scenario sketch (the runnable story):** published version
standing → operator loads `withdrawal_record` → `None` → creates a
withdrawal work (request document naming the version + published digest)
→ proposal BLOCKED (W02 pending) → tampered `card_withdrawal` refused
`EVIDENCE_AUTHENTICATION_FAILED`, zero intake writes → valid signed
approval verifies → intent accepted, business key = the withdrawal key →
dispatch commits exactly ONE new hash-named artifact (the record); the
publication artifact bytes unchanged; response lost → restart reconcile,
one attempt, `confirmed_succeeded`; `accepted` proof runtime-written
under `sop-store`, `event_id` = withdrawal operation id; completion
closes the withdrawal work `succeeded` → loader now refuses the version
with the **withdrawn** error (distinct from absent); `pinned_card` fails
closed; `withdrawal_record()` returns the record → second withdrawal
work: `REQUIREMENT_UNSATISFIED` first, `OPERATION_CONTENT_CONFLICT` after
its own approval (D66 order) → re-publish same version in-database:
`OPERATION_CONTENT_CONFLICT` after its own approval, store census
unchanged → admin revokes the publication work's `card_approval` via S8:
closed work stays `closed/succeeded`, completion byte-identical, record
and artifact untouched → approver key rotated: retired-key
`card_withdrawal` refused `EVIDENCE_KEY_RETIRED`, six tables and both
artifacts untouched. All five existing gates green; no new global gate.

## 13. TDD-shaped test implications (list only — no tests written here)

- `tests/test_publication.py` (store + loader): `withdrawal_key`
  derivation and hostile-identity non-collision (IR-P16 fixture reuse);
  record commit/replay/refusal matrix at the adapter level; absent-target
  and wrong-target-digest refusals; loader matrix — valid, absent,
  **withdrawn** (distinct message), corrupt record, identity-mismatched
  record, digest-mismatched record; `pinned_card` on a withdrawn version;
  `withdrawal_record()` present/absent; directory census (two artifacts,
  zero `.stage`).
- `tests/test_publication.py` (governed flow): withdrawal-request
  admission (malformed → bounded unpersisted `ValueError`); W02 blocking
  incl. wrong-digest/wrong-version approvals; wrong-source intake
  `AUTHORITY_DENIED`; full flow on real SQLite + directory (accepted
  proof under `sop-store`, `event_id` = operation id; completion);
  response-loss one-attempt reconcile; command replay verbatim; D66 order
  for second withdrawal works; cross-approval isolation; **publication
  works complete unchanged** (the F18 regression); re-publish after
  withdrawal → `OPERATION_CONTENT_CONFLICT` after own approval, census
  unchanged.
- `tests/test_publication.py` or a sibling (SWD-13): S8 composition —
  admin revokes `card_approval` and `accepted` on the closed publication
  work; owner/source-without-grant denials; closed-work correction
  (completion byte-identical, S02/S03 pending, two `EvidenceRevoked`
  events, one artifact).
- `tests/test_publication_rotation.py`: `card_withdrawal` under keyring
  rotation — retired/dropped refusals with six-table byte equality,
  same-`command_id` verbatim replay, current-status resend, both
  artifacts untouched.
- `tests/test_publication_demo.py`: the demo chapter end-to-end with
  independently re-derived counts/keys/digests/receipts and secret-echo
  hygiene (planted-marker discipline).

## 14. Honest limits

- **Trusted-local governance, not security:** the withdrawing approver is
  a configured name with a shared-key signature; any key holder can sign
  as that source; the store directory is trusted configuration with no
  tamper-evidence, power-loss or hostile-filesystem guarantee. No tenant
  authentication, TLS, KMS, non-repudiation, revocation-propagation or
  distributed exactly-once claim.
- **Withdrawal fences no running consumer:** the Runtime never consults
  the store (D62); already-loaded policies, completed pin checks and
  in-flight works are unaffected — the read surface changes, executing
  systems do not. This mirrors S8's unfenced in-flight-call residual and
  is stated, not hidden.
- **The record is exactly as trustworthy as the directory:** deleting or
  editing files is operator misuse that the loader turns into
  absent/corrupt errors, never into tamper detection (§9). Raw adapter
  use can commit a record without the governed flow; shared directories
  admit cross-database withdrawal (MD-4-adjacent boundary, accepted).
- **No un-withdrawal, no same-version reinstatement:** correction is
  forward-only (new version); a withdrawn version's loader error is
  permanent while the record stands.
- **Two truths stay separate on purpose:** store validity (the record,
  loader-visible) and runtime proof validity (S8 revocation,
  ledger-visible) do not synchronize automatically (§7); an operator
  changing both performs both acts.
- **Grounding limits of this document:** every factual claim carries a
  file:line or probe reference read at `860571c5`; probes P1–P2 ran on
  fresh ephemeral stores and are reproduced in the
  [recon note](../../../.agents/notes/2026-10-16-s13-design-recon.md);
  everything else is recommendation. The API shapes in §3–§9 are
  candidate sketches, not implemented or test-verified code. External
  author usability remains untested (unchanged 0.4 gap). This draft
  self-ratifies nothing — the master's ratification and the independent
  review it dispatches are the counterweight.

## MASTER ratification - 2026-10-16 D67-D79 (before implementation)

Ratified on the independent design review
[8eee4ad](../../../.agents/notes/2026-10-16-s13-independent-design-review.md)
(verdict: implementable with amendments; 48/48 probes; R2 proved the drafted
SWD-8 refusal channel strands the governed work). The DRAFT body above is
ratified **as amended** by this section; where they differ, this section
governs.

- **D67** (=SWD-1) Withdrawal is a second immutable hash-named record
  artifact in the same store directory; publication artifacts are never
  mutated or deleted.
- **D68** (=SWD-2) `withdrawal_key = "sop-withdrawn:" +
  digest([policy_id, policy_version])` — collision-free in every namespace
  (D56 basis).
- **D69** (=SWD-3 + RV-F2 disclosure) Deterministic closed four-field record
  document, no free text. Withdrawal request documents are effectively
  immutable under `revise_document` (id-less shape; content changes enter as
  new works — the S12 IR-F2 precedent wording applies verbatim).
- **D70** (=SWD-4 + RV-F4(a) pin) Same family/database/ledger, second
  capability `sop.withdraw`, document-shape-discriminated W02/W03
  requirements, operation key = withdrawal key. A dispatch whose adapter is
  the publication store (capability mismatch) holds bounded — pin it.
- **D71** (=SWD-5) Signed version-bound `card_withdrawal` `{digest,
  policy_version}` from the configured source; no admin bypass on the
  governed path (the admin's real reach is `revoke_evidence`, which never
  touches the store — Q2 asymmetry ratified).
- **D72** (=SWD-6 + RV-F5 amendment) Loader gains the withdrawal check and
  two new bounded errors — withdrawn (distinct from absent) and
  invalid-record (fail-closed) — plus `withdrawal_record()` audit read; no
  override parameter. A corrupt withdrawal record maps to the invalid-record
  error by explicit catch-and-re-raise, never an unbounded store traceback.
- **D73** (=SWD-7) No write-path fencing: current validity lives at the read
  surface only (structurally enforced by reconcile-from-lookup; re-publication
  of a withdrawn version is refused by the governed proposal's target checks,
  not by the store).
- **D74** (=SWD-8, **amended per MD-2 Alternative A — replaces the drafted
  refusal channel**): `SopWithdrawalStore` wraps `FilePublisher` unchanged
  and refuses an absent target or digest mismatch by returning a **rejected
  receipt** (`status: "rejected"`), which resolves `confirmed_failed` —
  terminal, truthful, and the work stays cancellable. The drafted
  `ValueError` channel (which strands the work at `NO_AUTHORITATIVE_RESULT`
  with both completion and cancel refusing `OUTCOME_UNRESOLVED`, RV-F1/R2)
  is **rejected**. Per-capability adapter discipline disclosure (RV-F3):
  each capability's dispatch/reconcile/recover path uses exactly its own
  adapter; nothing crosses.
- **D75** (=SWD-9) D66 order inherited and pinned for withdrawal works:
  requirement blockers before the business-key branch.
- **D76** (=SWD-10) No un-withdrawal (forward-only correction: publish a new
  version), no compensation semantics, no Runtime wiring, no UI change.
- **D77** (=SWD-11) `publication-demo` withdrawal chapter + installed
  module/console stage as existing installer evidence — **no new global
  gate**; demo census/counts updated for the new artifact population.
- **D78** (=SWD-12, MD-5 confirmation) Doc set per story 6 (sop-authoring.md
  withdrawal sections, verification.md coverage); the master confirms **zero
  new `doc_sync_map` rows** — the existing
  `work_runtime/publication.py → docs/sop-authoring.md` row covers the
  withdrawal surface (RV-F7), so same-commit pairing is owed there as-is.
- **D79** (=SWD-13) The S8 `revoke_evidence` × sop-publish composition
  (admin revokes `card_approval`/accepted proofs on the closed work;
  artifacts untouched; completion byte-identical) is **pinned by tests** —
  real today, previously unpinned.

**Ratified defaults:** Q1–Q10 all as drafted (same family; no admin bypass;
separate wrapper; forward-only; etc.) — verified implementable and internally
consistent by the review; none challenged.

**MD-4 test-list extensions (pin in story 3):** capability × document-shape
pairing in both directions; the governed refusal outcome per D74
(`confirmed_failed`, cancellable); the wrong-adapter dispatch hold per D70.

No history rewrite, no distributed revocation, no tenant authentication, no
un-withdrawal, no security-certification claim. Config rollback revives old
approver keys (S11 limits); cross-database store sharing remains the accepted
MD-4 operator boundary from S12.
