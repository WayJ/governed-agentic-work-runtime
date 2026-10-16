---
epic: E13
status: open
date: 2026-10-16
---

# Published-card withdrawal on the immutable publication store

## Deliverables

| deliverable | note |
|---|---|
| Withdrawal record surface | Second immutable hash-named artifact per withdrawn version; distinct bounded loader errors; audit read. |
| Governed withdrawal flow | `sop.withdraw` capability in the same family; signed version-bound `card_withdrawal`; cancellable refusal channel. |
| Composition and release | S8 × sop-publish composition pinned; withdrawal demo chapter + installed proof; mapped docs. |

## Definition of Done

- [ ] Withdrawing a published version commits exactly one second hash-named record artifact in the same directory under the digest-based withdrawal key; publication artifacts stay byte-identical; replay is idempotent; same-key-changed-digest is refused bounded.
- [ ] The loader fails closed with distinct bounded errors for withdrawn vs absent vs invalid record; `pinned_card` and `published_card_matches` respect withdrawal; `withdrawal_record()` exposes the audit record; no override exists.
- [ ] The governed flow (W02/W03 shape discrimination, `sop.withdraw` grants, signed `{digest, policy_version}` withdrawal approval, D66 order) runs through the real Runtime with cross-approval isolation and the completion gate for publication works unchanged; a refused withdrawal (absent target / digest mismatch) resolves `confirmed_failed` and the work stays cancellable.
- [ ] Re-publication of a withdrawn version is refused by the governed proposal's target checks with zero store writes; there is no un-withdrawal; S8 `revoke_evidence` composes on the sop-publish family with artifacts untouched, pinned by tests.
- [ ] Approver-keyring rotation interacts exactly as S11 pinned (retired/dropped codes, verbatim cached receipts, current-status resend); six-table and artifact-byte preservation hold.
- [ ] The withdrawal demo chapter proves the story with installed module+console trials outside the checkout without printing secrets; full tests, the five configured gates, the demo set, rehearsals and serial installed verification pass with exact counts/skips.
- [ ] Independent acceptance precedes integration-owned ordinary main merge/non-force push with same-commit doc pairing and honest limits (no un-withdrawal, no distributed revocation, config-rollback key revival).

## Sprint Breakdown

| sprint | state | note |
|---|---|---|
| S13 | started | 2026-10-16 strategic go: S12 merged `a02b5b8`/published `860571c` with [CI 38683808192](https://github.com/WayJ/governed-agentic-work-runtime/actions/runs/38683808192) success verified; candidate design `d331495` grounded (F1–F25, P1/P2), independent review `8eee4ad` implementable-with-amendments (RV-F1 refusal-channel stranding → rejected-receipt fix), master ratification **D67–D79** (SWD-8 amended). Materialized 2026-10-16 [S13](../sprints/2026-10-16-S13-plan.md). |

## Decisions (ADR)

| id | decision | rationale | date | evidence |
|---|---|---|---|---|
| D67 | Second immutable record artifact, same directory | Tombstones-in-place are structurally illegal (F4). | 2026-10-16 | [Design](../specs/2026-10-16-sop-publication-withdrawal-design.md) |
| D68 | Digest-based withdrawal key | Collision-free in every namespace (D56 basis). | 2026-10-16 | [Review §7](../../../.agents/notes/2026-10-16-s13-independent-design-review.md) |
| D69 | Deterministic closed record; effective immutability disclosed | RV-F2/S12 IR-F2 precedent. | 2026-10-16 | [Review §4](../../../.agents/notes/2026-10-16-s13-independent-design-review.md) |
| D70 | Same family, `sop.withdraw`, W02/W03, wrong-adapter hold pinned | Proven with zero runtime changes (R1). | 2026-10-16 | [Review §3](../../../.agents/notes/2026-10-16-s13-independent-design-review.md) |
| D71 | Signed `card_withdrawal`, no admin bypass | Q2 asymmetry verified. | 2026-10-16 | [Design §4](../specs/2026-10-16-sop-publication-withdrawal-design.md) |
| D72 | Loader: distinct withdrawn/invalid errors + audit read, no override | Fail-closed matrix extended (D62). | 2026-10-16 | [Review R1.20](../../../.agents/notes/2026-10-16-s13-independent-design-review.md) |
| D73 | Validity at the read surface only | P2′ reconcile-from-lookup structure. | 2026-10-16 | [Recon](../../../.agents/notes/2026-10-16-s13-design-recon.md) |
| D74 | Refusal via rejected receipt (`confirmed_failed`, cancellable) | Drafted ValueError strands the work (RV-F1/R2). | 2026-10-16 | [Review §4](../../../.agents/notes/2026-10-16-s13-independent-design-review.md) |
| D75 | D66 order inherited and pinned | runtime.py:668-690 verified. | 2026-10-16 | [Review §3](../../../.agents/notes/2026-10-16-s13-independent-design-review.md) |
| D76 | No un-withdrawal, no compensation semantics, no Runtime wiring, no UI | Forward-only correction. | 2026-10-16 | [Design §10](../specs/2026-10-16-sop-publication-withdrawal-design.md) |
| D77 | Demo chapter + installer stage, no new global gate | SKR-10 precedent. | 2026-10-16 | [Design §12](../specs/2026-10-16-sop-publication-withdrawal-design.md) |
| D78 | Doc set; zero new doc_sync_map rows confirmed | Existing publication.py row covers (RV-F7). | 2026-10-16 | [AGENTS](../../../AGENTS.md) |
| D79 | S8 × sop-publish composition pinned by tests | Real today, previously unpinned (P1′). | 2026-10-16 | [Review §3](../../../.agents/notes/2026-10-16-s13-independent-design-review.md) |

## Asset Disposition

| asset | disposition | note | date | evidence |
|---|---|---|---|---|
| S12 publication surface | reuse | publication.py/file_adapter.py semantics unchanged. | 2026-10-16 | [SOP authoring](../../sop-authoring.md) |
| S8 revocation model | reuse + pin | Composition pinned, no merge of models. | 2026-10-16 | [Evidence revocation](../../evidence-revocation.md) |
| FilePublisher store | reuse | Second artifact via the same commit machinery. | 2026-10-16 | [File adapter](../../file-adapter.md) |
| SignedEvidenceGateway + keyrings | reuse | S11 rotation semantics unchanged. | 2026-10-16 | [Signed evidence](../../signed-evidence.md) |

## Open Questions

| id | question | status | resolution |
|---|---|---|---|
| Q1–Q10 | Design §11 open questions | closed | Ratified defaults in the MASTER ratification section of the [design](../specs/2026-10-16-sop-publication-withdrawal-design.md), 2026-10-16. |

## Cross-cutting

| concern | owning epic | note |
|---|---|---|
| Rule-card authority | E12/E13 | Withdrawal is a governed operator act, never a store mutation. |
| Evidence revocation | E8/E13 | Distinct models, verified composition, no merge. |
