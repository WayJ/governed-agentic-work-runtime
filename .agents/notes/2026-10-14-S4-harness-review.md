# S4 adoption harness review (independent, early — rehearsal runs elsewhere)

Reviewer: s4-release-control worktree. Harness branch `WayJ/s4-adoption-harness` @ **bfbd29b**
(clean tip, base `cc40ef0`), reviewed against D22 (carrier spec), the S4 sprint plan, the
foundation-integration note and the harness plan/report; carrier itself is at `84cd4c8`
(D25 GUI planning docs, out of S4-harness scope). Changed files only; guide-only rehearsal
runs in a separate checkout and is not pre-empted here. My controller's GUI builder note
`01b93c3` remains preserved untouched for the later final integration — deliberately not
conflated with S4 scope.

## Verdict

**Implementable and integration-ready.** No product defect found; no master-ask needed. One
report-only nit (N1). Full fresh evidence below on a disposable tip worktree.

## Boundary audit (ownership)

`git diff --stat cc40ef0..bfbd29b` over runtime.py, policy.py, adapters.py,
adapter_contract.py, ingress.py, authoring.py, file_adapter.py, the three existing demos,
all pre-existing test files, check_docs.py and AGENTS.md → **empty**. Footprint is exactly
the owned set: `adoption_demo.py` (new), `cli.py` (+15: lint-sop/adoption-demo wiring only),
`tests/test_adoption_demo.py` (43 tests), `pyproject.toml` (package-data `data/sop/*.json`),
`scripts/verify_install.py` (+187), `.github/workflows/ci.yml` (+5 steps), public docs
(README×2, CONTRIBUTING, verification, roadmap), contributor guide, own plan/report.

## Fresh evidence (disposable worktree at bfbd29b)

- **43/43** harness tests; **512/512** full suite (469 carrier + 43; no existing test
  edited); `demo`, `publish-demo`, `intervention-demo`, `adoption-demo` all exit 0;
  `check_docs` 46 files/166 links/0 broken; `compileall` clean.
- **Real non-editable install**: `python3 scripts/verify_install.py` → **PASS**, 13 stages,
  fresh venv, import origin inside venv, zero third-party deps, module AND console
  `adoption-demo` outside the checkout each independently parsed: exactly one hash-named
  `224f2254…e4bae.json` (matches the report's deterministic sha256-of-business-key name),
  zero `.stage` leftovers, exact 5 artifact keys, `artifact_version` 1, key == the
  operation's business key, recomputed sha256(canonical(document)) == content_digest,
  accepted `FILE-` receipt, work `article-1` closed/succeeded, one confirmed_succeeded
  operation, printed inspect command re-run verbatim. Installed `lint-sop` reproduces the
  pinned packaged-card digests via `importlib.resources` (single truth — no embedded copy,
  no repo-cwd dependency).

## Meaningful RED (bounded mutations, restored to green each time)

- **HA** duplicate-key rejection neutered (`raise _LoaderFault(DUPLICATE_OBJECT_KEY)` →
  `pass`): **4 failures**.
- **HB** response loss moved BEFORE the real delegate commit: **5 failures + 2 errors** —
  the suite pins real-effect-then-loss (artifact exists at `outcome_unknown`), wrapper
  lookup delegation and contract surfacing.
- **HD** 1 MiB cap `>` → `>=`: **1 failure** (the exactly-1 MiB file must load).
Base-import RED (module absent) is documented by the owner; not re-counted here.

## Loader boundary matrix (direct CLI probes, beyond the suite)

| input | result |
|---|---|
| `NaN` / `Infinity` tokens | exit **2** `NONFINITE_LITERAL` (bounded static stderr) |
| well-formed `1e999` literal | exit **1** `NONFINITE_FLOAT` at `/policy/note`, no literal echo |
| `10**30` integer literal | exit **1** `INTEGER_RANGE` at `/policy/note` |
| escaped surrogate in value / in key | exit **1** `INVALID_UNICODE` at `/policy/goal` / `<root>`, printable |
| duplicate top-level/nested key | exit **2** `DUPLICATE_OBJECT_KEY`, doomed value never echoed (suite marker test) |
| invalid UTF-8 bytes, missing file, directory-as-file | exit **2** bounded codes |
| 5000-deep nesting | exit **2** `DEEP_JSON`, no traceback |
| exactly 1 MiB valid card | loads and lints **clean** (exit 0) |

(Probe-construction note: `json.dumps` renders float-inf as the `Infinity` token, so my
first overflow probe accidentally retested the token path — redone with a true `1e999`
literal; the product boundary is exactly as the owner's d894e95 pin claims.)

## Demo semantics and honesty

`ResponseLossPublisher` is pure composition: delegates the durable commit to the real
`FilePublisher`, surfaces `.contract` (capability preflight still applies), raises
`TimeoutError` only after the side effect, `lookup` delegates — restart + reconcile of the
original business key yields `confirmed_succeeded` with exactly **one** attempt and one
artifact. Prologue prints invalid-card diagnostics (inline card, not a packaged copy), both
pinned digests, and the static-only statement that the Runtime executes the engineered
`PublishingPolicy`, never the linted JSON. Hygiene suite: parent-directory contents
survive, fresh stores per run, runs with cwd outside the repo. CI steps (exit-0/1/2 trio +
adoption-demo + packaged-card lint) accurately mirror local behavior; remote-runner
execution correctly deferred to wave 4 — the owner says so explicitly.

## Contributor guide (teaching adapter honesty)

The guide's minimal adapter takes the shortcuts **on purpose and says so in place**:
`os.replace` can overwrite a concurrent winner vs `FilePublisher`'s exclusive `os.link`,
no pre-validation of document against `content_digest`, no fsync — with an explicit
pointer to the reference implementation and "declare what you actually enforce" framing.
The four conformance fixture hooks are documented, and the owner verified the guide's
code verbatim against `AdapterConformanceMixin` (5/5) in a disposable scratch before
removing it from the repo. Public interfaces/import surface the guide teaches
(`AdapterContract`, `execute/lookup`, mixin hooks, `packaged_card`/`lint-sop` workflow)
are sufficient for the separate guide-only rehearsal to find its own gaps; nothing here
claims human feedback.

## Findings

- **N1 (report-only nit, no action required):** the report's final-gates line says
  `check_docs` → "47 markdown files"; the actual count at `bfbd29b` is 46 (166 links, 0
  broken — the substantive claim holds). Owner may fix the numeral at integration if convenient.
- No substantive product defects; nothing routed to the original owner; no self-fixes made
  (review-only dispatch).

## Boundaries respected

No product/master/doc edits, no merges/pushes/accept (final integration follows the
separate rehearsal), no nested agents, no local approval UI. Disposable worktree and probe
files removed. This note is the only file changed.
