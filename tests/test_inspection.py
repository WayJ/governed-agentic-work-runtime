"""Tests for work_runtime.inspection — the read-only store inspector."""

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from work_runtime.adapters import FakeOA
from work_runtime.demo import action, demo_grants, initialize, prerequisites, send
from work_runtime.policy import ExpensePolicy
from work_runtime.runtime import Runtime
from work_runtime.inspection import GuiReaderError, ReadOnlyInspector


class InspectorFixture(unittest.TestCase):
    """Shared helpers: build real Runtime stores, never hand-written state."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.path = str(self.dir / "runtime.sqlite")

    def store(self, work_id="demo"):
        runtime = Runtime(self.path, ExpensePolicy(), demo_grants())
        initialize(runtime, work_id=work_id)
        return runtime

    def read(self):
        with sqlite3.connect(self.path) as db:
            return db

    def raw_columns(self, table, columns, order):
        with sqlite3.connect(self.path) as db:
            return db.execute(
                "SELECT %s FROM %s ORDER BY %s" % (",".join(columns), table, order)
            ).fetchall()

    def succeeded_store(self, work_id="demo"):
        """Drive a real expense work to closed/succeeded plus one rejection."""
        runtime = self.store(work_id=work_id)
        rejected = send(runtime, work_id, "request_completion")
        assert rejected["decision"] == "rejected", rejected
        assert rejected["blockers"], "rejection fixture needs blockers"
        prerequisites(runtime, work_id=work_id)
        receipt = action(runtime, work_id=work_id)
        assert receipt["decision"] == "accepted", receipt
        runtime.dispatch(receipt["operation_id"], FakeOA(str(self.dir / "oa.sqlite")))
        accepted = send(runtime, work_id, "request_completion")
        assert accepted["decision"] == "accepted", accepted
        return runtime


class ConstructorTests(InspectorFixture):
    def test_missing_db_raises_and_never_creates(self):
        missing = str(self.dir / "absent.sqlite")
        with self.assertRaises(GuiReaderError) as caught:
            ReadOnlyInspector(missing)
        self.assertEqual(caught.exception.code, "DB_NOT_FOUND")
        self.assertFalse(os.path.exists(missing))

    def test_unreadable_db_raises(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores file permissions")
        self.store()
        os.chmod(self.path, 0o000)
        self.addCleanup(os.chmod, self.path, 0o644)
        with self.assertRaises(GuiReaderError) as caught:
            ReadOnlyInspector(self.path)
        self.assertEqual(caught.exception.code, "DB_NOT_READABLE")

    def test_text_file_is_not_a_database(self):
        Path(self.path).write_text("this is not a database", encoding="utf-8")
        with self.assertRaises(GuiReaderError) as caught:
            ReadOnlyInspector(self.path)
        self.assertEqual(caught.exception.code, "NOT_A_DATABASE")

    def test_empty_sqlite_file_is_unsupported_schema(self):
        sqlite3.connect(self.path).close()
        with self.assertRaises(GuiReaderError) as caught:
            ReadOnlyInspector(self.path)
        self.assertEqual(caught.exception.code, "UNSUPPORTED_SCHEMA")

    def test_wrong_schema_version_is_unsupported(self):
        db = sqlite3.connect(self.path)
        db.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT INTO metadata VALUES ('schema_version','2')")
        db.commit()
        db.close()
        with self.assertRaises(GuiReaderError) as caught:
            ReadOnlyInspector(self.path)
        self.assertEqual(caught.exception.code, "UNSUPPORTED_SCHEMA")

    def test_valid_store_constructs(self):
        self.store()
        inspector = ReadOnlyInspector(self.path)
        self.assertEqual(Path(inspector.path).is_absolute(), True)
        self.assertEqual(Path(inspector.path).name, "runtime.sqlite")

    def test_gui_reader_error_is_bounded_exception(self):
        self.assertTrue(issubclass(GuiReaderError, Exception))
        error = GuiReaderError("DB_NOT_FOUND", "no store at the given path")
        self.assertEqual(error.code, "DB_NOT_FOUND")
        self.assertEqual(error.message, "no store at the given path")
        self.assertIn("DB_NOT_FOUND", str(error))


class SummaryTests(InspectorFixture):
    def test_summary_counts_match_sql_reality(self):
        self.succeeded_store()
        summary = ReadOnlyInspector(self.path).summary()
        db = self.read()
        self.assertEqual(summary["source"], "runtime.sqlite")
        self.assertEqual(summary["schema_version"], "1")
        expected_counts = {
            "works": db.execute("SELECT COUNT(*) FROM works").fetchone()[0],
            "events": db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
            "operations": db.execute("SELECT COUNT(*) FROM operations").fetchone()[0],
            "evidence": db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0],
            "commands": db.execute("SELECT COUNT(*) FROM commands").fetchone()[0],
        }
        expected_counts["attempts"] = sum(
            len(json.loads(row[0])["attempts"])
            for row in db.execute("SELECT body FROM operations"))
        self.assertEqual(summary["counts"], expected_counts)
        self.assertGreater(expected_counts["attempts"], 0)

        work_statuses = {}
        closed_outcomes = {}
        for (state,) in db.execute("SELECT state FROM works"):
            work = json.loads(state)
            work_statuses[work["status"]] = work_statuses.get(work["status"], 0) + 1
            if work["status"] == "closed" and work.get("outcome") is not None:
                closed_outcomes[work["outcome"]] = (
                    closed_outcomes.get(work["outcome"], 0) + 1)
        self.assertEqual(summary["work_statuses"], work_statuses)
        self.assertEqual(summary["closed_outcomes"], closed_outcomes)

        operation_statuses = {}
        for (body,) in db.execute("SELECT body FROM operations"):
            operation = json.loads(body)
            operation_statuses[operation["status"]] = (
                operation_statuses.get(operation["status"], 0) + 1)
        self.assertEqual(summary["operation_statuses"], operation_statuses)

        evidence_statuses = {}
        for (body,) in db.execute("SELECT body FROM evidence"):
            proof = json.loads(body)
            evidence_statuses[proof["status"]] = evidence_statuses.get(proof["status"], 0) + 1
        self.assertEqual(summary["evidence_statuses"], evidence_statuses)

        command_decisions = {}
        for (receipt,) in db.execute("SELECT receipt FROM commands"):
            decision = json.loads(receipt)["decision"]
            command_decisions[decision] = command_decisions.get(decision, 0) + 1
        self.assertEqual(summary["command_decisions"], command_decisions)
        self.assertEqual(set(command_decisions), {"accepted", "rejected"})

        event_types = dict(db.execute(
            "SELECT type, COUNT(*) FROM events GROUP BY type").fetchall())
        self.assertEqual(summary["event_types"], event_types)
        self.assertIn("WorkCompleted", event_types)

    def test_summary_maps_keys_sorted(self):
        self.succeeded_store()
        summary = ReadOnlyInspector(self.path).summary()
        for key in ("work_statuses", "closed_outcomes", "operation_statuses",
                    "evidence_statuses", "command_decisions", "event_types"):
            self.assertEqual(list(summary[key]), sorted(summary[key]), key)

    def test_summary_malformed_state_raises_invalid_store(self):
        self.store()
        db = self.read()
        db.execute("UPDATE works SET state='{\"broken'")
        db.commit()
        with self.assertRaises(GuiReaderError) as caught:
            ReadOnlyInspector(self.path).summary()
        self.assertEqual(caught.exception.code, "INVALID_STORE")

    def test_summary_malformed_operation_body_raises_invalid_store(self):
        self.succeeded_store()
        db = self.read()
        db.execute("UPDATE operations SET body='not json'")
        db.commit()
        with self.assertRaises(GuiReaderError) as caught:
            ReadOnlyInspector(self.path).summary()
        self.assertEqual(caught.exception.code, "INVALID_STORE")


class ListWorksTests(InspectorFixture):
    def test_list_works_envelope_and_order(self):
        for work_id in ("b-work", "a-work", "c-work"):
            initialize(self.store(work_id=work_id), work_id=work_id)
        result = ReadOnlyInspector(self.path).list_works()
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["limit"], 100)
        self.assertEqual(result["offset"], 0)
        self.assertEqual([w["id"] for w in result["works"]], ["a-work", "b-work", "c-work"])
        first = result["works"][0]
        self.assertEqual(set(first), {"id", "status", "state_version", "owner",
                                      "outcome", "contract", "cancellation_requested"})
        self.assertEqual(first["status"], "active")
        self.assertIsInstance(first["state_version"], str)
        self.assertTrue(first["state_version"].isdigit())
        self.assertEqual(first["owner"], "agent")
        self.assertIsNone(first["outcome"])
        self.assertEqual(first["contract"], {
            "policy_id": "expense-submit", "policy_version": "demo-1",
            "goal": "expense.accepted", "revision": "1"})
        self.assertIsInstance(first["contract"]["revision"], str)
        self.assertFalse(first["cancellation_requested"])

    def test_list_works_absent_owner_contract_null(self):
        self.store()
        # Legacy reader fixture: a store written before owners existed. The
        # engine is not involved; this exercises reader tolerance only.
        state = json.loads(self.raw_columns("works", ["state"], "id")[0][0])
        del state["owner"]
        db = self.read()
        db.execute("UPDATE works SET state=?", (json.dumps(state),))
        db.commit()
        item = ReadOnlyInspector(self.path).list_works()["works"][0]
        self.assertIsNone(item["owner"])

    def test_list_works_cancellation_requested(self):
        runtime = self.store()
        send(runtime, "demo", "request_cancel", {"reason": "no longer needed"})
        item = ReadOnlyInspector(self.path).list_works()["works"][0]
        self.assertTrue(item["cancellation_requested"])

    def test_list_works_pagination_and_defaults(self):
        for work_id in ("w1", "w2", "w3"):
            initialize(self.store(work_id=work_id), work_id=work_id)
        result = ReadOnlyInspector(self.path).list_works(limit=2, offset=1)
        self.assertEqual(result["total"], 3)
        self.assertEqual([w["id"] for w in result["works"]], ["w2", "w3"])
        empty = ReadOnlyInspector(self.path).list_works(limit=2, offset=10)
        self.assertEqual(empty["works"], [])
        self.assertEqual(empty["total"], 3)

    def test_list_works_rejects_bad_limit_offset(self):
        inspector = ReadOnlyInspector(self.store().path and self.path)
        for limit, offset in ((0, 0), (201, 0), (-1, 0), ("5", 0), (None, 0),
                              (100, -1), (100, "0")):
            with self.assertRaises(GuiReaderError) as caught:
                inspector.list_works(limit=limit, offset=offset)
            self.assertEqual(caught.exception.code, "BAD_QUERY", (limit, offset))


if __name__ == "__main__":
    unittest.main()
