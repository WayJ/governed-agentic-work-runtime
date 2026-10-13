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
