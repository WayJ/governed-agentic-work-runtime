"""S8 Task3: revocation demo harness — real scenarios, counted effects, printed commands.

The demo builds every state through public Runtime commands and the real
adapters; these tests read the SQLite stores directly to assert what the
public path actually produced, never trusting the printed text for state.
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

REPO_ROOT = Path(__file__).resolve().parents[1]

FINAL_LINE = ("3 scenarios; retained external effects: 2 accepted applications, "
              "1 published artifact; effects reversed: 0")


def evidence_body(runtime_db, source, event_id):
    """One parsed evidence row, or None, straight from the runtime database."""
    db = sqlite3.connect(str(runtime_db))
    try:
        row = db.execute("SELECT body FROM evidence WHERE source=? AND event_id=?",
                         (source, event_id)).fetchone()
        return json.loads(row[0]) if row else None
    finally:
        db.close()


def revoked_events(runtime_db):
    db = sqlite3.connect(str(runtime_db))
    try:
        return [json.loads(row[0]) for row in db.execute(
            "SELECT body FROM events WHERE type='EvidenceRevoked' ORDER BY seq")]
    finally:
        db.close()


def operation_bodies(runtime_db):
    db = sqlite3.connect(str(runtime_db))
    try:
        return [json.loads(row[0]) for row in db.execute("SELECT body FROM operations")]
    finally:
        db.close()


def work_state(runtime_db, work_id):
    db = sqlite3.connect(str(runtime_db))
    try:
        row = db.execute("SELECT state FROM works WHERE id=?", (work_id,)).fetchone()
        return json.loads(row[0])
    finally:
        db.close()


def requirement(state, rule_id):
    return next(r for r in state["requirements"] if r["id"].startswith(rule_id + ":"))


def accepted_in_store(oa_path):
    db = sqlite3.connect(str(oa_path))
    try:
        rows = [json.loads(row[0]) for row in db.execute("SELECT result FROM receipts")]
    finally:
        db.close()
    return sum(1 for row in rows if row.get("status") == "accepted")


def receipt_count(oa_path):
    db = sqlite3.connect(str(oa_path))
    try:
        return db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
    finally:
        db.close()


def publication_count(publisher_db):
    db = sqlite3.connect(str(publisher_db))
    try:
        return db.execute("SELECT COUNT(*) FROM publications").fetchone()[0]
    finally:
        db.close()


class RevocationDemoTests(unittest.TestCase):
    def setUp(self):
        from work_runtime import revocation_demo
        self.revocation_demo = revocation_demo
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def run_demo(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            folder = self.revocation_demo.run_revocation_demo(self.temp.name)
        return folder, out.getvalue()

    def test_demo_creates_separate_fresh_stores_per_scenario(self):
        folder, _ = self.run_demo()
        paths = [folder / scenario / name
                 for scenario, names in (("hold", ("runtime.sqlite", "oa.sqlite")),
                                         ("uncertain", ("runtime.sqlite", "oa.sqlite")),
                                         ("publish", ("runtime.sqlite", "publisher.sqlite")))
                 for name in names]
        for path in paths:
            self.assertTrue(path.exists(), path)
        self.assertEqual(len({str(path) for path in paths}), 6)

    def test_hold_store_shows_revoked_approval_readmission_and_single_call(self):
        folder, _ = self.run_demo()
        runtime_db = folder / "hold" / "runtime.sqlite"
        revoked = evidence_body(runtime_db, "finance", "evt-hold-approval")
        self.assertEqual((revoked["status"], revoked["source"], revoked["kind"]),
                         ("revoked", "finance", "approval"))
        replacement = evidence_body(runtime_db, "finance", "evt-hold-approval-2")
        self.assertEqual(replacement["status"], "verified")
        # One readmitted operation under a stable business key: held with zero
        # attempts first, then dispatched exactly once.
        operations = operation_bodies(runtime_db)
        self.assertEqual(len(operations), 1)
        operation = operations[0]
        self.assertEqual((operation["status"], operation["dispatch_state"]),
                         ("confirmed_succeeded", "finished"))
        self.assertEqual(len(operation["attempts"]), 1)
        self.assertTrue(operation["external_id"].startswith("OA-"))
        self.assertEqual(len(operation["business_key"]), 64)
        events = revoked_events(runtime_db)
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0]["event_id"], events[0]["prior_status"]),
                         ("evt-hold-approval", "verified"))
        # Zero external calls while held; exactly one receipt for the final call.
        self.assertEqual(receipt_count(folder / "hold" / "oa.sqlite"), 1)
        self.assertEqual(accepted_in_store(folder / "hold" / "oa.sqlite"), 1)
        state = work_state(runtime_db, "hold")
        self.assertEqual(requirement(state, "E05")["fulfillment"], "satisfied")

    def test_uncertain_store_retains_one_effect_with_two_revoked_proofs(self):
        folder, _ = self.run_demo()
        runtime_db = folder / "uncertain" / "runtime.sqlite"
        operations = operation_bodies(runtime_db)
        self.assertEqual(len(operations), 1)
        operation_id = operations[0]["id"]
        approval = evidence_body(runtime_db, "finance", "evt-uncertain-approval")
        self.assertEqual(approval["status"], "revoked")
        accepted = evidence_body(runtime_db, "oa", operation_id)
        self.assertEqual((accepted["status"], accepted["kind"], accepted["event_id"]),
                         ("revoked", "accepted", operation_id))
        self.assertEqual((operations[0]["status"], operations[0]["dispatch_state"]),
                         ("confirmed_succeeded", "finished"))
        self.assertEqual(len(operations[0]["attempts"]), 1)
        self.assertTrue(operations[0]["external_id"].startswith("OA-"))
        events = revoked_events(runtime_db)
        self.assertEqual([event["source"] for event in events], ["oa", "finance"])
        # The uncertain effect was reconciled by lookup, never resent.
        self.assertEqual(receipt_count(folder / "uncertain" / "oa.sqlite"), 1)
        self.assertEqual(accepted_in_store(folder / "uncertain" / "oa.sqlite"), 1)
        state = work_state(runtime_db, "uncertain")
        self.assertEqual(requirement(state, "E05")["fulfillment"], "pending")
        self.assertEqual(requirement(state, "E08")["fulfillment"], "pending")

    def test_publish_store_closed_correction_preserves_completion(self):
        folder, _ = self.run_demo()
        runtime_db = folder / "publish" / "runtime.sqlite"
        state = work_state(runtime_db, "publish")
        self.assertEqual((state["status"], state["outcome"]), ("closed", "succeeded"))
        operations = operation_bodies(runtime_db)
        self.assertEqual(len(operations), 1)
        operation_id = operations[0]["id"]
        accepted = evidence_body(runtime_db, "publisher", operation_id)
        self.assertEqual(accepted["status"], "revoked")
        # Historical closure keeps citing the acceptance; only current
        # validity changed (C04 pending again, C02 satisfied by replacement).
        self.assertIn(accepted["id"], state["completion"]["evidence"])
        self.assertEqual(requirement(state, "C04")["fulfillment"], "pending")
        self.assertEqual(requirement(state, "C02")["fulfillment"], "satisfied")
        self.assertEqual(evidence_body(runtime_db, "reviewer", "evt-pub-approval")["status"],
                         "revoked")
        self.assertEqual(evidence_body(runtime_db, "reviewer", "evt-pub-approval-2")["status"],
                         "verified")
        events = revoked_events(runtime_db)
        self.assertEqual([event["source"] for event in events], ["reviewer", "publisher"])
        self.assertTrue(events[1]["work_was_closed"])
        self.assertTrue(events[1]["completion_cites_evidence"])
        self.assertEqual(publication_count(folder / "publish" / "publisher.sqlite"), 1)

    def test_demo_output_pins_key_markers(self):
        _, out = self.run_demo()
        for marker in ("REQUIREMENT_UNSATISFIED", "held", "confirmed_succeeded",
                       "evidence_status \"revoked\"", FINAL_LINE):
            self.assertIn(marker, out)
        inspect_lines = [line.strip() for line in out.splitlines()
                         if line.strip().startswith("python3 -m work_runtime inspect")]
        self.assertEqual(len(inspect_lines), 3)
        self.assertTrue(inspect_lines[2].endswith("--policy content-publish"),
                        inspect_lines[2])

    def test_demo_runs_are_repeatable(self):
        folder_a, out_a = self.run_demo()
        folder_b, out_b = self.run_demo()
        self.assertIn(FINAL_LINE, out_a)
        self.assertIn(FINAL_LINE, out_b)
        for folder in (folder_a, folder_b):
            self.assertEqual(accepted_in_store(folder / "hold" / "oa.sqlite"), 1)
            self.assertEqual(accepted_in_store(folder / "uncertain" / "oa.sqlite"), 1)
            self.assertEqual(publication_count(folder / "publish" / "publisher.sqlite"), 1)


class RevocationDemoCliTests(unittest.TestCase):
    def test_cli_revocation_demo_module_runs(self):
        result = subprocess.run([sys.executable, "-m", "work_runtime", "revocation-demo"],
                                cwd=str(REPO_ROOT), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(FINAL_LINE, result.stdout)
        self.assertIn("effects reversed: 0", result.stdout)


def _load_verify_install():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "verify_install", REPO_ROOT / "scripts" / "verify_install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VerifyInstallRevocationProofTests(unittest.TestCase):
    """The installer proof reads the demo's real stores, never its stdout."""

    def setUp(self):
        from work_runtime import revocation_demo
        self.verify_install = _load_verify_install()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.folder = revocation_demo.run_revocation_demo(self.temp.name)
        self.stdout = out.getvalue()

    def test_proof_passes_on_real_demo_output(self):
        stores = self.verify_install.require_revocation_proof(self.stdout, "test")
        self.assertEqual([Path(store).parent.name for store in stores],
                         ["hold", "uncertain", "publish"])

    def test_proof_rejects_missing_final_line(self):
        stripped = "\n".join(line for line in self.stdout.splitlines()
                             if FINAL_LINE not in line) + "\n"
        with self.assertRaises(SystemExit) as raised:
            self.verify_install.require_revocation_proof(stripped, "test")
        self.assertIn("effects reversed", str(raised.exception))

    def test_proof_rejects_swapped_store_order(self):
        lines = self.stdout.splitlines()
        indexes = [i for i, line in enumerate(lines) if "inspect --db" in line]
        lines[indexes[0]], lines[indexes[1]] = lines[indexes[1]], lines[indexes[0]]
        with self.assertRaises(SystemExit) as raised:
            self.verify_install.require_revocation_proof("\n".join(lines), "test")
        self.assertIn("hold, uncertain, publish", str(raised.exception))

    def test_proof_rejects_deleted_external_receipt(self):
        db = sqlite3.connect(str(self.folder / "hold" / "oa.sqlite"))
        with db:
            db.execute("DELETE FROM receipts")
        db.close()
        with self.assertRaises(SystemExit) as raised:
            self.verify_install.require_revocation_proof(self.stdout, "test")
        self.assertIn("hold", str(raised.exception))

    def test_proof_rejects_flipped_revoked_status(self):
        db = sqlite3.connect(str(self.folder / "hold" / "runtime.sqlite"))
        with db:
            db.execute("UPDATE evidence SET body=replace(body, "
                       "'\"status\":\"revoked\"', '\"status\":\"verified\"') "
                       "WHERE source='finance' AND event_id='evt-hold-approval'")
        db.close()
        with self.assertRaises(SystemExit) as raised:
            self.verify_install.require_revocation_proof(self.stdout, "test")
        self.assertIn("evt-hold-approval", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
