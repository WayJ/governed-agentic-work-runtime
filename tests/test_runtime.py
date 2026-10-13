import copy
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from work_runtime import CommandError, ExpensePolicy, Runtime
from work_runtime.adapters import FakeOA
from work_runtime.demo import action, demo_grants, document, initialize, prerequisites, proof, send


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        self.oa_path = str(Path(self.temp.name) / "oa.sqlite")
        self.grants = demo_grants()
        self.runtime = Runtime(self.path, ExpensePolicy(), self.grants)
        self.oa = FakeOA(self.oa_path)
        initialize(self.runtime)

    def ready(self):
        prerequisites(self.runtime)

    def submit(self):
        self.ready()
        receipt = action(self.runtime)
        self.assertEqual(receipt["decision"], "accepted")
        return receipt["operation_id"]

    def requirement(self, rule):
        return next(r for r in self.runtime.get_work("demo")["requirements"] if r["rule_id"] == rule)

    def test_standard_expense_and_completion(self):
        op = self.submit()
        self.assertEqual(self.runtime.dispatch(op, self.oa)["status"], "confirmed_succeeded")
        self.assertEqual(send(self.runtime, "demo", "request_completion")["decision"], "accepted")
        self.assertEqual(self.runtime.get_work("demo")["outcome"], "succeeded")
        self.assertEqual(self.oa.accepted_count(), 1)

    def test_missing_approval_cannot_be_deleted_with_plan(self):
        prerequisites(self.runtime, approval=False)
        send(self.runtime, "demo", "revise_plan", {
            "steps": ["submit"], "open_requirements": [], "replan_when": []})
        receipt = action(self.runtime)
        self.assertEqual(receipt["decision"], "rejected")
        self.assertIn("E05", {b["rule_id"] for b in receipt["blockers"]})

    def test_unknown_amount_blocks(self):
        self.ready()
        doc = document(amount=None)
        send(self.runtime, "demo", "revise_document", {"document": doc})
        self.assertEqual(self.requirement("E05")["applicability"], "unknown")
        self.assertEqual(action(self.runtime)["code"], "APPLICABILITY_UNRESOLVED")

    def test_empty_and_unsealed_invoice_sets_block(self):
        for change in ({"invoices": []}, {"sealed": False}):
            doc = document()
            doc.update(change)
            send(self.runtime, "demo", "revise_document", {"document": doc})
            prerequisites(self.runtime)
            self.assertEqual(self.requirement("E01")["fulfillment"], "pending")
            self.assertEqual(action(self.runtime)["decision"], "rejected")

    def test_low_amount_has_no_approval_requirement(self):
        send(self.runtime, "demo", "revise_document", {"document": document(amount=80000)})
        prerequisites(self.runtime, approval=False)
        self.assertEqual(self.requirement("E05")["applicability"], "not_applicable")
        self.assertEqual(action(self.runtime)["decision"], "accepted")

    def test_evidence_receipt_is_not_verification(self):
        proof(self.runtime, "demo", "approval", "finance")
        self.assertEqual(self.requirement("E05")["fulfillment"], "pending")
        self.runtime.verify_pending("demo")
        self.assertEqual(self.requirement("E05")["fulfillment"], "satisfied")

    def test_source_cannot_be_impersonated_in_payload(self):
        receipt = proof(self.runtime, "demo", "approval", "agent")
        self.assertEqual(receipt["code"], "AUTHORITY_DENIED")
        self.assertEqual(self.runtime.verify_pending("demo"), 0)

    def test_invalid_candidate_does_not_satisfy_requirement(self):
        proof(self.runtime, "demo", "approval", "finance", {"approved": True})
        self.runtime.verify_pending("demo")
        self.assertEqual(self.requirement("E05")["fulfillment"], "pending")

    def test_existing_invoice_proof_reused_after_document_change(self):
        self.ready()
        changed = document(amount=130000)
        send(self.runtime, "demo", "revise_document", {"document": changed})
        self.assertEqual(self.requirement("E02")["fulfillment"], "satisfied")
        self.assertEqual(self.requirement("E05")["fulfillment"], "pending")
        self.assertEqual(self.requirement("E06")["fulfillment"], "pending")

    def test_invoice_revision_invalidates_old_verification(self):
        self.ready()
        changed = document()
        changed["invoices"][0]["revision"] = 2
        send(self.runtime, "demo", "revise_document", {"document": changed})
        self.assertEqual(self.requirement("E02")["fulfillment"], "pending")

    def test_rejected_command_replay_remains_rejected(self):
        prerequisites(self.runtime, approval=False)
        work = self.runtime.get_work("demo")
        payload = {"capability": "expense.submit", "document_digest": work["document_digest"],
                   "contract_revision": 1, "plan_revision": work["plan_revision"]}
        args = ("agent", "old-rejected", "demo", "propose_action", payload, work["state_version"])
        before = self.runtime.command(*args)
        proof(self.runtime, "demo", "approval", "finance")
        self.runtime.verify_pending("demo")
        self.assertEqual(self.runtime.command(*args), before)
        self.assertEqual(action(self.runtime)["decision"], "accepted")

    def test_changed_content_with_same_command_id_rejected(self):
        self.ready()
        work = self.runtime.get_work("demo")
        payload = {"capability": "expense.submit", "document_digest": work["document_digest"],
                   "contract_revision": 1, "plan_revision": work["plan_revision"]}
        args = ("agent", "same-id", "demo", "propose_action", payload, work["state_version"])
        self.runtime.command(*args)
        altered = {**payload, "document_digest": "different"}
        result = self.runtime.command("agent", "same-id", "demo", "propose_action", altered, work["state_version"])
        self.assertEqual(result["code"], "COMMAND_ID_REUSED")

    def test_duplicate_commands_concurrently_have_one_receipt(self):
        self.ready()
        work = self.runtime.get_work("demo")
        payload = {"capability": "expense.submit", "document_digest": work["document_digest"],
                   "contract_revision": 1, "plan_revision": work["plan_revision"]}
        def invoke(_):
            runtime = Runtime(self.path, ExpensePolicy(), demo_grants())
            return runtime.command("agent", "concurrent", "demo", "propose_action", payload,
                                   work["state_version"])
        with ThreadPoolExecutor(max_workers=4) as pool:
            receipts = list(pool.map(invoke, range(4)))
        self.assertTrue(all(r == receipts[0] for r in receipts))
        self.assertEqual(len([e for e in self.runtime.events("demo") if e["type"] == "OperationPrepared"]), 1)

    def test_conflicting_plan_revisions_use_compare_and_swap(self):
        work = self.runtime.get_work("demo")
        payload = {"steps": [], "open_requirements": [], "replan_when": ["new facts"]}
        first = self.runtime.command("agent", "p1", "demo", "revise_plan", payload, work["state_version"])
        second = self.runtime.command("agent", "p2", "demo", "revise_plan", payload, work["state_version"])
        self.assertEqual(first["decision"], "accepted")
        self.assertEqual(second["code"], "STATE_VERSION_CONFLICT")

    def test_new_command_same_business_operation_reuses_identity(self):
        op = self.submit()
        self.assertEqual(action(self.runtime)["operation_id"], op)
        self.runtime.dispatch(op, self.oa)
        self.assertEqual(action(self.runtime)["operation_id"], op)
        self.runtime.dispatch(op, self.oa)
        self.assertEqual(self.oa.accepted_count(), 1)

    def test_prepared_intent_survives_restart(self):
        op = self.submit()
        restarted = Runtime(self.path, ExpensePolicy(), demo_grants())
        restarted.recover(self.oa)
        self.assertEqual(restarted.get_operation(op)["status"], "confirmed_succeeded")

    def test_actual_process_crash_after_external_commit(self):
        op = self.submit()
        child = subprocess.run([sys.executable, "-m", "work_runtime", "worker", "--runtime", self.path,
                                "--oa", self.oa_path, "--operation", op, "--crash-after-effect"], check=False)
        self.assertEqual(child.returncode, 73)
        self.assertEqual(self.runtime.get_operation(op)["status"], "dispatched")
        self.assertEqual(self.oa.accepted_count(), 1)
        restarted = Runtime(self.path, ExpensePolicy(), demo_grants())
        restarted.recover(self.oa)
        self.assertEqual(restarted.get_operation(op)["status"], "confirmed_succeeded")
        self.assertEqual(self.oa.accepted_count(), 1)

    def test_timeout_after_commit_then_reconcile(self):
        op = self.submit()
        result = self.runtime.dispatch(op, FakeOA(self.oa_path, timeout_after_commit=True))
        self.assertEqual(result["status"], "outcome_unknown")
        self.assertEqual(send(self.runtime, "demo", "request_completion")["code"], "OUTCOME_UNRESOLVED")
        self.runtime.reconcile(op, self.oa)
        self.assertEqual(self.oa.accepted_count(), 1)
        self.assertEqual(send(self.runtime, "demo", "request_completion")["decision"], "accepted")

    def test_unknown_without_query_result_requires_attention(self):
        class Unqueryable:
            def execute(self, *args):
                raise TimeoutError()
            def lookup(self, key):
                return None
        op = self.submit()
        self.runtime.dispatch(op, Unqueryable())
        self.runtime.recover(Unqueryable())
        self.assertEqual(self.runtime.get_work("demo")["status"], "needs_attention")
        self.assertEqual(len(self.runtime.get_operation(op)["attempts"]), 1)

    def test_early_approval_and_duplicate_callback_do_not_lose_wakeup(self):
        proof(self.runtime, "demo", "approval", "finance", event_id="approve-early")
        self.runtime.verify_pending("demo")
        send(self.runtime, "demo", "register_wait", {
            "requirement_id": "E05:EXP-001", "deadline": 100, "owner": "finance"})
        work = self.runtime.get_work("demo")
        self.assertEqual(work["waits"][0]["status"], "triggered")
        proof(self.runtime, "demo", "approval", "finance", event_id="approve-early")
        self.assertEqual(self.runtime.verify_pending("demo"), 0)
        self.assertEqual(self.runtime.get_work("demo")["state_version"], work["state_version"])

    def test_conflicting_source_event_preserves_original(self):
        proof(self.runtime, "demo", "approval", "finance", event_id="e1")
        receipt = proof(self.runtime, "demo", "approval", "finance", {"digest": "different"}, event_id="e1")
        self.assertEqual(receipt["code"], "SOURCE_EVENT_CONFLICT")
        self.runtime.verify_pending("demo")
        self.assertEqual(self.requirement("E05")["fulfillment"], "satisfied")

    def test_wait_expiry_survives_restart(self):
        send(self.runtime, "demo", "register_wait", {
            "requirement_id": "E05:EXP-001", "deadline": 100, "owner": "finance"})
        restarted = Runtime(self.path, ExpensePolicy(), demo_grants())
        restarted.recover(self.oa, now=101)
        self.assertEqual(restarted.get_work("demo")["status"], "needs_attention")
        self.assertEqual(restarted.get_work("demo")["waits"][0]["status"], "expired")

    def test_authority_revoked_before_dispatch_holds_intent(self):
        op = self.submit()
        self.grants["agent"].remove("expense.submit")
        result = self.runtime.dispatch(op, self.oa)
        self.assertEqual(result["dispatch_state"], "held")
        self.assertEqual(self.oa.accepted_count(), 0)

    def test_document_revision_cancels_unstarted_intent(self):
        op = self.submit()
        send(self.runtime, "demo", "revise_document", {"document": document(amount=130000)})
        result = self.runtime.dispatch(op, self.oa)
        self.assertEqual(result["dispatch_state"], "cancelled")
        self.assertEqual(self.oa.accepted_count(), 0)

    def test_plan_revision_readmits_same_unstarted_operation(self):
        op = self.submit()
        send(self.runtime, "demo", "revise_plan", {
            "steps": ["submit"], "open_requirements": [], "replan_when": []})
        self.assertEqual(self.runtime.get_operation(op)["dispatch_state"], "cancelled")
        self.assertEqual(action(self.runtime)["operation_id"], op)
        self.assertEqual(self.runtime.get_operation(op)["dispatch_state"], "ready")
        self.runtime.dispatch(op, self.oa)
        self.assertEqual(self.oa.accepted_count(), 1)

    def test_unknown_old_content_blocks_new_submission(self):
        op = self.submit()
        self.runtime.dispatch(op, FakeOA(self.oa_path, timeout_after_commit=True))
        send(self.runtime, "demo", "revise_document", {"document": document(amount=130000)})
        prerequisites(self.runtime)
        self.assertEqual(action(self.runtime)["code"], "OUTCOME_UNRESOLVED")

    def test_completion_needs_business_evidence(self):
        self.ready()
        receipt = send(self.runtime, "demo", "request_completion")
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual({r["rule_id"] for r in receipt["blockers"]}, {"E08"})

    def test_verification_crash_rolls_back_adoption_and_evaluation(self):
        proof(self.runtime, "demo", "approval", "finance")
        def crash():
            raise RuntimeError("simulated crash before evaluation")
        with self.assertRaises(RuntimeError):
            self.runtime.verify_pending("demo", fault=crash)
        self.assertEqual(self.requirement("E05")["fulfillment"], "pending")
        restarted = Runtime(self.path, ExpensePolicy(), demo_grants())
        self.assertEqual(restarted.verify_pending("demo"), 1)
        self.assertEqual(self.requirement("E05")["fulfillment"], "satisfied")

    def test_real_process_death_during_evidence_adoption(self):
        proof(self.runtime, "demo", "approval", "finance")
        script = (
            "import os,sys; from work_runtime import Runtime,ExpensePolicy; "
            "from work_runtime.demo import demo_grants; "
            "Runtime(sys.argv[1],ExpensePolicy(),demo_grants()).verify_pending(" 
            "'demo',fault=lambda:os._exit(74))"
        )
        child = subprocess.run([sys.executable, "-c", script, self.path], check=False)
        self.assertEqual(child.returncode, 74)
        self.assertEqual(self.requirement("E05")["fulfillment"], "pending")
        restarted = Runtime(self.path, ExpensePolicy(), demo_grants())
        self.assertEqual(restarted.verify_pending("demo"), 1)
        self.assertEqual(self.requirement("E05")["fulfillment"], "satisfied")

    def test_policy_migration_is_not_implicit(self):
        other = ExpensePolicy()
        other.version = "demo-2"
        reopened = Runtime(self.path, other, demo_grants())
        with self.assertRaises(CommandError):
            reopened.get_work("demo")

    def test_evidence_before_binding_does_not_activate_work(self):
        send(self.runtime, "unbound", "create_work", {"document": document(document_id="unbound")})
        proof(self.runtime, "unbound", "approval", "finance")
        self.runtime.verify_pending("unbound")
        self.assertEqual(self.runtime.get_work("unbound")["status"], "establishing")

    def test_late_event_does_not_reopen_closed_work(self):
        op = self.submit()
        self.runtime.dispatch(op, self.oa)
        send(self.runtime, "demo", "request_completion")
        completion = copy.deepcopy(self.runtime.get_work("demo")["completion"])
        proof(self.runtime, "demo", "approval", "finance", {"digest": "old-content"})
        self.runtime.verify_pending("demo")
        work = self.runtime.get_work("demo")
        self.assertEqual(work["status"], "closed")
        self.assertEqual(work["completion"], completion)

    def test_external_uniqueness_across_works(self):
        first = self.submit()
        self.runtime.dispatch(first, self.oa)
        initialize(self.runtime, "other", document(document_id="EXP-002"))
        prerequisites(self.runtime, "other")
        second = action(self.runtime, "other")["operation_id"]
        self.assertEqual(self.runtime.dispatch(second, self.oa)["status"], "confirmed_failed")
        self.assertEqual(self.oa.accepted_count(), 1)
        self.assertEqual(send(self.runtime, "other", "request_completion")["decision"], "rejected")

    def test_malformed_document_rolls_back(self):
        with self.assertRaises(ValueError):
            send(self.runtime, "demo", "revise_document", {"document": document(amount=True)})
        self.assertEqual(self.runtime.get_work("demo")["document"]["amount"], 120000)

    def test_unsupported_command_explicitly_rejected(self):
        receipt = send(self.runtime, "demo", "request_refund")
        self.assertEqual(receipt["code"], "COMMAND_UNSUPPORTED")


if __name__ == "__main__":
    unittest.main()
