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
                                  SourceReferenceAdapter, build, current_attempt,
                                  document, input_digest_of, instance_of,
                                  instantiate, send, source_reference_validator,
                                  submit, submit_valid, version_of)
    from workflow_support import workflow_demo_validators
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import (POLICY_GOAL, POLICY_ID, POLICY_VERSION,
                                        REVALIDATION_TEMPLATE, RevalidationPolicy,
                                        SourceReferenceAdapter, build,
                                        current_attempt, document,
                                        input_digest_of, instance_of,
                                        instantiate, send,
                                        source_reference_validator, submit,
                                        submit_valid, version_of)
    from tests.workflow_support import workflow_demo_validators
    from tests.workflow_support import DemoBusinessSystem

OWNER = "coordinator"
EXECUTOR = "agent-executor"
WORK_ID = "W-1"
# The manifest the platform freezes: a reference to the archive it
# reacquired, never the material itself.
SOURCE_REFERENCE = {"kind": "business-material-snapshot",
                    "referenceId": "REF-2", "workflowId": WORK_ID,
                    "sourceNode": "s00", "documentDigest": "d" * 64,
                    "snapshotDigest": "e" * 64, "scope": "records"}


def revalidation_validators():
    """The demo validators plus the structural validator of a source."""
    registry = workflow_demo_validators()
    registry.register("source-reference", "1", source_reference_validator)
    return registry
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
    quality_failures = 0
    park_wait = True

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-revalidation-")
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.adapter = SourceReferenceAdapter(
            os.path.join(self.folder, "effects.db"))
        self.runtime, self.engine = build(self.path, policy=RevalidationPolicy(),
                                          validators=revalidation_validators())
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
        for _ in range(self.quality_failures):
            # the first consumer spends its quality allowance on bad
            # candidates before it succeeds
            attempt = current_attempt(self.engine, self.runtime, self.work, "n01")
            failed = submit(self.engine, self.runtime, self.work, "n01", attempt,
                            "intake", {"records": "not a list"})
            self.assertEqual("rejected", failed["decision"], failed)
            self.engine.advance(self.work, 1500)
        for node, name, result in (("n01", "intake", VALID_INTAKE),
                                   ("n02", "analysis", VALID_ANALYSIS)):
            submitted = submit_valid(self.engine, self.runtime, self.work, node,
                                     name, result)
            self.assertEqual("accepted", submitted["decision"], submitted)
        if self.park_wait:
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
        self.assertEqual({"sourceReference": SOURCE_REFERENCE}, current["body"])
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
        self.assertEqual("WORKFLOW_SOURCE_REFERENCE_INVALID",
                         self.replace(reference=dict(SOURCE_REFERENCE,
                                                      workflowId="W-other"))["code"])
        self.assertEqual("WORKFLOW_SOURCE_REFERENCE_INVALID",
                         self.replace(reference=dict(SOURCE_REFERENCE,
                                                      sourceNode="n01"))["code"])
        self.assertEqual("WORKFLOW_SOURCE_REFERENCE_INVALID",
                         self.replace(reference=dict(SOURCE_REFERENCE,
                                                      rawUrl="https://x"))["code"])
        self.assertEqual("WORKFLOW_SOURCE_REFERENCE_INVALID",
                         self.replace(reference=dict(SOURCE_REFERENCE,
                                                      credential="secret"))["code"])
        self.assertEqual("WORKFLOW_SOURCE_REFERENCE_INVALID",
                         self.replace(reference=dict(SOURCE_REFERENCE,
                                                      kind="other"))["code"])
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


class MaterialAttemptTestCase(RevalidationTestCase):
    """The affected chain is revalidated on material attempts."""

    def drive(self, node, name, result):
        """The agent answers the current attempt of the node."""
        entry = self.instance(node)[-1]
        submitted = submit(self.engine, self.runtime, self.work, node,
                           entry["attempt"], name, result,
                           input_digest=entry["body"].get("input_digest"))
        return submitted

    def test_the_affected_chain_re_runs_on_material_attempts(self):
        receipt = self.replace()
        self.assertEqual("accepted", receipt["decision"], receipt)
        # the chain starts at the first consumer
        self.assertEqual("n01", self.runtime.get_work(self.work)["workflow_current"])
        self.engine.advance(self.work, 2000)
        n01 = self.instance("n01")
        self.assertEqual(2, len(n01))
        # the new attempt is a material attempt, and the attempt number is
        # monotonic: the old attempt stays where it was
        self.assertEqual("material", n01[1]["body"]["trigger"])
        self.assertEqual(1, n01[1]["body"]["material_generation"])
        self.assertEqual("completed", n01[0]["state"])
        self.assertTrue(n01[0]["body"]["check_results"])
        # the agent is asked again under a new identity, and the withdrawn
        # one is cancelled
        intents = self.rows("SELECT id,status FROM workflow_intents "
                             "WHERE work_id=? AND node='n01' ORDER BY id",
                             (self.work,))
        self.assertEqual(2, len(intents))
        # the withdrawn prompt is not pending any more, and the new one is
        self.assertNotEqual("pending", intents[0][1])
        self.assertEqual("pending", intents[1][1])
        # the new attempt runs on the new material
        submitted = self.drive("n01", "intake", VALID_INTAKE)
        self.assertEqual("accepted", submitted["decision"], submitted)
        self.assertEqual(2, self.object_revision("intake")["revision"])
        # the second consumer is revalidated next, on the material the
        # first one produced
        self.engine.advance(self.work, 2001)
        n02 = self.instance("n02")
        self.assertEqual(2, len(n02))
        self.assertEqual("material", n02[1]["body"]["trigger"])
        self.assertEqual(2, n02[1]["body"]["inputs"][0]["revision"])
        submitted = self.drive("n02", "analysis", VALID_ANALYSIS)
        self.assertEqual("accepted", submitted["decision"], submitted)
        self.engine.advance(self.work, 2002)
        n03 = self.instance("n03")
        self.assertEqual(2, len(n03))
        self.assertEqual("material", n03[1]["body"]["trigger"])
        # the wait of the third consumer was bound to the old material: it
        # ended with the recorded reason and the node runs again
        self.assertEqual("cancelled", n03[0]["state"])
        self.assertEqual("MATERIAL_REPLACED", n03[0]["body"]["reason"])

    def test_a_material_attempt_that_fails_on_quality_opens_no_further_attempt(self):
        self.replace()
        self.engine.advance(self.work, 2000)
        failed = self.drive("n01", "intake", {"records": "not a list"})
        self.assertEqual("rejected", failed["decision"], failed)
        self.engine.advance(self.work, 2001)
        # the material attempt failed on quality: the node fails and no
        # further attempt opens. A material attempt has no automatic retry.
        n01 = self.instance("n01")
        self.assertEqual(2, len(n01))
        self.assertEqual("failed", n01[1]["state"])
        self.assertEqual("material", n01[1]["body"]["trigger"])
        # the routing stopped at the failed node: the workflow is not
        # finished in the sense of a delivery, and the acceptance refuses it
        self.assertEqual("finished",
                         self.runtime.get_work(self.work)["workflow_status"])
        self.assertEqual("WORKFLOW_RESULT_INVALID",
                         self.instance("n01")[-1]["body"]["reason"])

    def test_a_second_replacement_is_refused(self):
        first = self.replace()
        self.assertEqual("accepted", first["decision"], first)
        second = self.replace()
        self.assertEqual("rejected", second["decision"], second)
        self.assertEqual("WORKFLOW_REVALIDATION_BUDGET_EXHAUSTED",
                         second["code"])

    def test_the_ticket_of_the_old_attempt_is_stale(self):
        stale = input_digest_of(self.engine, self.work, "n01")
        self.replace()
        self.engine.advance(self.work, 2000)
        refused = submit(self.engine, self.runtime, self.work, "n01", 1,
                         "intake", VALID_INTAKE, input_digest=stale)
        self.assertEqual("rejected", refused["decision"], refused)
        self.assertIn(refused["code"], ("WORKFLOW_ATTEMPT_STALE",
                                        "WORKFLOW_INPUT_STALE"))

    def test_the_view_reports_the_revalidation(self):
        self.replace()
        view = self.engine.instance(self.work)
        plan = view["materialRevalidation"]
        self.assertEqual("revalidating", plan["state"])
        self.assertEqual(1, plan["generation"])
        self.assertEqual("s00", plan["attestation"]["sourceNode"])
        self.assertEqual(["n01", "n02", "n03"],
                         [entry["node"] for entry in plan["affected"]])
        self.assertIn("does not cover", plan["attestation"]["claim"])


class SpentQualityTestCase(RevalidationTestCase):
    """A node whose quality allowance is already spent."""

    spend_quality_first = True

    def test_the_material_attempt_spends_no_quality_allowance(self):
        # the first consumer failed once on quality, so its quality
        # allowance is spent by its second attempt
        n01 = self.instance("n01")
        self.assertEqual(2, len(n01))
        self.assertEqual("quality", n01[1]["body"]["trigger"])
        # the material attempt opens although the quality allowance is
        # spent: the two allowances are separate
        receipt = self.replace()
        self.assertEqual("accepted", receipt["decision"], receipt)
        self.engine.advance(self.work, 2000)
        n01 = self.instance("n01")
        self.assertEqual(3, len(n01))
        self.assertEqual("material", n01[2]["body"]["trigger"])
        self.assertEqual(2, n01[0]["attempt"] + 1)

def legacy_template():
    """A definition published before the material budget existed.

    The live safety definition has no ``material_generations`` field and
    must not be mutated to make a revalidation possible: the core
    allowance of one generation per workflow applies on its own.
    """
    spec = json.loads(json.dumps(REVALIDATION_TEMPLATE))
    for node in spec["nodes"].values():
        node.pop("material_generations", None)
    return spec


def spent_quality_template():
    """A definition whose first consumer has three quality attempts."""
    spec = json.loads(json.dumps(REVALIDATION_TEMPLATE))
    spec["nodes"]["n01"]["max_attempts"] = 3
    return spec


def effect_branch_template():
    """A definition with an automatic node behind the consumers."""
    spec = json.loads(json.dumps(REVALIDATION_TEMPLATE))
    spec["terminal"] = ["n04"]
    spec["nodes"]["n04"] = {"kind": "action", "capability": "work.dispatch",
                            "subject": {"object": "proposal"},
                            "output": {"object": "receipt",
                                       "validation": {"shape": {
                                           "type": "object",
                                           "properties": {"recordId": {"type": "string"}},
                                           "required": ["recordId"]},
                                           "validator": "effect",
                                           "validator_version": "1"}},
                            "max_attempts": 1}
    spec["edges"].append({"from": "n03", "to": "n04"})
    return spec


class LegacyTemplateTestCase(RevalidationTestCase):
    """A definition published before the material budget existed."""

    template = legacy_template()

    def test_the_core_allowance_carries_a_legacy_definition(self):
        for node in self.template["nodes"].values():
            self.assertNotIn("material_generations", node)
        receipt = self.replace()
        self.assertEqual("accepted", receipt["decision"], receipt)
        self.engine.advance(self.work, 2000)
        n01 = self.instance("n01")
        self.assertEqual(2, len(n01))
        self.assertEqual("material", n01[1]["body"]["trigger"])


class SpentQualityTestCase(RevalidationTestCase):
    """A node that used its whole quality allowance."""

    template = spent_quality_template()
    quality_failures = 2

    def test_a_used_up_node_gets_a_fresh_material_attempt(self):
        n01 = self.instance("n01")
        # the node used three of its three quality attempts
        self.assertEqual(3, len(n01))
        self.assertEqual(3, n01[-1]["attempt"])
        receipt = self.replace()
        self.assertEqual("accepted", receipt["decision"], receipt)
        self.engine.advance(self.work, 2000)
        n01 = self.instance("n01")
        # the material attempt is the fourth: the attempt number is
        # monotonic, and the quality allowance was not raised
        self.assertEqual(4, len(n01))
        self.assertEqual(4, n01[3]["attempt"])
        self.assertEqual("material", n01[3]["body"]["trigger"])


class EffectBranchTestCase(RevalidationTestCase):
    """A branch that already carries a business effect."""

    template = effect_branch_template()
    park_wait = False

    def test_a_branch_with_a_prepared_effect_is_refused(self):
        # the third consumer completes and the automatic node behind it
        # prepares its operation
        self.engine.advance(self.work, 2000)
        submitted = submit_valid(self.engine, self.runtime, self.work, "n03",
                                 "proposal")
        self.assertEqual("accepted", submitted["decision"], submitted)
        self.engine.advance(self.work, 2001)
        operations = self.rows("SELECT id,body FROM operations WHERE work_id=?",
                               (self.work,))
        self.assertTrue(operations)
        # the branch carries a prepared effect: the replacement is refused
        # and the effect is never replayed
        receipt = self.replace(waiting_node=None)
        self.assertEqual("rejected", receipt["decision"], receipt)
        self.assertEqual("WORKFLOW_REVALIDATION_EFFECT_PRESENT",
                         receipt["code"])
        self.assertEqual(operations,
                         self.rows("SELECT id,body FROM operations WHERE work_id=?",
                                   (self.work,)))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
