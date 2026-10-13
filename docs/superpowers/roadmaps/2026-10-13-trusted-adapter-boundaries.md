---
epic: E2
status: open
date: 2026-10-13
evidence: ../specs/2026-10-13-s2-trusted-boundaries.md
---

# Trusted adapter boundaries and reusable domain execution

## Deliverables

| deliverable | note |
|---|---|
| Signed evidence ingress | HMAC source identity and full envelope integrity before trusted command intake. |
| Adapter contract + reusable conformance suite | Explicit claims, receipt validation and disposable test fixtures. |
| Second domain and protocol harness | Content publication shares Runtime with expense; signed approval, uncertain success, query recovery and evidence-backed completion. |
| Independently verified publication | Supervibe acceptance, integration-session main merge/push and remote SHA/CI evidence. |

## Definition of Done

- [ ] Expense and content publication use the same Runtime implementation; policy-owned accepted evidence is tested.
- [ ] HMAC ingress rejects unknown, impersonated, tampered and expired sources before persistence; valid evidence still requires verification.
- [ ] Both built-in adapters pass reusable conformance tests; exact effect counts, idempotency scope, retention, lookup and uniqueness limits are documented.
- [ ] A no-credentials publication harness drives the command protocol, recovers uncertain acceptance by query, and creates exactly one artifact.
- [ ] Configured gates and fresh installed expense/publication demos outside the checkout pass; coverage and security claims match the tested scope.
- [ ] Behavior changes have observed RED/GREEN evidence and independent integration review; the accepted sprint is merged/pushed by the integration session and remote main is verified.

Amendment 2026-10-13: expanded original two-line DoD into observable S2 criteria before materialization. The original intent (two domains, adapter guarantees/conformance, harness and publication) is preserved. Evidence: [design](../specs/2026-10-13-s2-trusted-boundaries.md).

## Sprint Breakdown

| sprint | state | note |
|---|---|---|
| S2 | started | Materialized 2026-10-13: [S2](../sprints/2026-10-13-S2-plan.md). Go 2026-10-13: S1 merged and CI green; bounded HMAC ingress + adapter foundations followed by publication domain. Evidence: [S1 acceptance](../acceptances/2026-10-13-S1-acceptance.md), [S2 design](../specs/2026-10-13-s2-trusted-boundaries.md). |

## Decisions (ADR)

| id | decision | rationale | date | evidence |
|---|---|---|---|---|
| D4 | HMAC-SHA256 ingress with configured source keys | Demonstrates authenticated source/integrity without dependencies or a network server. Not tenant auth, TLS or proof of business truth. | 2026-10-13 | [design](../specs/2026-10-13-s2-trusted-boundaries.md) |
| D5 | Content publication is the second domain | Non-financial lifecycle exercises approval, content invalidation and query recovery; independent external store. | 2026-10-13 | [design](../specs/2026-10-13-s2-trusted-boundaries.md) |
| D6 | Two independent foundations then dependent domain | Disjoint ownership; integration owns foundation merges, not developer self-merges. No pretend parallelism over missing interfaces. | 2026-10-13 | [design](../specs/2026-10-13-s2-trusted-boundaries.md) |
| D7 | One policy per database remains in prototype | Shared engine is verified through two domains; multi-policy database recovery requires separate design. | 2026-10-13 | [design](../specs/2026-10-13-s2-trusted-boundaries.md) |

| D8 | Ratify builder-check error/source/conformance decisions; reserve accepted ingress | Prevent divergent interfaces, silent serialization coercions and unsigned business completion assumptions before implementation. | 2026-10-13 | [decisions](../../../.agents/notes/2026-10-13-S2-decisions.md) |

## Asset Disposition

| asset | disposition | note | date | evidence |
|---|---|---|---|---|
| S1 Runtime and 63 tests | reuse | Preserve compatibility and enforce regression gates. | 2026-10-13 | [S1 acceptance](../acceptances/2026-10-13-S1-acceptance.md) |
| FakeOA | reuse | Add declared contract, adopt conformance mixin. | 2026-10-13 | [design](../specs/2026-10-13-s2-trusted-boundaries.md) |
| Trust documentation | re-order | Describe optional signed ingress accurately; direct library API stays trusted-local. | 2026-10-13 | [design](../specs/2026-10-13-s2-trusted-boundaries.md) |

## Open Questions

| id | question | status | resolution |
|---|---|---|---|
| Q1 | What smallest externally useful integration should this wave demonstrate? | closed | D4/D5: authenticated evidence ingress plus deterministic publication harness through command protocol; 2026-10-13, [design](../specs/2026-10-13-s2-trusted-boundaries.md). |
| Q2 | Which real enterprise/model framework should follow? | deferred | D5 scope: no-credentials harness first; select real integration after S2 evidence. 2026-10-13, [design](../specs/2026-10-13-s2-trusted-boundaries.md). |

## Cross-cutting

| concern | owning epic | note |
|---|---|---|
| Source authenticity is distinct from evidence truth | E2 | Signed intake does not bypass candidate verification. |
| Cancellation and policy migration | E3 | Preserve existing uncertain-effect behavior for future intervention. |
