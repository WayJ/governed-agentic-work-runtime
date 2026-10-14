"""S9 accepted-evidence collision: intake reservation and legacy recovery.

Pins the ratified D38–D42 core semantics
(docs/superpowers/specs/2026-10-15-td1-accepted-evidence-collision-design.md,
summarized in docs/runtime-boundaries.md): accepted-source operation-id
intake is rejected OPERATION_ID_RESERVED after unchanged authority and
old-row dedup/conflict precedence, and pre-fix poisoned stores resolve to
the actual accepted external result with an exact conflict snapshot
instead of failing the acceptance-proof INSERT.
"""

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from work_runtime import CommandError, ExpensePolicy, Runtime
from work_runtime.adapters import FakeOA
from work_runtime.demo import (action, demo_grants, document, initialize,
                               prerequisites, send)
from work_runtime.policy import canonical, digest
from work_runtime.publishing import FakePublisher, PublishingPolicy
from work_runtime.publishing_demo import article, publishing_grants


def collision_grants():
    """Demo grants plus a granted accepted source.

    The poisoning actor must hold evidence.write: an ungranted "oa" is
    envelope-rejected before any admission check (independent review
    grounding), so the trusted-local collision requires a granted source.
    """
    grants = demo_grants()
    grants["oa"] = {"evidence.write"}
    return grants


class OverlapPolicy(ExpensePolicy):
    """Test-owned policy: the accepted source also serves duplicate_clear."""

    evidence_sources = {**ExpensePolicy.evidence_sources, "duplicate_clear": "oa"}


class RenamedAcceptedPolicy(ExpensePolicy):
    """Test-owned V2: the accepted source is renamed to oa2."""

    version = "demo-2"
    evidence_sources = {**ExpensePolicy.evidence_sources, "accepted": "oa2"}


def legacy_poison(path, work_id, op_id, *, actor="oa", kind="accepted", data=None,
                  status="pending_verification", body=None, fingerprint=None):
    """Insert a pre-fix poisoned evidence row by direct SQL (D40 B-fixture).

    Post-fix the product rejects this intake (OPERATION_ID_RESERVED), so
    tests construct the legacy store directly with the canonical `_receive`
    row shape from accepted original inputs: five columns, fingerprint
    digest([work_id, payload]) and the candidate body. Clearly a legacy
    fixture — no product bypass exists.
    """
    payload = {"event_id": op_id, "kind": kind,
               "data": data if data is not None else {}}
    if fingerprint is None:
        fingerprint = digest([work_id, payload])
    candidate = {"id": uuid.uuid4().hex, "source": actor, "event_id": op_id,
                 "kind": kind, "data": payload["data"], "status": status}
    if body is not None:
        candidate = body
    db = sqlite3.connect(path)
    try:
        db.execute("INSERT INTO evidence VALUES (?,?,?,?,?)",
                   (actor, op_id, work_id, fingerprint, canonical(candidate)))
        db.commit()
    finally:
        db.close()
    return candidate


def evidence_row(path, source, event_id):
    db = sqlite3.connect(path)
    try:
        return db.execute(
            "SELECT source,event_id,work_id,fingerprint,body FROM evidence "
            "WHERE source=? AND event_id=?", (source, event_id)).fetchone()
    finally:
        db.close()


def conflict_events(path, work_id):
    """Parsed AcceptanceProofConflict event bodies for one work, in order."""
    db = sqlite3.connect(path)
    try:
        return [json.loads(row[0]) for row in db.execute(
            "SELECT body FROM events WHERE work_id=? AND "
            "type='AcceptanceProofConflict' ORDER BY seq", (work_id,))]
    finally:
        db.close()


def store_snapshot(path):
    """All six tables' full contents for byte-preservation/rollback asserts."""
    db = sqlite3.connect(path)
    try:
        return {table: sorted(db.execute("SELECT * FROM %s" % table).fetchall())
                for table in ("works", "commands", "evidence", "operations",
                              "events", "metadata")}
    finally:
        db.close()


def rewrite_work(path, work_id, work):
    """Custom legacy-fixture helper: overwrite one work's stored state."""
    db = sqlite3.connect(path)
    try:
        db.execute("UPDATE works SET state=? WHERE id=?",
                   (canonical(work), work_id))
        db.commit()
    finally:
        db.close()


def crash_worker(runtime_path, oa_path, operation_id):
    """Real child process death after external acceptance (exit 73)."""
    return subprocess.run([sys.executable, "-m", "work_runtime", "worker",
                           "--runtime", runtime_path, "--oa", oa_path,
                           "--operation", operation_id,
                           "--crash-after-effect"], check=False)


SNAPSHOT_FIELDS = {"source", "event_id", "evidence_id", "evidence_work_id",
                   "evidence_kind", "evidence_status", "evidence_fingerprint",
                   "external_id", "document_digest"}


class CollisionCase(unittest.TestCase):
    """Two initialized works with distinct invoices; ops go under 'other'."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        self.oa_path = str(Path(self.temp.name) / "oa.sqlite")
        self.grants = collision_grants()
        self.runtime = Runtime(self.path, ExpensePolicy(), self.grants)
        self.oa = FakeOA(self.oa_path)
        initialize(self.runtime, "demo", document(invoice_id="INV-001"))
        initialize(self.runtime, "other",
                   document(document_id="EXP-002", invoice_id="INV-002"))
        prerequisites(self.runtime, "demo")
        prerequisites(self.runtime, "other")

    def record(self, runtime, actor, work_id, kind, data, event_id,
               command_id=None):
        return runtime.command(actor, command_id or uuid.uuid4().hex, work_id,
                               "record_evidence",
                               {"event_id": event_id, "kind": kind, "data": data})

    def submit_other(self):
        receipt = action(self.runtime, "other")
        self.assertEqual(receipt["decision"], "accepted")
        return receipt["operation_id"]


class IntakeReservationTests(CollisionCase):
    def test_operation_id_intake_rejected_for_accepted_source(self):
        receipt = action(self.runtime, "demo")
        self.assertEqual(receipt["decision"], "accepted")
        op = receipt["operation_id"]
        digest_value = self.runtime.get_work("demo")["document_digest"]
        fresh = self.record(self.runtime, "oa", "demo", "accepted",
                            {"digest": digest_value, "external_id": "OA-1"},
                            "fresh-import-1")
        self.assertEqual(fresh["decision"], "accepted")  # fresh ids stay valid
        self.assertEqual(fresh["evidence_status"], "pending_verification")
        reserved = self.record(self.runtime, "oa", "demo", "accepted",
                               {"digest": digest_value}, op)
        self.assertEqual(reserved["decision"], "rejected")
        self.assertEqual(reserved["code"], "OPERATION_ID_RESERVED")
        self.assertEqual(reserved["blockers"], [op])
        self.assertEqual(reserved["observed_state_version"],
                         self.runtime.get_work("demo")["state_version"])

    def test_reservation_is_global_across_works(self):
        op = self.submit_other()  # stored under work 'other'
        digest_value = self.runtime.get_work("demo")["document_digest"]
        reserved = self.record(self.runtime, "oa", "demo", "accepted",
                               {"digest": digest_value}, op)
        self.assertEqual(reserved["decision"], "rejected")
        self.assertEqual(reserved["code"], "OPERATION_ID_RESERVED")
        self.assertEqual(reserved["blockers"], [op])

    def test_reservation_is_source_scoped_not_kind_scoped(self):
        op = self.submit_other()
        overlap = Runtime(self.path, OverlapPolicy(), self.grants)
        digest_value = overlap.get_work("demo")["document_digest"]
        # The accepted source never uses kind "accepted" here, yet the id is
        # reserved: the danger condition is source equality, not the kind.
        reserved = self.record(overlap, "oa", "demo", "duplicate_clear",
                               {"digest": digest_value}, op)
        self.assertEqual(reserved["decision"], "rejected")
        self.assertEqual(reserved["code"], "OPERATION_ID_RESERVED")
        # An unrelated source may record the very same id under its kind.
        control = self.record(overlap, "invoice-service", "demo", "invoice_valid",
                              {"invoice_id": "INV-001", "invoice_revision": 1,
                               "valid": True}, op)
        self.assertEqual(control["decision"], "accepted")

    def test_registry_union_spans_loaded_versions(self):
        op = self.submit_other()
        grants = collision_grants()
        grants["oa2"] = {"evidence.write"}
        grants["root"] = {"work.intervene"}
        registry_runtime = Runtime(self.path, ExpensePolicy(), grants,
                                   policies={"demo-2": RenamedAcceptedPolicy()})
        send(registry_runtime, "v2work", "create_work",
             {"document": document(document_id="EXP-003", invoice_id="INV-003")})
        send(registry_runtime, "v2work", "bind_contract",
             {"policy_id": "expense-submit", "policy_version": "demo-1",
              "goal": "expense.accepted"})
        send(registry_runtime, "v2work", "migrate_policy",
             {"policy_id": "expense-submit", "policy_version": "demo-2",
              "reason": "accepted source renamed"}, actor="root")
        digest_value = registry_runtime.get_work("v2work")["document_digest"]
        # A runtime serving both versions reserves both accepted actors:
        # V1-pinned works still resolve (and INSERT) under oa.
        old_source = self.record(registry_runtime, "oa", "demo", "accepted",
                                 {"digest": digest_value}, op)
        self.assertEqual(old_source["decision"], "rejected")
        self.assertEqual(old_source["code"], "OPERATION_ID_RESERVED")
        new_source = self.record(registry_runtime, "oa2", "v2work", "accepted",
                                 {"digest": digest_value}, op)
        self.assertEqual(new_source["decision"], "rejected")
        self.assertEqual(new_source["code"], "OPERATION_ID_RESERVED")
        # A registry that does not load V1 keeps the existing fail-closed
        # rule for V1-pinned works; the shrunken union stays sound.
        v2_only = Runtime(self.path, RenamedAcceptedPolicy(), grants)
        with self.assertRaises(CommandError):
            v2_only.get_work("demo")
        still_reserved = self.record(v2_only, "oa2", "v2work", "accepted",
                                     {"digest": digest_value}, op)
        self.assertEqual(still_reserved["decision"], "rejected")
        self.assertEqual(still_reserved["code"], "OPERATION_ID_RESERVED")

    def test_reservation_union_recomputed_per_intake(self):
        op = self.submit_other()
        policy = ExpensePolicy()
        self.grants["oa3"] = {"evidence.write"}
        runtime = Runtime(self.path, policy, self.grants)
        digest_value = runtime.get_work("demo")["document_digest"]
        unmapped = self.record(runtime, "oa3", "demo", "accepted",
                               {"digest": digest_value}, op)
        self.assertEqual(unmapped["decision"], "rejected")
        self.assertEqual(unmapped["code"], "AUTHORITY_DENIED")
        # Trusted-local reconfiguration of the live default policy object:
        # the union must follow on the next intake, not stay frozen at init.
        policy.evidence_sources = {**policy.evidence_sources, "accepted": "oa3"}
        reserved = self.record(runtime, "oa3", "demo", "accepted",
                               {"digest": digest_value}, op)
        self.assertEqual(reserved["decision"], "rejected")
        self.assertEqual(reserved["code"], "OPERATION_ID_RESERVED")


class PublishingCollisionCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        self.publisher_path = str(Path(self.temp.name) / "publisher.sqlite")
        self.grants = publishing_grants()
        self.grants["publisher"] = {"evidence.write"}
        self.runtime = Runtime(self.path, PublishingPolicy(), self.grants)
        self.publisher = FakePublisher(self.publisher_path)

    def publish_intent(self, work_id="article-1"):
        send(self.runtime, work_id, "create_work", {"document": article()})
        send(self.runtime, work_id, "bind_contract",
             {"policy_id": "content-publish", "policy_version": "demo-1",
              "goal": "content.published"})
        digest_value = self.runtime.get_work(work_id)["document_digest"]
        send(self.runtime, work_id, "record_evidence",
             {"event_id": "review-1", "kind": "approval",
              "data": {"digest": digest_value}}, actor="reviewer")
        send(self.runtime, work_id, "record_evidence",
             {"event_id": "confirm-1", "kind": "confirmation",
              "data": {"digest": digest_value}}, actor="author")
        self.runtime.verify_pending(work_id)
        work = self.runtime.get_work(work_id)
        receipt = send(self.runtime, work_id, "propose_action", {
            "capability": "content.publish",
            "document_digest": work["document_digest"],
            "contract_revision": work["contract"]["revision"],
            "plan_revision": work["plan_revision"]})
        self.assertEqual(receipt["decision"], "accepted")
        return receipt["operation_id"]

    def record(self, actor, work_id, kind, data, event_id):
        return self.runtime.command(actor, uuid.uuid4().hex, work_id,
                                    "record_evidence",
                                    {"event_id": event_id, "kind": kind,
                                     "data": data})


class PublishingReservationTests(PublishingCollisionCase):
    def test_publishing_operation_id_intake_rejected(self):
        op = self.publish_intent()
        digest_value = self.runtime.get_work("article-1")["document_digest"]
        fresh = self.record("publisher", "article-1", "accepted",
                            {"digest": digest_value, "external_id": "PUB-1"},
                            "fresh-1")
        self.assertEqual(fresh["decision"], "accepted")
        reserved = self.record("publisher", "article-1", "accepted",
                               {"digest": digest_value}, op)
        self.assertEqual(reserved["decision"], "rejected")
        self.assertEqual(reserved["code"], "OPERATION_ID_RESERVED")
        self.assertEqual(reserved["blockers"], [op])


class LegacyConflictTests(CollisionCase):
    """Pre-fix poisoned stores resolve to actual truth with a conflict snapshot."""

    def submit_poisoned(self, data=None, *, work_id="demo", status="pending_verification"):
        """A dispatched poisoned operation plus its legacy conflicting row."""
        op = self.submit_other()
        digest_value = self.runtime.get_work(work_id)["document_digest"]
        candidate = legacy_poison(self.path, work_id, op, data=data,
                                  status=status)
        return op, candidate

    def test_legacy_poisoned_store_resolves_with_proof_conflict(self):
        op, candidate = self.submit_poisoned(
            data={"digest": self.runtime.get_work("demo")["document_digest"]})
        before = evidence_row(self.path, "oa", op)
        rows_before = len(store_snapshot(self.path)["evidence"])
        resolved = self.runtime.dispatch(op, self.oa)
        # The external acceptance is real and authoritative (D41): the
        # operation records it; nothing is parked as unknown.
        self.assertEqual(resolved["status"], "confirmed_succeeded")
        self.assertEqual(resolved["dispatch_state"], "finished")
        self.assertTrue(resolved["external_id"])
        self.assertEqual(len(resolved["attempts"]), 1)
        self.assertEqual(resolved["attempts"][-1]["status"], "confirmed_succeeded")
        self.assertEqual(self.oa.accepted_count(), 1)
        # The nine-field additive snapshot separates candidate from result.
        snapshot = resolved["proof_conflict"]
        self.assertEqual(set(snapshot), SNAPSHOT_FIELDS)
        self.assertEqual(snapshot["source"], "oa")
        self.assertEqual(snapshot["event_id"], op)
        self.assertEqual(snapshot["evidence_id"], candidate["id"])
        self.assertEqual(snapshot["evidence_work_id"], "demo")
        self.assertEqual(snapshot["evidence_kind"], "accepted")
        self.assertEqual(snapshot["evidence_status"], "pending_verification")
        self.assertEqual(snapshot["evidence_fingerprint"],
                         digest(["demo", {"event_id": op, "kind": "accepted",
                                          "data": candidate["data"]}]))
        self.assertEqual(snapshot["external_id"], resolved["external_id"])
        self.assertEqual(snapshot["document_digest"], resolved["document_digest"])
        self.assertNotEqual(snapshot["document_digest"],
                            candidate["data"]["digest"])
        # Attention surfaces on the operation's work; one conflict event
        # replaces OperationResolved for this resolution.
        self.assertEqual(self.runtime.get_work("other")["status"],
                         "needs_attention")
        events = conflict_events(self.path, "other")
        self.assertEqual(len(events), 1)
        body = events[0]
        self.assertEqual(set(body), SNAPSHOT_FIELDS | {"operation_id",
                                                       "work_was_closed"})
        self.assertFalse(body["work_was_closed"])
        self.assertEqual(body["operation_id"], op)
        for field in snapshot:
            self.assertEqual(body[field], snapshot[field])
        db = sqlite3.connect(self.path)
        resolved_events = db.execute(
            "SELECT body FROM events WHERE work_id='other' AND "
            "type='OperationResolved'").fetchall()
        db.close()
        self.assertEqual([e for e in resolved_events
                          if json.loads(e[0])["operation_id"] == op], [])
        # The conflicting candidate is untouched and no proof was inserted.
        self.assertEqual(evidence_row(self.path, "oa", op), before)
        self.assertEqual(len(store_snapshot(self.path)["evidence"]), rows_before)

    def test_conflict_snapshot_records_row_status_at_resolution(self):
        digest_value = self.runtime.get_work("demo")["document_digest"]
        self.grants["root"] = {"work.intervene"}
        variants = (
            ("verified", {"digest": digest_value, "external_id": "OA-x"},
             "verified"),
            ("invalid", {"digest": digest_value}, "invalid"),
            ("revoked", {"digest": digest_value, "external_id": "OA-x"},
             "revoked"),
        )
        for index, (label, data, expected) in enumerate(variants):
            with self.subTest(variant=label):
                work_id = "variant-%d" % index
                initialize(self.runtime, work_id,
                           document(document_id="EXP-V%d" % index,
                                    invoice_id="INV-V%d" % index))
                prerequisites(self.runtime, work_id)
                op = action(self.runtime, work_id)["operation_id"]
                legacy_poison(self.path, "demo", op, data=data)
                self.runtime.verify_pending("demo")
                if label == "revoked":
                    version = self.runtime.get_work("demo")["state_version"]
                    receipt = self.runtime.command(
                        "root", uuid.uuid4().hex, "demo", "revoke_evidence",
                        {"source": "oa", "event_id": op, "reason": "withdrawn"},
                        version)
                    self.assertEqual(receipt["decision"], "accepted")
                before = evidence_row(self.path, "oa", op)
                resolved = self.runtime.dispatch(op, self.oa)
                self.assertEqual(resolved["status"], "confirmed_succeeded")
                self.assertEqual(resolved["proof_conflict"]["evidence_status"],
                                 expected)
                self.assertEqual(evidence_row(self.path, "oa", op), before)

    def test_recover_liveness_after_conflict(self):
        op = self.submit_other()
        legacy_poison(self.path, "demo", op,
                      data={"digest": self.runtime.get_work("demo")["document_digest"]})
        self.assertEqual(crash_worker(self.path, self.oa_path, op).returncode, 73)
        initialize(self.runtime, "third",
                   document(document_id="EXP-003", invoice_id="INV-003"))
        prerequisites(self.runtime, "third")
        later = action(self.runtime, "third")["operation_id"]
        results = self.runtime.recover(self.oa)  # Today: IntegrityError, starvation.
        by_id = {r["id"]: r for r in results}
        self.assertEqual(by_id[op]["status"], "confirmed_succeeded")
        self.assertIn("proof_conflict", by_id[op])
        self.assertEqual(len(conflict_events(self.path, "other")), 1)
        self.assertEqual(by_id[later]["status"], "confirmed_succeeded")
        self.assertEqual(self.oa.accepted_count(), 2)

    def test_conflict_resolution_crash_atomic_exception(self):
        op = self.submit_other()
        legacy_poison(self.path, "demo", op,
                      data={"digest": self.runtime.get_work("demo")["document_digest"]})

        def explode():
            raise RuntimeError("death between effect and resolution")
        with self.assertRaises(RuntimeError):
            self.runtime.dispatch(op, self.oa, fault=explode)
        # External effect committed; no resolution writes survived.
        self.assertEqual(self.oa.accepted_count(), 1)
        self.assertEqual(self.runtime.get_operation(op)["status"], "dispatched")
        self.assertEqual(conflict_events(self.path, "other"), [])
        resolved = self.runtime.reconcile(op, self.oa)
        self.assertEqual(resolved["status"], "confirmed_succeeded")
        self.assertIn("proof_conflict", resolved)
        self.assertEqual(len(conflict_events(self.path, "other")), 1)
        self.assertEqual(self.oa.accepted_count(), 1)

    def test_conflict_resolution_real_process_death(self):
        op = self.submit_other()
        legacy_poison(self.path, "demo", op,
                      data={"digest": self.runtime.get_work("demo")["document_digest"]})
        script = (
            "import os,sys\n"
            "from work_runtime import Runtime, ExpensePolicy\n"
            "from work_runtime.adapters import FakeOA\n"
            "from work_runtime.demo import demo_grants\n"
            "class Dying(Runtime):\n"
            "    # Test-owned subclass: real process death inside the\n"
            "    # conflict-resolution transaction, after the operation write.\n"
            "    def _save_op(self, db, operation):\n"
            "        if 'proof_conflict' in operation:\n"
            "            os._exit(76)\n"
            "        return Runtime._save_op(self, db, operation)\n"
            "grants = demo_grants(); grants['oa'] = {'evidence.write'}\n"
            "Dying(sys.argv[1], ExpensePolicy(), grants).dispatch(\n"
            "    sys.argv[2], FakeOA(sys.argv[3]))\n"
        )
        child = subprocess.run([sys.executable, "-c", script, self.path, op,
                                self.oa_path], check=False)
        self.assertEqual(child.returncode, 76)
        # The whole resolution transaction rolled back with the process.
        self.assertEqual(self.oa.accepted_count(), 1)
        op_after = self.runtime.get_operation(op)
        self.assertEqual(op_after["status"], "dispatched")
        self.assertNotIn("proof_conflict", op_after)
        self.assertEqual(conflict_events(self.path, "other"), [])
        # Recovery redoes the resolution deterministically, exactly once.
        restarted = Runtime(self.path, ExpensePolicy(), collision_grants())
        restarted.recover(self.oa)
        self.assertEqual(self.runtime.get_operation(op)["status"],
                         "confirmed_succeeded")
        self.assertEqual(len(conflict_events(self.path, "other")), 1)
        self.assertEqual(self.oa.accepted_count(), 1)

    def test_accepted_lost_response_conflict_recovery_confirms_once(self):
        op = self.submit_other()
        legacy_poison(self.path, "demo", op,
                      data={"digest": self.runtime.get_work("demo")["document_digest"]})
        unknown = self.runtime.dispatch(op, FakeOA(self.oa_path,
                                                    timeout_after_commit=True))
        self.assertEqual(unknown["status"], "outcome_unknown")
        self.assertEqual(self.oa.accepted_count(), 1)
        resolved = self.runtime.reconcile(op, self.oa)
        self.assertEqual(resolved["status"], "confirmed_succeeded")
        self.assertIn("proof_conflict", resolved)
        self.assertEqual(len(conflict_events(self.path, "other")), 1)
        self.assertEqual(self.oa.accepted_count(), 1)
        again = self.runtime.reconcile(op, self.oa)
        self.assertEqual(again["status"], "confirmed_succeeded")
        self.assertEqual(len(conflict_events(self.path, "other")), 1)

    def test_closed_work_conflict_preserves_closure(self):
        op = self.submit_other()
        legacy_poison(self.path, "demo", op,
                      data={"digest": self.runtime.get_work("demo")["document_digest"]})
        self.assertEqual(crash_worker(self.path, self.oa_path, op).returncode, 73)
        # Custom legacy fixture: public closure paths gate on
        # OUTCOME_UNRESOLVED, so a closed work with a dispatched operation
        # only exists in a directly written store.
        work = self.runtime.get_work("other")
        work["status"], work["outcome"] = "closed", "succeeded"
        work["completion"] = {"contract": work["contract"],
                              "document_digest": work["document_digest"],
                              "evidence": []}
        rewrite_work(self.path, "other", work)
        resolved = self.runtime.reconcile(op, self.oa)
        self.assertEqual(resolved["status"], "confirmed_succeeded")
        after = self.runtime.get_work("other")
        self.assertEqual(after["status"], "closed")
        self.assertEqual(after["outcome"], "succeeded")
        self.assertEqual(after["completion"], work["completion"])
        events = conflict_events(self.path, "other")
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["work_was_closed"])

    def test_malformed_conflict_body_degrades_to_null(self):
        def body(**overrides):
            candidate = {"id": "e-%d" % (len(overrides) or 0), "source": "oa",
                         "event_id": "x", "kind": "accepted", "data": {},
                         "status": "pending_verification"}
            candidate.update(overrides)
            return candidate
        cases = [
            ("wrong-type id", body(id=7), (None, "accepted", "pending_verification")),
            ("missing id", {k: v for k, v in body().items() if k != "id"},
             (None, "accepted", "pending_verification")),
            ("none kind", body(kind=None), ("e-1", None, "pending_verification")),
            ("wrong-type status", body(status=123), ("e-1", "accepted", None)),
            ("non-object body", ["not", "a", "dict"], (None, None, None)),
        ]
        for index, (label, row_body, expected) in enumerate(cases):
            with self.subTest(variant=label):
                work_id = "malformed-%d" % index
                initialize(self.runtime, work_id,
                           document(document_id="EXP-M%d" % index,
                                    invoice_id="INV-M%d" % index))
                prerequisites(self.runtime, work_id)
                op = action(self.runtime, work_id)["operation_id"]
                legacy_poison(self.path, "demo", op, body=row_body,
                              fingerprint="fp-%d" % index)
                before = evidence_row(self.path, "oa", op)
                resolved = self.runtime.dispatch(op, self.oa)
                self.assertEqual(resolved["status"], "confirmed_succeeded")
                snapshot = resolved["proof_conflict"]
                self.assertEqual(set(snapshot), SNAPSHOT_FIELDS)
                self.assertEqual((snapshot["evidence_id"],
                                  snapshot["evidence_kind"],
                                  snapshot["evidence_status"]), expected)
                # SQL columns stay verbatim; the row itself is untouched.
                self.assertEqual(snapshot["evidence_work_id"], "demo")
                self.assertEqual(snapshot["evidence_fingerprint"], "fp-%d" % index)
                self.assertEqual(evidence_row(self.path, "oa", op), before)


class PublishingLegacyConflictTests(PublishingCollisionCase):
    def test_publishing_legacy_conflict_resolves(self):
        op = self.publish_intent()
        legacy_poison(self.path, "article-1", op, actor="publisher",
                      data={"digest": self.runtime.get_work("article-1")["document_digest"]})
        before = evidence_row(self.path, "publisher", op)
        resolved = self.runtime.dispatch(op, self.publisher)
        self.assertEqual(resolved["status"], "confirmed_succeeded")
        self.assertEqual(resolved["dispatch_state"], "finished")
        snapshot = resolved["proof_conflict"]
        self.assertEqual(set(snapshot), SNAPSHOT_FIELDS)
        self.assertEqual(snapshot["source"], "publisher")
        self.assertEqual(snapshot["event_id"], op)
        self.assertEqual(snapshot["evidence_work_id"], "article-1")
        self.assertEqual(snapshot["evidence_status"], "pending_verification")
        self.assertEqual(self.runtime.get_work("article-1")["status"],
                         "needs_attention")
        events = conflict_events(self.path, "article-1")
        self.assertEqual(len(events), 1)
        body = events[0]
        self.assertEqual(set(body), SNAPSHOT_FIELDS | {"operation_id",
                                                       "work_was_closed"})
        self.assertFalse(body["work_was_closed"])
        self.assertEqual(evidence_row(self.path, "publisher", op), before)
        self.assertEqual(self.publisher.published_count(), 1)


if __name__ == "__main__":
    unittest.main()
