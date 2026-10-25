"""The owner's rework authorization through the private workflow service.

The bridge owns no rework engine of its own: it exposes the runtime's
own command, so a platform authorizes one controlled candidate rework
exactly the way a trusted local caller would — same transaction, same
compare-and-swap, same command receipts, same replay rules. The tests
run a real service over a real SQLite store and assert stored truth,
never a status code alone.
"""

import http.client
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
import uuid

from work_runtime.workflow_server import API_PREFIX, serve

try:
    from workflow_support import (POLICY_GOAL, POLICY_ID, POLICY_VERSION,
                                  REVALIDATION_TEMPLATE, RevalidationPolicy,
                                  SourceReferenceAdapter, build, document,
                                  input_digest_of, send, submit, submit_valid,
                                  version_of)
    from workflow_support import workflow_demo_validators
    from test_workflow_material_revalidation import revalidation_validators
    from test_workflow_material_revalidation import spent_quality_template
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import (POLICY_GOAL, POLICY_ID, POLICY_VERSION,
                                        REVALIDATION_TEMPLATE,
                                        RevalidationPolicy,
                                        SourceReferenceAdapter, build,
                                        document, input_digest_of, send,
                                        submit, submit_valid, version_of)
    from tests.workflow_support import workflow_demo_validators
    from tests.test_workflow_material_revalidation import revalidation_validators
    from tests.test_workflow_material_revalidation import spent_quality_template

WORK_ID = "W-1"
OWNER = "coordinator"
EXECUTOR = "agent-executor"
BASE = API_PREFIX + "/instances/" + WORK_ID
SOURCE_REFERENCE = {"kind": "business-material-snapshot",
                    "referenceId": "REF-2", "workflowId": WORK_ID,
                    "sourceNode": "s00", "documentDigest": "d" * 64,
                    "snapshotDigest": "e" * 64, "scope": "records"}
REASON = "the owner authorizes one controlled rework"


class ReworkHttpTestCase(unittest.TestCase):
    """A real service over a real store, driven to the terminal failure."""

    template = spent_quality_template()

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-rework-http-")
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.grants = {"coordinator": {"work.manage", "work.dispatch"},
                       EXECUTOR: {"workflow.execute"},
                       "business-system": {"evidence.write"}}
        self.adapter = SourceReferenceAdapter(
            os.path.join(self.folder, "effects.db"))
        self.runtime, self.engine = build(
            self.path, policy=RevalidationPolicy(), grants=self.grants,
            validators=revalidation_validators())
        published = self.engine.publish_template(OWNER, self.template)
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
        send(self.runtime, OWNER, WORK_ID, "revise_object",
             {"name": "request", "object": {"id": "REQ-1"}})
        bound = self.engine.command(
            OWNER, "bind-1", WORK_ID, "bind_workflow",
            {"template_id": self.template["id"],
             "template_version": self.template["version"],
             "parameters": {"subject": "east parapet"},
             "session_id": "sess-original"},
            version_of(self.runtime, WORK_ID))
        self.assertEqual("accepted", bound["decision"], bound)
        self.engine.pump(self.adapter, 1000)
        # the node spends its quality allowance: two rejected candidates
        for _ in range(2):
            attempt = self.current_attempt("n01")
            rejected = submit(self.engine, self.runtime, WORK_ID, "n01",
                              attempt, "intake", {"records": "not a list"})
            self.assertEqual("rejected", rejected["decision"], rejected)
            self.engine.advance(WORK_ID, 1200)
        accepted = submit_valid(self.engine, self.runtime, WORK_ID, "n01",
                                "intake",
                                {"records": [{"id": "R-1", "source": "s"}],
                                 "standard": "STD-1"})
        self.assertEqual("accepted", accepted["decision"], accepted)
        accepted = submit_valid(self.engine, self.runtime, WORK_ID, "n02",
                                "analysis",
                                {"findings": [{"issueId": "H-1", "clause": "C-1",
                                               "finding": "gap"}]})
        self.assertEqual("accepted", accepted["decision"], accepted)
        parked = self.engine.command(
            OWNER, "wait-1", WORK_ID, "request_material_wait",
            {"node": "n03", "attempt": 1,
             "input_digest": input_digest_of(self.engine, WORK_ID, "n03"),
             "reason": "the referenced standard is missing",
             "request_version": 1},
            version_of(self.runtime, WORK_ID))
        self.assertEqual("accepted", parked["decision"], parked)
        replaced = self.engine.command(
            OWNER, "replace-1", WORK_ID, "replace_material",
            {"node": "s00", "source_reference": SOURCE_REFERENCE,
             "reason": "the archive was refreshed", "request_version": 1,
             "waiting_node": "n03",
             "waiting_ticket": input_digest_of(self.engine, WORK_ID, "n03")},
            version_of(self.runtime, WORK_ID))
        self.assertEqual("accepted", replaced["decision"], replaced)
        self.engine.advance(WORK_ID, 1300)
        rejected = submit(self.engine, self.runtime, WORK_ID, "n01", 4,
                          "intake", {"records": "not a list"})
        self.assertEqual("rejected", rejected["decision"], rejected)
        self.engine.advance(WORK_ID, 1301)
        work = self.runtime.get_work(WORK_ID)
        self.assertEqual("finished", work["workflow_status"])
        self.assertEqual("n01", work["workflow_terminal"]["node"])
        self.failed_ticket = self.engine.instance(WORK_ID)["nodes"]
        self.failed_ticket = next(entry for entry in self.failed_ticket
                                  if entry["node"] == "n01")["inputDigest"]

    def tearDown(self):
        self.ticker.stop()
        self.server.shutdown()
        self.server.server_close()
        if self.lock is not None:
            self.lock.release()

    # -- helpers ---------------------------------------------------------

    def current_attempt(self, node_id):
        for entry in self.engine.instance(WORK_ID)["nodes"]:
            if entry["node"] == node_id:
                return entry["attempt"]
        return 0

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

    def next_id(self, label="rework"):
        self.counter += 1
        return label + "-" + str(self.counter)

    def rework_body(self, **extra):
        body = {"actor": OWNER, "commandId": self.next_id(),
                "expectedVersion": version_of(self.runtime, WORK_ID),
                "node": "n01", "attempt": 4,
                "inputDigest": self.failed_ticket, "reason": REASON}
        body.update(extra)
        return body

    # -- the surface -----------------------------------------------------

    def test_the_private_route_authorizes_the_rework(self):
        # the projection names the failure before anybody acts
        status, before = self.call("GET", BASE)
        self.assertEqual(200, status, before)
        projection = before["candidateRework"]
        self.assertEqual(1, projection["cap"])
        self.assertEqual(0, projection["used"])
        self.assertTrue(projection["eligible"], projection)
        self.assertEqual("n01", projection["failed"]["node"])
        self.assertEqual(4, projection["failed"]["attempt"])
        self.assertEqual("WORKFLOW_RESULT_INVALID",
                         projection["failed"]["reason"])
        self.assertEqual(self.failed_ticket,
                         projection["failed"]["inputDigest"])
        self.assertIsNone(projection.get("authorization"))

        status, view = self.call("POST", BASE + "/rework", self.rework_body())
        self.assertEqual(200, status, view)
        # the work is active again at the failed node
        self.assertEqual("active", view["workflowStatus"])
        self.assertEqual("n01", view["currentNode"])
        rework = view["rework"]
        self.assertEqual("n01", rework["node"])
        self.assertEqual(5, rework["attempt"])
        self.assertEqual("running", rework["state"])
        self.assertNotEqual(self.failed_ticket, rework["inputDigest"])
        authorization = rework["grant"]
        self.assertEqual(OWNER, authorization["authorizedBy"])
        self.assertEqual(REASON, authorization["reason"])
        self.assertEqual(4, authorization["fromAttempt"])
        self.assertEqual(5, authorization["toAttempt"])
        self.assertEqual("n01", authorization["terminal"]["node"])
        # the projection now reports the spent authorization
        projection = view["candidateRework"]
        self.assertEqual(1, projection["used"])
        self.assertFalse(projection["eligible"])
        self.assertEqual(OWNER,
                         projection["grant"]["authorizedBy"])

        # the new agent task is pending for the original session
        status, listed = self.call(
            "GET", BASE + "/intents?kind=agent_task&sessionId=sess-original")
        self.assertEqual(200, status, listed)
        pending = [intent for intent in listed["intents"]
                   if intent["status"] == "pending"]
        self.assertEqual(1, len(pending), listed["intents"])
        self.assertEqual("n01", pending[0]["node"])
        self.assertEqual(5, pending[0]["attempt"])
        self.assertEqual("sess-original", pending[0]["sessionId"])

        # the old failed attempt is untouched on the record
        status, attempts = self.call("GET", BASE + "/nodes/n01/attempts")
        self.assertEqual(200, status, attempts)
        failed = next(entry for entry in attempts["attempts"]
                      if entry["attempt"] == 4)
        self.assertEqual("failed", failed["state"])

    def test_the_replay_and_the_cap(self):
        request = self.rework_body()
        status, first = self.call("POST", BASE + "/rework", request)
        self.assertEqual(200, status, first)
        # the exact duplicate replays the same receipt
        status, second = self.call("POST", BASE + "/rework", request)
        self.assertEqual(200, status, second)
        self.assertEqual(first["rework"]["resultStateVersion"],
                         second["rework"]["resultStateVersion"])
        # a new command id cannot buy a second authorization
        status, third = self.call("POST", BASE + "/rework", self.rework_body())
        self.assertEqual(409, status, third)
        self.assertEqual("WORKFLOW_REWORK_ALREADY_AUTHORIZED",
                         third["error"]["code"])
        # a reused command id with another body is refused
        status, conflict = self.call(
            "POST", BASE + "/rework",
            dict(request, reason="a different reason"))
        self.assertEqual(409, status, conflict)
        self.assertEqual("COMMAND_ID_REUSED", conflict["error"]["code"])

    def test_the_stale_version_and_the_wrong_actor(self):
        status, body = self.call("POST", BASE + "/rework",
                                 self.rework_body(expectedVersion=0))
        self.assertEqual(409, status, body)
        self.assertEqual("STATE_VERSION_CONFLICT", body["error"]["code"])
        status, body = self.call("POST", BASE + "/rework",
                                 self.rework_body(actor=EXECUTOR))
        self.assertEqual(403, status, body)
        self.assertEqual("AUTHORITY_DENIED", body["error"]["code"])
        # nothing was written by either refusal
        work = self.runtime.get_work(WORK_ID)
        self.assertEqual("finished", work["workflow_status"])
        self.assertNotIn("candidate_rework", work)

    def test_unknown_fields_and_a_blank_reason_are_refused(self):
        # the envelope is exact: no caller budget, no force, no rule
        # override, and no requestVersion on this route
        for extra in ({"budget": 1}, {"maxAttempts": 9},
                      {"forcePass": True}, {"ruleOverride": "skip"},
                      {"requestVersion": 1}):
            status, body = self.call("POST", BASE + "/rework",
                                     self.rework_body(**extra))
            self.assertEqual(400, status, body)
            self.assertEqual("REWORK_INVALID", body["error"]["code"])
        # a whitespace-only reason is no reason
        status, body = self.call("POST", BASE + "/rework",
                                 self.rework_body(reason="   "))
        self.assertEqual(400, status, body)
        self.assertEqual("REWORK_INVALID", body["error"]["code"])
        # nothing was written by any refusal
        work = self.runtime.get_work(WORK_ID)
        self.assertEqual("finished", work["workflow_status"])
        self.assertNotIn("candidate_rework", work)
        self.assertEqual(4, self.current_attempt("n01"))

    def test_the_wrong_attempt_ticket_and_node(self):
        status, body = self.call("POST", BASE + "/rework",
                                 self.rework_body(attempt=3))
        self.assertEqual(409, status, body)
        self.assertEqual("WORKFLOW_ATTEMPT_STALE", body["error"]["code"])
        status, body = self.call("POST", BASE + "/rework",
                                 self.rework_body(inputDigest="0" * 64))
        self.assertEqual(422, status, body)
        self.assertEqual("WORKFLOW_INPUT_STALE", body["error"]["code"])
        status, body = self.call("POST", BASE + "/rework",
                                 self.rework_body(node="n02"))
        self.assertEqual(409, status, body)
        self.assertEqual("WORKFLOW_REWORK_INELIGIBLE", body["error"]["code"])
        work = self.runtime.get_work(WORK_ID)
        self.assertEqual("finished", work["workflow_status"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
