# S1 Contributor Wave — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the S1 contributor-preview checkout verifiable: a stdlib local-Markdown-link checker (contracts gate), a fresh-venv out-of-repo install verification script, and an honest P01–P15 RFC coverage matrix wired into README/CONTRIBUTING/CI.

**Architecture:** Two standalone stdlib scripts under `scripts/` plus one new unittest module. `check_docs.py` exposes a small library core (`extract_links`, `check`) and a CLI used as the AGENTS.md `contracts` gate. `verify_install.py` is an executable acceptance check (no unittest — its execution IS the test, per ownership scope `tests/test_docs.py` only). Doc edits annotate status and link RFCs to the coverage matrix; no runtime/policy/sprint file is touched.

**Tech Stack:** Python >=3.9 standard library only (unittest, argparse, pathlib, re, urllib.parse, sqlite3, json, venv, subprocess, tempfile, shutil). Zero runtime dependencies.

**Spec:** [S1 sprint plan](../../docs/superpowers/sprints/2026-10-13-S1-plan.md) · [E1 roadmap](../../docs/superpowers/roadmaps/2026-10-13-open-source-preview.md) · [AGENTS.md](../../AGENTS.md) (gates, doc_sync_map, ownership) · [S1-open handover](2026-10-13-S1-open.md) (contributor ownership) · [RFC-003 §9–10](../../docs/RFC-003-runtime-protocol.md) (P01–P15 definitions and prototype-scope caveat).

## Global Constraints

- Python >=3.9, zero runtime dependencies, standard-library `unittest` only (AGENTS.md).
- Ownership (S1-open note + dispatch brief): only `scripts/check_docs.py`, `scripts/verify_install.py`, `tests/test_docs.py`, `README.md`, `README.zh-CN.md`, `CONTRIBUTING.md`, `docs/verification.md`, RFC **status annotations only**, `docs/reference-scenarios.md`, packaging/CI if needed, this plan and its report. Never touch `work_runtime/*`, `tests/test_runtime.py`, `docs/runtime-boundaries.md`, sprint/epic/roadmap docs, `.agents/notes/*` other than own uniquely named plan/report.
- doc_sync_map: any `scripts/check_docs.py` change ships **in the same commit** as its owed `CONTRIBUTING.md` change.
- No merge, no push (integration session owns those). Commit hashes reported in the report.
- Honesty rules: P13 (distributed worker leases) explicitly deferred; no remote-authentication or blanket RFC-coverage claims; local principal names are not authentication.
- The link `docs/runtime-boundaries.md` inside `docs/verification.md` is a known **temporary cross-worker condition**: it stays red in this worktree and resolves when the parallel runtime worker's branch lands at integration. Recorded, not hidden.
- `idea.md` and `上一次建议.md` are historical source material (AGENTS.md): excluded as link *sources*; links *targeting* them are still validated.

## Review Focus

Input classes / failure modes the brief implies but task tests must be pinned against:

1. **Checker exits 0 while reporting broken links** — CLI must exit non-zero on any finding (pinned in Task 1 CLI tests).
2. **Link-like text inside fences/inline code counted as links** — would false-red the gate (pinned: fence + inline-code tests, incl. indented fence).
3. **Post-install artifact dirs (`build/`, `*.egg-info`) scanned as doc sources** — would make the gate nondeterministic after `verify_install` runs (pinned: excluded-dir test).
4. **`verify_install` importing the package from the checkout instead of the venv** — would fake a passing install (pinned: `work_runtime.__file__` origin assertion + cwd outside repo).
5. **Installation failures swallowed** — pip/venv/demo non-zero exits must fail the script loudly with full output (pinned: every stage checks returncode; no `check=False` without handling).
6. **Trusting the printed "external applications created: 1" line only** — count accepted receipts directly in the demo's OA SQLite file (pinned in Task 4 module-demo stage).

---

### Task 0: Commit this plan

**Files:**
- Create: `.agents/notes/2026-10-13-S1-contributor-plan.md` (this file)

- [x] **Step 1: Save plan and commit**

```bash
git add .agents/notes/2026-10-13-S1-contributor-plan.md
git commit -m "docs(plan): scoped S1 contributor plan for docs/install verification"
```

### Task 1: Markdown link checker (TDD)

**Files:**
- Create: `scripts/check_docs.py`
- Create: `tests/test_docs.py`
- Modify: `CONTRIBUTING.md` (contracts gate + structure rows — same commit per doc_sync_map)

**Interfaces:**
- Produces (library core in `scripts/check_docs.py`, loaded by tests via `importlib.util.spec_from_file_location`):
  - `Link = NamedTuple("Link", [("file", str), ("line", int), ("target", str)])` — `target` is the cleaned local target (fragment stripped, percent-decoded).
  - `extract_links(text: str) -> List[Link]` — inline links/images `[t](url "title")`/`![a](src)`, explicit reference links `[t][ref]` + `[ref]: url` definitions (labels case-insensitive); skips fenced code blocks (``` or ~~~, ≤3-space indent) and inline code spans; `file` is `"-"` (filled by caller).
  - `is_local_target(raw: str) -> bool` — False for `scheme:` URLs (covers http/https/mailto) and pure `#anchor`/empty targets.
  - `check(root: Path, sources: Optional[List[Path]] = None) -> Tuple[int, int, List[Tuple[Path, int, str]]]` — returns `(files_checked, local_links, findings)`; finding = `(source_file, line, raw_target)` when the resolved path (relative to the source's directory; leading `/` resolves against `root`) does not exist. Default sources: `*.md` under `root`, excluding `EXCLUDED_DIRS = {".git", ".agents", ".claude", ".venv", "__pycache__", "build", "dist"}` + any `*.egg-info`, and `EXCLUDED_FILES = {"idea.md", "上一次建议.md"}`.
  - `main(argv: List[str]) -> int` — `[--root PATH] [paths...]`; prints `broken link: <relpath>:<line> -> <target>` per finding, then `checked N markdown files, M local links, K broken`; exit 1 iff K > 0.

- [ ] **Step 1: Write failing tests** in `tests/test_docs.py` (loader + hermetic tmp-tree fixtures): `test_valid_links_pass` (relative, `../`, percent-encoded `sp%20ace.md` → `sp ace.md`, link to directory), `test_broken_link_reported_with_location` (finding carries file/line/target), `test_external_urls_and_mailto_skipped`, `test_pure_anchor_links_skipped`, `test_fragment_targets_check_file_only` (`missing.md#frag` → finding; `exists.md#frag` → clean), `test_fenced_code_blocks_skipped` (``` and ~~~, indented fence, link after closing fence still checked), `test_inline_code_spans_skipped`, `test_reference_links_checked` (broken + valid + case-insensitive label), `test_images_checked`, `test_leading_slash_resolves_from_root`, `test_excluded_sources_are_not_checked` (`idea.md`, `.agents/n.md`, `build/b.md`, `pkg.egg-info/e.md` with broken links → ignored; `docs/bad.md` → checked), `test_cli_clean_tree_exits_zero`, `test_cli_broken_link_exits_one_and_prints` (subprocess `[sys.executable, scripts/check_docs.py, "--root", tmp]`).
- [ ] **Step 2: Run to observe RED** — `python3 -m unittest tests.test_docs -v` → all ERROR/FAIL: `scripts/check_docs.py` does not exist (FileNotFoundError on module load). Record output.
- [ ] **Step 3: Implement `scripts/check_docs.py`** minimally to the interfaces above (module docstring documents scope + exclusions; regex-based extraction; `urllib.parse.unquote`; `Path.exists()` resolution).
- [ ] **Step 4: Run to observe GREEN** — `python3 -m unittest tests.test_docs -v` → all new tests OK; full suite `python3 -m unittest discover -s tests -q` → 35 + new, OK. Note: repo-wide `python3 scripts/check_docs.py` is still red here (README → missing `docs/verification.md`) — expected until Task 3.
- [ ] **Step 5: Update `CONTRIBUTING.md`** — add `python3 scripts/check_docs.py` to local setup, add `scripts/`, `tests/test_docs.py`, `docs/verification.md` rows to the structure table, one PR-checklist line.
- [ ] **Step 6: Commit** `scripts/check_docs.py tests/test_docs.py CONTRIBUTING.md` — `feat(docs): stdlib Markdown link checker as contracts gate`.

### Task 2: Coverage matrix + RFC status annotations (TDD at repo level)

**Files:**
- Create: `docs/verification.md`
- Modify: `docs/RFC-001-core-semantics.md`, `docs/RFC-002-sop-authoring-and-binding.md`, `docs/RFC-003-runtime-protocol.md` (status banner only, after the 版本 line; RFC-003 also one pointer line at §9)
- Modify: `docs/reference-scenarios.md` (status line: subset implemented, link matrix)
- Modify: `tests/test_docs.py` (repo contract test)

**Interfaces:**
- Consumes: `check_docs.check` from Task 1; the 35 named runtime tests in `tests/test_runtime.py`.

- [ ] **Step 1: Write failing repo-contract test** `test_repo_docs_no_unexpected_broken_links`: `check(REPO_ROOT)` findings must all be `(docs/verification.md, *, "runtime-boundaries.md")` — the recorded temporary cross-worker link. RED now: README's `docs/verification.md` links are also broken (file absent).
- [ ] **Step 2: Observe RED** — `python3 -m unittest tests.test_docs -v` → the new test FAILs listing README broken links.
- [ ] **Step 3: Write `docs/verification.md`** — (a) scope statement: local single-process reference prototype, in-process trusted library, principal names ≠ authentication, FakeOA is a local SQLite stand-in; (b) how verification runs (4 gate commands + `python3 scripts/verify_install.py`); (c) P01–P15 table with per-case status + named tests from the existing 35: P01 `test_duplicate_commands_concurrently_have_one_receipt`; P02 `test_changed_content_with_same_command_id_rejected`; P03 `test_conflicting_plan_revisions_use_compare_and_swap`; P04 `test_duplicate_commands_concurrently_have_one_receipt` + `test_rejected_command_replay_remains_rejected` (transport loss simulated by re-invocation); P05 `test_new_command_same_business_operation_reuses_identity`; P06 `test_prepared_intent_survives_restart` (clean restart, not crash-at-point; real deaths are injected for P07/P15); P07 `test_actual_process_crash_after_external_commit`; P08 `test_early_approval_and_duplicate_callback_do_not_lose_wakeup`; P09 `test_conflicting_source_event_preserves_original` + `test_late_event_does_not_reopen_closed_work`; P10 `test_missing_approval_cannot_be_deleted_with_plan`; P11 `test_authority_revoked_before_dispatch_holds_intent`; P12 `test_completion_needs_business_evidence` + `test_timeout_after_commit_then_reconcile`; **P13 deferred — single coordinator, no distributed leases, no distributed exactly-once claim**; P14 `test_unknown_amount_blocks` + `test_empty_and_unsealed_invoice_sets_block`; P15 `test_verification_crash_rolls_back_adoption_and_evaluation` + `test_real_process_death_during_evidence_adoption`; (d) R1–R7 brief cross-reference; (e) E01–E08/T01–T12 note (demo policy embodies E01–E08; T-cases partially mirrored, listed); (f) limitations list; (g) link to `docs/runtime-boundaries.md` with note it lands with the parallel S1 runtime work.
- [ ] **Step 4: Annotate RFCs + reference-scenarios** — one-line status banners linking `[验证覆盖](verification.md)`; reference-scenarios status line updated from "尚未实现" to subset-implemented with link.
- [ ] **Step 5: Observe GREEN** — `python3 -m unittest tests.test_docs -v` all OK (repo findings == exactly the pending boundary link); `python3 scripts/check_docs.py` exits 1 with only `docs/verification.md -> runtime-boundaries.md` (recorded as the temporary owned boundary link).
- [ ] **Step 6: Commit** — `docs(verification): honest P01–P15 coverage matrix and RFC status links`.

### Task 3: Fresh-venv install verification script

**Files:**
- Create: `scripts/verify_install.py`

**Interfaces:**
- Produces: CLI `python3 scripts/verify_install.py [--python INTERP] [--repo PATH] [--keep]` → exit 0 only if every stage passes; stages printed with headers; failures print full subprocess output then exit non-zero. Helper `count_accepted(oa_db: str) -> int` (SQLite receipts with `json.loads(result)["status"] == "accepted"`).

- [ ] **Step 1: Implement** — fresh `venv` under `tempfile.mkdtemp(prefix="gwr-verify-install-")`; real (non-editable) `pip install <repo>` with returncode checked (retry once with `--no-build-isolation` only if the isolated build failed on index/network access, decision recorded in output); origin assertion `work_runtime.__file__` resolves under the venv, run with cwd outside the repo; dependency audit `pip list --format=freeze` ⊆ {pip, setuptools, wheel, governed-work-runtime}; module demo `python -m work_runtime demo` and console demo `work-runtime demo` with cwd outside repo, returncode 0 and stdout containing `external applications created: 1`; independent count via `--db "..."` regex → sibling `oa.sqlite` → `count_accepted == 1`; cleanup unless `--keep`.
- [ ] **Step 2: Run and record evidence** — `python3 scripts/verify_install.py` → PASS with stage output (record interpreter + pip versions, elapsed). Any failure → fix script or packaging, never the assertion.
- [ ] **Step 3: Commit** — `feat(scripts): fresh-venv out-of-repo install and demo verification`.

### Task 4: Contributor docs + CI mirroring

**Files:**
- Modify: `README.md`, `README.zh-CN.md` (verify-checkout command block incl. both scripts; claims aligned with matrix)
- Modify: `CONTRIBUTING.md` (verify_install in setup; PR checklist gains contracts gate + optional install check)
- Modify: `.github/workflows/ci.yml` (per-job: `python scripts/check_docs.py`, `python -m compileall -q work_runtime tests scripts`, `python scripts/verify_install.py` added around existing steps)

- [ ] **Step 1: Edit the three files** as above; keep matrix wording ("P13 deferred", "local trust") consistent with `docs/verification.md`.
- [ ] **Step 2: Verify gates** — `python3 -m unittest discover -s tests -q` OK; `python3 scripts/check_docs.py` still exactly the one pending boundary link; `python3 -m compileall -q work_runtime tests scripts` OK; `python -c "import yaml"` not required — CI YAML validated by `python3 -c "import ast"`-level syntax? No: validate by re-reading; CI run itself is integration's evidence. Note as caveat.
- [ ] **Step 3: Commit** — `docs(readme): contributor verification commands and mirrored CI gates`.

### Task 5: Final gates, report, closing commit

**Files:**
- Create: `.agents/notes/2026-10-13-S1-contributor-report.md`

- [ ] **Step 1: Run every gate fresh** and capture output: tests (with names/count), contracts (temporary boundary red recorded), demo, syntax, `scripts/verify_install.py`.
- [ ] **Step 2: Write report** — RED/GREEN evidence (commands + observed output), commit hashes, test names, caveats (pip build isolation network note, CI not executed locally, cross-worker link pending, verify_install not under unittest per ownership), remaining risks.
- [ ] **Step 3: Commit** — `docs(report): S1 contributor wave report with RED/GREEN evidence`.
- [ ] **Step 4: `orca orchestration check` then `worker_done`** with 3-sentence body, files-modified list, report path; then idle.

## Self-Review

- Spec coverage: brief items → checker+tests (T1), verification matrix + RFC links + P13 deferral + no overclaims (T2), fresh-venv/outside-repo/one-application assertions + reproducibility (T3), README/CONTRIBUTING/CI (T4), evidence+report+worker_done (T5). doc_sync_map honored (T1 same-commit CONTRIBUTING). ✔
- Steps decide file paths, names, signatures, exact test names, commit messages; no TBDs. ✔
- Type consistency: `check()` returns `(int, int, List[Tuple[Path, int, str]])` used that way by tests; `Link` fields consistent. ✔
- Review Focus lines each pinned to a task test or script assertion (1→T1 CLI tests, 2→T1 fence/code tests, 3→T1 exclusion test, 4/5/6→T3 stages). ✔
- Proportion: plan ≈ spec-appropriate; no function bodies transcribed. ✔
