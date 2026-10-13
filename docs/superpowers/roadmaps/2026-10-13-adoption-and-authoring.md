---
epic: E4
status: open
date: 2026-10-13
evidence: ../../roadmap.md
---

# Adoption And Authoring

## Deliverables

Contributor adapter guide and independent guide-only agent rehearsal, static JSON SOP rule-card linting with exact content digests, a real filesystem publication adapter and an inspectable no-credentials adoption harness. External human author feedback, policy publication authority and semantic compilation remain separate follow-ups.

## Definition of Done

- [ ] Static SOP lint has reproducible structural/reference/cycle/provenance diagnostics and exact content digest; valid and invalid examples run without executing textual predicates or conferring policy authority.
- [ ] FilePublisher passes reusable conformance, restart, corruption and concurrent-key tests using real committed filesystem artifacts, with honest retention, uniqueness and process-death/platform boundaries; Runtime/Policy lifecycle code remains unchanged.
- [ ] A no-credentials adoption harness uses existing policy/command/evidence interfaces, recovers a lost response by the original key and completes with exactly one actual committed file; printed inspection commands work.
- [ ] Contributor adapter and SOP guides support a separately reported guide-only Claude rehearsal implementing a third-party-style adapter without lifecycle edits; agent rehearsal is distinguished from uncollected external human feedback.
- [ ] All273 baseline tests and previous demos pass, meaningful RED/GREEN and independent review cover new behavior, configured gates and fresh installed module AND console adoption harness pass with independent file counts/content checks.
- [ ] Append-only independent acceptance precedes main merge; integration alone performs non-force push, remote SHA equality and actual CI verification before publication completion, then master advances the next sprint without waiting for user.

## Sprint Breakdown

| sprint | state | note |
|---|---|---|
| S4 | started | Materialized 2026-10-13: [S4](../sprints/2026-10-13-S4-plan.md). Strategic go after S3 merged273tests/remoteCI: bounded authoring+real local file adapter+adoption harness. 2026-10-13; [design](../specs/2026-10-13-s4-adoption-design.md), [S3 evidence](../../../.agents/notes/2026-10-13-S3-close.md). |

## Decisions (ADR)

| id | decision | rationale | date | evidence |
|---|---|---|---|---|
| D17 | Static JSON rule-card lint before any semantic compiler/publication service | Useful structural author feedback, without pretending prose becomes runtime authority. | 2026-10-13 | [design](../specs/2026-10-13-s4-adoption-design.md) |
| D18 | Real filesystem publication adapter is third extension | Actual artifact and queryable receipt show adapter reuse without network credentials or lifecycle forks. | 2026-10-13 | [design](../specs/2026-10-13-s4-adoption-design.md) |
| D19 | Parallel disjoint foundations then dependent harness and guide rehearsal | Authoring and adapter own separate files; combined demonstration consumes reviewed interfaces. | 2026-10-13 | [design](../specs/2026-10-13-s4-adoption-design.md) |
| D20 | Continue sprints autonomously after actual merge/push/CI | User expressly requests continuous overnight advancement; routine choices recorded, only real external blockers escalated. | 2026-10-13 | [opening note](../../../.agents/notes/2026-10-13-S4-open.md) |

| D22 | Ratify static-lint/schema and atomic file commit boundaries | Business scope separated from normative source, mandatory prohibitions allowed, bounded diagnostics, packaged single-source examples, real subprocess proof and no production crash flags. | 2026-10-13 | [ratified design](../specs/2026-10-13-s4-adoption-design.md) |

## Asset Disposition

| asset | disposition | note | date | evidence |
|---|---|---|---|---|
| S2/S3 Runtime, PublishingPolicy, gateway, conformance | reuse | No lifecycle edits; demonstrate actual independent extension and precise source/recovery limits. | 2026-10-13 | [milestones](../../roadmap.md) |

## Open Questions

| id | question | status | resolution |
|---|---|---|---|
| Q1 | What smallest externally useful integration should this wave demonstrate? | closed | D17–D19: linted authoring input plus real file artifact through existing Runtime; guide-only agent rehearsal. 2026-10-13, [design](../specs/2026-10-13-s4-adoption-design.md). |

## Cross-cutting

| concern | owning epic | note |
|---|---|---|
| Easy trial, accountable actions, explicit trust model | E4 | Preserve E1 guarantees and expand only with evidence. |
