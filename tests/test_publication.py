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
from work_runtime.policy import digest
from work_runtime.publication import SopPublicationStore, publication_key

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
