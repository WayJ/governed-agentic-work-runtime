"""The atomic acceptance of a successful mixed-node workflow.

The platform runner closes its task on the strength of an acceptance, not on
the strength of a mutable read: ``workflow_status = finished`` says that the
routing stopped, never that the work was delivered. These tests drive the
real ``Runtime`` and the real ``WorkflowEngine`` and assert the stored
receipt, the stored snapshot and the frozen state — never a return value
alone.

The fixture is a two-node workflow published as data: an agent node that
produces the material and an automatic node that performs exactly one
external effect. The family is the demonstration family with its obligation
already satisfied, so the acceptance is exercised for what it is: the
verification of a terminal, the settledness of the material, the settledness
of the effects and the settledness of the obligations.
"""

import http.client
import json
import os
import sqlite3
import tempfile
import threading
import unittest

from work_runtime.runtime import Runtime
from work_runtime.workflow import WorkflowEngine
from work_runtime.workflow_demo import EFFECT_SHAPE, INTAKE_SHAPE
from work_runtime.workflow_server import API_PREFIX, serve

try:
    from workflow_support import (DemoPolicy, RecordingAdapter, decide_command,
                                  demo_grants, demo_validators, instantiate,
                                  submit_valid, version_of)
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import (DemoPolicy, RecordingAdapter,
                                        decide_command, demo_grants,
                                        demo_validators, instantiate,
                                        submit_valid, version_of)

RUNNER = "workflow-runner"
WORK_ID = "W-1"

# The sentinel of "keep the configured runner".
UNCHANGED = object()


class OpenPolicy(DemoPolicy):
    """The demonstration family with its obligation already satisfied."""

    def evaluate(self, work, evidence):
        return [{"id": "R01:" + work["document"]["id"], "rule_id": "R01",
                 "subject": work["document"]["id"], "applicability": "applicable",
                 "fulfillment": "satisfied",
                 "explanation": "The obligation is satisfied in this fixture"}]


class PendingPolicy(DemoPolicy):
    """The same family with one obligation outstanding.

    The obligation the automatic node needs is satisfied, so the workflow
    really reaches its terminal; the second one is not, so the acceptance
    must still be refused.
    """

    def evaluate(self, work, evidence):
        subject = work["document"]["id"]
        return [{"id": "R01:" + subject, "rule_id": "R01", "subject": subject,
                 "applicability": "applicable", "fulfillment": "satisfied",
                 "explanation": "The dispatch obligation is satisfied"},
                {"id": "R02:" + subject, "rule_id": "R02", "subject": subject,
                 "applicability": "applicable", "fulfillment": "pending",
                 "explanation": "The delivery obligation is outstanding"}]


class RejectingAdapter:
    """An external system that refuses the effect."""

    def execute(self, key, document, content_digest, *, action=None,
                compensates=None):
        return {"status": "rejected", "external_id": "EXT-REJECTED",
                "digest": content_digest, "action": action,
                "payload": {"recordId": "EXT-REJECTED", "action": action,
                            "items": ["M-1"]}}

    def lookup(self, key):
        return None


class InvalidOutputAdapter:
    """An external system whose receipt does not satisfy the criterion."""

    def execute(self, key, document, content_digest, *, action=None,
                compensates=None):
        return {"status": "accepted", "external_id": "EXT-BAD",
                "digest": content_digest, "action": "work.deliver",
                "payload": {"recordId": "EXT-BAD", "action": "work.deliver",
                            "items": []}}

    def lookup(self, key):
        return None


def finalization_template(template_id="finalization-fixture", version="t1"):
    """The published definition of the fixture: data, never engine code."""
    return {
        "id": template_id,
        "version": version,
        "policy_family": "workflow-demo",
        "entry": "n01",
        "terminal": ["n02"],
        "nodes": {
            "n01": {"kind": "agent", "executor": "agent-executor",
                    "max_attempts": 1,
                    "output": {"object": "intake",
                               "validation": {"shape": INTAKE_SHAPE,
                                              "validator": "intake",
                                              "validator_version": "1"}},
                    "checks": [{"id": "N01-1", "method": "PROGRAM",
                                "criterion": "Every record names its source.",
                                "criterion_version": "1",
                                "validator": "intake",
                                "validator_version": "1"}]},
            "n02": {"kind": "action", "capability": "work.dispatch",
                    "subject": {"object": "intake"},
                    "output": {"object": "order",
                               "validation": {"shape": EFFECT_SHAPE,
                                              "validator": "effect",
                                              "validator_version": "1"}},
                    "checks": [{"id": "N02-1", "method": "PROGRAM",
                                "criterion": "The receipt names the order it "
                                            "created.",
                                "criterion_version": "1",
                                "validator": "effect",
                                "validator_version": "1"}]},
        },
        "edges": [{"from": "n01", "to": "n02"}],
    }


def human_terminal_template(template_id="finalization-human", version="t1"):
    """The same fixture with a human terminal node.

    A human node that approves completes with the verdict of its kind
    ("approved"), not with the "completed" of an automatic node: the
    acceptance reads the *state* of the terminal node, so both count.
    """
    return {
        "id": template_id,
        "version": version,
        "policy_family": "workflow-demo",
        "entry": "n01",
        "terminal": ["n02"],
        "nodes": {
            "n01": {"kind": "agent", "executor": "agent-executor",
                    "max_attempts": 1,
                    "output": {"object": "intake",
                               "validation": {"shape": INTAKE_SHAPE,
                                              "validator": "intake",
                                              "validator_version": "1"}}},
            "n02": {"kind": "human", "evidence_kind": "safety_review",
                    "authority": "reviewer-a", "subject": {"object": "intake"},
                    "checks": [{"id": "N02-1", "method": "HUMAN",
                                "criterion": "The intake covers every "
                                            "applicable requirement.",
                                "criterion_version": "1",
                                "validator": "safety-review",
                                "validator_version": "1"}]},
        },
        "edges": [{"from": "n01", "to": "n02"}],
    }


class FinalizationTestCase(unittest.TestCase):
    """The fixture: one workflow, one external effect, one runner."""

    policy_class = OpenPolicy
    runner = RUNNER

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-finalization-")
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.adapter_path = os.path.join(self.folder, "effects.sqlite")
        self.runtime, self.engine = self.build()
        self.adapter = RecordingAdapter(self.adapter_path)
        self.template = finalization_template()
        published = self.engine.publish_template("coordinator", self.template)
        self.assertEqual(published["decision"], "accepted", published)

    # -- helpers ---------------------------------------------------------

    def build(self, policy=None, runner=UNCHANGED, path=None):
        grants = demo_grants()
        grants[RUNNER] = {"workflow.finalize"}
        # The trusted source may also withdraw a proof it wrote, so the
        # frozen workflow can be tested against a late revocation.
        grants["business-system"] = {"evidence.write", "evidence.revoke"}
        runtime = Runtime(path or self.path,
                          policy or self.policy_class(), grants)
        engine = WorkflowEngine(runtime, demo_validators(),
                                runner=self.runner if runner is UNCHANGED
                                else runner)
        return runtime, engine

    def rows(self, table, where="1=1", arguments=()):
        db = sqlite3.connect(self.path)
        try:
            return db.execute("SELECT * FROM " + table + " WHERE " + where,
                              arguments).fetchall()
        except sqlite3.OperationalError:
            return []
        finally:
            db.close()

    def events(self):
        return [entry["type"] for entry in self.runtime.events(WORK_ID)]

    def drive_to_success(self, adapter=None, crash=False):
        """Drive the fixture to its successful terminal.

        ``adapter`` replaces the external system, ``crash`` kills the
        process between the external effect and the local record.
        """
        receipt = instantiate(self.runtime, self.engine, WORK_ID,
                              template=self.template)
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.engine.advance(WORK_ID, 1000)
        submitted = submit_valid(self.engine, self.runtime, WORK_ID, "n01", "intake")
        self.assertEqual(submitted["decision"], "accepted", submitted)
        self.engine.advance(WORK_ID, 1000)
        if crash:
            rows = self.rows("operations", "work_id=?", (WORK_ID,))
            operation = json.loads(rows[0][3])

            def fault():
                raise RuntimeError("process died after the effect")

            with self.assertRaises(RuntimeError):
                self.runtime.dispatch(operation["id"], self.adapter, fault=fault)
            return self.runtime.get_work(WORK_ID)
        if adapter is not None:
            self.adapter = adapter
        self.engine.pump(self.adapter, 1000)
        self.engine.advance(WORK_ID, 1000)
        return self.runtime.get_work(WORK_ID)

    def assert_successful_terminal_after_drive(self):
        self.drive_to_success()
        return self.assert_successful_terminal()

    def assert_successful_terminal(self):
        """The fixture really reached its successful terminal."""
        work = self.runtime.get_work(WORK_ID)
        self.assertEqual(work["workflow_status"], "finished", work)
        self.assertIsNone(work["workflow_current"], work)
        self.assertEqual(work["workflow_terminal"]["outcome"], "completed", work)
        return work

    def finalize(self, command_id="final-1", expected_version=None, actor=None):
        version = version_of(self.runtime, WORK_ID) if expected_version is None \
            else expected_version
        return self.engine.command(actor or RUNNER, command_id, WORK_ID,
                                   "finalize_workflow_success", {}, version)

    def object_reference(self, name):
        rows = self.rows("workflow_objects", "work_id=? AND name=?",
                         (WORK_ID, name))
        return {"name": name, "revision": rows[-1][2], "digest": rows[-1][3]}


class SuccessfulAcceptanceTests(FinalizationTestCase):
    def test_a_successful_workflow_is_accepted_and_frozen(self):
        self.assert_successful_terminal_after_drive()
        receipt = self.finalize()
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.assertEqual(receipt["code"] if "code" in receipt else None, None)
        work = self.runtime.get_work(WORK_ID)
        self.assertEqual(work["status"], "closed")
        self.assertEqual(work["outcome"], "succeeded")
        self.assertIn("WorkflowFinalized", self.events())
        finalization = receipt["finalization"]
        self.assertEqual(finalization["workId"], WORK_ID)
        self.assertEqual(finalization["finalizedBy"], RUNNER)
        self.assertEqual(finalization["terminal"]["node"], "n02")
        self.assertEqual(finalization["terminal"]["outcome"], "completed")

    def test_the_snapshot_names_the_exact_identities_it_accepted(self):
        self.assert_successful_terminal_after_drive()
        receipt = self.finalize()
        finalization = receipt["finalization"]
        published = self.engine.template(self.template["id"], self.template["version"])
        work = self.runtime.get_work(WORK_ID)
        self.assertEqual(finalization["template"]["id"], self.template["id"])
        self.assertEqual(finalization["template"]["version"], self.template["version"])
        self.assertEqual(finalization["template"]["digest"], published["digest"])
        self.assertEqual(finalization["contract"]["policyId"], "workflow-demo")
        self.assertEqual(finalization["contract"]["policyVersion"], "demo-1")
        self.assertEqual(finalization["contract"]["revision"], 1)
        self.assertEqual(finalization["plan"]["revision"], work["plan_revision"])
        self.assertEqual(finalization["document"]["revision"],
                         work["document_revision"])
        self.assertEqual(finalization["document"]["digest"], work["document_digest"])
        objects = {entry["name"]: entry for entry in finalization["objects"]}
        self.assertEqual(objects["intake"]["revision"],
                         self.object_reference("intake")["revision"])
        self.assertEqual(objects["intake"]["digest"],
                         self.object_reference("intake")["digest"])
        self.assertEqual(objects["order"]["revision"],
                         self.object_reference("order")["revision"])
        self.assertEqual(objects["order"]["digest"],
                         self.object_reference("order")["digest"])
        nodes = {entry["node"]: entry for entry in finalization["nodes"]}
        self.assertEqual(nodes["n01"]["attempt"], 1)
        self.assertEqual(nodes["n01"]["outcome"], "completed")
        self.assertEqual(nodes["n01"]["quality"]["mode"], "validated")
        self.assertEqual(nodes["n02"]["effect"]["status"], "succeeded")
        self.assertEqual(len(finalization["operations"]), 1)
        self.assertEqual(finalization["operations"][0]["status"],
                         "confirmed_succeeded")
        self.assertEqual(finalization["requirements"][0]["fulfillment"], "satisfied")

    def test_the_receipt_replays_after_a_restart(self):
        self.assert_successful_terminal_after_drive()
        receipt = self.finalize("final-restart")
        finalization_id = receipt["finalization"]["finalizationId"]
        runtime, engine = self.build(path=self.path)
        replay = engine.command(RUNNER, "final-restart", WORK_ID,
                                "finalize_workflow_success", {},
                                receipt["finalization"]["stateVersion"] - 1)
        self.assertEqual(replay, receipt)
        stored = runtime.get_command_receipt(RUNNER, "final-restart", WORK_ID)
        self.assertEqual(stored, receipt)
        work = runtime.get_work(WORK_ID)
        self.assertEqual(work["workflow_finalization"]["finalizationId"],
                         finalization_id)
        self.assertEqual(self.events().count("WorkflowFinalized"), 1)

    def test_a_new_command_key_after_the_freeze_creates_no_second_finalization(self):
        self.assert_successful_terminal_after_drive()
        receipt = self.finalize("final-first")
        finalization_id = receipt["finalization"]["finalizationId"]
        again = self.finalize("final-second")
        self.assertEqual(again["decision"], "rejected", again)
        self.assertEqual(again["code"], "WORK_NOT_ACTIONABLE")
        work = self.runtime.get_work(WORK_ID)
        self.assertEqual(work["workflow_finalization"]["finalizationId"],
                         finalization_id)
        self.assertEqual(self.events().count("WorkflowFinalized"), 1)

    def test_a_stale_version_is_refused_before_the_closure(self):
        self.assert_successful_terminal_after_drive()
        stale = version_of(self.runtime, WORK_ID) - 1
        receipt = self.finalize("final-stale", expected_version=stale)
        self.assertEqual(receipt["decision"], "rejected", receipt)
        self.assertEqual(receipt["code"], "STATE_VERSION_CONFLICT")
        work = self.runtime.get_work(WORK_ID)
        self.assertNotEqual(work["status"], "closed")
        self.assertIsNone(work.get("workflow_finalization"))
        self.assertNotIn("WorkflowFinalized", self.events())

    def test_only_the_trusted_runner_may_accept_the_workflow(self):
        self.assert_successful_terminal_after_drive()
        for actor in ("agent-executor", "coordinator", "reviewer-a"):
            receipt = self.finalize("final-" + actor, actor=actor)
            self.assertEqual(receipt["decision"], "rejected", receipt)
            self.assertEqual(receipt["code"], "WORKFLOW_RUNNER_MISMATCH")
        self.assertIsNone(self.runtime.get_work(WORK_ID).get("workflow_finalization"))

    def test_a_runtime_without_a_trusted_runner_fails_closed(self):
        self.assert_successful_terminal_after_drive()
        runtime, engine = self.build(runner=None)
        receipt = engine.command(RUNNER, "final-unconfigured", WORK_ID,
                                  "finalize_workflow_success", {},
                                  version_of(runtime, WORK_ID))
        self.assertEqual(receipt["decision"], "rejected", receipt)
        self.assertEqual(receipt["code"], "WORKFLOW_RUNNER_UNCONFIGURED")
        self.assertIsNone(runtime.get_work(WORK_ID).get("workflow_finalization"))


class RefusalTests(FinalizationTestCase):
    def test_a_failed_terminal_cannot_be_accepted(self):
        self.drive_to_success(adapter=RejectingAdapter())
        receipt = self.finalize()
        self.assertEqual(receipt["decision"], "rejected", receipt)
        self.assertEqual(receipt["code"], "WORKFLOW_TERMINAL_NOT_COMPLETED")
        self.assertIsNone(self.runtime.get_work(WORK_ID).get("workflow_finalization"))

    def test_an_output_invalid_terminal_cannot_be_accepted(self):
        self.drive_to_success(adapter=InvalidOutputAdapter())
        receipt = self.finalize()
        self.assertEqual(receipt["decision"], "rejected", receipt)
        self.assertEqual(receipt["code"], "WORKFLOW_TERMINAL_NOT_COMPLETED")
        work = self.runtime.get_work(WORK_ID)
        self.assertIsNone(work.get("workflow_finalization"))
        self.assertNotEqual(work["status"], "closed")

    def test_a_cancelled_workflow_cannot_be_accepted(self):
        self.drive_to_success()
        cancelled = self.runtime.command("coordinator", "cancel-1", WORK_ID,
                                         "request_cancel", {"reason": "stop"},
                                         version_of(self.runtime, WORK_ID))
        self.assertEqual(cancelled["decision"], "accepted", cancelled)
        receipt = self.finalize()
        self.assertEqual(receipt["decision"], "rejected", receipt)
        self.assertEqual(receipt["code"], "WORKFLOW_CANCELLED")
        self.assertIsNone(self.runtime.get_work(WORK_ID).get("workflow_finalization"))

    def test_an_unknown_effect_cannot_be_accepted(self):
        self.drive_to_success(crash=True)
        receipt = self.finalize()
        self.assertEqual(receipt["decision"], "rejected", receipt)
        self.assertEqual(receipt["code"], "WORKFLOW_NOT_FINISHED")
        work = self.runtime.get_work(WORK_ID)
        self.assertIsNone(work.get("workflow_finalization"))
        self.assertEqual(self.adapter.effect_count(), 1)

    def test_an_outstanding_requirement_cannot_be_accepted(self):
        runtime, engine = self.build(policy=PendingPolicy())
        self.runtime, self.engine = runtime, engine
        self.drive_to_success()
        receipt = self.finalize()
        self.assertEqual(receipt["decision"], "rejected", receipt)
        self.assertEqual(receipt["code"], "WORKFLOW_REQUIREMENT_UNSATISFIED")
        self.assertIsNone(self.runtime.get_work(WORK_ID).get("workflow_finalization"))

    def test_a_running_workflow_cannot_be_accepted(self):
        instantiate(self.runtime, self.engine, WORK_ID, template=self.template)
        self.engine.advance(WORK_ID, 1000)
        receipt = self.finalize()
        self.assertEqual(receipt["decision"], "rejected", receipt)
        self.assertEqual(receipt["code"], "WORKFLOW_NOT_FINISHED")
        self.assertIsNone(self.runtime.get_work(WORK_ID).get("workflow_finalization"))


class FrozenStateTests(FinalizationTestCase):
    def test_an_unbounded_snapshot_is_refused_instead_of_truncated(self):
        """A partial snapshot is not the snapshot of the accepted workflow."""
        self.assert_successful_terminal_after_drive()
        for index in range(65):
            receipt = self.engine.command(
                "coordinator", "extra-" + str(index), WORK_ID, "revise_object",
                {"name": "extra-" + str(index), "object": {"index": index}},
                version_of(self.runtime, WORK_ID))
            self.assertEqual(receipt["decision"], "accepted", receipt)
        receipt = self.finalize()
        self.assertEqual(receipt["decision"], "rejected", receipt)
        self.assertEqual(receipt["code"], "WORKFLOW_SNAPSHOT_UNBOUNDED")
        self.assertIsNone(self.runtime.get_work(WORK_ID).get("workflow_finalization"))

    def test_a_finished_workflow_is_not_routed_again(self):
        """The terminal is a fact: the next routing pass changes nothing."""
        self.assert_successful_terminal_after_drive()
        before_version = version_of(self.runtime, WORK_ID)
        before_nodes = self.rows("workflow_nodes")
        self.engine.advance(WORK_ID, 1000)
        self.engine.recover(self.adapter, 1000)
        self.assertEqual(version_of(self.runtime, WORK_ID), before_version)
        self.assertEqual(self.rows("workflow_nodes"), before_nodes)
        work = self.runtime.get_work(WORK_ID)
        self.assertEqual(work["workflow_status"], "finished")
        self.assertIsNone(work["workflow_current"])

    def test_nothing_may_change_the_accepted_workflow(self):
        self.drive_to_success()
        receipt = self.finalize()
        self.assertEqual(receipt["decision"], "accepted", receipt)
        before_events = self.events()
        before_objects = self.rows("workflow_objects")
        before_effects = self.adapter.effect_count()
        version = version_of(self.runtime, WORK_ID)

        refused = {
            "object": self.engine.command("coordinator", "after-object", WORK_ID,
                                          "revise_object",
                                          {"name": "intake",
                                           "object": {"records": [],
                                                      "standard": "STD-2"}},
                                          version),
            "result": self.engine.command("agent-executor", "after-result",
                                           WORK_ID, "submit_node_result",
                                           {"node": "n01", "attempt": 1,
                                            "object": "intake",
                                            "result": {"records": [],
                                                       "standard": "STD-3"},
                                            "input_digest": "x"},
                                           version),
            "plan": self.runtime.command("coordinator", "after-plan", WORK_ID,
                                         "revise_plan",
                                         {"steps": ["n01"], "open_requirements": [],
                                          "replan_when": []}, version),
            "document": self.runtime.command("coordinator", "after-document",
                                             WORK_ID, "revise_document",
                                             {"document": {"id": "H-001",
                                                           "subject": "other"}},
                                             version),
            "cancel": self.runtime.command("coordinator", "after-cancel", WORK_ID,
                                           "request_cancel", {"reason": "late"},
                                           version),
            "effect": self.runtime.command("coordinator", "after-effect", WORK_ID,
                                           "propose_action",
                                           {"capability": "work.dispatch",
                                            "contract_revision": 1,
                                            "plan_revision": 1,
                                            "document_digest":
                                                self.runtime.get_work(WORK_ID)[
                                                    "document_digest"]},
                                           version),
        }
        for name, answer in refused.items():
            self.assertEqual(answer["decision"], "rejected", (name, answer))
        self.assertEqual(self.events(), before_events)
        self.assertEqual(self.rows("workflow_objects"), before_objects)
        self.assertEqual(self.adapter.effect_count(), before_effects)
        self.assertEqual(self.runtime.get_work(WORK_ID)["workflow_finalization"],
                         receipt["finalization"])

    def test_a_late_proof_cannot_reopen_the_accepted_workflow(self):
        self.drive_to_success()
        receipt = self.finalize()
        self.assertEqual(receipt["decision"], "accepted", receipt)
        frozen = self.runtime.get_work(WORK_ID)["workflow_finalization"]
        late = self.runtime.command("business-system", "late-proof", WORK_ID,
                                    "record_evidence",
                                    {"event_id": "late-1", "kind": "accepted",
                                     "data": {"digest": "d", "external_id": "E-1"}},
                                    None)
        self.assertEqual(late["decision"], "accepted", late)
        self.runtime.verify_pending(WORK_ID)
        self.engine.advance(WORK_ID, 1000)
        work = self.runtime.get_work(WORK_ID)
        self.assertEqual(work["workflow_finalization"], frozen)
        self.assertEqual(work["workflow_status"], "finished")
        self.assertIsNone(work.get("workflow_current"))
        self.assertEqual(self.adapter.effect_count(), 1)

    def test_a_revocation_cannot_reopen_the_accepted_workflow(self):
        self.drive_to_success()
        receipt = self.finalize()
        self.assertEqual(receipt["decision"], "accepted", receipt)
        frozen = self.runtime.get_work(WORK_ID)["workflow_finalization"]
        self.runtime.command("business-system", "late-proof", WORK_ID,
                             "record_evidence",
                             {"event_id": "late-1", "kind": "accepted",
                              "data": {"digest": "d", "external_id": "E-1"}}, None)
        self.runtime.verify_pending(WORK_ID)
        revoked = self.runtime.command("business-system", "late-revoke", WORK_ID,
                                       "revoke_evidence",
                                       {"source": "business-system",
                                        "event_id": "late-1",
                                        "reason": "not needed"},
                                       version_of(self.runtime, WORK_ID))
        self.assertEqual(revoked["decision"], "accepted", revoked)
        self.engine.advance(WORK_ID, 1000)
        work = self.runtime.get_work(WORK_ID)
        self.assertEqual(work["workflow_finalization"], frozen)
        self.assertEqual(work["workflow_status"], "finished")
        self.assertEqual(self.adapter.effect_count(), 1)

    def test_the_acceptance_and_a_mutation_do_not_both_win(self):
        self.drive_to_success()
        version = version_of(self.runtime, WORK_ID)
        barrier = threading.Barrier(2)
        receipts = {}

        def accept():
            barrier.wait()
            receipts["accept"] = self.engine.command(
                RUNNER, "final-concurrent", WORK_ID,
                "finalize_workflow_success", {}, version)

        def mutate():
            barrier.wait()
            receipts["mutate"] = self.engine.command(
                "coordinator", "object-concurrent", WORK_ID, "revise_object",
                {"name": "intake", "object": {"records": [], "standard": "STD-2"}},
                version)

        threads = [threading.Thread(target=accept), threading.Thread(target=mutate)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        accepted = [name for name, answer in receipts.items()
                    if answer.get("decision") == "accepted"]
        self.assertEqual(len(accepted), 1, receipts)
        loser = [answer for answer in receipts.values()
                 if answer.get("decision") == "rejected"][0]
        self.assertEqual(loser["code"], "STATE_VERSION_CONFLICT")
        work = self.runtime.get_work(WORK_ID)
        if "accept" in accepted:
            self.assertEqual(work["status"], "closed")
            self.assertIsNotNone(work.get("workflow_finalization"))
        else:
            self.assertIsNone(work.get("workflow_finalization"))


class HumanTerminalTests(FinalizationTestCase):
    """A workflow whose terminal node is a human one."""

    def drive_to_approval(self):
        self.template = human_terminal_template()
        published = self.engine.publish_template("coordinator", self.template)
        self.assertEqual(published["decision"], "accepted", published)
        receipt = instantiate(self.runtime, self.engine, WORK_ID,
                              template=self.template)
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.engine.advance(WORK_ID, 1000)
        submitted = submit_valid(self.engine, self.runtime, WORK_ID, "n01", "intake")
        self.assertEqual(submitted["decision"], "accepted", submitted)
        self.engine.advance(WORK_ID, 1000)
        reference = self.object_reference("intake")
        decided = decide_command(
            self.engine, self.runtime, WORK_ID, "safety_review", "reviewer-a",
            "approved", reference["digest"], reference["revision"], node="n02",
            items=[{"check": "N02-1", "verdict": "passed",
                    "reason": "every applicable requirement is covered",
                    "evidence": ["intake#revision-1"]}])
        self.assertEqual(decided["decision"], "accepted", decided)
        self.engine.advance(WORK_ID, 1000)
        return self.runtime.get_work(WORK_ID)

    def test_an_approved_human_terminal_is_accepted(self):
        work = self.drive_to_approval()
        self.assertEqual(work["workflow_status"], "finished", work)
        # The verdict of a human node is its own: "approved", not
        # "completed". The acceptance reads the state of the node.
        self.assertEqual(work["workflow_terminal"]["outcome"], "approved", work)
        receipt = self.finalize()
        self.assertEqual(receipt["decision"], "accepted", receipt)
        finalization = receipt["finalization"]
        self.assertEqual(finalization["terminal"]["node"], "n02")
        self.assertEqual(finalization["terminal"]["state"], "completed")
        self.assertEqual(finalization["terminal"]["outcome"], "approved")

    def test_a_rejected_human_terminal_is_not_accepted(self):
        self.template = human_terminal_template()
        published = self.engine.publish_template("coordinator", self.template)
        self.assertEqual(published["decision"], "accepted", published)
        instantiate(self.runtime, self.engine, WORK_ID, template=self.template)
        self.engine.advance(WORK_ID, 1000)
        submit_valid(self.engine, self.runtime, WORK_ID, "n01", "intake")
        self.engine.advance(WORK_ID, 1000)
        reference = self.object_reference("intake")
        decided = decide_command(
            self.engine, self.runtime, WORK_ID, "safety_review", "reviewer-a",
            "rejected", reference["digest"], reference["revision"], node="n02",
            items=[{"check": "N02-1", "verdict": "failed",
                    "reason": "the intake misses a requirement",
                    "evidence": ["intake#revision-1"]}])
        self.assertEqual(decided["decision"], "accepted", decided)
        self.engine.advance(WORK_ID, 1000)
        receipt = self.finalize()
        self.assertEqual(receipt["decision"], "rejected", receipt)
        self.assertIn(receipt["code"], ("WORKFLOW_TERMINAL_NOT_COMPLETED",
                                        "WORKFLOW_NOT_FINISHED"))
        self.assertIsNone(self.runtime.get_work(WORK_ID).get("workflow_finalization"))


class HttpFinalizationTests(FinalizationTestCase):
    """The bridge: the platform request and the immutable completion read."""

    def setUp(self):
        super().setUp()
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

    def test_the_bridge_accepts_the_workflow_and_answers_the_completion(self):
        self.drive_to_success()
        version = version_of(self.runtime, WORK_ID)
        status, body = self.call("POST", API_PREFIX + "/instances/" + WORK_ID
                                 + "/finalize",
                                 {"commandId": "http-final", "expectedVersion": version})
        self.assertEqual(status, 200, body)
        finalization = body["finalization"]
        self.assertEqual(finalization["finalizedBy"], RUNNER)
        self.assertEqual(finalization["terminal"]["outcome"], "completed")
        status, completion = self.call("GET", API_PREFIX + "/instances/" + WORK_ID
                                       + "/completion")
        self.assertEqual(status, 200, completion)
        self.assertEqual(completion["finalization"], finalization)
        # The completion read is immutable: it answers the same snapshot.
        status, again = self.call("GET", API_PREFIX + "/instances/" + WORK_ID
                                  + "/completion")
        self.assertEqual(again, completion)

    def test_the_bridge_refuses_a_stale_version_and_a_foreign_actor(self):
        self.drive_to_success()
        version = version_of(self.runtime, WORK_ID)
        status, body = self.call("POST", API_PREFIX + "/instances/" + WORK_ID
                                 + "/finalize",
                                 {"commandId": "http-stale",
                                  "expectedVersion": version - 1})
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error"]["code"], "STATE_VERSION_CONFLICT")
        status, body = self.call("POST", API_PREFIX + "/instances/" + WORK_ID
                                 + "/finalize",
                                 {"commandId": "http-actor",
                                  "expectedVersion": version,
                                  "actor": "agent-executor"})
        self.assertEqual(status, 403, body)
        self.assertEqual(body["error"]["code"], "WORKFLOW_RUNNER_MISMATCH")
        status, body = self.call("GET", API_PREFIX + "/instances/" + WORK_ID
                                 + "/completion")
        self.assertEqual(status, 404, body)
        self.assertEqual(body["error"]["code"], "WORKFLOW_NOT_FINALIZED")

    def test_the_bridge_refuses_a_mutation_of_an_accepted_workflow(self):
        self.drive_to_success()
        version = version_of(self.runtime, WORK_ID)
        status, body = self.call("POST", API_PREFIX + "/instances/" + WORK_ID
                                 + "/finalize",
                                 {"commandId": "http-final", "expectedVersion": version})
        self.assertEqual(status, 200, body)
        status, body = self.call("POST", API_PREFIX + "/instances/" + WORK_ID
                                 + "/objects",
                                 {"name": "intake",
                                  "object": {"records": [], "standard": "STD-2"},
                                  "actor": "coordinator", "commandId": "http-object",
                                  "expectedVersion": version_of(self.runtime, WORK_ID)})
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error"]["code"], "WORKFLOW_FINALIZED")
