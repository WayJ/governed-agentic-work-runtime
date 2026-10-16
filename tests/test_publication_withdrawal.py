"""Published-card withdrawal tests (S13 core wave, D67-D79).

Real runtimes, real SQLite stores and real publication directories throughout
— no mocks. Approver signing keys are fresh random bytes per run and are
never printed or persisted. See docs/sop-authoring.md (withdrawal section)
and the S13 design spec for the ratified boundaries.
"""

import json
import os
import secrets
import unittest
import uuid

from work_runtime import Runtime
from work_runtime.authoring import sop_digest
from work_runtime.file_adapter import FilePublisher
from work_runtime.ingress import SignedEvidenceGateway, sign_evidence
from work_runtime.policy import digest
from work_runtime.publication import (
    WITHDRAWAL_DISCRIMINATOR,
    WITHDRAWAL_KEY_PREFIX,
    WITHDRAWAL_RECORD_INVALID_MESSAGE,
    WITHDRAWAL_REQUEST_KEYS,
    WITHDRAWAL_TARGET_ABSENT,
    WITHDRAWAL_TARGET_DIGEST,
    WITHDRAWN_MESSAGE,
    SopPublicationPolicy,
    SopPublicationStore,
    SopWithdrawalStore,
    is_withdrawal_request,
    load_published_card,
    pinned_card,
    publication_key,
    published_card_matches,
    withdrawal_key,
    withdrawal_record,
)
from tests.test_publication import (
    artifact_name,
    card_with,
    committed_names,
    evidence_bodies,
    json_read,
    stage_names,
    table_counts,
)

FLOW_NOW = 2000000000  # Fixed clock keeps gateway freshness deterministic.


def withdrawal_request(policy_id="expense-submit", policy_version="demo-1",
                       published_digest=None):
    """The closed deterministic withdrawal record document (D69)."""
    return {
        "discriminator": WITHDRAWAL_DISCRIMINATOR,
        "policy_id": policy_id,
        "policy_version": policy_version,
        "published_digest": (published_digest if published_digest is not None
                             else digest({"placeholder": policy_version})),
    }


def withdrawal_grants():
    """Demo-local grants: the agent's set gains sop.withdraw (Q3/D71)."""
    return {"agent": {"work.manage", "sop.publish", "sop.withdraw"},
            "sop-owner": {"evidence.write"}}


class WithdrawalTestCase(unittest.TestCase):
    def setUp(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory(prefix="sop-withdrawal-test-")
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.store_dir = os.path.join(self.root, "store")

    def publish(self, card, directory=None):
        store = SopPublicationStore(directory or self.store_dir)
        return store.execute(publication_key(card), card, sop_digest(card))


class WithdrawalKeyTests(unittest.TestCase):
    def test_exact_digest_based_key(self):
        expected = ("sop-withdrawn:"
                    + digest(["expense-submit", "demo-1"]))
        self.assertEqual(withdrawal_key("expense-submit", "demo-1"), expected)
        key = withdrawal_key("expense-submit", "demo-1")
        self.assertTrue(key.startswith("sop-withdrawn:"))
        self.assertRegex(key[len("sop-withdrawn:"):], r"^[0-9a-f]{64}$")

    def test_delimiter_hostile_ids_do_not_collide(self):
        # D56 basis (R3): a delimiter-joined key would collide here.
        self.assertNotEqual(withdrawal_key("collide:one", "v1"),
                            withdrawal_key("collide", "one:v1"))

    def test_identity_changes_change_the_key(self):
        base = withdrawal_key("expense-submit", "demo-1")
        self.assertNotEqual(withdrawal_key("other", "demo-1"), base)
        self.assertNotEqual(withdrawal_key("expense-submit", "v2"), base)
        self.assertEqual(withdrawal_key("expense-submit", "demo-1"), base)

    def test_withdrawal_key_differs_from_publication_key(self):
        card = card_with()
        self.assertNotEqual(withdrawal_key(card["policy"]["id"],
                                           card["policy"]["version"]),
                            publication_key(card))

    def test_malformed_identity_raises_bounded_valueerror(self):
        for bad in (("", "v1"), ("x", ""), (7, "v1"), ("x", None), (None, None)):
            with self.assertRaises(ValueError) as raised:
                withdrawal_key(*bad)
            self.assertIs(type(raised.exception), ValueError)
            message = str(raised.exception)
            self.assertIn("identity", message)
            self.assertNotIn("collide", message)


class WithdrawalRequestTests(unittest.TestCase):
    def test_exact_closed_shape_is_a_withdrawal_request(self):
        request = withdrawal_request()
        self.assertTrue(is_withdrawal_request(request))
        self.assertEqual(set(request), WITHDRAWAL_REQUEST_KEYS)

    def test_cards_and_malformed_shapes_are_not_withdrawal_requests(self):
        card = card_with()
        self.assertFalse(is_withdrawal_request(card))
        self.assertFalse(is_withdrawal_request("not a document"))
        self.assertFalse(is_withdrawal_request(None))
        self.assertFalse(is_withdrawal_request([]))
        wrong_discriminator = withdrawal_request()
        wrong_discriminator["discriminator"] = "sop.publish"
        self.assertFalse(is_withdrawal_request(wrong_discriminator))
        extra = withdrawal_request()
        extra["reason"] = "operator note"
        self.assertFalse(is_withdrawal_request(extra))  # no free text (D69)
        missing = withdrawal_request()
        del missing["published_digest"]
        self.assertFalse(is_withdrawal_request(missing))
        empty_digest = withdrawal_request(published_digest="")
        self.assertFalse(is_withdrawal_request(empty_digest))
        non_str = withdrawal_request()
        non_str["policy_id"] = 7
        self.assertFalse(is_withdrawal_request(non_str))


class SopWithdrawalStoreTests(WithdrawalTestCase):
    def setUp(self):
        super().setUp()
        self.card = card_with()
        self.publish(self.card)
        self.target_digest = sop_digest(self.card)
        self.request = withdrawal_request(
            published_digest=self.target_digest)
        self.wkey = withdrawal_key("expense-submit", "demo-1")

    def make_store(self):
        return SopWithdrawalStore(self.store_dir)

    def test_contract_declares_sop_withdraw_and_keyed_uniqueness(self):
        contract = self.make_store().contract
        self.assertEqual(contract.actions, ("sop.withdraw",))
        self.assertEqual(contract.uniqueness, ("withdrawal.key",))

    def test_execute_commits_exactly_one_second_record_artifact(self):
        receipt = self.make_store().execute(
            self.wkey, self.request, digest(self.request))
        self.assertEqual(receipt["status"], "accepted")
        self.assertEqual(receipt["digest"], digest(self.request))
        self.assertEqual(committed_names(self.store_dir),
                         sorted([artifact_name(publication_key(self.card)),
                                 artifact_name(self.wkey)]))
        self.assertEqual(stage_names(self.store_dir), [])
        raw = json_read(self.store_dir, self.wkey)
        self.assertEqual(raw["key"], self.wkey)
        self.assertEqual(raw["document"], self.request)
        self.assertEqual(raw["content_digest"], digest(self.request))
        self.assertEqual(raw["receipt"], receipt)

    def test_replay_returns_the_identical_receipt(self):
        store = self.make_store()
        first = store.execute(self.wkey, self.request, digest(self.request))
        self.assertEqual(
            store.execute(self.wkey, self.request, digest(self.request)),
            first)
        restarted = SopWithdrawalStore(self.store_dir)
        self.assertEqual(
            restarted.execute(self.wkey, self.request, digest(self.request)),
            first)
        self.assertEqual(len(committed_names(self.store_dir)), 2)

    def test_absent_target_returns_a_rejected_receipt_without_writes(self):
        ghost = withdrawal_request(policy_id="never-published",
                                   policy_version="v1",
                                   published_digest="a" * 64)
        before = committed_names(self.store_dir)
        receipt = self.make_store().execute(
            withdrawal_key("never-published", "v1"), ghost, digest(ghost))
        self.assertEqual(receipt["status"], "rejected")
        self.assertEqual(receipt["digest"], digest(ghost))
        self.assertEqual(receipt["reason"], WITHDRAWAL_TARGET_ABSENT)
        self.assertTrue(receipt["external_id"].startswith(
            "SOP-WITHDRAWAL-REFUSED-"))
        replayed = self.make_store().execute(
            withdrawal_key("never-published", "v1"), ghost, digest(ghost))
        self.assertEqual(replayed, receipt)  # deterministic refusal id
        self.assertEqual(committed_names(self.store_dir), before)

    def test_digest_mismatch_returns_a_rejected_receipt(self):
        doctored_digest = sop_digest(card_with(policy_version="other"))
        self.assertNotEqual(doctored_digest, self.target_digest)
        wrong = withdrawal_request(published_digest=doctored_digest)
        publication_bytes = json_read(self.store_dir,
                                      publication_key(self.card))
        receipt = self.make_store().execute(self.wkey, wrong,
                                            digest(wrong))
        self.assertEqual(receipt["status"], "rejected")
        self.assertEqual(receipt["reason"], WITHDRAWAL_TARGET_DIGEST)
        self.assertEqual(receipt["digest"], digest(wrong))
        self.assertEqual(json_read(self.store_dir, publication_key(self.card)),
                         publication_bytes)
        self.assertEqual(len(committed_names(self.store_dir)), 1)

    def test_same_key_changed_record_is_refused_without_overwrite(self):
        store = self.make_store()
        winner = store.execute(self.wkey, self.request, digest(self.request))
        changed = withdrawal_request(published_digest="b" * 64)
        self.assertEqual(withdrawal_key(changed["policy_id"],
                                        changed["policy_version"]), self.wkey)
        before = json_read(self.store_dir, self.wkey)
        refused = store.execute(self.wkey, changed, digest(changed))
        self.assertEqual(refused["status"], "rejected")
        self.assertEqual(refused["reason"], WITHDRAWAL_TARGET_DIGEST)
        with self.assertRaises(ValueError) as raised:
            FilePublisher(self.store_dir).execute(
                self.wkey, changed, digest(changed))
        self.assertIs(type(raised.exception), ValueError)
        self.assertEqual(json_read(self.store_dir, self.wkey), before)
        self.assertEqual(store.lookup(self.wkey), winner)

    def test_lookup_delegates_to_the_committed_record(self):
        store = self.make_store()
        receipt = store.execute(self.wkey, self.request, digest(self.request))
        self.assertEqual(store.lookup(self.wkey), receipt)
        self.assertIsNone(store.lookup(WITHDRAWAL_KEY_PREFIX + "0" * 64))


class LoaderWithdrawalTests(WithdrawalTestCase):
    """Fail-closed loader matrix with withdrawal (D72): six bounded
    distinguishable classes, absent precedence, audit read, no override."""

    def setUp(self):
        super().setUp()
        self.card = card_with()
        self.publish(self.card)
        self.pkey = publication_key(self.card)
        self.wkey = withdrawal_key("expense-submit", "demo-1")

    def withdraw(self):
        request = withdrawal_request(published_digest=sop_digest(self.card))
        receipt = SopWithdrawalStore(self.store_dir).execute(
            self.wkey, request, digest(request))
        self.assertEqual(receipt["status"], "accepted")
        return request

    def rewrite(self, key, raw):
        with open(os.path.join(self.store_dir, artifact_name(key)), "w") as handle:
            json.dump(raw, handle)

    def test_round_trip_before_withdrawal_still_loads(self):
        self.assertEqual(load_published_card(self.store_dir,
                                             "expense-submit", "demo-1"),
                         self.card)
        self.assertIsNone(withdrawal_record(self.store_dir,
                                            "expense-submit", "demo-1"))

    def test_after_withdrawal_the_loader_raises_the_exact_withdrawn_error(self):
        self.withdraw()
        with self.assertRaises(ValueError) as raised:
            load_published_card(self.store_dir, "expense-submit", "demo-1")
        self.assertIs(type(raised.exception), ValueError)
        self.assertEqual(str(raised.exception), WITHDRAWN_MESSAGE)

    def test_pinned_card_raises_withdrawn_before_any_pin_judgment(self):
        self.withdraw()
        for pin in (sop_digest(self.card), "0" * 64):
            with self.assertRaises(ValueError) as raised:
                pinned_card(self.store_dir, "expense-submit", "demo-1", pin)
            self.assertEqual(str(raised.exception), WITHDRAWN_MESSAGE)

    def test_corrupt_withdrawal_record_maps_to_the_invalid_record_error(self):
        self.withdraw()
        with open(os.path.join(self.store_dir, artifact_name(self.wkey)),
                  "wb") as handle:
            handle.write(b"not json")
        with self.assertRaises(ValueError) as raised:
            load_published_card(self.store_dir, "expense-submit", "demo-1")
        self.assertEqual(str(raised.exception),
                         WITHDRAWAL_RECORD_INVALID_MESSAGE)

    def test_tampered_stale_digest_record_maps_to_the_invalid_record_error(self):
        self.withdraw()
        raw = json_read(self.store_dir, self.wkey)
        raw["document"]["policy_id"] = "doctored.after.commit"
        self.rewrite(self.wkey, raw)
        with self.assertRaises(ValueError) as raised:
            withdrawal_record(self.store_dir, "expense-submit", "demo-1")
        self.assertEqual(str(raised.exception),
                         WITHDRAWAL_RECORD_INVALID_MESSAGE)
        self.assertNotEqual(str(raised.exception), WITHDRAWN_MESSAGE)

    def test_foreign_record_under_the_withdrawal_key_fails_closed(self):
        # Raw adapter use can commit any record under any key; this one
        # carries another version's identity and must not withdraw ours.
        foreign = withdrawal_request(policy_id="other-policy",
                                     policy_version="v9",
                                     published_digest="c" * 64)
        FilePublisher(self.store_dir).execute(self.wkey, foreign,
                                              digest(foreign))
        with self.assertRaises(ValueError) as raised:
            load_published_card(self.store_dir, "expense-submit", "demo-1")
        self.assertEqual(str(raised.exception),
                         WITHDRAWAL_RECORD_INVALID_MESSAGE)

    def test_digest_mismatched_record_is_invalid_never_silently_served(self):
        # The governed path refuses to commit a record binding a different
        # published_digest (D74 receipt); raw adapter use bypasses it, and
        # such a standing record fails closed instead of withdrawing.
        wrong = withdrawal_request(published_digest="d" * 64)
        receipt = SopWithdrawalStore(self.store_dir).execute(
            self.wkey, wrong, digest(wrong))
        self.assertEqual(receipt["status"], "rejected")
        self.assertEqual(receipt["reason"], WITHDRAWAL_TARGET_DIGEST)
        FilePublisher(self.store_dir).execute(self.wkey, wrong,
                                              digest(wrong))
        with self.assertRaises(ValueError) as raised:
            load_published_card(self.store_dir, "expense-submit", "demo-1")
        self.assertEqual(str(raised.exception),
                         WITHDRAWAL_RECORD_INVALID_MESSAGE)

    def test_absent_artifact_reads_absent_even_with_a_record_present(self):
        self.withdraw()
        os.unlink(os.path.join(self.store_dir, artifact_name(self.pkey)))
        with self.assertRaises(ValueError) as raised:
            load_published_card(self.store_dir, "expense-submit", "demo-1")
        self.assertIn("no published card", str(raised.exception))

    def test_missing_directory_is_never_created_by_withdrawal_reads(self):
        missing = os.path.join(self.root, "never-created")
        self.assertIsNone(withdrawal_record(missing, "expense-submit",
                                            "demo-1"))
        with self.assertRaises(ValueError) as raised:
            load_published_card(missing, "expense-submit", "demo-1")
        self.assertIn("no published card", str(raised.exception))
        self.assertFalse(os.path.exists(missing))

    def test_withdrawal_record_audit_read_returns_the_stored_record(self):
        request = self.withdraw()
        record = withdrawal_record(self.store_dir, "expense-submit",
                                   "demo-1")
        self.assertEqual(record, request)

    def test_loaders_accept_no_override_keyword(self):
        self.withdraw()
        for call in (
                lambda: load_published_card(self.store_dir, "expense-submit",
                                            "demo-1", allow_withdrawn=True),
                lambda: pinned_card(self.store_dir, "expense-submit",
                                    "demo-1", sop_digest(self.card),
                                    allow_withdrawn=True),
                lambda: withdrawal_record(self.store_dir, "expense-submit",
                                          "demo-1", allow_withdrawn=True)):
            with self.assertRaises(TypeError):
                call()
            with self.assertRaises(ValueError):
                load_published_card(self.store_dir, "expense-submit",
                                    "demo-1")

    def test_published_card_matches_stays_pure_and_refuses_records(self):
        request = self.withdraw()
        self.assertFalse(published_card_matches(request, None))
        self.assertTrue(published_card_matches(self.card,
                                               type("P", (), {
                                                   "id": self.card["policy"]["id"],
                                                   "version": self.card["policy"]["version"],
                                                   "goal": self.card["policy"]["goal"],
                                               })()))
        with self.assertRaises(ValueError):
            load_published_card(self.store_dir, "expense-submit", "demo-1")


class ResponseLossWithdrawalStore:
    """The real withdrawal store commits, then the response is lost."""

    def __init__(self, store):
        self._store = store
        self.contract = store.contract  # surfaced, never bypassed

    def execute(self, key, document, content_digest):
        self._store.execute(key, document, content_digest)
        raise TimeoutError("response lost after the withdrawal commit")

    def lookup(self, key):
        return self._store.lookup(key)


class GovernedWithdrawalFlowTests(WithdrawalTestCase):
    """The governed sop.withdraw story on a real Runtime, SQLite and
    directory, in the same family/database as a standing publication
    (D70): W02/W03 shape discrimination, D66 order, the D74 refusal
    channel and the F18 completion-gate regression."""

    def setUp(self):
        super().setUp()
        self.policy = SopPublicationPolicy()
        self.grants = withdrawal_grants()
        self.runtime = Runtime(os.path.join(self.root, "runtime.sqlite"),
                               self.policy, self.grants)
        self.approver_key = secrets.token_bytes(32)  # never printed
        self.gateway = SignedEvidenceGateway(
            self.runtime, {"sop-owner": self.approver_key},
            clock=lambda: FLOW_NOW)
        self.card = card_with()
        self.publish(self.card)
        self.target_digest = sop_digest(self.card)
        self.request = withdrawal_request(published_digest=self.target_digest)
        self.wkey = withdrawal_key("expense-submit", "demo-1")

    def _send(self, work_id, kind, payload=None, actor="agent",
              command_id=None, version=None):
        if version is None and kind not in ("create_work", "record_evidence"):
            version = self.runtime.get_work(work_id)["state_version"]
        return self.runtime.command(actor, command_id or uuid.uuid4().hex,
                                    work_id, kind, payload, version)

    def _propose(self, work_id, capability="sop.withdraw", command_id=None,
                 version=None):
        work = self.runtime.get_work(work_id)
        if version is None:
            version = work["state_version"]
        return self._send(work_id, "propose_action", {
            "capability": capability,
            "document_digest": work["document_digest"],
            "contract_revision": work["contract"]["revision"],
            "plan_revision": work["plan_revision"]}, command_id=command_id,
            version=version)

    def _signed_withdrawal(self, work_id, digest_value=None,
                           policy_version=None, source="sop-owner",
                           command_id=None, event_id=None):
        request = self.runtime.get_work(work_id)["document"]
        return sign_evidence(self.approver_key, {
            "source": source, "command_id": command_id or uuid.uuid4().hex,
            "work_id": work_id, "event_id": event_id or uuid.uuid4().hex,
            "kind": "card_withdrawal",
            "data": {"digest": digest_value or request["published_digest"],
                     "policy_version": policy_version
                     or request["policy_version"]},
            "issued_at": FLOW_NOW})

    def _signed_card_approval(self, work_id, digest_value=None,
                              policy_version=None, command_id=None,
                              event_id=None):
        card = self.runtime.get_work(work_id)["document"]
        return sign_evidence(self.approver_key, {
            "source": "sop-owner", "command_id": command_id or uuid.uuid4().hex,
            "work_id": work_id, "event_id": event_id or uuid.uuid4().hex,
            "kind": "card_approval",
            "data": {"digest": digest_value
                     or self.runtime.get_work(work_id)["document_digest"],
                     "policy_version": policy_version
                     or card["policy"]["version"]},
            "issued_at": FLOW_NOW})

    def _establish(self, work_id, document):
        self._send(work_id, "create_work", {"document": document})
        self._send(work_id, "bind_contract", {
            "policy_id": self.policy.id, "policy_version": self.policy.version,
            "goal": self.policy.goal})

    def _approve_withdrawal(self, work_id, **overrides):
        receipt = self.gateway.record(
            self._signed_withdrawal(work_id, **overrides))
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.runtime.verify_pending(work_id)

    def _approve_card(self, work_id, **overrides):
        receipt = self.gateway.record(
            self._signed_card_approval(work_id, **overrides))
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.runtime.verify_pending(work_id)

    def _w02_blocker(self, receipt):
        return any(b["id"].startswith("W02:") for b in receipt["blockers"])

    def test_malformed_request_is_refused_unpersisted_at_admission(self):
        extra = dict(self.request, reason="free text is refused")
        wrong_kind = dict(self.request, discriminator="sop.publish")
        non_str = dict(self.request, published_digest=7)
        for bad in (extra, wrong_kind, non_str):
            with self.assertRaises(ValueError) as raised:
                self._send("wd-x", "create_work", {"document": bad})
            self.assertIs(type(raised.exception), ValueError)
        self.assertEqual(table_counts(os.path.join(self.root,
                                                   "runtime.sqlite"))["works"],
                         0)

    def test_request_document_digest_is_its_canonical_digest(self):
        self._establish("wd-1", self.request)
        work = self.runtime.get_work("wd-1")
        self.assertEqual(work["document_digest"], digest(self.request))
        self.assertEqual(work["document"], self.request)

    def test_revise_document_refuses_the_id_less_request(self):
        self._establish("wd-1", self.request)
        with self.assertRaises(KeyError):
            self._send("wd-1", "revise_document",
                       {"document": dict(self.request,
                                         published_digest="0" * 64)})

    def test_proposal_before_withdrawal_approval_is_blocked_pending_w02(self):
        self._establish("wd-1", self.request)
        blocked = self._propose("wd-1")
        self.assertEqual(blocked["decision"], "rejected")
        self.assertEqual(blocked["code"], "REQUIREMENT_UNSATISFIED")
        self.assertTrue(self._w02_blocker(blocked))
        self.assertEqual(committed_names(self.store_dir),
                         [artifact_name(publication_key(self.card))])

    def test_card_approval_never_satisfies_w02(self):
        self._establish("wd-1", self.request)
        receipt = self.gateway.record(self._signed_card_approval(
            "wd-1", digest_value=self.target_digest, policy_version="demo-1"))
        self.assertEqual(receipt["decision"], "accepted")
        self.runtime.verify_pending("wd-1")
        statuses = {e["kind"]: e["status"] for e in
                    evidence_bodies(os.path.join(self.root,
                                                 "runtime.sqlite"))}
        self.assertEqual(statuses["card_approval"], "invalid")
        blocked = self._propose("wd-1")
        self.assertEqual(blocked["code"], "REQUIREMENT_UNSATISFIED")
        self.assertTrue(self._w02_blocker(blocked))

    def test_tampered_withdrawal_approval_is_refused_with_zero_intake_writes(self):
        self._establish("wd-1", self.request)
        tampered = self._signed_withdrawal("wd-1")
        tampered["data"]["digest"] = "0" * 64  # forged after signing
        before = table_counts(os.path.join(self.root, "runtime.sqlite"))
        rejection = self.gateway.record(tampered)
        self.assertEqual(rejection,
                         {"decision": "rejected",
                          "code": "EVIDENCE_AUTHENTICATION_FAILED"})
        self.assertEqual(table_counts(os.path.join(self.root,
                                                   "runtime.sqlite")), before)

    def test_wrong_source_withdrawal_intake_is_authority_denied(self):
        self._establish("wd-1", self.request)
        other_key = secrets.token_bytes(32)
        gateway = SignedEvidenceGateway(
            self.runtime, {"sop-owner": self.approver_key, "other": other_key},
            clock=lambda: FLOW_NOW)
        envelope = sign_evidence(other_key, {
            "source": "other", "command_id": uuid.uuid4().hex,
            "work_id": "wd-1", "event_id": uuid.uuid4().hex,
            "kind": "card_withdrawal",
            "data": {"digest": self.request["published_digest"],
                     "policy_version": self.request["policy_version"]},
            "issued_at": FLOW_NOW})
        receipt = gateway.record(envelope)
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "AUTHORITY_DENIED")
        self.assertEqual(table_counts(os.path.join(self.root,
                                                   "runtime.sqlite"))["evidence"],
                         0)

    def test_wrong_digest_withdrawal_verifies_but_keeps_w02_pending(self):
        self._establish("wd-1", self.request)
        self._approve_withdrawal("wd-1", digest_value="e" * 64)
        statuses = {e["kind"]: e["status"] for e in
                    evidence_bodies(os.path.join(self.root,
                                                 "runtime.sqlite"))}
        self.assertEqual(statuses["card_withdrawal"], "verified")
        blocked = self._propose("wd-1")
        self.assertEqual(blocked["code"], "REQUIREMENT_UNSATISFIED")
        self.assertTrue(self._w02_blocker(blocked))

    def test_wrong_version_withdrawal_turns_invalid_at_verification(self):
        self._establish("wd-1", self.request)
        self._approve_withdrawal("wd-1", policy_version="v9")
        statuses = {e["kind"]: e["status"] for e in
                    evidence_bodies(os.path.join(self.root,
                                                 "runtime.sqlite"))}
        self.assertEqual(statuses["card_withdrawal"], "invalid")
        blocked = self._propose("wd-1")
        self.assertEqual(blocked["code"], "REQUIREMENT_UNSATISFIED")

    def test_valid_withdrawal_verifies_and_business_key_is_the_withdrawal_key(self):
        self._establish("wd-1", self.request)
        self._approve_withdrawal("wd-1")
        intent = self._propose("wd-1", command_id="withdraw-once")
        self.assertEqual(intent["decision"], "accepted")
        operation = self.runtime.get_operation(intent["operation_id"])
        self.assertEqual(operation["business_key"], self.wkey)

    def test_capability_and_document_shape_pair_in_both_directions(self):
        self._establish("wd-1", self.request)
        mismatched = self._propose("wd-1", capability="sop.publish")
        self.assertEqual(mismatched["decision"], "rejected")
        self.assertTrue(any(b.get("code") == "CAPABILITY_UNSUPPORTED"
                            for b in mismatched["blockers"]))
        second_card = card_with(policy_version="v2")
        self._establish("pub-1", second_card)
        backwards = self._propose("pub-1", capability="sop.withdraw")
        self.assertEqual(backwards["decision"], "rejected")
        self.assertTrue(any(b.get("code") == "CAPABILITY_UNSUPPORTED"
                            for b in backwards["blockers"]))

    def test_wrong_adapter_holds_bounded_then_correct_redispatch_succeeds(self):
        self._establish("wd-1", self.request)
        self._approve_withdrawal("wd-1")
        intent = self._propose("wd-1")
        held = self.runtime.dispatch(intent["operation_id"],
                                     SopPublicationStore(self.store_dir))
        self.assertEqual(held["dispatch_state"], "held")
        self.assertEqual(held["reason"], "ADAPTER_ACTION_UNSUPPORTED")
        operation = self.runtime.get_operation(intent["operation_id"])
        self.assertEqual(operation["attempts"], [])
        self.assertEqual(committed_names(self.store_dir),
                         [artifact_name(publication_key(self.card))])
        resolved = self.runtime.dispatch(intent["operation_id"],
                                         SopWithdrawalStore(self.store_dir))
        self.assertEqual(resolved["status"], "confirmed_succeeded")
        self.assertEqual(len(committed_names(self.store_dir)), 2)

    def test_full_story_with_response_loss_and_one_attempt_reconcile(self):
        self._establish("wd-1", self.request)
        self._approve_withdrawal("wd-1")
        intent = self._propose("wd-1")
        unknown = self.runtime.dispatch(
            intent["operation_id"],
            ResponseLossWithdrawalStore(SopWithdrawalStore(self.store_dir)))
        self.assertEqual(unknown["status"], "outcome_unknown")
        self.assertEqual(len(committed_names(self.store_dir)), 2)
        self.assertEqual(stage_names(self.store_dir), [])
        raw = json_read(self.store_dir, self.wkey)
        self.assertEqual(raw["document"], self.request)
        restarted = Runtime(os.path.join(self.root, "runtime.sqlite"),
                            self.policy, self.grants)
        recovered = restarted.reconcile(
            intent["operation_id"], SopWithdrawalStore(self.store_dir))
        self.assertEqual(recovered["status"], "confirmed_succeeded")
        self.assertEqual(len(restarted.get_operation(intent["operation_id"])
                            ["attempts"]), 1)
        proofs = [e for e in evidence_bodies(os.path.join(
            self.root, "runtime.sqlite")) if e["kind"] == "accepted"]
        self.assertEqual(len(proofs), 1)
        proof = proofs[0]
        self.assertNotIn("sop-store", self.grants)  # no principal can sign it
        self.assertEqual(proof["source"], "sop-store")
        self.assertEqual(proof["event_id"], intent["operation_id"])
        self.assertEqual(proof["status"], "verified")
        self.assertEqual(proof["data"]["digest"], digest(self.request))
        completion = self._send("wd-1", "request_completion",
                                command_id="complete")
        self.assertEqual(completion["decision"], "accepted")
        work = self.runtime.get_work("wd-1")
        self.assertEqual((work["status"], work["outcome"]),
                         ("closed", "succeeded"))
        publication_bytes = json_read(self.store_dir,
                                      publication_key(self.card))
        self.assertEqual(publication_bytes["document"], self.card)
        with self.assertRaises(ValueError) as raised:
            load_published_card(self.store_dir, "expense-submit", "demo-1")
        self.assertEqual(str(raised.exception), WITHDRAWN_MESSAGE)
        self.assertEqual(withdrawal_record(self.store_dir, "expense-submit",
                                           "demo-1"), self.request)

    def _ghost_request(self):
        return withdrawal_request(policy_id="never-published",
                                  policy_version="v1",
                                  published_digest="a" * 64)

    def test_absent_target_confirms_failed_and_the_work_stays_cancellable(self):
        ghost = self._ghost_request()
        self._establish("wd-1", ghost)
        self._approve_withdrawal("wd-1")
        intent = self._propose("wd-1")
        self.assertEqual(intent["decision"], "accepted")  # W02 is the only gate
        resolved = self.runtime.dispatch(intent["operation_id"],
                                         SopWithdrawalStore(self.store_dir))
        self.assertEqual(resolved["status"], "confirmed_failed")
        self.assertTrue(resolved["external_id"].startswith(
            "SOP-WITHDRAWAL-REFUSED-"))
        self.assertEqual(self.runtime.get_work("wd-1")["status"],
                         "needs_attention")
        completion = self._send("wd-1", "request_completion")
        self.assertEqual(completion["decision"], "rejected")
        self.assertEqual(completion["code"], "REQUIREMENT_UNSATISFIED")
        self._send("wd-1", "request_cancel", {"reason": "target missing"})
        cancelled = self._send("wd-1", "finalize_cancel",
                               {"acknowledged_operations": []})
        self.assertEqual(cancelled["decision"], "accepted")
        work = self.runtime.get_work("wd-1")
        self.assertEqual((work["status"], work["outcome"]),
                         ("closed", "cancelled"))
        self.assertEqual(len(committed_names(self.store_dir)), 1)

    def test_digest_mismatch_target_also_confirms_failed(self):
        wrong = withdrawal_request(published_digest="f" * 64)
        self._establish("wd-1", wrong)
        self._approve_withdrawal("wd-1")
        intent = self._propose("wd-1")
        resolved = self.runtime.dispatch(intent["operation_id"],
                                         SopWithdrawalStore(self.store_dir))
        self.assertEqual(resolved["status"], "confirmed_failed")
        self.assertEqual(len(committed_names(self.store_dir)), 1)
        raw = json_read(self.store_dir, publication_key(self.card))
        self.assertEqual(raw["document"], self.card)  # publication untouched

    def test_second_withdrawal_conflicts_only_after_its_own_approval(self):
        self.test_full_story_with_response_loss_and_one_attempt_reconcile()
        self._establish("wd-2", self.request)
        blocked = self._propose("wd-2")
        self.assertEqual(blocked["code"], "REQUIREMENT_UNSATISFIED")  # D75
        self._approve_withdrawal("wd-2")
        conflict = self._propose("wd-2")
        self.assertEqual(conflict["decision"], "rejected")
        self.assertEqual(conflict["code"], "OPERATION_CONTENT_CONFLICT")
        self.assertEqual(len(committed_names(self.store_dir)), 2)

    def test_republication_of_a_withdrawn_version_conflicts_census_unchanged(self):
        # The version is first published through the governed flow in THIS
        # database (the store replays the standing artifact, zero writes),
        # then withdrawn; re-publication is refused by the proposal's own
        # target checks — the D66 conflict — with the census unchanged.
        self._establish("pub-0", self.card)
        self._approve_card("pub-0")
        published = self._propose("pub-0", capability="sop.publish")
        self.runtime.dispatch(published["operation_id"],
                              SopPublicationStore(self.store_dir))
        self.assertEqual(len(committed_names(self.store_dir)), 1)
        self._establish("wd-1", self.request)
        self._approve_withdrawal("wd-1")
        intent = self._propose("wd-1")
        self.runtime.dispatch(intent["operation_id"],
                              SopWithdrawalStore(self.store_dir))
        self.assertEqual(len(committed_names(self.store_dir)), 2)
        self._establish("pub-9", self.card)
        blocked = self._propose("pub-9", capability="sop.publish")
        self.assertEqual(blocked["code"], "REQUIREMENT_UNSATISFIED")
        self._approve_card("pub-9")
        conflict = self._propose("pub-9", capability="sop.publish")
        self.assertEqual(conflict["decision"], "rejected")
        self.assertEqual(conflict["code"], "OPERATION_CONTENT_CONFLICT")
        self.assertEqual(len(committed_names(self.store_dir)), 2)  # no un-withdrawal

    def test_publication_work_completes_unchanged_in_the_same_family(self):
        second = card_with(policy_version="v2")
        self._establish("pub-1", second)
        self._approve_card("pub-1")
        intent = self._propose("pub-1", capability="sop.publish")
        self.assertEqual(intent["decision"], "accepted")
        operation = self.runtime.get_operation(intent["operation_id"])
        self.assertEqual(operation["business_key"], publication_key(second))
        self.runtime.dispatch(intent["operation_id"],
                              SopPublicationStore(self.store_dir))
        completion = self._send("pub-1", "request_completion")
        self.assertEqual(completion["decision"], "accepted")
        work = self.runtime.get_work("pub-1")
        self.assertEqual((work["status"], work["outcome"]),
                         ("closed", "succeeded"))


if __name__ == "__main__":
    unittest.main()
