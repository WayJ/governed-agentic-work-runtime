---
epic: E14
status: open
date: 2026-10-16
---

# Publishing-family linked compensation (bounded beyond-window slice)

## Deliverables

| deliverable | note |
|---|---|
| Paired unpublish capability | `content.unpublish` linked compensation on the unchanged S10 machinery, inside the active cancellation window. |
| FakePublisher retraction surface | D46-pattern additive store migration, alias receipts, retraction accounting. |
| Retraction demo chapter + installed proof | Additive publish-demo chapter and installer module+console coverage. |

## Definition of Done

- [ ] A current owner holding `content.unpublish` can propose a linked retraction of a published document inside the active cancellation window; the immutable original snapshot, D6 business key, replay/conflict semantics and `withdrawn` proof kind behave exactly as S10 pinned, with `runtime.py`/`adapters.py` byte-unchanged (escalation rule: any needed edit stops and asks the master).
- [ ] The forward publishing path is behavior-identical (no withdraw-by-store-state branch; same-content dedup to the same receipt; identical dispositions/store state) with the single disclosed column-naming INSERT edit; retraction is append-only; `FilePublisher` is untouched and holds at the actions preflight.
- [ ] FakePublisher gains the paired action behind the documented contract ordering (`content.publish` first), additive receipts `action`/`link_digest` migration, a `retractions` table, alias receipts, `ORIGINAL_ABSENT` and the forward-receipt original-existence scan — the verified D46 pattern.
- [ ] The re-publish-after-retraction limit is documented with its reachability note (unreachable through the governed flow; binds the adapter model).
- [ ] `publish-demo` keeps its succeeded-completion story and appends the cancellation+retraction chapter (counts 2/1) with the exact two-id closure; the installer stage is updated same-commit and a new console stage is added; no secrets printed; the five gates, full suite, demo set, rehearsals and serial installed verification pass with exact counts/skips.
- [ ] Independent acceptance precedes integration-owned ordinary main merge/non-force push with same-commit truthfulness docs and the master-owned roadmap 0.3 close-out note.

## Sprint Breakdown

| sprint | state | note |
|---|---|---|
| S14 | started | 2026-10-16 strategic go: S13 merged `f17e4ed`/published `678d7b4` with [CI 38843016908](https://github.com/WayJ/governed-agentic-work-runtime/actions/runs/38843016908) success verified; candidate design `9dd195c` (family-agnosticism 21/21 + review 50/50 probes), independent review `cf70b05` implementable-with-amendments (RF1 byte-pin impossible, RF2 demo restructure), master ratification **D80–D91** (D87 behavior-level pin; D90 additive demo structure (b), counts 2/1). Materialized 2026-10-16 [S14](../sprints/2026-10-16-S14-plan.md). |

## Decisions (ADR)

| id | decision | rationale | date | evidence |
|---|---|---|---|---|
| D80 | Publishing-family scope; post-closure/chains deferred | Smallest coherent slice; deferrals evidence-grounded. | 2026-10-16 | [Recon](../../../.agents/notes/2026-10-16-s14-design-recon.md) |
| D81 | `content.unpublish` paired capability | S10 pairing precedent; no S13 namespace collision. | 2026-10-16 | [Design §3](../specs/2026-10-16-beyond-window-compensation-design.md) |
| D82 | Runtime/adapters byte-unchanged, DoD-pinned with escalation | Family-agnosticism proven by two probes. | 2026-10-16 | [Review](../../../.agents/notes/2026-10-16-s14-independent-design-review.md) |
| D83 | Current-owner authority + grant | Ordinary rule; demo grants updated. | 2026-10-16 | [Design §4](../specs/2026-10-16-beyond-window-compensation-design.md) |
| D84 | D6 key/replay rules verbatim; no new codes | S10 semantics unchanged. | 2026-10-16 | [Design §5](../specs/2026-10-16-beyond-window-compensation-design.md) |
| D85 | `withdrawn` proof kind reused | F7 lifecycle verbatim. | 2026-10-16 | [Recon](../../../.agents/notes/2026-10-16-s14-design-recon.md) |
| D86 | FakePublisher D46-pattern surface; contract order pinned | actions[0] conformance coupling (RF3). | 2026-10-16 | [Review](../../../.agents/notes/2026-10-16-s14-independent-design-review.md) |
| D87 | Forward path pinned at behavior level | Byte pin impossible on migrated table (RF1). | 2026-10-16 | [Review §RF1](../../../.agents/notes/2026-10-16-s14-independent-design-review.md) |
| D88 | FilePublisher untouched | Holds at actions preflight. | 2026-10-16 | [Design](../specs/2026-10-16-beyond-window-compensation-design.md) |
| D89 | Policy pairing attribute, no new version | Q7 default. | 2026-10-16 | [Design §8](../specs/2026-10-16-beyond-window-compensation-design.md) |
| D90 | Additive demo structure (b), counts 2/1; console stage new | (1,1) would silently drop succeeded path (RF2). | 2026-10-16 | [Review §RF2](../../../.agents/notes/2026-10-16-s14-independent-design-review.md) |
| D91 | Same-commit truthfulness docs; roadmap 0.3 at close-out | Owed for truth, not the map (F11); MD-4. | 2026-10-16 | [AGENTS](../../../AGENTS.md) |

## Asset Disposition

| asset | disposition | note | date | evidence |
|---|---|---|---|---|
| S10 compensation machinery | reuse | Proven family-agnostic. | 2026-10-16 | [Interventions](../../interventions.md) |
| FakePublisher store | extend | D46 additive migration pattern. | 2026-10-16 | [Adapter contract](../../adapter-contract.md) |
| publish-demo harness | extend | Additive chapter, existing ending kept. | 2026-10-16 | [Verification](../../verification.md) |

## Open Questions

| id | question | status | resolution |
|---|---|---|---|
| Q1–Q9 | Design §open questions | closed | Ratified defaults in the MASTER ratification section, 2026-10-16 (Q4 sharpened by RF4). |

## Cross-cutting

| concern | owning epic | note |
|---|---|---|
| Business compensation | E10/E14 | Same bounded model, second family; chains remain deferred. |
| Publication withdrawal | E13/E14 | Distinct: sop-store record vs external adapter action. |
