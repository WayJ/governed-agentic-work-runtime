"""Read-only inspection of existing work stores.

Opens real schema-1 SQLite stores through ``mode=ro``/``query_only``
connections only: this module never creates, initializes, migrates or
writes a store, and it never constructs a Runtime. Loopback GUI tooling
is its only consumer; loopback is not authentication.
"""

import os
import sqlite3
import urllib.parse
from contextlib import contextmanager
from pathlib import Path


class GuiReaderError(Exception):
    """Bounded reader failure: code plus message, never file contents."""

    def __init__(self, code: str, message: str):
        super().__init__("%s: %s" % (code, message))
        self.code = code
        self.message = message


_READ_TIMEOUT_SECONDS = 1.0


class ReadOnlyInspector:
    """Inspect one existing store; each call is a short read transaction."""

    def __init__(self, path: str):
        resolved = str(Path(path).resolve())
        if not os.path.exists(resolved):
            raise GuiReaderError("DB_NOT_FOUND", "no store exists at the given path")
        if not os.access(resolved, os.R_OK):
            raise GuiReaderError("DB_NOT_READABLE", "the store is not readable")
        self.path = resolved
        with self._read_connection() as db:
            self._require_schema1(db)

    @property
    def _uri(self) -> str:
        return "file:" + urllib.parse.quote(self.path, safe="/") + "?mode=ro"

    @contextmanager
    def _read_connection(self):
        db = sqlite3.connect(self._uri, uri=True, timeout=_READ_TIMEOUT_SECONDS)
        try:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN DEFERRED")
            yield db
            db.execute("COMMIT")
        finally:
            db.close()

    @staticmethod
    def _require_schema1(db) -> None:
        try:
            row = db.execute(
                "SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        except sqlite3.OperationalError as error:
            # An existing SQLite file without the metadata table is a store
            # this reader does not understand.
            raise GuiReaderError("UNSUPPORTED_SCHEMA",
                                 "the store has no readable schema version") from error
        except sqlite3.DatabaseError as error:
            raise GuiReaderError("NOT_A_DATABASE",
                                 "the file is not a readable SQLite store") from error
        if row is None or row[0] != "1":
            raise GuiReaderError("UNSUPPORTED_SCHEMA",
                                 "unsupported store schema version")
