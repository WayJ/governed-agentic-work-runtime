"""A named output is bound to the verified decision that produced it.

The named record a human decision carries is written inside the decision's
own compare-and-swap guarded command — and the decision's evidence is
verified **after** that command. A decision the family refuses has
therefore already written its record, and nothing bound that record to
the decision that carried it.

The consequence was a mixed node: the human rejects without the record,
the human approves **with** a record, the family refuses that approval —
and the node completes with the outcome of the rejection and the output of
the refused approval. The record satisfied the output requirement of a
decision it had nothing to do with, and the read model presented it as
the node's accepted output.

These tests drive the real command API over the real store. A record is
adopted only by the decision that carried it, and only when that decision
is verified; everything else stays a candidate on the record.
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
ACCEPTED = "the family accepts this approval"


class SelectivePolicy(WorkflowDemoPolicy):
    """A family that refuses one named approval and admits the other.

    The refusal is the family's own rule, applied by the trusted verifier:
    the decision is admitted as evidence and then judged invalid, so it may
    never become an approval.
    """

    def evaluate(self, work, evidence):
        return [{"id": "R01:" + work["document"]["id"], "rule_id": "R01",
                 "subject": work["document"]["id"], "applicability": "applicable",
                 "fulfillment": "satisfied",
                 "explanation": "The obligation is satisfied in this fixture"}]

    def validate_evidence(self, work, candidate):
        data = candidate.get("data") or {}
        if candidate.get("kind") == "safety_review":
            for item in data.get("items") or []:
                if item.get("reason") == REFUSED:
                    return False
        return super().validate_evidence(work, candidate)


def binding_template(on_decisions=None, rework=False,
                     template_id="decision-output-binding", version="t1"):
    """One agent node and one human node with a named record.

    The human node declares two criteria — one the human judges and one
    the validator of the record judges — so the projection can show both.
    """
    human = {"kind": "human", "evidence_kind": "safety_review",
             "authority": "reviewer-a", "subject": {"object": "intake"},
             "max_attempts": 2,
             "output": {"object": "acceptance",
                        "validation": {"shape": RECORD_SHAPE,
                                       "validator": "record",
                                       "validator_version": "1"}},
             "checks": [{"id": "N02-1", "method": "HUMAN",
                         "criterion": "The material is accepted as it stands.",
                         "criterion_version": "1",
                         "validator": "safety-review",
                         "validator_version": "1"},
                        {"id": "N02-2", "method": "PROGRAM",
                         "criterion": "The record names what it archived.",
                         "criterion_version": "1",
                         "validator": "record",
                         "validator_version": "1"}]}
    if on_decisions is not None:
        human["output"]["on_decisions"] = list(on_decisions)
    if rework:
        human["on_reject"] = "n01"
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
                "n02": human},
            "edges": [{"from": "n01", "to": "n02"}]}


class OutputBindingTestCase(unittest.TestCase):
    """The fixture: one agent node, one human node, one named record."""

    policy = SelectivePolicy

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-binding-")
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.counter = 0
        self.runtime, self.engine = self.build()
        self.template = binding_template()
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

    def instantiate(self, template=None):
        template = template or self.template
        published = self.engine.publish_template("coordinator", template)
        self.assertEqual(published["decision"], "accepted", published)
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
                                      {"template_id": template["id"],
                                       "template_version": template["version"],
                                       "parameters": {"subject": "east parapet"}},
                                      version_of(self.runtime, WORK_ID))
        self.assertEqual(receipt["decision"], "accepted", receipt)

    def drive_to_human(self, template=None):
        self.instantiate(template)
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
               actor="reviewer-a", source="reviewer-a", reason=REASON,
               settle=True, verify=True):
        """Admit a decision through the real command API."""
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


class RefusedApprovalTests(OutputBindingTestCase):
    """A decision the family refuses produces no adopted output."""

    def test_the_old_rejection_is_not_completed_by_a_refused_approval(self):
        """The refusal does not let the previous decision complete the node."""
        self.drive_to_human()
        rejected = self.decide("rejected")
        self.assertEqual(rejected["decision"], "accepted", rejected)
        self.assertEqual(self.node()["state"], "running")
        # The approval carries a record, and the family refuses it.
        refused = self.decide("approved", result=self.record(), reason=REFUSED)
        self.assertEqual(refused["decision"], "accepted", refused)
        statuses = {proof.get("status") for proof in self.proofs()
                    if proof.get("kind") == "safety_review"}
        self.assertIn("invalid", statuses)
        # The node is not completed on the rejection: the record the refused
        # approval carried is not the rejection's output.
        self.assertEqual(self.node()["state"], "running")
        self.assertIsNone(self.node()["outcome"])

    def test_the_refused_record_is_not_an_accepted_output(self):
        self.drive_to_human()
        self.decide("rejected")
        self.decide("approved", result=self.record(), reason=REFUSED)
        # The read model shows no accepted output.
        self.assertEqual(self.node()["outputs"], [])
        self.assertNotEqual(self.node()["quality"]["mode"], "validated")
        # The record itself is kept: the history is never rewritten.
        self.assertEqual(len(self.object_rows()), 1)

    def test_the_refused_record_is_not_a_judged_criterion(self):
        """The check projection does not show the candidate as judged."""
        self.drive_to_human()
        self.decide("rejected")
        self.decide("approved", result=self.record(), reason=REFUSED)
        reports = {report["checkId"]: report
                   for report in self.node()["checkResults"]}
        self.assertIn("N02-1", reports)
        self.assertNotIn("N02-2", reports)

    def test_the_node_waits_for_the_record_of_the_decision_it_follows(self):
        """The waiting is explicit: the missing output says what is missing."""
        self.drive_to_human()
        self.decide("rejected")
        self.decide("approved", result=self.record(), reason=REFUSED)
        codes = [finding["code"] for finding in self.node()["findings"] or []]
        self.assertIn("WORKFLOW_OUTPUT_MISSING", codes)


class PendingDecisionTests(OutputBindingTestCase):
    """A record whose decision is not verified is never adopted."""

    def test_a_pending_decision_record_is_not_adopted(self):
        self.drive_to_human()
        self.decide("rejected")
        # The approval is admitted, but the verifier has not judged it.
        admitted = self.decide("approved", result=self.record(),
                               reason=ACCEPTED, settle=False, verify=False)
        self.assertEqual(admitted["decision"], "accepted", admitted)
        self.engine.advance(WORK_ID, 5000)
        self.assertEqual(self.node()["state"], "running")
        self.assertEqual(self.node()["outputs"], [])
        # The record is kept as a candidate, not as the node's output.
        stored = self.stored_node()
        self.assertTrue(stored.get("output_candidate"))
        self.assertIsNone(stored.get("output"))


class LaterValidDecisionTests(OutputBindingTestCase):
    """A later legitimate decision brings its own record."""

    def setUp(self):
        super().setUp()
        self.drive_to_human()
        self.decide("rejected")
        self.decide("approved", result=self.record(), reason=REFUSED)

    def test_a_later_valid_approval_completes_the_node(self):
        receipt = self.decide("approved", result=self.record("ACC-2"),
                              reason=ACCEPTED)
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.assertEqual(self.node()["state"], "completed")
        self.assertEqual(self.node()["outcome"], "approved")
        self.assertEqual(len(self.node()["outputs"]), 1)

    def test_the_adopted_output_is_the_record_of_that_decision(self):
        self.decide("approved", result=self.record("ACC-2"), reason=ACCEPTED)
        binding = self.stored_node().get("output_binding") or {}
        # The binding names the decision that carried the record.
        event_id = binding.get("eventId")
        self.assertTrue(event_id, binding)
        verified = [proof for proof in self.proofs()
                    if proof.get("event_id") == event_id]
        self.assertEqual(len(verified), 1)
        self.assertEqual(verified[0]["status"], "verified")
        # The record it carried is the adopted one: the later decision's
        # record, not the refused one.
        self.assertEqual(binding.get("object", {}).get("name"), "acceptance")
        rows = self.object_rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(binding["object"]["revision"], rows[-1][2])
        self.assertIn("ACC-2", rows[-1][4])
        self.assertIn("ACC-1", rows[0][4])

    def test_the_refused_record_is_not_reused(self):
        """The deferral lifting does not make the refused record usable."""
        self.decide("approved", result=self.record("ACC-2"), reason=ACCEPTED)
        binding = self.stored_node().get("output_binding") or {}
        refused = [proof for proof in self.proofs()
                   if proof.get("status") == "invalid"]
        self.assertEqual(len(refused), 1)
        self.assertNotEqual(binding.get("eventId"), refused[0].get("event_id"))


class ExemptDecisionTests(OutputBindingTestCase):
    """With the record exempt for a rejection, the rejection carries none."""

    def test_the_rejection_carries_no_record_of_a_refused_approval(self):
        template = binding_template(on_decisions=["approved"],
                                    template_id="binding-exempt")
        self.drive_to_human(template)
        # The refused approval writes its record as a candidate.
        refused = self.decide("approved", result=self.record(), reason=REFUSED)
        self.assertEqual(refused["decision"], "accepted", refused)
        # The rejection does not need a record: it settles the node.
        rejected = self.decide("rejected", reason=REASON)
        self.assertEqual(rejected["decision"], "accepted", rejected)
        self.assertEqual(self.node()["state"], "completed")
        self.assertEqual(self.node()["outcome"], "rejected")
        # And the record of the refused approval is not delivered as the
        # node's output.
        self.assertEqual(self.node()["outputs"], [])
        self.assertIsNone(self.stored_node().get("output"))


class UnchangedBehaviourTests(OutputBindingTestCase):
    """The ordinary paths keep their behaviour."""

    def test_the_first_approval_still_completes_the_node(self):
        self.drive_to_human()
        receipt = self.decide("approved", result=self.record())
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.assertEqual(self.node()["state"], "completed")
        self.assertEqual(self.node()["outcome"], "approved")
        self.assertEqual(len(self.node()["outputs"]), 1)
        self.assertEqual(self.stored_node()["quality"]["mode"], "validated")

    def test_a_real_rejection_still_reaches_its_rework_branch(self):
        template = binding_template(on_decisions=["approved"], rework=True,
                                    template_id="binding-rework")
        self.drive_to_human(template)
        receipt = self.decide("rejected", reason=REASON)
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.engine.advance(WORK_ID, 2000)
        work = self.runtime.get_work(WORK_ID)
        self.assertEqual(work["workflow_current"], "n01")
        self.assertEqual(self.node("n01")["attempt"], 2)


if __name__ == "__main__":
    unittest.main()
