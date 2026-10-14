# TD-1 candidate design — independent builder-check review — 2026-10-15

Independent Orca review of the DRAFT spec
`docs/superpowers/specs/2026-10-15-td1-accepted-evidence-collision-design.md`
(candidate branch `WayJ/next-core-recon` tip `90e980b`, draft base `a90ddc6`,
published-main baseline `635e7b1` — the spec and designer notes live on that
branch, not in this tree, so they are cited by path/commit rather than
linked). Distinct from the designer's own self-review
`.agents/notes/2026-10-15-TD1-design-review.md` (same-head grounding audit):
every load-bearing claim below was re-derived against the main-baseline tree
and reproduced with fresh public-API probes (`/tmp/td1-review/`, throwaway
stores, no product edits). This is a recommendation to the master, who owns
ratification; nothing here is an implementation instruction, and no
epic/sprint id is allocated.

## Verdict

The candidate is **implementable and directionally sound** — the problem is
real and reproduced, the P2a + registry-union + `OPERATION_ID_RESERVED`
shape is the minimal coherent slice, and the designer's grounding held up
under independent re-derivation with **four amendments required before
ratification** (F1–F4 below: two undefined/underspecified persisted-field
semantics, one missing closed-work guard, one claim-scoping correction) and
one master decision (D6) that needs the grounded consequence analysis in §4.

## Independent grounding (fresh probes on the main baseline)

- **Poison reproduced (cross-work, S1 shape)**: accepted source `oa`
  (holding `evidence.write`) imported work W2's operation id as an event id
  into W1 — intake accepted today; W2's dispatch then raised
  `sqlite3.IntegrityError: UNIQUE constraint failed: evidence.source,
  evidence.event_id`, and `recover()` raised the same error so a second,
  independent ready operation on W1 was never dispatched — store-wide
  supervision liveness broken, exactly the spec's §1. (First probe run
  failed for an instructive reason worth recording: `demo_grants()` has no
  `oa` actor, so ungranted "oa" imports are envelope-rejected
  (`command()` `actor not in self.grants`) — the poisoning actor must be a
  *granted* accepted source, which the spec's trusted-local framing already
  implies.)
- **General synthetic-acceptance boundary (no collision needed)**: the
  accepted source imported an `accepted`-kind proof under a fresh event id;
  after `verify_pending` the acceptance rule read **satisfied** on the
  synthetic alone; `request_completion` while the real operation was
  unresolved was rejected `OUTCOME_UNRESOLVED`; after a normal reconcile,
  completion was accepted citing **both** the synthetic and the real proof
  ids. Two consequences: (a) both closure paths gate on unresolved
  operations (`runtime.py` request_completion and `finalize_cancel` both
  compute `OUTCOME_UNRESOLVED`), confirming the spec's closed-work
  impossibility claim for public-API stores; (b) "completion on a verified
  synthetic acceptance" is a **pre-existing capability independent of TD-1**
  — the material D6 input.
- Code re-derivation on the baseline tree confirms the self-review's table
  where it matters: `_receive` precedence (shape → source+kind authority →
  old-row dedup/`SOURCE_EVENT_CONFLICT` → insert), `_resolve` plain INSERT
  under `_accepted_source(work_of_op)` only on accepted results with the
  terminal early-return, `reconcile` is lookup-only (never re-executes),
  `attempts[-1]` guaranteed for reached ops, `migrate_policy` rejects
  `OUTCOME_UNRESOLVED` (no accepted-source race at resolution),
  `_validated_registry` always places the default policy inside
  `self.policies.values()` (union soundness), and the reader needs zero
  change (events pass `type` through with `body_raw`; `event_types` is a
  GROUP BY; the operations DTO allowlists fields but carries `body_raw`, so
  an additive `proof_conflict` surfaces as raw JSON without a DTO change).

## Material findings (amendments required before ratification)

- **F1 — `proof_conflict.digest` is undefined.** The seven-field snapshot
  lists `digest` without saying *what* digest: the conflicting row's
  `data.digest`, the row's source-event fingerprint, or the operation's
  `document_digest` (what the real external acceptance attests). A
  persisted event body with an undefined field invites implementer
  divergence and reader confusion — precisely the "real external result vs
  candidate" hazard the master flagged. Pin it (recommendation: record the
  operation's `document_digest` — it lets a reader compare the synthetic
  row's `data.digest` against what was actually accepted; optionally also
  the row's own `data_digest`). While pinning, consider adding
  `evidence_work_id` (the conflicting row's work): the row is locatable by
  its `(source, event_id)` PK from anywhere, but cross-work is the Canary
  shape (probe above; spec S1), and knowing which work's requirements the
  row can satisfy is audit-relevant.
- **F2 — `evidence_id` shape/null rule missing.** Legacy rows written by
  the real `_receive` carry uuid-hex ids, but custom/malformed stores may
  lack `id` or carry a non-string (the S8 viewer malformed-store tests pin
  exactly `id: 7` and missing-`id` rows). The snapshot and event must
  define valid-string-or-`null` (the D37 `_valid_id` precedent) rather than
  assume — the B-fixture uses accepted original inputs (valid ids), so this
  is about honest degradation on arbitrary stores, which this repo
  elsewhere requires of readers.
- **F3 — P2a needs a closed-work guard.** The spec sets
  `work["status"] = "needs_attention"` unconditionally at conflict
  resolution. Public-API closed works cannot host a dispatched operation
  (verified: both closure paths gate `OUTCOME_UNRESOLVED`), so this fires
  only on custom/direct-SQL state — which this repo does test elsewhere.
  Without a guard, resolution on such a store would overwrite `closed`,
  violating the S8 D34 closed-work discipline. Mirror `_revoke`: preserve
  `closed`, and record a `work_was_closed`-style fact in the event. One
  conditional; zero cost; removes a class of custom-store hazard.
- **F4 — "zero writes on repeated recover" must be scoped.** `recover()`
  runs `verify_pending` + `expire_waits` over every work each cycle before
  reconciling; those write `EvidenceEvaluated`/`WaitExpired` when they apply,
  and `expire_waits` is wall-clock-dependent (new deadlines can fire between
  cycles). The design's idempotence claim is true **for the conflicted
  operation and its resolution event only** — the spec's wording ("zero
  writes, zero adapter calls") must say so, and test 5 must assert
  op-scoped no-op plus adapter-count bounds, not whole-store byte equality
  across `recover`.

## D6 analysis (completion blocker — the master's flagged concern)

Grounded facts: a verified synthetic acceptance satisfies the acceptance
rule **today, with no collision at all** (fresh-id import; probe P1), and
`needs_attention` stickiness never gates closure commands (no status check
in `request_completion`) — "sticky" only means `_evaluate` will not clear
it automatically. Therefore:

- **No new blocker (spec recommendation)** is *consistent* with the
  unchanged trusted-local boundary: the conflict case is not a new
  capability, and P2a makes it visible (durable `AcceptanceProofConflict`
  event + `needs_attention` + `proof_conflict` on the operation) instead of
  silent. Minimal slice; no new deadlock surface.
- **A conflict-only blocker** (reject `request_completion` while any
  operation carries an unresolved `proof_conflict`) is coherent and
  small, but its only in-protocol resolution is revoking the conflicting
  row (`revoke_evidence`) — after which the acceptance rule is
  **permanently unsatisfiable** for that work (the runtime can never insert
  its own accepted proof while the row occupies the PK), so success-closure
  is permanently denied and only `request_cancel` + `finalize_cancel`
  remains (which acknowledges the real effect — possible, since the
  conflicted op is `confirmed_succeeded`). That is arguably the honest
  outcome for a synthetic acceptance, but it must be stated as the
  resolution path's consequence, not discovered later. A softer variant
  (block only while the conflicting row is currently `verified`, i.e. when
  completion would actually cite it) has the same terminal consequence.
- If the master wants the stronger gate, it should also say whether the
  *general* synthetic boundary (fresh-id imports) stays ungated — a
  conflict-only blocker leaves that larger hole open, which is defensible
  scope discipline but worth an explicit sentence in runtime-boundaries.

Recommendation: **no new blocker for the minimal slice** (D6 as drafted),
with F1–F3 amendments and the D8 doc note expanded to state the general
boundary explicitly.

## Agreements with the draft (independently confirmed)

Poison mechanics and blast radius; prevention predicate soundness/completeness
of the registry union (with F6 implementation notes: skip policies whose
`accepted` source is absent/invalid when precomputing — `_accepted_source`
has **no** default fallback, it fails closed by raising, so the union must
filter, not assume; state the policies-are-immutable-for-the-lifetime
assumption or compute per call — registries in play are tiny); reservation
placement after the old-row branch preserving dedup/`SOURCE_EVENT_CONFLICT`
semantics (S3 re-verified in the S8 core review); `OPERATION_ID_RESERVED`
as a new persisted admission rejection (name and blockers shape fine);
migration/retirement union behavior; P2b rejection (misrepresents a known
accepted effect; permanent closure deadlock); B-fixture faithfulness
(five-column legacy row, fingerprint `digest([work_id, payload])`, canonical
candidate body); "no test anywhere asserts the IntegrityError" (grep clean
on the baseline); repayment only in full with P2a **and** both the
prevention tests and the liveness/crash tests real — the master's
no-partial-claim caveat is structurally satisfied by §7 tests 1–6 plus the
GREEN preservation set.

## Suggested decision-list delta for the master

Confirm D1–D5, D7–D10 as drafted (recommendations concur). Add/reshape:
**D11** pin `digest` semantics (+`evidence_work_id`?) per F1; **D12**
`evidence_id` valid-string-or-null per F2; **D13** closed-work guard +
`work_was_closed` fact at conflict resolution per F3; **D14** scope the
repeated-recover claim in spec text and test 5 per F4; and treat the D6
analysis above as its input. These are amendments to a draft, not new
architecture — none changes the slice's shape or size materially
(~4 additional lines of guard/pinning plus test assertions).

## Limits

Review-only: no product/code/UI changes were made; probes used public APIs
on throwaway `/tmp` stores; the candidate branch and all worktrees are
untouched. TD-1 remains open until the master ratifies and a scoped slice
lands with the tests above; no repayment is claimed here.
