"""An in-flight dispatch is not an absent effect.

The lease is per Runtime instance and in-memory. Another instance on the
same file — a restart, including one in this process — does not see it and
must still isolate. The barrier is the post-commit, pre-execute window.
"""
import threading
import unittest

import test_same_key_retry as retry_tests
from work_runtime.publishing import FakePublisher


class _GuardedPublisher:
    """Refuses the effect unless the operation is still dispatched/in_flight."""

    contract = retry_tests.DECLARED

    def __init__(self, runtime, operation_id, publisher, during=None):
        self.runtime = runtime
        self.operation_id = operation_id
        self.publisher = publisher
        self.during = during
        self.seen = []
        self.lookups = 0
        self.executes = 0

    def execute(self, key, document, digest, **kwargs):
        current = self.runtime.get_operation(self.operation_id)
        self.seen.append((current["status"], current["dispatch_state"],
                          current.get("same_key_retries", 0)))
        if (current["status"] != "dispatched"
                or current["dispatch_state"] != "in_flight"):
            raise RuntimeError("WORKFLOW_ACTION_DISPATCH_INVALID")
        if self.during is not None:
            self.during()
        self.executes += 1
        return self.publisher.execute(key, document, digest)

    def lookup(self, key):
        self.lookups += 1
        return None


def _pause_after_dispatched_commit(runtime, operation_id, paused):
    real = runtime._transaction
    fired = {"done": False}

    def wrapped():
        manager = real()

        class Proxy:
            def __enter__(self):
                return manager.__enter__()

            def __exit__(self, exc_type, exc, tb):
                result = manager.__exit__(exc_type, exc, tb)
                if exc_type is None and not fired["done"]:
                    current = runtime.get_operation(operation_id)
                    if (current["status"] == "dispatched"
                            and current["dispatch_state"] == "in_flight"):
                        fired["done"] = True
                        paused()
                return result

        return Proxy()

    runtime._transaction = wrapped


class LiveDispatchLeaseTests(unittest.TestCase):
    def setUp(self):
        self.host = retry_tests.SameKeyRetryTests()
        self.host.setUp()
        self.addCleanup(self.host.doCleanups)

    def test_cross_thread_absent_lookup_does_not_isolate_a_live_dispatch(self):
        host = self.host
        operation = host.ready_operation("publish-live-lease")
        publisher = FakePublisher(host.publisher_path)
        committed = threading.Event()
        release = threading.Event()
        overlap = {}

        def reconciler():
            self.assertTrue(committed.wait(5), "dispatch did not reach the commit barrier")
            overlap["before"] = host.runtime.reconcile(operation, adapter)
            release.set()

        def during():
            overlap["during"] = host.runtime.reconcile(operation, adapter)

        adapter = _GuardedPublisher(host.runtime, operation, publisher, during)
        _pause_after_dispatched_commit(host.runtime, operation, lambda: (committed.set(), release.wait(5)))
        worker = threading.Thread(target=reconciler, name="reconcile-live")
        worker.start()
        try:
            resolved = host.runtime.dispatch(operation, adapter)
        finally:
            committed.set()
            release.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual((overlap["before"]["status"], overlap["before"]["dispatch_state"]),
                         ("dispatched", "in_flight"))
        self.assertNotIn("same_key_retries", overlap["before"])
        self.assertEqual((overlap["during"]["status"], overlap["during"]["dispatch_state"]),
                         ("dispatched", "in_flight"))
        self.assertEqual(resolved["status"], "confirmed_succeeded")
        self.assertEqual(adapter.executes, 1)
        self.assertEqual(publisher.published_count(), 1)
        self.assertEqual(adapter.lookups, 0)
        self.assertEqual(adapter.seen, [("dispatched", "in_flight", 0)])
        self.assertNotIn("ReconciliationRequired", host.work_events())
        self.assertNotIn("SameKeyRetryArmed", host.work_events())
        self.assertNotIn("same_key_retries", host.runtime.get_operation(operation))

    def test_another_runtime_instance_still_isolates(self):
        host = self.host
        operation = host.ready_operation("publish-restart-lease")
        publisher = FakePublisher(host.publisher_path)
        adapter = _GuardedPublisher(host.runtime, operation, publisher)
        restarted = host.fresh_runtime()
        holder = {}
        committed = threading.Event()
        release = threading.Event()

        def reconciler():
            self.assertTrue(committed.wait(5))
            holder["answer"] = restarted.reconcile(
                operation, retry_tests.NeverReached(retry_tests.DECLARED))
            release.set()

        _pause_after_dispatched_commit(
            host.runtime, operation, lambda: (committed.set(), release.wait(5)))
        worker = threading.Thread(target=reconciler, name="reconcile-restart")
        worker.start()
        try:
            host.runtime.dispatch(operation, adapter)
        except RuntimeError as error:
            self.assertEqual(str(error), "WORKFLOW_ACTION_DISPATCH_INVALID")
        finally:
            committed.set()
            release.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        stored = restarted.get_operation(operation)
        self.assertEqual(stored["same_key_retries"], 1)
        self.assertIn(stored["status"], ("prepared", "outcome_unknown"))
        self.assertEqual(adapter.executes, 0)

    def test_execute_exception_still_records_unknown_and_keeps_one_retry(self):
        host = self.host
        operation = host.ready_operation("publish-exception-lease")
        unknown = host.runtime.dispatch(operation, retry_tests.NeverReached(retry_tests.DECLARED))
        self.assertEqual(unknown["status"], "outcome_unknown")
        self.assertNotIn("same_key_retries", unknown)
        armed = host.runtime.reconcile(operation, retry_tests.NeverReached(retry_tests.DECLARED))
        self.assertEqual((armed["status"], armed["dispatch_state"], armed["same_key_retries"]),
                         ("prepared", "ready", 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
