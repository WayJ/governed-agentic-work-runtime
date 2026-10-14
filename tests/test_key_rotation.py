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
        # Rotated direction (design §4.5 step 3, D51): with K2 current, a
        # legacy-format envelope signed with the retained, still-valid K1
        # fails HMAC against K2 — explicit, never silently accepted.
        rotated = SignedEvidenceGateway(
            self.runtime,
            {"finance": [SourceKey(self.k1.key_id, self.k1.secret),
                         SourceKey(self.k2.key_id, self.k2.secret, current=True)],
             "ledger": self.ledger},
            clock=lambda: self.now)
        old_key_envelope = self.signed(secret=self.k1.secret)
        self.assertEqual(rotated.record(old_key_envelope),
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


class WindowClockTests(unittest.TestCase):
    """Inclusive key windows on one finite shared clock sample (D51)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 2000000000
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        self.runtime = Runtime(self.path, ExpensePolicy(), demo_grants())
        initialize(self.runtime)
        self.legacy = key()

    def message(self, source="finance", **overrides):
        base = {"source": source, "command_id": "cmd-1", "work_id": "demo",
                "event_id": "evt-1", "kind": "approval",
                "data": {"digest": self.runtime.get_work("demo")["document_digest"]},
                "issued_at": self.now}
        base.update(overrides)
        return base

    def signed(self, secret, key_id=False, **overrides):
        message = self.message(**overrides)
        if key_id is not False:
            message["key_id"] = key_id
        return sign_evidence(secret, message)

    def gateway(self, ring, clock=None):
        return SignedEvidenceGateway(self.runtime, {"finance": ring, "ledger": self.legacy},
                                     clock=clock or (lambda: self.now))

    def table_counts(self):
        with sqlite3.connect(self.path) as db:
            return {t: db.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
                    for t in ("works", "commands", "evidence", "operations", "events", "metadata")}

    def test_window_bounds_inclusive_at_edges(self):
        secret = key()
        for edge in (self.now - 100, self.now + 100):
            windowed = SourceKey("ring-windowed", secret, current=True,
                                 not_before=self.now - 100, not_after=self.now + 100)
            gateway = self.gateway([windowed], clock=lambda: edge)
            for key_id in (False, "ring-windowed"):
                envelope = self.signed(secret, key_id=key_id,
                                       command_id="cmd-%s-%s" % (edge, key_id),
                                       event_id="evt-%s-%s" % (edge, key_id))
                self.assertEqual(gateway.record(envelope)["decision"], "accepted",
                                 (edge, key_id))

    def test_retired_key_rejected_after_not_after(self):
        retired = SourceKey("ring-old", key(), current=True,
                            not_after=self.now - 10)
        gateway = self.gateway([retired, SourceKey("ring-new", key())])
        before = self.table_counts()
        envelope = self.signed(retired.secret, key_id="ring-old")
        self.assertEqual(gateway.record(envelope),
                         {"decision": "rejected", "code": "EVIDENCE_KEY_RETIRED"})
        self.assertEqual(self.table_counts(), before)

    def test_not_yet_valid_key_rejected(self):
        future = SourceKey("ring-future", key(), current=True,
                           not_before=self.now + 10)
        gateway = self.gateway([future, SourceKey("ring-new", key())])
        before = self.table_counts()
        envelope = self.signed(future.secret, key_id="ring-future")
        self.assertEqual(gateway.record(envelope),
                         {"decision": "rejected", "code": "EVIDENCE_KEY_NOT_YET_VALID"})
        self.assertEqual(self.table_counts(), before)

    def test_window_precedes_freshness(self):
        retired = SourceKey("ring-old", key(), current=True, not_after=self.now - 10)
        future = SourceKey("ring-future", key(), current=True,
                           not_before=self.now + 10)
        for entry, code in ((retired, "EVIDENCE_KEY_RETIRED"),
                            (future, "EVIDENCE_KEY_NOT_YET_VALID")):
            gateway = self.gateway([entry, SourceKey("ring-new", key())])
            stale = self.signed(entry.secret, key_id=entry.key_id,
                                issued_at=self.now - 400)  # also stale
            self.assertEqual(gateway.record(stale),
                             {"decision": "rejected", "code": code}, entry.key_id)

    def test_window_uses_verification_time_not_issued_at(self):
        # A key holder cannot backdate around not_after, nor future-date its
        # way past not_before: the window sees the verification clock only.
        retired = SourceKey("ring-old", key(), current=True, not_after=self.now - 10)
        gateway = self.gateway([retired, SourceKey("ring-new", key())])
        backdated = self.signed(retired.secret, key_id="ring-old",
                                issued_at=self.now - 100)  # fresh, inside at issue time
        self.assertEqual(gateway.record(backdated),
                         {"decision": "rejected", "code": "EVIDENCE_KEY_RETIRED"})
        future = SourceKey("ring-future", key(), current=True,
                           not_before=self.now + 100)
        gateway = self.gateway([future, SourceKey("ring-new", key())])
        future_dated = self.signed(future.secret, key_id="ring-future",
                                   issued_at=self.now + 150)  # fresh, valid at issue time
        self.assertEqual(gateway.record(future_dated),
                         {"decision": "rejected", "code": "EVIDENCE_KEY_NOT_YET_VALID"})

    def test_window_codes_require_valid_signature(self):
        retired = SourceKey("ring-old", key(), current=True, not_after=self.now - 10)
        gateway = self.gateway([retired, SourceKey("ring-new", key())])
        before = self.table_counts()
        for key_id in (False, "ring-old"):
            envelope = self.signed(key(), key_id=key_id)
            self.assertEqual(gateway.record(envelope),
                             {"decision": "rejected",
                              "code": "EVIDENCE_AUTHENTICATION_FAILED"}, key_id)
        self.assertEqual(self.table_counts(), before)

    def test_current_entry_outside_window_on_legacy_path(self):
        retired = SourceKey("ring-old", key(), current=True, not_after=self.now - 10)
        future = SourceKey("ring-future", key(), current=True,
                           not_before=self.now + 10)
        for entry, code in ((retired, "EVIDENCE_KEY_RETIRED"),
                            (future, "EVIDENCE_KEY_NOT_YET_VALID")):
            gateway = self.gateway([entry, SourceKey("ring-new", key())])
            legacy_format = self.signed(entry.secret)
            self.assertEqual(gateway.record(legacy_format),
                             {"decision": "rejected", "code": code}, entry.key_id)

    def test_dropped_and_retained_expired_keys_have_distinct_codes(self):
        old = SourceKey("ring-old", key(), not_after=self.now - 10)
        new = SourceKey("ring-new", key(), current=True)
        envelope = self.signed(old.secret, key_id="ring-old")
        retained = self.gateway([old, new])
        self.assertEqual(retained.record(envelope),
                         {"decision": "rejected", "code": "EVIDENCE_KEY_RETIRED"})
        dropped = self.gateway([new])
        before = self.table_counts()
        self.assertEqual(dropped.record(envelope),
                         {"decision": "rejected",
                          "code": "EVIDENCE_AUTHENTICATION_FAILED"})
        self.assertEqual(self.table_counts(), before)

    def test_clock_invalid_samples_fail_closed(self):
        open_ring = [SourceKey("ring-open", key(), current=True)]
        bad_samples = (float("nan"), float("inf"), float("-inf"),
                       "2000000000", True, False, None, [self.now])
        for sample in bad_samples:
            for label, ring, envelope in (
                    ("ring", open_ring, self.signed(open_ring[0].secret)),
                    ("legacy", open_ring, self.signed(self.legacy, source="ledger"))):
                gateway = self.gateway(ring, clock=lambda s=sample: s)
                before = self.table_counts()
                self.assertEqual(gateway.record(envelope),
                                 {"decision": "rejected",
                                  "code": "EVIDENCE_CLOCK_INVALID"}, (sample, label))
                self.assertEqual(self.table_counts(), before, (sample, label))

    def test_clock_raising_ordinary_exception_fails_closed(self):
        def broken_clock():
            raise ValueError("operator clock failed")
        secret = key()
        gateway = self.gateway([SourceKey("ring-open", secret, current=True)],
                               clock=broken_clock)
        before = self.table_counts()
        self.assertEqual(gateway.record(self.signed(secret)),
                         {"decision": "rejected", "code": "EVIDENCE_CLOCK_INVALID"})
        self.assertEqual(self.table_counts(), before)

    def test_clock_base_exception_propagates(self):
        def interrupted_clock():
            raise KeyboardInterrupt
        secret = key()
        gateway = self.gateway([SourceKey("ring-open", secret, current=True)],
                               clock=interrupted_clock)
        with self.assertRaises(KeyboardInterrupt):
            gateway.record(self.signed(secret))

    def test_huge_int_clock_sample_is_finite_and_safe(self):
        open_ring = [SourceKey("ring-open", key(), current=True)]
        bounded = [SourceKey("ring-bounded", key(), current=True,
                             not_before=self.now - 100, not_after=self.now + 100)]
        cases = ((bounded, 10 ** 400, "EVIDENCE_KEY_RETIRED"),
                 (bounded, -(10 ** 400), "EVIDENCE_KEY_NOT_YET_VALID"),
                 (open_ring, 10 ** 400, "EVIDENCE_EXPIRED"),
                 (open_ring, -(10 ** 400), "EVIDENCE_EXPIRED"))
        for ring, sample, code in cases:
            gateway = self.gateway(ring, clock=lambda s=sample: s)
            self.assertEqual(gateway.record(self.signed(ring[0].secret)),
                             {"decision": "rejected", "code": code}, sample)

    def test_single_clock_sample_shared_by_window_and_freshness(self):
        sequence = []

        def sequencing_clock():
            sequence.append(len(sequence))
            return (self.now - 400, self.now)[sequence[-1]]

        # First sample passes the window but fails freshness; a second sample
        # (fresh) would accept. One shared sample must report EVIDENCE_EXPIRED.
        windowed = SourceKey("ring-windowed", key(), current=True,
                             not_before=self.now - 1000, not_after=self.now + 1000)
        gateway = self.gateway([windowed], clock=sequencing_clock)
        envelope = self.signed(windowed.secret, issued_at=self.now)
        self.assertEqual(gateway.record(envelope),
                         {"decision": "rejected", "code": "EVIDENCE_EXPIRED"})
        self.assertEqual(len(sequence), 1)
        # Mirror case: the first sample fails the window (before not_before)
        # while the second would pass window and freshness both.
        sequence.clear()
        future = SourceKey("ring-future", key(), current=True,
                           not_before=self.now - 300)
        gateway = self.gateway([future], clock=sequencing_clock)
        envelope = self.signed(future.secret, issued_at=self.now)
        self.assertEqual(gateway.record(envelope),
                         {"decision": "rejected", "code": "EVIDENCE_KEY_NOT_YET_VALID"})
        self.assertEqual(len(sequence), 1)

    def test_clock_not_sampled_until_hmac_succeeds(self):
        calls = []

        def counting_clock():
            calls.append(1)
            return self.now

        secret = key()
        gateway = self.gateway([SourceKey("ring-open", secret, current=True)],
                               clock=counting_clock)
        missing = self.signed(secret)
        del missing["kind"]
        unknown_source = self.signed(secret, source="ghost")
        bad_selector = self.signed(secret, key_id="ring-ghost")
        wrong_secret = self.signed(key())
        for bad in (missing, unknown_source, bad_selector, wrong_secret):
            self.assertEqual(gateway.record(bad)["decision"], "rejected")
            self.assertEqual(len(calls), 0, "clock sampled before successful HMAC")
        self.assertEqual(gateway.record(self.signed(secret))["decision"], "accepted")
        self.assertEqual(len(calls), 1)

    def test_legacy_freshness_semantics_unchanged(self):
        gateway = SignedEvidenceGateway(self.runtime, {"finance": self.legacy},
                                        clock=lambda: self.now)
        for issued_at in (self.now - 300, self.now + 300):
            receipt = gateway.record(self.signed(self.legacy,
                                                 command_id="cmd-%d" % issued_at,
                                                 event_id="evt-%d" % issued_at,
                                                 issued_at=issued_at))
            self.assertEqual(receipt["decision"], "accepted", issued_at)
        before = self.table_counts()
        for issued_at in (self.now - 301, self.now + 301):
            receipt = gateway.record(self.signed(self.legacy,
                                                 command_id="cmd-%d" % issued_at,
                                                 event_id="evt-%d" % issued_at,
                                                 issued_at=issued_at))
            self.assertEqual(receipt, {"decision": "rejected", "code": "EVIDENCE_EXPIRED"},
                             issued_at)
        self.assertEqual(self.table_counts(), before)


class ReplayHistoryTests(unittest.TestCase):
    """Authentication-before-cache, two resend branches, history preservation (D52)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 2000000000
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        grants = demo_grants()
        grants["finance"] = {"evidence.write", "evidence.revoke"}
        self.runtime = Runtime(self.path, ExpensePolicy(), grants)
        initialize(self.runtime)
        self.k1 = SourceKey("ring-2026-08", key(), current=True)
        self.k2 = SourceKey("ring-2026-10", key())

    def message(self, **overrides):
        base = {"source": "finance", "command_id": "cmd-1", "work_id": "demo",
                "event_id": "evt-1", "kind": "approval",
                "data": {"digest": self.runtime.get_work("demo")["document_digest"]},
                "issued_at": self.now}
        base.update(overrides)
        return base

    def signed(self, secret, key_id=False, **overrides):
        message = self.message(**overrides)
        if key_id is not False:
            message["key_id"] = key_id
        return sign_evidence(secret, message)

    def gateway(self, ring=None, clock=None, runtime=None):
        return SignedEvidenceGateway(runtime or self.runtime,
                                     {"finance": ring or [self.k1, self.k2]},
                                     clock=clock or (lambda: self.now))

    def table_counts(self):
        with sqlite3.connect(self.path) as db:
            return {t: db.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
                    for t in ("works", "commands", "evidence", "operations", "events", "metadata")}

    def table_dump(self):
        dump = {}
        with sqlite3.connect(self.path) as db:
            for table in ("works", "commands", "evidence", "operations",
                          "events", "metadata"):
                dump[table] = db.execute(
                    "SELECT * FROM %s ORDER BY rowid" % table).fetchall()
        return dump

    def test_resign_same_event_new_command_under_new_key_dedupes(self):
        gateway = self.gateway()
        first = gateway.record(self.signed(self.k1.secret, key_id=self.k1.key_id,
                                           command_id="cmd-a", event_id="evt-1"))
        before = self.table_counts()
        second = gateway.record(self.signed(self.k2.secret, key_id=self.k2.key_id,
                                            command_id="cmd-b", event_id="evt-1"))
        self.assertEqual(second["decision"], "accepted")
        self.assertEqual(second["evidence_id"], first["evidence_id"])
        self.assertEqual(second["evidence_status"], "pending_verification")
        after = self.table_counts()
        self.assertEqual(after["commands"], before["commands"] + 1)
        self.assertEqual(after["evidence"], before["evidence"])

    def test_resign_same_command_under_new_key_returns_original_receipt(self):
        gateway = self.gateway()
        first = gateway.record(self.signed(self.k1.secret, key_id=self.k1.key_id,
                                           command_id="cmd-a", event_id="evt-1"))
        before = self.table_dump()
        resend = gateway.record(self.signed(self.k2.secret, key_id=self.k2.key_id,
                                            command_id="cmd-a", event_id="evt-1"))
        self.assertEqual(resend, first)
        self.assertEqual(self.table_dump(), before)

    def test_revoked_evidence_preserves_original_receipt_and_reports_status(self):
        gateway = self.gateway()
        first = gateway.record(self.signed(self.k1.secret, key_id=self.k1.key_id,
                                           command_id="cmd-a", event_id="evt-1"))
        version = self.runtime.get_work("demo")["state_version"]
        self.runtime.command("finance", "cmd-revoke", "demo", "revoke_evidence",
                             {"source": "finance", "event_id": "evt-1",
                              "reason": "rotated"}, version)
        after_revoke = self.table_dump()
        same_command = gateway.record(
            self.signed(self.k2.secret, key_id=self.k2.key_id,
                        command_id="cmd-a", event_id="evt-1"))
        self.assertEqual(same_command, first)  # original pending receipt verbatim
        self.assertEqual(self.table_dump(), after_revoke)
        before = self.table_counts()
        new_command = gateway.record(
            self.signed(self.k2.secret, key_id=self.k2.key_id,
                        command_id="cmd-b", event_id="evt-1"))
        self.assertEqual(new_command["decision"], "accepted")
        self.assertEqual(new_command["evidence_id"], first["evidence_id"])
        self.assertEqual(new_command["evidence_status"], "revoked")
        after = self.table_counts()
        self.assertEqual(after["commands"], before["commands"] + 1)
        self.assertEqual(after["evidence"], before["evidence"])

    def test_grant_loss_is_fresh_unpersisted_authority_denied(self):
        gateway = self.gateway()
        envelope = self.signed(self.k2.secret, key_id=self.k2.key_id,
                               command_id="cmd-a", event_id="evt-1")
        self.assertEqual(gateway.record(envelope)["decision"], "accepted")
        before = self.table_dump()
        reopened = Runtime(self.path, ExpensePolicy(),
                           {"agent": {"work.manage", "expense.submit"}})  # no finance
        denied = self.gateway(runtime=reopened).record(envelope)
        self.assertEqual(denied, {"decision": "rejected", "code": "AUTHORITY_DENIED"})
        self.assertEqual(self.table_dump(), before)

    def test_changed_content_same_event_is_source_event_conflict(self):
        gateway = self.gateway()
        gateway.record(self.signed(self.k1.secret, key_id=self.k1.key_id,
                                   command_id="cmd-a", event_id="evt-1"))
        before = self.table_counts()
        conflict = gateway.record(
            self.signed(self.k2.secret, key_id=self.k2.key_id,
                        command_id="cmd-b", event_id="evt-1", data={"digest": "0" * 64}))
        self.assertEqual(conflict["code"], "SOURCE_EVENT_CONFLICT")
        after = self.table_counts()
        self.assertEqual(after["commands"], before["commands"] + 1)
        self.assertEqual(after["evidence"], before["evidence"])

    def test_retired_key_replay_cannot_reach_cached_receipt(self):
        original = self.gateway().record(
            self.signed(self.k1.secret, key_id=self.k1.key_id,
                        command_id="cmd-a", event_id="evt-1"))
        self.assertEqual(original["decision"], "accepted")
        envelope = self.signed(self.k1.secret, key_id=self.k1.key_id,
                               command_id="cmd-a", event_id="evt-1")
        rotated = [SourceKey(self.k1.key_id, self.k1.secret, not_after=self.now - 10),
                   SourceKey(self.k2.key_id, self.k2.secret, current=True)]
        before = self.table_dump()
        replay = self.gateway(ring=rotated).record(envelope)
        self.assertEqual(replay, {"decision": "rejected", "code": "EVIDENCE_KEY_RETIRED"})
        self.assertEqual(self.table_dump(), before)

    def test_history_six_tables_preserved_across_rotation_acts(self):
        gateway = self.gateway()
        gateway.record(self.signed(self.k1.secret, key_id=self.k1.key_id,
                                   command_id="cmd-a", event_id="evt-1"))
        gateway.record(self.signed(self.k2.secret, key_id=self.k2.key_id,
                                   command_id="cmd-b", event_id="evt-2"))
        self.runtime.verify_pending("demo")  # one legitimate evaluation bump
        snapshot = self.table_dump()
        # Pure reconstruction plus every denial class writes nothing, byte-equal
        # across all six tables including metadata.
        idle = self.gateway()
        retired = [SourceKey(self.k1.key_id, self.k1.secret, not_after=self.now - 10),
                   SourceKey(self.k2.key_id, self.k2.secret, current=True)]
        future = [SourceKey(self.k1.key_id, self.k1.secret,
                            not_before=self.now + 10),
                  SourceKey(self.k2.key_id, self.k2.secret, current=True)]
        broken = self.gateway(clock=lambda: float("nan"))
        tampered = self.signed(self.k1.secret, key_id=self.k1.key_id,
                               command_id="cmd-a", event_id="evt-1")
        tampered["event_id"] = "evt-tampered"  # valid bytes, now forged
        denials = (
            idle.record(self.signed(self.k1.secret, source="ghost")),
            idle.record(tampered),
            idle.record(self.signed(self.k1.secret, key_id="ring-ghost")),
            idle.record(self.signed(self.k1.secret, issued_at=self.now - 301)),
            self.gateway(ring=retired).record(
                self.signed(self.k1.secret, key_id=self.k1.key_id)),
            self.gateway(ring=future).record(
                self.signed(self.k1.secret, key_id=self.k1.key_id)),
            broken.record(self.signed(self.k1.secret)),
        )
        for receipt in denials:
            self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(self.table_dump(), snapshot)
        # Legitimate new ingress keeps the append-only tables prefix-equal and
        # leaves works/metadata untouched by the mere pending insertion (M1:
        # per-act scope, no universal works-row-prefix claim).
        accepted = self.gateway().record(
            self.signed(self.k2.secret, key_id=self.k2.key_id,
                        command_id="cmd-c", event_id="evt-3"))
        self.assertEqual(accepted["decision"], "accepted")
        grown = self.table_dump()
        for table in ("commands", "evidence", "operations", "events"):
            self.assertEqual(grown[table][:len(snapshot[table])], snapshot[table], table)
        self.assertEqual(grown["works"], snapshot["works"])
        self.assertEqual(grown["metadata"], snapshot["metadata"])

    def test_deterministic_restart_same_config_same_decisions(self):
        series = [
            self.signed(self.k1.secret, key_id=self.k1.key_id,
                        command_id="cmd-a", event_id="evt-1"),
            self.signed(self.k1.secret, key_id=self.k1.key_id,
                        command_id="cmd-a", event_id="evt-1"),  # exact replay
            self.signed(self.k1.secret, key_id=self.k1.key_id,
                        command_id="cmd-stale", event_id="evt-stale",
                        issued_at=self.now - 301),
            self.signed(key(), key_id=self.k1.key_id,
                        command_id="cmd-bad", event_id="evt-bad"),
            self.signed(self.k2.secret, key_id="ring-ghost",
                        command_id="cmd-ghost", event_id="evt-ghost"),
        ]
        first = [self.gateway().record(envelope) for envelope in series]
        restarted = self.gateway()  # same config, same clock, same store
        second = [restarted.record(envelope) for envelope in series]
        self.assertEqual(second, first)

    def test_new_code_receipts_are_minimal_without_key_echo(self):
        retired = [SourceKey(self.k1.key_id, self.k1.secret, not_after=self.now - 10),
                   SourceKey(self.k2.key_id, self.k2.secret, current=True)]
        future = [SourceKey(self.k1.key_id, self.k1.secret,
                            not_before=self.now + 10),
                  SourceKey(self.k2.key_id, self.k2.secret, current=True)]
        cases = (
            (self.gateway(ring=retired),
             self.signed(self.k1.secret, key_id=self.k1.key_id), "EVIDENCE_KEY_RETIRED"),
            (self.gateway(ring=future),
             self.signed(self.k1.secret, key_id=self.k1.key_id),
             "EVIDENCE_KEY_NOT_YET_VALID"),
            (self.gateway(clock=lambda: float("inf")),
             self.signed(self.k1.secret), "EVIDENCE_CLOCK_INVALID"),
            (self.gateway(),
             self.signed(self.k1.secret, key_id="ring-ghost"),
             "EVIDENCE_AUTHENTICATION_FAILED"),
        )
        for gateway, envelope, code in cases:
            receipt = gateway.record(envelope)
            self.assertEqual(receipt, {"decision": "rejected", "code": code})
            self.assertEqual(set(receipt), {"decision", "code"})
            rendered = json.dumps(receipt)
            self.assertNotIn(self.k1.key_id, rendered)
            self.assertNotIn(self.k2.key_id, rendered)
            self.assertNotIn(self.k1.secret.hex(), rendered)
            self.assertNotIn(self.k2.secret.hex(), rendered)

    def test_reserved_and_withdrawn_kinds_unchanged_for_keyring_source(self):
        gateway = self.gateway()
        before = self.table_counts()
        reserved = gateway.record(
            self.signed(self.k1.secret, kind="accepted",
                        data={"digest": "0" * 64, "external_id": "X"}))
        self.assertEqual(reserved,
                         {"decision": "rejected", "code": "EVIDENCE_KIND_UNSUPPORTED"})
        self.assertEqual(self.table_counts(), before)
        withdrawn = gateway.record(
            self.signed(self.k1.secret, kind="withdrawn",
                        command_id="cmd-w", event_id="evt-w",
                        data={"digest": "0" * 64}))
        self.assertEqual(withdrawn["code"], "AUTHORITY_DENIED")
        after = self.table_counts()
        self.assertEqual(after["commands"], before["commands"] + 1)
        self.assertEqual(after["evidence"], before["evidence"])


class LegacyCompatTests(unittest.TestCase):
    """Legacy bytes behavior unchanged beside keyrings; published KAT (T16/T25)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 2000000000
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        self.runtime = Runtime(self.path, ExpensePolicy(), demo_grants())
        initialize(self.runtime)
        self.finance_k1 = SourceKey("ring-2026-08", key(), current=True)
        self.requester = key()

    def message(self, **overrides):
        base = {"source": "requester", "command_id": "cmd-1", "work_id": "demo",
                "event_id": "evt-1", "kind": "confirmation",
                "data": {"digest": "0" * 64}, "issued_at": self.now}
        base.update(overrides)
        return base

    def signed(self, secret, **overrides):
        return sign_evidence(secret, self.message(**overrides))

    def gateway(self):
        return SignedEvidenceGateway(
            self.runtime,
            {"finance": [self.finance_k1], "requester": self.requester},
            clock=lambda: self.now)

    def table_counts(self):
        with sqlite3.connect(self.path) as db:
            return {t: db.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
                    for t in ("works", "commands", "evidence", "operations", "events", "metadata")}

    def test_legacy_bytes_source_semantics_beside_a_keyring(self):
        gateway = self.gateway()
        first = gateway.record(self.signed(self.requester))
        self.assertEqual(first["decision"], "accepted")
        replay = gateway.record(self.signed(self.requester))
        self.assertEqual(replay, first)
        stable = self.table_counts()
        tampered = self.signed(self.requester)
        tampered["event_id"] = "evt-tampered"
        self.assertEqual(gateway.record(tampered),
                         {"decision": "rejected", "code": "EVIDENCE_AUTHENTICATION_FAILED"})
        stale = self.signed(self.requester, command_id="cmd-stale",
                            event_id="evt-stale", issued_at=self.now - 301)
        self.assertEqual(gateway.record(stale),
                         {"decision": "rejected", "code": "EVIDENCE_EXPIRED"})
        self.assertEqual(self.table_counts(), stable)
        # The ring source in the same gateway keeps working throughout.
        ring_envelope = sign_evidence(self.finance_k1.secret, {
            "source": "finance", "command_id": "cmd-ring", "work_id": "demo",
            "event_id": "evt-ring", "kind": "approval",
            "data": {"digest": self.runtime.get_work("demo")["document_digest"]},
            "issued_at": self.now, "key_id": self.finance_k1.key_id})
        self.assertEqual(gateway.record(ring_envelope)["decision"], "accepted")

    def test_known_answer_vector_unchanged(self):
        # Published non-secret vector (identical to tests/test_ingress.py): the
        # legacy seven-field canonicalization is untouched by rotation work.
        envelope = sign_evidence(bytes(range(32)), {
            "source": "invoice-service", "command_id": "cmd-kat", "work_id": "demo",
            "event_id": "evt-kat", "kind": "invoice_valid",
            "data": {"invoice_id": "INV-KAT", "invoice_revision": 1, "valid": True},
            "issued_at": 2000000000})
        self.assertEqual(envelope["signature"],
                         "84ba6259ac240cab06a5f9df89b8525be99ecb20605b975d76ee6e7f0c04ec08")


if __name__ == "__main__":
    unittest.main()
