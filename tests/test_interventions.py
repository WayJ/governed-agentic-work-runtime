"""S3 intervention lifecycle: registry, cancellation, ownership, migration."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from work_runtime import CommandError, ExpensePolicy, Runtime
from work_runtime.adapters import FakeOA
from work_runtime.demo import action, demo_grants, document, initialize, prerequisites, proof, send
from work_runtime.policy import canonical
from work_runtime.publishing import PublishingPolicy


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


if __name__ == "__main__":
    unittest.main()
