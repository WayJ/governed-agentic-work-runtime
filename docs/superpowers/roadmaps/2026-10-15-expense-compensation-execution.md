---
epic: E10
status: open
date: 2026-10-15
---

# Expense withdrawal as a distinct accountable external operation

## Deliverables

| deliverable | note |
|---|---|
| Linked compensation | Expense-only active cancellation, current owner and capability, stable original link/key. |
| Opt-in external action | Explicit action/link, legacy compatible and additive FakeOA withdrawal store. |
| Truthful adoption | Distinct proof, result/dispositions and actual demo/install/readonly effects. |

## Definition of Done

- [ ] Authorized version-bound linked compensation and dispatch revalidation permit expense withdrawal only during active cancellation, preserve ordinary admission/replay/ownership, and reuse immutable original links with separate stable keys.
- [ ] Explicit opt-in action/link execution preserves legacy calls and forward behavior; additive adapter migration, per-key receipts and per-original withdrawal effects remain race-safe, queryable and idempotent with truthful counts.
- [ ] Actual results bind original effects, use withdrawn proof semantics and preserve original history; stored adapter results and cancellation dispositions expose refusal without false reversal or forward acceptance.
- [ ] Meaningful RED/GREEN, lost-response/process-death, revision/link/alias/legacy/concurrency tests and readonly inspection prove one retained original and withdrawal effect; generic assets and publishing remain valid without UI changes.
- [ ] A no-credentials compensation-demo and installed module plus console trials prove actual stored links/effects/closure; Python>=3.9/schema1/zero dependencies, full tests, five gates, six demos, fourteen rehearsal tests and installed verification pass with exact counts/skips.
- [ ] Independent acceptance precedes integration ordinary main merge/non-force push with same-commit runtime/adapter boundary docs, truthful bounded compensation coverage and exact final remote equality/CI; unimplemented family/window/auth/fencing guarantees remain unclaimed.

## Sprint Breakdown

| sprint | state | note |
|---|---|---|
| S10 | started | 2026-10-15 strategic go: S9 merged11919f6/published254c714 exact CI38616203004 independently verified; master resolves both independent reviews in [v2.1](../specs/2026-10-15-compensation-execution-design.md). One core owner then independent assembly/demo wave, bounded DoD covered. Materialized2026-10-15 [S10](../sprints/2026-10-15-S10-plan.md). |

## Decisions (ADR)

| id | decision | rationale | date | evidence |
|---|---|---|---|---|
| D43 | Expense/window scope and linked proposal | Distinct appended action; postclosure/publishing need separate semantics. | 2026-10-15 | [Design](../specs/2026-10-15-compensation-execution-design.md) |
| D44 | Opt-in explicit action/link | Prevent inferred duplicate-submit withdrawal; legacy calls preserved. | 2026-10-15 | [First review](../../../.agents/notes/2026-10-15-compensation-independent-design-review.md) |
| D45 | Withdrawn proof and stored result/disposition | No false E08 proof, refusal/ack remains honest. | 2026-10-15 | [Ratification](../specs/2026-10-15-compensation-execution-design.md) |
| D46 | Receipts/effects separation and serialized migration | Real original existence, alias query/replay/count semantics pinned. | 2026-10-15 | [Second review](../../../.agents/notes/2026-10-15-compensation-independent-design-review-v2.md) |
| D47 | One core owner then independent review/demo | Shared lifecycle/protocol mutations and same-commit docs. | 2026-10-15 | [S9 close](../../../.agents/notes/2026-10-15-S9-close.md) |
| D48 | Actual installed adoption and verified release | No global gate churn or UI/distributed promises. | 2026-10-15 | [Ratification](../specs/2026-10-15-compensation-execution-design.md) |

## Asset Disposition

| asset | disposition | note | date | evidence |
|---|---|---|---|---|
| Runtime/schema/contract | reuse | Additive JSON and opt-in. | 2026-10-15 | [Design](../specs/2026-10-15-compensation-execution-design.md) |
| FakeOA | reuse | Forward behavior preserved, withdrawal distinct. | 2026-10-15 | [Ratification](../specs/2026-10-15-compensation-execution-design.md) |
| S9 TD-1 repair | reuse | Identity/recovery boundary independently published. | 2026-10-15 | [Debt](../../tech-debt-tracker.md) |
| GUI/publishing | reuse | No visual or publishing compensation changes. | 2026-10-15 | [Review](../../../.agents/notes/2026-10-15-compensation-independent-design-review-v2.md) |

## Open Questions

| id | question | status | resolution |
|---|---|---|---|
| Q1 | Action and exactoriginal binding? | closed | D44 explicit opt-in, [ratification](../specs/2026-10-15-compensation-execution-design.md), 2026-10-15. |
| Q2 | Migration/replay/effect accounting? | closed | D46 reviewed receipt and effect identity, serialized migration. |
| Q3 | Failed or unresolved compensation? | closed | D43/D45 failed result explicit; unresolved remains blocker, abandon future. |

## Cross-cutting

| concern | owning epic | note |
|---|---|---|
| Compensation roadmap | E3/E10 | Bounded expense/window slice; broader scope remains. |
| Adapter/evidence trust | E2/E9 | Preserve trusted-local boundary, no auth/keyrotation/fencing. |
