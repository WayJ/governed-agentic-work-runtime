"""A human node's named output may be declared for some decisions only.

A human node that declares a named acceptance output needs the record for
every decision today, so a **rejection** - which has no business effect and
no acceptance record by design - leaves the node running with
``WORKFLOW_OUTPUT_MISSING`` and never reaches its ``on_reject`` branch.

A published human node may now narrow that requirement explicitly. The
default is unchanged: a declared output is required for every decision.
The narrowing is protected material (part of the published definition, and
never caller data), it is human-only, and the checks, the audit trail and
the routing of an authentic decision are all preserved.
"""

import json
import os
import sqlite3
import tempfile
import unittest

from work_runtime.runtime import Runtime
from work_runtime.workflow import WorkflowEngine
from work_runtime.workflow_demo import (EFFECT_SHAPE, INTAKE_SHAPE, RECORD_SHAPE,
                                         WorkflowDemoPolicy, workflow_demo_grants,
                                         workflow_demo_validators)

try:
    from workflow_support import submit_valid, version_of
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import submit_valid, version_of

WORK_ID = "W-1"
RUNNER = "workflow-runner"
INTAKE = {"records": [{"id": "R-1", "source": "site-log"}], "standard": "STD-1"}


class OpenPolicy(WorkflowDemoPolicy):
    """The demonstration family with its obligation already satisfied."""

    def evaluate(self, work, evidence):
        return [{"id": "R01:" + work["document"]["id"], "rule_id": "R01",
                 "subject": work["document"]["id"], "applicability": "applicable",
                 "fulfillment": "satisfied",
                 "explanation": "The obligation is satisfied in this fixture"}]


def conditional_template(on_decisions=None, rework=True,
                         template_id="conditional-output", version="t1"):
    """A human node that judges the material and may archive a record."""
    human = {"kind": "human", "evidence_kind": "safety_review",
             "authority": "reviewer-a", "subject": {"object": "intake"},
             "output": {"object": "acceptance",
                        "validation": {"shape": RECORD_SHAPE,
                                       "validator": "record",
                                       "validator_version": "1"}},
             "checks": [{"id": "N02-1", "method": "HUMAN",
                         "criterion": "The material is accepted as it stands.",
                         "criterion_version": "1",
                         "validator": "safety-review",
                         "validator_version": "1"}]}
    if on_decisions is not None:
        human["output"]["on_decisions"] = list(on_decisions)
    if rework:
        human["on_reject"] = "n01"
    return {"id": template_id, "version": version,
            "policy_family": "workflow-demo", "entry": "n01",
            "terminal": ["n02"],
            "nodes": {
                "n01": {"kind": "agent", "executor": "agent-executor",
                        "max_attempts": 2,
                        "output": {"object": "intake",
                                   "validation": {"shape": INTAKE_SHAPE,
                                                  "validator": "intake",
                                                  "validator_version": "1"}},
                        "checks": [{"id": "N01-1", "method": "PROGRAM",
                                    "criterion": "Every record names its source.",
                                    "criterion_version": "1",
                                    "validator": "intake",
                                    "validator_version": "1"}]},
                "n02": human},
            "edges": [{"from": "n01", "to": "n02"}]}


class ConditionalOutputTestCase(unittest.TestCase):
    """The fixture: one agent node, one human node, one named output."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-conditional-")
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.counter = 0
        self.runtime, self.engine = self.build()
        self.template = conditional_template()
        published = self.engine.publish_template("coordinator", self.template)
        self.assertEqual(published["decision"], "accepted", published)

    # -- helpers ---------------------------------------------------------

    def build(self):
        grants = workflow_demo_grants()
        grants[RUNNER] = {"workflow.finalize"}
        runtime = Runtime(self.path, OpenPolicy(), grants)
        engine = WorkflowEngine(runtime, workflow_demo_validators(), runner=RUNNER)
        return runtime, engine

    def next_id(self, label):
        self.counter += 1
        return label + "-" + str(self.counter)

    def publish(self, template):
        published = self.engine.publish_template("coordinator", template)
        return published

    def instantiate(self, template):
        self.template = template
        published = self.publish(template)
        self.assertEqual(published["decision"], "accepted", published)
        self.runtime.command("coordinator", self.next_id("create"), WORK_ID,
                             "create_work",
                             {"document": {"id": "H-001", "subject": "east parapet"}},
                             None)
        self.runtime.command("coordinator", self.next_id("contract"), WORK_ID,
                             "bind_contract",
                             {"policy_id": "workflow-demo",
                              "policy_version": "demo-1",
                              "goal": "workflow.completed"},
                             version_of(self.runtime, WORK_ID))
        self.runtime.command("coordinator", self.next_id("plan"), WORK_ID,
                             "revise_plan",
                             {"steps": ["n01", "n02"], "open_requirements": [],
                              "replan_when": []},
                             version_of(self.runtime, WORK_ID))
        receipt = self.engine.command("coordinator", self.next_id("bind"), WORK_ID,
                                      "bind_workflow",
                                      {"template_id": template["id"],
                                       "template_version": template["version"],
                                       "parameters": {"subject": "east parapet"}},
                                      version_of(self.runtime, WORK_ID))
        self.assertEqual(receipt["decision"], "accepted", receipt)

    def drive_to_human(self, template=None):
        """The agent produced the material; the human node is waiting."""
        self.instantiate(template if template is not None else self.template)
        self.engine.advance(WORK_ID, 1000)
        submitted = submit_valid(self.engine, self.runtime, WORK_ID, "n01", "intake")
        self.assertEqual(submitted["decision"], "accepted", submitted)
        self.engine.advance(WORK_ID, 1000)
        return self.runtime.get_work(WORK_ID)

    def subject_reference(self):
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT revision,digest FROM workflow_objects "
                             "WHERE work_id=? AND name='intake' ORDER BY revision "
                             "DESC LIMIT 1", (WORK_ID,)).fetchone()
        finally:
            db.close()
        return {"revision": row[0], "digest": row[1]}

    def decide(self, decision="approved", result=None, attempt=1,
               actor="reviewer-a", source="reviewer-a", command_id=None,
               expected_version=None, extra=None):
        reference = self.subject_reference()
        verdict = {"approved": "passed", "rejected": "failed",
                   "request_material": "insufficient"}[decision]
        item = {"check": "N02-1", "verdict": verdict,
                "reason": "the material was judged against the criterion"}
        if decision == "approved":
            item["evidence"] = ["intake#revision-" + str(reference["revision"])]
        payload = {"node": "n02", "attempt": attempt, "decision": decision,
                   "digest": reference["digest"], "revision": reference["revision"],
                   "actor": actor, "items": [item]}
        if result is not None:
            payload["result"] = result
        if extra:
            payload.update(extra)
        receipt = self.engine.command(
            source, command_id or self.next_id("decision"), WORK_ID,
            "record_decision", payload,
            version_of(self.runtime, WORK_ID) if expected_version is None
            else expected_version)
        if receipt.get("decision") == "accepted":
            self.runtime.verify_pending(WORK_ID)
        return receipt

    def record(self, record_id="ACC-1"):
        return {"recordId": record_id, "kind": "safety_review",
                "actor": "reviewer-a", "items": ["M-1"]}

    def node(self, node="n02"):
        for entry in self.engine.instance(WORK_ID)["nodes"]:
            if entry["node"] == node:
                return entry
        return {}

    def stored_node(self, node="n02"):
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT body FROM workflow_nodes WHERE work_id=? AND "
                             "node=? ORDER BY attempt DESC LIMIT 1",
                             (WORK_ID, node)).fetchone()
        finally:
            db.close()
        return json.loads(row[0]) if row else {}

    def object_rows(self, name="acceptance"):
        db = sqlite3.connect(self.path)
        try:
            return db.execute("SELECT * FROM workflow_objects WHERE work_id=? AND "
                              "name=?", (WORK_ID, name)).fetchall()
        finally:
            db.close()

    def proof_ids(self, kind="safety_review"):
        db = sqlite3.connect(self.path)
        try:
            return [body["id"] for body in
                    (json.loads(row[0]) for row in db.execute(
                        "SELECT body FROM evidence WHERE work_id=?", (WORK_ID,)))
                    if body.get("kind") == kind]
        finally:
            db.close()


class DefaultSemanticsTests(ConditionalOutputTestCase):
    """Without the declaration, every decision needs the named output."""

    def test_a_rejection_still_needs_the_named_output(self):
        self.drive_to_human()
        receipt = self.decide("rejected")
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.engine.advance(WORK_ID, 1000)
        node = self.node()
        self.assertEqual(node["state"], "running")
        self.assertEqual(self.object_rows(), [])
        codes = [finding["code"] for finding in node.get("findings") or []]
        self.assertIn("WORKFLOW_OUTPUT_MISSING", codes)
        # And the routing did not move: the rework branch was not taken.
        work = self.runtime.get_work(WORK_ID)
        self.assertEqual(work["workflow_current"], "n02")

    def test_an_approval_still_writes_the_named_output(self):
        self.drive_to_human()
        receipt = self.decide("approved", result=self.record())
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.engine.advance(WORK_ID, 1000)
        self.assertEqual(self.node()["state"], "completed")
        self.assertEqual(len(self.object_rows()), 1)


class NarrowedOutputTests(ConditionalOutputTestCase):
    """A published human node may narrow the decisions its output applies to."""

    def narrowed(self, rework=True, template_id="conditional-narrowed"):
        return conditional_template(on_decisions=["approved"], rework=rework,
                                    template_id=template_id)

    def test_a_rejection_settles_the_node_without_an_output(self):
        self.drive_to_human(self.narrowed())
        receipt = self.decide("rejected")
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.engine.advance(WORK_ID, 1000)
        node = self.node()
        self.assertEqual(node["state"], "completed")
        self.assertEqual(node["outcome"], "rejected")
        # No acceptance record was invented for a rejection.
        self.assertEqual(self.object_rows(), [])
        self.assertEqual(self.stored_node()["quality"]["mode"], "exempt")
        # The audit and the check evidence are preserved.
        self.assertTrue(self.proof_ids())
        checks = self.stored_node().get("check_results") or []
        self.assertTrue(checks)
        self.assertEqual(checks[0]["checkId"], "N02-1")
        self.assertEqual(checks[0]["verdict"], "failed")

    def test_a_rejection_takes_the_rework_branch(self):
        self.drive_to_human(self.narrowed())
        receipt = self.decide("rejected")
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.engine.advance(WORK_ID, 1000)
        work = self.runtime.get_work(WORK_ID)
        # The declared on_reject branch is taken: the agent runs again.
        self.assertEqual(work["workflow_current"], "n01")
        self.assertEqual(self.node("n01")["attempt"], 2)
        self.assertEqual(self.node("n01")["state"], "running")

    def test_an_approval_still_requires_the_named_output(self):
        self.drive_to_human(self.narrowed())
        receipt = self.decide("approved")
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.engine.advance(WORK_ID, 1000)
        self.assertEqual(self.node()["state"], "running")
        self.assertEqual(self.object_rows(), [])

    def test_an_approval_still_validates_and_binds_the_named_output(self):
        self.drive_to_human(self.narrowed())
        receipt = self.decide("approved", result=self.record())
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.engine.advance(WORK_ID, 1000)
        self.assertEqual(self.node()["state"], "completed")
        self.assertEqual(len(self.object_rows()), 1)
        binding = self.stored_node().get("output_binding") or {}
        self.assertEqual(binding.get("actor"), "reviewer-a")
        self.assertEqual(binding.get("subject", {}).get("digest"),
                         self.subject_reference()["digest"])

    def test_an_approval_is_never_exempt(self):
        """No declaration may exempt the acceptance record of an approval."""
        self.drive_to_human(conditional_template(
            on_decisions=["rejected"], template_id="conditional-no-approval"))
        receipt = self.decide("approved")
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.engine.advance(WORK_ID, 1000)
        # The approval still needs its record: the node keeps waiting.
        self.assertEqual(self.node()["state"], "running")
        self.assertEqual(self.object_rows(), [])

    def test_a_supplied_record_for_an_exempt_decision_is_refused(self):
        self.drive_to_human(self.narrowed())
        receipt = self.decide("rejected", result=self.record())
        self.assertEqual(receipt["decision"], "rejected", receipt)
        self.assertEqual(receipt["code"], "WORKFLOW_OUTPUT_NOT_REQUIRED")
        # Nothing was written: no acceptance record, no decision proof.
        self.assertEqual(self.object_rows(), [])
        self.assertEqual(self.proof_ids(), [])
        self.assertEqual(self.node()["state"], "running")

    def test_a_request_for_more_material_still_waits(self):
        self.drive_to_human(self.narrowed())
        receipt = self.decide("request_material")
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.engine.advance(WORK_ID, 1000)
        node = self.node()
        self.assertEqual(node["state"], "running")
        self.assertEqual(self.object_rows(), [])

    def test_a_rejection_cannot_be_finalized(self):
        """A workflow that ended on a rejection is never accepted."""
        self.drive_to_human(self.narrowed(rework=False,
                                          template_id="conditional-terminal"))
        receipt = self.decide("rejected")
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.engine.advance(WORK_ID, 1000)
        work = self.runtime.get_work(WORK_ID)
        self.assertEqual(work["workflow_status"], "finished", work)
        self.assertEqual(work["workflow_terminal"]["outcome"], "rejected", work)
        final = self.engine.command(RUNNER, "final-1", WORK_ID,
                                    "finalize_workflow_success", {},
                                    version_of(self.runtime, WORK_ID))
        self.assertEqual(final["decision"], "rejected", final)
        self.assertEqual(final["code"], "WORKFLOW_TERMINAL_NOT_COMPLETED")
        self.assertIsNone(work.get("workflow_finalization"))


class DeclarationLintTests(ConditionalOutputTestCase):
    """The narrowing is protected material, and it is human-only."""

    def test_other_node_kinds_refuse_the_option(self):
        for kind, node in (("agent", {"kind": "agent", "executor": "agent-executor",
                                      "output": {"object": "x",
                                                 "on_decisions": ["approved"]}}),
                           ("action", {"kind": "action",
                                       "capability": "work.dispatch",
                                       "subject": {"object": "x"},
                                       "output": {"object": "x",
                                                  "on_decisions": ["approved"]}}),
                           ("wait", {"kind": "wait", "deadline_s": 60,
                                     "match": {"evidence_kind": "accepted"},
                                     "output": {"object": "x",
                                                "on_decisions": ["approved"]}})):
            template = conditional_template(
                template_id="conditional-kind-" + kind)
            template["nodes"]["n03"] = node
            template["edges"].append({"from": "n02", "to": "n03"})
            published = self.publish(template)
            self.assertEqual(published["decision"], "rejected", published)
            codes = [finding["code"] for finding in published.get("findings") or []]
            self.assertIn("NODE_FIELD_UNKNOWN", codes)

    def test_a_malformed_declaration_is_refused(self):
        for value in ("approved", ["approved", "maybe"], [1], {"decision": "approved"}):
            template = conditional_template(
                on_decisions=None, template_id="conditional-bad-" + str(len(str(value))))
            template["nodes"]["n02"]["output"]["on_decisions"] = value
            published = self.publish(template)
            self.assertEqual(published["decision"], "rejected", published)
            self.assertTrue(published.get("findings"))

    def test_a_caller_cannot_narrow_the_declaration(self):
        self.drive_to_human(self.narrowed_template())
        with self.assertRaises(Exception):
            self.decide("rejected", extra={"on_decisions": ["rejected"]})
        self.assertEqual(self.proof_ids(), [])

    def narrowed_template(self):
        return conditional_template(on_decisions=["approved"],
                                    template_id="conditional-caller")


class UnchangedGuardsTests(ConditionalOutputTestCase):
    """The narrowing changes nothing about staleness, compare-and-swap or authority."""

    def setUp(self):
        super().setUp()
        self.drive_to_human(conditional_template(
            on_decisions=["approved"], template_id="conditional-guards"))

    def test_a_stale_attempt_is_refused(self):
        receipt = self.decide("rejected", attempt=2)
        self.assertEqual(receipt["decision"], "rejected", receipt)
        self.assertEqual(receipt["code"], "WORKFLOW_ATTEMPT_STALE")

    def test_a_foreign_actor_is_refused(self):
        receipt = self.decide("rejected", actor="someone-else")
        self.assertEqual(receipt["decision"], "rejected", receipt)
        self.assertEqual(receipt["code"], "WORKFLOW_AUTHORITY_MISMATCH")

    def test_a_stale_compare_and_swap_is_refused(self):
        receipt = self.decide("rejected", expected_version=1)
        self.assertEqual(receipt["decision"], "rejected", receipt)
        self.assertEqual(receipt["code"], "STATE_VERSION_CONFLICT")


if __name__ == "__main__":
    unittest.main()
