# SOP authoring (static rule-card lint)

`work_runtime/authoring.py` adds a static authoring foundation for reviewable
SOP rule cards: `lint_sop` produces deterministic structural diagnostics and
`sop_digest` ties a manual review to the exact submitted content. Both are
pure functions — no filesystem, no Runtime calls, no coercion, no secret
echoing. See [RFC-002](RFC-002-sop-authoring-and-binding.md) for the SOP
model behind the card fields.

## What lint-clean means — and does not mean

Lint-clean means *structural review readiness* only:

- Textual predicates, triggers and requirements are **text**. They are never
  executed, never parsed as an expression language and never counted as proof
  of anything.
- `source` fields are **declared provenance**. Naming a document, version or
  section does not verify its existence, authenticity or authority.
- The linter cannot prove institution coverage, business truth or policy
  correctness, and it cannot bind the Runtime or a `Policy` implementation to
  a card. A lint-clean card is not executable and not published authority.
- Advice entries are suggestions; they never become rules and never satisfy
  the mandatory-rule requirement.

Authority approvals, immutable publication and a `lint-sop` CLI are later
sprint work (see [roadmap](roadmap.md)).

## API

| function | behavior |
|---|---|
| `lint_sop(value) -> list[dict]` | Returns `{"code", "path", "message"}` diagnostics for any Python value. Never raises, never mutates the input. |
| `sop_digest(value) -> str` | Canonical SHA-256 digest of the value after a clean lint. Raises `ValueError` with a bounded message (diagnostic count and first code/pointer only) otherwise. |

## Diagnostics

- `path` is an RFC 6901 JSON pointer; the root pointer is `""` (rendered
  `<root>` in digest error messages), `~` escapes as `~0` and `/` as `~1`.
- Results are sorted by the plain string tuple `(path, code, message)` and
  identical triples are deduplicated.
- Messages are static text plus identifier/enum snippets capped at 64
  characters. Whole requirement/source/document values are never echoed, and
  no user-defined `repr`/iteration hook is ever invoked to build a message.

### Error codes (exactly 14)

| code | meaning |
|---|---|
| `NOT_JSON_NATIVE` | value (or object key) is not an exact JSON-native type |
| `NONFINITE_FLOAT` | float is NaN or infinite |
| `INVALID_UNICODE` | string or object key is not UTF-8 encodable (e.g. lone surrogate) |
| `INTEGER_RANGE` | integer magnitude exceeds ±(2^53−1) |
| `DEPTH_LIMIT` | value is nested deeper than 64 levels |
| `CYCLE` | input object contains a reference cycle, or a rule dependency cycle |
| `MISSING_FIELD` | required field absent (anchored at the containing object) |
| `UNKNOWN_FIELD` | field outside the exact schema (anchored at the field key) |
| `TYPE_MISMATCH` | wrong type for the field or slot (`INVALID_SHAPE` is folded here) |
| `EMPTY_VALUE` | string is empty or whitespace-only (content is never trimmed) |
| `INVALID_VALUE` | right type, disallowed value (enums, reserved tokens, schema_version) |
| `DUPLICATE_ID` | reused ID, capability, or depends_on entry |
| `UNKNOWN_REFERENCE` | scope/depends_on/deadline names nothing declared |
| `NO_MANDATORY_RULE` | no rule with modality `must` or `forbidden` |

## JSON-native preflight

Preflight runs first over the whole tree, iteratively (no recursion, so no
`RecursionError`), and its findings suppress the schema layer entirely: a
value the linter cannot address reliably is reported as-is, not guessed past.

- Exact types only: `dict` (string keys), `list`, `str`, `int`, `float`,
  `bool`, `None`. Tuples, sets, bytes, subclasses and custom objects are
  `NOT_JSON_NATIVE` and are never descended, repr'd or iterated.
- Depth: root is depth 0; any node at depth 65 or deeper is `DEPTH_LIMIT`
  and its subtree is not visited.
- Integers outside ±(2^53−1) are `INTEGER_RANGE`; non-finite floats are
  `NONFINITE_FLOAT`; strings and keys that cannot encode as UTF-8 are
  `INVALID_UNICODE` (anchored at the container for keys, which cannot be
  addressed by pointer).
- A container on the active traversal path that contains itself is `CYCLE`;
  the same object appearing at two off-path positions (a repeated acyclic
  alias) is valid.
- These numeric and Unicode bounds are a project interoperability choice,
  not a claim about what RFC 8259 permits.

## Rule-card schema

The root object has exactly `schema_version`, `policy`, `defaults`, `facts`,
`collections`, `rules`, `advice`.

| section | exact fields | notes |
|---|---|---|
| `schema_version` | — | integer `1`; a boolean is a `TYPE_MISMATCH` |
| `policy` | `id, version, goal, source, scope, capabilities` | identity fields nonempty strings; `capabilities` a list of unique nonempty strings (an empty list is allowed) |
| `policy.source` | `document, version, section` | all nonempty strings; declared provenance only — never verified, and never a scope |
| `defaults` | `unknown, conflict, exemptions, migration` | exactly `block`, `escalate`, `forbidden`, `explicit` |
| `facts` | entries are exactly `{id}` | unique nonempty IDs; may be empty |
| `collections` | `id, version, completeness, allow_empty` | three nonempty strings and a strict boolean; may be empty |
| `rules` | see below | at least one mandatory rule required |
| `advice` | list of nonempty strings | never a rule, never satisfies cardinality |

Rules have exactly `id, source, modality, type, scope, trigger, depends_on,
requirement, deadline, evidence, unknown, conflict, exemption, migration`:

- `modality` is `must` or `forbidden` (both are mandatory rules; an
  all-forbidden package is valid); `type` is `state`, `action` or `history`.
- `scope` (policy and rules) is the literal `document` or a declared
  collection ID. `policy.source.document` is institutional text, never the
  business object scope.
- `depends_on` entries are unique nonempty strings referencing declared
  fact, collection or rule IDs.
- `deadline` is the literal `goal` (the goal boundary) or a declared
  capability.
- `evidence` has exactly `kind, source, subject, version`, all nonempty
  strings — declared acceptable provenance, not authenticated facts.
- `unknown`/`conflict`/`exemption`/`migration` are pinned to
  `block`/`escalate`/`forbidden`/`explicit`.

Reserved tokens: collection ID `document` and capability `goal` are rejected
with `INVALID_VALUE` so the scope and deadline literals stay unambiguous.
Fact, collection and rule IDs share one global namespace; a reused ID is
`DUPLICATE_ID` at each later occurrence (document order: facts, then
collections, then rules).

Reference checks run only against navigable declaring lists: malformed
`collections` suppresses scope checks, malformed `capabilities` suppresses
deadline checks, and `depends_on` references need `facts`, `collections` and
`rules` all navigable. Declared sets collect only well-formed entries.

Rule dependency cycles are found with an **iterative** Tarjan SCC over the
rule-to-rule edges (the JSON depth limit does not bound a flat rule graph).
Each cyclic component — not each simple cycle — yields one `CYCLE`
diagnostic at its lowest document-index member, with the bounded message
`rule dependency cycle component: '<id>' (+N more members)`. Long acyclic
chains of thousands of rules lint clean.

## Content digest

`sop_digest` reuses `policy.canonical`/`policy.digest` (sorted-key compact
JSON, SHA-256) only after the clean preflight + schema gate. Object key
order never matters; any content change does. No JCS compliance or
cross-language float canonicalization is claimed — the digest is exact and
stable for this library's canonical form.

## Examples

- Valid packaged cards (the single truth source for examples):
  [expense](../work_runtime/data/sop/expense.json) mirroring the demo
  expense policy (E01–E08) and
  [publishing](../work_runtime/data/sop/publishing.json) mirroring the
  content-publication policy (C01–C04). Dates and paths in them confer no
  policy authority.
- Invalid bounded fixtures covering every diagnostic family live under
  [examples/sop](../examples/sop/), one defect theme per file, including a
  long-chain cycle fixture for the graph boundary.
