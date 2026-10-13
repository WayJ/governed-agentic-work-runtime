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
    contract = AdapterContract(
        actions=("expense.submit",),
        idempotency_scope="adapter-store:key",
        retention="lifetime-of-store",
        lookup_consistency="authoritative-by-key",
        uniqueness=("invoice.id",))

    def __init__(self, path: str, timeout_after_commit: bool = False):
        self.path = str(path)
        self.timeout_after_commit = timeout_after_commit
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        try:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS receipts (
                    key TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS invoices (
                    invoice_id TEXT PRIMARY KEY, external_id TEXT NOT NULL);
            """)
            db.commit()
        finally:
            db.close()

    def execute(self, key: str, document: dict, content_digest: str) -> dict:
        if digest(document) != content_digest:
            raise ValueError("Content digest does not match document")
        db = sqlite3.connect(self.path, timeout=15)
        try:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT digest,result FROM receipts WHERE key=?", (key,)).fetchone()
            if old:
                if old[0] != content_digest:
                    raise ValueError("Idempotency key reused with different content")
                result = json.loads(old[1])
            else:
                duplicate = any(db.execute("SELECT 1 FROM invoices WHERE invoice_id=?",
                                           (i["id"],)).fetchone() for i in document["invoices"])
                result = {"status": "rejected" if duplicate else "accepted",
                          "external_id": "OA-" + uuid.uuid4().hex[:12], "digest": content_digest}
                db.execute("INSERT INTO receipts VALUES (?,?,?)", (key, content_digest, canonical(result)))
                if not duplicate:
                    for invoice in document["invoices"]:
                        db.execute("INSERT INTO invoices VALUES (?,?)", (invoice["id"], result["external_id"]))
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
        if self.timeout_after_commit:
            raise TimeoutError("Response lost after OA committed")
        return result

    def lookup(self, key: str):
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT result FROM receipts WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None
        finally:
            db.close()

    def accepted_count(self) -> int:
        db = sqlite3.connect(self.path)
        try:
            return sum(json.loads(row[0])["status"] == "accepted"
                       for row in db.execute("SELECT result FROM receipts"))
        finally:
            db.close()
