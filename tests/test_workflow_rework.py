"""The responsible owner authorizes one controlled candidate rework.

After a terminal Agent quality failure the trusted work manager may
authorize **one** rework per workflow: the old failure, its report and
the terminal record stay on the record, a new monotonic attempt opens
with its own ticket under the original session, nothing is reset — not
the quality allowance, not the material generation, not the revalidation
queue — and the new candidate must pass the original checks honestly.

The tests run on a real store and assert stored truth (rows, attempts,
operations, events), never a receipt alone. The terminal shape is the
deployed one: three spent quality attempts, one failed material attempt
behind a pending revalidation queue.
"""

import json
import sqlite3
import unittest
import uuid

from work_runtime.policy import canonical
from work_runtime.workflow import WorkflowError

try:
    from workflow_support import (VALID_RESULTS, input_digest_of, send,
                                  submit, version_of)
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import (VALID_RESULTS, input_digest_of, send,
                                        submit, version_of)
try:
    from test_workflow_material_revalidation import (
        OWNER, EXECUTOR, VALID_ANALYSIS, VALID_INTAKE, RevalidationTestCase,
        spent_quality_template)
except ImportError:  # pragma: no cover - repository-root import style
    from tests.test_workflow_material_revalidation import (
        OWNER, EXECUTOR, VALID_ANALYSIS, VALID_INTAKE, RevalidationTestCase,
        spent_quality_template)

REASON = "the owner authorizes one controlled rework"
VALID_PROPOSAL = VALID_RESULTS["proposal"]


class ReworkTestCase(RevalidationTestCase):
    """The deployed terminal shape: the material attempt failed on quality.

    n01 spent its three quality attempts (two rejected candidates, one
    accepted), the manager replaced the source material while n03 waited,
    and the material attempt 4 failed the published validation: the
    workflow stopped terminally at a failed agent node with the
    revalidation queue still pending.
    """

    template = spent_quality_template()
    quality_failures = 2

    def setUp(self):
        super().setUp()
        self.fail_terminally()

    def fail_terminally(self):
        """Drive the work into the terminal failed-agent shape."""
        receipt = self.replace()
        self.assertEqual("accepted", receipt["decision"], receipt)
        self.engine.advance(self.work, 2000)
        rejected = self.drive("n01", "intake", {"records": "not a list"})
        self.assertEqual("rejected", rejected["decision"], rejected)
        self.engine.advance(self.work, 2001)
        work = self.runtime.get_work(self.work)
        self.assertEqual("finished", work["workflow_status"])
        self.assertEqual("n01", work["workflow_terminal"]["node"])
        failed = self.instance("n01")[-1]
        self.assertEqual("failed", failed["state"])
        self.assertEqual("WORKFLOW_RESULT_INVALID", failed["body"]["reason"])
        self.assertEqual("material", failed["body"]["trigger"])
        self.assertEqual(4, failed["attempt"])

    def authorize(self, *, node="n01", attempt=None, input_digest=None,
                  reason=REASON, actor=OWNER, command_id=None):
        rows = self.instance(node)
        if rows:
            failed = rows[-1]
            if attempt is None:
                attempt = failed["attempt"]
            if input_digest is None:
                input_digest = failed["body"]["input_digest"]
        return self.engine.command(
            actor, command_id or uuid.uuid4().hex, self.work,
            "authorize_rework",
            {"node": node, "attempt": attempt if attempt is not None else 0,
             "input_digest": input_digest or "", "reason": reason},
            version_of(self.runtime, self.work))


class AuthorizedPathTestCase(ReworkTestCase):
    """The authorization itself."""

    def test_the_owner_authorizes_one_controlled_rework(self):
        before_instances = [(row["attempt"], row["state"],
                             canonical(row["body"]))
                            for row in self.instance("n01")]
        before_source = self.instance("s00")
        terminal = dict(self.runtime.get_work(self.work)["workflow_terminal"])
        receipt = self.authorize()
        self.assertEqual("accepted", receipt["decision"], receipt)
        # the work is working again, at the failed node
        work = self.runtime.get_work(self.work)
        self.assertEqual("active", work["workflow_status"])
        self.assertEqual("n01", work["workflow_current"])
        self.assertIsNone(work["workflow_terminal"])
        # the authorization is on the record with the failure provenance
        record = work["candidate_rework"]
        self.assertEqual("authorized", record["state"])
        self.assertEqual(1, record["cap"])
        self.assertEqual(OWNER, record["authorized_by"])
        self.assertEqual(REASON, record["reason"])
        self.assertEqual("n01", record["node"])
        self.assertEqual(4, record["from_attempt"])
        self.assertEqual(5, record["to_attempt"])
        self.assertEqual(terminal, record["terminal"])
        # the authorization wave is exactly two events
        self.assertEqual(["WorkflowReworkAuthorized", "WorkflowNodeActivated"],
                         self.events()[-2:])
        # the old failure is immutable: attempts 1-4 byte for byte
        after = [(row["attempt"], row["state"], canonical(row["body"]))
                 for row in self.instance("n01")]
        self.assertEqual(before_instances, after[:4])
        # the new attempt: monotonic, its own trigger, its own ticket
        self.assertEqual(5, len(after))
        new = self.instance("n01")[-1]
        self.assertEqual(5, new["attempt"])
        self.assertEqual("rework", new["body"]["trigger"])
        self.assertEqual("running", new["state"])
        self.assertNotEqual(
            json.loads(before_instances[-1][2])["input_digest"],
            new["body"]["input_digest"])
        # same material generation, a new input generation
        self.assertEqual(
            json.loads(before_instances[-1][2])["material_generation"],
            new["body"]["material_generation"])
        self.assertGreater(
            new["body"]["input_generation"],
            json.loads(before_instances[-1][2])["input_generation"])
        # and exactly the material the failure judged: the reworked
        # attempt re-pins the failed attempt's input revisions
        self.assertEqual(
            json.loads(before_instances[-1][2])["inputs"],
            new["body"]["inputs"])
        # the agent is asked again under a new pending intent
        intents = self.rows("SELECT id,status,body FROM workflow_intents "
                            "WHERE work_id=? AND node='n01' ORDER BY id",
                            (self.work,))
        pending = [row for row in intents if row[1] == "pending"]
        self.assertEqual(1, len(pending), intents)
        body = json.loads(pending[0][2])
        self.assertEqual(5, body["attempt"])
        # nothing is reset: the source, the budget, the queue
        self.assertEqual(before_source, self.instance("s00"))
        self.assertEqual(1, work["material_generations_used"])
        plan = work["material_revalidation"]
        self.assertEqual("revalidating", plan["state"])
        self.assertEqual(["n01", "n02", "n03"], plan["queue"])
        # the rework attempt spends no quality allowance
        quality = [row for row in self.instance("n01")
                   if row["body"]["trigger"] not in ("material", "rework")]
        self.assertEqual(3, len(quality))

    def test_the_reworked_attempt_completes_and_the_queue_continues(self):
        self.authorize()
        submitted = self.drive("n01", "intake", VALID_INTAKE)
        self.assertEqual("accepted", submitted["decision"], submitted)
        self.engine.advance(self.work, 2100)
        # the queue continues: n02 re-runs on a material attempt
        n02 = self.instance("n02")
        self.assertEqual(2, len(n02))
        self.assertEqual("material", n02[1]["body"]["trigger"])
        submitted = self.drive("n02", "analysis", VALID_ANALYSIS)
        self.assertEqual("accepted", submitted["decision"], submitted)
        self.engine.advance(self.work, 2101)
        # then n03: its old wait was bound to the replaced material
        n03 = self.instance("n03")
        self.assertEqual(2, len(n03))
        self.assertEqual("material", n03[1]["body"]["trigger"])
        self.assertEqual("cancelled", n03[0]["state"])
        self.assertEqual("MATERIAL_REPLACED", n03[0]["body"]["reason"])
        submitted = self.drive("n03", "proposal", VALID_PROPOSAL)
        self.assertEqual("accepted", submitted["decision"], submitted)
        self.engine.advance(self.work, 2102)
        work = self.runtime.get_work(self.work)
        self.assertEqual("finished", work["workflow_status"])
        self.assertEqual("revalidated",
                         work["material_revalidation"]["state"])
        # the source read was never re-run
        self.assertEqual(1, len(self.instance("s00")))
        self.assertEqual(2, self.object_revision("sources")["revision"])
        # and the accepted workflow is grantable
        accepted = self.engine.command(
            "workflow-runner", uuid.uuid4().hex, self.work,
            "finalize_workflow_success", {},
            version_of(self.runtime, self.work))
        self.assertEqual("accepted", accepted["decision"], accepted)
        # the failed attempt is still on the record after the acceptance
        failed = self.instance("n01")[3]
        self.assertEqual("failed", failed["state"])
        self.assertEqual("WORKFLOW_RESULT_INVALID", failed["body"]["reason"])

    def test_the_reworked_attempt_fails_terminally_and_nothing_retries(self):
        self.authorize()
        rejected = self.drive("n01", "intake", {"records": "not a list"})
        self.assertEqual("rejected", rejected["decision"], rejected)
        self.engine.advance(self.work, 2100)
        n01 = self.instance("n01")
        self.assertEqual(5, len(n01))
        self.assertEqual("failed", n01[4]["state"])
        self.assertEqual("WORKFLOW_RESULT_INVALID", n01[4]["body"]["reason"])
        self.assertEqual("rework", n01[4]["body"]["trigger"])
        work = self.runtime.get_work(self.work)
        self.assertEqual("finished", work["workflow_status"])
        self.assertEqual("n01", work["workflow_terminal"]["node"])
        # no automatic rework: a second authorization is refused
        again = self.authorize()
        self.assertEqual("rejected", again["decision"], again)
        self.assertEqual("WORKFLOW_REWORK_ALREADY_AUTHORIZED", again["code"])


class CapAndIdentityTestCase(ReworkTestCase):
    """One authorization per workflow, exactly once, whoever asks again."""

    def test_the_cap_is_one_and_the_receipt_replays_exactly(self):
        failed_digest = self.instance("n01")[-1]["body"]["input_digest"]
        version = version_of(self.runtime, self.work)
        payload = {"node": "n01", "attempt": 4,
                   "input_digest": failed_digest, "reason": REASON}
        first = self.engine.command(OWNER, "rework-once", self.work,
                                    "authorize_rework", payload, version)
        self.assertEqual("accepted", first["decision"], first)
        # the exact duplicate — same key, same body, same version —
        # replays the stored receipt
        replay = self.runtime.command(OWNER, "rework-once", self.work,
                                      "authorize_rework", payload, version)
        self.assertEqual(first, replay)
        # a new key cannot buy a second authorization
        second = self.authorize(attempt=4, input_digest=failed_digest)
        self.assertEqual("rejected", second["decision"], second)
        self.assertEqual("WORKFLOW_REWORK_ALREADY_AUTHORIZED", second["code"])
        # a reused key with another body is refused
        conflict = self.authorize(command_id="rework-once", attempt=4,
                                  input_digest=failed_digest,
                                  reason="a different reason")
        self.assertEqual("rejected", conflict["decision"], conflict)
        self.assertEqual("COMMAND_ID_REUSED", conflict["code"])
        # the receipt still replays after the rework progressed
        submitted = self.drive("n01", "intake", VALID_INTAKE)
        self.assertEqual("accepted", submitted["decision"], submitted)
        self.engine.advance(self.work, 2100)
        late = self.runtime.command(OWNER, "rework-once", self.work,
                                    "authorize_rework", payload, version)
        self.assertEqual(first, late)

    def test_a_concurrent_authorization_on_the_same_version_fails(self):
        version = version_of(self.runtime, self.work)
        digest = self.instance("n01")[-1]["body"]["input_digest"]
        first = self.runtime.command(
            OWNER, "cas-1", self.work, "authorize_rework",
            {"node": "n01", "attempt": 4, "input_digest": digest,
             "reason": REASON}, version)
        self.assertEqual("accepted", first["decision"], first)
        # the second caller held the version the first one consumed
        second = self.runtime.command(
            OWNER, "cas-2", self.work, "authorize_rework",
            {"node": "n01", "attempt": 4, "input_digest": digest,
             "reason": REASON}, version)
        self.assertEqual("rejected", second["decision"], second)
        self.assertEqual("STATE_VERSION_CONFLICT", second["code"])


class ReworkGuardTestCase(ReworkTestCase):
    """Everything that must be refused writes nothing."""

    def snapshot(self):
        return (version_of(self.runtime, self.work), self.events(),
                self.rows("SELECT node,attempt,state,body FROM workflow_nodes"),
                self.rows("SELECT id,body FROM workflow_intents"))

    def test_only_the_manager_may_authorize(self):
        before = self.snapshot()
        receipt = self.authorize(actor=EXECUTOR)
        self.assertEqual("rejected", receipt["decision"], receipt)
        self.assertEqual("AUTHORITY_DENIED", receipt["code"])
        self.assertEqual(before, self.snapshot())

    def test_the_failed_attempt_and_ticket_must_be_named_exactly(self):
        before = self.snapshot()
        stale_attempt = self.authorize(attempt=3)
        self.assertEqual("rejected", stale_attempt["decision"], stale_attempt)
        self.assertEqual("WORKFLOW_ATTEMPT_STALE", stale_attempt["code"])
        stale_digest = self.authorize(input_digest="0" * 64)
        self.assertEqual("rejected", stale_digest["decision"], stale_digest)
        self.assertEqual("WORKFLOW_INPUT_STALE", stale_digest["code"])
        wrong_node = self.authorize(node="n02")
        self.assertEqual("rejected", wrong_node["decision"], wrong_node)
        self.assertEqual("WORKFLOW_REWORK_INELIGIBLE", wrong_node["code"])
        unknown_node = self.authorize(node="n99", attempt=4,
                                       input_digest="0" * 64)
        self.assertEqual("rejected", unknown_node["decision"], unknown_node)
        self.assertEqual("WORKFLOW_NODE_UNKNOWN", unknown_node["code"])
        self.assertEqual(before, self.snapshot())

    def test_the_payload_is_exact(self):
        with self.assertRaises(WorkflowError):
            self.authorize(reason="")
        with self.assertRaises(WorkflowError):
            self.engine.command(
                OWNER, uuid.uuid4().hex, self.work, "authorize_rework",
                {"node": "n01", "attempt": 4,
                 "input_digest": self.instance("n01")[-1]["body"]["input_digest"]},
                version_of(self.runtime, self.work))

    def test_a_cancelling_work_is_never_reopened(self):
        send(self.runtime, OWNER, self.work, "request_cancel",
             {"reason": "the owner stopped the work"})
        before = self.snapshot()
        receipt = self.authorize()
        self.assertEqual("rejected", receipt["decision"], receipt)
        self.assertEqual("CANCELLATION_ACTIVE", receipt["code"])
        self.assertEqual(before, self.snapshot())

    def test_a_finalized_work_is_never_reopened(self):
        self.authorize()
        for node, name, result in (("n01", "intake", VALID_INTAKE),
                                   ("n02", "analysis", VALID_ANALYSIS),
                                   ("n03", "proposal", VALID_PROPOSAL)):
            submitted = self.drive(node, name, result)
            self.assertEqual("accepted", submitted["decision"], submitted)
            self.engine.advance(self.work, 2200)
        accepted = self.engine.command(
            "workflow-runner", uuid.uuid4().hex, self.work,
            "finalize_workflow_success", {},
            version_of(self.runtime, self.work))
        self.assertEqual("accepted", accepted["decision"], accepted)
        # a frozen work accepts no command at all: the runtime's own
        # closed-work boundary refuses before the rework is even judged
        receipt = self.authorize()
        self.assertEqual("rejected", receipt["decision"], receipt)
        self.assertEqual("WORK_NOT_ACTIONABLE", receipt["code"])

    def test_an_effect_in_the_branch_blocks_the_rework(self):
        # A prepared business effect downstream of the failed node must
        # never be replayed or contradicted. A legal history cannot reach
        # this shape (the replacement that produced the terminal failure
        # already refuses such a branch), so the test writes the crafted
        # row into its own store the way a legacy deployment would carry
        # it — production code never writes this.
        db = sqlite3.connect(self.path)
        try:
            row = db.execute(
                "SELECT attempt,body FROM workflow_nodes WHERE work_id=? "
                "AND node='n02' ORDER BY attempt DESC LIMIT 1",
                (self.work,)).fetchone()
            body = json.loads(row[1])
            body["operation_id"] = "op-crafted"
            db.execute("UPDATE workflow_nodes SET body=? WHERE work_id=? "
                       "AND node='n02' AND attempt=?",
                       (canonical(body), self.work, row[0]))
            db.execute("INSERT INTO operations VALUES (?,?,?,?)",
                       ("op-crafted", "bk-crafted", self.work,
                        canonical({"id": "op-crafted", "status": "prepared",
                                   "dispatch_state": "prepared",
                                   "business_key": "bk-crafted"})))
            db.commit()
        finally:
            db.close()
        before = self.snapshot()
        receipt = self.authorize()
        self.assertEqual("rejected", receipt["decision"], receipt)
        self.assertEqual("WORKFLOW_REWORK_EFFECT_PRESENT", receipt["code"])
        self.assertEqual(before, self.snapshot())


    def test_the_rework_judges_the_material_the_failure_judged(self):
        # after the failure the manager revises a declared input through
        # the ordinary command — the rework may not silently adopt the
        # new revision under the failed ticket: it must judge the
        # material the failure judged, or refuse
        moved = send(self.runtime, OWNER, self.work, "revise_object",
                     {"name": "sources",
                      "object": {"sourceReference": {"referenceId": "REF-3"}}})
        self.assertEqual("accepted", moved["decision"], moved)
        failed = self.instance("n01")[-1]
        before = self.snapshot()
        receipt = self.authorize(attempt=failed["attempt"],
                                 input_digest=failed["body"]["input_digest"])
        self.assertEqual("rejected", receipt["decision"], receipt)
        self.assertEqual("INPUT_DEPENDENCIES_REQUIRE_REVALIDATION",
                         receipt["code"])
        drift = receipt["blockers"][0]
        self.assertEqual("sources", drift["name"])
        self.assertEqual(2, drift["accepted"]["revision"])
        self.assertEqual(3, drift["current"]["revision"])
        # nothing was written: no new attempt, the work stays terminal
        self.assertEqual(before, self.snapshot())
        self.assertEqual(4, len(self.instance("n01")))


class WaitingNotEligibleTestCase(RevalidationTestCase):
    """A work that waits is not a terminal failure."""

    template = spent_quality_template()
    quality_failures = 2

    def test_a_waiting_work_is_not_eligible(self):
        # setUp left n03 waiting for material: no terminal, no failure
        work = self.runtime.get_work(self.work)
        self.assertEqual("waiting", work["workflow_status"])
        receipt = self.engine.command(
            OWNER, uuid.uuid4().hex, self.work, "authorize_rework",
            {"node": "n03", "attempt": 1,
             "input_digest": input_digest_of(self.engine, self.work, "n03"),
             "reason": REASON},
            version_of(self.runtime, self.work))
        self.assertEqual("rejected", receipt["decision"], receipt)
        self.assertEqual("WORKFLOW_REWORK_INELIGIBLE", receipt["code"])
        self.assertEqual("waiting",
                         self.runtime.get_work(self.work)["workflow_status"])


class LateOldResultTestCase(ReworkTestCase):
    """Old tickets, old candidates and old acknowledgements are dead."""

    def test_a_late_old_candidate_cannot_advance_the_new_attempt(self):
        old = self.instance("n01")[-1]
        self.authorize()
        refused = submit(self.engine, self.runtime, self.work, "n01",
                         old["attempt"], "intake", VALID_INTAKE,
                         input_digest=old["body"]["input_digest"])
        self.assertEqual("rejected", refused["decision"], refused)
        self.assertEqual("WORKFLOW_ATTEMPT_STALE", refused["code"])
        # the new attempt still waits for its own candidate
        new = self.instance("n01")[-1]
        self.assertEqual("running", new["state"])
        self.assertIsNone(new["body"].get("result"))

    def test_an_old_acknowledgement_cannot_satisfy_the_new_prompt(self):
        old_intent = self.rows(
            "SELECT id,status FROM workflow_intents WHERE work_id=? "
            "AND node='n01' AND attempt=4", (self.work,))[0][0]
        self.authorize()
        before_events = self.events()
        self.engine.acknowledge_intent(EXECUTOR, old_intent)
        # whatever the old prompt answered, the new prompt is untouched
        # and nothing settled behind the acknowledgement
        new = self.rows(
            "SELECT id,status FROM workflow_intents WHERE work_id=? "
            "AND node='n01' AND attempt=5", (self.work,))
        self.assertEqual("pending", new[0][1])
        self.assertEqual("running", self.instance("n01")[-1]["state"])
        self.assertEqual(before_events, self.events())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
