"""A rejected candidate, the exhausted allowance and the return.

The shape is the OA daily report: an agent node ``M01`` writes the
candidate, a human node ``M02`` decides on it and may send it back with
``on_reject``, and a downstream node ``M03`` consumes the acceptance
record.

Two things are under test, and they are kept apart on purpose:

* **the exhausted allowance** (``max_attempts: 1`` on the human node, the
  shape ``oa-4`` published): the reworked candidate is kept, the work
  escalates **stably**, the cursor never points at a node whose attempt
  was not opened, and the old rejection is never consumed again — the
  agent is not asked a third time;
* **the return** (``max_attempts: 2`` on the human node, the shape the
  next published definition declares): the candidate is offered to the
  human again on a **new** attempt, the old decision does not answer the
  new attempt, the new decision binds the new attempt and the new
  candidate, the old attempt keeps its history, and a new approval
  advances the work downstream.

The defect this wave fixes is the first one: when the routing could not
open the successor, the work was left pointing at the successor's
attempt — which had already been routed from — and the next pass routed
from it **again**. The old rejection was consumed twice and the work
walked past the node it could not open.
"""

import json
import os
import sqlite3
import tempfile
import unittest

from work_runtime.runtime import Runtime
from work_runtime.workflow import WorkflowEngine
from work_runtime.workflow_demo import (ANALYSIS_SHAPE, INTAKE_SHAPE, RECORD_SHAPE,
                                         WorkflowDemoPolicy, workflow_demo_grants,
                                         workflow_demo_validators)

try:
    from workflow_support import submit_valid, version_of
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import submit_valid, version_of

WORK_ID = "W-1"
REVIEWER = "reviewer-a"
EVIDENCE_KIND = "safety_review"

CANDIDATE = {"records": [{"id": "R-1", "source": "site-log"}], "standard": "STD-1"}
REWORKED = {"records": [{"id": "R-2", "source": "site-log"}], "standard": "STD-1"}


def daily_template(human_attempts=None):
    """The OA shape: an agent, a human that may send the candidate back.

    ``human_attempts`` is the allowance the human node declares. ``None``
    keeps the core default; the two shapes under test declare it
    explicitly, so the tests say which budget they mean.
    """
    human = {"kind": "human", "evidence_kind": EVIDENCE_KIND,
             "authority": REVIEWER,
             "subject": {"object": "intake"},
             "on_reject": "M01",
             "output": {"object": "acceptance",
                        "on_decisions": ["approved"],
                        "validation": {"shape": RECORD_SHAPE,
                                       "validator": "record",
                                       "validator_version": "1"}},
             "checks": [{"id": "M02-1", "method": "HUMAN",
                         "criterion": "The candidate is judged item by item.",
                         "criterion_version": "1",
                         "validator": "safety-review",
                         "validator_version": "1"}]}
    if human_attempts is not None:
        human["max_attempts"] = human_attempts
    return {
        "id": "daily-report-return",
        "version": "t1",
        "policy_family": "workflow-demo",
        "entry": "M01",
        "terminal": ["M03"],
        "nodes": {
            "M01": {"kind": "agent", "executor": "agent-executor",
                    "max_attempts": 3,
                    "output": {"object": "intake",
                               "validation": {"shape": INTAKE_SHAPE,
                                              "validator": "intake",
                                              "validator_version": "1"}},
                    "checks": [{"id": "M01-1", "method": "PROGRAM",
                                "criterion": "Every record names its source.",
                                "criterion_version": "1",
                                "validator": "intake",
                                "validator_version": "1"}]},
            "M02": human,
            "M03": {"kind": "agent", "executor": "agent-executor",
                    "max_attempts": 2,
                    "inputs": [{"object": "acceptance"}],
                    "output": {"object": "analysis",
                               "validation": {"shape": ANALYSIS_SHAPE,
                                              "validator": "analysis",
                                              "validator_version": "1"}},
                    "checks": [{"id": "M03-1", "method": "PROGRAM",
                                "criterion": "Every finding cites a clause.",
                                "criterion_version": "1",
                                "validator": "analysis",
                                "validator_version": "1"}]},
        },
        "edges": [{"from": "M01", "to": "M02"}, {"from": "M02", "to": "M03"}],
    }


class DailyReportTestCase(unittest.TestCase):
    """The fixture: an agent, a human that may send the candidate back."""

    human_attempts = None

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-reject-return-")
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.counter = 0
        self.runtime, self.engine = self.build()
        self.template = daily_template(self.human_attempts)
        self.instantiate()

    # -- helpers ---------------------------------------------------------

    def build(self):
        runtime = Runtime(self.path, WorkflowDemoPolicy(), workflow_demo_grants())
        engine = WorkflowEngine(runtime, workflow_demo_validators())
        return runtime, engine

    def next_id(self, label):
        self.counter += 1
        return label + "-" + str(self.counter)

    def instantiate(self):
        published = self.engine.publish_template("coordinator", self.template)
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
                             {"steps": ["M01", "M02", "M03"],
                              "open_requirements": [], "replan_when": []},
                             version_of(self.runtime, WORK_ID))
        receipt = self.engine.command("coordinator", self.next_id("bind"), WORK_ID,
                                      "bind_workflow",
                                      {"template_id": self.template["id"],
                                       "template_version": self.template["version"],
                                       "parameters": {"subject": "east parapet"}},
                                      version_of(self.runtime, WORK_ID))
        self.assertEqual(receipt["decision"], "accepted", receipt)

    def node(self, node_id):
        for entry in self.engine.instance(WORK_ID)["nodes"]:
            if entry["node"] == node_id:
                return entry
        return {}

    def attempts(self, node_id):
        """Every attempt of a node, as the read model records them."""
        return self.engine.attempts(WORK_ID, node_id)

    def work(self):
        return self.runtime.get_work(WORK_ID)

    def candidate_reference(self):
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT revision,digest FROM workflow_objects "
                             "WHERE work_id=? AND name='intake' "
                             "ORDER BY revision DESC LIMIT 1", (WORK_ID,)).fetchone()
        finally:
            db.close()
        return {"revision": row[0], "digest": row[1]}

    def events(self):
        db = sqlite3.connect(self.path)
        try:
            rows = db.execute("SELECT type,body FROM events WHERE work_id=? "
                              "ORDER BY seq", (WORK_ID,)).fetchall()
        finally:
            db.close()
        return [(row[0], json.loads(row[1])) for row in rows]

    def event_types(self):
        return [row[0] for row in self.events()]

    def decide(self, decision, attempt, reference=None, result=None,
               actor=REVIEWER, source=REVIEWER):
        """A human decision, bound to one attempt and one candidate."""
        reference = reference or self.candidate_reference()
        verdict = {"approved": "passed", "rejected": "failed"}[decision]
        item = {"check": "M02-1", "verdict": verdict,
                "reason": "the candidate was judged against the criterion"}
        if decision == "approved":
            # A passed criterion names the material it was made against.
            item["evidence"] = ["intake#revision-" + str(reference["revision"])]
        payload = {"node": "M02", "attempt": attempt, "decision": decision,
                   "digest": reference["digest"], "revision": reference["revision"],
                   "actor": actor, "items": [item]}
        if result is not None:
            payload["result"] = result
        receipt = self.engine.command(
            source, self.next_id("decision"), WORK_ID, "record_decision",
            payload, version_of(self.runtime, WORK_ID))
        if receipt.get("decision") == "accepted":
            self.runtime.verify_pending(WORK_ID)
            self.engine.advance(WORK_ID, 1000)
        return receipt

    def record(self, record_id="ACC-1"):
        return {"recordId": record_id, "kind": EVIDENCE_KIND,
                "actor": REVIEWER, "items": ["M-1"]}

    def drive_to_human(self):
        """The first candidate is written; the human node waits."""
        self.engine.advance(WORK_ID, 1000)
        submitted = submit_valid(self.engine, self.runtime, WORK_ID, "M01", "intake")
        self.assertEqual(submitted["decision"], "accepted", submitted)
        self.engine.advance(WORK_ID, 1000)
        self.assertEqual(self.node("M02")["state"], "running")
        # The candidate the first attempt was judged on.
        self.first_reference = self.candidate_reference()

    def rework(self):
        """The human rejects; the agent writes a second candidate.

        A command settles the workflow itself, so the routing that follows
        the reworked candidate has already happened when this returns.
        """
        self.drive_to_human()
        rejected = self.decide("rejected", 1)
        self.assertEqual(rejected["decision"], "accepted", rejected)
        self.assertEqual(self.node("M02")["outcome"], "rejected")
        # The declared branch is taken: the agent runs again.
        self.assertEqual(self.node("M01")["attempt"], 2)
        self.assertEqual(self.node("M01")["state"], "running")
        submitted = self.engine.command(
            "agent-executor", self.next_id("result"), WORK_ID,
            "submit_node_result",
            {"node": "M01", "attempt": 2, "object": "intake",
             "result": REWORKED,
             "input_digest": self.node("M01")["inputDigest"]},
            version_of(self.runtime, WORK_ID))
        self.assertEqual(submitted["decision"], "accepted", submitted)


class ExhaustedAllowanceTestCase(DailyReportTestCase):
    """The human node declares one attempt: the allowance is spent.

    This is the shape ``oa-4`` published. The work cannot ask the human
    again, and it must say so **once**: the escalation is stable, the
    cursor names the node the work is really on, and the rejection that
    sent the work back is never routed from a second time.
    """

    human_attempts = 1

    def test_the_reworked_candidate_is_kept(self):
        """The work that was done is not lost when the routing stops."""
        self.rework()
        self.engine.advance(WORK_ID, 2000)
        node = self.node("M01")
        self.assertEqual(node["attempt"], 2)
        self.assertEqual(node["state"], "completed")
        self.assertEqual(node["outcome"], "completed")
        # The candidate the agent reworked is the node's output.
        self.assertEqual(len(node["outputs"]), 1)
        self.assertEqual(self.candidate_reference()["revision"], 2)

    def test_the_limit_is_reached_and_recorded_once(self):
        """The escalation says which node could not be opened."""
        self.rework()
        limits = [body for name, body in self.events()
                  if name == "WorkflowReworkLimitExceeded"]
        self.assertEqual(len(limits), 1)
        self.assertEqual(limits[0]["node"], "M02")
        self.assertEqual(self.work()["workflow_status"], "needs_attention")

    def test_the_cursor_does_not_point_at_a_node_that_was_not_opened(self):
        """The cursor names the node the work is really working on."""
        self.rework()
        # The human node could not be opened: the cursor does not name it.
        self.assertEqual(self.work()["workflow_current"], "M01")
        # No attempt of the human node was opened beyond the one that
        # was decided.
        self.assertEqual(self.node("M02")["attempt"], 1)
        self.assertEqual(len(self.attempts("M02")), 1)

    def test_the_old_rejection_is_not_consumed_again(self):
        """A decision is one decision: it routes the work exactly once."""
        self.rework()
        # The agent is not asked a third time: the rejection did not
        # reach the routing twice.
        self.assertEqual(self.node("M01")["attempt"], 2)
        self.assertEqual(len(self.attempts("M01")), 2)
        # And it is not routed from on the next pass either.
        self.engine.advance(WORK_ID, 2000)
        self.assertEqual(self.node("M01")["attempt"], 2)
        self.assertEqual(len(self.attempts("M01")), 2)
        self.assertEqual(self.work()["workflow_current"], "M01")

    def test_the_escalation_is_stable_under_a_repeated_pump(self):
        """A pass that changes nothing writes nothing."""
        self.rework()
        version = version_of(self.runtime, WORK_ID)
        events = len(self.events())
        for _ in range(3):
            self.engine.advance(WORK_ID, 2000)
        self.assertEqual(version_of(self.runtime, WORK_ID), version)
        self.assertEqual(len(self.events()), events)
        self.assertEqual(self.work()["workflow_status"], "needs_attention")
        self.assertEqual(self.node("M01")["attempt"], 2)

    def test_the_escalation_is_stable_after_a_reopen_of_the_store(self):
        """The state is the store's, not the process's."""
        self.rework()
        version = version_of(self.runtime, WORK_ID)
        runtime, engine = self.build()
        nodes = {entry["node"]: entry for entry in engine.instance(WORK_ID)["nodes"]}
        self.assertEqual(nodes["M01"]["attempt"], 2)
        self.assertEqual(nodes["M02"]["attempt"], 1)
        engine.advance(WORK_ID, 3000)
        self.assertEqual(version_of(runtime, WORK_ID), version)
        self.assertEqual(runtime.get_work(WORK_ID)["workflow_status"],
                         "needs_attention")
        self.assertEqual(runtime.get_work(WORK_ID)["workflow_current"], "M01")
        nodes = {entry["node"]: entry for entry in engine.instance(WORK_ID)["nodes"]}
        self.assertEqual(nodes["M01"]["attempt"], 2)


class ReturnedDecisionTestCase(DailyReportTestCase):
    """The human node declares two attempts: the work can come back."""

    human_attempts = 2

    def test_the_candidate_is_offered_to_the_human_again(self):
        """After the rework the human is asked again, on a new attempt."""
        self.rework()
        node = self.node("M02")
        self.assertEqual(node["attempt"], 2)
        self.assertEqual(node["state"], "running")
        self.assertIsNone(node["outcome"])
        # The new attempt judges the new candidate.
        self.assertEqual(node["subject"]["revision"],
                         self.candidate_reference()["revision"])
        # Not the candidate the first attempt was judged on.
        self.assertNotEqual(node["subject"]["digest"],
                            self.first_reference["digest"])
        self.assertEqual(self.first_reference["revision"], 1)

    def test_the_old_decision_does_not_answer_the_new_attempt(self):
        """The old proof says nothing about the attempt it was not made for."""
        self.rework()
        stale = self.decide("approved", 1, result=self.record())
        self.assertEqual(stale["decision"], "rejected", stale)
        self.assertEqual(stale["code"], "WORKFLOW_ATTEMPT_STALE")
        self.assertEqual(self.node("M02")["state"], "running")
        self.assertIsNone(self.node("M02")["outcome"])

    def test_the_new_decision_binds_the_new_attempt_and_the_new_candidate(self):
        """The new attempt waits for a new decision about the new candidate."""
        self.rework()
        reference = self.candidate_reference()
        self.assertEqual(reference["revision"], 2)
        approved = self.decide("approved", 2, reference=reference,
                               result=self.record())
        self.assertEqual(approved["decision"], "accepted", approved)
        self.assertEqual(self.node("M02")["state"], "completed")
        self.assertEqual(self.node("M02")["outcome"], "approved")
        self.assertEqual(self.node("M02")["actor"], REVIEWER)

    def test_the_old_attempt_keeps_its_history(self):
        """The rejection stays on the record; it is never rewritten."""
        self.rework()
        reference = self.candidate_reference()
        approved = self.decide("approved", 2, reference=reference,
                               result=self.record())
        self.assertEqual(approved["decision"], "accepted", approved)
        old = [entry for entry in self.attempts("M02")
               if entry.get("attempt") == 1]
        self.assertTrue(old)
        self.assertEqual(old[0].get("outcome"), "rejected")
        self.assertEqual(old[0].get("actor"), REVIEWER)

    def test_a_new_approval_advances_the_work_downstream(self):
        """The return is not a dead end: the work advances on the approval."""
        self.rework()
        reference = self.candidate_reference()
        approved = self.decide("approved", 2, reference=reference,
                               result=self.record())
        self.assertEqual(approved["decision"], "accepted", approved)
        # The downstream node runs on the acceptance record.
        self.assertEqual(self.node("M03")["state"], "running")
        submitted = submit_valid(self.engine, self.runtime, WORK_ID, "M03",
                                 "analysis")
        self.assertEqual(submitted["decision"], "accepted", submitted)
        self.engine.advance(WORK_ID, 1000)
        self.assertEqual(self.node("M03")["state"], "completed")
        self.assertEqual(self.work()["workflow_status"], "finished")

    def test_the_return_is_idempotent_under_a_repeated_pump(self):
        """A pass that changes nothing writes nothing."""
        self.rework()
        version = version_of(self.runtime, WORK_ID)
        events = len(self.events())
        for _ in range(3):
            self.engine.advance(WORK_ID, 2000)
        self.assertEqual(version_of(self.runtime, WORK_ID), version)
        self.assertEqual(len(self.events()), events)
        self.assertEqual(self.node("M02")["attempt"], 2)
        self.assertEqual(self.node("M02")["state"], "running")


if __name__ == "__main__":  # pragma: no cover - manual run
    unittest.main()
