"""Declared adapter contracts and receipt validation.

Contract fields are assertions the adapter's owner makes about the external
system. They are configuration for trusted local code, not remotely verified
guarantees; declaring metadata does not authenticate an adapter.
"""

from dataclasses import dataclass
from typing import Tuple

_ACCEPTED_STATUSES = ("accepted", "rejected")


@dataclass(frozen=True)
class AdapterContract:
    """Adapter assertions consumed by dispatch and conformance tests."""

    actions: Tuple[str, ...]
    idempotency_scope: str
    retention: str
    lookup_consistency: str
    uniqueness: Tuple[str, ...]

    def __post_init__(self):
        _check_invariants(self)


def _check_invariants(contract: "AdapterContract") -> None:
    actions = contract.actions
    if not isinstance(actions, tuple) or not actions:
        raise ValueError("actions must be a nonempty tuple of action names")
    if not all(isinstance(action, str) and action for action in actions):
        raise ValueError("every action must be a nonempty string")
    if len(set(actions)) != len(actions):
        raise ValueError("actions must be unique")
    for name in ("idempotency_scope", "retention", "lookup_consistency"):
        value = getattr(contract, name)
        if not isinstance(value, str) or not value:
            raise ValueError(name + " must be a nonempty string")
    uniqueness = contract.uniqueness
    if not isinstance(uniqueness, tuple):
        raise ValueError("uniqueness must be a tuple of field names")
    if not all(isinstance(entry, str) and entry for entry in uniqueness):
        raise ValueError("every uniqueness entry must be a nonempty string")
    # An empty uniqueness tuple is valid: it asserts no additional uniqueness
    # promise beyond idempotent replay of the same key.


def valid_contract(value: object) -> bool:
    """True when value is an AdapterContract whose declared invariants hold."""
    if not isinstance(value, AdapterContract):
        return False
    try:
        _check_invariants(value)
    except (ValueError, AttributeError):
        # ValueError: invariant violation; AttributeError: an incomplete
        # instance whose fields were never set (e.g. object.__new__ bypass).
        return False
    return True


def receipt_is_valid(result: object, expected_digest: str) -> bool:
    """Authoritative-result shape check used by Runtime resolution.

    A result counts only when it is a dict whose digest equals the
    operation's document digest, whose status is accepted or rejected and
    whose external_id is a nonempty string. Extra fields remain allowed.
    """
    return (isinstance(result, dict)
            and result.get("digest") == expected_digest
            and result.get("status") in _ACCEPTED_STATUSES
            and isinstance(result.get("external_id"), str)
            and bool(result["external_id"]))
