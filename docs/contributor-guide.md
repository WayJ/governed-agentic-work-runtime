# Contributor guide: adapters and SOP rule cards

Updated: 2026-10-14 (S4 adoption wave) · Audience: a contributor extending this runtime from its public interfaces, without touching lifecycle internals.

This guide shows how to (A) implement a third-party-style adapter and pass the reusable conformance tests, (B) author and lint a static SOP rule card, and (C) walk the adoption harness that ties them together. Everything here uses documented public surfaces only — the same bar an independent implementer meets without reading the lifecycle source.

Read the boundaries first; they are part of the interface:

- **Static lint is not executable authority.** `lint-sop` performs structural review of a rule card and prints an exact content digest. It never executes textual predicates, never verifies provenance, and a lint-clean card is not a `Policy` the Runtime loads. The demos run engineered Python policies (`ExpensePolicy`, `PublishingPolicy`); no JSON card is compiled or executed.
- **Everything here is trusted-local.** Principal names, grants, owners and adapter directories are local configuration, not authentication. There is no tenant model, no network service, and no remote verification of adapter claims.
- **Adapters declare, they do not prove remotely.** An `AdapterContract` is an assertion for trusted local code. The filesystem adapter additionally requires hardlink support and declares best-effort directory fsync only — no power-loss, hostile-filesystem/symlink, or distributed exactly-once guarantees anywhere in this project.

## Quick tour

```bash
python3 -m work_runtime demo                # real crash-and-recovery demonstration
python3 -m work_runtime adoption-demo       # lint + file-adapter adoption (this wave)
python3 -m unittest discover -s tests -v    # full suite
python3 scripts/check_docs.py               # documentation link gate
```

## Part A — implement an adapter

The Runtime drives external effects through a two-method protocol (`work_runtime.runtime.Adapter`):

```python
class Adapter(Protocol):
    def execute(self, key: str, document: dict, content_digest: str) -> dict: ...
    def lookup(self, key: str) -> Optional[dict]: ...
```

- `execute(key, document, content_digest)` performs the side effect idempotently under `key` and returns a receipt dict `{"status": "accepted", "external_id": <nonempty str>, "digest": content_digest}` (an external id and the digest you were given). Replaying the same key with the same content must return the identical receipt without a second effect; the same key with different content must raise `ValueError` instead of overwriting.
- `lookup(key)` is authoritative for the committed by-key artifact: the committed receipt, or `None` when nothing was committed. A lost response leaves the Runtime with an unknown outcome; it reconciles by calling `lookup` on the original business key — never by resubmitting.

Declare what your adapter claims with `work_runtime.adapter_contract.AdapterContract` (see [adapter contract](adapter-contract.md) for the field meanings and receipt validation rules):

```python
from work_runtime.adapter_contract import AdapterContract

contract = AdapterContract(
    actions=("content.publish",),          # capabilities this adapter accepts
    idempotency_scope="directory:key",     # what a key is unique within
    retention="lifetime-of-directory",     # how long effects are kept
    lookup_consistency="authoritative-by-key",
    uniqueness=(),                         # no document-content uniqueness promise
)
```

### A worked minimal adapter

A complete teaching adapter — one JSON receipt file per key under a directory (the hardened, atomically-committed reference version is [`FilePublisher`](file-adapter.md)):

```python
import hashlib
import json
import os


class AuditFilePublisher:
    """Teaching adapter: one JSON receipt file per idempotency key."""

    contract = AdapterContract(actions=("content.publish",),
                               idempotency_scope="directory:key",
                               retention="lifetime-of-directory",
                               lookup_consistency="authoritative-by-key",
                               uniqueness=())

    def __init__(self, directory):
        self.directory = directory
        os.makedirs(self.directory, exist_ok=True)

    def _path(self, key):
        # Never use the caller key as a path: hash it to a safe basename.
        name = hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json"
        return os.path.join(self.directory, name)

    def execute(self, key, document, content_digest):
        if not isinstance(key, str) or not key:
            raise ValueError("idempotency key must be a nonempty string")
        path = self._path(key)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                receipt = json.load(handle)
            if receipt["digest"] != content_digest:
                raise ValueError("idempotency key reused with different content")
            return receipt
        receipt = {"status": "accepted",
                   "external_id": "AUDIT-" + hashlib.sha256(key.encode()).hexdigest()[:12],
                   "digest": content_digest}
        temporary = path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(receipt, handle, sort_keys=True)
        os.replace(temporary, path)  # single-process teaching commit; see note
        return receipt

    def lookup(self, key):
        path = self._path(key)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
```

Teaching shortcuts, on purpose: `os.replace` can overwrite a concurrent winner (the reference adapter commits through an exclusive `os.link` instead, so racing processes produce exactly one artifact), the receipt is written without pre-validating the document against `content_digest`, and there is no fsync. Before proposing a real adapter, copy the gate and commit discipline from [`work_runtime/file_adapter.py`](file-adapter.md), and declare your metadata honestly — `uniqueness` is what you actually enforce, not what sounds good.

### Pass the reusable conformance tests

Put your adapter and its tests in the repository (for a disposable exercise, a fresh checkout) and adopt the mixin — implement exactly these four fixture hooks:

```python
import tempfile
import unittest
from pathlib import Path

from tests.adapter_conformance import AdapterConformanceMixin


class AuditFilePublisherConformanceTests(AdapterConformanceMixin, unittest.TestCase):
    def make_adapter(self):
        # Fresh, disposable fixture per test — the tests mutate the store.
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        return AuditFilePublisher(str(Path(self._temp.name) / "audit"))

    def sample_document(self):
        return {"id": "DOC-1", "title": "t", "body": "b", "requires_review": True}

    def changed_document(self):
        return {"id": "DOC-1", "title": "t2", "body": "b", "requires_review": True}

    def effect_count(self, adapter):
        # Count the real external effect, never an internal counter.
        return len(list(Path(adapter.directory).glob("*.json")))
```

Run from the repository root:

```bash
python3 -m unittest tests.test_audit_adapter -v
```

The mixin then proves: your declared contract is a valid frozen `AdapterContract`; same-key replay returns the identical receipt with exactly one external effect; the same key with different content raises `ValueError` without a new effect; `lookup` returns the committed receipt and `None` for a missing key. Test your domain's own rules (uniqueness beyond key idempotency, corruption handling, restart) separately, the way [the file adapter's suite](file-adapter.md#verification) does.

### How the Runtime treats your adapter

A declared `contract` is checked at dispatch: an operation whose capability is not in `actions` is held with `ADAPTER_ACTION_UNSUPPORTED` and zero external calls. When your `execute` raises — including a simulated response loss — the attempt is recorded as `outcome_unknown`, and reconciliation calls `lookup` with the original business key. An invalid result from `lookup`/`execute` quarantines the operation (`needs_attention`) rather than guessing. Do not build retry storms into adapters; the single coordinator resolves uncertainty by query.

## Part B — author an SOP rule card

A rule card is a JSON document recording reviewable policy: exact required fields, pinned handling values, declared facts/collections/rules and their references. The schema, the exactly-14 diagnostic codes and the digest rules are specified in [SOP authoring](sop-authoring.md).

The packaged cards are the single source of valid examples and ship inside the package — read them through `importlib.resources`, never by relative path from the checkout:

```python
import importlib.resources
import json

raw = (importlib.resources.files("work_runtime")
       .joinpath("data", "sop", "publishing.json").read_bytes())
card = json.loads(raw.decode("utf-8"))
```

Invalid fixtures covering every diagnostic family live under [examples/sop](../examples/sop/).

### Lint from the command line

```bash
python3 -m work_runtime lint-sop path/to/card.json        # human output
python3 -m work_runtime lint-sop path/to/card.json --json # machine output
```

Exit codes: `0` lint-clean, `1` lint diagnostics, `2` file-level failure (unreadable file, larger than 1 MiB, invalid UTF-8, malformed JSON, duplicate object keys, non-finite number literals, or nesting too deep to parse). Loader failures print bounded static messages — never your file's contents.

The `--json` envelope is exactly:

```json
{"valid": false, "digest": null,
 "diagnostics": [{"code": "EMPTY_VALUE", "path": "/policy/goal",
                  "message": "string is empty or whitespace-only"}],
 "scope": "static-only"}
```

A clean card prints `"valid": true` with the canonical SHA-256 `digest` of its exact content (object key order never matters, any content change does). The digest ties a human review to the exact submitted bytes; it grants nothing else. Authoring a card, having it reviewed and linting it clean does **not** make it executable, authoritative or published — the publication process is a roadmap follow-up, not part of this project.

## Part C — the adoption harness

`python3 -m work_runtime adoption-demo` runs the whole adoption story on fresh temporary stores (nothing is deleted, no credentials, deterministic output):

1. An intentionally invalid demo card produces bounded diagnostics (`lint-sop` exit 1 class).
2. The two packaged cards lint clean with their exact digests (exit 0 class) — with the explicit reminder that the Runtime executes the engineered `PublishingPolicy`, never the linted JSON.
3. A publication proposal is blocked by the review requirement (C02).
4. A tampered HMAC-signed reviewer approval is rejected before any intake write.
5. Valid signed approvals stay candidates until verified, then the intent is accepted.
6. The real [`FilePublisher`](file-adapter.md) commits one hash-named JSON artifact; a composition wrapper loses the response after the commit → outcome unknown, artifact on disk.
7. A restarted Runtime reconciles the original business key → confirmed succeeded, nothing resent.
8. Evidence-backed completion → the work closes `succeeded`; committed file artifacts: 1.

The demo prints an `inspect` command for the durable history and the committed artifact's path — both work verbatim. `scripts/verify_install.py` re-runs this demo from a fresh non-editable install (module and console entry points, outside the checkout) and independently enumerates and parses the artifact rather than trusting the printed text.

## What we do not claim

- Lint-clean means structurally reviewable, nothing more. No textual-predicate execution, no semantic consistency proof, no provenance verification, no publication authority.
- Adapter contracts and demo identities are trusted-local configuration. No remote authentication, tenant authorization, transport security or business-truth proof.
- The filesystem adapter is for trusted local directories. Hardlink support is required, directory fsync is best-effort (POSIX), and there is no power-loss, hostile-filesystem, symlink or distributed exactly-once guarantee. See [platform boundaries](file-adapter.md#platform-and-scope-boundaries).
- Guide exercises performed by an AI agent are agent rehearsals — recorded as such, they are not external human adoption feedback, which remains uncollected.

## Related

- [Adapter contract](adapter-contract.md) — receipt validation and the conformance mixin contract.
- [File adapter](file-adapter.md) — the hardened reference adapter and its verification suite.
- [SOP authoring](sop-authoring.md) — the rule-card schema, diagnostic codes and digest semantics.
- [Signed evidence](signed-evidence.md) — the HMAC ingress trust boundary.
- [Verification](verification.md) — what is actually tested, and what is explicitly deferred.
