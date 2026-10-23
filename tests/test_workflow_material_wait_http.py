"""The material wait lifecycle through the private workflow service.

The bridge owns no waiting engine of its own: it exposes the runtime's own
commands, so a platform parks a node, adopts the material and resumes it
exactly the way a trusted local caller would — same transaction, same
compare-and-swap, same command receipts, same replay rules. The tests run a
real service over a real SQLite store and assert stored truth (rows, events,
receipts), never a status code alone.
"""

import http.client
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from work_runtime.workflow_server import API_PREFIX, serve

try:
    from workflow_support import (FOCUSED_TEMPLATE, POLICY_GOAL, POLICY_ID,
                                  POLICY_VERSION, build, demo_grants, document,
                                  instantiate, scenario_template, send,
                                  submit_valid, version_of)
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import (FOCUSED_TEMPLATE, POLICY_GOAL, POLICY_ID,
                                        POLICY_VERSION, build, demo_grants,
                                        document, instantiate, scenario_template,
                                        send, submit_valid, version_of)

WORK_ID = "W-1"
OWNER = "coordinator"
SECOND_MANAGER = "ops-manager"
EXECUTOR = "agent-executor"
BASE = API_PREFIX + "/instances/" + WORK_ID
SUPPLEMENT = {"records": [{"id": "R-1", "source": "site-log"},
                          {"id": "R-2", "source": "site-log"}],
              "standard": "STD-1"}


class MaterialWaitHttpBase(unittest.TestCase):
    """A real service over a real store; the ticker only advances.

    The service, the store and the helpers are shared; each family below
    publishes its own definition and starts its own work.
    """

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-wait-http-")
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.path = os.path.join(self.folder, "runtime.sqlite")
        grants = demo_grants()
        grants[SECOND_MANAGER] = {"work.manage"}
        self.runtime, self.engine = build(self.path, grants=grants,
                                          runner="workflow-runner")
        self.server, self.ticker, self.lock = serve(
            self.runtime, self.engine, None, host="127.0.0.1", port=0,
            interval_s=0.05)
        self.host, self.port = (self.server.server_address[0],
                                self.server.server_address[1])
        self.counter = 0
        self.publish_and_start()

    def publish_and_start(self):
        """Publish the demonstration family and open its first agent node."""
        published = self.engine.publish_template(OWNER, scenario_template())
        self.assertEqual("accepted", published["decision"], published)
        instantiate(self.runtime, self.engine, WORK_ID)
        self.engine.advance(WORK_ID, 1000)
        submitted = submit_valid(self.engine, self.runtime, WORK_ID, "n01",
                                 "intake")
        self.assertEqual("accepted", submitted["decision"], submitted)
        self.version = version_of(self.runtime, WORK_ID)
        self.digest = self.node("n02")["inputDigest"]

    def tearDown(self):
        self.ticker.stop()
        self.server.shutdown()
        self.server.server_close()
        if self.lock is not None:
            self.lock.release()

    # -- helpers ---------------------------------------------------------

    def call(self, method, path, body=None):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=10)
        try:
            payload = json.dumps(body).encode("utf-8") if body is not None else None
            headers = {"Content-Type": "application/json"} if payload else {}
            connection.request(method, path, payload, headers)
            response = connection.getresponse()
            raw = response.read().decode("utf-8")
            return response.status, (json.loads(raw) if raw else {})
        finally:
            connection.close()

    def next_id(self, label="wait"):
        self.counter += 1
        return label + "-" + str(self.counter)

    def node(self, node_id="n02"):
        status, view = self.call("GET", BASE)
        self.assertEqual(200, status, view)
        for entry in view["nodes"]:
            if entry["node"] == node_id:
                return entry
        return None

    def wait_body(self, **extra):
        body = {"actor": OWNER, "commandId": self.next_id(),
                "expectedVersion": version_of(self.runtime, WORK_ID),
                "requestVersion": 1, "node": "n02", "attempt": 1,
                "inputDigest": self.digest,
                "reason": "the referenced record is missing a page"}
        body.update(extra)
        return body

    def adopt_body(self, **extra):
        body = {"actor": OWNER, "commandId": self.next_id("adopt"),
                "expectedVersion": version_of(self.runtime, WORK_ID),
                "requestVersion": 1, "node": "n02", "attempt": 1,
                "name": "intake", "object": SUPPLEMENT}
        body.update(extra)
        return body

    def resume_body(self, **extra):
        body = {"actor": OWNER, "commandId": self.next_id("resume"),
                "expectedVersion": version_of(self.runtime, WORK_ID),
                "requestVersion": 1, "node": "n02", "attempt": 1}
        body.update(extra)
        return body

    def rows(self, query, arguments=()):
        db = sqlite3.connect(self.path)
        try:
            return db.execute(query, arguments).fetchall()
        finally:
            db.close()

    def events(self):
        return [entry["type"] for entry in self.runtime.events(WORK_ID)]

class MaterialWaitHttpTestCase(MaterialWaitHttpBase):
    """The wait lifecycle over the wire, on the demonstration family.

    Every object this family names is produced by one of its own nodes, so
    an adoption of it is refused: it would write material no completed node
    ever accepted.
    """

    # -- the lifecycle ---------------------------------------------------

    def test_the_bridge_parks_the_current_node(self):
        status, view = self.call("POST", BASE + "/material/wait",
                                  self.wait_body())
        self.assertEqual(200, status, view)
        self.assertEqual("waiting", view["workflowStatus"])
        self.assertEqual("waiting", view["status"])
        node = [entry for entry in view["nodes"] if entry["node"] == "n02"][0]
        self.assertEqual("waiting", node["state"])
        self.assertEqual("the referenced record is missing a page",
                         node["materialWait"]["reason"])
        self.assertEqual(OWNER, node["materialWait"]["requestedBy"])
        self.assertEqual("intake", node["materialWait"]["dependencies"][0]["name"])
        # the view offers the manager its own command, and no result
        actions = [entry["action"] for entry in view["allowedActions"]]
        self.assertEqual(["resume_material_wait"], actions)
        self.assertIn("WorkflowMaterialWaitRequested", self.events())

    def test_a_result_submitted_while_waiting_is_refused(self):
        status, view = self.call("POST", BASE + "/material/wait",
                                  self.wait_body())
        self.assertEqual(200, status, view)
        before = self.rows("SELECT id,status,body FROM workflow_intents")
        status, body = self.call("POST", BASE + "/results",
                                  {"actor": EXECUTOR, "commandId": self.next_id("r"),
                                   "expectedVersion": version_of(self.runtime, WORK_ID),
                                   "node": "n02", "attempt": 1, "object": "analysis",
                                   "result": {"findings": [{"issueId": "H-001",
                                                            "clause": "C-1",
                                                            "finding": "gap"}]},
                                   "inputDigest": self.digest})
        self.assertEqual(409, status, body)
        self.assertEqual("WORKFLOW_NODE_WAITING", body["error"]["code"])
        self.assertEqual(before, self.rows("SELECT id,status,body FROM workflow_intents"))

    def test_a_refused_request_mutates_nothing(self):
        before = self.rows("SELECT node,attempt,state,body FROM workflow_nodes")
        status, body = self.call("POST", BASE + "/material/wait",
                                  self.wait_body(actor=EXECUTOR))
        self.assertEqual(403, status, body)
        self.assertEqual("AUTHORITY_DENIED", body["error"]["code"])
        self.assertEqual(before, self.rows("SELECT node,attempt,state,body FROM workflow_nodes"))

    def test_a_stale_version_is_a_conflict(self):
        status, body = self.call("POST", BASE + "/material/wait",
                                  self.wait_body(expectedVersion=0))
        self.assertEqual(409, status, body)
        self.assertEqual("STATE_VERSION_CONFLICT", body["error"]["code"])

    def test_a_replay_returns_the_same_receipt(self):
        body = self.wait_body()
        status, first = self.call("POST", BASE + "/material/wait", body)
        self.assertEqual(200, status, first)
        version = version_of(self.runtime, WORK_ID)
        status, second = self.call("POST", BASE + "/material/wait", body)
        self.assertEqual(200, status, second)
        # the replay did not act twice
        self.assertEqual(1, len(self.rows(
            "SELECT body FROM events WHERE work_id=? AND type=?",
            (WORK_ID, "WorkflowMaterialWaitRequested"))))
        self.assertEqual(version, version_of(self.runtime, WORK_ID))

    def test_a_reused_command_id_with_another_body_is_refused(self):
        body = self.wait_body()
        status, first = self.call("POST", BASE + "/material/wait", body)
        self.assertEqual(200, status, first)
        status, refused = self.call("POST", BASE + "/material/wait",
                                    dict(body, reason="another reason"))
        self.assertEqual(409, status, refused)
        self.assertEqual("COMMAND_ID_REUSED", refused["error"]["code"])

    def test_an_unknown_version_is_refused(self):
        status, body = self.call("POST", BASE + "/material/wait",
                                  self.wait_body(requestVersion=2))
        self.assertEqual(400, status, body)
        self.assertEqual("MATERIAL_WAIT_VERSION_UNSUPPORTED",
                         body["error"]["code"])

    def test_the_adoption_of_a_completed_upstream_output_is_refused(self):
        status, view = self.call("POST", BASE + "/material/wait",
                                  self.wait_body())
        self.assertEqual(200, status, view)
        before = self.rows("SELECT name,revision,digest FROM workflow_objects")
        status, refused = self.call("POST", BASE + "/material/adopt",
                                    self.adopt_body())
        self.assertEqual(422, status, refused)
        self.assertEqual("INPUT_DEPENDENCIES_REQUIRE_REVALIDATION",
                         refused["error"]["code"])
        finding = refused["error"]["findings"][0]
        self.assertEqual("intake", finding["name"])
        self.assertEqual("n01", finding["node"])
        # nothing was written and the node keeps waiting
        self.assertEqual(before, self.rows("SELECT name,revision,digest FROM workflow_objects"))
        self.assertEqual("waiting", self.node("n02")["state"])

    def test_a_material_that_moved_under_the_wait_blocks_the_resume(self):
        status, view = self.call("POST", BASE + "/material/wait",
                                  self.wait_body())
        self.assertEqual(200, status, view)
        # somebody revises the material the wait is about
        status, body = self.call("POST", BASE + "/objects",
                                  {"actor": OWNER, "commandId": self.next_id("rev"),
                                   "expectedVersion": version_of(self.runtime, WORK_ID),
                                   "name": "intake",
                                   "object": {"records": [{"id": "R-9",
                                                            "source": "other"}],
                                              "standard": "STD-1"}})
        self.assertEqual(200, status, body)
        status, refused = self.call("POST", BASE + "/material/resume",
                                    self.resume_body())
        self.assertEqual(422, status, refused)
        self.assertEqual("INPUT_DEPENDENCIES_REQUIRE_REVALIDATION",
                         refused["error"]["code"])
        finding = refused["error"]["findings"][0]
        self.assertEqual("intake", finding["name"])
        self.assertEqual(1, finding["accepted"]["revision"])
        self.assertEqual(2, finding["current"]["revision"])
        # the node is still waiting
        self.assertEqual("waiting", self.node("n02")["state"])

    def test_the_resume_moves_the_ticket_and_the_intent_identity(self):
        status, view = self.call("POST", BASE + "/material/wait",
                                  self.wait_body())
        self.assertEqual(200, status, view)
        status, resumed = self.call("POST", BASE + "/material/resume",
                                     self.resume_body())
        self.assertEqual(200, status, resumed)
        self.assertEqual("running", resumed["materialResume"]["state"])
        self.assertEqual("active", resumed["workflowStatus"])
        # the ticket moved even though the material did not
        self.assertNotEqual(self.digest, resumed["materialResume"]["inputDigest"])
        # and the agent is asked again under a new identity
        ids = {row[0]: row[1] for row in self.rows(
            "SELECT id,status FROM workflow_intents WHERE work_id=?",
            (WORK_ID,))}
        self.assertEqual("cancelled", ids["wf:%s:n02:1:agent_task" % WORK_ID])
        self.assertEqual("pending", ids["wf:%s:n02:1:agent_task:1" % WORK_ID])

    def test_the_receipt_of_the_wait_is_readable(self):
        body = self.wait_body()
        status, view = self.call("POST", BASE + "/material/wait", body)
        self.assertEqual(200, status, view)
        status, receipt = self.call(
            "GET", API_PREFIX + "/commands/" + body["commandId"]
            + "?workId=" + WORK_ID + "&actor=" + OWNER)
        self.assertEqual(200, status, receipt)
        self.assertEqual("accepted", receipt["receipt"]["decision"])

    def test_a_replay_after_an_ownership_change_is_refused(self):
        body = self.wait_body()
        status, first = self.call("POST", BASE + "/material/wait", body)
        self.assertEqual(200, status, first)
        # the work changes hands
        transferred = send(self.runtime, OWNER, WORK_ID, "transfer_owner",
                           {"owner": SECOND_MANAGER,
                            "reason": "the platform took over"})
        self.assertEqual("accepted", transferred["decision"], transferred)
        # the stored receipt is replayed only while the authority that
        # decided it still holds
        status, refused = self.call("POST", BASE + "/material/wait", body)
        self.assertEqual(403, status, refused)
        self.assertEqual("AUTHORITY_DENIED", refused["error"]["code"])
        # the new owner may resume the wait himself
        status, accepted = self.call("POST", BASE + "/material/resume",
                                     self.resume_body(actor=SECOND_MANAGER))
        self.assertEqual(200, status, accepted)
        self.assertEqual("running", accepted["materialResume"]["state"])

    def test_an_unknown_work_is_not_created_by_waiting_on_it(self):
        status, body = self.call(
            "POST", API_PREFIX + "/instances/W-none/material/wait",
            self.wait_body())
        self.assertEqual(404, status, body)
        self.assertEqual(0, len(self.rows(
            "SELECT id FROM works WHERE id='W-none'")))


class FocusedMaterialWaitHttpTestCase(MaterialWaitHttpBase):
    """The full adoption cycle over the wire, on externally supplied material.

    The demonstration family names objects that its own nodes produced, so
    an adoption there is refused. This family supplies the material from
    outside, and the adoption is legitimate.
    """

    def publish_and_start(self):
        """Publish the focused family and open its first agent node."""
        published = self.engine.publish_template(OWNER, FOCUSED_TEMPLATE)
        self.assertEqual("accepted", published["decision"], published)
        send(self.runtime, OWNER, WORK_ID, "create_work",
             {"document": document()})
        send(self.runtime, OWNER, WORK_ID, "bind_contract",
             {"policy_id": POLICY_ID, "policy_version": POLICY_VERSION,
              "goal": POLICY_GOAL})
        send(self.runtime, OWNER, WORK_ID, "revise_plan",
             {"steps": ["n01"], "open_requirements": [], "replan_when": []})
        # the material comes from outside the workflow
        supplied = send(self.runtime, OWNER, WORK_ID, "revise_object",
                        {"name": "intake",
                         "object": {"records": [{"id": "R-1",
                                                 "source": "site-log"}],
                                    "standard": "STD-1"}})
        self.assertEqual("accepted", supplied["decision"], supplied)
        bound = self.engine.command(
            OWNER, "focused-bind", WORK_ID, "bind_workflow",
            {"template_id": FOCUSED_TEMPLATE["id"],
             "template_version": FOCUSED_TEMPLATE["version"],
             "parameters": {"subject": "east parapet"}},
            version_of(self.runtime, WORK_ID))
        self.assertEqual("accepted", bound["decision"], bound)
        self.engine.advance(WORK_ID, 1000)
        self.digest = self.node("n01")["inputDigest"]

    def wait_body(self, **extra):
        body = {"actor": OWNER, "commandId": self.next_id(),
                "expectedVersion": version_of(self.runtime, WORK_ID),
                "requestVersion": 1, "node": "n01", "attempt": 1,
                "inputDigest": self.digest,
                "reason": "the referenced record is missing a page"}
        body.update(extra)
        return body

    def adopt_body(self, **extra):
        body = {"actor": OWNER, "commandId": self.next_id("adopt"),
                "expectedVersion": version_of(self.runtime, WORK_ID),
                "requestVersion": 1, "node": "n01", "attempt": 1,
                "name": "intake", "object": SUPPLEMENT}
        body.update(extra)
        return body

    def resume_body(self, **extra):
        body = {"actor": OWNER, "commandId": self.next_id("resume"),
                "expectedVersion": version_of(self.runtime, WORK_ID),
                "requestVersion": 1, "node": "n01", "attempt": 1}
        body.update(extra)
        return body

    def test_the_bridge_adopts_the_material_and_resumes_the_node(self):
        status, view = self.call("POST", BASE + "/material/wait",
                                  self.wait_body())
        self.assertEqual(200, status, view)
        self.assertEqual("waiting", view["workflowStatus"])

        status, view = self.call("POST", BASE + "/material/adopt",
                                  self.adopt_body())
        self.assertEqual(200, status, view)
        adoption = view["materialAdoption"]["adoption"]
        self.assertEqual("intake", adoption["name"])
        self.assertEqual(2, adoption["revision"])
        # the historical revision is still there and still readable
        status, revision = self.call("GET", BASE + "/objects/intake/revisions/1")
        self.assertEqual(200, status, revision)
        self.assertNotIn("R-2", json.dumps(revision["object"]))

        status, view = self.call("POST", BASE + "/material/resume",
                                  self.resume_body())
        self.assertEqual(200, status, view)
        self.assertEqual("running", view["materialResume"]["state"])
        self.assertEqual("active", view["workflowStatus"])
        node = [entry for entry in view["nodes"] if entry["node"] == "n01"][0]
        self.assertEqual("running", node["state"])
        self.assertEqual(1, node["attempt"])
        # the adopted material is the pinned input now
        self.assertEqual(2, node["inputs"][0]["revision"])
        self.assertIn("WorkflowMaterialWaitRequested", self.events())
        self.assertIn("WorkflowMaterialAdopted", self.events())
        self.assertIn("WorkflowMaterialWaitResumed", self.events())

    def test_an_oversized_adoption_is_refused_over_the_wire(self):
        status, view = self.call("POST", BASE + "/material/wait",
                                  self.wait_body())
        self.assertEqual(200, status, view)
        status, refused = self.call(
            "POST", BASE + "/material/adopt",
            self.adopt_body(object={"records": [], "padding": "x" * 70000}))
        self.assertEqual(422, status, refused)
        self.assertEqual("WORKFLOW_MATERIAL_TOO_LARGE",
                         refused["error"]["code"])

    def test_the_bridge_refuses_an_adoption_of_another_object(self):
        status, view = self.call("POST", BASE + "/material/wait",
                                  self.wait_body())
        self.assertEqual(200, status, view)
        status, refused = self.call("POST", BASE + "/material/adopt",
                                     self.adopt_body(name="analysis"))
        self.assertEqual(422, status, refused)
        self.assertEqual("WORKFLOW_MATERIAL_NOT_DEPENDENCY",
                         refused["error"]["code"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
