"""S14 publishing-compensation core: linked content.unpublish retraction.

Implements the master-ratified design D80-D91: linked compensation for the
publishing family inside the active cancellation window, on the unchanged
S10 machinery. Publishing family and active-cancellation window only;
post-closure compensation, chains, cross-work compensation and intervener
authority remain deferred scope. `content.unpublish` (content family) is
distinct from S13's `sop.withdraw` (SOP authoring family).
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from threading import Barrier, Thread

from work_runtime.file_adapter import FilePublisher
from work_runtime.policy import canonical, digest
from work_runtime.publishing import FakePublisher, PublishingPolicy


def article(article_id="ART-001", title="Release notes", body="Draft body",
            requires_review=True):
    return {"id": article_id, "title": title, "body": body,
            "requires_review": requires_review}


def publishing_compensation_grants():
    """Demo grants with the compensating capability held by the owner."""
    return {"agent": {"work.manage", "content.publish", "content.unpublish"},
            "reviewer": {"evidence.write"}, "author": {"evidence.write"},
            "admin": {"work.intervene"}}


def pending_requirements():
    """C01-C03 pending requirement results, the pre-publication state."""
    return [{"id": "C01:ART-001", "rule_id": "C01", "subject": "ART-001",
             "applicability": "applicable", "fulfillment": "pending",
             "explanation": "The current artifact must be complete"},
            {"id": "C02:ART-001", "rule_id": "C02", "subject": "ART-001",
             "applicability": "applicable", "fulfillment": "pending",
             "explanation": "A true requires_review needs the reviewer's approval"},
            {"id": "C03:ART-001", "rule_id": "C03", "subject": "ART-001",
             "applicability": "applicable", "fulfillment": "pending",
             "explanation": "The author must confirm the current content"}]


class PolicyPairingTests(unittest.TestCase):
    def test_paired_capability_attribute_and_empty_blockers(self):
        policy = PublishingPolicy()
        self.assertEqual(policy.compensation_capabilities,
                         {"content.unpublish": "content.publish"})
        # A paired compensating capability is admitted through its link check
        # (runtime), never through requirements: its blockers are empty even
        # while every publication requirement is still pending.
        self.assertEqual(policy.action_blockers("content.unpublish",
                                                pending_requirements()), [])

    def test_off_family_capabilities_stay_unsupported(self):
        policy = PublishingPolicy()
        for capability in ("content.withdraw", "expense.submit", "expense.withdraw"):
            with self.subTest(capability=capability):
                self.assertEqual(
                    policy.action_blockers(capability, pending_requirements()),
                    [{"code": "CAPABILITY_UNSUPPORTED", "capability": capability}])

    def test_forward_capability_blockers_shape_unchanged(self):
        policy = PublishingPolicy()
        pending = pending_requirements()
        # The forward filter keeps returning the pending requirement objects.
        self.assertEqual(policy.action_blockers("content.publish", pending), pending)

    def test_policy_version_is_unchanged(self):
        # D89: the pairing is a family declaration, not a new policy version.
        self.assertEqual(PublishingPolicy.version, "demo-1")

    def test_file_publisher_stays_forward_only(self):
        # D88: FilePublisher is untouched — no pairing, forward-only contract.
        self.assertFalse(getattr(FilePublisher, "compensation_capabilities", None))
        self.assertEqual(FilePublisher.contract.actions, ("content.publish",))
        self.assertIs(FilePublisher.contract.supports_action_context, False)


def legacy_publisher_store(path, key="legacy-key", document=None):
    """A pre-S14 FakePublisher store: 3-column receipts plus publications."""
    document = article() if document is None else document
    db = sqlite3.connect(path)
    try:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS receipts (
                key TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS publications (
                document_id TEXT, digest TEXT, external_id TEXT NOT NULL,
                document TEXT NOT NULL, PRIMARY KEY(document_id, digest));
        """)
        result = {"status": "accepted", "external_id": "PUB-legacy000001",
                  "digest": digest(document)}
        db.execute("INSERT INTO receipts VALUES (?,?,?)",
                   (key, digest(document), canonical(result)))
        db.execute("INSERT INTO publications VALUES (?,?,?,?)",
                   (document["id"], digest(document), result["external_id"],
                    canonical(document)))
        db.commit()
        return document, result
    finally:
        db.close()


def store_columns(path, table):
    db = sqlite3.connect(path)
    try:
        return [row[1] for row in db.execute("PRAGMA table_info(%s)" % table)]
    finally:
        db.close()


CURRENT_RECEIPT_COLUMNS = ["key", "digest", "result", "action", "link_digest"]


class FakePublisherMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def path(self, name="publisher.sqlite"):
        return str(Path(self.temp.name) / name)

    def test_old_publisher_store_migrates_additively(self):
        path = self.path("legacy.sqlite")
        document, result = legacy_publisher_store(path)
        with sqlite3.connect(path) as snapshot:
            legacy_receipts = snapshot.execute(
                "SELECT key,digest,result FROM receipts").fetchall()
            legacy_publications = snapshot.execute(
                "SELECT * FROM publications").fetchall()
        publisher = FakePublisher(path)
        self.assertEqual(store_columns(path, "receipts"),
                         CURRENT_RECEIPT_COLUMNS)
        with sqlite3.connect(path) as db:
            row = db.execute("SELECT action,link_digest FROM receipts WHERE key=?",
                             ("legacy-key",)).fetchone()
            tables = {r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            migrated_receipts = db.execute(
                "SELECT key,digest,result FROM receipts").fetchall()
            migrated_publications = db.execute(
                "SELECT * FROM publications").fetchall()
        self.assertEqual(row, (None, None))  # NULL = legacy forward row
        self.assertEqual(tables, {"receipts", "publications", "retractions"})
        self.assertEqual(migrated_receipts, legacy_receipts)  # no row rewritten
        self.assertEqual(migrated_publications, legacy_publications)
        # Forward behavior preserved: the legacy receipt replays by key+digest.
        replay = publisher.execute("legacy-key", document, digest(document))
        self.assertEqual(replay, result)
        # Reopening is idempotent: each column exists exactly once.
        FakePublisher(path)
        self.assertEqual(store_columns(path, "receipts"),
                         CURRENT_RECEIPT_COLUMNS)

    def test_concurrent_first_open_serializes(self):
        path = self.path("race.sqlite")
        legacy_publisher_store(path, key="seed")
        barrier = Barrier(2)
        errors = []

        def opener():
            try:
                barrier.wait()
                FakePublisher(path)
            except BaseException as error:  # noqa: BLE001 - recorded, re-raised below
                errors.append(error)

        threads = [Thread(target=opener) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(store_columns(path, "receipts"),
                         CURRENT_RECEIPT_COLUMNS)

    def test_fresh_store_is_schema_current(self):
        publisher = FakePublisher(self.path())
        self.assertEqual(store_columns(publisher.path, "receipts"),
                         CURRENT_RECEIPT_COLUMNS)
        with sqlite3.connect(publisher.path) as db:
            tables = {r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tables, {"receipts", "publications", "retractions"})
        self.assertEqual(publisher.published_count(), 0)
        self.assertEqual(publisher.retracted_count(), 0)


class ForwardIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "publisher.sqlite")
        self.publisher = FakePublisher(self.path)

    def receipt_row(self, key):
        with sqlite3.connect(self.path) as db:
            return db.execute(
                "SELECT digest,action,link_digest,result FROM receipts WHERE key=?",
                (key,)).fetchone()

    def store_counts(self):
        with sqlite3.connect(self.path) as db:
            return {t: db.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
                    for t in ("receipts", "publications", "retractions")}

    def test_forward_rows_stay_null_action_and_replay_identically(self):
        document = article()
        positional = self.publisher.execute("fwd-key", document, digest(document))
        kwargs_replay = self.publisher.execute("fwd-key", document, digest(document),
                                               action="content.publish",
                                               compensates=None)
        self.assertEqual(kwargs_replay, positional)
        row = self.receipt_row("fwd-key")
        self.assertEqual((row[1], row[2]), (None, None))
        # An explicit-context first call stores the same NULL-tagged row.
        explicit = self.publisher.execute("fwd-explicit", document, digest(document),
                                          action="content.publish",
                                          compensates=None)
        self.assertEqual(self.receipt_row("fwd-explicit")[1:3], (None, None))
        self.assertEqual(explicit["external_id"], positional["external_id"])
        # Same key, different content: ValueError, zero new effects.
        changed = article(body="changed")
        with self.assertRaises(ValueError):
            self.publisher.execute("fwd-key", changed, digest(changed))
        self.assertEqual(self.store_counts(),
                         {"receipts": 2, "publications": 1, "retractions": 0})

    def test_same_content_dedup_identity(self):
        document = article()
        first = self.publisher.execute("key-1", document, digest(document))
        second = self.publisher.execute("key-2", document, digest(document))
        self.assertEqual(first, second)
        self.assertEqual(self.store_counts(),
                         {"receipts": 2, "publications": 1, "retractions": 0})
        self.assertEqual(self.publisher.published_count(), 1)

    def test_contract_order_and_optin(self):
        # D86+MD-2: content.publish stays FIRST (conformance derives forward
        # context from actions[0]) and the store opts into action/link context.
        contract = FakePublisher.contract
        self.assertEqual(contract.actions, ("content.publish", "content.unpublish"))
        self.assertIs(contract.supports_action_context, True)
        self.assertEqual(contract.uniqueness,
                         ("document.id+content_digest",
                          "retraction.original_external_id"))


if __name__ == "__main__":
    unittest.main()
