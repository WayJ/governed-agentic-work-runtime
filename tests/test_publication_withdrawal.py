"""Published-card withdrawal tests (S13 core wave, D67-D79).

Real runtimes, real SQLite stores and real publication directories throughout
— no mocks. Approver signing keys are fresh random bytes per run and are
never printed or persisted. See docs/sop-authoring.md (withdrawal section)
and the S13 design spec for the ratified boundaries.
"""

import json
import os
import unittest

from work_runtime.authoring import sop_digest
from work_runtime.file_adapter import FilePublisher
from work_runtime.policy import digest
from work_runtime.publication import (
    WITHDRAWAL_DISCRIMINATOR,
    WITHDRAWAL_KEY_PREFIX,
    WITHDRAWAL_RECORD_INVALID_MESSAGE,
    WITHDRAWAL_REQUEST_KEYS,
    WITHDRAWAL_TARGET_ABSENT,
    WITHDRAWAL_TARGET_DIGEST,
    WITHDRAWN_MESSAGE,
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
    json_read,
    stage_names,
)


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


if __name__ == "__main__":
    unittest.main()
