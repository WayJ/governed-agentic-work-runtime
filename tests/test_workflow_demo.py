"""The mixed-node demonstration is part of the suite, not only a script.

The test drives the real demonstration (published template, trusted
principals, a real worker process that dies after the external effect, a
restart) and counts the external effects in the business system's own store.
"""

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from work_runtime.workflow_demo import (DemoBusinessSystem, build_demo_runtime,
                                         run_workflow_demo, workflow_demo_template)

try:
    from workflow_support import decide, send, submit_valid, version_of
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import decide, send, submit_valid, version_of


class WorkflowDemoTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-workflow-demo-test-")
        self.runtime_path = os.path.join(self.folder, "runtime.sqlite")
        self.system_path = os.path.join(self.folder, "business-system.sqlite")
        self.runtime, self.engine = build_demo_runtime(self.runtime_path)
        self.system = DemoBusinessSystem(self.system_path)

    def test_the_ten_node_scenario_runs_end_to_end(self):
        folder = run_workflow_demo(self.folder)
        runtime_path = str(Path(folder) / "runtime.sqlite")
        system_path = str(Path(folder) / "business-system.sqlite")
        runtime, engine = build_demo_runtime(runtime_path)
        system = DemoBusinessSystem(system_path)
        view = engine.instance("W-001")
        self.assertEqual(view["workflowStatus"], "finished")
        states = {entry["node"]: entry["state"] for entry in view["nodes"]}
        self.assertEqual(set(states.values()), {"completed"})
        # Two external effects: one dispatch, one delivery. Counted in the
        # business system's own store.
        self.assertEqual(system.effect_count(), 2)
        actions = sorted(effect["action"] for effect in system.effects())
        self.assertEqual(actions, ["work.deliver", "work.dispatch"])
        # The dispatch was performed once, by the operation that was recovered.
        db = sqlite3.connect(runtime_path)
        try:
            operations = [json.loads(row[0]) for row in
                          db.execute("SELECT body FROM operations")]
        finally:
            db.close()
        self.assertEqual(len(operations), 2)
        for operation in operations:
            self.assertEqual(operation["status"], "confirmed_succeeded")
            self.assertEqual(len(operation["attempts"]), 1)
        # Every human node carries the criterion report of its decision.
        for node in ("n04", "n05", "n07", "n08"):
            entry = [item for item in engine.instance("W-001")["nodes"]
                     if item["node"] == node][0]
            self.assertTrue(entry["checkResults"], node)
            for criterion in entry["checkResults"]:
                self.assertTrue(criterion["verdict"])
                self.assertTrue(criterion["reason"])
                if criterion["method"] == "HUMAN":
                    # The human's own verdict names the human who decided.
                    self.assertTrue(criterion["decidedBy"])
                else:
                    # A program verdict names the validator that judged it.
                    self.assertIsNone(criterion["decidedBy"])
                    self.assertTrue(criterion["validator"])
                    self.assertTrue(criterion["validatorVersion"])

    def test_a_human_decision_needs_the_current_version(self):
        self.engine.publish_template("coordinator", workflow_demo_template())
        self.runtime.command("coordinator", "create", "W-1", "create_work",
                             {"document": {"id": "H-001", "subject": "east parapet"}},
                             None)
        self.runtime.command("coordinator", "contract", "W-1", "bind_contract",
                             {"policy_id": "workflow-demo", "policy_version": "demo-1",
                              "goal": "workflow.completed"},
                             self.runtime.get_work("W-1")["state_version"])
        self.runtime.command("coordinator", "plan", "W-1", "revise_plan",
                             {"steps": ["n01"], "open_requirements": [],
                              "replan_when": []},
                             self.runtime.get_work("W-1")["state_version"])
        receipt = self.engine.command("coordinator", "bind", "W-1", "bind_workflow",
                                      {"template_id": "inspection-review-delivery",
                                       "template_version": "test-1",
                                       "parameters": {"subject": "east parapet"}},
                                      self.runtime.get_work("W-1")["state_version"])
        self.assertEqual(receipt["decision"], "accepted")
        self.engine.advance("W-1", 1000)
        for node, name in (("n01", "intake"), ("n02", "analysis"), ("n03", "proposal")):
            submitted = submit_valid(self.engine, self.runtime, "W-1", node, name)
            self.assertEqual(submitted["decision"], "accepted", submitted)
        db = sqlite3.connect(self.runtime_path)
        try:
            row = db.execute("SELECT revision,digest FROM workflow_objects "
                             "WHERE work_id='W-1' AND name='proposal'").fetchone()
        finally:
            db.close()
        # A decision that names another revision never advances the node.
        decide(self.runtime, self.engine, "W-1", "safety_review", "reviewer-a",
               "approved", row[1], row[0] + 5)
        node = [entry for entry in self.engine.instance("W-1")["nodes"]
                if entry["node"] == "n04"][0]
        self.assertNotEqual(node["state"], "completed")
        # The decision that covers the current version does.
        decide(self.runtime, self.engine, "W-1", "safety_review", "reviewer-a",
               "approved", row[1], row[0])
        node = [entry for entry in self.engine.instance("W-1")["nodes"]
                if entry["node"] == "n04"][0]
        self.assertEqual(node["state"], "completed")
        decided = [entry for entry in node["checkResults"]
                   if entry["checkId"] == "N04-2"][0]
        self.assertEqual(decided["decidedBy"], "reviewer-a")


if __name__ == "__main__":
    unittest.main()
