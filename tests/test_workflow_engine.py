"""Behaviour of the durable mixed-node workflow engine.

Every test asserts stored truth (rows, receipts, events, effect counts), not
return values alone. The engine is generic: the scenario below is published
template data plus a demonstration policy family, never engine code.
"""

import os
import sqlite3
import tempfile
import unittest
import uuid

try:
    from workflow_support import (DemoPolicy, RecordingAdapter, build, decide,
                                  demo_grants, demo_validators, document,
                                  instance_of, scenario_template, send, submit,
                                  submit_valid, version_of)
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import (DemoPolicy, RecordingAdapter, build, decide,
                                        demo_grants, demo_validators, document,
                                        instance_of, scenario_template, send, submit,
                                        submit_valid, version_of)


class WorkflowTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-workflow-")
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.adapter_path = os.path.join(self.folder, "effects.sqlite")
        self.runtime, self.engine = build(self.path)
        self.adapter = RecordingAdapter(self.adapter_path)
        self.template = scenario_template()
        self.published = self.engine.publish_template("coordinator", self.template)
        self.assertEqual(self.published["decision"], "accepted")
        self.work_id = "W-1"

    # -- helpers ---------------------------------------------------------
    def rows(self, table, where="1=1", arguments=()):
        db = sqlite3.connect(self.path)
        try:
            return db.execute("SELECT * FROM " + table + " WHERE " + where,
                              arguments).fetchall()
        finally:
            db.close()

    def object_rows(self, name):
        return self.rows("workflow_objects", "work_id=? AND name=?",
                         (self.work_id, name))

    def node_state(self, node):
        return instance_of(self.engine, self.runtime, self.work_id, node)

    def instantiate(self, **kwargs):
        receipt = instantiate_work(self.runtime, self.engine, self.work_id, **kwargs)
        self.assertEqual(receipt["decision"], "accepted", receipt)
        return receipt

    def drive_agents(self, upto="n03"):
        order = ["n01", "n02", "n03"]
        for node in order[:order.index(upto) + 1]:
            name = {"n01": "intake", "n02": "analysis", "n03": "proposal"}[node]
            receipt = submit_valid(self.engine, self.runtime, self.work_id, node, name)
            self.assertEqual(receipt["decision"], "accepted", receipt)

    def proposal_reference(self):
        row = self.object_rows("proposal")[0]
        return {"name": "proposal", "revision": row[2], "digest": row[3]}


def instantiate_work(runtime, engine, work_id="W-1", **kwargs):
    from workflow_support import instantiate
    return instantiate(runtime, engine, work_id, **kwargs)


class PublicationAndBindingTests(WorkflowTestCase):
    def test_publish_reports_a_stable_content_digest(self):
        self.assertEqual(len(self.published["digest"]), 64)
        again = self.engine.publish_template("coordinator", self.template)
        self.assertEqual(again["decision"], "accepted")
        self.assertEqual(again["digest"], self.published["digest"])

    def test_publish_refuses_to_mutate_a_published_definition(self):
        mutated = scenario_template()
        mutated["nodes"]["n01"]["max_attempts"] = 9
        receipt = self.engine.publish_template("coordinator", mutated)
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "WORKFLOW_TEMPLATE_IMMUTABLE")

    def test_publish_rejects_an_unknown_validator_version(self):
        broken = scenario_template()
        broken["nodes"]["n01"]["output"]["validation"]["validator_version"] = "9"
        receipt = self.engine.publish_template("coordinator", broken)
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "WORKFLOW_VALIDATOR_UNKNOWN")

    def test_bind_refuses_a_policy_family_mismatch(self):
        other = scenario_template(template_id="other", version="v1",
                                  policy_family="some-other-family")
        self.engine.publish_template("coordinator", other)
        receipt = instantiate_work(self.runtime, self.engine, self.work_id,
                                   template=other)
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "WORKFLOW_FAMILY_MISMATCH")

    def test_bind_refuses_an_incomplete_required_check(self):
        thin = scenario_template(template_id="thin", version="v1")
        thin["nodes"]["n03"]["checks"] = []
        self.engine.publish_template("coordinator", thin)
        receipt = instantiate_work(self.runtime, self.engine, self.work_id,
                                   template=thin)
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "WORKFLOW_REQUIRED_CHECKS_MISSING")

    def test_bind_pins_the_published_digest(self):
        self.instantiate()
        binding = self.runtime.get_work(self.work_id)["workflow"]
        self.assertEqual(binding["digest"], self.published["digest"])
        self.assertEqual(binding["template_version"], "test-1")

    def test_a_non_workflow_work_cannot_borrow_the_object_binding(self):
        """The object binding is a workflow capability, not a new shortcut."""
        runtime, engine = build(os.path.join(self.folder, "plain.sqlite"))
        send(runtime, "coordinator", "P-1", "create_work", {"document": document()})
        send(runtime, "coordinator", "P-1", "bind_contract",
             {"policy_id": "workflow-demo", "policy_version": "demo-1",
              "goal": "workflow.completed"})
        receipt = send(runtime, "coordinator", "P-1", "propose_action", {
            "capability": "work.dispatch", "document_digest": "0" * 64,
            "contract_revision": 1, "plan_revision": 0,
            "object": {"name": "anything", "revision": 1, "digest": "0" * 64}})
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "WORKFLOW_OBJECT_BINDING_UNSUPPORTED")
        self.assertEqual(self.rows("operations", "1=1"), [])

    def test_bind_refuses_a_second_binding(self):
        self.instantiate()
        receipt = self.engine.command("coordinator", uuid.uuid4().hex, self.work_id,
                                       "bind_workflow",
                                       {"template_id": self.template["id"],
                                        "template_version": self.template["version"],
                                        "parameters": {"subject": "east parapet"}},
                                       version_of(self.runtime, self.work_id))
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "WORKFLOW_ALREADY_BOUND")


class RoutingTests(WorkflowTestCase):
    def test_a_second_pass_writes_nothing(self):
        self.instantiate()
        self.engine.advance(self.work_id, 1000)
        first = self.runtime.get_work(self.work_id)["state_version"]
        self.engine.advance(self.work_id, 1000)
        self.engine.advance(self.work_id, 1000)
        self.assertEqual(self.runtime.get_work(self.work_id)["state_version"], first)

    def test_the_entry_node_opens_and_waits_for_the_executor(self):
        self.instantiate()
        self.engine.advance(self.work_id, 1000)
        entry = self.node_state("n01")
        self.assertEqual(entry["state"], "running")
        self.assertEqual(entry["attempt"], 1)
        intents = self.engine.intents(kind="agent_task")
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0]["node"], "n01")
        self.assertTrue(intents[0]["id"].endswith(":agent_task"))

    def test_only_the_configured_executor_may_submit(self):
        self.instantiate()
        self.engine.advance(self.work_id, 1000)
        receipt = submit(self.engine, self.runtime, self.work_id, "n01", 1, "intake",
                         {"records": [{"id": "R-1", "source": "s"}], "standard": "STD"},
                         actor="coordinator")
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "AUTHORITY_DENIED")

    def test_an_invalid_candidate_is_rejected_and_stores_no_object(self):
        self.instantiate()
        self.engine.advance(self.work_id, 1000)
        receipt = submit(self.engine, self.runtime, self.work_id, "n01", 1, "intake",
                         {"records": [], "standard": "STD"})
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "WORKFLOW_RESULT_INVALID")
        self.assertEqual(self.object_rows("intake"), [])
        self.assertNotEqual(self.node_state("n01")["state"], "completed")

    def test_a_self_certifying_claim_is_not_accepted(self):
        self.instantiate()
        self.engine.advance(self.work_id, 1000)
        receipt = submit(self.engine, self.runtime, self.work_id, "n01", 1, "intake",
                         {"records": [{"id": "R-1", "source": "s"}], "standard": "STD",
                          "validated": True})
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "WORKFLOW_RESULT_INVALID")
        self.assertEqual(self.object_rows("intake"), [])

    def test_a_valid_candidate_is_stored_as_a_new_object_revision(self):
        self.instantiate()
        self.engine.advance(self.work_id, 1000)
        receipt = submit_valid(self.engine, self.runtime, self.work_id, "n01", "intake")
        self.assertEqual(receipt["decision"], "accepted")
        rows = self.object_rows("intake")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], 1)
        self.assertEqual(self.node_state("n01")["state"], "completed")
        self.assertEqual(self.node_state("n02")["state"], "running")

    def test_a_review_evidence_is_required_before_an_agent_node_completes(self):
        self.instantiate()
        self.drive_agents()
        decide(self.runtime, self.engine, self.work_id, "safety_review",
               "reviewer-a", "approved", self.proposal_reference()["digest"],
               self.proposal_reference()["revision"])
        decide(self.runtime, self.engine, self.work_id, "project_approval",
               "reviewer-b", "approved", self.proposal_reference()["digest"],
               self.proposal_reference()["revision"])
        self.assertEqual(self.node_state("n06")["state"], "running")
        # The action is dispatched; the next human node opens.
        self.engine.pump(self.adapter, 1000)
        self.assertEqual(self.node_state("n07")["state"], "running")
        # A decision binds the attempt it was made for, so it is recorded
        # once the node is open.
        decide(self.runtime, self.engine, self.work_id, "field_report",
               "responsible-c", "approved", self.proposal_reference()["digest"],
               self.proposal_reference()["revision"])
        self.assertEqual(self.node_state("n07")["state"], "completed")
        decide(self.runtime, self.engine, self.work_id, "independent_review",
               "reviewer-d", "approved", self.proposal_reference()["digest"],
               self.proposal_reference()["revision"])
        self.assertEqual(self.node_state("n08")["state"], "completed")
        receipt = submit_valid(self.engine, self.runtime, self.work_id, "n09", "report")
        self.assertEqual(receipt["decision"], "accepted")
        self.assertEqual(self.node_state("n09")["state"], "submitted")
        reference = self.object_rows("report")[0]
        send(self.runtime, "reviewer-v", self.work_id, "record_evidence",
             {"event_id": uuid.uuid4().hex, "kind": "agent_review",
              "data": {"digest": reference[3], "verdict": "passed",
                       "items": [{"check": "N09-2", "result": "passed"}]}})
        self.runtime.verify_pending(self.work_id)
        self.engine.advance(self.work_id, 1000)
        self.assertEqual(self.node_state("n09")["state"], "completed")

    def test_an_approval_creates_the_next_human_task_without_an_agent_turn(self):
        self.instantiate()
        self.drive_agents()
        agent_intents_before = len(self.engine.intents(kind="agent_task"))
        decide(self.runtime, self.engine, self.work_id, "safety_review",
               "reviewer-a", "approved", self.proposal_reference()["digest"],
               self.proposal_reference()["revision"])
        human_intents = self.engine.intents(kind="human_task", status=None)
        self.assertEqual([entry["node"] for entry in human_intents], ["n04", "n05"])
        pending = self.engine.intents(kind="human_task")
        self.assertEqual([entry["node"] for entry in pending], ["n05"])
        self.assertEqual(len(self.engine.intents(kind="agent_task")),
                         agent_intents_before)
        self.assertEqual(self.node_state("n05")["state"], "running")

    def test_a_stale_decision_does_not_satisfy_a_node(self):
        self.instantiate()
        self.drive_agents()
        decide(self.runtime, self.engine, self.work_id, "safety_review",
               "reviewer-a", "approved", "0" * 64, 1)
        self.assertEqual(self.node_state("n04")["state"], "running")
        decide(self.runtime, self.engine, self.work_id, "safety_review",
               "reviewer-a", "approved", self.proposal_reference()["digest"], 99)
        self.assertEqual(self.node_state("n04")["state"], "running")
        decide(self.runtime, self.engine, self.work_id, "safety_review",
               "reviewer-a", "approved", self.proposal_reference()["digest"],
               self.proposal_reference()["revision"])
        self.assertEqual(self.node_state("n04")["state"], "completed")

    def test_a_rejection_routes_back_to_the_rework_branch(self):
        self.instantiate()
        self.drive_agents()
        decide(self.runtime, self.engine, self.work_id, "safety_review",
               "reviewer-a", "rejected", self.proposal_reference()["digest"],
               self.proposal_reference()["revision"])
        self.assertEqual(self.node_state("n04")["outcome"], "rejected")
        self.assertEqual(self.node_state("n03")["attempt"], 2)
        self.assertEqual(self.node_state("n03")["state"], "running")

    def test_bounded_rework_escalates_to_needs_attention(self):
        self.instantiate()
        self.engine.advance(self.work_id, 1000)
        for _ in range(2):
            submit(self.engine, self.runtime, self.work_id, "n01",
                   current_attempt_of(self, "n01"), "intake",
                   {"records": [], "standard": "STD"})
            self.engine.advance(self.work_id, 1000)
        self.assertEqual(self.runtime.get_work(self.work_id)["workflow_status"],
                         "needs_attention")
        events = [row[3] for row in self.rows("events", "work_id=?", (self.work_id,))]
        self.assertIn("WorkflowReworkLimitExceeded", events)

    def test_a_late_result_cannot_revive_a_completed_node(self):
        self.instantiate()
        self.engine.advance(self.work_id, 1000)
        submit_valid(self.engine, self.runtime, self.work_id, "n01", "intake")
        receipt = submit(self.engine, self.runtime, self.work_id, "n01", 1, "intake",
                         {"records": [{"id": "R-2", "source": "s"}], "standard": "STD"})
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "WORKFLOW_ATTEMPT_STALE")
        self.assertEqual(len(self.object_rows("intake")), 1)

    def test_the_same_command_replays_and_a_changed_body_conflicts(self):
        self.instantiate()
        self.engine.advance(self.work_id, 1000)
        payload = {"node": "n01", "attempt": 1, "object": "intake",
                   "result": {"records": [{"id": "R-1", "source": "s"}],
                              "standard": "STD"},
                   "input_digest": instance_of(self.engine, self.runtime,
                                               self.work_id, "n01")["inputDigest"]}
        sent_version = version_of(self.runtime, self.work_id)
        first = self.runtime.command("agent-executor", "cmd-1", self.work_id,
                                     "submit_node_result", payload, sent_version)
        self.assertEqual(first["decision"], "accepted")
        replay = self.runtime.command("agent-executor", "cmd-1", self.work_id,
                                      "submit_node_result", payload, sent_version)
        self.assertEqual(replay["decision"], "accepted")
        self.assertEqual(len(self.object_rows("intake")), 1)
        changed = dict(payload, result={"records": [{"id": "R-9", "source": "s"}],
                                         "standard": "STD"})
        conflict = self.runtime.command("agent-executor", "cmd-1", self.work_id,
                                        "submit_node_result", changed, sent_version)
        self.assertEqual(conflict["decision"], "rejected")
        self.assertEqual(conflict["code"], "COMMAND_ID_REUSED")

    def test_rework_invalidates_the_approval_of_the_previous_version(self):
        self.instantiate()
        self.drive_agents()
        decide(self.runtime, self.engine, self.work_id, "safety_review",
               "reviewer-a", "approved", self.proposal_reference()["digest"],
               self.proposal_reference()["revision"])
        decide(self.runtime, self.engine, self.work_id, "project_approval",
               "reviewer-b", "rejected", self.proposal_reference()["digest"],
               self.proposal_reference()["revision"])
        self.assertEqual(self.node_state("n03")["attempt"], 2)
        submit_valid(self.engine, self.runtime, self.work_id, "n03", "proposal",
                     {"measures": [{"issueId": "H-001", "measureId": "M-2",
                                    "measure": "install guard v2"}]})
        self.assertEqual(self.node_state("n04")["attempt"], 2)
        self.assertEqual(self.node_state("n04")["state"], "running")
        # The old approval is still on the record, but it no longer covers the
        # current version.
        proofs = self.rows("evidence", "work_id=?", (self.work_id,))
        self.assertTrue(any(row[0] == "reviewer-a" for row in proofs))


def current_attempt_of(case, node):
    return instance_of(case.engine, case.runtime, case.work_id, node)["attempt"]


class RoleIsolationTests(WorkflowTestCase):
    def test_an_executor_may_not_approve(self):
        class ExecutorIsAuthority(DemoPolicy):
            evidence_sources = dict(DemoPolicy.evidence_sources,
                                    safety_review="agent-executor")

        grants = demo_grants()
        # The executor is a trusted local principal that may write evidence of
        # its own kind; what it may never do is approve with it.
        grants["agent-executor"] = {"workflow.execute", "evidence.write"}
        runtime, engine = build(os.path.join(self.folder, "isolated.sqlite"),
                                policy=ExecutorIsAuthority(), grants=grants)
        engine.publish_template("coordinator", self.template)
        from workflow_support import instantiate
        instantiate(runtime, engine, self.work_id)
        engine.advance(self.work_id, 1000)
        submit_valid(engine, runtime, self.work_id, "n01", "intake")
        submit_valid(engine, runtime, self.work_id, "n02", "analysis")
        submit_valid(engine, runtime, self.work_id, "n03", "proposal")
        reference = engine.instance(self.work_id)
        proposal = [entry for entry in reference["nodes"] if entry["node"] == "n03"][0]
        digest_value = proposal["outputs"][0]["digest"]
        send(runtime, "agent-executor", self.work_id, "record_evidence",
             {"event_id": uuid.uuid4().hex, "kind": "safety_review",
              "data": {"decision": "approved", "digest": digest_value, "revision": 1,
                       "node": "n04", "attempt": 1, "actor": "agent-executor",
                       "items": [{"check": "N04-2", "verdict": "passed",
                                  "reason": "reviewed", "evidence": ["doc-1"]}]}})
        runtime.verify_pending(self.work_id)
        engine.advance(self.work_id, 1000)
        node = [entry for entry in engine.instance(self.work_id)["nodes"]
                if entry["node"] == "n04"][0]
        self.assertNotEqual(node["state"], "completed")
        self.assertTrue(any(finding["code"] == "WORKFLOW_EXECUTOR_MAY_NOT_APPROVE"
                            for finding in node["findings"]))

    def test_a_reviewer_may_not_repeat_another_reviewers_role(self):
        class SamePersonHoldsBothRoles(DemoPolicy):
            evidence_sources = dict(DemoPolicy.evidence_sources,
                                    project_approval="reviewer-a")

        runtime, engine = build(os.path.join(self.folder, "roles.sqlite"),
                                policy=SamePersonHoldsBothRoles())
        engine.publish_template("coordinator", self.template)
        from workflow_support import instantiate
        instantiate(runtime, engine, self.work_id)
        engine.advance(self.work_id, 1000)
        submit_valid(engine, runtime, self.work_id, "n01", "intake")
        submit_valid(engine, runtime, self.work_id, "n02", "analysis")
        submit_valid(engine, runtime, self.work_id, "n03", "proposal")
        proposal = [entry for entry in engine.instance(self.work_id)["nodes"]
                    if entry["node"] == "n03"][0]
        digest_value = proposal["outputs"][0]["digest"]
        for kind, node in (("safety_review", "n04"), ("project_approval", "n05")):
            send(runtime, "reviewer-a", self.work_id, "record_evidence",
                 {"event_id": uuid.uuid4().hex, "kind": kind,
                  "data": {"decision": "approved", "digest": digest_value,
                           "revision": 1, "node": node, "attempt": 1,
                           "actor": "reviewer-a",
                           "items": [{"check": "N04-2", "verdict": "passed",
                                      "reason": "reviewed", "evidence": ["doc-1"]}]}})
        runtime.verify_pending(self.work_id)
        engine.advance(self.work_id, 1000)
        node = [entry for entry in engine.instance(self.work_id)["nodes"]
                if entry["node"] == "n05"][0]
        self.assertNotEqual(node["state"], "completed")
        self.assertTrue(any(finding["code"] == "WORKFLOW_ROLE_ISOLATION"
                            for finding in node["findings"]))


class ActionTests(WorkflowTestCase):
    def drive_to_dispatch(self):
        self.instantiate()
        self.drive_agents()
        decide(self.runtime, self.engine, self.work_id, "safety_review",
               "reviewer-a", "approved", self.proposal_reference()["digest"],
               self.proposal_reference()["revision"])
        decide(self.runtime, self.engine, self.work_id, "project_approval",
               "reviewer-b", "approved", self.proposal_reference()["digest"],
               self.proposal_reference()["revision"])

    def test_an_approval_creates_exactly_one_external_action(self):
        self.drive_to_dispatch()
        operations = self.rows("operations", "work_id=?", (self.work_id,))
        self.assertEqual(len(operations), 1)
        self.engine.pump(self.adapter, 1000)
        self.assertEqual(self.adapter.effect_count(), 1)
        self.engine.pump(self.adapter, 1000)
        self.assertEqual(self.adapter.effect_count(), 1)
        self.assertEqual(self.node_state("n06")["state"], "completed")
        self.assertEqual(self.node_state("n07")["state"], "running")

    def test_a_replayed_dispatch_never_duplicates_the_effect(self):
        self.drive_to_dispatch()
        self.engine.pump(self.adapter, 1000)
        operation = self.runtime.get_work(self.work_id)
        rows = self.rows("operations", "work_id=?", (self.work_id,))
        operation_id = json_body(rows[0][3])["id"]
        self.runtime.dispatch(operation_id, self.adapter)
        self.runtime.dispatch(operation_id, self.adapter)
        self.assertEqual(self.adapter.effect_count(), 1)

    def test_an_unknown_effect_is_looked_up_and_never_repeated(self):
        self.drive_to_dispatch()
        rows = self.rows("operations", "work_id=?", (self.work_id,))
        operation = json_body(rows[0][3])
        # A real crash between the external effect and the local record: the
        # adapter committed, the runtime never learned the outcome.
        def crash():
            raise RuntimeError("process died after the effect")
        with self.assertRaises(RuntimeError):
            self.runtime.dispatch(operation["id"], self.adapter, fault=crash)
        self.assertEqual(self.adapter.effect_count(), 1)
        self.assertEqual(self.runtime.get_operation(operation["id"])["status"],
                         "dispatched")
        self.engine.recover(self.adapter, 1000)
        self.assertEqual(self.adapter.effect_count(), 1)
        self.assertEqual(self.runtime.get_operation(operation["id"])["status"],
                         "confirmed_succeeded")
        self.assertEqual(self.node_state("n06")["state"], "completed")


def json_body(text):
    import json
    return json.loads(text)


if __name__ == "__main__":
    unittest.main()
