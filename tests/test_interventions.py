"""S3 intervention lifecycle: registry, cancellation, ownership, migration."""

import json
import sqlite3
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
