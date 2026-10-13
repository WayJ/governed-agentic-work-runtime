# S2 Content Publication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the dependent content-publication domain — `PublishingPolicy`, `FakePublisher` adapter, deterministic signed-evidence publishing demo, `publish-demo`/`inspect --policy` CLI, installed verification and docs — on top of the foundation-integrated S2 carrier without touching foundation code.

**Architecture:** One new domain module `work_runtime/publishing.py` (policy + adapter, mirroring `policy.py`/`adapters.py` shapes), one new harness `work_runtime/publishing_demo.py` driving the *existing* Runtime command protocol through `SignedEvidenceGateway`, small additive CLI changes, and test/doc/verifier updates. No Runtime/adapter_contract/adapters/ingress changes; `__init__.py` stays untouched (module-path imports).

**Tech Stack:** Python >= 3.9 standard library only, `unittest`, real SQLite Runtime and adapter stores in tests.

**Spec:** `docs/superpowers/specs/2026-10-13-s2-trusted-boundaries.md` ("Domain and harness — content publication" + D8 B3/M5 + D9 pins), `docs/superpowers/sprints/2026-10-13-S2-plan.md` Wave 2, `AGENTS.md`.

## Global Constraints

- Python 3.9.6 on this machine: no 3.10+ syntax; `typing` spellings as in existing code.
- Zero runtime dependencies; standard-library `unittest` only.
- Ownership (exact): `work_runtime/publishing.py`, `work_runtime/publishing_demo.py`, `work_runtime/cli.py`, `tests/test_publishing.py`, `README.md`, `README.zh-CN.md`, `CONTRIBUTING.md`, `docs/verification.md`, `docs/roadmap.md`, `scripts/verify_install.py`, `.github/workflows/ci.yml`, this plan and the report in `.agents/notes/`. **Never** edit Runtime/adapter_contract/adapters/ingress/demo, baseline tests (`test_runtime.py`, `test_boundaries.py`, `test_docs.py`), `work_runtime/__init__.py`, or sprint/epic docs. Interface defects go to the coordinator via `orca orchestration ask`.
- Baseline: 130 carrier tests green before and after; suite green except during observed RED steps.
- No merge, no push; scoped commits; no nested agents, no local approval UI; coordinator mail at checkpoints (before new files, after tests, before `worker_done`).
- Demo keys: fresh random per run (`secrets.token_bytes(32)`), never printed or persisted; fixed clock keeps runs deterministic.
- Docs must state tested scope only: HMAC authenticates evidence sources, not business truth; `accepted` kind forbidden at ingress; direct Runtime is trusted-local; one policy per database; descriptors are claims; P13 deferred; no model-framework/server integration claims.

## Pinned contract (decisions the implementer cannot choose)

- `PublishingPolicy`: `id="content-publish"`, `version="demo-1"`, `goal="content.published"`, `evidence_sources={"approval": "reviewer", "confirmation": "author", "accepted": "publisher"}`, capability `content.publish`.
- `validate_document`: exact keys `{id, title, body, requires_review}`; `id`/`title`/`body` nonempty strings; `requires_review` is `bool` or `None` (ints/strings rejected).
- `validate_evidence` (used by `verify_pending`): `approval`/`confirmation` → data exactly `{digest}` with str digest; `accepted` → data exactly `{digest, external_id}` with nonempty str `external_id` (D8 M5). Extra or missing fields → invalid.
- `evaluate` rules on the current document digest: C01 complete artifact (applicable; satisfied when title and body nonempty — enforced at intake, kept as defense in depth); C02 review — applicability `applicable`/`not_applicable`/`unknown` when `requires_review` is `True`/`False`/`None`, satisfied only by *verified* `approval` with current digest from the `reviewer` source; C03 — *verified* `confirmation` current digest from `author`; C04 — *verified* `accepted` current digest from `publisher` (source binding checked in evaluate, not only intake). Requirement ids `"C0n:"+document id`, expense-shaped fields.
- `action_blockers`: capability != `content.publish` → `CAPABILITY_UNSUPPORTED`; else requirements except C04 that are unknown/conflict or applicable-unsatisfied (C04 is proven by the external effect itself, like E08).
- `operation_key`: `digest([policy.id, capability, document.id, work["document_digest"]])` (digest-bound, not revision-bound).
- `FakePublisher(path, timeout_after_commit=False)`: declares `AdapterContract(actions=("content.publish",), idempotency_scope="adapter-store:key", retention="lifetime-of-store", lookup_consistency="authoritative-by-key", uniqueness=("document.id+content_digest",))`. Separate SQLite store with `receipts(key TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL)` and `publications(document_id TEXT, digest TEXT, external_id TEXT NOT NULL, document TEXT NOT NULL, PRIMARY KEY(document_id, digest))` (D9). `execute(key, document, content_digest)`: digest mismatch → `ValueError`; existing key+same digest → replay stored result; existing key+different digest → `ValueError` before any write; new key → reuse `publications.external_id` when `(document_id, digest)` exists else insert new `"PUB-"+uuid12`; always insert the receipt; commit; then raise `TimeoutError` if `timeout_after_commit`. `lookup(key)` → stored result or `None`. `published_count()` → `COUNT(*) FROM publications`.
- `publishing_demo.run_demo(directory=None)`: fresh `tempfile.mkdtemp(prefix="governed-publish-")`; `runtime.sqlite` + `publisher.sqlite`; grants `{"agent": {"work.manage", "content.publish"}, "reviewer": {"evidence.write"}, "author": {"evidence.write"}}`; two fresh random signing keys; gateway clock fixed at 2000000000; flow = create/bind/plan → missing review BLOCKED → tampered signed approval rejected before intake (evidence rows unchanged) → valid reviewer+author envelopes recorded, still pending until `verify_pending` → publish intent accepted → dispatch on `FakePublisher(timeout_after_commit=True)` → `outcome_unknown` with 1 committed publication → recreate Runtime → `reconcile` by lookup (no resend) → `request_completion` accepted; success line contains `published artifacts: 1`; assert `published_count() == 1`; print `inspect` command including `--policy content-publish`; return the folder. No secrets printed.
- CLI: new `publish-demo [--directory]`; `inspect` gains `--policy {expense-submit,content-publish}` default `expense-submit` (default path byte-identical to today, grants per policy); `demo`/`worker` unchanged.
- `scripts/verify_install.py`: after the existing expense module-demo stage, run `python -m work_runtime publish-demo` outside the checkout, require `published artifacts: 1` in output, locate `publisher.sqlite` from the printed inspect path, and independently `SELECT COUNT(*) FROM publications` == 1; docstring stage list updated.
- CI: add `python -m work_runtime publish-demo` after the expense demo step.

## Review Focus

1. Unknown review state (`requires_review=None`) silently passing as "no review needed" → C02 applicability `unknown` blocks propose (`APPLICABILITY_UNRESOLVED`) and completion (Task 2 policy tests, Task 4 flow test).
2. A proof from the wrong source satisfying a rule (e.g. author-signed "accepted") → evaluate checks `e["source"]` against `evidence_sources` per kind, pinned with synthetic proofs (Task 2 `PublishingEvaluateTests`).
3. Duplicate publication of identical content under a *different* idempotency key creating a second artifact → `(document_id, digest)` uniqueness reuses the external id, one row, two receipts (Task 3 `test_duplicate_content_under_another_key_reuses_external_id_and_one_artifact`).
4. Same key with changed content partially writing before raising → key/digest check precedes every INSERT; receipts/publications counts unchanged after the raise (Task 3, conformance mixin + domain test).
5. Recovery resending after timeout (double publish) → reconcile resolves by `lookup` only; attempts stay at 1, `execute` called once, `published_count()` stays 1 (Task 4 `test_timeout_after_commit_recovers_by_lookup_without_resend`).
6. Malformed adapter results quarantined without being counted as effects → per-variant isolated fixture, real `execute` asserted called, `outcome_unknown`/`ADAPTER_RESULT_INVALID`, no accepted proof (Task 4 `MalformedResultTests`).

---

### Task 1: Baseline and plan

**Files:** Create: this plan.
- [x] Record baseline: `python3 -m unittest discover -s tests` → `Ran 130 tests ... OK`; `check_docs` 27 files/84 links/0 broken; demo + compileall green (observed 2026-10-13, Python 3.9.6).
- [ ] Commit plan: `docs(plan): scoped S2 content publication plan`.

### Task 2: `PublishingPolicy` (RED → GREEN)

**Files:** Create `work_runtime/publishing.py`, `tests/test_publishing.py`.
**Interfaces:** Produces `PublishingPolicy` per Pinned contract; test helpers reused by later tasks: `article(**overrides)` document factory, `publishing_grants()`.

- [ ] **Step 1: Write failing policy tests** — `PublishingDocumentTests` (valid doc; missing/extra field; empty id/title/body; `requires_review` True/False/None valid, `1`/`"yes"` invalid), `PublishingEvidenceShapeTests` (`validate_evidence` per-kind exact shapes, nonempty external_id, extras rejected), `PublishingEvaluateTests` (C02 true→applicable pending / false→not_applicable / none→unknown; digest binding: old-digest approval leaves C02/C03 pending; C04 satisfied only by publisher-source accepted with current digest — synthetic proof lists incl. wrong-source variants; `action_blockers` unsupported capability + C04 exclusion + unknown blocking; `operation_key` digest-bound: same document id, different digest → different key, and equality with the pinned digest formula).
- [ ] **Step 2: RED** — `python3 -m unittest discover -s tests -p test_publishing.py -v` → `ModuleNotFoundError: No module named 'work_runtime.publishing'`. Record verbatim.
- [ ] **Step 3: Implement** `publishing.py` module docstring + `PublishingPolicy` only.
- [ ] **Step 4: GREEN** — same command passes; full discover → 130 + new OK; compileall clean.
- [ ] **Step 5: Commit** — `feat(publishing): PublishingPolicy document/evidence/rules for content publication`.

### Task 3: `FakePublisher` (RED → GREEN)

**Files:** Modify `work_runtime/publishing.py`, `tests/test_publishing.py`.
**Interfaces:** Produces `FakePublisher(path, timeout_after_commit=False)` with `execute`/`lookup`/`published_count`/`contract` per Pinned contract.

- [ ] **Step 1: Write failing adapter tests** — `FakePublisherConformanceTests(AdapterConformanceMixin, unittest.TestCase)` with per-test temp SQLite fixtures (`make_adapter` fresh file, `sample_document`/`changed_document` via `article(body=...)`, `effect_count=adapter.published_count`); `FakePublisherDomainTests`: digest mismatch `ValueError`; same-key different content raises with receipts/publications counts unchanged; duplicate identical content under another key reuses external id with exactly one publication and two receipts; changed content under another key adds a version (two publications); `timeout_after_commit` raises `TimeoutError` after the publication row is committed; `lookup` missing key `None`.
- [ ] **Step 2: RED** — discover on `test_publishing.py` → `ImportError: cannot import name 'FakePublisher'`. Record verbatim.
- [ ] **Step 3: Implement** `FakePublisher` in `publishing.py` (FakeOA-shaped transaction, publications table per D9).
- [ ] **Step 4: GREEN** — targeted + full suite + compileall.
- [ ] **Step 5: Commit** — `feat(publishing): FakePublisher with (document_id,digest) artifact uniqueness`.

### Task 4: Runtime flow tests (integration + fixes)

**Files:** Modify `tests/test_publishing.py` (and `publishing.py` only if a genuine defect surfaces — record RED first).
**Interfaces:** Consumes Task 2/3 outputs, real `Runtime`, `SignedEvidenceGateway`/`sign_evidence`.

- [ ] **Step 1: Write flow tests** — `PublishingFlowTests` over a real Runtime per test: missing review blocks propose; `revise_plan` cannot remove review (still blocked); `revise_document` invalidates approval+confirmation (requirements pending again, old-digest evidence rejected at re-verify, stale prepared operation cancelled); signed approval/confirmation through the gateway stay pending until `verify_pending`; full happy path (gateway evidence → verify → propose → dispatch → completion accepted, one publication); `MalformedResultTests` (six per-variant isolated fixtures with a counting wrapper over a real `FakePublisher`: returned None/str, missing/empty `external_id`, wrong digest, bad status → `outcome_unknown` + `ADAPTER_RESULT_INVALID`, work `needs_attention`, exactly one real `execute`, no accepted evidence); `test_timeout_after_commit_recovers_by_lookup_without_resend`.
- [ ] **Step 2: Observe** — run the file; any failure is a real defect → systematic fix in owned files with RED recorded; passing tests are integration characterizations of Tasks 2–3 behavior (note in report).
- [ ] **Step 3: Full suite + compileall green; Commit** — `test(publishing): runtime flow, malformed-result quarantine and timeout recovery`.

### Task 5: Publishing demo (RED → GREEN)

**Files:** Create `work_runtime/publishing_demo.py`; modify `tests/test_publishing.py`.
**Interfaces:** Produces `run_demo(directory=None) -> Path`, `publishing_grants()`, `article(...)` re-exported helpers per Pinned contract.

- [ ] **Step 1: Write failing demo tests** — `PublishingDemoTests`: captured stdout contains the six numbered story lines and `published artifacts: 1`; returned folder holds `runtime.sqlite` + `publisher.sqlite`; independent `SELECT COUNT(*) FROM publications` == 1; second run in another directory also succeeds (fresh-state determinism); no key material (`token_bytes` hex of generated keys cannot be checked — instead assert output has no 64-hex signature/secret strings beyond fixed ids).
- [ ] **Step 2: RED** — `ModuleNotFoundError: No module named 'work_runtime.publishing_demo'`. Record verbatim.
- [ ] **Step 3: Implement** `publishing_demo.py` per Pinned contract.
- [ ] **Step 4: GREEN** — targeted + full suite + compileall; manual `python3 -m work_runtime publish-demo` fails only on the missing CLI (expected until Task 6) — demo itself exercised via tests here.
- [ ] **Step 5: Commit** — `feat(publishing): deterministic signed-evidence publication demo harness`.

### Task 6: CLI (RED → GREEN)

**Files:** Modify `work_runtime/cli.py`, `tests/test_publishing.py`.
**Interfaces:** Produces `publish-demo [--directory]` and `inspect --policy {expense-submit,content-publish}` (default expense-submit).

- [ ] **Step 1: Write failing CLI tests** — subprocess-driven: `python3 -m work_runtime publish-demo --directory <tmp>` exits 0 with the success line; `inspect --db <publishing runtime.sqlite> --work <id> --policy content-publish` exits 0 and prints JSON whose work contract goal is `content.published`; default-policy inspect on an expense-demo database still works; `--policy bogus` exits 2.
- [ ] **Step 2: RED** — publish-demo exits 2 (`invalid choice`), `--policy` unrecognized. Record verbatim.
- [ ] **Step 3: Implement** cli.py additions (imports from `.publishing`/`.publishing_demo`; policy-specific grants for inspect; expense default path unchanged).
- [ ] **Step 4: GREEN** — targeted + full suite + compileall + `python3 -m work_runtime demo` still green (backwards compatibility).
- [ ] **Step 5: Commit** — `feat(cli): publish-demo command and policy-aware inspect`.

### Task 7: Installed verification + CI (RED → GREEN)

**Files:** Modify `scripts/verify_install.py`, `.github/workflows/ci.yml`.

- [ ] **Step 1: Extend `verify_install.py`** — publication stage after the expense module demo per Pinned contract; update module docstring stages.
- [ ] **Step 2: RED** — `git archive 9c493cc` into a temp dir, run `python3 scripts/verify_install.py --repo <base>` → FAILED at the publication stage (base has no `publish-demo`). Record verbatim; dispose of the temp checkout.
- [ ] **Step 3: GREEN** — `python3 scripts/verify_install.py` on this checkout → PASS with `publications = 1` line.
- [ ] **Step 4: CI** — add `python -m work_runtime publish-demo` after the demo step in `ci.yml`.
- [ ] **Step 5: Commit** — `feat(verify): installed publication demo verification and CI smoke`.

### Task 8: Documentation and gates

**Files:** Modify `README.md`, `README.zh-CN.md`, `CONTRIBUTING.md`, `docs/verification.md`, `docs/roadmap.md`.

- [ ] **Step 1: Update docs to actual scope** — READMEs: publication demo section (command + story lines), "What works today" additions (signed ingress, adapter contracts, second domain), verify commands incl. `publish-demo`, verifier description incl. publication count. CONTRIBUTING: structure table rows for S2 modules/tests/docs; refresh contribution opportunities (second-domain example now exists). `docs/verification.md`: S2 section (foundation + publication coverage with named test files; one policy per DB; HMAC ≠ business truth; descriptors are claims; P13 still deferred), updated date/how-to-verify. `docs/roadmap.md`: note under 0.2 that the local prototype now provides these items with evidence pointers. No claims beyond tested scope.
- [ ] **Step 2: Gates** — `python3 scripts/check_docs.py`; `python3 -m unittest discover -s tests -v`; `python3 -m work_runtime demo`; `python3 -m work_runtime publish-demo`; `python3 -m compileall -q work_runtime tests scripts`.
- [ ] **Step 3: Commit** — `docs(publishing): S2 publication coverage in READMEs, contributing, verification and roadmap`.

### Task 9: Report and handoff

**Files:** Create `.agents/notes/2026-10-13-S2-publishing-report.md`.
- [ ] **Step 1: Report** — verbatim RED/GREEN outputs per task, named tests, commit SHAs, commands + results for every gate (incl. verifier and both demos), ownership confirmation, remaining risks.
- [ ] **Step 2: Commit** — `docs(publishing): S2 publication developer report`.
- [ ] **Step 3:** Coordinator mail check, then one `worker_done`; idle.
