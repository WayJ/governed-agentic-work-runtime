"""Support-ticket family: policy and its fake GitHub-issue-shaped tracker.

The third business family on the shared Runtime (S15). The policy carries
severity/category admission with an unknown-blocking rule (an unresolved
severity or category can never pass as within-policy), an urgent-SLA
conditional obligation, and a ticket-reference business key. The tracker
adapter models an external issue tracker. Source names (`support-desk`,
`tracker`) are local trust configuration, not authentication — see
docs/adapter-contract.md and docs/runtime-boundaries.md.
"""

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
