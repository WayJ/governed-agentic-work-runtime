"""Withdrawal approver-key rotation battery (S13 core wave, story 4).

Pins the S11 rotation semantics on the sop-publish family's `card_withdrawal`
envelopes: retired/dropped refusals with zero writes, cached-receipt verbatim
replay, current-status resend, and six-table plus both-artifact byte
preservation across every rotation act. Every secret here is synthetic and
ephemeral (secrets.token_bytes, never printed).
"""

import os
import secrets
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from work_runtime import Runtime
from work_runtime.authoring import sop_digest
from work_runtime.ingress import SourceKey, SignedEvidenceGateway, sign_evidence
from work_runtime.publication import (
    SopPublicationPolicy,
    SopPublicationStore,
    SopWithdrawalStore,
    publication_key,
    withdrawal_key,
)
from tests.test_publication import (
    artifact_name,
    card_with,
    committed_names,
)
from tests.test_publication_withdrawal import (
    FLOW_NOW,
    withdrawal_grants,
    withdrawal_request,
)

TABLES = ("works", "commands", "evidence", "operations", "events", "metadata")


def key():
    return secrets.token_bytes(32)


class WithdrawalRotationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="sop-withdrawal-rotation-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.runtime_path = str(self.root / "runtime.sqlite")
        self.store_dir = str(self.root / "store")
        self.policy = SopPublicationPolicy()
        self.grants = withdrawal_grants()
        self.runtime = Runtime(self.runtime_path, self.policy, self.grants)
        self.k1 = SourceKey("ring-2026-08", key(), current=True)
        self.k2 = SourceKey("ring-2026-10", key())
        self.card = card_with()
        self.publish_card()

    def publish_card(self):
        store = SopPublicationStore(self.store_dir)
        store.execute(publication_key(self.card), self.card,
                      sop_digest(self.card))

    def request(self):
        return withdrawal_request(published_digest=sop_digest(self.card))

    def gateway(self, ring=None):
        return SignedEvidenceGateway(
            self.runtime, {"sop-owner": ring or [self.k1, self.k2]},
            clock=lambda: FLOW_NOW)

    def rotated_retained(self):
        return [SourceKey(self.k1.key_id, self.k1.secret, not_after=FLOW_NOW - 10),
                SourceKey(self.k2.key_id, self.k2.secret, current=True)]

    def rotated_dropped(self):
        return [SourceKey(self.k2.key_id, self.k2.secret, current=True)]

    def establish(self, work_id="wd-1"):
        request = self.request()
        self.runtime.command("agent", uuid.uuid4().hex, work_id,
                             "create_work", {"document": request}, None)
        work = self.runtime.get_work(work_id)
        self.runtime.command("agent", uuid.uuid4().hex, work_id,
                             "bind_contract", {
                                 "policy_id": self.policy.id,
                                 "policy_version": self.policy.version,
                                 "goal": self.policy.goal},
                             work["state_version"])
        return request

    def signed(self, secret, work_id, request, key_id=None, command_id=None,
               event_id=None):
        message = {"source": "sop-owner",
                   "command_id": command_id or uuid.uuid4().hex,
                   "work_id": work_id,
                   "event_id": event_id or uuid.uuid4().hex,
                   "kind": "card_withdrawal",
                   "data": {"digest": request["published_digest"],
                            "policy_version": request["policy_version"]},
                   "issued_at": FLOW_NOW}
        if key_id is not None:
            message["key_id"] = key_id
        return sign_evidence(secret, message)

    def envelope(self, work_id, request, secret=None, key_id=None,
                 command_id=None, event_id=None):
        return self.signed(secret or self.k1.secret, work_id, request,
                           key_id=key_id, command_id=command_id,
                           event_id=event_id)

    def table_dump(self):
        dump = {}
        with sqlite3.connect(self.runtime_path) as db:
            for table in TABLES:
                dump[table] = db.execute(
                    "SELECT * FROM %s ORDER BY rowid" % table).fetchall()
        return dump

    def table_counts(self):
        with sqlite3.connect(self.runtime_path) as db:
            return {t: db.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
                    for t in TABLES}

    def store_dump(self):
        return {name: Path(os.path.join(self.store_dir, name)).read_bytes()
                for name in committed_names(self.store_dir)}

    def test_retired_old_key_refused_with_zero_writes(self):
        request = self.establish()
        accepted = self.gateway().record(
            self.envelope("wd-1", request, key_id=self.k1.key_id,
                          command_id="cmd-a", event_id="evt-1"))
        self.assertEqual(accepted["decision"], "accepted")
        before = self.table_dump()
        refused = self.gateway(ring=self.rotated_retained()).record(
            self.envelope("wd-1", request, secret=self.k1.secret,
                          key_id=self.k1.key_id,
                          command_id="cmd-z", event_id="evt-z"))
        self.assertEqual(refused,
                         {"decision": "rejected",
                          "code": "EVIDENCE_KEY_RETIRED"})
        self.assertEqual(self.table_dump(), before)

    def test_dropped_old_key_refuses_authentication(self):
        request = self.establish()
        self.gateway().record(
            self.envelope("wd-1", request, key_id=self.k1.key_id,
                          command_id="cmd-a", event_id="evt-1"))
        before = self.table_dump()
        refused = self.gateway(ring=self.rotated_dropped()).record(
            self.envelope("wd-1", request, secret=self.k1.secret,
                          command_id="cmd-z", event_id="evt-z"))
        self.assertEqual(refused,
                         {"decision": "rejected",
                          "code": "EVIDENCE_AUTHENTICATION_FAILED"})
        cited = self.gateway(ring=self.rotated_dropped()).record(
            self.envelope("wd-1", request, secret=self.k1.secret,
                          key_id=self.k1.key_id,
                          command_id="cmd-y", event_id="evt-y"))
        self.assertEqual(cited["code"], "EVIDENCE_AUTHENTICATION_FAILED")
        self.assertEqual(self.table_dump(), before)

    def test_same_command_id_resign_replays_original_receipt_verbatim(self):
        request = self.establish()
        first = self.gateway().record(
            self.envelope("wd-1", request, key_id=self.k1.key_id,
                          command_id="cmd-a", event_id="evt-1"))
        self.assertEqual(first["decision"], "accepted")
        rotated = self.gateway(ring=self.rotated_retained())
        before = self.table_dump()
        replay = rotated.record(
            self.envelope("wd-1", request, secret=self.k2.secret,
                          key_id=self.k2.key_id,
                          command_id="cmd-a", event_id="evt-1"))
        self.assertEqual(replay, first)  # verbatim, zero writes
        self.assertEqual(self.table_dump(), before)

    def test_new_command_id_same_event_reports_current_status(self):
        request = self.establish()
        first = self.gateway().record(
            self.envelope("wd-1", request, key_id=self.k1.key_id,
                          command_id="cmd-a", event_id="evt-1"))
        rotated = self.gateway(ring=self.rotated_retained())
        before = self.table_counts()
        status = rotated.record(
            self.envelope("wd-1", request, secret=self.k2.secret,
                          key_id=self.k2.key_id,
                          command_id="cmd-b", event_id="evt-1"))
        self.assertEqual(status["decision"], "accepted")
        self.assertEqual(status["evidence_id"], first["evidence_id"])
        self.assertEqual(status["evidence_status"], "pending_verification")
        after = self.table_counts()
        self.assertEqual(after["commands"], before["commands"] + 1)
        self.assertEqual(after["evidence"], before["evidence"])

    def test_rotation_untouches_completed_withdrawal_history(self):
        request = self.establish()
        self.gateway().record(
            self.envelope("wd-1", request, key_id=self.k1.key_id,
                          command_id="cmd-a", event_id="evt-1"))
        self.runtime.verify_pending("wd-1")
        work = self.runtime.get_work("wd-1")
        intent = self.runtime.command(
            "agent", "withdraw-once", "wd-1", "propose_action", {
                "capability": "sop.withdraw",
                "document_digest": work["document_digest"],
                "contract_revision": work["contract"]["revision"],
                "plan_revision": work["plan_revision"]},
            work["state_version"])
        self.runtime.dispatch(intent["operation_id"],
                              SopWithdrawalStore(self.store_dir))
        self.assertEqual(self.runtime.get_operation(intent["operation_id"])
                         ["status"], "confirmed_succeeded")
        self.assertEqual(len(committed_names(self.store_dir)), 2)
        tables = self.table_dump()
        artifacts = self.store_dump()
        self.assertEqual(sorted(artifacts),
                         sorted([artifact_name(publication_key(self.card)),
                                 artifact_name(withdrawal_key(
                                     request["policy_id"],
                                     request["policy_version"]))]))
        denials = (
            self.gateway(ring=self.rotated_retained()).record(
                self.envelope("wd-1", request, secret=self.k1.secret,
                              key_id=self.k1.key_id,
                              command_id="cmd-z", event_id="evt-z")),
            self.gateway(ring=self.rotated_dropped()).record(
                self.envelope("wd-1", request, secret=self.k1.secret,
                              key_id=self.k1.key_id,
                              command_id="cmd-y", event_id="evt-y")),
        )
        for receipt in denials:
            self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(self.table_dump(), tables)
        self.assertEqual(self.store_dump(), artifacts)

    def test_pre_rotation_approval_still_verifies_and_completes(self):
        request = self.establish()
        self.gateway().record(
            self.envelope("wd-1", request, key_id=self.k1.key_id,
                          command_id="cmd-1", event_id="evt-1"))
        rotated = self.gateway(ring=self.rotated_retained())
        # Fingerprints are key-agnostic: the pre-rotation approval still
        # verifies and carries the withdrawal to a completed close.
        self.runtime.verify_pending("wd-1")
        work = self.runtime.get_work("wd-1")
        intent = self.runtime.command(
            "agent", "withdraw-v1", "wd-1", "propose_action", {
                "capability": "sop.withdraw",
                "document_digest": work["document_digest"],
                "contract_revision": work["contract"]["revision"],
                "plan_revision": work["plan_revision"]},
            work["state_version"])
        self.runtime.dispatch(intent["operation_id"],
                              SopWithdrawalStore(self.store_dir))
        self.assertEqual(self.runtime.get_operation(intent["operation_id"])
                         ["status"], "confirmed_succeeded")
        version = self.runtime.get_work("wd-1")["state_version"]
        self.runtime.command("agent", "complete-wd", "wd-1",
                             "request_completion", {}, version)
        self.assertEqual((self.runtime.get_work("wd-1")["status"],
                          self.runtime.get_work("wd-1")["outcome"]),
                         ("closed", "succeeded"))
        self.assertEqual(len(committed_names(self.store_dir)), 2)
        # A legitimate NEW withdrawal continues under the rotated key.
        second_card = card_with(policy_version="v2")
        store = SopPublicationStore(self.store_dir)
        store.execute(publication_key(second_card), second_card,
                      sop_digest(second_card))
        second = withdrawal_request(policy_version="v2",
                                    published_digest=sop_digest(second_card))
        self.runtime.command("agent", uuid.uuid4().hex, "wd-2",
                             "create_work", {"document": second}, None)
        work2 = self.runtime.get_work("wd-2")
        self.runtime.command("agent", uuid.uuid4().hex, "wd-2",
                             "bind_contract", {
                                 "policy_id": self.policy.id,
                                 "policy_version": self.policy.version,
                                 "goal": self.policy.goal},
                             work2["state_version"])
        accepted = rotated.record(
            self.envelope("wd-2", second, secret=self.k2.secret,
                          key_id=self.k2.key_id,
                          command_id="cmd-2", event_id="evt-2"))
        self.assertEqual(accepted["decision"], "accepted")
        self.runtime.verify_pending("wd-2")
        self.assertEqual(len(committed_names(self.store_dir)), 3)


if __name__ == "__main__":
    unittest.main()
