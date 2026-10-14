"""Tests for work_runtime.inspection — the read-only store inspector."""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from work_runtime.demo import demo_grants, initialize
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


if __name__ == "__main__":
    unittest.main()
