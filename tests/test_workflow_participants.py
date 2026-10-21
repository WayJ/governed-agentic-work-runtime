"""Participant assignment and criterion quality at the core boundary.

A published definition may name a static principal or the platform's
current assignee of a node. The core never knows a workspace role id: it
asks a trusted, injected resolver who currently holds the assignment, and
it compares *actual actors* when it checks separation of duties.

A decision's criterion report is checked at the boundary: an item that
names an undeclared criterion, repeats one, carries a blank reason or empty
evidence is refused; a required criterion that is not passed is a genuine
shortfall and is never turned into a pass.
"""

import os
import tempfile
import unittest

try:
    from workflow_support import (DemoPolicy, build, decide, decide_command,
                                  demo_grants, instantiate, scenario_template,
                                  send, submit_valid, version_of)
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import (DemoPolicy, build, decide, decide_command,
                                        demo_grants, instantiate, scenario_template,
                                        send, submit_valid, version_of)


class PlatformPolicy(DemoPolicy):
    """The platform ingress carries the decision; the actor is asserted."""

    evidence_sources = dict(DemoPolicy.evidence_sources,
                            safety_review="platform-ingress",
                            project_approval="platform-ingress")


class StaticResolver:
    """A trusted stand-in for the platform's assignment lookup."""

    def __init__(self, mapping=None):
        self.mapping = dict(mapping or {})
        self.calls = []

    def resolve(self, work, node_id, member_id):
        self.calls.append((node_id, member_id))
        return self.mapping.get((node_id, member_id))


def assigned_template():
    """The same scenario with the reviewers assigned by the platform."""
    template = scenario_template(template_id="assigned", version="v1")
    template["nodes"]["n04"]["authority"] = {"assigned": True}
    template["nodes"]["n05"]["authority"] = {"assigned": True}
    return template


class ParticipantTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-workflow-participants-")
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.grants = demo_grants()
        self.grants["platform-ingress"] = {"evidence.write"}
        self.work_id = "W-1"

    def build(self, resolver=None, policy=PlatformPolicy, template=None):
        runtime, engine = build(self.path, policy=policy(), grants=self.grants,
                                resolver=resolver)
        self.runtime, self.engine = runtime, engine
        self.template = template or assigned_template()
        self.engine.publish_template("coordinator", self.template)
        return runtime, engine

    def instantiate(self, participants=None):
        if participants is None:
            participants = {"n04": "member-123", "n05": "member-456"}
        receipt = instantiate(self.runtime, self.engine, self.work_id,
                              template=self.template,
                              participants=participants)
        self.assertEqual(receipt["decision"], "accepted", receipt)
        return receipt

    def node(self, node_id):
        for entry in self.engine.instance(self.work_id)["nodes"]:
            if entry["node"] == node_id:
                return entry
        return None

    def drive_agents(self):
        for node, name in (("n01", "intake"), ("n02", "analysis"), ("n03", "proposal")):
            receipt = submit_valid(self.engine, self.runtime, self.work_id, node, name)
            self.assertEqual(receipt["decision"], "accepted", receipt)

    def proposal(self):
        return self.node("n03")["outputs"][0]


class AssignmentTests(ParticipantTestCase):
    def test_without_a_resolver_an_assigned_node_fails_closed(self):
        self.build(resolver=None)
        self.instantiate()
        self.drive_agents()
        receipt = decide(self.runtime, self.engine, self.work_id, "safety_review",
                         "platform-ingress", "approved", self.proposal()["digest"],
                         self.proposal()["revision"], node="n04", attempt=1,
                         actor="member-123")
        self.assertEqual(receipt["decision"], "accepted")
        self.runtime.verify_pending(self.work_id)
        self.engine.advance(self.work_id, 1000)
        node = self.node("n04")
        self.assertNotEqual(node["state"], "completed")
        self.assertTrue(any(finding["code"] == "WORKFLOW_AUTHORITY_MISMATCH"
                            for finding in node["findings"]))

    def test_the_resolved_assignee_may_decide(self):
        resolver = StaticResolver({("n04", "member-123"): "user-1"})
        self.build(resolver=resolver)
        self.instantiate()
        self.drive_agents()
        decide(self.runtime, self.engine, self.work_id, "safety_review",
               "platform-ingress", "approved", self.proposal()["digest"],
               self.proposal()["revision"], node="n04", attempt=1, actor="user-1")
        node = self.node("n04")
        self.assertEqual(node["state"], "completed")
        self.assertEqual(node["actor"], "user-1")
        self.assertIn(("n04", "member-123"), resolver.calls)

    def test_someone_else_may_not_decide(self):
        resolver = StaticResolver({("n04", "member-123"): "user-1"})
        self.build(resolver=resolver)
        self.instantiate()
        self.drive_agents()
        decide(self.runtime, self.engine, self.work_id, "safety_review",
               "platform-ingress", "approved", self.proposal()["digest"],
               self.proposal()["revision"], node="n04", attempt=1, actor="user-2")
        node = self.node("n04")
        self.assertNotEqual(node["state"], "completed")
        self.assertTrue(any(finding["code"] == "WORKFLOW_AUTHORITY_MISMATCH"
                            for finding in node["findings"]))

    def test_the_assignment_is_rechecked_when_the_node_settles(self):
        resolver = StaticResolver({("n04", "member-123"): "user-1"})
        self.build(resolver=resolver)
        self.instantiate()
        self.drive_agents()
        # The evidence is written while user-1 holds the assignment.
        receipt = send(self.runtime, "platform-ingress", self.work_id,
                       "record_evidence", {
                           "event_id": "evt-1", "kind": "safety_review",
                           "data": {"decision": "approved",
                                    "digest": self.proposal()["digest"],
                                    "revision": self.proposal()["revision"],
                                    "node": "n04", "attempt": 1, "actor": "user-1",
                                    "items": [{"check": "N04-2", "verdict": "passed",
                                               "reason": "reviewed",
                                               "evidence": ["proposal#revision-1"]}]}})
        self.assertEqual(receipt["decision"], "accepted")
        self.runtime.verify_pending(self.work_id)
        # The assignment is withdrawn before the node settles.
        resolver.mapping = {}
        self.engine.advance(self.work_id, 1000)
        node = self.node("n04")
        self.assertNotEqual(node["state"], "completed")
        self.assertTrue(any(finding["code"] == "WORKFLOW_AUTHORITY_MISMATCH"
                            for finding in node["findings"]))

    def test_two_roles_held_by_one_person_is_refused(self):
        resolver = StaticResolver({("n04", "member-123"): "user-1",
                                   ("n05", "member-456"): "user-1"})
        self.build(resolver=resolver)
        self.instantiate()
        self.drive_agents()
        decide(self.runtime, self.engine, self.work_id, "safety_review",
               "platform-ingress", "approved", self.proposal()["digest"],
               self.proposal()["revision"], node="n04", attempt=1, actor="user-1")
        self.assertEqual(self.node("n04")["state"], "completed")
        decide(self.runtime, self.engine, self.work_id, "project_approval",
               "platform-ingress", "approved", self.proposal()["digest"],
               self.proposal()["revision"], node="n05", attempt=1, actor="user-1")
        node = self.node("n05")
        self.assertNotEqual(node["state"], "completed")
        self.assertTrue(any(finding["code"] == "WORKFLOW_ROLE_ISOLATION"
                            for finding in node["findings"]))

    def test_a_participant_must_name_a_declared_node(self):
        self.build(resolver=StaticResolver())
        receipt = instantiate(self.runtime, self.engine, self.work_id,
                              template=self.template,
                              participants={"n99": "member-123"})
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "WORKFLOW_PARTICIPANT_UNKNOWN")


class CriterionQualityTests(ParticipantTestCase):
    def build(self, resolver=None, policy=DemoPolicy, template=None):
        runtime, engine = build(self.path, policy=policy(), grants=self.grants,
                                resolver=resolver)
        self.runtime, self.engine = runtime, engine
        self.template = template or scenario_template()
        self.engine.publish_template("coordinator", self.template)
        return runtime, engine

    def decide_with_items(self, items, decision="approved", node="n04"):
        return decide_command(self.engine, self.runtime, self.work_id,
                              "safety_review", "reviewer-a", decision,
                              self.proposal()["digest"],
                              self.proposal()["revision"], node=node, attempt=1,
                              actor="reviewer-a", items=items)

    def test_an_unknown_criterion_is_refused(self):
        self.build()
        self.instantiate()
        self.drive_agents()
        receipt = self.decide_with_items([{"check": "N99-9", "verdict": "passed",
                                           "reason": "ok", "evidence": ["x"]}])
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "WORKFLOW_CHECK_REPORT_INVALID")

    def test_a_repeated_criterion_is_refused(self):
        self.build()
        self.instantiate()
        self.drive_agents()
        receipt = self.decide_with_items([
            {"check": "N04-2", "verdict": "passed", "reason": "ok", "evidence": ["x"]},
            {"check": "N04-2", "verdict": "failed", "reason": "no", "evidence": ["y"]}])
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "WORKFLOW_CHECK_REPORT_INVALID")

    def test_a_blank_reason_is_refused(self):
        self.build()
        self.instantiate()
        self.drive_agents()
        receipt = self.decide_with_items([{"check": "N04-2", "verdict": "passed",
                                           "reason": "   ", "evidence": ["x"]}])
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "WORKFLOW_CHECK_REPORT_INVALID")

    def test_empty_evidence_is_refused(self):
        self.build()
        self.instantiate()
        self.drive_agents()
        receipt = self.decide_with_items([{"check": "N04-2", "verdict": "passed",
                                           "reason": "ok", "evidence": []}])
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "WORKFLOW_CHECK_REPORT_INVALID")

    def test_an_unknown_verdict_is_refused(self):
        self.build()
        self.instantiate()
        self.drive_agents()
        receipt = self.decide_with_items([{"check": "N04-2", "verdict": "great",
                                           "reason": "ok", "evidence": ["x"]}])
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "WORKFLOW_CHECK_REPORT_INVALID")

    def test_a_failing_required_criterion_stops_an_approval(self):
        self.build()
        self.instantiate()
        self.drive_agents()
        receipt = self.decide_with_items([{"check": "N04-2", "verdict": "failed",
                                           "reason": "the guard is not covered",
                                           "evidence": ["proposal#measure-2"]}])
        self.assertEqual(receipt["decision"], "accepted")
        node = self.node("n04")
        self.assertNotEqual(node["state"], "completed")
        report = node["checkResults"]
        self.assertEqual(report[0]["verdict"], "failed")
        self.assertEqual(report[0]["reason"], "the guard is not covered")
        self.assertTrue(any(finding["code"] == "WORKFLOW_CHECK_SHORTFALL"
                            for finding in node["findings"]))

    def test_a_not_applicable_verdict_needs_a_protected_rule(self):
        template = scenario_template(template_id="na", version="v1")
        template["nodes"]["n04"]["checks"][0]["allow_not_applicable"] = False
        self.build(template=template)
        self.instantiate()
        self.drive_agents()
        self.decide_with_items([{"check": "N04-2", "verdict": "not_applicable",
                                 "reason": "no requirement applies",
                                 "evidence": ["standard#scope"]}])
        node = self.node("n04")
        self.assertNotEqual(node["state"], "completed")
        self.assertTrue(any(finding["code"] == "WORKFLOW_CHECK_SHORTFALL"
                            for finding in node["findings"]))

    def test_a_not_applicable_verdict_is_accepted_when_the_rule_allows_it(self):
        template = scenario_template(template_id="na2", version="v1")
        template["nodes"]["n04"]["checks"][0]["allow_not_applicable"] = True
        self.build(template=template)
        self.instantiate()
        self.drive_agents()
        self.decide_with_items([{"check": "N04-2", "verdict": "not_applicable",
                                 "reason": "no requirement applies",
                                 "evidence": ["standard#scope"]}])
        node = self.node("n04")
        self.assertEqual(node["state"], "completed")
        self.assertEqual(node["checkResults"][0]["verdict"], "not_applicable")

    def test_a_rejection_keeps_the_shortages(self):
        self.build()
        self.instantiate()
        self.drive_agents()
        self.decide_with_items([{"check": "N04-2", "verdict": "failed",
                                 "reason": "the guard is not covered",
                                 "evidence": ["proposal#measure-2"]}],
                               decision="rejected")
        node = self.node("n04")
        self.assertEqual(node["outcome"], "rejected")
        self.assertEqual(node["checkResults"][0]["verdict"], "failed")
        self.assertEqual(node["checkResults"][0]["reason"],
                         "the guard is not covered")

    def test_a_shortage_may_carry_no_evidence(self):
        """A missing fact is reported as missing, not filled in."""
        self.build()
        self.instantiate()
        self.drive_agents()
        receipt = self.decide_with_items(
            [{"check": "N04-2", "verdict": "insufficient",
              "reason": "the standard text is not available to this reviewer"}],
            decision="request_material")
        self.assertEqual(receipt["decision"], "accepted")
        node = self.node("n04")
        self.assertEqual(node["state"], "running")
        self.assertEqual(node["checkResults"][0]["verdict"], "insufficient")
        self.assertEqual(node["checkResults"][0]["reason"],
                         "the standard text is not available to this reviewer")

    def test_a_pass_always_needs_its_evidence(self):
        self.build()
        self.instantiate()
        self.drive_agents()
        receipt = self.decide_with_items([{"check": "N04-2", "verdict": "passed",
                                           "reason": "checked", "evidence": []}])
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "WORKFLOW_CHECK_REPORT_INVALID")

    def test_the_report_records_the_judgment_context(self):
        self.build()
        self.instantiate()
        self.drive_agents()
        self.decide_with_items([{"check": "N04-2", "verdict": "passed",
                                 "reason": "every requirement is covered",
                                 "evidence": ["proposal#revision-1"]}])
        entry = self.node("n04")["checkResults"][0]
        self.assertEqual(entry["method"], "HUMAN")
        self.assertEqual(entry["decidedBy"], "reviewer-a")
        self.assertEqual(entry["criterionVersion"], "1")
        self.assertEqual(entry["reviewedInputDigest"],
                         self.node("n04")["inputDigest"])
        self.assertEqual(entry["reviewedOutputDigest"],
                         self.node("n04")["subject"]["digest"])
        self.assertTrue(entry["at"])
