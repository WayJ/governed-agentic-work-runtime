# File adapter (`FilePublisher`)

The third adapter on the unchanged Runtime lifecycle (`work_runtime/file_adapter.py`).
Its external effect is real: one immutable JSON artifact per idempotency key on
the local disk. The single-coordinator Runtime, policies and dispatch/reconcile
protocol are untouched — see [adapter-contract.md](adapter-contract.md) for the
shared declared-contract machinery this adapter adopts.

**Trust boundary, stated plainly:** the directory is trusted local
configuration. `FilePublisher` makes no hostile-filesystem, symlink, or
path-traversal *security* claim (its safety is structural — see naming below),
no power-loss durability guarantee, and no distributed exactly-once claim. Its
contract is an assertion for trusted local code, exactly like every other
adapter contract; it does not authenticate anything.

## Declared contract

```python
AdapterContract(actions=("content.publish",),
                idempotency_scope="directory:key",
                retention="lifetime-of-directory",
                lookup_consistency="authoritative-by-key",
                uniqueness=())
```

| value | assertion |
|---|---|
| `actions=("content.publish",)` | executes only the content publish capability |
| `idempotency_scope="directory:key"` | the key is scoped to this one directory |
| `retention="lifetime-of-directory"` | artifacts live as long as the directory |
| `lookup_consistency="authoritative-by-key"` | `lookup` reports the committed by-key artifact |
| `uniqueness=()` | **no** document-content uniqueness promise beyond key replay — the same content under two keys commits two artifacts |

## Storage layout

- The directory is created (`mkdir -p`) by the constructor; `FilePublisher(directory)`
  takes exactly one argument — there is deliberately no crash, timeout or fault
  constructor flag anywhere in this module.
- Committed artifact path: `<directory>/<sha256(key UTF-8)><.json>` — a fixed
  64-hex basename. The caller key and any document id are **never** used as a
  path, so keys like `"../../etc/passwd"` or `"a/b"` cannot escape the
  directory: hashing bounds every basename to safe hex by construction.
- Staging files are `<32-hex uuid>.stage` in the same directory. A crash before
  commit can leave only such staging files behind; they are ignorable and are
  never read, cleaned up by other processes, or counted as committed artifacts.

## Committed artifact shape

The committed bytes are the canonical JSON (`policy.canonical`, UTF-8) of
exactly:

```json
{"artifact_version": 1,
 "key": "<original key>",
 "content_digest": "<sha256 of the canonical document>",
 "document": { ... detached canonical snapshot ... },
 "receipt": {"status": "accepted",
             "external_id": "FILE-<32 hex>",
             "digest": "<content_digest>"}}
```

- `artifact_version` is strictly integer `1` (a JSON `true` or `1.0` is a
  validation error).
- `receipt` has exactly `status`, `external_id`, `digest`; `external_id` is
  nonempty and starts `FILE-`. The uuid is chosen when the staged artifact is
  built; the **winning** staged commit's uuid is the durable one, so racing
  staging files may differ but the committed bytes never change after commit.

## Publish protocol (`execute`)

`execute(key, document, content_digest)` validates everything before touching
the filesystem:

1. **Key gate** — the key must be a nonempty string that encodes to UTF-8
   (lone surrogates rejected). Bounded `ValueError` otherwise.
2. **Digest argument gate** — `content_digest` must be a nonempty string.
3. **JSON-native gate + one detached snapshot** (see below) — bounded
   `ValueError` on any violation.
4. **Digest validation** — the snapshot is serialized exactly once and hashed;
   a mismatch with `content_digest` raises `ValueError` before any I/O.
5. **Commit** — write the artifact bytes to an exclusive `.stage` file in the
   same directory (`open(..., "xb")`), `flush()` + `os.fsync()`, then
   `os.link(stage, final)`. The link is the atomic, non-overwriting commit:
   there is no rename fallback anywhere, and on filesystems without hardlink
   support the `OSError` propagates explicitly.
   - **Link lost to a racer (`FileExistsError`)** — read and fully validate the
     winner: same content → return the *winner's* receipt (stable across
     processes and restarts); different content → `ValueError`, the winner is
     never overwritten.
   - **Link won** — best-effort directory fsync (supported on POSIX, silently
     skipped where the platform refuses it — an honest platform boundary, not
     an error), then the committed file is read back, validated, and **its**
     receipt returned: the returned receipt is exactly what is durable.
6. **Cleanup** — the caller's own staging file is removed in a `finally`
   block; foreign/leftover staging files are never touched.

### Validation gate

Implemented inside this module — deliberately independent of any authoring
module (the two were developed in parallel with disjoint ownership):

- document must be a plain `dict`; exact types only (`dict`, `list`, `str`,
  `int`, `float`, `bool`, `null`) — subclasses, tuples, sets, bytes and custom
  objects are rejected;
- dict keys must be plain nonempty UTF-8 strings; strings must encode to
  UTF-8 (lone surrogates rejected);
- floats must be finite; integers bounded to `abs(value) <= 2^53 - 1`
  (booleans pass as JSON booleans, not integers);
- container depth at most 64 (the document root dict is depth 1);
- reference cycles (detected by active-path container identity, iteratively —
  no `RecursionError`) raise `ValueError`; repeated *acyclic* aliases are
  valid and each occurrence is copied;
- the walk produces **one detached plain snapshot**: after `execute` returns,
  caller mutations of the submitted document cannot change the committed
  artifact, and nothing the adapter returns aliases caller objects.

Every validation failure is a bounded `ValueError` whose message names the
violation class only — key and document content are never echoed.

## Query protocol (`lookup`)

`lookup(key)` applies the same key gate, then:

- no committed artifact → `None` (Runtime reconciles this as
  `NO_AUTHORITATIVE_RESULT`);
- otherwise the file is parsed and **fully validated**: exact five keys,
  strict integer `artifact_version` 1, stored `key` equal to the requested
  key, stored document re-passing the JSON-native gate with its digest
  **recomputed from the actual stored contents** (a receipt field alone is
  never trusted), and the receipt shape checked against the recomputed digest.
  Any corruption — invalid JSON/UTF-8, wrong shape, wrong key, tampered
  digest, bad version, malformed receipt — raises a bounded `ValueError`
  naming the violation class only, and the file is never rewritten. The
  Runtime retains the operation as `outcome_unknown` and the work in
  `needs_attention` when this happens.

## Idempotency semantics

| call | outcome |
|---|---|
| same key + same content (any process, any later restart) | identical winning receipt, no second artifact, committed bytes unchanged |
| same key + different content | `ValueError`, zero overwrite, zero side effects |
| different key, same content | a second artifact — empty `uniqueness` promises nothing more |

One `execute` maps to at most one committed artifact; a lost response is
resolved by `lookup` of the original key, never by a resend (that is the
Runtime's reconcile protocol, unchanged here).

## Platform and scope boundaries

- Hardlink support is required (`os.link` commit); hardlink-unsupported
  volumes fail explicitly with the underlying `OSError` — no rename fallback.
- Best-effort directory fsync: supported on POSIX, skipped on platforms that
  refuse directory fsyncs. After a crash the artifact is either fully visible
  under its final name or not at all; the adapter does not claim what a power
  loss does to a not-yet-flushed directory entry.
- Trusted local directory only: no hostile-filesystem, symlink or concurrent
  hostile-writer defense is claimed or implemented.
- Single coordinator, single directory: nothing here implies distributed
  exactly-once or external fencing across directories or machines.

## Verification

`python3 -m unittest discover -s tests -p test_file_adapter.py -v` — real
temporary directories and real subprocesses throughout, no filesystem mocks:

| guarantee | tests |
|---|---|
| reusable conformance (contract metadata, replay, one effect, lookup) | `FilePublisherConformanceTests` (`AdapterConformanceMixin`, `effect_count` = actual hash-named file enumeration) |
| strict key / document / digest gates (tuples, subclasses, non-string keys, NaN, 2^53, lone surrogates, cycles, aliases, depth 64) | `KeyGateTests`, `DocumentGateTests`, `DigestGateTests` |
| commit layout, replay/restart receipt stability, changed-content refusal, traversal keys, unicode round trip | `CommitTests` |
| corruption matrix (JSON/UTF-8, shape, version incl. `true`, key swap, digest recompute, receipt variants, replay-vs-corrupt-winner) | `CorruptionTests` |
| snapshot detachment from caller mutations | `SnapshotDetachmentTests` |
| staging hygiene (foreign `.stage` ignored, effect counts) | `StagingHygieneTests` |
| bounded messages (no payload echo) | `BoundedMessageTests` |
| API shape (constructor takes only `directory`; no `_exit`, no rename fallback) | `ApiShapeTests` |
| real subprocess same-key and 3-vs-3 mixed-content races: exactly one artifact, stable winning receipt, losers `ValueError` | `SubprocessRaceTests` |
| real process death before link (`os.link` wrapped with `os._exit(77)` → ignorable staging only) and after commit (outer `os._exit(78)` → one artifact, stable receipt) | `SubprocessRaceTests` |
| dispatches through the unchanged `Runtime` + `PublishingPolicy` to `confirmed_succeeded` with one committed artifact | `RuntimeDispatchTests` |

Design source: [S4 adoption design](superpowers/specs/2026-10-13-s4-adoption-design.md)
(D22 builder ratification); test conventions follow
[adapter-contract.md](adapter-contract.md).
