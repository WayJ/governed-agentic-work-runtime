# Roadmap

Status: proposed milestones, not delivery commitments. The aim is a useful open-source execution foundation with a clear promise: agent-proposed business actions remain accountable across changing plans and failed sessions.

## 0.1 — An inspectable reference implementation

- Clone and run a meaningful demonstration without credentials or services.
- Persist command decisions, evidence, waits and logical operations.
- Show real process death after external acceptance and recover the original receipt.
- Publish actual verification coverage, including deferred guarantees.
- Provide English and Chinese entry points, contribution guidance and CI.

The initial implementation provides this local slice. Publication and CI results still require the repository to be pushed and the workflow to run.

## 0.2 — Trustworthy integration boundaries

- Define verified source identities independently of caller-supplied actor names.
- Describe adapter capabilities: supported actions, idempotency scope and retention, lookup consistency, uniqueness and result verification.
- Provide adapter conformance tests with duplicate, ambiguous and mismatched results.
- Demonstrate a second business domain and one harness integration through the same command protocol.
- A new contributor can implement an adapter using documentation without modifying lifecycle internals.

The S2 wave provides this as a local, test-gated slice: HMAC-signed evidence intake with per-source keys ([signed evidence](signed-evidence.md)), declared adapter contracts with a reusable conformance mixin ([adapter contract](adapter-contract.md)), and the content-publication domain with its no-credentials harness (`python3 -m work_runtime publish-demo`). The S4 wave adds the adapter-authoring half of the last bullet: a real third adapter (`FilePublisher`, [file adapter](file-adapter.md)) passed through the same public conformance tests without lifecycle edits, a [contributor guide](contributor-guide.md) with worked adapter and rule-card tutorials, and an inspectable adoption harness (`python3 -m work_runtime adoption-demo`). A guide-only AI-agent rehearsal exercises the guide without reading internals and is reported separately; it is an agent rehearsal, not collected external human feedback. "Trustworthy" still owes external review, real adapter experience beyond the local filesystem, and key-rotation/revocation semantics — none of which a local prototype can claim.

## 0.3 — Change and intervention

- Implement cancellation, authority-aware responsibility transfer and compensation.
- Preserve and reconcile all in-flight effects before declaring cancellation complete.
- Implement evidence revocation and explicit policy migration.
- Explain every blocker with its rule, object scope and permitted recovery path.
- Publish failure scenarios showing both automatic recovery and required human intervention.

The S3 wave provides part of this as a local, test-gated slice: cancellation that acknowledges external effects exactly (never reversing them), authority-aware ownership transfer with replay protection, and explicit same-family policy migration with per-work pinned versions ([interventions](interventions.md), [verification](verification.md)). Compensation execution, evidence revocation and distributed fencing remain open, and every intervention here is a trusted-local decision — not an authenticated multi-tenant one.

## 0.4 — Authoring and execution at scale

- Use real author feedback to validate the rule-card model and publication process. The S4 slice delivers static rule-card linting with exact content digests and packaged examples ([SOP authoring](sop-authoring.md)); the publication process itself — authority approvals, an immutable publication store — is not implemented, and external author feedback remains uncollected (the recorded guide-only exercise is an agent rehearsal).
- Measure concurrent-work needs before choosing distributed storage and scheduling.
- Add worker leases and fencing only with external-system enforcement and dedicated race tests.
- Provide an inspectable timeline and operational metrics grounded in business events.

## How we judge progress

Stars describe reach. The engineering milestones use reproducible behavior: time to first demo, successful independent integrations, recovery correctness, comprehensible rejection reasons, and contributor ability to fix a failure.

Before expanding integrations, keep the core promise small enough to explain and verify. A missing guarantee should appear in the coverage report rather than becoming an undocumented assumption.
