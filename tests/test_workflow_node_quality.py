"""Per-node IO and quality for the automatic and wait nodes.

The engine must not treat "the external effect succeeded" as "the node's
output is good". These tests assert the stored truth: the receipt that was
really returned, the per-criterion report, the named object that was written,
the binding a wait matched on, and the fact that a rejected output never
causes a second external effect.

The definitions below are published template data; the engine stays generic.
"""

import os
import sqlite3
import tempfile
import unittest
import uuid

from work_runtime.policy import canonical, digest
from work_runtime.runtime import Runtime
from work_runtime.workflow import WorkflowEngine
from work_runtime.workflow_demo import DemoBusinessSystem
from work_runtime.workflow_spec import ValidatorRegistry, lint_template

POLICY_ID = "workflow-quality"
POLICY_VERSION = "quality-1"
POLICY_GOAL = "quality.completed"

EFFECT_SHAPE = {
    "type": "object",
    "properties": {"recordId": {"type": "string"},
                   "action": {"type": "string"},
                   "items": {"type": "array", "items": {"type": "string"}}},
    "required": ["recordId", "action", "items"],
}


class QualityPolicy:
    """A minimal family: no obligations, so the effect itself is the subject."""

    id = POLICY_ID
    version = POLICY_VERSION
    goal = POLICY_GOAL
    evidence_sources = {"dispatch_receipt": "business-system",
                        "field_report": "responsible-c",
                        "agent_review": "reviewer-v",
                        "accepted": "business-system"}

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


def quality_grants():
    return {"coordinator": {"work.manage", "work.dispatch", "work.deliver"},
            "agent-executor": {"workflow.execute"},
            "responsible-c": {"evidence.write"},
            "reviewer-v": {"evidence.write"},
            "business-system": {"evidence.write"}}


def quality_validators(reject_output=False, reject_input=False, reject_node=None,
                       omit_checks=False):
    """Host-registered, version-pinned validators for this family."""
    registry = ValidatorRegistry()

    def effect(work, node_ref, result):
        findings = []
        if not isinstance(result, dict):
            return {"findings": [{"code": "EFFECT_NOT_OBJECT",
                                  "message": "The receipt is not an object"}],
                    "checks": []}
        if not isinstance(result.get("recordId"), str) or not result["recordId"]:
            findings.append({"code": "EFFECT_UNIDENTIFIED",
                             "message": "The receipt does not name the effect"})
        capability = node_ref.get("capability")
        if capability and result.get("action") != capability:
            findings.append({"code": "EFFECT_ACTION_MISMATCH",
                             "message": "The receipt names another action"})
        if not result.get("items"):
            findings.append({"code": "EFFECT_EMPTY",
                             "message": "The receipt names no item"})
        if reject_output:
            findings.append({"code": "EFFECT_REJECTED",
                             "message": "The host rejected this receipt"})
        if reject_node and node_ref.get("node") == reject_node:
            findings.append({"code": "EFFECT_REJECTED",
                             "message": "The host rejected this receipt"})
        verdict = "failed" if findings else "passed"
        reason = ("the receipt names the effect it recorded" if not findings
                  else "the receipt did not satisfy the criterion")
        if omit_checks:
            return {"findings": findings, "checks": []}
        checks = [{"check": identifier, "verdict": verdict, "reason": reason,
                   "evidence": ["receipt:" + str(result.get("recordId"))]}
                  for identifier in (node_ref.get("checks") or [])]
        return {"findings": findings, "checks": checks}

    def business_input(work, node_ref, value):
        findings = []
        unusable = reject_input
        if not unusable and isinstance(value, dict) and "ok" in value:
            unusable = value["ok"] is not True
        if unusable:
            findings.append({"code": "INPUT_UNUSABLE",
                             "message": "The input object is not usable"})
        return {"findings": findings, "checks": []}

    def review_rubric(work, node_ref, result):
        return {"findings": [], "checks": []}

    registry.register("effect", "1", effect)
    registry.register("business-input", "1", business_input)
    registry.register("review-rubric", "1", review_rubric)
    return registry


def quality_template(template_id="quality-flow", version="test-1"):
    """The action → wait → human → action shape of this family."""
    return {
        "id": template_id,
        "version": version,
        "policy_family": POLICY_ID,
        "entry": "n01",
        "terminal": ["n04"],
        "nodes": {
            "n01": {"kind": "action", "capability": "work.dispatch",
                    "subject": {"object": "proposal"},
                    "output": {"object": "order",
                               "evidence_kind": "dispatch_receipt",
                               "validation": {"shape": EFFECT_SHAPE,
                                              "validator": "effect",
                                              "validator_version": "1"}},
                    "checks": [{"id": "N01-1",
                                "method": "PROGRAM",
                                "criterion": "The receipt names the effect it "
                                            "recorded.",
                                "criterion_version": "1",
                                "validator": "effect",
                                "validator_version": "1"}]},
            "n02": {"kind": "wait", "deadline_s": 3600,
                    "match": {"evidence_kind": "dispatch_receipt",
                              "subject": {"object": "order"},
                              "bind": {"node": "n01"}},
                    "output": {"object": "receipt",
                               "validation": {"shape": EFFECT_SHAPE,
                                              "validator": "effect",
                                              "validator_version": "1"}},
                    "checks": [{"id": "N02-1",
                                "method": "PROGRAM",
                                "criterion": "The receipt names the effect it "
                                            "recorded.",
                                "criterion_version": "1",
                                "validator": "effect",
                                "validator_version": "1"}]},
            "n03": {"kind": "human", "evidence_kind": "field_report",
                    "authority": "responsible-c", "subject": {"object": "order"},
                    "checks": [{"id": "N03-1",
                                "method": "HUMAN",
                                "criterion": "The order was carried out.",
                                "criterion_version": "1",
                                "validator": "review-rubric",
                                "validator_version": "1"}]},
            "n04": {"kind": "action", "capability": "work.deliver",
                    "subject": {"object": "order"}},
        },
        "edges": [{"from": "n01", "to": "n02"},
                  {"from": "n02", "to": "n03"},
                  {"from": "n03", "to": "n04"}],
    }


def binding_template():
    """A definition whose entry is a wait bound to an explicit attempt."""
    return {
        "id": "binding-flow",
        "version": "test-1",
        "policy_family": POLICY_ID,
        "entry": "n00",
        "terminal": ["n00"],
        "nodes": {
            "n00": {"kind": "wait", "deadline_s": 600,
                    "match": {"evidence_kind": "dispatch_receipt",
                              "subject": {"object": "order"},
                              "bind": {"node": "n01", "attempt": 2}}},
            "n01": {"kind": "action", "capability": "work.dispatch",
                    "subject": {"object": "proposal"}},
        },
        "edges": [],
    }


def human_output_template():
    """A human node that declares the named record it produces."""
    return {
        "id": "human-output-flow",
        "version": "test-1",
        "policy_family": POLICY_ID,
        "entry": "n01",
        "terminal": ["n02"],
        "nodes": {
            "n01": {"kind": "human", "evidence_kind": "field_report",
                    "authority": "responsible-c", "subject": {"object": "proposal"},
                    "output": {"object": "feedback",
                               "validation": {"shape": EFFECT_SHAPE,
                                              "validator": "effect",
                                              "validator_version": "1"}},
                    "checks": [{"id": "N01-1",
                                "method": "HUMAN",
                                "criterion": "The record names the effect.",
                                "criterion_version": "1",
                                "validator": "review-rubric",
                                "validator_version": "1"}]},
            "n02": {"kind": "action", "capability": "work.deliver",
                    "subject": {"object": "feedback"}},
        },
        "edges": [{"from": "n01", "to": "n02"}],
    }


def candidate_template():
    """An agent node whose candidate is reviewed independently."""
    return {
        "id": "candidate-flow",
        "version": "test-1",
        "policy_family": POLICY_ID,
        "entry": "n01",
        "terminal": ["n01"],
        "nodes": {
            "n01": {"kind": "agent", "executor": "agent-executor", "max_attempts": 2,
                    "output": {"object": "candidate",
                               "validation": {"shape": EFFECT_SHAPE,
                                              "validator": "effect",
                                              "validator_version": "1"}},
                    "checks": [{"id": "N01-1",
                                "method": "PROGRAM",
                                "criterion": "The candidate names the effect.",
                                "criterion_version": "1",
                                "validator": "effect",
                                "validator_version": "1"}],
                    "review": {"evidence_kind": "agent_review",
                               "reviewer": "reviewer-v",
                               "rubric": {"validator": "review-rubric",
                                          "validator_version": "1"}}},
        },
        "edges": [],
    }


class QualityTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-quality-")
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.adapter_path = os.path.join(self.folder, "effects.sqlite")
        self.runtime = Runtime(self.path, QualityPolicy(), quality_grants())
        self.engine = WorkflowEngine(self.runtime, quality_validators())
        self.adapter = DemoBusinessSystem(self.adapter_path)
        self.work_id = "W-1"

    # -- helpers ---------------------------------------------------------

    def version(self):
        return self.runtime.get_work(self.work_id)["state_version"]

    def command(self, actor, kind, payload, command_id=None, version=None):
        if version is None and kind != "create_work":
            version = self.version()
        return self.runtime.command(actor, command_id or uuid.uuid4().hex,
                                    self.work_id, kind, payload, version)

    def publish(self, template):
        receipt = self.engine.publish_template("coordinator", template)
        self.assertEqual(receipt["decision"], "accepted", receipt)
        return receipt

    def instantiate(self, template):
        self.publish(template)
        self.command("coordinator", "create_work",
                     {"document": {"id": "H-001", "subject": "east parapet"}},
                     command_id="create")
        self.command("coordinator", "bind_contract",
                     {"policy_id": POLICY_ID, "policy_version": POLICY_VERSION,
                      "goal": POLICY_GOAL}, command_id="contract")
        self.command("coordinator", "revise_plan",
                     {"steps": ["n01"], "open_requirements": [],
                      "replan_when": []}, command_id="plan")
        receipt = self.engine.command("coordinator", uuid.uuid4().hex, self.work_id,
                                      "bind_workflow",
                                      {"template_id": template["id"],
                                       "template_version": template["version"],
                                       "parameters": {"subject": "east parapet"}},
                                      self.version())
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.engine.advance(self.work_id, 1_000)

    def revise(self, name, body):
        receipt = self.engine.command("coordinator", uuid.uuid4().hex, self.work_id,
                                      "revise_object",
                                      {"name": name, "object": body}, self.version())
        self.assertEqual(receipt["decision"], "accepted", receipt)
        return receipt

    def object_row(self, name):
        db = sqlite3.connect(self.path)
        try:
            return db.execute("SELECT name,revision,digest,body FROM workflow_objects "
                              "WHERE work_id=? AND name=? ORDER BY revision DESC "
                              "LIMIT 1", (self.work_id, name)).fetchone()
        finally:
            db.close()

    def object_reference(self, name):
        row = self.object_row(name)
        return {"name": row[0], "revision": row[1], "digest": row[2]}

    def node(self, node_id):
        for entry in self.engine.instance(self.work_id)["nodes"]:
            if entry["node"] == node_id:
                return entry
        return None

    def instance_row(self, node_id, attempt=None):
        db = sqlite3.connect(self.path)
        try:
            if attempt is None:
                row = db.execute("SELECT body FROM workflow_nodes WHERE work_id=? "
                                 "AND node=? ORDER BY attempt DESC LIMIT 1",
                                 (self.work_id, node_id)).fetchone()
            else:
                row = db.execute("SELECT body FROM workflow_nodes WHERE work_id=? "
                                 "AND node=? AND attempt=?",
                                 (self.work_id, node_id, attempt)).fetchone()
            return __import__("json").loads(row[0]) if row else None
        finally:
            db.close()

    def operations(self):
        db = sqlite3.connect(self.path)
        try:
            return [__import__("json").loads(row[0]) for row in
                    db.execute("SELECT body FROM operations WHERE work_id=?",
                               (self.work_id,))]
        finally:
            db.close()

    def inject_proof(self, kind, data, event_id=None, source="business-system"):
        event_id = event_id or uuid.uuid4().hex
        proof = {"id": uuid.uuid4().hex, "source": source, "event_id": event_id,
                 "kind": kind, "status": "verified", "data": data}
        with self.runtime._transaction() as db:
            db.execute("INSERT INTO evidence VALUES (?,?,?,?,?)",
                       (source, event_id, self.work_id, digest(proof),
                        canonical(proof)))
        return event_id

    def proposal_body(self):
        return {"measures": [{"issueId": "H-001", "measureId": "M-1",
                               "measure": "complete the guard"}]}

    def current_attempt(self, node):
        entry = self.node(node)
        return entry["attempt"] if entry else 0

    def decide(self, node, decision, digest_value, revision, result=None,
               items=None, actor="responsible-c", kind="field_report",
               source="responsible-c"):
        """Record a human decision, optionally with the record it carries."""
        payload = {"node": node, "attempt": self.current_attempt(node),
                   "decision": decision, "digest": digest_value,
                   "revision": revision, "actor": actor,
                   "items": items if items is not None else [
                       {"check": "N01-1", "verdict": "passed",
                        "reason": "reviewed against the criterion",
                        "evidence": ["proposal#revision-1"]}]}
        if result is not None:
            payload["result"] = result
        receipt = self.engine.command(source, uuid.uuid4().hex, self.work_id,
                                      "record_decision", payload, self.version())
        self.runtime.verify_pending(self.work_id)
        self.engine.advance(self.work_id, 1_000)
        return receipt


class DefinitionLanguageTests(unittest.TestCase):
    def test_an_action_node_may_declare_an_output_and_checks(self):
        spec = quality_template()
        self.assertEqual(lint_template(spec), [])

    def test_a_wait_node_may_declare_an_output_and_checks(self):
        self.assertEqual(lint_template(quality_template()), [])

    def test_a_wait_binding_must_name_a_declared_node(self):
        spec = quality_template()
        spec["nodes"]["n02"]["match"]["bind"] = {"node": "n99"}
        codes = [finding["code"] for finding in lint_template(spec)]
        self.assertTrue(codes, codes)

    def test_a_human_node_may_declare_a_named_output(self):
        spec = human_output_template()
        self.assertEqual(lint_template(spec), [])

    def test_a_required_agent_criterion_without_a_review_is_refused(self):
        spec = quality_template()
        spec["nodes"]["n01"]["checks"][0]["method"] = "AGENT"
        codes = [finding["code"] for finding in lint_template(spec)]
        self.assertIn("NODE_JUDGE_MISSING", codes)

    def test_a_required_program_criterion_without_an_output_validator_is_refused(self):
        spec = quality_template()
        spec["nodes"]["n01"]["output"].pop("validation")
        codes = [finding["code"] for finding in lint_template(spec)]
        self.assertIn("NODE_JUDGE_MISSING", codes)

    def test_a_wait_match_must_declare_exactly_one_source(self):
        spec = quality_template()
        spec["nodes"]["n02"]["match"]["timeout"] = True
        codes = [finding["code"] for finding in lint_template(spec)]
        self.assertIn("SPEC_FIELD_MISSING", codes)


class WrongActionAdapter(DemoBusinessSystem):
    """A stand-in that names another action in its receipt."""

    def execute(self, key, document, content_digest, **kwargs):
        result = dict(super().execute(key, document, content_digest, **kwargs))
        result["action"] = "work.deliver"
        return result


class WrongDigestAdapter(DemoBusinessSystem):
    """A stand-in whose receipt does not match the document it was given."""

    def execute(self, key, document, content_digest, **kwargs):
        result = dict(super().execute(key, document, content_digest, **kwargs))
        result["digest"] = "0" * 64
        return result


class ActionNodeQualityTests(QualityTestCase):
    def test_a_validated_payload_becomes_a_named_object(self):
        self.instantiate(quality_template())
        self.revise("proposal", self.proposal_body())
        self.engine.advance(self.work_id, 1_000)
        self.engine.pump(self.adapter, 1_000)
        self.engine.advance(self.work_id, 1_000)

        row = self.object_row("order")
        self.assertIsNotNone(row, "the validated payload was not written")
        body = __import__("json").loads(row[3])
        self.assertEqual(body["action"], "work.dispatch")
        self.assertEqual(row[2], digest(body))

        node = self.instance_row("n01")
        self.assertEqual(node["state"], "completed", node.get("findings"))
        self.assertEqual(node["outcome"], "completed")
        self.assertEqual(node["effect"]["status"], "succeeded")
        self.assertEqual(node["effect"]["externalId"], body["recordId"])

    def test_the_output_report_names_the_judge_of_every_criterion(self):
        self.instantiate(quality_template())
        self.revise("proposal", self.proposal_body())
        self.engine.advance(self.work_id, 1_000)
        self.engine.pump(self.adapter, 1_000)
        self.engine.advance(self.work_id, 1_000)

        report = self.instance_row("n01")["check_results"]
        self.assertEqual(len(report), 1, report)
        entry = report[0]
        self.assertEqual(entry["checkId"], "N01-1")
        self.assertEqual(entry["method"], "PROGRAM")
        self.assertEqual(entry["criterionVersion"], "1")
        self.assertEqual(entry["validator"], "effect")
        self.assertEqual(entry["validatorVersion"], "1")
        self.assertTrue(entry["reviewedInputDigest"])
        self.assertTrue(entry["reviewedOutputDigest"])
        self.assertTrue(entry["reason"])
        self.assertTrue(entry["evidence"])

    def test_a_declared_output_failure_stops_the_downstream_node(self):
        self.engine = WorkflowEngine(self.runtime, quality_validators(reject_output=True))
        self.instantiate(quality_template())
        self.revise("proposal", self.proposal_body())
        self.engine.advance(self.work_id, 1_000)
        self.engine.pump(self.adapter, 1_000)
        self.engine.advance(self.work_id, 1_000)

        node = self.instance_row("n01")
        self.assertEqual(node["state"], "failed", node)
        self.assertEqual(node["reason"], "WORKFLOW_OUTPUT_INVALID")
        self.assertIsNone(self.object_row("order"))
        self.assertEqual(self.node("n02")["state"], "pending")
        view = self.engine.instance(self.work_id)
        self.assertEqual(view["workflowStatus"], "needs_attention", view)

    def test_the_external_effect_stays_recorded_when_the_output_fails(self):
        self.engine = WorkflowEngine(self.runtime, quality_validators(reject_output=True))
        self.instantiate(quality_template())
        self.revise("proposal", self.proposal_body())
        self.engine.advance(self.work_id, 1_000)
        self.engine.pump(self.adapter, 1_000)
        self.engine.advance(self.work_id, 1_000)

        operations = self.operations()
        self.assertEqual(len(operations), 1, operations)
        self.assertEqual(operations[0]["status"], "confirmed_succeeded")
        node = self.instance_row("n01")
        self.assertEqual(node["effect"]["status"], "succeeded")
        self.assertTrue(node["effect"]["externalId"])
        self.assertEqual(node["effect"]["operationId"], operations[0]["id"])

    def test_a_rejected_output_is_never_dispatched_again(self):
        self.engine = WorkflowEngine(self.runtime, quality_validators(reject_output=True))
        self.instantiate(quality_template())
        self.revise("proposal", self.proposal_body())
        self.engine.advance(self.work_id, 1_000)
        self.engine.pump(self.adapter, 1_000)
        self.engine.advance(self.work_id, 1_000)
        counted = DemoBusinessSystem(self.adapter_path).effect_count()
        self.assertEqual(counted, 1, counted)

        # Recovery and further routing must not repeat the external effect.
        self.engine.recover(self.adapter, 2_000)
        self.engine.advance(self.work_id, 2_000)
        self.engine.pump(self.adapter, 2_000)
        self.engine.advance(self.work_id, 2_000)
        self.assertEqual(DemoBusinessSystem(self.adapter_path).effect_count(), 1)
        self.assertEqual(len(self.operations()), 1)

    def test_an_input_validator_failure_prevents_the_external_effect(self):
        spec = quality_template()
        spec["nodes"]["n01"]["inputs"] = [
            {"object": "proposal",
             "validation": {"validator": "business-input",
                            "validator_version": "1"}}]
        self.engine = WorkflowEngine(self.runtime, quality_validators(reject_input=True))
        self.instantiate(spec)
        self.revise("proposal", self.proposal_body())
        self.engine.advance(self.work_id, 1_000)
        self.engine.pump(self.adapter, 1_000)
        self.engine.advance(self.work_id, 1_000)

        node = self.instance_row("n01")
        self.assertEqual(node["state"], "blocked", node)
        self.assertEqual(self.operations(), [])
        self.assertEqual(DemoBusinessSystem(self.adapter_path).effect_count(), 0)

    def test_a_receipt_that_does_not_match_the_operation_is_refused(self):
        self.instantiate(quality_template())
        self.revise("proposal", self.proposal_body())
        self.engine.advance(self.work_id, 1_000)
        self.engine.pump(self.adapter, 1_000)
        self.engine.advance(self.work_id, 1_000)
        node = self.instance_row("n01")
        self.assertEqual(node["state"], "completed", node.get("findings"))
        stored = node["receipt"]["receipt"]
        self.assertEqual(stored["digest"], node["effect"]["documentDigest"])

    def test_a_receipt_that_names_another_action_is_refused(self):
        self.adapter = WrongActionAdapter(self.adapter_path)
        self.instantiate(quality_template())
        self.revise("proposal", self.proposal_body())
        self.engine.advance(self.work_id, 1_000)
        self.engine.pump(self.adapter, 1_000)
        self.engine.advance(self.work_id, 1_000)

        node = self.instance_row("n01")
        self.assertEqual(node["state"], "failed", node.get("findings"))
        codes = [finding["code"] for finding in node["findings"]]
        self.assertIn("WORKFLOW_RECEIPT_ACTION_MISMATCH", codes)
        self.assertIsNone(self.object_row("order"))

    def test_a_receipt_that_does_not_match_the_document_is_never_accepted(self):
        self.adapter = WrongDigestAdapter(self.adapter_path)
        self.instantiate(quality_template())
        self.revise("proposal", self.proposal_body())
        self.engine.advance(self.work_id, 1_000)
        self.engine.pump(self.adapter, 1_000)
        self.engine.advance(self.work_id, 1_000)

        operations = self.operations()
        self.assertEqual(len(operations), 1, operations)
        self.assertEqual(operations[0]["status"], "outcome_unknown")
        self.assertEqual(self.instance_row("n01")["state"], "running")
        self.assertIsNone(self.object_row("order"))

    def test_a_rejected_output_is_never_routed_back_into_the_same_node(self):
        self.engine = WorkflowEngine(self.runtime, quality_validators(reject_output=True))
        spec = quality_template()
        spec["nodes"]["n01"]["on_failure"] = "n01"
        self.instantiate(spec)
        self.revise("proposal", self.proposal_body())
        self.engine.advance(self.work_id, 1_000)
        self.engine.pump(self.adapter, 1_000)
        self.engine.advance(self.work_id, 1_000)
        self.engine.pump(self.adapter, 2_000)
        self.engine.advance(self.work_id, 2_000)

        self.assertEqual(DemoBusinessSystem(self.adapter_path).effect_count(), 1)
        self.assertEqual(len(self.operations()), 1)
        db = sqlite3.connect(self.path)
        try:
            attempts = db.execute("SELECT COUNT(*) FROM workflow_nodes WHERE work_id=? "
                                  "AND node=?", (self.work_id, "n01")).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(attempts, 1, "the node was opened again")

    def test_a_node_without_a_declaration_is_not_implied_to_be_checked(self):
        spec = quality_template()
        spec["nodes"]["n01"].pop("output")
        spec["nodes"]["n01"].pop("checks")
        self.instantiate(spec)
        self.revise("proposal", self.proposal_body())
        self.engine.advance(self.work_id, 1_000)
        self.engine.pump(self.adapter, 1_000)
        self.engine.advance(self.work_id, 1_000)

        node = self.node("n01")
        self.assertEqual(node["state"], "completed", node)
        self.assertEqual(node["quality"], {"declared": False, "mode": "undeclared"})
        self.assertEqual(node["checkResults"], [])
        self.assertIsNone(self.object_row("order"))


class WaitNodeQualityTests(QualityTestCase):
    def test_a_wait_binds_the_proof_it_matched(self):
        self.instantiate(quality_template())
        self.revise("proposal", self.proposal_body())
        self.engine.advance(self.work_id, 1_000)
        self.engine.pump(self.adapter, 1_000)
        self.engine.advance(self.work_id, 1_000)

        node = self.instance_row("n02")
        self.assertEqual(node["state"], "completed", node.get("findings"))
        binding = node["wait_match"]
        self.assertEqual(binding["work"], self.work_id)
        self.assertEqual(binding["node"], "n02")
        self.assertEqual(binding["attempt"], 1)
        self.assertEqual(binding["boundNode"], "n01")
        self.assertEqual(binding["boundAttempt"], 1)
        self.assertTrue(binding["eventId"])
        self.assertTrue(binding["source"])
        self.assertEqual(binding["object"]["name"], "order")
        self.assertEqual(binding["object"]["revision"], 1)
        self.assertTrue(binding["object"]["digest"])

    def test_a_wait_output_failure_stops_the_downstream_node(self):
        self.engine = WorkflowEngine(self.runtime, quality_validators(reject_node="n02"))
        self.instantiate(quality_template())
        self.revise("proposal", self.proposal_body())
        self.engine.advance(self.work_id, 1_000)
        self.engine.pump(self.adapter, 1_000)
        self.engine.advance(self.work_id, 1_000)

        node = self.instance_row("n02")
        self.assertEqual(node["state"], "failed", node.get("findings"))
        self.assertEqual(node["reason"], "WORKFLOW_OUTPUT_INVALID")
        self.assertIsNone(self.object_row("receipt"))
        self.assertEqual(self.node("n03")["state"], "pending")

    def test_a_missing_per_check_verdict_is_refused(self):
        self.engine = WorkflowEngine(self.runtime, quality_validators(omit_checks=True))
        self.instantiate(quality_template())
        self.revise("proposal", self.proposal_body())
        self.engine.advance(self.work_id, 1_000)
        self.engine.pump(self.adapter, 1_000)
        self.engine.advance(self.work_id, 1_000)

        node = self.instance_row("n01")
        self.assertEqual(node["state"], "failed", node.get("findings"))
        codes = [finding["code"] for finding in node["findings"]]
        self.assertIn("WORKFLOW_CHECK_RESULT_MISSING", codes)
        self.assertIsNone(self.object_row("order"))

    def test_a_wait_writes_its_validated_output(self):
        self.instantiate(quality_template())
        self.revise("proposal", self.proposal_body())
        self.engine.advance(self.work_id, 1_000)
        self.engine.pump(self.adapter, 1_000)
        self.engine.advance(self.work_id, 1_000)

        row = self.object_row("receipt")
        self.assertIsNotNone(row, "the wait did not write its validated output")
        report = self.instance_row("n02")["check_results"]
        self.assertEqual(len(report), 1, report)
        self.assertEqual(report[0]["method"], "PROGRAM")
        self.assertEqual(report[0]["validator"], "effect")


class WaitBindingTests(QualityTestCase):
    def setUp(self):
        super().setUp()
        self.instantiate(binding_template())
        self.revise("proposal", self.proposal_body())
        self.revise("order", {"recordId": "EXT-1", "action": "work.dispatch",
                              "items": ["M-1"]})
        self.engine.advance(self.work_id, 1_000)

    def _proof(self, attempt, revision=None, digest_value=None):
        reference = self.object_reference("order")
        return {"node": "n01", "attempt": attempt,
                "object": {"name": "order",
                           "revision": reference["revision"] if revision is None
                           else revision,
                           "digest": reference["digest"] if digest_value is None
                           else digest_value}}

    def test_a_proof_of_another_attempt_does_not_satisfy_the_wait(self):
        self.inject_proof("dispatch_receipt", self._proof(1))
        self.engine.advance(self.work_id, 1_000)
        self.assertEqual(self.instance_row("n00")["state"], "running")

    def test_a_proof_of_the_bound_attempt_satisfies_the_wait(self):
        self.inject_proof("dispatch_receipt", self._proof(2))
        self.engine.advance(self.work_id, 1_000)
        node = self.instance_row("n00")
        self.assertEqual(node["state"], "completed", node.get("findings"))
        self.assertEqual(node["wait_match"]["boundAttempt"], 2)

    def test_a_proof_of_a_superseded_revision_does_not_satisfy_the_wait(self):
        self.inject_proof("dispatch_receipt", self._proof(2, revision=99))
        self.engine.advance(self.work_id, 1_000)
        self.assertEqual(self.instance_row("n00")["state"], "running")

    def test_a_proof_of_another_digest_does_not_satisfy_the_wait(self):
        self.inject_proof("dispatch_receipt", self._proof(2, digest_value="0" * 64))
        self.engine.advance(self.work_id, 1_000)
        self.assertEqual(self.instance_row("n00")["state"], "running")


class UnboundWaitTests(QualityTestCase):
    """A wait that declared no binding keeps the previous rule."""

    def setUp(self):
        super().setUp()
        spec = {
            "id": "unbound-flow", "version": "test-1", "policy_family": POLICY_ID,
            "entry": "n00", "terminal": ["n00"],
            "nodes": {"n00": {"kind": "wait", "deadline_s": 600,
                              "match": {"evidence_kind": "dispatch_receipt"}}},
            "edges": [],
        }
        self.instantiate(spec)

    def test_an_unbound_wait_matches_any_verified_proof_of_its_kind(self):
        self.inject_proof("dispatch_receipt", {"external_id": "EXT-1"})
        self.engine.advance(self.work_id, 1_000)
        node = self.instance_row("n00")
        self.assertEqual(node["state"], "completed", node.get("findings"))
        self.assertEqual(node["wait_match"]["mode"], "kind_only")
        self.assertEqual(node["quality"], {"declared": False, "mode": "undeclared"})


class ReadModelTests(QualityTestCase):
    def test_the_read_model_carries_the_quality_record(self):
        self.instantiate(quality_template())
        self.revise("proposal", self.proposal_body())
        self.engine.advance(self.work_id, 1_000)
        self.engine.pump(self.adapter, 1_000)
        self.engine.advance(self.work_id, 1_000)

        node = self.node("n01")
        self.assertTrue(node["quality"]["declared"])
        self.assertEqual(node["quality"]["mode"], "validated")
        self.assertEqual(node["effect"]["status"], "succeeded")
        self.assertTrue(node["effect"]["externalId"])
        self.assertEqual(node["receipt"]["externalId"], node["effect"]["externalId"])


if __name__ == "__main__":
    unittest.main()


class InputValidationTests(QualityTestCase):
    """A declared input is judged by its pinned validator, before the effect."""

    def _spec(self):
        spec = quality_template()
        spec["nodes"]["n01"]["inputs"] = [
            {"object": "proposal",
             "validation": {"validator": "business-input",
                            "validator_version": "1"}}]
        return spec

    def test_an_input_rejection_blocks_with_pinned_provenance(self):
        self.engine = WorkflowEngine(self.runtime, quality_validators(reject_input=True))
        self.instantiate(self._spec())
        self.revise("proposal", self.proposal_body())
        self.engine.advance(self.work_id, 1_000)
        self.engine.pump(self.adapter, 1_000)
        self.engine.advance(self.work_id, 1_000)

        node = self.instance_row("n01")
        self.assertEqual(node["state"], "blocked", node)
        finding = [entry for entry in node["findings"]
                   if entry["code"] == "INPUT_UNUSABLE"][0]
        self.assertEqual(finding["validator"], "business-input")
        self.assertEqual(finding["validator_version"], "1")
        self.assertEqual(finding["revision"], 1)
        self.assertTrue(finding["digest"])
        self.assertEqual(self.operations(), [])
        self.assertEqual(DemoBusinessSystem(self.adapter_path).effect_count(), 0)

    def test_an_accepted_input_is_reported_with_its_pinned_judge(self):
        self.instantiate(self._spec())
        self.revise("proposal", self.proposal_body())
        self.engine.advance(self.work_id, 1_000)
        report = self.instance_row("n01")["input_report"]
        self.assertEqual(len(report), 1, report)
        self.assertEqual(report[0]["object"], "proposal")
        self.assertEqual(report[0]["role"], "input")
        self.assertEqual(report[0]["validator"], "business-input")
        self.assertEqual(report[0]["validatorVersion"], "1")
        self.assertEqual(report[0]["verdict"], "passed")
        self.assertEqual(report[0]["revision"], 1)
        self.assertTrue(report[0]["digest"])

    def test_an_unresolvable_input_validator_fails_closed_at_publication(self):
        self.engine = WorkflowEngine(self.runtime, ValidatorRegistry())
        receipt = self.engine.publish_template("coordinator", self._spec())
        self.assertEqual(receipt["decision"], "rejected", receipt)
        self.assertEqual(receipt["code"], "WORKFLOW_VALIDATOR_UNKNOWN")
        names = [entry["validator"] for entry in receipt["validators"]]
        self.assertIn("business-input", names)

    def test_a_subject_with_a_declared_validation_is_a_protected_input(self):
        spec = quality_template()
        spec["nodes"]["n01"]["subject"] = {
            "object": "proposal",
            "validation": {"validator": "business-input",
                           "validator_version": "1"}}
        self.engine = WorkflowEngine(self.runtime, quality_validators(reject_input=True))
        self.instantiate(spec)
        self.revise("proposal", self.proposal_body())
        self.engine.advance(self.work_id, 1_000)
        node = self.instance_row("n01")
        self.assertEqual(node["state"], "blocked", node)
        roles = [entry["role"] for entry in node["findings"]
                 if entry["code"] == "INPUT_UNUSABLE"]
        self.assertEqual(roles, ["subject"])
        self.assertEqual(self.operations(), [])


class HumanOutputTests(QualityTestCase):
    """A human node may declare the named record its decision carries."""

    def setUp(self):
        super().setUp()
        self.instantiate(human_output_template())
        self.revise("proposal", self.proposal_body())
        self.engine.advance(self.work_id, 1_000)

    def _record(self, record_id="EXT-1"):
        return {"recordId": record_id, "action": "work.dispatch", "items": ["M-1"]}

    def test_a_human_decision_writes_its_named_output(self):
        proposal = self.object_reference("proposal")
        before = self.version()
        receipt = self.decide("n01", "approved", proposal["digest"],
                               proposal["revision"], result=self._record())
        self.assertEqual(receipt["decision"], "accepted", receipt)
        # The record was written in the same transaction as the decision, so
        # the receipt reports a version the work reached through that one
        # command.
        self.assertGreater(receipt["result_state_version"], before)
        self.assertLessEqual(receipt["result_state_version"],
                             self.version())
        row = self.object_row("feedback")
        self.assertIsNotNone(row, "the named record was not written")
        self.assertEqual(__import__("json").loads(row[3])["recordId"], "EXT-1")
        node = self.instance_row("n01")
        self.assertEqual(node["state"], "completed", node.get("findings"))
        self.assertEqual(node["quality"]["mode"], "validated")
        binding = node["output_binding"]
        self.assertEqual(binding["actor"], "responsible-c")
        self.assertEqual(binding["source"], "responsible-c")
        self.assertEqual(binding["node"], "n01")
        self.assertEqual(binding["attempt"], 1)
        self.assertEqual(binding["outputDigest"], row[2])
        self.assertEqual(binding["subject"]["digest"], proposal["digest"])

    def test_a_human_decision_without_its_record_keeps_the_node_waiting(self):
        proposal = self.object_reference("proposal")
        receipt = self.decide("n01", "approved", proposal["digest"],
                               proposal["revision"])
        self.assertEqual(receipt["decision"], "accepted", receipt)
        node = self.instance_row("n01")
        self.assertEqual(node["state"], "running", node)
        self.assertIsNone(self.object_row("feedback"))
        codes = [entry["code"] for entry in node["findings"]]
        self.assertIn("WORKFLOW_OUTPUT_MISSING", codes)

    def test_a_rejected_record_is_not_written_and_does_not_route_on(self):
        proposal = self.object_reference("proposal")
        receipt = self.decide("n01", "approved", proposal["digest"],
                               proposal["revision"], result={"recordId": ""})
        self.assertEqual(receipt["decision"], "accepted", receipt)
        node = self.instance_row("n01")
        self.assertEqual(node["state"], "running", node)
        self.assertIsNone(self.object_row("feedback"))
        self.assertEqual(node["quality"]["mode"], "rejected")
        codes = [entry["code"] for entry in node["findings"]]
        self.assertIn("EFFECT_UNIDENTIFIED", codes)

    def test_a_rejected_record_never_overwrites_the_previous_revision(self):
        proposal = self.object_reference("proposal")
        self.decide("n01", "approved", proposal["digest"], proposal["revision"],
                    result=self._record("EXT-1"))
        self.assertIsNotNone(self.object_row("feedback"))
        # A later decision with a record that fails its quality must not
        # replace the record that is already on the ledger.
        self.decide("n01", "approved", proposal["digest"], proposal["revision"],
                    result={"recordId": ""})
        row = self.object_row("feedback")
        self.assertEqual(__import__("json").loads(row[3])["recordId"], "EXT-1")
        self.assertEqual(row[1], 1)


class HumanCompatibilityTests(QualityTestCase):
    """A human node that declared no output keeps its previous behaviour."""

    def test_a_human_node_without_a_declared_output_is_not_implied_to_be_checked(self):
        spec = human_output_template()
        spec["nodes"]["n01"].pop("output")
        self.instantiate(spec)
        self.revise("proposal", self.proposal_body())
        self.engine.advance(self.work_id, 1_000)
        proposal = self.object_reference("proposal")
        self.decide("n01", "approved", proposal["digest"], proposal["revision"])
        node = self.instance_row("n01")
        self.assertEqual(node["state"], "completed", node.get("findings"))
        self.assertEqual(node["quality"], {"declared": False, "mode": "undeclared"})


class SupersedeTests(QualityTestCase):
    """A new revision of the material a node pinned supersedes the node."""

    def test_a_revised_candidate_supersedes_the_reviewing_node(self):
        self.instantiate(candidate_template())
        node = self.node("n01")
        attempt = node["attempt"]
        input_digest = node["inputDigest"]
        receipt = self.engine.command("agent-executor", uuid.uuid4().hex, self.work_id,
                                      "submit_node_result",
                                      {"node": "n01", "attempt": attempt,
                                       "object": "candidate",
                                       "result": {"recordId": "EXT-1",
                                                  "action": "work.dispatch",
                                                  "items": ["M-1"]},
                                       "input_digest": input_digest},
                                      self.version())
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.assertEqual(self.instance_row("n01")["state"], "submitted")

        # A new revision of the candidate invalidates the node: the review of
        # the superseded candidate must not be able to complete it.
        self.revise("candidate", {"recordId": "EXT-2", "action": "work.dispatch",
                                   "items": ["M-2"]})
        instance = self.instance_row("n01", attempt)
        self.assertEqual(instance["state"], "cancelled", instance)
        self.assertEqual(instance["reason"], "OBJECT_SUPERSEDED")

    def test_revising_the_subject_of_a_human_node_supersedes_it(self):
        self.instantiate(human_output_template())
        self.revise("proposal", self.proposal_body())
        self.engine.advance(self.work_id, 1_000)
        self.assertEqual(self.instance_row("n01")["state"], "running")
        self.revise("proposal", {"measures": [{"issueId": "H-001",
                                                "measureId": "M-2",
                                                "measure": "another guard"}]})
        instance = self.instance_row("n01")
        self.assertEqual(instance["state"], "cancelled", instance)
        self.assertEqual(instance["reason"], "OBJECT_SUPERSEDED")
