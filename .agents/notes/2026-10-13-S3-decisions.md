# S3 design decisions — 2026-10-13

## Background

Independent builder report c84ac61 (s3-release-control) confirms feasibility with two ratifications. Scope checked on 172 green tests and both existing domains. Report will be merged by integration; root owns strategic docs only.

## Decisions

D15 in E3/design ratifies B1 request_cancel unsupported-probe collision (one kind-name replacement, unchanged assertion/count) and B2 pre-replay current authority denial without modifying stored receipt. Accept explicit keyword-only same-family registry, eight new codes, actual contract revisions and no implicit version migration. All-kind provenance required both migration and pending verification. Reject new waits during cancellation. Demo v2 strengthens approval and binds it to policy_version demo-2; opt-in inspect registry supports both loaded versions. Details are authoritative in [design](../../docs/superpowers/specs/2026-10-13-s3-intervention-design.md).

## Lessons

Bounded builder review surfaced an actual inherited-test collision before product code. Use scoped exception with preserved test intent rather than promising incompatible expectations. Lifecycle policy resolution must cover query recovery and accepted-source adoption, not only migration command.

## Handover

Core owner receives D15 in complete task brief; integration merges report plus corrected core tip into current carrier. Demo owner consumes settled registry/v2/command APIs after foundation review. No compensation/revocation scope added.

## D16 review addendum

Core b6adae8 passed244 but explicit empty policies mapping skipped default structural validation. Actual root probe created DB with noncallable default operation_key. Original owner receives scoped TDD correction; independent integration holds merge. Additive mapping omission clarified after code with retrospective discipline note in design; default object explicitly passed, no implicit upgrade.
