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
                                  decide_command, document, input_digest_of,
                                  instance_of, instantiate, send,
                                  source_reference_validator, submit,
                                  submit_valid, version_of)
    from workflow_support import workflow_demo_validators
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import (POLICY_GOAL, POLICY_ID, POLICY_VERSION,
                                        REVALIDATION_TEMPLATE, RevalidationPolicy,
                                        SourceReferenceAdapter, build,
                                        current_attempt, decide_command, document,
                                        input_digest_of, instance_of, instantiate,
                                        send, source_reference_validator, submit,
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
    settle_review = True
    quality_failures = 0
    park_wait = True
    park_first_consumer = False
    drive_consumers = ("n01", "n02")

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-revalidation-")
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.adapter = SourceReferenceAdapter(
            os.path.join(self.folder, "effects.db"))
        self.runtime, self.engine = build(self.path, policy=RevalidationPolicy(),
                                          validators=revalidation_validators(),
                                          runner="workflow-runner")
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
        if self.park_first_consumer:
            # the first consumer is still working: its prompt is pending,
            # which is where an acknowledgement is meaningful
            return
        for node, name, result in (("n01", "intake", VALID_INTAKE),
                                   ("n02", "analysis", VALID_ANALYSIS)):
            if node not in self.drive_consumers:
                continue
            submitted = submit_valid(self.engine, self.runtime, self.work, node,
                                     name, result)
            self.assertEqual("accepted", submitted["decision"], submitted)
            if node == "n01":
                self.settle_first_consumer()
        if self.park_wait:
            # the third consumer waits for what is still missing
            self.wait()

    def settle_first_consumer(self):
        """A hook for a family whose first consumer needs a review."""

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
            if not waiting_ticket:
                # the node has no ticket: there is nothing to check
                waiting_node = None
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
        # the fan-in node re-pins **both** of its inputs: the analysis it
        # produced and the source it read
        self.assertEqual(2, n02[1]["body"]["inputs"][0]["revision"])
        self.assertEqual(2, n02[1]["body"]["inputs"][1]["revision"])
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
        # the waiting node the manager observed is no longer the current
        # one: the replacement is refused before anything is written
        stale = self.replace()
        self.assertEqual("rejected", stale["decision"], stale)
        self.assertEqual("WORKFLOW_WAITING_NODE_NOT_CURRENT", stale["code"])
        # and without the waiting pair the material generation is spent
        second = self.replace(waiting_node=None)
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

    def test_the_acceptance_refuses_a_pending_revalidation(self):
        # the work carries a revalidation that has not run yet
        self.replace()
        receipt = self.engine.command(
            "workflow-runner", uuid.uuid4().hex, self.work,
            "finalize_workflow_success", {},
            version_of(self.runtime, self.work))
        self.assertEqual("rejected", receipt["decision"], receipt)
        self.assertEqual("WORKFLOW_REVALIDATION_PENDING", receipt["code"])

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


def approval_branch_template():
    """A definition with a human approval behind the consumers."""
    spec = json.loads(json.dumps(REVALIDATION_TEMPLATE))
    spec["terminal"] = ["n03"]
    spec["nodes"]["h01"] = {"kind": "human", "evidence_kind": "safety_review",
                            "authority": "reviewer-a",
                            "subject": {"object": "analysis"},
                            "max_attempts": 1}
    spec["edges"] = [{"from": "s00", "to": "n01"}, {"from": "n01", "to": "n02"},
                     {"from": "n02", "to": "h01"}, {"from": "h01", "to": "n03"}]
    return spec


class ApprovalBranchTestCase(RevalidationTestCase):
    """A branch that already carries a human judgement."""

    template = approval_branch_template()
    park_wait = False

    def approve(self):
        """The reviewer approves the analysis the branch judged."""
        entry = self.instance("h01")[-1]
        subject = entry["body"].get("subject") or {}
        decided = send(self.runtime, "reviewer-a", self.work, "record_evidence",
                       {"event_id": uuid.uuid4().hex, "kind": "safety_review",
                        "data": {"decision": "approved",
                                 "digest": subject.get("digest"),
                                 "revision": subject.get("revision"),
                                 "node": "h01", "attempt": entry["attempt"],
                                 "actor": "reviewer-a", "items": []}})
        self.runtime.verify_pending(self.work)
        self.engine.advance(self.work, 2000)
        return decided

    def test_a_human_approval_in_the_branch_blocks_the_revalidation(self):
        decided = self.approve()
        self.assertEqual("accepted", decided["decision"], decided)
        h01 = self.instance("h01")[-1]
        self.assertEqual("completed", h01["state"])
        # the branch carries a human judgement: the replacement is refused
        receipt = self.replace(waiting_node=None)
        self.assertEqual("rejected", receipt["decision"], receipt)
        self.assertEqual("WORKFLOW_REVALIDATION_EFFECT_PRESENT",
                         receipt["code"])
        self.assertIn("decision", receipt["blockers"][0])


def branch_template():
    """A definition with two consumers of the same source."""
    spec = json.loads(json.dumps(REVALIDATION_TEMPLATE))
    spec["terminal"] = ["n03"]
    spec["nodes"]["n04"] = {"kind": "agent", "executor": "agent-executor",
                            "max_attempts": 2,
                            "inputs": [{"object": "sources"}],
                            "output": {"object": "side",
                                       "validation": {"shape": {
                                           "type": "object",
                                           "properties": {"note": {"type": "string"}},
                                           "required": ["note"]},
                                           "validator": "record",
                                           "validator_version": "1"}},
                            "checks": [{"id": "N04-1", "method": "PROGRAM",
                                        "criterion": "The note names itself.",
                                        "criterion_version": "1",
                                        "validator": "record",
                                        "validator_version": "1"}]}
    spec["edges"] = [{"from": "s00", "to": "n01"}, {"from": "n01", "to": "n02"},
                     {"from": "n01", "to": "n04"}, {"from": "n02", "to": "n03"}]
    return spec


class BranchClosureTestCase(RevalidationTestCase):
    """Two consumers of the same source are both invalidated."""

    template = branch_template()
    park_wait = False

    def test_every_consumer_of_the_source_is_invalidated(self):
        # the sibling consumer runs before the replacement
        self.engine.advance(self.work, 2000)
        receipt = self.replace(waiting_node=None)
        self.assertEqual("accepted", receipt["decision"], receipt)
        affected = [entry["node"] for entry in receipt["affected"]]
        # the consumers that were instantiated, and the node behind them
        self.assertIn("n01", affected)
        self.assertIn("n02", affected)
        self.assertIn("n03", affected)
        # the chain is ordered: a consumer comes after what it judged
        self.assertLess(affected.index("n01"), affected.index("n02"))
        self.assertLess(affected.index("n02"), affected.index("n03"))
        # the sibling consumer never ran, so it has no history: it is not
        # invalidated and it proceeds through the ordinary routing
        self.assertNotIn("n04", affected)
        self.assertEqual([], self.instance("n04"))


def review_template():
    """A definition whose first consumer needs an independent review."""
    spec = json.loads(json.dumps(REVALIDATION_TEMPLATE))
    spec["nodes"]["n01"]["review"] = {
        "evidence_kind": "agent_review", "reviewer": "reviewer-v",
        "rubric": {"validator": "review-rubric", "validator_version": "1"}}
    return spec


class StaleBindingTestCase(RevalidationTestCase):
    """The old review and the restart."""

    template = review_template()

    def settle_first_consumer(self):
        """The independent reviewer settles the first consumer."""
        if not self.settle_review:
            return
        entry = self.instance("n01")[-1]
        reviewed = self.review(entry["attempt"], entry["body"]["input_digest"],
                               entry["body"]["result"]["digest"])
        self.assertEqual("accepted", reviewed["decision"], reviewed)
        self.runtime.verify_pending(self.work)
        self.engine.advance(self.work, 1500)

    def review(self, attempt, input_digest, output_digest):
        return send(self.runtime, "reviewer-v", self.work, "record_evidence",
                    {"event_id": uuid.uuid4().hex, "kind": "agent_review",
                     "data": {"node": "n01", "attempt": attempt,
                              "input_digest": input_digest,
                              "output_digest": output_digest,
                              "producer": "reviewer-v", "verdict": "passed",
                              "items": []}})

    def test_an_old_review_never_settles_the_new_attempt(self):
        # the setup drove the first consumer and settled its review
        entry = self.instance("n01")[-1]
        self.assertEqual("completed", entry["state"])
        # the material is replaced and the consumer runs again
        receipt = self.replace()
        self.assertEqual("accepted", receipt["decision"], receipt)
        self.engine.advance(self.work, 2000)
        fresh = self.instance("n01")[-1]
        self.assertEqual(2, fresh["attempt"])
        self.assertEqual("material", fresh["body"]["trigger"])
        # the review of the earlier attempt does not settle the new one
        old = self.review(1, entry["body"]["input_digest"],
                          entry["body"]["result"]["digest"])
        self.assertEqual("accepted", old["decision"], old)
        self.runtime.verify_pending(self.work)
        self.engine.advance(self.work, 2001)
        self.assertEqual("running", self.instance("n01")[-1]["state"])

    def test_the_revalidation_survives_a_restart(self):
        receipt = self.replace()
        self.assertEqual("accepted", receipt["decision"], receipt)
        # a fresh engine reads the plan and continues the chain
        _, engine2 = build(self.path, policy=RevalidationPolicy(),
                           validators=revalidation_validators(),
                           runner="workflow-runner")
        engine2.advance(self.work, 2000)
        n01 = self.instance("n01")
        self.assertEqual(2, len(n01))
        self.assertEqual("material", n01[1]["body"]["trigger"])


class OldAcknowledgementTestCase(RevalidationTestCase):
    """An acknowledgement of the withdrawn prompt.

    The first consumer is still working when the manager acknowledges its
    prompt: that is where an acknowledgement is meaningful.
    """

    park_first_consumer = True

    def test_an_old_acknowledgement_does_not_swallow_the_new_prompt(self):
        # the withdrawn prompt is acknowledged before the replacement
        intent = self.rows("SELECT id FROM workflow_intents WHERE work_id=? "
                           "AND node='n01' AND kind='agent_task'", (self.work,))
        self.assertEqual(1, len(intent))
        acknowledged = self.engine.acknowledge_intent("coordinator", intent[0][0])
        self.assertEqual("accepted", acknowledged["decision"], acknowledged)
        receipt = self.replace()
        self.assertEqual("accepted", receipt["decision"], receipt)
        self.engine.advance(self.work, 2000)
        # the new prompt is a new intent, and it is pending
        intents = self.rows("SELECT id,status FROM workflow_intents "
                            "WHERE work_id=? AND node='n01' AND kind='agent_task' "
                            "ORDER BY id", (self.work,))
        self.assertEqual(2, len(intents))
        self.assertEqual("acknowledged", intents[0][1])
        self.assertEqual("pending", intents[1][1])


class PublishedValidationTestCase(RevalidationTestCase):
    """The new reference is judged by the published source validation."""

    def test_a_manifest_missing_a_field_is_refused(self):
        before = self.objects()
        reference = {key: value for key, value in SOURCE_REFERENCE.items()
                     if key != "scope"}
        refused = self.replace(reference=reference)
        self.assertEqual("rejected", refused["decision"], refused)
        self.assertEqual("WORKFLOW_SOURCE_REFERENCE_REJECTED", refused["code"])
        # nothing was written: no revision, no invalidation, no event
        self.assertEqual(before, self.objects())
        self.assertEqual([], [entry for entry in self.revalidation()
                               if entry["node"] != "n01"])
        # and the material generation was not spent
        accepted = self.replace()
        self.assertEqual("accepted", accepted["decision"], accepted)

    def test_a_manifest_with_a_malformed_field_is_refused(self):
        before = self.objects()
        refused = self.replace(reference=dict(SOURCE_REFERENCE, scope=42))
        self.assertEqual("rejected", refused["decision"], refused)
        self.assertEqual("WORKFLOW_SOURCE_REFERENCE_REJECTED", refused["code"])
        self.assertEqual(before, self.objects())
        # the finding names the shape or the validator that refused it
        codes = [finding.get("code") for finding in refused["blockers"]]
        self.assertTrue(any(code in ("SHAPE_TYPE", "SOURCE_REFERENCE_INCOMPLETE")
                            for code in codes), refused["blockers"])

    def objects(self):
        return self.rows("SELECT name,revision,digest,body FROM workflow_objects "
                         "ORDER BY name,revision")

    def revalidation(self):
        plan = self.runtime.get_work(self.work).get("material_revalidation") or {}
        return plan.get("affected") or []


class InvalidatedAttemptTestCase(RevalidationTestCase):
    """A descendant that is still working when the material is replaced."""

    drive_consumers = ("n01",)
    park_wait = False

    def test_an_old_downstream_result_is_refused_immediately(self):
        # the second consumer is still working on the old material
        running = self.instance("n02")[-1]
        self.assertEqual("running", running["state"])
        old_digest = running["body"]["input_digest"]
        receipt = self.replace(waiting_node=None)
        self.assertEqual("accepted", receipt["decision"], receipt)
        # its candidate, produced from the material that was replaced, is
        # refused at once - before any advance opens the material attempt
        refused = submit(self.engine, self.runtime, self.work, "n02",
                         running["attempt"], "analysis", VALID_ANALYSIS,
                         input_digest=old_digest)
        self.assertEqual("rejected", refused["decision"], refused)
        self.assertEqual("WORKFLOW_NODE_INVALIDATED", refused["code"])
        # nothing was written: no analysis object, no event, no new attempt
        self.assertEqual([], self.rows("SELECT name FROM workflow_objects "
                                       "WHERE work_id=? AND name='analysis'",
                                       (self.work,)))
        self.assertEqual(1, len(self.instance("n02")))
        self.assertEqual("running", self.instance("n02")[-1]["state"])
        self.assertEqual(old_digest, self.instance("n02")[-1]["body"]["input_digest"])


def pending_review_template():
    """A definition whose second consumer needs an independent review."""

    spec = json.loads(json.dumps(REVALIDATION_TEMPLATE))
    spec["nodes"]["n02"]["review"] = {
        "evidence_kind": "agent_review", "reviewer": "reviewer-v",
        "rubric": {"validator": "review-rubric", "validator_version": "1"}}
    return spec


class PendingReviewTestCase(RevalidationTestCase):
    """A consumer that waits for its review when the material is replaced."""

    template = review_template()
    park_wait = False
    drive_consumers = ("n01",)
    settle_review = False

    def review(self, attempt, input_digest, output_digest):
        return send(self.runtime, "reviewer-v", self.work, "record_evidence",
                    {"event_id": uuid.uuid4().hex, "kind": "agent_review",
                     "data": {"node": "n01", "attempt": attempt,
                              "input_digest": input_digest,
                              "output_digest": output_digest,
                              "producer": "reviewer-v", "verdict": "passed",
                              "items": []}})

    def test_an_old_review_is_not_accepted_for_the_invalidated_attempt(self):
        # the consumer waits for its independent review
        entry = self.instance("n01")[-1]
        self.assertEqual("submitted", entry["state"])
        receipt = self.replace(waiting_node=None)
        self.assertEqual("accepted", receipt["decision"], receipt)
        # the review of the invalidated attempt arrives
        reviewed = self.review(entry["attempt"], entry["body"]["input_digest"],
                               entry["body"]["result"]["digest"])
        self.assertEqual("accepted", reviewed["decision"], reviewed)
        self.runtime.verify_pending(self.work)
        # the node did not settle on the old review: the material attempt
        # opened instead, and nothing of the old review was materialized
        fresh = self.instance("n01")[-1]
        self.assertEqual(2, fresh["attempt"])
        self.assertEqual("material", fresh["body"]["trigger"])
        self.assertNotEqual("completed", fresh["state"])
        self.assertNotIn("completed", [entry["state"]
                                       for entry in self.instance("n01")])
        # and no check of the old review was materialized on the new attempt
        self.assertEqual([], fresh["body"].get("check_results") or [])
        # the old attempt is withdrawn with the recorded reason, and it
        # keeps its history: the candidate it judged is still on the record
        old = self.instance("n01")[0]
        self.assertEqual("cancelled", old["state"])
        self.assertEqual("MATERIAL_REPLACED", old["body"]["reason"])
        self.assertIsNotNone(old["body"].get("result"))
        self.assertIsNotNone(old["body"].get("output"))


class InvalidatedDecisionTestCase(RevalidationTestCase):
    """A human node that waits for a decision when the material is replaced."""

    template = approval_branch_template()
    park_wait = False

    def test_an_old_decision_is_refused_immediately(self):
        entry = self.instance("h01")[-1]
        self.assertEqual("running", entry["state"])
        subject = entry["body"]["subject"]
        receipt = self.replace(waiting_node=None)
        self.assertEqual("accepted", receipt["decision"], receipt)
        # the decision made on the material that was replaced is refused
        # at once
        decided = decide_command(self.engine, self.runtime, self.work,
                                 "safety_review", "reviewer-a", "approved",
                                 subject["digest"], subject["revision"],
                                 node="h01", attempt=entry["attempt"],
                                 actor="reviewer-a", items=[])
        self.assertEqual("rejected", decided["decision"], decided)
        self.assertEqual("WORKFLOW_NODE_INVALIDATED", decided["code"])
        # the human node keeps waiting
        self.assertEqual("running", self.instance("h01")[-1]["state"])


class WaitingNodeTestCase(RevalidationTestCase):
    """The waiting node the manager states must be the current one."""

    def test_the_waiting_node_must_be_the_current_waiting_node(self):
        # a node that is not waiting
        refused = self.replace(waiting_node="n01",
                               waiting_ticket=input_digest_of(self.engine,
                                                             self.work, "n01"))
        self.assertEqual("rejected", refused["decision"], refused)
        self.assertEqual("WORKFLOW_WAITING_NODE_NOT_CURRENT", refused["code"])
        # a node that does not exist
        refused = self.replace(waiting_node="n99", waiting_ticket="0" * 64)
        self.assertEqual("rejected", refused["decision"], refused)
        self.assertEqual("WORKFLOW_WAITING_NODE_NOT_CURRENT", refused["code"])
        # the current waiting node with a ticket that is not current
        refused = self.replace(waiting_ticket="0" * 64)
        self.assertEqual("rejected", refused["decision"], refused)
        self.assertEqual("WORKFLOW_WAITING_TICKET_STALE", refused["code"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
