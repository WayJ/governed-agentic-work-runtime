"""Publication approver-key rotation battery (S12 core wave, story 4).

Pins the S11 rotation semantics on the publication family's approver
keyring: retired/dropped refusals with zero writes, cached-receipt verbatim
replay, current-status resend, and six-table plus committed-artifact byte
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
from work_runtime.ingress import SignedEvidenceGateway, SourceKey, sign_evidence
from work_runtime.publication import (
    SopPublicationPolicy,
    SopPublicationStore,
    publication_key,
)
from work_runtime.authoring import sop_digest
from tests.test_publication import (
    artifact_name,
    card_with,
    committed_names,
    publication_grants,
)

NOW = 2000000000  # Fixed clock keeps windows and freshness deterministic.
TABLES = ("works", "commands", "evidence", "operations", "events", "metadata")


def key():
    return secrets.token_bytes(32)


class PublicationRotationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="sop-pub-rotation-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.runtime_path = str(self.root / "runtime.sqlite")
        self.store_dir = str(self.root / "store")
        self.policy = SopPublicationPolicy()
        self.grants = publication_grants()
        self.runtime = Runtime(self.runtime_path, self.policy, self.grants)
        self.k1 = SourceKey("ring-2026-08", key(), current=True)
        self.k2 = SourceKey("ring-2026-10", key())

    def gateway(self, ring=None):
        return SignedEvidenceGateway(
            self.runtime, {"sop-owner": ring or [self.k1, self.k2]},
            clock=lambda: NOW)

    def rotated_retained(self):
        # Old key kept in the ring but its window has closed.
        return [SourceKey(self.k1.key_id, self.k1.secret, not_after=NOW - 10),
                SourceKey(self.k2.key_id, self.k2.secret, current=True)]

    def rotated_dropped(self):
        return [SourceKey(self.k2.key_id, self.k2.secret, current=True)]

    def establish(self, runtime, card, work_id):
        version = None
        runtime.command("agent", uuid.uuid4().hex, work_id, "create_work",
                        {"document": card}, version)
        work = runtime.get_work(work_id)
        runtime.command("agent", uuid.uuid4().hex, work_id, "bind_contract", {
            "policy_id": self.policy.id, "policy_version": self.policy.version,
            "goal": self.policy.goal}, work["state_version"])

    def signed(self, secret, work_id, digest_value, policy_version,
               key_id=None, command_id=None, event_id=None):
        message = {"source": "sop-owner",
                   "command_id": command_id or uuid.uuid4().hex,
                   "work_id": work_id,
                   "event_id": event_id or uuid.uuid4().hex,
                   "kind": "card_approval",
                   "data": {"digest": digest_value,
                            "policy_version": policy_version},
                   "issued_at": NOW}
        if key_id is not None:
            message["key_id"] = key_id
        return sign_evidence(secret, message)

    def approval_envelope(self, work_id, card, secret=None, key_id=None,
                          command_id=None, event_id=None):
        work = self.runtime.get_work(work_id)
        return self.signed(secret or self.k1.secret, work_id,
                           work["document_digest"],
                           card["policy"]["version"], key_id=key_id,
                           command_id=command_id, event_id=event_id)

    def table_dump(self, path=None):
        dump = {}
        with sqlite3.connect(path or self.runtime_path) as db:
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
        card = card_with()
        self.establish(self.runtime, card, "pub-1")
        accepted = self.gateway().record(
            self.approval_envelope("pub-1", card, key_id=self.k1.key_id,
                                   command_id="cmd-a", event_id="evt-1"))
        self.assertEqual(accepted["decision"], "accepted")
        before = self.table_dump()
        refused = self.gateway(ring=self.rotated_retained()).record(
            self.approval_envelope("pub-1", card, secret=self.k1.secret,
                                   key_id=self.k1.key_id,
                                   command_id="cmd-z", event_id="evt-z"))
        self.assertEqual(refused,
                         {"decision": "rejected", "code": "EVIDENCE_KEY_RETIRED"})
        self.assertEqual(self.table_dump(), before)

    def test_dropped_old_key_refuses_authentication(self):
        card = card_with()
        self.establish(self.runtime, card, "pub-1")
        self.gateway().record(
            self.approval_envelope("pub-1", card, key_id=self.k1.key_id,
                                   command_id="cmd-a", event_id="evt-1"))
        before = self.table_dump()
        # A selector-less legacy envelope authenticated only against the
        # current entry: the dropped key cannot reach the runtime.
        refused = self.gateway(ring=self.rotated_dropped()).record(
            self.approval_envelope("pub-1", card, secret=self.k1.secret,
                                   command_id="cmd-z", event_id="evt-z"))
        self.assertEqual(refused,
                         {"decision": "rejected",
                          "code": "EVIDENCE_AUTHENTICATION_FAILED"})
        cited = self.gateway(ring=self.rotated_dropped()).record(
            self.approval_envelope("pub-1", card, secret=self.k1.secret,
                                   key_id=self.k1.key_id,
                                   command_id="cmd-y", event_id="evt-y"))
        self.assertEqual(cited["code"], "EVIDENCE_AUTHENTICATION_FAILED")
        self.assertEqual(self.table_dump(), before)

    def test_same_command_id_resign_replays_original_receipt_verbatim(self):
        card = card_with()
        self.establish(self.runtime, card, "pub-1")
        first = self.gateway().record(
            self.approval_envelope("pub-1", card, key_id=self.k1.key_id,
                                   command_id="cmd-a", event_id="evt-1"))
        self.assertEqual(first["decision"], "accepted")
        rotated = self.gateway(ring=self.rotated_retained())
        before = self.table_dump()
        replay = rotated.record(
            self.approval_envelope("pub-1", card, secret=self.k2.secret,
                                   key_id=self.k2.key_id,
                                   command_id="cmd-a", event_id="evt-1"))
        self.assertEqual(replay, first)  # verbatim, zero writes
        self.assertEqual(self.table_dump(), before)

    def test_new_command_id_same_event_reports_current_status(self):
        card = card_with()
        self.establish(self.runtime, card, "pub-1")
        first = self.gateway().record(
            self.approval_envelope("pub-1", card, key_id=self.k1.key_id,
                                   command_id="cmd-a", event_id="evt-1"))
        rotated = self.gateway(ring=self.rotated_retained())
        before = self.table_counts()
        status = rotated.record(
            self.approval_envelope("pub-1", card, secret=self.k2.secret,
                                   key_id=self.k2.key_id,
                                   command_id="cmd-b", event_id="evt-1"))
        self.assertEqual(status["decision"], "accepted")
        self.assertEqual(status["evidence_id"], first["evidence_id"])
        self.assertEqual(status["evidence_status"], "pending_verification")
        after = self.table_counts()
        self.assertEqual(after["commands"], before["commands"] + 1)
        self.assertEqual(after["evidence"], before["evidence"])

    def test_rotation_untouches_publication_history(self):
        card = card_with()
        self.establish(self.runtime, card, "pub-1")
        self.gateway().record(
            self.approval_envelope("pub-1", card, key_id=self.k1.key_id,
                                   command_id="cmd-a", event_id="evt-1"))
        self.runtime.verify_pending("pub-1")
        work = self.runtime.get_work("pub-1")
        intent = self.runtime.command(
            "agent", "publish-once", "pub-1", "propose_action", {
                "capability": "sop.publish",
                "document_digest": work["document_digest"],
                "contract_revision": work["contract"]["revision"],
                "plan_revision": work["plan_revision"]},
            work["state_version"])
        self.assertEqual(intent["decision"], "accepted")
        self.runtime.dispatch(intent["operation_id"],
                              SopPublicationStore(self.store_dir))
        tables = self.table_dump()
        artifacts = self.store_dump()
        self.assertEqual(list(artifacts), [artifact_name(publication_key(card))])
        # Every refusal class after rotation writes nothing anywhere.
        denials = (
            self.gateway(ring=self.rotated_retained()).record(
                self.approval_envelope("pub-1", card, secret=self.k1.secret,
                                       key_id=self.k1.key_id,
                                       command_id="cmd-z", event_id="evt-z")),
            self.gateway(ring=self.rotated_dropped()).record(
                self.approval_envelope("pub-1", card, secret=self.k1.secret,
                                       key_id=self.k1.key_id,
                                       command_id="cmd-y", event_id="evt-y")),
        )
        for receipt in denials:
            self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(self.table_dump(), tables)
        self.assertEqual(self.store_dump(), artifacts)

    def test_mid_flow_rotation_continues_with_old_and_new_keys(self):
        first_card = card_with()
        self.establish(self.runtime, first_card, "pub-1")
        # Pre-rotation approval recorded while k1 was current.
        self.gateway().record(
            self.approval_envelope("pub-1", first_card, key_id=self.k1.key_id,
                                   command_id="cmd-1", event_id="evt-1"))
        rotated = self.gateway(ring=self.rotated_retained())
        # Fingerprints are key-agnostic: the pre-rotation approval still
        # verifies and carries its work to a completed publication.
        self.runtime.verify_pending("pub-1")
        work = self.runtime.get_work("pub-1")
        intent = self.runtime.command(
            "agent", "publish-v1", "pub-1", "propose_action", {
                "capability": "sop.publish",
                "document_digest": work["document_digest"],
                "contract_revision": work["contract"]["revision"],
                "plan_revision": work["plan_revision"]},
            work["state_version"])
        self.runtime.dispatch(intent["operation_id"],
                              SopPublicationStore(self.store_dir))
        self.assertEqual(self.runtime.get_operation(intent["operation_id"])
                         ["status"], "confirmed_succeeded")
        # A legitimate NEW version continues under the rotated key.
        second_card = card_with(policy_version="v2")
        self.assertNotEqual(publication_key(second_card),
                            publication_key(first_card))
        self.establish(self.runtime, second_card, "pub-2")
        accepted = rotated.record(
            self.approval_envelope("pub-2", second_card, secret=self.k2.secret,
                                   key_id=self.k2.key_id,
                                   command_id="cmd-2", event_id="evt-2"))
        self.assertEqual(accepted["decision"], "accepted")
        self.runtime.verify_pending("pub-2")
        work2 = self.runtime.get_work("pub-2")
        intent2 = self.runtime.command(
            "agent", "publish-v2", "pub-2", "propose_action", {
                "capability": "sop.publish",
                "document_digest": work2["document_digest"],
                "contract_revision": work2["contract"]["revision"],
                "plan_revision": work2["plan_revision"]},
            work2["state_version"])
        self.assertEqual(intent2["decision"], "accepted")
        self.runtime.dispatch(intent2["operation_id"],
                              SopPublicationStore(self.store_dir))
        self.assertEqual(self.runtime.get_operation(intent2["operation_id"])
                         ["status"], "confirmed_succeeded")
        self.assertEqual(sorted(self.store_dump()),
                         sorted([artifact_name(publication_key(first_card)),
                                 artifact_name(publication_key(second_card))]))
