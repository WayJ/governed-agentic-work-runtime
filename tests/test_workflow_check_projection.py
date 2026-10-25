"""The read model shows the judgment that is in force, per criterion.

A node's `checkResults` used to be the **oldest** sixteen entries of the
report history the attempt produced. The OA node ``M02`` carries 326
identical ``human-check`` reports, so a reader saw sixteen copies of a
stale judgement and never the judgement that is in force — and a reader
that folds the copies by hand has to guess which one is current.

The engine now records the judgment it applied to an attempt, and the
read model projects the current position out of it: one entry per declared
criterion, in the declaration order, from the judgment that covered it
last. It is never guessed from a timestamp, it never mixes criteria,
attempts or material, and it carries at most one entry per criterion — so
a reader never has to pick a winner.

The history itself is untouched: every report the attempt produced stays in
the store, every event stays, and nothing is cleaned.
"""

import json
import os
import sqlite3
import tempfile
import time
import unittest

from work_runtime.policy import canonical
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
OTHER_REASON = "the material was judged again, on a second look"
STALE = 20


class OpenPolicy(WorkflowDemoPolicy):
    """The demonstration family with its obligation already satisfied."""

    def evaluate(self, work, evidence):
        return [{"id": "R01:" + work["document"]["id"], "rule_id": "R01",
                 "subject": work["document"]["id"], "applicability": "applicable",
                 "fulfillment": "satisfied",
                 "explanation": "The obligation is satisfied in this fixture"}]


def projection_template(template_id="check-projection", version="t1"):
    """One agent node and one human node with two declared criteria.

    Two criteria, so the projection has to be readable **per criterion**:
    one entry each, never one criterion's verdict under another's name.
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
                                    "validator_version": "1"},
                                   {"id": "N02-2", "method": "HUMAN",
                                    "criterion": "The doubt is written down.",
                                    "criterion_version": "1",
                                    "validator": "safety-review",
                                    "validator_version": "1"}]}},
            "edges": [{"from": "n01", "to": "n02"}]}


class CheckProjectionTestCase(unittest.TestCase):
    """The fixture: one agent node, one human node, two criteria."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-projection-")
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.counter = 0
        self.runtime, self.engine = self.build()
        self.template = projection_template()
        published = self.engine.publish_template("coordinator", self.template)
        self.assertEqual(published["decision"], "accepted", published)

    # -- helpers ---------------------------------------------------------

    def build(self):
        grants = workflow_demo_grants()
        grants[RUNNER] = {"workflow.finalize"}
        runtime = Runtime(self.path, OpenPolicy(), grants)
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

    def decide(self, decision="rejected", reason=REASON, attempt=1,
               actor="reviewer-a", source="reviewer-a"):
        reference = self.subject_reference()
        verdict = {"approved": "passed", "rejected": "failed"}[decision]
        items = []
        for criterion in ("N02-1", "N02-2"):
            item = {"check": criterion, "verdict": verdict, "reason": reason}
            if verdict == "passed":
                item["evidence"] = ["intake#revision-" + str(reference["revision"])]
            items.append(item)
        payload = {"node": "n02", "attempt": attempt, "decision": decision,
                   "digest": reference["digest"], "revision": reference["revision"],
                   "actor": actor, "items": items}
        receipt = self.engine.command(
            source, self.next_id("decision"), WORK_ID, "record_decision",
            payload, version_of(self.runtime, WORK_ID))
        if receipt.get("decision") == "accepted":
            self.runtime.verify_pending(WORK_ID)
        return receipt

    def node(self, node="n02"):
        for entry in self.engine.instance(WORK_ID)["nodes"]:
            if entry["node"] == node:
                return entry
        return {}

    def attempts(self, node="n02"):
        return self.engine.attempts(WORK_ID, node)

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

    def seed_stale_reports(self, count, entry, attempt=1):
        """The shape the old runtime left behind: one report, many times.

        The fix stops the growth; it does not rewrite the history that is
        already on the record. This fixture reproduces that history in an
        isolated store, so the projection can be read against it.
        """
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT body FROM workflow_nodes WHERE work_id=? AND "
                             "node=? AND attempt=?",
                             (WORK_ID, "n02", attempt)).fetchone()
            body = json.loads(row[0])
            body["check_results"] = [dict(entry) for _ in range(count)]
            db.execute("UPDATE workflow_nodes SET body=? WHERE work_id=? AND "
                       "node=? AND attempt=?",
                       (canonical(body), WORK_ID, "n02", attempt))
            db.commit()
        finally:
            db.close()


class CurrentProjectionTests(CheckProjectionTestCase):
    """More than sixteen stale reports must not hide the current judgment."""

    def setUp(self):
        super().setUp()
        self.drive_to_human()
        self.decide("rejected")
        # The shape the old runtime left behind on this node.
        stale = self.stored_node()["check_results"][0]
        self.seed_stale_reports(STALE, stale)

    def test_the_current_judgment_is_visible_after_many_stale_reports(self):
        """A new judgment is what the reader sees."""
        self.decide("approved", reason=OTHER_REASON)
        reports = self.node()["checkResults"]
        self.assertTrue(reports)
        self.assertEqual({report["reason"] for report in reports},
                         {OTHER_REASON})

    def test_the_attempts_projection_shows_the_current_judgment(self):
        self.decide("approved", reason=OTHER_REASON)
        history = self.attempts()
        self.assertEqual(len(history), 1)
        reports = history[0]["checkResults"]
        self.assertTrue(reports)
        self.assertEqual({report["reason"] for report in reports},
                         {OTHER_REASON})

    def test_the_projection_carries_at_most_one_entry_per_criterion(self):
        """A reader never has to pick a winner: the criterion names the entry."""
        self.decide("approved", reason=OTHER_REASON)
        for reports in (self.node()["checkResults"],
                        self.attempts()[0]["checkResults"]):
            identifiers = [report["checkId"] for report in reports]
            self.assertEqual(len(identifiers), len(set(identifiers)))
            self.assertEqual(sorted(identifiers), ["N02-1", "N02-2"])

    def test_every_criterion_is_readable(self):
        self.decide("approved", reason=OTHER_REASON)
        reports = self.node()["checkResults"]
        self.assertEqual(len(reports), 2)
        for report in reports:
            self.assertEqual(report["verdict"], "passed")
            self.assertEqual(report["reason"], OTHER_REASON)
            self.assertEqual(report["method"], "HUMAN")
            self.assertEqual(report["decidedBy"], "reviewer-a")

    def test_the_history_is_kept_in_the_store(self):
        """The projection hides nothing: the history is still on the record."""
        self.decide("approved", reason=OTHER_REASON)
        stored = self.stored_node()
        self.assertGreaterEqual(len(stored.get("check_results") or []), STALE)
        events = [event["type"] for event in self.runtime.events(WORK_ID)]
        self.assertIn("WorkflowOutputMissing", events)

    def test_the_projection_is_not_guessed_from_a_timestamp(self):
        """A newer entry that is not the judgment does not become current."""
        foreign = dict(self.stored_node()["check_results"][0],
                       at=int(time.time()) + 3600,
                       reason="a stale foreign report")
        self.seed_stale_reports(1, foreign)
        reports = self.node()["checkResults"]
        self.assertTrue(reports)
        self.assertNotIn("a stale foreign report",
                         [report["reason"] for report in reports])


class AttemptSeparationTests(CheckProjectionTestCase):
    """The projection never mixes attempts."""

    def test_each_attempt_carries_its_own_judgment(self):
        self.drive_to_human()
        self.decide("rejected", reason=REASON)
        # New material supersedes the attempt: the node runs again.
        receipt = self.runtime.command(
            "coordinator", self.next_id("revise"), WORK_ID, "revise_object",
            {"name": "intake",
             "object": {"records": [{"id": "R-2", "source": "site-log"}],
                        "standard": "STD-2"}},
            version_of(self.runtime, WORK_ID))
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.engine.advance(WORK_ID, 2000)
        self.assertEqual(self.node()["attempt"], 2)
        self.decide("rejected", reason=OTHER_REASON, attempt=2)
        history = self.attempts()
        self.assertEqual(len(history), 2)
        first = [entry for entry in history if entry["attempt"] == 1][0]
        second = [entry for entry in history if entry["attempt"] == 2][0]
        # Each attempt shows its own judgment: nothing is mixed.
        self.assertEqual({report["reason"] for report in first["checkResults"]},
                         {REASON})
        self.assertEqual({report["reason"] for report in second["checkResults"]},
                         {OTHER_REASON})
        # And the two attempts judged different material: the report names
        # the subject it was made against.
        self.assertNotEqual(first["checkResults"][0]["reviewedOutputDigest"],
                            second["checkResults"][0]["reviewedOutputDigest"])


if __name__ == "__main__":
    unittest.main()
