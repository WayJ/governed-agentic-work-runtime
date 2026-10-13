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
from typing import Callable, Dict

from .policy import canonical

SIGNED_FIELDS = ("command_id", "data", "event_id", "issued_at", "kind", "source", "work_id")
ENVELOPE_FIELDS = frozenset(SIGNED_FIELDS) | {"signature"}
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
    if set(message) != set(SIGNED_FIELDS):
        return "message requires exactly the signed fields"
    if type(message["issued_at"]) is not int:
        return "issued_at must be an integer epoch second, not bool"
    if not isinstance(message["data"], dict) or not _json_native(message["data"]):
        return "data must be a JSON-native object"
    for field in _IDENTITY_FIELDS:
        if not isinstance(message[field], str) or not message[field]:
            return field + " must be a nonempty string"
    return None


def _canonical_bytes(message):
    """Canonical UTF-8 bytes of the message; raises on non-serializable input."""
    return canonical(message).encode("utf-8")


def _validate_secret(secret):
    if not isinstance(secret, bytes):
        raise ValueError("secret must be bytes")
    if len(secret) < MIN_SECRET_BYTES:
        raise ValueError("secret must be at least %d bytes" % MIN_SECRET_BYTES)


def _signature(secret, encoded):
    return hmac.new(secret, encoded, hashlib.sha256).hexdigest()


def sign_evidence(secret: bytes, message: dict) -> dict:
    """Return a detached signed envelope for ``message``; never mutate the input.

    Raises ValueError for an invalid key, message shape or canonicalization
    failure (D8 B1). The returned envelope is a fresh JSON-native copy: later
    mutations of the caller's message cannot change what was signed.
    """
    _validate_secret(secret)
    problem = _message_problem(message)
    if problem is not None:
        raise ValueError(problem)
    encoded = _canonical_bytes(message)
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
    if not isinstance(envelope, dict) or set(envelope) != set(ENVELOPE_FIELDS):
        return None, None, "envelope requires exactly the signed fields plus signature"
    message = {field: envelope[field] for field in SIGNED_FIELDS}
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
    """

    def __init__(self, runtime, keys: Dict[str, bytes], max_age: int = 300,
                 clock: Callable = time.time):
        if not isinstance(keys, dict):
            raise ValueError("keys must map source names to bytes")
        material = []
        for name, secret in keys.items():
            if not isinstance(name, str) or not name:
                raise ValueError("source names must be nonempty strings")
            _validate_secret(secret)
            material.append(secret)
        if len(set(material)) != len(material):
            raise ValueError("each source requires distinct key material")
        if type(max_age) is not int or max_age < 0:
            raise ValueError("max_age must be a nonnegative integer, not bool")
        if not callable(clock):
            raise ValueError("clock must be callable")
        self.runtime = runtime
        self.keys = dict(keys)
        self.max_age = max_age
        self.clock = clock

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
        secret = self.keys.get(message["source"])
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
