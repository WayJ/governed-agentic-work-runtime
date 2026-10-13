---
epic: E2
status: open
date: 2026-10-13
evidence: ../../roadmap.md
---

# Trusted Adapter Boundaries

## Deliverables

Authenticated source identity boundary, adapter conformance suite, and second-domain reference.

## Definition of Done

- [ ] Two domains use the same lifecycle, adapter guarantees are documented and conformance tests pass; a harness example drives the command protocol.
- [ ] Configured gates, independent acceptance, integration-session merge and verified main push succeed.

## Sprint Breakdown

No stubs allocated yet: refine scope after E1 supplies acceptance evidence. 2026-10-13; [milestone intent](../../roadmap.md).

## Decisions (ADR)

No decisions yet; implementation must wait for a ready sprint and recorded design choices.

## Asset Disposition

| asset | disposition | note | date | evidence |
|---|---|---|---|---|
| Preceding epic implementation | watch | Evaluate reuse at readiness, do not fork lifecycle semantics. | 2026-10-13 | [milestones](../../roadmap.md) |

## Open Questions

| id | question | status | resolution |
|---|---|---|---|
| Q1 | What smallest externally useful integration should this wave demonstrate? | open | Decide before ready. 2026-10-13, [milestones](../../roadmap.md). |

## Cross-cutting

| concern | owning epic | note |
|---|---|---|
| Easy trial, accountable actions, explicit trust model | E2 | Preserve E1 guarantees and expand only with evidence. |
