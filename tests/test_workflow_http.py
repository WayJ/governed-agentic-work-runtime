"""The generic HTTP bridge over the mixed-node workflow runtime.

The bridge is exercised over a real loopback socket: the tests assert the
wire shapes a platform client depends on, the bounded read model, the durable
intent ids and the promise that progress needs no client polling.
"""

import http.client
import json
import os
import tempfile
import unittest

from work_runtime.workflow_server import (API_PREFIX, WorkflowService, serve)

try:
    from workflow_support import (RecordingAdapter, build, demo_grants,
                                  scenario_template, send, version_of)
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import (RecordingAdapter, build, demo_grants,
                                        scenario_template, send, version_of)


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

    def publish(self):
        status, body = self.call("POST", API_PREFIX + "/templates",
                                  {"spec": scenario_template()})
        self.assertEqual(status, 201, body)
        return body

    def create(self, work_id="W-1", session_id="sess-1"):
        status, body = self.call("POST", API_PREFIX + "/instances", {
            "workId": work_id,
            "document": {"id": "H-001", "subject": "east parapet"},
            "templateId": scenario_template()["id"],
            "templateVersion": scenario_template()["version"],
            "parameters": {"subject": "east parapet"},
            "sessionId": session_id,
        })
        self.assertEqual(status, 201, body)
        return body

    def submit(self, node, attempt, name, result, actor="agent-executor"):
        return self.call("POST", API_PREFIX + "/instances/W-1/results", {
            "node": node, "attempt": attempt, "object": name,
            "result": result, "actor": actor})

    def subject(self, work_id="W-1", node="n03"):
        status, body = self.call("GET", API_PREFIX + "/instances/" + work_id)
        self.assertEqual(status, 200, body)
        for entry in body["nodes"]:
            if entry["node"] == node:
                return entry["outputs"][0] if entry["outputs"] else None
        return None


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

    def test_a_malformed_body_is_rejected(self):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=10)
        try:
            connection.request("POST", API_PREFIX + "/templates", b"not json",
                               {"Content-Type": "application/json"})
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
        finally:
            connection.close()


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
        status, body = self.call("GET", API_PREFIX + "/instances/W-1")
        self.assertEqual(status, 200)
        self.assertLessEqual(len(body["nodes"]), 64)
        self.assertLessEqual(len(body["intents"]), 32)
        for entry in body["nodes"]:
            self.assertLessEqual(len(entry["findings"]), 16)
            self.assertLessEqual(len(entry["blockers"]), 16)
        for check in body["checks"]:
            self.assertIn("checkId", check)
            self.assertIn("node", check)

    def test_a_result_is_accepted_and_a_bad_one_is_refused(self):
        self.publish()
        self.create()
        status, body = self.submit("n01", 1, "intake",
                                   {"records": [{"id": "R-1", "source": "s"}],
                                    "standard": "STD"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["result"]["output"]["name"], "intake")
        status, body = self.submit("n02", 1, "analysis",
                                   {"findings": []})
        self.assertEqual(status, 422)
        self.assertEqual(body["error"]["code"], "WORKFLOW_RESULT_INVALID")
        self.assertTrue(body["error"]["findings"])

    def test_a_decision_must_cover_the_current_version(self):
        self.publish()
        self.create()
        for node, name, result in (("n01", "intake", None), ("n02", "analysis", None),
                                   ("n03", "proposal", None)):
            attempt = self._attempt(node)
            status, body = self.submit(node, attempt, name, {
                "intake": {"records": [{"id": "R-1", "source": "s"}], "standard": "STD"},
                "analysis": {"findings": [{"issueId": "H-001", "clause": "C-1",
                                           "finding": "gap"}]},
                "proposal": {"measures": [{"issueId": "H-001", "measureId": "M-1",
                                           "measure": "guard"}]},
            }[name])
            self.assertEqual(status, 200, body)
        status, body = self.call("POST", API_PREFIX + "/instances/W-1/decisions", {
            "node": "n04", "decision": "approved", "digest": "0" * 64, "revision": 1})
        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "WORKFLOW_DECISION_STALE")
        subject = self.subject()
        status, body = self.call("POST", API_PREFIX + "/instances/W-1/decisions", {
            "node": "n04", "decision": "approved", "digest": subject["digest"],
            "revision": subject["revision"]})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["outcome"], "approved")
        self.assertEqual(body["currentNode"], "n05")

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

    def test_the_log_never_carries_a_credential(self):
        self.publish()
        self.call("POST", API_PREFIX + "/instances", {
            "workId": "W-2",
            "document": {"id": "H-002", "subject": "north"},
            "templateId": scenario_template()["id"],
            "templateVersion": scenario_template()["version"],
            "parameters": {"subject": "north"},
            "authorization": "super-secret-token",
        })
        for line in self.server.log:
            self.assertNotIn("super-secret-token", line)
        self.assertNotIn("super-secret-token", json.dumps(self.server.service.__dict__,
                                                          default=str))

    def _attempt(self, node):
        status, body = self.call("GET", API_PREFIX + "/instances/W-1")
        self.assertEqual(status, 200, body)
        for entry in body["nodes"]:
            if entry["node"] == node:
                return entry["attempt"]
        return 0


class ProgressTests(HttpBridgeTestCase):
    def test_progress_continues_without_a_client_poll(self):
        self.publish()
        self.create()
        for node, name in (("n01", "intake"), ("n02", "analysis"), ("n03", "proposal")):
            attempt = self._attempt(node)
            status, body = self.submit(node, attempt, name, {
                "intake": {"records": [{"id": "R-1", "source": "s"}], "standard": "STD"},
                "analysis": {"findings": [{"issueId": "H-001", "clause": "C-1",
                                           "finding": "gap"}]},
                "proposal": {"measures": [{"issueId": "H-001", "measureId": "M-1",
                                           "measure": "guard"}]},
            }[name])
            self.assertEqual(status, 200, body)
        subject = self.subject()
        status, body = self.call("POST", API_PREFIX + "/instances/W-1/decisions", {
            "node": "n04", "decision": "approved", "digest": subject["digest"],
            "revision": subject["revision"]})
        self.assertEqual(status, 200, body)
        status, body = self.call("POST", API_PREFIX + "/instances/W-1/decisions", {
            "node": "n05", "decision": "approved", "digest": subject["digest"],
            "revision": subject["revision"]})
        self.assertEqual(status, 200, body)
        # The ticker dispatches the authorized action on its own; the client
        # never asks for it.
        self._wait_for(lambda: self.adapter.effect_count() == 1)
        self.assertEqual(self.adapter.effect_count(), 1)
        self._wait_for(lambda: self._attempt("n07") >= 1)
        status, body = self.call("GET", API_PREFIX + "/instances/W-1")
        node = [entry for entry in body["nodes"] if entry["node"] == "n06"][0]
        self.assertEqual(node["state"], "completed")

    def _wait_for(self, predicate, timeout=10.0):
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        return False

    def _attempt(self, node):
        status, body = self.call("GET", API_PREFIX + "/instances/W-1")
        self.assertEqual(status, 200, body)
        for entry in body["nodes"]:
            if entry["node"] == node:
                return entry["attempt"]
        return 0


if __name__ == "__main__":
    unittest.main()
