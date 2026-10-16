"""S14 publishing-compensation core: linked content.unpublish retraction.

Implements the master-ratified design D80-D91: linked compensation for the
publishing family inside the active cancellation window, on the unchanged
S10 machinery. Publishing family and active-cancellation window only;
post-closure compensation, chains, cross-work compensation and intervener
authority remain deferred scope. `content.unpublish` (content family) is
distinct from S13's `sop.withdraw` (SOP authoring family).
"""

import json
import secrets
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path
from threading import Barrier, Thread

from work_runtime import Runtime
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


class RejectingPublisher:
    """Legacy adapter returning a digest-valid business rejection."""

    def execute(self, key, document, content_digest):
        return {"status": "rejected", "external_id": "PUB-rejected",
                "digest": content_digest}

    def lookup(self, key):
        return None


class SilentPublisher:
    """External call lost; no authoritative answer is ever available."""

    def execute(self, key, document, content_digest):
        raise TimeoutError()

    def lookup(self, key):
        return None


class PublishingCompensationCase(unittest.TestCase):
    """A confirmed publishing effect inside the active cancellation window."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        self.publisher_path = str(Path(self.temp.name) / "publisher.sqlite")
        self.runtime = self.fresh_runtime()
        self.work_id = "article-1"
        self.initialize(self.work_id)

    def fresh_runtime(self, grants=None):
        return Runtime(self.path, PublishingPolicy(),
                       grants if grants is not None else publishing_compensation_grants())

    def send(self, kind, payload=None, actor="agent", command_id=None,
             work_id=None, runtime=None):
        runtime = runtime or self.runtime
        work_id = work_id or self.work_id
        version = None if kind in ("create_work", "record_evidence") \
            else runtime.get_work(work_id)["state_version"]
        return runtime.command(actor, command_id or uuid.uuid4().hex, work_id,
                               kind, payload, version)

    def initialize(self, work_id, requires_review=True):
        self.send("create_work", {"document": article(requires_review=requires_review)},
                  work_id=work_id)
        self.send("bind_contract", {"policy_id": "content-publish",
                                    "policy_version": "demo-1",
                                    "goal": "content.published"}, work_id=work_id)
        self.send("revise_plan", {"steps": ["draft", "review", "confirm", "publish"],
                                  "open_requirements": ["C02"],
                                  "replan_when": ["reviewer rejects"]}, work_id=work_id)

    def record_proof(self, kind, source, work_id=None):
        work_id = work_id or self.work_id
        current = self.runtime.get_work(work_id)["document_digest"]
        return self.send("record_evidence",
                         {"event_id": uuid.uuid4().hex, "kind": kind,
                          "data": {"digest": current}},
                         actor=source, work_id=work_id)

    def approve_and_confirm(self, work_id=None):
        work_id = work_id or self.work_id
        self.record_proof("approval", "reviewer", work_id=work_id)
        self.record_proof("confirmation", "author", work_id=work_id)
        self.runtime.verify_pending(work_id)

    def propose_publish(self, work_id=None, runtime=None, actor="agent",
                        command_id=None):
        runtime = runtime or self.runtime
        work = runtime.get_work(work_id or self.work_id)
        return self.send("propose_action", {
            "capability": "content.publish", "document_digest": work["document_digest"],
            "contract_revision": work["contract"]["revision"],
            "plan_revision": work["plan_revision"]}, actor=actor,
            command_id=command_id, work_id=work_id, runtime=runtime)

    def confirmed_publish(self, work_id=None, publisher=None, command_id=None):
        work_id = work_id or self.work_id
        self.approve_and_confirm(work_id=work_id)
        receipt = self.propose_publish(work_id=work_id, command_id=command_id)
        assert receipt["decision"] == "accepted", receipt
        operation_id = receipt["operation_id"]
        resolved = self.runtime.dispatch(
            operation_id, publisher or FakePublisher(self.publisher_path))
        assert resolved["status"] == "confirmed_succeeded", resolved
        return operation_id

    def request_cancel(self, reason="content must come down", work_id=None,
                       runtime=None):
        receipt = self.send("request_cancel", {"reason": reason},
                            work_id=work_id, runtime=runtime)
        assert (receipt["decision"] == "accepted"
                or receipt["code"] == "CANCELLATION_ALREADY_REQUESTED"), receipt
        return receipt

    def unpublish(self, target_id, actor="agent", command_id=None,
                  capability="content.unpublish", work_id=None, runtime=None):
        runtime = runtime or self.runtime
        work = runtime.get_work(work_id or self.work_id)
        return self.send("propose_action", {
            "capability": capability,
            "document_digest": work["document_digest"],
            "contract_revision": work["contract"]["revision"],
            "plan_revision": work["plan_revision"],
            "compensates": target_id}, actor=actor, command_id=command_id,
            work_id=work_id, runtime=runtime)


class PublishingCompensationAdmissionTests(PublishingCompensationCase):
    def test_linked_retraction_proposal_accepted_during_window(self):
        target = self.confirmed_publish(command_id="publish-1")
        self.request_cancel()
        receipt = self.unpublish(target, command_id="unpublish-1")
        self.assertEqual(receipt["decision"], "accepted")
        self.assertEqual(receipt["operation_status_at_decision"], "prepared")
        operation = self.runtime.get_operation(receipt["operation_id"])
        self.assertEqual(operation["compensates"], {
            "operation_id": target,
            "external_id": self.runtime.get_operation(target)["external_id"],
            "capability": "content.publish"})
        event = [e for e in self.runtime.events(self.work_id)
                 if e["type"] == "OperationPrepared"][-1]
        self.assertEqual(json.loads(event["body"])["compensates"],
                         operation["compensates"])

    def test_linked_retraction_requires_active_cancellation(self):
        target = self.confirmed_publish()
        receipt = self.unpublish(target)
        self.assertEqual((receipt["decision"], receipt["code"], receipt["blockers"]),
                         ("rejected", "CANCELLATION_NOT_REQUESTED", []))
        self.assertEqual(receipt["observed_state_version"],
                         self.runtime.get_work(self.work_id)["state_version"])

    def test_forward_proposal_still_rejected_in_window(self):
        self.confirmed_publish()
        self.request_cancel()
        receipt = self.propose_publish(command_id="forward-in-window")
        self.assertEqual((receipt["decision"], receipt["code"]),
                         ("rejected", "CANCELLATION_ACTIVE"))

    def test_compensation_payload_shape_is_exact(self):
        target = self.confirmed_publish()
        self.request_cancel()
        work = self.runtime.get_work(self.work_id)
        base = {"capability": "content.unpublish",
                "document_digest": work["document_digest"],
                "contract_revision": work["contract"]["revision"],
                "plan_revision": work["plan_revision"], "compensates": target}
        from work_runtime import CommandError
        bad_payloads = [
            {**base, "note": "extra"},                      # extra key
            {k: v for k, v in base.items() if k != "plan_revision"},  # missing key
            {**base, "compensates": 42},                    # non-string target
            {**base, "compensates": ""},                    # empty target
        ]
        version = work["state_version"]
        events_before = len(self.runtime.events(self.work_id))
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(CommandError):
                    self.send("propose_action", payload)
        # Nothing persisted: no state bump, no events, no command rows.
        self.assertEqual(self.runtime.get_work(self.work_id)["state_version"], version)
        self.assertEqual(len(self.runtime.events(self.work_id)), events_before)
        self.assertIsNone(self.runtime.get_command("agent", "shape-probe"))

    def test_retraction_target_must_be_confirmed_succeeded_same_work(self):
        # A prepared, never-dispatched target at the first content revision.
        self.approve_and_confirm()
        prepared = self.propose_publish(command_id="prepared-only")["operation_id"]
        # A confirmed target needs its own revision: a second proposal of the
        # same document re-admits the same business key (forward dedup).
        self.send("revise_document", {"document": article(body="Second body")})
        confirmed = self.confirmed_publish(command_id="confirmed")
        # A stuck-at-dispatched target: another revision makes this a third
        # distinct operation; the fault dies between the attempt commit and
        # resolution.
        self.send("revise_document", {"document": article(body="Third body")})
        self.approve_and_confirm()
        stuck = self.propose_publish(command_id="stuck")["operation_id"]

        def boom():
            raise RuntimeError("died between attempt commit and resolve")

        with self.assertRaises(RuntimeError):
            self.runtime.dispatch(stuck, FakePublisher(self.publisher_path), fault=boom)
        self.assertEqual(self.runtime.get_operation(stuck)["status"], "dispatched")
        # A confirmed_failed target in a second work of the same store.
        for work_id in ("failedwork", "unknownwork"):
            self.send("create_work",
                      {"document": article(article_id="ART-" + work_id,
                                           body="Body of " + work_id)},
                      work_id=work_id)
            self.send("bind_contract", {"policy_id": "content-publish",
                                        "policy_version": "demo-1",
                                        "goal": "content.published"}, work_id=work_id)
            self.send("revise_plan", {"steps": ["review", "confirm", "publish"],
                                      "open_requirements": ["C02"],
                                      "replan_when": []}, work_id=work_id)
            self.approve_and_confirm(work_id=work_id)
        failed = self.propose_publish(work_id="failedwork")["operation_id"]
        self.assertEqual(self.runtime.dispatch(failed, RejectingPublisher())["status"],
                         "confirmed_failed")
        uncertain = self.propose_publish(work_id="unknownwork")["operation_id"]
        self.runtime.dispatch(uncertain, SilentPublisher())
        self.assertEqual(self.runtime.get_operation(uncertain)["status"],
                         "outcome_unknown")
        self.request_cancel()
        self.request_cancel(work_id="failedwork", reason="also cancelling")
        self.request_cancel(work_id="unknownwork", reason="also cancelling")
        for name, target_id, work_id in (
                ("prepared", prepared, self.work_id),
                ("dispatched", stuck, self.work_id),
                ("confirmed_failed", failed, self.work_id),
                ("unknown-id", "no-such-operation", self.work_id),
                ("outcome_unknown", uncertain, "unknownwork")):
            with self.subTest(target=name):
                receipt = self.unpublish(target_id, work_id=work_id)
                self.assertEqual(receipt["decision"], "rejected")
                self.assertEqual(receipt["code"], "COMPENSATION_TARGET_INVALID")
                self.assertEqual(receipt["blockers"], [target_id])
        # Cross-work: unknownwork's window cannot compensate the main work's effect.
        receipt = self.unpublish(confirmed, work_id="unknownwork")
        self.assertEqual((receipt["decision"], receipt["code"], receipt["blockers"]),
                         ("rejected", "COMPENSATION_TARGET_INVALID", [confirmed]))

    def test_retraction_target_must_not_be_compensation(self):
        target = self.confirmed_publish()
        self.request_cancel()
        retraction = self.unpublish(target)["operation_id"]
        receipt = self.unpublish(retraction)
        self.assertEqual((receipt["decision"], receipt["code"], receipt["blockers"]),
                         ("rejected", "COMPENSATION_TARGET_INVALID", [retraction]))

    def test_retraction_business_key_stable_and_distinct(self):
        target = self.confirmed_publish(command_id="publish-a")
        other_work = "article-2"
        self.send("create_work", {"document": article(article_id="ART-2",
                                                      body="Second article")},
                  work_id=other_work)
        self.send("bind_contract", {"policy_id": "content-publish",
                                    "policy_version": "demo-1",
                                    "goal": "content.published"}, work_id=other_work)
        self.send("revise_plan", {"steps": ["review", "confirm", "publish"],
                                  "open_requirements": ["C02"],
                                  "replan_when": []}, work_id=other_work)
        self.approve_and_confirm(work_id=other_work)
        other = self.propose_publish(work_id=other_work)["operation_id"]
        self.runtime.dispatch(other, FakePublisher(self.publisher_path))
        self.request_cancel()
        self.request_cancel(work_id=other_work, reason="second article too")
        first = self.unpublish(target, command_id="u1")
        second = self.unpublish(target, command_id="u2")
        self.assertEqual(first["operation_id"], second["operation_id"])
        operation = self.runtime.get_operation(first["operation_id"])
        self.assertEqual(operation["business_key"],
                         digest(["content-publish", "content.unpublish", target]))
        forward = self.runtime.get_operation(target)
        self.assertNotEqual(operation["business_key"], forward["business_key"])
        third = self.unpublish(other, work_id=other_work, command_id="u3")
        self.assertNotEqual(third["operation_id"], first["operation_id"])
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT COUNT(*) FROM operations WHERE business_key=?",
                              (operation["business_key"],)).fetchone()[0]
        self.assertEqual(rows, 1)

    def test_retraction_link_snapshot_is_immutable(self):
        target = self.confirmed_publish()
        self.request_cancel()
        first = self.unpublish(target, command_id="retract-1")
        before = self.runtime.get_operation(first["operation_id"])["compensates"]
        replay = self.unpublish(target, command_id="re-admit-1")
        self.assertEqual(replay["operation_id"], first["operation_id"])
        self.assertEqual(replay["operation_status_at_decision"], "prepared")
        self.assertEqual(self.runtime.get_operation(first["operation_id"])["compensates"],
                         before)


class PublishingCompensationAuthorityTests(PublishingCompensationCase):
    def test_retraction_authority_is_current_owner_with_grant(self):
        target = self.confirmed_publish()
        self.request_cancel()
        # An intervener holding work.intervene but not the capability.
        receipt = self.unpublish(target, actor="admin", command_id="by-admin")
        self.assertEqual((receipt["decision"], receipt["code"]),
                         ("rejected", "AUTHORITY_DENIED"))
        # A former owner after transfer: transfer needs a grant-holding target.
        grants = publishing_compensation_grants()
        grants["agent2"] = {"work.manage", "content.publish", "content.unpublish"}
        runtime = Runtime(self.path, PublishingPolicy(), grants)
        self.send("transfer_owner", {"owner": "agent2", "reason": "reassign"},
                  actor="admin", runtime=runtime)
        receipt = self.unpublish(target, runtime=runtime, command_id="by-former")
        self.assertEqual((receipt["decision"], receipt["code"]),
                         ("rejected", "AUTHORITY_DENIED"))
        # The new owner with the grant re-admits inside the window.
        receipt = self.unpublish(target, runtime=runtime, actor="agent2",
                                 command_id="by-new-owner")
        self.assertEqual(receipt["decision"], "accepted")
        # An owner whose grants lack the capability entirely (fresh store).
        no_unpublish = {actor: caps - {"content.unpublish"} if actor == "agent" else caps
                        for actor, caps in publishing_compensation_grants().items()}
        fresh = tempfile.TemporaryDirectory()
        self.addCleanup(fresh.cleanup)
        runtime2 = Runtime(str(Path(fresh.name) / "runtime.sqlite"),
                           PublishingPolicy(), no_unpublish)
        case = PublishingCompensationCase()
        case.path = runtime2.path
        case.runtime = runtime2
        case.work_id = "fresh-article"
        case.initialize("fresh-article")
        case.approve_and_confirm()
        other = case.propose_publish()["operation_id"]
        runtime2.dispatch(other, FakePublisher(str(Path(fresh.name) / "pub.sqlite")))
        case.request_cancel()
        receipt = case.unpublish(other)
        self.assertEqual((receipt["decision"], receipt["code"]),
                         ("rejected", "AUTHORITY_DENIED"))

    def test_retraction_replay_and_authority(self):
        target = self.confirmed_publish()
        self.request_cancel()
        decision_version = self.runtime.get_work(self.work_id)["state_version"]
        first = self.unpublish(target, command_id="unpub-once")

        def replay_command(runtime):
            work = runtime.get_work(self.work_id)
            return runtime.command("agent", "unpub-once", self.work_id,
                                   "propose_action", {
                                       "capability": "content.unpublish",
                                       "document_digest": work["document_digest"],
                                       "contract_revision": work["contract"]["revision"],
                                       "plan_revision": work["plan_revision"],
                                       "compensates": target}, decision_version)

        self.assertEqual(replay_command(self.runtime), first)
        # Grant loss: replay returns a fresh, unpersisted AUTHORITY_DENIED.
        grants = publishing_compensation_grants()
        grants["agent"] = grants["agent"] - {"content.unpublish"}
        runtime = Runtime(self.path, PublishingPolicy(), grants)
        denied = replay_command(runtime)
        self.assertEqual((denied["decision"], denied["code"]),
                         ("rejected", "AUTHORITY_DENIED"))
        # Restore: the stored receipt replays verbatim again.
        self.assertEqual(replay_command(self.runtime), first)

    def test_republish_after_retraction_unreachable_governed(self):
        # RF4 reachability evidence, both refusal legs of the governed flow.
        target = self.confirmed_publish()
        self.request_cancel()
        retraction = self.unpublish(target)["operation_id"]
        resolved = self.runtime.dispatch(retraction, FakePublisher(self.publisher_path))
        self.assertEqual(resolved["status"], "confirmed_succeeded")
        # Same-work leg: the permanent intent refuses any forward re-publish.
        receipt = self.propose_publish(command_id="republish-same-work")
        self.assertEqual((receipt["decision"], receipt["code"]),
                         ("rejected", "CANCELLATION_ACTIVE"))
        # Cross-work leg: identical content collides on the store-global
        # forward business key (digest embeds no work id).
        other_work = "article-cross"
        self.send("create_work", {"document": article()}, work_id=other_work)
        self.send("bind_contract", {"policy_id": "content-publish",
                                    "policy_version": "demo-1",
                                    "goal": "content.published"}, work_id=other_work)
        self.send("revise_plan", {"steps": ["review", "confirm", "publish"],
                                  "open_requirements": ["C02"],
                                  "replan_when": []}, work_id=other_work)
        self.approve_and_confirm(work_id=other_work)
        receipt = self.propose_publish(work_id=other_work)
        self.assertEqual((receipt["decision"], receipt["code"]),
                         ("rejected", "OPERATION_CONTENT_CONFLICT"))


if __name__ == "__main__":
    unittest.main()
