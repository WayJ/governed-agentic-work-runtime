# S4 SOP Authoring Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the ratified S4 authoring foundation — `lint_sop` deterministic structural diagnostics and `sop_digest` canonical content digest for reviewable JSON rule cards — plus the packaged valid examples, invalid fixtures and the static-only authoring guide.

**Architecture:** One new pure module `work_runtime/authoring.py` (no filesystem, no runtime calls, no coercion). A JSON-native iterative preflight gate (types/depth/finite/UTF-8/integer/cycles) runs first; only a clean preflight reaches the strict schema layer (exact fields, enums, global ID namespace, reserved tokens, references, mandatory-rule cardinality, iterative SCC dependency-cycle components). `sop_digest` reuses `policy.digest` only after lint-clean. Valid cards live in `work_runtime/data/sop/` (single truth for later package-data); invalid fixtures live in `examples/sop/`; tests read those source files.

**Tech Stack:** Python >= 3.9 standard library only, standard-library unittest.

**Spec:** `docs/superpowers/specs/2026-10-13-s4-adoption-design.md` in this checkout. Authoritative CURRENT carrier: `/Users/jiangwei/orca/workspaces/governed-agentic-work-runtime/sprint-s4-adoption/docs/superpowers/specs/2026-10-13-s4-adoption-design.md` — includes D22 plus the **D22 graph traversal clarification** (iterative SCC, no RecursionError on long chains, one bounded diagnostic per cyclic component at the lowest document-index member, actual long-chain/long-cycle regressions), also delivered as Orca message `msg_949d43281eab` on this dispatch.

## Global Constraints

- Python >= 3.9, zero runtime dependencies, standard-library unittest only.
- Ownership scope (nothing else): `work_runtime/authoring.py`, `tests/test_authoring.py`, `work_runtime/data/sop/expense.json`, `work_runtime/data/sop/publishing.json`, `examples/sop/*.json`, `docs/sop-authoring.md`, this plan and `.agents/notes/2026-10-13-S4-sop-authoring-report.md`.
- NO edits to runtime.py, policy.py, adapters, publishing, ingress, CLI, README(s), pyproject, CI, epic/roadmap/sprint/acceptance docs, RFCs, or the local spec copy (integration merges the carrier).
- All 273 baseline tests must pass after every task; the three prior demos (`demo`, `publish-demo`, `intervention-demo`), `scripts/check_docs.py` (0 broken) and `compileall` stay green. No merge, no push, no nested agents, no local approval UI; blockers go through Orca `ask`.

## Settled contracts (from D22 + graph clarification; implement exactly)

### Public API

- `lint_sop(value) -> list` — pure function; each diagnostic is `{"code": str, "path": str, "message": str}`. Output sorted by `(path, code, message)`; identical triples deduplicated. Never raises for any Python input (non-native values, cycles, depth, invalid Unicode included); never mutates input; never evaluates predicates; no filesystem/runtime calls.
- `sop_digest(value) -> str` — runs preflight + schema; if not lint-clean raises `ValueError` with a bounded message (`SOP is not lint-clean: N diagnostic(s); first: CODE at PATH`; codes and pointers only, never input values). Clean input returns `policy.digest(value)` (canonical sorted-key compact JSON SHA-256).

### Diagnostic codes — exactly these 14

`MISSING_FIELD, UNKNOWN_FIELD, TYPE_MISMATCH, EMPTY_VALUE, INVALID_VALUE, DUPLICATE_ID, UNKNOWN_REFERENCE, CYCLE, NO_MANDATORY_RULE, NOT_JSON_NATIVE, NONFINITE_FLOAT, INVALID_UNICODE, INTEGER_RANGE, DEPTH_LIMIT` (INVALID_SHAPE folded into TYPE_MISMATCH).

### Pointers, order, message bounds

- RFC 6901 pointers; root is `""`; `~` → `~0`, `/` → `~1`. Paths are exact, never truncated, never contain surrogate characters.
- Sort key is the plain string tuple `(path, code, message)`; identical triples collapse to one.
- Messages are static text plus identifier/enum snippets capped at 64 characters; whole source/requirement/document values are never echoed; no user-defined `repr`/iteration hook is ever invoked while producing diagnostics.

### Preflight (JSON-native gate) — iterative only

Runs over the whole tree first. If it produces ANY diagnostics, they are the entire result (schema cascade suppressed). Node depth: root = 0, child = parent + 1; any node at depth >= 65 → `DEPTH_LIMIT` at its pointer; its children are not visited.

- Exact types only (`type(x) is T`): dict, list, str, int, float, bool, None. Anything else (tuple, set, bytes, subclasses, custom objects) → `NOT_JSON_NATIVE` at that node's pointer; not descended.
- Dict keys: any non-`str` key → `NOT_JSON_NATIVE` at the dict's pointer; any key that is not UTF-8-encodable (lone surrogates) → `INVALID_UNICODE` at the dict's pointer; entries under unusable keys are skipped (they cannot be addressed).
- `str` values not UTF-8-encodable → `INVALID_UNICODE` at the value's pointer. Non-finite floats → `NONFINITE_FLOAT`. Integers with `abs(v) > 2**53 - 1` → `INTEGER_RANGE` (bools are their own native type and exempt).
- Cycles: iterative traversal with an active-path identity set; a child whose `id()` is on the active path → `CYCLE` at that child's pointer with the input-cycle message; not descended. Repeated acyclic aliases (same object at two off-path positions) are valid — no diagnostic.
- No recursion anywhere (explicit stack), so no `RecursionError`; no `UnicodeEncodeError` escapes (encode checks are guarded).

### Schema (only after a clean preflight) — exact shapes

- Root: dict with exactly `schema_version, policy, defaults, facts, collections, rules, advice` (missing → `MISSING_FIELD` at `""`; unknown → `UNKNOWN_FIELD` at `""`). Non-dict root → `TYPE_MISMATCH` at `""`.
- `schema_version`: `type is int` (bool is a mismatch) and value `1` (other ints → `INVALID_VALUE`).
- `policy`: dict with exactly `id, version, goal, source, scope, capabilities`. `id/version/goal` nonempty non-whitespace strings. `source`: dict exactly `document, version, section`, all nonempty strings — declared provenance only, never verified, and `policy.source.document` is NEVER a scope. `scope`: nonempty string, literal `document` or a declared collection ID (else `UNKNOWN_REFERENCE`). `capabilities`: list of unique nonempty strings (element errors at `/policy/capabilities/i`: type/empty/duplicate/`goal` reserved → `INVALID_VALUE`); an empty list is allowed.
- `defaults`: dict exactly `unknown, conflict, exemptions, migration` = exactly `block, escalate, forbidden, explicit`.
- `facts`: list of dicts exactly `{"id"}`; `id` nonempty string. May be empty.
- `collections`: list of dicts exactly `id, version, completeness, allow_empty`; `id/version/completeness` nonempty strings; `allow_empty` exactly bool. Collection id `document` → `INVALID_VALUE` (reserved business-document scope token). May be empty.
- `rules`: list of dicts with exactly `id, source, modality, type, scope, trigger, depends_on, requirement, deadline, evidence, unknown, conflict, exemption, migration`. `id` nonempty string; `source` shaped like policy source; `modality` ∈ {`must`, `forbidden`}; `type` ∈ {`state`, `action`, `history`}; `scope` like policy scope; `trigger`/`requirement` nonempty strings; `depends_on` list of unique nonempty strings referencing declared fact/collection/rule IDs; `deadline` literal `goal` or a declared capability; `evidence`: dict exactly `kind, source, subject, version`, all nonempty strings (declared provenance, not authenticated facts); `unknown`/`conflict`/`exemption`/`migration` = exactly `block`/`escalate`/`forbidden`/`explicit`.
- `advice`: list of nonempty strings; never interpreted as rules, never satisfies mandatory cardinality.
- Global ID namespace: fact + collection + rule IDs (document order facts → collections → rules); a second occurrence → `DUPLICATE_ID` at the later entry's `/id`. Duplicate capability entries and duplicate entries within one `depends_on` list are also `DUPLICATE_ID`.
- `NO_MANDATORY_RULE` at `/rules` when `rules` is a list containing no rule whose `modality` is exactly `must` or `forbidden` (empty rules included; all-forbidden packages are valid).
- Cascade guards: a malformed container suppresses its descendants' checks. Reference checks run only against navigable declaring lists: scope needs `collections` to be a list; `deadline` needs `policy.capabilities` to be a list; `depends_on` references need `facts`, `collections` AND `rules` all to be lists. Declared sets collect only well-formed entries.

### Rule dependency cycles — iterative SCC (D22 graph clarification)

The depth-64 JSON limit does NOT bound a flat rule graph. Build the rule graph (nodes = well-formed rules by document index; edge rule → each `depends_on` entry naming another rule; first occurrence wins for duplicated IDs), then run an **iterative** Tarjan SCC (explicit stacks). Each cyclic component (size > 1, or a self-loop) yields exactly ONE `CYCLE` diagnostic at `/rules/<lowest-index-member>` with message `rule dependency cycle component: '<id>'` plus ` (+N more members)` when the component is larger — bounded ID snippet, never an enumeration of simple cycles. Long acyclic chains (thousands of rules) must lint clean without `RecursionError`; long cycles must produce exactly one component diagnostic.

### Digest semantics

`sop_digest` reuses `policy.canonical`/`policy.digest` only AFTER clean preflight + schema. Object-key-order neutral (sorted keys), exact content sensitivity, SHA-256 hex. No JCS or cross-language float canonicalization claim.

### Truth boundaries (docs must state)

Static only: predicates/requirements are text, never executed, never proof; `source` fields are declared provenance, never existence or authenticity; the linter cannot prove institution coverage, authority or business truth and cannot bind the Runtime/Policy; lint-clean ≠ executable/published. CLI `lint-sop` is a later sprint (loader duplicate-key/nonfinite/UTF-8/1MiB/recursion handling is NOT in this foundation).

## Tasks

### Task 0 — this plan

- [x] Write and commit this plan. No code.

### Task 1: preflight gate

**Files:** `tests/test_authoring.py` (new; classes `PreflightNativeTests`, `PreflightLimitsTests`, `PreflightCycleAliasTests`, `PointerOrderTests`), `work_runtime/authoring.py` (new).

- [ ] Step 1 RED: tests import `work_runtime.authoring` → `ModuleNotFoundError`; also write the preflight suites (native types/subclasses/bool-vs-int, non-str and surrogate keys, nonfinite, int bound ±(2^53-1), depth 64 ok / 65 rejected, input cycles → `CYCLE` without `RecursionError`, acyclic aliases valid, pointer escaping `~0`/`~1`, sort order, identical-triple dedup, call-twice stability, hostile `__repr__`/`__iter__` never invoked, `lint_sop` never raises). Observe RED.
- [ ] Step 2 Implement: iterative `_preflight` + `_sorted_dedup`; `lint_sop` returns preflight-only result. Minimal — no schema yet.
- [ ] Step 3 GREEN: `python3 -m unittest tests.test_authoring -v`; then full discover (273 + new).
- [ ] Step 4 Commit: `feat(authoring): iterative JSON-native preflight gate`.

### Task 2: root/policy/defaults schema

**Files:** same tests (new classes `RootSchemaTests`, `PolicySectionTests`, `DefaultsTests`), `work_runtime/authoring.py`.

- [ ] Step 1 RED: root non-dict → `TYPE_MISMATCH` at `""`; each of the 7 root keys missing → `MISSING_FIELD`; extra → `UNKNOWN_FIELD`; schema_version 1/2/`"1"`/`true`; policy id/version/goal/source/scope/capabilities shape, whitespace-only strings → `EMPTY_VALUE`; capabilities dup/`goal`-reserved/type/empty; defaults wrong enum per key. Observe RED (schema unimplemented → `[]`).
- [ ] Step 2 Implement: `_lint_schema` root + policy + defaults (scope reference check stubbed until Task 5 — no, collect collections in Task 3; for Task 2 scope reference validation is exercised only as nonempty-string presence).

  Correction (pinned): scope/deadline/depends_on REFERENCE checks land in Task 5 with the declared-ID collection; Task 2 asserts only shape/emptiness for `policy.scope`.

- [ ] Step 3 GREEN + full suite.
- [ ] Step 4 Commit: `feat(authoring): strict root, policy and defaults schema`.

### Task 3: facts/collections, global namespace, reserved tokens

**Files:** tests (`FactsCollectionsTests`, `GlobalIdNamespaceTests`), `work_runtime/authoring.py`.

- [ ] Step 1 RED: facts `{"id"}` exactness (extra/missing/type/whitespace); collections shape incl. `allow_empty` strict bool and reserved `document` → `INVALID_VALUE`; empty facts/collections valid; fact/collection/rule-ID collisions in every pairing → `DUPLICATE_ID` at the later occurrence.
- [ ] Step 2 Implement: declared-ID collection (document order facts → collections → rules) with duplicate reporting; facts/collections field checks.
- [ ] Step 3 GREEN + full suite.
- [ ] Step 4 Commit: `feat(authoring): facts, collections, global ID namespace and reserved scope token`.

### Task 4: rules schema, advice, mandatory cardinality

**Files:** tests (`RulesSchemaTests`, `AdviceTests`, `MandatoryRuleTests`), `work_runtime/authoring.py`.

- [ ] Step 1 RED: all 14 rule fields (missing each → `MISSING_FIELD` at `/rules/i`; unknown → `UNKNOWN_FIELD`); enums modality/type; fixed unknown/conflict/exemption/migration values; evidence exact shape; trigger/requirement whitespace → `EMPTY_VALUE`; advice element type/empty; empty rules and modality-free rules → `NO_MANDATORY_RULE`; all-forbidden package valid (`[]` diagnostics); advice never satisfies cardinality.
- [ ] Step 2 Implement: rule/evidence/advice checks + mandatory count.
- [ ] Step 3 GREEN + full suite.
- [ ] Step 4 Commit: `feat(authoring): strict rule cards, advice and mandatory-rule cardinality`.

### Task 5: references and iterative SCC cycles

**Files:** tests (`ReferenceTests`, `RuleCycleTests`), `work_runtime/authoring.py`.

- [ ] Step 1 RED: policy/rule scope literal `document` ok, declared collection ok, undeclared → `UNKNOWN_REFERENCE`; `depends_on` fact/collection/rule refs ok, undeclared → `UNKNOWN_REFERENCE` at the entry index, duplicates → `DUPLICATE_ID`; deadline `goal`/declared/undeclared; cascade guards (malformed declaring lists suppress reference checks, not shape checks); cycles: self-loop, 2-cycle, 3-cycle, two disjoint cycles → one `CYCLE` per component at the lowest-index member with bounded message; 2000-rule acyclic chain → `[]` with no `RecursionError`; 1500-rule single cycle → exactly one component diagnostic; cross-list dependencies (rule → fact) never cycle.
- [ ] Step 2 Implement: declared-set reference validation + iterative Tarjan SCC cycle components.
- [ ] Step 3 GREEN + full suite.
- [ ] Step 4 Commit: `feat(authoring): declared references and iterative SCC dependency-cycle diagnostics`.

### Task 6: sop_digest

**Files:** tests (`DigestTests`), `work_runtime/authoring.py`.

- [ ] Step 1 RED: clean synthetic card digests to 64-hex and equals `policy.digest`; key-order neutrality (rebuilt reversed-order card, same digest); any single value mutation → different digest; non-clean (schema error, non-native tuple, cycle, nonfinite, surrogate, deep, non-dict) → `ValueError` with bounded message that does not contain payload values; `lint_sop` still never raises for the same inputs.
- [ ] Step 2 Implement: `sop_digest` (reuse `policy.digest` after clean).
- [ ] Step 3 GREEN + full suite.
- [ ] Step 4 Commit: `feat(authoring): sop_digest reusing canonical digest after clean lint`.

### Task 7: packaged valid examples (single truth)

**Files:** tests (`PackagedExampleTests`), `work_runtime/data/sop/expense.json`, `work_runtime/data/sop/publishing.json`.

- [ ] Step 1 RED: tests read `work_runtime/data/sop/expense.json` and `publishing.json` from the source tree (no importlib.resources yet — packaging is the harness owner's task) and assert `lint_sop(...) == []`, `sop_digest` works, `schema_version == 1`, expense card carries E01–E08 with ≥1 must and ≥1 forbidden rule and both deadline kinds, publishing card mirrors `PublishingPolicy` (C01–C04, capability `content.publish`). Files absent → `FileNotFoundError` RED.
- [ ] Step 2 Implement: write the two cards mirroring the demo policies' semantics as reviewable text (dates/paths confer no authority).
- [ ] Step 3 GREEN + full suite.
- [ ] Step 4 Commit: `feat(authoring): packaged expense and publishing rule-card examples`.

### Task 8: invalid fixtures

**Files:** tests (`FixtureFileTests`), `examples/sop/*.json`.

- [ ] Step 1 RED: tests enumerate the fixture set by filename and assert the exact expected code set (and selected paths) per file, sorted output, nonempty diagnostics; `long-chain-cycle.json` asserts exactly one `CYCLE`. Absent files → RED.
- [ ] Step 2 Implement: write bounded, varied fixtures: missing-root-field, unknown-root-field, wrong-schema-version, boolean-schema-version, nonfinite-limit (NaN literal), empty-values, wrong-enums, type-mismatches, malformed-source, duplicate-ids, duplicate-capability, duplicate-depends-on, reserved-tokens, unknown-scope, unknown-deadline, unknown-depends-on, rule-cycle, long-chain-cycle, empty-rules. JSON only; not mirrors of the valid cards.
- [ ] Step 3 GREEN + full suite.
- [ ] Step 4 Commit: `feat(authoring): varied invalid SOP fixtures under examples/sop`.

### Task 9: guide, gates, report

**Files:** `docs/sop-authoring.md` (new), `.agents/notes/2026-10-13-S4-sop-authoring-report.md` (new).

- [ ] Step 1 Write `docs/sop-authoring.md`: exact API, diagnostics format and all 14 codes, preflight limits (native/depth 64/integer ±(2^53-1)/UTF-8/finite/cycles-and-aliases, iterative), full schema tables, global namespace and reserved tokens (`document`, `goal`), references and SCC cycle diagnostics, digest semantics and non-guarantees, links to the packaged examples and fixtures, static-only truth boundaries, CLI as a later sprint.
- [ ] Step 2 Gates: `python3 scripts/check_docs.py` (0 broken), `python3 -m unittest discover -s tests` (273 + new), `python3 -m work_runtime demo`, `... publish-demo`, `... intervention-demo`, `python3 -m compileall -q work_runtime tests scripts`.
- [ ] Step 3 Write the report (named tests, RED/GREEN commands and results, counts, commits, decisions, limits) and commit both: `docs(authoring): SOP authoring guide and worker report`.
- [ ] Step 4 Orca `check` for late redirects, then `worker_done` (exactly once) and idle.

## Verification

Every task: observed RED output quoted in the report, then GREEN, then full 273+new discover. Final: all gates above green; scoped `git log` clean; no out-of-ownership file touched (`git status` clean apart from report/plan commits).
