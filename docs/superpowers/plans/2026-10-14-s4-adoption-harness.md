# S4 Adoption Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the S4 wave-3 adoption surface: a strict `lint-sop` CLI (file loader with D22 exit-2 rules), a no-credentials `adoption-demo` that drives the unchanged PublishingPolicy/Runtime with HMAC candidates and the real `FilePublisher` through a composition response-loss wrapper, packaged SOP resources shipped as package-data and read via `importlib.resources`, installed module AND console adoption verification, CI wiring, and the public contributor guide + docs.

**Architecture:** One new module `work_runtime/adoption_demo.py` owns the strict SOP file loader (`load_sop_file`/`load_sop_bytes`), packaged-card access (`packaged_card`), the JSON result builder (`lint_result`), the `ResponseLossPublisher` composition wrapper and `run_adoption_demo`. `work_runtime/cli.py` gains `lint-sop <path> [--json]` (exits 0/1/2) and `adoption-demo [--directory DIR]`. `pyproject.toml` ships `work_runtime/data/sop/*.json`; `scripts/verify_install.py` and `.github/workflows/ci.yml` verify installed adoption independently of printed text. Docs: new `docs/contributor-guide.md` plus README/README.zh-CN/CONTRIBUTING/verification/roadmap updates.

**Tech Stack:** Python >= 3.9 standard library only (`json` with `object_pairs_hook`/`parse_constant`, `importlib.resources`, `hashlib`, `sqlite3` for independent parses), `unittest`, real filesystem artifacts, fresh venv installs.

**Spec:** `docs/superpowers/specs/2026-10-13-s4-adoption-design.md` (Intent, "Static SOP authoring" CLI paragraph, "Dependent adoption harness", D22 addendum items on the CLI loader/packaged examples/installed adoption, and the graph-clarification note), `docs/superpowers/sprints/2026-10-13-S4-plan.md` Wave 3 + DoD, `docs/superpowers/plans/2026-10-13-s4-supervision.md` Task 5, `.agents/notes/2026-10-13-S4-foundation-integration.md` ("Delivered interfaces for wave 3"), `AGENTS.md`.

## Global Constraints

- Python 3.9.6 on this machine: no 3.10+ syntax; zero runtime dependencies; standard-library `unittest` only.
- Baseline: **469** tests green before and after (`273` pre-S4 baseline + `146` authoring + `50` file); no existing test file, no `work_runtime/authoring.py`, `file_adapter.py`, `runtime.py`, `policy.py`, `adapters.py`, `adapter_contract.py`, `ingress.py`, `__init__.py`, `__main__.py`, `demo.py`, `publishing_demo.py`, `intervention_demo.py` edits — foundation/lifecycle defects go to the coordinator through Orca, never fixed here.
- The three earlier demos keep working unchanged (`demo`, `publish-demo`, `intervention-demo`).
- Ownership (exact): `work_runtime/adoption_demo.py`, `work_runtime/cli.py`, `tests/test_adoption_demo.py`, `pyproject.toml` (package-data only), `scripts/verify_install.py`, `.github/workflows/ci.yml`, `docs/contributor-guide.md`, `README.md`, `README.zh-CN.md`, `CONTRIBUTING.md`, `docs/verification.md`, `docs/roadmap.md`, this plan, report in `.agents/notes/`. NOT `docs/superpowers/` sprint/roadmap/spec docs (master's).
- Work only on top of base `cc40ef0`; no rebase/merge/push, no nested agents, no local approval UI; Orca heartbeats while active; `orca orchestration check` before starting new files, after test runs, and before `worker_done`.
- Honest-language rules (D22 + AGENTS.md): lint is static-only (no textual-predicate execution, no publication/policy authority); no power-loss, hostile-filesystem/symlink, distributed exactly-once, or authentication claims; fresh temp stores per run; no credentials, no secrets echoed, no user data deleted.
- Coordinator follow-up msg_10f05ef4b0a8: lint JSON output must use safe escaping so INVALID_UNICODE diagnostics cannot crash stdout; test escaped-surrogate values AND keys (exit 1); loader invalid-UTF-8 bytes exit 2; installed module AND console adoption must independently parse/count the actual artifact (document/key/digest/receipt/Work success), no stdout-only PASS; the public guide must carry enough imports/commands for a docs-only rehearsal.

## Pinned contract (decisions the implementer cannot choose)

### Strict loader (D22)

- `lint-sop <path> [--json]` exits: **0** lint-clean, **1** lint diagnostics, **2** file-level/CLI usage errors.
- Loader exit-2 cases, each a stable code with bounded static message (no input content, no file path echoed in JSON output): `FILE_UNREADABLE` (OSError/IsADirectoryError/missing), `FILE_TOO_LARGE` (strictly more than 1 MiB = 1048576 bytes), `INVALID_UTF8`, `MALFORMED_JSON`, `DUPLICATE_OBJECT_KEY` (via `object_pairs_hook` sentinel), `NONFINITE_LITERAL` (`parse_constant` sentinel for `NaN`/`Infinity`/`-Infinity`), `DEEP_JSON` (`RecursionError` from `json.loads` caught, no traceback).
- Syntactically valid escaped surrogates (`"\ud800"`) pass the loader and surface as linter `INVALID_UNICODE` → exit 1.
- JSON mode prints `{"valid": bool, "digest": <sha256-hex>|null, "diagnostics": [...], "scope": "static-only"}` serialized with `ensure_ascii=True` (ASCII-safe for lone-surrogate paths/messages). Clean: `digest` = `authoring.sop_digest(value)`, `diagnostics: []`. Loader failure (exit 2) in JSON mode prints the same envelope with exactly one diagnostic `{code, path: "", message}`.
- Human mode: clean prints the digest and a static-only limitation line; defects print `code path message` lines; loader failures print one bounded line to stderr; every diagnostic line is surrogate-safe (`backslashreplace` on encode).
- `load_sop_bytes(raw: bytes) -> dict` raises `SopFileError(code, message)`; `load_sop_file(path) -> dict` reads bytes (cap applies) and delegates.

### Packaged resources (D22)

- `packaged_card(name: str) -> dict` reads `importlib.resources.files("work_runtime").joinpath("data", "sop", name)` bytes through `load_sop_bytes` (no repo-cwd dependency, no duplicate embedded example dicts).
- Pinned digests (foundation report): `expense.json` = `4876285f00f5f9ad0287e92825f1aec212e9fc3bce10fd8c073bd2151d817627`, `publishing.json` = `56c85d32da9a9eee6330326e2d14ce0661dbc26d782b13d0259c3f149e6be000`. A mismatch is a foundation defect → coordinator, not a local edit.
- `pyproject.toml` gains `[tool.setuptools.package-data] work_runtime = ["data/sop/*.json"]`.

### Adoption demo (design "Dependent adoption harness")

- `run_adoption_demo(directory=None) -> Path`; fresh `tempfile.mkdtemp(prefix="governed-adoption-", dir=directory)`; `runtime.sqlite` + `publisher/` artifact directory inside; no deletes.
- Prologue (static, printed as such): an intentionally invalid inline card (NOT a copy of any packaged example) → diagnostics; both packaged cards via `packaged_card` → lint-clean + exact digests; printed text states the Runtime executes the engineered `PublishingPolicy`, never the linted JSON.
- Live flow mirrors `publishing_demo.run_demo` (same `DEMO_NOW` clock, `secrets.token_bytes(32)` reviewer/author keys, `SignedEvidenceGateway`, `publishing_grants()`, work id `article-1`): blocked C02 proposal → tampered-approval `EVIDENCE_AUTHENTICATION_FAILED` with zero intake writes → valid signed candidates `pending_verification` → `verify_pending` → intent accepted.
- `ResponseLossPublisher(publisher)` composition wrapper: `self.contract = publisher.contract`, `execute` calls the real `FilePublisher.execute` then raises `TimeoutError("response lost after the real file commit")`; `lookup` delegates. `dispatch` → `outcome_unknown` while exactly one `^[0-9a-f]{64}\.json$` artifact exists on disk.
- Restart: fresh `Runtime` on the same database + plain `FilePublisher` on the same directory; `reconcile(operation_id, …)` → `confirmed_succeeded`, `attempts` length 1 (original key queried, nothing resent); then `request_completion` accepted → work `closed/succeeded`.
- Prints, all asserted: numbered steps; final line `committed file artifacts: 1`; then `python3 -m work_runtime inspect --db "<runtime>" --work article-1 --policy content-publish` and `committed artifact: "<path>"`.
- CLI: `adoption-demo` with optional `--directory` (an existing parent directory, same semantics as the other demos).

### Installed verification + CI

- `scripts/verify_install.py` new stages: (a) packaged resources resolve inside the venv (`os.fspath(importlib.resources.files("work_runtime"))` under the venv) and installed `work-runtime lint-sop` on an extracted copy of `publishing.json` prints the pinned digest; (b) module `adoption-demo` outside the checkout: final line present, printed artifact path + inspect command extracted, artifact directory independently enumerated (exactly 1 hash-named `.json`, no `.stage` leftovers), artifact independently parsed with stdlib only (exact 5 keys, `artifact_version` 1, nonempty key, recomputed `sha256(canonical json.dumps(document, sort_keys, compact separators, ensure_ascii=False, allow_nan=False)) == content_digest`, receipt exact 3 keys/accepted/`FILE-`-prefixed nonempty external_id/matching digest), runtime DB independently parsed via sqlite (`works` row `article-1` `status="closed"`, `outcome="succeeded"`; operation `confirmed_succeeded`), and the printed inspect command re-run verbatim (tokens with `python3` swapped for the venv interpreter) asserting `"outcome": "succeeded"`; (c) the same independent enumeration/parse for the console `work-runtime adoption-demo` entry point. No stdout-only PASS anywhere.
- CI: `python -m work_runtime adoption-demo`; extract the packaged `publishing.json` to a sample file and run `lint-sop` exit 0; `lint-sop examples/sop/rule-cycle.json` expecting exit 1 and a malformed-input case expecting exit 2 (`|| test $? -eq N`).

## Review Focus

1. Lone-surrogate strings in diagnostics (value AND object key) crashing stdout on encode — exit-1 JSON and human output must stay printable (`ensure_ascii=True`; `backslashreplace` for human lines); pinned by Task 2 surrogate tests.
2. Duplicate JSON object keys silently accepted (last-wins) — loader must exit 2 without echoing the doomed values; pinned by Task 2 duplicate-key + secret-echo tests.
3. Deeply nested JSON producing a raw `RecursionError` traceback or a hang — caught, exit 2 `DEEP_JSON`; >1 MiB files rejected before reading fully; pinned by Task 2 boundary tests.
4. Adoption verification trusting the demo's own printed claim — verify_install must enumerate/parse the artifact, receipt, digest and Work state independently of stdout; pinned by Task 4 fresh-venv stages (and the packaged-resource RED before package-data).
5. Response loss simulated by stubbing the adapter or editing lifecycle — wrapper must compose the REAL `FilePublisher` (artifact bytes on disk after the loss), restart reconciles the original key; pinned by Task 3 wrapper + demo tests.

---

### Task 1: Baseline and plan

**Files:** Create: this plan.
- [ ] Step 1: Record baseline on `cc40ef0`: `python3 -m unittest discover -s tests` → expect `Ran 469 tests … OK`; `python3 scripts/check_docs.py` → 0 broken; `python3 -m work_runtime demo` / `publish-demo` / `intervention-demo` → exit 0; `python3 -m compileall -q work_runtime tests scripts` clean; `python3 --version`.
- [ ] Step 2: Commit plan: `docs(plan): scoped S4 adoption harness plan`.

### Task 2: Strict loader, packaged resources, `lint-sop` CLI (RED → GREEN)

**Files:** Create `work_runtime/adoption_demo.py`, `tests/test_adoption_demo.py`; modify `work_runtime/cli.py`.
**Interfaces:** Produces `load_sop_bytes(raw) -> dict` / `load_sop_file(path) -> dict` raising `SopFileError(code, message)`; `packaged_card(name) -> dict`; `lint_result(value) -> dict`; `run_lint_sop(argv) -> int` (exit code; CLI prints); consumed by Tasks 3–4.

- [ ] Step 1: Write failing tests — classes `LintCleanTests` (packaged `expense.json`/`publishing.json` written to temp files: `--json` exit 0 with exact envelope and pinned digests; human mode exit 0 prints digest + static-only line), `LintDefectTests` (a defect card → exit 1, `valid:false`, `digest:null`, diagnostics sorted `{code,path,message}`; escaped-surrogate VALUE and KEY in otherwise-valid JSON text → exit 1 `INVALID_UNICODE` with stdout JSON-parseable and safe), `LoaderExit2Tests` (duplicate top-level and nested keys, `NaN`/`Infinity` literal, malformed JSON, invalid UTF-8 bytes, missing file, directory-as-file, >1 MiB file, ~20000-deep nesting → exit 2 with the mapped code, no traceback; exactly-1048576-byte valid JSON loads), `SecretEchoTests` (marker strings in duplicate-key/malformed files never appear in stdout+stderr), `PackagedResourceTests` (both cards lint-clean with pinned digests; resource traversable is a file under the package), `LintCliUsageTests` (missing path → argparse exit 2).
- [ ] Step 2: RED — `python3 -m unittest tests.test_adoption_demo -v` → module/file import failure. Record verbatim.
- [ ] Step 3: Implement `work_runtime/adoption_demo.py` loader/resources/result and `cli.py` `lint-sop` per Pinned contract (sentinel exception inside `object_pairs_hook`/`parse_constant`; size check before decode; `ensure_ascii=True` JSON envelope; surrogate-safe human printer).
- [ ] Step 4: GREEN — new module passes; full suite `python3 -m unittest discover -s tests` → 469 + new, OK.
- [ ] Step 5: Commit — `feat(adoption): strict lint-sop CLI loader and packaged SOP resources`.

### Task 3: Adoption demo + response-loss wrapper + CLI (RED → GREEN)

**Files:** Modify `work_runtime/adoption_demo.py`, `work_runtime/cli.py`, `tests/test_adoption_demo.py`.
**Interfaces:** Consumes Task 2 loader/`packaged_card`, unchanged `PublishingPolicy`/`Runtime`/`SignedEvidenceGateway`/`FilePublisher`. Produces `ResponseLossPublisher`, `run_adoption_demo(directory=None) -> Path`, CLI `adoption-demo [--directory DIR]`.

- [ ] Step 1: Write failing tests — `ResponseLossWrapperTests` (real `FilePublisher` on a temp dir: `execute` raises `TimeoutError` after exactly one hash-named artifact exists; `lookup` returns the validated receipt; `contract` is the delegate's contract), `AdoptionDemoTests` (run with captured stdout: final line `committed file artifacts: 1`; publisher dir holds exactly 1 `^[0-9a-f]{64}\.json$`, artifact exact 5 keys/`artifact_version` 1/key == operation business key/document == the demo article/`content_digest == policy.digest(article)`/receipt accepted `FILE-`+32 hex; `Runtime` reopen: work `article-1` `closed/succeeded`, operation `confirmed_succeeded` with 1 attempt; printed inspect command runs verbatim via `shlex` + `sys.executable` and reports the work; printed artifact path exists and is the committed file; prologue prints both pinned digests and a static-only/"not executed by the Runtime" line), `AdoptionDemoHygieneTests` (sentinel file in the parent directory survives; two runs → two distinct folders each with exactly 1 artifact; demo runs with cwd outside the repo), `AdoptionCliTests` (`cli.main(["adoption-demo", "--directory", tmp])` completes; unknown `lint-sop` extra args rejected).
- [ ] Step 2: RED — new classes fail (`AttributeError: module 'work_runtime.adoption_demo' has no attribute 'run_adoption_demo'` / CLI parse error). Record verbatim.
- [ ] Step 3: Implement `run_adoption_demo` + `ResponseLossPublisher` + CLI wiring per Pinned contract.
- [ ] Step 4: GREEN — module passes; full suite OK; `python3 -m work_runtime adoption-demo` runs green from the checkout, `python3 -m work_runtime lint-sop` re-checked.
- [ ] Step 5: Commit — `feat(adoption): FilePublisher adoption demo with response-loss recovery`.

### Task 4: package-data + installed verification + CI (RED → GREEN)

**Files:** Modify `pyproject.toml`, `scripts/verify_install.py`, `.github/workflows/ci.yml`.
**Interfaces:** Consumes Task 2–3 surfaces. Produces the fresh-venv installed proof (module AND console) and CI stages.

- [ ] Step 1: RED — fresh venv: `pip install <repo>` then `python -c "import importlib.resources as r; r.files('work_runtime').joinpath('data','sop','publishing.json').read_bytes()"` from outside the checkout → `FileNotFoundError` (resource not shipped). Record verbatim.
- [ ] Step 2: Add `[tool.setuptools.package-data]` and the verify_install adoption stages + CI steps per Pinned contract (docstring stage list updated).
- [ ] Step 3: GREEN — `python3 scripts/verify_install.py` full run passes (all stages incl. installed lint-sop pinned digest, module and console adoption with independent parse/count); repeat resource probe → bytes read. Record stage output.
- [ ] Step 4: Commit — `build(adoption): package SOP data; installed module+console adoption verification`.

### Task 5: Contributor guide + public docs (doc gate)

**Files:** Create `docs/contributor-guide.md`; modify `README.md`, `README.zh-CN.md`, `CONTRIBUTING.md`, `docs/verification.md`, `docs/roadmap.md`.
**Interfaces:** Consumes Tasks 2–4 surfaces; the guide is the sole product-side input for the later guide-only rehearsal (public docs only).

- [ ] Step 1: Write `docs/contributor-guide.md`: boundaries (static lint ≠ executable authority; trusted-local; no power-loss/hostile-FS/symlink/distributed/auth claims); adapter tutorial with exact imports (`work_runtime.adapter_contract.AdapterContract`, `work_runtime.policy.digest`, `tests.adapter_conformance.AdapterConformanceMixin`), the four fixture hooks, a complete worked minimal adapter, run commands; metadata/platform limits; SOP authoring workflow (`lint-sop` exits/JSON envelope, packaged examples via `importlib.resources`, digest meaning, 14-code pointer to `docs/sop-authoring.md`); adoption harness walkthrough; honest limits section.
- [ ] Step 2: Update README (adoption section + expected output block, gates list, verify_install description, "What works today" bullets), README.zh-CN (mirror), CONTRIBUTING (structure-table rows, setup commands, adapter pointer to the guide), `docs/verification.md` (S4 coverage section: lint/digest, FilePublisher conformance/races boundaries, adoption harness + installed module/console verification; out-of-scope additions), `docs/roadmap.md` (0.2 S4 slice note incl. agent-rehearsal-vs-human-feedback distinction).
- [ ] Step 3: Gates — `python3 scripts/check_docs.py` → 0 broken; full suite OK; all 4 demos green.
- [ ] Step 4: Commit — `docs(adoption): contributor guide and public adoption docs`.

### Task 6: Full evidence, report, final checkpoint

**Files:** Create `.agents/notes/2026-10-14-S4-adoption-harness-report.md`.
- [ ] Step 1: Full gates + all four demos + fresh `python3 scripts/verify_install.py`; capture exact counts, exits, entrypoints, file list, commit SHAs, limits.
- [ ] Step 2: Write the report (RED/GREEN evidence verbatim per task, test counts, files, SHAs, pinned digests, boundaries, remaining risks).
- [ ] Step 3: Inbox check; commit report `docs(adoption): S4 adoption harness report`; single `worker_done` with 3-sentence summary.
