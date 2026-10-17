"""Support-ticket family tests: policy admission, issue tracker, governed flow.

The family is the third business domain on the shared Runtime (S15): severity
and category admission with an unknown-blocking rule, a ticket-reference
business key, and a GitHub-issue-shaped fake tracker adapter.
"""

import tempfile
import unittest
import uuid
from pathlib import Path

from work_runtime.policy import digest
from work_runtime.support import (FakeIssueTracker, SupportPolicy,
                                   SupportPolicyV2)


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


try:
    from adapter_conformance import AdapterConformanceMixin
except ImportError:
    from tests.adapter_conformance import AdapterConformanceMixin


def proof(kind, source, data, status="verified"):
    return {"id": uuid.uuid4().hex, "source": source, "event_id": uuid.uuid4().hex,
            "kind": kind, "data": data, "status": status}


def work_state(document=None):
    doc = ticket() if document is None else document
    return {"id": "w1", "document": doc, "document_digest": digest(doc)}


def requirement(rules, rule_id):
    return next(r for r in rules if r["rule_id"] == rule_id)


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


class SupportEvaluateTests(unittest.TestCase):
    def setUp(self):
        self.policy = SupportPolicy()
        self.work = work_state()
        self.current = self.work["document_digest"]

    def rules(self, document=None, proofs=()):
        work = work_state(document)
        return self.policy.evaluate(work, list(proofs))

    def test_unresolved_severity_and_category_block_with_unknown_applicability(self):
        rules = self.rules(ticket(severity=None, category=None))
        for rule_id in ("T01", "T02", "T03"):
            self.assertEqual(requirement(rules, rule_id)["applicability"],
                             "unknown", rule_id)
            self.assertEqual(requirement(rules, rule_id)["fulfillment"],
                             "pending", rule_id)

    def test_resolved_severity_and_category_admit_their_rules(self):
        rules = self.rules(ticket())
        for rule_id in ("T01", "T02"):
            rule = requirement(rules, rule_id)
            self.assertEqual((rule["applicability"], rule["fulfillment"]),
                             ("applicable", "satisfied"), rule_id)
        partial = self.rules(ticket(category=None))
        self.assertEqual(requirement(partial, "T01")["fulfillment"], "satisfied")
        self.assertEqual(requirement(partial, "T02")["applicability"], "unknown")

    def test_urgent_sla_applicability_follows_severity(self):
        for severity, expected in (("critical", "applicable"), ("high", "applicable"),
                                   ("normal", "not_applicable"), (None, "unknown")):
            with self.subTest(severity=severity):
                rules = self.rules(ticket(severity=severity))
                self.assertEqual(requirement(rules, "T03")["applicability"], expected)

    def test_urgent_sla_satisfied_only_within_the_severity_budget(self):
        for severity, minutes, satisfied in (("critical", 60, True),
                                             ("critical", 61, False),
                                             ("high", 240, True),
                                             ("high", 241, False)):
            with self.subTest(severity=severity, minutes=minutes):
                document = ticket(severity=severity)
                rules = self.rules(document, proofs=[
                    proof("sla", "support-desk",
                          {"digest": digest(document),
                           "response_target_minutes": minutes})])
                self.assertEqual(requirement(rules, "T03")["fulfillment"],
                                 "satisfied" if satisfied else "pending")

    def test_wrong_source_stale_digest_or_unverified_does_not_satisfy_sla(self):
        document = ticket(severity="critical")
        current = digest(document)
        stale = digest(ticket(summary="A different report"))
        cases = (
            [proof("sla", "tracker",
                   {"digest": current, "response_target_minutes": 30})],
            [proof("sla", "support-desk",
                   {"digest": stale, "response_target_minutes": 30})],
            [proof("sla", "support-desk",
                   {"digest": current, "response_target_minutes": 30},
                   status="pending_verification")],
        )
        for proofs in cases:
            rules = self.rules(document, proofs=proofs)
            self.assertEqual(requirement(rules, "T03")["fulfillment"], "pending")

    def test_accepted_rule_tracks_tracker_receipt_at_current_digest(self):
        rules = self.rules(proofs=[proof("accepted", "tracker",
                                         {"digest": self.current, "external_id": "#1"})])
        rule = requirement(rules, "T04")
        self.assertEqual((rule["applicability"], rule["fulfillment"]),
                         ("applicable", "satisfied"))
        stale = self.rules(proofs=[proof("accepted", "tracker",
                                         {"digest": digest(ticket(summary="Other")),
                                          "external_id": "#1"})])
        self.assertEqual(requirement(stale, "T04")["fulfillment"], "pending")
        wrong_source = self.rules(proofs=[proof("accepted", "support-desk",
                                                {"digest": self.current,
                                                 "external_id": "#1"})])
        self.assertEqual(requirement(wrong_source, "T04")["fulfillment"], "pending")

    def test_requirements_carry_the_ticket_reference_subject(self):
        rules = self.rules(ticket(ticket_reference="TCK-77"))
        self.assertIn("T01:TCK-77", [r["id"] for r in rules])
        self.assertEqual({r["rule_id"] for r in rules}, {"T01", "T02", "T03", "T04"})


class SupportAdmissionTests(unittest.TestCase):
    """Dispatch blockers, the ticket-reference business key, policy V2."""

    def setUp(self):
        self.policy = SupportPolicy()

    def rules_with_sla(self, severity, minutes=30, policy=None):
        document = ticket(severity=severity)
        return (policy or self.policy).evaluate(work_state(document), [
            proof("sla", "support-desk", {"digest": digest(document),
                                          "response_target_minutes": minutes})])

    def test_action_blockers_exclude_the_accepted_rule_and_track_applicability(self):
        rules = self.policy.evaluate(work_state(ticket(severity=None)), [])
        blockers = self.policy.action_blockers("ticket.dispatch", rules)
        self.assertEqual({b["rule_id"] for b in blockers}, {"T01", "T03"})
        self.assertEqual(blockers[0]["applicability"], "unknown")
        self.assertNotIn("T04", [b["rule_id"] for b in blockers])

    def test_satisfied_requirements_admit_the_dispatch_capability(self):
        self.assertEqual(self.policy.action_blockers(
            "ticket.dispatch", self.rules_with_sla("critical")), [])

    def test_missing_sla_blocks_a_resolved_urgent_ticket(self):
        rules = self.policy.evaluate(work_state(ticket(severity="critical")), [])
        self.assertEqual([b["rule_id"] for b in
                          self.policy.action_blockers("ticket.dispatch", rules)],
                         ["T03"])

    def test_normal_severity_needs_no_sla(self):
        rules = self.policy.evaluate(work_state(ticket(severity="normal")), [])
        self.assertEqual(self.policy.action_blockers("ticket.dispatch", rules), [])

    def test_unsupported_capability_is_always_blocked(self):
        blockers = self.policy.action_blockers("expense.submit", [])
        self.assertEqual(blockers, [{"code": "CAPABILITY_UNSUPPORTED",
                                     "capability": "expense.submit"}])

    def test_operation_key_is_ticket_reference_bound(self):
        work = work_state()
        key = self.policy.operation_key("ticket.dispatch", work)
        self.assertEqual(key, digest(["support-ticket", "ticket.dispatch",
                                      work["document"]["ticket_reference"]]))
        revised = work_state(ticket(summary="Updated summary after triage"))
        self.assertEqual(key,
                         self.policy.operation_key("ticket.dispatch", revised))
        other = work_state(ticket(ticket_reference="TCK-1002"))
        self.assertNotEqual(key,
                            self.policy.operation_key("ticket.dispatch", other))
        self.assertEqual(SupportPolicyV2().operation_key("ticket.dispatch", work),
                         key)

    def test_policy_v2_tightens_the_critical_sla_budget(self):
        v2 = SupportPolicyV2()
        self.assertEqual(v2.version, "demo-2")
        for minutes, fulfillment in ((30, "satisfied"), (31, "pending"),
                                     (45, "pending")):
            rules = self.rules_with_sla("critical", minutes, policy=v2)
            self.assertEqual(requirement(rules, "T03")["fulfillment"], fulfillment,
                             minutes)
        high = self.rules_with_sla("high", 240, policy=v2)
        self.assertEqual(requirement(high, "T03")["fulfillment"], "satisfied")


class FakeIssueTrackerConformanceTests(AdapterConformanceMixin, unittest.TestCase):
    def make_adapter(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        return FakeIssueTracker(str(Path(folder.name) / "tracker.sqlite"))

    def sample_document(self):
        return ticket()

    def changed_document(self):
        return ticket(summary="A different problem report")

    def effect_count(self, adapter):
        return adapter.issue_count()


class FakeIssueTrackerDomainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "tracker.sqlite")

    def test_receipt_is_github_issue_shaped(self):
        tracker = FakeIssueTracker(self.path)
        document = ticket()
        receipt = tracker.execute("key-1", document, digest(document))
        self.assertEqual(receipt["status"], "accepted")
        self.assertEqual(receipt["external_id"], "#1")
        self.assertEqual(receipt["issue_number"], 1)
        self.assertEqual(receipt["issue_state"], "open")
        self.assertEqual(receipt["ticket_reference"], document["ticket_reference"])
        self.assertEqual(receipt["digest"], digest(document))
        second = tracker.execute("key-2", ticket(ticket_reference="TCK-1002"), 
                                 digest(ticket(ticket_reference="TCK-1002")))
        self.assertEqual((second["issue_number"], second["external_id"]), (2, "#2"))

    def test_digest_mismatch_is_rejected_without_writes(self):
        tracker = FakeIssueTracker(self.path)
        document = ticket()
        with self.assertRaises(ValueError):
            tracker.execute("key-1", document, digest(ticket(summary="Other")))
        self.assertEqual(tracker.issue_count(), 0)
        self.assertIsNone(tracker.lookup("key-1"))

    def test_one_issue_per_ticket_reference_across_keys(self):
        tracker = FakeIssueTracker(self.path)
        document = ticket()
        first = tracker.execute("key-1", document, digest(document))
        alias = tracker.execute("key-2", document, digest(document))
        self.assertEqual(alias["external_id"], first["external_id"])
        self.assertEqual(alias["issue_number"], first["issue_number"])
        self.assertEqual(tracker.issue_count(), 1)

    def test_same_reference_different_content_is_a_queryable_business_rejection(self):
        tracker = FakeIssueTracker(self.path)
        document = ticket()
        tracker.execute("key-1", document, digest(document))
        changed = ticket(summary="Changed the report entirely")
        rejected = tracker.execute("key-3", changed, digest(changed))
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["reason"], "TICKET_REFERENCE_CONTENT_CONFLICT")
        self.assertEqual(rejected["external_id"], "#1")
        self.assertEqual(tracker.issue_count(), 1)
        self.assertEqual(tracker.lookup("key-3"), rejected)

    def test_timeout_after_commit_raises_with_issue_committed(self):
        tracker = FakeIssueTracker(self.path, timeout_after_commit=True)
        document = ticket()
        with self.assertRaises(TimeoutError):
            tracker.execute("key-1", document, digest(document))
        self.assertEqual(tracker.issue_count(), 1)
        recovered = FakeIssueTracker(self.path).lookup("key-1")
        self.assertEqual(recovered["status"], "accepted")
        self.assertEqual(recovered["external_id"], "#1")

    def test_issue_for_reference_returns_the_written_issue(self):
        tracker = FakeIssueTracker(self.path)
        self.assertIsNone(tracker.issue_for_reference("TCK-1001"))
        document = ticket()
        tracker.execute("key-1", document, digest(document))
        issue = tracker.issue_for_reference("TCK-1001")
        self.assertEqual(issue["issue_number"], 1)
        self.assertEqual(issue["digest"], digest(document))
        self.assertEqual(issue["document"], document)

    def test_link_carrying_calls_and_unknown_actions_raise(self):
        tracker = FakeIssueTracker(self.path)
        document = ticket()
        link = {"operation_id": "op", "external_id": "#9", "capability": "ticket.dispatch"}
        with self.assertRaises(ValueError):
            tracker.execute("key-1", document, digest(document),
                            action="ticket.dispatch", compensates=link)
        with self.assertRaises(ValueError):
            tracker.execute("key-2", document, digest(document), action="ticket.close")
        self.assertEqual(tracker.issue_count(), 0)
