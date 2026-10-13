# S4 SOP authoring worker report (2026-10-13)

Worker: s4-sop-authoring (WayJ/s4-sop-authoring), base 726a39c, plan
`docs/superpowers/plans/2026-10-13-s4-sop-authoring.md`, spec
`docs/superpowers/specs/2026-10-13-s4-adoption-design.md` incl. D22 and the
D22 graph traversal clarification (CURRENT carrier copy; Orca message
msg_949d43281eab delivered mid-run and incorporated before the cycle task).
Scope held: `work_runtime/authoring.py`, `tests/test_authoring.py`,
`work_runtime/data/sop/expense.json`, `work_runtime/data/sop/publishing.json`,
`examples/sop/*.json` (19 files), `docs/sop-authoring.md`, plan + this
report. No runtime/policy/adapter/CLI/README/pyproject/CI/sprint-doc edits;
no merge, no push, no nested agents.

## Commits

| commit | content |
|---|---|
| 0c45af0 | scoped implementation plan |
| 008d429 | iterative JSON-native preflight gate (Task 1) |
| 2141787 | strict root, policy and defaults schema (Task 2) |
| 1b8457e | facts, collections, global ID namespace and reserved scope token (Task 3) |
| 38ed5fe | strict rule cards, advice and mandatory-rule cardinality (Task 4; amended locally pre-push so the committed state is green) |
| 9ed2fcc | declared references and iterative SCC dependency-cycle diagnostics (Task 5) |
| 7684dd5 | sop_digest reusing canonical digest after clean lint (Task 6) |
| d9e622e | packaged expense and publishing rule-card examples (Task 7) |
| bf53e98 | varied invalid SOP fixtures under examples/sop (Task 8) |
| (this) | docs/sop-authoring.md + worker report (Task 9) |

## RED/GREEN evidence (all runs from this checkout)

| task | RED (observed) | GREEN |
|---|---|---|
| 1 preflight | `python3 -m unittest tests.test_authoring -v` → `ModuleNotFoundError: No module named 'work_runtime.authoring'` | 36/36 OK |
| 2 root/policy/defaults | same suite → 72 failures + 1 IndexError, all "schema missing → []" | 58/58 OK |
| 3 facts/collections/namespace | → 27 failures | 76/76 OK |
| 4 rules/advice/cardinality | → 58 failures | 97/97 OK |
| 5 references + SCC cycles | → 14 failures; after implementation 19 (unneutralized references in earlier tests + two genuine cycles my probes had built) | 125/125 OK |
| 6 sop_digest | → `ImportError: cannot import name 'sop_digest'` | 134/134 OK |
| 7 packaged examples | `tests.test_authoring.PackagedExampleTests` → 6 × FileNotFoundError | 139/139 OK |
| 8 fixtures | `FixtureFileTests` → set mismatch + 42 FileNotFoundError | 146/146 OK |

## New tests: 146 in tests/test_authoring.py

PreflightNativeTests 12, PreflightLimitsTests 12, PreflightCycleAliasTests 6,
PointerOrderTests 6, RootSchemaTests 6, PolicySectionTests 11, DefaultsTests 5,
FactsCollectionsTests 10, GlobalIdNamespaceTests 8, RulesSchemaTests 13,
AdviceTests 3, MandatoryRuleTests 5, ReferenceTests 16, RuleCycleTests 12,
DigestTests 9, PackagedExampleTests 5, FixtureFileTests 7.
Highlights: hostile `__repr__`/`__iter__`/`keys` hooks never invoked; depth
64 ok / 65 rejected at `"/0"*65`; ±(2^53−1) boundaries; surrogate strings and
keys; acyclic aliases valid vs input cycles `CYCLE`; pointer escaping
`~0`/`~1`; sort + identical-triple dedup; 2000-rule acyclic chain lints clean
and 1500-rule cycle yields exactly ONE component diagnostic (iterative
Tarjan, D22 graph clarification); digest key-order neutrality, exact content
sensitivity, bounded no-payload-leak ValueError; packaged cards E01–E08 /
C01–C04 lint-clean; 19 fixtures each pinned to an exact code set.

## Final gates

- `python3 scripts/check_docs.py` → 43 markdown files, 134 local links, 0 broken.
- `python3 -m unittest discover -s tests` → **419 tests OK** (273 baseline + 146 new).
- `python3 -m work_runtime demo`, `publish-demo`, `intervention-demo` → all run to completion.
- `python3 -m compileall -q work_runtime tests scripts` → clean.

## Decisions and rulings (with cost if wrong)

1. Unknown fields anchor at the offending key's own pointer (root: `/extra`),
   not the container path — plan's parenthetical adjusted; spec silent.
2. `depends_on` entries colliding with a duplicated rule ID resolve to the
   first occurrence for cycle edges; tests avoid the ambiguity rather than
   suppressing cycle checks on duplicate IDs.
3. Element-malformed rules lists (list present, entry not an object) still
   emit `NO_MANDATORY_RULE` — pinned "rules is a list containing no mandatory
   rule"; only a malformed LIST suppresses cardinality.
4. A rule with an invalid modality does not count as mandatory, so a lone
   such rule gets `INVALID_VALUE` + `NO_MANDATORY_RULE` both.
5. Cycle-component message: `rule dependency cycle component: '<lowest-index
   id>' (+N more members)` — bounded, no simple-cycle enumeration.
6. `sop_digest` error renders root as `<root>`; message carries count + first
   code/pointer only.

## Review status and remaining risks

Final whole-branch review was a self-review (the user's brief forbids nested
agents); no Critical/Important findings; two cosmetic minors deferred
(triple blank lines, one >80-col line in `_check_capabilities`). Independent
foundation review by the S4 integration worker is still pending and expected
to reproduce RED/GREEN. Known limits, all documented in
docs/sop-authoring.md: static-only (no predicate execution, no provenance or
authority verification, cannot bind Runtime/Policy); preflight numeric and
Unicode bounds are project choices; digest has no JCS/cross-language float
guarantee; CLI `lint-sop` (loader duplicate-key/nonfinite/UTF-8/1MiB
recursion-safe handling, exit 0/1/2) and pyproject package-data wiring for
`data/sop/*.json` belong to the later harness-owning sprint; foundation
tests read the packaged source files directly.
