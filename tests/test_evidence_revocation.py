"""S8 evidence revocation: command authority, codes, atomicity, permanence.

Pins the ratified D33–D37 core semantics (docs/evidence-revocation.md):
trusted-local revocation command, permanent revoked proof status, preserved
receipts/completion/effects, and current-requirement reaction.
"""

import json
import sqlite3
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

from work_runtime import CommandError, ExpensePolicy, Runtime
from work_runtime.adapters import FakeOA
from work_runtime.demo import (action, demo_grants, document, initialize,
                               prerequisites, proof, send)
from work_runtime.policy import ExpensePolicyV2, canonical, digest
from work_runtime.publishing import FakePublisher, PublishingPolicy


def revocation_grants():
    grants = demo_grants()
    grants["root"] = {"work.intervene"}
    grants["finance"] = {"evidence.write", "evidence.revoke"}
    grants["oa"] = {"evidence.revoke"}  # accepted source may revoke its proof
    return grants


def revoke(runtime, work_id, source, event_id, reason="withdrawn", actor=None,
           command_id=None, version=None):
    actor = source if actor is None else actor
    if version is None:
        version = runtime.get_work(work_id)["state_version"]
    return runtime.command(actor, command_id or uuid.uuid4().hex, work_id,
                           "revoke_evidence",
                           {"source": source, "event_id": event_id,
                            "reason": reason}, version)


def approval(runtime, work_id="demo", event_id="evt-approval", data=None):
    """Record and verify one approval proof with a known event id."""
    payload = {"digest": runtime.get_work(work_id)["document_digest"]
               } if data is None else data
    send(runtime, work_id, "record_evidence",
         {"event_id": event_id, "kind": "approval", "data": payload}, actor="finance")
    runtime.verify_pending(work_id)
    return event_id


class RevocationCase(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        self.oa_path = str(Path(self.temp.name) / "oa.sqlite")

    def new_runtime(self, grants=None, policy=None, policies=None):
        return Runtime(self.path, policy or ExpensePolicy(),
                       grants if grants is not None else revocation_grants(),
                       policies=policies)

    def evidence_row(self, source, event_id):
        db = sqlite3.connect(self.path)
        try:
            return db.execute(
                "SELECT body,fingerprint,work_id FROM evidence WHERE source=? AND event_id=?",
                (source, event_id)).fetchone()
        finally:
            db.close()

    def scalar(self, sql, args=()):
        db = sqlite3.connect(self.path)
        try:
            return db.execute(sql, args).fetchone()[0]
        finally:
            db.close()


class RevokeAuthorizationTests(RevocationCase):
    def setUp(self):
        super().setUp()
        self.runtime = self.new_runtime()
        initialize(self.runtime)
        self.event_id = approval(self.runtime)

    def test_malformed_payloads_raise_and_persist_nothing(self):
        malformed = [
            {},
            {"source": "finance"},
            {"source": "finance", "event_id": "evt-approval"},
            {"source": "finance", "event_id": "evt-approval", "reason": ""},
            {"source": "finance", "event_id": "evt-approval", "reason": None},
            {"source": 7, "event_id": "evt-approval", "reason": "r"},
            {"source": "finance", "event_id": "evt-approval", "reason": "r",
             "extra": True},
        ]
        for payload in malformed:
            with self.subTest(payload=payload):
                before = (self.runtime.get_work("demo")["state_version"],
                          self.scalar("SELECT COUNT(*) FROM commands"))
                with self.assertRaises(CommandError):
                    self.runtime.command("finance", uuid.uuid4().hex, "demo",
                                         "revoke_evidence", payload, before[0])
                after = (self.runtime.get_work("demo")["state_version"],
                         self.scalar("SELECT COUNT(*) FROM commands"))
                self.assertEqual(after, before)

    def test_stale_version_is_rejected_before_any_work(self):
        version = self.runtime.get_work("demo")["state_version"]
        receipt = self.runtime.command("finance", uuid.uuid4().hex, "demo",
                                       "revoke_evidence",
                                       {"source": "finance", "event_id": self.event_id,
                                        "reason": "r"}, version - 1)
        self.assertEqual(receipt["code"], "STATE_VERSION_CONFLICT")
        self.assertEqual(self.runtime.get_work("demo")["state_version"], version)

    def test_owner_and_write_grant_alone_cannot_revoke(self):
        receipt = revoke(self.runtime, "demo", "finance", self.event_id, actor="agent")
        self.assertEqual((receipt["decision"], receipt["code"]),
                         ("rejected", "AUTHORITY_DENIED"))
        write_only = self.new_runtime(demo_grants())  # finance lacks evidence.revoke
        receipt = revoke(write_only, "demo", "finance", self.event_id)
        self.assertEqual(receipt["code"], "AUTHORITY_DENIED")
        self.assertEqual(json.loads(self.evidence_row("finance", self.event_id)[0])
                         ["status"], "verified")

    def test_current_source_and_admin_may_revoke(self):
        by_source = revoke(self.runtime, "demo", "finance", "evt-approval")
        self.assertEqual(by_source["decision"], "accepted")
        other = approval(self.runtime, event_id="evt-approval-2")
        by_admin = revoke(self.runtime, "demo", "finance", other, actor="root")
        self.assertEqual(by_admin["decision"], "accepted")

    def test_retired_source_loses_revoke_right_after_migration(self):
        class RelabeledApprovalV2(ExpensePolicyV2):
            evidence_sources = {**ExpensePolicy.evidence_sources,
                                "approval": "finance2"}

        grants = revocation_grants()
        grants["finance2"] = {"evidence.revoke"}
        migrated = self.new_runtime(grants=grants,
                                policies={"demo-2": RelabeledApprovalV2()})
        # A pending old-source candidate: migration revalidates only verified
        # proofs, so this one stays pending under the new mapping (D36).
        send(migrated, "demo", "record_evidence",
             {"event_id": "evt-old-pending", "kind": "approval",
              "data": {"digest": "d"}}, actor="finance")
        send(migrated, "demo", "migrate_policy",
             {"policy_id": "expense-submit", "policy_version": "demo-2",
              "reason": "rotate approval source"}, actor="root")
        receipt = revoke(migrated, "demo", "finance", "evt-old-pending")
        self.assertEqual(receipt["code"], "AUTHORITY_DENIED")
        corrected = revoke(migrated, "demo", "finance", "evt-old-pending",
                           actor="finance2")
        self.assertEqual(corrected["decision"], "accepted")
        self.assertEqual(corrected["prior_status"], "pending_verification")


class RevokeDecisionTests(RevocationCase):
    def setUp(self):
        super().setUp()
        self.runtime = self.new_runtime()
        initialize(self.runtime)
        self.event_id = approval(self.runtime)

    def test_unknown_evidence_is_rejected(self):
        receipt = revoke(self.runtime, "demo", "finance", "missing-event")
        self.assertEqual((receipt["decision"], receipt["code"]),
                         ("rejected", "EVIDENCE_UNKNOWN"))

    def test_cross_work_evidence_is_scope_mismatch(self):
        initialize(self.runtime, "other", document(document_id="EXP-002"))
        other = approval(self.runtime, "other", event_id="evt-other")
        receipt = revoke(self.runtime, "demo", "finance", other)
        self.assertEqual(receipt["code"], "EVIDENCE_SCOPE_MISMATCH")

    def test_double_revoke_is_already_revoked(self):
        self.assertEqual(revoke(self.runtime, "demo", "finance", self.event_id)["decision"],
                         "accepted")
        receipt = revoke(self.runtime, "demo", "finance", self.event_id,
                         command_id="second-try")
        self.assertEqual(receipt["code"], "EVIDENCE_ALREADY_REVOKED")

    def test_invalid_proof_is_not_revocable(self):
        bad = approval(self.runtime, event_id="evt-bad", data={"digest": 5})
        self.assertEqual(json.loads(self.evidence_row("finance", bad)[0])["status"],
                         "invalid")
        receipt = revoke(self.runtime, "demo", "finance", bad)
        self.assertEqual(receipt["code"], "EVIDENCE_NOT_REVOKABLE")

    def test_pending_and_verified_are_both_revocable(self):
        send(self.runtime, "demo", "record_evidence",
             {"event_id": "evt-pending", "kind": "approval",
              "data": {"digest": self.runtime.get_work("demo")["document_digest"]}},
             actor="finance")
        pending = revoke(self.runtime, "demo", "finance", "evt-pending")
        self.assertEqual(pending["decision"], "accepted")
        self.assertEqual(pending["prior_status"], "pending_verification")
        verified = revoke(self.runtime, "demo", "finance", self.event_id)
        self.assertEqual(verified["decision"], "accepted")
        self.assertEqual(verified["prior_status"], "verified")

    def test_accepted_receipt_and_atomic_single_version_single_event(self):
        version = self.runtime.get_work("demo")["state_version"]
        commands_before = self.scalar("SELECT COUNT(*) FROM commands")
        revoked_events = self.scalar(
            "SELECT COUNT(*) FROM events WHERE type='EvidenceRevoked'")
        evidence_rows = self.scalar("SELECT COUNT(*) FROM evidence")
        receipt = revoke(self.runtime, "demo", "finance", self.event_id,
                         command_id="revoke-1")
        stored_id = json.loads(self.evidence_row("finance", self.event_id)[0])["id"]
        self.assertEqual(receipt, {"command_id": "revoke-1", "decision": "accepted",
                                   "result_state_version": version + 1,
                                   "evidence_id": stored_id,
                                   "evidence_status": "revoked",
                                   "prior_status": "verified"})
        self.assertEqual(self.runtime.get_work("demo")["state_version"], version + 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM commands"),
                         commands_before + 1)
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM events WHERE type='EvidenceRevoked'"),
            revoked_events + 1)
        event = json.loads(self.scalar(
            "SELECT body FROM events WHERE type='EvidenceRevoked'"))
        self.assertEqual(event["evidence_id"], stored_id)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM evidence"), evidence_rows)

    def test_revocation_preserves_candidate_identity_and_fingerprint(self):
        body, fingerprint, work_id = self.evidence_row("finance", self.event_id)
        before = json.loads(body)
        revoke(self.runtime, "demo", "finance", self.event_id)
        body2, fingerprint2, work_id2 = self.evidence_row("finance", self.event_id)
        after = json.loads(body2)
        self.assertEqual({k: after[k] for k in ("id", "source", "event_id",
                                                "kind", "data")},
                         {k: before[k] for k in ("id", "source", "event_id",
                                                 "kind", "data")})
        self.assertEqual(after["status"], "revoked")
        self.assertEqual(fingerprint2, fingerprint)
        self.assertEqual(work_id2, work_id)

    def test_admin_obeys_scope_status_and_version(self):
        self.assertEqual(revoke(self.runtime, "demo", "finance", "missing",
                                actor="root")["code"], "EVIDENCE_UNKNOWN")
        self.assertEqual(revoke(self.runtime, "demo", "finance", self.event_id,
                                actor="root")["decision"], "accepted")
        self.assertEqual(revoke(self.runtime, "demo", "finance", self.event_id,
                                actor="root", command_id="again")["code"],
                         "EVIDENCE_ALREADY_REVOKED")
        version = self.runtime.get_work("demo")["state_version"]
        self.assertEqual(self.runtime.command(
            "root", "stale", "demo", "revoke_evidence",
            {"source": "finance", "event_id": "evt-pending", "reason": "r"},
            version - 1)["code"], "STATE_VERSION_CONFLICT")

    def test_revoke_allowed_on_unbound_work(self):
        send(self.runtime, "unbound", "create_work",
             {"document": document(document_id="UNB-001")})
        send(self.runtime, "unbound", "record_evidence",
             {"event_id": "evt-unbound", "kind": "approval", "data": {"digest": "d"}},
             actor="finance")
        receipt = revoke(self.runtime, "unbound", "finance", "evt-unbound")
        self.assertEqual(receipt["decision"], "accepted")
        self.assertEqual(self.runtime.get_work("unbound")["status"], "establishing")

    def test_revoke_allowed_during_active_cancellation(self):
        send(self.runtime, "demo", "request_cancel", {"reason": "stop"})
        receipt = revoke(self.runtime, "demo", "finance", self.event_id)
        self.assertEqual(receipt["decision"], "accepted")


class RevokeEventTests(RevocationCase):
    def setUp(self):
        super().setUp()
        self.runtime = self.new_runtime()
        initialize(self.runtime)
        self.oa = FakeOA(self.oa_path)

    def event(self):
        return json.loads(self.scalar(
            "SELECT body FROM events WHERE type='EvidenceRevoked'"))

    def test_event_has_exactly_the_ratified_fields_with_real_diffs(self):
        approval(self.runtime)
        revoke(self.runtime, "demo", "finance", "evt-approval", reason="wrong approval")
        event = self.event()
        self.assertEqual(set(event),
                         {"actor", "evidence_id", "source", "event_id", "kind",
                          "prior_status", "reason", "work_was_closed",
                          "completion_cites_evidence", "affected_requirements",
                          "wait_dispositions"})
        self.assertEqual(event["actor"], "finance")
        self.assertEqual(event["reason"], "wrong approval")
        self.assertEqual(event["kind"], "approval")
        self.assertEqual(event["prior_status"], "verified")
        self.assertFalse(event["work_was_closed"])
        self.assertFalse(event["completion_cites_evidence"])
        self.assertEqual(event["affected_requirements"], [
            {"id": "E05:EXP-001",
             "before": {"applicability": "applicable", "fulfillment": "satisfied"},
             "after": {"applicability": "applicable", "fulfillment": "pending"}}])
        self.assertEqual(event["wait_dispositions"], [])

    def test_partial_revocation_with_second_sufficient_proof_changes_nothing(self):
        approval(self.runtime)
        approval(self.runtime, event_id="evt-approval-2")
        send(self.runtime, "demo", "register_wait",
             {"requirement_id": "E05:EXP-001", "deadline": 2000000000,
              "owner": "finance"})
        # The rule is satisfied, so the wait was already triggered when it
        # was registered; revoking one of two sufficient proofs keeps both.
        self.assertEqual(self.runtime.get_work("demo")["waits"][0]["status"],
                         "triggered")
        revoke(self.runtime, "demo", "finance", "evt-approval")
        event = self.event()
        self.assertEqual(event["affected_requirements"], [])
        self.assertEqual(event["wait_dispositions"], [
            {"id": self.runtime.get_work("demo")["waits"][0]["id"],
             "prior_status": "triggered", "status": "triggered",
             "disposition": "unchanged"}])

    def test_revoked_rule_keeps_historical_trigger_without_demotion_or_reset(self):
        send(self.runtime, "demo", "register_wait",
             {"requirement_id": "E05:EXP-001", "deadline": 2000000000,
              "owner": "finance"})
        approval(self.runtime)  # satisfaction triggers the wait durably
        self.assertEqual(self.runtime.get_work("demo")["waits"][0]["status"],
                         "triggered")
        revoke(self.runtime, "demo", "finance", "evt-approval")
        wait = self.runtime.get_work("demo")["waits"][0]
        self.assertEqual(wait["status"], "triggered")  # historical, never demoted
        self.assertEqual(wait["deadline"], 2000000000)  # no deadline reset
        self.assertEqual(self.event()["wait_dispositions"], [
            {"id": wait["id"], "prior_status": "triggered", "status": "triggered",
             "disposition": "unchanged"}])

    def test_unrelated_waiting_wait_is_untouched_by_revocation(self):
        send(self.runtime, "demo", "register_wait",
             {"requirement_id": "E05:EXP-001", "deadline": 2000000000,
              "owner": "finance"})
        send(self.runtime, "demo", "record_evidence",
             {"event_id": "evt-conf", "kind": "confirmation",
              "data": {"digest": self.runtime.get_work("demo")["document_digest"]}},
             actor="requester")
        self.runtime.verify_pending("demo")
        wait = self.runtime.get_work("demo")["waits"][0]
        self.assertEqual(wait["status"], "waiting")
        revoke(self.runtime, "demo", "requester", "evt-conf", actor="root")
        after = self.runtime.get_work("demo")["waits"][0]
        self.assertEqual((after["status"], after["deadline"]),
                         ("waiting", 2000000000))
        self.assertEqual(self.event()["wait_dispositions"], [
            {"id": wait["id"], "prior_status": "waiting", "status": "waiting",
             "disposition": "unchanged"}])
        # The still-waiting wait keeps the work in its ordinary waiting state;
        # revocation never escalates to needs_attention on its own.
        self.assertEqual(self.runtime.get_work("demo")["status"], "waiting")


class ClosedWorkCorrectionTests(RevocationCase):
    def setUp(self):
        super().setUp()
        self.runtime = self.new_runtime()
        initialize(self.runtime)
        self.oa = FakeOA(self.oa_path)

    def completed_work(self):
        """Full happy path: prerequisites, submitted, OA accepted, closed."""
        prerequisites(self.runtime)
        operation = action(self.runtime)["operation_id"]
        self.runtime.dispatch(operation, self.oa)
        send(self.runtime, "demo", "request_completion")
        return operation

    def test_revoked_accepted_on_closed_work_preserves_completion(self):
        operation = self.completed_work()
        completion = self.runtime.get_work("demo")["completion"]
        version = self.runtime.get_work("demo")["state_version"]
        accepted = json.loads(self.evidence_row("oa", operation)[0])
        receipt = revoke(self.runtime, "demo", "oa", operation, actor="root")
        self.assertEqual(receipt["decision"], "accepted")
        work = self.runtime.get_work("demo")
        self.assertEqual((work["status"], work["outcome"]), ("closed", "succeeded"))
        self.assertEqual(work["completion"], completion)
        self.assertEqual(work["state_version"], version + 1)
        event = json.loads(self.scalar(
            "SELECT body FROM events WHERE type='EvidenceRevoked'"))
        self.assertTrue(event["work_was_closed"])
        self.assertTrue(event["completion_cites_evidence"])
        # Current validity is visible in the recomputed requirements while the
        # historical completion decision stays untouched.
        requirement = next(r for r in work["requirements"] if r["id"] == "E08:EXP-001")
        self.assertEqual(requirement["fulfillment"], "pending")
        self.assertEqual(json.loads(self.evidence_row("oa", operation)[0])["id"],
                         accepted["id"])

    def test_revoked_approval_on_cancelled_closure_never_invents_citations(self):
        prerequisites(self.runtime)
        approval(self.runtime)  # known event id for the revocation target
        operation = action(self.runtime)["operation_id"]
        self.runtime.dispatch(operation, self.oa)
        send(self.runtime, "demo", "request_cancel", {"reason": "stop"})
        send(self.runtime, "demo", "finalize_cancel",
             {"acknowledged_operations": [operation]})
        completion = self.runtime.get_work("demo")["completion"]
        receipt = revoke(self.runtime, "demo", "finance", "evt-approval")
        self.assertEqual(receipt["decision"], "accepted")
        work = self.runtime.get_work("demo")
        self.assertEqual((work["status"], work["outcome"]), ("closed", "cancelled"))
        self.assertEqual(work["completion"], completion)
        event = json.loads(self.scalar(
            "SELECT body FROM events WHERE type='EvidenceRevoked'"))
        self.assertTrue(event["work_was_closed"])
        # Cancellation completion acknowledges operations, never evidence.
        self.assertFalse(event["completion_cites_evidence"])

    def test_revocation_on_unbound_closed_work_keeps_closure_stable(self):
        send(self.runtime, "unbound", "create_work",
             {"document": document(document_id="UNB-001")})
        send(self.runtime, "unbound", "record_evidence",
             {"event_id": "evt-unbound", "kind": "approval", "data": {"digest": "d"}},
             actor="finance")
        send(self.runtime, "unbound", "request_cancel", {"reason": "stop"})
        send(self.runtime, "unbound", "finalize_cancel",
             {"acknowledged_operations": []})
        completion = self.runtime.get_work("unbound")["completion"]
        receipt = revoke(self.runtime, "unbound", "finance", "evt-unbound")
        self.assertEqual(receipt["decision"], "accepted")
        self.assertEqual(receipt["prior_status"], "pending_verification")
        work = self.runtime.get_work("unbound")
        self.assertEqual((work["status"], work["outcome"]), ("closed", "cancelled"))
        self.assertEqual(work["completion"], completion)
        event = json.loads(self.scalar(
            "SELECT body FROM events WHERE type='EvidenceRevoked'"))
        self.assertTrue(event["work_was_closed"])
        self.assertFalse(event["completion_cites_evidence"])


class RevokeReplayTests(RevocationCase):
    def setUp(self):
        super().setUp()
        self.runtime = self.new_runtime()
        initialize(self.runtime)
        self.event_id = approval(self.runtime)

    def counts(self):
        return (self.scalar("SELECT COUNT(*) FROM events"),
                self.scalar("SELECT COUNT(*) FROM commands"))

    def test_replay_returns_stored_receipt_verbatim_without_new_writes(self):
        version = self.runtime.get_work("demo")["state_version"]
        payload = {"source": "finance", "event_id": self.event_id,
                   "reason": "withdrawn"}
        receipt = self.runtime.command("finance", "revoke-1", "demo",
                                       "revoke_evidence", payload, version)
        self.assertEqual(receipt["decision"], "accepted")
        before = self.counts()
        replay = self.runtime.command("finance", "revoke-1", "demo",
                                      "revoke_evidence", payload, version)
        self.assertEqual(replay, receipt)
        self.assertEqual(self.counts(), before)

    def test_replay_with_changed_content_is_command_id_reused(self):
        version = self.runtime.get_work("demo")["state_version"]
        self.runtime.command("finance", "revoke-1", "demo", "revoke_evidence",
                             {"source": "finance", "event_id": self.event_id,
                              "reason": "withdrawn"}, version)
        replay = self.runtime.command("finance", "revoke-1", "demo",
                                      "revoke_evidence",
                                      {"source": "finance", "event_id": self.event_id,
                                       "reason": "other"}, version)
        self.assertEqual(replay["code"], "COMMAND_ID_REUSED")

    def test_replay_after_revoke_grant_loss_denies_without_mutating_receipt(self):
        version = self.runtime.get_work("demo")["state_version"]
        payload = {"source": "finance", "event_id": self.event_id,
                   "reason": "withdrawn"}
        receipt = self.runtime.command("finance", "revoke-1", "demo",
                                       "revoke_evidence", payload, version)
        before = self.counts()
        lost = self.new_runtime(demo_grants())  # finance lost evidence.revoke
        replay = lost.command("finance", "revoke-1", "demo", "revoke_evidence",
                              payload, version)
        self.assertEqual((replay["decision"], replay["code"]),
                         ("rejected", "AUTHORITY_DENIED"))
        self.assertEqual(replay["observed_state_version"],
                         lost.get_work("demo")["state_version"])
        self.assertEqual(self.counts(), before)
        self.assertEqual(lost.get_command("finance", "revoke-1"), receipt)

    def test_replay_after_admin_grant_loss_denies(self):
        version = self.runtime.get_work("demo")["state_version"]
        payload = {"source": "finance", "event_id": self.event_id,
                   "reason": "withdrawn"}
        self.runtime.command("root", "revoke-1", "demo", "revoke_evidence",
                             payload, version)
        lost = self.new_runtime({**revocation_grants(), "root": set()})
        replay = lost.command("root", "revoke-1", "demo", "revoke_evidence",
                              payload, version)
        self.assertEqual(replay["code"], "AUTHORITY_DENIED")
        self.assertIsNotNone(lost.get_command("root", "revoke-1"))

    def test_replay_after_source_retirement_denies(self):
        class RelabeledApprovalV2(ExpensePolicyV2):
            evidence_sources = {**ExpensePolicy.evidence_sources,
                                "approval": "finance2"}

        grants = revocation_grants()
        grants["finance2"] = {"evidence.revoke"}
        version = self.runtime.get_work("demo")["state_version"]
        payload = {"source": "finance", "event_id": self.event_id,
                   "reason": "withdrawn"}
        self.assertEqual(self.runtime.command(
            "finance", "revoke-1", "demo", "revoke_evidence", payload,
            version)["decision"], "accepted")
        migrated = self.new_runtime(grants=grants,
                                    policies={"demo-2": RelabeledApprovalV2()})
        send(migrated, "demo", "migrate_policy",
             {"policy_id": "expense-submit", "policy_version": "demo-2",
              "reason": "rotate"}, actor="root")
        replay = migrated.command("finance", "revoke-1", "demo", "revoke_evidence",
                                  payload, version)
        self.assertEqual(replay["code"], "AUTHORITY_DENIED")

    def test_cached_unknown_rejection_replays_verbatim_after_proof_exists(self):
        version = self.runtime.get_work("demo")["state_version"]
        payload = {"source": "finance", "event_id": "evt-later", "reason": "r"}
        rejected = self.runtime.command("finance", "revoke-unk", "demo",
                                        "revoke_evidence", payload, version)
        self.assertEqual(rejected["code"], "EVIDENCE_UNKNOWN")
        approval(self.runtime, event_id="evt-later")
        replay = self.runtime.command("finance", "revoke-unk", "demo",
                                      "revoke_evidence", payload, version)
        self.assertEqual(replay, rejected)

    def test_cached_unknown_rejection_replay_after_authority_loss_denies(self):
        version = self.runtime.get_work("demo")["state_version"]
        payload = {"source": "finance", "event_id": "evt-later", "reason": "r"}
        self.runtime.command("finance", "revoke-unk", "demo", "revoke_evidence",
                             payload, version)
        lost = self.new_runtime(demo_grants())
        replay = lost.command("finance", "revoke-unk", "demo", "revoke_evidence",
                              payload, version)
        self.assertEqual(replay["code"], "AUTHORITY_DENIED")
        stored = self.runtime.get_command("finance", "revoke-unk")
        self.assertEqual(stored["code"], "EVIDENCE_UNKNOWN")

    def test_cached_unknown_rejection_keeps_preliminary_check_after_row_appears(self):
        # D33: a rejected unknown-proof command replays under the same
        # conservative preliminary check as its admission — the later
        # existence of the row (recorded by another source) must not tighten
        # the replay into a fresh denial while that authority still holds.
        version = self.runtime.get_work("demo")["state_version"]
        payload = {"source": "requester", "event_id": "evt-later-req",
                   "reason": "r"}
        rejected = self.runtime.command("finance", "revoke-unk2", "demo",
                                        "revoke_evidence", payload, version)
        self.assertEqual(rejected["code"], "EVIDENCE_UNKNOWN")
        send(self.runtime, "demo", "record_evidence",
             {"event_id": "evt-later-req", "kind": "confirmation",
              "data": {"digest": self.runtime.get_work("demo")
                       ["document_digest"]}}, actor="requester")
        replay = self.runtime.command("finance", "revoke-unk2", "demo",
                                      "revoke_evidence", payload, version)
        self.assertEqual(replay, rejected)


class RevokePermanenceTests(RevocationCase):
    def setUp(self):
        super().setUp()
        self.runtime = self.new_runtime()
        initialize(self.runtime)
        self.event_id = approval(self.runtime)

    def status_of(self, source, event_id):
        return json.loads(self.evidence_row(source, event_id)[0])["status"]

    def test_revoked_pending_proof_cannot_verify_later(self):
        send(self.runtime, "demo", "record_evidence",
             {"event_id": "evt-pending", "kind": "approval",
              "data": {"digest": self.runtime.get_work("demo")["document_digest"]}},
             actor="finance")
        revoke(self.runtime, "demo", "finance", "evt-pending")
        self.assertEqual(self.runtime.verify_pending("demo"), 0)
        self.assertEqual(self.status_of("finance", "evt-pending"), "revoked")

    def test_restart_and_recover_never_revive_revoked_proof(self):
        revoke(self.runtime, "demo", "finance", self.event_id)
        restarted = self.new_runtime()
        restarted.recover(FakeOA(self.oa_path))
        self.assertEqual(self.status_of("finance", self.event_id), "revoked")
        requirement = next(r for r in restarted.get_work("demo")["requirements"]
                           if r["id"] == "E05:EXP-001")
        self.assertEqual(requirement["fulfillment"], "pending")

    def test_migration_records_revoked_disposition_and_keeps_it(self):
        revoked_id = json.loads(self.evidence_row("finance", self.event_id)[0])["id"]
        revoke(self.runtime, "demo", "finance", self.event_id)
        migrated = self.new_runtime(policies={"demo-2": ExpensePolicyV2()})
        send(migrated, "demo", "migrate_policy",
             {"policy_id": "expense-submit", "policy_version": "demo-2",
              "reason": "tighten"}, actor="root")
        event = json.loads(self.scalar(
            "SELECT body FROM events WHERE type='PolicyMigrated'"))
        self.assertIn({"id": revoked_id, "from": "revoked", "to": "revoked"},
                      event["evidence"])
        self.assertEqual(self.status_of("finance", self.event_id), "revoked")

    def test_resend_under_new_command_reports_current_status(self):
        evidence_rows = self.scalar("SELECT COUNT(*) FROM evidence")
        verified = send(self.runtime, "demo", "record_evidence",
                        {"event_id": "evt-live", "kind": "approval",
                         "data": {"digest": self.runtime.get_work("demo")
                                  ["document_digest"]}}, actor="finance")
        self.runtime.verify_pending("demo")
        resend = send(self.runtime, "demo", "record_evidence",
                      {"event_id": "evt-live", "kind": "approval",
                       "data": {"digest": self.runtime.get_work("demo")
                                ["document_digest"]}}, actor="finance")
        self.assertEqual((resend["decision"], resend["evidence_status"]),
                         ("accepted", "verified"))
        self.assertEqual(resend["evidence_id"], verified["evidence_id"])
        revoke(self.runtime, "demo", "finance", "evt-live")
        after = send(self.runtime, "demo", "record_evidence",
                     {"event_id": "evt-live", "kind": "approval",
                      "data": {"digest": self.runtime.get_work("demo")
                               ["document_digest"]}}, actor="finance")
        self.assertEqual((after["decision"], after["evidence_status"]),
                         ("accepted", "revoked"))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM evidence"),
                         evidence_rows + 1)

    def test_resend_of_invalid_proof_reports_invalid(self):
        send(self.runtime, "demo", "record_evidence",
             {"event_id": "evt-bad", "kind": "approval", "data": {"digest": 5}},
             actor="finance")
        self.runtime.verify_pending("demo")
        resend = send(self.runtime, "demo", "record_evidence",
                      {"event_id": "evt-bad", "kind": "approval",
                       "data": {"digest": 5}}, actor="finance")
        self.assertEqual(resend["evidence_status"], "invalid")

    def test_resend_with_changed_content_is_source_event_conflict(self):
        revoke(self.runtime, "demo", "finance", self.event_id)
        receipt = send(self.runtime, "demo", "record_evidence",
                       {"event_id": self.event_id, "kind": "approval",
                        "data": {"digest": "changed"}}, actor="finance")
        self.assertEqual(receipt["code"], "SOURCE_EVENT_CONFLICT")

    def test_original_record_command_replay_stays_verbatim(self):
        original = send(self.runtime, "demo", "record_evidence",
                        {"event_id": "evt-replay", "kind": "approval",
                         "data": {"digest": self.runtime.get_work("demo")
                                  ["document_digest"]}},
                        actor="finance", command_id="rec-1")
        self.runtime.verify_pending("demo")
        revoke(self.runtime, "demo", "finance", "evt-replay")
        replay = self.runtime.command("finance", "rec-1", "demo", "record_evidence",
                                      {"event_id": "evt-replay", "kind": "approval",
                                       "data": {"digest": self.runtime.get_work("demo")
                                                ["document_digest"]}}, None)
        self.assertEqual(replay, original)

    def test_replacement_proof_restores_rule_under_new_event(self):
        revoke(self.runtime, "demo", "finance", self.event_id)
        replacement = approval(self.runtime, event_id="evt-approval-new")
        self.assertNotEqual(replacement, self.event_id)
        requirement = next(r for r in self.runtime.get_work("demo")["requirements"]
                           if r["id"] == "E05:EXP-001")
        self.assertEqual(requirement["fulfillment"], "satisfied")
        self.assertEqual(self.status_of("finance", self.event_id), "revoked")

    def test_confirmed_operation_never_reruns_to_regen_accepted_proof(self):
        prerequisites(self.runtime)
        self.oa = FakeOA(self.oa_path)
        operation = action(self.runtime)["operation_id"]
        self.runtime.dispatch(operation, self.oa)
        revoke(self.runtime, "demo", "oa", operation, actor="root")
        reproposed = action(self.runtime)
        self.assertEqual(reproposed["operation_id"], operation)
        self.assertEqual(reproposed["operation_status_at_decision"],
                         "confirmed_succeeded")
        after_dispatch = self.runtime.dispatch(operation, self.oa)
        self.assertEqual(after_dispatch["status"], "confirmed_succeeded")
        self.assertEqual(self.oa.accepted_count(), 1)
        self.assertEqual(self.status_of("oa", operation), "revoked")
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM evidence WHERE event_id=?", (operation,)), 1)
        after_reconcile = self.runtime.reconcile(operation, self.oa)
        self.assertEqual(after_reconcile["status"], "confirmed_succeeded")
        self.assertEqual(after_reconcile.get("external_id"),
                         after_dispatch.get("external_id"))
        self.assertEqual(self.oa.accepted_count(), 1)


class RevokeWaitsTests(RevocationCase):
    def setUp(self):
        super().setUp()
        self.runtime = self.new_runtime()
        initialize(self.runtime)
        self.event_id = approval(self.runtime)

    def revoked_event(self):
        return json.loads(self.scalar(
            "SELECT body FROM events WHERE type='EvidenceRevoked'"))

    def test_cancelled_wait_stays_terminal_across_revocation(self):
        send(self.runtime, "demo", "register_wait",
             {"requirement_id": "E05:EXP-001", "deadline": 2000000000,
              "owner": "finance"})
        send(self.runtime, "demo", "request_cancel", {"reason": "stop"})
        wait = self.runtime.get_work("demo")["waits"][0]
        self.assertEqual(wait["status"], "cancelled")
        revoke(self.runtime, "demo", "finance", self.event_id)
        work = self.runtime.get_work("demo")
        self.assertEqual(work["waits"][0]["status"], "cancelled")
        self.assertEqual(self.revoked_event()["wait_dispositions"], [
            {"id": wait["id"], "prior_status": "cancelled", "status": "cancelled",
             "disposition": "unchanged"}])

    def test_expired_wait_keeps_state_and_deadline_without_reset(self):
        # The wait sits on the still-unsatisfied confirmation rule so it can
        # genuinely expire; the approval revocation must not touch it.
        send(self.runtime, "demo", "register_wait",
             {"requirement_id": "E06:EXP-001", "deadline": 1000,
              "owner": "requester"})
        self.runtime.expire_waits("demo", 2000)
        wait = self.runtime.get_work("demo")["waits"][0]
        self.assertEqual(wait["status"], "expired")
        revoke(self.runtime, "demo", "finance", self.event_id)
        work = self.runtime.get_work("demo")
        self.assertEqual(work["waits"][0]["status"], "expired")
        self.assertEqual(work["waits"][0]["deadline"], 1000)
        self.assertEqual(work["status"], "needs_attention")  # sticky expiry
        self.assertEqual(self.revoked_event()["wait_dispositions"], [
            {"id": wait["id"], "prior_status": "expired", "status": "expired",
             "disposition": "unchanged"}])


class RevokeDispatchTests(RevocationCase):
    def setUp(self):
        super().setUp()
        self.runtime = self.new_runtime()
        initialize(self.runtime)
        self.oa = FakeOA(self.oa_path)

    def approval_event(self):
        return self.scalar(
            "SELECT event_id FROM evidence WHERE work_id='demo' AND source='finance'")

    def oa_calls(self):
        db = sqlite3.connect(self.oa_path)
        try:
            return db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
        finally:
            db.close()

    def prepared_operation(self):
        prerequisites(self.runtime)
        receipt = action(self.runtime)
        self.assertEqual(receipt["decision"], "accepted")
        return receipt["operation_id"]

    def test_prepared_intent_holds_at_dispatch_with_zero_attempts_and_calls(self):
        operation = self.prepared_operation()
        revoke(self.runtime, "demo", "finance", self.approval_event())
        held = self.runtime.dispatch(operation, self.oa)
        self.assertEqual(held["status"], "prepared")
        self.assertEqual(held["dispatch_state"], "held")
        self.assertEqual(held["reason"], "REQUIREMENT_UNSATISFIED")
        self.assertEqual(held["attempts"], [])
        self.assertEqual(self.oa_calls(), 0)
        self.assertEqual(self.oa.accepted_count(), 0)

    def test_recover_holds_prepared_intent_with_zero_calls(self):
        operation = self.prepared_operation()
        revoke(self.runtime, "demo", "finance", self.approval_event())
        restarted = self.new_runtime()
        results = restarted.recover(self.oa)
        held = next(op for op in results if op["id"] == operation)
        self.assertEqual(held["dispatch_state"], "held")
        self.assertEqual(held["reason"], "REQUIREMENT_UNSATISFIED")
        self.assertEqual(held["attempts"], [])
        self.assertEqual(self.oa_calls(), 0)

    def test_replacement_readmits_same_operation_key_and_dispatches_once(self):
        operation = self.prepared_operation()
        revoke(self.runtime, "demo", "finance", self.approval_event())
        held = self.runtime.dispatch(operation, self.oa)
        self.assertEqual(held["dispatch_state"], "held")
        approval(self.runtime, event_id="evt-approval-replacement")
        readmitted = action(self.runtime)
        self.assertEqual(readmitted["decision"], "accepted")
        self.assertEqual(readmitted["operation_id"], operation)
        events = [e["type"] for e in self.runtime.events("demo")]
        self.assertIn("OperationReadmitted", events)
        confirmed = self.runtime.dispatch(operation, self.oa)
        self.assertEqual(confirmed["status"], "confirmed_succeeded")
        self.assertEqual(self.oa.accepted_count(), 1)

    def test_proposal_blocked_after_revoking_approval(self):
        prerequisites(self.runtime)
        revoke(self.runtime, "demo", "finance", self.approval_event())
        receipt = action(self.runtime)
        self.assertEqual((receipt["decision"], receipt["code"]),
                         ("rejected", "REQUIREMENT_UNSATISFIED"))
        self.assertIn("E05:EXP-001", [b["id"] for b in receipt["blockers"]])

    def test_completion_blocked_after_revoking_accepted_evidence(self):
        operation = self.prepared_operation()
        self.runtime.dispatch(operation, self.oa)
        revoke(self.runtime, "demo", "oa", operation, actor="root")
        receipt = send(self.runtime, "demo", "request_completion")
        self.assertEqual((receipt["decision"], receipt["code"]),
                         ("rejected", "REQUIREMENT_UNSATISFIED"))
        self.assertIn("E08:EXP-001", [b["id"] for b in receipt["blockers"]])
        self.assertEqual(self.oa.accepted_count(), 1)  # effect retained

    def test_inflight_operation_reconciles_after_revocation_with_one_effect(self):
        operation = self.prepared_operation()
        uncertain = self.runtime.dispatch(
            operation, FakeOA(self.oa_path, timeout_after_commit=True))
        self.assertEqual(uncertain["status"], "outcome_unknown")
        revoke(self.runtime, "demo", "finance", self.approval_event())
        confirmed = self.runtime.reconcile(operation, self.oa)
        self.assertEqual(confirmed["status"], "confirmed_succeeded")
        self.assertTrue(confirmed["external_id"].startswith("OA-"))
        self.assertEqual(len(confirmed["attempts"]), 1)
        self.assertEqual(self.oa.accepted_count(), 1)
        self.assertEqual(
            json.loads(self.evidence_row("oa", operation)[0])["status"],
            "verified")
        self.assertEqual(
            json.loads(self.evidence_row("finance", self.approval_event())[0])
            ["status"], "revoked")


def publishing_revocation_grants():
    return {"agent": {"work.manage", "content.publish"},
            "reviewer": {"evidence.write", "evidence.revoke"},
            "author": {"evidence.write"},
            "publisher": {"evidence.revoke"},
            "root": {"work.intervene"}}


def article(article_id="ART-001", title="Release notes", body="Draft body",
            requires_review=True):
    return {"id": article_id, "title": title, "body": body,
            "requires_review": requires_review}


class PublishingRevokeTests(RevocationCase):
    def setUp(self):
        super().setUp()
        self.grants = publishing_revocation_grants()
        self.runtime = Runtime(self.path, PublishingPolicy(), self.grants)
        self.publisher = FakePublisher(str(Path(self.temp.name) / "pub.sqlite"))
        send(self.runtime, "pub", "create_work", {"document": article()})
        send(self.runtime, "pub", "bind_contract",
             {"policy_id": "content-publish", "policy_version": "demo-1",
              "goal": "content.published"})

    def record(self, kind, source, event_id):
        send(self.runtime, "pub", "record_evidence",
             {"event_id": event_id, "kind": kind,
              "data": {"digest": self.runtime.get_work("pub")["document_digest"]}},
             actor=source)

    def verified_prerequisites(self):
        self.record("approval", "reviewer", "evt-rev-approval")
        self.record("confirmation", "author", "evt-rev-confirmation")
        self.runtime.verify_pending("pub")

    def publish(self):
        work = self.runtime.get_work("pub")
        return send(self.runtime, "pub", "propose_action", {
            "capability": "content.publish",
            "document_digest": work["document_digest"],
            "contract_revision": work["contract"]["revision"],
            "plan_revision": work["plan_revision"]})

    def test_revoked_approval_blocks_publication_admission(self):
        self.verified_prerequisites()
        revoke(self.runtime, "pub", "reviewer", "evt-rev-approval")
        receipt = self.publish()
        self.assertEqual((receipt["decision"], receipt["code"]),
                         ("rejected", "REQUIREMENT_UNSATISFIED"))
        self.assertIn("C02:ART-001", [b["id"] for b in receipt["blockers"]])

    def test_prepared_publication_holds_with_zero_published_artifacts(self):
        self.verified_prerequisites()
        operation = self.publish()["operation_id"]
        revoke(self.runtime, "pub", "reviewer", "evt-rev-approval")
        held = self.runtime.dispatch(operation, self.publisher)
        self.assertEqual((held["dispatch_state"], held["reason"]),
                         ("held", "REQUIREMENT_UNSATISFIED"))
        self.assertEqual(held["attempts"], [])
        self.assertEqual(self.publisher.published_count(), 0)

    def test_replacement_readmits_and_publishes_exactly_once(self):
        self.verified_prerequisites()
        operation = self.publish()["operation_id"]
        revoke(self.runtime, "pub", "reviewer", "evt-rev-approval")
        self.runtime.dispatch(operation, self.publisher)
        self.record("approval", "reviewer", "evt-rev-approval-2")
        self.runtime.verify_pending("pub")
        readmitted = self.publish()
        self.assertEqual(readmitted["operation_id"], operation)
        confirmed = self.runtime.dispatch(operation, self.publisher)
        self.assertEqual(confirmed["status"], "confirmed_succeeded")
        self.assertEqual(self.publisher.published_count(), 1)
        self.assertEqual(
            json.loads(self.evidence_row("publisher", operation)[0])["status"],
            "verified")

    def test_closed_publication_correction_preserves_completion(self):
        self.verified_prerequisites()
        operation = self.publish()["operation_id"]
        self.runtime.dispatch(operation, self.publisher)
        send(self.runtime, "pub", "request_completion")
        completion = self.runtime.get_work("pub")["completion"]
        revoke(self.runtime, "pub", "publisher", operation, actor="root")
        work = self.runtime.get_work("pub")
        self.assertEqual((work["status"], work["outcome"]), ("closed", "succeeded"))
        self.assertEqual(work["completion"], completion)
        event = json.loads(self.scalar(
            "SELECT body FROM events WHERE type='EvidenceRevoked'"))
        self.assertTrue(event["work_was_closed"])
        self.assertTrue(event["completion_cites_evidence"])
        requirement = next(r for r in work["requirements"] if r["id"] == "C04:ART-001")
        self.assertEqual(requirement["fulfillment"], "pending")

    def test_publishing_permanence_across_resend_and_restart(self):
        self.verified_prerequisites()
        revoke(self.runtime, "pub", "reviewer", "evt-rev-approval")
        resend = send(self.runtime, "pub", "record_evidence",
                      {"event_id": "evt-rev-approval", "kind": "approval",
                       "data": {"digest": self.runtime.get_work("pub")
                                ["document_digest"]}}, actor="reviewer")
        self.assertEqual((resend["decision"], resend["evidence_status"]),
                         ("accepted", "revoked"))
        restarted = Runtime(self.path, PublishingPolicy(), self.grants)
        restarted.recover(self.publisher)
        self.assertEqual(
            json.loads(self.evidence_row("reviewer", "evt-rev-approval")[0])
            ["status"], "revoked")


DYING_REVOKE_SCRIPT = """
import os, sys
from work_runtime import Runtime, ExpensePolicy
from work_runtime.demo import demo_grants


class Dying(Runtime):
    def _save(self, db, work, event, details=None):
        if event == "EvidenceRevoked":
            os._exit(75)
        return Runtime._save(self, db, work, event, details)


grants = demo_grants()
grants["finance"] = {"evidence.write", "evidence.revoke"}
runtime = Dying(sys.argv[1], ExpensePolicy(), grants)
version = runtime.get_work("demo")["state_version"]
runtime.command("finance", "child-revoke", "demo", "revoke_evidence",
                {"source": "finance", "event_id": sys.argv[2], "reason": "die"},
                version)
"""


class RevokeCrashTests(RevocationCase):
    def setUp(self):
        super().setUp()
        self.runtime = self.new_runtime()
        initialize(self.runtime)
        self.event_id = approval(self.runtime)
        self.oa = FakeOA(self.oa_path)

    def snapshot(self):
        db = sqlite3.connect(self.path)
        try:
            return {
                "works": db.execute("SELECT id,state FROM works ORDER BY id"
                                    ).fetchall(),
                "evidence": db.execute(
                    "SELECT source,event_id,fingerprint,body FROM evidence"
                    " ORDER BY source,event_id").fetchall(),
                "events": db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                "commands": db.execute("SELECT COUNT(*) FROM commands").fetchone()[0],
            }
        finally:
            db.close()

    def test_revoke_transaction_exception_rolls_back_everything(self):
        class ExplodingSave(Runtime):
            def _save(self, db, work, event, details=None):
                if event == "EvidenceRevoked":
                    raise RuntimeError("injected")
                return Runtime._save(self, db, work, event, details)

        before = self.snapshot()
        exploding = ExplodingSave(self.path, ExpensePolicy(),
                                  revocation_grants())
        with self.assertRaises(RuntimeError):
            revoke(exploding, "demo", "finance", self.event_id,
                   command_id="boom")
        self.assertEqual(self.snapshot(), before)
        requirement = next(r for r in self.runtime.get_work("demo")["requirements"]
                           if r["id"] == "E05:EXP-001")
        self.assertEqual(requirement["fulfillment"], "satisfied")
        self.assertIsNone(self.runtime.get_command("finance", "boom"))
        # The store is intact, so an ordinary retry succeeds.
        self.assertEqual(revoke(self.runtime, "demo", "finance",
                                self.event_id)["decision"], "accepted")

    def test_real_process_death_inside_revoke_rolls_back(self):
        before = self.snapshot()
        child = subprocess.run([sys.executable, "-c", DYING_REVOKE_SCRIPT,
                                self.path, self.event_id], check=False)
        self.assertEqual(child.returncode, 75)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(
            json.loads(self.evidence_row("finance", self.event_id)[0])["status"],
            "verified")
        restarted = self.new_runtime()
        self.assertEqual(revoke(restarted, "demo", "finance",
                                self.event_id)["decision"], "accepted")
        self.assertEqual(
            json.loads(self.evidence_row("finance", self.event_id)[0])["status"],
            "revoked")

    def test_external_death_then_revoke_reconciles_one_retained_effect(self):
        prerequisites(self.runtime)
        operation = action(self.runtime)["operation_id"]
        approval_event = self.scalar(
            "SELECT event_id FROM evidence WHERE work_id='demo' AND source='finance'")
        child = subprocess.run(
            [sys.executable, "-m", "work_runtime", "worker",
             "--runtime", self.path, "--oa", self.oa_path,
             "--operation", operation, "--crash-after-effect"], check=False)
        self.assertEqual(child.returncode, 73)
        self.assertEqual(self.oa.accepted_count(), 1)
        restarted = self.new_runtime()
        revoke(restarted, "demo", "finance", approval_event)
        restarted.recover(self.oa)
        op = restarted.get_operation(operation)
        self.assertEqual(op["status"], "confirmed_succeeded")
        self.assertTrue(op["external_id"].startswith("OA-"))
        self.assertEqual(self.oa.accepted_count(), 1)  # exactly one effect
        self.assertEqual(
            json.loads(self.evidence_row("oa", operation)[0])["status"], "verified")
        self.assertEqual(
            json.loads(self.evidence_row("finance", approval_event)[0])["status"],
            "revoked")
