# Roadmap

Status: proposed milestones, not delivery commitments. The aim is a useful open-source execution foundation with a clear promise: agent-proposed business actions remain accountable across changing plans and failed sessions.

## 0.1 — An inspectable reference implementation

- Clone and run a meaningful demonstration without credentials or services.
- Persist command decisions, evidence, waits and logical operations.
- Show real process death after external acceptance and recover the original receipt.
- Publish actual verification coverage, including deferred guarantees.
- Provide English and Chinese entry points, contribution guidance and CI.

This reference slice has been published on GitHub. At the S6 release (`7931cc6`), [CI](https://github.com/WayJ/governed-agentic-work-runtime/actions/runs/38528039775) and [Pages deployment](https://github.com/WayJ/governed-agentic-work-runtime/actions/runs/38528125321) succeeded at the same published commit. The [developer website](https://wayj.github.io/governed-agentic-work-runtime/) provides English and Chinese entry points and real sample GUI images. This is a pre-alpha local reference implementation; publication is not production validation.

## 0.2 — Trustworthy integration boundaries

- Define verified source identities independently of caller-supplied actor names.
- Describe adapter capabilities: supported actions, idempotency scope and retention, lookup consistency, uniqueness and result verification.
- Provide adapter conformance tests with duplicate, ambiguous and mismatched results.
- Demonstrate a second business domain and one harness integration through the same command protocol.
- A new contributor can implement an adapter using documentation without modifying lifecycle internals.

The S2 wave provides this as a local, test-gated slice: HMAC-signed evidence intake with per-source keys ([signed evidence](signed-evidence.md)), declared adapter contracts with a reusable conformance mixin ([adapter contract](adapter-contract.md)), and the content-publication domain with its no-credentials harness (`python3 -m work_runtime publish-demo`). The S4 wave adds the adapter-authoring half of the last bullet: a real third adapter (`FilePublisher`, [file adapter](file-adapter.md)) passed through the same public conformance tests without lifecycle edits, a [contributor guide](contributor-guide.md) with worked adapter and rule-card tutorials, and an inspectable adoption harness (`python3 -m work_runtime adoption-demo`). A guide-only AI-agent rehearsal exercises the guide without reading internals and is reported separately; it is an agent rehearsal, not collected external human feedback. Source-key rotation shipped in S11 as configured per-source keyrings with an optional authenticated key_id selector, inclusive validity windows sharing one finite verification-time sample, and cache-first replay that returns original receipts without rewriting history ([signed evidence](signed-evidence.md), [S11 acceptance](superpowers/acceptances/2026-10-15-S11-acceptance.md)); rotating a source's signing key remains distinct from withdrawing an already-accepted proof (evidence revocation, S8). "Trustworthy" still owes external review and real adapter experience beyond the local filesystem — none of which a local prototype can claim.

## 0.3 — Change and intervention

- Implement cancellation, authority-aware responsibility transfer and compensation.
- Preserve and reconcile all in-flight effects before declaring cancellation complete.
- Implement evidence revocation and explicit policy migration.
- Explain every blocker with its rule, object scope and permitted recovery path.
- Publish failure scenarios showing both automatic recovery and required human intervention.

The S3 wave provides part of this as a local, test-gated slice: cancellation that acknowledges external effects exactly (never reversing them), authority-aware ownership transfer with replay protection, and explicit same-family policy migration with per-work pinned versions ([interventions](interventions.md), [verification](verification.md)). Evidence revocation shipped in S8 as a durable, version-bound command that withdraws a proof's current validity while preserving receipts, closure snapshots and accepted effects ([evidence revocation](evidence-revocation.md), [S8 acceptance](superpowers/acceptances/2026-10-15-S8-acceptance.md)); bounded expense compensation shipped in S10 as a linked, version-bound withdrawal executed only inside the active cancellation window — a distinct external action with its own receipts, one effect per original and an appended `withdrawn` proof, never a reversal ([interventions](interventions.md), [S10 acceptance](superpowers/acceptances/2026-10-15-S10-acceptance.md)); publishing-family retraction shipped in S14 as a linked, version-bound `content.unpublish` executed by the current owner inside the same active window — the second compensation family on the byte-unchanged S10 machinery, with a real crash-and-recovery demonstration and installed module/console proof ([interventions](interventions.md), [S14 acceptance](superpowers/acceptances/2026-10-16-S14-acceptance.md)); post-closure compensation and chains remain deferred with recorded evidence, and external fencing of in-flight calls and distributed guarantees remain open, and every intervention here is a trusted-local decision — not an authenticated multi-tenant one.

## 0.4 — Authoring and execution at scale

- Use real author feedback to validate the rule-card model and publication process. The S4 slice delivers static rule-card linting with exact content digests and packaged examples ([SOP authoring](sop-authoring.md)); governed rule-card publication shipped in S12 as a `sop.publish` work over the unchanged command protocol — version-bound signed approvals `{digest, policy_version}` through the existing evidence gateway, exactly one hash-named immutable artifact per `(policy_id, version)` under a collision-free digest key, a fail-closed loader with no card-to-policy compilation, and a no-credentials `publication-demo` with installed module/console proof ([SOP authoring](sop-authoring.md), [S12 acceptance](superpowers/acceptances/2026-10-15-S12-acceptance.md)); publication withdrawal shipped in S13 as a governed `sop.withdraw` flow committing a second immutable hash-named record per withdrawn version — the loader fails closed with a distinct withdrawn error, re-publication of a withdrawn version is refused with zero store writes, and there is no un-withdrawal (correction ships as a new version string) ([SOP authoring](sop-authoring.md), [S13 acceptance](superpowers/acceptances/2026-10-16-S13-acceptance.md)); approval-identity envelopes and quorum remain separately-designed future work, and external author feedback remains uncollected (the recorded guide-only exercise is an agent rehearsal).
- Measure concurrent-work needs before choosing distributed storage and scheduling.
- Add worker leases and fencing only with external-system enforcement and dedicated race tests.
- Provide an inspectable timeline and operational metrics grounded in business events. S5 delivers an offline, bilingual [read-only operations viewer](gui.md) over actual SQLite snapshots, evidence, command decisions, logical operations and event sequence. Counts describe persisted records, not agent-session telemetry; no lifecycle controls, tenant authentication or distributed timing guarantees are implied. S7 applied the subsequently supplied visual specification and was independently accepted and released.

## How we judge progress

Stars describe reach. The engineering milestones use reproducible behavior: time to first demo, successful independent integrations, recovery correctness, comprehensible rejection reasons, and contributor ability to fix a failure.

Before expanding integrations, keep the core promise small enough to explain and verify. A missing guarantee should appear in the coverage report rather than becoming an undocumented assumption.
