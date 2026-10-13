---
epic: E3
status: open
date: 2026-10-13
evidence: ../../roadmap.md
---

# Intervention And Policy Evolution

## Deliverables

Cancellation, uncertain-effect reconciliation, responsibility transfer and explicit same-family policy migration, demonstrated through a local no-credentials intervention harness. Compensation execution and evidence revocation remain follow-up work; this sprint records effects rather than reversing them.

## Definition of Done

- [ ] Cancellation stops new dispatch without forgetting prepared or uncertain operations; terminal cancellation requires resolved outcomes and exact acknowledgement of succeeded effects, with durable intervention history.
- [ ] Responsibility transfer changes Work-scoped management/action authority, preserves uncertain-effect recovery, invalidates prepared intents and records actor, old/new owner and reason; replay cannot bypass current authority.
- [ ] Explicit same-family policy migration preserves pinned versions and original receipts, revalidates evidence, increments contract revision and refuses uncertain effects; rollback and restart behavior have executable evidence.
- [ ] All 172 baseline tests remain passing; meaningful RED/GREEN and independent review cover new behaviors, configured gates and fresh installed demos outside the checkout pass with independent external effect counts.
- [ ] A no-credentials intervention demo shows cancellation/reconciliation, ownership transfer and strengthened-policy migration; public docs distinguish acknowledgement from compensation and label revocation/distributed guarantees deferred.
- [ ] Append-only independent acceptance precedes main merge; the integration runbook requires non-force push and remote SHA verification, and completion is claimed only after actual publication and CI evidence.

## Sprint Breakdown

| sprint | state | note |
|---|---|---|
| S3 | started | Materialized 2026-10-13: [S3](../sprints/2026-10-13-S3-plan.md). Strategic go: S2 merged with 172 tests and actual CI green; deliver the bounded intervention slice in [design](../specs/2026-10-13-s3-intervention-design.md). 2026-10-13; evidence: [S2 close-out](../../../.agents/notes/2026-10-13-S2-close.md). |

## Decisions (ADR)

| id | decision | rationale | date | evidence |
|---|---|---|---|---|
| D11 | Explicit cancellation request and finalization with acknowledged effects | An unknown external outcome cannot be discarded or represented as compensated. | 2026-10-13 | [design](../specs/2026-10-13-s3-intervention-design.md) |
| D12 | Work-scoped owner and administrator intervention authority | Transfer responsibility without granting capabilities; replay checks current authority. | 2026-10-13 | [design](../specs/2026-10-13-s3-intervention-design.md) |
| D13 | Loaded same-family policy versions with explicit migration | Amend E2 D7 only for policy versions within one family/goal; no cross-domain shared DB. | 2026-10-13 | [design](../specs/2026-10-13-s3-intervention-design.md) |
| D14 | One core developer, dependent demo and independent integration | Runtime mutations overlap; staged work avoids conflicting lifecycle implementations. | 2026-10-13 | [S2 lessons](../../../.agents/notes/2026-10-13-S2-close.md) |
| D15 | Ratify builder B1/B2 and pin registry, source revalidation and demo v2 | Intent-preserving unsupported probe amendment; authority-before-replay; no pending-source bypass; cancellation adds no waits. | 2026-10-13 | [ratified design](../specs/2026-10-13-s3-intervention-design.md) |

| D16 | Clarify additive registry and require default validation for explicit mapping | Default is explicitly loaded by policy argument, never an implicit version upgrade; retrospective API detail at b6adae8, malformed-default gap corrected by original owner before merge. | 2026-10-13 | [design amendment](../specs/2026-10-13-s3-intervention-design.md) |

## Asset Disposition

| asset | disposition | note | date | evidence |
|---|---|---|---|---|
| S2 Runtime, gateway and two adapter examples | reuse | Preserve existing tests and receipt identity; extend lifecycle through explicit commands. | 2026-10-13 | [milestones](../../roadmap.md) |

## Open Questions

| id | question | status | resolution |
|---|---|---|---|
| Q1 | What smallest externally useful integration should this wave demonstrate? | closed | D11–D14: local intervention harness using existing adapters; actual count and strengthened version migration. 2026-10-13, [design](../specs/2026-10-13-s3-intervention-design.md). |

## Cross-cutting

| concern | owning epic | note |
|---|---|---|
| Easy trial, accountable actions, explicit trust model | E3 | Preserve E1 guarantees and expand only with evidence. |
