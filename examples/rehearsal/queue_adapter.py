"""A third-party-style persistent queue adapter for ``content.publish``.

S4 rehearsal sample: written from the public contributor docs only
(docs/contributor-guide.md, docs/adapter-contract.md, docs/file-adapter.md)
without reading the runtime lifecycle source.

The external effect is one durable row in a ``queue`` table of a SQLite
database file; the committed receipt per idempotency key lives in a
``receipts`` table and survives restarts. Disposable teaching grade: one
``BEGIN IMMEDIATE`` transaction commits the queue row and the receipt
together for a single process — no power-loss, hostile-filesystem or
distributed exactly-once guarantee, and no concurrent-writer testing.
"""

import hashlib
import json
import sqlite3

from work_runtime.adapter_contract import AdapterContract

_SCHEMA = """
CREATE TABLE IF NOT EXISTS queue (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash TEXT NOT NULL,
    external_id TEXT NOT NULL UNIQUE,
    content_digest TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    enqueued_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TABLE IF NOT EXISTS receipts (
    key_hash TEXT PRIMARY KEY,
    external_id TEXT NOT NULL UNIQUE,
    content_digest TEXT NOT NULL,
    receipt_json TEXT NOT NULL
);
"""


class SqliteQueuePublisher:
    """Enqueue once per idempotency key; receipts are queryable by key."""

    contract = AdapterContract(
        actions=("content.publish",),
        idempotency_scope="queue-database:key",
        retention="lifetime-of-database",
        lookup_consistency="authoritative-by-key",
        uniqueness=(),
    )

    def __init__(self, database):
        self.database = database
        self._connection = sqlite3.connect(database, isolation_level=None)
        self._connection.executescript(_SCHEMA)

    def execute(self, key, document, content_digest):
        """Idempotently enqueue ``document`` under ``key``; return the receipt."""
        key_hash = self._key_hash(key)
        if not isinstance(content_digest, str) or not content_digest:
            raise ValueError("content digest must be a nonempty string")
        payload_json = self._encode(document)
        external_id = "QUEUE-" + key_hash[:16]
        receipt = {"status": "accepted",
                   "external_id": external_id,
                   "digest": content_digest}
        connection = self._connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            committed = connection.execute(
                "SELECT content_digest, receipt_json FROM receipts WHERE key_hash = ?",
                (key_hash,),
            ).fetchone()
            if committed is not None:
                connection.execute("ROLLBACK")
                if committed[0] != content_digest:
                    raise ValueError("idempotency key reused with different content")
                return json.loads(committed[1])
            connection.execute(
                "INSERT INTO queue (key_hash, external_id, content_digest, payload_json)"
                " VALUES (?, ?, ?, ?)",
                (key_hash, external_id, content_digest, payload_json),
            )
            connection.execute(
                "INSERT INTO receipts (key_hash, external_id, content_digest, receipt_json)"
                " VALUES (?, ?, ?, ?)",
                (key_hash, external_id, content_digest, json.dumps(receipt, sort_keys=True)),
            )
            connection.execute("COMMIT")
            return receipt
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    def lookup(self, key):
        """The committed receipt for ``key``, or ``None`` when nothing committed."""
        row = self._connection.execute(
            "SELECT receipt_json FROM receipts WHERE key_hash = ?",
            (self._key_hash(key),),
        ).fetchone()
        return json.loads(row[0]) if row is not None else None

    @staticmethod
    def _key_hash(key):
        if not isinstance(key, str) or not key:
            raise ValueError("idempotency key must be a nonempty string")
        try:
            return hashlib.sha256(key.encode("utf-8")).hexdigest()
        except UnicodeEncodeError:
            raise ValueError("idempotency key must encode to UTF-8")

    @staticmethod
    def _encode(document):
        try:
            return json.dumps(document, sort_keys=True, separators=(",", ":"),
                              allow_nan=False)
        except (TypeError, ValueError):
            raise ValueError("document is not JSON-native with finite numbers")
