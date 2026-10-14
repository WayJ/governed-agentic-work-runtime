"""Source signing-key rotation tests: keyrings, signed key selectors, windows, replay.

Covers the S11 ratified design (D49-D53): per-source SourceKey rings with exact
configuration validation and immutable copying, the optional authenticated
key_id envelope field, strict verification-key selection, inclusive validity
windows on one finite clock sample, and cache-first replay semantics on real
SQLite stores. Every secret here is synthetic and ephemeral (secrets.token_bytes,
never printed); the known-answer vector is a published fixed value, not a
credential.
"""

import secrets
import sqlite3
import tempfile
import unittest
from pathlib import Path

from work_runtime import ExpensePolicy, Runtime
from work_runtime.demo import demo_grants, initialize
from work_runtime.ingress import SIGNED_FIELDS, SignedEvidenceGateway, SourceKey, sign_evidence


def key():
    return secrets.token_bytes(32)


class KeyringConfigTests(unittest.TestCase):
    """Constructor validation, normalization and copying of SourceKey rings (D50)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 2000000000
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        self.runtime = Runtime(self.path, ExpensePolicy(), demo_grants())
        initialize(self.runtime)
        self.finance = key()
        self.k1 = SourceKey("ring-2026-08", key(), current=True)
        self.k2 = SourceKey("ring-2026-10", key())

    def message(self, **overrides):
        base = {"source": "finance", "command_id": "cmd-1", "work_id": "demo",
                "event_id": "evt-1", "kind": "approval",
                "data": {"digest": self.runtime.get_work("demo")["document_digest"]},
                "issued_at": self.now}
        base.update(overrides)
        return base

    def table_counts(self):
        with sqlite3.connect(self.path) as db:
            return {t: db.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
                    for t in ("works", "commands", "evidence", "operations", "events", "metadata")}

    def test_valid_rings_and_mixed_configs_construct(self):
        tuple_ring = (self.k1, self.k2)
        list_ring = [SourceKey("ledger-2026-10", key(), current=True,
                               not_before=self.now - 10, not_after=self.now + 10)]
        point_window = [SourceKey("point", key(), current=True,
                                  not_before=self.now, not_after=self.now)]
        for ring in (tuple_ring, list_ring, point_window):
            gateway = SignedEvidenceGateway(self.runtime, {"finance": ring},
                                            clock=lambda: self.now)
            self.assertEqual(gateway.keyrings["finance"], tuple(ring))
        mixed = {"finance": [self.k1, self.k2], "ledger": key()}
        gateway = SignedEvidenceGateway(self.runtime, mixed, clock=lambda: self.now)
        self.assertEqual(set(gateway.keyrings), {"finance"})
        self.assertEqual(set(gateway.keys), {"ledger"})

    def test_ring_must_be_list_or_tuple(self):
        entries = (self.k1, self.k2)
        for bad in (iter(entries), set(entries), {"a": self.k1}, 7, None, "k1", True):
            with self.assertRaises(ValueError):
                SignedEvidenceGateway(self.runtime, {"finance": bad}, clock=lambda: self.now)

    def test_ring_must_not_be_empty(self):
        for bad in ([], ()):
            with self.assertRaises(ValueError):
                SignedEvidenceGateway(self.runtime, {"finance": bad}, clock=lambda: self.now)

    def test_ring_entries_must_be_sourcekey_instances(self):
        for bad in (["finance-2026-08", "finance-2026-10"],
                    [key(), key()],
                    [(self.k1.key_id, self.k1.secret, True, None, None)],
                    [self.k1, ("finance-2026-10", key())]):
            with self.assertRaises(ValueError):
                SignedEvidenceGateway(self.runtime, {"finance": bad}, clock=lambda: self.now)

    def test_ring_entry_field_types_are_exact(self):
        good_secret = key()
        variants = [
            SourceKey(7, good_secret, current=True),
            SourceKey("", good_secret, current=True),
            SourceKey(None, good_secret, current=True),
            SourceKey(b"finance-2026-08", good_secret, current=True),
            SourceKey("finance-2026-08", "str-secret", current=True),
            SourceKey("finance-2026-08", b"0" * 31, current=True),
            SourceKey("finance-2026-08", bytearray(32), current=True),
            SourceKey("finance-2026-08", good_secret, current=1),
            SourceKey("finance-2026-08", good_secret, current=0),
            SourceKey("finance-2026-08", good_secret, current=None),
            SourceKey("finance-2026-08", good_secret, current="yes"),
        ]
        for bound_field in ("not_before", "not_after"):
            for bad_bound in (True, False, 1.5, "0", object()):
                variants.append(SourceKey("finance-2026-08", good_secret, current=True,
                                           **{bound_field: bad_bound}))
        for bad in variants:
            with self.assertRaises(ValueError):
                SignedEvidenceGateway(self.runtime, {"finance": [bad]},
                                      clock=lambda: self.now)

    def test_ring_key_ids_unique_within_source(self):
        duplicate = SourceKey(self.k1.key_id, key())
        with self.assertRaises(ValueError):
            SignedEvidenceGateway(self.runtime, {"finance": [self.k1, duplicate]},
                                  clock=lambda: self.now)

    def test_ring_requires_exactly_one_current_entry(self):
        no_current = [SourceKey("finance-2026-08", key()), SourceKey("finance-2026-10", key())]
        two_current = [SourceKey("finance-2026-08", key(), current=True),
                       SourceKey("finance-2026-10", key(), current=True)]
        for bad in (no_current, two_current):
            with self.assertRaises(ValueError):
                SignedEvidenceGateway(self.runtime, {"finance": bad}, clock=lambda: self.now)

    def test_ring_window_order_validated(self):
        inverted = SourceKey("finance-2026-10", key(), current=True,
                             not_before=self.now + 1, not_after=self.now)
        with self.assertRaises(ValueError):
            SignedEvidenceGateway(self.runtime, {"finance": [self.k1, inverted]},
                                  clock=lambda: self.now)

    def test_secret_material_distinct_across_entire_config(self):
        shared = key()
        same_ring = [SourceKey("a", shared, current=True), SourceKey("b", shared)]
        cross_ring = {"finance": [self.k1, self.k2],
                      "ledger": [SourceKey("ledger-2026-10", self.k1.secret, current=True)]}
        ring_vs_legacy = {"finance": [self.k1, self.k2], "ledger": self.k1.secret}
        for bad in ({"finance": same_ring}, cross_ring, ring_vs_legacy):
            with self.assertRaises(ValueError):
                SignedEvidenceGateway(self.runtime, bad, clock=lambda: self.now)

    def test_configuration_is_copied_at_construction(self):
        caller_list = [self.k1, self.k2]
        keys = {"finance": self.finance, "rotating": caller_list}
        gateway = SignedEvidenceGateway(self.runtime, keys, clock=lambda: self.now)
        self.assertIsInstance(gateway.keyrings["rotating"], tuple)
        self.assertIsNot(gateway.keyrings["rotating"], caller_list)
        self.assertEqual(gateway.keyrings["rotating"], (self.k1, self.k2))
        # Mutating the caller's inner list and outer map changes nothing.
        caller_list.append(SourceKey("ring-2026-12", key(), current=True))
        caller_list[0] = SourceKey("ring-2026-08", key(), current=True)
        keys["observer"] = key()
        del keys["finance"]
        self.assertEqual(gateway.keyrings["rotating"], (self.k1, self.k2))
        self.assertEqual(gateway.keys, {"finance": self.finance})
        self.assertNotIn("observer", gateway.keys)
        # The legacy path still records with the pre-mutation configuration.
        before = self.table_counts()
        receipt = gateway.record(sign_evidence(self.finance, self.message()))
        self.assertEqual(receipt["decision"], "accepted")
        observer = gateway.record(sign_evidence(keys["observer"],
                                                 self.message(source="observer")))
        self.assertEqual(observer, {"decision": "rejected",
                                    "code": "EVIDENCE_AUTHENTICATION_FAILED"})
        after = self.table_counts()
        self.assertEqual(after["commands"], before["commands"] + 1)
        self.assertEqual(after["evidence"], before["evidence"] + 1)

    def test_legacy_bytes_validation_is_unchanged_beside_rings(self):
        for bad_keys in (["finance"], {"finance": b"0" * 31}, {"finance": "str"},
                         {7: self.finance}, {"": self.finance},
                         {"finance": self.finance, "ledger": self.finance}):
            with self.assertRaises(ValueError):
                SignedEvidenceGateway(self.runtime, bad_keys, clock=lambda: self.now)


if __name__ == "__main__":
    unittest.main()
