---
epic: E8
status: open
date: 2026-10-14
evidence: ../../../.agents/notes/2026-10-14-S7-master-release-verification.md
---

# Evidence revocation and retained-effect accountability

## Deliverables

| deliverable | note |
|---|---|
| Explicit durable local evidence revocation | Current authorization/requirements change, immutable source/command history and replay, existing-store compatibility. |
| Auditable recovery and closed-work correction | Prepared/inflight/confirmed effects and waits handled explicitly; original closure preserved. |
| Real visible reproducible proof | Both policy families, no-credentials demo/installed verification, truthful inspection/GUI and docs. |

## Definition of Done

- [ ] Explicit version-bound authorized revocation preserves source identity/payload/fingerprints and historical receipts; replay, stale/cross-work/malformed/retired-authority cases are atomic and revoked candidates never silently reactivate through verification, restart, migration or dedup resend.
- [ ] Current requirements and future action/completion admission react to revoked proof; replacement evidence, wait disposition and prepared-intent handling are explicit and cannot resurrect cancelled waits or dispatch stale permission.
- [ ] In-flight and confirmed external effects retain their original business keys/results and reconcile without extra calls or pretend reversal; closed-work correction preserves original outcome/completion history and explicitly exposes current invalidity/audit attention.
- [ ] Expense and publishing scenarios, meaningful RED/GREEN/real crash rollback/process-death tests, inspect/read-only GUI and installed no-credentials trials prove actual stored truth and external effect counts; any UI change follows DESIGN with actual browser/zero-write proof.
- [ ] Python>=3.9/zero dependencies/existing stores and prior tests/demos remain valid; all configured gates, standalone rehearsal and installed verifier pass with exact coverage/skips, doc-sync current and trusted-local/residual external-race limits truthful.
- [ ] Independent acceptance precedes integration-owned main merge/non-force push; actual final remote equality and exact-SHA CI verified, with usable inspect/GUI/demo instructions and no false compensation/distributed claim.

## Sprint Breakdown

| sprint | state | note |
|---|---|---|
| S8 | started | 2026-10-14 after S7 mergedc324357/published48c01fd and independently verified CI38582122483/Pages38582352604/public8files. Strategic ready: review6bd11d6 and master D33–D37 settle all material choices; DoD covers full current/historical/effect behavior, Materialized2026-10-14 [S8](../sprints/2026-10-14-S8-plan.md), WIP1; no early/deferred dependency. [Design](../specs/2026-10-14-s8-evidence-revocation-design.md). |

## Decisions (ADR)

| id | decision | rationale | date | evidence |
|---|---|---|---|---|
| D32 | Prioritize explicit evidence revocation after S7 | RFC001 permits satisfied→pending while preserving history; current runtime has no revoked state. This is a remaining0.3 core promise, not a new marketing feature. | 2026-10-14 | [Recon](../../../.agents/notes/2026-10-14-next-core-recon.md), [design](../specs/2026-10-14-s8-evidence-revocation-design.md) |

| D33 | Version-bound source/admin revoke command and replay authority | Exact payload/codes/source mapping and explicit replay branch pinned from actual protocol. | 2026-10-14 | [Ratification](../specs/2026-10-14-s8-evidence-revocation-design.md#master-ratification--2026-10-14-d33d37-before-implementation) |
| D34 | Audit correction preserves closure; fix unbound closed-state guard | Master fresh probe confirms D-1; allow proof correction during cancellation/unbound rather than hide invariant failure. | 2026-10-14 | [Review](../../../.agents/notes/2026-10-14-S8-design-review.md) |
| D35 | Dispatch-time holds, immutable effects and actual wait dispositions | Reuse existing revalidation; cover newly live blocker path and no cancelled-wait resurrection. | 2026-10-14 | [Ratification](../specs/2026-10-14-s8-evidence-revocation-design.md) |
| D36 | Permanent revoked rows and explicit new-event replacement | Preserve source fingerprints/historical receipts; no synthetic acceptance or confirmed re-execution. | 2026-10-14 | [Ratification](../specs/2026-10-14-s8-evidence-revocation-design.md) |
| D37 | Derived read-only closure notice and isolated ownership | Preserve exact raw fields/no state annotations; known accepted-source collision tracked, not scope creep. | 2026-10-14 | [TD-1](../../tech-debt-tracker.md) |

## Asset Disposition

| asset | disposition | note | date | evidence |
|---|---|---|---|---|
| Runtime durable command/proof/operation protocol | reuse | Preserve identity/replay/reconciliation and existing stores; source-grant trust explicit. | 2026-10-14 | [Boundaries](../../runtime-boundaries.md) |
| Existing inspect/GUI and real demos | reuse | Actual current validity/history/effects visible; no invented fields or write endpoints. | 2026-10-14 | [GUI](../../gui.md) |

## Open Questions

| id | question | status | resolution |
|---|---|---|---|
| Q1 | Exact command/source/admin authorization and replay representation? | closed | D33–D37 ratification2026-10-14; [design](../specs/2026-10-14-s8-evidence-revocation-design.md), [review](../../../.agents/notes/2026-10-14-S8-design-review.md). |
| Q2 | Closed-work correction/current validity while preserving historical closure? | closed | D33–D37 ratification2026-10-14; [design](../specs/2026-10-14-s8-evidence-revocation-design.md), [review](../../../.agents/notes/2026-10-14-S8-design-review.md). |
| Q3 | Wait and prepared-intent recovery under revoked proof? | closed | D33–D37 ratification2026-10-14; [design](../specs/2026-10-14-s8-evidence-revocation-design.md), [review](../../../.agents/notes/2026-10-14-S8-design-review.md). |
| Q4 | Same source-event resend vs fresh replacement proof semantics? | closed | D33–D37 ratification2026-10-14; [design](../specs/2026-10-14-s8-evidence-revocation-design.md), [review](../../../.agents/notes/2026-10-14-S8-design-review.md). |

## Cross-cutting

| concern | owning epic | note |
|---|---|---|
| Signed evidence source authenticity vs business truth | E2 | Revocation is local trusted decision, not distributed authentication. |
| Real-effect accountability/compensation | E3 | Never erase/reverse already accepted effects by changing local evidence. |
| Offline read-only inspect/GUI | E5/E7 | Real current/historical distinctions, exact raw data and DESIGN/browser proof. |
