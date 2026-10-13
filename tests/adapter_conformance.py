"""Reusable adapter conformance tests over disposable fixtures.

A domain adopts this mixin next to unittest.TestCase and implements the
four fixture hooks. The tests mutate the adapter's external store, so every
hook must return a fresh, explicitly disposable fixture (for example a
SQLite file under a per-test temporary directory). Domain-specific
uniqueness beyond key idempotency is tested separately by each domain.
"""

import dataclasses

from work_runtime.adapter_contract import AdapterContract, receipt_is_valid, valid_contract
from work_runtime.policy import digest


class AdapterConformanceMixin:
    """Conformance tests for an adapter declaring an AdapterContract.

    Fixture hooks (override all four):
    - make_adapter(): a fresh disposable adapter instance.
    - sample_document(): a valid document for a declared action.
    - changed_document(): a valid document with a DIFFERENT digest.
    - effect_count(adapter): external effects committed so far.
    """

    def make_adapter(self):
        raise NotImplementedError("conformance fixtures must be disposable; provide make_adapter()")

    def sample_document(self):
        raise NotImplementedError("provide sample_document()")

    def changed_document(self):
        raise NotImplementedError("provide changed_document() with a different digest")

    def effect_count(self, adapter):
        raise NotImplementedError("provide effect_count(adapter)")

    def test_declared_contract_meets_metadata_invariants(self):
        adapter = self.make_adapter()
        contract = getattr(adapter, "contract", None)
        self.assertIsNotNone(contract, "adapter must declare a contract")
        self.assertIsInstance(contract, AdapterContract)
        self.assertTrue(valid_contract(contract))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            contract.retention = "tampered"

    def test_same_key_replay_returns_identical_receipt_with_one_effect(self):
        adapter = self.make_adapter()
        document = self.sample_document()
        first = adapter.execute("conformance-key", document, digest(document))
        second = adapter.execute("conformance-key", document, digest(document))
        self.assertEqual(first, second)
        self.assertTrue(receipt_is_valid(first, digest(document)))
        self.assertEqual(self.effect_count(adapter), 1)

    def test_same_key_different_content_raises_without_new_effect(self):
        adapter = self.make_adapter()
        document = self.sample_document()
        adapter.execute("conformance-key", document, digest(document))
        changed = self.changed_document()
        with self.assertRaises(ValueError):
            adapter.execute("conformance-key", changed, digest(changed))
        self.assertEqual(self.effect_count(adapter), 1)

    def test_lookup_existing_key_returns_committed_receipt(self):
        adapter = self.make_adapter()
        document = self.sample_document()
        receipt = adapter.execute("conformance-key", document, digest(document))
        self.assertEqual(adapter.lookup("conformance-key"), receipt)

    def test_lookup_missing_key_returns_none(self):
        adapter = self.make_adapter()
        self.assertIsNone(adapter.lookup("missing-conformance-key"))
