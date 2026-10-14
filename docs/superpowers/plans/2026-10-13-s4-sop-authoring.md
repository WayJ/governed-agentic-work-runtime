# S4 SOP Authoring Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the ratified S4 authoring foundation — `lint_sop` deterministic structural diagnostics and `sop_digest` canonical content digest for reviewable JSON rule cards — plus the packaged valid examples, invalid fixtures and the static-only authoring guide.

**Architecture:** One new pure module `work_runtime/authoring.py` (no filesystem, no runtime calls, no coercion). A JSON-native iterative preflight gate (types/depth/finite/UTF-8/integer/cycles) runs first; only a clean preflight reaches the strict schema layer (exact fields, enums, global ID namespace, reserved tokens, references, mandatory-rule cardinality, iterative SCC dependency-cycle components). `sop_digest` reuses `policy.digest` only after lint-clean. Valid cards live in `work_runtime/data/sop/` (single truth for later package-data); invalid fixtures live in `examples/sop/`; tests read those source files.

**Tech Stack:** Python >= 3.9 standard library only, standard-library unittest.

**Spec:** `docs/superpowers/specs/2026-10-13-s4-adoption-design.md` in this checkout. Authoritative CURRENT carrier: `/Users/jiangwei/orca/workspaces/governed-agentic-work-runtime/sprint-s4-adoption/docs/superpowers/specs/2026-10-13-s4-adoption-design.md` — includes D22 plus the **D22 graph traversal clarification** (iterative SCC, no RecursionError on long chains, one bounded diagnostic per cyclic component at the lowest document-index member, actual long-chain/long-cycle regressions), also delivered as Orca message `msg_949d43281eab` on this dispatch.

> **Alignment note (2026-10-14):** This plan was authored 2026-10-13 without the
> `writing-plans` skill loaded (which was loaded only on 2026-10-14, for the audit
> of commit 86d4a9e, and remains loaded for this docs-only alignment). Per that
> audit and master's acceptance, this revision corrects the stale unknown-field
> anchor (the implemented, tested and documented behavior anchors at the offending
> key's pointer, root included), adds the Review Focus and per-task Interfaces
> sections, makes the test-first/RED/GREEN phases explicit, and cleans two
> drafting artifacts. Historical task content, observed RED/GREEN evidence and
> commit identities are preserved verbatim; the approved spec and all completed
> code are untouched.

## Global Constraints

- Python >= 3.9, zero runtime dependencies, standard-library unittest only.
- Ownership scope (nothing else): `work_runtime/authoring.py`, `tests/test_authoring.py`, `work_runtime/data/sop/expense.json`, `work_runtime/data/sop/publishing.json`, `examples/sop/*.json`, `docs/sop-authoring.md`, this plan and `.agents/notes/2026-10-13-S4-sop-authoring-report.md`.
- NO edits to runtime.py, policy.py, adapters, publishing, ingress, CLI, README(s), pyproject, CI, epic/roadmap/sprint/acceptance docs, RFCs, or the local spec copy (integration merges the carrier).
- All 273 baseline tests must pass after every task; the three prior demos (`demo`, `publish-demo`, `intervention-demo`), `scripts/check_docs.py` (0 broken) and `compileall` stay green. No merge, no push, no nested agents, no local approval UI; blockers go through Orca `ask`.

## Review Focus

Input classes the spec implies that no happy-path test would exercise; each is pinned by the named tests in the owning task (all delivered):

- Hostile Python values — custom `__repr__`/`__iter__`/`keys` hooks, subclasses of native types — must never crash `lint_sop` nor leak value content into messages. Pinned by `PreflightNativeTests` (Task 1) and `DigestTests.test_error_message_never_leaks_payload_values` (Task 6).
- Boundary limits — depth 64 allowed/65 rejected at `"/0"*65`, integers ±(2^53−1) inclusive, non-finite floats, surrogate strings AND keys — pinned by `PreflightLimitsTests` (Task 1).
- Alias-vs-cycle confusion — repeated acyclic aliases valid, active-path identity cycles `CYCLE`, cycles in multiple branches both reported — pinned by `PreflightCycleAliasTests` (Task 1).
- Reference ambiguity under malformed declaring lists — shape errors still reported while scope/deadline/depends_on reference checks are suppressed or partial — pinned by `ReferenceTests` (Task 5).
- Flat unbounded rule graphs — thousands of rules are depth-3 JSON; long acyclic chains must lint clean without `RecursionError` and long cycles must collapse to ONE component diagnostic — pinned by `RuleCycleTests` (Task 5) and the `long-chain-cycle.json` fixture (Task 8).

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

- Root: dict with exactly `schema_version, policy, defaults, facts, collections, rules, advice` (missing → `MISSING_FIELD` at `""`; unknown → `UNKNOWN_FIELD` at the offending key's own pointer, root included, e.g. `/extra` — anchor as implemented, tested and accepted by master 2026-10-14; formerly pinned here as `""`). Non-dict root → `TYPE_MISMATCH` at `""`.
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

All tasks below were executed 2026-10-13 with observed RED/GREEN evidence recorded in `.agents/notes/2026-10-13-S4-sop-authoring-report.md`; commit identities are historical fact and preserved.

### Task 0 — this plan

- [x] Write and commit this plan. No code.

**Interfaces:**
- Consumes: ratified spec/D22 + graph clarification (Orca msg_949d43281eab).
- Produces: this plan (commit 0c45af0; aligned 2026-10-14 by the docs-only dispatch).

### Task 1: preflight gate

**Files:**
- Create: `tests/test_authoring.py` (classes `PreflightNativeTests`, `PreflightLimitsTests`, `PreflightCycleAliasTests`, `PointerOrderTests`), `work_runtime/authoring.py`.

**Interfaces:**
- Consumes: nothing from other tasks (standalone foundation).
- Produces: `lint_sop(value) -> List[Dict[str, str]]` returning preflight-only diagnostics until Task 2; iterative `_preflight` and `_finalize` (sort + identical-triple dedup); module constants for the exactly-14 codes; `_escape` (RFC 6901) and `_snippet` (64-char bound).

- [ ] **Step 1: Write the failing tests** — import `work_runtime.authoring` (module absent) and write the four preflight suites: native types/subclasses/bool-vs-int, non-str and surrogate keys, nonfinite, int bound ±(2^53-1), depth 64 ok / 65 rejected, input cycles → `CYCLE` without `RecursionError`, acyclic aliases valid, pointer escaping `~0`/`~1`, sort order, identical-triple dedup, call-twice stability, hostile `__repr__`/`__iter__` never invoked, `lint_sop` never raises.
- [ ] **Step 2: Run to observe RED** — `python3 -m unittest tests.test_authoring -v` → `ModuleNotFoundError: No module named 'work_runtime.authoring'`.
- [ ] **Step 3: Implement (minimal)** — iterative `_preflight` + `_finalize`; `lint_sop` returns the preflight-only result. No schema yet.
- [ ] **Step 4: Run to observe GREEN** — `python3 -m unittest tests.test_authoring -v` → all pass; then full discover (273 + new).
- [ ] **Step 5: Commit** — `feat(authoring): iterative JSON-native preflight gate` (→ 008d429).

### Task 2: root/policy/defaults schema

**Files:**
- Create: no new files; add test classes `RootSchemaTests`, `PolicySectionTests`, `DefaultsTests` to `tests/test_authoring.py`; modify `work_runtime/authoring.py`.

**Interfaces:**
- Consumes: `lint_sop`'s clean-preflight gate from Task 1 (schema layer runs only when preflight is empty).
- Produces: `_lint_schema` with `_check_exact_fields` (MISSING_FIELD at container, UNKNOWN_FIELD at the key's pointer), `_require_text` (TYPE_MISMATCH / whitespace EMPTY_VALUE), `_check_source`, `_check_capabilities` (`goal` reserved → INVALID_VALUE); policy scope validated for shape/emptiness only — reference resolution is deferred to Task 5.

- [ ] **Step 1: Write the failing tests** — root non-dict → `TYPE_MISMATCH` at `""`; each of the 7 root keys missing → `MISSING_FIELD`; extra → `UNKNOWN_FIELD` at the key pointer; schema_version 1/2/`"1"`/`true`; policy id/version/goal/source/scope/capabilities shape, whitespace-only strings → `EMPTY_VALUE`; capabilities dup/`goal`-reserved/type/empty; defaults wrong enum per key.
- [ ] **Step 2: Run to observe RED** — suite fails with `[]`-vs-expected diagnostics (schema unimplemented).
- [ ] **Step 3: Implement (minimal)** — root + policy + defaults checks per the settled contracts.
- [ ] **Step 4: Run to observe GREEN** — module suite, then full discover.
- [ ] **Step 5: Commit** — `feat(authoring): strict root, policy and defaults schema` (→ 2141787).

### Task 3: facts/collections, global namespace, reserved tokens

**Files:**
- Modify: `work_runtime/authoring.py`; add test classes `FactsCollectionsTests`, `GlobalIdNamespaceTests`.

**Interfaces:**
- Consumes: `_check_exact_fields`/`_require_text` from Task 2.
- Produces: `_lint_id_list`, `_lint_facts`, `_lint_collections` (strict-bool `allow_empty`; reserved collection id `document` → INVALID_VALUE) and `_collect_global_ids` — the declared-ID walk in document order facts → collections → rules that Task 5's reference layer consumes.

- [ ] **Step 1: Write the failing tests** — facts `{"id"}` exactness (extra/missing/type/whitespace); collections shape incl. `allow_empty` strict bool and reserved `document` → `INVALID_VALUE`; empty facts/collections valid; fact/collection/rule-ID collisions in every pairing → `DUPLICATE_ID` at the later occurrence.
- [ ] **Step 2: Run to observe RED** — suite fails (facts/collections unchecked).
- [ ] **Step 3: Implement (minimal)** — declared-ID collection with duplicate reporting; facts/collections field checks.
- [ ] **Step 4: Run to observe GREEN** — module suite, then full discover.
- [ ] **Step 5: Commit** — `feat(authoring): facts, collections, global ID namespace and reserved scope token` (→ 1b8457e).

### Task 4: rules schema, advice, mandatory cardinality

**Files:**
- Modify: `work_runtime/authoring.py`; add test classes `RulesSchemaTests`, `AdviceTests`, `MandatoryRuleTests`.

**Interfaces:**
- Consumes: Task 2 field helpers and Task 3's list/ID conventions.
- Produces: `_lint_rules` (14 exact fields, modality/type enums via `_require_enum`, pinned handling values via `_require_pinned`), `_lint_depends_on_shape`, `_lint_evidence`, `_lint_advice`, and the mandatory-rule count that later tasks rely on for card validity.

- [ ] **Step 1: Write the failing tests** — all 14 rule fields (missing each → `MISSING_FIELD` at `/rules/i`; unknown → `UNKNOWN_FIELD`); enums modality/type; fixed unknown/conflict/exemption/migration values; evidence exact shape; trigger/requirement whitespace → `EMPTY_VALUE`; advice element type/empty; empty rules and modality-free rules → `NO_MANDATORY_RULE`; all-forbidden package valid (`[]` diagnostics); advice never satisfies cardinality.
- [ ] **Step 2: Run to observe RED** — suite fails (rules layer missing).
- [ ] **Step 3: Implement (minimal)** — rule/evidence/advice checks + mandatory count.
- [ ] **Step 4: Run to observe GREEN** — module suite, then full discover.
- [ ] **Step 5: Commit** — `feat(authoring): strict rule cards, advice and mandatory-rule cardinality` (→ 38ed5fe; amended locally pre-push so the committed state is green).

### Task 5: references and iterative SCC cycles

**Files:**
- Modify: `work_runtime/authoring.py`; add test classes `ReferenceTests`, `RuleCycleTests`.

**Interfaces:**
- Consumes: declared-ID walk from Task 3 and rule shapes from Task 4.
- Produces: `_declared_collection_ids` / `_declared_capability_ids` / `_declared_reference_ids` (None when a declaring list is malformed), `_check_references` (scope/depends_on/deadline with cascade guards and duplicate-entry DUPLICATE_ID), `_check_rule_cycles` + `_cyclic_components` (iterative Tarjan SCC; one bounded `CYCLE` per cyclic component at the lowest document-index member).

- [ ] **Step 1: Write the failing tests** — policy/rule scope literal `document` ok, declared collection ok, undeclared → `UNKNOWN_REFERENCE`; `depends_on` fact/collection/rule refs ok, undeclared → `UNKNOWN_REFERENCE` at the entry index, duplicates → `DUPLICATE_ID`; deadline `goal`/declared/undeclared; cascade guards (malformed declaring lists suppress reference checks, not shape checks); cycles: self-loop, 2-cycle, 3-cycle, two disjoint cycles → one `CYCLE` per component at the lowest-index member with bounded message; 2000-rule acyclic chain → `[]` with no `RecursionError`; 1500-rule single cycle → exactly one component diagnostic; cross-list dependencies (rule → fact) never cycle.
- [ ] **Step 2: Run to observe RED** — reference and cycle assertions fail (layer missing).
- [ ] **Step 3: Implement (minimal)** — declared-set reference validation + iterative Tarjan SCC cycle components.
- [ ] **Step 4: Run to observe GREEN** — module suite, then full discover.
- [ ] **Step 5: Commit** — `feat(authoring): declared references and iterative SCC dependency-cycle diagnostics` (→ 9ed2fcc).

### Task 6: sop_digest

**Files:**
- Modify: `work_runtime/authoring.py`; add test class `DigestTests`.

**Interfaces:**
- Consumes: the complete clean gate from Tasks 1–5 and `policy.digest`.
- Produces: `sop_digest(value) -> str` — canonical SHA-256 for lint-clean input, bounded `ValueError` ("SOP is not lint-clean: N diagnostic(s); first: CODE at PATH", root rendered `<root>`) otherwise.

- [ ] **Step 1: Write the failing tests** — clean synthetic card digests to 64-hex and equals `policy.digest`; key-order neutrality (rebuilt reversed-order card, same digest); any single value mutation → different digest; non-clean (schema error, non-native tuple, cycle, nonfinite, surrogate, deep, non-dict) → `ValueError` with bounded message that does not contain payload values; `lint_sop` still never raises for the same inputs.
- [ ] **Step 2: Run to observe RED** — `ImportError: cannot import name 'sop_digest'`.
- [ ] **Step 3: Implement (minimal)** — `sop_digest` reusing `policy.digest` after clean lint.
- [ ] **Step 4: Run to observe GREEN** — module suite, then full discover.
- [ ] **Step 5: Commit** — `feat(authoring): sop_digest reusing canonical digest after clean lint` (→ 7684dd5).

### Task 7: packaged valid examples (single truth)

**Files:**
- Create: `work_runtime/data/sop/expense.json`, `work_runtime/data/sop/publishing.json`; add test class `PackagedExampleTests`.

**Interfaces:**
- Consumes: full `lint_sop` + `sop_digest`.
- Produces: the two packaged cards that later harness work reads via `importlib.resources` (not wired in this sprint — tests read the source files directly).

- [ ] **Step 1: Write the failing tests** — tests read both files and assert `lint_sop(...) == []`, `sop_digest` works, `schema_version == 1`, expense card carries E01–E08 with ≥1 must and ≥1 forbidden rule and both deadline kinds, publishing card mirrors `PublishingPolicy` (C01–C04, capability `content.publish`). Files absent → `FileNotFoundError`.
- [ ] **Step 2: Run to observe RED** — `FileNotFoundError` on the missing files.
- [ ] **Step 3: Implement** — write the two cards mirroring the demo policies' semantics as reviewable text (dates/paths confer no authority).
- [ ] **Step 4: Run to observe GREEN** — module suite, then full discover.
- [ ] **Step 5: Commit** — `feat(authoring): packaged expense and publishing rule-card examples` (→ d9e622e).

### Task 8: invalid fixtures

**Files:**
- Create: `examples/sop/*.json` (19 files); add test class `FixtureFileTests` with a `FIXTURE_EXPECTATIONS` filename → expected-code-set table.

**Interfaces:**
- Consumes: full lint (and digest for the raise-path assertions).
- Produces: the bounded invalid-fixture set, one defect theme per file, including the `long-chain-cycle.json` graph-boundary fixture (80-rule single cycle → exactly one `CYCLE`).

- [ ] **Step 1: Write the failing tests** — enumerate the fixture set by filename, assert the exact expected code set (and selected paths) per file, sorted output, nonempty diagnostics.
- [ ] **Step 2: Run to observe RED** — set mismatch + `FileNotFoundError` (files absent).
- [ ] **Step 3: Implement** — write the fixtures: missing-root-field, unknown-root-field, wrong-schema-version, boolean-schema-version, nonfinite-limit (NaN literal), empty-values, wrong-enums, type-mismatches, malformed-source, duplicate-ids, duplicate-capability, duplicate-depends-on, reserved-tokens, unknown-scope, unknown-deadline, unknown-depends-on, rule-cycle, long-chain-cycle, empty-rules. JSON only; not mirrors of the valid cards.
- [ ] **Step 4: Run to observe GREEN** — module suite, then full discover.
- [ ] **Step 5: Commit** — `feat(authoring): varied invalid SOP fixtures under examples/sop` (→ bf53e98).

### Task 9: guide, gates, report

**Files:**
- Create: `docs/sop-authoring.md`; `.agents/notes/2026-10-13-S4-sop-authoring-report.md`.

**Interfaces:**
- Consumes: the finished module, examples, fixtures and all prior evidence.
- Produces: the public static-only guide and the worker report (RED/GREEN commands and results, counts, commits, decisions, limits) that integration reviews.

- [ ] **Step 1: Write `docs/sop-authoring.md`** — exact API, diagnostics format and all 14 codes, preflight limits, full schema tables, global namespace and reserved tokens, references and SCC cycle diagnostics, digest semantics and non-guarantees, links to the packaged examples and fixtures, static-only truth boundaries, CLI as a later sprint.
- [ ] **Step 2: Run the gates** — `python3 scripts/check_docs.py` (0 broken), `python3 -m unittest discover -s tests` (273 + new), `python3 -m work_runtime demo`, `... publish-demo`, `... intervention-demo`, `python3 -m compileall -q work_runtime tests scripts`.
- [ ] **Step 3: Write the report and commit both** — `docs(authoring): SOP authoring guide and worker report` (→ d1051b6).
- [ ] **Step 4: Orca close-out** — final `check`, then `worker_done` and idle.

## Verification

Every task: observed RED output quoted in the report, then GREEN, then full 273+new discover. Final: all gates green; scoped `git log` clean; no out-of-ownership file touched (`git status` clean apart from report/plan commits).
