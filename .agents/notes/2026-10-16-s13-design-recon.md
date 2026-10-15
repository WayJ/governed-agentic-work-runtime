# S13 publication-withdrawal design reconnaissance — 2026-10-16 (post-S12)

## Scope and evidence

Master-authorized S13 design/reconnaissance for the ratified D63 deferral:
design publication withdrawal on the S8 evidence-revocation model (withdraw
current validity, never rewrite history). **Design only — no implementation,
no product/test/UI changes, no dependencies, no merges/pushes, no extra
workers.** The only repo writes from this dispatch are the candidate DRAFT
spec
[2026-10-16-sop-publication-withdrawal-design.md](../../docs/superpowers/specs/2026-10-16-sop-publication-withdrawal-design.md)
(pending master ratification + the independent design review the master
dispatches next) and this note. No roadmap, sprint, acceptance, ADR or
tech-debt ledger mutation was made; the master owns those.

Fresh worktree asserted at published main
`860571c5c89b7dd22dc2be2567d7870c9b093f66`
(`git rev-parse HEAD` = the task's named baseline, branch
`WayJ/s13-withdrawal-design`, `git status --porcelain` empty before this
note). Sources read as truth: [AGENTS.md](../../AGENTS.md) (working
agreement incl. supervibe gates + doc_sync_map),
[roadmap.md](../../docs/roadmap.md) 0.4,
[sop-authoring.md](../../docs/sop-authoring.md) (S12 publication sections),
[evidence-revocation.md](../../docs/evidence-revocation.md),
[interventions.md](../../docs/interventions.md),
[file-adapter.md](../../docs/file-adapter.md),
[signed-evidence.md](../../docs/signed-evidence.md),
[verification.md](../../docs/verification.md),
[tech-debt-tracker.md](../../docs/tech-debt-tracker.md),
[RFC-002](../../docs/RFC-002-sop-authoring-and-binding.md) §6, the S8 and
S12 design specs + acceptance records, the S12 epic ADR ledger
([2026-10-15-sop-publication.md](../../docs/superpowers/roadmaps/2026-10-15-sop-publication.md)),
and the actual `publication.py`, `publication_demo.py`, `runtime.py`,
`file_adapter.py`, `ingress.py`, `policy.py`, `adapters.py` plus
`tests/test_publication.py`, `tests/test_publication_rotation.py`,
`tests/test_publication_demo.py`, `tests/test_evidence_revocation.py`
(inventory + naming; the S8 behavior table in evidence-revocation.md
summarizes the 55-test module). Historical `idea.md` / `上一次建议.md`
treated as source material only. Probes (§3) ran from `/tmp` against the
public API with ephemeral synthetic stores; probe stores were deleted
afterwards and the worktree re-asserted clean.

## Findings

### The S12 publication surface being extended

- **F1 (baseline).** `860571c5c89b7dd22dc2be2567d7870c9b093f66` is the
  published main tip (S12 close-out); tree clean. The S12 module docstring
  itself pins the gap: "there is no withdrawal in this slice (D63)"
  (`work_runtime/publication.py:16-18`;
  `work_runtime/publication_demo.py:16-17`).
- **F2 (the deferral is roadmap-level, verbatim).**
  [roadmap.md](../../docs/roadmap.md) 0.4: "publication withdrawal,
  approval-identity envelopes and quorum remain separately-designed future
  work" (line 37). D63 in
  [sop-authoring.md](../../docs/sop-authoring.md) lines 186–188: the store
  is append-only and "rolling back" a publication means publishing a
  corrected new version. The S12 design §10 (lines 278–293) already frames
  the exact seam this design must fill: "Approval revocation does not reach
  the store … whether a *published version* can be withdrawn — and what
  that means for works already bound — is separately designed future work
  (Q4)"; its Q4 default was ratified (design lines 381, 453–454, 481).
- **F3 (publication identity).** `publication_key(card) = "sop-pub:" +
  digest([policy_id, policy_version])` — collision-free digest form (D56),
  committed path `sha256(key)` hex, key never touches the filesystem
  (`work_runtime/publication.py:28, 35-45, 48-62`;
  `work_runtime/file_adapter.py:224-228`).
- **F4 (the store is mechanically immutable — an in-place tombstone is
  impossible without breaking pinned validation).** Commit is exclusive
  stage + fsync + atomic non-overwriting `os.link`
  (`file_adapter.py:249-284`, link at 269); same key + same content replays
  the byte-identical winner receipt (270–274); same key + changed content
  is a bounded `ValueError` with zero side effects (273,
  `REUSED_MESSAGE`); the only `unlink` in the module is the adapter's own
  stage file (279–284) — **no code path deletes or rewrites a committed
  artifact**. `_validated_artifact` pins the exact five-field shape with
  `artifact_version == 1` (181–182), key equality (183–184), recomputed
  document digest (191–193) and `receipt["status"] == "accepted"` (195–199)
  — so flipping a field inside a committed file is not a legal state of
  this store at all.
- **F5 (additive read surface, D61).** `FilePublisher.read_validated(key)`
  returns `None` for an absent key and the full validated artifact
  otherwise, same bounded corruption refusals as `lookup`
  (`file_adapter.py:286-309`). `SopPublicationStore.lookup` delegates
  verbatim (`publication.py:93-94`).
- **F6 (loader fail-closed chain).** `_read_publication_artifact` derives
  the key, refuses a missing directory without creating it, reads via
  `read_validated`, converts absence into `ABSENT_MESSAGE`, re-lints the
  stored card, recomputes `sop_digest` against the stored
  `content_digest` and receipt, and checks stored identity against the
  request (`publication.py:96-134`; messages 100–105). Today's bounded,
  distinguishable classes: absent (incl. missing directory), corrupt,
  digest mismatch, identity mismatch — plus the pin classes in
  `pinned_card` (151–163) and the non-card/foreign-content refusals
  (MD-4 discipline, documented in
  [sop-authoring.md](../../docs/sop-authoring.md) 203–212). The loader has
  no Runtime wiring and no card→policy compilation (D62).
- **F7 (policy surface and its S8 hook).** `SopPublicationPolicy`:
  `evidence_sources = {"card_approval": "sop-owner", "accepted":
  "sop-store"}` (`publication.py:198-201`); admission lints via
  `sop_digest` (203–204, D57); `validate_evidence` pins the exact D58
  `{digest, policy_version}` shape (206–222); **`evaluate` counts only
  `status == "verified"` proofs** (227) — this is precisely the hook S8
  revocation uses to stop a proof satisfying a rule;
  `action_blockers` excludes the store-acceptance rule S03 and receives
  the capability (251–257); `operation_key` returns the publication key —
  the store key IS the business key (259–262, D66).
- **F8 (S12 wrapper contract is a declared assertion).**
  `SopPublicationStore.contract` declares `actions=("sop.publish",)`,
  keyed uniqueness, lifetime retention, authoritative-by-key lookup
  (`publication.py:80-85`); dispatch's capability preflight reads the
  adapter's declared contract (`runtime.py:1029-1036`).

### The S8 revocation machinery to mirror

- **F9 (command and routing).** `revoke_evidence` payload exactly
  `{source, event_id, reason}`; routed beside `record_evidence` and
  **before the closed-work guard**, so it is accepted on closed works,
  unbound works and during active cancellation
  (`runtime.py:281-288`; [evidence-revocation.md](../../docs/evidence-revocation.md)
  29–43).
- **F10 (authority).** A `work.intervene` administrator, or the actor who
  is the work's currently configured source for the stored proof kind AND
  holds `evidence.revoke`; ownership/`work.manage`/`evidence.write` alone
  grant nothing (`runtime.py:805-817`; docs 45–70). Replay reauthorization
  re-runs the identical predicate; a replay after authority loss is a
  fresh unpersisted `AUTHORITY_DENIED` and the stored receipt stays
  immutable (`runtime.py:298-338`, revoke branch 315–325).
- **F11 (effect and permanence).** One transaction: proof row updated
  in place to `status "revoked"` with everything else byte-identical,
  requirements recomputed, one version bump, one `EvidenceRevoked` event
  with actual requirement diffs and wait dispositions
  (`runtime.py:841-883`). Rows are never deleted; `verify_pending` adopts
  only pending candidates and migration revalidates only verified ones, so
  revoked is skipped by both; resend reports the candidate's current
  status under the original `evidence_id`
  (`runtime.py:885-908`; docs 160–172).
- **F12 (closed-work correction).** Revocation on a closed work preserves
  `status`, `outcome` and the `completion` snapshot byte-identically — no
  reopen, no automatic needs_attention; correction is visible only in
  current data ([evidence-revocation.md](../../docs/evidence-revocation.md)
  124–140).
- **F13 (terminology collision — S10 owns "withdrawn").** A
  **compensation's** accepted proof uses kind `"withdrawn"` (S10 D45) with
  `original_external_id`, written only for ops carrying a `compensates`
  link (`runtime.py:932-961`, kind choice at 952–955). S13 publication
  withdrawal must not reuse this kind or imply compensation semantics.
- **F14 (accepted-proof write path and reservation).** The runtime writes
  the `accepted` proof itself at resolution under the family's accepted
  source with `event_id` = the operation id (`runtime.py:925-961`);
  privileged accepted-source intake collisions are pre-reserved
  (`runtime.py:751-759`, TD-1 repaid per
  [tech-debt-tracker.md](../../docs/tech-debt-tracker.md) — no open debt
  touches withdrawal).

### Composition probes (fresh stores, public API only)

- **F15 (P1: S8 revocation already composes with the sop-publish family —
  and nothing pins it).** On a real `SopPublicationPolicy` runtime with a
  completed publication work: the owner (`agent`, `work.manage` +
  `sop.publish`) and the approval source without `evidence.revoke`
  (`sop-owner`, `evidence.write` only) are both refused
  `AUTHORITY_DENIED`; a `work.intervene` administrator successfully revokes
  the `card_approval` **and** the runtime-written `accepted` proof
  (`sop-store`, `event_id` = operation id) on the **closed** work — two
  `EvidenceRevoked` events, work stays `closed/succeeded`, completion
  snapshot byte-identical, `S02` and `S03` both pending, exactly one
  committed artifact unchanged. This is S8's documented model applied to
  the S12 family by construction (`evaluate`'s verified filter, F7) — but
  `grep -n revoke tests/test_publication*.py` finds **zero** coverage: the
  composition is real, unpinned behavior (the S8 module pinned the
  *publishing* C02/C04 family instead).
- **F16 (P2: a store-layer execute refusal cannot fence re-publication —
  reconcile bypasses it).** With a second runtime database sharing the
  store directory, a same-card proposal is accepted (its own operations
  table); dispatch through a wrapper whose `execute` refuses the
  publication key yields `outcome_unknown` (exception path,
  `runtime.py:1064-1065`); **reconcile then resolves
  `confirmed_succeeded` from the standing artifact via `lookup`**
  (`runtime.py:1105-1115`) with still exactly one artifact. Enforcing "no
  re-publication after withdrawal" at the adapter's execute is therefore
  structurally unenforceable without poisoning `lookup`'s
  authoritative-by-key contract. Consequence: withdrawal's validity
  effect belongs at the loader/read surface, not the write path.
- **F17 (P2 corollary: cross-database same-version re-publish converges by
  store replay).** A fresh database re-publishing the same `(policy_id,
  version)` commits nothing new — `FilePublisher.execute` returns the
  winner receipt (F4) — so any withdrawal marker that lives beside the
  artifact keeps governing validity regardless of which database acted.
  This is documented store semantics (S12 design §7 layer 3), restated
  here because it bounds what withdrawal can and cannot change.

### Load-bearing structural constraints

- **F18 (the completion gate is capability-blind).** `request_completion`
  blocks on **every** unsatisfied requirement of the work
  (`runtime.py:422-433`) — there is no capability filter, unlike
  `action_blockers` (F7). Works do not carry capabilities (capability is a
  `propose_action` payload field). Therefore a policy family that admits
  two governed acts (publish, withdraw) must discriminate their
  requirement sets by the **work document's shape** — adding a
  withdrawal-approval requirement to card works would permanently block
  publication completion.
- **F19 (one policy family per database).** Every work resolves its own
  pinned policy; migration is never implicit (`runtime.py:171-185`), and
  the S12 design states the one-family-per-database convention (§6). A
  second family for withdrawal would split the publication ledger across
  two databases.
- **F20 (D66 pinned order).** `_propose` checks requirement blockers
  **before** the business-key branch (`runtime.py:668-673` before
  674–690; `OPERATION_CONTENT_CONFLICT` at 689–690), documented
  ([sop-authoring.md](../../docs/sop-authoring.md) 251–266) and pinned by
  `tests/test_publication.py:563, 579`. Any new governed act inherits this
  ordering for free; tests must pin it for withdrawal works too.
- **F21 (ingress surface for a withdrawal approval).** Signed ingress
  refuses only kind `"accepted"` (`RESERVED_KIND`,
  `work_runtime/ingress.py:26, 318-319`); a new signed kind such as
  `card_withdrawal` is an ordinary envelope. Keyring windows and codes are
  unchanged S11 semantics (`ingress.py:28-34, 304-311`); the gateway
  forwards to `record_evidence` with `expected_version=None`
  (`ingress.py:320-325`). Rotation never rewrites evidence fingerprints,
  so rotating the approver never withdraws anything by itself.
- **F22 (decision-number ceiling and house numbering).** The global D
  ledger tops out at **D66** (S12 ratification; epic ADR table
  2026-10-15-sop-publication.md lines 36–48; no D67+ anywhere in docs/ or
  .agents/). House pattern: candidate designs use a local prefix that
  cannot collide (S11 `SKR-*`, S12 `SPD-*`) and the master maps the
  ratified subset to global numbers — next free **D67**.
- **F23 (version discipline is external and unchanged).** RFC-002 §6:
  approval binds the exact content identity; any later change requires a
  new version ([RFC-002](../../docs/RFC-002-sop-authoring-and-binding.md)
  §6, lines 129–146). Withdrawal withdraws a version's current validity;
  it never changes content identity, and corrected content is a new
  version — the forward-only rule S12 §10 already states.
- **F24 (demo and coverage surfaces the sprint extends).**
  `publication-demo` runs the frozen S12 story with asserted counts and a
  FINAL_LINE fact (`work_runtime/publication_demo.py:39-52, 142-256`);
  [verification.md](../../docs/verification.md) 455–534 carries the S12
  coverage rows. A withdrawal chapter changes directory census (a second
  hash-named artifact) and table counts — the sprint updates both honestly
  (tests currently assert "exactly one hash-named artifact",
  `tests/test_publication.py:150`).
- **F25 (inspect/viewer need no change).** Works, evidence (incl. revoked
  status), operations and events render through the existing generic
  read-only surfaces (events table `work_id, version, type, body`,
  `runtime.py:124-127, 216-218`); the S8 viewer precedent already renders
  revoked evidence. No UI change is required for withdrawal to be
  auditable.

## Probes

Ran 2026-10-16 from `/tmp/s13-probe/probe.py` (deleted afterwards) against
the public API on this worktree, fresh `tempfile` stores:

- **P1 (S8 × sop-publish composition).** Asserted: owner-only and
  source-without-`evidence.revoke` revocations denied; admin revocation of
  `card_approval` and of the runtime-written `accepted` proof on the closed
  publication work accepted (`prior_status "verified"`); closed/succeeded
  preserved with completion byte-identical; S02 and S03 pending; exactly
  two `EvidenceRevoked` events; exactly one committed artifact. Result:
  all assertions passed (F15).
- **P2 (execute refusal vs reconcile).** Asserted: cross-database
  same-card proposal accepted; dispatch through a refusing `execute` →
  `outcome_unknown`; `reconcile` → `confirmed_succeeded` via `lookup`,
  one attempt, one artifact. Result: passed (F16/F17).

No probe wrote anything into the worktree; `git status --porcelain` was
re-asserted empty afterwards (before this note and the spec were written).

## What this note does not do

It ratifies nothing, allocates no epic/sprint/ADR/ledger entry, writes no
tests and no product code, and does not speak for the master. The
candidate design in the spec is recommendation grounded in the findings
above; the master's ratification and the independent review it dispatches
are the counterweight (S12 recon precedent).
