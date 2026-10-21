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
                                         run_workflow_demo,
                                         workflow_demo_template)


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
        attempt = engine_attempt(self.engine, "W-1", "n01")
        submitted = self.engine.command("agent-executor", "c1", "W-1",
                                        "submit_node_result",
                                        {"node": "n01", "attempt": attempt,
                                         "object": "intake",
                                         "result": {"records": [{"id": "REC-1",
                                                                 "source": "log"}],
                                                    "standard": "STD"}},
                                        self.runtime.get_work("W-1")["state_version"])
        self.assertEqual(submitted["decision"], "accepted")
        for node, name, result in (
                ("n02", "analysis", {"findings": [{"issueId": "H-001", "clause": "C-1",
                                                    "finding": "gap"}]}),
                ("n03", "proposal", {"measures": [{"issueId": "H-001", "measureId": "M-1",
                                                   "measure": "guard"}]})):
            attempt = engine_attempt(self.engine, "W-1", node)
            submitted = self.engine.command("agent-executor", "c-" + node, "W-1",
                                            "submit_node_result",
                                            {"node": node, "attempt": attempt,
                                             "object": name, "result": result},
                                            self.runtime.get_work("W-1")["state_version"])
            self.assertEqual(submitted["decision"] == "accepted", True, submitted)
        db = sqlite3.connect(self.runtime_path)
        try:
            row = db.execute("SELECT revision,digest FROM workflow_objects "
                             "WHERE work_id='W-1' AND name='proposal'").fetchone()
        finally:
            db.close()
        stale = self.runtime.command("reviewer-a", "d1", "W-1", "record_evidence",
                                     {"event_id": "d1", "kind": "safety_review",
                                      "data": {"decision": "approved",
                                               "digest": row[1], "revision": row[0] + 5}},
                                     None)
        self.assertEqual(stale["decision"], "accepted")
        self.runtime.verify_pending("W-1")
        self.engine.advance("W-1", 1000)
        node = [entry for entry in self.engine.instance("W-1")["nodes"]
                if entry["node"] == "n04"][0]
        self.assertNotEqual(node["state"], "completed")


def engine_attempt(engine, work_id, node):
    for entry in engine.instance(work_id)["nodes"]:
        if entry["node"] == node:
            return entry["attempt"]
    return 0


if __name__ == "__main__":
    unittest.main()
