"""A decision is judged after it is verified, and the newest decision wins.

`WorkflowEngine.command` settles the workflow right after the command it
ran. For a `record_decision` that is premature: the decision's evidence is
still `pending_verification` when the settle runs — the trusted verifier
runs afterwards — so the settle judges the **previous** decision.

The consequence is visible on a node that waits for a named output. The
human rejects without the record, the node waits (`WORKFLOW_OUTPUT_MISSING`
— correct), and the human then approves **with** the record. The command is
accepted, the record is written — and the node completes with the outcome
of the *rejection*: the approval is swallowed and the workflow routes on
the rejection.

These tests drive the **real command API** (`engine.command`) over the real
store. An unverified proof is never trusted: it may not complete a node,
and it may not be passed over in favour of an older decision either — the
node simply waits for the verifier.
"""

import json
import os
import sqlite3
import tempfile
import unittest

from work_runtime.runtime import Runtime
from work_runtime.workflow import WorkflowEngine
from work_runtime.workflow_demo import (INTAKE_SHAPE, RECORD_SHAPE,
                                         WorkflowDemoPolicy, workflow_demo_grants,
                                         workflow_demo_validators)

try:
    from workflow_support import submit_valid, version_of
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import submit_valid, version_of

WORK_ID = "W-1"
RUNNER = "workflow-runner"
REASON = "the material was judged against the criterion"
REFUSED = "the family refuses this approval"


class OpenPolicy(WorkflowDemoPolicy):
    """The demonstration family with its obligation already satisfied."""

    def evaluate(self, work, evidence):
        return [{"id": "R01:" + work["document"]["id"], "rule_id": "R01",
                 "subject": work["document"]["id"], "applicability": "applicable",
                 "fulfillment": "satisfied",
                 "explanation": "The obligation is satisfied in this fixture"}]


class StrictPolicy(OpenPolicy):
    """A family that refuses one named approval and admits the other.

    The refusal is the family's own rule, applied by the trusted verifier:
    the decision is admitted as evidence and then judged invalid, so it may
    never become an approval.
    """

    def validate_evidence(self, work, candidate):
        data = candidate.get("data") or {}
        if candidate.get("kind") == "safety_review":
            for item in data.get("items") or []:
                if item.get("reason") == REFUSED:
                    return False
        return super().validate_evidence(work, candidate)


def decision_template(template_id="decision-order", version="t1"):
    """One agent node and one human node that declares a named record.

    The human node declares the record for every decision — the default,
    with no narrowing — so a rejection without the record leaves the node
    waiting, exactly as the OA node ``M02`` does.
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
                                                  "validator": "record",
                                                  "validator_version": "1"}},
                        "checks": [{"id": "N02-1", "method": "HUMAN",
                                    "criterion": "The material is accepted "
                                                 "as it stands.",
                                    "criterion_version": "1",
                                    "validator": "safety-review",
                                    "validator_version": "1"}]}},
            "edges": [{"from": "n01", "to": "n02"}]}


class DecisionOrderTestCase(unittest.TestCase):
    """The fixture: one agent node, one human node, one named record."""

    policy = OpenPolicy

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-decision-")
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.counter = 0
        self.runtime, self.engine = self.build()
        self.template = decision_template()
        published = self.engine.publish_template("coordinator", self.template)
        self.assertEqual(published["decision"], "accepted", published)

    # -- helpers ---------------------------------------------------------

    def build(self):
        grants = workflow_demo_grants()
        grants[RUNNER] = {"workflow.finalize"}
        runtime = Runtime(self.path, self.policy(), grants)
        engine = WorkflowEngine(runtime, workflow_demo_validators(), runner=RUNNER)
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

    def decide(self, decision="rejected", result=None, attempt=1,
               actor="reviewer-a", source="reviewer-a", reason=REASON,
               verify=True, settle=True):
        """Admit a decision through the real command API.

        ``verify=False`` admits the decision without letting the trusted
        verifier judge it, and ``settle=False`` admits it without the
        engine's own settle pass — the two windows the routing must not
        act on an unverified proof in.
        """
        reference = self.subject_reference()
        verdict = {"approved": "passed", "rejected": "failed",
                   "request_material": "insufficient"}[decision]
        item = {"check": "N02-1", "verdict": verdict, "reason": reason}
        if verdict == "passed":
            item["evidence"] = ["intake#revision-" + str(reference["revision"])]
        payload = {"node": "n02", "attempt": attempt, "decision": decision,
                   "digest": reference["digest"], "revision": reference["revision"],
                   "actor": actor, "items": [item]}
        if result is not None:
            payload["result"] = result
        command_id = self.next_id("decision")
        if settle:
            receipt = self.engine.command(
                source, command_id, WORK_ID, "record_decision", payload,
                version_of(self.runtime, WORK_ID))
        else:
            receipt = self.runtime.command(
                source, command_id, WORK_ID, "record_decision", payload,
                version_of(self.runtime, WORK_ID))
        if verify and receipt.get("decision") == "accepted":
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

    def proofs(self):
        db = sqlite3.connect(self.path)
        try:
            return [json.loads(row[0]) for row in
                    db.execute("SELECT body FROM evidence WHERE work_id=?", (WORK_ID,))]
        finally:
            db.close()

    def object_rows(self, name="acceptance"):
        db = sqlite3.connect(self.path)
        try:
            return db.execute("SELECT * FROM workflow_objects WHERE work_id=? AND "
                              "name=?", (WORK_ID, name)).fetchall()
        finally:
            db.close()


class LawfulApprovalTests(DecisionOrderTestCase):
    """The decision that was made last is the one the node follows."""

    def test_a_lawful_approval_after_a_rejection_completes_the_node(self):
        self.drive_to_human()
        rejected = self.decide("rejected")
        self.assertEqual(rejected["decision"], "accepted", rejected)
        # The rejection stands and the node waits for the named record.
        self.assertEqual(self.node()["state"], "running")
        self.assertIsNone(self.node()["outcome"])
        approved = self.decide("approved", result=self.record())
        self.assertEqual(approved["decision"], "accepted", approved)
        # The node follows the decision that was made last.
        self.assertEqual(self.node()["state"], "completed")
        self.assertEqual(self.node()["outcome"], "approved")
        self.assertEqual(len(self.object_rows()), 1)

    def test_the_approval_binds_the_acceptance_to_the_exact_subject(self):
        self.drive_to_human()
        self.decide("rejected")
        self.decide("approved", result=self.record())
        binding = self.stored_node().get("output_binding") or {}
        self.assertEqual(binding.get("actor"), "reviewer-a")
        self.assertEqual(binding.get("subject", {}).get("digest"),
                         self.subject_reference()["digest"])
        self.assertEqual(self.stored_node()["quality"]["mode"], "validated")

    def test_the_old_rejection_stays_on_the_record(self):
        """The swallowed decision is never deleted: it stays on the record."""
        self.drive_to_human()
        self.decide("rejected")
        self.decide("approved", result=self.record())
        decisions = [(proof.get("data") or {}).get("decision")
                     for proof in self.proofs()
                     if proof.get("kind") == "safety_review"]
        self.assertIn("rejected", decisions)
        self.assertIn("approved", decisions)

    def test_the_first_decision_is_judged_as_before(self):
        """An ordinary first decision still completes the node at once."""
        self.drive_to_human()
        receipt = self.decide("approved", result=self.record())
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.assertEqual(self.node()["state"], "completed")
        self.assertEqual(self.node()["outcome"], "approved")

    def test_a_request_for_more_material_still_waits(self):
        self.drive_to_human()
        receipt = self.decide("request_material")
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.assertEqual(self.node()["state"], "running")
        self.assertIsNone(self.node()["outcome"])


class UnverifiedProofTests(DecisionOrderTestCase):
    """An unverified proof is never trusted — and never passed over."""

    def test_an_unverified_decision_does_not_settle_the_node(self):
        """While the verifier has not judged the decision, nothing settles."""
        self.drive_to_human()
        self.decide("rejected")
        self.assertEqual(self.node()["state"], "running")
        # The approval is admitted, but the verifier has not judged it and
        # the routing pass has not seen it.
        admitted = self.decide("approved", result=self.record(),
                               settle=False, verify=False)
        self.assertEqual(admitted["decision"], "accepted", admitted)
        # A routing pass must not settle the node on the older decision.
        self.engine.advance(WORK_ID, 5000)
        self.assertEqual(self.node()["state"], "running")
        self.assertIsNone(self.node()["outcome"])
        # And once the verifier has judged it, the node follows it.
        self.runtime.verify_pending(WORK_ID)
        self.engine.advance(WORK_ID, 5001)
        self.assertEqual(self.node()["state"], "completed")
        self.assertEqual(self.node()["outcome"], "approved")

    def test_an_unverified_decision_is_not_a_pass(self):
        """The node never completes on a proof nobody verified."""
        self.drive_to_human()
        self.decide("approved", result=self.record(), settle=False,
                    verify=False)
        self.engine.advance(WORK_ID, 5000)
        self.assertNotEqual(self.node()["state"], "completed")
        self.assertIsNone(self.node()["outcome"])


class InvalidDecisionTests(DecisionOrderTestCase):
    """A decision the family refuses never becomes an approval."""

    policy = StrictPolicy

    def test_an_invalid_decision_never_completes_the_node(self):
        self.drive_to_human()
        receipt = self.decide("approved", result=self.record(), reason=REFUSED)
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.engine.advance(WORK_ID, 5000)
        self.assertNotEqual(self.node()["outcome"], "approved")
        statuses = {proof.get("status") for proof in self.proofs()
                    if proof.get("kind") == "safety_review"}
        self.assertIn("invalid", statuses)

    def test_an_invalid_decision_leaves_the_node_waiting(self):
        self.drive_to_human()
        self.decide("rejected")
        self.decide("approved", result=self.record(), reason=REFUSED)
        self.engine.advance(WORK_ID, 5000)
        # The refusal is not an approval: the node is not accepted.
        self.assertNotEqual(self.node()["outcome"], "approved")
        # And the node waits for the record of the decision it follows.
        self.assertEqual(self.node()["state"], "running")

    def test_a_refused_decision_does_not_stick_the_node(self):
        """The refusal does not leave the node waiting for the verifier.

        The verifier has answered: the proof is not pending any more, so
        the routing pass settles the node again — on the decision that is
        on the record, not on the refused one.
        """
        self.drive_to_human()
        self.decide("rejected")
        self.decide("approved", result=self.record(), reason=REFUSED)
        self.engine.advance(WORK_ID, 5000)
        statuses = {proof.get("status") for proof in self.proofs()
                    if proof.get("kind") == "safety_review"}
        self.assertIn("invalid", statuses)
        self.assertNotIn("pending_verification", statuses)
        # The refusal is not an approval, and the node waits for the record
        # of the decision it follows.
        self.assertNotEqual(self.node()["outcome"], "approved")
        self.assertEqual(self.node()["state"], "running")
        # And the routing is not stuck: a later legitimate decision settles
        # the node.
        receipt = self.decide("approved", result=self.record("ACC-2"))
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.assertEqual(self.node()["state"], "completed")
        self.assertEqual(self.node()["outcome"], "approved")


if __name__ == "__main__":
    unittest.main()
