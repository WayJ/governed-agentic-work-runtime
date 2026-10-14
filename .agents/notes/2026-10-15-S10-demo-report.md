# S10 W2 demo development report — 2026-10-15

Worker: S10 demo owner (this checkout `s10-compensation-demo`, branch
`WayJ/s10-compensation-demo`). Scoped plan:
[docs/superpowers/plans/2026-10-15-s10-demo.md](../../docs/superpowers/plans/2026-10-15-s10-demo.md)
committed with the docs task. Baseline asserted clean at the exact required
carrier SHA **`3996b83dc873c62f4bfe5346952d8cf422518003`**; the assembled core
(`4b57468`) and the
[W1 integration review](2026-10-15-S10-core-integration-review.md) were read in
full before planning (worker-CLI boundary, stable API, Mi-1/Mi-4 respected:
core history/docs untouched, installer run serial). No main merge, no push, no
sprint/acceptance/debt/ledger change, no full-S10-release claim — independent
final acceptance and the integration-owned merge are separate stories.

## Commits (this wave, on 3996b83)

| commit | task | content |
|---|---|---|
| `344ee3d` | 1 | `work_runtime/compensation_demo.py` (new) + `tests/test_compensation_demo.py` (10 tests) |
| `19eef50` | 2 | narrow `compensation-demo` CLI subcommand + CLI tests (incl. shipped-worker boundary pin) |
| `03108dd` | 3 | `scripts/verify_install.py` independent proof + module/console stages + 9 proof tests |
| `114a4d6` | 4 | bilingual README sections + bounded scope truth + verification/interventions/adapter-contract additive docs + scoped plan file |

Changed paths vs `3996b83` (exactly the owned set): `work_runtime/compensation_demo.py`
(new), `work_runtime/cli.py` (+11 lines, one subcommand), `scripts/verify_install.py`
(+330/−6), `tests/test_compensation_demo.py` (new, 21 tests), `README.md`,
`README.zh-CN.md`, `docs/verification.md`, `docs/interventions.md`,
`docs/adapter-contract.md` (additive), `docs/superpowers/plans/2026-10-15-s10-demo.md` (new).
Protected audit: `git diff 3996b83..HEAD` over runtime/adapters/contract/policy/demo/inspection/file_adapter/ingress/publishing/UI modules/web/data/website/examples/check_docs/check_site/AGENTS/pyproject/website.md/CONTRIBUTING/sprints/roadmaps/acceptances/debt-tracker/runtime-boundaries/S8-S9 reports is **empty** — byte-identical.

## RED/GREEN evidence (superpowers TDD, every leg observed)

- **Task 1 RED**: `python3 -m unittest tests.test_compensation_demo -v` →
  `Ran 10 tests … FAILED (errors=10)`, all
  `ImportError: cannot import name 'compensation_demo'` (behavioral store-reading
  tests, not guards). **GREEN**: 10/10 after implementation (one impl-side fix:
  inspector detail nests requirements under `work`). Full battery 798 OK (skip 3).
- **Task 2 RED**: CLI module run → exit 2
  `invalid choice: 'compensation-demo'`. **GREEN**: 12/12 focused; battery 800 OK
  (skip 3). `test_shipped_worker_cli_cannot_withdraw` passed pre-change by design
  — disclosed preservation leg pinning the review-verified boundary: real
  `python3 -m work_runtime worker` subprocess on a prepared withdrawal → exit 0,
  operation `held/AUTHORITY_DENIED`, `attempts == []`, `withdrawals == 0`.
- **Task 3 RED**: 9 proof tests → `AttributeError: module 'verify_install' has
  no attribute 'require_compensation_proof'`. **GREEN**: 21/21 focused after
  implementation (impl-side fixes: two SQL strings missing `FROM receipts`;
  negative-test substrings aligned to the actual checkpoint messages — every
  mutation is still rejected at the first meaningful invariant). Battery 809 OK
  (skip 3).
- **Task 4**: docs only; `check_docs.py` 0 broken; battery 809 OK (skip 3).

## The demo (deterministic, no credentials, fresh stores per run)

`python3 -m work_runtime compensation-demo` (also installed
`work-runtime compensation-demo`, `--directory` supported). Scenario A
(`crash/`, work `expense`): prerequisites → forward `expense.submit`
confirmed (`OA-…`, E08 satisfied) → admin `request_cancel` → owner's linked
withdrawal (exact five-key payload incl. `compensates`) prepared with the
immutable original snapshot and its own stable key → **real child death**:
a scoped grants-carrying inline subprocess (`sys.executable -c`, public API
only, `fault=lambda: os._exit(73)`) dispatches the withdrawal, the external
`WD-…` effect commits, the child dies before recording the outcome (exit code
73 asserted) → restart + `recover()` reconciles the original business key,
confirmed once (attempts length 1) → read-only store truth (forward accepted
proof still verified, E08 still satisfied, `withdrawn`-kind proof appended,
counts 1/1) → `finalize_cancel` with the exact two-id ack → closed/cancelled
with the compensation disposition (`compensates` + `adapter_result`). Scenario
B (`refusal/`): same prefix, then the withdrawal dispatched against a second
external store (`absent.sqlite`) that never saw the original → authoritative
stored `ORIGINAL_ABSENT` rejection → `confirmed_failed`, refusal reason in
`adapter_result`, ack = exactly the retained forward id, zero withdrawal
effects. No fake original-0 count and no deleted history anywhere; refusal is
never presented as reversal or unknown.

**Worker-CLI truth** (from the W1 review, re-verified by test): the shipped
`worker` CLI hardwires `demo_grants()` (no `expense.withdraw`), so it holds a
withdrawal dispatch `AUTHORITY_DENIED` with zero attempts/effects — the demo
uses its own `compensation_grants()`-carrying child and makes no false CLI
capability claim; `demo.py`/runtime grant sets are unchanged (pinned by
`test_grants_stay_scoped_to_the_demo_module`).

## Tests and gates (exact counts and skips)

- Baseline on clean `3996b83`: battery **788 OK (skipped=3)**; rehearsal
  **15 OK (skipped=1)**. Skips (names/reasons, unchanged through the wave):
  `Opt-in action/link execution: explicit forward context replays.` on
  `FilePublisherConformanceTests` and `FakePublisherConformanceTests`
  ('adapter does not opt into action/link execution context');
  `test_ui_cli.AbsentBackendTests.test_absent_backend_is_a_bounded_startup_error`
  ('backend assembled: absent-install path unreachable'); rehearsal skip =
  the same mixin test on the queue adapter. These are the designed C4 opt-in
  skips.
- Final battery: **809 OK (skipped=3)** = 788 baseline + 21 new
  (`tests/test_compensation_demo.py`: 10 demo-store, 2 CLI/boundary, 9
  installer-proof incl. 8 negatives). Rehearsal: **15 OK (skipped=1)**.
- Five AGENTS gates verbatim, unchanged command list: contracts
  `check_docs.py` **0 broken** (95→96 files during the session: +1 committed
  plan file; the remaining untracked delta is the git-ignored SDD workspace
  briefs, the same class as the W1 Mi-3 note — committed-tree count is 91),
  tests (above), demo exit 0, `compileall` clean, `check_site.py` 2 pages /
  0 findings.
- **Six demos explicit S10 validation (not a global gate, D12/D48)**:
  `demo`, `publish-demo`, `intervention-demo`, `adoption-demo`,
  `revocation-demo`, `compensation-demo` — all exit 0.

## Installed verification (serial run; Mi-4 respected — nothing ran in parallel)

`python3 scripts/verify_install.py` → **PASS, exit 0** (full log:
`.superpowers/sdd/2026-10-15-s10-demo/verify-install-run2.log`, scratch).
All 18 stages ran, no SKIPPED lines: fresh venv, real non-editable install,
import resolves inside the venv, zero third-party deps, legacy module+console
demos with independent store counts, SOP/lint, adoption, revocation, **new
module and console `compensation-demo` stages outside the checkout**, packaged
web assets byte-equal, installed UI over real HTTP with read-only table
equality and clean interrupt.

The compensation proof (`require_compensation_proof`, stdlib-only, never
imports the product, never trusts the demo's counters or narration) verifies
from the two scenario stores: forward and withdrawal business keys
**recomputed locally** (`digest(["expense-submit","expense.submit",doc id,revision])`
and `digest(["expense-submit","expense.withdraw",original op id])`), full
original snapshot equality with the forward op, stored `adapter_result`
binding (`original_external_id` = forward external id, `WD-` id, receipt
result equality), exactly two tagged receipts (forward
`expense.submit`/NULL link; withdrawal `expense.withdraw` with
`link_digest == digest(compensates)` recomputed), exactly one `withdrawals`
row per original with the withdrawal key/digest, invoices unchanged
(`INV-001` → forward external id), accepted/withdrawn counts recomputed from
rows (1/1), original op confirmed with exactly one succeeded attempt each,
forward `accepted` proof still verified, distinct **`withdrawn`-kind** proof
(never forward-accepted) with fingerprint recomputed from its body, E08 still
satisfied by the real forward proof, exact two-id closure ack with external
ids and the 3-key forward / 5-key compensation dispositions; refusal store:
`confirmed_failed` with the stored `ORIGINAL_ABSENT` `adapter_result`, no
withdrawn proof, single-id ack, refusal disposition, `absent.sqlite` holding
exactly one queryable rejection tagged with action/link digest and zero
effects. Negative proof checks (named tests, mutation-based, not
implementation mirrors): deleted withdrawal row, wrong linked target
(mutated snapshot), swapped link digest, forged extra accepted forward
receipt, flipped `withdrawn`→`accepted` proof kind, refusal-store withdrawal
effect inserted, deleted absent-store rejection, missing final line — every
one rejected. The module stage also re-runs the printed `inspect` command
verbatim against the installed entry point (`"outcome": "cancelled"`).

## Runtime proof truth and boundaries (as demonstrated, no more)

Expense-family, active-cancellation-window compensation only; the immutable
link and separate stable key; one withdrawal effect per original with
per-key receipts; `withdrawn` proof appended (never importable, admin-only
revoke); refusal explicit (`ORIGINAL_ABSENT` queryable) and unknown outcomes
block closure (no public abandon); history appended, never deleted; trusted
local grants are not authentication; dispatch/reconcile caller-trusted.
Publishing compensation, post-closure compensation, chains, auth, fencing,
key rotation and distributed exactly-once remain unimplemented and unclaimed.

## Remaining risks / notes for the master

- The W1 **Mi-1** (`c3f103c` boundary-doc pairing gap) is untouched here by
  instruction — routed to the master/integration as recorded in the W1 review.
- Final whole-branch review was a **self-review** (the dispatch forbids extra
  agents); the independent S10 final acceptance/integration review remains
  the load-bearing gate. Deferred minors from self-review: (1) demo step 4
  prints the withdrawal external id as the `(WD-…)` format placeholder rather
  than the concrete id (it is asserted and inspectable); (2) the refusal-store
  OA check reuses the unfiltered `count_accepted` helper — correct in this
  scenario because the withdrawal receipt lives in `absent.sqlite`; (3) the
  compensation API usage example exists only in the EN README (the zh README
  defers Python examples to EN by pre-existing design).
- Installer flake Mi-4 remains root-cause-untracked upstream; both runs here
  were serial and passed.
