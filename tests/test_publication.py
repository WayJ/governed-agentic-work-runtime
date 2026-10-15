"""Governed SOP rule-card publication tests (S12 core wave, D54-D66).

Real runtimes, real SQLite stores and real publication directories throughout
— no mocks. Approver signing keys are fresh random bytes per run and are
never printed or persisted. See docs/sop-authoring.md (publication section)
and docs/file-adapter.md for the declared boundaries.
"""

import copy
import hashlib
import json
import os
import re
import secrets
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from work_runtime import Runtime
from work_runtime.adoption_demo import packaged_card
from work_runtime.authoring import lint_sop, sop_digest
from work_runtime.file_adapter import FilePublisher
from work_runtime.ingress import SignedEvidenceGateway, sign_evidence
from work_runtime.policy import digest
from work_runtime.publication import (
    SopPublicationPolicy,
    SopPublicationStore,
    load_published_card,
    pinned_card,
    publication_key,
    published_card_matches,
)

_HEX_JSON = re.compile(r"[0-9a-f]{64}\.json")
_FLOW_NOW = 2000000000  # Fixed clock keeps gateway freshness deterministic.


def publication_grants():
    """Demo-local grants (design Q7), mirroring publishing_grants()."""
    return {"agent": {"work.manage", "sop.publish"}, "sop-owner": {"evidence.write"}}


def card_with(policy_id="expense-submit", policy_version="demo-1"):
    """A lint-clean card with a replaceable policy identity."""
    card = copy.deepcopy(packaged_card("expense.json"))
    card["policy"]["id"] = policy_id
    card["policy"]["version"] = policy_version
    return card


def doctored_card():
    """The same identity with different lint-clean content (different digest)."""
    card = card_with()
    card["policy"]["goal"] = "expense.accepted.v2-doctored"
    return card


def committed_names(directory):
    return sorted(name for name in os.listdir(directory)
                  if _HEX_JSON.fullmatch(name))


def stage_names(directory):
    return sorted(name for name in os.listdir(directory)
                  if name.endswith(".stage"))


def artifact_name(key):
    return hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json"


def table_counts(path):
    db = sqlite3.connect(str(path))
    try:
        return {t: db.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
                for t in ("works", "commands", "evidence", "operations",
                          "events", "metadata")}
    finally:
        db.close()


def json_read(directory, key):
    with open(os.path.join(str(directory), artifact_name(key)), "rb") as handle:
        return json.loads(handle.read().decode("utf-8"))


class PublicationTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="sop-publication-test-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store_dir = self.root / "store"
        self.runtime_path = self.root / "runtime.sqlite"

    def make_store(self):
        return SopPublicationStore(str(self.store_dir))


class PublicationKeyTests(unittest.TestCase):
    def test_exact_digest_based_key_for_the_packaged_card(self):
        card = packaged_card("expense.json")
        expected = "sop-pub:" + digest([card["policy"]["id"],
                                        card["policy"]["version"]])
        self.assertEqual(publication_key(card), expected)
        key = publication_key(card)
        self.assertTrue(key.startswith("sop-pub:"))
        self.assertRegex(key[len("sop-pub:"):], r"^[0-9a-f]{64}$")

    def test_delimiter_hostile_ids_do_not_collide(self):
        # IR-P16: two lint-clean cards whose (id, version) pairs collide under
        # a delimiter-joined key must not collide under the digest key (D56).
        one = card_with(policy_id="collide:one", policy_version="v1")
        other = card_with(policy_id="collide", policy_version="one:v1")
        self.assertEqual(lint_sop(one), [])
        self.assertEqual(lint_sop(other), [])
        self.assertEqual(one["policy"]["id"] + ":" + one["policy"]["version"],
                         other["policy"]["id"] + ":" + other["policy"]["version"])
        self.assertNotEqual(publication_key(one), publication_key(other))

    def test_identity_changes_change_the_key(self):
        base = card_with()
        self.assertNotEqual(publication_key(card_with(policy_id="other")),
                            publication_key(base))
        self.assertNotEqual(publication_key(card_with(policy_version="v2")),
                            publication_key(base))
        self.assertEqual(publication_key(card_with()), publication_key(base))

    def test_malformed_identity_raises_bounded_valueerror(self):
        for bad in ("not-a-card", {"policy": "nope"}, {"policy": {}},
                    {"policy": {"id": "", "version": "v1"}},
                    {"policy": {"id": "x", "version": ""}},
                    {"policy": {"id": 7, "version": "v1"}},
                    {"policy": {"id": "x", "version": None}}, None, []):
            with self.assertRaises(ValueError) as raised:
                publication_key(bad)
            self.assertIs(type(raised.exception), ValueError)
            message = str(raised.exception)
            self.assertIn("policy", message)
            self.assertNotIn("collide", message)


class SopPublicationStoreTests(PublicationTestCase):
    def test_contract_declares_sop_publish_and_keyed_uniqueness(self):
        contract = self.make_store().contract
        self.assertEqual(contract.actions, ("sop.publish",))
        self.assertEqual(contract.uniqueness, ("publication.key",))

    def test_execute_commits_exactly_one_hash_named_artifact(self):
        store = self.make_store()
        card = card_with()
        receipt = store.execute(publication_key(card), card, sop_digest(card))
        self.assertEqual(receipt["status"], "accepted")
        self.assertTrue(receipt["external_id"].startswith("FILE-"))
        self.assertEqual(receipt["digest"], sop_digest(card))
        self.assertEqual(committed_names(self.store_dir),
                         [artifact_name(publication_key(card))])
        self.assertEqual(stage_names(self.store_dir), [])
        raw = json_read(self.store_dir, publication_key(card))
        self.assertEqual(raw["key"], publication_key(card))
        self.assertEqual(raw["document"], card)
        self.assertEqual(raw["content_digest"], sop_digest(card))
        self.assertEqual(raw["receipt"], receipt)

    def test_replay_returns_the_identical_receipt(self):
        store = self.make_store()
        card = card_with()
        key = publication_key(card)
        first = store.execute(key, card, sop_digest(card))
        self.assertEqual(store.execute(key, card, sop_digest(card)), first)
        restarted = SopPublicationStore(str(self.store_dir))
        self.assertEqual(restarted.execute(key, card, sop_digest(card)), first)
        self.assertEqual(committed_names(self.store_dir),
                         [artifact_name(key)])

    def test_same_key_changed_content_refused_without_overwrite(self):
        store = self.make_store()
        card = card_with()
        key = publication_key(card)
        winner = store.execute(key, card, sop_digest(card))
        before = json_read(self.store_dir, key)
        doctored = doctored_card()  # same identity, different content
        self.assertEqual(publication_key(doctored), key)
        with self.assertRaises(ValueError) as raised:
            store.execute(key, doctored, sop_digest(doctored))
        self.assertIs(type(raised.exception), ValueError)
        self.assertEqual(json_read(self.store_dir, key), before)
        self.assertEqual(store.lookup(key), winner)

    def test_lookup_delegates_to_the_committed_artifact(self):
        store = self.make_store()
        card = card_with()
        receipt = store.execute(publication_key(card), card, sop_digest(card))
        self.assertEqual(store.lookup(publication_key(card)), receipt)
        self.assertIsNone(store.lookup("sop-pub:" + "0" * 64))



class LoaderPinTests(PublicationTestCase):
    """Fail-closed read path (D62): absent/corrupt/digest/identity errors
    are bounded and distinguishable; no fallback, no silent skip, no Runtime
    wiring, no directory-creation side effect on reads."""

    def publish(self, card):
        store = self.make_store()
        receipt = store.execute(publication_key(card), card, sop_digest(card))
        return receipt

    def test_round_trip_returns_the_published_card_with_matching_digest(self):
        card = card_with()
        receipt = self.publish(card)
        loaded = load_published_card(str(self.store_dir), "expense-submit", "demo-1")
        self.assertEqual(loaded, card)
        raw = json_read(self.store_dir, publication_key(card))
        self.assertEqual(sop_digest(loaded), raw["content_digest"])
        self.assertEqual(receipt["digest"], sop_digest(loaded))

    def test_absent_version_raises_bounded_distinguishable_error(self):
        self.publish(card_with())
        with self.assertRaises(ValueError) as raised:
            load_published_card(str(self.store_dir), "expense-submit", "v2")
        message = str(raised.exception)
        self.assertIs(type(raised.exception), ValueError)
        self.assertIn("no published card", message)
        # Distinguishable from corruption classes: none of the file-adapter
        # corruption messages or the lint message may equal this one.
        for other in ("committed artifact is not valid UTF-8 JSON",
                      "SOP is not lint-clean"):
            self.assertNotEqual(message, other)

    def test_missing_directory_raises_absent_without_creating_it(self):
        missing = self.root / "never-created"
        with self.assertRaises(ValueError) as raised:
            load_published_card(str(missing), "expense-submit", "demo-1")
        self.assertIn("no published card", str(raised.exception))
        self.assertFalse(missing.exists())

    def test_corrupt_bytes_raise_bounded_valueerror(self):
        card = card_with()
        self.publish(card)
        target = os.path.join(str(self.store_dir),
                              artifact_name(publication_key(card)))
        with open(target, "wb") as handle:
            handle.write(b"not json")
        with self.assertRaises(ValueError) as raised:
            load_published_card(str(self.store_dir), "expense-submit", "demo-1")
        self.assertIs(type(raised.exception), ValueError)
        self.assertIn("committed artifact", str(raised.exception))

    def test_tampered_document_with_stale_digest_raises(self):
        card = card_with()
        self.publish(card)
        raw = json_read(self.store_dir, publication_key(card))
        raw["document"]["policy"]["goal"] = "doctored.after.commit"
        with open(os.path.join(str(self.store_dir),
                               artifact_name(publication_key(card))), "w") as handle:
            json.dump(raw, handle)
        with self.assertRaises(ValueError) as raised:
            load_published_card(str(self.store_dir), "expense-submit", "demo-1")
        self.assertIs(type(raised.exception), ValueError)

    def test_doctored_key_field_raises(self):
        card = card_with()
        self.publish(card)
        raw = json_read(self.store_dir, publication_key(card))
        raw["key"] = "sop-pub:someone-elses-key"
        with open(os.path.join(str(self.store_dir),
                               artifact_name(publication_key(card))), "w") as handle:
            json.dump(raw, handle)
        with self.assertRaises(ValueError):
            load_published_card(str(self.store_dir), "expense-submit", "demo-1")

    def test_other_card_committed_under_this_key_fails_closed(self):
        # Cross-database/doctored store (MD-4 class): raw FilePublisher use
        # can commit ANY content under this key; the loader must refuse.
        other = card_with(policy_id="a-different-policy")
        key = publication_key(card_with())
        FilePublisher(str(self.store_dir)).execute(key, other, sop_digest(other))
        with self.assertRaises(ValueError) as raised:
            load_published_card(str(self.store_dir), "expense-submit", "demo-1")
        self.assertNotIn("no published card", str(raised.exception))

    def test_non_card_document_committed_under_this_key_fails_closed(self):
        key = publication_key(card_with())
        document = {"id": "ART-001", "title": "not a card"}
        FilePublisher(str(self.store_dir)).execute(key, document, digest(document))
        with self.assertRaises(ValueError) as raised:
            load_published_card(str(self.store_dir), "expense-submit", "demo-1")
        self.assertIs(type(raised.exception), ValueError)

    def test_pinned_card_requires_the_exact_pin(self):
        card = card_with()
        self.publish(card)
        pinned = pinned_card(str(self.store_dir), "expense-submit", "demo-1",
                             sop_digest(card))
        self.assertEqual(pinned, card)
        with self.assertRaises(ValueError) as raised:
            pinned_card(str(self.store_dir), "expense-submit", "demo-1", "0" * 64)
        self.assertIn("pin", str(raised.exception).lower())
        for bad in ("", 7, None):
            with self.assertRaises(ValueError):
                pinned_card(str(self.store_dir), "expense-submit", "demo-1", bad)

    def test_published_card_matches_compares_identity_and_goal_only(self):
        from work_runtime import ExpensePolicy
        card = packaged_card("expense.json")
        self.assertTrue(published_card_matches(card, ExpensePolicy()))
        self.assertTrue(published_card_matches(card, ExpensePolicy()))  # pure
        changed_version = copy.deepcopy(card)
        changed_version["policy"]["version"] = "v2"
        self.assertFalse(published_card_matches(changed_version, ExpensePolicy()))
        changed_goal = copy.deepcopy(card)
        changed_goal["policy"]["goal"] = "something.else"
        self.assertFalse(published_card_matches(changed_goal, ExpensePolicy()))
        self.assertFalse(published_card_matches("not a card", ExpensePolicy()))
        self.assertFalse(published_card_matches({}, ExpensePolicy()))


class ResponseLossPublicationStore:
    """Composition wrapper mirroring adoption_demo.ResponseLossPublisher:
    the real store commits, then the response is lost after the effect."""

    def __init__(self, store):
        self._store = store
        self.contract = store.contract  # surfaced, never bypassed

    def execute(self, key, document, content_digest):
        self._store.execute(key, document, content_digest)
        raise TimeoutError("response lost after the publication commit")

    def lookup(self, key):
        return self._store.lookup(key)


def evidence_bodies(path):
    db = sqlite3.connect(str(path))
    try:
        return [json.loads(row[0]) for row in
                db.execute("SELECT body FROM evidence ORDER BY rowid")]
    finally:
        db.close()


class GovernedFlowTests(PublicationTestCase):
    """The full RFC-002 §6 story on a real Runtime, SQLite and directory."""

    def setUp(self):
        super().setUp()
        self.policy = SopPublicationPolicy()
        self.grants = publication_grants()
        self.runtime = Runtime(str(self.runtime_path), self.policy, self.grants)
        self.approver_key = secrets.token_bytes(32)  # never printed
        self.gateway = SignedEvidenceGateway(
            self.runtime, {"sop-owner": self.approver_key},
            clock=lambda: DEMO_NOW if False else _FLOW_NOW)

    def _send(self, runtime, work_id, kind, payload=None, actor="agent",
              command_id=None, version=None):
        if version is None and kind not in ("create_work", "record_evidence"):
            version = runtime.get_work(work_id)["state_version"]
        return runtime.command(actor, command_id or uuid.uuid4().hex, work_id,
                               kind, payload, version)

    def _propose(self, runtime, work_id, command_id=None, version=None):
        work = runtime.get_work(work_id)
        if version is None:
            version = work["state_version"]
        return self._send(runtime, work_id, "propose_action", {
            "capability": "sop.publish", "document_digest": work["document_digest"],
            "contract_revision": work["contract"]["revision"],
            "plan_revision": work["plan_revision"]}, command_id=command_id,
            version=version)

    def _signed_approval(self, runtime, work_id, card, digest_value=None,
                         policy_version=None, command_id=None, event_id=None):
        work = runtime.get_work(work_id)
        return sign_evidence(self.approver_key, {
            "source": "sop-owner", "command_id": command_id or uuid.uuid4().hex,
            "work_id": work_id, "event_id": event_id or uuid.uuid4().hex,
            "kind": "card_approval",
            "data": {"digest": digest_value or work["document_digest"],
                     "policy_version": policy_version
                     or card["policy"]["version"]},
            "issued_at": _FLOW_NOW})

    def _establish(self, runtime, card, work_id):
        self._send(runtime, work_id, "create_work", {"document": card})
        self._send(runtime, work_id, "bind_contract", {
            "policy_id": self.policy.id, "policy_version": self.policy.version,
            "goal": self.policy.goal})

    def _approve(self, runtime, work_id, card, **overrides):
        receipt = self.gateway.record(
            self._signed_approval(runtime, work_id, card, **overrides))
        assert receipt["decision"] == "accepted", receipt
        runtime.verify_pending(work_id)

    def test_dirty_card_is_refused_unpersisted_at_admission(self):
        dirty = card_with()
        dirty["rogue_field"] = 1  # UNKNOWN_FIELD
        with self.assertRaises(ValueError) as raised:
            self._send(self.runtime, "pub-1", "create_work", {"document": dirty})
        self.assertIs(type(raised.exception), ValueError)
        self.assertIn("lint-clean", str(raised.exception))
        self.assertEqual(table_counts(self.runtime_path)["works"], 0)
        self.assertFalse(self.store_dir.exists())  # nothing committed anywhere

    def test_clean_card_document_digest_equals_sop_digest(self):
        card = card_with()
        self._establish(self.runtime, card, "pub-1")
        work = self.runtime.get_work("pub-1")
        self.assertEqual(work["document_digest"], sop_digest(card))
        self.assertEqual(work["document"], card)

    def test_proposal_before_approval_is_blocked_pending_s02(self):
        card = card_with()
        self._establish(self.runtime, card, "pub-1")
        blocked = self._propose(self.runtime, "pub-1")
        self.assertEqual(blocked["decision"], "rejected")
        self.assertEqual(blocked["code"], "REQUIREMENT_UNSATISFIED")
        self.assertTrue(any(b["id"].startswith("S02:")
                            for b in blocked["blockers"]))
        self.assertFalse(self.store_dir.exists())

    def test_tampered_approval_rejected_before_any_intake_write(self):
        card = card_with()
        self._establish(self.runtime, card, "pub-1")
        tampered = self._signed_approval(self.runtime, "pub-1", card)
        tampered["data"]["digest"] = "0" * 64  # forged after signing
        before = table_counts(self.runtime_path)
        rejection = self.gateway.record(tampered)
        self.assertEqual(rejection,
                         {"decision": "rejected",
                          "code": "EVIDENCE_AUTHENTICATION_FAILED"})
        self.assertEqual(table_counts(self.runtime_path), before)

    def test_wrong_source_intake_is_authority_denied(self):
        card = card_with()
        self._establish(self.runtime, card, "pub-1")
        other_key = secrets.token_bytes(32)
        gateway = SignedEvidenceGateway(
            self.runtime, {"sop-owner": self.approver_key, "other": other_key},
            clock=lambda: _FLOW_NOW)
        envelope = sign_evidence(other_key, {
            "source": "other", "command_id": uuid.uuid4().hex, "work_id": "pub-1",
            "event_id": uuid.uuid4().hex, "kind": "card_approval",
            "data": {"digest": self.runtime.get_work("pub-1")["document_digest"],
                     "policy_version": card["policy"]["version"]},
            "issued_at": _FLOW_NOW})
        receipt = gateway.record(envelope)
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "AUTHORITY_DENIED")
        self.assertEqual(table_counts(self.runtime_path)["evidence"], 0)

    def test_wrong_version_approval_is_candidate_then_unsatisfied(self):
        card = card_with()
        self._establish(self.runtime, card, "pub-1")
        receipt = self.gateway.record(
            self._signed_approval(self.runtime, "pub-1", card,
                                  policy_version="v9"))
        self.assertEqual(receipt["decision"], "accepted")
        self.assertEqual(receipt["evidence_status"], "pending_verification")
        self.runtime.verify_pending("pub-1")
        statuses = {e["kind"]: e["status"] for e in
                    evidence_bodies(self.runtime_path)}
        self.assertEqual(statuses["card_approval"], "invalid")
        blocked = self._propose(self.runtime, "pub-1")
        self.assertEqual(blocked["code"], "REQUIREMENT_UNSATISFIED")

    def test_wrong_digest_approval_verifies_shape_but_keeps_s02_pending(self):
        card = card_with()
        self._establish(self.runtime, card, "pub-1")
        receipt = self.gateway.record(
            self._signed_approval(self.runtime, "pub-1", card,
                                  digest_value=sop_digest(doctored_card())))
        self.assertEqual(receipt["decision"], "accepted")
        self.runtime.verify_pending("pub-1")
        statuses = {e["kind"]: e["status"] for e in
                    evidence_bodies(self.runtime_path)}
        self.assertEqual(statuses["card_approval"], "verified")
        blocked = self._propose(self.runtime, "pub-1")
        self.assertEqual(blocked["code"], "REQUIREMENT_UNSATISFIED")

    def test_valid_signed_approval_verifies_and_proposal_accepts(self):
        card = card_with()
        self._establish(self.runtime, card, "pub-1")
        self._approve(self.runtime, "pub-1", card)
        intent = self._propose(self.runtime, "pub-1", command_id="publish-once")
        self.assertEqual(intent["decision"], "accepted")
        operation = self.runtime.get_operation(intent["operation_id"])
        self.assertEqual(operation["business_key"], publication_key(card))

    def test_dispatch_response_loss_then_one_attempt_reconcile(self):
        card = card_with()
        self._establish(self.runtime, card, "pub-1")
        self._approve(self.runtime, "pub-1", card)
        intent = self._propose(self.runtime, "pub-1")
        store = self.make_store()
        unknown = self.runtime.dispatch(
            intent["operation_id"], ResponseLossPublicationStore(store))
        self.assertEqual(unknown["status"], "outcome_unknown")
        self.assertEqual(committed_names(self.store_dir),
                         [artifact_name(publication_key(card))])
        self.assertEqual(stage_names(self.store_dir), [])
        self.assertEqual(json_read(self.store_dir, publication_key(card))["document"],
                         card)
        restarted = Runtime(str(self.runtime_path), self.policy, self.grants)
        recovered = restarted.reconcile(intent["operation_id"], self.make_store())
        self.assertEqual(recovered["status"], "confirmed_succeeded")
        self.assertEqual(len(restarted.get_operation(intent["operation_id"])
                            ["attempts"]), 1)
        self.assertEqual(committed_names(self.store_dir),
                         [artifact_name(publication_key(card))])

    def test_accepted_proof_is_runtime_written_under_the_store_source(self):
        card = card_with()
        self._establish(self.runtime, card, "pub-1")
        self._approve(self.runtime, "pub-1", card)
        intent = self._propose(self.runtime, "pub-1")
        resolved = self.runtime.dispatch(intent["operation_id"], self.make_store())
        self.assertEqual(resolved["status"], "confirmed_succeeded")
        self.assertNotIn("sop-store", self.grants)  # no principal can sign as it
        proofs = [e for e in evidence_bodies(self.runtime_path)
                  if e["kind"] == "accepted"]
        self.assertEqual(len(proofs), 1)
        proof = proofs[0]
        self.assertEqual(proof["source"], "sop-store")
        self.assertEqual(proof["event_id"], intent["operation_id"])
        self.assertEqual(proof["status"], "verified")
        self.assertEqual(proof["data"]["digest"], sop_digest(card))
        self.assertTrue(proof["data"]["external_id"].startswith("FILE-"))

    def test_completion_closes_the_work_succeeded(self):
        card = card_with()
        self._establish(self.runtime, card, "pub-1")
        self._approve(self.runtime, "pub-1", card)
        intent = self._propose(self.runtime, "pub-1")
        self.runtime.dispatch(intent["operation_id"], self.make_store())
        completion = self._send(self.runtime, "pub-1", "request_completion",
                                command_id="complete")
        self.assertEqual(completion["decision"], "accepted")
        work = self.runtime.get_work("pub-1")
        self.assertEqual((work["status"], work["outcome"]),
                         ("closed", "succeeded"))
        self.assertTrue(work["completion"]["evidence"])
        self.assertEqual(committed_names(self.store_dir),
                         [artifact_name(publication_key(card))])

    def test_command_replay_returns_the_stored_receipt_verbatim(self):
        card = card_with()
        self._establish(self.runtime, card, "pub-1")
        self._approve(self.runtime, "pub-1", card)
        version = self.runtime.get_work("pub-1")["state_version"]
        first = self._propose(self.runtime, "pub-1", command_id="publish-once",
                              version=version)
        again = self._propose(self.runtime, "pub-1", command_id="publish-once",
                              version=version)
        self.assertEqual(again, first)
        operations = table_counts(self.runtime_path)["operations"]
        self.assertEqual(operations, 1)

    def test_cross_work_same_card_conflicts_only_after_its_own_approval(self):
        card = card_with()
        self._establish(self.runtime, card, "pub-1")
        self._approve(self.runtime, "pub-1", card)
        self.runtime.dispatch(
            self._propose(self.runtime, "pub-1")["operation_id"],
            self.make_store())
        self._establish(self.runtime, card, "pub-2")
        blocked = self._propose(self.runtime, "pub-2")
        self.assertEqual(blocked["code"], "REQUIREMENT_UNSATISFIED")  # D66 order
        self._approve(self.runtime, "pub-2", card)
        conflict = self._propose(self.runtime, "pub-2")
        self.assertEqual(conflict["decision"], "rejected")
        self.assertEqual(conflict["code"], "OPERATION_CONTENT_CONFLICT")
        self.assertEqual(len(committed_names(self.store_dir)), 1)

    def test_doctored_same_version_card_conflicts_after_its_own_approval(self):
        card = card_with()
        self._establish(self.runtime, card, "pub-1")
        self._approve(self.runtime, "pub-1", card)
        self.runtime.dispatch(
            self._propose(self.runtime, "pub-1")["operation_id"],
            self.make_store())
        winner_bytes = Path(os.path.join(
            str(self.store_dir), artifact_name(publication_key(card)))).read_bytes()
        doctored = doctored_card()  # same (id, version), different content
        self.assertEqual(publication_key(doctored), publication_key(card))
        self._establish(self.runtime, doctored, "pub-2")
        blocked = self._propose(self.runtime, "pub-2")
        self.assertEqual(blocked["code"], "REQUIREMENT_UNSATISFIED")  # D66 order
        self._approve(self.runtime, "pub-2", doctored)
        conflict = self._propose(self.runtime, "pub-2")
        self.assertEqual(conflict["code"], "OPERATION_CONTENT_CONFLICT")
        after = Path(os.path.join(
            str(self.store_dir), artifact_name(publication_key(card)))).read_bytes()
        self.assertEqual(after, winner_bytes)  # artifact untouched
        self.assertEqual(len(committed_names(self.store_dir)), 1)
