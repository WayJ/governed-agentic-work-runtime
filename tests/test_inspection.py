"""Tests for work_runtime.inspection — the read-only store inspector."""

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from work_runtime.adapters import FakeOA
from work_runtime.demo import action, demo_grants, document, initialize, prerequisites, send
from work_runtime.policy import ExpensePolicy, canonical
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

    def succeeded_store(self, work_id="demo", amount=120000, path=None):
        """Drive a real expense work to closed/succeeded plus one rejection."""
        runtime = Runtime(path or self.path, ExpensePolicy(), demo_grants())
        initialize(runtime, work_id=work_id, doc=document(amount=amount))
        rejected = send(runtime, work_id, "request_completion")
        assert rejected["decision"] == "rejected", rejected
        assert rejected["blockers"], "rejection fixture needs blockers"
        prerequisites(runtime, work_id=work_id)
        send(runtime, work_id, "register_wait", {
            "requirement_id": "E05:EXP-001",
            "deadline": 2000000000, "owner": "finance"})
        receipt = action(runtime, work_id=work_id)
        assert receipt["decision"] == "accepted", receipt
        runtime.dispatch(receipt["operation_id"], FakeOA(str(self.dir / "oa.sqlite")))
        accepted = send(runtime, work_id, "request_completion")
        assert accepted["decision"] == "accepted", accepted
        return runtime

    def cancelled_store(self, work_id="demo"):
        """Drive a real work to closed/cancelled with an acknowledged effect."""
        runtime = self.store(work_id=work_id)
        prerequisites(runtime, work_id=work_id)
        receipt = action(runtime, work_id=work_id)
        operation_id = receipt["operation_id"]
        runtime.dispatch(operation_id, FakeOA(str(self.dir / "oa.sqlite")))
        send(runtime, work_id, "request_cancel", {"reason": "business closed"})
        final = send(runtime, work_id, "finalize_cancel",
                     {"acknowledged_operations": [operation_id]})
        assert final["decision"] == "accepted", final
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


class WorkDetailTests(InspectorFixture):
    def test_work_detail_full_shape(self):
        self.succeeded_store(amount=10000000000000001)
        detail = ReadOnlyInspector(self.path).work_detail("demo")
        work = detail["work"]
        self.assertEqual(set(work), {
            "id", "status", "state_version", "owner", "outcome", "contract",
            "cancellation_requested", "plan_revision", "document_revision",
            "document_digest", "waits", "cancellation", "requirements",
            "state_raw", "document_raw", "plan_raw", "completion_raw"})
        self.assertEqual(work["status"], "closed")
        self.assertEqual(work["outcome"], "succeeded")
        self.assertIsNone(work["cancellation"])
        self.assertIsInstance(work["plan_revision"], str)
        self.assertIsInstance(work["document_revision"], str)
        (state_column,) = self.raw_columns("works", ["state"], "id")[0]
        self.assertEqual(work["state_raw"], state_column)
        # Huge integers survive exactly in raw text; JS Number would round them.
        self.assertIn("10000000000000001", work["document_raw"])
        self.assertIn("10000000000000001", work["state_raw"])
        state = json.loads(state_column)
        self.assertEqual(work["document_raw"], canonical(state["document"]))
        self.assertEqual(work["plan_raw"], canonical(state["plan"]))
        self.assertEqual(work["completion_raw"], canonical(state["completion"]))
        self.assertEqual(len(work["waits"]), 1)
        wait = work["waits"][0]
        self.assertEqual(set(wait),
                         {"id", "requirement_id", "owner", "status", "deadline"})
        self.assertEqual(wait["requirement_id"], "E05:EXP-001")
        self.assertEqual(wait["deadline"], "2000000000")
        self.assertEqual(wait["status"], "triggered")
        requirements = {r["id"]: r for r in work["requirements"]}
        e05 = requirements["E05:EXP-001"]
        self.assertEqual(set(e05), {"id", "rule_id", "subject", "applicability",
                                    "fulfillment", "explanation"})
        self.assertEqual(e05["rule_id"], "E05")
        self.assertEqual(e05["subject"], "EXP-001")
        self.assertEqual(e05["fulfillment"], "satisfied")

        evidence = detail["evidence"]
        self.assertEqual(len(evidence), 5)
        accepted = [e for e in evidence if e["kind"] == "accepted"][0]
        self.assertEqual(set(accepted), {"source", "event_id", "kind", "status",
                                         "body_raw", "data_raw"})
        self.assertEqual(accepted["source"], "oa")
        self.assertEqual(accepted["status"], "verified")
        evidence_columns = {(row[0], row[1]): row[2] for row in
                            self.raw_columns("evidence", ["source", "event_id", "body"],
                                             "source, event_id")}
        for proof in evidence:
            self.assertEqual(proof["body_raw"],
                             evidence_columns[(proof["source"], proof["event_id"])])
        self.assertEqual(accepted["data_raw"],
                         canonical(json.loads(accepted["body_raw"])["data"]))

        operations = detail["operations"]
        self.assertEqual(len(operations), 1)
        operation = operations[0]
        self.assertEqual(set(operation), {
            "id", "business_key", "capability", "actor", "status", "dispatch_state",
            "reason", "attempts", "external_id", "document_digest", "plan_revision",
            "contract_revision", "document_raw", "body_raw"})
        self.assertEqual(operation["status"], "confirmed_succeeded")
        self.assertEqual(operation["dispatch_state"], "finished")
        self.assertIsNone(operation["reason"])
        self.assertEqual(len(operation["attempts"]), 1)
        self.assertEqual(set(operation["attempts"][0]), {"id", "status"})
        self.assertEqual(operation["attempts"][0]["status"], "confirmed_succeeded")
        self.assertIsInstance(operation["external_id"], str)
        self.assertIsInstance(operation["plan_revision"], str)
        self.assertIsInstance(operation["contract_revision"], str)
        self.assertIn("10000000000000001", operation["document_raw"])
        (operation_body,) = self.raw_columns("operations", ["body"], "id")[0]
        self.assertEqual(operation["body_raw"], operation_body)

    def test_work_detail_commands_sorted_with_raws(self):
        self.succeeded_store()
        rows = self.raw_columns("commands", ["actor", "id", "receipt"], "actor, id")
        expected = []
        for actor, command_id, receipt_text in rows:
            receipt = json.loads(receipt_text)
            version = receipt.get("result_state_version")
            if version is None:
                version = receipt.get("observed_state_version")
            expected.append((version if type(version) is int else -1,
                             actor, command_id, receipt_text))
        expected.sort(key=lambda item: item[:3])
        commands = ReadOnlyInspector(self.path).work_detail("demo")["commands"]
        self.assertEqual([c["id"] for c in commands], [item[2] for item in expected])
        self.assertEqual([c["actor"] for c in commands], [item[1] for item in expected])
        rejected_seen = accepted_seen = 0
        for command, (_, _, _, receipt_text) in zip(commands, expected):
            receipt = json.loads(receipt_text)
            self.assertEqual(set(command), {
                "actor", "id", "decision", "code", "result_state_version",
                "observed_state_version", "receipt_raw", "blockers_raw"})
            self.assertEqual(command["receipt_raw"], receipt_text)
            self.assertEqual(command["decision"], receipt["decision"])
            if receipt["decision"] == "rejected":
                rejected_seen += 1
                self.assertEqual(command["code"], receipt["code"])
                self.assertIsInstance(command["observed_state_version"], str)
                self.assertIsNone(command["result_state_version"])
                self.assertEqual(command["blockers_raw"],
                                 canonical(receipt.get("blockers")))
            else:
                accepted_seen += 1
                self.assertIsNone(command["code"])
                self.assertIsInstance(command["result_state_version"], str)
                self.assertIsNone(command["blockers_raw"])
        self.assertGreater(rejected_seen, 0)
        self.assertGreater(accepted_seen, 0)

    def test_work_detail_cancelled_work(self):
        self.cancelled_store()
        work = ReadOnlyInspector(self.path).work_detail("demo")["work"]
        self.assertEqual(work["status"], "closed")
        self.assertEqual(work["outcome"], "cancelled")
        self.assertTrue(work["cancellation_requested"])
        self.assertEqual(work["cancellation"],
                         {"reason": "business closed", "requested_by": "agent"})
        completion = json.loads(work["completion_raw"])
        self.assertEqual(set(completion), {"cancellation", "acknowledged_operations",
                                           "operation_dispositions"})
        self.assertEqual(completion["cancellation"], work["cancellation"])
        self.assertEqual(len(completion["acknowledged_operations"]), 1)
        self.assertEqual(set(completion["acknowledged_operations"][0]),
                         {"operation_id", "external_id"})
        self.assertEqual([d["status"] for d in completion["operation_dispositions"]],
                         ["confirmed_succeeded"])

    def test_unicode_slash_quote_id_roundtrip(self):
        work_id = '订单/"A"&1'
        self.succeeded_store(work_id=work_id)
        inspector = ReadOnlyInspector(self.path)
        self.assertIn(work_id, [w["id"] for w in inspector.list_works()["works"]])
        detail = inspector.work_detail(work_id)
        self.assertEqual(detail["work"]["id"], work_id)

    def test_work_detail_unknown_raises(self):
        self.store()
        with self.assertRaises(GuiReaderError) as caught:
            ReadOnlyInspector(self.path).work_detail("no-such-work")
        self.assertEqual(caught.exception.code, "UNKNOWN_WORK")

    def test_work_detail_malformed_records_raise_invalid_store(self):
        self.succeeded_store()
        db = self.read()
        db.execute("UPDATE evidence SET body='{bad'")
        db.commit()
        with self.assertRaises(GuiReaderError) as caught:
            ReadOnlyInspector(self.path).work_detail("demo")
        self.assertEqual(caught.exception.code, "INVALID_STORE")
        other = str(self.dir / "second.sqlite")
        self.succeeded_store(path=other)
        db = sqlite3.connect(other)
        db.execute("UPDATE commands SET receipt='[1]'")
        db.commit()
        with self.assertRaises(GuiReaderError) as caught:
            ReadOnlyInspector(other).work_detail("demo")
        self.assertEqual(caught.exception.code, "INVALID_STORE")


class EventsTests(InspectorFixture):
    def many_events(self, count=210):
        runtime = self.store()
        plan = {"steps": ["verify"], "open_requirements": [], "replan_when": []}
        for _ in range(count):
            send(runtime, "demo", "revise_plan", plan)
        return runtime

    def all_events(self):
        return self.raw_columns("events", ["seq", "version", "type", "body"], "seq")

    def test_events_keyset_paging(self):
        self.many_events()
        inspector = ReadOnlyInspector(self.path)
        stored = self.all_events()
        self.assertGreater(len(stored), 200)
        collected, after, has_more = [], 0, True
        while has_more:
            page = inspector.events("demo", after=after, limit=3)
            self.assertEqual(len(page["events"]),
                             3 if page["has_more"] else len(page["events"]))
            self.assertIsInstance(page["next_after"], str)
            collected.extend(page["events"])
            self.assertEqual(page["next_after"],
                             page["events"][-1]["seq"] if page["events"]
                             else str(after))
            after = int(page["next_after"])
            has_more = page["has_more"]
        self.assertEqual([int(e["seq"]) for e in collected],
                         [row[0] for row in stored])
        self.assertEqual([e["type"] for e in collected], [row[2] for row in stored])
        self.assertFalse(has_more)
        # Empty tail page keeps the cursor unchanged.
        tail = inspector.events("demo", after=after, limit=3)
        self.assertEqual(tail["events"], [])
        self.assertFalse(tail["has_more"])
        self.assertEqual(tail["next_after"], str(after))

    def test_events_envelope_fields(self):
        self.many_events()
        page = ReadOnlyInspector(self.path).events("demo", after=0, limit=2)
        event = page["events"][0]
        self.assertEqual(set(event), {"seq", "work_id", "version", "type", "body_raw"})
        self.assertIsInstance(event["seq"], str)
        self.assertIsInstance(event["version"], str)
        self.assertEqual(event["work_id"], "demo")
        (seq, version, type_, body) = self.all_events()[0]
        self.assertEqual(event["seq"], str(seq))
        self.assertEqual(event["version"], str(version))
        self.assertEqual(event["type"], type_)
        self.assertEqual(event["body_raw"], body)

    def test_events_default_limit_is_100(self):
        self.many_events()
        page = ReadOnlyInspector(self.path).events("demo")
        self.assertEqual(len(page["events"]), 100)
        self.assertTrue(page["has_more"])

    def test_events_validation_and_unknown_work(self):
        inspector = ReadOnlyInspector(self.store().path and self.path)
        for after, limit in ((-1, 10), ("0", 10), (0, 0), (0, 201), (0, "10")):
            with self.assertRaises(GuiReaderError) as caught:
                inspector.events("demo", after=after, limit=limit)
            self.assertEqual(caught.exception.code, "BAD_QUERY", (after, limit))
        with self.assertRaises(GuiReaderError) as caught:
            inspector.events("no-such-work")
        self.assertEqual(caught.exception.code, "UNKNOWN_WORK")

    def test_events_version_must_be_integer(self):
        self.store()
        db = self.read()
        db.execute("INSERT INTO events(work_id, version, type, body) "
                   "VALUES ('demo', 'abc', 'X', '{}')")
        db.commit()
        with self.assertRaises(GuiReaderError) as caught:
            ReadOnlyInspector(self.path).events("demo")
        self.assertEqual(caught.exception.code, "INVALID_STORE")

    def test_events_malformed_body_raises_invalid_store(self):
        self.store()
        db = self.read()
        db.execute("INSERT INTO events(work_id, version, type, body) "
                   "VALUES ('demo', 1, 'X', '{bad')")
        db.commit()
        with self.assertRaises(GuiReaderError) as caught:
            ReadOnlyInspector(self.path).events("demo")
        self.assertEqual(caught.exception.code, "INVALID_STORE")


class FailureModeTests(InspectorFixture):
    def test_malformed_json_in_each_table_raises_invalid_store(self):
        corruptions = [
            ("UPDATE works SET state='{\"broken'", "list_works"),
            ("UPDATE works SET state='[1,2]'", "work_detail"),
            ("UPDATE operations SET body='nope'", "summary"),
            ("UPDATE evidence SET body='nope'", "work_detail"),
            ("UPDATE commands SET receipt='nope'", "work_detail"),
        ]
        for index, (statement, method) in enumerate(corruptions):
            with self.subTest(statement=statement, method=method):
                path = str(self.dir / ("corrupt-%d.sqlite" % index))
                self.succeeded_store(path=path)
                db = sqlite3.connect(path)
                db.execute(statement)
                db.commit()
                inspector = ReadOnlyInspector(path)
                with self.assertRaises(GuiReaderError) as caught:
                    if method == "list_works":
                        inspector.list_works()
                    elif method == "work_detail":
                        inspector.work_detail("demo")
                    else:
                        inspector.summary()
                self.assertEqual(caught.exception.code, "INVALID_STORE")

    def test_state_version_must_be_integer(self):
        self.store()
        state = json.loads(self.raw_columns("works", ["state"], "id")[0][0])
        state["state_version"] = "seven"
        db = self.read()
        db.execute("UPDATE works SET state=?", (canonical(state),))
        db.commit()
        inspector = ReadOnlyInspector(self.path)
        for reader in (inspector.list_works, lambda: inspector.work_detail("demo")):
            with self.assertRaises(GuiReaderError) as caught:
                reader()
            self.assertEqual(caught.exception.code, "INVALID_STORE")

    def test_db_busy_on_exclusive_lock(self):
        self.succeeded_store()
        inspector = ReadOnlyInspector(self.path)
        writer = sqlite3.connect(self.path)
        writer.execute("PRAGMA journal_mode=DELETE")
        writer.execute("BEGIN EXCLUSIVE")
        try:
            with self.assertRaises(GuiReaderError) as caught:
                inspector.summary()
            self.assertEqual(caught.exception.code, "DB_BUSY")
        finally:
            writer.rollback()
            writer.close()
        self.assertEqual(inspector.summary()["counts"]["works"], 1)

    def test_wal_reader_sees_commits_during_immediate_writer(self):
        runtime = self.store()
        inspector = ReadOnlyInspector(self.path)
        before = inspector.summary()["counts"]["events"]
        writer = sqlite3.connect(self.path)
        writer.execute("BEGIN IMMEDIATE")
        try:
            during = inspector.summary()["counts"]["events"]
            self.assertEqual(during, before)
        finally:
            writer.rollback()
            writer.close()
        send(runtime, "demo", "revise_plan",
             {"steps": ["verify"], "open_requirements": [], "replan_when": []})
        writer = sqlite3.connect(self.path)
        writer.execute("BEGIN IMMEDIATE")
        try:
            after = inspector.summary()["counts"]["events"]
            self.assertEqual(after, before + 1)
        finally:
            writer.rollback()
            writer.close()

    def test_full_read_pass_writes_nothing(self):
        self.succeeded_store(work_id="w-a")
        self.succeeded_store(work_id="w-b", path=str(self.dir / "unused.sqlite"))
        # A second work in the main store: fresh runtime on the same path.
        runtime = Runtime(self.path, ExpensePolicy(), demo_grants())
        initialize(runtime, work_id="w-b")
        inspector = ReadOnlyInspector(self.path)

        def snapshot():
            with sqlite3.connect(self.path) as db:
                return {
                    table: db.execute(
                        "SELECT * FROM %s ORDER BY 1" % table).fetchall()
                    for table in ("works", "commands", "evidence", "operations",
                                  "events", "metadata")
                }

        before = snapshot()
        inspector.summary()
        listing = inspector.list_works()
        for item in listing["works"]:
            inspector.work_detail(item["id"])
            page = inspector.events(item["id"])
            self.assertIsInstance(page["next_after"], str)
        self.assertEqual(snapshot(), before)

    def test_read_only_file_permissions(self):
        self.succeeded_store()
        os.chmod(self.path, 0o444)
        self.addCleanup(os.chmod, self.path, 0o644)
        inspector = ReadOnlyInspector(self.path)
        self.assertEqual(inspector.summary()["counts"]["works"], 1)
        self.assertEqual(inspector.work_detail("demo")["work"]["id"], "demo")


if __name__ == "__main__":
    unittest.main()
