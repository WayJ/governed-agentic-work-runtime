---
epic: E12
status: open
date: 2026-10-15
---

# Governed SOP rule-card publication (authority approvals + immutable store)

## Deliverables

| deliverable | note |
|---|---|
| Governed publication flow | Card work → admission lint → version-bound signed approval → dispatch → immutable artifact, on the unchanged command protocol and gateway. |
| Collision-free store identity and read surface | Digest-based publication key over the unchanged FilePublisher; additive `read_validated`; fail-closed loader/pin with no Runtime wiring. |
| Actual adoption/release | `publication-demo` + installed module/console proof, mapped docs, verified publication. |

## Definition of Done

- [ ] Lint-clean cards publish through the governed flow with exact digests end-to-end (`sop_digest` == `document_digest` == stored `content_digest`); dirty cards fail bounded and unpersisted at admission.
- [ ] Version-bound signed approvals `{digest, policy_version}` verify through the existing gateway (tampered/wrong-version refused, zero intake writes); approver-key rotation interacts exactly as S11 pinned (retired/dropped codes, verbatim cached receipts, current-status resend).
- [ ] The store stays immutable and collision-free: exactly one hash-named artifact per `(policy_id, version)` under the digest-based key; same-version doctored content ⇒ persisted `OPERATION_CONTENT_CONFLICT` after the second work's own approval; response loss after commit recovers the original in one attempt.
- [ ] The loader fails closed: absent version and corrupt artifact are bounded, distinguishable errors; no Runtime wiring, no card→policy compilation — published cards never execute.
- [ ] `publication-demo` proves the whole story with installed module+console trials outside the checkout without printing secrets; full tests, the five configured gates, the existing demo set plus `publication-demo`, rehearsals and serial installed verification pass with exact counts/skips.
- [ ] Independent acceptance precedes integration-owned ordinary main merge/non-force push with same-commit doc pairing, honest operator-discipline boundaries (cross-database store sharing, config-only trust, rollback limits) and exact final remote equality/CI.

## Sprint Breakdown

| sprint | state | note |
|---|---|---|
| S12 | started | 2026-10-15 strategic go: S11 merged `867e968`/published `56a7f2e` with [CI 38669825874](https://github.com/WayJ/governed-agentic-work-runtime/actions/runs/38669825874) success verified; candidate design `e18851a` grounded, independent review `61b50fc` implementable-with-amendments (IR-F1 key collision, IR-F2 revise_document grounding), master ratification **D54–D66** (SPD-3 amended to the digest-based key, §8 re-framed). Materialized 2026-10-15 [S12](../sprints/2026-10-15-S12-plan.md). |

## Decisions (ADR)

| id | decision | rationale | date | evidence |
|---|---|---|---|---|
| D54 | Governed `sop.publish` Work on unchanged protocol/gateway | Composes proven machinery; no new authority model. | 2026-10-15 | [Design](../specs/2026-10-15-sop-publication-design.md) |
| D55 | Thin `SopPublicationStore` wrapper over FilePublisher | Immutable hash-named store already test-pinned. | 2026-10-15 | [Recon](../../../.agents/notes/2026-10-15-s12-design-recon.md) |
| D56 | Digest-based collision-free publication key | Drafted delimiter key provably collides (IR-P16). | 2026-10-15 | [Review](../../../.agents/notes/2026-10-15-s12-independent-design-review.md) |
| D57 | Lint at admission | Reuses `sop_digest` identity chain. | 2026-10-15 | [Design §4](../specs/2026-10-15-sop-publication-design.md) |
| D58 | Version-bound signed `card_approval` | `{digest, policy_version}` precedent verified. | 2026-10-15 | [Design §8](../specs/2026-10-15-sop-publication-design.md) |
| D59 | Bare card as stored document; evidence store is the audit | No envelope format change (Q1 defer). | 2026-10-15 | [Review §4](../../../.agents/notes/2026-10-15-s12-independent-design-review.md) |
| D60 | Wrapper contract keyed uniqueness | Three verified conflict layers. | 2026-10-15 | [Review IR-P14/P15](../../../.agents/notes/2026-10-15-s12-independent-design-review.md) |
| D61 | Additive `read_validated` (None on absent; corrupt bounded) | Corrupt vs absent distinguishable (IR-F4 pin). | 2026-10-15 | [Review §4](../../../.agents/notes/2026-10-15-s12-independent-design-review.md) |
| D62 | Loader/pin functions only, no Runtime wiring | No card→policy execution binding (Q3). | 2026-10-15 | [Design §6](../specs/2026-10-15-sop-publication-design.md) |
| D63 | No withdrawal this slice | Follow-up on the S8 revocation model (Q4). | 2026-10-15 | [Design §10](../specs/2026-10-15-sop-publication-design.md) |
| D64 | `publication-demo` + installer stage, no new global gate | SKR-10 precedent. | 2026-10-15 | [Design §11](../specs/2026-10-15-sop-publication-design.md) |
| D65 | Doc set + master-added doc_sync_map rows | SKR-9 precedent; workers never edit AGENTS.md. | 2026-10-15 | [AGENTS](../../../AGENTS.md) |
| D66 | Cross-work `OPERATION_CONTENT_CONFLICT` with pinned order | Blockers precede business-key (IR-F3 pin). | 2026-10-15 | [Review §4](../../../.agents/notes/2026-10-15-s12-independent-design-review.md) |

## Asset Disposition

| asset | disposition | note | date | evidence |
|---|---|---|---|---|
| FilePublisher store machinery | reuse | Immutable hash-named commit, race/death pins. | 2026-10-15 | [File adapter](../../file-adapter.md) |
| SignedEvidenceGateway + keyrings | reuse | S11 rotation semantics unchanged. | 2026-10-15 | [Signed evidence](../../signed-evidence.md) |
| Grants/authority names | reuse | Trusted-local principals, no authentication claim. | 2026-10-15 | [Runtime boundaries](../../runtime-boundaries.md) |
| Authoring lint/digests | reuse | `sop_digest` == `document_digest` chain. | 2026-10-15 | [SOP authoring](../../sop-authoring.md) |
| Agreement doc-sync | re-order | Master adds publication rows at ratification. | 2026-10-15 | [AGENTS](../../../AGENTS.md) |

## Open Questions

| id | question | status | resolution |
|---|---|---|---|
| Q1–Q7 | Design §13 open questions | closed | Ratified defaults recorded in the MASTER ratification section of the [design](../specs/2026-10-15-sop-publication-design.md), 2026-10-15. |

## Cross-cutting

| concern | owning epic | note |
|---|---|---|
| Source trust integration | E2/E11/E12 | Shared-key boundary; approver rotation reuses S11 semantics. |
| Rule-card authority | E12 / RFC-002 §6 | Trusted-local principals approve exact content; drafts never become rules. |
