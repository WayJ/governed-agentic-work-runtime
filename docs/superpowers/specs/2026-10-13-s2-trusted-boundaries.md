# S2 design — signed evidence and a second domain

Date: 2026-10-13. Master implementation choices under the user-authorized autonomous workflow. This is the implementation spec for E2/S2, not a production security claim.

## Intent

A contributor should be able to add an adapter and a business policy without cloning the lifecycle engine. A forged external approval must be rejected before it reaches the trusted local command API. Demonstrate both with expense and content publication, shared Runtime implementation, reusable conformance tests and a no-credentials CLI harness.

## Scope and constraints

Python >=3.9, zero runtime dependencies, unittest. Preserve all 63 S1 tests and existing expense CLI/API behavior. No remote HTTP server, model SDK, tenant authorization, distributed workers, policy migration or real enterprise platform in S2. One policy per runtime database remains an explicit prototype constraint; two domains use separate databases and the same Runtime class. HMAC proves source authenticity and content integrity within a configured shared-key trust boundary; it does not prove business truth or provide transport confidentiality/key rotation. Direct Runtime methods remain trusted-local APIs.

## Foundation A — adapter contract and policy-owned receipts

Create `work_runtime/adapter_contract.py`:
- Frozen `AdapterContract` dataclass fields: `actions: Tuple[str, ...]`, `idempotency_scope: str`, `retention: str`, `lookup_consistency: str`, `uniqueness: Tuple[str, ...]`. Descriptions are adapter assertions, not remotely verified guarantees.
- `receipt_is_valid(result: object, expected_digest: str) -> bool`: preserve current Runtime receipt validation (dict; matching digest; status accepted/rejected; nonempty string external_id). Extra receipt fields remain allowed.
- FakeOA exposes `contract` with expense.submit, adapter-store key scope, lifetime-of-store retention, authoritative-by-key lookup, invoice.id uniqueness.
- Adapter metadata is optional for legacy trusted duck-typed adapters. If a declared contract excludes the proposed capability, dispatch holds the prepared operation with `ADAPTER_ACTION_UNSUPPORTED` before an attempt or external call. A compatible adapter can later dispatch that same held operation. Metadata does not authenticate an adapter.
- Runtime uses receipt_is_valid and policy.evidence_sources['accepted'] for accepted receipt evidence, replacing hard-coded oa. Require a nonempty configured accepted source for effect-using policies; fail closed on invalid configuration before accepting results. ExpensePolicy retains oa, all S1 behavior remains.
- `tests/adapter_conformance.py`: reusable unittest mixin `AdapterConformanceMixin` with fixture hooks `make_adapter()`, `sample_document()`, `changed_document()`, `effect_count(adapter)`. Tests: declared actions; same-key same-payload replay returns identical receipt and exactly one effect; same key/different content raises ValueError without another effect; lookup(existing key) matches the committed receipt; lookup(missing key) returns None. Run only on explicit disposable fixtures. Individual domain uniqueness is tested separately.
- `tests/test_adapter_contract.py` adopts the mixin for FakeOA and tests receipt validation (non-dict/missing/wrong fields and digest), unsupported-action dispatch has zero attempts/effects, and policy-owned source adoption. Runtime/adapters edits owe docs/runtime-boundaries.md in the SAME commit.

## Foundation B — signed evidence ingress

Create `work_runtime/ingress.py`:
- `sign_evidence(secret: bytes, message: dict) -> dict`: returns a copy with signature, never mutates input. Message exact fields source, command_id, work_id, event_id, kind, data, issued_at; signature is lowercase HMAC-SHA256 hex of canonical(message) UTF-8. Keys are configured bytes >=32 bytes; require an integer timestamp, not bool, dict data and nonempty identity strings. No source/actor alias field.
- `SignedEvidenceGateway(runtime, keys: Dict[str, bytes], max_age: int = 300, clock: Callable = time.time)` exposes `record(envelope: dict) -> dict`. Check exact shape/types, known configured source, valid signature with compare_digest, and abs(now-issued_at) <= max_age. Reject invalid candidates before invoking runtime.command. Error receipts are decision=rejected with code EVIDENCE_ENVELOPE_INVALID, EVIDENCE_AUTHENTICATION_FAILED or EVIDENCE_EXPIRED; no secret/signature/candidate body in rejection details or persistence.
- On success call runtime.command(actor=authenticated configured source, command_id=message.command_id, work_id=message.work_id, kind='record_evidence', payload={event_id, kind, data}, expected_version=None). The signature/timestamp are authentication envelope only, never persisted in business payload. Runtime still checks source authorization and returns pending_verification; verification and evaluation remain separate.
- A valid replay within freshness returns the existing receipt; source event dedup preserves identity even if signer refreshes timestamp under a NEW command ID. Different event content under same source/event ID remains SOURCE_EVENT_CONFLICT. Unknown source, another source's key, tampered signed fields, stale/future timestamps, malformed types and extra actor fields fail before intake. Invalid source keys/configuration fail clearly; no default global secret.
- `tests/test_ingress.py` verifies signed success remains pending until verify_pending, all signed field tampering, cross-source impersonation, freshness edge boundaries, duplicates/conflicts, source grant refusal, and rejected input leaves command/evidence/event tables unchanged. Test real Runtime, not only a mock. Document in docs/signed-evidence.md including limitations and explicit key-handling guidance without publishing secrets.

## Domain and harness — content publication

After both foundations are merged into the S2 carrier, create `work_runtime/publishing.py`:
- `PublishingPolicy`: id content-publish, version demo-1, goal content.published. Documents exact id/title/body/requires_review; nonempty strings, requires_review bool or None. Sources: approval reviewer, confirmation author, accepted publisher. Capability content.publish.
- Rules C01 valid complete artifact; C02 review applicable when true, not_applicable when false, unknown when None; C03 author confirmation bound to current digest; C04 publication receipt bound to current digest and publisher source. Approval is also digest-bound. Unsupported capability blocks. Business operation key = digest([policy.id, capability, document.id, document_digest]). Replanning cannot delete these policy requirements; edited content invalidates old approval/confirmation. validate_evidence preserves source-specific shapes, no expense assumptions.
- `FakePublisher(path, timeout_after_commit=False)` implements execute(key, document, content_digest), lookup(key), published_count() and contract. Separate SQLite store: exact-key replay; changed-content same key raises; uniqueness on (document.id, content_digest) gives one published artifact even under another external key; compatible receipt shape status/external_id/digest; different content creates a new publication version. Timeout-after-commit models ambiguous success and can be reconciled by key.
- Adopt AdapterConformanceMixin in tests/test_publishing.py, plus domain rules, evidence invalidation, source identity, duplicates/uniqueness, malformed results, and result-unknown recovery tests. Assert genuine adapter interactions/effect count, one isolated fixture per malformed variant (S1 lesson).
- `work_runtime/publishing_demo.py` is an inspectable deterministic harness: create/bind/plan, show missing reviewer approval blocks, show tampered HMAC approval is rejected with zero intake, submit valid signed reviewer and author evidence through gateway, verify candidates, propose publish, simulate timeout after external commit, recreate Runtime, reconcile same operation, request_completion, assert one publication. Fresh temp directory every run; no printed secrets. Success text includes `published artifacts: 1`.
- Add CLI `python3 -m work_runtime publish-demo` and optional --directory, retain existing demo/inspect/worker unchanged. This harness is an integration example through the same command protocol, not a claim of integration with a model framework.
- Update both READMEs, CONTRIBUTING, docs/verification.md and docs/roadmap.md to describe actual S2 coverage and scope. Expense sources remain local unless caller opts into gateway. Extend scripts/verify_install.py to run installed publishing demo outside checkout and independently inspect publisher SQLite count; add meaningful failure checks before changing the script. CI runs publish-demo in addition to expense demo. New tests named in docs.

## Ownership and execution order

1. Adapter worker: adapter_contract.py, runtime.py, adapters.py, tests/adapter_conformance.py, tests/test_adapter_contract.py, docs/adapter-contract.md, docs/runtime-boundaries.md, its own plan/report. No ingress/publishing/README edits.
2. Ingress worker: ingress.py, tests/test_ingress.py, docs/signed-evidence.md, its own plan/report. No Runtime changes; uses existing command protocol.
3. Integration session merges these disjoint foundations into the carrier and verifies baseline + new tests. Master then creates publishing worker from that updated carrier.
4. Publishing worker: publishing.py, publishing_demo.py, cli.py, tests/test_publishing.py, READMEs, CONTRIBUTING, docs/verification.md, docs/roadmap.md, scripts/verify_install.py, CI, its own plan/report. No foundation edits; ask master if an interface needs adjustment.
5. Independent integration session reviews and assembles the publication branch, runs supervibe accept/merge S2, merges main, pushes (use known working SSH transport if HTTPS workflow scope rejects), verifies origin SHA and actual CI. Main and all branch merges are owned by integration sessions; master only authors roadmap/design and supervises.

No unapproved nested subagents or worker fan-out. Read coordinator mail before a new file, after tests and before worker_done. TDD behavior changes with actual RED/GREEN; bounded recon, concise scoped plans, no placeholder features. Existing inherited assets are verified rather than rewritten.
