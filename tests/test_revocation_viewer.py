"""S8 viewer slice: D37 read-only derived revocation fields (reader + API).

Pins the ratified D37 reader additions on stores built through the real public
Runtime API (never hand-written business state): ``evidence[].id`` (valid
string else null, raw retained), top-level ``revoked_evidence`` and
``completion_revoked_evidence_ids`` derived inside the same read-only
snapshot. Cancellation completions acknowledge operations and never invent
proof citations; raw payloads and exact integers stay untouched; reading
writes nothing. Direct SQL edits appear only in malformed-store robustness
tests, following the established test_inspection.py pattern.
"""

import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
import uuid
from pathlib import Path

from work_runtime.adapters import FakeOA
from work_runtime.demo import (action, demo_grants, document, initialize,
                               prerequisites, send)
from work_runtime.inspection import ReadOnlyInspector
from work_runtime.policy import ExpensePolicy, canonical
from work_runtime.runtime import Runtime


def viewer_grants():
    """Demo grants plus the trusted-local revoke rights used by the core."""
    grants = demo_grants()
    grants["root"] = {"work.intervene"}
    grants["finance"] = {"evidence.write", "evidence.revoke"}
    return grants


class ViewerFixture(unittest.TestCase):
    """Real stores through public commands; no fabricated business state."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.path = str(self.dir / "runtime.sqlite")

    def runtime(self):
        return Runtime(self.path, ExpensePolicy(), viewer_grants())

    def proof_row(self, work_id, kind):
        """The stored (source, event_id, body) of one proof by kind."""
        db = sqlite3.connect(self.path)
        try:
            for source, event_id, body in db.execute(
                    "SELECT source, event_id, body FROM evidence WHERE work_id=?",
                    (work_id,)):
                parsed = json.loads(body)
                if parsed.get("kind") == kind:
                    return source, event_id, parsed
        finally:
            db.close()
        raise AssertionError("no %s proof recorded for %s" % (kind, work_id))

    def revoke_proof(self, runtime, work_id, kind, actor="finance"):
        """Revoke one real proof through the public command; return its row."""
        source, event_id, body = self.proof_row(work_id, kind)
        version = runtime.get_work(work_id)["state_version"]
        receipt = runtime.command(actor, uuid.uuid4().hex, work_id,
                                  "revoke_evidence",
                                  {"source": source, "event_id": event_id,
                                   "reason": "withdrawn"}, version)
        self.assertEqual(receipt["decision"], "accepted", receipt)
        return source, event_id, body

    def succeeded_store(self, work_id="demo", amount=120000, doc=None):
        """Drive a real expense work to closed/succeeded with verified proofs."""
        runtime = self.runtime()
        initialize(runtime, work_id=work_id,
                   doc=doc or document(amount=amount))
        prerequisites(runtime, work_id=work_id)
        send(runtime, work_id, "register_wait", {
            "requirement_id": "E05:EXP-001", "deadline": 2000000000,
            "owner": "finance"})
        receipt = action(runtime, work_id=work_id)
        self.assertEqual(receipt["decision"], "accepted", receipt)
        runtime.dispatch(receipt["operation_id"],
                         FakeOA(str(self.dir / ("oa-%s.sqlite" % work_id))))
        accepted = send(runtime, work_id, "request_completion")
        self.assertEqual(accepted["decision"], "accepted", accepted)
        return runtime

    def cancelled_store(self, work_id="demo"):
        """Drive a real work to closed/cancelled with an acknowledged effect."""
        runtime = self.runtime()
        initialize(runtime, work_id=work_id)
        prerequisites(runtime, work_id=work_id)
        receipt = action(runtime, work_id=work_id)
        operation_id = receipt["operation_id"]
        runtime.dispatch(operation_id,
                         FakeOA(str(self.dir / ("oa-%s.sqlite" % work_id))))
        send(runtime, work_id, "request_cancel", {"reason": "stop"})
        final = send(runtime, work_id, "finalize_cancel",
                     {"acknowledged_operations": [operation_id]})
        self.assertEqual(final["decision"], "accepted", final)
        return runtime

    def unbound_closed_store(self, work_id="unbound"):
        """D-1 family: close an unbound work, leaving one recorded proof."""
        runtime = self.runtime()
        send(runtime, work_id, "create_work",
             {"document": document(document_id="UNB-001")})
        send(runtime, work_id, "record_evidence",
             {"event_id": "evt-unbound", "kind": "approval",
              "data": {"digest": "d"}}, actor="finance")
        send(runtime, work_id, "request_cancel", {"reason": "stop"})
        final = send(runtime, work_id, "finalize_cancel",
                     {"acknowledged_operations": []})
        self.assertEqual(final["decision"], "accepted", final)
        return runtime

    def all_tables(self):
        db = sqlite3.connect(self.path)
        try:
            return {
                table: db.execute("SELECT * FROM %s ORDER BY 1" % table).fetchall()
                for table in ("works", "commands", "evidence", "operations",
                              "events", "metadata")
            }
        finally:
            db.close()


class DerivedFieldTests(ViewerFixture):
    def test_closed_succeeded_revoked_cited_evidence_derived(self):
        runtime = self.succeeded_store()
        source, event_id, approval = self.revoke_proof(runtime, "demo",
                                                       "approval")
        detail = ReadOnlyInspector(self.path).work_detail("demo")
        # evidence[].id mirrors each stored body id (valid strings here).
        db = sqlite3.connect(self.path)
        columns = {(row[0], row[1]): row[2] for row in db.execute(
            "SELECT source, event_id, body FROM evidence")}
        db.close()
        for item in detail["evidence"]:
            body = json.loads(columns[(item["source"], item["event_id"])])
            self.assertEqual(item["id"], body["id"])
            self.assertEqual(item["body_raw"],
                             columns[(item["source"], item["event_id"])])
        self.assertEqual(detail["revoked_evidence"], [
            {"id": approval["id"], "source": source, "event_id": event_id,
             "kind": "approval", "status": "revoked"}])
        # The completion record cites verified proofs; the revoked one counts.
        completion = json.loads(detail["work"]["completion_raw"])
        self.assertIn(approval["id"], completion["evidence"])
        self.assertEqual(detail["completion_revoked_evidence_ids"],
                         [approval["id"]])

    def test_closed_cancelled_revoked_evidence_has_no_citations(self):
        runtime = self.cancelled_store()
        _, _, approval = self.revoke_proof(runtime, "demo", "approval")
        detail = ReadOnlyInspector(self.path).work_detail("demo")
        self.assertEqual(detail["work"]["status"], "closed")
        self.assertEqual(detail["work"]["outcome"], "cancelled")
        self.assertEqual(len(detail["revoked_evidence"]), 1)
        self.assertEqual(detail["revoked_evidence"][0]["id"], approval["id"])
        self.assertEqual(detail["revoked_evidence"][0]["status"], "revoked")
        # Cancellation completions acknowledge operations, never citations.
        completion = json.loads(detail["work"]["completion_raw"])
        self.assertNotIn("evidence", completion)
        self.assertIn("acknowledged_operations", completion)
        self.assertEqual(detail["completion_revoked_evidence_ids"], [])

    def test_unbound_closed_work_revoked_derivation(self):
        runtime = self.unbound_closed_store()
        _, _, proof = self.revoke_proof(runtime, "unbound", "approval")
        detail = ReadOnlyInspector(self.path).work_detail("unbound")
        self.assertEqual(detail["work"]["status"], "closed")
        self.assertEqual(detail["work"]["outcome"], "cancelled")
        self.assertEqual(detail["revoked_evidence"], [
            {"id": proof["id"], "source": "finance", "event_id": "evt-unbound",
             "kind": "approval", "status": "revoked"}])
        self.assertEqual(detail["completion_revoked_evidence_ids"], [])

    def test_open_work_with_revoked_evidence_lists_without_citations(self):
        runtime = self.runtime()
        initialize(runtime)
        prerequisites(runtime)
        _, _, approval = self.revoke_proof(runtime, "demo", "approval")
        detail = ReadOnlyInspector(self.path).work_detail("demo")
        self.assertNotEqual(detail["work"]["status"], "closed")
        self.assertIsNone(detail["work"]["completion_raw"])
        self.assertEqual([entry["id"] for entry in detail["revoked_evidence"]],
                         [approval["id"]])
        self.assertEqual(detail["completion_revoked_evidence_ids"], [])

    def test_clean_works_have_empty_derived_arrays(self):
        self.succeeded_store()
        detail = ReadOnlyInspector(self.path).work_detail("demo")
        self.assertEqual(detail["revoked_evidence"], [])
        self.assertEqual(detail["completion_revoked_evidence_ids"], [])
        db = sqlite3.connect(self.path)
        columns = {(row[0], row[1]): row[2] for row in db.execute(
            "SELECT source, event_id, body FROM evidence")}
        db.close()
        for item in detail["evidence"]:
            self.assertEqual(item["id"],
                             json.loads(columns[(item["source"],
                                                 item["event_id"])])["id"])


class MalformedStoreTests(ViewerFixture):
    """Reader robustness on corrupted rows: degrade, never crash or invent."""

    def _update_evidence(self, source, event_id, parsed):
        db = sqlite3.connect(self.path)
        db.execute("UPDATE evidence SET body=? WHERE source=? AND event_id=?",
                   (canonical(parsed), source, event_id))
        db.commit()
        db.close()

    def _update_state(self, mutate):
        db = sqlite3.connect(self.path)
        state = json.loads(db.execute(
            "SELECT state FROM works WHERE id='demo'").fetchone()[0])
        mutate(state)
        db.execute("UPDATE works SET state=? WHERE id='demo'",
                   (canonical(state),))
        db.commit()
        db.close()

    def test_malformed_evidence_id_degrades_to_null(self):
        runtime = self.succeeded_store()
        self.revoke_proof(runtime, "demo", "approval")
        # Re-read the stored revoked row, then corrupt only its id.
        revoked_source, revoked_event, revoked_body = self.proof_row(
            "demo", "approval")
        revoked_key = (revoked_source, revoked_event)
        self.assertEqual(revoked_body["status"], "revoked")
        other_source, other_event, other_body = self.proof_row(
            "demo", "duplicate_clear")
        revoked_body = dict(revoked_body)
        revoked_body["id"] = 7          # revoked row with an invalid id
        self._update_evidence(revoked_source, revoked_event, revoked_body)
        other_body = dict(other_body)
        del other_body["id"]             # clean row with a missing id
        self._update_evidence(other_source, other_event, other_body)
        detail = ReadOnlyInspector(self.path).work_detail("demo")
        by_key = {(item["source"], item["event_id"]): item
                  for item in detail["evidence"]}
        self.assertIsNone(by_key[revoked_key]["id"])
        self.assertIsNone(by_key[(other_source, other_event)]["id"])
        # Raw content stays exactly available for both corrupted rows.
        self.assertEqual(json.loads(by_key[revoked_key]["body_raw"])["id"], 7)
        self.assertNotIn("id", json.loads(
            by_key[(other_source, other_event)]["body_raw"]))
        self.assertEqual(detail["revoked_evidence"], [
            {"id": None, "source": revoked_key[0], "event_id": revoked_key[1],
             "kind": "approval", "status": "revoked"}])
        # An invalid revoked id can never appear as a cited revoked id.
        self.assertEqual(detail["completion_revoked_evidence_ids"], [])

    def test_malformed_completion_citations_ignored(self):
        runtime = self.succeeded_store()
        _, _, approval = self.revoke_proof(runtime, "demo", "approval")
        revoked_id = approval["id"]

        def cited(value):
            def mutate(state):
                state["completion"]["evidence"] = value
            return mutate

        cases = [
            ([revoked_id, 7, None, "", revoked_id, "not-an-id"],
             [revoked_id]),      # valid strings only, citation order, deduped
            ("oops", []),        # non-list citations contribute nothing
            ([7, None, ""], []),  # no valid string at all
        ]
        for value, expected in cases:
            with self.subTest(citations=value):
                self._update_state(cited(value))
                detail = ReadOnlyInspector(self.path).work_detail("demo")
                self.assertEqual(detail["completion_revoked_evidence_ids"],
                                 expected)


class ExactnessTests(ViewerFixture):
    def test_exact_raw_and_huge_integers_survive(self):
        huge = 10000000000000001
        runtime = self.succeeded_store(amount=huge)
        before = ReadOnlyInspector(self.path).work_detail("demo")
        before_approval = [item for item in before["evidence"]
                           if item["kind"] == "approval"][0]
        _, _, approval = self.revoke_proof(runtime, "demo", "approval")
        after = ReadOnlyInspector(self.path).work_detail("demo")
        after_approval = [item for item in after["evidence"]
                          if item["kind"] == "approval"][0]
        # Revocation preserves identity and data; only status changed.
        self.assertEqual(after_approval["id"], approval["id"])
        self.assertEqual(after_approval["id"], before_approval["id"])
        self.assertEqual(after_approval["data_raw"], before_approval["data_raw"])
        self.assertEqual(after["work"]["completion_raw"],
                         before["work"]["completion_raw"])
        # Huge integers stay exact in every raw surface.
        for raw in (after["work"]["document_raw"], after["work"]["state_raw"],
                    after["operations"][0]["document_raw"]):
            self.assertIn(str(huge), raw)


class ZeroWriteTests(ViewerFixture):
    def test_full_read_pass_writes_nothing(self):
        runtime_a = self.succeeded_store(work_id="w-a")
        self.revoke_proof(runtime_a, "w-a", "approval")
        # Distinct content: the policy derives the operation business key from
        # the document, so two works with identical documents would collide.
        self.succeeded_store(work_id="w-b",
                             doc=document(amount=130000, invoice_id="INV-002",
                                          document_id="EXP-002"))
        before = self.all_tables()
        inspector = ReadOnlyInspector(self.path)
        inspector.summary()
        listing = inspector.list_works()
        for item in listing["works"]:
            inspector.work_detail(item["id"])
            page = inspector.events(item["id"])
            self.assertIsInstance(page["next_after"], str)
        self.assertEqual(self.all_tables(), before)


class ApiWorkDetailTests(ViewerFixture):
    """The loopback API passes the derived fields through unchanged."""

    def setUp(self):
        super().setUp()
        runtime = self.succeeded_store()
        self.approval_source, self.approval_event, self.approval = \
            self.revoke_proof(runtime, "demo", "approval")
        # Lazy import: this module must not load the backend at import time
        # (tests/test_ui_cli.py pins that CLI behavior in a fresh process).
        from work_runtime.ui_server import make_ui_server
        self.server = make_ui_server(self.path, 0)
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever,
                                  kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)

    def get_work(self, work_id="demo"):
        connection = http.client.HTTPConnection("127.0.0.1", self.port,
                                                timeout=10)
        connection.request("GET", "/api/work?id=" + work_id)
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response, json.loads(body)

    def test_api_work_returns_derived_revocation_fields(self):
        response, payload = self.get_work()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"),
                         "application/json; charset=utf-8")
        self.assertEqual(payload["revoked_evidence"], [
            {"id": self.approval["id"], "source": self.approval_source,
             "event_id": self.approval_event, "kind": "approval",
             "status": "revoked"}])
        self.assertEqual(payload["completion_revoked_evidence_ids"],
                         [self.approval["id"]])
        revoked = [item for item in payload["evidence"]
                   if item["source"] == self.approval_source][0]
        self.assertIsInstance(revoked["id"], str)
        self.assertEqual(revoked["id"], self.approval["id"])
        self.assertEqual(revoked["status"], "revoked")

    def test_api_work_malformed_id_is_null_over_http(self):
        _, _, body = self.proof_row("demo", "approval")
        body = dict(body)
        body["id"] = 7
        db = sqlite3.connect(self.path)
        db.execute("UPDATE evidence SET body=? WHERE source='finance' "
                   "AND event_id=?", (canonical(body), body["event_id"]))
        db.commit()
        db.close()
        _, payload = self.get_work()
        revoked = [item for item in payload["evidence"]
                   if item["source"] == "finance"][0]
        self.assertIsNone(revoked["id"])
        self.assertEqual(payload["revoked_evidence"][0]["id"], None)
        self.assertEqual(payload["completion_revoked_evidence_ids"], [])


if __name__ == "__main__":
    unittest.main()
