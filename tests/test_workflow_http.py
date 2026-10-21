"""The generic HTTP bridge over the mixed-node workflow runtime.

The bridge is exercised over a real loopback socket: the tests assert the
wire shapes a platform client depends on, the bounded read model, the
durable intent ids and the promise that progress needs no client polling.

Every mutation carries a stable ``commandId`` and, where the work already
exists, the ``expectedVersion`` the client observed: the bridge never
substitutes its own idea of the current version for the caller's.
"""

import http.client
import json
import os
import tempfile
import unittest

from work_runtime.workflow_server import API_PREFIX, serve

try:
    from workflow_support import (RecordingAdapter, build, scenario_template,
                                  version_of)
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import (RecordingAdapter, build, scenario_template,
                                        version_of)


class HttpBridgeTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-workflow-http-")
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.runtime, self.engine = build(self.path)
        self.adapter = RecordingAdapter(os.path.join(self.folder, "effects.sqlite"))
        self.server, self.ticker, self.lock = serve(
            self.runtime, self.engine, self.adapter, host="127.0.0.1", port=0,
            interval_s=0.05)
        self.host, self.port = self.server.server_address[0], self.server.server_address[1]
        self.counter = 0

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

    def next_id(self, label="cmd"):
        self.counter += 1
        return label + "-" + str(self.counter)

    def publish(self):
        status, body = self.call("POST", API_PREFIX + "/templates",
                                  {"spec": scenario_template()})
        self.assertEqual(status, 201, body)
        return body

    def create(self, work_id="W-1", session_id="sess-1", command_id=None,
               extra=None, participants=None, plan=None, policy=None):
        body = {
            "workId": work_id,
            "document": {"id": "H-001", "subject": "east parapet"},
            "templateId": scenario_template()["id"],
            "templateVersion": scenario_template()["version"],
            "commandId": command_id or self.next_id("create"),
        }
        if participants is not None:
            body["instance"] = {"workspaceId": "ws-1", "taskId": "task-1",
                                "ownerUserId": "user-1", "sessionId": session_id,
                                "parameters": {"subject": "east parapet"},
                                "participants": participants}
        else:
            body["parameters"] = {"subject": "east parapet"}
            body["sessionId"] = session_id
        if plan is not None:
            body["plan"] = plan
        if policy is not None:
            body["policy"] = policy
        if extra:
            body.update(extra)
        status, response = self.call("POST", API_PREFIX + "/instances", body)
        self.assertEqual(status, 201, response)
        return response

    def drive_agents(self, work_id="W-1"):
        for node, name, result in (
                ("n01", "intake", {"records": [{"id": "R-1", "source": "s"}],
                                   "standard": "STD"}),
                ("n02", "analysis", {"findings": [{"issueId": "H-001", "clause": "C-1",
                                                   "finding": "gap"}]}),
                ("n03", "proposal", {"measures": [{"issueId": "H-001", "measureId": "M-1",
                                                    "measure": "guard"}]})):
            attempt = self.node(work_id, node)["attempt"]
            status, body = self.submit(node, attempt, name, result, work_id=work_id)
            self.assertEqual(status, 200, body)

    def view(self, work_id="W-1"):
        status, body = self.call("GET", API_PREFIX + "/instances/" + work_id)
        self.assertEqual(status, 200, body)
        return body

    def node(self, work_id, node_id):
        for entry in self.view(work_id)["nodes"]:
            if entry["node"] == node_id:
                return entry
        return None

    def submit(self, node, attempt, name, result, actor="agent-executor",
               input_digest=None, work_id="W-1", command_id=None,
               expected_version=None):
        if input_digest is None:
            input_digest = self.node(work_id, node)["inputDigest"]
        if expected_version is None:
            expected_version = self.view(work_id)["stateVersion"]
        return self.call("POST", API_PREFIX + "/instances/" + work_id + "/results", {
            "node": node, "attempt": attempt, "object": name, "result": result,
            "actor": actor, "inputDigest": input_digest,
            "commandId": command_id or self.next_id("submit"),
            "expectedVersion": expected_version})

    def decide(self, node, attempt, decision, digest, revision, actor_id,
               items=None, work_id="W-1", command_id=None, expected_version=None):
        if items is None:
            items = [{"check": "N04-2", "verdict": "passed",
                      "reason": "the proposal covers every requirement",
                      "evidence": ["proposal#revision-1"]}]
        if expected_version is None:
            expected_version = self.view(work_id)["stateVersion"]
        return self.call("POST", API_PREFIX + "/instances/" + work_id + "/decisions", {
            "node": node, "attempt": attempt, "decision": decision, "digest": digest,
            "revision": revision, "actorId": actor_id, "items": items,
            "commandId": command_id or self.next_id("decide"),
            "expectedVersion": expected_version})


class RouteTests(HttpBridgeTestCase):
    def test_only_the_workflow_routes_exist(self):
        status, body = self.call("GET", "/v1/deliveries")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "ROUTE_UNKNOWN")
        status, body = self.call("GET", "/v1/workflows/nope")
        self.assertEqual(status, 404)

    def test_the_health_route_reports_the_coordinator_model(self):
        status, body = self.call("GET", API_PREFIX)
        self.assertEqual(status, 200)
        self.assertEqual(body["coordinator"], "single")

    def test_a_template_is_published_and_readable(self):
        published = self.publish()
        status, body = self.call("GET", API_PREFIX + "/templates")
        self.assertEqual(status, 200)
        self.assertEqual(body["templates"][0]["digest"], published["digest"])
        status, body = self.call("GET", API_PREFIX + "/templates/"
                                  + published["templateId"] + "/"
                                  + published["templateVersion"])
        self.assertEqual(status, 200)
        self.assertEqual(body["spec"]["id"], published["templateId"])
        # The protected definition carries the criterion text and the
        # validator binding of every declared criterion.
        criterion = body["spec"]["nodes"]["n04"]["checks"][0]
        self.assertEqual(criterion["id"], "N04-2")
        self.assertTrue(criterion["criterion"])
        self.assertEqual(criterion["validator"], "safety-review")
        self.assertEqual(criterion["validator_version"], "1")

    def test_a_malformed_body_is_rejected(self):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=10)
        try:
            connection.request("POST", API_PREFIX + "/templates", b"not json",
                               {"Content-Type": "application/json"})
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
        finally:
            connection.close()


class MutationContractTests(HttpBridgeTestCase):
    def test_a_mutation_without_a_command_id_is_refused(self):
        self.publish()
        status, body = self.call("POST", API_PREFIX + "/instances", {
            "workId": "W-1", "document": {"id": "H-001", "subject": "east"},
            "templateId": scenario_template()["id"],
            "templateVersion": scenario_template()["version"],
            "parameters": {"subject": "east"}})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "COMMAND_ID_REQUIRED")

    def test_a_result_without_an_expected_version_is_refused(self):
        self.publish()
        self.create()
        status, body = self.call("POST", API_PREFIX + "/instances/W-1/results", {
            "node": "n01", "attempt": 1, "object": "intake",
            "result": {"records": [{"id": "R-1", "source": "s"}], "standard": "STD"},
            "actor": "agent-executor", "inputDigest": "0" * 64,
            "commandId": "c-1"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "EXPECTED_VERSION_REQUIRED")

    def test_a_stale_expected_version_is_refused(self):
        self.publish()
        self.create()
        status, body = self.submit("n01", 1, "intake",
                                   {"records": [{"id": "R-1", "source": "s"}],
                                    "standard": "STD"},
                                   expected_version=999)
        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "STATE_VERSION_CONFLICT")

    def test_a_result_without_an_input_digest_is_refused(self):
        self.publish()
        self.create()
        status, body = self.call("POST", API_PREFIX + "/instances/W-1/results", {
            "node": "n01", "attempt": 1, "object": "intake",
            "result": {"records": [{"id": "R-1", "source": "s"}], "standard": "STD"},
            "actor": "agent-executor", "commandId": "c-1",
            "expectedVersion": self.view("W-1")["stateVersion"]})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "SUBMISSION_INVALID")

    def test_a_result_bound_to_a_stale_input_is_refused(self):
        self.publish()
        self.create()
        status, body = self.submit("n01", 1, "intake",
                                   {"records": [{"id": "R-1", "source": "s"}],
                                    "standard": "STD"},
                                   input_digest="0" * 64)
        self.assertEqual(status, 422)
        self.assertEqual(body["error"]["code"], "WORKFLOW_INPUT_STALE")

    def test_a_decision_without_an_actor_is_refused(self):
        self.publish()
        self.create()
        status, body = self.call("POST", API_PREFIX + "/instances/W-1/decisions", {
            "node": "n04", "attempt": 1, "decision": "approved", "digest": "0" * 64,
            "revision": 1, "items": [{"check": "N04-2", "verdict": "passed",
                                      "reason": "r", "evidence": []}],
            "commandId": "d-1"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "ACTOR_ID_REQUIRED")

    def test_a_decision_without_items_is_refused(self):
        self.publish()
        self.create()
        status, body = self.call("POST", API_PREFIX + "/instances/W-1/decisions", {
            "node": "n04", "attempt": 1, "decision": "approved", "digest": "0" * 64,
            "revision": 1, "actorId": "reviewer-a", "commandId": "d-1"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "DECISION_INVALID")

    def test_a_decision_from_another_actor_is_refused(self):
        self.publish()
        self.create()
        status, body = self.decide("n04", 1, "approved", "0" * 64, 1,
                                   "someone-else")
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "WORKFLOW_AUTHORITY_MISMATCH")

    def test_a_decision_for_another_attempt_is_refused(self):
        self.publish()
        self.create()
        status, body = self.decide("n04", 7, "approved", "0" * 64, 1, "reviewer-a")
        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "WORKFLOW_ATTEMPT_STALE")

    def test_a_mutation_returns_the_root_instance_view(self):
        self.publish()
        self.create()
        status, body = self.submit("n01", 1, "intake",
                                   {"records": [{"id": "R-1", "source": "s"}],
                                    "standard": "STD"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["workId"], "W-1")
        self.assertEqual(body["currentNode"], "n02")
        self.assertEqual(body["result"]["output"]["name"], "intake")
        self.assertIn("nodes", body)
        self.assertIn("allowedActions", body)


class CreateContractTests(HttpBridgeTestCase):
    def test_a_policy_that_is_not_the_registered_one_is_refused(self):
        self.publish()
        status, body = self.call("POST", API_PREFIX + "/instances", {
            "workId": "W-1", "document": {"id": "H-001", "subject": "east"},
            "templateId": scenario_template()["id"],
            "templateVersion": scenario_template()["version"],
            "commandId": "create-1",
            "policy": {"policyId": "workflow-demo", "policyVersion": "demo-9",
                       "goal": "workflow.completed"}})
        self.assertEqual(status, 422)
        self.assertEqual(body["error"]["code"], "WORKFLOW_POLICY_MISMATCH")

    def test_the_registered_policy_is_accepted(self):
        self.publish()
        status, body = self.call("POST", API_PREFIX + "/instances", {
            "workId": "W-1", "document": {"id": "H-001", "subject": "east"},
            "templateId": scenario_template()["id"],
            "templateVersion": scenario_template()["version"],
            "commandId": "create-1",
            "parameters": {"subject": "east parapet"},
            "policy": {"policyId": "workflow-demo", "policyVersion": "demo-1",
                       "goal": "workflow.completed"}})
        self.assertEqual(status, 201, body)

    def test_the_submitted_plan_is_used(self):
        self.publish()
        plan = {"steps": ["n01", "n02"], "openRequirements": ["R01"],
                "replanWhen": ["a reviewer rejects"]}
        self.create(plan=plan)
        status, body = self.call("GET", API_PREFIX + "/instances/W-1")
        self.assertEqual(status, 200, body)
        # The plan is part of the stored work, not silently replaced.
        work = self.runtime.get_work("W-1")
        self.assertEqual(work["plan"]["steps"], plan["steps"])

    def test_a_malformed_plan_is_refused(self):
        self.publish()
        status, body = self.call("POST", API_PREFIX + "/instances", {
            "workId": "W-1", "document": {"id": "H-001", "subject": "east"},
            "templateId": scenario_template()["id"],
            "templateVersion": scenario_template()["version"],
            "commandId": "create-1",
            "plan": {"steps": "n01"}})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "PLAN_INVALID")

    def test_the_trusted_snapshot_carries_the_session_and_the_participants(self):
        self.publish()
        self.create(participants={"n04": "member-123", "n05": "member-456"})
        status, body = self.call("GET", API_PREFIX + "/instances/W-1")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["workflow"]["sessionId"], "sess-1")
        self.assertEqual(body["workflow"]["participants"],
                         {"n04": "member-123", "n05": "member-456"})
        self.assertEqual(body["workflow"]["parameters"], {"subject": "east parapet"})

    def test_the_snapshot_may_name_the_instance_it_creates(self):
        self.publish()
        status, body = self.call("POST", API_PREFIX + "/instances", {
            "workId": "W-1", "document": {"id": "H-001", "subject": "east"},
            "templateId": scenario_template()["id"],
            "templateVersion": scenario_template()["version"],
            "commandId": "create-1",
            "instance": {"id": "W-1", "workspaceId": "ws-1", "taskId": "task-1",
                         "ownerUserId": "user-1", "sessionId": "sess-1",
                         "parameters": {"subject": "east parapet"},
                         "participants": {"n04": "member-123"}}})
        self.assertEqual(status, 201, body)
        status, body = self.call("POST", API_PREFIX + "/instances", {
            "workId": "W-2", "document": {"id": "H-001", "subject": "east"},
            "templateId": scenario_template()["id"],
            "templateVersion": scenario_template()["version"],
            "commandId": "create-2",
            "instance": {"id": "W-1", "workspaceId": "ws-1", "taskId": "task-1",
                         "ownerUserId": "user-1", "sessionId": "sess-1",
                         "parameters": {"subject": "east parapet"},
                         "participants": {}}})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "INSTANCE_INVALID")

    def test_a_participant_must_name_a_declared_node(self):
        self.publish()
        status, body = self.call("POST", API_PREFIX + "/instances", {
            "workId": "W-1", "document": {"id": "H-001", "subject": "east"},
            "templateId": scenario_template()["id"],
            "templateVersion": scenario_template()["version"],
            "commandId": "create-1",
            "instance": {"workspaceId": "ws-1", "taskId": "task-1",
                         "ownerUserId": "user-1", "sessionId": "sess-1",
                         "parameters": {"subject": "east parapet"},
                         "participants": {"n99": "member-123"}}})
        self.assertEqual(status, 422)
        self.assertEqual(body["error"]["code"], "WORKFLOW_PARTICIPANT_UNKNOWN")


class DecisionContractTests(HttpBridgeTestCase):
    def test_a_decision_without_an_expected_version_is_refused(self):
        self.publish()
        self.create()
        status, body = self.call("POST", API_PREFIX + "/instances/W-1/decisions", {
            "node": "n04", "attempt": 1, "decision": "approved", "digest": "0" * 64,
            "revision": 1, "actorId": "reviewer-a",
            "items": [{"check": "N04-2", "verdict": "passed", "reason": "r",
                       "evidence": ["x"]}],
            "commandId": "d-1"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "EXPECTED_VERSION_REQUIRED")

    def test_a_stale_expected_version_is_refused(self):
        self.publish()
        self.create()
        self.drive_agents()
        subject = self.node("W-1", "n04")["subject"]
        status, body = self.decide("n04", 1, "approved", subject["digest"],
                                   subject["revision"], "reviewer-a",
                                   expected_version=999)
        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "STATE_VERSION_CONFLICT")

    def test_a_malformed_criterion_report_is_refused(self):
        self.publish()
        self.create()
        self.drive_agents()
        subject = self.node("W-1", "n04")["subject"]
        status, body = self.decide("n04", 1, "approved", subject["digest"],
                                   subject["revision"], "reviewer-a",
                                   items=[{"check": "N04-2", "verdict": "passed",
                                           "reason": "", "evidence": []}])
        self.assertEqual(status, 422)
        self.assertEqual(body["error"]["code"], "WORKFLOW_CHECK_REPORT_INVALID")

    def test_an_approval_with_a_failing_criterion_does_not_complete_the_node(self):
        self.publish()
        self.create()
        self.drive_agents()
        subject = self.node("W-1", "n04")["subject"]
        status, body = self.decide("n04", 1, "approved", subject["digest"],
                                   subject["revision"], "reviewer-a",
                                   items=[{"check": "N04-2", "verdict": "failed",
                                           "reason": "the guard is not covered",
                                           "evidence": ["proposal#measure-2"]}])
        self.assertEqual(status, 200, body)
        self.assertEqual(self.node("W-1", "n04")["state"], "running")
        self.assertEqual(self.node("W-1", "n04")["checkResults"][0]["verdict"],
                         "failed")


class InstanceTests(HttpBridgeTestCase):
    def test_an_instance_is_created_and_read_back(self):
        self.publish()
        body = self.create()
        self.assertEqual(body["workId"], "W-1")
        self.assertEqual(body["workflowStatus"], "active")
        self.assertEqual(body["currentNode"], "n01")
        self.assertEqual(len(body["nodes"]), 10)
        self.assertEqual(body["allowedActions"][0]["action"], "submit_node_result")
        self.assertEqual(body["allowedActions"][0]["node"], "n01")

    def test_the_read_model_is_bounded(self):
        self.publish()
        self.create()
        body = self.view()
        self.assertLessEqual(len(body["nodes"]), 64)
        self.assertLessEqual(len(body["intents"]), 32)
        for entry in body["nodes"]:
            self.assertLessEqual(len(entry["findings"]), 16)
            self.assertLessEqual(len(entry["blockers"]), 16)
            self.assertLessEqual(len(entry["checkResults"]), 16)
        for check in body["checks"]:
            self.assertIn("checkId", check)
            self.assertIn("node", check)
            self.assertTrue(check["criterion"])

    def test_an_object_revision_is_readable(self):
        self.publish()
        self.create()
        self.submit("n01", 1, "intake",
                    {"records": [{"id": "R-1", "source": "s"}], "standard": "STD"})
        status, body = self.call("GET", API_PREFIX + "/instances/W-1/objects/intake"
                                  "/revisions/1")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["name"], "intake")
        self.assertEqual(body["revision"], 1)
        self.assertEqual(body["object"], {"records": [{"id": "R-1", "source": "s"}],
                                          "standard": "STD"})
        self.assertTrue(body["digest"])
        status, body = self.call("GET", API_PREFIX + "/instances/W-1/objects/intake"
                                  "/revisions/9")
        self.assertEqual(status, 404)

    def test_a_result_is_accepted_and_a_bad_one_is_refused(self):
        self.publish()
        self.create()
        status, body = self.submit("n01", 1, "intake",
                                   {"records": [{"id": "R-1", "source": "s"}],
                                    "standard": "STD"})
        self.assertEqual(status, 200, body)
        status, body = self.submit("n02", 1, "analysis", {"findings": []})
        self.assertEqual(status, 422)
        self.assertEqual(body["error"]["code"], "WORKFLOW_RESULT_INVALID")
        self.assertTrue(body["error"]["findings"])

    def test_a_decision_must_cover_the_current_version(self):
        self.publish()
        self.create()
        self.drive_agents()
        status, body = self.decide("n04", 1, "approved", "0" * 64, 1, "reviewer-a")
        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "WORKFLOW_DECISION_STALE")
        subject = self.node("W-1", "n04")["subject"]
        status, body = self.decide("n04", 1, "approved", subject["digest"],
                                   subject["revision"], "reviewer-a")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["decision"]["outcome"], "approved")
        self.assertEqual(body["currentNode"], "n05")

    def test_a_request_for_more_material_keeps_the_node_waiting(self):
        self.publish()
        self.create()
        self.drive_agents()
        subject = self.node("W-1", "n04")["subject"]
        status, body = self.decide("n04", 1, "request_material", subject["digest"],
                                   subject["revision"], "reviewer-a")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["currentNode"], "n04")
        self.assertEqual(self.node("W-1", "n04")["state"], "running")

    def test_the_attempt_history_of_a_node_is_readable(self):
        self.publish()
        self.create()
        status, body = self.call("GET", API_PREFIX + "/instances/W-1/nodes/n01/attempts")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["node"], "n01")
        self.assertTrue(body["attempts"])

    def test_durable_intents_are_listed_and_acknowledged(self):
        self.publish()
        self.create()
        status, body = self.call("GET", API_PREFIX + "/instances/W-1/intents")
        self.assertEqual(status, 200)
        self.assertTrue(body["intents"])
        intent = body["intents"][0]
        self.assertTrue(intent["id"].endswith(":agent_task"))
        self.assertEqual(intent["sessionId"], "sess-1")
        status, body = self.call("POST", API_PREFIX + "/intents/" + intent["id"]
                                  + "/ack", {"actor": "coordinator"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["status"], "acknowledged")

    def test_the_global_intent_listing_is_scoped_by_work(self):
        self.publish()
        self.create("W-1")
        self.create("W-2")
        status, body = self.call("GET", API_PREFIX + "/intents?workIds=W-2")
        self.assertEqual(status, 200)
        self.assertTrue(body["intents"])
        for intent in body["intents"]:
            self.assertTrue(intent["id"].startswith("wf:W-2:"))

    def test_the_log_never_carries_a_credential(self):
        self.publish()
        self.call("POST", API_PREFIX + "/instances", {
            "workId": "W-2",
            "document": {"id": "H-002", "subject": "north"},
            "templateId": scenario_template()["id"],
            "templateVersion": scenario_template()["version"],
            "parameters": {"subject": "north"},
            "commandId": "create-2",
            "authorization": "super-secret-token",
        })
        for line in self.server.log:
            self.assertNotIn("super-secret-token", line)

class ProgressTests(HttpBridgeTestCase):
    def test_progress_continues_without_a_client_poll(self):
        self.publish()
        self.create()
        for node, name, result in (
                ("n01", "intake", {"records": [{"id": "R-1", "source": "s"}],
                                   "standard": "STD"}),
                ("n02", "analysis", {"findings": [{"issueId": "H-001", "clause": "C-1",
                                                   "finding": "gap"}]}),
                ("n03", "proposal", {"measures": [{"issueId": "H-001", "measureId": "M-1",
                                                    "measure": "guard"}]})):
            attempt = self.node("W-1", node)["attempt"]
            status, body = self.submit(node, attempt, name, result)
            self.assertEqual(status, 200, body)
        subject = self.node("W-1", "n04")["subject"]
        status, body = self.decide("n04", 1, "approved", subject["digest"],
                                   subject["revision"], "reviewer-a")
        self.assertEqual(status, 200, body)
        status, body = self.decide("n05", 1, "approved", subject["digest"],
                                   subject["revision"], "reviewer-b",
                                   items=[{"check": "N05-3", "verdict": "passed",
                                           "reason": "the arrangement is authorized",
                                           "evidence": ["proposal#revision-1"]}])
        self.assertEqual(status, 200, body)
        # The ticker dispatches the authorized action on its own; the client
        # never asks for it.
        self._wait_for(lambda: self.adapter.effect_count() == 1)
        self.assertEqual(self.adapter.effect_count(), 1)
        self._wait_for(lambda: self.node("W-1", "n06")["state"] == "completed")
        self.assertEqual(self.node("W-1", "n06")["state"], "completed")

    def _wait_for(self, predicate, timeout=10.0):
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        return False


if __name__ == "__main__":
    unittest.main()


class ReceiptAndTerminalTests(HttpBridgeTestCase):
    def test_a_stored_command_receipt_is_readable_without_resending(self):
        self.publish()
        created = self.create(command_id="create-1")
        self.assertEqual(created["bindingCommandId"], "create-1:bind")
        status, body = self.call("GET", API_PREFIX + "/commands/create-1:bind"
                                  "?workId=W-1&actor=coordinator")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["receipt"]["decision"], "accepted")
        self.assertEqual(body["workId"], "W-1")
        # The lookup is read-only: it does not create anything.
        before = self.runtime.get_work("W-1")["state_version"]
        self.call("GET", API_PREFIX + "/commands/create-1:bind?workId=W-1&actor=coordinator")
        self.assertEqual(self.runtime.get_work("W-1")["state_version"], before)

    def test_a_receipt_of_another_work_or_actor_is_not_found(self):
        self.publish()
        self.create(command_id="create-1")
        status, body = self.call("GET", API_PREFIX + "/commands/create-1:bind"
                                  "?workId=W-2&actor=coordinator")
        self.assertEqual(status, 404)
        status, body = self.call("GET", API_PREFIX + "/commands/create-1:bind"
                                  "?workId=W-1&actor=someone-else")
        self.assertEqual(status, 404)

    def test_a_receipt_lookup_needs_its_scope(self):
        status, body = self.call("GET", API_PREFIX + "/commands/create-1")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "COMMAND_SCOPE_REQUIRED")

    def test_a_pinned_template_digest_is_checked(self):
        self.publish()
        published = self.engine.list_templates()[0]
        status, body = self.call("POST", API_PREFIX + "/instances", {
            "workId": "W-1", "document": {"id": "H-001", "subject": "east"},
            "templateId": scenario_template()["id"],
            "templateVersion": scenario_template()["version"],
            "templateDigest": published["digest"],
            "parameters": {"subject": "east parapet"},
            "commandId": "create-1"})
        self.assertEqual(status, 201, body)
        status, body = self.call("POST", API_PREFIX + "/instances", {
            "workId": "W-2", "document": {"id": "H-001", "subject": "east"},
            "templateId": scenario_template()["id"],
            "templateVersion": scenario_template()["version"],
            "templateDigest": "0" * 64,
            "parameters": {"subject": "east parapet"},
            "commandId": "create-2"})
        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "WORKFLOW_TEMPLATE_MISMATCH")

    def test_a_finished_work_reports_its_terminal_node_and_outcome(self):
        self.publish()
        self.create()
        self.drive_agents()
        subject = self.node("W-1", "n04")["subject"]
        status, body = self.decide("n04", 1, "approved", subject["digest"],
                                   subject["revision"], "reviewer-a")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["workflowStatus"], "active")
        self.assertIsNone(body["terminalNode"])


class ExactMaterialTests(HttpBridgeTestCase):
    def test_the_exact_read_returns_the_material_the_digest_covers(self):
        self.publish()
        self.create()
        self.submit("n01", 1, "intake",
                    {"records": [{"id": "R-1", "source": "s"}], "standard": "STD"})
        status, body = self.call("GET", API_PREFIX + "/instances/W-1/objects/intake"
                                  "/revisions/1")
        self.assertEqual(status, 200, body)
        self.assertFalse(body["redacted"])
        self.assertEqual(body["digest"], body["originalDigest"])
        # The digest covers exactly what was returned.
        from work_runtime.policy import digest as content_digest
        self.assertEqual(body["digest"], content_digest(body["object"]))

    def test_a_material_with_a_credential_is_never_silently_altered(self):
        self.publish()
        self.create()
        self.submit("n01", 1, "intake",
                    {"records": [{"id": "R-1", "source": "s"}], "standard": "STD"})
        status, body = self.call("POST", API_PREFIX + "/instances/W-1/objects", {
            "name": "intake",
            "object": {"records": [{"id": "R-1", "source": "s"}], "standard": "STD",
                       "access_token": "super-secret"},
            "actor": "coordinator",
            "commandId": "object-1",
            "expectedVersion": self.view("W-1")["stateVersion"]})
        self.assertEqual(status, 200, body)
        status, body = self.call("GET", API_PREFIX + "/instances/W-1/objects/intake"
                                  "/revisions/2")
        # The exact read refuses rather than returning something the digest
        # does not cover.
        self.assertEqual(status, 422)
        self.assertEqual(body["error"]["code"], "WORKFLOW_OBJECT_CONTAINS_SECRETS")
        # The declared alternative says exactly what it returned.
        status, body = self.call("GET", API_PREFIX + "/instances/W-1/objects/intake"
                                  "/revisions/2?redact=true")
        self.assertEqual(status, 200, body)
        self.assertTrue(body["redacted"])
        self.assertNotEqual(body["digest"], body["originalDigest"])
        self.assertNotIn("access_token", body["object"])
