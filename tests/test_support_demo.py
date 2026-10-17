"""S15 W2 demo wave: support-ticket family demo — forward + crash-recovery chapters.

The demo builds every state through public Runtime commands, the real
FakeIssueTracker store and a grants-carrying child subprocess that dies after
the tracker accepted the write; these tests read the SQLite stores directly
to assert what the public path actually produced, never trusting the printed
text for state.
"""

import contextlib
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from work_runtime.policy import digest
from work_runtime.support_demo import FINAL_LINE, run_demo


class SupportDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def run_capture(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            folder = run_demo(directory=self.temp.name)
        return Path(folder), buffer.getvalue()

    def test_demo_story_and_independent_store_counts(self):
        folder, output = self.run_capture()
        for expected in ("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.",
                         "APPLICABILITY_UNRESOLVED", "REQUIREMENT_UNSATISFIED",
                         "exit code 73", "issues: 2", "receipts: 2",
                         FINAL_LINE, "--policy support-ticket"):
            self.assertIn(expected, output, expected)
        self.assertNotRegex(output, "[0-9a-f]{64}")
        runtime_path, tracker_path = folder / "runtime.sqlite", folder / "tracker.sqlite"
        self.assertTrue(runtime_path.exists())
        self.assertTrue(tracker_path.exists())
        with sqlite3.connect(str(tracker_path)) as db:
            issues = db.execute("SELECT ticket_reference, issue_number, digest "
                                "FROM issues ORDER BY issue_number").fetchall()
            self.assertEqual([(row[0], row[1]) for row in issues],
                             [("TCK-1001", 1), ("TCK-1002", 2)])
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0], 2)
        with sqlite3.connect(str(runtime_path)) as db:
            for work_id in ("ticket-1", "ticket-2"):
                state = json.loads(db.execute(
                    "SELECT state FROM works WHERE id=?", (work_id,)).fetchone()[0])
                self.assertEqual((state["status"], state["outcome"]),
                                 ("closed", "succeeded"), work_id)
            operations = [json.loads(row[0]) for row in
                          db.execute("SELECT body FROM operations")]
            self.assertEqual(len(operations), 2)
            for operation in operations:
                reference = operation["document"]["id"]
                self.assertEqual(operation["business_key"],
                                 digest(["support-ticket", "ticket.dispatch",
                                         reference]))
                self.assertEqual(operation["status"], "confirmed_succeeded")
                self.assertEqual(len(operation["attempts"]), 1)
                row = db.execute("SELECT body FROM evidence WHERE source='tracker' "
                                 "AND event_id=?", (operation["id"],)).fetchone()
                proof = json.loads(row[0])
                self.assertEqual((proof["kind"], proof["status"]),
                                 ("accepted", "verified"))
                self.assertEqual(proof["data"]["external_id"],
                                 operation["external_id"])

    def test_demo_runs_repeatably_in_fresh_directories(self):
        first, first_output = self.run_capture()
        second, second_output = self.run_capture()
        self.assertIn(FINAL_LINE, first_output)
        self.assertIn(FINAL_LINE, second_output)
        self.assertNotEqual(first, second)
        for folder in (first, second):
            with sqlite3.connect(str(folder / "tracker.sqlite")) as db:
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM issues").fetchone()[0], 2)
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0], 2)

    def test_demo_leaves_parent_directory_contents_untouched(self):
        parent = Path(self.temp.name) / "parent"
        parent.mkdir()
        (parent / "keep.txt").write_text("user data")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            run_demo(directory=str(parent))
        self.assertEqual((parent / "keep.txt").read_text(), "user data")
        folders = [path for path in parent.iterdir() if path.is_dir()]
        self.assertEqual(len(folders), 1)


if __name__ == "__main__":
    unittest.main()


class SupportCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "work_runtime", *args],
                              capture_output=True, text=True)

    def test_support_demo_command_runs_the_harness(self):
        result = self.run_cli("support-demo", "--directory", self.temp.name)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(FINAL_LINE, result.stdout)

    def test_inspect_support_ticket_policy_reads_ticket_work(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            folder = run_demo(directory=self.temp.name)
        result = self.run_cli("inspect", "--db", str(Path(folder) / "runtime.sqlite"),
                              "--work", "ticket-1", "--policy", "support-ticket")
        self.assertEqual(result.returncode, 0, result.stderr)
        snapshot = json.loads(result.stdout)
        self.assertEqual(snapshot["work"]["contract"]["goal"], "ticket.dispatched")
        self.assertEqual(snapshot["work"]["status"], "closed")

    def test_inspect_rejects_unknown_policy_choice_unchanged(self):
        result = self.run_cli("inspect", "--db", "unused.sqlite", "--policy", "bogus")
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)


class SupportInstallerProofTests(unittest.TestCase):
    """The verify_install support-demo stage's proof logic, exercised in-repo.

    The full script needs a fresh venv and pip index access; these tests pin
    the proof itself: the real demo output passes it, and doctored output
    (missing final line, wrong store counts) must fail.
    """

    def setUp(self):
        import importlib.util
        script = Path(__file__).resolve().parents[1] / "scripts" / "verify_install.py"
        spec = importlib.util.spec_from_file_location("verify_install", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.installer = module
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_real_demo_output_passes_the_store_proof(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            folder = run_demo(directory=self.temp.name)
        self.installer.require_support_proof(buffer.getvalue(),
                                             "test support-demo")

    def test_doctored_output_fails_the_proof(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            folder = run_demo(directory=self.temp.name)
        with self.assertRaises(SystemExit):
            self.installer.require_support_proof(
                buffer.getvalue().replace("issues filed: 2", "issues filed: 3"),
                "test support-demo")

    def test_missing_final_line_fails_the_proof(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            folder = run_demo(directory=self.temp.name)
        with self.assertRaises(SystemExit):
            self.installer.require_support_proof(
                "no final line here", "test support-demo")
