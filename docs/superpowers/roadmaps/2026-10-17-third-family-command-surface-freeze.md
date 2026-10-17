---
epic: E15
status: open
date: 2026-10-17
---

# Third business family: command-surface freeze acceptance

## Deliverables

| deliverable | note |
|---|---|
| Third business family (policy + adapter) | A new family over the unchanged command protocol; candidate domain vendor payment, final selection at S15 design recon (Q1). |
| Family demo + installed proof | Clean-clone, no-credentials chapter joining the demo set and the installer module/console stages (D90 additive pattern). |
| Freeze acceptance verdict | Hash pins on lifecycle internals with an escalation rule; the zero-edit outcome — or a disclosed freeze gap — written into truth docs. |

## Definition of Done

- [ ] A third business family runs end-to-end over the unchanged command protocol — proposal admission (including an unknown-applicability blocking rule), dispatch with result-unknown fencing, receipt reconciliation and business closure — with `work_runtime/runtime.py` and `work_runtime/adapters.py` byte-unchanged (hash-pinned; escalation rule: any required lifecycle edit stops and asks the master, and is recorded as a disclosed freeze-gap finding, never silently absorbed).
- [ ] The family adapter passes the public conformance mixin without lifecycle edits; family policy rules are new code preserving unknown semantics (an unknown amount can never pass as within-limit).
- [ ] The family demo runs from a clean clone without credentials or services, prints no secrets, and the installer module/console stages are updated same-commit with exact counts and every skip delta explained.
- [ ] Deferrals hold: no post-closure compensation, no compensation chains, no new lifecycle commands (D94).
- [ ] The five gates, full suite, demo set, rehearsals and serial installed verification pass with exact counts/skips; independent acceptance precedes the integration-owned ordinary main merge and non-force push, with truth docs and the roadmap note same-commit.

## Sprint Breakdown

| sprint | state | note |
|---|---|---|
| S15 | ready | 2026-10-17 owner decision: proceed per the adopted order ("其他的按照你推荐来进行。直接开始吧"). Strategic go verified against the DoD: design recon resolved Q1 (support-ticket family) and Q2 (forward + crash-recovery chapters) with byte pins and scope guard — [recon](../../../.agents/notes/2026-10-17-s15-design-recon.md). First slice: third-family command-surface freeze acceptance. Materialization follows per supervibe:start. |

## Decisions (ADR)

| id | decision | rationale | date | evidence |
|---|---|---|---|---|
| D92 | Adopt the 2026-10-17 owner-endorsed order: freeze the command surface first (third family, zero lifecycle edits), then a credential-holding adapter host with one real external write path, then one rule-card binding experiment | The S14 close-out recorded the next direction as an owner-level decision; the owner selected the advice order on 2026-10-17 | 2026-10-17 | [Advice](../../../上一次建议.md) |
| D93 | E15 scope is the third-family freeze acceptance only; entry-point consolidation, the adapter host and the binding experiment are separately scheduled follow-ups (Q3/Q4) | Smallest coherent slice (D80 precedent); keeps the acceptance unambiguous | 2026-10-17 | [S14 close](../../../.agents/notes/2026-10-16-S14-close.md) |
| D94 | Post-closure compensation and compensation chains stay unimplemented; the active-window compensation boundary is endorsed as-is | The advice explicitly endorses stopping at the current window semantics; this boundary is worth more than "completing" revocation | 2026-10-17 | [Advice](../../../上一次建议.md) |
| D95 | Runtime ledger stays SQLite; storage re-selection stays gated on the 0.4 concurrency measurement; PostgreSQL is recorded as a runner-up EXTERNAL system ([E16/D96](2026-10-17-adapter-host-real-external-write-path.md)), not a ledger migration | Zero-dependency clean-clone promise; single-process single-writer means SQLite already pins the transaction boundary; PG's value (multi-writer coordination) is exactly the deferred domain | 2026-10-17 | [Roadmap §0.4](../../roadmap.md) |

## Asset Disposition

| asset | disposition | note | date | evidence |
|---|---|---|---|---|
| Command protocol / lifecycle internals | reuse | Freeze target: byte-unchanged, hash-pinned | 2026-10-17 | [Runtime boundaries](../../runtime-boundaries.md) |
| Adapter conformance mixin | reuse | Public conformance tests, no lifecycle edits | 2026-10-17 | [Adapter contract](../../adapter-contract.md) |
| Demo harness / installer stages | extend | Additive chapter (D90 pattern) | 2026-10-17 | [Verification](../../verification.md) |
| Expense / publishing families | watch | Cross-family business-key stability reference for the new policy author | 2026-10-17 | [Interventions](../../interventions.md) |

## Open Questions

| id | question | status | resolution |
|---|---|---|---|
| Q1 | Which third business domain (candidate: vendor payment) best stresses the untested parts of the admission ladder? | resolved | 2026-10-17 design recon: **support ticket family (客户工单)** — severity/category/SLA admission with unknown-blocking, ticket-reference business key, GitHub-issue-shaped fake-adapter receipts preparing E16 reuse; vendor payment rejected (amount-shaped like expense, payment-system counterpart mismatches D96) — [recon](../../../.agents/notes/2026-10-17-s15-design-recon.md) |
| Q2 | Does the freeze claim need a crash-recovery chapter in the family demo, or is forward-path coverage sufficient? | resolved | 2026-10-17 design recon: crash-recovery chapter included — the freeze must cover the result-unknown dispatch machinery, not only admission; the local fake adapter suffices (external realness is E16's job) — [recon](../../../.agents/notes/2026-10-17-s15-design-recon.md) |
| Q3 | When does entry-point consolidation ship (single product entry plus a proof-catalog index of demos)? | open | Follow-up scheduling decision after E15 |
| Q4 | Which external system becomes the first real write path behind the credential-holding adapter host (advice step 2)? | resolved | 2026-10-17 owner decision, recorded as [E16/D96](2026-10-17-adapter-host-real-external-write-path.md): GitHub REST API; runner-ups self-hosted PostgreSQL (best inspectability, needs an optional client dependency) and Stripe test mode (payout narrative, account + network dependency) documented there |

## Cross-cutting

| concern | owning epic | note |
|---|---|---|
| Business compensation | E10/E14 | The third family adds no compensation; active-window semantics unchanged (D94). |
| Rule-card two-track (governed cards vs Python policies) | E12/E13 + follow-up | Closed only by the advice step-3 binding experiment or its recorded failure; no new card publication states before it. |
| Adapter host / real external write path | E16 | Advice step 2; Q4 resolved 2026-10-17 → GitHub REST API ([E16/D96](2026-10-17-adapter-host-real-external-write-path.md)). |
