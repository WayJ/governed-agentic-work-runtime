# Live-dispatch lease: reconcile must not isolate a call this instance is making

R04 platform.artifact.publish incident (op 8a718c0…/platform.artifact.publish,
`outcome_unknown`/`in_flight`, `same_key_retries=1`, zero executes, one lookup)
was reproduced deterministically before any fix: with a barrier placed after
the `dispatched`/`in_flight` commit and before `adapter.execute` (wrapped
`_transaction`, post-`__exit__`), a `reconcile` on another thread of the same
`Runtime` saw the committed row, looked it up, got `None` and re-armed the
single same-key retry; the adapter's dispatched guard then refused the still-
live call (`http_executes=0`). With the budget already spent the same window
ends in `outcome_unknown`/`in_flight`/`retries=1` — the incident's shape.

Fix (minimal, in this repo only):

- `Runtime.__init__`: `self._live_dispatches` + `threading.Lock` guard
  (in-memory, per instance; never persisted, never cross-instance).
- `dispatch`: `_live_dispatch_begin` inside the commit transaction, before
  the row becomes visible; released in a `finally` **only after** `_resolve`
  or `_unknown` persisted the outcome (also covers a raising `fault()`).
- `reconcile`: a leased operation returns as-is — no lookup, no quarantine,
  no retry arm. A fresh instance (restart, or a second instance on the same
  file, including in-process) has no lease and isolates exactly as before.

Untouched by design: the dispatched execution guard, CAS/authority/quality
gates, the one-retry budget, and every persisted shape. Pins updated
consciously per their own instruction: `test_compensation.PreservationPins`
import allowlist (+ stdlib `threading`) and the
`test_publishing_compensation.BoundaryPins` digest for `runtime.py`.
Docs: `docs/runtime-boundaries.md` (trust model, dispatch boundary, recovery
contract). Regression: `tests/test_dispatch_lease.py` — cross-thread barrier
(no isolation, exactly one execute, no retry write), other-instance
strictness (budget consumed there), exception path keeps one retry.

Known residual (unchanged, stated not hidden): the lease protects only calls
of the same instance; a second dispatcher process on one store remains the
P13 deferred limitation, and the CoordinatorLock/file-lock discipline around
it is unchanged.
