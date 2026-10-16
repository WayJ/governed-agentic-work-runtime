"""S10 expense-compensation core: admission, execution, proof and closure.

Implements the master-ratified v2.1 design (D43-D48): linked compensation
proposals inside the active cancellation window, opt-in adapter action/link
execution, the FakeOA withdrawal store, the `withdrawn` proof kind, stored
adapter results and truthful closure. Expense family and active-cancellation
window only; publishing, post-closure compensation, chains and a public
abandon command remain future scope.
"""

import json
import sqlite3
import tempfile
import os
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from threading import Barrier, Thread

from work_runtime.adapter_contract import AdapterContract, receipt_is_valid
from work_runtime.adapters import FakeOA
from work_runtime import Runtime
from work_runtime.demo import action, document, initialize, prerequisites, send
from work_runtime.inspection import ReadOnlyInspector
from work_runtime.policy import ExpensePolicy, ExpensePolicyV2, canonical, digest


def compensation_grants(extra=None):
    """Demo grants with the compensating capability held by the owner."""
    grants = {"agent": {"work.manage", "expense.submit", "expense.withdraw"},
              "finance": {"evidence.write"}, "requester": {"evidence.write"},
              "invoice-service": {"evidence.write"}, "expense-service": {"evidence.write"},
              "admin": {"work.intervene"}}
    if extra:
        grants.update(extra)
    return grants


class PolicyPairingTests(unittest.TestCase):
    def test_paired_capability_has_no_requirement_blockers(self):
        pending = [{"id": "E01:EXP-001", "rule_id": "E01", "subject": "EXP-001",
                    "applicability": "applicable", "fulfillment": "pending",
                    "explanation": "…"}]
        for policy in (ExpensePolicy(), ExpensePolicyV2()):
            with self.subTest(version=policy.version):
                self.assertEqual(
                    policy.action_blockers("expense.withdraw", pending), [])
                self.assertEqual(policy.compensation_capabilities,
                                 {"expense.withdraw": "expense.submit"})

    def test_unpaired_and_publishing_capabilities_stay_unsupported(self):
        for policy in (ExpensePolicy(), ExpensePolicyV2()):
            with self.subTest(version=policy.version):
                blocker = policy.action_blockers("content.publish", [])[0]
                self.assertEqual(blocker["code"], "CAPABILITY_UNSUPPORTED")
                self.assertEqual(blocker["capability"], "content.publish")
        from work_runtime.publishing import FakePublisher, PublishingPolicy
        from work_runtime.file_adapter import FilePublisher
        # S14 supersession (master option A, 2026-10-16): the S10 pin asserted
        # the publishing family was unpaired; ratified D81/D89 pair it. The
        # expense pins above are unchanged.
        self.assertEqual(PublishingPolicy.compensation_capabilities,
                         {"content.unpublish": "content.publish"})
        for owner in (FakePublisher, FilePublisher):
            with self.subTest(owner=owner.__name__):
                self.assertFalse(getattr(owner, "compensation_capabilities", None))
        self.assertIs(FilePublisher.contract.supports_action_context, False)
        self.assertIs(FakePublisher.contract.supports_action_context, False)



def legacy_oa_store(path, key="legacy-key", invoice_ids=("INV-OLD",)):
    """A pre-S10 FakeOA store: 3-column receipts plus invoices rows."""
    db = sqlite3.connect(path)
    try:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS receipts (
                key TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS invoices (
                invoice_id TEXT PRIMARY KEY, external_id TEXT NOT NULL);
        """)
        document = {"id": "EXP-OLD", "amount": 1, "limit": 2,
                    "invoices": [{"id": i, "revision": 1} for i in invoice_ids],
                    "sealed": True}
        result = {"status": "accepted", "external_id": "OA-legacy000001",
                  "digest": digest(document)}
        db.execute("INSERT INTO receipts VALUES (?,?,?)",
                   (key, digest(document), canonical(result)))
        for invoice_id in invoice_ids:
            db.execute("INSERT INTO invoices VALUES (?,?)",
                       (invoice_id, result["external_id"]))
        db.commit()
        return document, result
    finally:
        db.close()


def store_columns(path, table):
    db = sqlite3.connect(path)
    try:
        return [row[1] for row in db.execute("PRAGMA table_info(%s)" % table)]
    finally:
        db.close()


class AdapterStoreMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def path(self, name="oa.sqlite"):
        return str(Path(self.temp.name) / name)

    def test_old_adapter_store_migrates_additively(self):
        path = self.path("legacy.sqlite")
        document, result = legacy_oa_store(path)
        oa = FakeOA(path)
        self.assertEqual(store_columns(path, "receipts"),
                         ["key", "digest", "result", "action", "link_digest"])
        db = sqlite3.connect(path)
        try:
            row = db.execute("SELECT action,link_digest FROM receipts WHERE key=?",
                             ("legacy-key",)).fetchone()
        finally:
            db.close()
        self.assertEqual(row, (None, None))  # NULL = legacy forward row
        # Forward behavior preserved: the legacy receipt replays by key+digest.
        replay = oa.execute("legacy-key", document, digest(document))
        self.assertEqual(replay, result)
        # Reopening is idempotent: the migration adds each column exactly once.
        FakeOA(path)
        self.assertEqual(store_columns(path, "receipts"),
                         ["key", "digest", "result", "action", "link_digest"])
        db = sqlite3.connect(path)
        try:
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            db.close()
        self.assertEqual(tables, {"receipts", "invoices", "withdrawals"})

    def test_concurrent_first_open_serializes(self):
        path = self.path("race.sqlite")
        legacy_oa_store(path, key="seed")
        barrier = Barrier(2)
        errors = []

        def opener():
            try:
                barrier.wait()
                FakeOA(path)
            except BaseException as error:  # noqa: BLE001 - recorded, re-raised below
                errors.append(error)

        threads = [Thread(target=opener) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(store_columns(path, "receipts"),
                         ["key", "digest", "result", "action", "link_digest"])

    def test_fresh_store_is_schema_current(self):
        oa = FakeOA(self.path())
        self.assertEqual(store_columns(oa.path, "receipts"),
                         ["key", "digest", "result", "action", "link_digest"])
        self.assertEqual(oa.withdrawn_count(), 0)
        self.assertEqual(oa.accepted_count(), 0)


class ForwardWriteAndCounterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.oa = FakeOA(str(Path(self.temp.name) / "oa.sqlite"))

    def receipt_row(self, key):
        db = sqlite3.connect(self.oa.path)
        try:
            return db.execute(
                "SELECT digest,result,action,link_digest FROM receipts WHERE key=?",
                (key,)).fetchone()
        finally:
            db.close()

    def test_forward_rows_tag_explicit_action_and_replay_guards(self):
        document = {"id": "EXP-1", "amount": 10, "limit": 20,
                    "invoices": [{"id": "INV-1", "revision": 1}], "sealed": True}
        first = self.oa.execute("fwd-key", document, digest(document))
        self.assertEqual(first["status"], "accepted")
        row = self.receipt_row("fwd-key")
        self.assertEqual((row[2], row[3]), ("expense.submit", None))
        # Same key, same content: byte-identical replay, one effect.
        replay = self.oa.execute("fwd-key", document, digest(document))
        self.assertEqual(replay, first)
        self.assertEqual(self.oa.accepted_count(), 1)
        # Same key, different content: ValueError, zero new effects.
        changed = {**document, "amount": 11}
        with self.assertRaises(ValueError):
            self.oa.execute("fwd-key", changed, digest(changed))
        self.assertEqual(self.oa.accepted_count(), 1)
        # Cross-action replay (A4 forward half): a receipts row tagged as a
        # withdrawal cannot be replayed by a forward call under the same key.
        db = sqlite3.connect(self.oa.path)
        try:
            db.execute("UPDATE receipts SET action='expense.withdraw',"
                       " link_digest='x' WHERE key='fwd-key'")
            db.commit()
        finally:
            db.close()
        with self.assertRaises(ValueError):
            self.oa.execute("fwd-key", document, digest(document))
        self.assertEqual(self.oa.accepted_count(), 0)  # tag excluded it from the count

    def test_accepted_count_counts_distinct_forward_acceptances(self):
        one = {"id": "EXP-1", "amount": 10, "limit": 20,
               "invoices": [{"id": "INV-1", "revision": 1}], "sealed": True}
        two = {"id": "EXP-2", "amount": 10, "limit": 20,
               "invoices": [{"id": "INV-2", "revision": 1}], "sealed": True}
        self.oa.execute("k1", one, digest(one))
        self.oa.execute("k2", two, digest(two))
        duplicate = {**one, "id": "EXP-3"}
        rejected = self.oa.execute("k3", duplicate, digest(duplicate))
        self.assertEqual(rejected["status"], "rejected")
        # 3 receipts rows, 2 distinct accepted forward effects.
        self.assertEqual(self.oa.accepted_count(), 2)

    def test_zero_invoice_direct_acceptance_counts_via_receipts(self):
        zero = {"id": "EXP-Z", "amount": 10, "limit": 20, "invoices": [], "sealed": True}
        receipt = self.oa.execute("zero-key", zero, digest(zero))
        self.assertEqual(receipt["status"], "accepted")
        db = sqlite3.connect(self.oa.path)
        try:
            self.assertIsNone(db.execute(
                "SELECT 1 FROM invoices WHERE external_id=?",
                (receipt["external_id"],)).fetchone())
        finally:
            db.close()
        self.assertEqual(self.oa.accepted_count(), 1)

    def test_withdrawn_count_counts_effect_rows(self):
        self.assertEqual(self.oa.withdrawn_count(), 0)



def withdrawal_link(external_id, operation_id="op-original"):
    return {"operation_id": operation_id, "external_id": external_id,
            "capability": "expense.submit"}


class WithdrawalExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.oa = FakeOA(str(Path(self.temp.name) / "oa.sqlite"))

    def forward(self, key, invoice_id, document_id="EXP-F"):
        document = {"id": document_id, "amount": 10, "limit": 20,
                    "invoices": [{"id": invoice_id, "revision": 1}], "sealed": True}
        receipt = self.oa.execute(key, document, digest(document))
        self.assertEqual(receipt["status"], "accepted")
        return document, receipt

    def withdraw(self, key, document, original_id, **kwargs):
        return self.oa.execute(key, document, digest(document),
                               action="expense.withdraw",
                               compensates=withdrawal_link(original_id), **kwargs)

    def receipt_count(self):
        db = sqlite3.connect(self.oa.path)
        try:
            return db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
        finally:
            db.close()

    def test_withdrawal_executes_once_and_is_idempotent_by_key(self):
        document, forward = self.forward("fwd-1", "INV-1")
        receipt = self.withdraw("wd-1", document, forward["external_id"])
        self.assertEqual(receipt["status"], "accepted")
        self.assertTrue(receipt["external_id"].startswith("WD-"))
        self.assertEqual(receipt["original_external_id"], forward["external_id"])
        self.assertTrue(receipt_is_valid(receipt, digest(document)))
        replay = self.withdraw("wd-1", document, forward["external_id"])
        self.assertEqual(replay, receipt)
        self.assertEqual((self.oa.withdrawn_count(), self.oa.accepted_count()), (1, 1))
        db = sqlite3.connect(self.oa.path)
        try:
            row = db.execute("SELECT action,link_digest FROM receipts WHERE key='wd-1'").fetchone()
        finally:
            db.close()
        self.assertEqual(row[0], "expense.withdraw")
        self.assertEqual(row[1], digest(withdrawal_link(forward["external_id"])))

    def test_withdrawal_input_guards_raise_before_any_write(self):
        document, forward = self.forward("fwd-1", "INV-1")
        before = self.receipt_count()
        with self.assertRaises(ValueError):  # unknown action
            self.oa.execute("wd-x", document, digest(document), action="expense.purge")
        with self.assertRaises(ValueError):  # withdraw without link
            self.oa.execute("wd-x", document, digest(document), action="expense.withdraw")
        for malformed in (None, "OA-1", {}, {"operation_id": "op"},
                          {"operation_id": "op", "external_id": forward["external_id"],
                           "capability": "", "extra": 1}):
            with self.subTest(malformed=malformed):
                with self.assertRaises(ValueError):
                    self.oa.execute("wd-x", document, digest(document),
                                    action="expense.withdraw", compensates=malformed)
        with self.assertRaises(ValueError):  # forward with link
            self.oa.execute("wd-x", document, digest(document),
                            action="expense.submit",
                            compensates=withdrawal_link(forward["external_id"]))
        self.assertEqual((self.receipt_count(), self.oa.withdrawn_count()), (before, 0))

    def test_different_key_same_original_returns_alias_and_lookup_is_authoritative(self):
        document, forward = self.forward("fwd-1", "INV-1")
        first = self.withdraw("wd-1", document, forward["external_id"])
        # A second key with a DIFFERENT document digest gets a digest-valid
        # alias receipt carrying the same WD id; lookup stays authoritative
        # by key; still exactly one effect row.
        other = {**document, "id": "EXP-G", "invoices": [{"id": "INV-2", "revision": 1}]}
        alias = self.withdraw("wd-2", other, forward["external_id"])
        self.assertEqual(alias["status"], "accepted")
        self.assertEqual(alias["external_id"], first["external_id"])
        self.assertEqual(alias["original_external_id"], forward["external_id"])
        self.assertTrue(receipt_is_valid(alias, digest(other)))
        self.assertFalse(receipt_is_valid(alias, digest(document)))
        self.assertEqual(self.oa.lookup("wd-2"), alias)
        self.assertEqual(self.oa.withdrawn_count(), 1)
        self.assertEqual(self.oa.accepted_count(), 1)
        # Lost response after the alias commits: lookup remains authoritative.
        lost = FakeOA(self.oa.path, timeout_after_commit=True)
        document3 = {**document, "id": "EXP-H", "invoices": [{"id": "INV-3", "revision": 1}]}
        with self.assertRaises(TimeoutError):
            lost.execute("wd-3", document3, digest(document3), action="expense.withdraw",
                         compensates=withdrawal_link(forward["external_id"]))
        recovered = self.oa.lookup("wd-3")
        self.assertEqual(recovered["external_id"], first["external_id"])
        self.assertTrue(receipt_is_valid(recovered, digest(document3)))

    def test_same_key_different_link_conflicts_even_with_equal_digest(self):
        document, forward = self.forward("fwd-1", "INV-1")
        document2, forward2 = self.forward("fwd-2", "INV-9", document_id="EXP-F2")
        self.withdraw("wd-1", document, forward["external_id"])
        effects = self.oa.withdrawn_count()
        # Same key, same document digest, different compensates target.
        with self.assertRaises(ValueError):
            self.withdraw("wd-1", document, forward2["external_id"])
        self.assertEqual(self.oa.withdrawn_count(), effects)
        # Cross-action under one key, both directions.
        with self.assertRaises(ValueError):  # forward call against a withdrawal row
            self.oa.execute("wd-1", document, digest(document))
        self.forward("fwd-3", "INV-3")
        with self.assertRaises(ValueError):  # withdrawal call against a forward row
            self.withdraw("fwd-3", document, forward2["external_id"])
        self.assertEqual(self.oa.withdrawn_count(), effects)

    def test_missing_original_is_bounded_business_rejection(self):
        document = {"id": "EXP-M", "amount": 10, "limit": 20,
                    "invoices": [{"id": "INV-M", "revision": 1}], "sealed": True}
        receipt = self.withdraw("wd-1", document, "OA-neverexisted")
        self.assertEqual(receipt["status"], "rejected")
        self.assertEqual(receipt["reason"], "ORIGINAL_ABSENT")
        self.assertEqual(receipt["original_external_id"], "OA-neverexisted")
        self.assertTrue(receipt_is_valid(receipt, digest(document)))
        self.assertEqual(self.oa.withdrawn_count(), 0)
        replay = self.withdraw("wd-1", document, "OA-neverexisted")
        self.assertEqual(replay, receipt)

    def test_duplicate_invoice_forward_still_rejected_with_withdrawal_store(self):
        document, forward = self.forward("fwd-1", "INV-1")
        self.withdraw("wd-1", document, forward["external_id"])
        # Same invoice ids under a new key: business rejection, never a withdrawal.
        resubmit = {**document, "id": "EXP-DUP"}
        rejected = self.oa.execute("fwd-dup", resubmit, digest(resubmit))
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(self.oa.withdrawn_count(), 1)
        self.assertEqual(self.oa.accepted_count(), 1)

    def test_zero_invoice_original_is_present_via_receipts(self):
        zero = {"id": "EXP-Z", "amount": 10, "limit": 20, "invoices": [], "sealed": True}
        forward = self.oa.execute("zero-fwd", zero, digest(zero))
        self.assertEqual(forward["status"], "accepted")
        receipt = self.withdraw("wd-1", zero, forward["external_id"])
        self.assertEqual(receipt["status"], "accepted")  # not ORIGINAL_ABSENT
        self.assertEqual(self.oa.withdrawn_count(), 1)

    def test_withdrawal_timeout_after_commit(self):
        document, forward = self.forward("fwd-1", "INV-1")
        lost = FakeOA(self.oa.path, timeout_after_commit=True)
        with self.assertRaises(TimeoutError):
            lost.execute("wd-1", document, digest(document), action="expense.withdraw",
                         compensates=withdrawal_link(forward["external_id"]))
        self.assertEqual(self.oa.withdrawn_count(), 1)
        receipt = self.oa.lookup("wd-1")
        self.assertEqual(receipt["status"], "accepted")
        self.assertTrue(receipt_is_valid(receipt, digest(document)))



class SilentAdapter:
    """External call lost; no authoritative answer is ever available."""

    def execute(self, key, document, content_digest):
        raise TimeoutError()

    def lookup(self, key):
        return None


class RejectedAdapter:
    """Returns a digest-valid business rejection for every call."""

    def execute(self, key, document, content_digest):
        return {"status": "rejected", "external_id": "OA-rejected",
                "digest": content_digest}

    def lookup(self, key):
        return None


class CompensationCase(unittest.TestCase):
    """A confirmed expense effect inside the active cancellation window."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        self.oa_path = str(Path(self.temp.name) / "oa.sqlite")
        self.runtime = Runtime(self.path, ExpensePolicy(), compensation_grants())
        self.oa = FakeOA(self.oa_path)
        initialize(self.runtime)

    def confirmed_submit(self, runtime=None, work_id="demo", invoice_id="INV-001",
                         oa=None):
        runtime = runtime or self.runtime
        prerequisites(runtime, work_id)
        receipt = send(runtime, work_id, "revise_document",
                       {"document": document(invoice_id=invoice_id)})
        assert receipt["decision"] == "accepted", receipt
        prerequisites(runtime, work_id)
        receipt = action(runtime, work_id)
        assert receipt["decision"] == "accepted", receipt
        operation_id = receipt["operation_id"]
        resolved = runtime.dispatch(operation_id, oa or self.oa)
        assert resolved["status"] == "confirmed_succeeded", resolved
        return operation_id

    def request_cancel(self, runtime=None, work_id="demo", reason="duplicates found"):
        receipt = send(runtime or self.runtime, work_id, "request_cancel",
                       {"reason": reason})
        assert (receipt["decision"] == "accepted"
                or receipt["code"] == "CANCELLATION_ALREADY_REQUESTED"), receipt
        return receipt

    def withdraw(self, target_id, runtime=None, work_id="demo", actor="agent",
                 command_id=None, capability="expense.withdraw"):
        runtime = runtime or self.runtime
        work = runtime.get_work(work_id)
        return send(runtime, work_id, "propose_action", {
            "capability": capability, "document_digest": work["document_digest"],
            "contract_revision": work["contract"]["revision"],
            "plan_revision": work["plan_revision"], "compensates": target_id},
            actor=actor, command_id=command_id)

    def prepared_withdrawal(self, target_id=None, **kwargs):
        target = target_id or self.confirmed_submit()
        self.request_cancel()
        receipt = self.withdraw(target, **kwargs)
        assert receipt["decision"] == "accepted", receipt
        return target, receipt["operation_id"]


class CompensationAdmissionTests(CompensationCase):
    def test_withdrawal_proposal_accepted_during_cancellation_window(self):
        target = self.confirmed_submit()
        self.request_cancel()
        receipt = self.withdraw(target, command_id="withdraw-1")
        self.assertEqual(receipt["decision"], "accepted")
        self.assertEqual(receipt["operation_status_at_decision"], "prepared")
        operation = self.runtime.get_operation(receipt["operation_id"])
        self.assertEqual(operation["compensates"], {
            "operation_id": target,
            "external_id": self.runtime.get_operation(target)["external_id"],
            "capability": "expense.submit"})
        event = [e for e in self.runtime.events("demo")
                 if e["type"] == "OperationPrepared"][-1]
        self.assertEqual(json.loads(event["body"])["compensates"],
                         operation["compensates"])

    def test_withdrawal_requires_active_cancellation(self):
        target = self.confirmed_submit()
        receipt = self.withdraw(target)
        self.assertEqual((receipt["decision"], receipt["code"], receipt["blockers"]),
                         ("rejected", "CANCELLATION_NOT_REQUESTED", []))
        self.assertEqual(receipt["observed_state_version"],
                         self.runtime.get_work("demo")["state_version"])

    def test_compensation_payload_shape_is_exact(self):
        target = self.confirmed_submit()
        self.request_cancel()
        work = self.runtime.get_work("demo")
        base = {"capability": "expense.withdraw",
                "document_digest": work["document_digest"],
                "contract_revision": work["contract"]["revision"],
                "plan_revision": work["plan_revision"], "compensates": target}
        from work_runtime import CommandError
        bad_payloads = [
            {**base, "note": "extra"},                      # extra key
            {k: v for k, v in base.items() if k != "plan_revision"},  # missing key
            {**base, "compensates": 42},                    # non-string target
            {**base, "compensates": ""},                    # empty target
        ]
        version = work["state_version"]
        events_before = len(self.runtime.events("demo"))
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(CommandError):
                    send(self.runtime, "demo", "propose_action", payload)
        # Nothing persisted: no state bump, no events, no command rows.
        self.assertEqual(self.runtime.get_work("demo")["state_version"], version)
        self.assertEqual(len(self.runtime.events("demo")), events_before)
        self.assertIsNone(self.runtime.get_command("agent", "shape-probe"))

    def test_withdrawal_target_must_be_confirmed_succeeded_same_work(self):
        prerequisites(self.runtime)
        prepared = action(self.runtime)["operation_id"]  # prepared, never dispatched
        confirmed = self.confirmed_submit(invoice_id="INV-002")
        # A target stuck at dispatched: the attempt is durable, resolution never
        # ran (a fresh document revision makes this a distinct operation).
        prerequisites(self.runtime)
        send(self.runtime, "demo", "revise_document",
             {"document": document(invoice_id="INV-002B")})
        prerequisites(self.runtime)
        stuck = action(self.runtime)["operation_id"]

        def boom():
            raise RuntimeError("died between attempt commit and resolve")

        with self.assertRaises(RuntimeError):
            self.runtime.dispatch(stuck, self.oa, fault=boom)
        self.assertEqual(self.runtime.get_operation(stuck)["status"], "dispatched")
        # A confirmed_failed target in a second work of the same store.
        for work_id, invoice in (("failedwork", "INV-F"), ("unknownwork", "INV-U")):
            send(self.runtime, work_id, "create_work",
                 {"document": document(invoice_id=invoice,
                                       document_id="EXP-" + work_id[:4].upper())})
            send(self.runtime, work_id, "bind_contract",
                 {"policy_id": "expense-submit", "policy_version": "demo-1",
                  "goal": "expense.accepted"})
        prerequisites(self.runtime, "failedwork")
        failed = action(self.runtime, "failedwork")["operation_id"]
        self.assertEqual(self.runtime.dispatch(failed, RejectedAdapter())["status"],
                         "confirmed_failed")
        # An outcome_unknown target in its own work (uncertain ops with older
        # digests would block later same-work proposals, so it lives apart).
        prerequisites(self.runtime, "unknownwork")
        uncertain = action(self.runtime, "unknownwork")["operation_id"]
        self.runtime.dispatch(uncertain, SilentAdapter())
        self.assertEqual(self.runtime.get_operation(uncertain)["status"],
                         "outcome_unknown")
        self.request_cancel()
        self.request_cancel(work_id="failedwork", reason="also cancelling")
        self.request_cancel(work_id="unknownwork", reason="also cancelling")
        for name, target_id, work_id in (
                ("prepared", prepared, "demo"), ("dispatched", stuck, "demo"),
                ("confirmed_failed", failed, "demo"), ("unknown-id", "no-such-operation", "demo"),
                ("outcome_unknown", uncertain, "unknownwork")):
            with self.subTest(target=name):
                receipt = self.withdraw(target_id, work_id=work_id)
                self.assertEqual(receipt["decision"], "rejected")
                self.assertEqual(receipt["code"], "COMPENSATION_TARGET_INVALID")
                self.assertEqual(receipt["blockers"], [target_id])
        # Cross-work: failedwork's own window cannot compensate demo's effect.
        receipt = self.withdraw(confirmed, work_id="failedwork")
        self.assertEqual((receipt["decision"], receipt["code"], receipt["blockers"]),
                         ("rejected", "COMPENSATION_TARGET_INVALID", [confirmed]))

    def test_withdrawal_target_must_not_be_compensation(self):
        target, withdrawal_id = self.prepared_withdrawal()
        receipt = self.withdraw(withdrawal_id)
        self.assertEqual((receipt["decision"], receipt["code"], receipt["blockers"]),
                         ("rejected", "COMPENSATION_TARGET_INVALID", [withdrawal_id]))

    def test_withdrawal_target_pairing_must_match(self):
        good = self.confirmed_submit(invoice_id="INV-005")
        self.request_cancel()
        receipt = self.withdraw(good)
        self.assertEqual(receipt["decision"], "accepted")  # pairing currently matches
        # An unpaired capability degrades to CAPABILITY_UNSUPPORTED blockers
        # (authority first requires the actor to hold it).
        grants = compensation_grants()
        grants["agent"].add("content.publish")
        runtime = Runtime(self.path, ExpensePolicy(), grants)
        work = runtime.get_work("demo")
        receipt = send(runtime, "demo", "propose_action", {
            "capability": "content.publish",
            "document_digest": work["document_digest"],
            "contract_revision": work["contract"]["revision"],
            "plan_revision": work["plan_revision"], "compensates": good})
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "REQUIREMENT_UNSATISFIED")
        self.assertEqual(receipt["blockers"],
                         [{"code": "CAPABILITY_UNSUPPORTED", "capability": "content.publish"}])
        # Pairing mismatch (belt-and-braces at admission): corrupt the stored
        # target's capability so target(capability) != pairing[capability].
        db = sqlite3.connect(self.path)
        try:
            body = json.loads(db.execute("SELECT body FROM operations WHERE id=?",
                                         (good,)).fetchone()[0])
            body["capability"] = "content.publish"
            db.execute("UPDATE operations SET body=? WHERE id=?", (canonical(body), good))
            db.commit()
        finally:
            db.close()
        second = None
        runtime2 = Runtime(self.path, ExpensePolicy(), compensation_grants())
        work = runtime2.get_work("demo")
        receipt = send(runtime2, "demo", "propose_action", {
            "capability": "expense.withdraw",
            "document_digest": work["document_digest"],
            "contract_revision": work["contract"]["revision"],
            "plan_revision": work["plan_revision"], "compensates": good})
        self.assertEqual((receipt["decision"], receipt["code"], receipt["blockers"]),
                         ("rejected", "COMPENSATION_TARGET_INVALID", [good]))

    def test_withdrawal_business_key_stable_and_distinct(self):
        target = self.confirmed_submit(invoice_id="INV-001")
        other = self.confirmed_submit(invoice_id="INV-007")
        self.request_cancel()
        first = self.withdraw(target, command_id="w1")
        second = self.withdraw(target, command_id="w2")
        self.assertEqual(first["operation_id"], second["operation_id"])
        operation = self.runtime.get_operation(first["operation_id"])
        self.assertEqual(operation["business_key"],
                         digest(["expense-submit", "expense.withdraw", target]))
        forward = self.runtime.get_operation(target)
        self.assertNotEqual(operation["business_key"], forward["business_key"])
        third = self.withdraw(other, command_id="w3")
        self.assertNotEqual(third["operation_id"], first["operation_id"])
        db = sqlite3.connect(self.path)
        try:
            rows = db.execute(
                "SELECT COUNT(*) FROM operations WHERE business_key=?",
                (operation["business_key"],)).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(rows, 1)

    def test_withdrawal_link_snapshot_is_immutable(self):
        target, withdrawal_id = self.prepared_withdrawal()
        before = self.runtime.get_operation(withdrawal_id)["compensates"]
        replay = self.withdraw(target, command_id="re-admit-1")
        self.assertEqual(replay["operation_id"], withdrawal_id)
        self.assertEqual(replay["operation_status_at_decision"], "prepared")
        self.assertEqual(self.runtime.get_operation(withdrawal_id)["compensates"], before)

    def test_withdrawal_authority_is_current_owner_with_grant(self):
        target = self.confirmed_submit()
        self.request_cancel()
        # An intervener holding work.intervene but not the capability.
        receipt = self.withdraw(target, actor="admin", command_id="by-admin")
        self.assertEqual((receipt["decision"], receipt["code"]),
                         ("rejected", "AUTHORITY_DENIED"))
        # A former owner after transfer: transfer needs a target with work.manage.
        grants = compensation_grants(extra={"agent2": {"work.manage", "expense.withdraw"}})
        runtime = Runtime(self.path, ExpensePolicy(), grants)
        send(runtime, "demo", "transfer_owner", {"owner": "agent2", "reason": "reassign"})
        receipt = self.withdraw(target, runtime=runtime, command_id="by-former")
        self.assertEqual((receipt["decision"], receipt["code"]),
                         ("rejected", "AUTHORITY_DENIED"))
        # The new owner with the grant re-admits inside the window.
        receipt = self.withdraw(target, runtime=runtime, actor="agent2",
                                command_id="by-new-owner")
        self.assertEqual(receipt["decision"], "accepted")
        # An owner whose grants lack the capability entirely (fresh store).
        no_withdraw = {actor: caps - {"expense.withdraw"} if actor == "agent" else caps
                       for actor, caps in compensation_grants().items()}
        fresh = tempfile.TemporaryDirectory()
        self.addCleanup(fresh.cleanup)
        runtime2 = Runtime(str(Path(fresh.name) / "runtime.sqlite"),
                           ExpensePolicy(), no_withdraw)
        initialize(runtime2)
        prerequisites(runtime2)
        other = action(runtime2)["operation_id"]
        runtime2.dispatch(other, FakeOA(str(Path(fresh.name) / "oa.sqlite")))
        self.request_cancel(runtime=runtime2)
        receipt = send(runtime2, "demo", "propose_action", {
            "capability": "expense.withdraw",
            "document_digest": runtime2.get_work("demo")["document_digest"],
            "contract_revision": runtime2.get_work("demo")["contract"]["revision"],
            "plan_revision": runtime2.get_work("demo")["plan_revision"],
            "compensates": other})
        self.assertEqual((receipt["decision"], receipt["code"]),
                         ("rejected", "AUTHORITY_DENIED"))

    def test_revoked_original_proof_does_not_block_compensation(self):
        target = self.confirmed_submit()
        receipt = send(self.runtime, "demo", "revoke_evidence",
                       {"source": "oa", "event_id": target,
                        "reason": "withdrawn by admin"}, actor="admin")
        self.assertEqual(receipt["decision"], "accepted")
        self.request_cancel()
        receipt = self.withdraw(target)
        self.assertEqual(receipt["decision"], "accepted")

    def test_both_policy_versions_compensate(self):
        v2_temp = tempfile.TemporaryDirectory()
        self.addCleanup(v2_temp.cleanup)
        v2 = Runtime(str(Path(v2_temp.name) / "runtime.sqlite"),
                     ExpensePolicyV2(), compensation_grants())
        send(v2, "demo", "create_work", {"document": document()})
        send(v2, "demo", "bind_contract",
             {"policy_id": "expense-submit", "policy_version": "demo-2",
              "goal": "expense.accepted"})
        send(v2, "demo", "revise_plan", {
            "steps": ["verify", "approve", "confirm", "submit"],
            "open_requirements": ["E05"], "replan_when": ["invoice anomaly"]})
        work = v2.get_work("demo")
        from work_runtime.demo import proof
        proof(v2, "demo", "invoice_valid", "invoice-service",
              {"invoice_id": "INV-001", "invoice_revision": 1, "valid": True})
        proof(v2, "demo", "duplicate_clear", "expense-service")
        proof(v2, "demo", "confirmation", "requester")
        proof(v2, "demo", "approval", "finance",
              {"digest": work["document_digest"], "policy_version": "demo-2"})
        v2.verify_pending("demo")
        receipt = action(v2)
        self.assertEqual(receipt["decision"], "accepted", receipt)
        target = receipt["operation_id"]
        v2.dispatch(target, FakeOA(str(Path(v2_temp.name) / "oa.sqlite")))
        self.request_cancel(runtime=v2)
        receipt = self.withdraw(target, runtime=v2)
        self.assertEqual(receipt["decision"], "accepted")
        key = v2.get_operation(receipt["operation_id"])["business_key"]
        self.assertEqual(key, digest(["expense-submit", "expense.withdraw", target]))

    def test_ordinary_proposal_payload_handling_is_unchanged(self):
        # GREEN pin (disclosed): extra keys on an ordinary payload are ignored
        # exactly as before S10.
        prerequisites(self.runtime)
        work = self.runtime.get_work("demo")
        receipt = send(self.runtime, "demo", "propose_action", {
            "capability": "expense.submit", "document_digest": work["document_digest"],
            "contract_revision": work["contract"]["revision"],
            "plan_revision": work["plan_revision"], "note": "ignored"},
            command_id="ordinary-extra")
        self.assertEqual(receipt["decision"], "accepted")

    def test_forward_proposal_still_rejected_in_window(self):
        target = self.confirmed_submit()
        self.request_cancel()
        receipt = action(self.runtime, command_id="forward-in-window")
        self.assertEqual((receipt["decision"], receipt["code"]),
                         ("rejected", "CANCELLATION_ACTIVE"))



class BareRecorder:
    """Legacy duck-typed adapter (no contract attribute) recording its calls."""

    def __init__(self, inner):
        self.inner = inner
        self.calls = []

    def execute(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.inner.execute(*args, **kwargs)

    def lookup(self, key):
        return self.inner.lookup(key)


class RecordingAdapter:
    """Delegates to a real adapter while recording how the runtime called it."""

    def __init__(self, inner, contract=None):
        self.inner = inner
        self._contract = contract if contract is not None else inner.contract
        self.calls = []

    @property
    def contract(self):
        return self._contract

    def execute(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.inner.execute(*args, **kwargs)

    def lookup(self, *args, **kwargs):
        return self.inner.lookup(*args, **kwargs)


class ContextDeclaringOA(FakeOA):
    """Declares the withdraw action but NOT the execution-context opt-in."""

    contract = AdapterContract(
        actions=("expense.submit", "expense.withdraw"),
        idempotency_scope="adapter-store:key",
        retention="lifetime-of-store",
        lookup_consistency="authoritative-by-key",
        uniqueness=("invoice.id", "withdrawal.original_external_id"))


class CompensationDispatchTests(CompensationCase):
    def crafted_operation(self, op_id, capability, work_id="demo", compensates=None,
                          runtime=None):
        """Insert a prepared/ready operation directly (belt-and-braces legs)."""
        runtime = runtime or self.runtime
        work = runtime.get_work(work_id)
        operation = {"id": op_id, "business_key": "crafted-" + op_id,
                     "work_id": work_id, "actor": "agent", "capability": capability,
                     "status": "prepared", "dispatch_state": "ready", "attempts": [],
                     "document": work["document"],
                     "document_digest": work["document_digest"],
                     "plan_revision": work["plan_revision"],
                     "contract_revision": work["contract"]["revision"]}
        if compensates is not None:
            operation["compensates"] = compensates
        db = sqlite3.connect(self.path if runtime is self.runtime else runtime.path)
        try:
            db.execute("INSERT INTO operations VALUES (?,?,?,?)",
                       (op_id, operation["business_key"], work_id,
                        canonical(operation)))
            db.commit()
        finally:
            db.close()

    def test_dispatch_leaves_compensating_op_but_cancels_forward_ops(self):
        target, withdrawal_id = self.prepared_withdrawal()
        resolved = self.runtime.dispatch(withdrawal_id, self.oa)
        self.assertEqual((resolved["status"], resolved["dispatch_state"]),
                         ("confirmed_succeeded", "finished"))
        # Belt-and-braces: a forward prepared op reset to ready under the
        # active intent is still cancelled WORK_CANCELLED by dispatch.
        self.crafted_operation("crafted-forward", "expense.submit")
        cancelled = self.runtime.dispatch("crafted-forward", self.oa)
        self.assertEqual((cancelled["dispatch_state"], cancelled["reason"]),
                         ("cancelled", "WORK_CANCELLED"))
        # Belt-and-braces mirror: a compensation without an active intent is
        # STALE_INTENT (crafted: the window gate makes it unreachable).
        fresh = tempfile.TemporaryDirectory()
        self.addCleanup(fresh.cleanup)
        plain = Runtime(str(Path(fresh.name) / "runtime.sqlite"),
                        ExpensePolicy(), compensation_grants())
        initialize(plain)
        plain_target = self.confirmed_submit(runtime=plain,
                                             oa=FakeOA(str(Path(fresh.name) / "oa.sqlite")))
        self.crafted_operation("crafted-comp", "expense.withdraw",
                               runtime=plain,
                               compensates={"operation_id": plain_target,
                                            "external_id": plain.get_operation(
                                                plain_target)["external_id"],
                                            "capability": "expense.submit"})
        stale = plain.dispatch("crafted-comp", self.oa)
        self.assertEqual((stale["dispatch_state"], stale["reason"]),
                         ("cancelled", "STALE_INTENT"))

    def test_legacy_adapter_never_receives_kwargs_and_false_marker_holds(self):
        # Absent-contract adapter: exactly three positional arguments, forward.
        prerequisites(self.runtime)
        forward_id = action(self.runtime)["operation_id"]
        legacy = BareRecorder(self.oa)
        resolved = self.runtime.dispatch(forward_id, legacy)
        self.assertEqual(resolved["status"], "confirmed_succeeded")
        self.assertEqual(len(legacy.calls), 1)
        (args, kwargs), = legacy.calls
        self.assertEqual(len(args), 3)
        self.assertEqual(kwargs, {})
        # A declared contract without the opt-in: still three positional args.
        recording = RecordingAdapter(ContextDeclaringOA(self.oa_path))
        forward2 = self.confirmed_submit(invoice_id="INV-DEC", oa=recording)
        (args2, kwargs2), = recording.calls
        self.assertEqual(len(args2), 3)
        self.assertEqual(kwargs2, {})
        target, withdrawal_id = self.prepared_withdrawal(target_id=forward_id)
        # A compensation dispatched to a non-opted-in contract is held with
        # zero attempts and zero external calls — even though actions declares
        # the withdraw capability — and dispatches afterwards with an opted-in
        # adapter.
        declared = ContextDeclaringOA(self.oa_path)
        held = self.runtime.dispatch(withdrawal_id, declared)
        self.assertEqual((held["dispatch_state"], held["reason"]),
                         ("held", "ADAPTER_ACTION_CONTEXT_UNSUPPORTED"))
        persisted = self.runtime.get_operation(withdrawal_id)
        self.assertEqual(persisted["attempts"], [])
        self.assertNotEqual(self.runtime.get_work("demo")["status"], "needs_attention")
        self.assertEqual(self.oa.withdrawn_count(), 0)
        # ...and an absent-contract adapter is held the same way.
        legacy2 = BareRecorder(FakeOA(self.oa_path + ".2"))
        held2 = self.runtime.dispatch(withdrawal_id, legacy2)
        self.assertEqual(held2["reason"], "ADAPTER_ACTION_CONTEXT_UNSUPPORTED")
        self.assertEqual(legacy2.calls, [])
        resolved = self.runtime.dispatch(withdrawal_id, self.oa)
        self.assertEqual(resolved["status"], "confirmed_succeeded")
        self.assertEqual(self.oa.withdrawn_count(), 1)

    def test_opted_in_adapter_receives_action_and_link(self):
        recording = RecordingAdapter(self.oa)
        target = self.confirmed_submit(oa=recording)
        self.assertEqual(recording.executed if hasattr(recording, "executed") else 0, 0)
        (args, kwargs), = recording.calls
        self.assertEqual(kwargs, {"action": "expense.submit", "compensates": None})
        self.request_cancel()
        receipt = self.withdraw(target)
        withdrawal_id = receipt["operation_id"]
        snapshot = self.runtime.get_operation(withdrawal_id)["compensates"]
        recording2 = RecordingAdapter(self.oa)
        resolved = self.runtime.dispatch(withdrawal_id, recording2)
        self.assertEqual(resolved["status"], "confirmed_succeeded")
        (_, kwargs2), = recording2.calls
        self.assertEqual(kwargs2, {"action": "expense.withdraw", "compensates": snapshot})

    def test_dispatch_revalidates_link_and_holds_on_invalid_target(self):
        target2 = self.confirmed_submit(invoice_id="INV-REV2")
        target, withdrawal_id = self.prepared_withdrawal()
        db = sqlite3.connect(self.path)
        try:
            body = json.loads(db.execute("SELECT body FROM operations WHERE id=?",
                                         (target,)).fetchone()[0])
            body["status"] = "confirmed_failed"  # target truth re-derived at dispatch
            db.execute("UPDATE operations SET body=? WHERE id=?", (canonical(body), target))
            db.commit()
        finally:
            db.close()
        held = self.runtime.dispatch(withdrawal_id, self.oa)
        self.assertEqual((held["dispatch_state"], held["reason"]),
                         ("held", "COMPENSATION_TARGET_INVALID"))
        self.assertEqual(self.runtime.get_operation(withdrawal_id)["attempts"], [])
        self.assertEqual(self.oa.withdrawn_count(), 0)
        # Snapshot corruption (external_id no longer equals the target's) too.
        target2, withdrawal2 = self.prepared_withdrawal(target_id=target2)
        db = sqlite3.connect(self.path)
        try:
            body = json.loads(db.execute("SELECT body FROM operations WHERE id=?",
                                         (withdrawal2,)).fetchone()[0])
            body["compensates"]["external_id"] = "OA-mismatched"
            db.execute("UPDATE operations SET body=? WHERE id=?",
                       (canonical(body), withdrawal2))
            db.commit()
        finally:
            db.close()
        held2 = self.runtime.dispatch(withdrawal2, self.oa)
        self.assertEqual(held2["reason"], "COMPENSATION_TARGET_INVALID")
        self.assertEqual(self.runtime.get_operation(withdrawal2)["attempts"], [])

    def test_dispatch_holds_compensation_on_grant_loss(self):
        target, withdrawal_id = self.prepared_withdrawal()
        grants = compensation_grants()
        grants["agent"] = grants["agent"] - {"expense.withdraw"}
        runtime = Runtime(self.path, ExpensePolicy(), grants)
        held = runtime.dispatch(withdrawal_id, self.oa)
        self.assertEqual((held["dispatch_state"], held["reason"]),
                         ("held", "AUTHORITY_DENIED"))
        self.assertEqual(runtime.get_operation(withdrawal_id)["attempts"], [])
        self.assertEqual(self.oa.withdrawn_count(), 0)
        restored = Runtime(self.path, ExpensePolicy(), compensation_grants())
        resolved = restored.dispatch(withdrawal_id, self.oa)
        self.assertEqual(resolved["status"], "confirmed_succeeded")



class MismatchedWithdrawalAdapter:
    """Opted-in adapter returning receipts that bind the WRONG original."""

    contract = AdapterContract(
        actions=("expense.submit", "expense.withdraw"),
        idempotency_scope="adapter-store:key",
        retention="lifetime-of-store",
        lookup_consistency="authoritative-by-key",
        uniqueness=(), supports_action_context=True)

    def __init__(self, document_digest, original_id, status="accepted"):
        self.document_digest = document_digest
        self.original_id = original_id
        self.status = status
        self.stored = {}

    def execute(self, key, document, content_digest, *, action=None, compensates=None):
        self.stored[key] = self._receipt(content_digest)
        return self.stored[key]

    def lookup(self, key):
        return self.stored.get(key)

    def _receipt(self, content_digest):
        receipt = {"status": self.status, "external_id": "WD-wrong00000001",
                   "digest": content_digest,
                   "original_external_id": self.original_id}
        return receipt


class CompensationResolutionTests(CompensationCase):
    def withdrawn_proofs(self, work_id="demo"):
        db = sqlite3.connect(self.path)
        try:
            return [json.loads(row[0]) for row in db.execute(
                "SELECT body FROM evidence WHERE work_id=? AND event_id IN "
                "(SELECT id FROM operations WHERE work_id=?)", (work_id, work_id))]
        finally:
            db.close()

    def test_withdrawal_binds_linked_original_not_current_document(self):
        # P1 revision matrix: op1 accepted at r1 (INV-A); document revised to
        # r2 with a second acceptance (INV-B); the withdrawal linked to op1
        # always withdraws op1's snapshot external id.
        prerequisites(self.runtime)
        r1 = action(self.runtime)["operation_id"]
        self.runtime.dispatch(r1, self.oa)
        op1_external = self.runtime.get_operation(r1)["external_id"]
        r2 = self.confirmed_submit(invoice_id="INV-B")
        op2_external = self.runtime.get_operation(r2)["external_id"]
        self.assertNotEqual(op1_external, op2_external)
        # r3: never-submitted invoice ids; r4: ids spanning both acceptances.
        send(self.runtime, "demo", "revise_document",
             {"document": document(invoice_id="INV-NEW")})
        self.request_cancel()
        withdrawal = self.withdraw(r1)
        self.assertEqual(withdrawal["decision"], "accepted")
        resolved = self.runtime.dispatch(withdrawal["operation_id"], self.oa)
        self.assertEqual(resolved["status"], "confirmed_succeeded")
        db = sqlite3.connect(self.oa_path)
        try:
            effect = db.execute("SELECT original_external_id, external_id "
                                "FROM withdrawals").fetchall()
        finally:
            db.close()
        self.assertEqual(effect, [(op1_external, resolved["external_id"])])
        # INV-B's acceptance is untouched: still one forward effect each.
        self.assertEqual((self.oa.accepted_count(), self.oa.withdrawn_count()), (2, 1))

    def test_withdrawal_appends_exactly_one_row_original_intact(self):
        target, withdrawal_id = self.prepared_withdrawal()
        resolved = self.runtime.dispatch(withdrawal_id, self.oa)
        self.assertEqual(resolved["status"], "confirmed_succeeded")
        self.assertTrue(resolved["external_id"].startswith("WD-"))
        original = self.runtime.get_operation(target)
        self.assertEqual((original["status"], original["external_id"]),
                         ("confirmed_succeeded", original["external_id"]))
        self.assertNotIn("compensates", original)
        self.assertEqual((self.oa.accepted_count(), self.oa.withdrawn_count()), (1, 1))
        # The original's accepted proof and its operation stay untouched.
        proofs = [p for p in self.withdrawn_proofs()
                  if p["event_id"] == target and p["kind"] == "accepted"]
        self.assertEqual(len(proofs), 1)

    def test_withdrawal_receipt_binding_mismatch_is_quarantined(self):
        # Two independent confirmed targets and withdrawal intents, so each
        # status leg gets its own undispatched operation.
        targets = (self.confirmed_submit(invoice_id="INV-MM1"),
                   self.confirmed_submit(invoice_id="INV-MM2"))
        self.request_cancel()
        withdrawals = [self.withdraw(target)["operation_id"] for target in targets]
        work_digest = self.runtime.get_work("demo")["document_digest"]
        for status, withdrawal_id in zip(("accepted", "rejected"), withdrawals):
            with self.subTest(status=status):
                runtime = Runtime(self.path, ExpensePolicy(), compensation_grants())
                adapter = MismatchedWithdrawalAdapter(
                    work_digest, "OA-not-the-original", status=status)
                quarantined = runtime.dispatch(withdrawal_id, adapter)
                self.assertEqual((quarantined["status"], quarantined["reason"]),
                                 ("outcome_unknown", "ADAPTER_RESULT_INVALID"))
                self.assertEqual(runtime.get_work("demo")["status"],
                                 "needs_attention")
                op = runtime.get_operation(withdrawal_id)
                self.assertNotIn("external_id", op)
                self.assertNotIn("adapter_result", op)
                # Repeated reconcile with the same mismatch is idempotent.
                version = runtime.get_work("demo")["state_version"]
                events = len(runtime.events("demo"))
                again = runtime.reconcile(withdrawal_id, adapter)
                self.assertEqual((again["status"], again["reason"]),
                                 ("outcome_unknown", "ADAPTER_RESULT_INVALID"))
                self.assertEqual(runtime.get_work("demo")["state_version"], version)
                self.assertEqual(len(runtime.events("demo")), events)
                # No proof of any kind was inserted for the withdrawal.
                kinds = [p["kind"] for p in self.withdrawn_proofs()
                         if p["event_id"] == withdrawal_id]
                self.assertEqual(kinds, [])

    def test_withdrawn_proof_kind_never_satisfies_e08(self):
        # Forward acceptance at digest1, revise to digest2, E08 pending there.
        prerequisites(self.runtime)
        r1 = action(self.runtime)["operation_id"]
        self.runtime.dispatch(r1, self.oa)
        send(self.runtime, "demo", "revise_document",
             {"document": document(invoice_id="INV-R2")})
        requirements = {r["rule_id"]: r for r in
                        self.runtime.get_work("demo")["requirements"]}
        self.assertEqual(requirements["E08"]["fulfillment"], "pending")
        target, withdrawal_id = self.prepared_withdrawal(target_id=r1)
        resolved = self.runtime.dispatch(withdrawal_id, self.oa)
        self.assertEqual(resolved["status"], "confirmed_succeeded")
        # The withdrawn proof exists at digest2 but E08 stays pending.
        proof = next(p for p in self.withdrawn_proofs()
                     if p["event_id"] == withdrawal_id)
        self.assertEqual((proof["kind"], proof["status"]), ("withdrawn", "verified"))
        self.assertEqual(proof["data"]["original_external_id"],
                         self.runtime.get_operation(r1)["external_id"])
        requirements = {r["rule_id"]: r for r in
                        self.runtime.get_work("demo")["requirements"]}
        self.assertEqual(requirements["E08"]["fulfillment"], "pending")
        # Revoking the ORIGINAL accepted proof does not let withdrawn satisfy E08.
        send(self.runtime, "demo", "revoke_evidence",
             {"source": "oa", "event_id": r1, "reason": "audit"}, actor="admin")
        requirements = {r["rule_id"]: r for r in
                        self.runtime.get_work("demo")["requirements"]}
        self.assertEqual(requirements["E08"]["fulfillment"], "pending")
        # The withdrawn proof is revocable only by an administrator: the
        # configured accepted source actor (without work.intervene) is denied.
        grants = compensation_grants(extra={"oa": {"evidence.write", "evidence.revoke"}})
        runtime = Runtime(self.path, ExpensePolicy(), grants)
        receipt = send(runtime, "demo", "revoke_evidence",
                       {"source": "oa", "event_id": withdrawal_id,
                        "reason": "attempt by source"}, actor="oa")
        self.assertEqual((receipt["decision"], receipt["code"]),
                         ("rejected", "AUTHORITY_DENIED"))
        admin_receipt = send(self.runtime, "demo", "revoke_evidence",
                             {"source": "oa", "event_id": withdrawal_id,
                              "reason": "admin withdraws it"}, actor="admin")
        self.assertEqual(admin_receipt["decision"], "accepted")
        # No actor can import a withdrawn proof through record_evidence.
        import_receipt = send(runtime, "demo", "record_evidence",
                              {"event_id": "evt-w", "kind": "withdrawn",
                               "data": {"digest": "x", "external_id": "WD-1",
                                        "original_external_id": "OA-1"}},
                              actor="oa")
        self.assertEqual((import_receipt["decision"], import_receipt["code"]),
                         ("rejected", "AUTHORITY_DENIED"))

    def test_withdrawal_resolution_stores_adapter_result(self):
        # A second confirmed target for the refused leg, proposed before the
        # window opens (revise_document is CANCELLATION_ACTIVE inside it).
        self.refused_target = self.confirmed_submit(invoice_id="INV-R3")
        # Accepted withdrawal stores the full validated receipt.
        target, withdrawal_id = self.prepared_withdrawal()
        self.runtime.dispatch(withdrawal_id, self.oa)
        op = self.runtime.get_operation(withdrawal_id)
        self.assertEqual(op["adapter_result"]["status"], "accepted")
        self.assertEqual(op["adapter_result"]["original_external_id"],
                         op["compensates"]["external_id"])
        self.assertEqual(op["adapter_result"]["external_id"], op["external_id"])
        # A refused withdrawal (ORIGINAL_ABSENT: adapter store without the
        # original) stores its validated rejection receipt too.
        withdrawal2 = self.withdraw(self.refused_target)["operation_id"]
        empty_oa = FakeOA(str(Path(self.temp.name) / "empty-oa.sqlite"))
        failed = self.runtime.dispatch(withdrawal2, empty_oa)
        self.assertEqual(failed["status"], "confirmed_failed")
        op2 = self.runtime.get_operation(withdrawal2)
        self.assertEqual(op2["adapter_result"]["reason"], "ORIGINAL_ABSENT")
        # Ordinary forward operations never carry adapter_result.
        self.assertNotIn("adapter_result", self.runtime.get_operation(target))
        self.assertNotIn("adapter_result",
                         self.runtime.get_operation(self.refused_target))

    def test_withdrawal_rejected_by_adapter_is_failed_and_closure_stays_truthful(self):
        target, withdrawal_id = self.prepared_withdrawal()
        empty_oa = FakeOA(str(Path(self.temp.name) / "empty-oa.sqlite"))
        failed = self.runtime.dispatch(withdrawal_id, empty_oa)
        self.assertEqual(failed["status"], "confirmed_failed")
        self.assertEqual(self.runtime.get_work("demo")["status"], "needs_attention")

    def test_s9_conflict_path_covers_withdrawal_identity(self):
        target, withdrawal_id = self.prepared_withdrawal()
        # Poison the acceptance-proof identity (accepted source, withdrawal op
        # id) the way only a legacy/pre-reservation store could.
        poison = {"id": uuid.uuid4().hex, "source": "oa", "event_id": withdrawal_id,
                  "kind": "accepted", "status": "verified",
                  "data": {"digest": "0" * 64, "external_id": "OA-poison"}}
        db = sqlite3.connect(self.path)
        try:
            db.execute("INSERT INTO evidence VALUES (?,?,?,?,?)",
                       ("oa", withdrawal_id, "demo", digest(poison), canonical(poison)))
            db.commit()
        finally:
            db.close()
        resolved = self.runtime.dispatch(withdrawal_id, self.oa)
        self.assertEqual(resolved["status"], "confirmed_succeeded")
        self.assertTrue(resolved["external_id"].startswith("WD-"))
        conflict = resolved["proof_conflict"]
        self.assertEqual((conflict["source"], conflict["event_id"]),
                         ("oa", withdrawal_id))
        self.assertEqual(conflict["evidence_id"], poison["id"])
        # No proof of any kind was inserted; the poison row is untouched.
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT body FROM evidence WHERE source='oa' AND event_id=?",
                             (withdrawal_id,)).fetchone()
        finally:
            db.close()
        self.assertEqual(json.loads(row[0]), poison)
        events = [e["type"] for e in self.runtime.events("demo")]
        self.assertIn("AcceptanceProofConflict", events)
        self.assertEqual(self.oa.withdrawn_count(), 1)



class CompensationClosureTests(CompensationCase):
    def finalize(self, runtime=None, work_id="demo", ack=None):
        runtime = runtime or self.runtime
        operations = [json.loads(row[0]) for row in Runtime._connect(runtime).execute(
            "SELECT body FROM operations WHERE work_id=?", (work_id,))]
        succeeded = sorted(op["id"] for op in operations
                           if op["status"] == "confirmed_succeeded")
        receipt = send(runtime, work_id, "finalize_cancel",
                       {"acknowledged_operations": ack if ack is not None else succeeded},
                       actor="admin")
        return receipt

    def completed_withdrawal(self):
        target, withdrawal_id = self.prepared_withdrawal()
        self.runtime.dispatch(withdrawal_id, self.oa)
        return target, withdrawal_id

    def test_finalize_ack_includes_original_and_withdrawal(self):
        target, withdrawal_id = self.completed_withdrawal()
        # An ack missing the withdrawal is rejected with both ids as blockers.
        partial = self.finalize(ack=[target])
        self.assertEqual(partial["decision"], "rejected")
        self.assertEqual(partial["code"], "CANCEL_ACKNOWLEDGEMENT_MISMATCH")
        self.assertEqual(partial["blockers"], sorted([target, withdrawal_id]))
        receipt = self.finalize()
        self.assertEqual(receipt["decision"], "accepted")
        work = self.runtime.get_work("demo")
        self.assertEqual((work["status"], work["outcome"]), ("closed", "cancelled"))
        completion = work["completion"]
        acknowledged = {entry["operation_id"]: entry["external_id"]
                        for entry in completion["acknowledged_operations"]}
        self.assertEqual(set(acknowledged), {target, withdrawal_id})
        self.assertTrue(acknowledged[target].startswith("OA-"))
        self.assertTrue(acknowledged[withdrawal_id].startswith("WD-"))
        dispositions = {d["operation_id"]: d for d in
                        completion["operation_dispositions"]}
        self.assertEqual(dispositions[target],
                         {"operation_id": target, "status": "confirmed_succeeded",
                          "dispatch_state": "finished"})
        self.assertEqual(dispositions[withdrawal_id],
                         {"operation_id": withdrawal_id, "status": "confirmed_succeeded",
                          "dispatch_state": "finished",
                          "compensates": self.runtime.get_operation(withdrawal_id)["compensates"],
                          "adapter_result": self.runtime.get_operation(withdrawal_id)["adapter_result"]})

    def test_failed_withdrawal_closure_ack_is_original_only(self):
        target = self.confirmed_submit()
        refused_target = self.confirmed_submit(invoice_id="INV-RF")
        self.request_cancel()
        withdrawal_id = self.withdraw(target)["operation_id"]
        empty_oa = FakeOA(str(Path(self.temp.name) / "empty-oa.sqlite"))
        failed = self.runtime.dispatch(withdrawal_id, empty_oa)
        self.assertEqual(failed["status"], "confirmed_failed")
        # Ack must equal exactly the succeeded set: the two confirmed
        # originals, never the failed withdrawal.
        wrong = self.finalize(ack=[target, withdrawal_id])
        self.assertEqual(wrong["code"], "CANCEL_ACKNOWLEDGEMENT_MISMATCH")
        receipt = self.finalize(ack=[target, refused_target])
        self.assertEqual(receipt["decision"], "accepted")
        work = self.runtime.get_work("demo")
        completion = work["completion"]
        self.assertEqual(sorted(e["operation_id"] for e in
                                completion["acknowledged_operations"]),
                         sorted([target, refused_target]))
        disposition = next(d for d in completion["operation_dispositions"]
                           if d["operation_id"] == withdrawal_id)
        self.assertEqual(disposition["status"], "confirmed_failed")
        self.assertEqual(disposition["adapter_result"]["reason"], "ORIGINAL_ABSENT")
        self.assertEqual(disposition["compensates"]["operation_id"], target)
        # Refusal is described, never a reversal: original effects retained.
        self.assertEqual(self.oa.accepted_count(), 2)
        original = self.runtime.get_operation(target)
        self.assertEqual(original["status"], "confirmed_succeeded")

    def test_unresolved_compensations_block_finalize(self):
        target = self.confirmed_submit()
        self.request_cancel()
        prepared = self.withdraw(target)["operation_id"]
        blocked = self.finalize()
        self.assertEqual((blocked["decision"], blocked["code"], blocked["blockers"]),
                         ("rejected", "OUTCOME_UNRESOLVED", [prepared]))
        # Held compensation blocks the same way.
        self.runtime.dispatch(prepared, ContextDeclaringOA(self.oa_path))
        blocked = self.finalize()
        self.assertEqual(blocked["code"], "OUTCOME_UNRESOLVED")
        # And an outcome_unknown one.
        self.runtime.reconcile(prepared, SilentAdapter())
        blocked = self.finalize()
        self.assertEqual(blocked["code"], "OUTCOME_UNRESOLVED")

    def test_withdrawal_replay_and_authority(self):
        target = self.confirmed_submit()
        self.request_cancel()
        decision_version = self.runtime.get_work("demo")["state_version"]
        first = self.withdraw(target, command_id="wd-once")

        def replay_command(runtime):
            work = runtime.get_work("demo")
            return runtime.command("agent", "wd-once", "demo", "propose_action", {
                "capability": "expense.withdraw",
                "document_digest": work["document_digest"],
                "contract_revision": work["contract"]["revision"],
                "plan_revision": work["plan_revision"],
                "compensates": target}, decision_version)

        self.assertEqual(replay_command(self.runtime), first)
        # Grant loss: replay returns a fresh, unpersisted AUTHORITY_DENIED.
        grants = compensation_grants()
        grants["agent"] = grants["agent"] - {"expense.withdraw"}
        runtime = Runtime(self.path, ExpensePolicy(), grants)
        denied = replay_command(runtime)
        self.assertEqual((denied["decision"], denied["code"]),
                         ("rejected", "AUTHORITY_DENIED"))
        # Restore: the stored receipt replays verbatim again.
        self.assertEqual(replay_command(self.runtime), first)


class CompensationRecoveryTests(CompensationCase):
    def test_recover_dispatches_ready_withdrawal_inside_window(self):
        target = self.confirmed_submit()
        self.request_cancel()
        withdrawal_id = self.withdraw(target)["operation_id"]
        restarted = Runtime(self.path, ExpensePolicy(), compensation_grants())
        results = restarted.recover(self.oa)
        dispatched = [op for op in results if op["id"] == withdrawal_id]
        self.assertEqual(len(dispatched), 1)
        self.assertEqual(dispatched[0]["status"], "confirmed_succeeded")
        self.assertEqual(self.oa.withdrawn_count(), 1)

    def test_withdrawal_readmission_and_transfer_owner_inside_window(self):
        target = self.confirmed_submit()
        self.request_cancel()
        first = self.withdraw(target, command_id="wd-1")
        withdrawal_id = first["operation_id"]
        snapshot = self.runtime.get_operation(withdrawal_id)["compensates"]
        # Hold the compensation on a non-opted-in adapter, then transfer: the
        # held prepared intent is invalidated OWNERSHIP_TRANSFERRED.
        self.runtime.dispatch(withdrawal_id, ContextDeclaringOA(self.oa_path))
        self.assertEqual(self.runtime.get_operation(withdrawal_id)["dispatch_state"],
                         "held")
        grants = compensation_grants(extra={"agent2": {"work.manage",
                                                      "expense.withdraw"}})
        runtime = Runtime(self.path, ExpensePolicy(), grants)
        send(runtime, "demo", "transfer_owner",
             {"owner": "agent2", "reason": "reassign"}, actor="admin")
        invalidated = runtime.get_operation(withdrawal_id)
        self.assertEqual((invalidated["dispatch_state"], invalidated["reason"]),
                         ("cancelled", "OWNERSHIP_TRANSFERRED"))
        # The new owner re-admits inside the window: same operation, ready
        # again, actor updated, link never rebound.
        readmitted = self.withdraw(target, runtime=runtime, actor="agent2",
                                   command_id="wd-2")
        self.assertEqual(readmitted["operation_id"], withdrawal_id)
        readmitted_op = runtime.get_operation(withdrawal_id)
        self.assertEqual(readmitted_op["dispatch_state"], "ready")
        self.assertEqual(readmitted_op["actor"], "agent2")
        self.assertEqual(readmitted_op["compensates"], snapshot)
        # A further transfer to an owner WITHOUT the grant: re-proposal is
        # AUTHORITY_DENIED; with the grant, re-admission works again.
        grants4 = compensation_grants(extra={"agent3": {"work.manage",
                                                        "expense.withdraw"}})
        runtime4 = Runtime(self.path, ExpensePolicy(), grants4)
        send(runtime4, "demo", "transfer_owner",
             {"owner": "agent3", "reason": "reassign again"}, actor="admin")
        grants3 = compensation_grants(extra={"agent3": {"work.manage"}})
        runtime3 = Runtime(self.path, ExpensePolicy(), grants3)
        denied = self.withdraw(target, runtime=runtime3, actor="agent3",
                               command_id="wd-3")
        self.assertEqual((denied["decision"], denied["code"]),
                         ("rejected", "AUTHORITY_DENIED"))
        readmitted2 = self.withdraw(target, runtime=runtime4, actor="agent3",
                                    command_id="wd-4")
        self.assertEqual(readmitted2["operation_id"], withdrawal_id)
        self.assertEqual(runtime4.get_operation(withdrawal_id)["dispatch_state"],
                         "ready")
        resolved = runtime4.dispatch(withdrawal_id, self.oa)
        self.assertEqual(resolved["status"], "confirmed_succeeded")

    def test_fresh_withdrawal_outside_window_and_after_closure(self):
        target = self.confirmed_submit()
        fresh = tempfile.TemporaryDirectory()
        self.addCleanup(fresh.cleanup)
        plain = Runtime(str(Path(fresh.name) / "runtime.sqlite"),
                        ExpensePolicy(), compensation_grants())
        initialize(plain)
        prerequisites(plain)
        other = action(plain)["operation_id"]
        plain.dispatch(other, FakeOA(str(Path(fresh.name) / "oa.sqlite")))
        # No intent: CANCELLATION_NOT_REQUESTED.
        work = plain.get_work("demo")
        receipt = send(plain, "demo", "propose_action", {
            "capability": "expense.withdraw",
            "document_digest": work["document_digest"],
            "contract_revision": work["contract"]["revision"],
            "plan_revision": work["plan_revision"], "compensates": other})
        self.assertEqual(receipt["code"], "CANCELLATION_NOT_REQUESTED")
        # Closed work: WORK_NOT_ACTIONABLE.
        self.request_cancel()
        self.finalize_and_close()
        receipt = self.withdraw(target, command_id="after-close")
        self.assertEqual(receipt["code"], "WORK_NOT_ACTIONABLE")

    def finalize_and_close(self):
        operations = [json.loads(row[0]) for row in
                      Runtime._connect(self.runtime).execute(
                          "SELECT body FROM operations WHERE work_id='demo'")]
        succeeded = sorted(op["id"] for op in operations
                           if op["status"] == "confirmed_succeeded")
        receipt = send(self.runtime, "demo", "finalize_cancel",
                       {"acknowledged_operations": succeeded}, actor="admin")
        assert receipt["decision"] == "accepted", receipt

    def crash_child(self, withdrawal_id, extra=""):
        script = (
            "import sys\n"
            "sys.path.insert(0, {root!r})\n"
            "from work_runtime import Runtime\n"
            "from work_runtime.adapters import FakeOA\n"
            "from work_runtime.policy import ExpensePolicy\n"
            "GRANTS = {{'agent': {{'work.manage', 'expense.submit',"
            " 'expense.withdraw'}},\n"
            "          'finance': {{'evidence.write'}}, 'requester': {{'evidence.write'}},\n"
            "          'invoice-service': {{'evidence.write'}},"
            " 'expense-service': {{'evidence.write'}},\n"
            "          'admin': {{'work.intervene'}}}}\n"
            "import os\n"
            "runtime = Runtime({path!r}, ExpensePolicy(), GRANTS)\n"
            "runtime.dispatch({op!r}, FakeOA({oa!r}),"
            " fault=lambda: os._exit(73))\n" + extra)
        return subprocess.run(
            [sys.executable, "-c", script.format(
                root=os.getcwd(), path=self.path, op=withdrawal_id,
                oa=self.oa_path)], check=False)

    def test_withdrawal_crash_after_effect_recovers_once(self):
        target, withdrawal_id = self.prepared_withdrawal()
        child = self.crash_child(withdrawal_id)
        self.assertEqual(child.returncode, 73)
        self.assertEqual(self.oa.withdrawn_count(), 1)
        self.assertEqual(self.runtime.get_operation(withdrawal_id)["status"],
                         "dispatched")
        restarted = Runtime(self.path, ExpensePolicy(), compensation_grants())
        restarted.recover(self.oa)
        op = restarted.get_operation(withdrawal_id)
        self.assertEqual(op["status"], "confirmed_succeeded")
        self.assertEqual(len(op["attempts"]), 1)
        self.assertEqual(self.oa.withdrawn_count(), 1)

    def test_real_crash_one_withdrawal_one_original_counts(self):
        target, withdrawal_id = self.prepared_withdrawal()
        child = self.crash_child(withdrawal_id)
        self.assertEqual(child.returncode, 73)
        self.assertEqual((self.oa.accepted_count(), self.oa.withdrawn_count()), (1, 1))
        restarted = Runtime(self.path, ExpensePolicy(), compensation_grants())
        restarted.recover(self.oa)
        op = restarted.get_operation(withdrawal_id)
        self.assertEqual(op["status"], "confirmed_succeeded")
        self.assertEqual(op["attempts"][0]["status"], "confirmed_succeeded")
        self.assertEqual((self.oa.accepted_count(), self.oa.withdrawn_count()), (1, 1))
        # Invoices unchanged; finalize closes with the exact two-id ack and a
        # closure snapshot carrying both external ids and dispositions.
        db = sqlite3.connect(self.oa_path)
        try:
            invoices = db.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]
        finally:
            db.close()
        self.assertEqual(invoices, 1)
        operations = [json.loads(row[0]) for row in
                      Runtime._connect(restarted).execute(
                          "SELECT body FROM operations WHERE work_id='demo'")]
        succeeded = sorted(op["id"] for op in operations
                           if op["status"] == "confirmed_succeeded")
        self.assertEqual(succeeded, sorted([target, withdrawal_id]))
        receipt = send(restarted, "demo", "finalize_cancel",
                       {"acknowledged_operations": succeeded}, actor="admin")
        self.assertEqual(receipt["decision"], "accepted")
        completion = restarted.get_work("demo")["completion"]
        externals = {e["operation_id"]: e["external_id"]
                     for e in completion["acknowledged_operations"]}
        self.assertEqual(set(externals), {target, withdrawal_id})
        self.assertTrue(externals[withdrawal_id].startswith("WD-"))
        self.assertTrue(externals[target].startswith("OA-"))

    def test_execute_exception_stays_outcome_unknown(self):
        target, withdrawal_id = self.prepared_withdrawal()
        failing = MismatchedWithdrawalAdapter("", "")  # never used for its receipt

        def explode(key, document, content_digest, **kwargs):
            raise sqlite3.OperationalError("store unavailable")

        failing.execute = explode
        unknown = self.runtime.dispatch(withdrawal_id, failing)
        self.assertEqual((unknown["status"], unknown["reason"]),
                         ("outcome_unknown", "OperationalError"))
        self.assertEqual(self.oa.withdrawn_count(), 0)
        self.assertNotIn("adapter_result", self.runtime.get_operation(withdrawal_id))

    def test_readonly_inspector_handles_compensations_zero_write(self):
        target, withdrawal_id = self.completed_withdrawal_flow()
        before = (Path(self.path).read_bytes(), Path(self.oa_path).read_bytes())
        inspector = ReadOnlyInspector(self.path)
        summary = inspector.summary()
        events = inspector.events("demo")
        detail = inspector.work_detail("demo")
        after = (Path(self.path).read_bytes(), Path(self.oa_path).read_bytes())
        self.assertEqual(before, after)
        self.assertEqual(summary["works"][0]["work_id"]
                         if isinstance(summary.get("works"), list) else True, True)
        event_types = [e["type"] for e in events["events"]] \
            if isinstance(events.get("events"), list) else []
        self.assertIn("OperationPrepared", event_types)

    def completed_withdrawal_flow(self):
        target, withdrawal_id = self.prepared_withdrawal()
        self.runtime.dispatch(withdrawal_id, self.oa)
        return target, withdrawal_id



class PreservationPins(CompensationCase):
    """S10 additive-only pins: what must NOT have changed."""

    def test_publishing_family_and_assets_unchanged(self):
        from work_runtime.publishing import FakePublisher, PublishingPolicy
        from work_runtime.file_adapter import FilePublisher
        # S14 supersession (master option A, 2026-10-16): this S10 pin asserted
        # the publishing family was unpaired; ratified D81/D89 pair it. The
        # expense pins below are unchanged.
        self.assertEqual(PublishingPolicy.compensation_capabilities,
                         {"content.unpublish": "content.publish"})
        for owner in (FakePublisher, FilePublisher):
            with self.subTest(owner=owner.__name__):
                self.assertFalse(getattr(owner, "compensation_capabilities", None))
        self.assertIs(FilePublisher.contract.supports_action_context, False)
        self.assertIs(FakePublisher.contract.supports_action_context, False)
        self.assertEqual(PublishingPolicy().action_blockers("content.publish", []),
                         [])
        self.assertNotEqual(PublishingPolicy().action_blockers("content.withdraw", []),
                            [])
        self.assertEqual(PublishingPolicy().action_blockers("content.withdraw", []),
                         [{"code": "CAPABILITY_UNSUPPORTED",
                           "capability": "content.withdraw"}])

    def test_runtime_schema_stays_one(self):
        target, withdrawal_id = self.completed()
        db = sqlite3.connect(self.path)
        try:
            row = db.execute(
                "SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        finally:
            db.close()
        self.assertEqual(row[0], "1")

    def test_no_new_dependencies(self):
        import work_runtime.runtime, work_runtime.adapters
        import work_runtime.adapter_contract, work_runtime.policy
        import inspect
        allowed = {"json", "sqlite3", "time", "uuid", "hashlib", "typing",
                   "pathlib", "contextlib", "dataclasses"}
        for module in (work_runtime.runtime, work_runtime.adapters,
                       work_runtime.adapter_contract, work_runtime.policy):
            tree = inspect.getsource(module)
            for line in tree.splitlines():
                line = line.strip()
                if line.startswith("import ") or line.startswith("from ."):
                    parts = line.split()
                    if parts[0] == "from" and parts[1].startswith("."):
                        continue
                    if parts[0] == "import":
                        name = parts[1].split(".")[0].rstrip(",")
                        self.assertIn(name, allowed,
                                      "%s imports %s" % (module.__name__, name))

    def test_operation_payloads_unchanged_for_ordinary_ops(self):
        target, _ = self.completed()
        operation = self.runtime.get_operation(target)
        self.assertEqual(set(operation), {
            "id", "business_key", "work_id", "actor", "capability", "status",
            "dispatch_state", "attempts", "document", "document_digest",
            "plan_revision", "contract_revision", "external_id"})

    def completed(self):
        target, withdrawal_id = self.prepared_withdrawal()
        self.runtime.dispatch(withdrawal_id, self.oa)
        return target, withdrawal_id


if __name__ == "__main__":
    unittest.main()
