"""S3 wave 3: intervention demo harness, CLI policy-version flag, printed commands."""

import contextlib
import io
import json
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
