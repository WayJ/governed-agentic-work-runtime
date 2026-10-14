# S8 Task3 demo — developer report

Worker: S8 TASK3 demo owner (checkout `s8-revocation-demo`, branch
`WayJ/s8-revocation-demo`, base carrier `41583e2` asserted via
`git rev-parse HEAD` before coding). Scope: `work_runtime/revocation_demo.py`
(new), `work_runtime/cli.py`, `scripts/verify_install.py`,
`tests/test_revocation_demo.py`, `README.md`, `README.zh-CN.md`, additive
sections in `docs/evidence-revocation.md` / `docs/verification.md`. Date:
2026-10-15.

## Commits (scoped only; no merge/push, no extra workers)

| commit | subject |
|---|---|
| `5327d28` | feat: revocation-demo scenarios for hold, retained effects and closed correction |
| `07348fc` | feat: revocation-demo CLI subcommand |
| `aef84df` | feat: installed verifier proves revocation-demo stores outside the checkout |
| `19af10a` | docs: bilingual revocation-demo guide and S8 demo coverage |
| (this) | docs: S8 demo worker report |

Plan: `docs/superpowers/plans/2026-10-15-s8-task3-demo.md` (scoped plan,
executed with superpowers executing-plans; ledger in
`.superpowers/sdd/2026-10-15-s8-task3-demo/progress.md`, git-ignored).

## Baseline

Carrier `41583e2` exact; suite 679 tests OK (skipped=1) before any change.

## RED/GREEN evidence (observed)

- **Demo module**: 6 tests written first → RED `ImportError: cannot import
  name 'revocation_demo'` (6 errors) → GREEN after implementing the three
  scenarios (6/6). One plan defect surfaced GREEN-side: re-propose returns
  the confirmed operation only while admission rules are satisfied, so
  Scenario B was reordered (acceptance revoked first, approval last) —
  recorded as a ruling in the ledger; every brief beat kept truthfully.
  A test-side miscount (7 vs 6 store paths) was corrected before GREEN.
- **CLI subcommand**: `test_cli_revocation_demo_module_runs` RED with exit 2
  `invalid choice: 'revocation-demo'` → GREEN after the subparser/dispatch
  arm; adjacent `tests.test_ui_cli` unaffected (21 tests OK, skipped=1).
- **Installed verifier**: 5 tests RED `AttributeError:
  require_revocation_proof` → GREEN after implementing
  `require_revocation_proof` plus the two stages. One GREEN-side fix: the
  publishing adapter's external ids are `PUB-`-prefixed (not `OA-`), so the
  operation check takes the prefix per family.

## Real installed verification (not simulated)

`python3 scripts/verify_install.py` → **PASS, exit 0** (8.1s): fresh venv,
real non-editable install, import origin inside the venv, zero third-party
dependencies, all prior demos and stages green, and the two new stages
executed `python -m work_runtime revocation-demo` and
`work-runtime revocation-demo` outside the checkout with independent store
proof: revoked/verified statuses, source-event fingerprints recomputed
locally (acceptance fingerprints still match the original verified
acceptance — only status changed), business keys recomputed per family,
closed completion still citing the revoked acceptance, exactly one retained
external effect per store. The installed-UI HTTP stage also ran (backend
assembled in this checkout). Rejection paths pinned in tests: missing final
line, swapped store order, deleted external receipt, flipped revoked
status.

## Test counts and gates (final, this slice)

- New: `tests/test_revocation_demo.py` — 12 tests (6 demo-state, 1 CLI,
  5 installer-proof).
- Full suite: **691 tests OK (skipped=1)** (baseline 679 + 12; the single
  skip is the pre-existing installed-UI backend skip, unchanged).
- Gates: contracts `check_docs.py` 83 files / 307 links / 0 broken; tests
  (above); demo `work_runtime demo` exit 0; syntax `compileall` clean; site
  `check_site.py` 2 pages / 0 findings.
- All five demos exit 0: `demo`, `publish-demo`, `intervention-demo`,
  `adoption-demo`, `revocation-demo` (module `python3 -m work_runtime
  revocation-demo` and installed console `work-runtime revocation-demo`
  both proven by the verifier run above).

## Interface conformance

Consumed verbatim (core report / D33–D37): `Runtime.command(actor,
command_id, work_id, "revoke_evidence", {source, event_id, reason},
expected_version)`; accepted receipt `{command_id, decision,
result_state_version, evidence_id, evidence_status:"revoked",
prior_status}`; `record_evidence` dedup receipts carry current
`evidence_status`; event `EvidenceRevoked`. Authority in the demo: current
configured source with `evidence.revoke` (finance/reviewer) and
`work.intervene` administrator (root) — trusted local grants, not
authentication. Public APIs and real adapters only; no direct SQL
fabricated states (SQL reads appear only in tests/verifier for independent
proof, mirroring the existing intervention/adoption verifier pattern).
`revocation-demo` is not a new global gate (per D37 ratification it is an
S8 acceptance/install scenario; the AGENTS gates stay unchanged).

## Ownership honored

No `runtime.py`, policy, adapter, `inspection.py`, web-asset, GUI-doc,
sprint/acceptance/roadmap-ledger changes. README names discovered: both
`README.md` and `README.zh-CN.md` exist at the root; both updated.

## Remaining risks / limits (truthful)

- The marketing website's optional-demos list (`website/index.html`,
  `website/zh/index.html`) still shows the prior demos; website pages are
  outside this task's ownership (viewer/web owner or integration) — not
  updated, not claimed.
- D37 read-only viewer surfaces (derived revoked identities, closed-work
  notice) are the parallel viewer owner's wave; nothing claimed here.
- TD-1 (D-4 accepted-source event-id collision) remains deferred and open;
  no compensation, external fencing of in-flight calls, key rotation or
  distributed exactly-once claims are made anywhere in this slice.
- Decision codes reveal row existence (never status) to actors passing the
  preliminary check — unchanged ratified behavior; docs do not claim
  stronger confidentiality.
- `verify_install.py` needs pip index access for the build backend (it
  worked in this environment; offline runs fail at the install stage by
  design).
- **S8 as a whole is NOT declared released** — final acceptance, main
  merge/push and exact-SHA CI belong to the independent integration wave.
