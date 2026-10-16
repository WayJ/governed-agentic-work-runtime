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
wiring and no card-to-policy compilation (D62). S12 deferred withdrawal
(D63); S13 adds it additively in this module per ratified D67–D79 — a
second immutable record artifact, never a mutation of history — and
approver-key rotation follows the S11 configuration semantics, never
touching publication history.
"""

import os

from .adapter_contract import AdapterContract
from .authoring import sop_digest
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


# Withdrawal surface (S13, D67–D79): a withdrawal is a second immutable
# hash-named record artifact in the same store directory under its own
# digest-based key. The record document is the same closed four-field shape
# the governed withdrawal work carries, so the same withdrawal is
# byte-idempotent and no free text ever enters the store (D69).
WITHDRAWAL_KEY_PREFIX = "sop-withdrawn:"
WITHDRAWAL_DISCRIMINATOR = "sop.withdrawal"
WITHDRAWAL_REQUEST_KEYS = {"discriminator", "policy_id", "policy_version",
                           "published_digest"}

WITHDRAWAL_IDENTITY_MESSAGE = ("withdrawal identity requires nonempty string "
                               "policy id and version")
WITHDRAWAL_REQUEST_MESSAGE = ("withdrawal request must carry exactly the "
                              "closed discriminator, policy id, policy "
                              "version and published digest fields with "
                              "nonempty string values")
WITHDRAWN_MESSAGE = ("this published version is withdrawn; corrected "
                     "content requires a new version")
WITHDRAWAL_RECORD_INVALID_MESSAGE = ("withdrawal record for this version is "
                                     "invalid or does not bind it")

WITHDRAWAL_TARGET_ABSENT = "TARGET_PUBLICATION_ABSENT"
WITHDRAWAL_TARGET_DIGEST = "TARGET_DIGEST_MISMATCH"


def is_withdrawal_request(document):
    """True for the exact closed withdrawal record shape (D69); never raises.

    The shape is id-less and carries no free text, so it is deterministic
    given the target identity and effectively immutable: a content change
    enters as a new withdrawal request, never as a revision.
    """
    if not isinstance(document, dict) or set(document) != WITHDRAWAL_REQUEST_KEYS:
        return False
    if document.get("discriminator") != WITHDRAWAL_DISCRIMINATOR:
        return False
    return all(isinstance(document.get(field), str) and document.get(field)
               for field in ("policy_id", "policy_version", "published_digest"))


def withdrawal_key(policy_id, policy_version):
    """Collision-free store key for one withdrawn (policy id, version) (D68).

    The D56 digest form on the same identity basis as the publication key;
    the committed path is ``sha256(key)`` hex as always.
    """
    if (type(policy_id) is not str or not policy_id
            or type(policy_version) is not str or not policy_version):
        raise ValueError(WITHDRAWAL_IDENTITY_MESSAGE)
    return WITHDRAWAL_KEY_PREFIX + digest([policy_id, policy_version])


class SopWithdrawalStore:
    """Thin withdrawal wrapper over an unchanged ``FilePublisher`` (D74).

    Declares its own contract so dispatch's action check admits the
    ``sop.withdraw`` capability without touching the shipped publication
    wrapper. Immutability, hash-naming, race and corruption semantics are
    inherited wholesale; the wrapper adds one governed refusal: a record
    whose target publication artifact is absent or holds different content
    resolves as a **rejected receipt** — the governed work then resolves
    ``confirmed_failed`` and stays cancellable. The drafted ``ValueError``
    refusal channel was rejected at ratification (RV-F1): it strands the
    work at an unresolvable outcome.
    """

    # Declared assertions for trusted local configuration, not guarantees.
    contract = AdapterContract(
        actions=("sop.withdraw",),
        idempotency_scope="directory:withdrawal-key",
        retention="lifetime-of-directory",
        lookup_consistency="authoritative-by-key",
        uniqueness=("withdrawal.key",))

    def __init__(self, directory):
        self.publisher = FilePublisher(directory)

    def _rejected_receipt(self, key, content_digest, reason):
        # The refusal id is deterministic, so the same refusal is idempotent;
        # the digest binds the operation so receipt validation resolves the
        # failure truthfully instead of quarantining it.
        return {"status": "rejected",
                "external_id": "SOP-WITHDRAWAL-REFUSED-" + reason + "-"
                               + digest([key, reason]),
                "digest": content_digest,
                "reason": reason}

    def execute(self, key, document, content_digest):
        if is_withdrawal_request(document):
            target = self.publisher.read_validated(
                _identity_key(document["policy_id"],
                              document["policy_version"]))
            if target is None:
                return self._rejected_receipt(key, content_digest,
                                              WITHDRAWAL_TARGET_ABSENT)
            if target["content_digest"] != document["published_digest"]:
                return self._rejected_receipt(key, content_digest,
                                              WITHDRAWAL_TARGET_DIGEST)
        return self.publisher.execute(key, document, content_digest)

    def lookup(self, key):
        return self.publisher.lookup(key)

# Fail-closed read path (D62/D72): every failure below is a bounded ValueError
# naming the violation class only. Absence, corruption, digest mismatch,
# identity mismatch, withdrawal and an invalid withdrawal record stay
# distinguishable; nothing degrades to an unpinned card and no fallback or
# silent skip exists.
ABSENT_MESSAGE = "no published card is committed for this policy version"
DIGEST_MISMATCH_MESSAGE = "published card digest does not match the stored artifact"
IDENTITY_MISMATCH_MESSAGE = ("published card identity does not match the "
                             "requested policy version")
PIN_MESSAGE = "published digest does not match the pinned digest"
PIN_ARGUMENT_MESSAGE = "expected digest must be a nonempty string"


def _read_publication_artifact(directory, policy_id, policy_version):
    """Read and fully validate the committed artifact for one card version.

    The validation chain: derive the key, refuse a missing store directory
    without creating it, read through ``FilePublisher.read_validated``
    (absent key → ``None``), convert absence into this module's bounded
    fail-closed error, re-lint the stored card, recompute its digest against
    the stored ``content_digest`` and receipt, and check the stored identity
    against the requested one — raw adapter use can commit foreign content
    under any key, and the loader must refuse it (MD-4 discipline).
    """
    key = _identity_key(policy_id, policy_version)
    if not isinstance(directory, str) or not directory:
        raise ValueError(ABSENT_MESSAGE)
    if not os.path.isdir(directory):
        raise ValueError(ABSENT_MESSAGE)
    artifact = FilePublisher(directory).read_validated(key)
    if artifact is None:
        raise ValueError(ABSENT_MESSAGE)
    card = artifact["document"]
    card_digest = sop_digest(card)  # Bounded lint refusal for non-card content.
    if card_digest != artifact["content_digest"] or artifact["receipt"]["digest"] != card_digest:
        raise ValueError(DIGEST_MISMATCH_MESSAGE)
    policy = card["policy"]
    if policy["id"] != policy_id or policy["version"] != policy_version:
        raise ValueError(IDENTITY_MISMATCH_MESSAGE)
    record = _read_withdrawal_record(directory, policy_id, policy_version)
    if record is not None:
        # A standing record that binds this exact artifact withdraws it;
        # a record that does not bind it leaves the version under dispute
        # and is never silently served as valid (D72, fail-closed).
        if record["published_digest"] == artifact["content_digest"]:
            raise ValueError(WITHDRAWN_MESSAGE)
        raise ValueError(WITHDRAWAL_RECORD_INVALID_MESSAGE)
    return artifact


def _read_withdrawal_record(directory, policy_id, policy_version):
    """The validated withdrawal record for one version, or ``None``.

    Missing-store reads return ``None`` without creating the directory.
    Every adapter violation class on the record maps by explicit
    catch-and-re-raise onto this module's one invalid-record error, so the
    adapter's internal vocabulary never leaks as extra loader classes
    (RV-F5). A record that does not carry this version's identity is
    equally refused.
    """
    if not isinstance(directory, str) or not directory or not os.path.isdir(directory):
        return None
    try:
        artifact = FilePublisher(directory).read_validated(
            withdrawal_key(policy_id, policy_version))
    except ValueError:
        raise ValueError(WITHDRAWAL_RECORD_INVALID_MESSAGE) from None
    if artifact is None:
        return None
    record = artifact["document"]
    if (not is_withdrawal_request(record)
            or record["policy_id"] != policy_id
            or record["policy_version"] != policy_version):
        raise ValueError(WITHDRAWAL_RECORD_INVALID_MESSAGE)
    return record


def withdrawal_record(directory, policy_id, policy_version):
    """Audit read: the validated withdrawal record of record, or ``None``.

    Current validity is not negotiable at the loader, so there is
    deliberately no override parameter on the read surface — an operator
    sees *that* a version was withdrawn (and, via the governed ledger, who
    and when) through this dedicated function instead.
    """
    return _read_withdrawal_record(directory, policy_id, policy_version)


def load_published_card(directory, policy_id, policy_version):
    """The published card of record for one (policy id, version), fail-closed.

    Raises a bounded ``ValueError`` when the version is absent (including a
    missing store directory — never created by a read), the artifact is
    corrupt, the recomputed digest disagrees with the stored artifact, the
    stored card's identity does not match the request, the version is
    withdrawn (D72), or the standing withdrawal record does not bind this
    artifact. Returns the bare stored card; the approval audit lives in the
    runtime evidence store, not here (D59).
    """
    return _read_publication_artifact(directory, policy_id,
                                      policy_version)["document"]


def pinned_card(directory, policy_id, policy_version, expected_digest):
    """The published card, additionally required to equal an operator pin.

    The pin is the operator-side cross-check that the engineered Python
    policy version being loaded corresponds to the published card of
    record; a mismatch is a bounded fail-closed error, never a warning.
    """
    if not isinstance(expected_digest, str) or not expected_digest:
        raise ValueError(PIN_ARGUMENT_MESSAGE)
    card = load_published_card(directory, policy_id, policy_version)
    if sop_digest(card) != expected_digest:
        raise ValueError(PIN_MESSAGE)
    return card


def published_card_matches(card, policy):
    """Structural (id, version, goal) cross-check of card against a policy.

    Partial by design (D62): capabilities have no runtime counterpart —
    grants decide execution authority — and are never compared. Returns
    ``False`` for non-card shapes rather than raising; the authoritative
    content checks live in :func:`load_published_card`.
    """
    section = card.get("policy") if isinstance(card, dict) else None
    if not isinstance(section, dict):
        return False
    return (section.get("id") == getattr(policy, "id", None)
            and section.get("version") == getattr(policy, "version", None)
            and section.get("goal") == getattr(policy, "goal", None))


class SopPublicationPolicy:
    """The governed ``sop.publish`` family (D54): S02 approval, S03 acceptance.

    Mirrors the publishing domain on the unchanged command protocol: S02 is
    C02's shape — a version-bound signed ``card_approval`` of the current
    content digest from the configured authority source — and S03 is C04's
    shape, excluded from blockers because the store's own acceptance (the
    runtime-written ``accepted`` proof) satisfies it. Admission lints the
    card (D57): a dirty card is a bounded unpersisted ``ValueError``, the
    house convention for malformed documents; the lint workflow itself
    stays with ``lint-sop``.
    """

    id = "sop-publish"
    version = "demo-1"
    goal = "sop.published"
    evidence_sources = {
        "card_approval": "sop-owner",
        "accepted": "sop-store",
    }

    def validate_document(self, document):
        sop_digest(document)  # Bounded ValueError when the card is not lint-clean.

    def validate_evidence(self, work, candidate):
        data = candidate["data"]
        kind = candidate["kind"]
        if kind == "card_approval":
            # Version-bound approval (D58): the exact {digest, policy_version}
            # shape with the version bound to the CARD's own policy version.
            return (set(data) == {"digest", "policy_version"}
                    and isinstance(data["digest"], str)
                    and data["policy_version"]
                    == work["document"]["policy"]["version"])
        if kind == "accepted":
            # Reserved shape adopted from Runtime-written receipts.
            return (set(data) == {"digest", "external_id"}
                    and isinstance(data["digest"], str)
                    and isinstance(data["external_id"], str)
                    and bool(data["external_id"]))
        return False

    def evaluate(self, work, evidence):
        document = work["document"]
        current = work["document_digest"]
        proofs = [e for e in evidence if e["status"] == "verified"]

        def has(kind):
            source = self.evidence_sources[kind]
            return any(e["kind"] == kind and e["source"] == source
                       and e["data"].get("digest") == current for e in proofs)

        result = []

        def add(rule, subject, satisfied, explanation):
            result.append({"id": rule + ":" + subject, "rule_id": rule,
                           "subject": subject, "applicability": "applicable",
                           "fulfillment": "satisfied" if satisfied else "pending",
                           "explanation": explanation})

        subject = document["policy"]["id"]
        add("S02", subject, has("card_approval"),
            "The configured authority must approve the exact current card content "
            "with a version-bound signed card_approval")
        add("S03", subject, has("accepted"),
            "The publication store must accept the current card content "
            "(runtime-written proof)")
        return result

    def action_blockers(self, capability, requirements):
        if capability != "sop.publish":
            return [{"code": "CAPABILITY_UNSUPPORTED", "capability": capability}]
        return [r for r in requirements if r["rule_id"] != "S03" and
                (r["applicability"] in ("unknown", "conflict")
                 or (r["applicability"] == "applicable"
                     and r["fulfillment"] != "satisfied"))]

    def operation_key(self, capability, work):
        # The store key IS the business key (D66): re-proposing the same card
        # converges on one operation identity per (policy id, version).
        return publication_key(work["document"])
