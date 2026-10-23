"""Manager-requested material waiting on the current agent node.

Business material is not candidate quality: a wait parks the node's current
attempt without opening a rework attempt, withdraws the agent's durable
intent, refuses result acceptance and persists across a restart until the
manager adopts the supplemented material and resumes. The tests run on a
real store and assert stored truth (rows, intents, events), never a receipt
alone.
"""

import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
import uuid

from work_runtime.workflow import WorkflowError

try:
    from workflow_support import (FOCUSED_TEMPLATE, POLICY_GOAL, POLICY_ID,
                                  POLICY_VERSION, current_attempt, document,
                                  input_digest_of, instance_of, instantiate,
                                  scenario_template, send, submit, submit_valid,
                                  version_of, build)
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import (FOCUSED_TEMPLATE, POLICY_GOAL, POLICY_ID,
                                        POLICY_VERSION, current_attempt, document,
                                        input_digest_of, instance_of,
                                        instantiate, scenario_template, send,
                                        submit, submit_valid, version_of, build)

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

    def intent_status(self, node, attempt, kind="agent_task", generation=0):
        intent_id = "wf:%s:%s:%d:%s" % (self.work, node, attempt, kind)
        if generation:
            intent_id += ":" + str(generation)
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


class AdoptMaterialTestCase(MaterialWaitTestCase):
    """A manager adopts externally provided material under an active wait.

    In the demonstration family the waited-for material is the output of a
    completed upstream node, so an adoption of it is refused: it would
    write material no completed node ever accepted. The adoption of
    genuinely external material belongs to the focused family below.
    """

    SUPPLEMENT = {"records": [{"id": "R-1", "source": "site-log"},
                              {"id": "R-2", "source": "site-log"}],
                  "standard": "STD-1"}

    def adopt(self, *, name="intake", body=None, actor=OWNER, attempt=None,
              request_version=1):
        payload = {"node": "n02", "attempt": self.attempt if attempt is None
                   else attempt, "name": name,
                   "object": self.SUPPLEMENT if body is None else body,
                   "request_version": request_version}
        return self.engine.command(actor, uuid.uuid4().hex, self.work,
                                   "adopt_material", payload,
                                   version_of(self.runtime, self.work))

    def object_revisions(self, name="intake"):
        db = sqlite3.connect(self.path)
        try:
            return db.execute(
                "SELECT revision,digest,body FROM workflow_objects "
                "WHERE work_id=? AND name=? ORDER BY revision",
                (self.work, name)).fetchall()
        finally:
            db.close()

    def test_the_adoption_of_a_completed_upstream_output_is_refused(self):
        self.wait()
        before = self.stored()
        receipt = self.adopt()
        self.assertEqual("rejected", receipt["decision"], receipt)
        self.assertEqual("INPUT_DEPENDENCIES_REQUIRE_REVALIDATION",
                         receipt["code"])
        finding = receipt["blockers"][0]
        self.assertEqual("intake", finding["name"])
        self.assertEqual("n01", finding["node"])
        self.assertEqual(1, finding["attempt"])
        self.assertEqual(1, finding["accepted"]["revision"])
        self.assertEqual(1, finding["current"]["revision"])
        # nothing was written and the wait keeps waiting
        self.assertEqual(before, self.stored())
        self.assertEqual("waiting", instance_of(self.engine, self.runtime,
                                                self.work, "n02")["state"])
        self.assertEqual(1, len(self.object_revisions()))

    def test_a_refused_adoption_mutates_nothing(self):
        self.wait()
        before = self.stored()
        self.assertEqual("WORKFLOW_MATERIAL_NOT_DEPENDENCY",
                         self.adopt(name="analysis")["code"])
        self.assertEqual("AUTHORITY_DENIED",
                         self.adopt(actor=EXECUTOR)["code"])
        self.assertEqual("WORKFLOW_ATTEMPT_STALE",
                         self.adopt(attempt=2)["code"])
        self.assertEqual(before, self.stored())

    def test_adopting_without_a_wait_is_refused(self):
        receipt = self.adopt()
        self.assertEqual("rejected", receipt["decision"], receipt)
        self.assertEqual("WORKFLOW_NOT_WAITING", receipt["code"])

    def test_an_oversized_adoption_is_refused(self):
        self.wait()
        before = self.stored()
        receipt = self.adopt(body={"records": [], "padding": "x" * 70000})
        self.assertEqual("rejected", receipt["decision"], receipt)
        self.assertEqual("WORKFLOW_MATERIAL_TOO_LARGE", receipt["code"])
        self.assertEqual(before, self.stored())

    def test_the_adoption_is_versioned(self):
        self.wait()
        with self.assertRaises(WorkflowError):
            self.adopt(request_version=2)


class ResumeMaterialWaitTestCase(AdoptMaterialTestCase):
    """The manager resumes the waiting node behind the dependency gate."""

    def resume(self, *, node="n02", attempt=None, actor=OWNER,
               request_version=1):
        payload = {"node": node, "attempt": self.attempt if attempt is None
                   else attempt, "request_version": request_version}
        return self.engine.command(actor, uuid.uuid4().hex, self.work,
                                   "resume_material_wait", payload,
                                   version_of(self.runtime, self.work))

    def test_the_wait_resumes_the_same_attempt(self):
        self.wait()
        receipt = self.resume()
        self.assertEqual("accepted", receipt["decision"], receipt)
        self.assertEqual("running", receipt["state"])
        self.assertEqual(1, receipt["attempt"])
        entry = instance_of(self.engine, self.runtime, self.work, "n02")
        self.assertEqual("running", entry["state"])
        # the attempt is the same one: the wait spent no quality allowance
        self.assertEqual(self.attempt, entry["attempt"])
        # the agent's task is issued again under a new identity: an old
        # acknowledgement can never swallow the resumed prompt
        self.assertEqual("cancelled", self.intent_status("n02", 1))
        self.assertEqual("pending", self.intent_status("n02", 1, generation=1))
        self.assertEqual(1, entry["inputGeneration"])
        # the work is active again
        work = self.runtime.get_work(self.work)
        self.assertEqual("active", work["workflow_status"])
        wait = entry["materialWait"]
        self.assertEqual("resumed", wait["state"])
        self.assertEqual(OWNER, wait["resumed"]["by"])

    def test_the_resume_moves_the_input_ticket_even_for_equal_material(self):
        self.wait()
        stale = input_digest_of(self.engine, self.work, "n02")
        receipt = self.resume()
        self.assertEqual("accepted", receipt["decision"], receipt)
        entry = instance_of(self.engine, self.runtime, self.work, "n02")
        # the material did not change, yet the ticket did: a result ticket
        # issued before the wait never satisfies the node after it
        self.assertNotEqual(stale, entry["inputDigest"])
        refused = submit(self.engine, self.runtime, self.work, "n02",
                         self.attempt, "analysis", VALID_ANALYSIS,
                         input_digest=stale)
        self.assertEqual("rejected", refused["decision"], refused)
        self.assertEqual("WORKFLOW_INPUT_STALE", refused["code"])

    def test_the_resumed_node_accepts_a_candidate_for_the_same_attempt(self):
        self.wait()
        self.resume()
        entry = instance_of(self.engine, self.runtime, self.work, "n02")
        self.assertEqual("running", entry["state"])
        self.assertEqual(1, entry["attempt"])
        receipt = submit(self.engine, self.runtime, self.work, "n02",
                         entry["attempt"], "analysis", VALID_ANALYSIS,
                         input_digest=entry["inputDigest"])
        self.assertEqual("accepted", receipt["decision"], receipt)
        node = instance_of(self.engine, self.runtime, self.work, "n02")
        self.assertEqual("completed", node["state"])

    def test_a_dependency_revised_during_the_wait_blocks_the_resume(self):
        self.wait()
        # somebody else revises the material the wait is about
        receipt = send(self.runtime, OWNER, self.work, "revise_object",
                       {"name": "intake",
                        "object": {"records": [{"id": "R-9", "source": "other"}],
                                   "standard": "STD-1"}})
        self.assertEqual("accepted", receipt["decision"], receipt)
        # the waiting node is not superseded by the revision: it keeps
        # waiting, and the resume is refused instead
        entry = instance_of(self.engine, self.runtime, self.work, "n02")
        self.assertEqual("waiting", entry["state"])
        before = self.stored()
        refused = self.resume()
        self.assertEqual("rejected", refused["decision"], refused)
        self.assertEqual("INPUT_DEPENDENCIES_REQUIRE_REVALIDATION",
                         refused["code"])
        finding = refused["blockers"][0]
        self.assertEqual("intake", finding["name"])
        self.assertEqual(1, finding["accepted"]["revision"])
        self.assertEqual(2, finding["current"]["revision"])
        self.assertEqual(before, self.stored())
        # the adoption of the upstream's output is refused as well, and
        # the wait keeps waiting: revalidating the upstream is a separate,
        # bounded step
        adopted = self.adopt(body={"records": [{"id": "R-9", "source": "other"}],
                                      "standard": "STD-1"})
        self.assertEqual("rejected", adopted["decision"], adopted)
        self.assertEqual("INPUT_DEPENDENCIES_REQUIRE_REVALIDATION",
                         adopted["code"])
        self.assertEqual("waiting", instance_of(self.engine, self.runtime,
                                                self.work, "n02")["state"])

    def test_a_refused_resume_mutates_nothing(self):
        self.wait()
        before = self.stored()
        self.assertEqual("AUTHORITY_DENIED", self.resume(actor=EXECUTOR)["code"])
        self.assertEqual("WORKFLOW_ATTEMPT_STALE", self.resume(attempt=2)["code"])
        self.assertEqual(before, self.stored())

    def test_resuming_a_node_that_does_not_wait_is_refused(self):
        receipt = self.resume()
        self.assertEqual("rejected", receipt["decision"], receipt)
        self.assertEqual("WORKFLOW_NOT_WAITING", receipt["code"])

    def test_a_cancelling_work_refuses_the_resume(self):
        self.wait()
        send(self.runtime, OWNER, self.work, "request_cancel",
             {"reason": "duplicated request"})
        receipt = self.resume()
        self.assertEqual("rejected", receipt["decision"], receipt)
        self.assertEqual("CANCELLATION_ACTIVE", receipt["code"])

    def test_a_cancelled_work_cancels_the_waiting_node(self):
        self.wait()
        send(self.runtime, OWNER, self.work, "request_cancel",
             {"reason": "duplicated request"})
        entry = instance_of(self.engine, self.runtime, self.work, "n02")
        self.assertEqual("cancelled", entry["state"])
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT body FROM workflow_nodes WHERE work_id=? "
                             "AND node='n02' AND attempt=?",
                             (self.work, self.attempt)).fetchone()
        finally:
            db.close()
        stored = json.loads(row[0])
        self.assertEqual("WORK_CANCELLED", stored["reason"])

    def test_the_view_reports_the_waiting_reason(self):
        self.wait()
        view = self.engine.instance(self.work)
        entry = [node for node in view["nodes"] if node["node"] == "n02"][0]
        self.assertEqual("waiting", entry["state"])
        wait = entry["materialWait"]
        self.assertEqual("waiting", wait["state"])
        self.assertEqual("the referenced record is missing a page",
                         wait["reason"])
        self.assertEqual(OWNER, wait["requestedBy"])
        self.assertEqual("intake", wait["dependencies"][0]["name"])
        self.assertEqual([], wait["adoptions"])


class FocusedWaitTestCase(unittest.TestCase):
    """A family whose agent node validates its input and has a deadline.

    The demonstration family declares no validation on the input of n02 and
    no deadline on any agent node, so the fail-closed material and the
    suspended deadline need a definition of their own.
    """

    VALID_INTAKE = {"records": [{"id": "R-1", "source": "site-log"}],
                    "standard": "STD-1"}

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-material-focus-")
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.runtime, self.engine = build(self.path, runner="workflow-runner")
        self.work = WORK_ID
        published = self.engine.publish_template(OWNER, FOCUSED_TEMPLATE)
        self.assertEqual("accepted", published["decision"], published)
        send(self.runtime, OWNER, self.work, "create_work",
             {"document": document()})
        send(self.runtime, OWNER, self.work, "bind_contract",
             {"policy_id": POLICY_ID, "policy_version": POLICY_VERSION,
              "goal": POLICY_GOAL})
        send(self.runtime, OWNER, self.work, "revise_plan",
             {"steps": ["n01"], "open_requirements": [],
              "replan_when": []})
        # the manager supplies the material the node needs
        sent = send(self.runtime, OWNER, self.work, "revise_object",
                    {"name": "intake", "object": self.VALID_INTAKE})
        self.assertEqual("accepted", sent["decision"], sent)
        bound = self.engine.command(
            OWNER, uuid.uuid4().hex, self.work, "bind_workflow",
            {"template_id": FOCUSED_TEMPLATE["id"],
             "template_version": FOCUSED_TEMPLATE["version"],
             "parameters": {"subject": "east parapet"}},
            version_of(self.runtime, self.work))
        self.assertEqual("accepted", bound["decision"], bound)
        self.engine.advance(self.work, 1_000)
        self.attempt = current_attempt(self.engine, self.runtime, self.work, "n01")
        self.assertEqual(1, self.attempt)

    def stored_instance(self, node="n01"):
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT body FROM workflow_nodes WHERE work_id=? "
                             "AND node=? AND attempt=?",
                             (self.work, node, self.attempt)).fetchone()
        finally:
            db.close()
        return json.loads(row[0])

    def wait(self, reason="the referenced record is missing a page"):
        return self.engine.command(
            OWNER, uuid.uuid4().hex, self.work, "request_material_wait",
            {"node": "n01", "attempt": self.attempt,
             "input_digest": input_digest_of(self.engine, self.work, "n01"),
             "reason": reason, "request_version": 1},
            version_of(self.runtime, self.work))

    def adopt(self, body):
        return self.engine.command(
            OWNER, uuid.uuid4().hex, self.work, "adopt_material",
            {"node": "n01", "attempt": self.attempt, "name": "intake",
             "object": body, "request_version": 1},
            version_of(self.runtime, self.work))

    def resume(self):
        return self.engine.command(
            OWNER, uuid.uuid4().hex, self.work, "resume_material_wait",
            {"node": "n01", "attempt": self.attempt, "request_version": 1},
            version_of(self.runtime, self.work))

    def test_the_manager_adopts_external_material_and_resumes(self):
        # The material of this family was supplied from outside: no
        # completed node accepted it, so an adoption of it is legitimate.
        self.wait()
        adopted = self.adopt({"records": [{"id": "R-1", "source": "site-log"},
                                          {"id": "R-2", "source": "site-log"}],
                              "standard": "STD-1"})
        self.assertEqual("accepted", adopted["decision"], adopted)
        self.assertEqual(2, adopted["adoption"]["revision"])
        # the historical revision is retained
        db = sqlite3.connect(self.path)
        try:
            revisions = db.execute(
                "SELECT revision,body FROM workflow_objects WHERE work_id=? "
                "AND name='intake' ORDER BY revision", (self.work,)).fetchall()
        finally:
            db.close()
        self.assertEqual(2, len(revisions))
        self.assertNotIn("R-2", revisions[0][1])
        self.assertIn("R-2", revisions[1][1])
        # the wait accepts the adopted revision
        wait = adopted["wait"]
        dependency = [entry for entry in wait["dependencies"]
                      if entry["name"] == "intake"][0]
        self.assertEqual(2, dependency["revision"])
        self.assertEqual(1, len(wait["adoptions"]))
        # the node is still waiting: adopting material does not start work
        self.assertEqual("waiting", self.stored_instance()["state"])
        # the manager resumes the same attempt
        receipt = self.resume()
        self.assertEqual("accepted", receipt["decision"], receipt)
        self.assertEqual("running", receipt["state"])
        stored = self.stored_instance()
        self.assertEqual("running", stored["state"])
        self.assertEqual(self.attempt, stored["attempt"])
        self.assertEqual(2, stored["inputs"][0]["revision"])
        self.assertEqual(1, stored["input_generation"])

    def test_the_number_of_adoptions_is_bounded(self):
        self.wait()
        for index in range(16):
            receipt = self.adopt({"records": [], "index": index})
            self.assertEqual("accepted", receipt["decision"], receipt)
        receipt = self.adopt({"records": [], "index": 17})
        self.assertEqual("rejected", receipt["decision"], receipt)
        self.assertEqual("WORKFLOW_ADOPTION_LIMIT_EXCEEDED", receipt["code"])
        db = sqlite3.connect(self.path)
        try:
            revisions = db.execute(
                "SELECT COUNT(*) FROM workflow_objects WHERE work_id=? "
                "AND name='intake'", (self.work,)).fetchone()[0]
        finally:
            db.close()
        # the refused adoption wrote nothing: sixteen adopted revisions and
        # the original one
        self.assertEqual(17, revisions)
        self.assertEqual(16, len(self.stored_instance()["material_wait"]["adoptions"]))

    def test_the_resume_asks_again_under_a_new_intent_identity(self):
        self.wait()
        self.resume()
        db = sqlite3.connect(self.path)
        try:
            rows = db.execute("SELECT id,status FROM workflow_intents "
                              "WHERE work_id=? ORDER BY id",
                              (self.work,)).fetchall()
        finally:
            db.close()
        ids = {row[0]: row[1] for row in rows}
        self.assertEqual("cancelled", ids["wf:%s:n01:1:agent_task" % self.work])
        self.assertEqual("pending", ids["wf:%s:n01:1:agent_task:1" % self.work])

    def test_material_that_fails_its_validator_blocks_the_resume(self):
        self.wait()
        self.adopt({"records": [], "standard": "STD-1"})
        receipt = self.resume()
        self.assertEqual("accepted", receipt["decision"], receipt)
        self.assertEqual("blocked", receipt["state"])
        stored = self.stored_instance()
        self.assertEqual("blocked", stored["state"])
        self.assertEqual(self.attempt, stored["attempt"])
        codes = [finding["code"] for finding in stored["blockers"]]
        self.assertIn("INTAKE_EMPTY", codes)
        # nothing asked the agent to work on material that was refused
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT status FROM workflow_intents WHERE id=?",
                             ("wf:%s:n01:1:agent_task" % self.work,)).fetchone()
        finally:
            db.close()
        self.assertEqual("cancelled", row[0])

    def test_material_that_does_not_match_the_shape_blocks_the_resume(self):
        self.wait()
        self.adopt({"records": "not a list", "standard": "STD-1"})
        receipt = self.resume()
        self.assertEqual("accepted", receipt["decision"], receipt)
        self.assertEqual("blocked", receipt["state"])
        stored = self.stored_instance()
        codes = [finding["code"] for finding in stored["blockers"]]
        self.assertIn("SHAPE_TYPE", codes)

    def test_the_deadline_is_suspended_while_the_node_waits(self):
        self.wait()
        # far beyond the deadline: a waiting node does not expire
        self.engine.advance(self.work, 1_000_000)
        stored = self.stored_instance()
        self.assertEqual("waiting", stored["state"])
        self.assertNotEqual("expired", stored["state"])
        self.assertIsNone(stored.get("reason"))

    def test_the_resumed_node_gets_a_fresh_deadline(self):
        self.wait()
        before = self.stored_instance()["deadline_at"]
        # The deadline is recomputed from the resume, so the only way to see
        # it is a real gap between the park and the resume.
        time.sleep(1.05)
        receipt = self.resume()
        self.assertEqual("accepted", receipt["decision"], receipt)
        stored = self.stored_instance()
        self.assertEqual("running", stored["state"])
        self.assertIsNotNone(stored.get("deadline_at"))
        # the deadline that was in force before the wait is not inherited
        self.assertGreater(stored["deadline_at"], before)

    def test_the_acceptance_refuses_a_waiting_workflow(self):
        self.wait()
        receipt = self.engine.command(
            "workflow-runner", uuid.uuid4().hex, self.work,
            "finalize_workflow_success", {},
            version_of(self.runtime, self.work))
        self.assertEqual("rejected", receipt["decision"], receipt)
        # a waiting node is never terminal, so the workflow is not finished
        # and the acceptance is refused before it looks at anything else
        self.assertEqual("WORKFLOW_NOT_FINISHED", receipt["code"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
