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
    grants["delegate"] = {"work.manage", "expense.submit"}
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

    def test_malformed_default_rejected_for_any_explicit_registry(self):
        # D16: ANY explicit policies dict, including the empty dict, must
        # structurally validate the default policy before any write.
        broken_method = ExpensePolicy()
        broken_method.operation_key = "not-callable"
        broken_sources = ExpensePolicy()
        broken_sources.evidence_sources = None
        uncreated = str(Path(self.temp.name) / "d16" / "never" / "runtime.sqlite")
        for policy, policies in ((broken_method, {}),
                                 (broken_method, {"demo-2": OtherExpenseVersion()}),
                                 (broken_sources, {})):
            with self.assertRaises(CommandError, msg=repr(policies)):
                Runtime(uncreated, policy, demo_grants(), policies=policies)
        self.assertFalse(Path(uncreated).parent.exists())

    def test_valid_additive_registry_and_none_legacy_are_preserved(self):
        runtime = self.runtime({"demo-2": OtherExpenseVersion()})
        self.assertEqual(set(runtime.policies), {"demo-1", "demo-2"})
        legacy = str(Path(self.temp.name) / "legacy" / "runtime.sqlite")
        malformed = ExpensePolicy()
        malformed.operation_key = "not-callable"
        Runtime(legacy, malformed, demo_grants())  # policies=None keeps legacy behavior
        self.assertTrue(Path(legacy).parent.exists())

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

    def test_v2_blocker_explains_all_known_amount_approval(self):
        runtime = self.v2_runtime()
        initialize_under(runtime)
        send(runtime, "demo", "revise_document", {"document": document(amount=80000)})
        prerequisites(runtime, approval=False)
        receipt = action(runtime)
        self.assertEqual(receipt["code"], "REQUIREMENT_UNSATISFIED")
        blocker = next(b for b in receipt["blockers"] if b["rule_id"] == "E05")
        explanation = blocker["explanation"].lower()
        self.assertIn("known amount", explanation)
        self.assertIn("version", explanation)
        self.assertNotIn("over-limit", explanation)
        # v1 diagnostics stay exactly as they were.
        v1 = Runtime(str(Path(self.temp.name) / "v1.sqlite"), ExpensePolicy(), demo_grants())
        initialize_under(v1)
        prerequisites(v1, approval=False)
        v1_blocker = next(b for b in action(v1)["blockers"] if b["rule_id"] == "E05")
        self.assertEqual(v1_blocker["explanation"],
                         "Over-limit submissions require approval of the current content")

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

    def test_finalize_cancel_on_unbound_work_persists_closed(self):
        send(self.runtime, "unbound", "create_work",
             {"document": document(document_id="UNB-001")})
        proof(self.runtime, "unbound", "approval", "finance")
        send(self.runtime, "unbound", "request_cancel", {"reason": "stop"})
        receipt = self.finalize([], work_id="unbound")
        self.assertEqual(receipt["decision"], "accepted")
        work = self.runtime.get_work("unbound")
        self.assertEqual(work["status"], "closed")
        self.assertEqual(work["outcome"], "cancelled")
        self.assertIn("cancellation", work["completion"])

    def test_unbound_closed_work_stays_closed_under_late_verification_and_recovery(self):
        send(self.runtime, "unbound", "create_work",
             {"document": document(document_id="UNB-001")})
        proof(self.runtime, "unbound", "approval", "finance")
        send(self.runtime, "unbound", "request_cancel", {"reason": "stop"})
        self.finalize([], work_id="unbound")
        completion = self.runtime.get_work("unbound")["completion"]
        restarted = Runtime(self.path, ExpensePolicy(), self.grants)
        self.assertEqual(restarted.verify_pending("unbound"), 1)
        restarted.recover(self.oa)
        work = restarted.get_work("unbound")
        self.assertEqual(work["status"], "closed")
        self.assertEqual(work["outcome"], "cancelled")
        self.assertEqual(work["completion"], completion)


class OwnershipTests(unittest.TestCase):
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

    def transfer(self, owner="delegate", reason="handover", actor="agent", work_id="demo"):
        version = self.runtime.get_work(work_id)["state_version"]
        return self.runtime.command(actor, uuid.uuid4().hex, work_id, "transfer_owner",
                                    {"owner": owner, "reason": reason}, version)

    def test_new_work_stores_creator_as_owner(self):
        self.assertEqual(self.runtime.get_work("demo")["owner"], "agent")

    def test_transfer_persists_actor_reason_and_both_owners(self):
        receipt = self.transfer(reason="vacation")
        self.assertEqual(receipt["decision"], "accepted")
        self.assertEqual(self.runtime.get_work("demo")["owner"], "delegate")
        events = [e for e in self.runtime.events("demo") if e["type"] == "OwnerTransferred"]
        self.assertEqual(len(events), 1)
        details = json.loads(events[0]["body"])
        self.assertEqual(details, {"actor": "agent", "from": "agent", "to": "delegate",
                                   "reason": "vacation", "reassigned_waits": [],
                                   "invalidated_operations": []})

    def test_former_owner_loses_management_proposal_and_dispatch(self):
        op = self.submit()
        self.transfer()
        plan = {"steps": ["submit"], "open_requirements": [], "replan_when": []}
        for kind, payload in (("revise_plan", plan),
                              ("revise_document", {"document": document(amount=130000)}),
                              ("request_completion", None)):
            self.assertEqual(send(self.runtime, "demo", kind, payload)["code"],
                             "AUTHORITY_DENIED")
        self.assertEqual(action(self.runtime)["code"], "AUTHORITY_DENIED")
        invalidated = self.runtime.get_operation(op)
        self.assertEqual(invalidated["dispatch_state"], "cancelled")
        self.assertEqual(invalidated["reason"], "OWNERSHIP_TRANSFERRED")
        self.assertEqual(self.runtime.dispatch(op, self.oa)["dispatch_state"], "cancelled")
        self.assertEqual(self.oa.accepted_count(), 0)

    def test_in_flight_operation_survives_transfer_and_reconciles(self):
        op = self.submit()
        self.assertEqual(self.runtime.dispatch(op, FakeOA(
            self.oa_path, timeout_after_commit=True))["status"], "outcome_unknown")
        self.transfer()
        self.grants["agent"].clear()  # former owner loses every grant
        self.runtime.reconcile(op, self.oa)
        self.assertEqual(self.runtime.get_operation(op)["status"], "confirmed_succeeded")
        self.assertEqual(self.oa.accepted_count(), 1)

    def test_transfer_reassigns_outstanding_waits(self):
        send(self.runtime, "demo", "register_wait", {
            "requirement_id": "E05:EXP-001", "deadline": 2000000000, "owner": "agent"})
        self.transfer()
        waits = self.runtime.get_work("demo")["waits"]
        self.assertEqual(waits[0]["owner"], "delegate")
        self.assertEqual(waits[0]["status"], "waiting")

    def test_new_owner_reproposes_same_operation_and_dispatches(self):
        op = self.submit()
        self.transfer()
        work = self.runtime.get_work("demo")
        receipt = send(self.runtime, "demo", "propose_action", {
            "capability": "expense.submit", "document_digest": work["document_digest"],
            "contract_revision": work["contract"]["revision"],
            "plan_revision": work["plan_revision"]}, actor="delegate")
        self.assertEqual(receipt["decision"], "accepted")
        self.assertEqual(receipt["operation_id"], op)
        operation = self.runtime.get_operation(op)
        self.assertEqual(operation["actor"], "delegate")
        self.assertEqual(operation["dispatch_state"], "ready")
        self.assertEqual(self.runtime.dispatch(op, self.oa)["status"], "confirmed_succeeded")
        self.assertEqual(self.oa.accepted_count(), 1)

    def test_evidence_writers_keep_source_authority(self):
        self.transfer()
        self.assertEqual(proof(self.runtime, "demo", "approval", "finance")["decision"],
                         "accepted")
        self.assertEqual(self.runtime.verify_pending("demo"), 1)

    def test_transfer_validates_target_and_rejects_same_owner(self):
        self.assertEqual(self.transfer(owner="finance")["code"], "AUTHORITY_DENIED")
        self.assertEqual(self.transfer(owner="nobody")["code"], "AUTHORITY_DENIED")
        self.assertEqual(self.transfer(owner="agent")["code"], "TRANSFER_SAME_OWNER")
        self.assertEqual(self.transfer(owner="requester")["code"], "AUTHORITY_DENIED")

    def test_transfer_during_cancellation_retains_intent(self):
        self.submit()
        version = self.runtime.get_work("demo")["state_version"]
        self.runtime.command("agent", "cancel-1", "demo", "request_cancel",
                             {"reason": "stop"}, version)
        self.assertEqual(self.transfer()["decision"], "accepted")
        work = self.runtime.get_work("demo")
        self.assertEqual(work["cancellation"]["reason"], "stop")
        self.assertEqual(work["owner"], "delegate")

    def test_transfer_payload_must_be_exact(self):
        for payload in ({"owner": "delegate"}, {"reason": "x"},
                        {"owner": "", "reason": "x"}, {"owner": "delegate", "reason": 5},
                        {"owner": "delegate", "reason": "x", "extra": 1}):
            with self.assertRaises(CommandError, msg=repr(payload)):
                self.runtime.command("agent", uuid.uuid4().hex, "demo", "transfer_owner",
                                     payload, self.runtime.get_work("demo")["state_version"])

    def test_legacy_ownerless_work_stays_grant_only_until_admin_adoption(self):
        strip_owner(self.path, "demo")
        reopened = Runtime(self.path, ExpensePolicy(), self.grants)
        # Legacy grant-only behavior: a manager who is not an owner can act.
        plan = {"steps": ["submit"], "open_requirements": [], "replan_when": []}
        self.assertEqual(send(reopened, "demo", "revise_plan", plan)["decision"], "accepted")
        # Non-admin intervention on an ownerless work is denied.
        version = reopened.get_work("demo")["state_version"]
        self.assertEqual(reopened.command("agent", uuid.uuid4().hex, "demo", "transfer_owner",
                                          {"owner": "delegate", "reason": "adopt"},
                                          version)["code"], "AUTHORITY_DENIED")
        # Admin adopts ownership explicitly.
        adopted = reopened.command("root", uuid.uuid4().hex, "demo", "transfer_owner",
                                   {"owner": "delegate", "reason": "adopt"}, version)
        self.assertEqual(adopted["decision"], "accepted")
        details = json.loads([e for e in reopened.events("demo")
                              if e["type"] == "OwnerTransferred"][-1]["body"])
        self.assertIsNone(details["from"])
        # After adoption the work is owner-gated; plain managers lose access.
        self.assertEqual(send(reopened, "demo", "revise_plan", plan,
                              actor="agent")["code"], "AUTHORITY_DENIED")
        self.assertEqual(send(reopened, "demo", "revise_plan", plan,
                              actor="delegate")["decision"], "accepted")

    def test_admin_can_transfer_without_being_owner(self):
        self.assertEqual(self.transfer(actor="root")["decision"], "accepted")
        self.assertEqual(self.runtime.get_work("demo")["owner"], "delegate")


class RelabeledApprovalSource(ExpensePolicy):
    evidence_sources = dict(ExpensePolicy.evidence_sources, approval="cfo")


class ReplayAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        self.oa_path = str(Path(self.temp.name) / "oa.sqlite")
        self.grants = intervention_grants()
        self.runtime = Runtime(self.path, ExpensePolicy(), self.grants)
        self.oa = FakeOA(self.oa_path)
        initialize(self.runtime)
        prerequisites(self.runtime)

    def test_create_work_replay_requires_work_manage(self):
        raw = document(document_id="REPLAY-1")
        first = self.runtime.command("agent", "create-1", "replay-work", "create_work",
                                     {"document": raw}, None)
        self.assertEqual(first["decision"], "accepted")
        self.grants["agent"].discard("work.manage")
        denial = self.runtime.command("agent", "create-1", "replay-work", "create_work",
                                      {"document": raw}, None)
        self.assertEqual((denial["decision"], denial["code"]),
                         ("rejected", "AUTHORITY_DENIED"))
        self.assertEqual(denial["observed_state_version"],
                         self.runtime.get_work("replay-work")["state_version"])
        self.assertEqual(self.runtime.get_command("agent", "create-1"), first)

    def test_record_evidence_replay_requires_current_source_and_write(self):
        payload = {"event_id": "ev-1", "kind": "approval",
                   "data": {"digest": self.runtime.get_work("demo")["document_digest"]}}
        first = self.runtime.command("finance", "ev-1", "demo", "record_evidence",
                                     payload, None)
        self.assertEqual(first["decision"], "accepted")
        self.grants["finance"].discard("evidence.write")
        denial = self.runtime.command("finance", "ev-1", "demo", "record_evidence",
                                      payload, None)
        self.assertEqual(denial["code"], "AUTHORITY_DENIED")
        self.assertEqual(self.runtime.get_command("finance", "ev-1"), first)
        self.grants["finance"].add("evidence.write")
        relabeled = Runtime(self.path, RelabeledApprovalSource(), self.grants)
        denial = relabeled.command("finance", "ev-1", "demo", "record_evidence",
                                   payload, None)
        self.assertEqual(denial["code"], "AUTHORITY_DENIED")

    def test_propose_replay_requires_current_owner(self):
        version = self.runtime.get_work("demo")["state_version"]
        payload = {"capability": "expense.submit",
                   "document_digest": self.runtime.get_work("demo")["document_digest"],
                   "contract_revision": 1, "plan_revision": 1}
        first = self.runtime.command("agent", "prop-1", "demo", "propose_action",
                                     payload, version)
        self.assertEqual(first["decision"], "accepted")
        self.assertEqual(self.transfer()["decision"], "accepted")
        denial = self.runtime.command("agent", "prop-1", "demo", "propose_action",
                                      payload, version)
        self.assertEqual((denial["decision"], denial["code"]),
                         ("rejected", "AUTHORITY_DENIED"))
        self.assertEqual(denial["observed_state_version"],
                         self.runtime.get_work("demo")["state_version"])
        self.assertEqual(self.runtime.get_command("agent", "prop-1"), first)

    def test_propose_replay_requires_capability(self):
        version = self.runtime.get_work("demo")["state_version"]
        payload = {"capability": "expense.submit",
                   "document_digest": self.runtime.get_work("demo")["document_digest"],
                   "contract_revision": 1, "plan_revision": 1}
        first = self.runtime.command("agent", "prop-2", "demo", "propose_action",
                                     payload, version)
        self.assertEqual(first["decision"], "accepted")
        self.grants["agent"].discard("expense.submit")
        denial = self.runtime.command("agent", "prop-2", "demo", "propose_action",
                                      payload, version)
        self.assertEqual(denial["code"], "AUTHORITY_DENIED")

    def test_management_replay_requires_work_manage(self):
        payload = {"steps": ["submit"], "open_requirements": [], "replan_when": []}
        version = self.runtime.get_work("demo")["state_version"]
        first = self.runtime.command("agent", "plan-1", "demo", "revise_plan",
                                     payload, version)
        self.assertEqual(first["decision"], "accepted")
        before = self.runtime.get_work("demo")
        events_before = len(self.runtime.events("demo"))
        self.grants["agent"].discard("work.manage")
        denial = self.runtime.command("agent", "plan-1", "demo", "revise_plan",
                                      payload, version)
        self.assertEqual(denial["code"], "AUTHORITY_DENIED")
        self.assertEqual(self.runtime.get_command("agent", "plan-1"), first)
        after = self.runtime.get_work("demo")
        self.assertEqual(after["state_version"], before["state_version"])
        self.assertEqual(len(self.runtime.events("demo")), events_before)

    def test_intervention_replay_after_transfer_denied(self):
        version = self.runtime.get_work("demo")["state_version"]
        first = self.runtime.command("agent", "cancel-x", "demo", "request_cancel",
                                     {"reason": "stop"}, version)
        self.assertEqual(first["decision"], "accepted")
        self.assertEqual(self.runtime.command("root", "adopt", "demo", "transfer_owner",
                                              {"owner": "delegate", "reason": "handover"},
                                              self.runtime.get_work("demo")["state_version"]
                                              )["decision"], "accepted")
        denial = self.runtime.command("agent", "cancel-x", "demo", "request_cancel",
                                      {"reason": "stop"}, version)
        self.assertEqual(denial["code"], "AUTHORITY_DENIED")
        self.assertEqual(self.runtime.get_command("agent", "cancel-x"), first)

    def test_replay_with_authority_returns_stored_receipt_after_close(self):
        op = action(self.runtime)["operation_id"]
        self.runtime.dispatch(op, self.oa)
        version = self.runtime.get_work("demo")["state_version"]
        final = self.runtime.command("agent", "done-1", "demo", "request_completion",
                                     None, version)
        self.assertEqual(final["decision"], "accepted")
        replay = self.runtime.command("agent", "done-1", "demo", "request_completion",
                                      None, version)
        self.assertEqual(replay, final)

    def test_replayed_fingerprint_mismatch_is_command_id_reused(self):
        payload = {"steps": ["submit"], "open_requirements": [], "replan_when": []}
        version = self.runtime.get_work("demo")["state_version"]
        first = self.runtime.command("agent", "plan-9", "demo", "revise_plan",
                                     payload, version)
        altered = {"steps": ["other"], "open_requirements": [], "replan_when": []}
        reused = self.runtime.command("agent", "plan-9", "demo", "revise_plan", altered,
                                      version)
        self.assertEqual(reused["code"], "COMMAND_ID_REUSED")
        self.assertEqual(self.runtime.get_command("agent", "plan-9"), first)

    def transfer(self, owner="delegate", reason="handover"):
        version = self.runtime.get_work("demo")["state_version"]
        return self.runtime.command("agent", uuid.uuid4().hex, "demo", "transfer_owner",
                                    {"owner": owner, "reason": reason}, version)


class Demo3RelabeledSource(ExpensePolicy):
    version = "demo-3"
    evidence_sources = dict(ExpensePolicy.evidence_sources, approval="cfo")


class Demo4ExplodingEvaluate(ExpensePolicyV2):
    version = "demo-4"

    def evaluate(self, work, evidence):
        raise RuntimeError("target evaluation exploded")


class Demo5ExplodingValidate(ExpensePolicyV2):
    version = "demo-5"

    def validate_evidence(self, work, candidate):
        raise RuntimeError("target verifier exploded")


class Demo6RejectingDocument(ExpensePolicyV2):
    version = "demo-6"

    def validate_document(self, document):
        raise ValueError("document rejected by target")


def evidence_bodies(path):
    db = sqlite3.connect(path)
    try:
        return [json.loads(row[0]) for row in db.execute("SELECT body FROM evidence")]
    finally:
        db.close()


def set_operation_field(path, operation_id, **fields):
    db = sqlite3.connect(path)
    try:
        op = json.loads(db.execute("SELECT body FROM operations WHERE id=?",
                                   (operation_id,)).fetchone()[0])
        op.update(fields)
        db.execute("UPDATE operations SET body=? WHERE id=?", (canonical(op), operation_id))
        db.commit()
    finally:
        db.close()


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        self.oa_path = str(Path(self.temp.name) / "oa.sqlite")
        self.grants = intervention_grants()
        self.v2 = ExpensePolicyV2()
        self.runtime = Runtime(self.path, ExpensePolicy(), self.grants,
                               policies={"demo-2": self.v2})
        self.oa = FakeOA(self.oa_path)
        initialize(self.runtime)

    def migrate(self, version="demo-2", actor="root", reason="strengthen",
                policy_id="expense-submit", work_id="demo", command_id=None):
        version_now = self.runtime.get_work(work_id)["state_version"]
        return self.runtime.command(actor, command_id or uuid.uuid4().hex, work_id,
                                    "migrate_policy", {"policy_id": policy_id,
                                                       "policy_version": version,
                                                       "reason": reason}, version_now)

    def requirement(self, rule, work_id="demo"):
        return next(r for r in self.runtime.get_work(work_id)["requirements"]
                    if r["rule_id"] == rule)

    def test_migration_requires_intervene_admin(self):
        self.assertEqual(self.migrate(actor="agent")["code"], "AUTHORITY_DENIED")
        self.assertEqual(self.migrate(actor="delegate")["code"], "AUTHORITY_DENIED")
        self.assertEqual(self.migrate()["decision"], "accepted")

    def test_migration_requires_bound_contract(self):
        send(self.runtime, "raw", "create_work", {"document": document(document_id="RAW-1")})
        self.assertEqual(self.migrate(work_id="raw")["code"], "CONTRACT_NOT_ACTIVE")

    def test_migration_refuses_cancellation_intent(self):
        version = self.runtime.get_work("demo")["state_version"]
        self.runtime.command("agent", "c", "demo", "request_cancel", {"reason": "stop"}, version)
        self.assertEqual(self.migrate()["code"], "CANCELLATION_ACTIVE")

    def test_migration_rejects_cross_family_before_lookup(self):
        self.assertEqual(self.migrate(policy_id="content-publish")["code"],
                         "MIGRATION_FAMILY_MISMATCH")

    def test_migration_rejects_unregistered_and_unchanged_targets(self):
        self.assertEqual(self.migrate(version="demo-9")["code"],
                         "MIGRATION_TARGET_UNREGISTERED")
        self.assertEqual(self.migrate(version="demo-1")["code"],
                         "MIGRATION_TARGET_UNCHANGED")
        self.assertEqual(self.migrate()["decision"], "accepted")

    def test_migration_refuses_uncertain_effects(self):
        prerequisites(self.runtime)
        op = action(self.runtime)["operation_id"]
        self.runtime.dispatch(op, FakeOA(self.oa_path, timeout_after_commit=True))
        before = self.runtime.get_work("demo")
        receipt = self.migrate()
        self.assertEqual(receipt["code"], "OUTCOME_UNRESOLVED")
        self.assertEqual(receipt["blockers"], [op])
        after = self.runtime.get_work("demo")
        self.assertEqual(after["contract"], before["contract"])
        self.assertEqual(after["state_version"], before["state_version"])

    def test_strengthened_rule_revalidates_approval_and_keeps_key(self):
        prerequisites(self.runtime)
        op = action(self.runtime)["operation_id"]
        self.assertEqual(self.migrate()["decision"], "accepted")
        work = self.runtime.get_work("demo")
        self.assertEqual(work["contract"]["policy_version"], "demo-2")
        self.assertEqual(work["contract"]["revision"], 2)
        self.assertEqual((self.requirement("E05")["applicability"],
                          self.requirement("E05")["fulfillment"]), ("applicable", "pending"))
        approval = next(e for e in evidence_bodies(self.path) if e["kind"] == "approval")
        self.assertEqual(approval["status"], "invalid")
        invalidated = self.runtime.get_operation(op)
        self.assertEqual((invalidated["dispatch_state"], invalidated["reason"]),
                         ("cancelled", "POLICY_MIGRATED"))
        stale = action(self.runtime)
        self.assertEqual(stale["code"], "REQUIREMENT_UNSATISFIED")
        work = self.runtime.get_work("demo")
        forced = send(self.runtime, "demo", "propose_action", {
            "capability": "expense.submit", "document_digest": work["document_digest"],
            "contract_revision": 1, "plan_revision": work["plan_revision"]})
        self.assertEqual(forced["code"], "CONTRACT_REVISION_MISMATCH")
        proof(self.runtime, "demo", "approval", "finance", {
            "digest": work["document_digest"], "policy_version": "demo-2"})
        self.runtime.verify_pending("demo")
        self.assertEqual(self.requirement("E05")["fulfillment"], "satisfied")
        readmitted = action(self.runtime)
        self.assertEqual(readmitted["decision"], "accepted")
        self.assertEqual(readmitted["operation_id"], op)
        operation = self.runtime.get_operation(op)
        self.assertEqual(operation["contract_revision"], 2)
        self.assertEqual(operation["dispatch_state"], "ready")
        self.assertEqual(self.runtime.dispatch(op, self.oa)["status"], "confirmed_succeeded")
        self.assertEqual(self.oa.accepted_count(), 1)

    def test_accepted_evidence_survives_migration(self):
        prerequisites(self.runtime)
        op = action(self.runtime)["operation_id"]
        self.runtime.dispatch(op, self.oa)
        external_id = self.runtime.get_operation(op)["external_id"]
        self.assertEqual(self.migrate()["decision"], "accepted")
        self.assertEqual(self.requirement("E08")["fulfillment"], "satisfied")
        operation = self.runtime.get_operation(op)
        self.assertEqual((operation["status"], operation["external_id"]),
                         ("confirmed_succeeded", external_id))
        accepted = next(e for e in evidence_bodies(self.path) if e["kind"] == "accepted")
        self.assertEqual(accepted["status"], "verified")
        self.assertEqual(self.oa.accepted_count(), 1)

    def test_two_works_pinned_to_different_versions(self):
        initialize(self.runtime, "other", document(document_id="EXP-002"))
        send(self.runtime, "other", "revise_document", {"document": document(
            amount=80000, document_id="EXP-002")})
        prerequisites(self.runtime, "other", approval=False)
        self.assertEqual(self.migrate()["decision"], "accepted")
        self.assertEqual(self.requirement("E05")["applicability"], "applicable")
        self.assertEqual(self.requirement("E05", "other")["applicability"], "not_applicable")
        restarted = Runtime(self.path, ExpensePolicy(), self.grants,
                            policies={"demo-2": self.v2})
        self.assertEqual(restarted.get_work("demo")["contract"]["policy_version"], "demo-2")
        self.assertEqual(restarted.get_work("other")["contract"]["policy_version"], "demo-1")

    def test_restart_without_pinned_version_fails_closed(self):
        self.assertEqual(self.migrate()["decision"], "accepted")
        smaller = Runtime(self.path, ExpensePolicy(), self.grants)
        with self.assertRaises(CommandError):
            smaller.get_work("demo")

    def test_old_command_receipts_retained_after_migration(self):
        prerequisites(self.runtime)
        accepted = action(self.runtime, command_id="propose-before")
        self.assertEqual(accepted["decision"], "accepted")
        self.assertEqual(self.migrate()["decision"], "accepted")
        self.assertEqual(self.runtime.get_command("agent", "propose-before"), accepted)

    def test_migration_rolls_back_atomically_on_target_failure(self):
        prerequisites(self.runtime)
        action(self.runtime)
        before_work = self.runtime.get_work("demo")
        before_evidence = sorted((e["kind"], e["status"])
                                 for e in evidence_bodies(self.path))
        for version, policy in (("demo-4", Demo4ExplodingEvaluate()),
                                ("demo-5", Demo5ExplodingValidate())):
            runtime = Runtime(self.path, ExpensePolicy(), self.grants,
                              policies={"demo-2": self.v2, version: policy})
            with self.assertRaises(RuntimeError):
                version_now = runtime.get_work("demo")["state_version"]
                runtime.command("root", uuid.uuid4().hex, "demo", "migrate_policy", {
                    "policy_id": "expense-submit", "policy_version": version,
                    "reason": "explode"}, version_now)
            after = runtime.get_work("demo")
            self.assertEqual(after["contract"], before_work["contract"])
            self.assertEqual(after["state_version"], before_work["state_version"])
            self.assertEqual(after["requirements"], before_work["requirements"])
            self.assertEqual(sorted((e["kind"], e["status"])
                                    for e in evidence_bodies(self.path)), before_evidence)
            self.assertEqual([e for e in runtime.events("demo")
                              if e["type"] == "PolicyMigrated"], [])

    def test_target_rejecting_document_raises_and_persists_nothing(self):
        before = self.runtime.get_work("demo")
        runtime = Runtime(self.path, ExpensePolicy(), self.grants,
                          policies={"demo-6": Demo6RejectingDocument()})
        version_now = runtime.get_work("demo")["state_version"]
        with self.assertRaises(CommandError):
            runtime.command("root", uuid.uuid4().hex, "demo", "migrate_policy", {
                "policy_id": "expense-submit", "policy_version": "demo-6",
                "reason": "nope"}, version_now)
        after = runtime.get_work("demo")
        self.assertEqual(after["contract"], before["contract"])
        self.assertEqual(after["state_version"], before["state_version"])

    def test_migration_preserves_plan_and_document_history(self):
        prerequisites(self.runtime)
        before = self.runtime.get_work("demo")
        self.assertEqual(self.migrate()["decision"], "accepted")
        after = self.runtime.get_work("demo")
        self.assertEqual(after["plan_revision"], before["plan_revision"])
        self.assertEqual(after["document_revision"], before["document_revision"])
        self.assertEqual(after["document_digest"], before["document_digest"])
        self.assertEqual(after["plan"], before["plan"])
        for wait in after["waits"]:
            self.assertEqual(wait["status"], "cancelled")

    def test_migration_payload_must_be_exact(self):
        for payload in ({"policy_id": "expense-submit", "policy_version": "demo-2"},
                        {"policy_version": "demo-2", "reason": "x"},
                        {"policy_id": "", "policy_version": "demo-2", "reason": "x"},
                        {"policy_id": "expense-submit", "policy_version": "demo-2",
                         "reason": "x", "extra": 1}):
            with self.assertRaises(CommandError, msg=repr(payload)):
                self.runtime.command("root", uuid.uuid4().hex, "demo", "migrate_policy",
                                     payload, self.runtime.get_work("demo")["state_version"])

    def test_migration_replayed_by_restored_authority_returns_stored_receipt(self):
        rejected = self.migrate(actor="agent", version="demo-9",
                                command_id="wished-migration")
        self.assertEqual(rejected["code"], "AUTHORITY_DENIED")
        self.grants["agent"].add("work.intervene")
        replay = self.runtime.command("agent", "wished-migration", "demo", "migrate_policy", {
            "policy_id": "expense-submit", "policy_version": "demo-9",
            "reason": "strengthen"}, rejected["observed_state_version"])
        self.assertEqual(replay, rejected)
        self.grants["agent"].discard("work.intervene")

    def test_dispatch_respects_actual_contract_revision(self):
        prerequisites(self.runtime)
        self.assertEqual(self.migrate()["decision"], "accepted")
        proof(self.runtime, "demo", "approval", "finance", {
            "digest": self.runtime.get_work("demo")["document_digest"],
            "policy_version": "demo-2"})
        self.runtime.verify_pending("demo")
        op = action(self.runtime)["operation_id"]
        set_operation_field(self.path, op, contract_revision=1)
        result = self.runtime.dispatch(op, self.oa)
        self.assertEqual(result["dispatch_state"], "cancelled")
        self.assertEqual(result["reason"], "STALE_INTENT")
        self.assertEqual(self.oa.accepted_count(), 0)


class PendingSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        self.grants = intervention_grants()
        self.runtime = Runtime(self.path, ExpensePolicy(), self.grants,
                               policies={"demo-3": Demo3RelabeledSource()})
        initialize(self.runtime)

    def requirement(self, rule):
        return next(r for r in self.runtime.get_work("demo")["requirements"]
                    if r["rule_id"] == rule)

    def migrate_to_demo_3(self):
        version = self.runtime.get_work("demo")["state_version"]
        receipt = self.runtime.command("root", uuid.uuid4().hex, "demo", "migrate_policy", {
            "policy_id": "expense-submit", "policy_version": "demo-3",
            "reason": "relabel"}, version)
        self.assertEqual(receipt["decision"], "accepted")

    def test_pending_old_source_proof_cannot_reappear_after_migration(self):
        proof(self.runtime, "demo", "approval", "finance")   # left pending
        self.migrate_to_demo_3()
        approval = next(e for e in evidence_bodies(self.path) if e["kind"] == "approval")
        self.assertEqual(approval["status"], "pending_verification")
        self.runtime.verify_pending("demo")
        approval = next(e for e in evidence_bodies(self.path) if e["kind"] == "approval")
        self.assertEqual(approval["status"], "invalid")
        self.assertEqual(self.requirement("E05")["fulfillment"], "pending")

    def test_invalid_evidence_never_resurrects(self):
        proof(self.runtime, "demo", "approval", "finance", {"approved": True})
        self.runtime.verify_pending("demo")
        self.assertEqual(self.requirement("E05")["fulfillment"], "pending")
        self.migrate_to_demo_3()
        self.runtime.verify_pending("demo")
        approval = next(e for e in evidence_bodies(self.path) if e["kind"] == "approval")
        self.assertEqual(approval["status"], "invalid")
        self.assertEqual(self.requirement("E05")["fulfillment"], "pending")


class CancelledWaitTests(unittest.TestCase):
    """Cancelled waits are terminally invalidated: evaluation never resurrects them."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        self.grants = intervention_grants()
        self.runtime = Runtime(self.path, ExpensePolicy(), self.grants)
        initialize(self.runtime)

    def register_wait(self, requirement_id="E05:EXP-001"):
        send(self.runtime, "demo", "register_wait", {
            "requirement_id": requirement_id, "deadline": 2000000000, "owner": "finance"})

    def wait_status(self):
        return self.runtime.get_work("demo")["waits"][0]["status"]

    def cancel(self):
        version = self.runtime.get_work("demo")["state_version"]
        receipt = self.runtime.command("agent", "cancel-1", "demo", "request_cancel",
                                       {"reason": "stop"}, version)
        self.assertEqual(receipt["decision"], "accepted")

    def test_cancelled_triggered_wait_stays_cancelled(self):
        prerequisites(self.runtime)
        self.register_wait()
        self.assertEqual(self.wait_status(), "triggered")
        self.cancel()
        self.assertEqual(self.wait_status(), "cancelled")

    def test_cancelled_wait_stays_cancelled_after_late_evidence(self):
        prerequisites(self.runtime, approval=False)
        self.register_wait()
        self.assertEqual(self.wait_status(), "waiting")
        self.cancel()
        self.assertEqual(self.wait_status(), "cancelled")
        proof(self.runtime, "demo", "approval", "finance")
        self.runtime.verify_pending("demo")
        work = self.runtime.get_work("demo")
        requirement = next(r for r in work["requirements"] if r["rule_id"] == "E05")
        self.assertEqual(requirement["fulfillment"], "satisfied")
        self.assertEqual(self.wait_status(), "cancelled")

    def test_migration_cancelled_wait_stays_cancelled_when_requirement_satisfied(self):
        prerequisites(self.runtime)   # E06 confirmation stays verified under demo-2
        self.register_wait(requirement_id="E06:EXP-001")
        self.assertEqual(self.wait_status(), "triggered")
        runtime = Runtime(self.path, ExpensePolicy(), self.grants,
                          policies={"demo-2": ExpensePolicyV2()})
        version = runtime.get_work("demo")["state_version"]
        receipt = runtime.command("root", "migrate-1", "demo", "migrate_policy", {
            "policy_id": "expense-submit", "policy_version": "demo-2",
            "reason": "strengthen"}, version)
        self.assertEqual(receipt["decision"], "accepted")
        work = runtime.get_work("demo")
        requirement = next(r for r in work["requirements"] if r["rule_id"] == "E06")
        self.assertEqual(requirement["fulfillment"], "satisfied")
        self.assertEqual(work["waits"][0]["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
