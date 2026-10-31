"""Binding a published definition is the work owner's own act.

A binding is the owner's authorization of the definition's action nodes: the
engine proposes those operations in the owner's name, the binding cannot be
undone, and the binder's participants map becomes the assignment snapshot of
the decision nodes. Only the work's manager may therefore bind.

The engine already said so on the replay path. This file pins the same
predicate on the fresh path:

* a principal that is not the owner is refused `AUTHORITY_DENIED`, and the
  refusal leaves the work exactly as it was — no binding, no state-version
  bump, no `WorkflowBound` event;
* the owner binds exactly as before;
* the replay rule and the fresh rule are one predicate, so the two paths
  cannot drift apart again;
* after a `transfer_owner`, the new owner binds and the previous owner does
  not;
* the HTTP bridge refuses the non-owner and still accepts the owner.
"""

import http.client
import json
import os
import tempfile
import unittest
import uuid

from work_runtime.workflow_server import API_PREFIX, serve

try:
    from workflow_support import (POLICY_GOAL, POLICY_ID, POLICY_VERSION,
                                  RecordingAdapter, build, demo_grants,
                                  document, scenario_template, send,
                                  version_of)
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import (POLICY_GOAL, POLICY_ID, POLICY_VERSION,
                                        RecordingAdapter, build, demo_grants,
                                        document, scenario_template, send,
                                        version_of)

OWNER = "coordinator"
# The shipped executor: a member of the grants that holds no management
# capability at all, and is certainly not the owner of somebody else's work.
EXECUTOR = "agent-executor"
# A second principal that holds `work.manage`, so that ownership can be
# transferred to it and the rule can be checked on both sides of the transfer.
DEPUTY = "deputy"


def grants_with_deputy():
    """The shipped grants plus one more manager.

    The evidence sources the published definition names must stay
    configured, so the extra principal is added to the shipped map rather
    than replacing it.
    """
    grants = demo_grants()
    grants[DEPUTY] = {"work.manage"}
    return grants


class BindAuthorityTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-bind-authority-")
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.runtime, self.engine = build(self.path)
        self.work_id = "W-1"
        self.engine.publish_template(OWNER, scenario_template())
        self.establish_work()

    def establish_work(self):
        """A work with a live contract and no definition bound yet."""
        send(self.runtime, OWNER, self.work_id, "create_work",
             {"document": document()})
        send(self.runtime, OWNER, self.work_id, "bind_contract",
             {"policy_id": POLICY_ID, "policy_version": POLICY_VERSION,
              "goal": POLICY_GOAL})
        send(self.runtime, OWNER, self.work_id, "revise_plan",
             {"steps": ["n01"], "open_requirements": ["R01"],
              "replan_when": ["review rejects"]})

    def payload(self):
        template = scenario_template()
        return {"template_id": template["id"],
                "template_version": template["version"],
                "parameters": {"subject": "east parapet"}}

    def bind(self, actor, work_id=None):
        """The binding command, issued the way a host issues it."""
        work_id = work_id or self.work_id
        return self.engine.command(actor, uuid.uuid4().hex, work_id,
                                   "bind_workflow", self.payload(),
                                   version_of(self.runtime, work_id))

    def work(self):
        return self.runtime.get_work(self.work_id)


class NonOwnerBindingTests(BindAuthorityTestCase):
    def test_a_non_owner_cannot_bind_a_published_definition(self):
        # The executor holds no management capability and is not the owner:
        # binding somebody else's work is not its act.
        receipt = self.bind(EXECUTOR)
        self.assertEqual(receipt["decision"], "rejected", receipt)
        self.assertEqual(receipt["code"], "AUTHORITY_DENIED", receipt)

    def test_a_refused_binding_leaves_the_work_unchanged(self):
        # A refusal is not a partial binding: the work keeps its state, its
        # version and its history.
        before = version_of(self.runtime, self.work_id)
        receipt = self.bind(EXECUTOR)
        self.assertEqual(receipt["decision"], "rejected", receipt)
        self.assertEqual(receipt["code"], "AUTHORITY_DENIED", receipt)
        work = self.work()
        self.assertNotIn("workflow", work)
        self.assertIsNone(work.get("workflow_status"))
        self.assertEqual(work["state_version"], before)
        bound = [event for event in self.runtime.events(self.work_id)
                 if event["type"] == "WorkflowBound"]
        self.assertEqual(bound, [])

    def test_the_owner_binds_the_definition(self):
        receipt = self.bind(OWNER)
        self.assertEqual(receipt["decision"], "accepted", receipt)
        template = scenario_template()
        work = self.work()
        self.assertEqual(work["workflow"]["template_id"], template["id"])
        self.assertEqual(work["workflow"]["template_version"], template["version"])
        self.assertEqual(work["workflow_status"], "active")

    def test_the_replay_rule_is_the_fresh_rule(self):
        # The stored receipt of a binding is replayed only while the owner
        # still holds the work; the fresh path asks the very same question.
        work = self.work()
        self.assertFalse(self.engine.replay_allowed(EXECUTOR, work,
                                                    "bind_workflow", self.payload()))
        self.assertTrue(self.engine.replay_allowed(OWNER, work,
                                                   "bind_workflow", self.payload()))


class TransferredOwnershipBindingTests(BindAuthorityTestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-bind-authority-transfer-")
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.runtime, self.engine = build(self.path, grants=grants_with_deputy())
        self.work_id = "W-1"
        self.engine.publish_template(OWNER, scenario_template())
        self.establish_work()

    def test_the_new_owner_binds_and_the_previous_owner_may_not(self):
        receipt = send(self.runtime, OWNER, self.work_id, "transfer_owner",
                       {"owner": DEPUTY, "reason": "the deputy takes over"})
        self.assertEqual(receipt["decision"], "accepted", receipt)
        # The previous owner is now a member of the grants that is not the
        # owner of this work: the binding is no longer its act.
        refused = self.bind(OWNER)
        self.assertEqual(refused["decision"], "rejected", refused)
        self.assertEqual(refused["code"], "AUTHORITY_DENIED", refused)
        # The new owner holds `work.manage` and binds as before.
        accepted = self.bind(DEPUTY)
        self.assertEqual(accepted["decision"], "accepted", accepted)
        self.assertEqual(self.work()["workflow"]["template_id"],
                         scenario_template()["id"])


class HttpBindAuthorityTestCase(unittest.TestCase):
    """The bridge over a real loopback socket."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-bind-authority-http-")
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.runtime, self.engine = build(self.path, grants=grants_with_deputy())
        self.adapter = RecordingAdapter(os.path.join(self.folder, "effects.sqlite"))
        self.server, self.ticker, self.lock = serve(
            self.runtime, self.engine, self.adapter, host="127.0.0.1", port=0,
            interval_s=0.05)
        self.host, self.port = (self.server.server_address[0],
                                 self.server.server_address[1])

    def tearDown(self):
        self.ticker.stop()
        self.server.shutdown()
        self.server.server_close()
        if self.lock is not None:
            self.lock.release()

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

    def test_the_bridge_binds_for_the_owner_and_refuses_a_non_owner(self):
        template = scenario_template()
        status, body = self.call("POST", API_PREFIX + "/templates",
                                 {"spec": template})
        self.assertEqual(status, 201, body)
        request = {"workId": "W-1",
                   "document": {"id": "H-001", "subject": "east parapet"},
                   "templateId": template["id"],
                   "templateVersion": template["version"],
                   "parameters": {"subject": "east parapet"},
                   "commandId": "create-1"}
        # The owner creates the instance over the socket: the definition is
        # bound and the binding is the owner's.
        status, body = self.call("POST", API_PREFIX + "/instances", request)
        self.assertEqual(status, 201, body)
        self.assertEqual(body["workflow"]["templateId"], template["id"])
        self.assertEqual(body["workflow"]["templateVersion"], template["version"])
        # The ownership moves to another principal. The bridge has no route
        # for the transfer, so the runtime carries it out.
        receipt = self.runtime.command(OWNER, "transfer-1", "W-1",
                                       "transfer_owner",
                                       {"owner": DEPUTY,
                                        "reason": "the deputy takes over"},
                                       version_of(self.runtime, "W-1"))
        self.assertEqual(receipt["decision"], "accepted", receipt)
        before = version_of(self.runtime, "W-1")
        # The previous owner still holds `work.manage`, but it is not the
        # owner of this work any more: the bridge refuses it and leaves the
        # owner's work exactly as it was. The bridge binds a definition
        # inside the creation flow, and every stage of that flow asks the
        # same owner question, so the refusal comes from the first
        # owner-gated stage rather than from the binding itself.
        status, body = self.call("POST", API_PREFIX + "/instances", request)
        self.assertEqual(status, 403, body)
        self.assertEqual(body["error"]["code"], "AUTHORITY_DENIED", body)
        self.assertEqual(version_of(self.runtime, "W-1"), before)
        self.assertEqual(self.runtime.get_work("W-1")["workflow"]["template_id"],
                         template["id"])
