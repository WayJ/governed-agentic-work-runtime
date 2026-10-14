# Compensation execution — candidate design (DRAFT)

Status: **DRAFT — pending master ratification.** Amended 2026-10-15 by the
appended **DRAFT v2** (§14) after the independent builder check; where they
conflict, v2 prevails — the v1 text is retained below as history. This is a
candidate design
prepared on the compensation-design checkout at `254c714` (= published main,
clean tree asserted). It allocates no epic or sprint id, writes no ADR,
mutates no roadmap ledger, and is **not** an implementation instruction: no
product code changes until the master ratifies a design and an independent
builder check resolves the draft's open findings. Suggestions below are the
designer's recommendations, each paired with the decision the master owns
(§11). Primary evidence: the post-S9
[recon](../../../.agents/notes/2026-10-15-compensation-design-recon.md) with
its public-API probe (two deterministic runs, /tmp stores), the prior
[next-core recon](../../../.agents/notes/2026-10-15-next-core-recon.md) §5
decision list, the ratified
[TD-1 design](2026-10-15-td1-accepted-evidence-collision-design.md)
(D38–D42), [E3](../roadmaps/2026-10-13-intervention-and-policy-evolution.md)
(the deliverable line still carries compensation as follow-up work),
[E9's](../roadmaps/2026-10-15-accepted-evidence-collision-recovery.md)
cross-cutting row ("compensation accountability … deferred distinct external
action; never erase accepted effects"), [RFC-001](../../../docs/RFC-001-core-semantics.md)
§7 D8 (已创建申请需要撤回 → 创建真实的撤回 Operation，并验证外部结果) and §7's
closure rule (完成核实与必要撤回，…才可关闭为 cancelled), historical
[idea.md](../../../idea.md):1200/:1795 (source material, not instructions),
and the actual runtime sources at this SHA. Everything stays trusted-local:
no authentication, tenant, fencing, distributed exactly-once, source-key
rotation, SOP-publication or human-feedback claim is made or implied.

## 1. Problem (grounded, with line-level citations)

Roadmap [0.3](../../../docs/roadmap.md) still owes compensation execution:
cancellation today stops new effects and acknowledges retained ones, but
"acknowledgement is not compensation"
([interventions.md](../../../docs/interventions.md):85-91) and
[verification.md](../../../docs/verification.md):258 lists compensation as
explicitly out of scope. A compensating capability does not exist at any
layer, and the probe pinned each gap precisely at `254c714`:

- **Policy**: `action_blockers` returns `CAPABILITY_UNSUPPORTED` for every
  capability except `expense.submit` (`policy.py:128-133`), so an
  `expense.withdraw` proposal is rejected `REQUIREMENT_UNSATISFIED` even with
  the grant held.
- **Payload**: `_propose` reads only known fields and builds the operation
  from work state (`runtime.py:612-665`); extra payload keys on an accepted
  proposal are silently dropped — a `compensates` link would vanish, and
  nothing on an operation records what it compensates.
- **Cancellation window**: `_propose` rejects **every** proposal with
  `CANCELLATION_ACTIVE` while an intent is active (`runtime.py:620-621`), and
  `dispatch` cancels any still-prepared operation `WORK_CANCELLED`
  (`runtime.py:891-897`) — the exact window where RFC-001 §7 places the
  "necessary withdrawal" cannot host it today.
- **Adapter**: `FakeOA`'s declared contract is forward-only
  (`adapters.py:16-22`); a withdrawal-capable dispatch is held
  `ADAPTER_ACTION_UNSUPPORTED` with zero attempts (`runtime.py:916-923`).
- **What already works**: with policy admission and a withdrawal-capable
  adapter, the whole dispatch → real-crash-after-effect → reconcile-once →
  confirm machinery, the accepted-proof insertion with S9 reservation, replay
  authority rechecks, and the exact-ack closure snapshot all behave
  link-agnostically (probe findings 6–7). The design's job is the five gaps,
  not the machinery.

## 2. Goals and non-goals

Goals: (a) the smallest useful concrete slice of the 0.3 compensation promise:
a **distinct appended external withdrawal effect** that references the actual
confirmed original operation/external id under a stable independent business
key; (b) truthful effect accounting — an actual withdrawal row/counter and
effect statuses, never a fake `accepted_count()==0` or a deleted
receipt/artifact/proof; (c) exactly one withdrawal per original across
re-proposal, retry, uncertain result and process death; (d) closure that stays
honest — a failed or uncertain compensation blocks or is recorded truthfully,
original effects are never erased; (e) a builder can plan from this document
without user questions.

Non-goals (master constraints carried from the dispatch): no schema change
(stays `1`); Python ≥3.9, stdlib only, zero runtime dependencies; no generic
flag bypass — every new path passes an explicit authority/admission test; no
UI change; no source-key rotation, fencing, SOP publication, human-feedback
loop, or fictional network integration (the external system remains the local
FakeOA stand-in); no epic/sprint/ADR allocation (master's); existing 726-test
baseline, five gates, five demos, 14 rehearsal tests and the installer remain
green and unchanged; the new compensation demo does **not** become a global
gate.

## 3. Scope recommendation (one bounded coherent slice)

**Expense family only, active-cancellation window only** (comparison and
grounding in the [recon](../../../.agents/notes/2026-10-15-compensation-design-recon.md)
§3):

- The active window is where RFC-001 §7 puts compensation (cancellation
  completes only after verification **and** necessary withdrawal), and
  `finalize_cancel`'s `OUTCOME_UNRESOLVED` gate (`runtime.py:506-510`) plus
  exact-ack snapshot (`runtime.py:511-524`) already provide the completion
  gate and truthful closure with zero finalize changes (probe 6).
- Post-closure compensation needs closed-work admission, closed-work dispatch
  and closed-history correction semantics that nothing supports today (probe
  5) — a second design cycle, carried explicitly (§12).
- Publishing-family compensation ("unpublish") is semantically distinct and
  `FilePublisher` artifacts are immutable hash-named files; carried
  explicitly (§12). The runtime admission below is family-agnostic (policy
  pairing), so that later extension needs no runtime surgery.

## 4. Design

### 4.1 Public surface — extend `propose_action` (recommended) vs dedicated command

**Recommendation: extend `propose_action`.** A compensation proposal is the
ordinary proposal protocol plus one link field:

- payload (compensation variant, **exact key set**, `CommandError` on anything
  else): `{capability, contract_revision, plan_revision, document_digest,
  compensates}` where `compensates` is the original operation id (nonempty
  string). The ordinary variant (no `compensates` key) keeps today's lenient
  payload handling unchanged — do not tighten it (regression risk).
- receipt: unchanged proposal shape (`operation_id`,
  `operation_status_at_decision`); the compensating nature is visible in the
  operation body and events (4.4).
- everything reused for free: command dedup/CAS/replay with authority
  recheck (`runtime.py:263-272,298-328`), business-key re-admission
  (`runtime.py:643-656`), operation construction, dispatch/reconcile/recover,
  accepted-proof insertion, finalization.

Alternative (rejected for this slice, documented): a dedicated
`compensate_action` command gives a cleaner payload and its own precedence
slot but duplicates op construction, re-admission and the replay-denial
branch, and still needs the same dispatch carve-out — more surface, no
additional guarantee. (Master decision D2.)

### 4.2 Authority and admission (precedence chain)

Authority (D3): the **current owner holding the compensating capability
grant** — exactly the ordinary `propose_action` rule (`runtime.py:614-619`),
so a former owner cannot compensate after transfer, and replay re-checks the
same way (`runtime.py:326-328`). Interveners/admins without the capability
grant do not compensate in this slice (§11 D3 carries the alternative).

Admission chain for the compensation variant, in order (each step a persisted
business rejection unless marked misuse):

```text
exact payload shape (CommandError, nothing persisted)
→ authority: current owner + capability in grants          AUTHORITY_DENIED
→ active cancellation intent REQUIRED                     CANCELLATION_NOT_REQUESTED (reuse; D4)
→ contract/plan/digest matches (unchanged codes)           CONTRACT_REVISION_MISMATCH /
                                                            PLAN_REVISION_MISMATCH / EVIDENCE_SCOPE_MISMATCH
→ link validation (D5): target exists, same work,
   status == confirmed_succeeded, target is not itself a
   compensation, no policy-pairing mismatch                COMPENSATION_TARGET_INVALID, blockers [target id]
→ policy blockers for the capability (usually empty)       REQUIREMENT_UNSATISFIED / APPLICABILITY_UNRESOLVED
→ pending different-digest guard (unchanged)               OUTCOME_UNRESOLVED
→ business-key lookup → existing op re-admitted (free) / OPERATION_CONTENT_CONFLICT
→ insert compensation operation + events
```

Link semantics (the "samework/sameoriginalconfirmedresult" rule):

- **Confirmed-only**: the target must be `confirmed_succeeded`. An
  `outcome_unknown`/`dispatched` target is rejected — the original must be
  reconciled first; a `confirmed_failed` target is rejected (no effect exists
  to withdraw); `prepared` likewise. This is admission-time truth; the target
  is terminal afterwards (`runtime.py:973-974`), so it cannot change under
  the link.
- **Same work**: cross-work targets are rejected; a withdrawal for another
  work's effect belongs to that work's own window (out of scope).
- **Not a compensation**: a target that itself carries `compensates` is
  rejected — no compensation-of-compensation in this slice (§12).
- **Policy pairing (D10)**: the policy declares the inverse/forward pair as a
  class attribute, e.g. `compensation_capabilities = {"expense.withdraw":
  "expense.submit"}` on `ExpensePolicy`; admission checks
  `target["capability"] == pairing[capability]`. A policy without the
  attribute (or without the entry) yields today's `CAPABILITY_UNSUPPORTED`
  blocker — graceful degradation for custom/old policy objects, and exactly
  how the publishing family stays out of scope without any runtime flag.
- **Requirement/proof state is orthogonal**: admission keys on the target
  operation's confirmed status, never on requirements or proof validity — a
  revoked accepted proof (S8) does not undo the effect, and compensation
  remains admissible; conversely a satisfied requirement does not create a
  compensable effect.

### 4.3 Compensation business key (D6)

**Recommendation: one runtime rule, uniform across families:**
`digest([policy.id, capability, target_operation_id])`. Stable across
same-family policy versions (the family id is the migration invariant), fully
independent of the forward key (different tuple shape → different digest; the
store-global `business_key UNIQUE` then guarantees **at most one compensation
operation per (family, capability, original) in the store**), and it embeds
the actual original operation id the brief requires. Re-proposal under a new
command id returns the same operation (re-admission path is reused).
Alternative: a policy method `compensation_key(...)` — policy-owned identity,
more surface; rejected for the minimal slice. The forward `operation_key`
(`policy.py:138-140`) is never consulted for compensation proposals.

### 4.4 Operation body, receipts and events (additive JSON only)

The compensation operation body is the ordinary body (`runtime.py:657-662`)
plus one additive field:

```json
"compensates": {"operation_id": "<target id>",
                "external_id": "<target external_id at proposal>",
                "capability": "<target capability>"}
```

a snapshot of terminal facts (immutable after proposal by construction).
Ordinary operations are unchanged; every reader treats an absent
`compensates` as an ordinary operation. Events: `OperationPrepared`/
`OperationReadmitted` for a compensation carry the same additive
`compensates` object in the event body (self-describing history; generic
readers unaffected). No new rejection-receipt mechanics: the new codes ride
the normal persisted-receipt protocol and replay verbatim while authority
holds (D8).

### 4.5 Dispatch boundary — the one carve-out (cancellation permitted dispatch)

`dispatch`'s cancellation branch (`runtime.py:891-897`) gains exactly one
exception: **an operation carrying `compensates` is not auto-cancelled by the
active cancellation intent**. This is not a generic flag bypass — the op is
structurally a compensation (admitted only through 4.2, which itself required
the active window), and dispatch still re-runs its full re-checks
(`runtime.py:898-914`): staleness, authority (current owner + capability
grant) and policy blockers — a compensation whose owner lost authority or
whose grants were removed is `held`, exactly like a forward intent. Every
other prepared operation continues to be cancelled `WORK_CANCELLED`
(probe 4 pins the unchanged behavior). `recover` inherits the carve-out
through `dispatch`, so a ready compensation dispatches on restart inside the
window. `request_cancel` itself is untouched (it runs before any
compensation can exist); `transfer_owner` keeps cancelling prepared
compensations (`OWNERSHIP_TRANSFERRED`, `runtime.py:546`) and the new owner
re-proposes through the unchanged re-admission path — uniform invalidation,
documented (D11 notes the residual: there is no public abandon command, see
§12).

### 4.6 Resolution, recovery, receipts (unchanged machinery — probe-verified)

Nothing in `_resolve`/`reconcile`/`recover` changes semantically:

- accepted withdrawal → `confirmed_succeeded` + the runtime-owned accepted
  proof at `(accepted source, withdrawal operation id)` (`runtime.py:984-990`)
  — the S9 reservation already protects that identity
  (`OPERATION_ID_RESERVED` for pre-identity imports; probe 8), and a
  collision resolves through the D40/D41 snapshot path unchanged;
- adapter business rejection → `confirmed_failed` and the work
  `needs_attention` (`runtime.py:993-994`) — an honest "withdrawal refused"
  state; closure remains possible (failed ops are excluded from the ack set)
  and the disposition records the failure;
- uncertain withdrawal (exception, lost response, crash after effect) →
  `outcome_unknown`, reconcile-by-key, `NO_AUTHORITATIVE_RESULT` escalation
  — all unchanged, and `finalize_cancel` keeps refusing while it is
  unresolved: the work cannot close past an uncertain compensation
  (truthful, no invented outcome);
- across crash, repeated reconcile/recover and re-proposal: **exactly one
  withdrawal effect per original** — runtime-side by the stable business key
  (never re-executed while dispatched), adapter-side by key idempotency plus
  the original-id uniqueness below.

### 4.7 Finalization gates and closure (unchanged — probe 6)

`finalize_cancel` needs **zero changes**: the succeeded set automatically
includes the confirmed withdrawal, so the acknowledgement must list the
original **and** withdrawal ids exactly, and the closure snapshot records
both with their external ids plus every disposition — the truthful picture
(one accepted effect, one withdrawal effect, neither erased). An intervener
who decides not to withdraw simply never proposes and finalizes as today; a
proposed-but-undispatched compensation blocks finalize via
`OUTCOME_UNRESOLVED` (there is no public intent-abandon command — §11 D11,
§12).

### 4.8 Adapter action contract and external store (FakeOA)

`FakeOA` gains a real append-only withdrawal action (D9):

- contract: `actions=("expense.submit", "expense.withdraw")`;
  `uniqueness=("invoice.id", "withdrawal.original_external_id")`.
- new table (created `IF NOT EXISTS`, additive; existing stores unaffected):
  `withdrawals(key TEXT PRIMARY KEY, original_external_id TEXT UNIQUE,
  external_id TEXT NOT NULL, digest TEXT NOT NULL)`. The original
  `receipts`/`invoices` rows are never deleted or rewritten.
- `execute(key, document, digest)` resolves the original `external_id` from
  its own `invoices` rows for the document's invoice ids (all rows of one
  acceptance share one external id, `adapters.py:56-58`); idempotent by key
  (same key+digest → same receipt; same key, different digest → `ValueError`,
  the established adapter rule); a **different key targeting an already-
  withdrawn original returns the existing withdrawal receipt** (UNIQUE
  original id → reuse, mirroring `FakePublisher`'s same-content dedup) — no
  second withdrawal row can exist per original; a missing original raises
  (→ `outcome_unknown`, honest inconsistency rather than a fabricated
  rejection).
- receipt shape (extra field beyond the validated three):
  `{"status": "accepted", "external_id": "WD-…", "digest": …,
  "original_external_id": "OA-…"}` — `receipt_is_valid`
  (`adapter_contract.py:62-73`) accepts it unchanged.
- outward effect meaning: `withdrawn_count()` (rows in `withdrawals`) is the
  honest effect counter for demos/tests; `accepted_count()` and the invoices
  table stay intact — the original effect is never counted away.
- `timeout_after_commit` applies to the withdrawal path too, so the
  crash/lost-response demos ride the existing flag.
- Publishing adapters (`FakePublisher`, `FilePublisher`) are untouched; the
  conformance mixin gains nothing family-specific (the withdrawal adapter is
  still key-idempotent with authoritative lookup — existing mixin applies).

### 4.9 Policy layer and migration compatibility (D10)

`ExpensePolicy` gains the `compensation_capabilities` pairing (inherited by
`ExpensePolicyV2`) and stops returning `CAPABILITY_UNSUPPORTED` for the
paired capability (requirement blockers for it are empty — its gate is the
link check, not requirements). `PublishingPolicy` is untouched. No new policy
version is introduced: works pinned to `demo-1`/`demo-2` resolve through the
same family objects and gain the capability together, which is the point
(compensating already-accepted effects on existing works); forward business
keys are untouched, so the documented same-family key-stability obligation
holds. `migrate_policy` is unreachable inside the window
(`CANCELLATION_ACTIVE`) and unaffected outside it. Custom/old policy objects
without the pairing attribute degrade to today's rejection. (Master decision
D10 carries the stricter alternative: a new version whose pairing is
deliberate.)

### 4.10 Store and migration version compatibility

Runtime schema stays `1`; changes are additive JSON on operation bodies and
event bodies plus one additive table in the **adapter's** store. Old stores
open unchanged; readers must treat a missing `compensates` as absent
(standard additive-JSON rule since D40). Old runtime code reading a new store
ignores the unknown field structurally (no code path keys on it). No data
migration, no backfill, nothing rewritten.

### 4.11 Read-only visibility (no UI change)

Zero reader/GUI change: `inspection.py` renders operation bodies and events
generically (`inspection.py:190-194,232-259`) and the web assets whitelist no
event names (S9-verified pattern). The demo prints `inspect` commands whose
raw output already shows the compensating operation, its link and both
external ids — developer-understandable through the existing generic raw
expose. A dedicated viewer surface, if ever wanted, is a separate DESIGN-
bound wave (§12); this slice claims no visual work and therefore no browser
evidence.

## 5. Public stored truth summary (proposed)

| surface | addition |
|---|---|
| command payload | `propose_action` compensation variant with exact key set incl. `compensates` |
| rejection codes | `COMPENSATION_TARGET_INVALID` (new, blockers `[target id]`); reused `CANCELLATION_NOT_REQUESTED` (no active intent); unchanged `CAPABILITY_UNSUPPORTED` path for unpaired capabilities |
| operation JSON | additive `compensates` snapshot `{operation_id, external_id, capability}` |
| event bodies | additive `compensates` on `OperationPrepared`/`OperationReadmitted` for compensations |
| adapter contract | `expense.withdraw` action + `withdrawal.original_external_id` uniqueness |
| external store | append-only `withdrawals` table; `withdrawn_count()` counter |
| reader/UI/GUI | none (generic raw expose only) |

## 6. Proposed tests (RED → GREEN; named, public API; both families where relevant)

RED (fail on current `254c714`):

1. `test_withdrawal_proposal_accepted_during_cancellation_window` — today
   `CANCELLATION_ACTIVE`.
2. `test_withdrawal_requires_active_cancellation` — new code expected (today
   rejected for the wrong reason / KeyError on code).
3. `test_withdrawal_target_must_be_confirmed_succeeded_same_work` —
   prepared/dispatched/outcome_unknown/confirmed_failed/cross-work targets →
   `COMPENSATION_TARGET_INVALID` (unknown-first: reconcile before compensating).
4. `test_withdrawal_target_must_not_be_compensation` — no chaining.
5. `test_withdrawal_business_key_stable_and_distinct` — re-proposal returns
   the same operation id; key differs from the forward key; one store row.
6. `test_dispatch_leaves_compensating_op_but_cancels_forward_ops` — both
   sides of the carve-out in one store (forward op still `WORK_CANCELLED`).
7. `test_withdrawal_appends_exactly_one_row_original_intact` —
   `withdrawn_count()==1`, `accepted_count()==1`, invoices unchanged,
   original op still `confirmed_succeeded` with its receipt/proof.
8. `test_withdrawal_rejected_by_adapter_is_failed_and_closure_stays_truthful`
   — `confirmed_failed`, work `needs_attention`, finalize ack excludes it,
   dispositions record it, original acknowledged exactly.
9. `test_uncertain_withdrawal_blocks_finalize_until_reconciled`.
10. `test_withdrawal_crash_after_effect_recovers_once` — real child death
    (repo `os._exit` idiom) after the withdrawal commits; reconcile confirms
    once; `withdrawn_count()==1`; attempts length 1.
11. `test_finalize_ack_includes_original_and_withdrawal` — exact set, closure
    snapshot with both external ids and dispositions (probe 6 shape).
12. `test_withdrawal_replay_and_authority` — stored receipt replays verbatim;
    owner loss → fresh unpersisted `AUTHORITY_DENIED`; restore → verbatim
    again.
13. `test_recover_dispatches_ready_withdrawal_inside_window`.
14. `test_transfer_owner_invalidates_prepared_withdrawal_and_readmits`.
15. `test_both_policy_versions_compensate` — `demo-1` and `demo-2` works.

GREEN (preservation pins): publishing family unchanged
(`content.*`/withdraw → `CAPABILITY_UNSUPPORTED`, zero adapter changes); S9
reservation covers withdrawal operation ids (held-op alias rejected,
confirmed-op alias `SOURCE_EVENT_CONFLICT`, fresh-id imports valid); ordinary
proposals/payloads unchanged; `needs_attention` stickiness; normal forward
regressions (the existing 726 battery verbatim); schema `1`; no new
dependency.

## 7. Demonstration and installed verification (no new global gate)

- `python3 -m work_runtime compensation-demo` (new
  `work_runtime/compensation_demo.py` + CLI subcommand, mirroring the
  revocation-demo house pattern): accepted expense → `request_cancel` →
  withdrawal proposal with link → real child crash after the withdrawal
  effect (reuse the `worker` subcommand — dispatch is link-agnostic) →
  restart `recover` → reconcile confirms once → `finalize_cancel` with the
  exact two-id ack → closed `cancelled`; printed counts asserted against the
  SQLite stores (`withdrawn_count()==1`, `accepted_count()==1`), never from
  stdout; fresh stores per run; printed `inspect` command runs verbatim.
- Tests in `tests/test_compensation_demo.py` assert states from the stores.
- `scripts/verify_install.py` gains a stage running module **and** console
  `compensation-demo` outside the checkout with independent effect counts
  (S8 precedent). **The five AGENTS gates and their command list stay
  exactly as configured** — the new demo is not wired into any gate (D12).

## 8. Documentation ownership and same-commit rules

| file | owes | rule |
|---|---|---|
| `work_runtime/runtime.py`, `work_runtime/adapters.py` | `docs/runtime-boundaries.md` | same commit (doc_sync_map) |
| `work_runtime/policy.py` | `docs/runtime-boundaries.md` (pairing/admission) + `docs/adapter-contract.md` (inverse action) | same commit |
| `docs/interventions.md` | cancellation section: carve-out, withdrawal-in-window, ack wording update | same commit |
| `docs/verification.md` | out-of-scope line update + new coverage section | same commit |
| `README.md` / `README.zh-CN.md` | demo list entry (if the list is enumerated there) | demo wave |
| `docs/roadmap.md` 0.3 note | release-time update | master/integration wave |

## 9. Delivery waves and dependencies

- **W1 core** (single core developer, TD-1 D42 precedent): `runtime.py`
  (admission, key, body/events, carve-out) + `policy.py` (pairing) +
  `adapters.py` (withdrawal action) + `tests/test_compensation.py` + the
  same-commit boundary/interventions/verification docs. Meaningful RED
  before minimal implementation, GREEN pins after; real crash + external
  effect counts mandatory (not guard-only tests — S8 lesson).
- **W2 demo** (same or second wave): `compensation_demo.py`, CLI, demo
  tests, README entries, `verify_install.py` stage.
- **Independent integration acceptance** precedes the integration-owned
  ordinary merge/non-force push: fresh full battery with exact counts/skips,
  five gates verbatim, five demos + the new demo, 14 rehearsal tests,
  installer, byte-equality of untouched web/data assets (no browser claim),
  doc-sync audit, exact final remote SHA/CI evidence (S9 standard). The
  builder needs no user questions to plan either wave from this document.

## 10. Alternatives considered (summary)

Dedicated `compensate_action` command: cleaner payload, duplicated machinery,
same carve-out needed — rejected (D2). Intervener/admin-only authority:
mirrors finalize, but orphans the capability-grant model and the ownership
transfer invalidation story — rejected for the slice (D3). Post-closure
compensation first: highest eventual value, needs closed-work admission/
dispatch/correction semantics nothing supports — future (D1). Both families
at once: doubles external-effect semantics for no runtime gain — future
(D1). Policy-method business key: policy-owned purity, more surface —
rejected (D6). Adapter-protocol change to pass the link to `execute`:
breaks every existing adapter signature for information the adapter already
owns — rejected. Generic "allow under cancellation" dispatch flag without
the structural link + re-checks: forbidden bypass — rejected by construction.
New policy version gate: stricter but delays the capability for existing
works — rejected (D10). Business-rejection receipt for double-withdrawal
under a different key: loses the exactly-one guarantee at the adapter —
rejected in favor of receipt reuse (D9). Silent finalize auto-abandon of
prepared compensations: discards durable intents dishonestly — rejected
(D11).

## 11. Unresolved master decisions (each with recommendation)

| id | decision | recommendation |
|---|---|---|
| D1 | scope: family + window | **expense-only + active-cancellation window**; publishing and post-closure carried (§12) |
| D2 | surface: extend `propose_action` vs dedicated command | **extend `propose_action`** with exact-key compensation variant (§4.1) |
| D3 | proposing authority | **current owner + capability grant** (ordinary proposal rule); intervener-with-grant alternative noted |
| D4 | no-window rejection code | **reuse `CANCELLATION_NOT_REQUESTED`**; alternative new `COMPENSATION_WITHOUT_CANCELLATION` |
| D5 | link-invalid granularity | **one code `COMPENSATION_TARGET_INVALID`, blockers `[target id]`**; alternative split codes per cause |
| D6 | business-key derivation | **runtime rule `digest([policy.id, capability, target id])`**; alternative policy method |
| D7 | link snapshot fields | `{operation_id, external_id, capability}` (confirm or trim) |
| D8 | event fields | additive `compensates` on `OperationPrepared`/`OperationReadmitted` (confirm) |
| D9 | FakeOA double-withdrawal under a different key | **reuse existing withdrawal receipt** (exactly-one row); alternative business rejection |
| D10 | policy surface | pairing attribute on the family, **no new version**; alternative a new demo-3 whose pairing is deliberate |
| D11 | prepared-but-undispatched compensation at finalize | **accept the `OUTCOME_UNRESOLVED` block**; no public abandon command this slice (future work) |
| D12 | demo/install | new `compensation-demo` + install stage; **not** a global gate (confirm) |
| D13 | reader/GUI | **no UI change**; generic raw expose only (confirm) |

## 12. Explicit future work (carried, not pre-decided)

Post-closure compensation (closed-work admission, dispatch and correction
semantics; S8-Q2-class design); publishing-family compensation
("unpublish"/retraction, incl. `FilePublisher` immutable artifacts); public
abandon of prepared intents (generic operation-lifecycle gap surfaced by
D11); compensation chains/sagas; cross-work compensation; intervener
compensation authority without owner transfer; any viewer surface for
compensations (DESIGN/browser-bound wave). Adjacent roadmap items excluded
here: source-key rotation (0.2), fencing/distributed leases (P13/0.4), SOP
publication, external human feedback.

## 13. Designer self-check (grounded claims vs open items)

Grounded (code/probe-cited at `254c714`): every §1 gap; the link-agnostic
machinery claim (probe 7: real crash, reconcile-once, original intact);
exact-ack closure with multiple succeeded ids (probe 6); S9 reservation
covering compensating operation ids (probe 8); extra-payload-keys-dropped
(pin); generic reader surfaces (code cite); all five gates green pre-work
(726/1-skip, 86/346/0, compileall, site 0, demo OK — this checkout, this
SHA). Recommendations, not facts: §3 scope, §4.1 surface, D1–D13. Open until
master ratification: the entire §11 table plus epic/sprint attachment.
Deliberately undecided (master-owned): every §12 item. Nothing in this
draft was implemented, tested in-product, or claimed as shipped; the probe
suite is throwaway under `/tmp` and its stores are disposable. The
independent builder check should attack in particular: the dispatch
carve-out's sufficiency (can any non-compensation path reach an external
call inside the window?), the business-key collision space, the FakeOA
original-resolution edge cases (multi-invoice documents, duplicate-invoice
rejections), and the finalize-blocking residual (D11).

## 14. DRAFT v2 — builder-check amendments (2026-10-15; supersedes conflicting v1 text; pending master ratification)

This section amends the DRAFT above after the independent builder check
([verbatim copy](../../../.agents/notes/2026-10-15-compensation-independent-design-review.md),
source `00833d8`; original workspace
`compensation-design-review`, clean at that SHA). The v1 text above is retained
verbatim as history; **where v2 conflicts with v1, v2 prevails** (supersession
list in §14.14). The master's preliminary choices recorded here — expense-only
active-cancellation scope, `propose_action` linked variant under
current-owner+capability authority, and alternative **B** (explicit opt-in
action/link execution context with legacy three-positional-args behavior
preserved) — are design rulings only, **not product implementation
authorization**: no code, test, UI or store changes until the master gives
final ratification after an independent second review of this amended
contract. This section still allocates no epic/sprint/ADR id and mutates no
ledger. All line citations below were re-verified against this checkout at
`d683429` (v1 draft commit; identical product code to the review baseline
`254c714`).

### 14.1 Master preliminary choices adopted (restated)

- **Scope (D1)**: expense family only, active-cancellation window only —
  endorsed by the review (§6 of the report) and unchanged from v1 §3.
- **Surface/authority (D2/D3)**: extend `propose_action` with the linked
  compensation variant; proposing authority is the current owner holding the
  compensating capability grant (ordinary rule, `runtime.py:614-619`; replay
  recheck `runtime.py:326-328`).
- **Mechanism (D15 = B)**: backwards-compatible protocol extension — the
  runtime passes the action and the runtime-validated immutable link to
  adapters that **opt in** via their declared contract; legacy adapters keep
  the existing three-positional-args call byte-identically. v1 §10's rejection
  of "adapter-protocol change to pass the link to `execute`" ("breaks every
  existing adapter signature") is **withdrawn as factually incorrect** for
  keyword-with-default extensions (review §3 B). Alternatives A (dedicated
  withdrawal adapter) and C (registry) remain documented as viable future
  variants but are not adopted in this slice; D18 (their conditional extras)
  is dropped.

### 14.2 F1/F2 — explicit action selection and exact-original binding (B, pinned)

**Opt-in surface.** `AdapterContract` (`adapter_contract.py:14-26`) gains one
optional field with a default:

```python
supports_action_context: bool = False
```

Backward compatibility verified against source: the dataclass is constructed
keyword-only everywhere in-repo (`adapters.py:16`, `publishing.py:117`,
`file_adapter.py:213`, `tests/test_adapter_contract.py:21-23,68`); a trailing
defaulted field leaves every existing construction, `valid_contract`, frozen
semantics and the conformance mixin untouched. `_check_invariants`
(`adapter_contract.py:28-46`) gains one check — `supports_action_context` must
be a `bool` (else `ValueError`) — which every existing contract (default
`False`) passes. Name chosen from source conventions (`supports_…` assertion
style of the contract layer); alternatives considered: `action_context`,
`executes_with_context` (rejected: less assertion-like), `supports_kwargs`
(rejected: names the mechanism, not the promise).

**Adapter call protocol.** An opted-in adapter's execute signature is:

```python
def execute(self, key, document, content_digest, *, action=None, compensates=None)
```

- Runtime call rule: contract declares `supports_action_context=True` →
  `adapter.execute(key, document, digest, action=op["capability"],
  compensates=op.get("compensates"))`. For forward operations `action` is the
  forward capability (e.g. `"expense.submit"`) and `compensates` is `None`;
  for compensations `action` is the paired capability (e.g.
  `"expense.withdraw"`) and `compensates` is the operation's immutable link
  snapshot (§4.4: `{operation_id, external_id, capability}`, a terminal-fact
  snapshot taken at proposal; revalidated at dispatch, §14.6).
- Legacy rule: any adapter whose declared contract is absent (legacy
  duck-typed path, `adapter-contract.md` "Optional metadata and legacy
  adapters") or does not set the field is invoked **exactly as today** —
  three positional arguments, never the kwargs. The runtime performs **no
  signature introspection, no `inspect`, no try/except-`TypeError`**
  (a TypeError probe could fire only *after* an effect committed — forbidden);
  the dispatch decision reads the declared contract only, which is
  trusted-local configuration.
- Direct legacy callers of `FakeOA.execute(key, document, digest)` (existing
  tests, `tests/adapter_conformance.py:50-73`) keep working: the kwargs
  default to `None`, and inside `FakeOA` `action=None` means the legacy
  forward call (treated as `"expense.submit"`).

**Action/link guards (runtime and FakeOA, both explicit).**

- Runtime hold, before any attempt or external call: a **compensation**
  operation dispatched to an adapter whose effective contract does not assert
  `supports_action_context=True` is **held** with a new named reason
  **`ADAPTER_ACTION_CONTEXT_UNSUPPORTED`** (zero `attempts`, zero effects,
  work stays out of `needs_attention`, re-dispatchable with an opted-in
  adapter — same semantics as `ADAPTER_ACTION_UNSUPPORTED`,
  `runtime.py:916-923`). This fires **even if the contract's `actions` tuple
  claims the withdraw capability** — declaring the action without the context
  opt-in leaves the adapter unable to receive the binding link. Ordering:
  after the existing declared-capability preflight, immediately before the
  attempt is persisted. A malformed (present-but-invalid) descriptor still
  fails closed `CommandError` before this, unchanged.
- `FakeOA` input guards (raise `ValueError` before any write, misuse class):
  unknown `action` string; `action == "expense.withdraw"` with
  `compensates` absent or not a dict of three nonempty string fields; a
  forward `action` with `compensates` not `None`.
- **No untrusted-document flag bypass**: the action is derived solely from
  the operation's capability and the link solely from the runtime-validated
  operation body; nothing in `document` can select or influence the action —
  a generic forwarding document can never choose withdraw. Forward admission
  is untouched (v1 §4.2 stands for the ordinary variant).

**Digest touchpoints stay exactly as v1 drafted** (this is why B is
recommended): the compensation operation's `document`/`document_digest`
remain the **current frozen work state** (`runtime.py:657-662`; in-window
freezing verified — `revise_document` rejects `CANCELLATION_ACTIVE`,
`runtime.py:380-381,402-412`), so the admission scope check
(`runtime.py:626-629`), the pending different-digest guard
(`runtime.py:637-641`), the dispatch staleness re-check
(`runtime.py:898-905`) and `execute`'s own
`digest(document) != content_digest` check (`adapters.py:40`) plus
`receipt_is_valid` (`adapter_contract.py:62-73`) all apply unchanged. Under B
the adapter **never** consults the document for original binding — the exact
original travels only in `compensates.external_id` (the immutable snapshot),
so the four F1 failure rows (wrong-original, missing-original,
ambiguous-original, duplicate-inversion) are unreachable by construction.

### 14.3 F3 — distinct runtime proof kind `withdrawn` (pinned, with source-mapping decision)

A compensation operation that resolves on an **accepted** withdrawal receipt
inserts a runtime-owned `verified` proof with kind **`"withdrawn"`** — never
`kind: "accepted"` — under the operation's work's accepted source
(`_accepted_source(work)`, `runtime.py:841-847`), event id = operation id:

```json
{"kind": "withdrawn", "status": "verified",
 "data": {"digest": "<op document_digest>", "external_id": "WD-…",
          "original_external_id": "OA-…"}}
```

- **E08 can never be satisfied by a withdrawal proof**: `evaluate`'s
  `has(kind)` matches kind literals (`policy.py:91-93`), so `E08`'s
  `has("accepted")` (`policy.py:124-125`) ignores `withdrawn` at every
  digest — pinned by test including after S8 revocation of the original
  accepted proof (the F3 survival scenario, review P3).
- **Source mapping decision (exact)**: **no** `"withdrawn"` entry is added to
  `evidence_sources`. Consequences, all verified against source and pinned:
  (a) the S9 operation-id reservation covers withdrawn proofs automatically —
  `_reserved_accepted_sources` (`runtime.py:667-682`) reserves every stored
  operation id for every loaded policy's accepted source, and withdrawn
  proofs insert at `(accepted source, operation id)`, the same identity space
  (`runtime.py:704-713,851-868`); (b) `record_evidence` admission rejects
  kind `withdrawn` for **every** actor — `evidence_sources.get("withdrawn")`
  is `None`, so `_receive`'s authority check (`runtime.py:691-692`) denies —
  withdrawn proofs are runtime-owned only, no trusted imports (deliberate
  asymmetry with `accepted`, documented as a boundary in
  `adapter-contract.md`/`verification.md`); (c) S8 revocation of a withdrawn
  proof is **admin-only**: `_revoke_authority` resolves the row's configured
  source by kind (`runtime.py:733`), finds none, and only a `work.intervene`
  administrator can revoke — a runtime-observed withdrawal effect is not
  source-claimable; (d) signed ingress needs no change: the gateway forwards
  non-`accepted` kinds to `record_evidence` (`ingress.py:25,177-190`), where
  (b) denies. Alternative considered and rejected: configuring
  `evidence_sources["withdrawn"]` — it would enable source revocation and
  trusted imports of the new kind, but requires extending the reservation
  union to the withdrawn source, a `validate_evidence` branch, and reopens an
  import surface for zero in-slice need.
- **S9 proof-conflict path unchanged in behavior and shape**: when the
  `(accepted source, operation id)` identity is already occupied, the D40/D41
  snapshot path fires verbatim — the operation records the **actual** result
  (`confirmed_succeeded`, the `WD-…` external id, `proof_conflict` snapshot),
  the conflicting row is untouched, and **no proof of any kind is inserted** —
  in particular never a falsely-forward `accepted` proof. The existing event
  name `AcceptanceProofConflict` (`runtime.py:1003`) is retained for history
  stability and clarified in docs: it names the **accepted-source proof
  identity space** (the runtime-owned proof family), which under this design
  includes withdrawal resolutions; renaming is out of scope.
- `request_completion` is unaffected: a withdrawn proof satisfies no
  requirement, and the in-window slice cannot reach completion anyway.

### 14.4 F4/F5 — per-key receipts + per-original withdrawals; honest counters (pinned)

Two separated surfaces replace v1 §4.8's single-table sketch:

**Adapter store schema (explicit additive migration; this is ADAPTER-store
evolution — the runtime schema stays `1`, and nothing about runtime schema 1
prevents the external stand-in's own additive migration; boundary documented
in `adapter-contract.md`):**

```sql
-- existing, unchanged shape for old stores
CREATE TABLE IF NOT EXISTS receipts (
    key TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL);
-- additive identity columns (ALTER TABLE ADD COLUMN, nullable, no default),
-- added on open when missing (PRAGMA table_info probe):
ALTER TABLE receipts ADD COLUMN action TEXT;       -- NULL = legacy forward row
ALTER TABLE receipts ADD COLUMN link_digest TEXT;  -- NULL = no compensation link
CREATE TABLE IF NOT EXISTS withdrawals (
    original_external_id TEXT PRIMARY KEY,  -- exactly one withdrawal effect per original
    external_id TEXT NOT NULL,              -- the WD-… id of that effect
    key TEXT NOT NULL,                      -- the key that created the effect
    digest TEXT NOT NULL);                  -- the digest of the creating call
```

`receipts` stays the **per-key call/lookup surface** (authoritative by key for
both actions; runtime business keys cannot collide across forward/compensation
because the key tuples differ, `policy.py:138-140` vs §4.3);
`withdrawals` is the **per-original effect surface** (`UNIQUE` by primary
key). Alternative considered: a dedicated withdrawal-receipts table — rejected
because reconcile looks up by business key regardless of action, and one
surface keeps `lookup` total and simple; alias rows (below) also live
naturally beside forward rows. Original `receipts`/`invoices` rows are never
deleted or rewritten.

**Withdrawal execute algorithm (FakeOA, pinned step order):**

1. Guards of §14.2 (action/link shape) and
   `digest(document) != content_digest → ValueError`, all before any write.
2. `BEGIN IMMEDIATE`; receipts row under `key` exists → replay only if
   `digest` equals this call's digest **and** `action` equals this call's
   action **and** `link_digest` equals `digest(compensates)` (**link
   fingerprint idempotency**: same key with a different target conflicts even
   when the document digest is identical) → return the stored result
   byte-identically; any mismatch → `ValueError("Idempotency key reused with
   different content")` (the established adapter rule), zero new effects.
3. No receipts row → `SELECT … FROM withdrawals WHERE original_external_id =
   compensates["external_id"]`:
   - **effect exists** (created earlier, possibly under a different key in a
     cross-runtime shared store): insert a receipts row under the
     *requesting* key with the *requesting* call's digest, this call's
     `action`/`link_digest`, and result `{"status": "accepted",
     "external_id": <same WD-… id>, "digest": <requesting digest>,
     "original_external_id": <original>}` — the **alias** that keeps
     `receipt_is_valid(result, requesting op digest)` true
     (`adapter_contract.py:62-73`) and `lookup(requesting key)` authoritative
     (fixes review P5 failure 1/2). No second `withdrawals` row can exist.
     (Alternative, rejected: a coherent business rejection for the second key
     — loses the exactly-one guarantee's observable confirmation.)
   - **no effect** → verify the original belongs to an actual forward
     acceptance by **store query** — `SELECT 1 FROM invoices WHERE
     external_id = compensates["external_id"] LIMIT 1` (`invoices` rows exist
     only for accepted non-duplicate effects, `adapters.py:51-58`; never
     inferred from the current document's invoice ids):
     - present → create the one effect: new `WD-…` id, insert the
       `withdrawals` row and the receipts row (with `action`/`link_digest`),
       return the accepted receipt.
     - absent → **bounded authoritative business rejection** (supersedes v1's
       "missing original raises → `outcome_unknown`"): insert only a receipts
       row with result `{"status": "rejected", "external_id": "WD-…" + uuid,
       "digest": <call digest>, "original_external_id": <original>, "reason":
       "ORIGINAL_ABSENT"}` — stored and queryable, no `withdrawals` row. The
       runtime resolves `confirmed_failed` and the work `needs_attention`
       (`runtime.py:993-994`); closure remains truthful (§14.6). A *genuine*
       lookup/store failure (exception) still rides `outcome_unknown`
       (`runtime.py:930-931`) — known absence is authoritative, unavailability
       is not.
4. Forward path (`action` `None` or `"expense.submit"`) is byte-identical to
   today (`adapters.py:39-67`): duplicate-invoice submits are **always**
   business-rejected; the forward path never consults `withdrawals` — **no
   automatic withdraw branch by store state** (pins review P2: the
   duplicate-inversion is structurally impossible because the action is
   explicit, not inferred).

**Counters (pinned; both asserted from the SQLite stores, never stdout):**

- `withdrawn_count()` = rows in `withdrawals` (effect rows).
- `accepted_count()` = **distinct forward acceptance effects**: parse each
  receipts row, keep `status == "accepted"` **and** (`action` is `NULL`
  [legacy row] or `action == "expense.submit"`), count distinct
  `external_id`s. This excludes every withdrawal/alias receipt, so one
  submit + one withdrawal keeps `accepted_count() == 1` (v1 §7 assertion
  restored; fixes review F5). Verified while here: `ExpensePolicy.action_blockers`
  for `expense.submit` includes E01 (`policy.py:128-133`), so runtime
  admission requires a nonempty invoice set — but direct adapter callers can
  still accept a zero-invoice document (no invoices rows), so the counter is
  receipts-based, not `invoices`-based, and stays correct on that edge; the
  distinct-`external_id` form counts effects, not receipts rows.

**Recovery truth after a real crash**: the receipts and (for an effect)
withdrawals rows commit in one transaction; crash-after-effect under `key1`
→ `lookup(key1)` returns the digest-valid receipt → reconcile confirms once
(`runtime.py:946-968`); the same holds for an alias row under a second key.
Original receipts/invoices/proofs/completion snapshot are untouched, and
exactly one withdrawal effect exists per original.

### 14.5 Additional receipt validation at resolution (target binding; backwards compatible)

`receipt_is_valid` itself is unchanged (extra fields allowed). For an
operation carrying `compensates`, `_resolve` adds one check after
`receipt_is_valid` (`runtime.py:977`): `result.get("original_external_id")`
must be a nonempty string **equal to** `op["compensates"]["external_id"]`.
A malformed or mismatched target receipt is **quarantined**
(`outcome_unknown` / `ADAPTER_RESULT_INVALID`, work `needs_attention`,
`runtime.py:977-982`) — never a false confirmation that the linked original
was withdrawn. Operations without `compensates` get exactly today's
validation (protocol backwards compatible). The accepted-result **status**
semantics are unchanged: `accepted` withdrawal → `confirmed_succeeded` with
`op["external_id"] = "WD-…"` (the withdrawal's own id; the snapshot's
`external_id` keeps the original `OA-…` id, unaffected); `rejected`
withdrawal → `confirmed_failed` (the receipt's `reason` rides the stored
adapter result for inspection).

### 14.6 F6 — window admission covers fresh AND re-admission; full dispatch revalidation

- **Proposal gate**: the `CANCELLATION_ACTIVE` gate (`runtime.py:620-621`)
  becomes variant-conditional — non-compensation payloads reject
  `CANCELLATION_ACTIVE` under an active intent exactly as today; the
  compensation variant instead **requires** the active intent
  (`CANCELLATION_NOT_REQUESTED` when absent, D4). Because this single gate
  sits **before** the business-key re-admission branch
  (`runtime.py:643-658`), the exemption covers **both** the fresh proposal
  and re-admission paths (fixes review F6/P4f). In-window freezing of
  document/plan/contract (`runtime.py:380-381`) keeps the re-admission
  digest guard (`OPERATION_CONTENT_CONFLICT`, `runtime.py:646-647`)
  unreachable from document drift — the key-dedup story holds as designed.
  `interventions.md`:64-66 ("new waits, proposals and re-admission … are
  rejected `CANCELLATION_ACTIVE`") owes the same-commit sentence stating the
  compensation-variant exception precisely.
- **Dispatch revalidation (full, in order)**: prepared/cancelled early
  return (`runtime.py:887-888`) → belt-and-braces window branches: forward op
  under active intent cancels `WORK_CANCELLED` (`runtime.py:891-897`,
  unchanged); **compensation** op without an active intent cancels
  `STALE_INTENT` (new belt-and-braces mirror, unreachable via public API —
  intents are permanent and `finalize_cancel` blocks on unresolved
  operations, `runtime.py:506-510`); compensation op whose stored link
  re-validation fails (target not `confirmed_succeeded`/same-work/
  non-compensation/pairing — re-derived from the stored target body;
  unreachable in practice because terminal facts are immutable,
  `runtime.py:973-974`) is **held** with reason `COMPENSATION_TARGET_INVALID`
  — visible, never auto-cancelled, never dispatched → then the unchanged
  staleness re-check (`STALE_INTENT`, `runtime.py:898-905`), authority +
  current-grant + policy-blocker re-check (held, `runtime.py:906-914`),
  accepted-source fail-closed (`CommandError`, `runtime.py:915`), declared
  actions preflight (held `ADAPTER_ACTION_UNSUPPORTED`,
  `runtime.py:916-923`), **context hold** (§14.2, held
  `ADAPTER_ACTION_CONTEXT_UNSUPPORTED`), then the attempt is persisted and
  `execute` called with the §14.2 call rule (`runtime.py:924-931`).
- **Finalize/dispositions (unchanged, restated precisely)**: a
  `confirmed_failed` withdrawal is excluded from the ack set, so
  `finalize_cancel` closes with the ack listing **the original only**
  (`runtime.py:511-514`), and the closure snapshot records the failed
  withdrawal disposition (`runtime.py:516-524`) — the acknowledgement text
  and `interventions.md` wording must describe a refused withdrawal as
  "attempted, refused, effect stands": **a necessary withdrawal's refusal is
  explicit description, never a guaranteed reversal**. Prepared/held/
  outcome_unknown compensations keep blocking finalize `OUTCOME_UNRESOLVED`
  (D11; no public abandon this slice — §12). `recover` inherits everything
  through `dispatch`/`reconcile` (`runtime.py:1008-1022`).

### 14.7 F7/F8 under B — caller surfaces unchanged; reconcile stays caller-trusted

With B, one adapter serves both actions (`FakeOA` declares both and opts in),
so the **existing single-adapter worker/CLI/`recover` surfaces remain
byte-compatible** — `run_worker` (`demo.py:107-112`), the `worker` CLI
subcommand, and `recover(adapter)` need no change and no per-capability
mapping. v1 §7's "dispatch is link-agnostic" is restated for B: dispatch
passes the link only to opted-in adapters; all callers hand over one adapter
as today. F7's reconcile preflight is required only under A/C (per-capability
adapters); under B the single two-action adapter makes a wrong-adapter
reconcile a caller wiring error outside the product surface — documented as
the caller's exclusive responsibility (unchanged from today), no code change
(D18 dropped).

### 14.8 Admission and rejection-code precedence (consolidated v2)

Proposal (`_propose`), each step a persisted business rejection unless marked
misuse:

```text
exact payload shape (compensation variant: CommandError, nothing persisted)
→ authority: current owner + capability in grants            AUTHORITY_DENIED
→ window split: forward payload + active intent              CANCELLATION_ACTIVE
              compensation variant + no intent               CANCELLATION_NOT_REQUESTED (D4)
→ contract/plan/digest matches (unchanged codes)             CONTRACT_REVISION_MISMATCH /
                                                              PLAN_REVISION_MISMATCH / EVIDENCE_SCOPE_MISMATCH
→ link validation (D5): target exists, same work,
   confirmed_succeeded, not itself a compensation,
   policy pairing matches                                     COMPENSATION_TARGET_INVALID, blockers [target id]
→ policy blockers for the capability (usually empty)          REQUIREMENT_UNSATISFIED / APPLICABILITY_UNRESOLVED
→ pending different-digest guard (unchanged)                  OUTCOME_UNRESOLVED
→ business-key lookup → re-admitted (free) /                  OPERATION_CONTENT_CONFLICT
→ insert compensation operation + events
```

Unknown-original rule: a target that is `dispatched`/`outcome_unknown` is
`COMPENSATION_TARGET_INVALID` — **the original must be reconciled first**;
`prepared`/`confirmed_failed` and cross-work targets likewise. New/changed
codes in v2: `COMPENSATION_TARGET_INVALID` (admission, above; also the
unreachable dispatch-hold reason), `ADAPTER_ACTION_CONTEXT_UNSUPPORTED`
(dispatch hold), `ORIGINAL_ABSENT` (receipt `reason`, not a rejection code).
`ADAPTER_RESULT_INVALID` extends to cover link-binding mismatch (§14.5).
Everything else — CAS/dedup/replay with authority recheck, exact-shape
`CommandError` — unchanged.

### 14.9 Public stored truth summary (v2 amendment of §5)

| surface | v2 addition/change vs v1 |
|---|---|
| adapter contract | `supports_action_context: bool = False` field; `FakeOA` sets `True` and `actions=("expense.submit", "expense.withdraw")`, `uniqueness=("invoice.id", "withdrawal.original_external_id")` |
| adapter call | opted-in `execute(key, document, content_digest, *, action=None, compensates=None)`; legacy three-positional-args call preserved |
| external store | `receipts` gains nullable `action`/`link_digest` (explicit ALTER migration); new `withdrawals(original_external_id PK, external_id, key, digest)`; alias rows under requesting keys |
| withdrawal receipt | `{"status": "accepted"/"rejected", "external_id": "WD-…", "digest": <call digest>, "original_external_id": "OA-…", ["reason": "ORIGINAL_ABSENT"]}` |
| counters | `accepted_count()` = distinct forward-accepted external ids (legacy/submit action tag); `withdrawn_count()` = `withdrawals` rows |
| proofs | compensation acceptance inserts kind `withdrawn` (data `{digest, external_id, original_external_id}`) at the accepted source; no `withdrawn` source mapping; admin-only revocation; no imports |
| operation JSON | `compensates` snapshot (v1 §4.4 unchanged); on accepted resolution `external_id` = the `WD-…` id, snapshot untouched |
| rejection codes | +`COMPENSATION_TARGET_INVALID`, +`ADAPTER_ACTION_CONTEXT_UNSUPPORTED`, `ADAPTER_RESULT_INVALID` covers link mismatch; `ORIGINAL_ABSENT` receipt reason |
| reader/UI/GUI | none (v1 §4.11 stands) |

### 14.10 TDD matrix (v2 amendments to §6; all public API, real stores, two deterministic runs)

Keep v1's fifteen RED/GREEN tests and add (RED on current `d683429`):

16. `test_withdrawal_binds_linked_original_not_current_document` — the P1
    revision matrix: original accepted at revision r1; document revised to
    r2 (new invoice ids, or ids never submitted, or ids spanning two
    acceptances); compensation links op1; the withdrawn original is always
    op1's `external_id` (from the snapshot), never a current-document
    resolution; invoices of other acceptances untouched.
17. `test_duplicate_invoice_forward_still_rejected_with_withdrawal_store` —
    P2 pin: same invoice ids under a new key are business-rejected with the
    withdrawal-capable store present and populated; no withdrawal occurs.
18. `test_withdrawn_proof_kind_never_satisfies_e08` — P3 pin: forward
    acceptance at digest1 → revise → E08 pending at digest2 → withdrawal
    resolves → E08 **still pending**; stays pending after S8 revocation of
    the original accepted proof; the withdrawn proof is revocable only by an
    admin; `record_evidence`/signed ingress cannot import kind `withdrawn`.
19. `test_different_key_same_original_returns_alias_and_lookup_is_authoritative`
    — P5 pin: effect under key1; execute under key2 (different digest)
    returns a `receipt_is_valid`-true receipt carrying the same `WD-…` id;
    `lookup(key2)` authoritative; `withdrawals` still one row.
20. `test_same_key_different_link_conflicts_even_with_equal_digest` — link
    fingerprint: same key, same document digest, different `compensates` →
    `ValueError`, zero new effects.
21. `test_legacy_adapter_never_receives_kwargs_and_false_marker_holds` — a
    probe adapter records its call args: contract without the field (and an
    absent-contract adapter) receives exactly three positional arguments for
    forward dispatch; a compensation dispatched to a contract that declares
    the withdraw action but `supports_action_context=False` is held
    `ADAPTER_ACTION_CONTEXT_UNSUPPORTED` with zero attempts/effects and
    dispatches with an opted-in adapter afterwards.
22. `test_missing_original_is_bounded_business_rejection` — withdrawal whose
    original external id is absent from the store: receipt
    `status=="rejected"`, `reason=="ORIGINAL_ABSENT"`, op
    `confirmed_failed`, work `needs_attention`, finalize ack = original
    only, disposition records the refusal; a store-level exception instead
    yields `outcome_unknown` (uncertain true absence stays uncertain).
23. `test_withdrawal_receipt_binding_mismatch_is_quarantined` — probe
    adapter returns a digest-valid receipt whose `original_external_id`
    differs from the snapshot → `ADAPTER_RESULT_INVALID` quarantine, no
    confirmation, no proof.
24. `test_withdrawal_readmission_and_transfer_owner_inside_window` — P4f
    flip (re-admission inside the window accepted, re-prepared `ready`,
    actor updated) and P4d/P4e (transfer invalidates the prepared
    compensation `OWNERSHIP_TRANSFERRED`; new owner without the grant
    cannot re-propose; with the grant, re-admission works; outside-window
    re-admission rejects `CANCELLATION_NOT_REQUESTED`/`WORK_NOT_ACTIONABLE`).
25. `test_real_crash_one_withdrawal_one_original_counts` — real child death
    (`os._exit` idiom) after the withdrawal commits; restart `recover`;
    reconcile confirms once; `withdrawn_count()==1`,
    `accepted_count()==1`, attempts length 1, invoices unchanged, finalize
    exact two-id ack, closure snapshot carries both external ids and
    dispositions.
26. `test_old_adapter_store_migrates_additively` — a store written by the
    current `FakeOA` opens under the new one: legacy rows keep `NULL`
    action/link_digest, forward replay still works, new columns/table added
    exactly once.
27. `test_conformance_mixin_unchanged_and_optin_coverage` — the five mixin
    tests pass byte-unchanged via three-positional calls on the upgraded
    `FakeOA`; the mixin gains action/link coverage (opted-in replay with
    explicit kwargs returns the identical receipt with one effect; runs for
    adapters declaring the opt-in, skipped otherwise); withdrawal-specific
    uniqueness stays in the domain suite, not the mixin.

GREEN pins (v2 additions to §6): guards of §14.2 (unknown action, withdraw
without link, forward with link — `ValueError` before any write);
`accepted_count`/`withdrawn_count` semantics incl. zero-invoice edge;
`withdrawn` proof shape and inertness; runtime schema still `1`; publishing
family byte-unchanged; the existing 726-test battery verbatim.

### 14.11 Delivery waves (v2 restatement of §9 — design only, nothing implemented here)

- **W1 core** (single core developer): `adapter_contract.py` (field +
  invariant + doc), `adapters.py` (`FakeOA` opt-in, withdrawal path, store
  migration, counters), `runtime.py` (variant admission, key, body/events,
  window exemption, dispatch revalidation + context hold + kwargs call,
  resolution binding check + `withdrawn` proof kind), `policy.py` (pairing),
  `tests/test_compensation.py` + adapter-contract tests + mixin coverage,
  and the **same-commit boundary docs**: `runtime-boundaries.md`,
  `adapter-contract.md` (opt-in protocol, store schema/migration, counters,
  withdrawn-kind boundary), `interventions.md` (carve-out incl. re-admission,
  refusal-not-reversal wording), `verification.md` (scope + proof-kind
  notes). Meaningful RED before minimal implementation; real crash +
  external effect counts mandatory.
- **W2 demo**: `compensation_demo.py`, CLI subcommand, demo tests, README
  entries, `verify_install.py` stage; **not** a global gate (D12).
- Independent assembly/acceptance precedes the integration-owned merge and
  non-force push (S9 standard: fresh battery with exact counts/skips, five
  gates verbatim, six demos, 14 rehearsal tests, installer, byte-equality of
  untouched assets, doc-sync audit, exact remote SHA/CI).

### 14.12 Decision resolution (D1–D13, review D14–D18, local D19–D24)

| id | resolution in v2 |
|---|---|
| D1 | expense-only + active-cancellation window — confirmed (master preliminary; review-endorsed) |
| D2 | extend `propose_action`, linked variant — confirmed (master preliminary) |
| D3 | current owner + capability grant — confirmed (master preliminary) |
| D4 | `CANCELLATION_NOT_REQUESTED` for compensation without an intent; forward payloads keep `CANCELLATION_ACTIVE` — confirmed |
| D5 | one code `COMPENSATION_TARGET_INVALID`, blockers `[target id]` — confirmed (also the unreachable dispatch-hold reason) |
| D6 | runtime key `digest([policy.id, capability, target_operation_id])` — confirmed |
| D7 | snapshot `{operation_id, external_id, capability}` — confirmed |
| D8 | additive `compensates` on `OperationPrepared`/`OperationReadmitted` — confirmed |
| D9 | superseded by D16 mechanics (alias rows + effect table) |
| D10 | family pairing attribute, no new policy version — confirmed |
| D11 | accept the `OUTCOME_UNRESOLVED` block, no public abandon this slice — confirmed with the F1-row-3 sharpening: known-absent originals now resolve bounded (`ORIGINAL_ABSENT`), so the permanent-block residual survives only for genuinely unavailable lookups (documented §12) |
| D12 | new demo + install stage, not a global gate — confirmed |
| D13 | no UI change — confirmed |
| D14 | distinct proof kind `withdrawn` (§14.3); alternative "no runtime-owned proof" rejected — the proof is the queryable withdrawal truth |
| D15 | **B** — opt-in `action`/`compensates` kwargs (master preliminary); §10's signature-breakage rejection withdrawn; A (+C) documented as viable future variant |
| D16 | per-key receipts rows + per-original `withdrawals` table; different-key reuse inserts a requesting-digest alias row reusing the same `WD-…` id; effect counters count effect surfaces — adopted (§14.4) |
| D17 | window exemption covers fresh **and** re-admission; `interventions.md` same-commit amendment — adopted (§14.6) |
| D18 | dropped (conditional on A/C) |
| D19 (local) | contract field name/default `supports_action_context: bool = False` + bool invariant (§14.2) |
| D20 (local) | hold code `ADAPTER_ACTION_CONTEXT_UNSUPPORTED`, before attempts, fires even when `actions` claims the capability (§14.2) |
| D21 (local) | missing original at execute = stored authoritative business rejection `ORIGINAL_ABSENT`; real lookup unavailability stays `outcome_unknown` (§14.4) |
| D22 (local) | resolution-time link binding check → `ADAPTER_RESULT_INVALID` quarantine; `receipt_is_valid` unchanged (§14.5) |
| D23 (local) | no `withdrawn` evidence-source mapping: proofs ride the accepted-source identity, admin-only revocation, no imports, ingress unchanged (§14.3) |
| D24 (local) | adapter-store additive migration (`receipts.action`/`link_digest` ALTER + `withdrawals` table) and counter semantics (§14.4) |

### 14.13 Remaining for the master (final ratification after second review)

This v2 is builder-ready and resolves F1–F8 and D1–D13/D14–D18 plus local
D19–D24, but it is still a **DRAFT**: the master's preliminary choices are
adopted as design rulings and must be **finally ratified** — together with
the local names/choices D19–D24 (or amended) — after an **independent second
review** of this amended contract, before any W1 dispatch. No implementation
is authorized by this section.

### 14.14 Supersession list (v1 statements overridden here)

1. §4.8 bullet 3 — "resolves the original `external_id` from its own
   `invoices` rows for the document's invoice ids" and all store-state
   inference: superseded by explicit binding (§14.2/§14.4).
2. §4.8 "a different key … returns the existing withdrawal receipt" as a
   same-key-space mechanism and the `withdrawals(key PRIMARY KEY,
   original_external_id UNIQUE …)` schema: superseded by D16/D24 (§14.4).
3. §4.8 "a missing original raises (→ `outcome_unknown` …)": superseded by
   D21 (§14.4).
4. §4.6 first bullet — "accepted withdrawal → … runtime-owned accepted
   proof": superseded by kind `withdrawn` (§14.3); the reservation, conflict
   path and shapes otherwise stand.
5. §10 — "Adapter-protocol change to pass the link to `execute`: breaks
   every existing adapter signature … rejected": withdrawn; B adopted (D15).
6. §10 — "Business-rejection receipt for double-withdrawal under a different
   key: … rejected in favor of receipt reuse (D9)": D9's mechanics replaced
   by D16 (alias rows); the business-rejection alternative remains rejected.
7. §5 rows for adapter contract/external store: amended by §14.9.
8. §4.2's chain: amended by the explicit window split (§14.8); §4.5's
   carve-out stands, with the §14.6 re-admission/belt-and-braces
   amendments.

Everything in v1 not listed here — including §2 goals, §3 scope, §4.1/§4.3/
§4.4/§4.7/§4.9/§4.10/§4.11, §6 tests 1–15, §7 demo shape, §12 future work —
stands as drafted, with §12 additionally carrying the sharpened D11 residual
(known-absent originals resolve bounded; only genuinely unavailable lookups
can block closure indefinitely pending a future abandon command).

## 15. MASTER ratification v2.1 - 2026-10-15 D43-D48 (before implementation)

This final design overrides contradictory draft v1/v2 suggestions; section14 otherwise governs. Choices belong to master under autonomous user authorization. Independent [second review2edc57b](../../../.agents/notes/2026-10-15-compensation-independent-design-review-v2.md) supplies A1-A4/C1-C4 corrections below. First review00833d8 and d683429/e25d170 drafts remain historical. These bounded reviewed fixes and meaningful tests resolve the design before implementation.

- **D43:** expense-only active-cancellation scope; linked propose_action by current owner+capability, runtime key digest([policy.id,capability,target_operation_id]), immutable compensates {operation_id,external_id,capability}. DraftD1-D13 ratified as amended. Failed withdrawal may close under existing explicit-ack cancellation with refusal recorded and original effect retained; no guaranteed reversal. Prepared/held/outcome_unknown compensations block finalize without abandon; lookup unavailability is only one cause. Publishing/postclosure/chains/abandon remain future.
- **D44:** B opt-in supports_action_context bool defaultFalse. Actions preflight then compensation without opt-in held ADAPTER_ACTION_CONTEXT_UNSUPPORTED before attempts/calls. Opted adapters receive explicit action and immutable link; legacy exactly three positional arguments. FakeOA-only action=None normalizes submit; not generic protocol. Proposal/dispatch revalidate target id exists/samework/confirmed_succeeded/noncompensation/current pairing and snapshot external_id/capability equality. Fresh AND re-admission window exceptions; re-admission never rebinds link. No signature introspection/TypeError fallback. Single-adapter reconcile remains caller-trusted store lookup, no authentication claim.
- **D45:** compensation original_external_id binding check BEFORE accepted/rejected split, plus existing receipt validation. Invalid target quarantines ADAPTER_RESULT_INVALID without proof/confirmation, repeated quarantine bounded. Valid compensation result adds full validated adapter_result to operation JSON. finalize_cancel adds compensates and adapter_result when present ONLY to compensation dispositions; ordinary shape unchanged, no old closure rewritten. Exact succeeded-id ack includes original+succeeded withdrawal, excludes failed withdrawal. Accepted withdrawal uses verified withdrawn proof with original_external_id, never forward accepted-kind proof/E08. No withdrawn source mapping: no imports/admin-only revoke. S9 conflict/reservation snapshot/event behavior unchanged; actual withdrawal result recorded on collision. Existing general invalid-result custom/corrupt-state repair not expanded.
- **D46:** receipts nullable action/link_digest and withdrawals effect table per v2. Original existence MUST match accepted FORWARD receipt external_id (normalized NULL/expense.submit), including direct zero-invoice effects; invoices-only lookup cannot declare absence. Known absence produces queryable rejected ORIGINAL_ABSENT, real store failure remains unknown. Probe+ALTER+table setup under BEGIN IMMEDIATE, PRAGMA probe INSIDE transaction; named-column receipts INSERT EVERY path. New forward action explicit expense.submit, legacy NULL normalized on read. Forward BEHAVIOR preserved, SQL necessarily changes; old receipt digest/result/invoices untouched. BOTH forward/withdraw replay validate digest+normalized action+link fingerprint (forward NULL), mismatch ValueError before writes/effects. Differentkey/sameoriginal inserts requesting-digest/action/link alias with same WD id, lookup authoritative. One withdrawal row per original; accepted_count distinct forward accepted external_ids including legacy, excludes withdrawal/aliases; withdrawn_count effectrows. Runtime schema1, adapter schema migration explicit.
- **D47:** all v1/v2 meaningful tests plus reviewed amendments: zero-invoice receipt presence, named writes/legacy replay, concurrent first-open/reopen, forward cross-action/link conflict; rejected target mismatch/repeated quarantine; stored adapter_result and compensation dispositions; unresolved blockers; generic opt-in conformance action from fixture hook/contract, never hardcoded expense.submit. Revision matrix/duplicate-invoice/revoked original/withdrawn inertness, legacy zero kwargs, falsemarker hold zero attempts/effects, alias changeddigest/lostresponse, real child death and one forward+one withdrawal effect. Single core then independent assembly before demo; runtime AND adapters boundary docs SAME code commit, corresponding contract/intervention/verification docs current.
- **D48:** compensation-demo and installed module+console outsidecheckout with actual links/counts/closure, five gates unchanged, six demos explicit scenario, 726baseline+new/full14rehearsal/install. No UI/reader feature; raw inspector/events/table equality plus untouchedasset regression, no visual compliance invented. Independent acceptance then integration ordinary main merge/nonforcepush/exactfinalremoteCI, preserve trees/preview, master never merges/pushes. No production/auth/fencing/distributed exactlyonce/keyrotation/fullfamily compensation claim.

LocalD14-D24 and MD1-MD5 ratified by D44-D47 as amended; A1-A4/C1-C4/m1-m5 resolved. Failed product tests route to coordinator with evidence, never silently change contract.
