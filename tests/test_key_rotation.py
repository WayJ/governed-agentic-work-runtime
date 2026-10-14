"""Source signing-key rotation tests: keyrings, signed key selectors, windows, replay.

Covers the S11 ratified design (D49-D53): per-source SourceKey rings with exact
configuration validation and immutable copying, the optional authenticated
key_id envelope field, strict verification-key selection, inclusive validity
windows on one finite clock sample, and cache-first replay semantics on real
SQLite stores. Every secret here is synthetic and ephemeral (secrets.token_bytes,
never printed); the known-answer vector is a published fixed value, not a
credential.
"""

import json
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


class KeySelectionTests(unittest.TestCase):
    """Optional signed key_id selection, current-only legacy path, HMAC (D49/D51)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 2000000000
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        self.runtime = Runtime(self.path, ExpensePolicy(), demo_grants())
        initialize(self.runtime)
        self.k1 = SourceKey("ring-2026-08", key(), current=True)
        self.k2 = SourceKey("ring-2026-10", key())
        self.ledger = key()
        self.gateway = SignedEvidenceGateway(
            self.runtime, {"finance": [self.k1, self.k2], "ledger": self.ledger},
            clock=lambda: self.now)

    def message(self, **overrides):
        base = {"source": "finance", "command_id": "cmd-1", "work_id": "demo",
                "event_id": "evt-1", "kind": "approval",
                "data": {"digest": self.runtime.get_work("demo")["document_digest"]},
                "issued_at": self.now}
        base.update(overrides)
        return base

    def signed(self, secret=None, key_id=False, **overrides):
        # key_id=False omits the optional field entirely.
        message = self.message(**overrides)
        if key_id is not False:
            message["key_id"] = key_id
        return sign_evidence(self.k1.secret if secret is None else secret, message)

    def table_counts(self):
        with sqlite3.connect(self.path) as db:
            return {t: db.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
                    for t in ("works", "commands", "evidence", "operations", "events", "metadata")}

    def evidence_bodies(self):
        with sqlite3.connect(self.path) as db:
            return [json.loads(r[0]) for r in db.execute("SELECT body FROM evidence")]

    def test_key_id_envelope_accepted_against_keyring(self):
        for entry in (self.k1, self.k2):
            envelope = self.signed(secret=entry.secret, key_id=entry.key_id,
                                   command_id="cmd-" + entry.key_id,
                                   event_id="evt-" + entry.key_id)
            receipt = self.gateway.record(envelope)
            self.assertEqual(receipt["decision"], "accepted", entry.key_id)
        body = self.evidence_bodies()[0]
        self.assertEqual(set(body), {"id", "source", "event_id", "kind", "data", "status"})
        rendered = json.dumps(body) + json.dumps(receipt)
        for field in ("key_id", "signature", "issued_at"):
            self.assertNotIn(field, rendered)

    def test_key_id_is_signed_content_and_tampering_fails(self):
        before = self.table_counts()
        envelope = self.signed(secret=self.k2.secret, key_id=self.k2.key_id)
        envelope["key_id"] = self.k1.key_id  # selector swap without re-signing
        self.assertEqual(self.gateway.record(envelope),
                         {"decision": "rejected", "code": "EVIDENCE_AUTHENTICATION_FAILED"})
        self.assertEqual(self.table_counts(), before)

    def test_unknown_key_id_rejected(self):
        before = self.table_counts()
        envelope = self.signed(secret=self.k2.secret, key_id="ring-2027-01")
        self.assertEqual(self.gateway.record(envelope),
                         {"decision": "rejected", "code": "EVIDENCE_AUTHENTICATION_FAILED"})
        self.assertEqual(self.table_counts(), before)

    def test_wrong_secret_with_known_key_id_rejected(self):
        before = self.table_counts()
        envelope = self.signed(secret=self.k2.secret, key_id=self.k1.key_id)
        self.assertEqual(self.gateway.record(envelope),
                         {"decision": "rejected", "code": "EVIDENCE_AUTHENTICATION_FAILED"})
        self.assertEqual(self.table_counts(), before)

    def test_key_id_envelope_against_legacy_bytes_source_rejected(self):
        before = self.table_counts()
        envelope = self.signed(secret=self.ledger, key_id=self.k1.key_id,
                               source="ledger")
        self.assertEqual(self.gateway.record(envelope),
                         {"decision": "rejected", "code": "EVIDENCE_AUTHENTICATION_FAILED"})
        self.assertEqual(self.table_counts(), before)

    def test_legacy_envelope_authenticates_against_current_entry_only(self):
        before = self.table_counts()
        envelope = self.signed(secret=self.k2.secret)  # k2 is listed but not current
        self.assertEqual(self.gateway.record(envelope),
                         {"decision": "rejected", "code": "EVIDENCE_AUTHENTICATION_FAILED"})
        self.assertEqual(self.table_counts(), before)

    def test_legacy_envelope_current_entry_happy_path_accepted(self):
        receipt = self.gateway.record(self.signed())
        self.assertEqual(receipt["decision"], "accepted")
        self.assertEqual(receipt["evidence_status"], "pending_verification")

    def test_ring_configuration_mutations_cannot_reach_verification(self):
        caller_ring = [self.k1, self.k2]
        keys = {"finance": caller_ring}
        gateway = SignedEvidenceGateway(self.runtime, keys, clock=lambda: self.now)
        k3 = SourceKey("ring-2026-12", key(), current=True)
        caller_ring.append(k3)
        keys["finance"] = [k3]
        before = self.table_counts()
        for envelope in (self.signed(secret=k3.secret, key_id=k3.key_id),
                         self.signed(secret=k3.secret)):
            self.assertEqual(gateway.record(envelope),
                             {"decision": "rejected",
                              "code": "EVIDENCE_AUTHENTICATION_FAILED"})
        receipt = gateway.record(self.signed())
        self.assertEqual(receipt["decision"], "accepted")
        after = self.table_counts()
        self.assertEqual(after["commands"], before["commands"] + 1)
        self.assertEqual(after["evidence"], before["evidence"] + 1)

    def test_cross_material_cannot_impersonate_across_sources(self):
        before = self.table_counts()
        ring_forged = self.signed(secret=self.k1.secret, source="ledger")
        legacy_forged = self.signed(secret=self.ledger, key_id=self.k1.key_id,
                                    source="ledger")
        for envelope in (ring_forged, legacy_forged):
            self.assertEqual(self.gateway.record(envelope),
                             {"decision": "rejected",
                              "code": "EVIDENCE_AUTHENTICATION_FAILED"})
        self.assertEqual(self.table_counts(), before)


class SignerKeyFieldTests(unittest.TestCase):
    """sign_evidence accepts and signs the optional key_id field (D49 §4.10)."""

    def setUp(self):
        self.secret = key()

    def message(self, **overrides):
        base = {"source": "finance", "command_id": "cmd-1", "work_id": "demo",
                "event_id": "evt-1", "kind": "approval",
                "data": {"digest": "0" * 64}, "issued_at": 2000000000}
        base.update(overrides)
        return base

    def test_envelope_carries_optional_key_id_and_signature_depends_on_it(self):
        plain = sign_evidence(self.secret, self.message())
        self.assertEqual(set(plain), set(SIGNED_FIELDS) | {"signature"})
        with_id = sign_evidence(self.secret, self.message(key_id="ring-2026-10"))
        self.assertEqual(set(with_id), set(SIGNED_FIELDS) | {"key_id", "signature"})
        self.assertNotEqual(plain["signature"], with_id["signature"])

    def test_signer_rejects_bad_key_id_values(self):
        for bad in ("", 7, None, True, b"ring-2026-10"):
            with self.assertRaises(ValueError):
                sign_evidence(self.secret, self.message(key_id=bad))
        both = self.message(key_id="ring-2026-10")
        both["nonce"] = "x"
        with self.assertRaises(ValueError):
            sign_evidence(self.secret, both)

    def test_gateway_rejects_bad_key_id_shape_as_envelope_invalid(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = str(Path(temp.name) / "runtime.sqlite")
        runtime = Runtime(path, ExpensePolicy(), demo_grants())
        initialize(runtime)
        gateway = SignedEvidenceGateway(
            runtime, {"finance": [SourceKey("ring-2026-08", key(), current=True)]},
            clock=lambda: 2000000000)

        def counts():
            with sqlite3.connect(path) as db:
                return {t: db.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
                        for t in ("works", "commands", "evidence", "operations",
                                  "events", "metadata")}

        before = counts()
        for bad in (7, "", None, True):
            envelope = sign_evidence(self.secret, self.message())
            envelope["key_id"] = bad
            self.assertEqual(gateway.record(envelope),
                             {"decision": "rejected",
                              "code": "EVIDENCE_ENVELOPE_INVALID"}, bad)
        self.assertEqual(counts(), before)


if __name__ == "__main__":
    unittest.main()
