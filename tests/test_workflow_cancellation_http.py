"""Cancellation of a bound workflow through the private workflow service.

The bridge owns no cancellation engine of its own: it exposes the runtime's
own ``request_cancel`` and ``finalize_cancel`` commands, so the platform
cancels exactly the way a trusted local caller would — same transaction,
same compare-and-swap, same command receipts, same acknowledgement gate.
The tests run a real service over a real SQLite store on a loopback socket
and assert stored truth (rows, events, effect counts), never a status code
alone.
"""

import http.client
import json
import os
import sqlite3
import tempfile
import unittest

from work_runtime.runtime import Runtime
from work_runtime.workflow import WorkflowEngine
from work_runtime.workflow_demo import DemoBusinessSystem
from work_runtime.workflow_server import API_PREFIX, serve

try:
    from workflow_support import (build, decide, demo_grants, instantiate,
                                  scenario_template, submit_valid, version_of)
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import (build, decide, demo_grants, instantiate,
                                        scenario_template, submit_valid,
                                        version_of)

WORK_ID = "W-1"
OWNER = "coordinator"
ADMIN = "ops-admin"


class CancellationHttpTestCase(unittest.TestCase):
    """A real service over a real store; the ticker never dispatches."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-cancel-http-")
        self.path = os.path.join(self.folder, "runtime.sqlite")
        grants = demo_grants()
        grants[ADMIN] = {"work.intervene"}
        self.runtime, self.engine = build(self.path, grants=grants,
                                          runner="workflow-runner")
        self.template = scenario_template()
        published = self.engine.publish_template(OWNER, self.template)
        self.assertEqual(published["decision"], "accepted", published)
        # No adapter on the service: the ticker only advances, so a prepared
        # effect stays prepared until a test dispatches it deliberately.
        self.server, self.ticker, self.lock = serve(
            self.runtime, self.engine, None, host="127.0.0.1", port=0,
            interval_s=0.05)
        self.host, self.port = (self.server.server_address[0],
                                self.server.server_address[1])
        self.counter = 0

    def tearDown(self):
        self.ticker.stop()
        self.server.shutdown()
        self.server.server_close()
        if self.lock is not None:
            self.lock.release()

    # -- helpers ---------------------------------------------------------

    def call(self, method, path, body=None):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=10)
        try:
            payload = json.dumps(body).encode("utf-8") if body is not None else None
            headers = {"Content-Type": "application/json"} if payload else {}
            connection.request(method, path, payload, headers)
            response = connection.getresponse()
            raw = response.read().decode("utf-8")
            return response.status, (json.loads(raw) if raw else {})
        finally:
            connection.close()

    def next_id(self, label):
        self.counter += 1
        return label + "-" + str(self.counter)

    def bind(self):
        receipt = instantiate(self.runtime, self.engine, WORK_ID)
        self.assertEqual(receipt["decision"], "accepted", receipt)

    def drive_to_human(self):
        """N01–N03 accepted; N04 waits for the safety review."""
        self.bind()
        self.engine.advance(WORK_ID, 1000)
        for node, name in (("n01", "intake"), ("n02", "analysis"),
                           ("n03", "proposal")):
            submitted = submit_valid(self.engine, self.runtime, WORK_ID, node, name)
            self.assertEqual(submitted["decision"], "accepted", submitted)

    def drive_to_dispatch(self):
        """Both reviews approved; the dispatch operation is prepared."""
        self.drive_to_human()
        reference = self.proposal_reference()
        for kind, source in (("safety_review", "reviewer-a"),
                             ("project_approval", "reviewer-b")):
            decided = decide(self.runtime, self.engine, WORK_ID, kind, source,
                             "approved", reference["digest"],
                             reference["revision"])
            self.assertEqual(decided["decision"], "accepted", decided)

    def proposal_reference(self):
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT revision,digest FROM workflow_objects "
                             "WHERE work_id=? AND name='proposal'",
                             (WORK_ID,)).fetchone()
        finally:
            db.close()
        return {"name": "proposal", "revision": row[0], "digest": row[1]}

    def operation_rows(self):
        db = sqlite3.connect(self.path)
        try:
            return [json.loads(row[0]) for row in db.execute(
                "SELECT body FROM operations WHERE work_id=?", (WORK_ID,))]
        finally:
            db.close()

    def events(self):
        return [entry["type"] for entry in self.runtime.events(WORK_ID)]

    def cancel_body(self, reason="duplicates found", actor=OWNER, **extra):
        body = {"actor": actor, "reason": reason,
                "commandId": self.next_id("cancel"),
                "expectedVersion": version_of(self.runtime, WORK_ID)}
        body.update(extra)
        return body

    def request_cancel(self, **kwargs):
        return self.call("POST", API_PREFIX + "/instances/" + WORK_ID + "/cancel",
                         self.cancel_body(**kwargs))

    def finalize_cancel(self, acknowledged, command_id=None,
                        expected_version=None, **extra):
        body = {"actor": OWNER, "acknowledgedOperations": list(acknowledged),
                "commandId": command_id or self.next_id("cancel-final"),
                "expectedVersion": (version_of(self.runtime, WORK_ID)
                                    if expected_version is None
                                    else expected_version)}
        body.update(extra)
        return self.call("POST", API_PREFIX + "/instances/" + WORK_ID
                         + "/cancel/finalize", body)


class RequestCancelTests(CancellationHttpTestCase):
    def test_the_owner_may_request_and_the_workflow_stops(self):
        self.drive_to_human()
        status, body = self.request_cancel()
        self.assertEqual(status, 200, body)
        cancellation = body["cancellation"]
        self.assertTrue(cancellation["requested"])
        self.assertEqual(cancellation["requestedBy"], OWNER)
        self.assertEqual(cancellation["reason"], "duplicates found")
        # Stored truth: the node, the intent and the wait are cancelled.
        work = self.runtime.get_work(WORK_ID)
        self.assertEqual(work["cancellation"]["requested_by"], OWNER)
        self.assertEqual(work["status"], "needs_attention")
        view = self.engine.instance(WORK_ID)
        human = [entry for entry in view["nodes"] if entry["node"] == "n04"][0]
        self.assertEqual(human["state"], "cancelled")
        intents = {entry["id"]: entry["status"] for entry in view["intents"]}
        self.assertTrue(intents)
        # The finished tasks stay done, the waiting one is cancelled - and
        # nothing new opens behind them: a cancelling work stops.
        self.assertEqual(set(intents.values()), {"done", "cancelled"})
        nodes = {entry["node"]: (entry["attempt"], entry["state"])
                 for entry in view["nodes"]}
        self.assertEqual(nodes["n02"], (1, "completed"))
        self.assertEqual(nodes["n03"], (1, "completed"))
        self.assertEqual(view["currentNode"], None)
        self.assertIn("CancellationRequested", self.events())

    def test_a_reviewer_may_not_and_an_administrator_may(self):
        self.drive_to_human()
        denied = self.request_cancel(actor="reviewer-a")
        self.assertEqual(denied[0], 403, denied)
        self.assertEqual(denied[1]["error"]["code"], "AUTHORITY_DENIED")
        self.assertIsNone(self.runtime.get_work(WORK_ID).get("cancellation"))
        accepted = self.request_cancel(actor=ADMIN)
        self.assertEqual(accepted[0], 200, accepted)
        self.assertEqual(accepted[1]["cancellation"]["requestedBy"], ADMIN)

    def test_a_missing_or_stale_expected_version_is_refused(self):
        self.drive_to_human()
        missing = self.call("POST", API_PREFIX + "/instances/" + WORK_ID
                            + "/cancel",
                            {"actor": OWNER, "reason": "stop",
                             "commandId": self.next_id("cancel")})
        self.assertEqual(missing[0], 400, missing)
        self.assertEqual(missing[1]["error"]["code"], "EXPECTED_VERSION_REQUIRED")
        stale = self.request_cancel(expectedVersion=1)
        self.assertEqual(stale[0], 409, stale)
        self.assertEqual(stale[1]["error"]["code"], "STATE_VERSION_CONFLICT")
        self.assertIsNone(self.runtime.get_work(WORK_ID).get("cancellation"))

    def test_the_same_command_replays_and_a_changed_body_conflicts(self):
        self.drive_to_human()
        body = self.cancel_body()
        first = self.call("POST", API_PREFIX + "/instances/" + WORK_ID
                          + "/cancel", body)
        self.assertEqual(first[0], 200, first)
        version = version_of(self.runtime, WORK_ID)
        replay = self.call("POST", API_PREFIX + "/instances/" + WORK_ID
                           + "/cancel", body)
        self.assertEqual(replay[0], 200, replay)
        self.assertEqual(replay[1]["cancellation"], first[1]["cancellation"])
        self.assertEqual(self.events().count("CancellationRequested"), 1)
        # A different body under the same command id is a reuse, not a replay.
        body["reason"] = "a different reason"
        reused = self.call("POST", API_PREFIX + "/instances/" + WORK_ID
                           + "/cancel", body)
        self.assertEqual(reused[0], 409, reused)
        self.assertEqual(reused[1]["error"]["code"], "COMMAND_ID_REUSED")

    def test_a_second_request_under_a_new_command_id_is_refused(self):
        self.drive_to_human()
        self.assertEqual(self.request_cancel()[0], 200)
        again = self.request_cancel(reason="another try")
        self.assertEqual(again[0], 409, again)
        self.assertEqual(again[1]["error"]["code"],
                         "CANCELLATION_ALREADY_REQUESTED")
        work = self.runtime.get_work(WORK_ID)
        self.assertEqual(work["cancellation"]["reason"], "duplicates found")

    def test_a_prepared_effect_is_never_dispatched_after_the_request(self):
        self.drive_to_dispatch()
        operations = self.operation_rows()
        self.assertEqual(len(operations), 1)
        adapter = DemoBusinessSystem(os.path.join(self.folder, "effects.sqlite"))
        status, body = self.request_cancel()
        self.assertEqual(status, 200, body)
        operation = self.operation_rows()[0]
        self.assertEqual(operation["dispatch_state"], "cancelled")
        # The ticker, a pump and a recovery pass all leave the effect alone.
        self.engine.pump(adapter, 2000)
        self.engine.recover(adapter, 3000)
        self.assertEqual(adapter.effect_count(), 0)


class FinalizeCancelTests(CancellationHttpTestCase):
    def in_flight_operation(self):
        """A real crash after the external effect, before the local record."""
        operations = self.operation_rows()
        adapter = DemoBusinessSystem(os.path.join(self.folder, "effects.sqlite"))
        operation = operations[0]

        def crash():
            raise RuntimeError("process died after the effect")

        with self.assertRaises(RuntimeError):
            self.runtime.dispatch(operation["id"], adapter, fault=crash)
        self.assertEqual(adapter.effect_count(), 1)
        return adapter, operation["id"]

    def test_an_unresolved_effect_blocks_and_the_exact_ack_closes(self):
        self.drive_to_dispatch()
        adapter, operation_id = self.in_flight_operation()
        status, body = self.request_cancel()
        self.assertEqual(status, 200, body)

        read = self.call("GET", API_PREFIX + "/instances/" + WORK_ID
                         + "/cancellation")
        self.assertEqual(read[0], 200, read)
        state = read[1]
        self.assertEqual(state["state"], "requested")
        self.assertEqual(state["unresolvedOperations"], [operation_id])
        self.assertEqual(state["requiredAcknowledgements"], [])

        unresolved = self.finalize_cancel([])
        self.assertEqual(unresolved[0], 409, unresolved)
        self.assertEqual(unresolved[1]["error"]["code"], "OUTCOME_UNRESOLVED")

        # Recovery looks the in-flight effect up; it is never repeated.
        self.engine.recover(adapter, 4000)
        self.assertEqual(adapter.effect_count(), 1)
        read = self.call("GET", API_PREFIX + "/instances/" + WORK_ID
                         + "/cancellation")
        self.assertEqual(read[1]["unresolvedOperations"], [])
        self.assertEqual(read[1]["requiredAcknowledgements"], [operation_id])

        mismatched = self.finalize_cancel([])
        self.assertEqual(mismatched[0], 409, mismatched)
        self.assertEqual(mismatched[1]["error"]["code"],
                         "CANCEL_ACKNOWLEDGEMENT_MISMATCH")
        # The bridge carries the required ids as the error's findings.
        self.assertEqual(mismatched[1]["error"].get("findings"), [operation_id])

        closed = self.finalize_cancel([operation_id])
        self.assertEqual(closed[0], 200, closed)
        self.assertTrue(closed[1]["cancellation"]["finalized"])
        self.assertEqual(closed[1]["cancellation"]["acknowledgedOperations"],
                         [operation_id])
        work = self.runtime.get_work(WORK_ID)
        self.assertEqual(work["status"], "closed")
        self.assertEqual(work["outcome"], "cancelled")
        # The confirmed effect is retained in the closure, never erased.
        acknowledged = work["completion"]["acknowledged_operations"]
        self.assertEqual([entry["operation_id"] for entry in acknowledged],
                         [operation_id])
        self.assertTrue(acknowledged[0]["external_id"])
        self.assertIn("WorkCancelled", self.events())

    def test_the_finalize_receipt_replays_and_a_new_key_is_refused(self):
        self.drive_to_dispatch()
        operations = self.operation_rows()
        adapter = DemoBusinessSystem(os.path.join(self.folder, "effects.sqlite"))
        self.runtime.dispatch(operations[0]["id"], adapter)
        self.assertEqual(adapter.effect_count(), 1)
        self.assertEqual(self.request_cancel()[0], 200)
        operation_id = self.operation_rows()[0]["id"]
        # A replay carries the command's own version: the compare-and-swap
        # the caller observed when it first issued the command.
        observed = version_of(self.runtime, WORK_ID)
        first = self.finalize_cancel([operation_id], command_id="cancel-final-replay",
                                     expected_version=observed)
        self.assertEqual(first[0], 200, first)
        replay = self.finalize_cancel([operation_id], command_id="cancel-final-replay",
                                      expected_version=observed)
        self.assertEqual(replay[0], 200, replay)
        self.assertEqual(replay[1]["cancellation"], first[1]["cancellation"])
        self.assertEqual(self.events().count("WorkCancelled"), 1)
        again = self.finalize_cancel([operation_id],
                                     command_id="cancel-final-second")
        self.assertEqual(again[0], 409, again)
        self.assertEqual(again[1]["error"]["code"], "WORK_NOT_ACTIONABLE")

    def test_finalize_without_a_request_is_refused(self):
        self.drive_to_human()
        refused = self.finalize_cancel([])
        self.assertEqual(refused[0], 409, refused)
        self.assertEqual(refused[1]["error"]["code"], "CANCELLATION_NOT_REQUESTED")

    def test_the_final_cancelled_state_is_not_a_success_proof(self):
        self.drive_to_dispatch()
        operations = self.operation_rows()
        adapter = DemoBusinessSystem(os.path.join(self.folder, "effects.sqlite"))
        self.runtime.dispatch(operations[0]["id"], adapter)
        self.assertEqual(self.request_cancel()[0], 200)
        operation_id = self.operation_rows()[0]["id"]
        closed = self.finalize_cancel([operation_id])
        self.assertEqual(closed[0], 200, closed)
        read = self.call("GET", API_PREFIX + "/instances/" + WORK_ID
                         + "/cancellation")
        self.assertEqual(read[1]["state"], "cancelled")
        self.assertEqual(read[1]["outcome"], "cancelled")
        completion = self.call("GET", API_PREFIX + "/instances/" + WORK_ID
                               + "/completion")
        self.assertEqual(completion[0], 404, completion)
        self.assertEqual(completion[1]["error"]["code"],
                         "WORKFLOW_NOT_FINALIZED")
        success = self.call("POST", API_PREFIX + "/instances/" + WORK_ID
                            + "/finalize",
                            {"commandId": self.next_id("final"),
                             "expectedVersion": version_of(self.runtime, WORK_ID)})
        self.assertEqual(success[0], 409, success)
        self.assertIn(success[1]["error"]["code"],
                      ("WORK_NOT_ACTIONABLE", "WORKFLOW_FINALIZED"))


class CancellationReadTests(CancellationHttpTestCase):
    def test_an_active_work_has_no_cancellation(self):
        self.drive_to_human()
        read = self.call("GET", API_PREFIX + "/instances/" + WORK_ID
                         + "/cancellation")
        self.assertEqual(read[0], 200, read)
        state = read[1]
        self.assertEqual(state["state"], "none")
        self.assertIsNone(state["requestedBy"])
        self.assertEqual(state["unresolvedOperations"], [])
        self.assertEqual(state["requiredAcknowledgements"], [])
        self.assertEqual(state["operations"], [])

    def test_an_unknown_work_is_not_found(self):
        read = self.call("GET", API_PREFIX + "/instances/W-none/cancellation")
        self.assertEqual(read[0], 404, read)
        self.assertEqual(read[1]["error"]["code"], "WORK_UNKNOWN")


if __name__ == "__main__":
    unittest.main()


class AuthorizationOrderingTests(CancellationHttpTestCase):
    """A refused request leaves the workflow exactly as it was."""

    def snapshot(self):
        db = sqlite3.connect(self.path)
        try:
            return {
                "nodes": db.execute("SELECT node,attempt,state,body FROM "
                                    "workflow_nodes ORDER BY node,attempt"
                                    ).fetchall(),
                "intents": db.execute("SELECT id,status,body FROM "
                                      "workflow_intents ORDER BY id").fetchall(),
                "operations": db.execute("SELECT id,body FROM operations "
                                         "ORDER BY id").fetchall(),
                "events": self.events(),
                "version": version_of(self.runtime, WORK_ID)}
        finally:
            db.close()

    def test_a_denied_actor_changes_nothing(self):
        self.drive_to_human()
        before = self.snapshot()
        denied = self.request_cancel(actor="reviewer-a")
        self.assertEqual(denied[0], 403, denied)
        after = self.snapshot()
        self.assertEqual(after, before,
                         "a refused cancellation mutated the workflow")

    def test_a_malformed_request_changes_nothing(self):
        self.drive_to_human()
        before = self.snapshot()
        malformed = self.call("POST", API_PREFIX + "/instances/" + WORK_ID
                              + "/cancel",
                              {"actor": OWNER, "commandId": self.next_id("cancel"),
                               "expectedVersion": version_of(self.runtime, WORK_ID)})
        self.assertEqual(malformed[0], 400, malformed)
        self.assertEqual(malformed[1]["error"]["code"], "REASON_REQUIRED")
        self.assertEqual(self.snapshot(), before)

    def test_a_duplicate_request_changes_nothing_more(self):
        self.drive_to_human()
        self.assertEqual(self.request_cancel()[0], 200)
        after_request = self.snapshot()
        again = self.request_cancel(reason="another try")
        self.assertEqual(again[0], 409, again)
        self.assertEqual(again[1]["error"]["code"],
                         "CANCELLATION_ALREADY_REQUESTED")
        self.assertEqual(self.snapshot(), after_request)


class PartialCreationTests(CancellationHttpTestCase):
    """A work may be cancelled between the stages of its creation."""

    def create_work_only(self):
        receipt = self.runtime.command(
            OWNER, self.next_id("create"), WORK_ID, "create_work",
            {"document": {"id": "H-001", "subject": "east parapet"}}, None)
        self.assertEqual(receipt["decision"], "accepted", receipt)

    def test_a_work_without_a_bound_workflow_may_be_cancelled(self):
        self.create_work_only()
        status, body = self.request_cancel()
        self.assertEqual(status, 200, body)
        self.assertTrue(body["cancellation"]["requested"])
        self.assertEqual(body["instanceView"], "unavailable")
        # The receipt is the truth: it is readable and it is accepted.
        receipt = self.call("GET", API_PREFIX + "/commands/"
                            + body_cancellation_command(self) + "?workId=" + WORK_ID
                            + "&actor=" + OWNER)
        self.assertEqual(receipt[0], 200, receipt)
        self.assertEqual(receipt[1]["receipt"]["decision"], "accepted")
        read = self.call("GET", API_PREFIX + "/instances/" + WORK_ID
                         + "/cancellation")
        self.assertEqual(read[0], 200, read)
        self.assertEqual(read[1]["state"], "requested")
        self.assertEqual(read[1]["operations"], [])
        work = self.runtime.get_work(WORK_ID)
        self.assertEqual(work["cancellation"]["requested_by"], OWNER)

    def test_an_unknown_work_is_not_created_by_cancelling_it(self):
        status, body = self.call("POST", API_PREFIX + "/instances/W-none/cancel",
                                 {"actor": OWNER, "reason": "stop",
                                  "commandId": self.next_id("cancel"),
                                  "expectedVersion": 1})
        self.assertEqual(status, 404, body)
        self.assertEqual(body["error"]["code"], "WORK_UNKNOWN")
        db = sqlite3.connect(self.path)
        try:
            count = db.execute("SELECT COUNT(*) FROM works WHERE id='W-none'"
                               ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(count, 0)
        read = self.call("GET", API_PREFIX + "/instances/W-none/cancellation")
        self.assertEqual(read[0], 404, read)
        self.assertEqual(read[1]["error"]["code"], "WORK_UNKNOWN")


def body_cancellation_command(case):
    """The command id of the last request_cancel a case issued."""
    return "cancel-" + str(case.counter)
