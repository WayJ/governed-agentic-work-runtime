"""Adapter contract, conformance mixin adoption and runtime preflight tests."""

import dataclasses
import json
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from work_runtime import CommandError, ExpensePolicy, Runtime
from work_runtime.adapter_contract import AdapterContract, receipt_is_valid, valid_contract
from work_runtime.adapters import FakeOA
from work_runtime.demo import action, demo_grants, document, initialize, prerequisites, send

try:
    from adapter_conformance import AdapterConformanceMixin
except ImportError:
    from tests.adapter_conformance import AdapterConformanceMixin

VALID_KWARGS = dict(actions=("expense.submit",), idempotency_scope="adapter-store:key",
                    retention="lifetime-of-store", lookup_consistency="authoritative-by-key",
                    uniqueness=("invoice.id",))


class ReceiptIsValidTests(unittest.TestCase):
    digest = "a" * 64

    def test_valid_accepted_and_rejected_receipts(self):
        accepted = {"status": "accepted", "external_id": "OA-1", "digest": self.digest}
        self.assertTrue(receipt_is_valid(accepted, self.digest))
        rejected = {"status": "rejected", "external_id": "OA-2", "digest": self.digest,
                    "extra": "extra receipt fields remain allowed"}
        self.assertTrue(receipt_is_valid(rejected, self.digest))

    def test_non_dict_results_are_invalid(self):
        for result in ("ok", None, 42, ["accepted"], b"bytes"):
            with self.subTest(result=repr(result)):
                self.assertFalse(receipt_is_valid(result, self.digest))

    def test_missing_fields_are_invalid(self):
        cases = {
            "digest-missing": {"status": "accepted", "external_id": "OA-1"},
            "status-missing": {"digest": self.digest, "external_id": "OA-1"},
            "external-id-missing": {"digest": self.digest, "status": "accepted"},
        }
        for name, result in cases.items():
            with self.subTest(variant=name):
                self.assertFalse(receipt_is_valid(result, self.digest))

    def test_wrong_digest_is_invalid(self):
        result = {"status": "accepted", "external_id": "OA-1", "digest": "b" * 64}
        self.assertFalse(receipt_is_valid(result, self.digest))

    def test_invalid_status_or_external_id_is_invalid(self):
        cases = {
            "status-pending": {"digest": self.digest, "status": "pending", "external_id": "OA-1"},
            "external-id-empty": {"digest": self.digest, "status": "accepted", "external_id": ""},
            "external-id-non-string": {"digest": self.digest, "status": "accepted", "external_id": 7},
        }
        for name, result in cases.items():
            with self.subTest(variant=name):
                self.assertFalse(receipt_is_valid(result, self.digest))


class AdapterContractTests(unittest.TestCase):
    def make(self, **overrides):
        return AdapterContract(**{**VALID_KWARGS, **overrides})

    def test_valid_contract_round_trips_fields_and_validates(self):
        contract = self.make()
        self.assertEqual(contract.actions, ("expense.submit",))
        self.assertEqual(contract.idempotency_scope, "adapter-store:key")
        self.assertEqual(contract.retention, "lifetime-of-store")
        self.assertEqual(contract.lookup_consistency, "authoritative-by-key")
        self.assertEqual(contract.uniqueness, ("invoice.id",))
        self.assertTrue(valid_contract(contract))

    def test_contract_is_frozen(self):
        contract = self.make()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            contract.retention = "tampered"

    def test_construction_rejects_invalid_invariants(self):
        cases = {
            "actions-empty": dict(actions=()),
            "actions-duplicate": dict(actions=("expense.submit", "expense.submit")),
            "action-not-string": dict(actions=(("nested",),)),
            "action-empty-string": dict(actions=("",)),
            "actions-not-tuple": dict(actions=["expense.submit"]),
            "scope-empty": dict(idempotency_scope=""),
            "scope-not-string": dict(idempotency_scope=5),
            "retention-empty": dict(retention=""),
            "lookup-empty": dict(lookup_consistency=""),
            "uniqueness-not-tuple": dict(uniqueness=["invoice.id"]),
            "uniqueness-entry-empty": dict(uniqueness=("",)),
            "uniqueness-entry-not-string": dict(uniqueness=(5,)),
        }
        for name, overrides in cases.items():
            with self.subTest(variant=name):
                with self.assertRaises(ValueError):
                    self.make(**overrides)

    def test_empty_uniqueness_means_no_additional_promise(self):
        contract = self.make(uniqueness=())
        self.assertEqual(contract.uniqueness, ())
        self.assertTrue(valid_contract(contract))

    def test_valid_contract_rejects_non_contract_values(self):
        for value in ("expense.submit", {"actions": ["expense.submit"]}, None, 42):
            with self.subTest(value=repr(value)):
                self.assertFalse(valid_contract(value))


if __name__ == "__main__":
    unittest.main()


class FakeOAConformanceTests(AdapterConformanceMixin, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def make_adapter(self):
        return FakeOA(str(Path(self.temp.name) / ("oa-" + uuid.uuid4().hex + ".sqlite")))

    def sample_document(self):
        return document()

    def changed_document(self):
        return document(amount=130000)

    def effect_count(self, adapter):
        return adapter.accepted_count()


class GatewayAcceptedPolicy(ExpensePolicy):
    evidence_sources = {"invoice_valid": "invoice-service", "duplicate_clear": "expense-service",
                        "approval": "finance", "confirmation": "requester",
                        "accepted": "oa-gateway"}


class MissingAcceptedPolicy(ExpensePolicy):
    evidence_sources = {k: v for k, v in ExpensePolicy.evidence_sources.items() if k != "accepted"}


class EmptyAcceptedPolicy(ExpensePolicy):
    evidence_sources = {**ExpensePolicy.evidence_sources, "accepted": ""}


class NonStringAcceptedPolicy(ExpensePolicy):
    evidence_sources = {**ExpensePolicy.evidence_sources, "accepted": None}


class CountingFakeOA:
    """Delegates to a real adapter while counting external interactions."""

    contract = FakeOA.contract

    def __init__(self, inner):
        self.inner = inner
        self.executed = 0
        self.looked_up = 0

    def execute(self, *args):
        self.executed += 1
        return self.inner.execute(*args)

    def lookup(self, *args):
        self.looked_up += 1
        return self.inner.lookup(*args)


def evidence_rows(path, work_id="demo"):
    db = sqlite3.connect(path)
    try:
        return [(row[0], row[1], json.loads(row[2])) for row in db.execute(
            "SELECT source, event_id, body FROM evidence WHERE work_id=?", (work_id,))]
    finally:
        db.close()


class PolicyReceiptSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        self.oa_path = str(Path(self.temp.name) / "oa.sqlite")

    def runtime_with(self, policy):
        runtime = Runtime(self.path, policy, demo_grants())
        initialize(runtime)
        return runtime

    def submit(self, runtime):
        prerequisites(runtime)
        receipt = action(runtime)
        self.assertEqual(receipt["decision"], "accepted")
        return receipt["operation_id"]

    def accepted_rows(self, path=None):
        return [row for row in evidence_rows(path or self.path)
                if row[2].get("kind") == "accepted"]

    def test_policy_owned_accepted_source_is_adopted(self):
        runtime = self.runtime_with(GatewayAcceptedPolicy())
        op = self.submit(runtime)
        self.assertEqual(runtime.dispatch(op, FakeOA(self.oa_path))["status"],
                         "confirmed_succeeded")
        rows = self.accepted_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0][0], rows[0][1]), ("oa-gateway", op))
        self.assertNotIn("oa", {row[0] for row in evidence_rows(self.path)})
        requirement = next(r for r in runtime.get_work("demo")["requirements"]
                           if r["rule_id"] == "E08")
        self.assertEqual(requirement["fulfillment"], "satisfied")
        self.assertEqual(send(runtime, "demo", "request_completion")["decision"], "accepted")

    def test_dispatch_fails_closed_without_accepted_source(self):
        policies = {"missing": MissingAcceptedPolicy, "empty": EmptyAcceptedPolicy,
                    "non-string": NonStringAcceptedPolicy}
        for name, policy_class in policies.items():
            with self.subTest(variant=name):
                path = str(Path(self.temp.name) / (name + ".sqlite"))
                oa_path = str(Path(self.temp.name) / (name + "-oa.sqlite"))
                runtime = Runtime(path, policy_class(), demo_grants())
                initialize(runtime)
                prerequisites(runtime)
                op = action(runtime)["operation_id"]
                oa = FakeOA(oa_path)
                with self.assertRaises(CommandError):
                    runtime.dispatch(op, oa)
                persisted = runtime.get_operation(op)
                self.assertEqual((persisted["status"], persisted["dispatch_state"]),
                                 ("prepared", "ready"))
                self.assertEqual(persisted["attempts"], [])
                self.assertEqual(oa.accepted_count(), 0)

    def test_reconcile_fails_closed_before_querying(self):
        runtime = self.runtime_with(ExpensePolicy())
        op = self.submit(runtime)
        counting = CountingFakeOA(FakeOA(self.oa_path, timeout_after_commit=True))
        self.assertEqual(runtime.dispatch(op, counting)["status"], "outcome_unknown")
        runtime.policy = MissingAcceptedPolicy()
        with self.assertRaises(CommandError):
            runtime.reconcile(op, counting)
        self.assertEqual(counting.looked_up, 0)

    def test_resolve_fails_closed_and_never_adopts_proof_under_broken_config(self):
        runtime = self.runtime_with(ExpensePolicy())
        op = self.submit(runtime)
        oa = FakeOA(self.oa_path)

        def break_config():
            runtime.policy = MissingAcceptedPolicy()

        with self.assertRaises(CommandError):
            runtime.dispatch(op, oa, fault=break_config)
        self.assertEqual(oa.accepted_count(), 1)
        persisted = runtime.get_operation(op)
        self.assertEqual(persisted["status"], "dispatched")
        self.assertEqual(len(persisted["attempts"]), 1)
        self.assertEqual(persisted["attempts"][-1]["status"], "outcome_unknown")
        self.assertEqual(self.accepted_rows(), [])
        runtime.policy = GatewayAcceptedPolicy()
        reconciled = runtime.reconcile(op, FakeOA(self.oa_path))
        self.assertEqual(reconciled["status"], "confirmed_succeeded")
        self.assertEqual([row[0] for row in self.accepted_rows()], ["oa-gateway"])

    def test_terminal_operation_early_returns_stay_config_independent(self):
        runtime = self.runtime_with(ExpensePolicy())
        op = self.submit(runtime)
        self.assertEqual(runtime.dispatch(op, FakeOA(self.oa_path))["status"],
                         "confirmed_succeeded")
        runtime.policy = MissingAcceptedPolicy()
        self.assertEqual(runtime.reconcile(op, FakeOA(self.oa_path))["status"],
                         "confirmed_succeeded")
        self.assertEqual(runtime.dispatch(op, FakeOA(self.oa_path))["status"],
                         "confirmed_succeeded")


class ExportCapablePolicy(ExpensePolicy):
    def action_blockers(self, capability, requirements):
        if capability not in ("expense.submit", "expense.export"):
            return [{"code": "CAPABILITY_UNSUPPORTED", "capability": capability}]
        return [r for r in requirements if r["rule_id"] != "E08" and
                (r["applicability"] in ("unknown", "conflict")
                 or (r["applicability"] == "applicable" and r["fulfillment"] != "satisfied"))]


class ExportCapableOA(FakeOA):
    contract = AdapterContract(
        actions=("expense.submit", "expense.export"),
        idempotency_scope="adapter-store:key",
        retention="lifetime-of-store",
        lookup_consistency="authoritative-by-key",
        uniqueness=("invoice.id",))


class StringContractOA(FakeOA):
    contract = "expense.submit"


class DictContractOA(FakeOA):
    contract = {"actions": ["expense.submit"]}


def export_grants():
    grants = demo_grants()
    grants["agent"] = grants["agent"] | {"expense.export"}
    return grants


def export_action(runtime, work_id="demo"):
    work = runtime.get_work(work_id)
    return send(runtime, work_id, "propose_action", {
        "capability": "expense.export", "document_digest": work["document_digest"],
        "contract_revision": work["contract"]["revision"], "plan_revision": work["plan_revision"]})


class DeclaredCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        self.oa_path = str(Path(self.temp.name) / "oa.sqlite")

    def runtime_with(self, policy, grants=None):
        runtime = Runtime(self.path, policy, grants or demo_grants())
        initialize(runtime)
        return runtime

    def submit_export(self, runtime):
        prerequisites(runtime)
        receipt = export_action(runtime)
        self.assertEqual(receipt["decision"], "accepted")
        return receipt["operation_id"]

    def dispatch_held_events(self, runtime, reason):
        return [e for e in runtime.events("demo") if e["type"] == "DispatchHeld"
                and json.loads(e["body"])["reason"] == reason]

    def test_unsupported_declared_capability_holds_with_zero_attempts_or_calls(self):
        runtime = self.runtime_with(ExportCapablePolicy(), export_grants())
        op = self.submit_export(runtime)
        oa = FakeOA(self.oa_path)
        counting = CountingFakeOA(oa)
        held = runtime.dispatch(op, counting)
        self.assertEqual((held["dispatch_state"], held.get("reason")),
                         ("held", "ADAPTER_ACTION_UNSUPPORTED"))
        self.assertEqual((counting.executed, counting.looked_up), (0, 0))
        persisted = runtime.get_operation(op)
        self.assertEqual(persisted["attempts"], [])
        self.assertEqual(oa.accepted_count(), 0)
        self.assertEqual(len(self.dispatch_held_events(runtime, "ADAPTER_ACTION_UNSUPPORTED")), 1)
        self.assertNotEqual(runtime.get_work("demo")["status"], "needs_attention")

    def test_held_operation_dispatches_with_compatible_adapter(self):
        runtime = self.runtime_with(ExportCapablePolicy(), export_grants())
        op = self.submit_export(runtime)
        oa = FakeOA(self.oa_path)
        restricted = CountingFakeOA(oa)
        self.assertEqual(runtime.dispatch(op, restricted)["dispatch_state"], "held")
        resolved = runtime.dispatch(op, ExportCapableOA(self.oa_path))
        self.assertEqual(resolved["status"], "confirmed_succeeded")
        self.assertEqual((restricted.executed, oa.accepted_count()), (0, 1))

    def test_malformed_descriptor_fails_closed_before_external_call(self):
        for name, adapter_class in {"string": StringContractOA, "dict": DictContractOA}.items():
            with self.subTest(variant=name):
                path = str(Path(self.temp.name) / (name + ".sqlite"))
                oa_path = str(Path(self.temp.name) / (name + "-oa.sqlite"))
                runtime = Runtime(path, ExportCapablePolicy(), export_grants())
                initialize(runtime)
                prerequisites(runtime)
                op = export_action(runtime)["operation_id"]
                adapter = adapter_class(oa_path)
                with self.assertRaises(CommandError):
                    runtime.dispatch(op, adapter)
                persisted = runtime.get_operation(op)
                self.assertEqual(persisted["attempts"], [])
                self.assertEqual(adapter.accepted_count(), 0)

    def test_legacy_adapter_without_contract_still_dispatches(self):
        class LegacyCounting:
            def __init__(self, inner):
                self.inner = inner
                self.executed = 0

            def execute(self, *args):
                self.executed += 1
                return self.inner.execute(*args)

            def lookup(self, *args):
                return self.inner.lookup(*args)

        runtime = self.runtime_with(ExpensePolicy())
        prerequisites(runtime)
        op = action(runtime)["operation_id"]
        legacy = LegacyCounting(FakeOA(self.oa_path))
        self.assertFalse(hasattr(legacy, "contract"))
        resolved = runtime.dispatch(op, legacy)
        self.assertEqual((resolved["status"], legacy.executed), ("confirmed_succeeded", 1))
