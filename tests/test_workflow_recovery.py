"""Restart recovery for the mixed-node workflow engine.

Every test restarts against the same store and counts the external effects
from the adapter's own store, never from a counter in the process that
performed them.
"""

import json
import os
import sqlite3
import tempfile
import unittest

try:
    from workflow_support import (RecordingAdapter, build, decide, instantiate,
                                  scenario_template, send, submit, submit_valid,
                                  version_of)
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import (RecordingAdapter, build, decide, instantiate,
                                        scenario_template, send, submit, submit_valid,
                                        version_of)


class RecoveryTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-workflow-recovery-")
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.adapter_path = os.path.join(self.folder, "effects.sqlite")
        self.adapter = RecordingAdapter(self.adapter_path)
        self.runtime, self.engine = build(self.path)
        self.work_id = "W-1"
        self.engine.publish_template("coordinator", scenario_template())

    def restart(self):
        """A fresh process over the same store."""
        runtime, engine = build(self.path)
        return runtime, engine

    def drive_to_dispatch(self):
        instantiate(self.runtime, self.engine, self.work_id)
        for node, name in (("n01", "intake"), ("n02", "analysis"), ("n03", "proposal")):
            submit_valid(self.engine, self.runtime, self.work_id, node, name)
        proposal = self.object_reference("proposal")
        for kind, source in (("safety_review", "reviewer-a"),
                             ("project_approval", "reviewer-b")):
            decide(self.runtime, self.engine, self.work_id, kind, source, "approved",
                   proposal["digest"], proposal["revision"])

    def object_reference(self, name):
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT name,revision,digest FROM workflow_objects "
                             "WHERE work_id=? AND name=? ORDER BY revision DESC LIMIT 1",
                             (self.work_id, name)).fetchone()
        finally:
            db.close()
        return {"name": row[0], "revision": row[1], "digest": row[2]}

    def operations(self, runtime=None):
        runtime = runtime or self.runtime
        db = sqlite3.connect(self.path)
        try:
            return [json.loads(row[0]) for row in
                    db.execute("SELECT body FROM operations WHERE work_id=?",
                               (self.work_id,))]
        finally:
            db.close()


class RestartTests(RecoveryTestCase):
    def test_a_prepared_action_is_dispatched_once_after_a_restart(self):
        self.drive_to_dispatch()
        operations = self.operations()
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0]["status"], "prepared")
        self.assertEqual(self.adapter.effect_count(), 0)
        runtime, engine = self.restart()
        engine.recover(self.adapter, 1000)
        self.assertEqual(self.adapter.effect_count(), 1)
        engine.recover(self.adapter, 1000)
        self.assertEqual(self.adapter.effect_count(), 1)
        stored = runtime.get_operation(operations[0]["id"])
        self.assertEqual(stored["status"], "confirmed_succeeded")

    def test_an_effect_committed_before_a_crash_is_looked_up_not_repeated(self):
        self.drive_to_dispatch()
        operation = self.operations()[0]
        def crash():
            raise RuntimeError("the process died after the effect")
        with self.assertRaises(RuntimeError):
            self.runtime.dispatch(operation["id"], self.adapter, fault=crash)
        self.assertEqual(self.adapter.effect_count(), 1)
        self.assertEqual(self.runtime.get_operation(operation["id"])["status"],
                         "dispatched")
        runtime, engine = self.restart()
        engine.recover(self.adapter, 1000)
        self.assertEqual(self.adapter.effect_count(), 1)
        self.assertEqual(runtime.get_operation(operation["id"])["status"],
                         "confirmed_succeeded")

    def test_a_restart_resumes_the_workflow_without_re_running_a_node(self):
        self.drive_to_dispatch()
        runtime, engine = self.restart()
        engine.recover(self.adapter, 1000)
        view = engine.instance(self.work_id)
        n06 = [entry for entry in view["nodes"] if entry["node"] == "n06"][0]
        self.assertEqual(n06["state"], "completed")
        n07 = [entry for entry in view["nodes"] if entry["node"] == "n07"][0]
        self.assertEqual(n07["state"], "running")
        # The agents are not asked to work again.
        for node in ("n01", "n02", "n03"):
            entry = [item for item in view["nodes"] if item["node"] == node][0]
            self.assertEqual(entry["attempt"], 1)
            self.assertEqual(entry["state"], "completed")
        # And every object was written exactly once: the intake, the
        # analysis, the proposal, the order the dispatch receipt produced and
        # the receipt the bound wait recorded.
        db = sqlite3.connect(self.path)
        try:
            rows = db.execute("SELECT name,COUNT(*) FROM workflow_objects "
                              "WHERE work_id=? GROUP BY name",
                              (self.work_id,)).fetchall()
        finally:
            db.close()
        self.assertEqual(sorted(rows),
                         [("analysis", 1), ("dispatch_receipt", 1), ("intake", 1),
                          ("order", 1), ("proposal", 1)])

    def test_a_pending_human_task_survives_a_restart(self):
        instantiate(self.runtime, self.engine, self.work_id)
        submit_valid(self.engine, self.runtime, self.work_id, "n01", "intake")
        submit_valid(self.engine, self.runtime, self.work_id, "n02", "analysis")
        submit_valid(self.engine, self.runtime, self.work_id, "n03", "proposal")
        runtime, engine = self.restart()
        engine.recover(self.adapter, 1000)
        intents = engine.intents(kind="human_task", status=None)
        self.assertEqual([entry["node"] for entry in intents], ["n04"])
        proposal = self.object_reference("proposal")
        decide(runtime, engine, self.work_id, "safety_review", "reviewer-a",
               "approved", proposal["digest"], proposal["revision"])
        view = engine.instance(self.work_id)
        n05 = [entry for entry in view["nodes"] if entry["node"] == "n05"][0]
        self.assertEqual(n05["state"], "running")


class CancellationTests(RecoveryTestCase):
    def test_cancelling_with_an_in_flight_effect_keeps_the_truth(self):
        self.drive_to_dispatch()
        operation = self.operations()[0]
        def crash():
            raise RuntimeError("the process died after the effect")
        with self.assertRaises(RuntimeError):
            self.runtime.dispatch(operation["id"], self.adapter, fault=crash)
        receipt = send(self.runtime, "coordinator", self.work_id, "request_cancel",
                       {"reason": "the engagement was withdrawn"})
        self.assertEqual(receipt["decision"], "accepted")
        work = self.runtime.get_work(self.work_id)
        # The work is not closed and claims no outcome: the cancellation is
        # recorded and the unresolved effect is still to be reconciled.
        self.assertNotEqual(work["status"], "closed")
        self.assertIsNone(work.get("outcome"))
        self.assertIsNotNone(work.get("cancellation"))
        self.assertEqual(work["workflow_status"], "needs_attention")
        # The unresolved effect blocks the closure: it is not declared failed.
        refused = send(self.runtime, "coordinator", self.work_id, "finalize_cancel",
                       {"acknowledged_operations": []})
        self.assertEqual(refused["decision"], "rejected")
        self.assertEqual(refused["code"], "OUTCOME_UNRESOLVED")
        # After a restart the effect is looked up and the truth is settled.
        runtime, engine = self.restart()
        engine.recover(self.adapter, 1000)
        self.assertEqual(self.adapter.effect_count(), 1)
        self.assertEqual(runtime.get_operation(operation["id"])["status"],
                         "confirmed_succeeded")

    def test_a_late_callback_cannot_revive_a_cancelled_instance(self):
        self.drive_to_dispatch()
        send(self.runtime, "coordinator", self.work_id, "request_cancel",
             {"reason": "the engagement was withdrawn"})
        receipt = submit(self.engine, self.runtime, self.work_id, "n01", 1, "intake",
                         {"records": [{"id": "R-9", "source": "s"}], "standard": "STD"})
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "WORKFLOW_ATTEMPT_STALE")
        work = self.runtime.get_work(self.work_id)
        self.assertIsNotNone(work.get("cancellation"))

    def test_a_cancelled_work_dispatches_nothing_further(self):
        self.drive_to_dispatch()
        send(self.runtime, "coordinator", self.work_id, "request_cancel",
             {"reason": "the engagement was withdrawn"})
        self.engine.pump(self.adapter, 1000)
        self.assertEqual(self.adapter.effect_count(), 0)
        self.engine.pump(self.adapter, 1000)
        self.assertEqual(self.adapter.effect_count(), 0)


if __name__ == "__main__":
    unittest.main()
