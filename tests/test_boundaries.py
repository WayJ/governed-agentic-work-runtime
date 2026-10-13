import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from work_runtime import ExpensePolicy, Runtime
from work_runtime.adapters import FakeOA
from work_runtime.demo import action, demo_grants, initialize, prerequisites, send


class SilentAdapter:
    """External call lost; no authoritative answer is ever available."""

    def __init__(self):
        self.execute_calls = 0

    def execute(self, key, document, content_digest):
        self.execute_calls += 1
        raise TimeoutError()

    def lookup(self, key):
        return None


class FailingAdapter:
    """Both the call and the reconciliation query raise."""

    def __init__(self, error):
        self.error = error
        self.execute_calls = 0

    def execute(self, key, document, content_digest):
        self.execute_calls += 1
        raise self.error

    def lookup(self, key):
        raise self.error


class MalformedAdapter:
    """Returns the same malformed payload from execute and lookup."""

    def __init__(self, result):
        self.result = result
        self.execute_calls = 0

    def execute(self, key, document, content_digest):
        self.execute_calls += 1
        return self.result

    def lookup(self, key):
        return self.result


class CountingAdapter:
    """Delegates to a real adapter while counting external interactions."""

    def __init__(self, inner):
        self.inner = inner
        self.executed = 0
        self.looked_up = 0

    def execute(self, key, document, content_digest):
        self.executed += 1
        return self.inner.execute(key, document, content_digest)

    def lookup(self, key):
        self.looked_up += 1
        return self.inner.lookup(key)


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        self.oa_path = str(Path(self.temp.name) / "oa.sqlite")
        self.runtime = Runtime(self.path, ExpensePolicy(), demo_grants())
        self.oa = FakeOA(self.oa_path)
        initialize(self.runtime)

    def submit(self):
        prerequisites(self.runtime)
        receipt = action(self.runtime)
        self.assertEqual(receipt["decision"], "accepted")
        return receipt["operation_id"]

    def events_of_type(self, event_type, work_id="demo"):
        return [e for e in self.runtime.events(work_id) if e["type"] == event_type]

    def requirement(self, rule, work_id="demo"):
        return next(r for r in self.runtime.get_work(work_id)["requirements"]
                    if r["rule_id"] == rule)

    def test_repeated_reconcile_without_authoritative_result_is_idempotent(self):
        op = self.submit()
        self.runtime.dispatch(op, SilentAdapter())
        first = self.runtime.reconcile(op, SilentAdapter())
        self.assertEqual((first["status"], first.get("reason")),
                         ("outcome_unknown", "NO_AUTHORITATIVE_RESULT"))
        self.assertEqual(self.runtime.get_work("demo")["status"], "needs_attention")
        version = self.runtime.get_work("demo")["state_version"]
        events = len(self.runtime.events("demo"))
        second = self.runtime.reconcile(op, SilentAdapter())
        self.assertEqual(second, first)
        self.assertEqual(self.runtime.get_work("demo")["state_version"], version)
        self.assertEqual(len(self.runtime.events("demo")), events)

    def test_repeated_reconcile_with_failing_lookup_is_idempotent(self):
        op = self.submit()
        failing = FailingAdapter(TimeoutError())
        self.runtime.dispatch(op, failing)
        first = self.runtime.reconcile(op, failing)
        self.assertEqual((first["status"], first.get("reason")),
                         ("outcome_unknown", "TimeoutError"))
        version = self.runtime.get_work("demo")["state_version"]
        second = self.runtime.reconcile(op, failing)
        self.assertEqual(second, first)
        self.assertEqual(self.runtime.get_work("demo")["state_version"], version)
        self.assertEqual(len(self.events_of_type("OutcomeUnknown")), 1)

    def test_repeated_malformed_result_reconcile_is_idempotent(self):
        op = self.submit()
        adapter = MalformedAdapter({"status": "accepted", "external_id": "OA-1"})
        quarantined = self.runtime.dispatch(op, adapter)
        self.assertEqual((quarantined["status"], quarantined.get("reason")),
                         ("outcome_unknown", "ADAPTER_RESULT_INVALID"))
        version = self.runtime.get_work("demo")["state_version"]
        resolved = len(self.events_of_type("OperationResolved"))
        self.runtime.reconcile(op, adapter)
        again = self.runtime.reconcile(op, adapter)
        self.assertEqual((again["status"], again.get("reason")),
                         ("outcome_unknown", "ADAPTER_RESULT_INVALID"))
        self.assertEqual(self.runtime.get_work("demo")["state_version"], version)
        self.assertEqual(len(self.events_of_type("OperationResolved")), resolved)


    def test_malformed_adapter_results_leave_inspectable_uncertainty(self):
        digest = self.runtime.get_work("demo")["document_digest"]
        variants = {
            "non-dict": "ok",
            "digest-missing": {"status": "accepted", "external_id": "OA-1"},
            "status-unknown": {"digest": digest, "status": "pending", "external_id": "OA-1"},
            "external-id-empty": {"digest": digest, "status": "accepted", "external_id": ""},
        }
        for name, result in variants.items():
            with self.subTest(variant=name):
                op = self.submit()
                quarantined = self.runtime.dispatch(op, MalformedAdapter(result))
                self.assertEqual((quarantined["status"], quarantined.get("reason")),
                                 ("outcome_unknown", "ADAPTER_RESULT_INVALID"))
                persisted = self.runtime.get_operation(op)
                self.assertEqual(persisted["attempts"][-1]["status"], "outcome_unknown")
                self.assertNotIn("external_id", persisted)
                self.assertEqual(self.runtime.get_work("demo")["status"], "needs_attention")
                self.assertEqual(self.requirement("E08")["fulfillment"], "pending")

    def test_mismatched_digest_result_is_quarantined(self):
        op = self.submit()
        adapter = MalformedAdapter({"status": "accepted", "external_id": "OA-wrong",
                                    "digest": "deadbeef"})
        quarantined = self.runtime.dispatch(op, adapter)
        self.assertEqual((quarantined["status"], quarantined.get("reason")),
                         ("outcome_unknown", "ADAPTER_RESULT_INVALID"))
        self.assertNotIn("external_id", self.runtime.get_operation(op))
        self.assertEqual(self.requirement("E08")["fulfillment"], "pending")
        receipt = send(self.runtime, "demo", "request_completion")
        self.assertEqual((receipt["decision"], receipt["code"]),
                         ("rejected", "OUTCOME_UNRESOLVED"))

    def test_adapter_recovering_with_valid_result_confirms_operation(self):
        op = self.submit()
        adapter = MalformedAdapter({"status": "accepted", "external_id": "OA-wrong",
                                    "digest": "deadbeef"})
        self.runtime.dispatch(op, adapter)
        adapter.result = {"status": "accepted", "external_id": "OA-fixed",
                          "digest": self.runtime.get_work("demo")["document_digest"]}
        recovered = self.runtime.reconcile(op, adapter)
        self.assertEqual(recovered["status"], "confirmed_succeeded")
        self.assertEqual(recovered["external_id"], "OA-fixed")
        self.assertEqual(self.requirement("E08")["fulfillment"], "satisfied")

    def test_recover_never_redispatches_uncertain_operation(self):
        op = self.submit()
        counting = CountingAdapter(FakeOA(self.oa_path, timeout_after_commit=True))
        unknown = self.runtime.dispatch(op, counting)
        self.assertEqual((unknown["status"], counting.executed, self.oa.accepted_count()),
                         ("outcome_unknown", 1, 1))
        for _ in range(3):
            self.runtime.recover(counting)
        self.runtime.dispatch(op, counting)
        self.assertEqual(counting.executed, 1)
        self.assertGreaterEqual(counting.looked_up, 1)
        self.assertEqual(self.runtime.get_operation(op)["status"], "confirmed_succeeded")
        self.assertEqual(self.oa.accepted_count(), 1)

    def test_execute_exception_then_recover_calls_adapter_once_and_escalates(self):
        op = self.submit()
        failing = FailingAdapter(ConnectionError())
        unknown = self.runtime.dispatch(op, failing)
        self.assertEqual((unknown["status"], unknown.get("reason")),
                         ("outcome_unknown", "ConnectionError"))
        self.assertEqual((failing.execute_calls,
                          len(self.runtime.get_operation(op)["attempts"])), (1, 1))
        silent = SilentAdapter()
        for _ in range(2):
            self.runtime.recover(silent)
        self.assertEqual((silent.execute_calls, failing.execute_calls), (0, 1))
        escalated = self.runtime.get_operation(op)
        self.assertEqual((escalated["status"], escalated.get("reason")),
                         ("outcome_unknown", "NO_AUTHORITATIVE_RESULT"))
        self.assertEqual(self.runtime.get_work("demo")["status"], "needs_attention")

    def test_new_reconcile_failure_reason_is_recorded(self):
        op = self.submit()
        self.runtime.dispatch(op, FailingAdapter(TimeoutError()))
        self.runtime.reconcile(op, FailingAdapter(ConnectionError()))
        again = self.runtime.reconcile(op, FailingAdapter(ConnectionError()))
        self.assertEqual((again["status"], again.get("reason")),
                         ("outcome_unknown", "ConnectionError"))
        self.assertEqual(len(self.events_of_type("OutcomeUnknown")), 2)

    def test_recover_with_nothing_to_do_is_idempotent(self):
        op = self.submit()
        self.runtime.dispatch(op, self.oa)
        self.assertEqual(self.runtime.recover(self.oa), [])
        version = self.runtime.get_work("demo")["state_version"]
        events = len(self.runtime.events("demo"))
        self.assertEqual(self.runtime.recover(self.oa), [])
        self.assertEqual(self.runtime.get_work("demo")["state_version"], version)
        self.assertEqual(len(self.runtime.events("demo")), events)

    def test_real_crash_recovery_yields_exactly_one_external_application(self):
        op = self.submit()
        child = subprocess.run([sys.executable, "-m", "work_runtime", "worker", "--runtime", self.path,
                                "--oa", self.oa_path, "--operation", op, "--crash-after-effect"], check=False)
        self.assertEqual(child.returncode, 73)
        self.assertEqual((self.runtime.get_operation(op)["status"], self.oa.accepted_count()),
                         ("dispatched", 1))
        counting = CountingAdapter(FakeOA(self.oa_path))
        restarted = Runtime(self.path, ExpensePolicy(), demo_grants())
        for _ in range(3):
            restarted.recover(counting)
        restarted.dispatch(op, counting)
        replay = action(restarted, command_id="replay-after-recovery")
        self.assertEqual((replay["decision"], replay["operation_id"]), ("accepted", op))
        self.assertEqual(counting.executed, 0)
        self.assertEqual(restarted.get_operation(op)["status"], "confirmed_succeeded")
        self.assertEqual(self.oa.accepted_count(), 1)

    def test_recovery_business_dedup_returns_existing_operation(self):
        op = self.submit()
        self.runtime.dispatch(op, self.oa)
        restarted = Runtime(self.path, ExpensePolicy(), demo_grants())
        replay = action(restarted, command_id="same-operation-new-command")
        self.assertEqual((replay["decision"], replay["operation_id"]), ("accepted", op))
        self.assertEqual(replay["operation_status_at_decision"], "confirmed_succeeded")
        self.assertEqual(len(self.events_of_type("OperationPrepared")), 1)
        self.assertEqual(self.oa.accepted_count(), 1)


if __name__ == "__main__":
    unittest.main()
