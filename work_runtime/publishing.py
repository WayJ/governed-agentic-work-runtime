"""Content publication demo policy and its fake external publisher.

The policy is the second business domain on the shared Runtime: review,
confirmation and publication rules travel with the policy instead of the
lifecycle engine. Source names (`reviewer`, `author`, `publisher`) are
local trust configuration, not authentication — signed ingress
authenticates evidence sources and direct Runtime calls stay trusted-local
(see docs/signed-evidence.md and docs/adapter-contract.md).
"""

from typing import List

from .policy import digest


class PublishingPolicy:
    """Demo C01–C04 policy for publishing a reviewed document.

    It trusts in-process source identities configured by the application,
    like ExpensePolicy. `requires_review` None means review applicability
    is unknown, which blocks publication until it is decided.
    """

    id = "content-publish"
    version = "demo-1"
    goal = "content.published"
    evidence_sources = {
        "approval": "reviewer",
        "confirmation": "author",
        "accepted": "publisher",
    }

    def validate_document(self, document: dict) -> None:
        if set(document) != {"id", "title", "body", "requires_review"}:
            raise ValueError("Document requires id, title, body and requires_review")
        for name in ("id", "title", "body"):
            if not isinstance(document[name], str) or not document[name]:
                raise ValueError("Document %s must be a nonempty string" % name)
        if document["requires_review"] is not None and type(document["requires_review"]) is not bool:
            raise ValueError("requires_review must be a boolean or null (unknown)")

    def validate_evidence(self, work: dict, candidate: dict) -> bool:
        data = candidate["data"]
        kind = candidate["kind"]
        if kind in ("approval", "confirmation"):
            return set(data) == {"digest"} and isinstance(data["digest"], str)
        if kind == "accepted":
            # Reserved shape adopted from Runtime-written receipts (design M5).
            return (set(data) == {"digest", "external_id"}
                    and isinstance(data["digest"], str)
                    and isinstance(data["external_id"], str)
                    and bool(data["external_id"]))
        return False

    def evaluate(self, work: dict, evidence: List[dict]) -> List[dict]:
        document = work["document"]
        current = work["document_digest"]
        proofs = [e for e in evidence if e["status"] == "verified"]

        def has(kind: str) -> bool:
            source = self.evidence_sources[kind]
            return any(e["kind"] == kind and e["source"] == source
                       and e["data"].get("digest") == current for e in proofs)

        result = []

        def add(rule: str, subject: str, applicable: str, satisfied: bool,
                explanation: str) -> None:
            result.append({"id": rule + ":" + subject, "rule_id": rule,
                           "subject": subject, "applicability": applicable,
                           "fulfillment": "satisfied" if satisfied else "pending",
                           "explanation": explanation})

        add("C01", document["id"], "applicable",
            bool(document["title"]) and bool(document["body"]),
            "The current artifact must be complete (nonempty title and body)")
        review = document["requires_review"]
        applicable = ("unknown" if review is None
                      else "applicable" if review else "not_applicable")
        add("C02", document["id"], applicable, has("approval"),
            "A true requires_review needs the reviewer's approval of the current content; "
            "a false one is not applicable, and an unknown one blocks")
        add("C03", document["id"], "applicable", has("confirmation"),
            "The author must confirm the current content")
        add("C04", document["id"], "applicable", has("accepted"),
            "The publisher must have accepted the current content")
        return result

    def action_blockers(self, capability: str, requirements: List[dict]) -> List[dict]:
        if capability != "content.publish":
            return [{"code": "CAPABILITY_UNSUPPORTED", "capability": capability}]
        return [r for r in requirements if r["rule_id"] != "C04" and
                (r["applicability"] in ("unknown", "conflict")
                 or (r["applicability"] == "applicable"
                     and r["fulfillment"] != "satisfied"))]

    def operation_key(self, capability: str, work: dict) -> str:
        return digest([self.id, capability, work["document"]["id"],
                       work["document_digest"]])
