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

from work_runtime.adapter_contract import receipt_is_valid
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


def retraction_link(external_id, operation_id="op-original"):
    return {"operation_id": operation_id, "external_id": external_id,
            "capability": "content.publish"}


class RetractionExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "publisher.sqlite")
        self.publisher = FakePublisher(self.path)

    def forward(self, key, document=None):
        document = article() if document is None else document
        receipt = self.publisher.execute(key, document, digest(document))
        self.assertEqual(receipt["status"], "accepted")
        return document, receipt

    def retract(self, key, document, original_id):
        return self.publisher.execute(key, document, digest(document),
                                      action="content.unpublish",
                                      compensates=retraction_link(original_id))

    def store_counts(self):
        with sqlite3.connect(self.path) as db:
            return {t: db.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
                    for t in ("receipts", "publications", "retractions")}

    def test_retraction_executes_once_and_is_idempotent_by_key(self):
        document, forward = self.forward("fwd-1")
        receipt = self.retract("rtr-1", document, forward["external_id"])
        self.assertEqual(receipt["status"], "accepted")
        self.assertTrue(receipt["external_id"].startswith("RTR-"))
        self.assertEqual(receipt["original_external_id"], forward["external_id"])
        self.assertTrue(receipt_is_valid(receipt, digest(document)))
        replay = self.retract("rtr-1", document, forward["external_id"])
        self.assertEqual(replay, receipt)
        self.assertEqual((self.publisher.retracted_count(),
                          self.publisher.published_count()), (1, 1))
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT action,link_digest FROM receipts "
                             "WHERE key='rtr-1'").fetchone()
        self.assertEqual(row[0], "content.unpublish")
        self.assertEqual(row[1], digest(retraction_link(forward["external_id"])))

    def test_retraction_input_guards_raise_before_any_write(self):
        document, forward = self.forward("fwd-1")
        before = self.store_counts()
        with self.assertRaises(ValueError) as caught:  # unknown action
            self.publisher.execute("rtr-x", document, digest(document),
                                   action="content.purge")
        self.assertIn("Unknown action", str(caught.exception))
        with self.assertRaises(ValueError) as caught:  # retraction without link
            self.publisher.execute("rtr-x", document, digest(document),
                                   action="content.unpublish")
        self.assertIn("compensates link", str(caught.exception))
        for malformed in (None, "PUB-1", {}, {"operation_id": "op"},
                          {"operation_id": "op", "external_id": forward["external_id"],
                           "capability": "", "extra": 1}):
            with self.subTest(malformed=malformed):
                with self.assertRaises(ValueError) as caught:
                    self.publisher.execute("rtr-x", document, digest(document),
                                           action="content.unpublish",
                                           compensates=malformed)
                self.assertIn("compensates link", str(caught.exception))
        with self.assertRaises(ValueError) as caught:  # forward with link
            self.publisher.execute("rtr-x", document, digest(document),
                                   action="content.publish",
                                   compensates=retraction_link(forward["external_id"]))
        self.assertIn("must not carry", str(caught.exception))
        self.assertEqual(self.store_counts(), before)
        self.assertEqual(self.publisher.retracted_count(), 0)

    def test_different_key_same_original_returns_alias_and_lookup_is_authoritative(self):
        document, forward = self.forward("fwd-1")
        first = self.retract("rtr-1", document, forward["external_id"])
        # A second key with a DIFFERENT document digest gets a digest-valid
        # alias receipt carrying the same RTR id; lookup stays authoritative
        # by key; still exactly one effect row.
        other = article(article_id="ART-002", body="A different body")
        alias = self.retract("rtr-2", other, forward["external_id"])
        self.assertEqual(alias["status"], "accepted")
        self.assertEqual(alias["external_id"], first["external_id"])
        self.assertEqual(alias["original_external_id"], forward["external_id"])
        self.assertTrue(receipt_is_valid(alias, digest(other)))
        self.assertFalse(receipt_is_valid(alias, digest(document)))
        self.assertEqual(self.publisher.lookup("rtr-2"), alias)
        self.assertEqual(self.publisher.retracted_count(), 1)
        self.assertEqual(self.publisher.published_count(), 1)
        # Lost response after the alias commits: lookup remains authoritative.
        lost = FakePublisher(self.path, timeout_after_commit=True)
        document3 = article(article_id="ART-003", body="A third body")
        with self.assertRaises(TimeoutError):
            lost.execute("rtr-3", document3, digest(document3),
                         action="content.unpublish",
                         compensates=retraction_link(forward["external_id"]))
        recovered = self.publisher.lookup("rtr-3")
        self.assertEqual(recovered["external_id"], first["external_id"])
        self.assertTrue(receipt_is_valid(recovered, digest(document3)))

    def test_same_key_different_link_conflicts_even_with_equal_digest(self):
        document, forward = self.forward("fwd-1")
        document2, forward2 = self.forward("fwd-2", article(body="Second body"))
        self.retract("rtr-1", document, forward["external_id"])
        effects = self.publisher.retracted_count()
        # Same key, same document digest, different compensates target.
        with self.assertRaises(ValueError):
            self.retract("rtr-1", document, forward2["external_id"])
        self.assertEqual(self.publisher.retracted_count(), effects)
        # Cross-action under one key, both directions.
        with self.assertRaises(ValueError):  # forward call against a retraction row
            self.publisher.execute("rtr-1", document, digest(document))
        with self.assertRaises(ValueError):  # retraction call against a forward row
            self.retract("fwd-2", document, forward2["external_id"])
        self.assertEqual(self.publisher.retracted_count(), effects)

    def test_missing_original_is_bounded_business_rejection(self):
        document = article()
        receipt = self.retract("rtr-1", document, "PUB-neverexisted")
        self.assertEqual(receipt["status"], "rejected")
        self.assertEqual(receipt["reason"], "ORIGINAL_ABSENT")
        self.assertEqual(receipt["original_external_id"], "PUB-neverexisted")
        self.assertTrue(receipt_is_valid(receipt, digest(document)))
        self.assertEqual(self.publisher.retracted_count(), 0)
        replay = self.retract("rtr-1", document, "PUB-neverexisted")
        self.assertEqual(replay, receipt)

    def test_original_existence_via_scan_and_short_circuit(self):
        # Leg 1: the receipts row was lost, the publications row kept —
        # existence decided true via the publications short-circuit.
        document, forward = self.forward("fwd-1")
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM receipts WHERE key='fwd-1'")
        receipt = self.retract("rtr-1", document, forward["external_id"])
        self.assertEqual(receipt["status"], "accepted")
        # Leg 2: the publications row was lost, the receipts row kept —
        # existence decided true via the authoritative receipts scan.
        path2 = str(Path(self.temp.name) / "publisher2.sqlite")
        publisher2 = FakePublisher(path2)
        receipt_f = publisher2.execute("fwd-1", document, digest(document))
        with sqlite3.connect(path2) as db:
            db.execute("DELETE FROM publications")
        receipt_r = publisher2.execute("rtr-1", document, digest(document),
                                       action="content.unpublish",
                                       compensates=retraction_link(
                                           receipt_f["external_id"]))
        self.assertEqual(receipt_r["status"], "accepted")
        self.assertEqual(publisher2.retracted_count(), 1)


class RetractionAppendOnlyTests(unittest.TestCase):
    """RF4 adapter-model interplay: retraction is append-only, dedup stands."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "publisher.sqlite")
        self.publisher = FakePublisher(self.path)

    def rows(self, table):
        with sqlite3.connect(self.path) as db:
            return db.execute("SELECT * FROM " + table).fetchall()

    def test_retraction_is_append_only_and_forward_still_dedups(self):
        document = article()
        forward = self.publisher.execute("fwd-1", document, digest(document))
        publications_before = self.rows("publications")
        retraction = self.publisher.execute(
            "rtr-1", document, digest(document), action="content.unpublish",
            compensates=retraction_link(forward["external_id"]))
        self.assertEqual(retraction["status"], "accepted")
        # Append-only: the publication rows are untouched, exactly one
        # retraction effect row exists, counts stay truthful.
        self.assertEqual(self.rows("publications"), publications_before)
        self.assertEqual(len(self.rows("retractions")), 1)
        self.assertEqual((self.publisher.published_count(),
                          self.publisher.retracted_count()), (1, 1))
        # Re-publishing identical (document id, digest) after the retraction
        # reuses the retracted artifact's id — the documented external-model
        # limit (unreachable through the governed flow; see runtime-boundaries).
        republish = self.publisher.execute("fwd-2", document, digest(document))
        self.assertEqual(republish["external_id"], forward["external_id"])
        self.assertEqual((self.publisher.published_count(),
                          self.publisher.retracted_count()), (1, 1))
        self.assertEqual(self.rows("publications"), publications_before)


if __name__ == "__main__":
    unittest.main()
