"""S9 accepted-evidence collision: intake reservation and legacy recovery.

Pins the ratified D38–D42 core semantics
(docs/superpowers/specs/2026-10-15-td1-accepted-evidence-collision-design.md,
summarized in docs/runtime-boundaries.md): accepted-source operation-id
intake is rejected OPERATION_ID_RESERVED after unchanged authority and
old-row dedup/conflict precedence, and pre-fix poisoned stores resolve to
the actual accepted external result with an exact conflict snapshot
instead of failing the acceptance-proof INSERT.
"""

import tempfile
import unittest
import uuid
from pathlib import Path

from work_runtime import CommandError, ExpensePolicy, Runtime
from work_runtime.adapters import FakeOA
from work_runtime.demo import (action, demo_grants, document, initialize,
                               prerequisites, send)
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


if __name__ == "__main__":
    unittest.main()
