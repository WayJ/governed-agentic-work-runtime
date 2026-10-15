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
import tempfile
import unittest
from pathlib import Path

from work_runtime.adoption_demo import packaged_card
from work_runtime.authoring import lint_sop, sop_digest
from work_runtime.file_adapter import FilePublisher
from work_runtime.policy import digest
from work_runtime.publication import (
    SopPublicationStore,
    load_published_card,
    pinned_card,
    publication_key,
    published_card_matches,
)

_HEX_JSON = re.compile(r"[0-9a-f]{64}\.json")


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
