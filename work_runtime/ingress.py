"""HMAC-signed evidence envelopes and the authenticated ingress gateway.

``sign_evidence`` is the trusted-side signer; ``SignedEvidenceGateway`` is the
surface that may face untrusted envelope input and authenticates it before any
Runtime write. An HMAC proves source authenticity and content integrity within
a configured shared-key trust boundary only — not business truth, transport
security, or tenant authorization. Direct Runtime methods stay trusted-local.
See docs/signed-evidence.md for the boundary and its limits.
"""

import hashlib
import hmac
import json
import math
import time
from typing import Callable, Dict, NamedTuple, Optional, Tuple

from .policy import canonical

SIGNED_FIELDS = ("command_id", "data", "event_id", "issued_at", "kind", "source", "work_id")
OPTIONAL_KEY_FIELD = "key_id"
ENVELOPE_FIELDS = frozenset(SIGNED_FIELDS) | {OPTIONAL_KEY_FIELD, "signature"}
MIN_SECRET_BYTES = 32
# Runtime writes accepted-receipt evidence itself during dispatch resolution;
# signed ingress never supplies that kind (design decision M1).
RESERVED_KIND = "accepted"

CODE_ENVELOPE_INVALID = "EVIDENCE_ENVELOPE_INVALID"
CODE_AUTHENTICATION_FAILED = "EVIDENCE_AUTHENTICATION_FAILED"
CODE_EXPIRED = "EVIDENCE_EXPIRED"
CODE_KIND_UNSUPPORTED = "EVIDENCE_KIND_UNSUPPORTED"

_IDENTITY_FIELDS = ("command_id", "event_id", "kind", "source", "work_id")
_HEX_DIGITS = frozenset("0123456789abcdef")


class SourceKey(NamedTuple):
    """One named signing key in a source's configured keyring (D49/D50).

    ``key_id`` is the authenticated selector a signer may cite; ``current``
    marks the single entry that serves legacy no-selector envelopes; the
    inclusive epoch-second bounds are evaluated against the same injectable
    clock as freshness, never against a signed timestamp.
    """

    key_id: str
    secret: bytes
    current: bool = False
    not_before: Optional[int] = None
    not_after: Optional[int] = None


def _reject(code):
    # Deliberately minimal: no secret, signature or candidate content (B1).
    return {"decision": "rejected", "code": code}


def _json_native(value):
    """True when canonical JSON represents value without silent coercion (B1)."""
    if isinstance(value, dict):
        return (all(isinstance(k, str) for k in value)
                and all(_json_native(v) for v in value.values()))
    if isinstance(value, list):
        return all(_json_native(v) for v in value)
    if isinstance(value, float):
        return math.isfinite(value)
    return isinstance(value, (str, int, bool, type(None)))


def _message_problem(message):
    if not isinstance(message, dict):
        return "message must be a dict"
    present = set(message)
    if not set(SIGNED_FIELDS) <= present or present - set(SIGNED_FIELDS) - {OPTIONAL_KEY_FIELD}:
        return "message requires exactly the signed fields, optionally key_id"
    if type(message["issued_at"]) is not int:
        return "issued_at must be an integer epoch second, not bool"
    if not isinstance(message["data"], dict) or not _json_native(message["data"]):
        return "data must be a JSON-native object"
    for field in _IDENTITY_FIELDS:
        if not isinstance(message[field], str) or not message[field]:
            return field + " must be a nonempty string"
    if OPTIONAL_KEY_FIELD in message:
        key_id = message[OPTIONAL_KEY_FIELD]
        if not isinstance(key_id, str) or not key_id:
            return "key_id must be a nonempty string"
    return None


def _canonical_bytes(message):
    """Canonical UTF-8 bytes of the message; raises on non-serializable input."""
    return canonical(message).encode("utf-8")


def _validate_secret(secret):
    if not isinstance(secret, bytes):
        raise ValueError("secret must be bytes")
    if len(secret) < MIN_SECRET_BYTES:
        raise ValueError("secret must be at least %d bytes" % MIN_SECRET_BYTES)


def _validated_ring(entries):
    """Validate one configured keyring; return its immutable normalized tuple.

    Exact types throughout (D50/F3): bool never passes as int, plain
    tuples/strings never pass as SourceKey, and the caller's sequence is
    copied into a tuple so later mutations cannot reach the gateway.
    """
    seen_ids = set()
    current = None
    ring = []
    for entry in entries:
        if not isinstance(entry, SourceKey):
            raise ValueError("keyring entries must be SourceKey instances")
        if type(entry.key_id) is not str or not entry.key_id:
            raise ValueError("key_id must be a nonempty string")
        if type(entry.secret) is not bytes or len(entry.secret) < MIN_SECRET_BYTES:
            raise ValueError("keyring secrets must be bytes of at least %d bytes"
                             % MIN_SECRET_BYTES)
        if type(entry.current) is not bool:
            raise ValueError("current must be exactly true or false")
        for bound in (entry.not_before, entry.not_after):
            if bound is not None and type(bound) is not int:
                raise ValueError("key validity bounds must be None or integer epoch "
                                 "seconds, not bool")
        if (entry.not_before is not None and entry.not_after is not None
                and entry.not_before > entry.not_after):
            raise ValueError("not_before must not exceed not_after")
        if entry.key_id in seen_ids:
            raise ValueError("keyring key ids must be unique within their source")
        seen_ids.add(entry.key_id)
        if entry.current:
            if current is not None:
                raise ValueError("keyring requires exactly one current entry")
            current = entry
        ring.append(entry)
    if current is None:
        raise ValueError("keyring requires exactly one current entry")
    return tuple(ring)


def _signature(secret, encoded):
    return hmac.new(secret, encoded, hashlib.sha256).hexdigest()


def sign_evidence(secret: bytes, message: dict) -> dict:
    """Return a detached signed envelope for ``message``; never mutate the input.

    Raises ValueError for an invalid key, message shape or canonicalization
    failure (D8 B1). The returned envelope is a fresh JSON-native copy: later
    mutations of the caller's message cannot change what was signed.
    """
    _validate_secret(secret)
    try:
        problem = _message_problem(message)
        encoded = None if problem is not None else _canonical_bytes(message)
    except RecursionError:
        # Self-referencing or pathologically deep data is invalid input, not a
        # crash: honor the D8 B1 ValueError misuse contract (as record does).
        problem = "message contains a reference cycle or exceeds the serialization depth"
    if problem is not None:
        raise ValueError(problem)
    envelope = json.loads(encoded)
    envelope["signature"] = _signature(secret, encoded)
    return envelope


def _open_envelope(envelope):
    """Read each envelope field exactly once; return (message, signature, problem).

    A problem string is static diagnostic text and never echoes candidate
    content. The single-read discipline plus the canonical snapshot in
    ``record`` guarantee the gateway authenticates and forwards the same
    bytes even if the caller passed a mutable or lying mapping.
    """
    if not isinstance(envelope, dict):
        return None, None, "envelope requires exactly the signed fields plus signature"
    present = set(envelope)
    required = set(ENVELOPE_FIELDS) - {OPTIONAL_KEY_FIELD}
    if not required <= present or not present <= set(ENVELOPE_FIELDS):
        return None, None, "envelope requires exactly the signed fields plus signature"
    message = {field: envelope[field] for field in SIGNED_FIELDS}
    if OPTIONAL_KEY_FIELD in present:
        message[OPTIONAL_KEY_FIELD] = envelope[OPTIONAL_KEY_FIELD]
    signature = envelope["signature"]
    problem = _message_problem(message)
    if problem is None:
        if (not isinstance(signature, str) or len(signature) != 64
                or not set(signature) <= _HEX_DIGITS):
            problem = "signature must be 64 lowercase hex characters"
    return message, signature, problem


class SignedEvidenceGateway:
    """Authenticates signed envelopes in front of a trusted-local Runtime.

    This is the only work_runtime surface intended to face untrusted envelope
    input. Every candidate is schema-checked, authenticated (HMAC-SHA256,
    ``compare_digest``) and freshness-checked before ``runtime.command`` is
    invoked, so intake failures persist nothing; authenticated business
    rejections keep normal Runtime receipt semantics. Configure one distinct
    random secret of at least 32 bytes per source — there is no default key.
    A source may instead be configured as a keyring (a list/tuple of
    ``SourceKey`` entries); see the keyring section of docs/signed-evidence.md
    for selection and rotation semantics.
    """

    def __init__(self, runtime, keys: Dict[str, object], max_age: int = 300,
                 clock: Callable = time.time):
        if not isinstance(keys, dict):
            raise ValueError("keys must map source names to bytes or keyrings")
        legacy_keys = {}
        keyrings = {}
        material = []
        for name, value in keys.items():
            if not isinstance(name, str) or not name:
                raise ValueError("source names must be nonempty strings")
            if isinstance(value, bytes):
                _validate_secret(value)
                legacy_keys[name] = value
                material.append(value)
            elif isinstance(value, (list, tuple)):
                if not value:
                    raise ValueError("keyring must be a nonempty list or tuple of "
                                     "SourceKey")
                keyrings[name] = _validated_ring(value)
                material.extend(entry.secret for entry in keyrings[name])
            else:
                raise ValueError("each source requires bytes or a list/tuple of "
                                 "SourceKey entries")
        if len(set(material)) != len(material):
            raise ValueError("each source requires distinct key material")
        if type(max_age) is not int or max_age < 0:
            raise ValueError("max_age must be a nonnegative integer, not bool")
        if not callable(clock):
            raise ValueError("clock must be callable")
        self.runtime = runtime
        self.keys = legacy_keys
        self.keyrings = keyrings
        self.max_age = max_age
        self.clock = clock

    def _select_key(self, source, key_id):
        """Resolve the single verification key for one candidate (D49/D51).

        Returns ``(secret, entry)`` — ``entry`` is the ``SourceKey`` for
        keyring sources (carrying its validity window for the post-HMAC
        checks) or ``None`` for legacy bytes sources; ``(None, None)`` when
        the source or the cited selector is unknown. No try-all-keys and no
        fallback: a keyring source without ``key_id`` selects its ``current``
        entry only, and a legacy bytes source rejects ``key_id`` envelopes.
        """
        ring = self.keyrings.get(source)
        if ring is not None:
            for entry in ring:
                if key_id is None:
                    if entry.current:
                        return entry.secret, entry
                elif entry.key_id == key_id:
                    return entry.secret, entry
            return None, None
        secret = self.keys.get(source)
        if secret is None or key_id is not None:
            return None, None
        return secret, None

    def record(self, envelope: dict) -> dict:
        """Authenticate one envelope and record its evidence; never raises on bad input."""
        try:
            message, signature, problem = _open_envelope(envelope)
            encoded = None if problem is not None else _canonical_bytes(message)
        except (TypeError, ValueError, RecursionError):
            # Canonicalization/UTF-8 failures (non-serializable values, lone
            # surrogates, extreme nesting) are schema failures, not crashes (B1).
            problem = "envelope cannot be canonically encoded as UTF-8"
        if problem is not None:
            return _reject(CODE_ENVELOPE_INVALID)
        secret, _entry = self._select_key(message["source"],
                                          message.get(OPTIONAL_KEY_FIELD))
        if secret is None:
            return _reject(CODE_AUTHENTICATION_FAILED)
        if not hmac.compare_digest(_signature(secret, encoded), signature):
            return _reject(CODE_AUTHENTICATION_FAILED)
        snapshot = json.loads(encoded)
        if abs(self.clock() - snapshot["issued_at"]) > self.max_age:
            return _reject(CODE_EXPIRED)
        if snapshot["kind"] == RESERVED_KIND:
            return _reject(CODE_KIND_UNSUPPORTED)
        return self.runtime.command(
            actor=snapshot["source"], command_id=snapshot["command_id"],
            work_id=snapshot["work_id"], kind="record_evidence",
            payload={"event_id": snapshot["event_id"], "kind": snapshot["kind"],
                     "data": snapshot["data"]},
            expected_version=None)
