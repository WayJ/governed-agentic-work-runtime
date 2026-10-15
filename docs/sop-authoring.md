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

The `lint-sop` CLI ships with the adoption wave (exit 0 clean / 1
diagnostics / 2 file error), and authority approvals plus immutable
publication are implemented as the governed publication core below (S12,
design D54–D66) — lint-clean still means review readiness, never executable
authority.

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

## Publication (governed, S12)

`work_runtime/publication.py` adds the ratified publication core (design
D54–D66): a lint-clean card can be published as one immutable, hash-named
artifact through the same governed command protocol every other external
effect uses, behind a signed, version-bound approval of the card's exact
content digest.

### What a publication is

A publication is **one committed artifact in an append-only store
directory**, identified by a three-part identity:

- **artifact identity** — the store key
  `publication_key(card) = "sop-pub:" + digest([card.policy.id,
  card.policy.version])` (D56). The key is collision-free by construction:
  the independent review (IR-P16) proved the drafted delimiter-joined form
  collides on legal colon-bearing lint-clean ids, so the digest form — the
  same pattern the Runtime uses for compensation keys — is ratified
  instead. The committed path is `sha256(key)` hex either way; the key
  never touches the filesystem.
- **content identity** — `sop_digest(card)`, which equals the Runtime's
  `work["document_digest"]` for a lint-clean card: every existing
  digest-bound mechanism (approvals, operation admission, receipt
  validation) binds SOP content with no new plumbing.
- **version** — the card's own `policy.version` (a nonempty string,
  operator discipline). Changed content under the same version is a
  **conflict, never a mutation**; legitimate change requires a new version
  string (RFC-002 §6).

### The store

`SopPublicationStore(directory)` is a thin wrapper over the unchanged
[`FilePublisher`](file-adapter.md) (D55): it delegates `execute`/`lookup`
verbatim and declares its own contract with `actions=("sop.publish",)` and
keyed uniqueness — exactly one artifact per publication key, same-key
changed content refused with zero overwrite (D60). Immutability,
hash-naming, race and corruption semantics are inherited wholesale from the
file adapter; the trusted-local directory boundary applies unchanged.
**There is no withdrawal in this slice** (D63): the store is append-only,
and "rolling back" a publication means publishing a corrected new version.

### Loading and pinning (fail-closed, D62)

Reading a publication back is a set of functions with **no Runtime wiring**
and no card-to-policy compilation — a published card is the reviewable
specification and content identity of record, never executable authority:

| function | behavior |
|---|---|
| `load_published_card(directory, policy_id, policy_version)` | Reads the hash-named artifact through `FilePublisher.read_validated`, re-lints the stored card, recomputes `sop_digest` against the stored `content_digest` and receipt, and checks the stored identity against the request. Returns the bare stored card. |
| `pinned_card(directory, policy_id, policy_version, expected_digest)` | Additionally requires the recomputed digest to equal the operator's pin — the explicit cross-check that the engineered Python policy version being loaded corresponds to the published card of record. |
| `published_card_matches(card, policy)` | Structural `(id, version, goal)` cross-check between a published card and a Python policy object. Partial by design: capabilities have no runtime counterpart (grants decide execution authority) and are never compared. |

The fail-closed matrix: an absent version (including a missing store
directory — a read never creates it), corrupt bytes, a digest mismatch, or
a card whose identity does not match the request each raise a **bounded,
distinguishable `ValueError`**; there is no fallback and nothing degrades
to an unpinned card. A store directory shared across runtime databases can
therefore contain foreign content under a publication key — the loader
refuses it rather than loading it (an accepted operator-discipline
boundary, MD-4); two databases sharing one directory also fail closed at
reconcile (`ADAPTER_RESULT_INVALID` + `needs_attention`, never an
overwrite). Making the Runtime itself consult the store at construction is
deliberately rejected: it would create the card→policy binding the
[contributor guide](contributor-guide.md) disclaims.

### The governed flow (write path)

`SopPublicationPolicy` is the ``sop.publish`` family riding the unchanged
command protocol in its own database: `create_work` with the card as the
work document → `bind_contract` → signed `card_approval` through the
unchanged [`SignedEvidenceGateway`](signed-evidence.md) → `verify_pending`
→ `propose_action` → `dispatch` through `SopPublicationStore` →
`reconcile` on uncertainty → `request_completion`.

- **Admission lint (D57):** `create_work` lints the card through
  `validate_document` — a dirty card is refused with a bounded,
  *unpersisted* `ValueError` (the house convention for malformed
  documents), and a clean card's `work["document_digest"]` equals
  `sop_digest(card)` exactly.
- **Requirements:** two, mirroring the publishing domain. **S02** — the
  configured authority (`sop-owner`, a trusted-local principal holding
  `evidence.write`) must have approved the *current* content digest;
  **S03** — the store must have accepted the current content, satisfied by
  the runtime-written `accepted` proof and excluded from blockers exactly
  like C04. A missing, wrong-digest or wrong-version approval leaves S02
  pending and blocks the proposal (`REQUIREMENT_UNSATISFIED`).
- **The approval is evidence, not a grant check (D58):** a signed envelope
  of kind `card_approval` whose `data` is exactly
  `{"digest": <sop_digest>, "policy_version": <card version>}` — the
  version-bound shape proven by the expense family's stronger policy. A
  tampered envelope is refused `EVIDENCE_AUTHENTICATION_FAILED` with zero
  intake writes; a correctly-signed wrong-version approval lands as a
  candidate but never verifies against the card's version; a
  correctly-signed wrong-digest approval verifies on shape but leaves S02
  unsatisfied because the digest does not bind the current content. The
  store's acceptance is *not* approval: the Runtime writes the `accepted`
  proof itself when resolving the confirmed effect, under the family's
  `sop-store` source (absent from grants — signed ingress refuses that
  kind outright), with `event_id` = the operation id.
- **The stored document is the bare card (D59):** the committed artifact's
  `document` is the card itself — no envelope change; the runtime evidence
  store is the approval audit.
- **Replay, idempotency and conflict (D66, pinned order):** the three
  existing layers compose with no new machinery. Command dedup replays the
  stored receipt while authority holds. `operation_key` returns the
  publication key, so one publication identity exists per card version per
  database. Because `_propose` checks requirement blockers **before** the
  business-key branch, a second work proposing the same `(policy id,
  version)` — the same card or a doctored variant — is first refused
  `REQUIREMENT_UNSATISFIED` while its own approval is missing, and only
  after that work records and verifies its **own** approval does the
  persisted `OPERATION_CONTENT_CONFLICT` surface; the committed artifact is
  never touched. A response lost after the store commits is recovered by
  reconciling the original key — one attempt, nothing resent. Within one
  work the card document is effectively immutable: `revise_document`
  requires a top-level document `id` which cards do not have, content
  changes enter as new works, and legitimate change requires a new version
  string — RFC-002 §6's model.
- **Approver rotation** follows the S11 configuration semantics unchanged
  (reconstruct the gateway from a rotated keyring): an old-key envelope is
  refused `EVIDENCE_KEY_RETIRED` (key retained, past its window) or
  `EVIDENCE_AUTHENTICATION_FAILED` (key dropped); the same `command_id`
  re-signed under the new key replays the original receipt verbatim;
  publication history — committed artifacts and runtime tables — is
  untouched by the rotation acts themselves.

### Demonstration (`publication-demo`)

`python3 -m work_runtime publication-demo [--directory DIR]` runs the whole
ratified story (design §11) deterministically in one fresh temporary
directory, no credentials and no network: a dirty fixture card is refused by
lint; the packaged `publishing.json` card is lint-clean with its pinned
digest and becomes the work document; the proposal blocks on S02; a tampered
`card_approval` is refused `EVIDENCE_AUTHENTICATION_FAILED` with zero intake
writes; the valid signed `{digest, policy_version}` approval verifies and
the intent is accepted; dispatch commits exactly one hash-named artifact and
loses the response; a restart reconciles the original key in one attempt to
`confirmed_succeeded`; the `accepted` proof is runtime-written under
`sop-store` with `event_id` = the operation id; completion closes the work
`succeeded`; a doctored same-version card is first blocked
`REQUIREMENT_UNSATISFIED` (the D66 order) and only after its own approval
persists `OPERATION_CONTENT_CONFLICT` with the winner artifact bytes
unchanged; the loader returns the card with its matching digest while an
absent version and a tampered file fail closed with distinguishable bounded
errors; and an approver-key rotation refuses the retired old-key envelope
`EVIDENCE_KEY_RETIRED` with all six runtime tables and the artifact bytes
untouched.

The approver keys are ephemeral in-memory random bytes for the run, never
printed or persisted — only key ids appear in the output. Every printed
count is asserted inside the demo against the real SQLite store and the
artifact directory, never against the narration; `tests/test_publication_demo.py`
and the installed verifier re-derive the counts, keys, digests and receipts
independently (planted-marker tests prove the secrets never reach the
output). The demo prints an `inspect --db … --work pub-1 --policy
sop-publish` command plus the committed artifact path; the `sop-publish`
inspect choice loads `SopPublicationPolicy` with the demo grants (added with
master authorization after a probe showed the pre-existing choices fail
closed on a sop-publish-family database).

The limits are unchanged and stated plainly: approvers and publishers are
trusted-local principals in grants configuration, not authentication;
rotation is config-only trust (a configuration rollback revives an old key);
there is no withdrawal in this slice (D63), no tenant authentication, TLS,
KMS, network or distributed exactly-once claim; and published cards never
execute (D62).

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
