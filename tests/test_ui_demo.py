"""Tests for the UI demo seed: five real works in one expense-family store.

Every assertion reads the durable SQLite record directly (the same stored
truth the GUI will serve), not the seed's printed text. The seed must reach
each pinned state through real Runtime commands and the real FakeOA only.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from work_runtime.adapters import FakeOA
from work_runtime.policy import digest
from work_runtime.demo import document
from work_runtime.ui_demo import UnavailableLookup, seed_ui_demo

WORK_IDS = ["cancel-1", "succeed-1", "transfer-1", "uncertain-1", "wait-1"]


def rows(db_path, sql, parameters=()):
    db = sqlite3.connect(str(db_path))
    try:
        return db.execute(sql, parameters).fetchall()
    finally:
        db.close()


def work_state(db_path, work_id):
    stored = rows(db_path, "SELECT state FROM works WHERE id=?", (work_id,))
    return json.loads(stored[0][0]) if stored else None


def operation_bodies(db_path, work_id):
    return [json.loads(r[0]) for r in rows(
        db_path, "SELECT body FROM operations WHERE work_id=?", (work_id,))]


def evidence_bodies(db_path, work_id):
    return [json.loads(r[0]) for r in rows(
        db_path, "SELECT body FROM evidence WHERE work_id=?", (work_id,))]


def event_types(db_path, work_id):
    return [r[0] for r in rows(
        db_path, "SELECT type FROM events WHERE work_id=? ORDER BY seq", (work_id,))]


def command_receipt(db_path, actor, command_id):
    stored = rows(db_path, "SELECT receipt FROM commands WHERE actor=? AND id=?",
                  (actor, command_id))
    return json.loads(stored[0][0]) if stored else None


class SeedShapeTests(unittest.TestCase):
    def setUp(self):
        self.parent = tempfile.mkdtemp()
        self.db = seed_ui_demo(self.parent)
        self.oa_db = str(Path(self.db).parent / "oa.sqlite")

    def test_creates_exactly_the_five_pinned_works(self):
        stored = [r[0] for r in rows(self.db, "SELECT id FROM works ORDER BY id")]
        self.assertEqual(stored, WORK_IDS)

    def test_wait_1_is_waiting_with_a_pending_approval(self):
        work = work_state(self.db, "wait-1")
        self.assertEqual(work["status"], "waiting")
        e05 = next(r for r in work["requirements"] if r["rule_id"] == "E05")
        self.assertEqual((e05["applicability"], e05["fulfillment"]),
                         ("applicable", "pending"))
        self.assertEqual(len(work["waits"]), 1)
        self.assertEqual((work["waits"][0]["status"], work["waits"][0]["owner"]),
                         ("waiting", "finance"))
        pending = [e for e in evidence_bodies(self.db, "wait-1")
                   if e["status"] == "pending_verification"]
        self.assertEqual([e["kind"] for e in pending], ["approval"])

    def test_wait_1_keeps_the_rejected_proposal_as_a_historic_decision(self):
        receipt = command_receipt(self.db, "agent", "wait-1-propose")
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "REQUIREMENT_UNSATISFIED")
        self.assertTrue(receipt["blockers"])

    def test_uncertain_1_needs_attention_with_retained_external_effect(self):
        work = work_state(self.db, "uncertain-1")
        self.assertEqual(work["status"], "needs_attention")
        operation = operation_bodies(self.db, "uncertain-1")[0]
        self.assertEqual(operation["status"], "outcome_unknown")
        self.assertEqual(operation["reason"], "NO_AUTHORITATIVE_RESULT")
        self.assertIn("ReconciliationRequired", event_types(self.db, "uncertain-1"))
        # The effect exists in the external store even though no authoritative
        # result could be produced for it.
        stored = rows(self.oa_db, "SELECT result FROM receipts WHERE key=?",
                      (operation["business_key"],))
        self.assertEqual(json.loads(stored[0][0])["status"], "accepted")

    def test_transfer_1_is_owned_by_the_delegate_and_succeeded(self):
        work = work_state(self.db, "transfer-1")
        self.assertEqual(work["owner"], "delegate")
        self.assertEqual(work["status"], "active")
        operation = operation_bodies(self.db, "transfer-1")[0]
        self.assertEqual(operation["status"], "confirmed_succeeded")
        self.assertEqual(operation["dispatch_state"], "finished")
        types = event_types(self.db, "transfer-1")
        self.assertIn("OwnerTransferred", types)
        self.assertIn("OperationReadmitted", types)

    def test_succeed_1_closed_with_completion(self):
        work = work_state(self.db, "succeed-1")
        self.assertEqual((work["status"], work["outcome"]), ("closed", "succeeded"))
        self.assertIn("document_digest", work["completion"])
        self.assertTrue(work["completion"]["evidence"])
        operation = operation_bodies(self.db, "succeed-1")[0]
        self.assertEqual(operation["status"], "confirmed_succeeded")

    def test_cancel_1_closed_acknowledging_the_exact_external_effect(self):
        work = work_state(self.db, "cancel-1")
        self.assertEqual((work["status"], work["outcome"]), ("closed", "cancelled"))
        operation = operation_bodies(self.db, "cancel-1")[0]
        self.assertEqual(operation["status"], "confirmed_succeeded")
        acknowledged = work["completion"]["acknowledged_operations"]
        self.assertEqual([a["operation_id"] for a in acknowledged], [operation["id"]])
        # The acknowledgement records the confirmed effect; it never reverses it.
        self.assertEqual(acknowledged[0]["external_id"], operation["external_id"])
        stored = rows(self.oa_db, "SELECT result FROM receipts WHERE key=?",
                      (operation["business_key"],))
        self.assertEqual(json.loads(stored[0][0])["status"], "accepted")


class SeedRealismTests(unittest.TestCase):
    def setUp(self):
        self.parent = tempfile.mkdtemp()
        self.db = seed_ui_demo(self.parent)
        self.oa_db = str(Path(self.db).parent / "oa.sqlite")

    def test_documents_carry_five_unique_invoice_ids(self):
        invoices = []
        for work_id in WORK_IDS:
            invoices += [i["id"] for i in work_state(self.db, work_id)["document"]["invoices"]]
        self.assertEqual(len(invoices), 5)
        self.assertEqual(len(set(invoices)), 5)

    def test_every_work_has_real_command_history(self):
        for work_id in WORK_IDS:
            types = event_types(self.db, work_id)
            self.assertEqual(types[0], "WorkCreated", work_id)
            self.assertIn("ContractBound", types, work_id)
        # Persisted command receipts exist for the whole five-work flow,
        # including the accepted cancel acknowledgement decision.
        self.assertEqual(command_receipt(self.db, "agent", "cancel-1-finalize")["decision"],
                         "accepted")

    def test_shared_external_store_holds_exactly_four_accepted(self):
        self.assertEqual(FakeOA(self.oa_db).accepted_count(), 4)


class SeedHygieneTests(unittest.TestCase):
    def test_existing_user_data_survives_a_seed(self):
        parent = tempfile.mkdtemp()
        sentinel = Path(parent) / "user-notes.txt"
        sentinel.write_text("keep me", encoding="utf-8")
        seed_ui_demo(parent)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep me")

    def test_two_runs_create_two_distinct_folders(self):
        parent = tempfile.mkdtemp()
        first, second = seed_ui_demo(parent), seed_ui_demo(parent)
        self.assertNotEqual(first, second)
        self.assertTrue(Path(first).exists() and Path(second).exists())


class UnavailableLookupTests(unittest.TestCase):
    def test_lookup_reports_no_authoritative_result_but_keeps_the_effect(self):
        parent = tempfile.mkdtemp()
        oa = FakeOA(str(Path(parent) / "oa.sqlite"))
        doc = document()
        oa.execute("key-1", doc, digest(doc))
        self.assertIsNone(UnavailableLookup(oa).lookup("key-1"))
        # The wrapped store itself still holds the committed authoritative receipt.
        self.assertEqual(oa.lookup("key-1")["status"], "accepted")


if __name__ == "__main__":
    unittest.main()
