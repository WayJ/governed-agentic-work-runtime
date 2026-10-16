"""S14 W2 demo wave: publish-demo retraction chapter — cancel, linked retraction,
real crash recovery, exact two-id closure.

The demo builds every state through public Runtime commands, the real
FakePublisher store and a grants-carrying child subprocess that dies after
the external retraction commit; these tests read the SQLite stores directly
to assert what the public path actually produced, never trusting the printed
text for state.
"""

import contextlib
import hashlib
import io
import json
import re
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from work_runtime.publishing_demo import publishing_grants, run_demo

REPO_ROOT = Path(__file__).resolve().parents[1]

FINAL_LINE = ("2 works; published artifacts: 2; retraction effects: 1; "
              "bounded in-window retraction, not reversal")

INSPECT_COMMAND = re.compile(r"^  (python3 -m work_runtime inspect .+)$",
                             re.MULTILINE)


def canonical_json(value):
    """Canonical JSON with the same parameters the runtime uses (local copy)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def local_digest(value):
    """SHA-256 over canonical JSON, recomputed independently of the product."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def rows(db_path, sql, args=()):
    db = sqlite3.connect(str(db_path))
    try:
        return db.execute(sql, args).fetchall()
    finally:
        db.close()


def operations(runtime_db):
    return [json.loads(row[0]) for row in rows(runtime_db, "SELECT body FROM operations")]


def work_state(runtime_db, work_id):
    state = rows(runtime_db, "SELECT state FROM works WHERE id=?", (work_id,))
    assert state, work_id
    return json.loads(state[0][0])


def evidence_body(runtime_db, source, event_id):
    found = rows(runtime_db, "SELECT body FROM evidence WHERE source=? AND event_id=?",
                 (source, event_id))
    return json.loads(found[0][0]) if found else None


class PublishingRetractionDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def run_demo(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            folder = run_demo(directory=self.temp.name)
        return folder, out.getvalue()

    def scenario_operations(self, runtime_db):
        """(forward, retraction) operation pair of the second work's store."""
        ops = [op for op in operations(runtime_db) if op["work_id"] == "article-2"]
        self.assertEqual(len(ops), 2)
        forward = next(op for op in ops if op["capability"] == "content.publish")
        retraction = next(op for op in ops if op["capability"] == "content.unpublish")
        return forward, retraction

    def test_demo_keeps_work_one_story_and_appends_chapter(self):
        _, out = self.run_demo()
        for expected in ("1.", "2.", "3.", "4.", "5.", "6.", "BLOCKED",
                         "EVIDENCE_AUTHENTICATION_FAILED",
                         "6. Evidence-backed completion → SUCCEEDED; "
                         "published artifacts: 1",
                         "Retraction chapter", "7.", "8.", "9.", "10.", "11.",
                         "12.", "exit code 73", FINAL_LINE,
                         "inspect --db"):
            self.assertIn(expected, out)
        self.assertEqual(out.count("inspect --db"), 2)

    def test_demo_grants_gain_the_paired_capability_only(self):
        self.assertEqual(publishing_grants(), {
            "agent": {"work.manage", "content.publish", "content.unpublish"},
            "reviewer": {"evidence.write"}, "author": {"evidence.write"}})

    def test_retraction_counts_asserted_against_real_stores(self):
        folder, _ = self.run_demo()
        publisher = folder / "publisher.sqlite"
        self.assertEqual(
            rows(publisher, "SELECT COUNT(*) FROM publications")[0][0], 2)
        self.assertEqual(
            rows(publisher, "SELECT COUNT(*) FROM retractions")[0][0], 1)
        self.assertEqual(sorted(row[0] for row in rows(
            publisher, "SELECT document_id FROM publications")),
            ["ART-001", "ART-002"])
        runtime_db = folder / "runtime.sqlite"
        first = work_state(runtime_db, "article-1")
        second = work_state(runtime_db, "article-2")
        self.assertEqual((first["status"], first["outcome"]),
                         ("closed", "succeeded"))
        self.assertEqual((second["status"], second["outcome"]),
                         ("closed", "cancelled"))

    def test_retraction_business_keys_and_link_recomputed(self):
        folder, _ = self.run_demo()
        runtime_db = folder / "runtime.sqlite"
        forward, retraction = self.scenario_operations(runtime_db)
        state = work_state(runtime_db, "article-2")
        self.assertEqual(forward["business_key"], local_digest(
            ["content-publish", "content.publish",
             state["document"]["id"], state["document_digest"]]))
        self.assertEqual(retraction["business_key"], local_digest(
            ["content-publish", "content.unpublish", forward["id"]]))
        self.assertNotEqual(forward["business_key"], retraction["business_key"])
        for operation, prefix, label in ((forward, "PUB-", "forward"),
                                         (retraction, "RTR-", "retraction")):
            self.assertEqual(operation["status"], "confirmed_succeeded", label)
            self.assertEqual(operation["dispatch_state"], "finished", label)
            self.assertEqual(len(operation["attempts"]), 1, label)
            self.assertTrue(operation["external_id"].startswith(prefix), label)
        self.assertEqual(retraction["compensates"], {
            "operation_id": forward["id"],
            "external_id": forward["external_id"],
            "capability": "content.publish"})
        self.assertEqual(retraction["adapter_result"], {
            "status": "accepted", "external_id": retraction["external_id"],
            "digest": forward["document_digest"],
            "original_external_id": forward["external_id"]})

    def test_withdrawn_proof_appends_and_forward_truth_retained(self):
        folder, _ = self.run_demo()
        runtime_db = folder / "runtime.sqlite"
        forward, retraction = self.scenario_operations(runtime_db)
        accepted = evidence_body(runtime_db, "publisher", forward["id"])
        self.assertEqual((accepted["kind"], accepted["status"]),
                         ("accepted", "verified"))
        self.assertEqual(accepted["data"], {"digest": forward["document_digest"],
                                            "external_id": forward["external_id"]})
        withdrawn = evidence_body(runtime_db, "publisher", retraction["id"])
        self.assertEqual((withdrawn["kind"], withdrawn["status"]),
                         ("withdrawn", "verified"))
        self.assertEqual(withdrawn["data"], {
            "digest": retraction["document_digest"],
            "external_id": retraction["external_id"],
            "original_external_id": forward["external_id"]})
        fingerprint = rows(runtime_db,
                           "SELECT fingerprint FROM evidence "
                           "WHERE source='publisher' AND event_id=?",
                           (retraction["id"],))[0][0]
        self.assertEqual(fingerprint, local_digest(withdrawn))
        # The retracted publication's accepted proof still satisfies C04: the
        # retraction appends a distinct proof kind, it never deletes truth.
        state = work_state(runtime_db, "article-2")
        c04 = next(r for r in state["requirements"] if r["rule_id"] == "C04")
        self.assertEqual(c04["fulfillment"], "satisfied")

    def test_publisher_store_rows_tagged_and_append_only(self):
        folder, _ = self.run_demo()
        publisher = folder / "publisher.sqlite"
        runtime_db = folder / "runtime.sqlite"
        forward, retraction = self.scenario_operations(runtime_db)
        receipts = rows(publisher, "SELECT key,digest,action,link_digest,result "
                                   "FROM receipts")
        # Work one's forward receipt, work two's forward receipt and the
        # retraction receipt — the original rows are never rewritten.
        self.assertEqual(len(receipts), 3)
        retraction_row = next(r for r in receipts
                              if r[0] == retraction["business_key"])
        self.assertEqual(retraction_row[2], "content.unpublish")
        self.assertEqual(retraction_row[3], local_digest(retraction["compensates"]))
        self.assertEqual(json.loads(retraction_row[4]), retraction["adapter_result"])
        self.assertEqual(
            rows(publisher, "SELECT original_external_id,external_id,key,digest "
                            "FROM retractions"),
            [(forward["external_id"], retraction["external_id"],
              retraction["business_key"], retraction["document_digest"])])

    def test_two_id_closure_and_dispositions(self):
        folder, _ = self.run_demo()
        runtime_db = folder / "runtime.sqlite"
        forward, retraction = self.scenario_operations(runtime_db)
        completion = work_state(runtime_db, "article-2")["completion"]
        externals = {entry["operation_id"]: entry["external_id"]
                     for entry in completion["acknowledged_operations"]}
        self.assertEqual(set(externals), {forward["id"], retraction["id"]})
        self.assertTrue(externals[forward["id"]].startswith("PUB-"))
        self.assertTrue(externals[retraction["id"]].startswith("RTR-"))
        dispositions = {entry["operation_id"]: entry
                        for entry in completion["operation_dispositions"]}
        self.assertEqual(set(dispositions[forward["id"]]),
                         {"operation_id", "status", "dispatch_state"})
        self.assertEqual(set(dispositions[retraction["id"]]),
                         {"operation_id", "status", "dispatch_state",
                          "compensates", "adapter_result"})
        self.assertEqual(dispositions[retraction["id"]]["compensates"],
                         retraction["compensates"])
        self.assertEqual(dispositions[retraction["id"]]["adapter_result"],
                         retraction["adapter_result"])

    def test_crash_beat_recovers_once(self):
        folder, out = self.run_demo()
        self.assertIn("exit code 73", out)
        runtime_db = folder / "runtime.sqlite"
        forward, retraction = self.scenario_operations(runtime_db)
        self.assertEqual(retraction["status"], "confirmed_succeeded")
        self.assertEqual(len(retraction["attempts"]), 1)
        self.assertEqual(retraction["attempts"][0]["status"],
                         "confirmed_succeeded")
        # Exactly one retraction effect after recovery — nothing resent.
        self.assertEqual(
            rows(folder / "publisher.sqlite",
                 "SELECT COUNT(*) FROM retractions")[0][0], 1)

    def test_secrets_never_printed(self):
        _, out = self.run_demo()
        self.assertNotRegex(out, "[0-9a-f]{64}")

    def test_runs_repeatable(self):
        folder_one, out_one = self.run_demo()
        folder_two, out_two = self.run_demo()
        self.assertNotEqual(folder_one, folder_two)
        for out in (out_one, out_two):
            self.assertIn(FINAL_LINE, out)
        for folder in (folder_one, folder_two):
            publisher = folder / "publisher.sqlite"
            self.assertEqual(
                rows(publisher, "SELECT COUNT(*) FROM publications")[0][0], 2)
            self.assertEqual(
                rows(publisher, "SELECT COUNT(*) FROM retractions")[0][0], 1)


class PublishingRetractionCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_cli_module_runs_with_chapter(self):
        result = subprocess.run(
            [sys.executable, "-m", "work_runtime", "publish-demo"],
            cwd=str(REPO_ROOT), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(FINAL_LINE, result.stdout)
        self.assertEqual(result.stdout.count("inspect --db"), 2)

    def test_printed_inspect_commands_run_verbatim(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            run_demo(directory=self.temp.name)
        commands = INSPECT_COMMAND.findall(out.getvalue())
        self.assertEqual(len(commands), 2)
        markers = {"article-1": '"outcome": "succeeded"',
                   "article-2": '"outcome": "cancelled"'}
        for command in commands:
            words = shlex.split(command)
            self.assertEqual(words[0], "python3")
            work = words[words.index("--work") + 1]
            self.assertIn(work, markers)
            words[0] = sys.executable
            result = subprocess.run(words, cwd=str(REPO_ROOT),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(markers[work], result.stdout)


def _load_verify_install():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "verify_install", REPO_ROOT / "scripts" / "verify_install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VerifyInstallPublishingProofTests(unittest.TestCase):
    """The installer proof reads the demo's real stores, never its stdout."""

    def setUp(self):
        self.verify_install = _load_verify_install()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.folder = run_demo(directory=self.temp.name)
        self.stdout = out.getvalue()

    def mutate(self, relative, sql, args=()):
        db = sqlite3.connect(str(self.folder / relative))
        with db:
            db.execute(sql, args)
        db.close()

    def proof(self, stdout=None):
        return self.verify_install.require_publishing_proof(
            stdout if stdout is not None else self.stdout, "test")

    def test_proof_passes_on_real_demo_output(self):
        runtime_db = Path(self.proof())
        self.assertEqual(runtime_db.name, "runtime.sqlite")
        self.assertEqual(runtime_db.parent.name.split("-")[:2],
                         ["governed", "publish"])

    def test_proof_rejects_missing_final_line(self):
        stripped = "\n".join(line for line in self.stdout.splitlines()
                             if FINAL_LINE not in line) + "\n"
        with self.assertRaises(SystemExit) as raised:
            self.proof(stripped)
        self.assertIn("not reversal", str(raised.exception))

    def test_proof_rejects_deleted_retraction_row(self):
        self.mutate("publisher.sqlite", "DELETE FROM retractions")
        with self.assertRaises(SystemExit) as raised:
            self.proof()
        self.assertIn("retraction", str(raised.exception).lower())

    def test_proof_rejects_missing_second_publication(self):
        self.mutate("publisher.sqlite",
                    "DELETE FROM publications WHERE document_id='ART-002'")
        with self.assertRaises(SystemExit) as raised:
            self.proof()
        self.assertIn("publication", str(raised.exception).lower())

    def test_proof_rejects_flipped_proof_kind(self):
        self.mutate("runtime.sqlite",
                    "UPDATE evidence SET body=replace(body, "
                    "'\"kind\":\"withdrawn\"', '\"kind\":\"accepted\"') "
                    "WHERE source='publisher' AND body LIKE "
                    "'%\"kind\":\"withdrawn\"%'")
        with self.assertRaises(SystemExit) as raised:
            self.proof()
        self.assertIn("withdrawn", str(raised.exception))

    def test_proof_rejects_forged_closure_ack(self):
        """Dropping the retraction id from the closure ack must fail the
        proof: the acknowledgement is store truth, not narration."""
        runtime_db = self.folder / "runtime.sqlite"
        db = sqlite3.connect(str(runtime_db))
        with db:
            state = json.loads(db.execute(
                "SELECT state FROM works WHERE id='article-2'").fetchone()[0])
            retraction_id = next(
                json.loads(row[0])["id"] for row in
                db.execute("SELECT body FROM operations")
                if json.loads(row[0])["capability"] == "content.unpublish")
        db.close()
        state["completion"]["acknowledged_operations"] = [
            entry for entry in state["completion"]["acknowledged_operations"]
            if entry["operation_id"] != retraction_id]
        db = sqlite3.connect(str(runtime_db))
        with db:
            db.execute("UPDATE works SET state=? WHERE id='article-2'",
                       (canonical_json(state),))
        db.close()
        with self.assertRaises(SystemExit) as raised:
            self.proof()
        self.assertIn("ack", str(raised.exception).lower())


if __name__ == "__main__":
    unittest.main()
