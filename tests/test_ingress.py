"""Signed evidence ingress tests: strict envelopes, HMAC authentication, freshness, replay."""

import copy
import json
import secrets
import sqlite3
import tempfile
import unittest
from pathlib import Path

from work_runtime import ExpensePolicy, Runtime
from work_runtime.demo import demo_grants, document, initialize, send
from work_runtime.ingress import SIGNED_FIELDS, sign_evidence


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

    def test_rejects_non_json_native_data(self):
        for bad_data in ({"x": float("nan")}, {"x": float("inf")}, {"x": float("-inf")},
                         {"deep": [{"y": (1, 2)}]}, {1: "int-key"}, {"x": {"y": {1, 2}}}):
            with self.assertRaises(ValueError):
                sign_evidence(self.secret, message(data=bad_data))


if __name__ == "__main__":
    unittest.main()
