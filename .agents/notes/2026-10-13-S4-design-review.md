# S4 adoption design review (independent builder check)

Reviewer: s4-release-control worktree (WayJ/s4-release-control @ 491680e); carrier spec diffed identical
to local `docs/superpowers/specs/2026-10-13-s4-adoption-design.md`. Carrier read at 17e5d1a: S4 plan,
E4 DoD and opening note are consistent with the draft and add no new constraint. Baseline reproduced
once on this checkout: **273 tests pass** (`python3 -m unittest discover -s tests`), matching the
design's "all273" and the S3 release note; no historical rerun. Read-only review; no
spec/roadmap/product edits.

## Verdict

**Implementable** with zero Runtime/Policy lifecycle edits: `dispatch` already converts adapter
exceptions to `outcome_unknown` (`runtime.py:760`) and `reconcile` retains it on lookup failure
(`runtime.py:783`), with invalid results quarantined as `ADAPTER_RESULT_INVALID`
(`runtime.py:807-810`) — exactly the uncertain-effect recovery the FilePublisher scenarios need.
No hard blockers. Four localized defaults (B1–B4) need master ratification before wave-1 code;
everything else is a bounded builder choice settled below.

## Ratify-before-code defaults (suggested defaults included)

- **B1 — facts entry shape is under-specified.** The design says only "Facts unique nonempty fact
  IDs". Default: each fact is an object with exactly one key `id` (nonempty string, unique);
  unknown fields rejected like everywhere else. If richer facts are wanted, name the exact keys
  now — examples, tests and docs all inherit this shape.
- **B2 — scope binding rule.** "Scope must name document or a declared collection" needs a
  referent for "document". Default: for `policy.scope` and every `rule.scope`, the string must
  equal `policy.source.document` or a declared collection id (literal comparison, checked after
  collections are known). Free-form nonempty strings would be strictly weaker.
- **B3 — `deadline` sentinel collision.** `deadline` is "either goal or one declared capability",
  so a capability literally named `goal` is ambiguous. Default: reserve the token — a capability
  named `goal` is a diagnostic (`INVALID_VALUE`, reserved word), `deadline: "goal"` always means
  the policy goal.
- **B4 — non-JSON-native input: diagnostics vs exception.** Design line 9 says "reject …
  predictably, no raw RecursionError" while line 13 says "linter API rejects invalid Python
  shapes". Default: `lint_sop` **never raises** — non-JSON-native values, nonfinite floats,
  lone surrogates, cycles and over-deep input are all ordinary diagnostics; only `sop_digest`
  raises `ValueError` for anything not lint-clean. This is the only reading where "lint failure
  is a result, not a crashing stack trace" holds unconditionally.

## Settled bounded proposals

### 1. Schema cardinality, references, cycles

- Root: exactly the seven keys, all required (`schema_version`, `policy`, `defaults`, `facts`,
  `collections`, `rules`, `advice`); `facts`/`collections`/`rules`/`advice` may be empty lists.
- `schema_version`: `type(v) is int` (bool excluded) and `== 1`.
- `policy`: exact six keys; `id`/`version`/`goal` nonempty strings; `source` exact
  `document`/`version`/`section` nonempty strings; `capabilities` list of unique nonempty
  strings; scope per B2.
- `defaults`: exact `unknown`/`conflict`/`exemptions`/`migration` = `block`/`escalate`/
  `forbidden`/`explicit` (enum-locked, matching the rule-level lock below).
- `collections`: exact `id`/`version`/`completeness`/`allow_empty` — three nonempty strings plus
  strict bool.
- `rules`: exact 14 keys (`id`, `source`, `modality`, `type`, `scope`, `trigger`, `depends_on`,
  `requirement`, `deadline`, `evidence`, `unknown`, `conflict`, `exemption`, `migration`);
  `source` same shape as policy source; `modality` ∈ {must, forbidden}; `type` ∈
  {state, action, history}; `trigger`/`requirement` nonempty strings; `depends_on` a duplicate-
  free list resolving against declared fact/collection/rule ids; `evidence` exact
  `kind`/`source`/`subject`/`version` nonempty strings; `deadline` per B3; and the four decision
  fields locked this sprint: `unknown="block"`, `conflict="escalate"`, `exemption="forbidden"`,
  `migration="explicit"`.
- **Global ID namespace** across facts + collections + rules. The design requires collections to
  be distinct from facts/rule ids; extending this to all three kinds is *necessary*, not
  stylistic: `depends_on` resolves against "declared facts/collections/rule IDs", which is
  ambiguous if kinds share an id. Later occurrence gets `DUPLICATE_ID`.
- `advice`: list of nonempty strings, never referenceable (no rule may depend on advice).
- At least one rule with `modality == "must"`, else one `NO_MANDATORY_RULE` at `/rules`
  (so an all-forbidden or empty rules list is a diagnostic, per "at least one mandatory rule").
- Cycles: rule→rule edges from `depends_on` only (fact/collection edges are leaves), DFS in
  document order with white/gray/black coloring; one `CYCLE` diagnostic per cycle at its
  lowest-index member rule, message listing the rule ids around the cycle. This is RFC-002 §6
  "no obvious deadlock" (A-requires-B-requires-A) made checkable, within H5's no-recursion bound.

### 2. Bounded diagnostics vocabulary and order

Exact code set (15), UPPER_SNAKE like existing rejected-codes:

| code | triggers |
|---|---|
| `MISSING_FIELD` / `UNKNOWN_FIELD` | absent required key / key outside the exact set |
| `TYPE_MISMATCH` | wrong JSON type at a typed slot (incl. non-dict/list root, bool-for-int) |
| `EMPTY_VALUE` | string that must be nonempty; empty list where disallowed (none this sprint) |
| `INVALID_VALUE` | enum violations, `schema_version != 1`, reserved `goal` (B3) |
| `DUPLICATE_ID` | repeated id within/between facts, collections, rules, capabilities, `depends_on` |
| `UNKNOWN_REFERENCE` | `depends_on` target undeclared; scope not document/collection (B2); deadline not goal/capability |
| `CYCLE` | rule dependency cycle (also self-dependency) |
| `NO_MANDATORY_RULE` | zero `must` rules |
| `NOT_JSON_NATIVE` | non-container types, non-str dict keys, tuples/sets/objects anywhere |
| `NONFINITE_FLOAT` | NaN/inf anywhere (API-level; see loader split below) |
| `INVALID_UNICODE` | string containing unpaired surrogates (blocks `UnicodeEncodeError` in digest) |
| `INTEGER_RANGE` | |int| > 2^53−1 (JSON-safe integers; only `schema_version` is an int slot) |
| `DEPTH_LIMIT` | nesting > 64 (see §3 for why 64 is load-bearing) |
| `INVALID_SHAPE` | non-dict where an object is required (e.g. list root) — may fold into `TYPE_MISMATCH`; keep exactly one |

Order: sort by `(path, code, message)`; path is an RFC 6901 JSON pointer (`~0`/`~1` escaped,
root = `""`) compared lexicographically — `/rules/10` sorts before `/rules/2` and that is
accepted as specified determinism, not numeric order. At most one diagnostic per
`(path, code, message)` triple. Messages quote at most 64 chars of an identifier/enum token;
never whole documents or long text fields — loader errors likewise never echo input contents.

### 3. Digest and JSON encoding edges

`sop_digest` reuses `policy.canonical`/`digest` verbatim (`policy.py:8-14`: sort_keys,
`,`/`:` separators, `ensure_ascii=False`, `allow_nan=False`, UTF-8, SHA-256) — one canonical
form for the whole codebase; `sop_digest(v)` = lint-clean check then `digest(v)`, else
`ValueError`. Mutation/reorder tests (DoD S1) fall out of canonicality. The **depth limit of 64
is load-bearing**: `json.dumps` recurses in C and raises `RecursionError` near ~1000 levels, so
lint must bound nesting well below that before any digest call. CLI loader: `object_pairs_hook`
raising on duplicate object keys, `parse_constant` raising on `NaN`/`Infinity` literals, caught
`UnicodeDecodeError`/`JSONDecodeError`/`OSError` → all exit **2** (malformed file; argparse
usage errors already exit 2) with path + reason only. Note the deliberate split: nonfinite
floats and surrogates reachable from a *file* are loader errors (exit 2, RFC 8259 forbids them);
the same values arriving as *Python objects* via the API are diagnostics (`NONFINITE_FLOAT`,
`INVALID_UNICODE`).

### 4. FilePublisher commit protocol (portable, atomic, non-overwriting)

Contract: `AdapterContract(actions=("content.publish",), idempotency_scope="directory:key",
retention="lifetime-of-directory", lookup_consistency="authoritative-by-key", uniqueness=())` —
empty uniqueness tuple exactly as the design pins (no document-content uniqueness promise,
unlike FakePublisher's `document.id+content_digest`).

- Basename: `sha256(key_utf8).hexdigest() + ".json"` — fixed length, traversal-proof; caller
  keys and `document.id` never touch the path (a key like `../../etc/passwd` still lands inside
  the directory; non-string/empty key → `ValueError`).
- Artifact body: `canonical()`-encoded `{"artifact_version": 1, "key", "content_digest",
  "document", "receipt": {"status": "accepted", "external_id": "FILE-" + uuid12, "digest"}}` —
  deterministic bytes for identical content; external_id generated once at commit and *read back
  from the artifact* on every replay/lookup, which is what makes receipts stable without a store.
- `execute(key, document, content_digest)`: strict key check → `digest(document) ==
  content_digest` check → JSON-nativeness gate (see §5) → if committed file exists, validate and
  return-or-raise; else write a staging file `.{basename}.stage-{pid}-{uuid}` opened
  `O_CREAT|O_EXCL` **in the same directory**, `flush` + `os.fsync(stage_fd)` → commit via
  `os.link(stage, committed)` (atomic, fails `FileExistsError` if the target exists — never
  overwrites, no `rename` clobber) → unlink stage → `fsync` the directory fd where the platform
  allows. On `FileExistsError` (race or replay): unlink own stage, read and validate the
  committed artifact — matching digest returns its receipt *identically*; mismatched digest
  raises the same `ValueError` message as FakeOA/FakePublisher ("Idempotency key reused with
  different content").
- `lookup(key)`: missing → `None`; present → parse, check embedded `key` equals the requested
  key and `digest(stored document) == content_digest == receipt.digest`; any parse/validation
  failure → bounded `ValueError` (the Runtime then retains `outcome_unknown`, `runtime.py:783`).
  Validation recomputes the document digest — never trusts the receipt field alone.
- Honest platform/fsync boundaries (docs must state, tests cannot prove): process death is fully
  covered (staging leftover is ignorable, committed file is complete because content is fsynced
  before the link); **power loss is not claimed anywhere** — macOS `fsync` is not `F_FULLFSYNC`,
  and Windows offers no directory fsync (skip it there; NTFS hardlinks work but FAT/network
  mounts may not support `os.link`, which surfaces as an ordinary adapter failure →
  `outcome_unknown`). No symlink/hostile-filesystem claim: root directory is trusted-local.
- Crash hooks follow the existing `timeout_after_commit` precedent (`adapters.py:23`,
  `publishing.py:124`): constructor flags `crash_after_stage` / `crash_after_commit` calling
  `os._exit(1)` at the two named points — small, documented, and demo-serving like their sibling.

### 5. Wave-1 disjointness: file_adapter keeps its own JSON gate

`file_adapter` must not import `authoring` (two parallel developers own disjoint files, D2).
`policy.canonical` would silently coerce tuples to arrays, so FilePublisher needs its own ~20-line
iterative nativeness/cycle/surrogate check before serializing. Deliberate duplication to keep the
foundations disjoint; dedupe only post-wave-2 if master wants.

### 6. Tests: conformance, process death, concurrency

- Conformance mixin adopter: `make_adapter` → `FilePublisher(fresh tempdir)`; `sample_document`
  → the `{id,title,body,requires_review}` article shape; `changed_document` → different body;
  `effect_count` → actual enumeration of committed `*.json` files (staging prefix excluded) —
  real filesystem counting, per D3's "no stdout-only verification" lesson.
- Process death (subprocess, parent inspects directory): crash after stage → staging leftover
  only, `lookup → None`, retry commits cleanly; crash after commit → exactly one committed
  artifact, `lookup` returns the receipt, retry same key/content returns it identically.
- Concurrency (subprocesses, not threads): N racers same key+content → exactly one committed
  artifact, every racer returns the identical receipt (read-back); mixed-content race → exactly
  one committed artifact, winners-by-content get the receipt, others get `ValueError`.
  Invariants asserted after joining all — no timing flakiness.
- Restart / key-mismatch (artifact planted under another key's hash) / corruption (truncated or
  garbage file) / path-traversal keys / non-string-empty keys: bounded `ValueError` or safe
  hash-name publish, never acceptance of wrong-key or wrong-digest content.

### 7. CLI `lint-sop` and adoption harness

`lint-sop <path> [--json]`: exit 0 = clean (print digest + a fixed static-only limitation line:
structural review readiness, not executable authority, business publisher still required);
exit 1 = diagnostics (JSON array of `{code,path,message}` under `--json`, stable order §2);
exit 2 = malformed file or usage (§3 loader rules). Adoption demo composes the publishing_demo
flow (`publishing_demo.py:83-130`: blocked proposal → signed candidates → verify → intent →
uncertain response → restart/reconcile → completion) with FilePublisher, plus an authoring
prologue (invalid fixture diagnostics, clean example + digest). Response loss uses a
**composition wrapper** around the real FilePublisher (delegates, then raises `TimeoutError`
after the real commit) — no stub, no adapter-internal flag, per the design. Fresh temp dirs,
prints the artifacts directory path and the `inspect` command.

### 8. Installed verification and the guide-only rehearsal

`scripts/verify_install.py` gains stages (module + console, outside checkout, per D3): run
`adoption-demo`, then independently — without importing work_runtime — `os.listdir` the printed
artifacts directory, require exactly one committed file, `json.load` it, and assert embedded
key/digest/equality with expected constants and path equality with what was printed. Rehearsal
definition (DoD S4): a separate Claude worktree, given only the contributor guide + public docs
(`docs/adapter-contract.md`, `docs/file-adapter.md`, `docs/sop-authoring.md`), explicitly barred
from reading `work_runtime/*.py` internals, implements a tiny disposable third-party-style
adapter (e.g. JSONL appender) plus its own tests against the documented interface, and files a
reproducible findings report (guide gaps, API friction). Findings feed wave-3 docs before
acceptance; the report is labeled agent rehearsal — never external human validation.

## Rejected by design (restated against RFC-002)

Lint is one row of the RFC-002 §6 publication pipeline (static check before authorized approval
and immutable publication, both out of scope this sprint). It structurally covers traceability
(source required), object explicitness (scope/`depends_on` references), deadline explicitness,
and deadlock freedom (cycles). It cannot and must not claim the decidability, privilege-closure
or capability-implementability rows — those stay with engineering binding and the business
publisher; no arbitrary expression evaluation, no natural-language compilation, and `lint-clean`
+ `sop_digest` confer zero Runtime authority. FilePublisher's directory-local idempotency
implies nothing distributed: no exactly-once, no external fencing claims.

## Minor choices left to the builder

`INVALID_SHAPE` folded into `TYPE_MISMATCH` or kept separate (pick one, document it); message
wording templates; artifact `artifact_version` constant name; guide file path (default
`docs/contributor-guide.md` linked from CONTRIBUTING.md); whether `verify_install` grows a
`--adoption-only` fast path. None affect interfaces.
