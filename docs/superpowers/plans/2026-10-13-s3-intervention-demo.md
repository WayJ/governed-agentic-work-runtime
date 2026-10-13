# S3 Wave 3 — Intervention Demonstration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the dependent demonstration wave of S3: a deterministic, no-credentials `intervention-demo` (transfer / cancel / migrate, one fresh store pair per scenario), the strict opt-in CLI `inspect --policy-versions`, installed-verification and CI coverage, and honest public docs.

**Architecture:** A new `work_runtime/intervention_demo.py` drives the *real* `Runtime` and `FakeOA` (foundation tip 5a66892: `request_cancel`, `finalize_cancel`, `transfer_owner`, `migrate_policy`, keyword-only `policies` registry, `ExpensePolicyV2`). Each scenario runs against its own `runtime.sqlite` + `oa.sqlite` under one fresh folder. The CLI gains an `intervention-demo` subcommand and an expense-family-only `--policy-versions` flag that loads an explicit registry (`demo-1` → the default `ExpensePolicy` object, `demo-2` → `ExpensePolicyV2`); the flag-free `inspect` default is untouched. `scripts/verify_install.py` extends to the third demo (module + console) with independent per-store SQLite counts, and CI adds one smoke line.

**Tech Stack:** Python >= 3.9 standard library only, `unittest`, SQLite.

**Spec:** `docs/superpowers/specs/2026-10-13-s3-intervention-design.md` (D15/D16) · `docs/superpowers/sprints/2026-10-13-S3-plan.md` (Wave 3) · `.agents/notes/2026-10-13-S3-foundation-integration.md` ("Stable interface for the demo wave").

**Execution method:** inline `superpowers:executing-plans` (dispatch brief mandates inline execution, no nested agents; blockers go to the coordinator through `orca orchestration ask`).

## Global Constraints

- Python >= 3.9, zero runtime dependencies, standard-library `unittest` only.
- Ownership scope (dispatch brief): `work_runtime/intervention_demo.py`, `work_runtime/cli.py`, `tests/test_intervention_demo.py`, `scripts/verify_install.py`, `.github/workflows/ci.yml`, `README.md`, `README.zh-CN.md`, `CONTRIBUTING.md`, `docs/verification.md`, `docs/roadmap.md`, this plan, this wave's report. **No** edits to `runtime.py`, `policy.py`, `adapters.py`, `ingress.py`, `publishing*.py`, `demo.py`, sprint/epic/acceptance docs, or any baseline test file.
- All 246 baseline tests keep passing, intent and count unchanged.
- Meaningful TDD: every behavior change observed RED then GREEN; record evidence in the report.
- No credentials, no network, deterministic runs. External-effect counts come from real SQLite queries on the external stores — never from printed text alone, never from stubs/mocks claiming recovery.
- No compensation/reversal claim anywhere: cancellation acknowledgement records an effect, it does not undo it. Docs label deferred: evidence revocation, compensation execution, distributed leases/fencing, multi-tenant auth.
- `docs/verification.md` claims only actual named tests; the P01–P15 matrix is not blanket-completed by this wave.
- Development worker commits its own branch only: no merge into main, no push.

## Review Focus

The five inputs/failure modes most likely to bite, each pinned by a test in the owning task:

1. `--policy-versions` combined with `--policy content-publish` (cross-family) must fail clearly, not silently ignore the flag → Task 1 `test_policy_versions_rejects_cross_family_policy`.
2. Malformed version lists — empty token (`demo-1,`), duplicates (`demo-1,demo-1`), unknown (`demo-9`, `demo-1, demo-2`) — must fail naming the offending token → Task 1 strict-parsing tests.
3. A store pinned to `demo-2` inspected *without* the flag must still fail closed (unchanged default behavior) → Task 1 `test_inspect_without_versions_fails_closed_on_pinned_store`.
4. The printed migrated `inspect` command must run verbatim (its `--policy-versions demo-1,demo-2` spelling is load-bearing) → Task 3 `test_printed_inspect_commands_run_correctly`.
5. If the demo's folder layout or printed `--db` lines drift, `verify_install.py` must fail loudly, not silently skip counts → Task 4 requires exactly three parsed stores, each independently counted as exactly 1 accepted.

---

### Task 1: CLI `inspect --policy-versions` (strict, expense family only)

**Files:**
- Modify: `work_runtime/cli.py`
- Test: `tests/test_intervention_demo.py` (create)

**Interfaces:**
- Consumes: `Runtime(path, policy, grants, *, policies=None)` from the foundation; `ExpensePolicy`, `ExpensePolicyV2` from `work_runtime.policy`.
- Produces: `cli.main(argv: Optional[List[str]] = None) -> None` (backward compatible; console entry unaffected); `inspect --policy-versions SPEC` where SPEC is a comma-separated list of exact version tokens from `{"demo-1", "demo-2"}`. Invalid input exits via `parser.error` (exit code 2, message on stderr). With the flag and `--policy expense-submit` (the default), the runtime is constructed as `Runtime(db, default, demo_grants(), policies=registry)` where `default = ExpensePolicy()` and `registry` maps `demo-1 → default` (same object) and/or `demo-2 → ExpensePolicyV2()`. Without the flag, `inspect` behaves exactly as before (`policies=None`).

- [ ] **Step 1: Write the failing tests** — new file `tests/test_intervention_demo.py`, class `InspectPolicyVersionsTests(unittest.TestCase)` with a helper that builds a store containing a work migrated to `demo-2` (real `Runtime` + `Runtime.command("root", …, "migrate_policy", …)`; no demo module yet) plus a plain `demo-1` store via `work_runtime.demo` helpers, and in-process `cli.main([...])` invocations capturing stdout via `contextlib.redirect_stdout`:

```python
def test_policy_versions_loads_registry_and_reads_migrated_work(self):
    # cli.main(["inspect", "--db", self.path, "--work", "demo",
    #           "--policy-versions", "demo-1,demo-2"]) → SystemExit is NOT raised;
    # stdout JSON work["contract"]["policy_version"] == "demo-2"

def test_policy_versions_single_version_registries_are_valid(self):
    # "demo-2" alone (additive, default omitted) and "demo-1" alone both read the migrated/plain store

def test_policy_versions_rejects_empty_tokens(self):
    # "" , "demo-1,", ",demo-1" → SystemExit code 2; stderr names the problem via parser.error

def test_policy_versions_rejects_duplicates(self):
    # "demo-1,demo-1" and "demo-2,demo-1,demo-2" → SystemExit code 2

def test_policy_versions_rejects_unknown_versions(self):
    # "demo-9", "demo-1, demo-2" (space-prefixed token), "content-v1" → SystemExit code 2,
    # message contains the offending token

def test_policy_versions_rejects_cross_family_policy(self):
    # --policy content-publish --policy-versions demo-1 → SystemExit code 2,
    # message says the flag supports the expense family only

def test_inspect_without_versions_fails_closed_on_pinned_store(self):
    # migrated store, no flag → assertRaises(CommandError) from Runtime (default unchanged)

def test_inspect_default_expense_and_content_publish_unchanged(self):
    # plain demo-1 store, no flag → works as before; minimal content-publish store +
    # --policy content-publish, no flag → works as before
```

- [ ] **Step 2: Run to verify RED** — `python3 -m unittest tests.test_intervention_demo -v` → fails with `SystemExit: 2` ("unrecognized arguments: --policy-versions") or `TypeError` on `main(argv)` — record output.
- [ ] **Step 3: Implement in `work_runtime/cli.py`** — change `main()` to `main(argv=None)` feeding `parser.parse_args(argv)`; add `inspect.add_argument("--policy-versions", dest="policy_versions", default=None, help="Explicitly load comma-separated expense policy versions (demo-1,demo-2) for pinned works")`; in the inspect branch, when `args.policy_versions is not None`: reject `--policy content-publish` (`parser.error("--policy-versions supports expense-family versions only; it cannot be combined with --policy content-publish")`), split on `","` (no stripping — exact tokens), then for each token: empty → `parser.error("empty policy version in --policy-versions")`; duplicate (already seen) → `parser.error("duplicate policy version '<tok>'")`; not in `{"demo-1","demo-2"}` → `parser.error("unknown policy version '<tok>'; supported versions: demo-1, demo-2")`; build `registry` (`demo-1 → default` object identity, `demo-2 → ExpensePolicyV2()`) and construct the `Runtime` with `policies=registry`. Import `ExpensePolicyV2` from `.policy`.
- [ ] **Step 4: Run to verify GREEN** — same command, all new tests pass; full `python3 -m unittest discover -s tests` → 246 + N OK.
- [ ] **Step 5: Commit** — `feat(cli): strict opt-in inspect --policy-versions for expense-family registries`

### Task 2: `work_runtime/intervention_demo.py` — three scenarios, separate fresh stores

**Files:**
- Create: `work_runtime/intervention_demo.py`
- Test: `tests/test_intervention_demo.py` (extend)

**Interfaces:**
- Consumes: `work_runtime.demo` helpers (`demo_grants`, `document`, `initialize`, `prerequisites`, `proof`, `send`), `action`-style propose payloads, `FakeOA(path, timeout_after_commit=…)`, `Runtime` with `policies=`, `ExpensePolicyV2`, `CommandError`.
- Produces: `intervention_grants() -> dict` (`demo_grants()` + `"root": {"work.intervene"}` + `"delegate": {"work.manage", "expense.submit"}`); `run_intervention_demo(directory: Optional[str] = None) -> Path` — creates one `tempfile.mkdtemp(prefix="governed-intervention-", dir=directory)` folder with subfolders `transfer/`, `cancel/`, `migrate/`, each holding its own `runtime.sqlite` + `oa.sqlite`; work ids `transfer`, `cancel`, `migrate`; prints the step lines below and returns the folder. Scenario C's runtime is `v1 = ExpensePolicy(); Runtime(path, v1, intervention_grants(), policies={"demo-1": v1, "demo-2": ExpensePolicyV2()})` (default v1 object identity in the explicit registry).

Exact printed copy (kept stable for README transcripts and verifier parsing):

```text
Scenario A — ownership transfer (own store: transfer/)
1. Agent proposes submission → intent prepared while agent owns the work
2. transfer_owner agent → delegate → prepared intent invalidated (OWNERSHIP_TRANSFERRED)
3. Former owner re-proposes → AUTHORITY_DENIED; replays the accepted command → fresh AUTHORITY_DENIED, stored receipt untouched; dispatch stays cancelled (0 external calls)
4. New owner re-proposes → SAME operation id (business key stable) → intent readmitted
5. Dispatch → confirmed_succeeded; accepted applications in this store: 1

Scenario B — cancellation with an uncertain external effect (own store: cancel/)
1. Agent proposes submission → intent prepared
2. Dispatch → OA accepted, response lost after commit → outcome unknown (the effect exists)
3. request_cancel → intent stored; finalize now → OUTCOME_UNRESOLVED while the effect is unknown
4. Reconcile the ORIGINAL business key → confirmed_succeeded, external id recovered, nothing resent
5. finalize [] → CANCEL_ACKNOWLEDGEMENT_MISMATCH; exact acknowledgement [op] → CLOSED cancelled
6. Acknowledgement records the effect (no reversal); accepted applications in this store: 1

Scenario C — explicit policy migration demo-1 → demo-2 (own store: migrate/)
1. Under-limit expense bound to demo-1 → E05 not applicable; a demo-1-shaped approval exists
2. work.intervene admin migrates to demo-2 → revision 2; old approval INVALID; E05 applicable + pending; prepared intent invalidated (POLICY_MIGRATED)
3. Re-propose → REQUIREMENT_UNSATISFIED; stale contract revision → CONTRACT_REVISION_MISMATCH
4. Finance approves under demo-2 ({digest, policy_version}) → E05 satisfied → SAME operation readmitted
5. Restart without the registry → fails closed; restart with the registry → pinned demo-2 usable
6. Dispatch → confirmed_succeeded; accepted applications in this store: 1

3 scenarios; accepted applications: 3 (one per store); effects reversed: 0

Inspect the durable history:
  python3 -m work_runtime inspect --db "<folder>/transfer/runtime.sqlite" --work transfer
  python3 -m work_runtime inspect --db "<folder>/cancel/runtime.sqlite" --work cancel
  python3 -m work_runtime inspect --db "<folder>/migrate/runtime.sqlite" --work migrate --policy-versions demo-1,demo-2
```

Scenario mechanics (all asserted in-module with real decisions/counts; transfer replay resends the *original* payload with the *original* `expected_version`):

- A: `initialize` → `prerequisites` → propose (`command_id="transfer-submit-once"`, capture payload + version + op id) → `transfer_owner {owner: "delegate", reason: "handover"}` → old owner: fresh propose `AUTHORITY_DENIED`, replay `AUTHORITY_DENIED`, `get_command("agent","transfer-submit-once")` still the stored accepted receipt, `dispatch(op)` stays cancelled with `oa.accepted_count() == 0` → delegate re-proposes (same op id, readmitted) → dispatch → `confirmed_succeeded`, count 1.
- B: propose → dispatch with `FakeOA(path, timeout_after_commit=True)` → `outcome_unknown`, count 1 → `request_cancel {reason: "wrong invoice discovered"}` → `finalize_cancel []` → `OUTCOME_UNRESOLVED` → `reconcile(op, FakeOA(path))` → `confirmed_succeeded` with `external_id`, attempts stay 1, count 1 → `finalize_cancel []` → `CANCEL_ACKNOWLEDGEMENT_MISMATCH` (blockers `[op]`) → `finalize_cancel [op]` → accepted; work `(closed, cancelled)`; `completion.acknowledged_operations[0].external_id` equals the recovered id; count still 1.
- C: create with `document(amount=80000)` (under limit) bound `demo-1`, `prerequisites(approval=True)` (approval data `{"digest": …}`, v1 shape), E05 `not_applicable`, propose accepted → root `migrate_policy {policy_id: "expense-submit", policy_version: "demo-2", reason: "strengthen the approval rule"}` → revision 2, E05 `applicable`+`pending`, op cancelled `POLICY_MIGRATED` → propose `REQUIREMENT_UNSATISFIED`; forced `contract_revision: 1` → `CONTRACT_REVISION_MISMATCH` → `proof("approval", data={"digest": …, "policy_version": "demo-2"})` + `verify_pending` → E05 satisfied → propose → same op id, `contract_revision` 2, ready → reopen `Runtime(path, ExpensePolicy(), grants)` (no registry) `get_work` raises `CommandError` (caught, printed as fails-closed evidence) → reopen with registry → dispatch → `confirmed_succeeded`, count 1.

- [ ] **Step 1: Write the failing tests** — `tests/test_intervention_demo.py`, class `InterventionDemoTests` (capture stdout with `redirect_stdout`; query stores with raw `sqlite3` on each `oa.sqlite` `receipts` table, independent of `FakeOA` helpers):

```python
def test_demo_creates_separate_fresh_stores_per_scenario(self):
    # folder has transfer/ cancel/ migrate/ each with runtime.sqlite + oa.sqlite (6 files, distinct paths)

def test_each_store_independently_holds_exactly_one_accepted_application(self):
    # raw sqlite3 "SELECT result FROM receipts" per store: exactly one row with status == "accepted";
    # same invoice id INV-001 in all three stores — possible only because stores are separate

def test_transfer_state_old_owner_denied_operation_preserved(self):
    # reopened Runtime (demo grants): owner == "delegate"; operation confirmed_succeeded;
    # get_command("agent", "transfer-submit-once") still accepted (stored receipt untouched);
    # events include OwnerTransferred and OperationReadmitted

def test_cancel_state_closed_cancelled_with_retained_effect(self):
    # work (closed, cancelled); completion.acknowledged_operations[0] has the external_id;
    # operation_dispositions lists the op confirmed_succeeded; store count == 1 (effect retained)

def test_migration_state_pinned_demo2_same_operation(self):
    # contract (policy_version demo-2, revision 2); operation confirmed_succeeded with
    # contract_revision 2 and one attempt; events include PolicyMigrated; reopening without
    # the registry raises CommandError

def test_demo_output_pins_key_markers(self):
    # stdout contains "OWNERSHIP_TRANSFERRED", "OUTCOME_UNRESOLVED", "CANCEL_ACKNOWLEDGEMENT_MISMATCH",
    # "POLICY_MIGRATED", the final line "accepted applications: 3 (one per store)", and three
    # "inspect --db" lines — the migrate one ending with "--policy-versions demo-1,demo-2"

def test_demo_runs_are_repeatable(self):
    # a second run into a different directory yields the same store counts (deterministic)
```

- [ ] **Step 2: Run to verify RED** — `python3 -m unittest tests.test_intervention_demo.InterventionDemoTests -v` → `ModuleNotFoundError`/`ImportError: intervention_demo` — record output.
- [ ] **Step 3: Implement `work_runtime/intervention_demo.py`** — module docstring ("deterministic intervention harness: transfer, cancel, migrate — no credentials, no network; acknowledgement is not compensation"), `intervention_grants()`, three private scenario functions, `run_intervention_demo(directory=None)`; reuse `work_runtime.demo` helpers; every step asserted before printed.
- [ ] **Step 4: Run to verify GREEN** — targeted class, then full discover; `python3 -m work_runtime demo` and `publish-demo` still green.
- [ ] **Step 5: Commit** — `feat(demo): deterministic intervention demo with per-scenario stores`

### Task 3: CLI `intervention-demo` subcommand; printed commands run

**Files:**
- Modify: `work_runtime/cli.py`
- Test: `tests/test_intervention_demo.py` (extend)

**Interfaces:**
- Consumes: `run_intervention_demo` from Task 2.
- Produces: `python3 -m work_runtime intervention-demo [--directory DIR]` and console `work-runtime intervention-demo` — consistent with the two existing demo subcommands.

- [ ] **Step 1: Write the failing tests** — class `InterventionDemoCliTests`:

```python
def test_cli_intervention_demo_module_runs(self):
    # subprocess [sys.executable, "-m", "work_runtime", "intervention-demo"] with cwd=REPO_ROOT
    # → exit 0; stdout contains the final line "accepted applications: 3 (one per store)"

def test_printed_inspect_commands_run_correctly(self):
    # parse the three printed "python3 -m work_runtime inspect …" lines; execute each verbatim
    # (leading "python3" replaced by sys.executable) with cwd=REPO_ROOT; all exit 0;
    # the migrate one prints contract policy_version demo-2; the transfer one (no flag) exits 0
```

- [ ] **Step 2: Run to verify RED** — `SystemExit: 2` ("invalid choice: 'intervention-demo'") / zero inspect lines parsed — record.
- [ ] **Step 3: Implement** — add the subparser (`intervention = sub.add_parser("intervention-demo", help="Run the ownership-transfer, cancellation and policy-migration demonstration")` with `--directory`) and the dispatch branch calling `run_intervention_demo(args.directory)`.
- [ ] **Step 4: Run to verify GREEN** — targeted tests, then full discover.
- [ ] **Step 5: Commit** — `feat(cli): intervention-demo subcommand with optional directory`

### Task 4: Installed verification + CI smoke

**Files:**
- Modify: `scripts/verify_install.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: printed demo lines and per-scenario store layout from Task 2/3.
- Produces: verifier stages for module + console `intervention-demo`, independent per-store accepted counts, and an in-venv `inspect --policy-versions demo-1,demo-2` run against the migrated store; CI line `python -m work_runtime intervention-demo`.

- [ ] **Step 1: Extend `scripts/verify_install.py`** — add `INTERVENTION_FINAL_LINE = "accepted applications: 3 (one per store)"`; after the publish-demo stage add: (a) module `intervention-demo` outside the checkout (`run(..., show=True)`), require the final line, `re.findall(INSPECT_DB, …)` must yield **exactly 3** db paths (order transfer, cancel, migrate) — otherwise fail loudly; (b) for each parsed db: `count_accepted(<parent>/oa.sqlite) == 1` (independent SQLite count); (c) run `[venv_python, "-m", "work_runtime", "inspect", "--db", <migrate db>, "--work", "migrate", "--policy-versions", "demo-1,demo-2"]` outside the checkout → exit 0 and stdout contains `"policy_version": "demo-2"`; (d) console `work-runtime intervention-demo` outside the checkout → final line. Update the module docstring stage list and the PASS summary ("three demos … one external application per intervention store").
- [ ] **Step 2: Run the verifier locally** — `python3 scripts/verify_install.py` (needs pip index access for the build backend; if offline, record that the stage cannot run here and rely on CI + local venv-less evidence; report honestly). Expected: `=== PASS ===` with all three demos.
- [ ] **Step 3: Add the CI smoke line** — `.github/workflows/ci.yml`: `- run: python -m work_runtime intervention-demo` directly after `publish-demo`.
- [ ] **Step 4: Verify gates** — `python3 -m compileall -q work_runtime tests scripts`; full unittest discover still green; `python3 -m work_runtime intervention-demo` runs in the checkout.
- [ ] **Step 5: Commit** — `test(verify): installed intervention-demo verification and CI smoke`

### Task 5: Public docs — honest boundaries and coverage

**Files:**
- Modify: `README.md`, `README.zh-CN.md`, `CONTRIBUTING.md`, `docs/verification.md`, `docs/roadmap.md`

**Interfaces:**
- Consumes: actual demo output (Task 2 copy), actual test names, deferred-scope list from the spec (revocation, compensation, distributed leases/fencing, multi-tenant auth; local trust ≠ authentication; acknowledgement ≠ reversal; version registry with no implicit migration; owners/administrators are trusted local principals).

- [ ] **Step 1: README.md** — new section after the publish-demo section: "Watch interventions stop work without losing effects" with `python3 -m work_runtime intervention-demo`, the printed transcript, and the accountability notes (per-scenario stores, acknowledgement records the effect and is not compensation, `inspect --policy-versions` for the pinned store, local trust). Update "What works today" (intervention commands, explicit registry + migration, pinned-version inspect), "Verify a checkout" (add the demo line; verifier now covers three demos), and "Where this is going" (0.3 has a local slice: cancellation, transfer, explicit migration; compensation/revocation/distributed fencing remain open). Fix the "does not implement … cancellation" sentence.
- [ ] **Step 2: README.zh-CN.md** — mirror every README.md change in Chinese, keeping commands verbatim.
- [ ] **Step 3: CONTRIBUTING.md** — add `work_runtime/intervention_demo.py` and `tests/test_intervention_demo.py` to the structure table; add the demo to the local-setup block; update the verify_install sentence ("runs all three demos"); replace the "Cancellation and compensation" opportunity with compensation/evidence-revocation framing.
- [ ] **Step 4: docs/verification.md** — refresh the "Updated:" header; rewrite the "One policy per runtime database" scope bullet (explicit same-family registry, per-work pinned versions, explicit migration — no implicit upgrades, cross-domain registries unsupported); add an "S3 coverage — interventions and pinned policy versions" section listing the named evidence (`tests/test_interventions.py` behaviors from the foundation wave + `tests/test_intervention_demo.py` demo/CLI/verifier-facing tests, the CLI flag, the installed verifier) — explicitly *not* blanket-completing P01–P15; correct the stale "Explicitly out of scope" bullet that still claims `request_cancel` is rejected (it names `test_unsupported_command_explicitly_rejected`, whose probe is now `request_refund`); keep compensation, revocation, distributed fencing (P13), multi-tenant auth deferred.
- [ ] **Step 5: docs/roadmap.md** — under "0.3 — Change and intervention", add the same style of local-slice paragraph as 0.2 has: what S3 provides now (cancellation with exact acknowledgement, authority-aware transfer, explicit same-family migration) and what still owes (compensation execution, evidence revocation, distributed fencing, external review).
- [ ] **Step 6: Run gates** — `python3 scripts/check_docs.py` (0 broken), full unittest discover (docs contract test included).
- [ ] **Step 7: Commit** — `docs: intervention demo, pinned-version inspection and honest S3 coverage`

### Task 6: Report and final gates

**Files:**
- Create: `.agents/notes/2026-10-13-S3-intervention-demo-report.md`

- [ ] **Step 1: Run every configured gate** — `python3 scripts/check_docs.py`; `python3 -m unittest discover -s tests -v` (record exact new/full counts); `python3 -m work_runtime demo`; `python3 -m work_runtime publish-demo`; `python3 -m work_runtime intervention-demo`; `python3 -m compileall -q work_runtime tests scripts`; `python3 scripts/verify_install.py` (or the honest offline note); record outputs.
- [ ] **Step 2: Write the report** — commits table; exact RED/GREEN evidence per task (observed outputs); new-test count and full-suite count; gate results; verification-map coverage against the brief's scenarios; remaining risks/limits (no merge, no push; deferred items).
- [ ] **Step 3: Commit** — `docs: S3 wave-3 intervention demonstration report`
- [ ] **Step 4: Close out** — check the Orca inbox once more (`orca orchestration check`, no `--run`), then send `worker_done` with the 3-sentence summary, `--files-modified` and `--report-path`.
