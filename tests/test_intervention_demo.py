"""S3 wave 3: intervention demo harness, CLI policy-version flag, printed commands."""

import contextlib
import importlib.util
import io
import json
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from work_runtime import CommandError, ExpensePolicy, Runtime, cli
from work_runtime.demo import demo_grants, document, initialize, prerequisites, send
from work_runtime.policy import ExpensePolicyV2
from work_runtime.publishing import PublishingPolicy
from work_runtime.publishing_demo import article, publishing_grants

REPO_ROOT = Path(__file__).resolve().parents[1]


def intervention_grants():
    grants = demo_grants()
    grants["root"] = {"work.intervene"}
    grants["delegate"] = {"work.manage", "expense.submit"}
    return grants


def registry_runtime(path):
    """Default v1 object plus the explicit v1/v2 registry (identity for demo-1)."""
    v1 = ExpensePolicy()
    return Runtime(path, v1, intervention_grants(),
                   policies={"demo-1": v1, "demo-2": ExpensePolicyV2()})


def migrated_store(directory, work_id="demo"):
    """A real store holding one work explicitly migrated to demo-2."""
    runtime = registry_runtime(str(Path(directory) / "runtime.sqlite"))
    initialize(runtime, work_id)
    prerequisites(runtime, work_id)
    version = runtime.get_work(work_id)["state_version"]
    receipt = runtime.command("root", "migrate-1", work_id, "migrate_policy",
                              {"policy_id": "expense-submit", "policy_version": "demo-2",
                               "reason": "strengthen"}, version)
    assert receipt["decision"] == "accepted"
    return runtime.path


def run_cli(argv):
    """Invoke the CLI in process; return (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            cli.main(argv)
    except SystemExit as raised:
        code = raised.code
    return code, out.getvalue(), err.getvalue()


class InspectPolicyVersionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.migrated = migrated_store(self.temp.name)

    def inspect(self, extra):
        return run_cli(["inspect", "--db", self.migrated, "--work", "demo"] + extra)

    def test_policy_versions_loads_registry_and_reads_migrated_work(self):
        code, out, _ = self.inspect(["--policy-versions", "demo-1,demo-2"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["work"]["contract"]["policy_version"], "demo-2")

    def test_policy_versions_single_version_registries_are_valid(self):
        # demo-2 alone is an additive registry that omits the default key (D16).
        for spec in ("demo-2", "demo-1,demo-2"):
            code, out, _ = self.inspect(["--policy-versions", spec])
            self.assertEqual(code, 0, spec)
            self.assertEqual(json.loads(out)["work"]["contract"]["policy_version"], "demo-2")
        plain = str(Path(self.temp.name) / "plain" / "runtime.sqlite")
        runtime = Runtime(plain, ExpensePolicy(), demo_grants())
        initialize(runtime)
        code, out, _ = run_cli(["inspect", "--db", plain, "--work", "demo",
                                "--policy-versions", "demo-1"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["work"]["contract"]["policy_version"], "demo-1")

    def test_policy_versions_rejects_empty_tokens(self):
        for spec in ("", "demo-1,", ",demo-1"):
            code, _, err = self.inspect(["--policy-versions", spec])
            self.assertEqual(code, 2, spec)
            self.assertIn("empty policy version", err)

    def test_policy_versions_rejects_duplicates(self):
        for spec in ("demo-1,demo-1", "demo-2,demo-1,demo-2"):
            code, _, err = self.inspect(["--policy-versions", spec])
            self.assertEqual(code, 2, spec)
            self.assertIn("duplicate policy version", err)

    def test_policy_versions_rejects_unknown_versions(self):
        for spec, token in (("demo-9", "demo-9"), ("demo-1, demo-2", " demo-2"),
                            ("content-v1", "content-v1")):
            code, _, err = self.inspect(["--policy-versions", spec])
            self.assertEqual(code, 2, spec)
            self.assertIn("unknown policy version", err)
            self.assertIn(token, err)

    def test_policy_versions_rejects_cross_family_policy(self):
        code, _, err = run_cli(["inspect", "--db", self.migrated, "--work", "demo",
                                "--policy", "content-publish",
                                "--policy-versions", "demo-1"])
        self.assertEqual(code, 2)
        self.assertIn("expense", err)

    def test_inspect_without_versions_fails_closed_on_pinned_store(self):
        # Default inspect loads no registry: a demo-2-pinned work must fail closed.
        with self.assertRaises(CommandError):
            cli.main(["inspect", "--db", self.migrated, "--work", "demo"])

    def test_inspect_default_expense_and_content_publish_unchanged(self):
        plain = str(Path(self.temp.name) / "plain" / "runtime.sqlite")
        initialize(Runtime(plain, ExpensePolicy(), demo_grants()))
        code, out, _ = run_cli(["inspect", "--db", plain, "--work", "demo"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["work"]["contract"]["policy_version"], "demo-1")
        publish_path = str(Path(self.temp.name) / "publish" / "runtime.sqlite")
        publisher = Runtime(publish_path, PublishingPolicy(), publishing_grants())
        policy = publisher.policy
        publisher.command("agent", "p-create", "article-1", "create_work",
                          {"document": article()})
        publisher.command("agent", "p-bind", "article-1", "bind_contract",
                          {"policy_id": policy.id, "policy_version": policy.version,
                           "goal": policy.goal},
                          publisher.get_work("article-1")["state_version"])
        code, out, _ = run_cli(["inspect", "--db", publish_path, "--work", "article-1",
                                "--policy", "content-publish"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["work"]["id"], "article-1")


if __name__ == "__main__":
    unittest.main()


def accepted_in_store(oa_path):
    """Count accepted applications by querying the external store directly."""
    import sqlite3
    db = sqlite3.connect(str(oa_path))
    try:
        rows = [json.loads(row[0]) for row in db.execute("SELECT result FROM receipts")]
    finally:
        db.close()
    return sum(1 for row in rows if row.get("status") == "accepted")


def operation_bodies(runtime_db):
    """Read operation rows straight from the runtime database."""
    import sqlite3
    db = sqlite3.connect(str(runtime_db))
    try:
        return [json.loads(row[0]) for row in db.execute("SELECT body FROM operations")]
    finally:
        db.close()


class InterventionDemoTests(unittest.TestCase):
    def setUp(self):
        from work_runtime import intervention_demo
        self.intervention_demo = intervention_demo
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def run_demo(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            folder = self.intervention_demo.run_intervention_demo(self.temp.name)
        return folder, out.getvalue()

    def test_demo_creates_separate_fresh_stores_per_scenario(self):
        folder, _ = self.run_demo()
        paths = [folder / scenario / name
                 for scenario in ("transfer", "cancel", "migrate")
                 for name in ("runtime.sqlite", "oa.sqlite")]
        for path in paths:
            self.assertTrue(path.exists(), path)
        self.assertEqual(len({str(path) for path in paths}), 6)

    def test_each_store_independently_holds_exactly_one_accepted_application(self):
        folder, _ = self.run_demo()
        for scenario in ("transfer", "cancel", "migrate"):
            # The same invoice id (INV-001) is submitted in all three scenarios;
            # exactly one accepted application per store is possible only
            # because every scenario owns a separate external database.
            self.assertEqual(accepted_in_store(folder / scenario / "oa.sqlite"), 1, scenario)

    def test_transfer_state_old_owner_denied_operation_preserved(self):
        folder, _ = self.run_demo()
        runtime = Runtime(str(folder / "transfer" / "runtime.sqlite"), ExpensePolicy(),
                          self.intervention_demo.intervention_grants())
        self.assertEqual(runtime.get_work("transfer")["owner"], "delegate")
        operations = operation_bodies(folder / "transfer" / "runtime.sqlite")
        self.assertEqual([op["status"] for op in operations], ["confirmed_succeeded"])
        # The denied replay left the stored accepted receipt untouched.
        stored = runtime.get_command("agent", "transfer-submit-once")
        self.assertEqual(stored["decision"], "accepted")
        event_types = [event["type"] for event in runtime.events("transfer")]
        for event_type in ("OwnerTransferred", "OperationReadmitted"):
            self.assertIn(event_type, event_types)

    def test_cancel_state_closed_cancelled_with_retained_effect(self):
        folder, _ = self.run_demo()
        runtime = Runtime(str(folder / "cancel" / "runtime.sqlite"), ExpensePolicy(),
                          self.intervention_demo.intervention_grants())
        work = runtime.get_work("cancel")
        self.assertEqual((work["status"], work["outcome"]), ("closed", "cancelled"))
        acknowledged = work["completion"]["acknowledged_operations"]
        self.assertEqual(len(acknowledged), 1)
        self.assertTrue(acknowledged[0]["external_id"])
        disposition = next(d for d in work["completion"]["operation_dispositions"]
                           if d["operation_id"] == acknowledged[0]["operation_id"])
        self.assertEqual(disposition["status"], "confirmed_succeeded")
        self.assertEqual(len(runtime.get_operation(
            acknowledged[0]["operation_id"])["attempts"]), 1)
        self.assertEqual(accepted_in_store(folder / "cancel" / "oa.sqlite"), 1)

    def test_migration_state_pinned_demo2_same_operation(self):
        folder, _ = self.run_demo()
        runtime = self.intervention_demo.registry_runtime(
            str(folder / "migrate" / "runtime.sqlite"))
        work = runtime.get_work("migrate")
        self.assertEqual((work["contract"]["policy_version"], work["contract"]["revision"]),
                         ("demo-2", 2))
        operations = operation_bodies(folder / "migrate" / "runtime.sqlite")
        self.assertEqual([op["status"] for op in operations], ["confirmed_succeeded"])
        self.assertEqual(operations[0]["contract_revision"], 2)
        self.assertEqual(len(operations[0]["attempts"]), 1)
        self.assertIn("PolicyMigrated",
                      [event["type"] for event in runtime.events("migrate")])
        bare = Runtime(str(folder / "migrate" / "runtime.sqlite"), ExpensePolicy(),
                       self.intervention_demo.intervention_grants())
        with self.assertRaises(CommandError):
            bare.get_work("migrate")

    def test_demo_output_pins_key_markers(self):
        _, out = self.run_demo()
        for marker in ("OWNERSHIP_TRANSFERRED", "OUTCOME_UNRESOLVED",
                       "CANCEL_ACKNOWLEDGEMENT_MISMATCH", "POLICY_MIGRATED",
                       "accepted applications: 3 (one per store)"):
            self.assertIn(marker, out)
        inspect_lines = [line.strip() for line in out.splitlines() if "inspect --db" in line]
        self.assertEqual(len(inspect_lines), 3)
        self.assertTrue(inspect_lines[2].endswith("--policy-versions demo-1,demo-2"),
                        inspect_lines[2])

    def test_demo_runs_are_repeatable(self):
        folder_a, out_a = self.run_demo()
        folder_b, out_b = self.run_demo()
        self.assertIn("accepted applications: 3 (one per store)", out_a)
        self.assertIn("accepted applications: 3 (one per store)", out_b)
        for folder in (folder_a, folder_b):
            for scenario in ("transfer", "cancel", "migrate"):
                self.assertEqual(accepted_in_store(folder / scenario / "oa.sqlite"), 1)


class InterventionDemoCliTests(unittest.TestCase):
    def setUp(self):
        from work_runtime import intervention_demo
        self.intervention_demo = intervention_demo
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_cli_intervention_demo_module_runs(self):
        result = subprocess.run([sys.executable, "-m", "work_runtime", "intervention-demo"],
                                cwd=str(REPO_ROOT), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("accepted applications: 3 (one per store)", result.stdout)

    def test_printed_inspect_commands_run_correctly(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.intervention_demo.run_intervention_demo(self.temp.name)
        commands = [line.strip() for line in out.getvalue().splitlines()
                    if line.strip().startswith("python3 -m work_runtime inspect")]
        self.assertEqual(len(commands), 3)
        results = []
        for command in commands:
            words = shlex.split(command)
            self.assertEqual(words[:4], ["python3", "-m", "work_runtime", "inspect"])
            results.append(subprocess.run([sys.executable] + words[1:], cwd=str(REPO_ROOT),
                                          capture_output=True, text=True))
            self.assertEqual(results[-1].returncode, 0, command + "\n" + results[-1].stderr)
        # The printed migrated command carries the registry flag and reads the demo-2 pin.
        self.assertTrue(commands[2].endswith("--policy-versions demo-1,demo-2"))
        self.assertIn('"policy_version": "demo-2"', results[2].stdout)


def _load_verify_install():
    spec = importlib.util.spec_from_file_location(
        "verify_install", REPO_ROOT / "scripts" / "verify_install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_oa(path, accepted):
    db = sqlite3.connect(str(path))
    try:
        db.executescript("CREATE TABLE IF NOT EXISTS receipts ("
                         "key TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL)")
        for index in range(accepted):
            db.execute("INSERT INTO receipts VALUES (?,?,?)",
                       ("key-%d" % index, "digest", json.dumps(
                           {"status": "accepted", "external_id": "OA-%d" % index})))
        db.commit()
    finally:
        db.close()


class VerifyInstallInterventionCountsTests(unittest.TestCase):
    """The shared helper gives module and console intervention runs equal proof."""

    def setUp(self):
        self.verify_install = _load_verify_install()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def store(self, scenario, accepted=1):
        scenario_dir = self.folder / scenario
        scenario_dir.mkdir(parents=True, exist_ok=True)
        _seed_oa(scenario_dir / "oa.sqlite", accepted)
        return str(scenario_dir / "runtime.sqlite")

    def printed(self, *stores):
        return "".join('  python3 -m work_runtime inspect --db "%s" --work x\n' % store
                       for store in stores)

    def test_three_distinct_stores_with_one_accepted_each_pass(self):
        stdout = self.printed(self.store("transfer"), self.store("cancel"),
                              self.store("migrate"))
        stores = self.verify_install.require_intervention_store_counts(stdout, "test")
        self.assertEqual([Path(store).parent.name for store in stores],
                         ["transfer", "cancel", "migrate"])

    def test_repeated_single_store_is_rejected_even_when_its_count_is_one(self):
        store = self.store("transfer")
        with self.assertRaises(SystemExit) as raised:
            self.verify_install.require_intervention_store_counts(
                self.printed(store, store, store), "test")
        self.assertIn("duplicate", str(raised.exception))

    def test_wrong_scenario_order_is_rejected(self):
        stdout = self.printed(self.store("transfer"), self.store("migrate"),
                              self.store("cancel"))
        with self.assertRaises(SystemExit) as raised:
            self.verify_install.require_intervention_store_counts(stdout, "test")
        self.assertIn("transfer, cancel, migrate", str(raised.exception))

    def test_missing_scenario_line_is_rejected(self):
        stdout = self.printed(self.store("transfer"), self.store("cancel"))
        with self.assertRaises(SystemExit) as raised:
            self.verify_install.require_intervention_store_counts(stdout, "test")
        self.assertIn("expected exactly 3", str(raised.exception))

    def test_incorrect_actual_accepted_count_is_rejected(self):
        stdout = self.printed(self.store("transfer"), self.store("cancel"),
                              self.store("migrate", accepted=2))
        with self.assertRaises(SystemExit) as raised:
            self.verify_install.require_intervention_store_counts(stdout, "test")
        self.assertIn("expected exactly 1", str(raised.exception))

    def test_missing_external_store_is_rejected(self):
        ghost = str(self.folder / "migrate" / "runtime.sqlite")
        stdout = self.printed(self.store("transfer"), self.store("cancel"), ghost)
        with self.assertRaises(SystemExit) as raised:
            self.verify_install.require_intervention_store_counts(stdout, "test")
        self.assertIn("oa.sqlite", str(raised.exception))
