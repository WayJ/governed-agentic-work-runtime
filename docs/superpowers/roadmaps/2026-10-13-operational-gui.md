---
epic: E5
status: open
date: 2026-10-13
evidence: ../../roadmap.md
---

# Inspectable local operations GUI

## Deliverables

A local browser UI for real Work state, requirement blockers, evidence and logical operations with event-sequence timeline; business-event metrics with stated definitions. Vanilla HTML/CSS/JavaScript served by Python stdlib, no frontend/runtime dependencies or CDN. Read-only existing SQLite inspection, offline trial and reproducible browser checks. A local CLI start command and actual visible preview after release. Master prioritizes this after the user asks whether a GUI is already available (2026-10-13); current product is CLI-only.

## Definition of Done

- [ ] A browser displays real stored Work snapshots, requirement applicability/fulfillment, source/evidence status, operation attempts/outcomes and durable event order with correct empty/error states; no fabricated timestamps or model-session information.
- [ ] Read-only local HTTP endpoints open existing databases without lifecycle writes or implicit policy evaluation/migration; only loopback bind supported, malformed input/unsupported methods fail clearly and existing core behavior remains unchanged.
- [ ] Business metrics have explicit definitions and fixtures tying counts to persisted records; safe text rendering prevents stored document/event content from executing HTML/JavaScript.
- [ ] The interface works offline with no new dependencies; desktop/narrow layout and actual browser interaction are verified, existing tests/demos/installation stay green.
- [ ] Independent acceptance precedes integration-owned main merge/non-force push; remote equality and actual CI verified, with a usable local preview URL or exact reproducible start instructions and honest local-trust limits.

## Sprint Breakdown

| sprint | state | note |
|---|---|---|
| S5 | planned | Start after S4 merged; WIP1 maintained. Concrete API/view design and builder check before ready. 2026-10-13; [S4](../sprints/2026-10-13-S4-plan.md), [user context](../../../.agents/notes/2026-10-13-autonomous-continuation.md). |

## Decisions (ADR)

| id | decision | rationale | date | evidence |
|---|---|---|---|---|
| D21 | Prioritize an offline local read-only operations GUI after S4 | User asks for a visible GUI; operational history is already a roadmap need. No lifecycle controls or external hosting required for first useful view. | 2026-10-13 | [current public scope](../../roadmap.md) |

## Asset Disposition

| asset | disposition | note | date | evidence |
|---|---|---|---|---|
| SQLite snapshots/events and existing inspect CLI | reuse | Render stored truth, preserve trusted-local boundary and version binding. | 2026-10-13 | [boundaries](../../runtime-boundaries.md) |
| S1–S4 demos and installed verifier | reuse | Fixtures and regression proof, not canned UI mock data. | 2026-10-13 | [verification](../../verification.md) |

## Open Questions

| id | question | status | resolution |
|---|---|---|---|
| Q1 | Which exact read-only API and view layout is smallest useful? | open | Master settles with builder before S5 ready; no routine approval wait. |

## Cross-cutting

| concern | owning epic | note |
|---|---|---|
| Clear local trust, no false live/distributed claims | E5 | Loopback UI is not tenant auth; stored event seq/state_version is logical order, not wall-clock duration. |
