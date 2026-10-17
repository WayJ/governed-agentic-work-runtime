"""Support-ticket family: policy and its fake GitHub-issue-shaped tracker.

The third business family on the shared Runtime (S15). The policy carries
severity/category admission with an unknown-blocking rule (an unresolved
severity or category can never pass as within-policy), an urgent-SLA
conditional obligation, and a ticket-reference business key. The tracker
adapter models an external issue tracker. Source names (`support-desk`,
`tracker`) are local trust configuration, not authentication — see
docs/adapter-contract.md and docs/runtime-boundaries.md.
"""

from typing import List

SEVERITIES = ("critical", "high", "normal")
CATEGORIES = ("billing", "technical", "account")


class SupportPolicy:
    """Support-ticket policy: severity/category admission and urgent SLA.

    A ``None`` severity or category means triage is unresolved: the rule's
    applicability is unknown, which blocks admission — unknown never passes
    as within-policy (RFC-001 P3/R3). ``SupportPolicyV2`` tightens the
    urgent-SLA budget without touching the business key.
    """

    id = "support-ticket"
    version = "demo-1"
    goal = "ticket.dispatched"
    evidence_sources = {
        "sla": "support-desk",
        "accepted": "tracker",
    }
    # No compensation_capabilities: this family has no compensation (D94).

    def validate_document(self, document: dict) -> None:
        if set(document) != {"ticket_reference", "summary", "severity", "category"}:
            raise ValueError("Document requires ticket_reference, summary, "
                             "severity and category")
        for name in ("ticket_reference", "summary"):
            if not isinstance(document[name], str) or not document[name]:
                raise ValueError("Document %s must be a nonempty string" % name)
        for name, vocabulary in (("severity", SEVERITIES), ("category", CATEGORIES)):
            value = document[name]
            if value is not None and value not in vocabulary:
                raise ValueError("Document %s must be one of %s or null (unknown)"
                                 % (name, ", ".join(vocabulary)))

    def validate_evidence(self, work: dict, candidate: dict) -> bool:
        data = candidate["data"]
        kind = candidate["kind"]
        if kind == "sla":
            return (set(data) == {"digest", "response_target_minutes"}
                    and isinstance(data["digest"], str)
                    and type(data["response_target_minutes"]) is int
                    and data["response_target_minutes"] > 0)
        if kind == "accepted":
            # Reserved shape adopted from Runtime-written receipts (design M5).
            return (set(data) == {"digest", "external_id"}
                    and isinstance(data["digest"], str)
                    and isinstance(data["external_id"], str)
                    and bool(data["external_id"]))
        return False

    # Urgent-SLA response budgets (minutes) by severity. SupportPolicyV2
    # tightens the critical budget; the ticket-reference business key is
    # untouched by either version.
    urgent_sla_budget_minutes = {"critical": 60, "high": 240}

    def evaluate(self, work: dict, evidence: List[dict]) -> List[dict]:
        document = work["document"]
        current = work["document_digest"]
        proofs = [e for e in evidence if e["status"] == "verified"]
        subject = document["ticket_reference"]
        result = []

        def add(rule: str, applicable: str, satisfied: bool,
                explanation: str) -> None:
            result.append({"id": rule + ":" + subject, "rule_id": rule,
                           "subject": subject, "applicability": applicable,
                           "fulfillment": "satisfied" if satisfied else "pending",
                           "explanation": explanation})

        add("T01",
            "unknown" if document["severity"] is None else "applicable",
            document["severity"] is not None,
            "Triage must resolve the severity; an unresolved severity never "
            "passes as within-policy")
        add("T02",
            "unknown" if document["category"] is None else "applicable",
            document["category"] is not None,
            "Triage must resolve the category; an unresolved category never "
            "passes as within-policy")
        severity = document["severity"]
        if severity is None:
            sla_applicable = "unknown"
        elif severity in self.urgent_sla_budget_minutes:
            sla_applicable = "applicable"
        else:
            sla_applicable = "not_applicable"
        sla_satisfied = False
        if sla_applicable == "applicable":
            budget = self.urgent_sla_budget_minutes[severity]
            sla_satisfied = any(
                e["kind"] == "sla" and e["source"] == self.evidence_sources["sla"]
                and e["data"].get("digest") == current
                and type(e["data"].get("response_target_minutes")) is int
                and 0 < e["data"]["response_target_minutes"] <= budget
                for e in proofs)
        add("T03", sla_applicable, sla_satisfied,
            "An urgent severity must carry a support-desk SLA commitment within "
            "the severity budget; while the severity is unknown, SLA "
            "applicability cannot be decided")
        accepted = any(
            e["kind"] == "accepted" and e["source"] == self.evidence_sources["accepted"]
            and e["data"].get("digest") == current
            and bool(e["data"].get("external_id")) for e in proofs)
        add("T04", "applicable", accepted,
            "The tracker must have accepted the current ticket content")
        return result
