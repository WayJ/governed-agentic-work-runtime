"""Manager-requested material waiting on the current agent node.

Business material is not candidate quality: a wait parks the node's current
attempt without opening a rework attempt, withdraws the agent's durable
intent, refuses result acceptance and persists across a restart until the
manager adopts the supplemented material and resumes. The tests run on a
real store and assert stored truth (rows, intents, events), never a receipt
alone.
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
import uuid

from work_runtime.workflow import WorkflowError

try:
    from workflow_support import (current_attempt, input_digest_of, instance_of,
                                  instantiate, scenario_template, send, submit,
                                  submit_valid, version_of, build)
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import (current_attempt, input_digest_of,
                                        instance_of, instantiate,
                                        scenario_template, send, submit,
                                        submit_valid, version_of, build)

OWNER = "coordinator"
EXECUTOR = "agent-executor"
WORK_ID = "W-1"
VALID_ANALYSIS = {"findings": [{"issueId": "H-001", "clause": "C-1",
                                "finding": "gap"}]}


class MaterialWaitTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-material-wait-")
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.runtime, self.engine = build(self.path)
        self.work = WORK_ID
        published = self.engine.publish_template(OWNER, scenario_template())
        self.assertEqual("accepted", published["decision"], published)
        instantiate(self.runtime, self.engine, self.work)
        # n01 completes with a valid intake, so n02 opens running with the
        # intake pinned: the node every wait test parks.
        submit_valid(self.engine, self.runtime, self.work, "n01", "intake")
        self.attempt = current_attempt(self.engine, self.runtime, self.work, "n02")
        self.assertEqual(1, self.attempt)

    # -- helpers ---------------------------------------------------------

    def stored(self):
        """The whole stored truth of the work, rows and version together."""
        db = sqlite3.connect(self.path)
        try:
            return {
                "nodes": db.execute(
                    "SELECT node,attempt,state,body FROM workflow_nodes "
                    "WHERE work_id=? ORDER BY node,attempt",
                    (self.work,)).fetchall(),
                "intents": db.execute(
                    "SELECT id,status,body FROM workflow_intents "
                    "WHERE work_id=? ORDER BY id", (self.work,)).fetchall(),
                "objects": db.execute(
                    "SELECT name,revision,digest,body FROM workflow_objects "
                    "WHERE work_id=? ORDER BY name,revision",
                    (self.work,)).fetchall(),
                "events": db.execute(
                    "SELECT version,type,body FROM events WHERE work_id=? "
                    "ORDER BY version", (self.work,)).fetchall(),
                "version": version_of(self.runtime, self.work),
            }
        finally:
            db.close()

    def intent_status(self, node, attempt, kind="agent_task"):
        intent_id = "wf:%s:%s:%d:%s" % (self.work, node, attempt, kind)
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT status FROM workflow_intents WHERE id=?",
                             (intent_id,)).fetchone()
            return row[0] if row else None
        finally:
            db.close()

    def wait(self, *, node="n02", attempt=None, input_digest=None,
             reason="the referenced record is missing a page", actor=OWNER,
             request_version=1, expected_version=None):
        if input_digest is None:
            input_digest = input_digest_of(self.engine, self.work, node)
            if not input_digest:
                # A node that is not open has no pinned digest; the request
                # is still well formed, and the engine refuses it for the
                # node, not for the digest.
                input_digest = "unpinned"
        payload = {"node": node, "attempt": self.attempt if attempt is None
                   else attempt, "input_digest": input_digest, "reason": reason,
                   "request_version": request_version}
        return self.engine.command(actor, uuid.uuid4().hex, self.work,
                                   "request_material_wait", payload,
                                   expected_version
                                   or version_of(self.runtime, self.work))

    # -- the lifecycle ---------------------------------------------------

    def test_the_manager_parks_the_current_agent_node(self):
        pinned = input_digest_of(self.engine, self.work, "n02")
        receipt = self.wait()
        self.assertEqual("accepted", receipt["decision"], receipt)
        wait = receipt["wait"]
        self.assertEqual("waiting", wait["state"])
        self.assertEqual(1, wait["request_version"])
        self.assertEqual(OWNER, wait["requested_by"])
        self.assertEqual("the referenced record is missing a page",
                         wait["reason"])
        self.assertEqual(pinned, wait["input_digest"])
        self.assertEqual([], wait["adoptions"])
        self.assertIsNone(wait["resumed"])
        self.assertEqual(1, len(wait["dependencies"]))
        self.assertEqual("intake", wait["dependencies"][0]["name"])
        self.assertEqual(1, wait["dependencies"][0]["revision"])
        # the node itself is parked on its own attempt, not failed and not
        # superseded
        entry = instance_of(self.engine, self.runtime, self.work, "n02")
        self.assertEqual("waiting", entry["state"])
        self.assertEqual(1, entry["attempt"])
        # the work says it is waiting for material, not needs-attention
        work = self.runtime.get_work(self.work)
        self.assertEqual("waiting", work["workflow_status"])
        self.assertEqual("waiting", work["status"])
        # the agent's durable intent is withdrawn: nothing asks the executor
        # to keep working while the material is missing
        self.assertEqual("cancelled",
                         self.intent_status("n02", 1))
        self.assertEqual("done", self.intent_status("n01", 1))
        # the request itself is on the event record
        kinds = [event["type"] for event in self.runtime.events(self.work)]
        self.assertIn("WorkflowMaterialWaitRequested", kinds)

    def test_the_wait_persists_across_a_restart_and_a_routing_pass(self):
        self.wait()
        before = self.stored()
        _, engine2 = build(self.path)
        engine2.advance(self.work, 2_000_000)
        self.assertEqual(before, self.stored())
        entry = instance_of(engine2, self.runtime, self.work, "n02")
        self.assertEqual("waiting", entry["state"])
        self.assertEqual("cancelled", self.intent_status("n02", 1))

    def test_a_result_submitted_while_waiting_is_refused_and_stores_nothing(self):
        self.wait()
        before = self.stored()
        receipt = submit(self.engine, self.runtime, self.work, "n02",
                         self.attempt, "analysis", VALID_ANALYSIS)
        self.assertEqual("rejected", receipt["decision"], receipt)
        self.assertEqual("WORKFLOW_NODE_WAITING", receipt["code"])
        self.assertEqual(before, self.stored())

    def test_the_wait_is_pinned_to_the_exact_node_attempt_and_input(self):
        self.assertEqual("WORKFLOW_NODE_UNKNOWN", self.wait(node="n99")["code"])
        self.assertEqual("WORKFLOW_NODE_NOT_CURRENT",
                         self.wait(node="n01", attempt=1)["code"])
        # a human node decides; its material path is the request_material
        # verdict, never a manager wait
        self.assertEqual("WORKFLOW_NODE_NOT_WAITABLE",
                         self.wait(node="n04")["code"])
        self.assertEqual("WORKFLOW_ATTEMPT_STALE",
                         self.wait(attempt=2)["code"])
        self.assertEqual("WORKFLOW_INPUT_STALE",
                         self.wait(input_digest="stale")["code"])

    def test_refused_wait_requests_mutate_nothing(self):
        before = self.stored()
        self.assertEqual("AUTHORITY_DENIED", self.wait(actor=EXECUTOR)["code"])
        self.assertEqual("WORKFLOW_NODE_UNKNOWN", self.wait(node="n99")["code"])
        self.assertEqual("WORKFLOW_NODE_NOT_CURRENT",
                         self.wait(node="n01", attempt=1)["code"])
        self.assertEqual("WORKFLOW_NODE_NOT_WAITABLE",
                         self.wait(node="n04")["code"])
        self.assertEqual("WORKFLOW_ATTEMPT_STALE",
                         self.wait(attempt=2)["code"])
        self.assertEqual("WORKFLOW_INPUT_STALE",
                         self.wait(input_digest="stale")["code"])
        self.assertEqual(before, self.stored())

    def test_a_second_wait_on_a_waiting_node_is_refused(self):
        self.wait()
        before = self.stored()
        receipt = self.wait()
        self.assertEqual("rejected", receipt["decision"], receipt)
        self.assertEqual("WORKFLOW_NODE_WAITING", receipt["code"])
        self.assertEqual(before, self.stored())

    def test_the_request_is_versioned(self):
        with self.assertRaises(WorkflowError):
            self.wait(request_version=2)
        with self.assertRaises(WorkflowError):
            self.wait(reason="")
        with self.assertRaises(WorkflowError):
            self.wait(reason="x" * 513)

    def test_a_cancelling_work_refuses_the_wait(self):
        send(self.runtime, OWNER, self.work, "request_cancel",
             {"reason": "duplicated request"})
        receipt = self.wait()
        self.assertEqual("rejected", receipt["decision"], receipt)
        self.assertEqual("CANCELLATION_ACTIVE", receipt["code"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
