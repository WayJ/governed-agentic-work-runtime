"""Persistent fake OA with externally enforced invoice uniqueness."""

import json
import sqlite3
import uuid
from pathlib import Path

from .adapter_contract import AdapterContract
from .policy import canonical, digest


class FakeOA:
    """A separate database models an external service, surviving worker crashes."""

    # Declared assertions for trusted local configuration, not a remote guarantee.
    # supports_action_context opts into explicit action/link execution (S10 D44).
    contract = AdapterContract(
        actions=("expense.submit", "expense.withdraw"),
        idempotency_scope="adapter-store:key",
        retention="lifetime-of-store",
        lookup_consistency="authoritative-by-key",
        uniqueness=("invoice.id", "withdrawal.original_external_id"),
        supports_action_context=True)

    def __init__(self, path: str, timeout_after_commit: bool = False):
        self.path = str(path)
        self.timeout_after_commit = timeout_after_commit
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15)
        try:
            # Additive migration (S10 D46): the probe and every ALTER/CREATE run
            # inside one BEGIN IMMEDIATE transaction so concurrent first-open
            # serializes instead of racing duplicate-column errors.
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS receipts (
                key TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS invoices (
                invoice_id TEXT PRIMARY KEY, external_id TEXT NOT NULL)""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(receipts)")}
            if "action" not in columns:
                db.execute("ALTER TABLE receipts ADD COLUMN action TEXT")
            if "link_digest" not in columns:
                db.execute("ALTER TABLE receipts ADD COLUMN link_digest TEXT")
            db.execute("""CREATE TABLE IF NOT EXISTS withdrawals (
                original_external_id TEXT PRIMARY KEY, external_id TEXT NOT NULL,
                key TEXT NOT NULL, digest TEXT NOT NULL)""")
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def execute(self, key: str, document: dict, content_digest: str, *,
                action=None, compensates=None) -> dict:
        if digest(document) != content_digest:
            raise ValueError("Content digest does not match document")
        if action is None:
            # FakeOA-side normalization for its own legacy direct callers; not a
            # protocol rule (legacy adapters are simply never called with kwargs).
            action = "expense.submit"
        if action not in ("expense.submit", "expense.withdraw"):
            raise ValueError("Unknown action: " + str(action))
        link_digest = None
        if action == "expense.withdraw":
            if not self._valid_link(compensates):
                raise ValueError("expense.withdraw requires a compensates link with "
                                 "operation_id, external_id and capability")
            link_digest = digest(compensates)
        elif compensates is not None:
            raise ValueError("Forward execution must not carry a compensates link")
        db = sqlite3.connect(self.path, timeout=15)
        try:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT digest,action,link_digest,result FROM receipts WHERE key=?",
                (key,)).fetchone()
            if old:
                # Replay requires digest, normalized action and link fingerprint
                # to match (legacy NULL action reads back as the forward action;
                # legacy NULL link digest means no compensation link).
                if (old[0] != content_digest
                        or (old[1] or "expense.submit") != action
                        or old[2] != link_digest):
                    raise ValueError("Idempotency key reused with different content")
                result = json.loads(old[3])
            elif action == "expense.withdraw":
                result = self._execute_withdrawal(db, key, content_digest,
                                                  compensates, link_digest)
            else:
                result = self._execute_forward(db, key, content_digest,
                                               document, action, link_digest)
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
        if self.timeout_after_commit:
            raise TimeoutError("Response lost after OA committed")
        return result

    @staticmethod
    def _valid_link(compensates) -> bool:
        return (isinstance(compensates, dict)
                and set(compensates) == {"operation_id", "external_id", "capability"}
                and all(isinstance(compensates[field], str) and compensates[field]
                        for field in compensates))

    def _execute_forward(self, db, key, content_digest, document, action, link_digest):
        duplicate = any(db.execute("SELECT 1 FROM invoices WHERE invoice_id=?",
                                   (i["id"],)).fetchone() for i in document["invoices"])
        result = {"status": "rejected" if duplicate else "accepted",
                  "external_id": "OA-" + uuid.uuid4().hex[:12], "digest": content_digest}
        db.execute("INSERT INTO receipts (key,digest,result,action,link_digest) "
                   "VALUES (?,?,?,?,?)",
                   (key, content_digest, canonical(result), action, link_digest))
        if not duplicate:
            for invoice in document["invoices"]:
                db.execute("INSERT INTO invoices VALUES (?,?)",
                           (invoice["id"], result["external_id"]))
        return result

    def _execute_withdrawal(self, db, key, content_digest, compensates, link_digest):
        """One withdrawal effect per original; receipts stay the call surface.

        Known absence of the original is an authoritative stored business
        rejection (ORIGINAL_ABSENT); only a genuine store failure is left
        uncertain (the caller sees the exception, never a fabricated verdict).
        """
        original = compensates["external_id"]
        row = db.execute("SELECT external_id FROM withdrawals WHERE original_external_id=?",
                         (original,)).fetchone()
        if row is not None:
            # Effect exists (possibly created under a different key in a shared
            # store): record a requesting-digest alias receipt reusing the WD id.
            result = {"status": "accepted", "external_id": row[0],
                      "digest": content_digest, "original_external_id": original}
        elif self._forward_receipt_exists(db, original):
            external_id = "WD-" + uuid.uuid4().hex[:12]
            db.execute("INSERT INTO withdrawals VALUES (?,?,?,?)",
                       (original, external_id, key, content_digest))
            result = {"status": "accepted", "external_id": external_id,
                      "digest": content_digest, "original_external_id": original}
        else:
            result = {"status": "rejected", "external_id": "WD-" + uuid.uuid4().hex[:12],
                      "digest": content_digest, "original_external_id": original,
                      "reason": "ORIGINAL_ABSENT"}
        db.execute("INSERT INTO receipts (key,digest,result,action,link_digest) "
                   "VALUES (?,?,?,?,?)",
                   (key, content_digest, canonical(result), "expense.withdraw", link_digest))
        return result

    @staticmethod
    def _forward_receipt_exists(db, external_id) -> bool:
        """Original existence = an accepted FORWARD receipt, not invoices-only.

        Direct adapter calls can accept zero-invoice documents (no invoices
        rows), so the receipts scan is authoritative; the invoices short-circuit
        covers the common case without changing the verdict.
        """
        if db.execute("SELECT 1 FROM invoices WHERE external_id=? LIMIT 1",
                      (external_id,)).fetchone():
            return True
        for action, stored in db.execute("SELECT action,result FROM receipts"):
            result = json.loads(stored)
            if (result.get("status") == "accepted"
                    and (action is None or action == "expense.submit")
                    and result.get("external_id") == external_id):
                return True
        return False

    def lookup(self, key: str):
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT result FROM receipts WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None
        finally:
            db.close()

    def accepted_count(self) -> int:
        """Distinct accepted forward effects (withdrawal/alias rows excluded)."""
        db = sqlite3.connect(self.path)
        try:
            external_ids = set()
            for action, stored in db.execute("SELECT action,result FROM receipts"):
                result = json.loads(stored)
                if (result.get("status") == "accepted"
                        and (action is None or action == "expense.submit")
                        and isinstance(result.get("external_id"), str)
                        and result["external_id"]):
                    external_ids.add(result["external_id"])
            return len(external_ids)
        finally:
            db.close()

    def withdrawn_count(self) -> int:
        """Withdrawal effect rows: exactly one per withdrawn original."""
        db = sqlite3.connect(self.path)
        try:
            return db.execute("SELECT COUNT(*) FROM withdrawals").fetchone()[0]
        finally:
            db.close()
