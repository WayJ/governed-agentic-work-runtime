"""Support-ticket family tests: policy admission, issue tracker, governed flow.

The family is the third business domain on the shared Runtime (S15): severity
and category admission with an unknown-blocking rule, a ticket-reference
business key, and a GitHub-issue-shaped fake tracker adapter.
"""

import unittest

from work_runtime.support import SupportPolicy


def ticket(ticket_reference="TCK-1001", summary="Payment failed after the update",
           severity="critical", category="billing"):
    return {"ticket_reference": ticket_reference, "summary": summary,
            "severity": severity, "category": category}


class SupportDocumentTests(unittest.TestCase):
    def test_valid_documents_cover_all_severities_categories_and_none(self):
        policy = SupportPolicy()
        for severity in ("critical", "high", "normal", None):
            policy.validate_document(ticket(severity=severity))
        for category in ("billing", "technical", "account", None):
            policy.validate_document(ticket(category=category))
        policy.validate_document(ticket(severity=None, category=None))

    def test_document_requires_exact_fields(self):
        policy = SupportPolicy()
        with self.assertRaises(ValueError):
            policy.validate_document({"ticket_reference": "TCK-1", "severity": None,
                                      "category": None})
        with self.assertRaises(ValueError):
            policy.validate_document({**ticket(), "priority": "critical"})

    def test_identity_strings_must_be_nonempty(self):
        policy = SupportPolicy()
        for field in ("ticket_reference", "summary"):
            with self.assertRaises(ValueError):
                policy.validate_document({**ticket(), field: ""})
            with self.assertRaises(ValueError):
                policy.validate_document({**ticket(), field: 7})

    def test_severity_and_category_use_the_vocabulary_or_none(self):
        policy = SupportPolicy()
        for field, value in (("severity", "urgent"), ("category", "legal")):
            with self.assertRaises(ValueError):
                policy.validate_document({**ticket(), field: value})
        policy.validate_document(ticket(severity="high", category="technical"))


if __name__ == "__main__":
    unittest.main()


class SupportEvidenceShapeTests(unittest.TestCase):
    def setUp(self):
        self.policy = SupportPolicy()
        self.work = {"document": ticket(), "document_digest": "d" * 64}

    def candidate(self, kind, data):
        return {"kind": kind, "data": data}

    def test_sla_requires_exact_shape_with_positive_integer_minutes(self):
        self.assertTrue(self.policy.validate_evidence(
            self.work, self.candidate("sla", {"digest": "d" * 64,
                                              "response_target_minutes": 60})))
        for bad in ({"digest": "d" * 64},
                    {"digest": "d" * 64, "response_target_minutes": 60, "x": 1},
                    {"digest": "d" * 64, "response_target_minutes": 0},
                    {"digest": "d" * 64, "response_target_minutes": -5},
                    {"digest": "d" * 64, "response_target_minutes": "60"},
                    {"response_target_minutes": 60}):
            self.assertFalse(self.policy.validate_evidence(
                self.work, self.candidate("sla", bad)), bad)

    def test_accepted_requires_digest_and_nonempty_external_id(self):
        self.assertTrue(self.policy.validate_evidence(
            self.work, self.candidate("accepted", {"digest": "d" * 64,
                                                   "external_id": "#1"})))
        for bad in ({"digest": "d" * 64},
                    {"digest": "d" * 64, "external_id": ""},
                    {"digest": "d" * 64, "external_id": 1},
                    {"external_id": "#1"}):
            self.assertFalse(self.policy.validate_evidence(
                self.work, self.candidate("accepted", bad)), bad)

    def test_unknown_kinds_are_invalid(self):
        for kind in ("approval", "triage", "TicketAccepted"):
            self.assertFalse(self.policy.validate_evidence(
                self.work, self.candidate(kind, {"digest": "d" * 64})), kind)
