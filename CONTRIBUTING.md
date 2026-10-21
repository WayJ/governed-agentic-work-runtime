# Contributing

The most useful contribution is a small, reproducible example that improves a business execution guarantee or makes the runtime easier to understand.

## Local setup

Python 3.9 or newer is sufficient. No service or API key is required.

```bash
python3 -m work_runtime demo
python3 -m work_runtime publish-demo
python3 -m work_runtime intervention-demo
python3 -m work_runtime adoption-demo
python3 -m work_runtime lint-sop work_runtime/data/sop/publishing.json
python3 -m unittest discover -s tests -v
python3 scripts/check_docs.py
```

The package has zero runtime dependencies. Optional development installation: `python3 -m pip install -e .`. To verify the packaged result the way CI does, run `python3 scripts/verify_install.py` (installs into a fresh virtual environment and runs all four demos through the module entry point outside the checkout — `demo`, `intervention-demo` and `adoption-demo` additionally through the `work-runtime` console entry point; there is no console `publish-demo` stage — counting every external effect against its own database and independently parsing the committed file artifact; it also requires the packaged SOP cards and GUI web assets to ship inside the install, and drives the installed `ui-demo`/`ui` entry points over real HTTP only when the read-only backend module is part of the install — otherwise that stage prints an explicit SKIPPED line and the final summary discloses it; needs pip index access for the build backend).

## Project structure

| Path | Responsibility |
|---|---|
| `work_runtime/runtime.py` | Transaction boundaries, commands, operation and evidence lifecycles |
| `work_runtime/policy.py` | Policy interface and the demo expense rules |
| `work_runtime/adapter_contract.py` | Declared adapter contracts and receipt validation |
| `work_runtime/adapters.py` | Separate persistent fake OA |
| `work_runtime/ingress.py` | HMAC-signed evidence envelopes and the authenticated ingress gateway |
| `work_runtime/publishing.py` | Content publication policy and the separate persistent fake publisher |
| `work_runtime/authoring.py` | Static SOP rule-card linting and canonical content digests |
| `work_runtime/file_adapter.py` | Real-filesystem `FilePublisher` adapter (one immutable JSON artifact per key) |
| `work_runtime/adoption_demo.py` | Strict SOP file loader, packaged-card access and the adoption demonstration |
| `work_runtime/workflow_spec.py` | Workflow definition lint, canonical digest, three-valued predicates, closed shape descriptors, validator registry |
| `work_runtime/workflow.py` | The mixed-node engine: published templates, named objects, node instances, routing, agent results, human decisions, automatic actions, durable intents, recovery |
| `work_runtime/workflow_server.py` | The generic `/v1/workflows` HTTP bridge, the single-coordinator lock and the periodic advance/recover ticker |
| `work_runtime/workflow_demo.py` | The ten-node demonstration family and its crash/restart harness |
| `work_runtime/data/sop/` | Packaged single-source example rule cards (shipped as package data) |
| `work_runtime/demo.py` | Deterministic proposer and real worker crash demonstration |
| `work_runtime/publishing_demo.py` | Signed-evidence publication demonstration |
| `work_runtime/intervention_demo.py` | Ownership-transfer, cancellation and policy-migration demonstration |
| `work_runtime/ui_demo.py` | Five-work real-command sample seed and the lazy `ui`/`ui-demo` serve loop |
| `work_runtime/web/` | Offline bilingual GUI assets (HTML/CSS/JS, shipped as package data) |
| `tests/test_runtime.py` | Invariants, failure injection and subprocess recovery |
| `tests/adapter_conformance.py` | Reusable adapter conformance mixin over disposable fixtures |
| `tests/test_authoring.py` | Rule-card lint and digest tests (14 diagnostic codes, graph boundary) |
| `tests/test_file_adapter.py` | File adapter conformance, corruption, races and process-death tests |
| `tests/test_adoption_demo.py` | lint-sop CLI/loader tests and the adoption demo harness tests |
| `tests/test_publishing.py` | Publication policy, adapter, runtime flow, demo and CLI tests |
| `tests/test_intervention_demo.py` | Intervention demo harness, `inspect --policy-versions` and CLI tests |
| `tests/test_ui_demo.py` | Sample-seed shape/realism/hygiene tests over stored SQLite truth |
| `tests/test_ui_cli.py` | `ui`/`ui-demo` CLI lazy-import, startup-error and serve-lifecycle tests |
| `scripts/check_docs.py` | Local Markdown link checker — the documentation contracts gate; ignores fenced examples, inline code, reference definitions inside fences and external URLs |
| `scripts/verify_install.py` | Fresh-venv install and outside-checkout demo verification |
| `tests/test_docs.py` | Link checker behavior and repository documentation contracts |
| `docs/RFC-*.md` | Candidate semantics and protocol |
| `docs/adapter-contract.md` | Adapter contract boundary and conformance-test adoption |
| `docs/signed-evidence.md` | Signed-evidence trust model, envelope semantics and key handling |
| `docs/contributor-guide.md` | Step-by-step adapter and SOP authoring tutorial (public interfaces only) |
| `docs/sop-authoring.md` | Rule-card schema, diagnostic codes and digest semantics |
| `docs/file-adapter.md` | File adapter contract, artifact shape and platform boundaries |
| `docs/gui.md` | Local read-only GUI guide: commands, fixture, tile definitions, limits |
| `docs/verification.md` | Honest protocol coverage matrix and deferred scope |

## Propose a change

For a bug, include the command or minimal code, expected behavior, observed behavior, Python version, and a redacted event history if relevant. Do not include real invoices, credentials or personal data.

For a new feature, describe the business case and the guarantee it needs. Changes to command semantics should update the RFC and coverage report together with a behavior test. Changes to external-effect recovery should check the external objects, not only the returned status.

Keep pull requests focused. Describe the observable behavior and validation, and run the local checks (`python3 -m unittest discover -s tests -v` and `python3 scripts/check_docs.py`) before submitting — documentation links must resolve. Avoid adding model, cloud or framework dependencies to the core; adapters can carry their own dependencies when needed.

## Current contribution opportunities

- Source-specific evidence verifiers beyond the demo shape checks.
- A real external adapter integration that runs the reusable conformance tests (the included `FilePublisher` covers the local-filesystem shape; network services remain uncollected).
- Compensation (effect reversal) execution and evidence revocation on top of recorded cancellations.
- A third small business domain to keep challenging the policy abstraction.
- Improvements to the demos, documentation and failure explanations.

Adding an adapter or authoring an SOP rule card: follow the [contributor guide](docs/contributor-guide.md) — declare an `AdapterContract` (see [docs/adapter-contract.md](docs/adapter-contract.md)), pass the reusable conformance mixin with disposable fixtures, and test the domain's own uniqueness rules separately; lint rule cards with `lint-sop` and review against the packaged examples. Adding a domain: write a `Policy` with its own evidence sources and run it in its own database — one policy per database is a prototype constraint.

Discuss distributed execution semantics before introducing workers or leases. The current single-coordinator tests cannot prove distributed guarantees.

Please keep discussion respectful and concrete. Challenge assumptions and implementations with examples, and help maintainers reproduce the issue.
