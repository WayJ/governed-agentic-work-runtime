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
