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

from .policy import canonical


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


def _reconstructed(value, what: str) -> str:
    """Canonical Python re-serialization: exact integers, honestly not verbatim."""
    try:
        return canonical(value)
    except (TypeError, ValueError) as error:
        raise GuiReaderError("INVALID_STORE",
                             "stored %s cannot be serialized" % what) from error


def _entries(value, what: str) -> list:
    if not isinstance(value, list):
        raise GuiReaderError("INVALID_STORE", "stored %s is not a list" % what)
    for entry in value:
        if not isinstance(entry, dict):
            raise GuiReaderError("INVALID_STORE",
                                 "stored %s entry is not an object" % what)
    return value


def _operational_error(error: sqlite3.OperationalError) -> GuiReaderError:
    text = str(error).lower()
    if "locked" in text or "busy" in text:
        return GuiReaderError("DB_BUSY", "the store is locked by another writer")
    if "unable to open" in text:
        return GuiReaderError("DB_NOT_READABLE", "the store cannot be opened")
    return GuiReaderError("INTERNAL", "the store could not be read")


def _database_error(error: sqlite3.DatabaseError) -> GuiReaderError:
    text = str(error).lower()
    if "not a database" in text or "malformed" in text:
        return GuiReaderError("NOT_A_DATABASE", "the file is not a readable SQLite store")
    return GuiReaderError("INTERNAL", "the store could not be read")


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
        except sqlite3.OperationalError as error:
            raise _operational_error(error) from error
        except sqlite3.DatabaseError as error:
            raise _database_error(error) from error
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

    def events(self, work_id: str, after: int = 0, limit: int = 100) -> dict:
        if not isinstance(work_id, str) or not work_id:
            raise GuiReaderError("BAD_QUERY", "work id must be a nonempty string")
        if type(after) is not int or after < 0:
            raise GuiReaderError("BAD_QUERY", "after must be a nonnegative integer")
        self._validate_page(limit, 0)
        with self._read_connection() as db:
            if db.execute("SELECT 1 FROM works WHERE id=?",
                          (work_id,)).fetchone() is None:
                raise GuiReaderError("UNKNOWN_WORK", "no work with the given id")
            rows = db.execute(
                "SELECT seq, work_id, version, type, body FROM events "
                "WHERE work_id=? AND seq>? ORDER BY seq LIMIT ?",
                (work_id, after, limit + 1)).fetchall()
        has_more = len(rows) > limit
        events = []
        for seq, stored_work_id, version, type_, body in rows[:limit]:
            _stored_json(body, "event body")  # bounded failure, never a silent skip
            events.append({
                "seq": _decimal(seq, "event seq"),
                "work_id": stored_work_id,
                "version": _decimal(version, "event version"),
                "type": type_,
                "body_raw": body,
            })
        return {"events": events,
                "next_after": events[-1]["seq"] if events else str(after),
                "has_more": has_more}

    def work_detail(self, work_id: str) -> dict:
        if not isinstance(work_id, str) or not work_id:
            raise GuiReaderError("BAD_QUERY", "work id must be a nonempty string")
        with self._read_connection() as db:
            row = db.execute("SELECT state FROM works WHERE id=?",
                             (work_id,)).fetchone()
            if row is None:
                raise GuiReaderError("UNKNOWN_WORK", "no work with the given id")
            state_text = row[0]
            state = _stored_json(state_text, "work state")
            work = self._work_envelope(state)
            waits = []
            for wait in _entries(state.get("waits", []), "waits"):
                waits.append({
                    "id": wait.get("id"),
                    "requirement_id": wait.get("requirement_id"),
                    "owner": wait.get("owner"),
                    "status": wait.get("status"),
                    "deadline": _decimal(wait.get("deadline"), "wait deadline"),
                })
            requirements = []
            for requirement in _entries(state.get("requirements", []),
                                         "requirements"):
                requirements.append({
                    "id": requirement.get("id"),
                    "rule_id": requirement.get("rule_id"),
                    "subject": requirement.get("subject"),
                    "applicability": requirement.get("applicability"),
                    "fulfillment": requirement.get("fulfillment"),
                    "explanation": requirement.get("explanation"),
                })
            work.update({
                "plan_revision": _decimal(state.get("plan_revision"),
                                          "plan revision"),
                "document_revision": _decimal(state.get("document_revision"),
                                              "document revision"),
                "document_digest": state.get("document_digest"),
                "waits": waits,
                "cancellation": state.get("cancellation"),
                "requirements": requirements,
                "state_raw": state_text,
                "document_raw": _reconstructed(state.get("document"), "document"),
                "plan_raw": _reconstructed(state.get("plan"), "plan"),
                "completion_raw": (
                    None if state.get("completion") is None
                    else _reconstructed(state["completion"], "completion")),
            })
            evidence = []
            for source, event_id, body in db.execute(
                    "SELECT source, event_id, body FROM evidence "
                    "WHERE work_id=? ORDER BY source, event_id", (work_id,)):
                proof = _stored_json(body, "evidence body")
                evidence.append({
                    "source": source,
                    "event_id": event_id,
                    "kind": proof.get("kind"),
                    "status": proof.get("status"),
                    "body_raw": body,
                    "data_raw": _reconstructed(proof.get("data"), "evidence data"),
                })
            operations = []
            for (body,) in db.execute(
                    "SELECT body FROM operations WHERE work_id=? ORDER BY id",
                    (work_id,)):
                operation = _stored_json(body, "operation body")
                operations.append({
                    "id": operation.get("id"),
                    "business_key": operation.get("business_key"),
                    "capability": operation.get("capability"),
                    "actor": operation.get("actor"),
                    "status": operation.get("status"),
                    "dispatch_state": operation.get("dispatch_state"),
                    "reason": operation.get("reason"),
                    "attempts": [{"id": attempt.get("id"), "status": attempt.get("status")}
                                 for attempt in _entries(operation.get("attempts", []),
                                                         "operation attempts")],
                    "external_id": operation.get("external_id"),
                    "document_digest": operation.get("document_digest"),
                    "plan_revision": _decimal(operation.get("plan_revision"),
                                              "operation plan revision"),
                    "contract_revision": _decimal(operation.get("contract_revision"),
                                                  "operation contract revision"),
                    "document_raw": _reconstructed(operation.get("document"),
                                                   "operation document"),
                    "body_raw": body,
                })
            commands = []
            for actor, command_id, receipt_text in db.execute(
                    "SELECT actor, id, receipt FROM commands WHERE work_id=?",
                    (work_id,)):
                receipt = _stored_json(receipt_text, "command receipt")
                result_version = receipt.get("result_state_version")
                observed_version = receipt.get("observed_state_version")
                commands.append({
                    "actor": actor,
                    "id": command_id,
                    "decision": receipt.get("decision"),
                    "code": receipt.get("code"),
                    "result_state_version": (
                        None if result_version is None
                        else _decimal(result_version, "receipt result_state_version")),
                    "observed_state_version": (
                        None if observed_version is None
                        else _decimal(observed_version, "receipt observed_state_version")),
                    "receipt_raw": receipt_text,
                    "blockers_raw": (
                        None if "blockers" not in receipt
                        else _reconstructed(receipt["blockers"], "receipt blockers")),
                    "_sort": (result_version if type(result_version) is int
                              else observed_version if type(observed_version) is int
                              else -1, actor, command_id),
                })
            commands.sort(key=lambda command: command.pop("_sort"))
        return {"work": work, "evidence": evidence, "operations": operations,
                "commands": commands}
