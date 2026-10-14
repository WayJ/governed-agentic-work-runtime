# S10 W1 core development — expense compensation during active cancellation — report

Worker: S10 CORE DEVELOPMENT (this checkout `s10-compensation-core`, carrier
`WayJ/sprint-s10-compensation` tip `4a15158` asserted ancestor/clean at
start; branch `WayJ/s10-compensation-core`). Date: 2026-10-15.
Scope honored: `work_runtime/runtime.py`, `work_runtime/adapters.py`,
`work_runtime/adapter_contract.py`, `work_runtime/policy.py`,
`tests/test_compensation.py` (new), additive `tests/test_adapter_contract.py`
+ `tests/adapter_conformance.py`, `docs/runtime-boundaries.md` (same commit
as every runtime/adapters change, per doc_sync_map), current
`docs/adapter-contract.md`/`docs/interventions.md`/`docs/verification.md`,
scoped plan `docs/superpowers/plans/2026-10-15-s10-core.md` and this report.
No demo/CLI/verify_install/README/UI/inspection/publishing/file_adapter/
site/AGENTS/roadmap/sprint/acceptance/debt edits; no merge, no push, no
full-S10-release claim. Compensation-demo and the installer stage are W2
(master dispatch); no fake future command was added and the five AGENTS
gates are unchanged.

Plan: `docs/superpowers/plans/2026-10-15-s10-core.md` (committed `8dab09c`
before implementation), executed with superpowers executing-plans + TDD;
ledger `.superpowers/sdd/2026-10-15-s10-core/progress.md` (workspace
deleted after the clean final review per executing-plans; the rulings and
review findings are carried in this report and in git history).

## Commits

| commit | subject |
|---|---|
| `8dab09c` | docs: scoped S10 W1 compensation core implementation plan |
| `687127d` | feat: adapter contracts declare supports_action_context opt-in (S10 D44) |
| `64504ac` | feat: expense policy pairs expense.withdraw compensation (S10 D43) |
| `aaf2e7b` | feat: FakeOA additive store migration, named writes and replay guards (S10 D46) |
| `1e66ac5` | feat: FakeOA withdrawal action with per-original effects and alias receipts (S10 D44/D46) |
| `4769574` | feat: linked compensation proposals inside the active cancellation window (S10 D43) |
| `f61abc8` | feat: compensation dispatch carve-out with full revalidation and opt-in context (S10 D44) |
| `0fd3ecb` | feat: withdrawal resolution binding, stored adapter results and withdrawn proofs (S10 D45) |
| `c3f103c` | feat: truthful compensation closure dispositions and recovery pins (S10 D45/D47) |
| `8f17ba7` | test: generic opt-in conformance coverage and S10 preservation pins (S10 D47) |
| `0275a97` | docs: state the caller-trusted reconcile boundary under the two-action adapter (S10 D44) |
| (this commit) | docs: S10 W1 core development report |

Every commit touching `runtime.py`/`adapters.py` (aaf2e7b, 1e66ac5, 4769574,
f61abc8, 0fd3ecb, c3f103c) updated `docs/runtime-boundaries.md` in the same
commit, with `adapter-contract.md`/`interventions.md`/`verification.md`
current for what each implements — no later consolidation.

## Baseline and final counts (observed)

- Baseline at `4a15158` before any change: `Ran 726 tests … OK (skipped=1)`.
- Final full battery: **`Ran 788 tests … OK (skipped=3)`** — +62 tests. The
  three skips: one pre-existing (ui-cli absent-install path) plus two new,
  disclosed below (generic mixin opt-in test skipped by `FilePublisher` and
  `FakePublisher`, which do not opt in — the designed C4 behavior).
- Five AGENTS gates: contracts `101 files, 386 links, 0 broken`; tests 788
  OK (skipped=3); `demo` OK; `compileall` clean; site `0 findings`.
- Five existing demos: `demo`, `publish-demo`, `intervention-demo`,
  `adoption-demo`, `revocation-demo` — all OK, unchanged.
- Rehearsals `examples/rehearsal`: **`Ran 15 tests … OK (skipped=1)`** — the
  14 pre-existing rehearsal tests pass unchanged; the 15th is the new
  generic opt-in conformance test, which the queue adapter (a fourth
  mixin adopter) skips because it does not opt in. No examples file was
  edited.
- `python3 scripts/verify_install.py`: **PASS** unchanged (fresh venv,
  module+console outside checkout, real effect counts, packaged web
  assets).
- Untouched-asset regression: `git diff 4a15158..HEAD` over
  `website/`, `work_runtime/web/`, `work_runtime/data/`,
  `work_runtime/inspection.py`, `work_runtime/cli.py`, `work_runtime/demo.py`,
  `work_runtime/publishing.py`, `work_runtime/file_adapter.py`,
  `work_runtime/ingress.py`, `scripts/verify_install.py`, `README.md`,
  `README.zh-CN.md`, `AGENTS.md`, `pyproject.toml`, `examples/` is **empty**
  — byte-equal, no UI/browser claim needed.
- Runtime store schema stays `1` (pinned); adapter store migration is
  explicit and additive; Python 3.9 stdlib-only (pinned import scan).

## RED → GREEN evidence (observed, per task)

| task | RED observed | GREEN |
|---|---|---|
| 1 contract field | `TypeError: __init__() got an unexpected keyword argument 'supports_action_context'` (2 tests, 6 errors) | 728 OK |
| 2 policy pairing | `AssertionError: [{'capability': 'expense.withdraw', 'code': 'CAPABILITY_UNSUPPORTED'}] != []` (both versions) | 730 OK |
| 3 migration/writes/counters | receipts columns missing (3 failures) + `TypeError: execute() got an unexpected keyword argument` / no `withdrawn_count` (2 errors) | 737 OK |
| 4 withdrawal path | `ValueError: Unknown action: expense.withdraw` (7 errors) | 745 OK |
| 5 admission | 13 failures + 1 error across the matrix (today: `CANCELLATION_ACTIVE` / lenient drop / wrong codes) | 758 OK |
| 6 dispatch | 4 failures + 1 error (compensation auto-cancelled `WORK_CANCELLED`; no kwargs; no holds) | 763 OK |
| 7 resolution | binding mismatch confirmed against wrong original (quarantine absent); no `adapter_result`; kind `accepted` flipped E08 to satisfied | 770 OK |
| 8 closure/recovery | dispositions lacked `compensates`/`adapter_result` (KeyError `adapter_result`; disposition equality) | 781 OK |
| 9 mixin/pins | new generic test; preservation pins | 788 OK (skipped=3) |

Harness-only test corrections made while observing RED (sequencing bugs in
the new tests, not product changes): confirmed submits must precede
`request_cancel` (window); uncertain same-work ops block later revisions;
secondary works need distinct document ids (business-key uniqueness); the
`worker` child cannot carry `expense.withdraw` grants, so crash tests use a
test-local child script with `compensation_grants()` (house inline-script
idiom); replay legs must reuse the stored CAS version.

## Behavior delivered (D43–D48 mapping)

- **D43 admission**: linked `propose_action` variant (exact payload →
  unpersisted `CommandError`), current owner + `expense.withdraw` grant,
  window split `CANCELLATION_ACTIVE`/`CANCELLATION_NOT_REQUESTED` covering
  fresh AND re-admission (single gate before the business-key branch),
  link validation `COMPENSATION_TARGET_INVALID` blockers `[target]`
  (exists/same-work/confirmed_succeeded/non-compensation/pairing; revoked
  original proof orthogonal), runtime key `digest([policy.id, capability,
  target_operation_id])`, immutable snapshot
  `{operation_id, external_id, capability}` on body and
  OperationPrepared/OperationReadmitted events, both policy versions.
- **D44 opt-in**: `supports_action_context` bool default False (+bool
  invariant); actions preflight then context hold
  `ADAPTER_ACTION_CONTEXT_UNSUPPORTED` before attempts/calls — even when
  `actions` declares withdraw, and for absent-contract adapters; opted-in
  adapters receive `action=capability, compensates=link_or_None`; legacy
  exactly three positional args (pinned by probe adapters; no
  introspection); FakeOA-only `action=None` normalizes submit; dispatch
  revalidates the link (belt-and-braces hold
  `COMPENSATION_TARGET_INVALID`); `STALE_INTENT` mirror for a compensation
  without intent; re-admission never rebinds the link; reconcile stays
  caller-trusted (documented).
- **D45 resolution/closure**: `original_external_id` binding check BEFORE
  the accepted/rejected split (accepted and rejected mismatch legs
  quarantined `ADAPTER_RESULT_INVALID`, idempotent); valid results add the
  full validated `op["adapter_result"]`; accepted withdrawal inserts kind
  `withdrawn` (`{digest, external_id, original_external_id}`) — never
  forward `accepted`/E08 (pinned incl. after S8 revocation of the original
  proof); no `withdrawn` source mapping: imports denied for every actor,
  admin-only revoke; S9 conflict/reservation/event semantics unchanged with
  the actual withdrawal result recorded on collision (pinned);
  `finalize_cancel` adds `compensates`/`adapter_result` only to
  compensation dispositions (ordinary three-field shape unchanged, no old
  closure rewritten); exact ack = original + succeeded withdrawal, failed
  withdrawal excluded and described ("attempted, refused, effect stands").
- **D46 adapter store**: serialized `BEGIN IMMEDIATE` migration (PRAGMA
  probe inside the transaction; concurrent first-open pinned with a
  barrier, reopen idempotent, fresh stores schema-current); named-column
  receipts writes on every path; new forward rows tagged
  `expense.submit`, legacy NULL normalized on read; BOTH actions replay
  validate digest + normalized action + link fingerprint (forward NULL),
  mismatch `ValueError` with zero writes (cross-action both directions);
  original existence = accepted FORWARD receipt external id (receipts scan,
  invoices short-circuit) including direct zero-invoice acceptances; known
  absence stores queryable rejected `ORIGINAL_ABSENT`, real store failure
  stays `outcome_unknown`; different-key/same-original inserts a
  requesting-digest/action/link alias reusing the same WD id with
  authoritative per-key lookup (lost-response leg pinned); one withdrawal
  row per original; `accepted_count` = distinct accepted forward
  external ids (legacy NULL included, withdrawal/alias excluded),
  `withdrawn_count` = effect rows.
- **D47 tests**: the full v1/v2 matrix + reviewed amendments, incl.
  revision matrix (r1 binding never a current-document resolution),
  duplicate-invoice forward still rejected with a populated withdrawal
  store (P2 inversion), legacy zero-kwargs + false-marker hold with zero
  attempts/effects then compatible re-dispatch, transfer/new-owner
  re-admission and grant loss, unresolved blockers (prepared/held/unknown),
  real child death after the withdrawal commit (`os._exit(73)` child;
  restart `recover`; `accepted_count()==1`, `withdrawn_count()==1`,
  attempts length 1, invoices unchanged, exact two-id ack, closure snapshot
  with both external ids and dispositions), S9 poison over a withdrawal
  identity, read-only `ReadOnlyInspector` over a compensation store with
  byte-equal files (zero-write), execute-exception truth, and the generic
  opt-in conformance test deriving its action from `contract.actions[0]`
  (skips without the opt-in — never hardcoding `expense.submit`).

## Disclosed preservation pins (GREEN with no product change)

- Publishing degradation test leg (`test_unpaired_and_publishing_…`),
  ordinary-payload leniency, forward-in-window `CANCELLATION_ACTIVE`,
  several resolution/closure/recovery legs once the underlying behavior
  existed from their own task's RED (revision matrix, one-row-original,
  S9 conflict over withdrawal identity, refused closure, recover-inside-
  window, crash legs in Task 8 once admission/dispatch/resolution landed
  with their own RED in Tasks 5–7), and Task 9's mixin opt-in test on
  FakeOA (the behavior was RED-driven in Tasks 3/6; the mixin test itself
  is the generic-domain pin). Each new test that GREENed without a product
  change pins behavior whose implementation was RED-driven in its owning
  task; none was written implementation-first.
- Test-infrastructure-only edit outside the new file:
  `tests/test_adapter_contract.py` `CountingFakeOA.execute/lookup` now
  forward `**kwargs` (it carries `FakeOA.contract`, which opted in) so its
  timeout-path intent is preserved under the new call protocol. No
  assertion semantics changed.

## Same-commit boundary doc audit

| commit | docs in the same commit |
|---|---|
| `aaf2e7b` (adapters migration) | `adapter-contract.md` (schema/migration/counters), `runtime-boundaries.md` (store-compatibility note) |
| `1e66ac5` (withdrawal path) | `adapter-contract.md` (withdrawal algorithm), `runtime-boundaries.md` |
| `4769574` (admission) | `runtime-boundaries.md` (compensation boundary), `interventions.md` (window exception incl. re-admission, codes), `adapter-contract.md` (pairing pointer) |
| `f61abc8` (dispatch) | `runtime-boundaries.md` (dispatch boundary rewrite), `adapter-contract.md` (opt-in call protocol, context hold) |
| `0fd3ecb` (resolution/proofs) | `runtime-boundaries.md` (binding/withdrawn proof/no-source-mapping), `adapter-contract.md` (withdrawal receipt pointer) |
| `c3f103c` (closure/recovery) | `interventions.md` (dispositions, refusal wording, unresolved rule, limits), `verification.md` (S10 coverage table, out-of-scope update) |
| `8f17ba7` (mixin/pins) | `adapter-contract.md` (mixin: six tests + skip rule) |

## Remaining risks and limits (truthful)

- **No public abandon** for prepared/held/`outcome_unknown` compensations:
  closure stays blocked until they resolve (D11 residual — any unresolved
  compensation, of which lookup unavailability is one cause). Held
  `ADAPTER_ACTION_CONTEXT_UNSUPPORTED` compensations need an opted-in
  adapter wired before closure.
- **Reconcile is caller-trusted** under B (single two-action adapter);
  a wrong-adapter reconcile remains a caller wiring error outside the
  product surface (documented, unchanged from today).
- The belt-and-braces dispatch branches (`STALE_INTENT` mirror, link
  revalidation) are unreachable via the public API and pinned only through
  crafted stores; if a future path makes them reachable their codes are
  already fixed.
- `adapter_result` storage means operation bodies grow with the full
  receipt (additive JSON only; schema 1).
- Expense family + active-cancellation window only: publishing-family,
  post-closure compensation, chains, cross-work compensation, intervener
  compensation authority, any viewer surface, source-key rotation,
  fencing/distributed exactly-once and multi-tenant authentication remain
  unimplemented and unclaimed.
- The two new suite skips and the rehearsal suite's 15th test are the
  generic mixin's designed opt-in skip, not coverage loss.
- W2 (compensation-demo, installer stage, README entries) and independent
  assembly/acceptance/merge remain with the master and later dispatches.

## Independent whole-branch review (final gate)

A fresh-context reviewer read the spec (§14/§15), the plan, the full
`4a15158..8f17ba7` diff and the ledger, **replayed every task's committed
tests against its parent commit** to falsify the RED claims, and re-ran the
gates, full battery, rehearsal suite, both real-crash tests and the
conformance suites; protected-path diff confirmed empty.

**Verdict: 0 Critical, 0 Important, 9 Minor** (all deferred, none enter a
fix pass). The reviewer confirmed: exact new strings and code orderings
match the spec; ordinary-path byte-compat is pinned; no signature
introspection/TypeError probing; no `withdrawn` source mapping (imports
denied, admin-only revoke, both pinned); runtime schema `1`; Python 3.9
stdlib-only; docs match implemented behavior line-for-line; crash tests use
real child processes asserting store truth; ownership is exactly the 12
allowed files. Deferred minors (full list in the ledger): two tautological
test assertions (inspector-summary arm; leftover `hasattr` in the kwargs
test — load-bearing assertions in both tests are real); the
no-new-dependencies pin skips absolute `from X import Y` lines (no new
imports diff-confirmed); a payload-shape probe leg uses an unsent command
id (real legs are the version/event-count assertions); the RED table lived
in this previously-uncommitted report; plan Step-2 "Run — FAIL" overstates
for Tasks 7/8 (already-GREEN legs disclosed above); `64504ac` (policy
pairing) carried no docs while spec §8's table names `policy.py` — the
enforced AGENTS `doc_sync_map` omits it, and the pairing docs landed
same-branch in `4769574` with the runtime admission they describe;
`verification.md` named the mixin test one commit before the mixin existed
(transient, final state truthful); the plan's Review Focus mapping misnames
two owning tests (coverage present and RED-verified). Declined by the
reviewer: `verify_install` internals beyond re-running the gates, and
pre-S10 machinery semantics (unchanged and pinned by their own suites).

## Final verification block (re-run after any review fixes)

Commands and expected results, as observed above: five gates, full
`unittest discover -s tests` (788, skipped=3), five demos,
`examples/rehearsal` (15, skipped=1), `scripts/verify_install.py` PASS,
protected-path diff empty.
