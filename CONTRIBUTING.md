# Contributing

The most useful contribution is a small, reproducible example that improves a business execution guarantee or makes the runtime easier to understand.

## Local setup

Python 3.9 or newer is sufficient. No service or API key is required.

```bash
python3 -m work_runtime demo
python3 -m unittest discover -s tests -v
python3 scripts/check_docs.py
```

The package has zero runtime dependencies. Optional development installation: `python3 -m pip install -e .`. To verify the packaged result the way CI does, run `python3 scripts/verify_install.py` (installs into a fresh virtual environment and runs both entry points outside the checkout; needs pip index access for the build backend).

## Project structure

| Path | Responsibility |
|---|---|
| `work_runtime/runtime.py` | Transaction boundaries, commands, operation and evidence lifecycles |
| `work_runtime/policy.py` | Policy interface and the demo expense rules |
| `work_runtime/adapters.py` | Separate persistent fake OA |
| `work_runtime/demo.py` | Deterministic proposer and real worker crash demonstration |
| `tests/test_runtime.py` | Invariants, failure injection and subprocess recovery |
| `scripts/check_docs.py` | Local Markdown link checker — the documentation contracts gate |
| `scripts/verify_install.py` | Fresh-venv install and outside-checkout demo verification |
| `tests/test_docs.py` | Link checker behavior and repository documentation contracts |
| `docs/RFC-*.md` | Candidate semantics and protocol |
| `docs/verification.md` | Honest protocol coverage matrix and deferred scope |

## Propose a change

For a bug, include the command or minimal code, expected behavior, observed behavior, Python version, and a redacted event history if relevant. Do not include real invoices, credentials or personal data.

For a new feature, describe the business case and the guarantee it needs. Changes to command semantics should update the RFC and coverage report together with a behavior test. Changes to external-effect recovery should check the external objects, not only the returned status.

Keep pull requests focused. Describe the observable behavior and validation, and run the local checks (`python3 -m unittest discover -s tests -v` and `python3 scripts/check_docs.py`) before submitting — documentation links must resolve. Avoid adding model, cloud or framework dependencies to the core; adapters can carry their own dependencies when needed.

## Current contribution opportunities

- Authenticated evidence intake and source-specific verification interfaces.
- External adapter capability declarations and conformance tests.
- Cancellation and compensation with unknown in-flight effects.
- A second small business example to challenge the policy abstraction.
- Improvements to the demo, documentation and failure explanations.

Discuss distributed execution semantics before introducing workers or leases. The current single-coordinator tests cannot prove distributed guarantees.

Please keep discussion respectful and concrete. Challenge assumptions and implementations with examples, and help maintainers reproduce the issue.
