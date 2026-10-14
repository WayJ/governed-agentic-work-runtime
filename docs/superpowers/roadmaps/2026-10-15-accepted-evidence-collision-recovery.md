---
epic: E9
status: open
date: 2026-10-15
---

# Accepted-evidence collision prevention and recoverable external truth

## Deliverables

| deliverable | note |
|---|---|
| Intake reservation | Global stored-operation ids reserved for loaded accepted sources, preserve dedup/source conflict precedence. |
| Existing-store recovery | Actual accepted operation plus explicit immutable conflict snapshot; no fabricated or overwritten proof. |
| Independent repayment/release | Both-family real effect/crash/liveness tests, current docs and exact remote CI. |

## Definition of Done

- [ ] Accepted-source operation-ID intake is rejected atomically with pinned precedence and authority; legitimate imports, resends, old receipts and confirmed-proof conflicts remain valid across works and both policy families.
- [ ] Existing poisoned stores record actual accepted external results and a durable conflict snapshot without altering candidate identity, raw payload or fingerprints; closed outcome/completion history remains intact.
- [ ] Repeated resolution is operation-scoped idempotent and recovery reaches later operations with one retained external effect, original keys and bounded calls; real exception/process-death rollback tests prove atomic retry.
- [ ] Python>=3.9, schema1 and zero runtime dependencies remain; full tests, five configured gates, five demos, standalone rehearsal and installed verification pass with exact counts/skips and truthful trusted-local limits.
- [ ] Independent acceptance precedes integration-owned ordinary main merge/non-force push; runtime boundary docs share the implementation commit, TD-1 repayment cites verified evidence, and exact final remote equality/CI are proven.

## Sprint Breakdown

| sprint | state | note |
|---|---|---|
| S9 | started | 2026-10-15 strategic go: S8 merged40dd635/published635e7b1 with CI38603764253 independently verified; full DoD covers bounded TD-1 repair, independent draft review resolved by [ratification](../specs/2026-10-15-td1-accepted-evidence-collision-design.md#master-ratification--2026-10-15-d38d42-before-implementation). No early/deferred start. Materialized 2026-10-15 [S9](../sprints/2026-10-15-S9-plan.md). |

## Decisions (ADR)

| id | decision | rationale | date | evidence |
|---|---|---|---|---|
| D38 | Repair TD-1 before compensation, including old poisoned stores | Existing recover starvation affects every later effect; prevention-only partial repayment rejected. | 2026-10-15 | [Recon](../../../.agents/notes/2026-10-15-next-core-recon.md) |
| D39 | Per-call loaded-source union, unchanged dedup before reservation | No kind/same-work hole or frozen-policy assumption; conservative over-block disclosed. | 2026-10-15 | [Ratification](../specs/2026-10-15-td1-accepted-evidence-collision-design.md) |
| D40 | Exact conflict snapshot separates candidate from external result | Undefined digest and malformed evidence-id review findings resolved. | 2026-10-15 | [Review](../../../.agents/notes/2026-10-15-TD1-independent-design-review.md) |
| D41 | Confirm real effect, preserve closed history, explicit attention event | No pretend unknown result, proof deletion or silent reopening; existing trusted-import completion boundary unchanged. | 2026-10-15 | [Ratification](../specs/2026-10-15-td1-accepted-evidence-collision-design.md) |
| D42 | One core owner and independent integration, same-commit boundary docs | Real RED/GREEN/crash/effect evidence; S8 doc-sync arrears lesson. | 2026-10-15 | [S8 close](../../../.agents/notes/2026-10-15-S8-close.md) |

## Asset Disposition

| asset | disposition | note | date | evidence |
|---|---|---|---|---|
| Runtime/schema1/adapters | reuse | Existing transaction, authoritative lookup and exact source identity. | 2026-10-15 | [Design](../specs/2026-10-15-td1-accepted-evidence-collision-design.md) |
| TD-1 | re-order | Dedicated E9 repayment carries E2 boundary debt; remains open until evidence. | 2026-10-15 | [Debt](../../tech-debt-tracker.md) |
| GUI/website | reuse | No visual/reader changes; generic event/raw fields already expose conflict. | 2026-10-15 | [Review](../../../.agents/notes/2026-10-15-TD1-independent-design-review.md) |

## Open Questions

| id | question | status | resolution |
|---|---|---|---|
| Q1 | Existing poisoned-store recovery or prevention only? | closed | D38/D41 P2a, [ratification](../specs/2026-10-15-td1-accepted-evidence-collision-design.md), 2026-10-15. |
| Q2 | New completion blocker for imported conflict proof? | closed | D41 no new blocker; trusted-source authority unchanged and explicit. |

## Cross-cutting

| concern | owning epic | note |
|---|---|---|
| Adapter evidence identity | E2/E9 | E9 carries TD-1 repayment; do not claim source-key rotation. |
| Compensation accountability | E3 | Deferred distinct external action; never erase accepted effects. |
