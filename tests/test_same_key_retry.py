"""Declared, verified same-key idempotent retry for unknown native outcomes.

An unknown outcome is never re-dispatched on the strength of "the row is
absent" or "the platform refused": absence is not evidence of settlement,
and a rejection is not a bound receipt. The only justification for sending
again is the adapter owner's declared, service-verified promise that the
effect is deduplicated by its business key: one retry, same operation, same
key, same frozen document, with the unknown history preserved.
"""

import dataclasses
import json
import secrets
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from work_runtime import Runtime
from work_runtime.ingress import SignedEvidenceGateway, sign_evidence
from work_runtime.policy import digest
from work_runtime.publishing import FakePublisher, PublishingPolicy

from test_publishing import article, publishing_grants, requirement


DECLARED = dataclasses.replace(
    FakePublisher.contract,
    same_key_idempotent_retry_actions=("content.publish",))


class DeclaredPublisher:
    """Real publisher behaviour carrying the same-key retry declaration."""

    contract = DECLARED

    def __init__(self, path, **kwargs):
        self.inner = FakePublisher(path, **kwargs)

    def execute(self, *args, **kwargs):
        return self.inner.execute(*args, **kwargs)

    def lookup(self, *args):
        return self.inner.lookup(*args)


class NeverReached:
    """The external call never lands (transport lost before the effect)."""

    def __init__(self, contract):
        self.contract = contract
        self.executed = 0

    def execute(self, *args, **kwargs):
        self.executed += 1
        raise OSError("connection lost before the effect")

    def lookup(self, *args):
        return None


class LookupUnavailable(NeverReached):
    """Lookup raises: availability of the answer is not the safety basis."""

    def lookup(self, *args):
        raise OSError("lookup unavailable")


class SameKeyRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        self.publisher_path = str(Path(self.temp.name) / "publisher.sqlite")
        self.now = 2000000000
        self.reviewer_key = secrets.token_bytes(32)
        self.author_key = secrets.token_bytes(32)
        self.runtime = self.fresh_runtime()
        self.work_id = "article-1"
        self.gateway = SignedEvidenceGateway(
            self.runtime, {"reviewer": self.reviewer_key, "author": self.author_key},
            clock=lambda: self.now)

    def fresh_runtime(self, grants=None):
        return Runtime(self.path, PublishingPolicy(), grants or publishing_grants())

    def send(self, kind, payload=None, actor="agent", command_id=None):
        version = None if kind in ("create_work", "record_evidence") \
            else self.runtime.get_work(self.work_id)["state_version"]
        return self.runtime.command(actor, command_id or uuid.uuid4().hex,
                                    self.work_id, kind, payload, version)

    def initialize(self):
        self.send("create_work", {"document": article(requires_review=True)})
        self.send("bind_contract", {"policy_id": "content-publish",
                                    "policy_version": "demo-1",
                                    "goal": "content.published"})
        self.send("revise_plan", {"steps": ["draft", "review", "confirm", "publish"],
                                  "open_requirements": ["C02"],
                                  "replan_when": ["reviewer rejects"]})

    def signed(self, source, secret, kind, data):
        return sign_evidence(secret, {
            "source": source, "command_id": uuid.uuid4().hex,
            "work_id": self.work_id, "event_id": uuid.uuid4().hex,
            "kind": kind, "data": data, "issued_at": self.now})

    def approve_and_confirm(self):
        current = self.runtime.get_work(self.work_id)["document_digest"]
        self.gateway.record(self.signed("reviewer", self.reviewer_key, "approval",
                                        {"digest": current}))
        self.gateway.record(self.signed("author", self.author_key, "confirmation",
                                        {"digest": current}))
        self.runtime.verify_pending(self.work_id)

    def ready_operation(self, command_id="publish-once"):
        self.initialize()
        self.approve_and_confirm()
        return self.send("propose_action", {
            "capability": "content.publish",
            "document_digest": self.runtime.get_work(self.work_id)["document_digest"],
            "contract_revision": self.runtime.get_work(self.work_id)["contract"]["revision"],
            "plan_revision": self.runtime.get_work(self.work_id)["plan_revision"],
        }, command_id=command_id)["operation_id"]

    def quarantined_operation(self, adapter, command_id="publish-once"):
        operation = self.ready_operation(command_id)
        unknown = self.runtime.dispatch(operation, adapter)
        self.assertEqual(unknown["status"], "outcome_unknown")
        return operation

    def requirement(self, rule_id):
        return requirement(self.runtime.get_work(self.work_id)["requirements"], rule_id)

    def work_events(self):
        with sqlite3.connect(self.path) as db:
            return [r[0] for r in db.execute(
                "SELECT type FROM events WHERE work_id=?", (self.work_id,))]

    # -- the retry itself -------------------------------------------------

    def test_declared_absent_lookup_rearms_the_same_operation_once(self):
        adapter = NeverReached(DECLARED)
        operation = self.quarantined_operation(adapter)
        # A lost dispatch leaves the operation unknown; the work itself is
        # quarantined only when a reconcile finds no authoritative result.
        self.assertEqual(self.runtime.get_work(self.work_id)["status"], "active")
        self.runtime.reconcile(operation, NeverReached(FakePublisher.contract))
        self.assertEqual(self.runtime.get_work(self.work_id)["status"],
                         "needs_attention")
        before = self.runtime.get_operation(operation)
        rearmed = self.runtime.reconcile(operation, adapter)
        self.assertEqual((rearmed["status"], rearmed["dispatch_state"],
                          rearmed["reason"]),
                         ("prepared", "ready", "SAME_KEY_RETRY_ARMED"))
        stored = self.runtime.get_operation(operation)
        # Same operation, same key, same frozen document; the unknown history
        # is preserved, not overwritten.
        self.assertEqual(stored["id"], operation)
        self.assertEqual(stored["business_key"], before["business_key"])
        self.assertEqual(stored["document_digest"], before["document_digest"])
        self.assertEqual(stored["contract_revision"], before["contract_revision"])
        self.assertEqual(stored["plan_revision"], before["plan_revision"])
        self.assertEqual([entry["reason"] for entry in stored["unknown_history"]],
                         ["OSError", "NO_AUTHORITATIVE_RESULT"])
        self.assertIn("SameKeyRetryArmed", self.work_events())
        # The attention was produced by this operation's own quarantine and
        # nothing else of the work is unresolved: routing resumes.
        self.assertEqual(self.runtime.get_work(self.work_id)["status"], "active")
        # The armed retry dispatches through the ordinary gates and succeeds;
        # the external effect happens exactly once.
        publisher = DeclaredPublisher(self.publisher_path)
        resolved = self.runtime.dispatch(operation, publisher)
        self.assertEqual(resolved["status"], "confirmed_succeeded")
        self.assertEqual(publisher.inner.published_count(), 1)
        self.assertEqual(self.requirement("C04")["fulfillment"], "satisfied")

    def test_lookup_unavailability_consumes_the_same_single_retry(self):
        adapter = LookupUnavailable(DECLARED)
        operation = self.quarantined_operation(adapter)
        rearmed = self.runtime.reconcile(operation, adapter)
        self.assertEqual((rearmed["status"], rearmed["reason"]),
                         ("prepared", "SAME_KEY_RETRY_ARMED"))

    def test_budget_is_one_and_survives_a_restart(self):
        adapter = NeverReached(DECLARED)
        operation = self.quarantined_operation(adapter)
        self.runtime.reconcile(operation, adapter)
        # The armed retry is dispatched and lost again.
        again = self.runtime.dispatch(operation, NeverReached(DECLARED))
        self.assertEqual(again["status"], "outcome_unknown")
        exhausted = self.runtime.reconcile(operation, NeverReached(DECLARED))
        self.assertEqual((exhausted["status"], exhausted["reason"]),
                         ("outcome_unknown", "NO_AUTHORITATIVE_RESULT"))
        self.assertEqual(self.runtime.get_work(self.work_id)["status"],
                         "needs_attention")
        # A restart neither forgets the spent budget nor rearms again.
        restarted = self.fresh_runtime()
        still = restarted.reconcile(operation, NeverReached(DECLARED))
        self.assertEqual(still["status"], "outcome_unknown")
        self.assertEqual(still["dispatch_state"], "in_flight")

    def test_receipt_on_lookup_resolves_without_the_retry_path(self):
        flaky = DeclaredPublisher(self.publisher_path, timeout_after_commit=True)
        operation = self.quarantined_operation(flaky)
        recovered = self.runtime.reconcile(operation, DeclaredPublisher(self.publisher_path))
        self.assertEqual(recovered["status"], "confirmed_succeeded")
        stored = self.runtime.get_operation(operation)
        self.assertNotIn("same_key_retries", stored)
        self.assertEqual(DeclaredPublisher(self.publisher_path).inner.published_count(), 1)

    # -- what must NOT re-arm ----------------------------------------------

    def test_undeclared_adapter_keeps_the_quarantine(self):
        adapter = NeverReached(FakePublisher.contract)
        operation = self.quarantined_operation(adapter)
        kept = self.runtime.reconcile(operation, adapter)
        self.assertEqual((kept["status"], kept["reason"]),
                         ("outcome_unknown", "NO_AUTHORITATIVE_RESULT"))
        stored = self.runtime.get_operation(operation)
        self.assertEqual(stored["dispatch_state"], "in_flight")
        self.assertNotIn("same_key_retries", stored)
        self.assertNotIn("SameKeyRetryArmed", self.work_events())

    def test_capability_outside_the_declared_range_keeps_the_quarantine(self):
        other = dataclasses.replace(
            FakePublisher.contract,
            same_key_idempotent_retry_actions=("content.unpublish",))
        adapter = NeverReached(other)
        operation = self.quarantined_operation(adapter)
        kept = self.runtime.reconcile(operation, adapter)
        self.assertEqual((kept["status"], kept["reason"]),
                         ("outcome_unknown", "NO_AUTHORITATIVE_RESULT"))
        self.assertEqual(self.runtime.get_operation(operation)["dispatch_state"],
                         "in_flight")

    def test_attention_without_provable_attribution_is_preserved(self):
        adapter = NeverReached(DECLARED)
        operation = self.quarantined_operation(adapter)
        self.runtime.reconcile(operation, NeverReached(FakePublisher.contract))
        self.assertEqual(self.runtime.get_work(self.work_id)["status"],
                         "needs_attention")
        # A later, unrelated state change owns the work's most recent event:
        # the attention can no longer be attributed to this operation alone.
        self.send("revise_document", {"document": article(body="Revised meanwhile")})
        rearmed = self.runtime.reconcile(operation, adapter)
        self.assertEqual(rearmed["status"], "prepared")
        self.assertEqual(self.runtime.get_work(self.work_id)["status"],
                         "needs_attention")
        # The armed retry still passes the staleness gate: no second effect.
        guarded = self.runtime.dispatch(operation, NeverReached(DECLARED))
        self.assertEqual((guarded["dispatch_state"], guarded["reason"]),
                         ("cancelled", "STALE_INTENT"))
        self.assertEqual(adapter.executed, 1)

    # -- the armed retry still passes every dispatch gate -------------------

    def test_armed_retry_is_cancelled_by_a_revised_subject(self):
        adapter = NeverReached(DECLARED)
        operation = self.quarantined_operation(adapter)
        self.runtime.reconcile(operation, adapter)
        self.send("revise_document", {"document": article(body="Revised after review")})
        guarded = self.runtime.dispatch(operation, NeverReached(DECLARED))
        self.assertEqual((guarded["dispatch_state"], guarded["reason"]),
                         ("cancelled", "STALE_INTENT"))
        self.assertEqual(adapter.executed, 1)  # only the original lost attempt

    def test_armed_retry_respects_a_later_cancellation(self):
        adapter = NeverReached(DECLARED)
        operation = self.quarantined_operation(adapter)
        self.runtime.reconcile(operation, adapter)
        self.send("request_cancel", {"reason": "operator stopped the work"})
        guarded = self.runtime.dispatch(operation, adapter)
        self.assertEqual((guarded["dispatch_state"], guarded["reason"]),
                         ("cancelled", "WORK_CANCELLED"))
        self.assertEqual(adapter.executed, 1)

    def test_armed_retry_is_held_when_authority_was_revoked(self):
        adapter = NeverReached(DECLARED)
        operation = self.quarantined_operation(adapter)
        self.runtime.reconcile(operation, adapter)
        revoked = self.fresh_runtime({"agent": {"work.manage"},
                                      "reviewer": {"evidence.write"},
                                      "author": {"evidence.write"}})
        guarded = revoked.dispatch(operation, NeverReached(DECLARED))
        self.assertEqual((guarded["dispatch_state"], guarded["reason"]),
                         ("held", "AUTHORITY_DENIED"))
        self.assertEqual(guarded["status"], "prepared")  # held, not consumed


class BadReceipt:
    """The retry lands, but the receipt does not bind to the operation."""

    contract = DECLARED

    def __init__(self):
        self.executed = 0

    def execute(self, *args, **kwargs):
        self.executed += 1
        return {"status": "accepted", "external_id": "EXT-FORGED",
                "digest": "0" * 64}

    def lookup(self, *args):
        return None


class SameKeyRetryGateTests(SameKeyRetryTests):
    """The armed retry passes every ordinary gate; nothing may fake success."""

    def test_armed_retry_is_held_when_a_requirement_was_revoked(self):
        approval_id = uuid.uuid4().hex
        operation = self.ready_operation_with_approval(approval_id)
        adapter = NeverReached(DECLARED)
        self.assertEqual(self.runtime.dispatch(operation, adapter)["status"],
                         "outcome_unknown")
        self.runtime.reconcile(operation, NeverReached(FakePublisher.contract))
        rearmed = self.runtime.reconcile(operation, adapter)
        self.assertEqual(rearmed["status"], "prepared")
        # The reviewer withdraws the approval: the publish requirement is no
        # longer satisfied, so the retry must be held, not sent.
        revoked = self.fresh_runtime({"agent": {"work.manage", "content.publish"},
                                      "reviewer": {"evidence.write",
                                                   "evidence.revoke"},
                                      "author": {"evidence.write"}})
        receipt = revoked.command("reviewer", uuid.uuid4().hex, self.work_id,
                                  "revoke_evidence",
                                  {"source": "reviewer", "event_id": approval_id,
                                   "reason": "withdrawn"},
                                  revoked.get_work(self.work_id)["state_version"])
        self.assertEqual(receipt["decision"], "accepted", receipt)
        guarded = revoked.dispatch(operation, NeverReached(DECLARED))
        self.assertEqual((guarded["dispatch_state"], guarded["reason"]),
                         ("held", "REQUIREMENT_UNSATISFIED"))
        self.assertEqual(adapter.executed, 1)

    def ready_operation_with_approval(self, approval_id):
        self.initialize()
        current = self.runtime.get_work(self.work_id)["document_digest"]
        self.gateway.record(sign_evidence(self.reviewer_key, {
            "source": "reviewer", "command_id": uuid.uuid4().hex,
            "work_id": self.work_id, "event_id": approval_id,
            "kind": "approval", "data": {"digest": current},
            "issued_at": self.now}))
        self.gateway.record(self.signed("author", self.author_key, "confirmation",
                                        {"digest": current}))
        self.runtime.verify_pending(self.work_id)
        return self.send("propose_action", {
            "capability": "content.publish",
            "document_digest": current,
            "contract_revision": self.runtime.get_work(self.work_id)["contract"]["revision"],
            "plan_revision": self.runtime.get_work(self.work_id)["plan_revision"],
        })["operation_id"]

    def test_invalid_receipt_on_the_retry_is_quarantined_not_faked(self):
        adapter = NeverReached(DECLARED)
        operation = self.quarantined_operation(adapter)
        self.runtime.reconcile(operation, adapter)  # quarantine, then arm
        bad = BadReceipt()
        invalid = self.runtime.dispatch(operation, bad)
        self.assertEqual((invalid["status"], invalid["reason"]),
                         ("outcome_unknown", "ADAPTER_RESULT_INVALID"))
        self.assertEqual(bad.executed, 1)
        self.assertEqual(self.runtime.get_work(self.work_id)["status"],
                         "needs_attention")
        # The budget is spent: no second arm, no fake success.
        exhausted = self.runtime.reconcile(operation, NeverReached(DECLARED))
        self.assertEqual((exhausted["status"], exhausted["reason"]),
                         ("outcome_unknown", "NO_AUTHORITATIVE_RESULT"))
        self.assertEqual(self.runtime.get_operation(operation)["dispatch_state"],
                         "in_flight")

    def test_compensations_never_consume_the_same_key_retry(self):
        declared_both = dataclasses.replace(
            DECLARED, same_key_idempotent_retry_actions=("content.publish",
                                                         "content.unpublish"))
        # The paired retraction capability needs its own grant.
        self.runtime = self.fresh_runtime(
            {"agent": {"work.manage", "content.publish", "content.unpublish"},
             "reviewer": {"evidence.write"}, "author": {"evidence.write"}})
        forward = self.ready_operation()
        resolved = self.runtime.dispatch(forward, DeclaredPublisher(self.publisher_path))
        self.assertEqual(resolved["status"], "confirmed_succeeded")
        self.send("request_cancel", {"reason": "content must come down"})
        work = self.runtime.get_work(self.work_id)
        compensation = self.send("propose_action", {
            "capability": "content.unpublish",
            "document_digest": work["document_digest"],
            "contract_revision": work["contract"]["revision"],
            "plan_revision": work["plan_revision"],
            "compensates": forward}, command_id="unpublish-once")["operation_id"]
        lost = NeverReached(declared_both)
        self.assertEqual(self.runtime.dispatch(compensation, lost)["status"],
                         "outcome_unknown")
        kept = self.runtime.reconcile(compensation, NeverReached(declared_both))
        self.assertEqual((kept["status"], kept["reason"]),
                         ("outcome_unknown", "NO_AUTHORITATIVE_RESULT"))
        self.assertEqual(self.runtime.get_operation(compensation)["dispatch_state"],
                         "in_flight")
        self.assertNotIn("SameKeyRetryArmed", self.work_events())
        self.assertNotIn("same_key_retries",
                         self.runtime.get_operation(compensation))

    def test_concurrent_reconciles_arm_the_single_budget_exactly_once(self):
        import concurrent.futures
        adapter = NeverReached(DECLARED)
        operation = self.quarantined_operation(adapter)
        self.runtime.reconcile(operation, NeverReached(FakePublisher.contract))
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.runtime.reconcile, operation,
                                   NeverReached(DECLARED)) for _ in range(2)]
            answers = [future.result(30) for future in futures]
        self.assertTrue(all(answer["status"] == "prepared" for answer in answers))
        stored = self.runtime.get_operation(operation)
        self.assertEqual(stored["same_key_retries"], 1)
        self.assertEqual(self.work_events().count("SameKeyRetryArmed"), 1)
        # The quarantine preserved the lost dispatch, the arm preserved the
        # quarantine: exactly the two unknown states, appended once each.
        self.assertEqual([entry["reason"] for entry in stored["unknown_history"]],
                         ["OSError", "NO_AUTHORITATIVE_RESULT"])


class SameKeyRetryContractTests(unittest.TestCase):
    def test_retry_actions_must_be_a_subset_of_declared_actions(self):
        from work_runtime.adapter_contract import AdapterContract
        base = dict(actions=("content.publish", "content.unpublish"),
                    idempotency_scope="adapter-store:key",
                    retention="lifetime-of-store",
                    lookup_consistency="authoritative-by-key",
                    uniqueness=())
        AdapterContract(**base,
                        same_key_idempotent_retry_actions=("content.publish",))
        with self.assertRaises(ValueError):
            AdapterContract(**base, same_key_idempotent_retry_actions=("other.action",))
        with self.assertRaises(ValueError):
            AdapterContract(**base, same_key_idempotent_retry_actions=["content.publish"])
        with self.assertRaises(ValueError):
            AdapterContract(**base,
                            same_key_idempotent_retry_actions=("content.publish",
                                                               "content.publish"))
        with self.assertRaises(ValueError):
            AdapterContract(**base, same_key_idempotent_retry_actions=("content.publish", ""))


if __name__ == "__main__":
    unittest.main()
