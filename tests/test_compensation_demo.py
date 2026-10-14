"""S10 demo wave: compensation demo — real crash withdrawal, refusal-not-reversal.

The demo builds every state through public Runtime commands, the real FakeOA
and a grants-carrying child subprocess that dies after the external commit;
these tests read the SQLite stores directly to assert what the public path
actually produced, never trusting the printed text for state.
"""

import contextlib
import hashlib
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

FINAL_LINE = ("2 scenarios; retained forward effects: 2 accepted applications; "
              "withdrawal effects: 1; refused withdrawals: 1; refusal is not reversal")


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


def accepted_forward_external_ids(oa_db):
    """Distinct accepted forward external ids (withdrawal/alias rows excluded)."""
    external_ids = set()
    for action, stored in rows(oa_db, "SELECT action,result FROM receipts"):
        result = json.loads(stored)
        if (result.get("status") == "accepted"
                and (action is None or action == "expense.submit")
                and isinstance(result.get("external_id"), str) and result["external_id"]):
            external_ids.add(result["external_id"])
    return external_ids


class CompensationDemoTests(unittest.TestCase):
    def setUp(self):
        from work_runtime import compensation_demo
        self.compensation_demo = compensation_demo
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def run_demo(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            folder = self.compensation_demo.run_compensation_demo(self.temp.name)
        return folder, out.getvalue()

    def scenario_operations(self, runtime_db):
        """(forward, withdrawal) operation pair of one scenario's store."""
        ops = operations(runtime_db)
        self.assertEqual(len(ops), 2)
        forward = next(op for op in ops if op["capability"] == "expense.submit")
        withdrawal = next(op for op in ops if op["capability"] == "expense.withdraw")
        return forward, withdrawal

    def test_demo_creates_separate_fresh_stores_per_scenario(self):
        folder, _ = self.run_demo()
        paths = [folder / scenario / name
                 for scenario, names in (("crash", ("runtime.sqlite", "oa.sqlite")),
                                         ("refusal", ("runtime.sqlite", "oa.sqlite",
                                                      "absent.sqlite")))
                 for name in names]
        for path in paths:
            self.assertTrue(path.exists(), path)
        self.assertEqual(len({str(path) for path in paths}), 5)

    def test_grants_stay_scoped_to_the_demo_module(self):
        grants = self.compensation_demo.compensation_grants()
        self.assertIn("expense.withdraw", grants["agent"])
        self.assertIn("work.intervene", grants["admin"])
        from work_runtime.demo import demo_grants
        for actor, capabilities in demo_grants().items():
            self.assertNotIn("expense.withdraw", capabilities, actor)
            self.assertNotIn("work.intervene", capabilities, actor)

    def test_crash_store_confirms_both_effects_with_single_attempts(self):
        folder, _ = self.run_demo()
        forward, withdrawal = self.scenario_operations(folder / "crash" / "runtime.sqlite")
        self.assertEqual(forward["status"], "confirmed_succeeded")
        self.assertEqual(len(forward["attempts"]), 1)
        self.assertTrue(forward["external_id"].startswith("OA-"))
        self.assertEqual(withdrawal["status"], "confirmed_succeeded")
        self.assertEqual(withdrawal["dispatch_state"], "finished")
        self.assertEqual(len(withdrawal["attempts"]), 1)
        self.assertEqual(withdrawal["attempts"][0]["status"], "confirmed_succeeded")
        self.assertTrue(withdrawal["external_id"].startswith("WD-"))
        self.assertEqual(withdrawal["compensates"], {
            "operation_id": forward["id"],
            "external_id": forward["external_id"],
            "capability": "expense.submit"})
        self.assertEqual(withdrawal["adapter_result"], {
            "status": "accepted", "external_id": withdrawal["external_id"],
            "digest": forward["document_digest"],
            "original_external_id": forward["external_id"]})

    def test_crash_store_business_keys_recomputed_locally(self):
        folder, _ = self.run_demo()
        runtime_db = folder / "crash" / "runtime.sqlite"
        forward, withdrawal = self.scenario_operations(runtime_db)
        state = work_state(runtime_db, "expense")
        self.assertEqual(forward["business_key"], local_digest(
            ["expense-submit", "expense.submit",
             state["document"]["id"], state["document_revision"]]))
        self.assertEqual(withdrawal["business_key"], local_digest(
            ["expense-submit", "expense.withdraw", forward["id"]]))
        self.assertNotEqual(forward["business_key"], withdrawal["business_key"])

    def test_crash_store_proofs_and_current_e08_truth(self):
        folder, _ = self.run_demo()
        runtime_db = folder / "crash" / "runtime.sqlite"
        forward, withdrawal = self.scenario_operations(runtime_db)
        accepted = evidence_body(runtime_db, "oa", forward["id"])
        self.assertEqual((accepted["kind"], accepted["status"]), ("accepted", "verified"))
        self.assertEqual(accepted["data"], {"digest": forward["document_digest"],
                                            "external_id": forward["external_id"]})
        withdrawn = evidence_body(runtime_db, "oa", withdrawal["id"])
        self.assertEqual((withdrawn["kind"], withdrawn["status"]), ("withdrawn", "verified"))
        self.assertEqual(withdrawn["data"], {
            "digest": withdrawal["document_digest"],
            "external_id": withdrawal["external_id"],
            "original_external_id": forward["external_id"]})
        fingerprint = rows(runtime_db,
                           "SELECT fingerprint FROM evidence WHERE source='oa' AND event_id=?",
                           (withdrawal["id"],))[0][0]
        self.assertEqual(fingerprint, local_digest(withdrawn))
        # The forward acceptance still satisfies E08: the withdrawal appends a
        # distinct proof kind, it never deletes or replaces the original truth.
        state = work_state(runtime_db, "expense")
        e08 = next(r for r in state["requirements"] if r["rule_id"] == "E08")
        self.assertEqual(e08["fulfillment"], "satisfied")

    def test_crash_store_oa_effect_rows_and_counts(self):
        folder, _ = self.run_demo()
        runtime_db = folder / "crash" / "runtime.sqlite"
        oa = folder / "crash" / "oa.sqlite"
        forward, withdrawal = self.scenario_operations(runtime_db)
        receipts = rows(oa, "SELECT key,digest,action,link_digest,result FROM receipts")
        self.assertEqual(len(receipts), 2)
        forward_row = next(r for r in receipts if r[0] == forward["business_key"])
        withdrawal_row = next(r for r in receipts if r[0] == withdrawal["business_key"])
        self.assertEqual((forward_row[2], forward_row[3]), ("expense.submit", None))
        self.assertEqual(forward_row[1], forward["document_digest"])
        self.assertEqual((withdrawal_row[2], withdrawal_row[3]),
                         ("expense.withdraw", local_digest(withdrawal["compensates"])))
        self.assertEqual(json.loads(withdrawal_row[4])["original_external_id"],
                         forward["external_id"])
        self.assertEqual(rows(oa, "SELECT original_external_id,external_id,key,digest "
                                  "FROM withdrawals"),
                         [(forward["external_id"], withdrawal["external_id"],
                           withdrawal["business_key"], withdrawal["document_digest"])])
        self.assertEqual(rows(oa, "SELECT invoice_id,external_id FROM invoices"),
                         [("INV-001", forward["external_id"])])
        self.assertEqual(accepted_forward_external_ids(oa), {forward["external_id"]})
        self.assertEqual(rows(oa, "SELECT COUNT(*) FROM withdrawals")[0][0], 1)

    def test_crash_store_closure_exact_two_id_ack_and_dispositions(self):
        folder, _ = self.run_demo()
        runtime_db = folder / "crash" / "runtime.sqlite"
        forward, withdrawal = self.scenario_operations(runtime_db)
        state = work_state(runtime_db, "expense")
        self.assertEqual((state["status"], state["outcome"]), ("closed", "cancelled"))
        completion = state["completion"]
        acknowledged = {entry["operation_id"]: entry["external_id"]
                        for entry in completion["acknowledged_operations"]}
        self.assertEqual(sorted(acknowledged), sorted([forward["id"], withdrawal["id"]]))
        self.assertEqual(acknowledged[forward["id"]], forward["external_id"])
        self.assertEqual(acknowledged[withdrawal["id"]], withdrawal["external_id"])
        dispositions = {entry["operation_id"]: entry
                        for entry in completion["operation_dispositions"]}
        self.assertEqual(set(dispositions[forward["id"]]),
                         {"operation_id", "status", "dispatch_state"})
        self.assertEqual(set(dispositions[withdrawal["id"]]),
                         {"operation_id", "status", "dispatch_state",
                          "compensates", "adapter_result"})
        self.assertEqual(dispositions[withdrawal["id"]]["compensates"],
                         withdrawal["compensates"])
        self.assertEqual(dispositions[withdrawal["id"]]["adapter_result"],
                         withdrawal["adapter_result"])

    def test_refusal_store_records_authoritative_refusal_without_reversal(self):
        folder, _ = self.run_demo()
        runtime_db = folder / "refusal" / "runtime.sqlite"
        forward, withdrawal = self.scenario_operations(runtime_db)
        self.assertEqual(forward["status"], "confirmed_succeeded")
        self.assertEqual(withdrawal["status"], "confirmed_failed")
        self.assertEqual(len(withdrawal["attempts"]), 1)
        self.assertEqual(withdrawal["attempts"][0]["status"], "confirmed_failed")
        self.assertEqual(withdrawal["adapter_result"]["status"], "rejected")
        self.assertEqual(withdrawal["adapter_result"]["reason"], "ORIGINAL_ABSENT")
        self.assertEqual(withdrawal["adapter_result"]["original_external_id"],
                         forward["external_id"])
        state = work_state(runtime_db, "expense")
        self.assertEqual((state["status"], state["outcome"]), ("closed", "cancelled"))
        acknowledged = [entry["operation_id"]
                        for entry in state["completion"]["acknowledged_operations"]]
        self.assertEqual(acknowledged, [forward["id"]])
        disposition = next(entry for entry in state["completion"]["operation_dispositions"]
                           if entry["operation_id"] == withdrawal["id"])
        self.assertEqual(disposition["adapter_result"]["reason"], "ORIGINAL_ABSENT")
        # A refused withdrawal never inserts a withdrawn proof.
        self.assertIsNone(evidence_body(runtime_db, "oa", withdrawal["id"]))
        # External truth: the original stays accepted and unwithdrawn in its own
        # store; the refusing store holds one queryable rejection, zero effects.
        oa, absent = folder / "refusal" / "oa.sqlite", folder / "refusal" / "absent.sqlite"
        self.assertEqual(accepted_forward_external_ids(oa), {forward["external_id"]})
        self.assertEqual(rows(oa, "SELECT COUNT(*) FROM withdrawals")[0][0], 0)
        absent_receipts = rows(absent, "SELECT action,link_digest,result FROM receipts")
        self.assertEqual(len(absent_receipts), 1)
        self.assertEqual(absent_receipts[0][0], "expense.withdraw")
        self.assertEqual(absent_receipts[0][1], local_digest(withdrawal["compensates"]))
        self.assertEqual(json.loads(absent_receipts[0][2])["reason"], "ORIGINAL_ABSENT")
        self.assertEqual(rows(absent, "SELECT COUNT(*) FROM withdrawals")[0][0], 0)

    def test_demo_output_pins_key_markers(self):
        _, out = self.run_demo()
        self.assertIn(FINAL_LINE, out)
        self.assertIn("exit code 73", out)
        self.assertIn("ORIGINAL_ABSENT", out)
        self.assertIn('inspect --db "', out)
        self.assertEqual(out.count("inspect --db"), 2)

    def test_demo_runs_are_repeatable(self):
        folder_one, out_one = self.run_demo()
        folder_two, out_two = self.run_demo()
        self.assertNotEqual(folder_one, folder_two)
        self.assertIn(FINAL_LINE, out_one)
        self.assertIn(FINAL_LINE, out_two)


class CompensationDemoCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_cli_compensation_demo_module_runs(self):
        result = subprocess.run([sys.executable, "-m", "work_runtime", "compensation-demo"],
                                cwd=str(REPO_ROOT), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(FINAL_LINE, result.stdout)
        self.assertEqual(result.stdout.count("inspect --db"), 2)

    def test_shipped_worker_cli_cannot_withdraw(self):
        """Truthful boundary pin: the shipped worker hardwires the demo grants
        (no expense.withdraw), so a withdrawal dispatch through it holds
        AUTHORITY_DENIED with zero attempts and zero effects — the demo's
        grants-carrying child exists precisely because of this boundary."""
        from work_runtime.adapters import FakeOA
        from work_runtime.compensation_demo import compensation_grants, withdrawal
        from work_runtime.demo import action, initialize, prerequisites, send
        from work_runtime.policy import ExpensePolicy
        from work_runtime.runtime import Runtime
        runtime_path = Path(self.temp.name) / "runtime.sqlite"
        oa_path = Path(self.temp.name) / "oa.sqlite"
        runtime = Runtime(str(runtime_path), ExpensePolicy(), compensation_grants())
        oa = FakeOA(str(oa_path))
        initialize(runtime, "expense")
        prerequisites(runtime, "expense")
        forward = action(runtime, work_id="expense", command_id="submit-once")
        runtime.dispatch(forward["operation_id"], oa)
        send(runtime, "expense", "request_cancel", {"reason": "r"}, actor="admin")
        proposal = withdrawal(runtime, "expense", forward["operation_id"],
                              command_id="withdraw-once")
        self.assertEqual(proposal["decision"], "accepted")
        withdrawal_id = proposal["operation_id"]
        result = subprocess.run([sys.executable, "-m", "work_runtime", "worker",
                                 "--runtime", str(runtime_path), "--oa", str(oa_path),
                                 "--operation", withdrawal_id],
                                cwd=str(REPO_ROOT), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        held = Runtime(str(runtime_path), ExpensePolicy(),
                       compensation_grants()).get_operation(withdrawal_id)
        self.assertEqual((held["dispatch_state"], held["reason"]),
                         ("held", "AUTHORITY_DENIED"))
        self.assertEqual(held["attempts"], [])
        self.assertEqual(rows(oa_path, "SELECT COUNT(*) FROM withdrawals")[0][0], 0)
        self.assertEqual(accepted_forward_external_ids(oa_path),
                         {runtime.get_operation(forward["operation_id"])["external_id"]})


def _load_verify_install():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "verify_install", REPO_ROOT / "scripts" / "verify_install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VerifyInstallCompensationProofTests(unittest.TestCase):
    """The installer proof reads the demo's real stores, never its stdout."""

    def setUp(self):
        from work_runtime import compensation_demo
        self.verify_install = _load_verify_install()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.folder = compensation_demo.run_compensation_demo(self.temp.name)
        self.stdout = out.getvalue()

    def mutate(self, relative, sql, args=()):
        db = sqlite3.connect(str(self.folder / relative))
        with db:
            db.execute(sql, args)
        db.close()

    def proof(self, stdout=None):
        return self.verify_install.require_compensation_proof(
            stdout if stdout is not None else self.stdout, "test")

    def test_proof_passes_on_real_demo_output(self):
        stores = self.proof()
        self.assertEqual([Path(store).parent.name for store in stores],
                         ["crash", "refusal"])

    def test_proof_rejects_missing_final_line(self):
        stripped = "\n".join(line for line in self.stdout.splitlines()
                             if FINAL_LINE not in line) + "\n"
        with self.assertRaises(SystemExit) as raised:
            self.proof(stripped)
        self.assertIn("refusal is not reversal", str(raised.exception))

    def test_proof_rejects_deleted_withdrawal_row(self):
        self.mutate("crash/oa.sqlite", "DELETE FROM withdrawals")
        with self.assertRaises(SystemExit) as raised:
            self.proof()
        self.assertIn("withdrawal row", str(raised.exception))

    def test_proof_rejects_wrong_linked_target(self):
        # Rewrite the withdrawal operation's immutable link to a forged original.
        db = sqlite3.connect(str(self.folder / "crash" / "runtime.sqlite"))
        with db:
            body_rows = db.execute("SELECT id, body FROM operations").fetchall()
        db.close()
        for op_id, body in body_rows:
            operation = json.loads(body)
            if operation["capability"] == "expense.withdraw":
                operation["compensates"]["external_id"] = "OA-forged000000"
                db = sqlite3.connect(str(self.folder / "crash" / "runtime.sqlite"))
                with db:
                    db.execute("UPDATE operations SET body=? WHERE id=?",
                               (canonical_json(operation), op_id))
                db.close()
        with self.assertRaises(SystemExit) as raised:
            self.proof()
        self.assertIn("compensates", str(raised.exception))

    def test_proof_rejects_swapped_link_digest(self):
        self.mutate("crash/oa.sqlite",
                    "UPDATE receipts SET link_digest='0' WHERE action='expense.withdraw'")
        with self.assertRaises(SystemExit) as raised:
            self.proof()
        self.assertIn("link", str(raised.exception).lower())

    def test_proof_rejects_forged_forward_receipt(self):
        self.mutate(
            "crash/oa.sqlite",
            "INSERT INTO receipts (key,digest,result,action,link_digest) "
            "VALUES ('forged-key','forged-digest',?,'expense.submit',NULL)",
            ('{"digest":"forged-digest","external_id":"OA-forged000000",'
             '"status":"accepted"}',))
        with self.assertRaises(SystemExit) as raised:
            self.proof()
        self.assertIn("receipts", str(raised.exception))

    def test_proof_rejects_flipped_proof_kind(self):
        self.mutate("crash/runtime.sqlite",
                    "UPDATE evidence SET body=replace(body, "
                    "'\"kind\":\"withdrawn\"', '\"kind\":\"accepted\"') "
                    "WHERE source='oa' AND body LIKE '%\"kind\":\"withdrawn\"%'")
        with self.assertRaises(SystemExit) as raised:
            self.proof()
        self.assertIn("withdrawn", str(raised.exception))

    def test_proof_rejects_refusal_withdrawal_effect(self):
        self.mutate("refusal/absent.sqlite",
                    "INSERT INTO withdrawals VALUES ('OA-forged','WD-forged',"
                    "'forged-key','forged-digest')")
        with self.assertRaises(SystemExit) as raised:
            self.proof()
        self.assertIn("refusing store", str(raised.exception))

    def test_proof_rejects_deleted_absent_rejection(self):
        self.mutate("refusal/absent.sqlite", "DELETE FROM receipts")
        with self.assertRaises(SystemExit) as raised:
            self.proof()
        self.assertIn("refusing store", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
