"""Read-only inspection of existing work stores.

Opens real schema-1 SQLite stores through ``mode=ro``/``query_only``
connections only: this module never creates, initializes, migrates or
writes a store, and it never constructs a Runtime. Loopback GUI tooling
is its only consumer; loopback is not authentication.
"""

import json
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
_LIMIT_MAX = 200


def _decimal(value, what: str) -> str:
    """Serialize a precision-bearing stored integer as a decimal string."""
    if type(value) is not int:
        raise GuiReaderError("INVALID_STORE", "stored %s is not an integer" % what)
    return str(value)


def _stored_json(text: str, what: str) -> dict:
    """Parse a stored canonical JSON column; bounded failure, never a skip."""
    try:
        value = json.loads(text)
    except (TypeError, ValueError) as error:
        raise GuiReaderError("INVALID_STORE",
                             "stored %s is not valid JSON" % what) from error
    if not isinstance(value, dict):
        raise GuiReaderError("INVALID_STORE", "stored %s is not an object" % what)
    return value


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

    def _validate_page(self, limit, offset) -> None:
        if type(limit) is not int or not 1 <= limit <= _LIMIT_MAX:
            raise GuiReaderError("BAD_QUERY", "limit must be an integer in 1..%d"
                                 % _LIMIT_MAX)
        if type(offset) is not int or offset < 0:
            raise GuiReaderError("BAD_QUERY", "offset must be a nonnegative integer")

    @staticmethod
    def _work_envelope(state: dict) -> dict:
        contract = state.get("contract")
        return {
            "id": state.get("id"),
            "status": state.get("status"),
            "state_version": _decimal(state.get("state_version"), "work state_version"),
            "owner": state.get("owner"),
            "outcome": state.get("outcome"),
            "contract": None if contract is None else {
                "policy_id": contract.get("policy_id"),
                "policy_version": contract.get("policy_version"),
                "goal": contract.get("goal"),
                "revision": _decimal(contract.get("revision"), "contract revision"),
            },
            "cancellation_requested": state.get("cancellation") is not None,
        }

    def summary(self) -> dict:
        with self._read_connection() as db:
            row = db.execute(
                "SELECT value FROM metadata WHERE key='schema_version'").fetchone()
            counts = {"attempts": 0}
            for table in ("works", "events", "operations", "evidence", "commands"):
                counts[table] = db.execute(
                    "SELECT COUNT(*) FROM %s" % table).fetchone()[0]
            work_statuses, closed_outcomes = {}, {}
            for (state_text,) in db.execute("SELECT state FROM works"):
                state = _stored_json(state_text, "work state")
                status = state.get("status")
                work_statuses[status] = work_statuses.get(status, 0) + 1
                if status == "closed" and state.get("outcome") is not None:
                    outcome = state["outcome"]
                    closed_outcomes[outcome] = closed_outcomes.get(outcome, 0) + 1
            operation_statuses = {}
            for (body,) in db.execute("SELECT body FROM operations"):
                operation = _stored_json(body, "operation body")
                counts["attempts"] += len(operation.get("attempts") or [])
                status = operation.get("status")
                operation_statuses[status] = operation_statuses.get(status, 0) + 1
            evidence_statuses = {}
            for (body,) in db.execute("SELECT body FROM evidence"):
                proof = _stored_json(body, "evidence body")
                status = proof.get("status")
                evidence_statuses[status] = evidence_statuses.get(status, 0) + 1
            command_decisions = {}
            for (receipt,) in db.execute("SELECT receipt FROM commands"):
                decision = _stored_json(receipt, "command receipt").get("decision")
                command_decisions[decision] = command_decisions.get(decision, 0) + 1
            event_types = dict(db.execute(
                "SELECT type, COUNT(*) FROM events GROUP BY type").fetchall())
        return {
            "source": os.path.basename(self.path),
            "schema_version": row[0] if row else "1",
            "counts": counts,
            "work_statuses": dict(sorted(work_statuses.items())),
            "closed_outcomes": dict(sorted(closed_outcomes.items())),
            "operation_statuses": dict(sorted(operation_statuses.items())),
            "evidence_statuses": dict(sorted(evidence_statuses.items())),
            "command_decisions": dict(sorted(command_decisions.items())),
            "event_types": dict(sorted(event_types.items())),
        }

    def list_works(self, limit: int = 100, offset: int = 0) -> dict:
        self._validate_page(limit, offset)
        with self._read_connection() as db:
            total = db.execute("SELECT COUNT(*) FROM works").fetchone()[0]
            works = []
            for work_id, state_text in db.execute(
                    "SELECT id, state FROM works ORDER BY id ASC LIMIT ? OFFSET ?",
                    (limit, offset)):
                state = _stored_json(state_text, "work state")
                item = self._work_envelope(state)
                item["id"] = work_id
                works.append(item)
        return {"total": total, "limit": limit, "offset": offset, "works": works}
