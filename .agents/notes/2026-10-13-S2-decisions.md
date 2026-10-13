# S2 builder decisions — 2026-10-13

## Background

Claude Code builder check completed in report commit8fc97fc before product implementation. [Effective design](../../docs/superpowers/specs/2026-10-13-s2-trusted-boundaries.md) addendum D8 resolves gaps.

## Decisions

Ratify B1 explicit error codes/canonical JSON rejection, B2 dispatch/reconcile/resolve-local CommandError source checks, B3 metadata vs behavioral conformance split. Reject signed accepted-kind ingress after authentication/freshness (separate EVIDENCE_KIND_UNSUPPORTED), forbid source key reuse. Keep Runtime business rejection receipts distinct from pre-intake authentication failure. Existing local trusted APIs remain explicit.

## Lessons

Shared-key authenticity alone would allow key holders to fabricate completion evidence; reserve result ingress until operation-bound verification is designed. A receipt-source test with unchanged oa source would pass against old code: use a different configured source to obtain meaningful RED. Reviewer read only relevant surfaces and verified baseline63 tests/doc links.

## Handover

Developer checkouts forked at7dd96a3; authoritative amended design lives in carrier and all dispatch briefs reference it. Integration must preserve master D8 changes, merge design-review report8fc97fc into carrier, and collect scoped developer RED/GREEN before branching publication.

## D10 acceptance sequencing amendment — 2026-10-13

The initial S2 final DoD line bundled actual merge/push into pre-merge acceptance, creating the same circular ordering already resolved in S1. Amend E2 then re-copy the amended clause verbatim into S2: acceptance proves the integration runbook and review; final release still requires actual merge, non-force push and remote equality. No product criterion or publication requirement removed. Independent final integration reads the current carrier artifacts; publication worker's feature interfaces are unchanged.
