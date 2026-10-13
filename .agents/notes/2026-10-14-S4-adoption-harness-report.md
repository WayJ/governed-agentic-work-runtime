# S4 adoption harness report — 2026-10-14

Wave 3 (dependent adoption harness). Worker: `s4-adoption-harness` (Claude Code,
Orca dispatch task_c471e48dc120). Base: `cc40ef0` (independently reviewed carrier,
469 tests) — worked isolated on top, no rebase/merge, per coordinator msg_10f05ef4b0a8.
Spec: [S4 design + D22](../../docs/superpowers/specs/2026-10-13-s4-adoption-design.md)
("Static SOP authoring" CLI paragraph, "Dependent adoption harness", D22 loader /
packaged-example / installed-adoption items), [sprint S4](../../docs/superpowers/sprints/2026-10-13-S4-plan.md)
Wave 3 + DoD, [supervision Task 5](../../docs/superpowers/plans/2026-10-13-s4-supervision.md),
[foundation interfaces](2026-10-13-S4-foundation-integration.md). Plan:
[2026-10-14-s4-adoption-harness.md](../../docs/superpowers/plans/2026-10-14-s4-adoption-harness.md).

## Commits (base cc40ef0 → tip)

| sha | subject |
|---|---|
| `30db084` | docs(plan): scoped S4 adoption harness plan |
| `07a7d20` | feat(adoption): strict lint-sop CLI loader and packaged SOP resources |
| `8cb4e57` | feat(adoption): FilePublisher adoption demo with response-loss recovery |
| `5692846` | build(adoption): package SOP data; installed module+console adoption verification |
| `39e62ae` | docs(adoption): contributor guide and public adoption docs |
| `d894e95` | test(adoption): pin overflowing-number-literal boundary (review finding) |

Owned files actually changed: `work_runtime/adoption_demo.py` (new, 402 lines),
`work_runtime/cli.py` (+15), `tests/test_adoption_demo.py` (new, 43 tests),
`pyproject.toml` (package-data), `scripts/verify_install.py` (3 new stages +
helpers), `.github/workflows/ci.yml` (+5 steps), `docs/contributor-guide.md` (new),
`README.md`, `README.zh-CN.md`, `CONTRIBUTING.md`, `docs/verification.md`,
`docs/roadmap.md`, own plan + this report. **Boundary audit:**
`git diff --stat cc40ef0..HEAD` over runtime.py / policy.py / adapters.py /
adapter_contract.py / ingress.py / authoring.py / file_adapter.py / __init__.py /
__main__.py / the three existing demos / every existing test file / scripts/check_docs.py /
sprint+roadmap+spec docs is **empty** (only my own plan file under
docs/superpowers/plans/ appears).

## RED → GREEN evidence (observed verbatim)

1. **Loader + lint-sop CLI** — RED: `python3 -m unittest tests.test_adoption_demo -v`
   → `ModuleNotFoundError: No module named 'work_runtime.adoption_demo'` (1 error).
   GREEN after implementing `adoption_demo.py` + `cli.py` wiring: 27/27 OK;
   full suite `Ran 496 tests ... OK`.
2. **Adoption demo + wrapper** — RED: `ImportError: cannot import name
   'ResponseLossPublisher' from 'work_runtime.adoption_demo'`. GREEN: 42/42 OK;
   full suite `Ran 511 tests ... OK`; `python3 -m work_runtime adoption-demo` exit 0.
3. **package-data / installed verification** — RED: fresh venv
   (`python3 -m venv`, `pip install <repo>`, cwd outside checkout, PYTHONPATH
   stripped): `FileNotFoundError: [Errno 2] No such file or directory:
   '.../venv/lib/python3.9/site-packages/work_runtime/data/sop/publishing.json'`.
   GREEN: full `python3 scripts/verify_install.py` → `=== PASS ===` exit 0
   (first run 6.0s, final re-run 13.8s) with all 13 stages.
4. **Review boundary pin** — `1e999` overflow literal probed: exit 1
   `NONFINITE_FLOAT` at `/policy/note` (well-formed file ⇒ value diagnosis;
   non-JSON `NaN`/`Infinity` tokens stay exit 2). Pinned by
   `test_overflowing_number_literal_is_a_value_diagnostic_not_a_file_error`
   (passed immediately — a pin of correct behavior found in self-review, not a
   defect fix; honestly recorded as such).

## Final evidence (tip d894e95, Python 3.9.6, darwin)

- `python3 -m unittest discover -s tests -v` → **`Ran 512 tests ... OK`**
  (469 carrier baseline — 273 pre-S4 + 146 authoring + 50 file — + 43 new in
  `tests/test_adoption_demo.py`; no existing test edited).
- `python3 scripts/check_docs.py` → `checked 47 markdown files, 166 local links,
  0 broken`.
- `python3 -m compileall -q work_runtime tests scripts` → clean.
- Demos: `demo`, `publish-demo`, `intervention-demo`, `adoption-demo` → all
  exit 0 (the three earlier demos byte-identical behavior; adoption demo run
  repeatedly, deterministic apart from fresh temp paths and random HMAC keys).
- `python3 scripts/verify_install.py` → exit 0, 13 stages: fresh venv; real
  non-editable install; import origin inside venv; zero third-party deps;
  module demo/publish/intervention outside checkout with independent counts;
  installed `inspect --policy-versions`; console demo/intervention;
  **packaged SOP resources resolve inside the venv and installed `lint-sop`
  reproduces the pinned digest**; **module `adoption-demo`** and **console
  `adoption-demo`** outside the checkout, each independently: exactly one
  hash-named `^[0-9a-f]{64}\.json$` artifact (zero `.stage` leftovers),
  artifact parsed with stdlib only (exact 5 keys, `artifact_version` 1, nonempty
  key == the operation's business key, recomputed
  sha256(canonical(document)) == content_digest, accepted `FILE-` receipt with
  matching digest), runtime DB read directly (work `article-1` closed/succeeded,
  one operation confirmed_succeeded), and the printed `inspect` command re-run
  verbatim (`python3` swapped for the venv interpreter).
- CI additions (not yet run on a remote runner — wave 4 owns push/CI):
  `python -m work_runtime adoption-demo`; packaged-card extraction +
  `lint-sop` exit 0; `lint-sop examples/sop/rule-cycle.json` expecting exit 1;
  malformed file expecting exit 2 — the trio replayed locally with exits 0/1/2.

## Delivered surfaces

- **CLI** `lint-sop <path> [--json]` (module and `work-runtime` console):
  exit 0 clean / 1 lint diagnostics / 2 file-level or usage error. Loader
  exit-2 codes: FILE_UNREADABLE, FILE_TOO_LARGE (>1 MiB strictly; exactly 1 MiB
  still loads), INVALID_UTF8, MALFORMED_JSON, DUPLICATE_OBJECT_KEY (top-level
  and nested, via `object_pairs_hook` sentinel), NONFINITE_LITERAL
  (NaN/Infinity/-Infinity tokens via `parse_constant`; a finite `1e999` literal
  is a linter NONFINITE_FLOAT exit 1 at its pointer), DEEP_JSON (RecursionError
  caught, no traceback). Messages are static; secret/marker echo tests prove no
  content leakage. `--json` envelope exactly
  `{valid, digest, diagnostics, scope:"static-only"}` serialized
  `ensure_ascii=True` so lone-surrogate diagnostics can never crash stdout
  (coordinator msg_10f05ef4b0a8); human lines go through `backslashreplace`.
  Escaped-surrogate values AND keys tested for both output modes (exit 1).
- **CLI** `adoption-demo [--directory DIR]` (optional existing parent directory,
  same semantics as the other demos). Prologue: inline invalid card (3
  diagnostics, not a copy of any packaged example) + both packaged cards clean
  via `packaged_card` with pinned digests — expense
  `4876285f00f5f9ad0287e92825f1aec212e9fc3bce10fd8c073bd2151d817627`, publishing
  `56c85d32da9a9eee6330326e2d14ce0661dbc26d782b13d0259c3f149e6be000`, plus the
  printed statement that the Runtime executes the engineered PublishingPolicy
  and the linted JSON is not executed. Live: blocked C02 → tampered-approval
  EVIDENCE_AUTHENTICATION_FAILED with zero intake writes → HMAC candidates
  pending until `verify_pending` → intent accepted → **real `FilePublisher`
  commit through `ResponseLossPublisher`** (composition wrapper: delegates the
  commit, surfaces the delegate's contract, raises TimeoutError only after the
  durable artifact) → outcome_unknown with exactly one hash-named artifact on
  disk → restart + reconcile original business key → confirmed_succeeded, one
  attempt, nothing resent → request_completion → work closed/succeeded; final
  line `committed file artifacts: 1`; printed `inspect` command and
  `committed artifact: "<path>"` both work verbatim. Deterministic artifact
  name across runs: `224f22546e52bbaefe9287a6554a309e61cd9030ccbc54918c1a6f43d28e4bae.json`
  (sha256 of the stable business key). Fresh `mkdtemp` stores per run; no
  credentials; no user data deleted (sentinel test); runs with cwd outside the
  repo (no repo-cwd dependency — resources via `importlib.resources.files`).
- **Packaging**: `[tool.setuptools.package-data] work_runtime = ["data/sop/*.json"]`;
  valid example cards remain the authoring foundation's single source.
- **Docs**: `docs/contributor-guide.md` — boundaries, adapter protocol +
  AdapterContract, a worked minimal adapter **whose code was verified verbatim
  against `AdapterConformanceMixin` (5/5) in a disposable scratch and then
  removed from the repo**, the four fixture hooks, Runtime treatment of
  adapters, SOP authoring workflow (importlib read of packaged cards, lint-sop
  exits/envelope, digest meaning, static-only boundary), adoption walkthrough,
  consolidated "what we do not claim". Public docs updated (README, README.zh-CN,
  CONTRIBUTING, verification.md S4 section + scope/out-of-scope, roadmap 0.2/0.4
  notes). Guide-only rehearsal is a separate later wave (Task 6); nothing here
  claims human feedback.

## Honest limits / remaining risks

- The guide's teaching adapter deliberately uses a simplified commit
  (`os.replace`, no fsync); the guide says so explicitly and points to
  `FilePublisher`'s atomic strategy. It is documentation, not shipped code.
- Lint JSON output safety is defense-in-depth: with the current foundation,
  diagnostics from parsed JSON carry static ASCII paths/messages (preflight
  reports key-level surrogate faults at the container path); the ASCII envelope
  and `backslashreplace` guarantee printability even if that ever changes.
- CI steps are committed but not yet executed on a remote runner (wave 4:
  merge/push/actual CI). `verify_install` was run fresh locally twice.
- Demo temp folders are intentionally kept for inspection (consistent with the
  three existing demos); on long-lived machines they accumulate like the others.
- Self-review only for this branch's final review (dispatch prohibits nested
  agents); independent review/acceptance belongs to the integration wave and
  master per the sprint.

## Reproduce

```bash
python3 -m unittest discover -s tests -v          # 512 OK
python3 scripts/check_docs.py                     # 0 broken
python3 -m work_runtime adoption-demo             # exit 0, committed file artifacts: 1
python3 -m work_runtime lint-sop work_runtime/data/sop/publishing.json --json
python3 scripts/verify_install.py                 # 13 stages, PASS
```

## Addendum — 2026-10-14: installed-verification coverage correction (docs-only)

Master finding (late msg83d436, reached the reviewer only at report completion;
the source finding stands regardless of the integration-ready verdict):
CONTRIBUTING.md overclaimed that `verify_install` runs "all four demos through
both entry points". Stage matrix re-verified against `scripts/verify_install.py`
source at `bfbd29b` (`rg 'run(\[venv_python, "-m", "work_runtime"|run(\[console,'`,
lines 314–403):

| demo | module stage | console stage |
|---|---|---|
| `demo` | yes (line 314) | yes (line 358) |
| `publish-demo` | yes (line 327) | **no console stage** |
| `intervention-demo` | yes (line 342) | yes (line 363) |
| `adoption-demo` | yes (line 394) | yes (line 403) |

plus module `inspect --policy-versions` on the migrated store (line 351) and
console `lint-sop` on the extracted packaged card (line 385).

Factual limits, recorded: the `work-runtime publish-demo` console entry point
is exercised by no `verify_install` stage and no CI step (CI runs
`work-runtime demo` only); its module entry point is verified with an
independent `publications` count. Corrected prose to exactly the existing
proof in CONTRIBUTING.md and README.zh-CN.md (gate comment + summary
sentence); README.md, docs/verification.md and docs/contributor-guide.md were
rg-checked and already state the precise per-demo coverage (their
"module and console" claims name `intervention-demo`/`adoption-demo`, which do
have both stages) — left unchanged. No script, entrypoint or test additions;
no old evidence deleted; docs-only reversible delta, so no 512-test rerun
(docs gate re-run below, suite state unchanged at 512 OK from bfbd29b).

The public guide-only rehearsal (sprint Task 6) runs in an isolated branch off
`bfbd29b` with the same API surface; this docs-only followup changes no code
and does not disturb it. Corrected tip for final integration: this single
docs-only commit on top of `bfbd29b` (SHA reported in the worker_done
message; `git log --oneline -1`).
