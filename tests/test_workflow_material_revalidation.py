"""Controlled source replacement and transitive revalidation.

A trusted manager replaces the archived source material of a running
workflow and the consumers that judged it are revalidated — in the same
workflow and session. The source read is never re-run, a business effect
is never replayed, the quality allowance is never raised, and the number
of material generations is bounded by the definition.

The tests run on a real store and assert stored truth (rows, attempts,
operations, events), never a receipt alone.
"""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest
import uuid

from work_runtime.workflow import WorkflowError

try:
    from workflow_support import (POLICY_GOAL, POLICY_ID, POLICY_VERSION,
                                  REVALIDATION_TEMPLATE, RevalidationPolicy,
                                  build, current_attempt, document,
                                  input_digest_of, instance_of, instantiate,
                                  send, submit, submit_valid, version_of)
    from workflow_support import DemoBusinessSystem
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import (POLICY_GOAL, POLICY_ID, POLICY_VERSION,
                                        REVALIDATION_TEMPLATE, RevalidationPolicy,
                                        build, current_attempt, document,
                                        input_digest_of, instance_of,
                                        instantiate, send, submit, submit_valid,
                                        version_of)
    from tests.workflow_support import DemoBusinessSystem

OWNER = "coordinator"
EXECUTOR = "agent-executor"
WORK_ID = "W-1"
SOURCE_REFERENCE = {"kind": "business-material-snapshot",
                    "archiveId": "ARCH-9", "revision": "r7",
                    "digest": "d" * 64, "capturedAt": 1760000000}
VALID_INTAKE = {"records": [{"id": "R-1", "source": "site-log"}],
                "standard": "STD-1"}
VALID_ANALYSIS = {"findings": [{"issueId": "H-001", "clause": "C-1",
                                "finding": "gap"}]}


class RevalidationTestCase(unittest.TestCase):
    """The workflow is driven to the point where the manager acts.

    The source read produced the material, two consumers judged it, and
    the third consumer waits for what is still missing.
    """

    template = REVALIDATION_TEMPLATE

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-revalidation-")
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.adapter = DemoBusinessSystem(os.path.join(self.folder, "effects.db"))
        self.runtime, self.engine = build(self.path, policy=RevalidationPolicy())
        self.work = WORK_ID
        published = self.engine.publish_template(OWNER, self.template)
        self.assertEqual("accepted", published["decision"], published)
        send(self.runtime, OWNER, self.work, "create_work",
             {"document": document()})
        send(self.runtime, OWNER, self.work, "bind_contract",
             {"policy_id": POLICY_ID, "policy_version": POLICY_VERSION,
              "goal": POLICY_GOAL})
        send(self.runtime, OWNER, self.work, "revise_plan",
             {"steps": ["s00", "n01", "n02", "n03"],
              "open_requirements": [], "replan_when": []})
        # the manager supplies what the source read acts on
        request = send(self.runtime, OWNER, self.work, "revise_object",
                       {"name": "request", "object": {"id": "REQ-1"}})
        self.assertEqual("accepted", request["decision"], request)
        bound = self.engine.command(
            OWNER, "bind-1", self.work, "bind_workflow",
            {"template_id": self.template["id"],
             "template_version": self.template["version"],
             "parameters": {"subject": "east parapet"}},
            version_of(self.runtime, self.work))
        self.assertEqual("accepted", bound["decision"], bound)
        # the source read: the effect really happens
        self.engine.pump(self.adapter, 1000)
        self.source_revision = self.object_revision("sources")
        self.assertEqual(1, self.source_revision["revision"])
        for node, name, result in (("n01", "intake", VALID_INTAKE),
                                   ("n02", "analysis", VALID_ANALYSIS)):
            submitted = submit_valid(self.engine, self.runtime, self.work, node,
                                     name, result)
            self.assertEqual("accepted", submitted["decision"], submitted)
        # the third consumer waits for what is still missing
        self.wait()

    # -- helpers ---------------------------------------------------------

    def rows(self, query, arguments=()):
        db = sqlite3.connect(self.path)
        try:
            return db.execute(query, arguments).fetchall()
        finally:
            db.close()

    def object_revision(self, name, revision=None):
        db = sqlite3.connect(self.path)
        try:
            if revision is None:
                row = db.execute(
                    "SELECT revision,digest,body FROM workflow_objects "
                    "WHERE work_id=? AND name=? ORDER BY revision DESC LIMIT 1",
                    (self.work, name)).fetchone()
            else:
                row = db.execute(
                    "SELECT revision,digest,body FROM workflow_objects "
                    "WHERE work_id=? AND name=? AND revision=?",
                    (self.work, name, revision)).fetchone()
        finally:
            db.close()
        if row is None:
            return None
        return {"revision": row[0], "digest": row[1], "body": json.loads(row[2])}

    def instance(self, node):
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT attempt,state,body FROM workflow_nodes "
                             "WHERE work_id=? AND node=? ORDER BY attempt",
                             (self.work, node)).fetchall()
        finally:
            db.close()
        return [{"attempt": attempt, "state": state, "body": json.loads(body)}
                for attempt, state, body in row]

    def wait(self):
        """The manager parks the third consumer for what is missing."""
        return self.engine.command(
            OWNER, uuid.uuid4().hex, self.work, "request_material_wait",
            {"node": "n03", "attempt": 1,
             "input_digest": input_digest_of(self.engine, self.work, "n03"),
             "reason": "the referenced standard is missing",
             "request_version": 1},
            version_of(self.runtime, self.work))

    def replace(self, *, node="s00", reference=None, reason="the archive was refreshed",
                waiting_node="n03", waiting_ticket=None, actor=OWNER,
                request_version=1):
        if waiting_ticket is None and waiting_node:
            waiting_ticket = input_digest_of(self.engine, self.work, waiting_node)
        payload = {"node": node,
                   "source_reference": SOURCE_REFERENCE if reference is None
                   else reference,
                   "reason": reason, "request_version": request_version,
                   "waiting_node": waiting_node,
                   "waiting_ticket": waiting_ticket}
        return self.engine.command(actor, uuid.uuid4().hex, self.work,
                                   "replace_material", payload,
                                   version_of(self.runtime, self.work))

    def events(self):
        return [entry["type"] for entry in self.runtime.events(self.work)]


class ReplaceMaterialTestCase(RevalidationTestCase):
    """The controlled replacement itself."""

    def test_the_manager_replaces_the_source_material(self):
        receipt = self.replace()
        self.assertEqual("accepted", receipt["decision"], receipt)
        attestation = receipt["attestation"]
        self.assertEqual("business-material-snapshot",
                         attestation["source_reference"]["kind"])
        self.assertEqual(OWNER, attestation["adopted_by"])
        self.assertEqual("s00", attestation["source_node"])
        self.assertEqual("sources", attestation["object"])
        self.assertEqual(1, attestation["from"]["revision"])
        self.assertEqual(2, attestation["to"]["revision"])
        # the claim is explicit: the old acceptance does not cover the new
        # revision
        self.assertIn("does not cover", attestation["claim"])
        # the new revision is the manager's frozen reference and the
        # historical revision is retained
        current = self.object_revision("sources")
        self.assertEqual(2, current["revision"])
        self.assertEqual(SOURCE_REFERENCE, current["body"])
        self.assertEqual(1, self.object_revision("sources", 1)["revision"])
        # the affected consumers are named
        affected = [entry["node"] for entry in receipt["affected"]]
        self.assertEqual(["n01", "n02", "n03"], affected)
        self.assertIn("WorkflowMaterialReplaced", self.events())

    def test_the_source_read_is_never_rerun(self):
        before_instance = self.instance("s00")
        before_operations = self.rows("SELECT id,body FROM operations WHERE work_id=?",
                                      (self.work,))
        before_intents = self.rows("SELECT id,status FROM workflow_intents "
                                   "WHERE work_id=? AND node='s00'", (self.work,))
        receipt = self.replace()
        self.assertEqual("accepted", receipt["decision"], receipt)
        # the source node keeps its attempt, its accepted output and its
        # effect: the replacement never re-runs the read
        self.assertEqual(before_instance, self.instance("s00"))
        self.assertEqual(before_operations,
                         self.rows("SELECT id,body FROM operations WHERE work_id=?",
                                   (self.work,)))
        self.assertEqual(before_intents,
                         self.rows("SELECT id,status FROM workflow_intents "
                                   "WHERE work_id=? AND node='s00'", (self.work,)))
        # and the accepted revision it produced is still revision 1
        body = self.instance("s00")[0]["body"]
        self.assertEqual(1, body["output"]["revision"])

    def test_a_refused_replacement_mutates_nothing(self):
        before_objects = self.rows("SELECT name,revision,digest,body FROM workflow_objects")
        before_nodes = self.rows("SELECT node,attempt,state,body FROM workflow_nodes")
        before_events = self.rows("SELECT version,type FROM events")
        before_version = version_of(self.runtime, self.work)
        self.assertEqual("AUTHORITY_DENIED", self.replace(actor=EXECUTOR)["code"])
        self.assertEqual("WORKFLOW_NODE_UNKNOWN", self.replace(node="n99")["code"])
        self.assertEqual("WORKFLOW_SOURCE_NOT_PRODUCER",
                         self.replace(node="n03")["code"])
        self.assertEqual("WORKFLOW_SOURCE_REFERENCE_INVALID",
                         self.replace(reference="not an object")["code"])
        self.assertEqual("WORKFLOW_SOURCE_REFERENCE_INVALID",
                         self.replace(reference={"no": "kind"})["code"])
        self.assertEqual("WORKFLOW_SOURCE_REFERENCE_TOO_LARGE",
                         self.replace(reference={"kind": "business-material-snapshot",
                                                 "blob": "x" * 8000})["code"])
        self.assertEqual("WORKFLOW_WAITING_TICKET_STALE",
                         self.replace(waiting_ticket="0" * 64)["code"])
        self.assertEqual(before_objects,
                         self.rows("SELECT name,revision,digest,body FROM workflow_objects"))
        self.assertEqual(before_nodes,
                         self.rows("SELECT node,attempt,state,body FROM workflow_nodes"))
        self.assertEqual(before_events, self.rows("SELECT version,type FROM events"))
        self.assertEqual(before_version, version_of(self.runtime, self.work))

    def test_the_request_is_versioned(self):
        with self.assertRaises(WorkflowError):
            self.replace(request_version=2)

    def test_a_cancelling_work_refuses_the_replacement(self):
        send(self.runtime, OWNER, self.work, "request_cancel",
             {"reason": "the source was withdrawn"})
        receipt = self.replace()
        self.assertEqual("rejected", receipt["decision"], receipt)
        self.assertEqual("CANCELLATION_ACTIVE", receipt["code"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
