"""A judgment that does not agree with itself is a conflict, not a repetition.

The identity of a judgment is the fact it judged — a decision's proof, or
a material and the validator that judged it. The report follows from that
fact. A second, **different** report under the same identity is a
disagreement about the same fact: it is named, never dropped, and the
read model says so instead of showing one of the two verdicts as if it
were the truth.

The same rule holds for the routing: a decision the trusted verifier
refuses is never routed on, and the refusal does not leave the node
waiting for a verifier that has already answered.
"""

import json
import os
import sqlite3
import tempfile
import unittest

from work_runtime.runtime import Runtime
from work_runtime.workflow import WorkflowEngine
from work_runtime.workflow_demo import (INTAKE_SHAPE, RECORD_SHAPE,
                                         ValidatorRegistry, WorkflowDemoPolicy,
                                         workflow_demo_grants,
                                         workflow_demo_validators)

try:
    from workflow_support import submit_valid, version_of
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import submit_valid, version_of

WORK_ID = "W-1"
RUNNER = "workflow-runner"
REASON = "the material was judged against the criterion"


class OpenPolicy(WorkflowDemoPolicy):
    """The demonstration family with its obligation already satisfied."""

    def evaluate(self, work, evidence):
        return [{"id": "R01:" + work["document"]["id"], "rule_id": "R01",
                 "subject": work["document"]["id"], "applicability": "applicable",
                 "fulfillment": "satisfied",
                 "explanation": "The obligation is satisfied in this fixture"}]


class FlakyValidator:
    """A validator that does not always answer the same.

    It judges the same material twice and answers differently: the first
    time the criterion is not satisfied, the second time it is. The
    material and the validator are the same, so the identity of the
    judgment is the same — and the two answers disagree.
    """

    def __init__(self):
        self.calls = 0

    def __call__(self, work, node_ref, result):
        self.calls += 1
        passed = self.calls > 1
        verdict = "passed" if passed else "failed"
        reason = ("the record names what it archived" if passed
                  else "the record did not satisfy the criterion")
        checks = [{"check": check, "verdict": verdict, "reason": reason,
                   "evidence": ["record:" + str(result.get("recordId"))]}
                  for check in (node_ref.get("checks") or [])]
        return {"findings": [], "checks": checks}


def conflict_template(template_id="judgment-conflict", version="t1"):
    """One agent node and one human node with a program criterion.

    The human judges one criterion; the validator of the named record
    judges the other. That is what makes the two judgments of the same
    attempt comparable.
    """
    return {"id": template_id, "version": version,
            "policy_family": "workflow-demo", "entry": "n01",
            "terminal": ["n02"],
            "nodes": {
                "n01": {"kind": "agent", "executor": "agent-executor",
                        "max_attempts": 2,
                        "output": {"object": "intake",
                                   "validation": {"shape": INTAKE_SHAPE,
                                                  "validator": "intake",
                                                  "validator_version": "1"}},
                        "checks": [{"id": "N01-1", "method": "PROGRAM",
                                    "criterion": "Every record names its source.",
                                    "criterion_version": "1",
                                    "validator": "intake",
                                    "validator_version": "1"}]},
                "n02": {"kind": "human", "evidence_kind": "safety_review",
                        "authority": "reviewer-a",
                        "subject": {"object": "intake"},
                        "max_attempts": 2,
                        "output": {"object": "acceptance",
                                   "validation": {"shape": RECORD_SHAPE,
                                                  "validator": "flaky-record",
                                                  "validator_version": "1"}},
                        "checks": [{"id": "N02-1", "method": "HUMAN",
                                    "criterion": "The material is accepted "
                                                 "as it stands.",
                                    "criterion_version": "1",
                                    "validator": "safety-review",
                                    "validator_version": "1"},
                                   {"id": "N02-2", "method": "PROGRAM",
                                    "criterion": "The record names what it "
                                                 "archived.",
                                    "criterion_version": "1",
                                    "validator": "flaky-record",
                                    "validator_version": "1"}]}},
            "edges": [{"from": "n01", "to": "n02"}]}


class JudgmentConflictTestCase(unittest.TestCase):
    """The fixture: a validator that answers differently the second time."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-conflict-")
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.counter = 0
        self.flaky = FlakyValidator()
        self.runtime, self.engine = self.build()
        self.template = conflict_template()
        published = self.engine.publish_template("coordinator", self.template)
        self.assertEqual(published["decision"], "accepted", published)

    # -- helpers ---------------------------------------------------------

    def build(self):
        grants = workflow_demo_grants()
        grants[RUNNER] = {"workflow.finalize"}
        # The demonstration validators, plus the one that answers
        # differently the second time.
        demo = workflow_demo_validators()
        registry = ValidatorRegistry(dict(demo._entries))
        registry.register("flaky-record", "1", self.flaky)
        runtime = Runtime(self.path, OpenPolicy(), grants)
        engine = WorkflowEngine(runtime, registry, runner=RUNNER)
        return runtime, engine

    def next_id(self, label):
        self.counter += 1
        return "%s-%03d" % (label, self.counter)

    def instantiate(self):
        self.runtime.command("coordinator", self.next_id("create"), WORK_ID,
                             "create_work",
                             {"document": {"id": "H-001", "subject": "east parapet"}},
                             None)
        self.runtime.command("coordinator", self.next_id("contract"), WORK_ID,
                             "bind_contract",
                             {"policy_id": "workflow-demo",
                              "policy_version": "demo-1",
                              "goal": "workflow.completed"},
                             version_of(self.runtime, WORK_ID))
        self.runtime.command("coordinator", self.next_id("plan"), WORK_ID,
                             "revise_plan",
                             {"steps": ["n01", "n02"], "open_requirements": [],
                              "replan_when": []},
                             version_of(self.runtime, WORK_ID))
        receipt = self.engine.command("coordinator", self.next_id("bind"), WORK_ID,
                                      "bind_workflow",
                                      {"template_id": self.template["id"],
                                       "template_version": self.template["version"],
                                       "parameters": {"subject": "east parapet"}},
                                      version_of(self.runtime, WORK_ID))
        self.assertEqual(receipt["decision"], "accepted", receipt)

    def drive_to_human(self):
        self.instantiate()
        self.engine.advance(WORK_ID, 1000)
        submitted = submit_valid(self.engine, self.runtime, WORK_ID, "n01", "intake")
        self.assertEqual(submitted["decision"], "accepted", submitted)
        self.engine.advance(WORK_ID, 1000)
        self.assertEqual(self.node()["state"], "running")

    def subject_reference(self):
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT revision,digest FROM workflow_objects "
                             "WHERE work_id=? AND name='intake' ORDER BY revision "
                             "DESC LIMIT 1", (WORK_ID,)).fetchone()
        finally:
            db.close()
        return {"revision": row[0], "digest": row[1]}

    def decide(self, decision="approved", result=None, attempt=1,
               actor="reviewer-a", source="reviewer-a", reason=REASON):
        reference = self.subject_reference()
        verdict = {"approved": "passed", "rejected": "failed"}[decision]
        item = {"check": "N02-1", "verdict": verdict, "reason": reason}
        if verdict == "passed":
            item["evidence"] = ["intake#revision-" + str(reference["revision"])]
        payload = {"node": "n02", "attempt": attempt, "decision": decision,
                   "digest": reference["digest"], "revision": reference["revision"],
                   "actor": actor, "items": [item]}
        if result is not None:
            payload["result"] = result
        receipt = self.engine.command(
            source, self.next_id("decision"), WORK_ID, "record_decision",
            payload, version_of(self.runtime, WORK_ID))
        if receipt.get("decision") == "accepted":
            self.runtime.verify_pending(WORK_ID)
        return receipt

    def record(self, record_id="ACC-1"):
        return {"recordId": record_id, "kind": "safety_review",
                "actor": "reviewer-a", "items": ["M-1"]}

    def node(self, node="n02"):
        for entry in self.engine.instance(WORK_ID)["nodes"]:
            if entry["node"] == node:
                return entry
        return {}

    def stored_node(self, node="n02", attempt=None):
        db = sqlite3.connect(self.path)
        try:
            if attempt is None:
                row = db.execute("SELECT body FROM workflow_nodes WHERE work_id=? AND "
                                 "node=? ORDER BY attempt DESC LIMIT 1",
                                 (WORK_ID, node)).fetchone()
            else:
                row = db.execute("SELECT body FROM workflow_nodes WHERE work_id=? AND "
                                 "node=? AND attempt=?",
                                 (WORK_ID, node, attempt)).fetchone()
        finally:
            db.close()
        return json.loads(row[0]) if row else {}


class ConflictingJudgmentTests(JudgmentConflictTestCase):
    """The same judgment, two different answers."""

    def test_the_conflict_is_named_and_never_swallowed(self):
        self.drive_to_human()
        # The first approval: the validator refuses the record, so the node
        # keeps waiting and the judgment of the record is on the record.
        first = self.decide("approved", result=self.record())
        self.assertEqual(first["decision"], "accepted", first)
        self.assertEqual(self.node()["state"], "running")
        # The second approval carries the same record: the same material,
        # the same validator — and the validator answers differently.
        second = self.decide("approved", result=self.record())
        self.assertEqual(second["decision"], "accepted", second)
        self.assertGreater(self.flaky.calls, 1)
        # The judgment did not agree with itself, and it says so.
        judgments = self.stored_node().get("judgments") or []
        conflicted = [judgment for judgment in judgments
                      if judgment.get("conflicts")]
        self.assertTrue(conflicted, judgments)
        self.assertIn("N02-2", conflicted[0]["conflicts"])

    def test_the_reader_is_told_about_the_conflict(self):
        self.drive_to_human()
        self.decide("approved", result=self.record())
        self.decide("approved", result=self.record())
        reports = {report["checkId"]: report
                   for report in self.node()["checkResults"]}
        self.assertIn("N02-2", reports)
        # Neither of the two verdicts is presented as the truth.
        self.assertEqual(reports["N02-2"]["verdict"], "conflict")
        self.assertIn("two different verdicts", reports["N02-2"]["reason"])
        # And the criterion the human judged is untouched by it.
        self.assertEqual(reports["N02-1"]["verdict"], "passed")

    def test_a_repetition_is_not_a_conflict(self):
        """The same judgment, re-derived, stays one judgment."""
        self.drive_to_human()
        self.decide("approved", result=self.record())
        self.engine.advance(WORK_ID, 5000)
        self.engine.advance(WORK_ID, 5001)
        judgments = self.stored_node().get("judgments") or []
        for judgment in judgments:
            self.assertFalse(judgment.get("conflicts"), judgment)


if __name__ == "__main__":
    unittest.main()
