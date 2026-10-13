"""S3 intervention lifecycle: registry, cancellation, ownership, migration."""

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from work_runtime import CommandError, ExpensePolicy, Runtime
from work_runtime.adapters import FakeOA
from work_runtime.demo import action, demo_grants, document, initialize, prerequisites, proof, send
from work_runtime.policy import ExpensePolicyV2, canonical, digest
from work_runtime.publishing import PublishingPolicy


def initialize_under(runtime, work_id="demo"):
    """Bind whatever policy version the runtime defaults to."""
    policy = runtime.policy
    send(runtime, work_id, "create_work", {"document": document()})
    send(runtime, work_id, "bind_contract", {"policy_id": policy.id,
         "policy_version": policy.version, "goal": policy.goal})
    send(runtime, work_id, "revise_plan", {"steps": ["verify", "approve", "confirm", "submit"],
         "open_requirements": ["E05"], "replan_when": ["invoice anomaly"]})


def intervention_grants():
    grants = demo_grants()
    grants["root"] = {"work.intervene"}
    return grants


def repin_contract(path, work_id, version):
    """Simulate a pre-existing database whose Work is pinned to `version`."""
    db = sqlite3.connect(path)
    try:
        work = json.loads(db.execute(
            "SELECT state FROM works WHERE id=?", (work_id,)).fetchone()[0])
        work["contract"]["policy_version"] = version
        db.execute("UPDATE works SET state=? WHERE id=?", (canonical(work), work_id))
        db.commit()
    finally:
        db.close()


def strip_owner(path, work_id):
    """Simulate a legacy pre-ownership database."""
    db = sqlite3.connect(path)
    try:
        work = json.loads(db.execute(
            "SELECT state FROM works WHERE id=?", (work_id,)).fetchone()[0])
        work.pop("owner", None)
        db.execute("UPDATE works SET state=? WHERE id=?", (canonical(work), work_id))
        db.commit()
    finally:
        db.close()


class OtherExpenseVersion(ExpensePolicy):
    version = "demo-2"


class NoSources(OtherExpenseVersion):
    evidence_sources = None


class BrokenMethod(OtherExpenseVersion):
    operation_key = "not-callable"


class OtherGoal(OtherExpenseVersion):
    goal = "other.goal"


class RegistryContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        self.uncreated = str(Path(self.temp.name) / "never" / "runtime.sqlite")

    def runtime(self, policies=None, policy=None):
        return Runtime(self.path, policy or ExpensePolicy(), demo_grants(),
                       policies=policies)

    def test_policies_argument_is_keyword_only(self):
        with self.assertRaises(TypeError):
            Runtime(self.path, ExpensePolicy(), demo_grants(), {"demo-2": OtherExpenseVersion()})

    def test_default_registry_maps_default_version_to_default_object(self):
        policy = ExpensePolicy()
        runtime = Runtime(self.path, policy, demo_grants())
        self.assertEqual(runtime.policies, {policy.version: policy})
        self.assertIs(runtime.policies[policy.version], policy)

    def test_malformed_registry_rejected_before_any_write(self):
        default = ExpensePolicy()
        other = OtherExpenseVersion()
        broken = [
            ["not-a-dict"],
            {1: other},
            {"": other},
            {"demo-9": ExpensePolicy()},               # key != value.version
            {object()},
            {"demo-2": NoSources()},
            {"demo-2": BrokenMethod()},
            {"demo-1": PublishingPolicy()},             # same version key, other family
            {"demo-2": OtherGoal()},
            {"demo-1": ExpensePolicy()},                # default version -> other object
        ]
        for policies in broken:
            with self.assertRaises(CommandError, msg=repr(policies)):
                Runtime(self.uncreated, default, demo_grants(), policies=policies)
        self.assertFalse(Path(self.uncreated).parent.exists())

    def test_valid_registry_accepts_and_keeps_defaults_working(self):
        runtime = self.runtime({"demo-2": OtherExpenseVersion()})
        self.assertEqual(set(runtime.policies), {"demo-1", "demo-2"})
        initialize(runtime)
        prerequisites(runtime)
        self.assertEqual(action(runtime)["decision"], "accepted")

    def test_registry_mapping_is_copied(self):
        policies = {"demo-2": OtherExpenseVersion()}
        runtime = self.runtime(policies)
        policies["demo-9"] = OtherExpenseVersion()
        self.assertNotIn("demo-9", runtime.policies)

    def test_hand_pinned_version_resolves_through_registry(self):
        runtime = self.runtime({"demo-2": OtherExpenseVersion()})
        initialize(runtime)
        repin_contract(self.path, "demo", "demo-2")
        work = runtime.get_work("demo")
        self.assertEqual(work["contract"]["policy_version"], "demo-2")
        # The pinned work stays fully usable under its loaded version.
        prerequisites(runtime)
        self.assertEqual(action(runtime)["decision"], "accepted")

    def test_missing_pinned_version_fails_closed(self):
        runtime = self.runtime()
        initialize(runtime)
        repin_contract(self.path, "demo", "demo-2")
        reopened = self.runtime()
        with self.assertRaises(CommandError):
            reopened.get_work("demo")
        with self.assertRaises(CommandError):
            reopened.command("agent", "late", "demo", "revise_plan",
                             {"steps": [], "open_requirements": [], "replan_when": []}, 0)


class ExpensePolicyV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "runtime.sqlite")

    def v2_runtime(self):
        return Runtime(self.path, ExpensePolicyV2(), demo_grants())

    def requirement(self, runtime, rule="E05"):
        return next(r for r in runtime.get_work("demo")["requirements"] if r["rule_id"] == rule)

    def approval_candidate(self, version, data=None):
        return {"kind": "approval", "data": data if data is not None else
                {"digest": "d", "policy_version": version}}

    def test_v2_shares_family_goal_and_key_with_v1(self):
        v1, v2 = ExpensePolicy(), ExpensePolicyV2()
        self.assertEqual((v2.id, v2.goal), (v1.id, v1.goal))
        self.assertEqual(v2.evidence_sources, v1.evidence_sources)
        work = {"document": document(), "document_revision": 1}
        self.assertEqual(v1.operation_key("expense.submit", work),
                         v2.operation_key("expense.submit", work))

    def test_v2_approval_evidence_requires_exact_version_bound_fields(self):
        v2 = ExpensePolicyV2()
        self.assertFalse(v2.validate_evidence({}, self.approval_candidate(None, {"digest": "d"})))
        self.assertFalse(v2.validate_evidence({}, self.approval_candidate("demo-1")))
        self.assertFalse(v2.validate_evidence({}, self.approval_candidate(
            "demo-2", {"digest": "d", "policy_version": "demo-2", "extra": 1})))
        self.assertTrue(v2.validate_evidence({}, self.approval_candidate("demo-2")))
        # Other kinds inherit the demo-1 validators.
        self.assertTrue(ExpensePolicy().validate_evidence(
            {}, {"kind": "confirmation", "data": {"digest": "d"}}))
        self.assertTrue(v2.validate_evidence({}, {"kind": "confirmation", "data": {"digest": "d"}}))

    def test_v2_requires_approval_for_every_known_amount(self):
        runtime = self.v2_runtime()
        initialize_under(runtime)
        send(runtime, "demo", "revise_document", {"document": document(amount=80000)})
        prerequisites(runtime, approval=False)
        self.assertEqual(self.requirement(runtime)["applicability"], "applicable")
        self.assertEqual(self.requirement(runtime)["fulfillment"], "pending")
        self.assertEqual(action(runtime)["code"], "REQUIREMENT_UNSATISFIED")

    def test_v2_unknown_amount_keeps_applicability_unknown(self):
        runtime = self.v2_runtime()
        initialize_under(runtime)
        send(runtime, "demo", "revise_document", {"document": document(amount=None)})
        self.assertEqual(self.requirement(runtime)["applicability"], "unknown")
        self.assertEqual(action(runtime)["code"], "APPLICABILITY_UNRESOLVED")

    def test_v1_keeps_over_limit_only_approval(self):
        runtime = Runtime(self.path, ExpensePolicy(), demo_grants())
        initialize_under(runtime)
        send(runtime, "demo", "revise_document", {"document": document(amount=80000)})
        prerequisites(runtime, approval=False)
        self.assertEqual(self.requirement(runtime)["applicability"], "not_applicable")
        self.assertEqual(action(runtime)["decision"], "accepted")

    def test_v2_approval_satisfies_end_to_end(self):
        runtime = self.v2_runtime()
        initialize_under(runtime)
        prerequisites(runtime, approval=False)
        work = runtime.get_work("demo")
        proof(runtime, "demo", "approval", "finance", {
            "digest": work["document_digest"], "policy_version": "demo-2"})
        runtime.verify_pending("demo")
        self.assertEqual(self.requirement(runtime)["fulfillment"], "satisfied")
        self.assertEqual(action(runtime)["decision"], "accepted")


class CancellationRequestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        self.oa_path = str(Path(self.temp.name) / "oa.sqlite")
        self.grants = demo_grants()
        self.runtime = Runtime(self.path, ExpensePolicy(), self.grants)
        self.oa = FakeOA(self.oa_path)
        initialize(self.runtime)

    def submit(self):
        prerequisites(self.runtime)
        receipt = action(self.runtime)
        self.assertEqual(receipt["decision"], "accepted")
        return receipt["operation_id"]

    def cancel(self, reason="stop", actor="agent", command_id=None, work_id="demo"):
        version = self.runtime.get_work(work_id)["state_version"]
        return self.runtime.command(actor, command_id or uuid.uuid4().hex, work_id,
                                    "request_cancel", {"reason": reason}, version)

    def test_cancel_before_dispatch_makes_zero_external_calls(self):
        op = self.submit()
        receipt = self.cancel(reason="wrong invoice")
        self.assertEqual(receipt["decision"], "accepted")
        operation = self.runtime.get_operation(op)
        self.assertEqual(operation["dispatch_state"], "cancelled")
        self.assertEqual(operation["reason"], "WORK_CANCELLED")
        self.assertEqual(self.runtime.dispatch(op, self.oa)["dispatch_state"], "cancelled")
        self.assertEqual(self.oa.accepted_count(), 0)
        self.assertEqual(action(self.runtime)["code"], "CANCELLATION_ACTIVE")

    def test_cancel_cancels_waits_and_blocks_new_waits(self):
        send(self.runtime, "demo", "register_wait", {
            "requirement_id": "E05:EXP-001", "deadline": 2000000000, "owner": "finance"})
        self.cancel()
        self.assertEqual(self.runtime.get_work("demo")["waits"][0]["status"], "cancelled")
        self.assertEqual(send(self.runtime, "demo", "register_wait", {
            "requirement_id": "E05:EXP-001", "deadline": 2000000000,
            "owner": "finance"})["code"], "CANCELLATION_ACTIVE")

    def test_cancel_prohibits_mutations_and_completion(self):
        self.cancel()
        plan = {"steps": ["submit"], "open_requirements": [], "replan_when": []}
        self.assertEqual(send(self.runtime, "demo", "revise_plan", plan)["code"],
                         "CANCELLATION_ACTIVE")
        self.assertEqual(send(self.runtime, "demo", "revise_document",
                              {"document": document(amount=130000)})["code"], "CANCELLATION_ACTIVE")
        self.assertEqual(send(self.runtime, "demo", "request_completion")["code"],
                         "CANCELLATION_ACTIVE")
        send(self.runtime, "raw", "create_work", {"document": document(document_id="RAW-1")})
        self.cancel(work_id="raw")
        self.assertEqual(send(self.runtime, "raw", "bind_contract", {
            "policy_id": "expense-submit", "policy_version": "demo-1",
            "goal": "expense.accepted"})["code"], "CANCELLATION_ACTIVE")

    def test_cancel_intent_is_immutable_and_replay_returns_original(self):
        observed = self.runtime.get_work("demo")["state_version"]
        first = self.cancel(reason="original reason", command_id="cancel-1")
        self.assertEqual(first["decision"], "accepted")
        second = self.cancel(reason="different reason", command_id="cancel-2")
        self.assertEqual(second["code"], "CANCELLATION_ALREADY_REQUESTED")
        self.assertEqual(self.runtime.command("agent", "cancel-1", "demo", "request_cancel",
                                              {"reason": "original reason"}, observed), first)
        cancellation = self.runtime.get_work("demo")["cancellation"]
        self.assertEqual(cancellation, {"requested_by": "agent", "reason": "original reason"})

    def test_cancel_of_establishing_work_is_supported(self):
        send(self.runtime, "raw", "create_work", {"document": document(document_id="RAW-1")})
        receipt = self.cancel(work_id="raw")
        self.assertEqual(receipt["decision"], "accepted")
        self.assertEqual(self.runtime.get_work("raw")["cancellation"]["requested_by"], "agent")

    def test_cancellation_survives_evaluation_expiry_and_recovery(self):
        op = self.submit()
        self.cancel()
        proof(self.runtime, "demo", "approval", "finance")
        self.assertEqual(self.runtime.verify_pending("demo"), 1)
        self.assertEqual(self.runtime.expire_waits("demo", now=2000000000), 0)
        restarted = Runtime(self.path, ExpensePolicy(), demo_grants())
        restarted.recover(self.oa)
        work = restarted.get_work("demo")
        self.assertEqual(work["cancellation"]["reason"], "stop")
        self.assertEqual(restarted.get_operation(op)["dispatch_state"], "cancelled")
        self.assertEqual(self.oa.accepted_count(), 0)

    def test_cancel_payload_must_be_exactly_one_nonempty_reason(self):
        before = self.runtime.get_work("demo")
        for payload in ({}, {"reason": ""}, {"reason": 5}, {"reason": "x", "extra": 1}):
            with self.assertRaises(CommandError, msg=repr(payload)):
                self.runtime.command("agent", uuid.uuid4().hex, "demo", "request_cancel",
                                     payload, before["state_version"])
        self.assertIsNone(self.runtime.get_work("demo").get("cancellation"))
        self.assertEqual(self.runtime.get_work("demo")["state_version"],
                         before["state_version"])

    def test_cancel_authority_owner_or_intervene_admin(self):
        self.assertEqual(self.cancel(actor="finance")["code"], "AUTHORITY_DENIED")
        grants = intervention_grants()
        runtime = Runtime(self.path, ExpensePolicy(), grants)
        initialize(runtime, "admin-work", document(document_id="ADM-1"))
        prerequisites(runtime, "admin-work")
        version = runtime.get_work("admin-work")["state_version"]
        receipt = runtime.command("root", "admin-cancel", "admin-work", "request_cancel",
                                  {"reason": "audit"}, version)
        self.assertEqual(receipt["decision"], "accepted")

    def test_cancel_respects_compare_and_swap(self):
        version = self.runtime.get_work("demo")["state_version"]
        receipt = self.runtime.command("agent", "stale-cancel", "demo", "request_cancel",
                                       {"reason": "stale"}, version - 1)
        self.assertEqual(receipt["code"], "STATE_VERSION_CONFLICT")
        self.assertIsNone(self.runtime.get_work("demo").get("cancellation"))

    def test_duplicate_cancel_commands_share_one_receipt(self):
        version = self.runtime.get_work("demo")["state_version"]

        def invoke(_):
            runtime = Runtime(self.path, ExpensePolicy(), demo_grants())
            return runtime.command("agent", "cancel-concurrent", "demo", "request_cancel",
                                   {"reason": "stop"}, version)

        with ThreadPoolExecutor(max_workers=4) as pool:
            receipts = list(pool.map(invoke, range(4)))
        self.assertTrue(all(r == receipts[0] for r in receipts))
        self.assertEqual(receipts[0]["decision"], "accepted")
        events = [e for e in self.runtime.events("demo") if e["type"] == "CancellationRequested"]
        self.assertEqual(len(events), 1)

    def test_evidence_intake_proceeds_during_cancellation(self):
        self.cancel()
        self.assertEqual(proof(self.runtime, "demo", "approval", "finance")["decision"],
                         "accepted")


class FinalizeCancelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        self.oa_path = str(Path(self.temp.name) / "oa.sqlite")
        self.grants = intervention_grants()
        self.runtime = Runtime(self.path, ExpensePolicy(), self.grants)
        self.oa = FakeOA(self.oa_path)
        initialize(self.runtime)

    def submit(self):
        prerequisites(self.runtime)
        receipt = action(self.runtime)
        self.assertEqual(receipt["decision"], "accepted")
        return receipt["operation_id"]

    def finalize(self, ack, actor="agent", command_id=None, work_id="demo"):
        version = self.runtime.get_work(work_id)["state_version"]
        return self.runtime.command(actor, command_id or uuid.uuid4().hex, work_id,
                                    "finalize_cancel", {"acknowledged_operations": ack},
                                    version)

    def test_finalize_requires_prior_request(self):
        self.assertEqual(self.finalize([])["code"], "CANCELLATION_NOT_REQUESTED")

    def test_zero_effect_finalize_closes_cancelled(self):
        op = self.submit()
        self.assertEqual(self.runtime.command("agent", "cancel-1", "demo", "request_cancel",
                                              {"reason": "stop"},
                                              self.runtime.get_work("demo")["state_version"]
                                              )["decision"], "accepted")
        receipt = self.finalize([])
        self.assertEqual(receipt["decision"], "accepted")
        work = self.runtime.get_work("demo")
        self.assertEqual((work["status"], work["outcome"]), ("closed", "cancelled"))
        completion = work["completion"]
        self.assertEqual(completion["acknowledged_operations"], [])
        self.assertEqual(completion["operation_dispositions"],
                         [{"operation_id": op, "status": "prepared",
                           "dispatch_state": "cancelled"}])
        self.assertEqual(self.oa.accepted_count(), 0)
        self.assertNotEqual(work["outcome"], "succeeded")

    def test_finalize_after_timeout_requires_exact_acknowledgement(self):
        op = self.submit()
        # The attempt is durable (and the external effect committed) before
        # cancellation is requested: it stays uncertain until queried.
        self.assertEqual(self.runtime.dispatch(op, FakeOA(
            self.oa_path, timeout_after_commit=True))["status"], "outcome_unknown")
        self.assertEqual(self.oa.accepted_count(), 1)
        self.assertEqual(self.runtime.command("agent", "cancel-1", "demo", "request_cancel",
                                              {"reason": "stop"},
                                              self.runtime.get_work("demo")["state_version"]
                                              )["decision"], "accepted")
        self.assertEqual(self.finalize([])["code"], "OUTCOME_UNRESOLVED")
        self.runtime.reconcile(op, self.oa)
        self.assertEqual(self.runtime.get_operation(op)["status"], "confirmed_succeeded")
        mismatch = self.finalize([])
        self.assertEqual(mismatch["code"], "CANCEL_ACKNOWLEDGEMENT_MISMATCH")
        self.assertEqual(mismatch["blockers"], [op])
        receipt = self.finalize([op])
        self.assertEqual(receipt["decision"], "accepted")
        work = self.runtime.get_work("demo")
        self.assertEqual((work["status"], work["outcome"]), ("closed", "cancelled"))
        self.assertEqual(work["completion"]["acknowledged_operations"],
                         [{"operation_id": op,
                           "external_id": self.runtime.get_operation(op)["external_id"]}])
        self.assertEqual(self.oa.accepted_count(), 1)

    def test_finalize_after_real_process_death(self):
        op = self.submit()
        child = subprocess.run([sys.executable, "-m", "work_runtime", "worker",
                                "--runtime", self.path, "--oa", self.oa_path,
                                "--operation", op, "--crash-after-effect"], check=False)
        self.assertEqual(child.returncode, 73)
        self.assertEqual(self.oa.accepted_count(), 1)
        self.assertEqual(self.runtime.command("agent", "cancel-1", "demo", "request_cancel",
                                              {"reason": "stop"},
                                              self.runtime.get_work("demo")["state_version"]
                                              )["decision"], "accepted")
        self.assertEqual(self.finalize([])["code"], "OUTCOME_UNRESOLVED")
        self.runtime.reconcile(op, self.oa)
        self.assertEqual(self.finalize([op])["decision"], "accepted")
        self.assertEqual(self.runtime.get_work("demo")["outcome"], "cancelled")
        self.assertEqual(self.oa.accepted_count(), 1)

    def test_missing_lookup_cannot_finalize(self):
        op = self.submit()

        class NoAnswer:
            def execute(self, *args):
                raise TimeoutError()
            def lookup(self, key):
                return None

        self.runtime.dispatch(op, NoAnswer())
        self.assertEqual(self.runtime.command("agent", "cancel-1", "demo", "request_cancel",
                                              {"reason": "stop"},
                                              self.runtime.get_work("demo")["state_version"]
                                              )["decision"], "accepted")
        self.runtime.reconcile(op, NoAnswer())
        self.assertEqual(self.finalize([])["code"], "OUTCOME_UNRESOLVED")
        self.assertEqual(self.runtime.get_work("demo")["status"], "needs_attention")

    def test_malformed_result_cannot_finalize(self):
        op = self.submit()

        class Malformed:
            def execute(self, *args):
                return {"status": "accepted", "external_id": ""}

        self.runtime.dispatch(op, Malformed())
        self.assertEqual(self.runtime.get_operation(op)["reason"], "ADAPTER_RESULT_INVALID")
        self.assertEqual(self.runtime.command("agent", "cancel-1", "demo", "request_cancel",
                                              {"reason": "stop"},
                                              self.runtime.get_work("demo")["state_version"]
                                              )["decision"], "accepted")
        self.assertEqual(self.finalize([])["code"], "OUTCOME_UNRESOLVED")

    def test_finalize_payload_must_be_distinct_nonempty_ids(self):
        self.assertEqual(self.runtime.command("agent", "cancel-1", "demo", "request_cancel",
                                              {"reason": "stop"},
                                              self.runtime.get_work("demo")["state_version"]
                                              )["decision"], "accepted")
        for ack in ("not-a-list", [""], ["a", "a"], [5], {"op": 1}, ["a", 5]):
            with self.assertRaises(CommandError, msg=repr(ack)):
                self.runtime.command("agent", uuid.uuid4().hex, "demo", "finalize_cancel",
                                     {"acknowledged_operations": ack},
                                     self.runtime.get_work("demo")["state_version"])
        for payload in ({}, {"acknowledged_operations": [], "extra": 1}):
            with self.assertRaises(CommandError, msg=repr(payload)):
                self.runtime.command("agent", uuid.uuid4().hex, "demo", "finalize_cancel",
                                     payload, self.runtime.get_work("demo")["state_version"])

    def test_finalize_after_close_is_not_actionable_but_replay_returns_receipt(self):
        self.submit()
        self.assertEqual(self.runtime.command("agent", "cancel-1", "demo", "request_cancel",
                                              {"reason": "stop"},
                                              self.runtime.get_work("demo")["state_version"]
                                              )["decision"], "accepted")
        version = self.runtime.get_work("demo")["state_version"]
        first = self.runtime.command("agent", "finalize-1", "demo", "finalize_cancel",
                                     {"acknowledged_operations": []}, version)
        self.assertEqual(first["decision"], "accepted")
        fresh = self.runtime.command("agent", "finalize-2", "demo", "finalize_cancel",
                                     {"acknowledged_operations": []},
                                     self.runtime.get_work("demo")["state_version"])
        self.assertEqual(fresh["code"], "WORK_NOT_ACTIONABLE")
        replay = self.runtime.command("agent", "finalize-1", "demo", "finalize_cancel",
                                      {"acknowledged_operations": []}, version)
        self.assertEqual(replay, first)

    def test_admin_can_finalize(self):
        self.submit()
        self.assertEqual(self.runtime.command("agent", "cancel-1", "demo", "request_cancel",
                                              {"reason": "stop"},
                                              self.runtime.get_work("demo")["state_version"]
                                              )["decision"], "accepted")
        self.assertEqual(self.finalize([], actor="root")["decision"], "accepted")


if __name__ == "__main__":
    unittest.main()
