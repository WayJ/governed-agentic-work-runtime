"""Real-filesystem content publisher: one immutable JSON artifact per key.

``FilePublisher`` is the third adapter on the unchanged Runtime lifecycle.
Its external effect is an actual file on local disk, committed atomically:
an exclusive same-directory ``.stage`` file is written and fsynced, then
hard-linked (never renamed, never overwritten) onto its final hash-named
path, and the committed bytes are read back and validated before the
receipt is returned.

The directory is trusted local configuration. This module makes no
hostile-filesystem, symlink, power-loss or distributed exactly-once claim;
the JSON-native gate below is deliberately independent of any authoring
module. See docs/file-adapter.md for the declared boundaries.
"""

import hashlib
import json
import math
import os
import uuid

from .adapter_contract import AdapterContract
from .policy import canonical

# Project interoperability bound: the document root dict is container depth 1.
MAX_DEPTH = 64
INT_LIMIT = 2 ** 53 - 1

_ARTIFACT_KEYS = {"artifact_version", "key", "content_digest", "document", "receipt"}
_RECEIPT_KEYS = {"status", "external_id", "digest"}

KEY_MESSAGE = "idempotency key must be a nonempty UTF-8 string"
DIGEST_MESSAGE = "content digest must be a nonempty string"
ROOT_MESSAGE = "document must be a plain dict"
NATIVE_MESSAGE = ("document values must be plain JSON-native types "
                  "(dict, list, str, int, float, bool, null)")
KEY_TYPE_MESSAGE = "document keys must be plain nonempty UTF-8 strings"
DEPTH_MESSAGE = "document exceeds the maximum JSON container depth of 64"
CYCLE_MESSAGE = "document contains a reference cycle"
FLOAT_MESSAGE = "document floats must be finite"
INT_MESSAGE = "document integers must be within +/-(2^53-1)"
UNICODE_MESSAGE = "document strings and keys must be UTF-8 encodable"
DIGEST_MISMATCH_MESSAGE = "content digest does not match the document"
REUSED_MESSAGE = "idempotency key is already committed with different content"
PARSE_MESSAGE = "committed artifact is not valid UTF-8 JSON"
SHAPE_MESSAGE = "committed artifact does not have the expected shape"
VERSION_MESSAGE = "committed artifact has an unsupported artifact_version"
KEY_MISMATCH_MESSAGE = "committed artifact was not committed under this key"
ARTIFACT_DIGEST_MESSAGE = "committed artifact digest does not match its document"
RECEIPT_MESSAGE = "committed artifact receipt is malformed"


def _validated_key(key):
    """Strict nonempty UTF-8 key; bounded ValueError, never the payload."""
    if type(key) is not str or not key:
        raise ValueError(KEY_MESSAGE)
    try:
        key.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(KEY_MESSAGE) from None
    return key


def _snapshot_document(document):
    """Validate JSON-native limits and return ONE detached plain copy.

    The walk is iterative: ``frames`` holds (source, target, iterator,
    depth, is_dict). ``active`` holds the ids of containers on the current
    path, so reference cycles raise ``ValueError`` while repeated acyclic
    aliases remain valid and are copied per occurrence. Exact types only —
    subclasses, tuples, sets, bytes and custom objects are rejected before
    any serialization, and error messages never echo payload content.
    """
    if type(document) is not dict:
        raise ValueError(ROOT_MESSAGE)
    root = {}
    active = {id(document)}
    frames = [(document, root, iter(document.items()), 1, True)]
    while frames:
        source, target, iterator, depth, is_dict = frames[-1]
        try:
            if is_dict:
                key, value = next(iterator)
            else:
                key, value = None, next(iterator)
        except StopIteration:
            frames.pop()
            active.discard(id(source))
            continue
        if is_dict:
            if type(key) is not str or not key:
                raise ValueError(KEY_TYPE_MESSAGE)
            _check_utf8(key)
        kind = type(value)
        if kind is dict or kind is list:
            if id(value) in active:
                raise ValueError(CYCLE_MESSAGE)
            if depth >= MAX_DEPTH:
                raise ValueError(DEPTH_MESSAGE)
            child = {} if kind is dict else []
            if is_dict:
                target[key] = child
            else:
                target.append(child)
            active.add(id(value))
            frames.append((value, child, iter(value.items()) if kind is dict
                           else iter(value), depth + 1, kind is dict))
        elif kind is str:
            _check_utf8(value)
            if is_dict:
                target[key] = value
            else:
                target.append(value)
        elif kind is float:
            if not math.isfinite(value):
                raise ValueError(FLOAT_MESSAGE)
            if is_dict:
                target[key] = value
            else:
                target.append(value)
        elif kind is int:
            if abs(value) > INT_LIMIT:
                raise ValueError(INT_MESSAGE)
            if is_dict:
                target[key] = value
            else:
                target.append(value)
        elif kind is bool or kind is type(None):
            if is_dict:
                target[key] = value
            else:
                target.append(value)
        else:
            raise ValueError(NATIVE_MESSAGE)
    return root


def _check_utf8(text):
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(UNICODE_MESSAGE) from None


def _sync_directory(directory):
    """Best-effort durability of the commit link.

    Directory fsync is supported on POSIX and skipped elsewhere; failures
    are ignored on purpose — the commit already happened, and a lost link
    durability is a platform boundary documented in docs/file-adapter.md,
    not an adapter error.
    """
    try:
        handle = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(handle)
    except OSError:
        pass
    finally:
        os.close(handle)


def _validated_artifact(raw, key):
    """Parse and fully validate committed bytes against the requested key.

    The stored document's digest is recomputed from its actual contents —
    a receipt field alone is never accepted. Every violation raises a
    bounded ValueError naming the violation class only.
    """
    try:
        artifact = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ValueError(PARSE_MESSAGE) from None
    if not isinstance(artifact, dict) or set(artifact) != _ARTIFACT_KEYS:
        raise ValueError(SHAPE_MESSAGE)
    version = artifact["artifact_version"]
    if type(version) is not int or version != 1:
        raise ValueError(VERSION_MESSAGE)
    if type(artifact["key"]) is not str or artifact["key"] != key:
        raise ValueError(KEY_MISMATCH_MESSAGE)
    content_digest = artifact["content_digest"]
    if type(content_digest) is not str or not content_digest:
        raise ValueError(SHAPE_MESSAGE)
    # Re-running the gate on the stored document bounds every parse-shaped
    # corruption (NaN literals, wrong types, cycles cannot exist in parsed
    # JSON) and gives the digest check a detached plain snapshot.
    snapshot = _snapshot_document(artifact["document"])
    if hashlib.sha256(canonical(snapshot).encode("utf-8")).hexdigest() != content_digest:
        raise ValueError(ARTIFACT_DIGEST_MESSAGE)
    receipt = artifact["receipt"]
    if (not isinstance(receipt, dict) or set(receipt) != _RECEIPT_KEYS
            or receipt["status"] != "accepted"
            or type(receipt["external_id"]) is not str or not receipt["external_id"]
            or receipt["digest"] != content_digest):
        raise ValueError(RECEIPT_MESSAGE)
    return artifact


class FilePublisher:
    """Committed JSON artifacts under ``directory``, one per idempotency key.

    Idempotency scope is this directory plus the key; retention is
    lifetime-of-directory; lookup is authoritative for the committed
    by-key artifact. ``uniqueness`` is empty: no document-content
    uniqueness promise beyond key replay. The contract is an assertion
    for trusted local code, not a remotely verified guarantee.
    """

    contract = AdapterContract(
        actions=("content.publish",),
        idempotency_scope="directory:key",
        retention="lifetime-of-directory",
        lookup_consistency="authoritative-by-key",
        uniqueness=())

    def __init__(self, directory):
        self.directory = str(directory)
        os.makedirs(self.directory, exist_ok=True)

    def _path_for(self, key):
        # The caller key is never used as a path: hashing bounds the
        # basename to safe 64 hex characters by construction.
        return os.path.join(self.directory,
                            hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json")

    def _write_stage(self, data):
        for _ in range(8):
            stage = os.path.join(self.directory, uuid.uuid4().hex + ".stage")
            try:
                with open(stage, "xb") as handle:  # exclusive: never another's stage
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                return stage
            except FileExistsError:
                continue
        raise OSError("unable to create an exclusive staging file")

    def _read_validated(self, key):
        """Read and fully validate the committed artifact for ``key``."""
        with open(self._path_for(key), "rb") as handle:
            raw = handle.read()
        return _validated_artifact(raw, key)

    def execute(self, key, document, content_digest):
        """Publish under ``key``; replay stable winner or refuse changed content."""
        key = _validated_key(key)
        if type(content_digest) is not str or not content_digest:
            raise ValueError(DIGEST_MESSAGE)
        snapshot = _snapshot_document(document)
        if hashlib.sha256(canonical(snapshot).encode("utf-8")).hexdigest() != content_digest:
            raise ValueError(DIGEST_MISMATCH_MESSAGE)
        receipt = {"status": "accepted",
                   "external_id": "FILE-" + uuid.uuid4().hex,
                   "digest": content_digest}
        artifact = {"artifact_version": 1, "key": key,
                    "content_digest": content_digest,
                    "document": snapshot, "receipt": receipt}
        data = canonical(artifact).encode("utf-8")
        final = self._path_for(key)
        stage = None
        try:
            stage = self._write_stage(data)
            try:
                os.link(stage, final)  # atomic non-overwrite commit
            except FileExistsError:
                winner = self._read_validated(key)
                if winner["content_digest"] != content_digest:
                    raise ValueError(REUSED_MESSAGE) from None
                return winner["receipt"]
            _sync_directory(self.directory)
            # Read the committed bytes back and validate before returning:
            # the returned receipt is exactly what is durable.
            return self._read_validated(key)["receipt"]
        finally:
            if stage is not None:
                try:
                    os.unlink(stage)  # own stage only; foreign stages untouched
                except FileNotFoundError:
                    pass

    def lookup(self, key):
        """Validated receipt for the committed by-key artifact, else None."""
        key = _validated_key(key)
        try:
            with open(self._path_for(key), "rb") as handle:
                raw = handle.read()
        except FileNotFoundError:
            return None
        return _validated_artifact(raw, key)["receipt"]
