"""Authority, attempt binding and per-check reports in the mixed-node engine.

These cases come from the coordinator's review of the first slice:

* a decision is bound to the node *and* the attempt, so a same-digest
  approval of an earlier attempt never satisfies a later one;
* the *actor* of a decision is the asserted principal, not the ingress
  source: the source is the platform ingress and says nothing about who
  decided;
* every declared criterion carries a verdict, a reason and its evidence, and
  the verdict is persisted, not only the check identifier;
* a request for more material keeps the node waiting; it is neither an
  approval nor a rejection;
* a candidate is bound to the input digest it was produced from.
"""

import os
import sqlite3
import tempfile
import unittest

try:
    from workflow_support import (DemoPolicy, build, decide, demo_grants,
                                  instantiate, scenario_template, send,
                                  submit, submit_valid, version_of)
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import (DemoPolicy, build, decide, demo_grants,
                                        instantiate, scenario_template, send,
                                        submit, submit_valid, version_of)


class AuthorityTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-workflow-authority-")
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.runtime, self.engine = build(self.path)
        self.work_id = "W-1"
        self.engine.publish_template("coordinator", scenario_template())
        instantiate(self.runtime, self.engine, self.work_id)

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

    def proofs(self):
        db = sqlite3.connect(self.path)
        try:
            return [row[0] for row in
                    db.execute("SELECT body FROM evidence WHERE work_id=?",
                               (self.work_id,))]
        finally:
            db.close()


class DecisionBindingTests(AuthorityTestCase):
    def test_a_decision_must_name_the_node_and_the_attempt(self):
        self.drive_agents()
        # A decision that names no node and no attempt never matches.
        receipt = send(self.runtime, "reviewer-a", self.work_id, "record_evidence", {
            "event_id": "evt-unbound", "kind": "safety_review",
            "data": {"decision": "approved", "digest": self.proposal()["digest"],
                     "revision": self.proposal()["revision"], "actor": "reviewer-a",
                     "items": [{"check": "N04-2", "verdict": "passed",
                                "reason": "reviewed", "evidence": ["doc-1"]}]}})
        self.assertEqual(receipt["decision"], "accepted")
        self.runtime.verify_pending(self.work_id)
        self.engine.advance(self.work_id, 1000)
        self.assertNotEqual(self.node("n04")["state"], "completed")
        # A decision made for another attempt never matches either.
        decide(self.runtime, self.engine, self.work_id, "safety_review",
               "reviewer-a", "approved", self.proposal()["digest"],
               self.proposal()["revision"], node="n04", attempt=7)
        self.assertNotEqual(self.node("n04")["state"], "completed")

    def test_a_same_digest_approval_of_an_earlier_attempt_is_refused(self):
        self.drive_agents()
        decide(self.runtime, self.engine, self.work_id, "safety_review",
               "reviewer-a", "approved", self.proposal()["digest"],
               self.proposal()["revision"], node="n04", attempt=1)
        self.assertEqual(self.node("n04")["state"], "completed")
        # The reviewer asks for a rework; the same proposal content is
        # approved again by the same person.
        decide(self.runtime, self.engine, self.work_id, "project_approval",
               "reviewer-b", "rejected", self.proposal()["digest"],
               self.proposal()["revision"], node="n05", attempt=1)
        submit_valid(self.engine, self.runtime, self.work_id, "n03", "proposal")
        self.assertEqual(self.node("n04")["attempt"], 2)
        # The old approval covers the same digest but the old attempt.
        self.assertNotEqual(self.node("n04")["state"], "completed")
        decide(self.runtime, self.engine, self.work_id, "safety_review",
               "reviewer-a", "approved", self.proposal()["digest"],
               self.proposal()["revision"], node="n04", attempt=2)
        self.assertEqual(self.node("n04")["state"], "completed")

    def test_the_actor_of_a_decision_is_not_the_ingress_source(self):
        self.drive_agents()
        # The platform ingress writes the proof; the asserted actor is the
        # human. A decision whose actor is not the assigned authority is
        # refused, and the ingress source is never used as the actor.
        receipt = send(self.runtime, "reviewer-a", self.work_id, "record_evidence", {
            "event_id": "evt-1", "kind": "safety_review",
            "data": {"decision": "approved", "digest": self.proposal()["digest"],
                     "revision": self.proposal()["revision"], "node": "n04",
                     "attempt": 1, "actor": "someone-else",
                     "items": [{"check": "N04-2", "verdict": "passed",
                                "reason": "reviewed", "evidence": ["doc-1"]}]}})
        self.assertEqual(receipt["decision"], "accepted")
        self.runtime.verify_pending(self.work_id)
        self.engine.advance(self.work_id, 1000)
        node = self.node("n04")
        self.assertNotEqual(node["state"], "completed")
        self.assertTrue(any(finding["code"] == "WORKFLOW_AUTHORITY_MISMATCH"
                            for finding in node["findings"]))

    def test_a_request_for_more_material_keeps_the_node_waiting(self):
        self.drive_agents()
        decide(self.runtime, self.engine, self.work_id, "safety_review",
               "reviewer-a", "request_material", self.proposal()["digest"],
               self.proposal()["revision"], node="n04", attempt=1)
        node = self.node("n04")
        self.assertEqual(node["state"], "running")
        self.assertIsNone(node["outcome"])
        self.assertEqual(self.engine.instance(self.work_id)["currentNode"], "n04")
        # The request is on the record.
        stored = [proof for proof in self.proofs() if "request_material" in proof]
        self.assertEqual(len(stored), 1)

    def test_every_declared_criterion_carries_a_verdict(self):
        self.drive_agents()
        decide(self.runtime, self.engine, self.work_id, "safety_review",
               "reviewer-a", "approved", self.proposal()["digest"],
               self.proposal()["revision"], node="n04", attempt=1,
               items=[])
        node = self.node("n04")
        self.assertNotEqual(node["state"], "completed")
        self.assertTrue(any(finding["code"] == "WORKFLOW_CHECK_RESULT_MISSING"
                            for finding in node["findings"]))

    def test_the_check_report_is_persisted_and_readable(self):
        self.drive_agents()
        decide(self.runtime, self.engine, self.work_id, "safety_review",
               "reviewer-a", "approved", self.proposal()["digest"],
               self.proposal()["revision"], node="n04", attempt=1,
               items=[{"check": "N04-2", "verdict": "passed",
                        "reason": "the proposal covers every requirement",
                        "evidence": ["proposal#revision-1"]}])
        node = self.node("n04")
        self.assertEqual(node["state"], "completed")
        report = node["checkResults"]
        self.assertEqual(len(report), 2)
        entry = [item for item in report if item["checkId"] == "N04-2"][0]
        self.assertEqual(entry["verdict"], "passed")
        self.assertEqual(entry["reason"], "the proposal covers every requirement")
        self.assertEqual(entry["evidence"], ["proposal#revision-1"])
        self.assertEqual(entry["decidedBy"], "reviewer-a")
        self.assertEqual(entry["method"], "HUMAN")
        # The named record the decision carries has its own program record:
        # a validator judges it, not the human.
        judged = [item for item in report if item["checkId"] == "N04-3"][0]
        self.assertEqual(judged["verdict"], "passed")
        self.assertEqual(judged["method"], "PROGRAM")
        self.assertEqual(judged["validator"], "record")
        self.assertEqual(judged["validatorVersion"], "1")
        self.assertIsNone(judged["decidedBy"])
        self.assertTrue(judged["reviewedOutputDigest"])


class InputBindingTests(AuthorityTestCase):
    def test_a_candidate_must_be_bound_to_the_current_input_digest(self):
        self.engine.advance(self.work_id, 1000)
        receipt = submit(self.engine, self.runtime, self.work_id, "n01", 1, "intake",
                         {"records": [{"id": "R-1", "source": "s"}], "standard": "STD"},
                         input_digest="0" * 64)
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "WORKFLOW_INPUT_STALE")

    def test_the_current_input_digest_is_accepted(self):
        self.engine.advance(self.work_id, 1000)
        node = self.node("n01")
        digest_value = node["inputDigest"]
        self.assertTrue(digest_value)
        receipt = submit(self.engine, self.runtime, self.work_id, "n01", 1, "intake",
                         {"records": [{"id": "R-1", "source": "s"}], "standard": "STD"},
                         input_digest=digest_value)
        self.assertEqual(receipt["decision"], "accepted", receipt)

    def test_the_input_digest_follows_the_pinned_input(self):
        submit_valid(self.engine, self.runtime, self.work_id, "n01", "intake")
        node = self.node("n02")
        pinned = node["inputDigest"]
        self.assertTrue(pinned)
        self.assertEqual(node["inputs"][0]["name"], "intake")
        receipt = submit(self.engine, self.runtime, self.work_id, "n02", 1, "analysis",
                         {"findings": [{"issueId": "H-001", "clause": "C-1",
                                        "finding": "gap"}]},
                         input_digest="0" * 64)
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "WORKFLOW_INPUT_STALE")
        receipt = submit(self.engine, self.runtime, self.work_id, "n02", 1, "analysis",
                         {"findings": [{"issueId": "H-001", "clause": "C-1",
                                        "finding": "gap"}]},
                         input_digest=pinned)
        self.assertEqual(receipt["decision"], "accepted", receipt)


class CriterionTextTests(AuthorityTestCase):
    def test_the_published_definition_carries_the_criterion_text(self):
        template = scenario_template()
        checks = template["nodes"]["n04"]["checks"]
        self.assertEqual(len(checks), 2)
        entry = [check for check in checks if check["id"] == "N04-2"][0]
        self.assertTrue(entry["criterion"])
        self.assertEqual(entry["validator"], "safety-review")
        self.assertEqual(entry["validator_version"], "1")
        self.assertEqual(entry["method"], "HUMAN")
        program = [check for check in checks if check["id"] == "N04-3"][0]
        self.assertTrue(program["criterion"])
        self.assertEqual(program["validator"], "record")
        self.assertEqual(program["validator_version"], "1")
        self.assertEqual(program["method"], "PROGRAM")

    def test_a_criterion_validator_must_resolve_at_publication(self):
        template = scenario_template(template_id="broken", version="v1")
        template["nodes"]["n04"]["checks"][0]["validator_version"] = "9"
        receipt = self.engine.publish_template("coordinator", template)
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "WORKFLOW_VALIDATOR_UNKNOWN")


if __name__ == "__main__":
    unittest.main()
