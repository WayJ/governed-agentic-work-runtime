"""The opt-in effect policy of an automatic action node.

An action node normally produces its external effect **once**: a later
attempt fails closed with ``WORKFLOW_EFFECT_ALREADY_APPLIED``. A node that
declares the per-revision policy may produce a *new* effect for a new
revision of its subject, after the previous effect is settled — the
automatic draft save a host needs when a human rejected the first draft and
the agent genuinely reworked the proposal.

The tests drive the real runtime: an agent proposal, an independent review,
an automatic draft, a human rejection, a reworked and independently reviewed
proposal, a second automatic draft, two approvals and one formal final
action. The external effects are counted in the business system's own store,
never in a counter of the process that performed them.
"""

import json
import os
import sqlite3
import tempfile
import unittest
import uuid

from work_runtime.policy import digest
from work_runtime.runtime import Runtime
from work_runtime.workflow import WorkflowEngine
from work_runtime.workflow_demo import (EFFECT_SHAPE, PROPOSAL_SHAPE,
                                         DemoBusinessSystem, WorkflowDemoPolicy,
                                         workflow_demo_grants,
                                         workflow_demo_validators)
from work_runtime.workflow_spec import (ValidatorRegistry, lint_template,
                                         template_digest)

POLICY_ID = "effect-policy"
POLICY_VERSION = "effect-1"
POLICY_GOAL = "effect.completed"

# The clock the tests drive. It is explicit everywhere: a node's deadline is
# a stored fact, and a test that expires a node has to say when it expires.
NOW = 1_000

PROPOSAL_V1 = {"measures": [{"issueId": "H-001", "measureId": "M-1",
                             "measure": "complete the guard"}]}
PROPOSAL_V2 = {"measures": [{"issueId": "H-001", "measureId": "M-1",
                             "measure": "complete the guard and record the result"}]}


class EffectPolicy(WorkflowDemoPolicy):
    """A family without obligations.

    The scenario needs the automatic draft to run before any approval
    exists, so the family declares no obligation: the effect itself is the
    subject. The evidence kinds and their sources are the demonstration's.
    """

    id = POLICY_ID
    version = POLICY_VERSION
    goal = POLICY_GOAL

    def evaluate(self, work, evidence):
        return []

    def action_blockers(self, capability, requirements):
        if capability not in ("work.dispatch", "work.deliver"):
            return [{"code": "CAPABILITY_UNSUPPORTED", "capability": capability}]
        return []


def effect_validators(reject_output=False):
    """The host-registered, version-pinned validators of this family.

    ``reject_output`` makes the receipt of every automatic node fail its
    quality: the external effect really happened and its output was refused.
    """
    registry = workflow_demo_validators()
    if not reject_output:
        return registry
    original = registry.resolve("effect", "1")

    def refusing(work, node_ref, result):
        findings = [{"code": "EFFECT_REJECTED",
                     "message": "The host rejected this receipt"}]
        checks = [{"check": check, "verdict": "failed",
                   "reason": "the host rejected this receipt",
                   "evidence": ["receipt:rejected"]}
                  for check in (node_ref.get("checks") or [])]
        return {"findings": findings, "checks": checks}

    registry.register("effect", "1", refusing)
    return registry


def revision_template(effect_policy=None, max_attempts=2,
                       template_id="revision-flow", version="test-1",
                       on_failure=None, on_timeout=None, deadline_s=None):
    """The scenario as published data.

    An agent proposes, an automatic node saves the draft, a human rejects
    the draft, the agent reworks and the draft is saved again — then a
    second human approves and one formal action follows.
    """
    draft = {
        "kind": "action", "capability": "work.dispatch",
        "subject": {"object": "proposal"},
        "max_attempts": max_attempts,
        "output": {"object": "draft",
                   "validation": {"shape": EFFECT_SHAPE,
                                  "validator": "effect", "validator_version": "1"}},
        "checks": [{"id": "N02-1", "method": "PROGRAM",
                    "criterion": "The draft receipt names the draft it recorded.",
                    "criterion_version": "1",
                    "validator": "effect", "validator_version": "1"}],
    }
    if effect_policy is not None:
        draft["effect_policy"] = effect_policy
    if on_failure is not None:
        draft["on_failure"] = on_failure
    if on_timeout is not None:
        draft["on_timeout"] = on_timeout
    if deadline_s is not None:
        draft["deadline_s"] = deadline_s
    return {
        "id": template_id,
        "version": version,
        "policy_family": POLICY_ID,
        "entry": "n01",
        "terminal": ["n05"],
        "nodes": {
            "n01": {"kind": "agent", "executor": "agent-executor", "max_attempts": 2,
                    "output": {"object": "proposal",
                               "validation": {"shape": PROPOSAL_SHAPE,
                                              "validator": "proposal",
                                              "validator_version": "1"}},
                    "checks": [{"id": "N01-1", "method": "PROGRAM",
                                "criterion": "Every measure has a stable identifier.",
                                "criterion_version": "1",
                                "validator": "proposal", "validator_version": "1"},
                               {"id": "N01-2", "method": "AGENT",
                                "criterion": "An independent reviewer confirms the "
                                            "proposal is ready to be saved.",
                                "criterion_version": "1"}],
                    "review": {"evidence_kind": "agent_review",
                               "reviewer": "reviewer-v",
                               "rubric": {"validator": "review-rubric",
                                          "validator_version": "1"}}},
            "n02": draft,
            "n03": {"kind": "human", "evidence_kind": "safety_review",
                    "authority": "reviewer-a", "subject": {"object": "draft"},
                    "on_reject": "n01", "max_attempts": 3,
                    "checks": [{"id": "N03-1", "method": "HUMAN",
                                "criterion": "The draft is fit to be saved.",
                                "criterion_version": "1",
                                "validator": "review-rubric",
                                "validator_version": "1"}]},
            "n04": {"kind": "human", "evidence_kind": "project_approval",
                    "authority": "reviewer-b", "subject": {"object": "draft"},
                    "distinct_from": ["n03"],
                    "checks": [{"id": "N04-1", "method": "HUMAN",
                                "criterion": "The arrangement names a responsible "
                                            "party and a deadline.",
                                "criterion_version": "1",
                                "validator": "review-rubric",
                                "validator_version": "1"}]},
            "n05": {"kind": "action", "capability": "work.deliver",
                    "subject": {"object": "draft"}},
        },
        "edges": [{"from": "n01", "to": "n02"},
                  {"from": "n02", "to": "n03"},
                  {"from": "n03", "to": "n04"},
                  {"from": "n04", "to": "n05"}],
    }


def linked_template():
    """Two automatic nodes of one capability on one subject.

    The business key of an object-bound operation names the capability, the
    work and the subject revision, so both nodes would address the same
    operation. The linkage of an operation is exact: the second node may not
    adopt the operation the first one owns.
    """
    template = revision_template(effect_policy="per_revision")
    template["id"] = "linked-flow"
    template["terminal"] = ["n02b"]
    template["nodes"]["n02b"] = {"kind": "action", "capability": "work.dispatch",
                                 "subject": {"object": "proposal"},
                                 "max_attempts": 2,
                                 "effect_policy": "per_revision"}
    template["edges"].insert(1, {"from": "n02", "to": "n02b"})
    return template


class EffectPolicyTestCase(unittest.TestCase):
    """The fixture: one store, one engine, one external business system."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-effect-policy-")
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.adapter_path = os.path.join(self.folder, "effects.sqlite")
        self.adapter = DemoBusinessSystem(self.adapter_path)
        self.runtime = Runtime(self.path, EffectPolicy(), workflow_demo_grants())
        self.engine = WorkflowEngine(self.runtime, effect_validators())
        self.work_id = "W-1"

    # -- helpers ---------------------------------------------------------

    def version(self):
        return self.runtime.get_work(self.work_id)["state_version"]

    def send(self, actor, kind, payload=None, command_id=None):
        """A runtime command under the caller's compare-and-swap.

        The workflow commands are issued through the runtime, so the test
        keeps control of the clock: the engine's own advance uses the wall
        clock, and a test that expires a node has to say when it expires.
        """
        expected = None if kind in ("create_work", "record_evidence") else self.version()
        return self.runtime.command(actor, command_id or uuid.uuid4().hex,
                                    self.work_id, kind, payload, expected)

    def advance(self, now=NOW):
        return self.engine.advance(self.work_id, now)

    def pump(self, now=NOW):
        return self.engine.pump(self.adapter, now)

    def publish(self, template):
        receipt = self.engine.publish_template("coordinator", template)
        self.assertEqual(receipt["decision"], "accepted", receipt)
        return receipt

    def instantiate(self, template):
        self.publish(template)
        self.send("coordinator", "create_work",
                  {"document": {"id": "H-001", "subject": "east parapet"}})
        self.send("coordinator", "bind_contract",
                  {"policy_id": POLICY_ID, "policy_version": POLICY_VERSION,
                   "goal": POLICY_GOAL})
        self.send("coordinator", "revise_plan",
                  {"steps": ["n01", "n02", "n03", "n04", "n05"],
                   "open_requirements": [], "replan_when": []})
        receipt = self.send("coordinator", "bind_workflow",
                            {"template_id": template["id"],
                             "template_version": template["version"],
                             "parameters": {"subject": "east parapet"}})
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.advance()

    def node(self, node_id):
        for entry in self.engine.instance(self.work_id)["nodes"]:
            if entry["node"] == node_id:
                return entry
        return None

    def latest_row(self, node_id):
        """The stored instance of the latest attempt of a node."""
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT body FROM workflow_nodes WHERE work_id=? "
                             "AND node=? ORDER BY attempt DESC LIMIT 1",
                             (self.work_id, node_id)).fetchone()
            return json.loads(row[0]) if row else None
        finally:
            db.close()

    def instance_row(self, node_id, attempt):
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT body FROM workflow_nodes WHERE work_id=? "
                             "AND node=? AND attempt=?",
                             (self.work_id, node_id, attempt)).fetchone()
            return json.loads(row[0]) if row else None
        finally:
            db.close()

    def object_revisions(self, name):
        db = sqlite3.connect(self.path)
        try:
            return db.execute("SELECT name,revision,digest FROM workflow_objects "
                              "WHERE work_id=? AND name=? ORDER BY revision",
                              (self.work_id, name)).fetchall()
        finally:
            db.close()

    def operations(self):
        db = sqlite3.connect(self.path)
        try:
            return [json.loads(row[0]) for row in
                    db.execute("SELECT body FROM operations WHERE work_id=?",
                               (self.work_id,))]
        finally:
            db.close()

    def submit_proposal(self, result):
        entry = self.node("n01")
        receipt = self.send("agent-executor", "submit_node_result",
                            {"node": "n01", "attempt": entry["attempt"],
                             "object": "proposal", "result": result,
                             "input_digest": entry["inputDigest"]})
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.advance()
        return receipt

    def review_proposal(self, verdict="passed"):
        """The independent review of the candidate the agent produced."""
        entry = self.node("n01")
        data = {"node": "n01", "attempt": entry["attempt"],
                "input_digest": entry["inputDigest"],
                "output_digest": entry["outputs"][0]["digest"],
                "producer": "reviewer-v", "verdict": verdict,
                "items": [{"check": "N01-2", "verdict": verdict,
                           "reason": "the candidate is ready to be saved",
                           "evidence": ["proposal#revision-1"]}]}
        receipt = self.send("reviewer-v", "record_evidence",
                            {"event_id": uuid.uuid4().hex, "kind": "agent_review",
                             "data": data})
        self.runtime.verify_pending(self.work_id)
        self.advance()
        return receipt

    def decide(self, node_id, kind, source, decision, digest_value, revision,
               verdict="passed", check=None):
        entry = self.node(node_id)
        items = [{"check": check or ("N03-1" if node_id == "n03" else "N04-1"),
                  "verdict": verdict,
                  "reason": "reviewed against the criterion",
                  "evidence": ["draft#revision-" + str(revision)]}]
        receipt = self.send(source, "record_decision",
                            {"node": node_id, "attempt": entry["attempt"],
                             "decision": decision, "digest": digest_value,
                             "revision": revision, "actor": source, "items": items})
        self.runtime.verify_pending(self.work_id)
        self.advance()
        return receipt

    def first_draft(self):
        """Drive the workflow to the first automatic draft."""
        self.submit_proposal(PROPOSAL_V1)
        self.review_proposal()
        self.assertEqual(self.node("n01")["state"], "completed")
        self.pump()
        self.assertEqual(self.node("n02")["state"], "completed")
        return self.node("n02")["outputs"][0]

    def rework(self, result=PROPOSAL_V2):
        """The human rejected the draft; the agent produces a new proposal."""
        draft = self.node("n02")["outputs"][0]
        receipt = self.decide("n03", "safety_review", "reviewer-a", "rejected",
                              draft["digest"], draft["revision"], verdict="failed")
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.assertEqual(self.node("n01")["attempt"], 2)
        self.submit_proposal(result)
        self.review_proposal()
        self.assertEqual(self.node("n01")["state"], "completed")


class DefinitionLanguageTests(unittest.TestCase):
    """The published definition is where the opt-in lives."""

    def test_an_action_node_may_declare_the_per_revision_policy(self):
        self.assertEqual(lint_template(revision_template(effect_policy="per_revision")), [])
        self.assertEqual(lint_template(revision_template(effect_policy="once")), [])

    def test_an_unknown_effect_policy_is_refused(self):
        findings = lint_template(revision_template(effect_policy="sometimes"))
        codes = [entry["code"] for entry in findings]
        self.assertIn("NODE_EFFECT_POLICY_UNKNOWN", codes)

    def test_the_per_revision_policy_needs_a_second_attempt(self):
        findings = lint_template(revision_template(effect_policy="per_revision",
                                                   max_attempts=1))
        codes = [entry["code"] for entry in findings]
        self.assertIn("NODE_EFFECT_POLICY_ATTEMPTS", codes)

    def test_the_effect_policy_is_an_action_node_field(self):
        template = revision_template()
        template["nodes"]["n03"]["effect_policy"] = "per_revision"
        codes = [entry["code"] for entry in lint_template(template)]
        self.assertIn("NODE_FIELD_UNKNOWN", codes)

    def test_the_policy_is_part_of_the_published_digest(self):
        first = template_digest(revision_template(effect_policy="per_revision"))
        second = template_digest(revision_template(effect_policy="once"))
        self.assertNotEqual(first, second)


class PerRevisionPathTests(EffectPolicyTestCase):
    """The real path: proposal, draft, rejection, rework, draft, approval."""

    def test_a_new_proposal_produces_a_new_draft_and_one_final_effect(self):
        self.instantiate(revision_template(effect_policy="per_revision"))
        draft_one = self.first_draft()
        self.assertEqual(draft_one["revision"], 1)
        self.assertEqual(self.adapter.effect_count(), 1)

        self.rework()
        self.pump()

        # The second attempt of the node produced a second draft.
        draft_two = self.node("n02")["outputs"][0]
        self.assertEqual(self.node("n02")["attempt"], 2)
        self.assertEqual(self.node("n02")["state"], "completed")
        self.assertEqual(draft_two["revision"], 2)
        self.assertNotEqual(draft_two["digest"], draft_one["digest"])
        # Two version drafts and one final effect.
        self.assertEqual(len(self.object_revisions("draft")), 2)
        self.assertEqual(self.adapter.effect_count(), 2)

        # The two approvals and the formal action.
        self.decide("n03", "safety_review", "reviewer-a", "approved",
                    draft_two["digest"], draft_two["revision"])
        self.decide("n04", "project_approval", "reviewer-b", "approved",
                    draft_two["digest"], draft_two["revision"])
        self.pump()
        self.assertEqual(self.node("n05")["state"], "completed")
        self.assertEqual(self.adapter.effect_count(), 3)
        final = [entry for entry in self.operations()
                 if entry["capability"] == "work.deliver"]
        self.assertEqual(len(final), 1)
        self.assertEqual(final[0]["status"], "confirmed_succeeded")

    def test_the_new_effect_is_a_new_operation_with_a_new_business_key(self):
        self.instantiate(revision_template(effect_policy="per_revision"))
        self.first_draft()
        self.rework()
        self.pump()
        drafts = [entry for entry in self.operations()
                  if entry["capability"] == "work.dispatch"]
        self.assertEqual(len(drafts), 2)
        self.assertNotEqual(drafts[0]["id"], drafts[1]["id"])
        self.assertNotEqual(drafts[0]["business_key"], drafts[1]["business_key"])
        self.assertEqual(drafts[0]["object"]["revision"], 1)
        self.assertEqual(drafts[1]["object"]["revision"], 2)
        self.assertNotEqual(drafts[0]["document_digest"], drafts[1]["document_digest"])

    def test_the_original_receipt_is_retained(self):
        self.instantiate(revision_template(effect_policy="per_revision"))
        first = self.first_draft()
        self.rework()
        self.pump()
        history = self.engine.attempts(self.work_id, "n02")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["attempt"], 1)
        self.assertEqual(history[0]["effect"]["status"], "succeeded")
        self.assertEqual(history[1]["attempt"], 2)
        self.assertEqual(history[1]["effect"]["status"], "succeeded")
        self.assertNotEqual(history[0]["effect"]["operationId"],
                            history[1]["effect"]["operationId"])
        # The receipt of the first draft is still on its own attempt.
        receipt = self.instance_row("n02", 1).get("receipt")
        self.assertIsNotNone(receipt)
        self.assertEqual(receipt["origin"]["externalId"],
                         history[0]["effect"]["externalId"])

    def test_both_business_keys_resolve_after_a_restart(self):
        self.instantiate(revision_template(effect_policy="per_revision"))
        self.first_draft()
        self.rework()
        self.pump()
        drafts = [entry for entry in self.operations()
                  if entry["capability"] == "work.dispatch"]
        self.assertEqual(len(drafts), 2)
        runtime = Runtime(self.path, EffectPolicy(), workflow_demo_grants())
        engine = WorkflowEngine(runtime, effect_validators())
        for operation, attempt in ((drafts[0], 1), (drafts[1], 2)):
            context = engine.action_context(operation["business_key"])
            self.assertTrue(context["present"], context)
            self.assertEqual(context["context"]["operationId"], operation["id"])
            self.assertEqual(context["context"]["node"], "n02")
            self.assertEqual(context["context"]["attempt"], attempt)
            self.assertEqual(context["context"]["subject"]["revision"], attempt)


class DefaultPolicyTests(EffectPolicyTestCase):
    """The default stays once per node."""

    def test_a_node_without_the_policy_never_repeats_its_effect(self):
        self.instantiate(revision_template())
        self.first_draft()
        self.rework()
        self.pump()
        node = self.node("n02")
        self.assertEqual(node["attempt"], 2)
        self.assertEqual(node["state"], "failed")
        self.assertEqual(self.latest_row("n02")["reason"],
                         "WORKFLOW_EFFECT_ALREADY_APPLIED")
        self.assertEqual(self.adapter.effect_count(), 1)
        self.assertEqual(len(self.operations()), 1)

    def test_the_explicit_once_policy_never_repeats_its_effect(self):
        self.instantiate(revision_template(effect_policy="once"))
        self.first_draft()
        self.rework()
        self.pump()
        self.assertEqual(self.latest_row("n02")["reason"],
                         "WORKFLOW_EFFECT_ALREADY_APPLIED")
        self.assertEqual(self.adapter.effect_count(), 1)


    def test_an_operation_already_linked_to_another_node_is_refused(self):
        self.instantiate(linked_template())
        self.submit_proposal(PROPOSAL_V1)
        self.review_proposal()
        self.pump()
        self.assertEqual(self.node("n02")["state"], "completed")
        second = self.node("n02b")
        self.assertEqual(second["state"], "failed")
        self.assertEqual(self.latest_row("n02b")["reason"], "WORKFLOW_EFFECT_REUSED")
        # The effect of the first node was not produced a second time.
        self.assertEqual(self.adapter.effect_count(), 1)
        self.assertEqual(len(self.operations()), 1)


class RefusalTests(EffectPolicyTestCase):
    """The refusals of the per-revision policy."""

    def test_the_same_digest_under_a_new_revision_is_refused(self):
        self.instantiate(revision_template(effect_policy="per_revision"))
        self.first_draft()
        self.rework(PROPOSAL_V1)
        self.pump()
        node = self.node("n02")
        self.assertEqual(node["attempt"], 2)
        self.assertEqual(node["state"], "failed")
        self.assertEqual(self.latest_row("n02")["reason"],
                         "WORKFLOW_EFFECT_SUBJECT_UNCHANGED")
        self.assertEqual(self.adapter.effect_count(), 1)
        self.assertEqual(len(self.operations()), 1)

    def test_an_unresolved_prior_effect_is_not_rewritten(self):
        self.instantiate(revision_template(effect_policy="per_revision",
                                           on_timeout="n02", deadline_s=60))
        self.submit_proposal(PROPOSAL_V1)
        self.review_proposal()
        operation = self.operations()[0]
        self.assertEqual(operation["status"], "prepared")

        def crash():
            raise RuntimeError("the process died after the effect")

        with self.assertRaises(RuntimeError):
            self.runtime.dispatch(operation["id"], self.adapter, fault=crash)
        self.assertEqual(self.adapter.effect_count(), 1)
        self.assertEqual(self.runtime.get_operation(operation["id"])["status"],
                         "dispatched")

        # The node runs out of its time while its effect is in flight; the
        # next attempt must reconcile the unknown outcome, not write again.
        self.advance(NOW + 600)
        node = self.node("n02")
        self.assertEqual(node["attempt"], 2)
        self.assertEqual(node["state"], "blocked")
        self.assertEqual([entry["code"] for entry in node["blockers"]],
                         ["WORKFLOW_EFFECT_UNRESOLVED"])
        self.assertEqual(len(self.operations()), 1)
        self.assertEqual(self.adapter.effect_count(), 1)

    def test_a_failed_output_is_not_bypassed_by_a_new_subject(self):
        self.runtime = Runtime(self.path, EffectPolicy(), workflow_demo_grants())
        self.engine = WorkflowEngine(self.runtime, effect_validators(reject_output=True))
        self.instantiate(revision_template(effect_policy="per_revision",
                                           on_failure="n01"))
        self.submit_proposal(PROPOSAL_V1)
        self.review_proposal()
        self.pump()
        # The effect really happened; its output did not pass its quality.
        node = self.node("n02")
        self.assertEqual(node["state"], "failed")
        self.assertEqual(self.latest_row("n02")["reason"],
                         "WORKFLOW_OUTPUT_INVALID")
        self.assertEqual(self.adapter.effect_count(), 1)

        # The workflow rewinds to the agent and a new proposal arrives.
        self.submit_proposal(PROPOSAL_V2)
        self.review_proposal()
        self.pump()
        node = self.node("n02")
        self.assertEqual(node["attempt"], 2)
        self.assertEqual(node["state"], "failed")
        self.assertEqual(self.latest_row("n02")["reason"],
                         "WORKFLOW_EFFECT_OUTPUT_INVALID")
        self.assertEqual(self.adapter.effect_count(), 1)
        self.assertEqual(len(self.operations()), 1)


class PublicationTests(EffectPolicyTestCase):
    """The policy is published, pinned and never changed under a version."""

    def test_an_unknown_policy_is_refused_at_publication(self):
        receipt = self.engine.publish_template(
            "coordinator", revision_template(effect_policy="sometimes"))
        self.assertEqual(receipt["decision"], "rejected", receipt)
        self.assertEqual(receipt["code"], "WORKFLOW_SPEC_INVALID")
        codes = [entry["code"] for entry in receipt["findings"]]
        self.assertIn("NODE_EFFECT_POLICY_UNKNOWN", codes)

    def test_a_pinned_template_cannot_be_changed_under_the_same_version(self):
        self.publish(revision_template(effect_policy="per_revision"))
        receipt = self.engine.publish_template(
            "coordinator", revision_template(effect_policy="once"))
        self.assertEqual(receipt["decision"], "rejected", receipt)
        self.assertEqual(receipt["code"], "WORKFLOW_TEMPLATE_IMMUTABLE")

    def test_an_unknown_policy_is_refused_at_binding(self):
        """A definition that never passed the lint cannot be bound."""
        template = revision_template(effect_policy="per_revision")
        body = {"id": template["id"], "version": template["version"],
                "digest": template_digest(template), "spec": template,
                "published_by": "coordinator", "published_at": NOW}
        template["nodes"]["n02"]["effect_policy"] = "sometimes"
        with self.runtime._transaction() as db:
            db.execute("INSERT INTO workflow_templates VALUES (?,?,?,?)",
                       (template["id"], template["version"],
                        template_digest(template), json.dumps(body)))
        self.send("coordinator", "create_work",
                  {"document": {"id": "H-001", "subject": "east parapet"}})
        self.send("coordinator", "bind_contract",
                  {"policy_id": POLICY_ID, "policy_version": POLICY_VERSION,
                   "goal": POLICY_GOAL})
        self.send("coordinator", "revise_plan",
                  {"steps": ["n01"], "open_requirements": [], "replan_when": []})
        receipt = self.send("coordinator", "bind_workflow",
                            {"template_id": template["id"],
                             "template_version": template["version"],
                             "parameters": {"subject": "east parapet"}})
        self.assertEqual(receipt["decision"], "rejected", receipt)
        self.assertEqual(receipt["code"], "WORKFLOW_EFFECT_POLICY_UNKNOWN")


if __name__ == "__main__":  # pragma: no cover - the suite runs the file
    unittest.main()
