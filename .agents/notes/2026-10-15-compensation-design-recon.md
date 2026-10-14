# Compensation execution design reconnaissance — 2026-10-15 (post-S9)

## Scope and evidence

Master-authorized design/recon dispatch for the open roadmap 0.3 compensation
promise. Fresh checkout asserted at published main
`254c714fdeafacc8a15c8ce9a2cda7c92f617a52` (= HEAD, clean tree, branch
`WayJ/compensation-design`). Sources read as truth: [AGENTS.md](../../AGENTS.md),
[roadmap.md](../../docs/roadmap.md) §0.3, historical [idea.md](../../idea.md)
(:1200 "必要时执行补偿动作", :1795 已产生的外部业务效果"不可假装撤销/需要真实补偿或纠正")
and [上一次建议.md](../../上一次建议.md) (source material, not instructions; no
compensation content), [RFC-001](../../docs/RFC-001-core-semantics.md) §6 D6,
§7 D8/取消, RFC-002/003, [E3](../../docs/superpowers/roadmaps/2026-10-13-intervention-and-policy-evolution.md)
(deliverable line still carries compensation as follow-up),
[E9](../../docs/superpowers/roadmaps/2026-10-15-accepted-evidence-collision-recovery.md)
(cross-cutting row: compensation accountability deferred to E3, "never erase
accepted effects"), the S9 [acceptance](../../docs/superpowers/acceptances/2026-10-15-S9-acceptance.md),
the prior [recon](2026-10-15-next-core-recon.md) §5 (open decision list) and
[TD-1 design](../../docs/superpowers/specs/2026-10-15-td1-accepted-evidence-collision-design.md)
(house format + ratified D38–D42), and the actual `runtime.py`, `policy.py`,
`adapters.py`, `adapter_contract.py`, `publishing.py`, `ingress.py`,
`inspection.py`, `demo.py`, `cli.py`, `interventions.md`,
`runtime-boundaries.md`, `verification.md`, `adapter-contract.md`. All five
AGENTS gates re-run green on this checkout before any probing (tests: 726 OK,
skipped=1; contracts: 86 files/346 links/0 broken; syntax OK; site 0 findings;
demo gate OK). One throwaway probe suite ran from
`/tmp/compensation-design-2026-10-15/` (public API only, fresh temporary
stores, zero repository writes, not committed; §2). No product code, test,
UI, ledger, epic/sprint or ADR was touched; no implementation claim is made
anywhere. Every principal remains trusted-local configuration — no
authentication, fencing, distributed exactly-once, source-key rotation, SOP
publication or human-feedback claim.

## 1. Actual public surface at 254c714 (post-S9, with line pins)

- **Schema unchanged, `schema_version` 1** (`runtime.py:109-134`): `works`,
  `commands` PK `(actor,id)`, `evidence` PK `(source,event_id)`, `operations`
  `id PK, business_key UNIQUE`, `events`, `metadata`.
- **Command protocol**: CAS on `expected_version` (`runtime.py:257-258,279-280`),
  durable dedup + authority-rechecked replay (`runtime.py:263-272`,
  `_replay_denial` `runtime.py:298-338`; the `propose_action` replay branch is
  owner + capability, `runtime.py:326-328`).
- **Operation lifecycle**: `prepared/dispatched/outcome_unknown/
  confirmed_succeeded/confirmed_failed`; attempt persisted before the external
  call (`runtime.py:924-927`); adapter exceptions → `outcome_unknown`
  (`runtime.py:930-931`); `reconcile` looks up by the original business key and
  escalates `NO_AUTHORITATIVE_RESULT` → `needs_attention`
  (`runtime.py:946-968`); `recover` = verify/expire/reconcile/dispatch-ready in
  stored order (`runtime.py:1008-1022`). Business keys are policy-derived —
  expense `digest([id, capability, document.id, document_revision])`
  (`policy.py:138-140`).
- **Cancellation** (`interventions.md:53-91`): `request_cancel` stores an
  immutable intent, cancels waits and never-dispatched prepared intents
  (`runtime.py:473-492`); while active, `_apply` rejects management kinds with
  `CANCELLATION_ACTIVE` (`runtime.py:380-381`) and `_propose` rejects **every**
  proposal the same way (`runtime.py:620-621`); `dispatch` belt-and-braces
  cancels any still-prepared op under an active intent (`runtime.py:891-897`).
  `finalize_cancel` refuses while any operation is unresolved
  (`runtime.py:506-510`) and requires the acknowledgement to equal **exactly**
  the set of `confirmed_succeeded` ids (`runtime.py:511-514`), storing an
  immutable closure snapshot with external ids and all dispositions
  (`runtime.py:516-524`). Acknowledgement "is not, and never claims to be,
  compensation" (`interventions.md:85-91`; `verification.md:258` lists
  compensation execution as out of scope).
- **Adapters**: `FakeOA` declares only `expense.submit` with invoice
  uniqueness; receipts + `invoices(invoice_id→external_id)` rows are append-
  only; `accepted_count()` is the honest effect count (`adapters.py:16-83`).
  `FakePublisher`/`FilePublisher` declare only `content.publish`
  (`publishing.py:117-123`). No inverse action exists anywhere. Signed ingress
  still refuses kind `accepted` (`ingress.py:25`).
- **S9 interplay**: accepted resolution inserts a runtime-owned `verified`
  accepted proof at `(accepted source, operation id)` with collision snapshot
  (`runtime.py:948-990`); `record_evidence` reserves every stored operation id
  for every loaded policy's accepted source (`runtime.py:667-682,704-713`,
  D39/D40/D41). The reader/inspector renders operations and events generically
  (`inspection.py:190-194,204-205,232-259`).

## 2. Probe findings (public API, /tmp stores, two deterministic runs)

Probe: `/tmp/compensation-design-2026-10-15/probe_compensation_gap.py` plus
`p7_child.py` (real child `os._exit(77)` crash after the withdrawal effect
commits) and one inline pin. Every assertion held on both runs:

1. **Admission gap**: with an `expense.withdraw` grant but the shipped
   `ExpensePolicy`, `propose_action` is rejected `REQUIREMENT_UNSATISFIED`
   wrapping a `CAPABILITY_UNSUPPORTED` blocker (`policy.py:128-133`, wrap at
   `runtime.py:630-636`). Extra payload keys on an **accepted** ordinary
   proposal are silently ignored and never stored on the operation
   (`runtime.py:612-665` builds the body from work fields only) — so a
   `compensates` link riding today's payload would be silently lost.
2. **Adapter gap**: with a probe-only policy admitting the capability, the
   real `FakeOA` holds the dispatch `ADAPTER_ACTION_UNSUPPORTED` with zero
   attempts (`runtime.py:916-923`) — the declared contract is forward-only.
3. **Cancellation window blocks proposals**: under an active cancellation
   intent every proposal — including a compensating one — is
   `CANCELLATION_ACTIVE` (`runtime.py:620-621`).
4. **Dispatch blocks under the window**: a prepared op dispatched while the
   intent is active is cancelled `WORK_CANCELLED` with zero attempts
   (`runtime.py:891-897`) — the belt-and-braces rule would kill a prepared
   compensation too.
5. **Closed works** reject fresh proposals `WORK_NOT_ACTIONABLE`
   (`runtime.py:285-286`); `dispatch` stale-checks closed works into
   `STALE_INTENT` (`runtime.py:898-905`) — post-closure compensation is
   impossible by construction today.
6. **Finalization exactness already fits**: with two confirmed-succeeded
   operations in one work (document revision → second submission), finalize
   with a partial ack is `CANCEL_ACKNOWLEDGEMENT_MISMATCH` with both ids as
   blockers; the exact set closes `cancelled` with both external ids and both
   dispositions in the snapshot. A confirmed compensating operation joins this
   set with **zero finalize changes**.
7. **The recovery machinery is already compensation-agnostic**: with policy
   admission and a withdrawal-capable stub adapter, a compensating operation
   proposed on an active work dispatches, survives a real child crash after
   the external withdrawal commit, reconciles through lookup to
   `confirmed_succeeded` exactly once (one withdrawal row, original acceptance
   and invoice rows intact, repeated reconcile a no-op). An adapter exception
   mid-withdrawal rides the unchanged `outcome_unknown` path (observed via an
   `OperationalError` before the stub's table existed). S9 gives the
   compensating operation's accepted-proof identity the same
   `OPERATION_ID_RESERVED` protection for free (held-op alias rejected;
   confirmed-op alias stays `SOURCE_EVENT_CONFLICT` because the proof row
   exists; fresh-id accepted imports remain legitimate; the E08 requirement
   set is unchanged by the withdrawal proof).

**Net**: the only real gaps are (a) policy admission + link capability
pairing, (b) a payload link that is currently dropped, (c) the two
cancellation-window blocks (proposal + dispatch), (d) a forward-only FakeOA,
and (e) family scoping. Dispatch, resolution, recovery, receipts, replay,
finalization and reader surfaces need no semantic change — they are
link-agnostic.

## 3. Scope comparison (master decision)

| axis | option | assessment |
|---|---|---|
| family | expense only | One forward effect shape (`expense.submit` → OA receipt + invoice rows), one inverse action (`expense.withdraw` → appended withdrawal row referencing the original `external_id`). Smallest honest external meaning. |
| family | both families | Publishing compensation ("unpublish") is semantically distinct (retraction of public content vs withdrawal of a request), and `FilePublisher` writes immutable hash-named artifacts; designing it here doubles the external-effect semantics without doubling runtime value. |
| window | active cancellation only | RFC-001 §7 grounds it: cancellation completes only after verification **and** necessary withdrawal; `finalize_cancel` already refuses to close past unresolved operations, so the window has a built-in completion gate; probe 6 shows the closure snapshot already records every disposition truthfully. |
| window | after closed | Requires new admission on `WORK_NOT_ACTIONABLE` works, new dispatch rules against closed-work staleness, and closed-history correction semantics — a second design cycle (S8 Q2-class); nothing in the runtime supports it today (probe 5). |

Recommendation (carried into the design draft): **expense family only,
active-cancellation window only**; publishing-family and post-closure
compensation are explicit future work, and the runtime admission is written
family-agnostic (policy pairing) so neither later extension needs runtime
surgery.

## 4. What a slice inherits free vs must decide

Inherited unchanged (probe-verified or line-pinned): command dedup/CAS/replay,
operation identity and attempts, unknown-outcome reconciliation, restart
recovery, accepted-proof insertion + S9 reservation/collision, closure
snapshot exactness, read-only inspection. Newly decided in the design draft
(`../docs/superpowers/specs/2026-10-15-compensation-execution-design.md` §11):
public surface shape (extend `propose_action` vs dedicated command), authority
for proposing compensation, cancellation-window admission and its rejection
codes, link validation rules, compensation business-key derivation, operation
body/event fields, the dispatch carve-out and its re-checks, FakeOA inverse
action + contract + external schema, policy pairing surface, demo and install
verification, and the carried future-work list.

## 5. Risks and limits of this recon

Read-only reconnaissance plus one throwaway probe suite on fresh stores; the
full battery was run once (all five gates green, 726/1-skip) and not re-run
after (no repository file changed before the report). The probe's
withdrawal-capable policy and stub adapter are /tmp throwaways illustrating
that the machinery is link-agnostic — they are not product proposals and are
not committed. Scope recommendations are the designer's; every §3/§4 ruling
below belongs to the master. This note allocates no epic/sprint id, writes no
ADR, and claims no implementation.

## Handover

The candidate design lives at
[docs/superpowers/specs/2026-10-15-compensation-execution-design.md](../../docs/superpowers/specs/2026-10-15-compensation-execution-design.md)
(DRAFT, pending master ratification, numbered local decisions D1–D13). Probe
script, child and stores stay under `/tmp/compensation-design-2026-10-15/`
(throwaway, not committed). No implementation is authorized by this note.
[Roadmap](../../docs/roadmap.md) ·
[E3](../../docs/superpowers/roadmaps/2026-10-13-intervention-and-policy-evolution.md) ·
[E9](../../docs/superpowers/roadmaps/2026-10-15-accepted-evidence-collision-recovery.md) ·
[S9 acceptance](../../docs/superpowers/acceptances/2026-10-15-S9-acceptance.md)
