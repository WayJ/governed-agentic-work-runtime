"""Support-ticket family tests: policy admission, issue tracker, governed flow.

The family is the third business domain on the shared Runtime (S15): severity
and category admission with an unknown-blocking rule, a ticket-reference
business key, and a GitHub-issue-shaped fake tracker adapter.
"""

import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from work_runtime.policy import digest
from work_runtime.runtime import Runtime
from work_runtime.support import (FakeIssueTracker, SupportPolicy,
                                   SupportPolicyV2, run_crash_worker,
                                   support_grants)


def ticket(ticket_reference="TCK-1001", summary="Payment failed after the update",
           severity="critical", category="billing"):
    # The document id is the external ticket reference.
    return {"id": ticket_reference, "summary": summary,
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
            policy.validate_document({"id": "TCK-1", "severity": None,
                                      "category": None})
        with self.assertRaises(ValueError):
            policy.validate_document({**ticket(), "priority": "critical"})

    def test_identity_strings_must_be_nonempty(self):
        policy = SupportPolicy()
        for field in ("id", "summary"):
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
                                      work["document"]["id"]]))
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
        self.assertEqual(receipt["ticket_reference"], document["id"])
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


class SupportFlowHarness:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        self.tracker_path = str(Path(self.temp.name) / "tracker.sqlite")
        self.runtime = self.fresh_runtime()
        self.work_id = "ticket-1"

    def fresh_runtime(self, policy=None):
        return Runtime(self.path, policy or SupportPolicy(), support_grants())

    def send(self, kind, payload=None, actor="agent", command_id=None):
        version = None if kind in ("create_work", "record_evidence") \
            else self.runtime.get_work(self.work_id)["state_version"]
        return self.runtime.command(actor, command_id or uuid.uuid4().hex,
                                    self.work_id, kind, payload, version)

    def initialize(self, document=None):
        self.send("create_work", {"document": document or ticket()})
        self.send("bind_contract", {"policy_id": "support-ticket",
                                    "policy_version": "demo-1",
                                    "goal": "ticket.dispatched"})
        self.send("revise_plan", {"steps": ["triage", "commit-sla", "dispatch"],
                                  "open_requirements": ["T01", "T02"],
                                  "replan_when": ["triage cannot resolve"]})

    def record_sla(self, minutes=45, command_id=None):
        work = self.runtime.get_work(self.work_id)
        return self.send("record_evidence",
                         {"event_id": "sla-" + uuid.uuid4().hex, "kind": "sla",
                          "data": {"digest": work["document_digest"],
                                   "response_target_minutes": minutes}},
                         actor="support-desk", command_id=command_id)

    def propose_payload(self):
        work = self.runtime.get_work(self.work_id)
        return {"capability": "ticket.dispatch",
                "document_digest": work["document_digest"],
                "contract_revision": work["contract"]["revision"],
                "plan_revision": work["plan_revision"]}

    def propose(self, command_id=None):
        return self.send("propose_action", self.propose_payload(),
                         command_id=command_id)

    def admit(self):
        self.record_sla()
        self.runtime.verify_pending(self.work_id)
        return self.propose(command_id="dispatch-once")


class SupportFlowTests(SupportFlowHarness, unittest.TestCase):
    def test_unresolved_severity_blocks_acceptance(self):
        self.initialize(ticket(severity=None))
        rejection = self.propose()
        self.assertEqual(rejection["decision"], "rejected")
        self.assertEqual(rejection["code"], "APPLICABILITY_UNRESOLVED")
        blocked = {b["rule_id"] for b in rejection["blockers"]}
        self.assertEqual(blocked, {"T01", "T03"})

    def test_unresolved_category_blocks_acceptance(self):
        self.initialize(ticket(category=None))
        rejection = self.propose()
        self.assertEqual(rejection["code"], "APPLICABILITY_UNRESOLVED")
        self.assertIn("T02", [b["rule_id"] for b in rejection["blockers"]])

    def test_resolved_urgent_ticket_without_sla_is_blocked(self):
        self.initialize(ticket())
        rejection = self.propose()
        self.assertEqual(rejection["decision"], "rejected")
        self.assertEqual(rejection["code"], "REQUIREMENT_UNSATISFIED")
        self.assertEqual([b["rule_id"] for b in rejection["blockers"]], ["T03"])

    def test_wrong_budget_sla_still_blocks(self):
        self.initialize(ticket())
        self.record_sla(minutes=61)
        self.runtime.verify_pending(self.work_id)
        rejection = self.propose()
        self.assertEqual(rejection["code"], "REQUIREMENT_UNSATISFIED")

    def test_forward_flow_dispatches_and_closes_the_work(self):
        self.initialize(ticket())
        self.record_sla()
        self.runtime.verify_pending(self.work_id)
        version = self.runtime.get_work(self.work_id)["state_version"]
        proposal = self.propose(command_id="dispatch-once")
        self.assertEqual(proposal["decision"], "accepted")
        replay_args = ("agent", "dispatch-once", self.work_id, "propose_action",
                       self.propose_payload(), version)
        self.assertEqual(self.runtime.command(*replay_args), proposal)
        fresh = self.propose()
        self.assertEqual(fresh["operation_id"], proposal["operation_id"])
        tracker = FakeIssueTracker(self.tracker_path)
        confirmed = self.runtime.dispatch(proposal["operation_id"], tracker)
        self.assertEqual(confirmed["status"], "confirmed_succeeded")
        self.assertEqual(confirmed["external_id"], "#1")
        rules = self.runtime.get_work(self.work_id)["requirements"]
        self.assertEqual(requirement(rules, "T04")["fulfillment"], "satisfied")
        completion = self.send("request_completion", command_id="complete-1")
        self.assertEqual(completion["decision"], "accepted")
        work = self.runtime.get_work(self.work_id)
        self.assertEqual((work["status"], work["outcome"]), ("closed", "succeeded"))
        self.assertEqual(tracker.issue_count(), 1)
        late = self.propose(command_id="late-proposal")
        self.assertEqual(late["decision"], "rejected")
        self.assertEqual(late["code"], "WORK_NOT_ACTIONABLE")
        self.assertEqual(tracker.issue_count(), 1)

    def test_cross_work_same_ticket_reference_conflicts(self):
        self.initialize(ticket())
        self.admit()
        self.work_id = "ticket-2"
        self.initialize(ticket())
        self.admit()
        conflict = self.propose(command_id="dispatch-second")
        self.assertEqual(conflict["decision"], "rejected")
        self.assertEqual(conflict["code"], "OPERATION_CONTENT_CONFLICT")

    def test_same_work_content_revision_after_proposal_conflicts(self):
        self.initialize(ticket())
        self.admit()
        self.send("revise_document", {"document": ticket(summary="Updated after triage")})
        stale_sla = self.propose()
        self.assertEqual(stale_sla["code"], "REQUIREMENT_UNSATISFIED")
        self.record_sla()
        self.runtime.verify_pending(self.work_id)
        conflict = self.propose()
        self.assertEqual(conflict["decision"], "rejected")
        self.assertEqual(conflict["code"], "OPERATION_CONTENT_CONFLICT")


class SupportRecoveryTests(SupportFlowHarness, unittest.TestCase):
    """Result-unknown dispatches reconcile by ticket reference, never resend."""

    def test_timeout_after_commit_recovers_by_lookup_without_resend(self):
        self.initialize(ticket())
        proposal = self.admit()
        unknown = self.runtime.dispatch(
            proposal["operation_id"],
            FakeIssueTracker(self.tracker_path, timeout_after_commit=True))
        self.assertEqual(unknown["status"], "outcome_unknown")
        tracker = FakeIssueTracker(self.tracker_path)
        self.assertEqual(tracker.issue_count(), 1)
        self.assertEqual(
            tracker.lookup(self.runtime.get_operation(
                proposal["operation_id"])["business_key"])["status"], "accepted")

        restarted = self.fresh_runtime()
        recovered = restarted.reconcile(proposal["operation_id"],
                                        FakeIssueTracker(self.tracker_path))
        self.assertEqual(recovered["status"], "confirmed_succeeded")
        self.assertEqual(recovered["external_id"], "#1")
        operation = restarted.get_operation(proposal["operation_id"])
        self.assertEqual(len(operation["attempts"]), 1)
        self.assertEqual(FakeIssueTracker(self.tracker_path).issue_count(), 1)
        db = sqlite3.connect(self.tracker_path)
        try:
            receipts = db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
        finally:
            db.close()
        self.assertEqual(receipts, 1)
        completion = restarted.command(
            "agent", "complete-1", self.work_id, "request_completion", None,
            restarted.get_work(self.work_id)["state_version"])
        self.assertEqual(completion["decision"], "accepted")

    def test_business_key_is_the_ticket_reference_digest(self):
        self.initialize(ticket())
        proposal = self.admit()
        operation = self.runtime.get_operation(proposal["operation_id"])
        self.assertEqual(operation["business_key"],
                         digest(["support-ticket", "ticket.dispatch", "TCK-1001"]))


class SupportMigrationTests(SupportFlowHarness, unittest.TestCase):
    """Policy migration re-gates the work; the business key never moves."""

    def fresh_runtime(self, policy=None):
        v1, v2 = SupportPolicy(), SupportPolicyV2()
        return Runtime(self.path, policy or v1, support_grants(),
                       policies={"demo-1": v1, "demo-2": v2})

    def migrate(self):
        return self.send("migrate_policy",
                         {"policy_id": "support-ticket", "policy_version": "demo-2",
                          "reason": "tighter critical SLA budget"}, actor="lead")

    def test_migration_readmits_the_same_operation_on_the_stable_key(self):
        self.initialize(ticket())
        proposal = self.admit()
        original = self.runtime.get_operation(proposal["operation_id"])
        self.assertEqual(self.migrate()["decision"], "accepted")
        invalidated = self.runtime.get_operation(proposal["operation_id"])
        self.assertEqual(invalidated["dispatch_state"], "cancelled")
        self.assertEqual(invalidated["business_key"], original["business_key"])
        # The V1-budget SLA (45 min) no longer satisfies the V2 critical budget
        rules = self.runtime.get_work(self.work_id)["requirements"]
        self.assertEqual(requirement(rules, "T03")["fulfillment"], "pending")
        blocked = self.propose(command_id="dispatch-v2-early")
        self.assertEqual(blocked["code"], "REQUIREMENT_UNSATISFIED")
        # A V2-compliant SLA reopens admission on the SAME operation id
        self.record_sla(minutes=30)
        self.runtime.verify_pending(self.work_id)
        again = self.propose(command_id="dispatch-v2")
        self.assertEqual(again["decision"], "accepted")
        self.assertEqual(again["operation_id"], proposal["operation_id"])
        confirmed = self.runtime.dispatch(again["operation_id"],
                                          FakeIssueTracker(self.tracker_path))
        self.assertEqual(confirmed["status"], "confirmed_succeeded")
        self.assertEqual(FakeIssueTracker(self.tracker_path).issue_count(), 1)

    def test_migration_refuses_uncertain_outcomes(self):
        self.initialize(ticket())
        proposal = self.admit()
        unknown = self.runtime.dispatch(
            proposal["operation_id"],
            FakeIssueTracker(self.tracker_path, timeout_after_commit=True))
        self.assertEqual(unknown["status"], "outcome_unknown")
        rejection = self.migrate()
        self.assertEqual(rejection["decision"], "rejected")
        self.assertEqual(rejection["code"], "OUTCOME_UNRESOLVED")


class SupportCrashRecoveryTests(SupportFlowHarness, unittest.TestCase):
    """Real process death after tracker acceptance; restart never re-sends."""

    def test_crash_after_acceptance_recovers_by_ticket_reference(self):
        self.initialize(ticket())
        proposal = self.admit()
        child = run_crash_worker(self.path, self.tracker_path,
                                 proposal["operation_id"])
        self.assertEqual(child.returncode, 73)
        tracker = FakeIssueTracker(self.tracker_path)
        self.assertEqual(tracker.issue_count(), 1)
        # The child died after the tracker accepted the write but before the
        # outcome was recorded: the operation is still in flight.
        restarted = self.fresh_runtime()
        self.assertEqual(restarted.get_operation(
            proposal["operation_id"])["status"], "dispatched")

        recovered = restarted.recover(FakeIssueTracker(self.tracker_path))
        self.assertEqual([op["status"] for op in recovered],
                         ["confirmed_succeeded"])
        operation = restarted.get_operation(proposal["operation_id"])
        self.assertEqual(operation["status"], "confirmed_succeeded")
        self.assertEqual(operation["external_id"], "#1")
        self.assertEqual(len(operation["attempts"]), 1)
        self.assertEqual(FakeIssueTracker(self.tracker_path).issue_count(), 1)
        db = sqlite3.connect(self.tracker_path)
        try:
            receipts = db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
        finally:
            db.close()
        self.assertEqual(receipts, 1)
        completion = restarted.command(
            "agent", "close-1", self.work_id, "request_completion", None,
            restarted.get_work(self.work_id)["state_version"])
        self.assertEqual(completion["decision"], "accepted")
        work = restarted.get_work(self.work_id)
        self.assertEqual((work["status"], work["outcome"]), ("closed", "succeeded"))
