"""The asynchronous review of an agent candidate.

A node that declares a review gets a durable review intent that pins the
rubric, the criteria, the candidate revision and the input digest, and the
review proof must bind the exact work, node, attempt and digests. A review
of a previous attempt never satisfies the current one, and the reviewer may
not be the executor.
"""

import os
import tempfile
import unittest
import uuid

try:
    from workflow_support import (RecordingAdapter, build, decide, demo_grants,
                                  instantiate, scenario_template, send,
                                  submit_valid, version_of)
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import (RecordingAdapter, build, decide, demo_grants,
                                        instantiate, scenario_template, send,
                                        submit_valid, version_of)


class ReviewTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-workflow-review-")
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

    def drive_to_review(self):
        for node, name in (("n01", "intake"), ("n02", "analysis"), ("n03", "proposal")):
            receipt = submit_valid(self.engine, self.runtime, self.work_id, node, name)
            self.assertEqual(receipt["decision"], "accepted", receipt)
        proposal = self.node("n03")["outputs"][0]
        decide(self.runtime, self.engine, self.work_id, "safety_review",
               "reviewer-a", "approved", proposal["digest"], proposal["revision"])
        decide(self.runtime, self.engine, self.work_id, "project_approval",
               "reviewer-b", "approved", proposal["digest"], proposal["revision"])
        self.engine.pump(RecordingAdapter(os.path.join(self.folder, "effects.sqlite")),
                         1000)
        order = self.node("n06")["outputs"][0]
        decide(self.runtime, self.engine, self.work_id, "field_report",
               "responsible-c", "approved", order["digest"], order["revision"])
        decide(self.runtime, self.engine, self.work_id, "independent_review",
               "reviewer-d", "approved", order["digest"], order["revision"])
        self.assertEqual(self.node("n09")["state"], "running")

    def submit_report(self, attempt=1):
        node = self.node("n09")
        receipt = submit_valid(self.engine, self.runtime, self.work_id, "n09", "report")
        self.assertEqual(receipt["decision"], "accepted", receipt)
        return self.node("n09")

    def review_proof(self, node, attempt=1, producer="reviewer-v", input_digest=None,
                     output_digest=None, event_id=None, verdict="passed"):
        data = {"node": "n09", "attempt": attempt,
                "input_digest": input_digest or node["inputDigest"],
                "output_digest": output_digest or node["outputs"][0]["digest"],
                "producer": producer, "verdict": verdict,
                "items": [{"check": "N09-2-review", "verdict": verdict,
                           "reason": "the report follows the signed record",
                           "evidence": ["proposal#revision-1"]}]}
        receipt = send(self.runtime, "reviewer-v", self.work_id, "record_evidence",
                       {"event_id": event_id or uuid.uuid4().hex,
                        "kind": "agent_review", "data": data})
        self.runtime.verify_pending(self.work_id)
        self.engine.advance(self.work_id, 1000)
        return receipt


class ReviewIntentTests(ReviewTestCase):
    def test_a_review_node_creates_a_durable_review_intent(self):
        self.drive_to_review()
        self.submit_report()
        intents = self.engine.intents(kind="review_task", status=None)
        self.assertEqual(len(intents), 1)
        intent = intents[0]
        self.assertTrue(intent["id"].endswith(":review_task"))
        self.assertEqual(intent["node"], "n09")
        self.assertEqual(intent["reviewer"], "reviewer-v")
        self.assertEqual(intent["rubric"]["validator"], "review-rubric")
        self.assertEqual(intent["rubric"]["validator_version"], "1")
        self.assertTrue(intent["candidate"]["digest"])
        self.assertTrue(intent["input_digest"])
        self.assertTrue(intent["criteria"])
        self.assertEqual(intent["criteria"][0]["id"], "N09-2")
        self.assertTrue(intent["criteria"][0]["criterion"])


class ReviewEvidenceTests(ReviewTestCase):
    def test_a_complete_review_completes_the_node(self):
        self.drive_to_review()
        node = self.submit_report()
        self.assertEqual(node["state"], "submitted")
        self.review_proof(node)
        node = self.node("n09")
        self.assertEqual(node["state"], "completed")
        report = [entry for entry in node["checkResults"]
                  if entry["method"] == "AGENT"]
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]["checkId"], "N09-2-review")
        self.assertEqual(report[0]["decidedBy"], "reviewer-v")
        # The program check of the same requirement keeps its own record.
        program = [entry for entry in node["checkResults"]
                   if entry["method"] == "PROGRAM"]
        self.assertEqual([entry["checkId"] for entry in program], ["N09-2"])
        self.assertEqual(report[0]["reviewedInputDigest"], node["inputDigest"])
        self.assertEqual(report[0]["reviewedOutputDigest"],
                         node["outputs"][0]["digest"])

    def test_a_review_of_another_attempt_does_not_satisfy(self):
        self.drive_to_review()
        node = self.submit_report()
        self.review_proof(node, attempt=2)
        self.assertNotEqual(self.node("n09")["state"], "completed")

    def test_a_review_of_another_input_does_not_satisfy(self):
        self.drive_to_review()
        node = self.submit_report()
        self.review_proof(node, input_digest="0" * 64)
        self.assertNotEqual(self.node("n09")["state"], "completed")

    def test_a_review_of_another_candidate_does_not_satisfy(self):
        self.drive_to_review()
        node = self.submit_report()
        self.review_proof(node, output_digest="0" * 64)
        self.assertNotEqual(self.node("n09")["state"], "completed")

    def test_the_executor_may_not_review_its_own_candidate(self):
        self.drive_to_review()
        node = self.submit_report()
        self.review_proof(node, producer="agent-executor")
        self.assertNotEqual(self.node("n09")["state"], "completed")

    def test_only_the_declared_reviewer_may_review(self):
        self.drive_to_review()
        node = self.submit_report()
        self.review_proof(node, producer="someone-else")
        self.assertNotEqual(self.node("n09")["state"], "completed")

    def test_a_same_digest_review_of_an_earlier_attempt_does_not_satisfy(self):
        self.drive_to_review()
        node = self.submit_report()
        # The review rejects the candidate: the node is reworked.
        self.review_proof(node, attempt=1, verdict="failed")
        # The rejected candidate is reworked as a new attempt.
        self.assertEqual(self.node("n09")["attempt"], 2)
        self.assertEqual(self.node("n09")["state"], "running")
        # A review of the first attempt must not satisfy the second one, even
        # when the candidate is identical.
        self.review_proof(node, attempt=1)
        self.assertNotEqual(self.node("n09")["state"], "completed")


class AttemptHistoryTests(ReviewTestCase):
    def test_the_judgment_history_is_readable_per_attempt(self):
        self.drive_to_review()
        node = self.submit_report()
        self.review_proof(node, attempt=1, verdict="failed")
        history = self.engine.attempts(self.work_id, "n09")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["attempt"], 1)
        self.assertEqual(history[0]["state"], "failed")
        self.assertEqual(history[1]["attempt"], 2)
        # The judgment of the first attempt is still on the record.
        reports = history[0]["checkResults"]
        self.assertTrue(any(entry["method"] == "AGENT" for entry in reports))
