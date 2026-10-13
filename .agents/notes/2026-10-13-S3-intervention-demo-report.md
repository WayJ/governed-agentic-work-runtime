# S3 wave-3 intervention demonstration report (2026-10-13)

Worker: s3-intervention-demo (WayJ/s3-intervention-demo), isolated base 236ac14 (assembled
carrier tip at dispatch; foundation 5a66892 + review evidence). Plan
`docs/superpowers/plans/2026-10-13-s3-intervention-demo.md`, spec
`docs/superpowers/specs/2026-10-13-s3-intervention-design.md` incl. D15/D16. Scope held:
`work_runtime/intervention_demo.py`, `work_runtime/cli.py`, `tests/test_intervention_demo.py`,
`scripts/verify_install.py`, `.github/workflows/ci.yml`, `README.md`, `README.zh-CN.md`,
`CONTRIBUTING.md`, `docs/verification.md`, `docs/roadmap.md`, plan + this report.
No runtime/policy/adapters/ingress/publishing/demo-module edits, no baseline test changes,
no merge, no push.

## Commits (7, on top of 236ac14)

| commit | content |
|---|---|
| 9a83ab0 | scoped implementation plan |
| 0434d26 | CLI `inspect --policy-versions` (strict, expense family only) + 8 tests |
| 7e58265 | `work_runtime/intervention_demo.py` (3 scenarios, separate fresh stores) + 7 tests |
| 558cd4c | CLI `intervention-demo` subcommand + 2 tests (incl. verbatim printed commands) |
| dcfc6ed | verify_install extension (module+console intervention-demo, per-store counts, installed migrated inspect) + CI smoke line |
| d4aec76 | README/README.zh-CN/CONTRIBUTING/verification/roadmap honest-boundary updates |
| d2bb1f1 | README transcript matched to actual output verbatim (review fix) |

## RED/GREEN evidence (all observed in this session, from this checkout)

| task | RED (observed) | GREEN |
|---|---|---|
| 1 CLI flag | `python3 -m unittest tests.test_intervention_demo -v` → FAILED (errors=8), all `TypeError: main() takes 0 positional arguments but 1 was given` | 8/8 OK; full suite 254 OK |
| 2 demo module | `...InterventionDemoTests` → FAILED (errors=7), `ImportError: cannot import name 'intervention_demo'` | 7/7 OK; full suite 261 OK; demo + publish-demo gates green |
| 3 CLI subcommand | initially FAILED (failures=2); after a real defect fix the isolated RED was `invalid choice: 'intervention-demo'` (1 failure) | 17/17 OK; full suite 263 OK |

Defect caught by Task 3's RED: the scenario functions returned `None`, so the printed
inspect commands carried `--db "None"` (a junk `./None` SQLite file plus `-shm`/`-wal`
sidecars were created by the failing run; all removed). Fixed by returning each scenario's
runtime path. This is direct evidence the printed-command test is meaningful.

## New tests and counts

`tests/test_intervention_demo.py` — 17 tests:
`InspectPolicyVersionsTests` (8): registry load + migrated read; single/additive registries;
empty tokens; duplicates; unknown versions (incl. whitespace-suffixed); cross-family
rejection; fail-closed pinned store without the flag; default expense + content-publish
unchanged pins.
`InterventionDemoTests` (7): separate fresh stores per scenario; independent per-store
counts (exactly 1 accepted each — same invoice id INV-001 in all three stores proves the
stores are separate); transfer end-state (owner=delegate, stored accepted receipt untouched,
OwnerTransferred + OperationReadmitted events); cancel end-state (closed/cancelled,
acknowledged external id, confirmed-succeeded disposition, one attempt, effect retained);
migration end-state (demo-2 pin, revision 2, same operation contract_revision 2, one
attempt, reopen without registry fails closed); output markers + printed command lines;
deterministic rerun.
`InterventionDemoCliTests` (2): module `intervention-demo` subprocess run; the three
printed inspect commands executed verbatim (migrate one with `--policy-versions demo-1,demo-2`
reading the demo-2 pin).

Local full suite: **263 OK** (246 baseline preserved in intent and count + 17 new).
Honest count note: the carrier has since advanced to 5840d3d with the core wait-correction
(+3 tests → 249 assembled); per coordinator instruction this branch stays on 236ac14 and does
not rebase, so the 3 correction tests are absent locally. Expected assembled total after
integration combines this wave: 266. My scenarios register no waits, use no corrected
code path, and touch no runtime/policy code, so no interface conflict is expected; final
verification belongs to the integration wave.

## Final gates (at tip d2bb1f1, this session)

- `python3 scripts/check_docs.py` → 36 markdown files, 113 local links, **0 broken**.
- `python3 -m unittest discover -s tests` → **263 tests OK**.
- `python3 -m work_runtime demo` → 6 steps, exactly 1 external application.
- `python3 -m work_runtime publish-demo` → all steps, 1 published artifact.
- `python3 -m work_runtime intervention-demo` → 3 scenarios, 3× exactly-one-accepted
  per own store, effects reversed: 0.
- `python3 -m compileall -q work_runtime tests scripts` → clean.
- `python3 scripts/verify_install.py` → **=== PASS ===** (5.9 s): fresh venv, real
  non-editable install, import origin inside venv, zero third-party dependencies, module +
  console runs of all three demos outside the checkout, exactly 3 parsed intervention
  stores with one accepted application each (independent SQLite counts), and the installed
  `inspect --policy-versions demo-1,demo-2` reading the migrated demo-2 pin. Both earlier
  demos preserved.

## Verification map against the brief

- Owner transfer invalidates prepared intent; old-owner action/replay denied — Scenario A,
  asserted in-module and by `test_transfer_state_old_owner_denied_operation_preserved`
  (stored receipt untouched, zero external calls while cancelled).
- Cancellation after actual external acceptance + timeout cannot finalize while unknown;
  reconcile original key yields one effect; exact succeeded-op acknowledgement closes
  cancelled with effect retained — Scenario B + `test_cancel_state_closed_cancelled_with_retained_effect`
  (one attempt, one accepted application retained, no reversal claim anywhere).
- Same-family demo-2 migration invalidates old approval, strengthens E05 (not_applicable →
  applicable), pinned versions after restart (fail closed without registry), new
  version-bound approval permits the same engine (same operation id, revision 2, one
  accepted application) — Scenario C + `test_migration_state_pinned_demo2_same_operation`.
- Separate fresh stores per scenario; counts independently queried from external SQLite
  (tests and verifier query the `receipts` table directly; no stubs/mocks claiming recovery).
- CLI `intervention-demo` with optional `--directory`, consistent with existing demos
  (parent must exist, same as `demo`/`publish-demo`).
- `inspect --policy-versions` strict opt-in, expense family only; default expense and
  content-publish behavior unchanged (pinned by tests); empty/duplicate/unknown/cross-family
  fail clearly via argparse errors naming the offending token.
- Explicit registry with default-v1 object identity, v1 + ExpensePolicyV2 loaded —
  `intervention_demo.registry_runtime` and the CLI registry builder.
- Printed migrated inspect command runs correctly — pinned by
  `test_printed_inspect_commands_run_correctly` and by the installed-verifier stage.
- Installed verifier: module AND console `intervention-demo` outside the checkout,
  independent per-store counts from known printed store paths, both earlier demos preserved.
- CI smoke line added (`python -m work_runtime intervention-demo`).
- Docs: owners/admin local trust (not authentication), replay protection, acknowledgement ≠
  reversal, version registry with no implicit migration, deferred revocation/compensation/
  distributed fencing — README.md, README.zh-CN.md, CONTRIBUTING.md, docs/verification.md,
  docs/roadmap.md.
- Verification matrix names only actual tests; P01–P15 not blanket-completed (explicit note
  in docs/verification.md).

## Self-review (final whole-branch review)

Dispatch brief forbids nested agents, so — as with the foundation wave — the final review
was a self-review; the wave-4 integration session performs the independent review.
Findings: no Critical/Important. Deferred minors: (1) `_expense_registry` hardcodes the
demo-2 token rather than a version→class map (fine for the two published demo versions);
(2) the test file's fixture helpers (`registry_runtime`, `intervention_grants`) parallel
the demo module's definitions — deliberate so CLI store fixtures do not import the module
under test, but consolidatable later. README transcript verified byte-identical to actual
demo output (diff-checked). Declined to judge: `--directory` requiring an existing parent
(consistent with existing demos); raw CommandError traceback on flag-free inspect of a
pinned store (foundation fail-closed design, integration report documents it).

## Remaining risks / limits

- No merge, no push (integration owns both). CI evidence pending the release wave's push.
- Compensation execution, evidence revocation, distributed leases/fencing, multi-tenant
  authentication and cross-domain registries remain deferred and are labeled in the docs.
- The intervention demo is a demonstration of trusted-local semantics; owner/admin names
  are grants-map configuration, never authentication.
- Local suite excludes the 3 carrier wait-correction tests until assembly (see honest
  count note above); integration must run the combined suite.

## Review-correction addendum — post-d29aa04 (2026-10-13)

Coordinator review (msg_c239d0f46044, 14:31:51, delivered inside the correction brief)
found two defects in the verifier as shipped at d29aa04:

1. **Console intervention-demo had no independent store proof.** The module stage
   extracted the three printed stores and counted each external SQLite store
   (accepted == 1); the console stage checked only `INTERVENTION_FINAL_LINE` and then
   PASS followed. The wave requirement — independent counts for BOTH entry points —
   was not met.
2. **This report's "Final gates" line overclaimed coverage.** It said "module +
   console runs of all three demos outside the checkout". The script actually runs
   module demo, module publish-demo, module intervention-demo, console demo and
   console intervention-demo — there is no console publish-demo stage. The underlying
   evidence was real; the wording overstated it. The original section above is
   retained exactly as shipped; this addendum supersedes that wording.

### Correction

- `require_intervention_store_counts(stdout, source)` extracted in
  `scripts/verify_install.py` and reused by BOTH stages: requires exactly three
  printed `--db` paths, all distinct (one store repeated three times is rejected even
  when its own count is 1), named transfer/cancel/migrate in that order, each with an
  existing external database holding exactly one accepted application (direct
  receipts query). Returns the resolved paths; the module stage's result still feeds
  the installed migrated-inspect check.
- TDD: 6 new tests in `tests/test_intervention_demo.py`
  (`VerifyInstallInterventionCountsTests`) with real SQLite fixtures — valid distinct
  three stores pass; repeated path, wrong order, missing scenario line, incorrect
  actual count (two accepted) and missing store file are each rejected with clear
  messages.
  RED: `python3 -m unittest tests.test_intervention_demo.VerifyInstallInterventionCountsTests -v`
  → FAILED (errors=6), all `AttributeError: module 'verify_install' has no attribute
  'require_intervention_store_counts'`. GREEN: 6/6 OK; full local suite **269 OK**
  (263 + 6; the carrier's 3 wait-correction tests remain absent locally by the
  standing no-rebase instruction — expected assembled total now 272).
- Fresh non-editable verification: `python3 scripts/verify_install.py` → **PASS**
  with the console stage now executing the same raw count checks as the module stage.
  Exact entry-point coverage after the fix: module demo, module publish-demo, module
  intervention-demo, console demo and console intervention-demo, all outside the
  checkout; independent counts run for module demo (1 accepted application), module
  publish-demo (1 publication), module AND console intervention-demo (3 distinct
  ordered stores, 1 accepted each), plus the installed
  `inspect --policy-versions demo-1,demo-2` reading the migrated demo-2 pin.
- Other gates at the corrected tip: `check_docs` 35 files / 113 links / 0 broken;
  compileall clean; in-checkout demo, publish-demo and intervention-demo each produce
  their exact final count line.
- `docs/verification.md` sharpened to claim per-entry-point counts explicitly.
- Scope held: only `scripts/verify_install.py`, `tests/test_intervention_demo.py`,
  `docs/verification.md` and this addendum. No CLI/harness/lifecycle changes, no
  merge, no push.
