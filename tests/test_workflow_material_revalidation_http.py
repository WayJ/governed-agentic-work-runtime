"""The controlled source replacement through the private workflow service.

The bridge owns no replacement engine of its own: it exposes the
runtime's own command, so a platform replaces the archived source
material and revalidates the affected consumers exactly the way a
trusted local caller would — same transaction, same compare-and-swap,
same command receipts, same replay rules. The tests run a real service
over a real SQLite store and assert stored truth (rows, attempts,
operations, receipts), never a status code alone.
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
    from workflow_support import (POLICY_GOAL, POLICY_ID, POLICY_VERSION,
                                  REVALIDATION_TEMPLATE, RevalidationPolicy,
                                  SourceReferenceAdapter, build, document,
                                  input_digest_of, send, submit_valid,
                                  version_of)
    from workflow_support import workflow_demo_validators
    from test_workflow_material_revalidation import revalidation_validators
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import (POLICY_GOAL, POLICY_ID, POLICY_VERSION,
                                        REVALIDATION_TEMPLATE, RevalidationPolicy,
                                        SourceReferenceAdapter, build, document,
                                        input_digest_of, send, submit_valid,
                                        version_of)
    from tests.workflow_support import workflow_demo_validators
    from tests.test_workflow_material_revalidation import revalidation_validators

WORK_ID = "W-1"
OWNER = "coordinator"
SECOND_MANAGER = "ops-manager"
BASE = API_PREFIX + "/instances/" + WORK_ID
SOURCE_REFERENCE = {"kind": "business-material-snapshot",
                    "referenceId": "REF-2", "workflowId": WORK_ID,
                    "sourceNode": "s00", "documentDigest": "d" * 64,
                    "snapshotDigest": "e" * 64, "scope": "records"}


class ReplaceMaterialHttpTestCase(unittest.TestCase):
    """A real service over a real store; the ticker only advances."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-replace-http-")
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.path = os.path.join(self.folder, "runtime.sqlite")
        grants = workflow_demo_validators  # keep the import honest
        self.grants = {"coordinator": {"work.manage", "work.dispatch"},
                       SECOND_MANAGER: {"work.manage"},
                       "agent-executor": {"workflow.execute"},
                       "business-system": {"evidence.write"}}
        self.adapter = SourceReferenceAdapter(
            os.path.join(self.folder, "effects.db"))
        self.runtime, self.engine = build(self.path,
                                          policy=RevalidationPolicy(),
                                          grants=self.grants,
                                          validators=revalidation_validators())
        published = self.engine.publish_template(OWNER, REVALIDATION_TEMPLATE)
        self.assertEqual("accepted", published["decision"], published)
        self.server, self.ticker, self.lock = serve(
            self.runtime, self.engine, None, host="127.0.0.1", port=0,
            interval_s=0.05)
        self.host, self.port = (self.server.server_address[0],
                                self.server.server_address[1])
        self.counter = 0
        send(self.runtime, OWNER, WORK_ID, "create_work",
             {"document": document()})
        send(self.runtime, OWNER, WORK_ID, "bind_contract",
             {"policy_id": POLICY_ID, "policy_version": POLICY_VERSION,
              "goal": POLICY_GOAL})
        send(self.runtime, OWNER, WORK_ID, "revise_plan",
             {"steps": ["s00", "n01", "n02", "n03"],
              "open_requirements": [], "replan_when": []})
        request = send(self.runtime, OWNER, WORK_ID, "revise_object",
                       {"name": "request", "object": {"id": "REQ-1"}})
        self.assertEqual("accepted", request["decision"], request)
        bound = self.engine.command(
            OWNER, "bind-1", WORK_ID, "bind_workflow",
            {"template_id": REVALIDATION_TEMPLATE["id"],
             "template_version": REVALIDATION_TEMPLATE["version"],
             "parameters": {"subject": "east parapet"}},
            version_of(self.runtime, WORK_ID))
        self.assertEqual("accepted", bound["decision"], bound)
        self.engine.pump(self.adapter, 1000)
        for node, name, result in (("n01", "intake",
                                    {"records": [{"id": "R-1", "source": "s"}],
                                     "standard": "STD-1"}),
                                   ("n02", "analysis",
                                    {"findings": [{"issueId": "H-1",
                                                   "clause": "C-1",
                                                   "finding": "g"}]})):
            submitted = submit_valid(self.engine, self.runtime, WORK_ID, node,
                                     name, result)
            self.assertEqual("accepted", submitted["decision"], submitted)
        self.ticket = input_digest_of(self.engine, WORK_ID, "n03")

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

    def next_id(self, label="replace"):
        self.counter += 1
        return label + "-" + str(self.counter)

    def rows(self, query, arguments=()):
        db = sqlite3.connect(self.path)
        try:
            return db.execute(query, arguments).fetchall()
        finally:
            db.close()

    def replace_body(self, **extra):
        body = {"actor": OWNER, "commandId": self.next_id(),
                "expectedVersion": version_of(self.runtime, WORK_ID),
                "requestVersion": 1, "node": "s00",
                "sourceReference": SOURCE_REFERENCE,
                "reason": "the archive was refreshed",
                "waitingNode": "n03", "waitingTicket": self.ticket}
        body.update(extra)
        return body

    def node(self, node_id="n03"):
        status, view = self.call("GET", BASE)
        self.assertEqual(200, status, view)
        for entry in view["nodes"]:
            if entry["node"] == node_id:
                return entry
        return None

    # -- the surface -----------------------------------------------------

    def test_the_bridge_replaces_the_source_material(self):
        status, view = self.call("POST", BASE + "/material/replace",
                                  self.replace_body())
        self.assertEqual(200, status, view)
        replacement = view["materialReplacement"]
        self.assertEqual("s00", replacement["node"])
        self.assertEqual(1, replacement["generation"])
        self.assertEqual(["n01", "n02", "n03"],
                         [entry["node"] for entry in replacement["affected"]])
        attestation = replacement["attestation"]
        self.assertEqual("s00", attestation["sourceNode"])
        self.assertEqual("sources", attestation["object"])
        self.assertIn("does not cover", attestation["claim"])
        # the view reports the revalidation
        plan = view["materialRevalidation"]
        self.assertEqual("revalidating", plan["state"])
        self.assertEqual(1, plan["generation"])
        # the new revision carries the envelope, and the old one is kept
        revisions = self.rows("SELECT revision,body FROM workflow_objects "
                              "WHERE work_id=? AND name='sources' ORDER BY revision",
                              (WORK_ID,))
        self.assertEqual(2, len(revisions))
        self.assertEqual({"sourceReference": SOURCE_REFERENCE},
                         json.loads(revisions[1][1]))

    def test_a_stale_version_is_a_conflict(self):
        status, body = self.call("POST", BASE + "/material/replace",
                                  self.replace_body(expectedVersion=0))
        self.assertEqual(409, status, body)
        self.assertEqual("STATE_VERSION_CONFLICT", body["error"]["code"])

    def test_a_replay_returns_the_same_receipt(self):
        request = self.replace_body()
        status, first = self.call("POST", BASE + "/material/replace", request)
        self.assertEqual(200, status, first)
        version = version_of(self.runtime, WORK_ID)
        status, second = self.call("POST", BASE + "/material/replace", request)
        self.assertEqual(200, status, second)
        self.assertEqual(1, len(self.rows(
            "SELECT body FROM events WHERE work_id=? AND type=?",
            (WORK_ID, "WorkflowMaterialReplaced"))))
        self.assertEqual(version, version_of(self.runtime, WORK_ID))

    def test_a_reused_command_id_with_another_body_is_refused(self):
        request = self.replace_body()
        status, first = self.call("POST", BASE + "/material/replace", request)
        self.assertEqual(200, status, first)
        status, refused = self.call("POST", BASE + "/material/replace",
                                    dict(request, reason="another reason"))
        self.assertEqual(409, status, refused)
        self.assertEqual("COMMAND_ID_REUSED", refused["error"]["code"])

    def test_only_the_manager_may_replace(self):
        before = self.rows("SELECT name,revision,digest,body FROM workflow_objects")
        status, body = self.call("POST", BASE + "/material/replace",
                                  self.replace_body(actor="agent-executor"))
        self.assertEqual(403, status, body)
        self.assertEqual("AUTHORITY_DENIED", body["error"]["code"])
        self.assertEqual(before, self.rows(
            "SELECT name,revision,digest,body FROM workflow_objects"))

    def test_a_replay_after_an_ownership_change_is_refused(self):
        request = self.replace_body()
        status, first = self.call("POST", BASE + "/material/replace", request)
        self.assertEqual(200, status, first)
        transferred = send(self.runtime, OWNER, WORK_ID, "transfer_owner",
                           {"owner": SECOND_MANAGER,
                            "reason": "the platform took over"})
        self.assertEqual("accepted", transferred["decision"], transferred)
        status, refused = self.call("POST", BASE + "/material/replace", request)
        self.assertEqual(403, status, refused)
        self.assertEqual("AUTHORITY_DENIED", refused["error"]["code"])

    def test_the_platform_envelope_is_accepted(self):
        request = self.replace_body()
        request.pop("actor")
        request["actorId"] = OWNER
        request["workId"] = WORK_ID
        status, view = self.call("POST", BASE + "/material/replace", request)
        self.assertEqual(200, status, view)

    def test_a_stale_waiting_ticket_is_refused(self):
        status, body = self.call("POST", BASE + "/material/replace",
                                  self.replace_body(waitingTicket="0" * 64))
        self.assertEqual(409, status, body)
        self.assertEqual("WORKFLOW_WAITING_TICKET_STALE", body["error"]["code"])

    def test_a_manifest_that_names_another_work_is_refused(self):
        reference = dict(SOURCE_REFERENCE, workflowId="W-other")
        status, body = self.call("POST", BASE + "/material/replace",
                                  self.replace_body(sourceReference=reference))
        self.assertEqual(422, status, body)
        self.assertEqual("WORKFLOW_SOURCE_REFERENCE_INVALID",
                         body["error"]["code"])

    def test_a_manifest_with_a_location_is_refused(self):
        reference = dict(SOURCE_REFERENCE, rawUrl="https://archive/x")
        status, body = self.call("POST", BASE + "/material/replace",
                                  self.replace_body(sourceReference=reference))
        self.assertEqual(422, status, body)
        self.assertEqual("WORKFLOW_SOURCE_REFERENCE_INVALID",
                         body["error"]["code"])

    def test_an_unknown_version_is_refused(self):
        status, body = self.call("POST", BASE + "/material/replace",
                                  self.replace_body(requestVersion=2))
        self.assertEqual(400, status, body)
        self.assertEqual("MATERIAL_WAIT_VERSION_UNSUPPORTED",
                         body["error"]["code"])

    def test_an_unknown_work_is_not_created_by_replacing_on_it(self):
        status, body = self.call(
            "POST", API_PREFIX + "/instances/W-none/material/replace",
            self.replace_body())
        self.assertEqual(404, status, body)
        self.assertEqual(0, len(self.rows(
            "SELECT id FROM works WHERE id='W-none'")))

    def test_the_source_read_is_never_rerun(self):
        before = self.rows("SELECT id,body FROM operations WHERE work_id=?",
                           (WORK_ID,))
        before_node = self.rows("SELECT node,attempt,state,body FROM workflow_nodes "
                                "WHERE work_id=? AND node='s00'", (WORK_ID,))
        status, view = self.call("POST", BASE + "/material/replace",
                                  self.replace_body())
        self.assertEqual(200, status, view)
        self.assertEqual(before, self.rows("SELECT id,body FROM operations "
                                           "WHERE work_id=?", (WORK_ID,)))
        self.assertEqual(before_node,
                         self.rows("SELECT node,attempt,state,body FROM "
                                   "workflow_nodes WHERE work_id=? AND node='s00'",
                                   (WORK_ID,)))

    def test_the_receipt_of_the_replacement_is_readable(self):
        request = self.replace_body()
        status, view = self.call("POST", BASE + "/material/replace", request)
        self.assertEqual(200, status, view)
        status, receipt = self.call(
            "GET", API_PREFIX + "/commands/" + request["commandId"]
            + "?workId=" + WORK_ID + "&actor=" + OWNER)
        self.assertEqual(200, status, receipt)
        self.assertEqual("accepted", receipt["receipt"]["decision"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
