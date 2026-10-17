# S15 design recon — third-family command-surface freeze

Date: 2026-10-17. Master-side design recon for [E15](../../docs/superpowers/roadmaps/2026-10-17-third-family-command-surface-freeze.md) before S15 materialization. Scope: resolve E15 open questions Q1/Q2 and pin the slice the worker receives.

## Q1 — third business domain: customer support ticket (客户工单)

Selected: **support ticket family**. Runner-ups considered: vendor payment (rhymes with expense amount rules; external counterpart is a payment system, mismatching D96/E16), purchase request (same issue).

Rationale:

- Fresh policy shape: severity/category/SLA admission instead of expense amount limits — stresses the admission ladder where it has not been stressed by two amount-shaped or content-shaped families.
- Natural unknown-blocking rule: an unresolved severity or category blocks acceptance (an unknown can never pass as within-policy), directly exercising the unknown-applicability machinery the freeze must prove.
- Distinct business-key shape: the business key is the external ticket reference, not a document digest.
- E16 reuse (D97): the fake adapter's receipt semantics are GitHub-issue-shaped (issue id, per-ticket reference carried in the written object, by-reference lookup), so the S16 real adapter targets the same family instead of adding an eighth local demo.

## Q2 — demo chapters: forward + crash recovery

Selected: the family demo includes **both** a forward chapter and a crash-recovery chapter (process death after the adapter has accepted the write; restart reconciles by business key and recovers the original receipt without re-sending).

Rationale: the freeze claim must cover the result-unknown dispatch machinery, not only admission. Crash semantics are runtime semantics — the local fake adapter suffices here; external realness is E16's job, not S15's.

## Pins and scope guard

- Byte pins: `work_runtime/runtime.py` and `work_runtime/adapters.py` hash-pinned byte-unchanged (D82 pattern with the escalation rule: any required lifecycle edit stops and asks the master; the edit request itself is recorded as a freeze-gap finding, never silently absorbed).
- New code only: family policy, fake adapter, conformance-mixin tests, demo chapters, installer module/console stage (D90 additive pattern), truth docs same-commit.
- Explicitly out of scope: compensation for the new family (D94), any rule-card changes or publication states (advice step 3 comes later), entry-point consolidation (E15 Q3 open), runtime phase-function refactor (advice mentions it; not needed to prove the freeze — a zero-edit family is the stronger result).

## Worker slice summary

TDD throughout (meaningful failing test first, RED evidence, minimal implementation, GREEN). Deliver: support-ticket policy with an unknown-blocking rule; GitHub-issue-shaped fake adapter passing the public conformance mixin; forward + crash-recovery demo chapters; installer stage update with exact counts and explained skip deltas; docs same-commit. Five gates, full suite, demo set, rehearsals, serial installed verification.
