# Next core delivery reconnaissance — 2026-10-15 (post-S8)

## Scope and evidence

Master-authorized strategic reconnaissance after the S8 release; not
implementation and not sprint materialization. Fresh checkout asserted at
published main `635e7b1e6c6d93e55dc47f141e0f29646eb525a9` (= HEAD, clean
tree). Sources read as truth: [AGENTS.md](../../AGENTS.md),
[roadmap.md](../../docs/roadmap.md), historical [idea.md](../../idea.md) /
[上一次建议.md](../../上一次建议.md) (source material, not instructions),
[RFC-001](../../docs/RFC-001-core-semantics.md) (§4.2, §5, §6 D6, §7 D8, §8),
RFC-002/003, [E3 roadmap](../../docs/superpowers/roadmaps/2026-10-13-intervention-and-policy-evolution.md),
[E8 roadmap](../../docs/superpowers/roadmaps/2026-10-14-evidence-revocation.md)
(ADR D32–D37), the S8 [design review](2026-10-14-S8-design-review.md) (D-1/D-4),
[S8 acceptance + correction](../../docs/superpowers/acceptances/2026-10-15-S8-acceptance.md),
[TD-1](../../docs/tech-debt-tracker.md) row, the prior
[recon](2026-10-14-next-core-recon.md), and the actual `runtime.py`,
`policy.py`, `publishing.py`, `adapters.py`, `file_adapter.py`, `ingress.py`,
`adapter_contract.py`, `runtime-boundaries.md`, `interventions.md`,
`evidence-revocation.md`, `verification.md` and the runtime/revocation tests.
One throwaway probe ran from `/tmp` (public API only, temporary stores, zero
repository writes; §3). Roadmap 0.3 still owes compensation execution; 0.2
owes source-key rotation; 0.4 owes measured fencing/concurrency, SOP
publication and real author feedback — all separate future work, none claimed
here. No distributed exactly-once, tenant-authentication or external-fencing
claim is made anywhere below; every principal remains trusted-local
configuration.

## 1. Actual public surface (as shipped at 635e7b1)

- **API**: `Runtime(path, policy, grants, *, policies=None)`;
  `command(actor, command_id, work_id, kind, payload, expected_version)` with
  kinds `create_work`, `record_evidence`, `revoke_evidence`, `bind_contract`,
  `revise_plan`, `revise_document`, `register_wait`, `request_completion`,
  `propose_action`, `request_cancel`, `finalize_cancel`, `transfer_owner`,
  `migrate_policy`; plus `verify_pending`, `expire_waits`, `dispatch`,
  `reconcile`, `recover`, `get_work`/`get_operation`/`get_command`, `events`
  (`runtime.py:92-942`). Command protocol: CAS on `expected_version`
  (`runtime.py:247,269`), durable dedup under `(actor, command_id)`
  (`runtime.py:253-262`), replay rechecks current authority per kind
  (`runtime.py:288-328`).
- **Schema** (unchanged since S1, `schema_version` 1, `runtime.py:99-124`):
  `works(id, state)`, `commands(actor, id, fingerprint, work_id, receipt)` PK
  `(actor,id)`, `evidence(source, event_id, work_id, fingerprint, body)` PK
  **`(source, event_id)`**, `operations(id PK, business_key UNIQUE, work_id,
  body)`, `events(seq, work_id, version, type, body)`, `metadata`.
- **Operation lifecycle**: `prepared/dispatched/outcome_unknown/
  confirmed_succeeded/confirmed_failed` with `dispatch_state`
  `ready/in_flight/finished/cancelled/held`; one attempt row per dispatch;
  confirmed ops are terminal and never re-resolve (`runtime.py:898-926`).
  Business key is policy-derived — expense
  `digest([id, capability, document.id, document_revision])`
  (`policy.py:138-140`), publishing `digest([id, capability, document.id,
  document_digest])` (`publishing.py:102-104`) — so identity is stable across
  retries and re-proposal re-admits the same operation (`runtime.py:632-646`).
- **Effect/recovery semantics** (RFC-001 D6 implemented): dispatch persists
  the attempt before the external call (`runtime.py:852-855`); adapter
  exceptions become `outcome_unknown`, never assumed failure; `reconcile`
  looks up by the original business key and resolves or escalates
  `NO_AUTHORITATIVE_RESULT` → `needs_attention` (`runtime.py:874-896`);
  `recover` = verify_pending + expire_waits for every work, then
  reconcile-uncertain and dispatch-ready per operation, in stored row order
  (`runtime.py:928-942`). A confirmed acceptance writes a runtime-owned
  `verified` proof of kind `accepted` with `event_id = operation id` under
  the policy's accepted source (`runtime.py:917-921`).
- **Adapters** (all forward-only, no inverse action anywhere):
  `FakeOA` declares `actions=("expense.submit",)`, external receipts plus
  `invoices(invoice_id→external_id)` rows that nothing ever deletes
  (`adapters.py:16-83`); `FakePublisher` and `FilePublisher` declare only
  `content.publish` (`publishing.py:117-123`, `file_adapter.py:213-214`).
  Signed ingress can never supply kind `accepted` (`ingress.py:25-27`).

## 2. Compensation grounding (business intent, authority, capability)

- **Intent**: RFC-001 D8 — compensation is a *different operation* from
  plan/contract revision: "已创建申请需要撤回 → 创建真实的撤回 Operation，并
  验证外部结果" (create a real withdrawal Operation and verify the external
  result). §7: cancellation completes only after verification and any
  necessary withdrawal (or authorized responsibility transfer). E3's
  deliverable line still reads "Compensation execution and evidence
  revocation remain follow-up work; this sprint records effects rather than
  reversing them" — revocation shipped in S8, compensation is the open E3
  follow-up. `interventions.md:85-91` pins the invariant: acknowledgement
  admits effects exist and "will not be reversed by this runtime"; revocation
  "is never compensation". `verification.md` lists compensation execution as
  explicitly out of scope.
- **Probe-verified gap** (W3/W4 below): a compensating capability does not
  exist at any layer — `expense.withdraw` without a grant →
  `AUTHORITY_DENIED`; with the grant → `REQUIREMENT_UNSATISFIED` wrapping a
  `CAPABILITY_UNSUPPORTED` blocker (`policy.py:128-133`, wrap at
  `runtime.py:621-626`); `FakeOA` has no inverse action. On a closed work
  every proposal is `WORK_NOT_ACTIONABLE` (`runtime.py:275-276`), so
  post-closure compensation is impossible by construction today.
- **Both families' actual irreversible local effects**: FakeOA acceptance
  inserts receipt + invoice rows (never removed; `accepted_count()` is the
  honest effect count); FakePublisher/FilePublisher publication artifacts are
  append-only per (document id, digest). A compensation slice must therefore
  model withdrawal as a **new appended effect** (e.g. a withdrawal row
  referencing the original `external_id`) — never a deletion or a pretend
  inverse of the historical acceptance, which stays `confirmed_succeeded`
  with its original receipt, proof and closure citation. This is exactly the
  S8 D36 discipline (permanent rows, explicit new events) applied to effects.
- **What any compensation slice inherits for free**: idempotency by business
  key, unknown-outcome reconciliation, restart recovery, evidence intake and
  revocation, event-sourced audit. **What it must decide newly**:
  §5 decision list.

## 3. TD-1 reproduced with the public API (throwaway /tmp probe)

Probe: `python3 /tmp/next-core-recon-2026-10-15/probe_td1_compensation_gap.py`
(clearly labelled throwaway; imports only
`work_runtime.{Runtime,policy.ExpensePolicy,adapters.FakeOA}`; brand-new
stores under `/tmp/next-core-recon-2026-10-15/`; zero writes to the checkout;
not committed). Minimal reproduction recipe: build a ready expense work
(create → bind → 3 proofs → verify → propose), read the prepared operation
id via `get_operation`, then — before dispatch — have the trusted-local
`oa` actor issue `record_evidence(kind="accepted",
event_id=<operation id>)`; then `dispatch`.

Observed, all assertions held:

1. **Misuse admitted today**: the intake returns
   `accepted / pending_verification` (`_receive` checks only source+kind
   authority, `runtime.py:657-682`; it does not know operation ids).
   Legitimate imports (fresh event id, resends, other kinds) behave
   identically and must keep working.
2. **Collision**: `dispatch` commits the real external effect in FakeOA, then
   `_resolve`'s proof INSERT (`runtime.py:920`) raises
   `sqlite3.IntegrityError: UNIQUE constraint failed: evidence.source,
   event_id` — the external acceptance exists but can never be recorded.
   The op stays `dispatched/in_flight` with attempt `outcome_unknown`
   forever; every `reconcile` re-raises identically (the documented rollback
   loop).
3. **Blast radius is larger than the tracker row records**: `recover()`
   raises on the poisoned op every cycle — store-wide supervision liveness is
   broken, and because `_save_op` uses `INSERT OR REPLACE` (re-saved
   operations move to fresh rowids; `runtime.py:215-218`) while `recover`
   walks operations in row order, **every operation stored after the poisoned
   row is starved** (probe: W2's ready op never dispatched, `lookup=None`).
   Before aborting, recover's verify phase still ran and **verified the
   shape-valid synthetic acceptance row**, satisfying E08 while the real op
   stays unresolved — the trusted-local boundary in one picture.
4. **Safe direction confirmed**: `record_evidence` with `event_id` equal to
   an *already-confirmed* operation id is cleanly rejected
   `SOURCE_EVENT_CONFLICT` (fingerprint mismatch, `runtime.py:670-672`). Only
   the pre-confirmation direction is broken.
5. **Counts** (final store): operations `2 confirmed_succeeded / 1
   dispatched (poisoned) / 1 prepared (starved)`; evidence 16 verified
   (incl. the synthetic row); FakeOA `accepted_count()=3`, invoices rows 3;
   works `active/active/closed/closed`; W1 events 6. Ack-not-compensation
   demo (W4): `finalize_cancel` accepted with the exact succeeded-id ack;
   closure snapshot records `external_id`; the op remains
   `confirmed_succeeded`; FakeOA effect count unchanged — nothing reversed.

## 4. Comparison: smallest meaningful compensation slice vs TD-1 repair first

**TD-1 repair** — reject conflicting reserved operation-id intake before
proof insertion (the ratified repayment criterion, decided at D37): one
admission guard in `_receive`, named rejection code, tests (legitimate
imports unaffected; collision rejected atomically; real dispatch→confirm→
resolve still writes exactly one accepted proof; safe direction unchanged;
replay of the new rejection per protocol), `runtime-boundaries.md` same
commit (doc_sync_map row), tracker repayment citing the commit hash. No
schema change, no new semantics, no UI. Small: a single bounded task.

**Smallest meaningful compensation slice** — even minimally scoped
(pre-closure compensation under an active cancellation intent, expense family
only, `FakeOA` gains an append-only withdrawal action) it must add: an
adapter inverse action + contract update, policy/runtime admission for a
compensating capability, an explicit link from the compensation operation to
the original (payload + validation that the original is
`confirmed_succeeded` in the same work), disposition in the
`finalize_cancel` closure snapshot, docs, demo and viewer surfacing — i.e. a
design-first epic-scale slice (E3's own deliverable framed it as follow-up
work), with every item in §5 needing a master ruling before interfaces can
be pinned.

**Why TD-1 first is the dependency-correct order**: every compensating
operation confirms through the exact `_resolve` INSERT that TD-1 breaks, and
compensation reconciliation rides the `reconcile`/`recover` path whose
liveness TD-1 destroys store-wide. Building the 0.3 compensation promise on
a resolution path with a known rollback loop repeats the anti-pattern S8
avoided by fixing D-1 before building on `_evaluate`. The probe's
new evidence (recover starvation + silent synthetic-acceptance verification)
was not available when D37 scoped TD-1 as "exotic, low priority".

## 5. Recommendation — ONE bounded next slice

**Repay TD-1 as the next bounded slice** (sprint id/epic attachment by
master scan — TD-1's owner field says lifecycle/integration-boundary epic
E2). Compensation design (brainstorm → spec → master ratification of §5
decisions) follows as the next core epic; nothing below pre-decides its
schema, commands or a compensator component.

Candidate DoD for the TD-1 slice:

- `record_evidence` from a work's accepted evidence source whose `event_id`
  equals **any** stored operation id (global scan — the evidence PK
  `(source, event_id)` is store-global, so a cross-work id collides too) is
  rejected atomically before any insert, under a named code, with a persisted
  receipt; malformed-payload handling unchanged.
- Legitimate trusted-local imports pinned: fresh event ids, resends (status
  reporting), other kinds/sources, and the safe post-confirmation direction
  (`SOURCE_EVENT_CONFLICT`) all unchanged.
- Actual accepted-effect reconciliation pinned: dispatch → external commit →
  `_resolve` writes exactly one `verified` accepted proof; the probe's
  record-then-dispatch sequence now ends with intake rejected and the op
  confirming normally; external effect counts asserted in tests.
- Poisoned-store disposition explicitly decided (repair or stated
  limitation) — intake rejection alone does not un-poison an existing store.
- `runtime-boundaries.md` updated same-commit; TD-1 repaid in the tracker
  citing the commit hash; `verification.md`/`interventions.md` TD-1-deferred
  mentions updated; existing 702-test battery and all five gates green;
  Python ≥3.9 / stdlib / schema 1 / no UI unchanged.

Missing design decisions needing master ruling — TD-1 slice: (a) rejection
predicate scope: source-equality (any kind whose configured source is the
accepted source) vs literal `kind == "accepted"` (equivalent in both
families today; source-equality is the robust rule); (b) new code name vs
reusing `SOURCE_EVENT_CONFLICT`; (c) whether `_resolve` should also degrade a
collision on an already-poisoned store to a durable `needs_attention`
outcome instead of the IntegrityError loop, or stay intake-only per the
repayment criterion; (d) whether the synthetic-acceptance-verification
boundary (trusted accepted source can satisfy E08 without any external
effect — probe §3.3) gets a doc note in this slice or stays separate.
Compensation epic (all open, none pre-decided): capability naming and
proposing authority (owner with capability / intervener / dedicated grant);
policy-layer vs runtime-layer admission of the op-link check; linkage payload
shape and business-key derivation for compensation operations; whether the
confirmed compensation writes any proof and which kind; closure-snapshot
disposition of compensated operations (ack set semantics); scope of
families (expense-only vs both) and of lifecycle window (active-cancellation
only vs post-closure correction à la S8 Q2); interaction with revoked
accepted proofs (compensation addresses effects, not requirements — assumed
orthogonal, needs ruling); viewer/inspection surfacing.

Alternatives considered: **A1** compensation first with TD-1 folded in as a
precondition task — rejected: conflates a ratified debt repayment with a
feature needing its own design cycle, and hides the new blast-radius
evidence; **A2** TD-1 repair plus compensation *spec* in one sprint — viable
if the master wants the design pipeline warm, at the cost of single-purpose
focus; **A3** keep TD-1 as a permanent documented limitation — rejected:
repayment was already ratified at D37 and recover-liveness now affects every
future recovery-path feature, not just the misused work.

## 6. Risks and limits of this recon

Read-only reconnaissance plus one /tmp probe on a fresh store; no full
battery was run (per dispatch; HEAD is the accepted S8 release whose gates
are recorded in the acceptance). The probe's rowid-ordering observation is
mechanism-specific (SQLite row order is an implementation detail, not a
contract) but the starvation consequence is deterministic for any operation
stored after the poisoned row. Severity of TD-1 remains medium (trusted-local
misuse only; signed ingress cannot produce it — `ingress.py:25-27`), and the
synthetic-acceptance fact is the documented trusted-local boundary, not a
new defect. This note allocates no epic/sprint ids, mutates no ledger, and
recommends rather than decides; every §5 ruling belongs to the master.

## Handover

[TD-1](../../docs/tech-debt-tracker.md) repayment is the recommended next
bounded slice, grounded in the probe evidence above; compensation execution
is the following core epic and needs the §5 design rulings first. Probe
script and stores stay in `/tmp/next-core-recon-2026-10-15/` (throwaway, not
committed). [Roadmap](../../docs/roadmap.md) ·
[E3](../../docs/superpowers/roadmaps/2026-10-13-intervention-and-policy-evolution.md) ·
[E8](../../docs/superpowers/roadmaps/2026-10-14-evidence-revocation.md) ·
[S8 acceptance](../../docs/superpowers/acceptances/2026-10-15-S8-acceptance.md)
