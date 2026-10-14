"""Real-SQLite tests for the third-party-style rehearsal queue adapter.

Run from the repository root:

    python3 -m unittest examples.rehearsal.test_queue_adapter -v

The suite adopts the reusable conformance mixin from the public fixture
``tests/adapter_conformance.py`` and adds domain tests that inspect the real
SQLite database file through independent read-only connections — no mocks,
internal counters or patched internals anywhere.
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
for _path in (HERE, REPO_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from queue_adapter import SqliteQueuePublisher  # noqa: E402
from tests.adapter_conformance import AdapterConformanceMixin  # noqa: E402
from work_runtime import ExpensePolicy, Runtime  # noqa: E402
from work_runtime.adapters import FakeOA  # noqa: E402
from work_runtime.demo import action, demo_grants, initialize, prerequisites, send  # noqa: E402
from work_runtime.policy import digest  # noqa: E402

SAMPLE_DOCUMENT = {"id": "DOC-1", "title": "t", "body": "b", "requires_review": True}


def readonly_connection(database):
    """An independent read-only connection to the adapter's external store."""
    return sqlite3.connect("file:%s?mode=ro" % database, uri=True)


def queue_row_count(database):
    """External effects committed so far: rows in the persistent queue."""
    connection = readonly_connection(database)
    try:
        return connection.execute("SELECT COUNT(*) FROM queue").fetchone()[0]
    finally:
        connection.close()


class TempDatabaseTestCase(unittest.TestCase):
    """Fresh disposable SQLite store per test (the tests mutate the store)."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.database = str(Path(self._temp.name) / "queue.sqlite")

    def make_adapter(self):
        return SqliteQueuePublisher(self.database)


class QueueAdapterConformanceTests(AdapterConformanceMixin, TempDatabaseTestCase):
    """The reusable public conformance suite against the queue adapter."""

    def make_adapter(self):
        # Override in the concrete class: the mixin's stub precedes
        # TempDatabaseTestCase in the MRO and would shadow it.
        return SqliteQueuePublisher(self.database)

    def sample_document(self):
        return dict(SAMPLE_DOCUMENT)

    def changed_document(self):
        changed = dict(SAMPLE_DOCUMENT)
        changed["title"] = "t2"
        return changed

    def effect_count(self, adapter):
        return queue_row_count(adapter.database)


class RestartStabilityTests(TempDatabaseTestCase):
    """Receipts and effects are durable in the database file, not memory."""

    def test_same_key_replay_after_restart_returns_identical_receipt_with_one_effect(self):
        adapter = self.make_adapter()
        receipt = adapter.execute("publish-1", SAMPLE_DOCUMENT, digest(SAMPLE_DOCUMENT))
        restarted = self.make_adapter()
        replay = restarted.execute("publish-1", SAMPLE_DOCUMENT, digest(SAMPLE_DOCUMENT))
        self.assertEqual(replay, receipt)
        self.assertEqual(restarted.lookup("publish-1"), receipt)
        self.assertEqual(queue_row_count(self.database), 1)

    def test_changed_content_after_restart_is_rejected_without_new_effect(self):
        adapter = self.make_adapter()
        adapter.execute("publish-1", SAMPLE_DOCUMENT, digest(SAMPLE_DOCUMENT))
        changed = dict(SAMPLE_DOCUMENT)
        changed["title"] = "t2"
        restarted = self.make_adapter()
        with self.assertRaises(ValueError):
            restarted.execute("publish-1", changed, digest(changed))
        self.assertEqual(queue_row_count(self.database), 1)
        self.assertEqual(restarted.lookup("publish-1")["digest"], digest(SAMPLE_DOCUMENT))


class QueueContentTests(TempDatabaseTestCase):
    """The external effect is a real queue row with the published content."""

    def test_queue_row_stores_payload_digest_and_external_id(self):
        adapter = self.make_adapter()
        receipt = adapter.execute("publish-1", SAMPLE_DOCUMENT, digest(SAMPLE_DOCUMENT))
        connection = readonly_connection(self.database)
        try:
            row = connection.execute(
                "SELECT key_hash, external_id, content_digest, payload_json FROM queue"
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNotNone(row)
        self.assertNotEqual(row[0], "publish-1")
        self.assertEqual(row[1], receipt["external_id"])
        self.assertTrue(row[1].startswith("QUEUE-"))
        self.assertEqual(row[2], digest(SAMPLE_DOCUMENT))
        self.assertEqual(json.loads(row[3]), SAMPLE_DOCUMENT)

    def test_different_key_same_content_commits_a_second_effect(self):
        adapter = self.make_adapter()
        first = adapter.execute("publish-1", SAMPLE_DOCUMENT, digest(SAMPLE_DOCUMENT))
        second = adapter.execute("publish-2", SAMPLE_DOCUMENT, digest(SAMPLE_DOCUMENT))
        self.assertNotEqual(first["external_id"], second["external_id"])
        self.assertEqual(queue_row_count(self.database), 2)

    def test_store_is_a_real_sqlite_file_on_disk(self):
        adapter = self.make_adapter()
        adapter.execute("publish-1", SAMPLE_DOCUMENT, digest(SAMPLE_DOCUMENT))
        self.assertTrue(os.path.isfile(self.database))
        with open(self.database, "rb") as handle:
            self.assertEqual(handle.read(16), b"SQLite format 3\x00")


class ArgumentGateTests(TempDatabaseTestCase):
    """Bounded rejection before any external effect."""

    def test_invalid_keys_are_rejected_before_any_effect(self):
        adapter = self.make_adapter()
        for key in ("", None, 7):
            with self.assertRaises(ValueError):
                adapter.execute(key, SAMPLE_DOCUMENT, digest(SAMPLE_DOCUMENT))
            with self.assertRaises(ValueError):
                adapter.lookup(key)
        self.assertEqual(queue_row_count(self.database), 0)

    def test_invalid_digest_argument_is_rejected_before_any_effect(self):
        adapter = self.make_adapter()
        for content_digest in ("", None):
            with self.assertRaises(ValueError):
                adapter.execute("publish-1", SAMPLE_DOCUMENT, content_digest)
        self.assertEqual(queue_row_count(self.database), 0)

    def test_non_json_native_document_is_rejected_before_any_effect(self):
        adapter = self.make_adapter()
        with self.assertRaises(ValueError):
            adapter.execute("publish-1", {"tags": {"a", "b"}}, "digest-opaque")
        self.assertEqual(queue_row_count(self.database), 0)


class RuntimeCapabilityGateTests(TempDatabaseTestCase):
    """Documented Runtime treatment of a declared contract (guide Part A).

    The queue adapter declares only ``content.publish``; dispatching an
    ``expense.submit`` operation against it must hold the operation with zero
    external effects (ADAPTER_ACTION_UNSUPPORTED), and re-dispatching with a
    compatible adapter runs normally (docs/adapter-contract.md). Uses only the
    local API documented in README.md.
    """

    def test_unsupported_capability_held_then_compatible_adapter_completes(self):
        work_database = str(Path(self._temp.name) / "work.sqlite")
        oa_database = str(Path(self._temp.name) / "oa.sqlite")
        runtime = Runtime(work_database, ExpensePolicy(), demo_grants())
        initialize(runtime, work_id="rehearsal-1")
        prerequisites(runtime, work_id="rehearsal-1")
        proposal = action(runtime, work_id="rehearsal-1")
        self.assertEqual(proposal["decision"], "accepted")
        operation_id = proposal["operation_id"]

        queue = SqliteQueuePublisher(self.database)
        runtime.dispatch(operation_id, queue)  # held: capability not declared
        self.assertEqual(queue_row_count(self.database), 0)

        runtime.dispatch(operation_id, FakeOA(oa_database))  # compatible adapter
        completion = send(runtime, "rehearsal-1", "request_completion")
        self.assertEqual(completion["decision"], "accepted")
        self.assertEqual(queue_row_count(self.database), 0)


if __name__ == "__main__":
    unittest.main()
