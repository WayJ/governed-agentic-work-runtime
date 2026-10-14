---
epic: E11
status: open
date: 2026-10-15
---

# Configured source signing-key rotation with authenticated key identity

## Deliverables

| deliverable | note |
|---|---|
| Signed optional selector/keyring | Legacy compatible, immutable caller config copy and explicit current key. |
| Rollover/retirement decisions | Single finite clock, postHMAC windows and cache-first prevention. |
| Actual adoption/release | Real store proof demo/install, mapped docs and verified publication. |

## Definition of Done

- [ ] Optional authenticated key_id and validated copied per-source keyrings preserve legacy seven-field canonical signatures and old source configuration while selecting exactly one verification key without fallback guessing.
- [ ] Inclusive configured validity windows and freshness share one finite verification-time sample; malformed, unknown, bad-signature, inactive, retired and invalid-clock outcomes have pinned minimal codes and zero runtime writes.
- [ ] Authentication remains ahead of cache and source authority; same-command re-sign returns original receipts while new-command resends dedupe current proof status, preserving revoked evidence, identities and historical effects/closure.
- [ ] Meaningful real-store RED/GREEN covers both formats, rollover/retirement, copy/type/clock boundaries, replay/grant-loss/conflict and all-table preservation; Python>=3.9/schema1/zero dependencies and existing business/UI behavior remain valid.
- [ ] Rotation-demo and installed module plus console trials prove actual stored identity/history without printing secrets; full tests, five configured gates, seven demos, existing rehearsal coverage and serial installed verification pass with exact counts/skips.
- [ ] Independent acceptance precedes integration ordinary main merge/non-force push with same-commit ingress/signed-evidence docs, honest config-only trust/rollback limits and exact final remote equality/CI.

## Sprint Breakdown

| sprint | state | note |
|---|---|---|
| S11 | started | 2026-10-15 strategic go: S10 mergedb0b28d5/publishedb594d757 exactCI38646424464 independently verified; reviewce07781 F1-F4 ratified beforecode, boundedDoDcovered. [Design](../specs/2026-10-15-source-key-rotation-design.md), no early/deferred start. Materialized2026-10-15 [S11](../sprints/2026-10-15-S11-plan.md). |

## Decisions (ADR)

| id | decision | rationale | date | evidence |
|---|---|---|---|---|
| D49 | Config keyring and optional signed selector | Minimal0.2 gap, no managedregistry/newruntimeauthority. | 2026-10-15 | [Design](../specs/2026-10-15-source-key-rotation-design.md) |
| D50 | Exact ring types and immutable copying | No bool/int traps or live caller-list aliases. | 2026-10-15 | [Review](../../../.agents/notes/2026-10-15-source-key-rotation-independent-design-review.md) |
| D51 | Single finite clock and precise key-denial codes | No NaN freshness fail-open or backdated key acceptance; drop/retain differs. | 2026-10-15 | [Ratification](../specs/2026-10-15-source-key-rotation-design.md) |
| D52 | Authentication beforecache and two resend branches | Cachedhistory unchanged; newcommand reportscurrentstatus; no business identity churn. | 2026-10-15 | [Review](../../../.agents/notes/2026-10-15-source-key-rotation-independent-design-review.md) |
| D53 | Scoped ingress then independent assembly/demo/release | New mapped docs, meaningful store tests and actual installed proof. | 2026-10-15 | [Agreement](../../../AGENTS.md), [ratification](../specs/2026-10-15-source-key-rotation-design.md) |

## Asset Disposition

| asset | disposition | note | date | evidence |
|---|---|---|---|---|
| HMAC/canonicalization/KAT | reuse | Legacy byte contract unchanged. | 2026-10-15 | [Signed evidence](../../signed-evidence.md) |
| Runtime/grants/evidence | reuse | Keyagnostic identity, no new authority/storewrites. | 2026-10-15 | [Recon](../../../.agents/notes/2026-10-15-source-key-rotation-recon.md) |
| Agreement doc-sync | re-order | Master adds ingress row before implementation. | 2026-10-15 | [AGENTS](../../../AGENTS.md) |

## Open Questions

| id | question | status | resolution |
|---|---|---|---|
| Q1 | Config-only or audited live registry? | closed | D49 OptionA, [ratification](../specs/2026-10-15-source-key-rotation-design.md), 2026-10-15. |
| Q2 | Clock/copy/replay/type details? | closed | D50-D52 fold F1-F4 into pinned contract. |

## Cross-cutting

| concern | owning epic | note |
|---|---|---|
| Source trust integration | E2/E11 | Configured shared-key boundary, no tenantauth/TLS/KMS. |
| Business revocation/compensation | E8/E10 | Rotation never changes prior proof/effect validity. |
