"""The native automatic-action context of a workflow action.

A platform adapter receives only the native business key. The engine's
action context answers what that key really is: the operation, the node
instance that proposed it, the pinned definition and the bound subject —
read from one consistent snapshot, without any schema access and without
changing the adapter's execution ABI.

Every test drives the real engine: the operations are created by the real
proposal path, the effects by the real adapter and the routing by the real
engine. Only the corrupt-linkage tests write rows by hand, because a
corrupt store is exactly what they are about.
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid

from work_runtime.policy import canonical, digest
from work_runtime.runtime import Runtime
from work_runtime.workflow import WorkflowEngine
from work_runtime.workflow_demo import DemoBusinessSystem

try:
    from workflow_support import (POLICY_GOAL, POLICY_ID, POLICY_VERSION,
                                  DemoPolicy, decide, demo_grants,
                                  demo_validators, document, scenario_template,
                                  send, submit_valid, version_of)
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import (POLICY_GOAL, POLICY_ID, POLICY_VERSION,
                                        DemoPolicy, decide, demo_grants,
                                        demo_validators, document,
                                        scenario_template, send, submit_valid,
                                        version_of)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PLAN = {"steps": ["n01", "n02", "n03", "n04", "n05", "n06", "n07", "n08",
                  "n09", "n10"],
        "open_requirements": ["R01"],
        "replan_when": ["review rejects"]}


class ContextReadingAdapter(DemoBusinessSystem):
    """The stand-in business system, with the engine's context read inside it.

    The adapter is a platform adapter: it only ever sees the native business
    key. It asks the engine what that key means and keeps the answer, so
    the test can read the context exactly as the adapter saw it.
    """

    def __init__(self, path, engine):
        super().__init__(path)
        self.engine = engine
        self.contexts = []

    def execute(self, key, document, content_digest, *, action=None,
                compensates=None):
        self.contexts.append((key, self.engine.suggest_action_context(key)))
        return super().execute(key, document, content_digest, action=action,
                               compensates=compensates)

    def lookup(self, key):
        self.contexts.append((key, self.engine.suggest_action_context(key)))
        return super().lookup(key)


class DemoFamilyTestCase(unittest.TestCase):
    """The demonstration family: a real ten-node workflow."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-action-context-")
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.adapter_path = os.path.join(self.folder, "effects.sqlite")
        self.runtime = Runtime(self.path, DemoPolicy(), demo_grants())
        self.engine = WorkflowEngine(self.runtime, demo_validators(),
                                     runner="workflow-runner")
        self.adapter = ContextReadingAdapter(self.adapter_path, self.engine)
        self.template = scenario_template()
        receipt = self.engine.publish_template("coordinator", self.template)
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.work_id = "W-1"

    # -- helpers ---------------------------------------------------------

    def rows(self, table, where="1=1", arguments=()):
        db = sqlite3.connect(self.path)
        try:
            return db.execute("SELECT * FROM " + table + " WHERE " + where,
                              arguments).fetchall()
        finally:
            db.close()

    def execute_on_db(self, statement, arguments=()):
        db = sqlite3.connect(self.path)
        try:
            db.execute(statement, arguments)
            db.commit()
        finally:
            db.close()

    def operation(self, work_id=None):
        rows = self.rows("operations", "work_id=?", (work_id or self.work_id,))
        self.assertTrue(rows, "no operation was created")
        return json.loads(rows[0][3])

    def node_instance(self, node, attempt=None):
        if attempt is None:
            rows = self.rows("workflow_nodes", "work_id=? AND node=?",
                             (self.work_id, node))
            rows = sorted(rows, key=lambda row: row[2])
        else:
            rows = self.rows("workflow_nodes", "work_id=? AND node=? AND attempt=?",
                             (self.work_id, node, attempt))
        self.assertTrue(rows, "no node instance for " + node)
        return json.loads(rows[-1][4])

    def instantiate(self, session_id="session-original"):
        send(self.runtime, "coordinator", self.work_id, "create_work",
             {"document": document()})
        send(self.runtime, "coordinator", self.work_id, "bind_contract",
             {"policy_id": POLICY_ID, "policy_version": POLICY_VERSION,
              "goal": POLICY_GOAL})
        send(self.runtime, "coordinator", self.work_id, "revise_plan", PLAN)
        payload = {"template_id": self.template["id"],
                   "template_version": self.template["version"],
                   "parameters": {"subject": "east parapet"},
                   "session_id": session_id}
        receipt = self.engine.command("coordinator", uuid.uuid4().hex, self.work_id,
                                      "bind_workflow", payload,
                                      version_of(self.runtime, self.work_id))
        self.assertEqual(receipt["decision"], "accepted", receipt)
        return receipt

    def drive_to_dispatch(self):
        """Drive the real workflow until the automatic action is proposed."""
        self.instantiate()
        for node, name in (("n01", "intake"), ("n02", "analysis"),
                           ("n03", "proposal")):
            receipt = submit_valid(self.engine, self.runtime, self.work_id,
                                    node, name)
            self.assertEqual(receipt["decision"], "accepted", receipt)
        reference = self.proposal_reference()
        decide(self.runtime, self.engine, self.work_id, "safety_review",
               "reviewer-a", "approved", reference["digest"], reference["revision"])
        decide(self.runtime, self.engine, self.work_id, "project_approval",
               "reviewer-b", "approved", reference["digest"], reference["revision"])

    def proposal_reference(self):
        rows = self.rows("workflow_objects", "work_id=? AND name=?",
                         (self.work_id, "proposal"))
        self.assertTrue(rows)
        # workflow_objects is (work_id, name, revision, digest, body).
        revision = rows[0][2]
        content_digest = rows[0][3]
        return {"name": rows[0][1], "revision": revision, "digest": content_digest}


class ActionContextReadTests(DemoFamilyTestCase):

    def test_the_context_is_readable_inside_the_adapter_execute(self):
        """The native context is available to the adapter that executes."""
        self.drive_to_dispatch()
        operation = self.operation()
        self.engine.pump(self.adapter, 1000)
        self.assertEqual(len(self.adapter.contexts), 1)
        key, context = self.adapter.contexts[0]
        self.assertEqual(key, operation["business_key"])
        self.assertTrue(context["present"], context)
        self.assertEqual(context["businessKey"], operation["business_key"])
        stable = context["context"]
        self.assertEqual(stable["businessKey"], operation["business_key"])
        self.assertEqual(stable["operationId"], operation["id"])
        self.assertEqual(stable["workId"], self.work_id)
        self.assertEqual(stable["node"], "n06")
        self.assertEqual(stable["attempt"], 1)
        self.assertEqual(stable["actor"], "coordinator")
        self.assertEqual(stable["capability"], "work.dispatch")
        self.assertEqual(stable["contractRevision"], 1)
        self.assertEqual(stable["planRevision"], 1)
        instance = self.node_instance("n06")
        self.assertEqual(stable["inputDigest"], instance["input_digest"])
        self.assertEqual(stable["template"]["id"], self.template["id"])
        self.assertEqual(stable["template"]["version"], self.template["version"])
        self.assertEqual(stable["template"]["digest"],
                         self.engine.template(self.template["id"],
                                              self.template["version"])["digest"])
        reference = self.proposal_reference()
        self.assertEqual(stable["subject"]["name"], "proposal")
        self.assertEqual(stable["subject"]["revision"], reference["revision"])
        self.assertEqual(stable["subject"]["digest"], reference["digest"])
        self.assertIn("measures", stable["subject"]["body"])
        self.assertEqual(stable["envelope"]["sessionId"], "session-original")
        self.assertEqual(stable["envelope"]["owner"], "coordinator")
        self.assertEqual(stable["envelope"]["runner"], "workflow-runner")
        # While the effect is in flight the node is still running: the
        # mutable part says so, the stable part does not change.
        self.assertEqual(context["current"]["nodeState"], "running")
        self.assertEqual(context["current"]["operationStatus"], "dispatched")
        settled = self.engine.suggest_action_context(operation["business_key"])
        self.assertEqual(settled["context"], stable)
        self.assertEqual(settled["current"]["nodeState"], "completed")
        self.assertEqual(settled["current"]["operationStatus"],
                         "confirmed_succeeded")

    def test_the_context_survives_a_process_reopen_and_is_readable_through_lookup(self):
        """A fresh process reads the same context from the same store."""
        self.drive_to_dispatch()
        self.engine.pump(self.adapter, 1000)
        operation = self.operation()
        script = (
            "import json, sys\n"
            "from work_runtime.runtime import Runtime\n"
            "from work_runtime.workflow import WorkflowEngine\n"
            "from work_runtime.workflow_demo import (WorkflowDemoPolicy,\n"
            "    workflow_demo_grants, workflow_demo_validators)\n"
            "runtime = Runtime(sys.argv[1], WorkflowDemoPolicy(),\n"
            "                   workflow_demo_grants())\n"
            "engine = WorkflowEngine(runtime, workflow_demo_validators())\n"
            "print(json.dumps(engine.suggest_action_context(sys.argv[2])))\n")
        environment = dict(os.environ)
        environment["PYTHONPATH"] = REPO_ROOT + os.pathsep + environment.get(
            "PYTHONPATH", "")
        finished = subprocess.run(
            [sys.executable, "-c", script, self.path, operation["business_key"]],
            cwd=REPO_ROOT, env=environment, capture_output=True, text=True,
            timeout=120)
        self.assertEqual(finished.returncode, 0, finished.stderr)
        context = json.loads(finished.stdout)
        self.assertTrue(context["present"], context)
        self.assertEqual(context["context"]["operationId"], operation["id"])
        self.assertEqual(context["context"]["node"], "n06")
        self.assertEqual(context["context"]["attempt"], 1)
        self.assertEqual(context["context"]["subject"]["digest"],
                         self.proposal_reference()["digest"])

    def test_the_lookup_of_a_closed_effect_reads_the_same_context(self):
        """The adapter's lookup path reads the same native context."""
        self.drive_to_dispatch()
        self.engine.pump(self.adapter, 1000)
        operation = self.operation()
        context = self.adapter.lookup(operation["business_key"])
        self.assertIsNotNone(context)
        key, read = self.adapter.contexts[-1]
        self.assertEqual(key, operation["business_key"])
        self.assertTrue(read["present"], read)
        self.assertEqual(read["context"]["node"], "n06")

    def test_an_unknown_key_is_a_documented_absence(self):
        context = self.engine.suggest_action_context("no-such-business-key")
        self.assertFalse(context["present"])
        self.assertEqual(context["code"], "ACTION_CONTEXT_ABSENT")
        self.assertEqual(context["businessKey"], "no-such-business-key")
        self.assertNotIn("context", context)

    def test_a_malformed_key_is_refused(self):
        for value in ("", None, 7):
            with self.assertRaises(Exception):
                self.engine.suggest_action_context(value)

    def test_a_manual_operation_is_refused(self):
        """An operation no workflow node proposed is not an action context."""
        work_id = "W-manual"
        send(self.runtime, "coordinator", work_id, "create_work",
             {"document": document("H-002")})
        send(self.runtime, "coordinator", work_id, "bind_contract",
             {"policy_id": POLICY_ID, "policy_version": POLICY_VERSION,
              "goal": POLICY_GOAL})
        send(self.runtime, "coordinator", work_id, "revise_plan", PLAN)
        send(self.runtime, "reviewer-b", work_id, "record_evidence",
             {"event_id": "EV-manual-1", "kind": "project_approval",
              "data": {"decision": "approved", "digest": "d" * 64,
                       "revision": 1, "node": "n05", "attempt": 1,
                       "actor": "reviewer-b",
                       "items": [{"check": "N05-3", "verdict": "passed",
                                  "reason": "reviewed",
                                  "evidence": ["document#revision-1"]}]}})
        self.runtime.verify_pending(work_id)
        work = self.runtime.get_work(work_id)
        receipt = self.runtime.command(
            "coordinator", uuid.uuid4().hex, work_id, "propose_action",
            {"capability": "work.dispatch", "contract_revision": 1,
             "plan_revision": 1, "document_digest": work["document_digest"]},
            version_of(self.runtime, work_id))
        self.assertEqual(receipt["decision"], "accepted", receipt)
        operation = self.operation(work_id)
        context = self.engine.suggest_action_context(operation["business_key"])
        self.assertFalse(context["present"])
        self.assertEqual(context["code"], "ACTION_CONTEXT_REFUSED")
        self.assertEqual(context["reason"], "OPERATION_NOT_WORKFLOW_BOUND")

    def test_a_mutated_answer_does_not_change_the_store(self):
        """The answer is a copy: changing it cannot change the store."""
        self.drive_to_dispatch()
        operation = self.operation()
        before = self.rows("operations")
        context = self.engine.suggest_action_context(operation["business_key"])
        stable = context["context"]
        stable["subject"]["body"]["measures"] = []
        stable["subject"]["digest"] = "tampered"
        stable["node"] = "tampered"
        stable["actor"] = "tampered"
        context["current"]["stateVersion"] = -1
        context["current"]["cancelled"] = True
        again = self.engine.suggest_action_context(operation["business_key"])
        self.assertEqual(again["context"]["node"], "n06")
        self.assertEqual(again["context"]["actor"], "coordinator")
        self.assertEqual(again["context"]["subject"]["digest"],
                         self.proposal_reference()["digest"])
        self.assertIn("measures", again["context"]["subject"]["body"])
        self.assertNotEqual(again["current"]["stateVersion"], -1)
        self.assertFalse(again["current"]["cancelled"])
        self.assertEqual(self.rows("operations"), before)

    def test_the_read_writes_no_event_and_changes_no_state_version(self):
        self.drive_to_dispatch()
        operation = self.operation()
        version = version_of(self.runtime, self.work_id)
        events = self.runtime.events(self.work_id)
        nodes = self.rows("workflow_nodes")
        for _ in range(3):
            context = self.engine.suggest_action_context(operation["business_key"])
            self.assertTrue(context["present"], context)
        self.assertEqual(version_of(self.runtime, self.work_id), version)
        self.assertEqual(self.runtime.events(self.work_id), events)
        self.assertEqual(self.rows("workflow_nodes"), nodes)

    def test_a_cancelled_work_keeps_its_context_and_grants_no_execution(self):
        """Cancellation ends the execution, never the record of the action."""
        self.drive_to_dispatch()
        operation = self.operation()
        receipt = self.runtime.command(
            "coordinator", uuid.uuid4().hex, self.work_id, "request_cancel",
            {"reason": "the work is not needed"}, version_of(self.runtime, self.work_id))
        self.assertEqual(receipt["decision"], "accepted", receipt)
        context = self.engine.suggest_action_context(operation["business_key"])
        self.assertTrue(context["present"], context)
        self.assertEqual(context["context"]["node"], "n06")
        self.assertEqual(context["context"]["subject"]["digest"],
                         self.proposal_reference()["digest"])
        self.assertTrue(context["current"]["cancelled"])
        self.assertEqual(context["current"]["cancellation"]["reason"],
                         "the work is not needed")
        self.assertEqual(context["current"]["nodeState"], "cancelled")
        self.assertEqual(context["current"]["dispatchState"], "cancelled")
        # The context is a description, never an authority: nothing leaves.
        self.runtime.dispatch(operation["id"], self.adapter)
        self.assertEqual(self.adapter.effect_count(), 0)


class CorruptLinkageTests(DemoFamilyTestCase):
    """A store whose linkage is broken is refused, never guessed."""

    def test_two_node_instances_of_one_operation_are_refused(self):
        self.drive_to_dispatch()
        operation = self.operation()
        instance = self.node_instance("n06")
        twin = dict(instance)
        twin["node"] = "n07"
        self.execute_on_db(
            "INSERT INTO workflow_nodes VALUES (?,?,?,?,?)",
            (self.work_id, "n07", 1, "running", canonical(twin)))
        context = self.engine.suggest_action_context(operation["business_key"])
        self.assertFalse(context["present"])
        self.assertEqual(context["code"], "ACTION_CONTEXT_REFUSED")
        self.assertEqual(context["reason"], "OPERATION_LINK_AMBIGUOUS")

    def test_a_link_of_another_kind_is_refused(self):
        self.drive_to_dispatch()
        operation = self.operation()
        instance = self.node_instance("n06")
        instance["kind"] = "agent"
        self.execute_on_db(
            "UPDATE workflow_nodes SET body=? WHERE work_id=? AND node=? AND attempt=?",
            (canonical(instance), self.work_id, "n06", 1))
        context = self.engine.suggest_action_context(operation["business_key"])
        self.assertFalse(context["present"])
        self.assertEqual(context["code"], "ACTION_CONTEXT_REFUSED")
        self.assertEqual(context["reason"], "OPERATION_LINK_WRONG_KIND")

    def test_a_subject_that_does_not_match_the_operation_is_refused(self):
        self.drive_to_dispatch()
        operation = self.operation()
        operation["object"] = {"name": "proposal", "revision": 99,
                               "digest": operation["document_digest"]}
        self.execute_on_db(
            "UPDATE operations SET body=? WHERE business_key=?",
            (canonical(operation), operation["business_key"]))
        context = self.engine.suggest_action_context(operation["business_key"])
        self.assertFalse(context["present"])
        self.assertEqual(context["code"], "ACTION_CONTEXT_REFUSED")
        self.assertEqual(context["reason"], "OPERATION_SUBJECT_MISMATCH")

    def test_an_object_with_a_broken_digest_is_refused(self):
        self.drive_to_dispatch()
        operation = self.operation()
        self.execute_on_db(
            "UPDATE workflow_objects SET digest=? WHERE work_id=? AND name=?",
            ("0" * 64, self.work_id, "proposal"))
        context = self.engine.suggest_action_context(operation["business_key"])
        self.assertFalse(context["present"])
        self.assertEqual(context["code"], "ACTION_CONTEXT_REFUSED")
        self.assertEqual(context["reason"], "OPERATION_OBJECT_DIGEST_MISMATCH")

    def test_a_capability_that_does_not_match_the_node_is_refused(self):
        self.drive_to_dispatch()
        operation = self.operation()
        operation["capability"] = "work.deliver"
        self.execute_on_db(
            "UPDATE operations SET body=? WHERE business_key=?",
            (canonical(operation), operation["business_key"]))
        context = self.engine.suggest_action_context(operation["business_key"])
        self.assertFalse(context["present"])
        self.assertEqual(context["code"], "ACTION_CONTEXT_REFUSED")
        self.assertEqual(context["reason"], "OPERATION_CAPABILITY_MISMATCH")


# --------------------------------------------------------------------------
# A second family: two action nodes of the same capability
# --------------------------------------------------------------------------

CONTEXT_POLICY_ID = "workflow-context"
CONTEXT_POLICY_VERSION = "context-1"
CONTEXT_POLICY_GOAL = "context.completed"


class ContextPolicy:
    """A minimal family: no obligations, so the effect itself is the subject."""

    id = CONTEXT_POLICY_ID
    version = CONTEXT_POLICY_VERSION
    goal = CONTEXT_POLICY_GOAL
    evidence_sources = {"accepted": "business-system"}

    def validate_document(self, document):
        if set(document) != {"id", "subject"}:
            raise ValueError("Document requires id and subject")

    def validate_evidence(self, work, candidate):
        return True

    def evaluate(self, work, evidence):
        return []

    def action_blockers(self, capability, requirements):
        return []

    def operation_key(self, capability, work):
        return digest([self.id, capability, work["document"]["id"]])


def context_grants():
    return {"coordinator": {"work.manage", "work.dispatch"},
            "business-system": {"evidence.write"}}


def context_template(attempts=1):
    """Two action nodes of the same capability, on two different subjects."""
    return {
        "id": "context-flow",
        "version": "test-1",
        "policy_family": CONTEXT_POLICY_ID,
        "entry": "n01",
        "terminal": ["n02"],
        "nodes": {
            "n01": {"kind": "action", "capability": "work.dispatch",
                    "subject": {"object": "left"}, "max_attempts": attempts},
            "n02": {"kind": "action", "capability": "work.dispatch",
                    "subject": {"object": "right"}},
        },
        "edges": [{"from": "n01", "to": "n02"}],
    }


class SameCapabilityTests(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-action-context-family-")
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.adapter_path = os.path.join(self.folder, "effects.sqlite")
        self.runtime = Runtime(self.path, ContextPolicy(), context_grants())
        self.engine = WorkflowEngine(self.runtime, runner="workflow-runner")
        self.adapter = DemoBusinessSystem(self.adapter_path)
        self.work_id = "W-1"

    def rows(self, table, where="1=1", arguments=()):
        db = sqlite3.connect(self.path)
        try:
            return db.execute("SELECT * FROM " + table + " WHERE " + where,
                              arguments).fetchall()
        finally:
            db.close()

    def operations(self):
        return [json.loads(row[3]) for row in self.rows("operations")]

    def instantiate(self, template):
        receipt = self.engine.publish_template("coordinator", template)
        self.assertEqual(receipt["decision"], "accepted", receipt)
        send(self.runtime, "coordinator", self.work_id, "create_work",
             {"document": {"id": "H-001", "subject": "east parapet"}})
        send(self.runtime, "coordinator", self.work_id, "bind_contract",
             {"policy_id": CONTEXT_POLICY_ID,
              "policy_version": CONTEXT_POLICY_VERSION,
              "goal": CONTEXT_POLICY_GOAL})
        send(self.runtime, "coordinator", self.work_id, "revise_plan",
             {"steps": ["n01", "n02"], "open_requirements": [],
              "replan_when": []})
        receipt = self.engine.command(
            "coordinator", uuid.uuid4().hex, self.work_id, "bind_workflow",
            {"template_id": template["id"], "template_version": template["version"],
             "parameters": {}}, version_of(self.runtime, self.work_id))
        self.assertEqual(receipt["decision"], "accepted", receipt)

    def write_object(self, name, body):
        receipt = self.engine.command(
            "coordinator", uuid.uuid4().hex, self.work_id, "revise_object",
            {"name": name, "object": body},
            version_of(self.runtime, self.work_id))
        self.assertEqual(receipt["decision"], "accepted", receipt)
        return receipt["object"]

    def test_two_nodes_of_the_same_capability_map_to_their_own_action(self):
        """The same capability in two nodes never confuses the mapping."""
        self.instantiate(context_template())
        self.write_object("left", {"measures": [{"id": "L-1"}]})
        self.write_object("right", {"measures": [{"id": "R-1"}]})
        self.engine.advance(self.work_id, 1000)
        self.engine.pump(self.adapter, 1000)
        self.engine.pump(self.adapter, 1000)
        operations = self.operations()
        self.assertEqual(len(operations), 2)
        contexts = {}
        for operation in operations:
            context = self.engine.suggest_action_context(operation["business_key"])
            self.assertTrue(context["present"], context)
            contexts[operation["business_key"]] = context["context"]
        self.assertEqual(len(contexts), 2)
        nodes = sorted(context["node"] for context in contexts.values())
        self.assertEqual(nodes, ["n01", "n02"])
        for context in contexts.values():
            self.assertEqual(context["capability"], "work.dispatch")
        subjects = sorted(context["subject"]["name"] for context in contexts.values())
        self.assertEqual(subjects, ["left", "right"])
        by_node = {context["node"]: context for context in contexts.values()}
        self.assertEqual(by_node["n01"]["subject"]["name"], "left")
        self.assertEqual(by_node["n02"]["subject"]["name"], "right")
        self.assertNotEqual(by_node["n01"]["subject"]["digest"],
                            by_node["n02"]["subject"]["digest"])

    def test_a_historical_attempt_keeps_its_own_action(self):
        """A superseded attempt keeps its own operation, subject and attempt."""
        self.instantiate(context_template(attempts=2))
        self.write_object("left", {"measures": [{"id": "L-1"}]})
        self.engine.advance(self.work_id, 1000)
        first = self.operations()
        self.assertEqual(len(first), 1)
        # The subject is revised while the first attempt is running: the
        # attempt is superseded and a second attempt proposes a new action.
        self.write_object("left", {"measures": [{"id": "L-2"}]})
        self.engine.advance(self.work_id, 2000)
        operations = self.operations()
        self.assertEqual(len(operations), 2)
        historical = self.engine.suggest_action_context(first[0]["business_key"])
        self.assertTrue(historical["present"], historical)
        self.assertEqual(historical["context"]["node"], "n01")
        self.assertEqual(historical["context"]["attempt"], 1)
        self.assertEqual(historical["context"]["subject"]["revision"], 1)
        self.assertEqual(historical["context"]["subject"]["body"]["measures"],
                         [{"id": "L-1"}])
        self.assertEqual(historical["current"]["nodeState"], "cancelled")
        live = self.engine.suggest_action_context(operations[1]["business_key"])
        self.assertTrue(live["present"], live)
        self.assertEqual(live["context"]["node"], "n01")
        self.assertEqual(live["context"]["attempt"], 2)
        self.assertEqual(live["context"]["subject"]["revision"], 2)
        self.assertNotEqual(live["context"]["subject"]["digest"],
                            historical["context"]["subject"]["digest"])


if __name__ == "__main__":
    unittest.main()
