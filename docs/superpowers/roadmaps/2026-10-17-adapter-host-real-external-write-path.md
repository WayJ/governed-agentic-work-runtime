---
epic: E16
status: open
date: 2026-10-17
---

# Credential-holding adapter host: one real external write path (GitHub)

## Deliverables

| deliverable | note |
|---|---|
| Adapter host (in-process) | Holds external credentials; external execution and query accept only prepared operations from the governed flow; the runtime stays a single-process library. |
| GitHub adapter | First real external adapter over the GitHub REST API (stdlib-only client), declared per the public adapter contract. |
| Real crash/cancel proof | Credential-gated demonstration against the real system: death after external acceptance reconciled by business key; a real cancellation-window case. |

## Definition of Done

- [ ] A credential-holding adapter host exists in-process: external credentials enter only through host configuration — never agent payloads, rule cards, or persisted runtime records — and execution/query paths accept only prepared operations; the runtime remains a library with lifecycle semantics unchanged except disclosed, master-ratified additions.
- [ ] The GitHub adapter implements the public adapter contract with stdlib-only client code (urllib/json; no new runtime dependencies): declared actions, idempotency scope (business key carried in the written object; by-id lookup), honestly-declared lookup consistency (GitHub search is eventual; reconcile strategy documented), retention, and result verification; conformance tests pass against the real API under credentials and disclose-skip with exact counts without.
- [ ] Real crash recovery is demonstrated against the real system: the process dies after GitHub has accepted the write and before the receipt lands; restart reconciles by business key and recovers the original receipt without re-sending; a real cancellation-window case runs end-to-end; evidence is recorded receipts, not screenshots.
- [ ] No eighth local demo: the real adapter targets the E15 third family (or an existing family if E15's proves unsuitable — disclosed decision, D97); clean-clone runs without credentials pass with the real stages disclosed-skipped and skip deltas explained.
- [ ] Boundaries stay honest: no distributed exactly-once or externally-fenced in-flight claims; the trusted-local caller boundary is unchanged; secrets are never printed or persisted.
- [ ] The five gates, full suite, demo set, rehearsals and serial installed verification pass with exact counts/skips; independent acceptance precedes the integration-owned ordinary merge and non-force push, with truth docs and the roadmap note same-commit.

## Sprint Breakdown

| sprint | state | note |
|---|---|---|
| S16 | planned | 2026-10-17 owner decision (D96): GitHub REST API is the first real external write path, resolving [E15/Q4](2026-10-17-third-family-command-surface-freeze.md). Runs after S15 per the adopted order (freeze first, then the host). Awaiting master go and design recon. |

## Decisions (ADR)

| id | decision | rationale | date | evidence |
|---|---|---|---|---|
| D96 | First real external write path = GitHub REST API behind the credential-holding adapter host; runner-ups recorded: self-hosted PostgreSQL (best inspectability, needs an optional client dependency) and Stripe test mode (payout narrative, account + network dependency) | Real third-party production API; stdlib-only client preserves zero runtime dependencies; real credentials (fine-grained PAT) exercise the host; receipts queryable by id and by business key with real eventual-consistency lookup semantics; already reachable in this toolchain and CI | 2026-10-17 | [Advice](../../ideas/2026-10-17-上一次建议.md), [E15 Q4](2026-10-17-third-family-command-surface-freeze.md) |
| D97 | The real adapter reuses the E15 third family (or an existing family); no new local demo family | The advice warns against an eighth local demo; the real path exists to test crash recovery and the cancellation window, not to add demo surface | 2026-10-17 | [Advice](../../ideas/2026-10-17-上一次建议.md) |

## Asset Disposition

| asset | disposition | note | date | evidence |
|---|---|---|---|---|
| Adapter contract (capability/lookup/idempotency declarations) | reuse | GitHub adapter declares per contract; eventual lookup consistency declared honestly | 2026-10-17 | [Adapter contract](../../adapter-contract.md) |
| Conformance mixin | reuse | Real-API conformance under credentials; disclosed skip without | 2026-10-17 | [Adapter contract](../../adapter-contract.md) |
| E15 third family | reuse | Real adapter target; no eighth demo (D97) | 2026-10-17 | [E15](2026-10-17-third-family-command-surface-freeze.md) |
| Runtime ledger store (SQLite) | watch | Stays SQLite; re-selection gated on the 0.4 concurrency measurement ([E15/D95](2026-10-17-third-family-command-surface-freeze.md)) | 2026-10-17 | [Roadmap §0.4](../../roadmap.md) |

## Open Questions

| id | question | status | resolution |
|---|---|---|---|
| Q1 | Which GitHub object is the write target (issue comment / release asset / repository dispatch) and how is the business key carried for by-key reconcile? | open | S16 design recon |
| Q2 | Scratch repository vs main repo for real writes; fine-grained PAT scope (least privilege) and CI secret gating? | open | S16 design recon |
| Q3 | Reconcile strategy under GitHub search's eventual consistency (polling window, by-id fallback) as declared in the adapter contract? | open | S16 design recon |
| Q4 | Rate-limit and secondary-rate handling: queued retry vs surfaced-blocker semantics? | open | S16 design recon |

## Cross-cutting

| concern | owning epic | note |
|---|---|---|
| Trusted-local caller ring | E2/E16 | The host owns credentials; who may call the runtime stays host-determined; no multi-tenant auth added. |
| External fencing of in-flight calls | deferred (roadmap 0.3/0.4) | Still open; the host does not claim it. |
| Storage re-selection | gated by [E15/D95](2026-10-17-third-family-command-surface-freeze.md) | Ledger stays SQLite until measured concurrency demands otherwise. |
