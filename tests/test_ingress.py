"""Signed evidence ingress tests: strict envelopes, HMAC authentication, freshness, replay."""

import copy
import json
import secrets
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from work_runtime import CommandError, ExpensePolicy, Runtime
from work_runtime.demo import demo_grants, document, initialize, send
from work_runtime.ingress import SIGNED_FIELDS, SignedEvidenceGateway, sign_evidence


def key():
    return secrets.token_bytes(32)


def message(**overrides):
    base = {"source": "invoice-service", "command_id": "cmd-1", "work_id": "demo",
            "event_id": "evt-1", "kind": "invoice_valid",
            "data": {"invoice_id": "INV-001", "invoice_revision": 1, "valid": True},
            "issued_at": 2000000000}
    base.update(overrides)
    return base


class SignEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.secret = key()

    def test_envelope_has_exact_fields_and_lowercase_hex_signature(self):
        rich = message(data={"s": "text", "b": True, "n": None, "f": 1.5, "l": [1, {"k": "v"}]})
        envelope = sign_evidence(self.secret, rich)
        self.assertEqual(set(envelope), set(SIGNED_FIELDS) | {"signature"})
        self.assertRegex(envelope["signature"], "^[0-9a-f]{64}$")

    def test_known_answer_vector_pins_hmac_sha256(self):
        # Published non-secret test vector: key bytes 00..1f, HMAC-SHA256 over
        # the canonical JSON of the fixed message below.
        envelope = sign_evidence(bytes(range(32)), message(
            command_id="cmd-kat", event_id="evt-kat",
            data={"invoice_id": "INV-KAT", "invoice_revision": 1, "valid": True}))
        self.assertEqual(envelope["signature"],
                         "84ba6259ac240cab06a5f9df89b8525be99ecb20605b975d76ee6e7f0c04ec08")

    def test_input_message_is_never_mutated_and_envelope_is_detached(self):
        original = message()
        frozen = copy.deepcopy(original)
        envelope = sign_evidence(self.secret, original)
        self.assertEqual(original, frozen)
        snapshot = copy.deepcopy(envelope)
        original["data"]["valid"] = False
        original["event_id"] = "evt-mutated"
        self.assertEqual(envelope, snapshot)
        self.assertIsNot(envelope["data"], original["data"])

    def test_signature_depends_on_every_field(self):
        baseline = sign_evidence(self.secret, message())
        changes = {"source": "finance", "command_id": "cmd-2", "work_id": "other",
                   "event_id": "evt-2", "kind": "duplicate_clear",
                   "data": {"invoice_id": "INV-002", "invoice_revision": 1, "valid": True},
                   "issued_at": 2000000001}
        self.assertEqual(set(changes), set(SIGNED_FIELDS))
        for field, value in changes.items():
            other = sign_evidence(self.secret, message(**{field: value}))
            self.assertNotEqual(other["signature"], baseline["signature"], field)
        self.assertNotEqual(sign_evidence(key(), message())["signature"], baseline["signature"])

    def test_rejects_short_or_non_bytes_secret(self):
        for bad in ("str-secret", b"0" * 31, 32, None):
            with self.assertRaises(ValueError):
                sign_evidence(bad, message())

    def test_rejects_wrong_field_sets(self):
        missing = message()
        del missing["issued_at"]
        extra = message()
        extra["nonce"] = "x"
        alias = message()
        alias["actor"] = "finance"
        for bad in (missing, extra, alias):
            with self.assertRaises(ValueError):
                sign_evidence(self.secret, bad)

    def test_rejects_invalid_field_types(self):
        variants = {"issued_at": (True, False, "2000000000", 2000000000.5),
                    "source": ("", 7, None), "command_id": ("", 7), "work_id": ("", 7),
                    "event_id": ("", 7), "kind": ("", 7),
                    "data": ("not-a-dict", None, 42)}
        for field, values in variants.items():
            for value in values:
                with self.assertRaises(ValueError):
                    sign_evidence(self.secret, message(**{field: value}))
        with self.assertRaises(ValueError):
            sign_evidence(self.secret, ["not", "a", "dict"])

    def test_rejects_self_referencing_data_with_value_error(self):
        cyclic = {"digest": "0" * 64}
        cyclic["self"] = cyclic
        with self.assertRaises(ValueError):
            sign_evidence(self.secret, message(data=cyclic))

    def test_rejects_excessively_deep_nesting_with_value_error(self):
        node = deep = {}
        for _ in range(10000):
            node["child"] = {}
            node = node["child"]
        with self.assertRaises(ValueError):
            sign_evidence(self.secret, message(data=deep))

    def test_repeated_acyclic_references_sign_and_detach(self):
        shared = {"note": "shared", "n": 1}
        envelope = sign_evidence(self.secret,
                                 message(data={"x": shared, "y": shared, "z": [shared]}))
        self.assertRegex(envelope["signature"], "^[0-9a-f]{64}$")
        self.assertEqual(envelope["data"]["x"], envelope["data"]["y"])
        self.assertIsNot(envelope["data"]["x"], envelope["data"]["y"])
        self.assertIsNot(envelope["data"]["x"], shared)
        self.assertIsNot(envelope["data"]["z"][0], shared)

    def test_rejects_non_json_native_data(self):
        for bad_data in ({"x": float("nan")}, {"x": float("inf")}, {"x": float("-inf")},
                         {"deep": [{"y": (1, 2)}]}, {1: "int-key"}, {"x": {"y": {1, 2}}}):
            with self.assertRaises(ValueError):
                sign_evidence(self.secret, message(data=bad_data))


if __name__ == "__main__":
    unittest.main()


class SignedEvidenceGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 2000000000
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        self.runtime = Runtime(self.path, ExpensePolicy(), demo_grants())
        initialize(self.runtime)
        self.finance = key()
        self.invoice_service = key()
        self.gateway = SignedEvidenceGateway(
            self.runtime, {"finance": self.finance, "invoice-service": self.invoice_service},
            clock=lambda: self.now)

    def message(self, **overrides):
        base = {"source": "finance", "command_id": "cmd-1", "work_id": "demo",
                "event_id": "evt-1", "kind": "approval",
                "data": {"digest": self.runtime.get_work("demo")["document_digest"]},
                "issued_at": self.now}
        base.update(overrides)
        return base

    def signed(self, secret=None, **overrides):
        return sign_evidence(self.finance if secret is None else secret, self.message(**overrides))

    def table_counts(self, path=None):
        with sqlite3.connect(path or self.path) as db:
            return {t: db.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
                    for t in ("works", "commands", "evidence", "operations", "events", "metadata")}

    def evidence_bodies(self, path=None):
        with sqlite3.connect(path or self.path) as db:
            return [json.loads(r[0]) for r in db.execute("SELECT body FROM evidence")]

    def requirement(self, rule, work_id="demo"):
        return next(r for r in self.runtime.get_work(work_id)["requirements"] if r["rule_id"] == rule)

    def test_signed_evidence_is_accepted_and_pending_until_verification(self):
        receipt = self.gateway.record(self.signed())
        self.assertEqual(receipt["decision"], "accepted")
        self.assertEqual(receipt["evidence_status"], "pending_verification")
        self.assertEqual(self.requirement("E05")["fulfillment"], "pending")
        self.runtime.verify_pending("demo")
        self.assertEqual(self.requirement("E05")["fulfillment"], "satisfied")
        default_clock = SignedEvidenceGateway(self.runtime, {"finance": self.finance})
        just_issued = self.signed(command_id="cmd-clock", issued_at=int(time.time()))
        self.assertEqual(default_clock.record(just_issued)["decision"], "accepted")

    def test_accepted_evidence_forwards_verified_snapshot_only(self):
        envelope = self.signed()
        receipt = self.gateway.record(envelope)
        bodies = self.evidence_bodies()
        self.assertEqual(len(bodies), 1)
        body = bodies[0]
        self.assertEqual(set(body), {"id", "source", "event_id", "kind", "data", "status"})
        self.assertEqual(body["status"], "pending_verification")
        self.assertEqual(body["data"], envelope["data"])
        self.assertNotIn("signature", json.dumps(body))
        self.assertNotIn("issued_at", json.dumps(body))
        self.assertNotIn("signature", json.dumps(receipt))

    def test_freshness_boundaries(self):
        for issued_at in (self.now - 300, self.now + 300):
            envelope = self.signed(command_id="cmd-%d" % issued_at, event_id="evt-%d" % issued_at,
                                   issued_at=issued_at)
            self.assertEqual(self.gateway.record(envelope)["decision"], "accepted", issued_at)

    def test_stale_and_future_timestamps_are_expired(self):
        before = self.table_counts()
        for issued_at in (self.now - 301, self.now + 301):
            envelope = self.signed(command_id="cmd-%d" % issued_at, issued_at=issued_at)
            self.assertEqual(self.gateway.record(envelope),
                             {"decision": "rejected", "code": "EVIDENCE_EXPIRED"}, issued_at)
        self.assertEqual(self.table_counts(), before)

    def test_exact_replay_inside_freshness_returns_existing_receipt(self):
        before = self.table_counts()
        envelope = self.signed()
        first = self.gateway.record(envelope)
        second = self.gateway.record(envelope)
        self.assertEqual(first, second)
        after = self.table_counts()
        self.assertEqual(after["commands"], before["commands"] + 1)
        self.assertEqual(after["evidence"], before["evidence"] + 1)

    def test_expired_replay_is_refused_before_runtime(self):
        envelope = self.signed()
        self.assertEqual(self.gateway.record(envelope)["decision"], "accepted")
        accepted_counts = self.table_counts()
        self.now += 301
        self.assertEqual(self.gateway.record(envelope),
                         {"decision": "rejected", "code": "EVIDENCE_EXPIRED"})
        self.assertEqual(self.table_counts(), accepted_counts)

    def test_timestamp_refresh_under_new_command_keeps_event_identity(self):
        before = self.table_counts()
        first = self.gateway.record(self.signed())
        self.now += 60
        refreshed = self.gateway.record(self.signed(command_id="cmd-refresh", issued_at=self.now))
        self.assertEqual(refreshed["decision"], "accepted")
        self.assertEqual(refreshed["evidence_id"], first["evidence_id"])
        after = self.table_counts()
        self.assertEqual(after["evidence"], before["evidence"] + 1)
        self.assertEqual(after["commands"], before["commands"] + 2)

    def test_event_id_reused_across_works_is_source_event_conflict(self):
        before = self.table_counts()
        self.assertEqual(self.gateway.record(self.signed())["decision"], "accepted")
        send(self.runtime, "demo2", "create_work", {"document": document(document_id="EXP-002")})
        receipt = self.gateway.record(self.signed(command_id="cmd-2", work_id="demo2"))
        self.assertEqual(receipt["code"], "SOURCE_EVENT_CONFLICT")
        after = self.table_counts()
        self.assertEqual(after["evidence"], before["evidence"] + 1)
        self.assertEqual(after["commands"], before["commands"] + 3)

    def test_same_command_id_with_different_content_is_command_id_reused(self):
        self.gateway.record(self.signed())
        receipt = self.gateway.record(self.signed(event_id="evt-2", data={"digest": "different"}))
        self.assertEqual(receipt["code"], "COMMAND_ID_REUSED")

    def test_source_grant_refusal_follows_runtime_persistence(self):
        before = self.table_counts()
        receipt = self.gateway.record(self.signed(source="invoice-service", kind="approval",
                                                  secret=self.invoice_service))
        self.assertEqual(receipt["code"], "AUTHORITY_DENIED")
        after = self.table_counts()
        self.assertEqual(after["commands"], before["commands"] + 1)
        self.assertEqual(after["evidence"], before["evidence"])

    def test_source_without_grants_is_rejected_without_writes(self):
        observer = key()
        gateway = SignedEvidenceGateway(self.runtime, {"observer": observer}, clock=lambda: self.now)
        before = self.table_counts()
        receipt = gateway.record(self.signed(source="observer", secret=observer))
        self.assertEqual(receipt, {"decision": "rejected", "code": "AUTHORITY_DENIED"})
        self.assertEqual(self.table_counts(), before)

    def test_valid_signature_for_unknown_work_raises_command_error(self):
        before = self.table_counts()
        with self.assertRaises(CommandError):
            self.gateway.record(self.signed(work_id="ghost"))
        self.assertEqual(self.table_counts(), before)

    def test_reserved_accepted_kind_is_refused_after_authentication(self):
        oa_key = key()
        grants = demo_grants()
        grants["oa"] = {"evidence.write"}
        path = str(Path(self.temp.name) / "runtime-oa.sqlite")
        runtime = Runtime(path, ExpensePolicy(), grants)
        initialize(runtime)
        gateway = SignedEvidenceGateway(runtime, {"oa": oa_key}, clock=lambda: self.now)
        before = self.table_counts(path)
        envelope = sign_evidence(oa_key, {
            "source": "oa", "command_id": "cmd-oa", "work_id": "demo",
            "event_id": "evt-oa", "kind": "accepted",
            "data": {"digest": "0" * 64, "external_id": "X"}, "issued_at": self.now})
        self.assertEqual(gateway.record(envelope),
                         {"decision": "rejected", "code": "EVIDENCE_KIND_UNSUPPORTED"})
        self.assertEqual(self.table_counts(path), before)

    def test_every_signed_field_tampering_fails_authentication(self):
        digest = self.runtime.get_work("demo")["document_digest"]
        replacements = {"source": "invoice-service", "command_id": "cmd-2", "work_id": "other",
                        "event_id": "evt-2", "kind": "confirmation",
                        "data": {"digest": digest + "0"}, "issued_at": self.now - 1}
        self.assertEqual(set(replacements), set(SIGNED_FIELDS))
        before = self.table_counts()
        for field, value in replacements.items():
            envelope = self.signed()
            envelope[field] = value
            receipt = self.gateway.record(envelope)
            self.assertEqual(receipt,
                             {"decision": "rejected", "code": "EVIDENCE_AUTHENTICATION_FAILED"}, field)
            self.assertEqual(self.table_counts(), before, field)

    def test_cross_source_key_cannot_impersonate(self):
        before = self.table_counts()
        forged = self.signed(secret=self.invoice_service)
        self.assertEqual(self.gateway.record(forged),
                         {"decision": "rejected", "code": "EVIDENCE_AUTHENTICATION_FAILED"})
        self.assertEqual(self.table_counts(), before)

    def test_unknown_source_has_no_key_and_fails_authentication(self):
        before = self.table_counts()
        self.assertEqual(self.gateway.record(self.signed(source="attacker")),
                         {"decision": "rejected", "code": "EVIDENCE_AUTHENTICATION_FAILED"})
        self.assertEqual(self.table_counts(), before)

    def test_rejection_receipts_disclose_no_secret_or_candidate(self):
        envelope = self.signed()
        stale = self.signed(command_id="cmd-stale", event_id="evt-stale",
                            issued_at=self.now - 301)
        reserved = self.signed(command_id="cmd-res", event_id="evt-res", kind="accepted",
                               data={"digest": "0" * 64})
        cases = [("schema", dict(envelope, signature=None), "EVIDENCE_ENVELOPE_INVALID"),
                 ("auth", {**envelope, "event_id": "evt-tampered"}, "EVIDENCE_AUTHENTICATION_FAILED"),
                 ("expired", stale, "EVIDENCE_EXPIRED"),
                 ("reserved", reserved, "EVIDENCE_KIND_UNSUPPORTED")]
        for label, candidate, code in cases:
            receipt = self.gateway.record(candidate)
            self.assertEqual(receipt, {"decision": "rejected", "code": code}, label)
            self.assertEqual(set(receipt), {"decision", "code"}, label)
            rendered = json.dumps(receipt)
            self.assertNotIn(envelope["signature"], rendered, label)
            self.assertNotIn(self.finance.hex(), rendered, label)

    def test_non_dict_envelopes_are_invalid(self):
        before = self.table_counts()
        for bad in ("json-string", None, [self.signed()], 42):
            self.assertEqual(self.gateway.record(bad),
                             {"decision": "rejected", "code": "EVIDENCE_ENVELOPE_INVALID"})
        self.assertEqual(self.table_counts(), before)

    def test_wrong_envelope_field_sets_are_invalid(self):
        before = self.table_counts()
        missing = self.signed()
        del missing["kind"]
        extra = self.signed()
        extra["nonce"] = "x"
        alias = self.signed()
        alias["actor"] = "finance"
        for bad in (missing, extra, alias, {}):
            self.assertEqual(self.gateway.record(bad),
                             {"decision": "rejected", "code": "EVIDENCE_ENVELOPE_INVALID"})
        self.assertEqual(self.table_counts(), before)

    def test_invalid_field_types_are_invalid(self):
        before = self.table_counts()
        variants = [("issued_at", True), ("issued_at", "2000000000"), ("issued_at", 2000000000.5),
                    ("source", ""), ("source", 7), ("kind", None), ("event_id", ""),
                    ("data", "not-a-dict"), ("data", None), ("signature", None),
                    ("signature", "deadbeef"), ("signature", "X" * 64),
                    ("signature", self.signed()["signature"].upper())]
        for field, value in variants:
            envelope = self.signed()
            envelope[field] = value
            self.assertEqual(self.gateway.record(envelope),
                             {"decision": "rejected", "code": "EVIDENCE_ENVELOPE_INVALID"},
                             (field, value))
        self.assertEqual(self.table_counts(), before)

    def test_non_json_native_or_nonfinite_data_is_invalid(self):
        before = self.table_counts()
        for bad_data in ({"x": float("nan")}, {"x": float("inf")}, {"deep": [{"y": (1, 2)}]},
                         {1: "int-key"}, {"x": {"y": {1, 2}}}):
            envelope = self.signed()
            envelope["data"] = bad_data
            self.assertEqual(self.gateway.record(envelope),
                             {"decision": "rejected", "code": "EVIDENCE_ENVELOPE_INVALID"}, bad_data)
        self.assertEqual(self.table_counts(), before)

    def test_schema_precedes_authentication(self):
        before = self.table_counts()
        wrong_type = self.signed()
        wrong_type["issued_at"] = "2000000000"
        self.assertEqual(self.gateway.record(wrong_type),
                         {"decision": "rejected", "code": "EVIDENCE_ENVELOPE_INVALID"})
        nan_data = self.signed()
        nan_data["data"] = {"digest": float("nan")}
        self.assertEqual(self.gateway.record(nan_data),
                         {"decision": "rejected", "code": "EVIDENCE_ENVELOPE_INVALID"})
        self.assertEqual(self.table_counts(), before)

    def test_envelope_mutation_after_record_cannot_affect_persisted_evidence(self):
        envelope = self.signed()
        self.gateway.record(envelope)
        signed_digest = envelope["data"]["digest"]
        envelope["data"]["digest"] = "tampered"
        body = self.evidence_bodies()[0]
        self.assertEqual(body["data"]["digest"], signed_digest)
        self.assertEqual(self.gateway.record(envelope),
                         {"decision": "rejected", "code": "EVIDENCE_AUTHENTICATION_FAILED"})
        self.assertEqual(len(self.evidence_bodies()), 1)

    def test_short_non_bytes_or_duplicate_key_material_is_invalid(self):
        good = key()
        for bad_keys in (["finance"], {"finance": b"0" * 31}, {"finance": "str"}, {7: good},
                         {"": good}, {"finance": good, "invoice-service": good}):
            with self.assertRaises(ValueError):
                SignedEvidenceGateway(self.runtime, bad_keys, clock=lambda: self.now)

    def test_key_map_is_copied_at_construction(self):
        keys = {"finance": self.finance}
        gateway = SignedEvidenceGateway(self.runtime, keys, clock=lambda: self.now)
        keys["invoice-service"] = self.invoice_service
        envelope = self.signed(secret=self.invoice_service, source="invoice-service",
                               kind="invoice_valid",
                               data={"invoice_id": "INV-001", "invoice_revision": 1, "valid": True})
        self.assertEqual(gateway.record(envelope),
                         {"decision": "rejected", "code": "EVIDENCE_AUTHENTICATION_FAILED"})

    def test_invalid_max_age_or_clock_is_invalid(self):
        for bad_age in (-1, True, "300", 300.5):
            with self.assertRaises(ValueError):
                SignedEvidenceGateway(self.runtime, {"finance": self.finance},
                                      max_age=bad_age, clock=lambda: self.now)
        with self.assertRaises(ValueError):
            SignedEvidenceGateway(self.runtime, {"finance": self.finance}, clock="time.time")

    def test_empty_key_map_authenticates_nothing(self):
        gateway = SignedEvidenceGateway(self.runtime, {}, clock=lambda: self.now)
        before = self.table_counts()
        self.assertEqual(gateway.record(self.signed()),
                         {"decision": "rejected", "code": "EVIDENCE_AUTHENTICATION_FAILED"})
        self.assertEqual(self.table_counts(), before)

    def test_cyclic_or_deeply_nested_envelope_data_is_envelope_invalid(self):
        before = self.table_counts()
        cyclic = self.signed()
        cyclic["data"]["self"] = cyclic["data"]
        deep = self.signed(command_id="cmd-deep", event_id="evt-deep")
        node = deep["data"]
        for _ in range(10000):
            node["child"] = {}
            node = node["child"]
        for bad in (cyclic, deep):
            self.assertEqual(self.gateway.record(bad),
                             {"decision": "rejected", "code": "EVIDENCE_ENVELOPE_INVALID"})
        self.assertEqual(self.table_counts(), before)

    def test_utf8_encoding_failure_is_envelope_invalid(self):
        # Lone surrogates pass the str type check and defeat canonical UTF-8
        # encoding; B1 requires record to catch it, not leak a stacktrace.
        before = self.table_counts()
        surrogate_identity = self.signed()
        surrogate_identity["source"] = "fin\ud800ance"
        surrogate_data = self.signed(command_id="cmd-sur", event_id="evt-sur")
        surrogate_data["data"] = {"digest": "\ud800"}
        for bad in (surrogate_identity, surrogate_data):
            self.assertEqual(self.gateway.record(bad),
                             {"decision": "rejected", "code": "EVIDENCE_ENVELOPE_INVALID"})
        self.assertEqual(self.table_counts(), before)
