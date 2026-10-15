"""Governed SOP rule-card publication: store wrapper, policy, loader and pin.

A publication is one committed immutable artifact in a trusted-local
directory, produced by a governed ``sop.publish`` Work on the unchanged
command protocol behind a signed, version-bound authority approval
(ratified design D54–D66; see docs/sop-authoring.md). The commit engine is
:class:`~work_runtime.file_adapter.FilePublisher` unchanged — this module
adds the publication key, a thin contract-declaring wrapper, the governing
policy family and fail-closed read functions.

Trust boundaries, stated plainly: approvers and publishers are configured
local principal names, not authenticated identities; signed ingress
authenticates sources within a shared-key boundary only. Nothing here is a
security, TLS, KMS or distributed exactly-once claim. Published cards never
execute: the loader and pin are explicit operator checks with no Runtime
wiring and no card-to-policy compilation (D62). There is no withdrawal in
this slice (D63); approver-key rotation follows the S11 configuration
semantics and never touches publication history.
"""

from .adapter_contract import AdapterContract
from .file_adapter import FilePublisher
from .policy import digest

PUBLICATION_KEY_PREFIX = "sop-pub:"

KEY_IDENTITY_MESSAGE = ("publication identity requires nonempty string "
                        "policy id and version")
KEY_CARD_MESSAGE = "publication key requires a card with a policy id and version"


def _identity_key(policy_id, policy_version):
    """Collision-free store key for one (policy id, version) pair (D56).

    The digest form replaces the drafted delimiter-joined key, which
    IR-P16 proved collides on legal colon-bearing ids. The committed path
    is ``sha256(key)`` either way, so callers see only this opaque form.
    """
    if (type(policy_id) is not str or not policy_id
            or type(policy_version) is not str or not policy_version):
        raise ValueError(KEY_IDENTITY_MESSAGE)
    return PUBLICATION_KEY_PREFIX + digest([policy_id, policy_version])


def publication_key(card):
    """The publication key of a rule card (its policy identity, D56).

    Bounded ``ValueError`` when the card does not carry a usable policy
    identity; the message names the requirement, never the card content.
    The whole card is linted at work admission and re-linted by the loader
    — this function only derives the store identity.
    """
    policy = card.get("policy") if isinstance(card, dict) else None
    if not isinstance(policy, dict):
        raise ValueError(KEY_CARD_MESSAGE)
    try:
        return _identity_key(policy.get("id"), policy.get("version"))
    except ValueError:
        raise ValueError(KEY_CARD_MESSAGE) from None


class SopPublicationStore:
    """Thin publication wrapper over an unchanged ``FilePublisher`` (D55).

    Delegates ``execute``/``lookup`` verbatim and declares its own contract
    so dispatch's action check admits the ``sop.publish`` capability without
    touching the pinned adapter or its conformance tests. Immutability,
    hash-naming, race and corruption semantics are inherited wholesale from
    docs/file-adapter.md; the wrapper adds none of its own.
    """

    # Declared assertions for trusted local configuration, not guarantees.
    # Keyed uniqueness (D60): exactly one artifact per publication key, with
    # same-key changed content refused by the delegate — the three verified
    # conflict layers are proposal business-key, command-id reuse and this
    # store refusal.
    contract = AdapterContract(
        actions=("sop.publish",),
        idempotency_scope="directory:publication-key",
        retention="lifetime-of-directory",
        lookup_consistency="authoritative-by-key",
        uniqueness=("publication.key",))

    def __init__(self, directory):
        self.publisher = FilePublisher(directory)

    def execute(self, key, document, content_digest):
        return self.publisher.execute(key, document, content_digest)

    def lookup(self, key):
        return self.publisher.lookup(key)
