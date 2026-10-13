---
epic: E1
status: open
date: 2026-10-13
evidence: ../../roadmap.md
---

# A reproducible governed-work open-source preview

## Deliverables

| deliverable | note |
|---|---|
| Runnable recovery reference | Preserve the existing local Python/SQLite slice; harden concrete boundary failures through TDD. |
| Honest verification matrix | Map RFC P01–P15 to named tests, partial coverage and deferred scope. |
| Contributor-ready checkout | Validate Markdown links, package installation and both CLI entry points. |
| Supervised release evidence | Separate developer branches and integration session; acceptance record, merge and verified origin/main push. |

## Definition of Done

- [ ] All configured gates pass freshly in the integration worktree.
- [ ] A real worker process dies after external acceptance; recovery produces exactly one FakeOA application.
- [ ] Installation into a fresh virtual environment works; module and console CLI demos run outside the checkout.
- [ ] RFC coverage and local trust limitations are explicit, and local documentation links resolve.
- [ ] Behavior changes have observed RED/GREEN evidence, scoped commits and independent integration review.
- [ ] The integration session merges the accepted sprint into main and pushes without force; origin/main matches the final published commit.

## Sprint Breakdown

| sprint | state | note |
|---|---|---|
| S1 | ready | Runtime boundaries + install/docs verification, then independent integration. Strategic go: existing 35 tests and real crash demo pass. 2026-10-13; evidence: [baseline note](../../../.agents/notes/2026-10-13-baseline.md). |

## Decisions (ADR)

| id | decision | rationale | date | evidence |
|---|---|---|---|---|
| D1 | Preserve Python >=3.9, SQLite and zero runtime dependencies | My implementation choice: maximize easy trial and inspectability; production/distributed execution deferred. Retroactive for inherited prototype: it predates this formal roadmap. | 2026-10-13 | [package](../../../pyproject.toml) |
| D2 | One integration branch per sprint, separate developer worktrees | Isolated ownership plus one release carrier; master supervises and integration session performs merge/push as explicitly requested. | 2026-10-13 | [agreement](../../../AGENTS.md) |
| D3 | Treat 100K stars as reach ambition, measure usefulness first | Acceptance measures runnable recovery, installation and understandable guarantees; no star-count promises. | 2026-10-13 | [milestones](../../roadmap.md) |

## Asset Disposition

| asset | disposition | note | date | evidence |
|---|---|---|---|---|
| RFC001–003 and reference scenarios | reuse | Authoritative design hypotheses, not blanket implementation claims. | 2026-10-13 | [protocol](../../RFC-003-runtime-protocol.md) |
| Uncommitted Python prototype | reuse | Snapshot before fan-out; audit regression boundaries rather than rewrite. | 2026-10-13 | [baseline](../../../.agents/notes/2026-10-13-baseline.md) |
| docs/roadmap.md | re-order | Public milestone overview; dated epic docs become delivery truth source. | 2026-10-13 | [overview](../../roadmap.md) |

## Open Questions

| id | question | status | resolution |
|---|---|---|---|
| Q1 | Which external system should be the first real authenticated integration? | deferred | D1; answer in E2 before building integration. 2026-10-13, [overview](../../roadmap.md). |

## Cross-cutting

| concern | owning epic | note |
|---|---|---|
| Honest authority and recovery claims | E1 | Runtime boundaries and verification matrix are acceptance inputs. |
| Trusted adapter contract and second domain | E2 | Planned in follow-up epic; no premature production claims. |
| Intervention and policy changes | E3 | Follow-up roadmap, dependent on trusted boundaries. |
