"""The durable preparation of a multi-stage instance creation.

The creation is four runtime commands, not one: the work is created, the
contract is bound, the plan is revised and the workflow is bound. Each of
them is a compare-and-swap on the work's state version, so a version
recomputed on a later attempt is a *different* command and the runtime
refuses it as a reused command id. The preparation is written before a
stage is issued, and the resume re-issues the recorded command.

These tests pin the preparation record and the resume it makes possible.
"""

import os
import tempfile
import unittest

try:
    from workflow_support import build, scenario_template
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import build, scenario_template

from work_runtime.workflow_server import WorkflowService


def document(work_id="H-001"):
    return {"id": work_id, "subject": "east parapet"}


class CreateResumeTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-create-resume-")
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.runtime, self.engine = build(self.path)
        self.engine.publish_template("coordinator", scenario_template())
        self.service = WorkflowService(self.runtime, self.engine)

    # -- helpers ---------------------------------------------------------
    def reopen(self):
        """A new service over the same store: the restart."""
        runtime, engine = build(self.path)
        return WorkflowService(runtime, engine)

    def body(self, **overrides):
        payload = {
            "workId": "W-1",
            "document": document(),
            "templateId": scenario_template()["id"],
            "templateVersion": scenario_template()["version"],
            "parameters": {"subject": "east parapet"},
            "sessionId": "sess-1",
            "commandId": "create-1",
        }
        payload.update(overrides)
        return payload

    def create(self, service=None, **overrides):
        return (service or self.service).create_instance(self.body(**overrides))


class PreparationStoreTests(CreateResumeTestCase):
    def test_a_preparation_survives_a_restart(self):
        stages = {"create": {"kind": "create_work",
                             "command_id": "create-1:create",
                             "payload": {"document": document()},
                             "expected_version": None}}
        self.service.preparations.save("create-1", "W-1", "coordinator",
                                        "digest-1", stages)
        reopened = self.reopen()
        record = reopened.preparations.load("create-1", "W-1")
        self.assertIsNotNone(record)
        self.assertEqual(record["actor"], "coordinator")
        self.assertEqual(record["request_digest"], "digest-1")
        self.assertEqual(record["stages"], stages)

    def test_an_unknown_preparation_is_absent(self):
        self.assertIsNone(self.service.preparations.load("create-9", "W-9"))


class CreateReplayTests(CreateResumeTestCase):
    """The creation is resumable, and a replay changes nothing."""

    # -- helpers ---------------------------------------------------------
    def crash_after(self, service, stage_number):
        """Crash the coordinator right after the n-th command committed.

        The command itself is committed: the crash is *between* two
        stages, which is exactly the boundary a resume has to cross.
        """
        original = service.runtime.command
        issued = []

        def crashing(actor, command_id, work_id, kind, payload=None,
                     expected_version=None):
            receipt = original(actor, command_id, work_id, kind, payload,
                               expected_version)
            issued.append(command_id)
            if len(issued) >= stage_number:
                raise RuntimeError("the coordinator crashed")
            return receipt

        service.runtime.command = crashing
        return issued

    def event_types(self, work_id="W-1"):
        return [event["type"] for event in self.runtime.events(work_id)]

    def intent_count(self):
        with self.runtime._connection() as db:
            return db.execute("SELECT COUNT(*) FROM workflow_intents").fetchone()[0]

    def assert_created(self, body):
        self.assertEqual(body["workflow"]["templateId"], scenario_template()["id"])
        self.assertEqual(body["workflow"]["templateVersion"],
                         scenario_template()["version"])

    # -- the replay of a completed creation ------------------------------
    def test_a_replay_after_the_creation_completed_returns_the_same_answer(self):
        status, first = self.create()
        self.assertEqual(status, 201, first)
        status, second = self.create()
        self.assertEqual(status, 201, second)
        self.assertEqual(second["stateVersion"], first["stateVersion"])
        self.assertEqual(second["commandId"], first["commandId"])

    def test_a_replay_adds_no_revision_no_intent_and_no_event(self):
        status, first = self.create()
        self.assertEqual(status, 201, first)
        work = self.runtime.get_work("W-1")
        events = self.event_types()
        intents = self.intent_count()
        status, second = self.create()
        self.assertEqual(status, 201, second)
        after = self.runtime.get_work("W-1")
        self.assertEqual(after["plan_revision"], work["plan_revision"])
        self.assertEqual(after["state_version"], work["state_version"])
        self.assertEqual(self.event_types(), events)
        self.assertEqual(self.intent_count(), intents)

    def test_a_replay_does_not_issue_an_accepted_stage_again(self):
        status, body = self.create()
        self.assertEqual(status, 201, body)
        self.create()
        types = self.event_types()
        for name in ("WorkCreated", "ContractBound", "PlanRevised",
                     "WorkflowBound"):
            self.assertEqual(types.count(name), 1, name)

    # -- the resume of a crashed creation --------------------------------
    def test_a_crash_after_the_work_was_created_resumes_the_creation(self):
        self.crash_after(self.service, 1)
        with self.assertRaises(RuntimeError):
            self.create()
        status, body = self.create(self.reopen())
        self.assertEqual(status, 201, body)
        self.assert_created(body)

    def test_a_crash_after_the_contract_resumes_the_creation(self):
        self.crash_after(self.service, 2)
        with self.assertRaises(RuntimeError):
            self.create()
        status, body = self.create(self.reopen())
        self.assertEqual(status, 201, body)
        self.assert_created(body)

    def test_a_crash_after_the_plan_resumes_the_creation(self):
        self.crash_after(self.service, 3)
        with self.assertRaises(RuntimeError):
            self.create()
        status, body = self.create(self.reopen())
        self.assertEqual(status, 201, body)
        self.assert_created(body)

    def test_a_crash_after_the_binding_resumes_the_creation(self):
        self.crash_after(self.service, 4)
        with self.assertRaises(RuntimeError):
            self.create()
        status, body = self.create(self.reopen())
        self.assertEqual(status, 201, body)
        self.assert_created(body)

    def test_the_resume_issues_an_accepted_stage_only_once(self):
        self.crash_after(self.service, 2)
        with self.assertRaises(RuntimeError):
            self.create()
        status, body = self.create(self.reopen())
        self.assertEqual(status, 201, body)
        types = self.event_types()
        self.assertEqual(types.count("WorkCreated"), 1)
        self.assertEqual(types.count("ContractBound"), 1)
        self.assertEqual(types.count("PlanRevised"), 1)
        self.assertEqual(types.count("WorkflowBound"), 1)

    def test_the_resume_binds_the_template_the_first_attempt_bound(self):
        self.crash_after(self.service, 3)
        with self.assertRaises(RuntimeError):
            self.create()
        status, body = self.create(self.reopen())
        self.assertEqual(status, 201, body)
        self.assert_created(body)
        receipt = self.runtime.get_command_receipt("coordinator",
                                                   "create-1:bind", "W-1")
        self.assertIsNotNone(receipt)
        self.assertEqual(receipt["decision"], "accepted")

    def test_the_binding_receipt_is_readable_after_a_crash(self):
        self.crash_after(self.service, 3)
        with self.assertRaises(RuntimeError):
            self.create()
        # The platform probes the final receipt: before the resume there is
        # no binding receipt at all.
        self.assertIsNone(self.runtime.get_command_receipt(
            "coordinator", "create-1:bind", "W-1"))
        self.create(self.reopen())
        receipt = self.runtime.get_command_receipt("coordinator",
                                                   "create-1:bind", "W-1")
        self.assertIsNotNone(receipt)
        self.assertEqual(receipt["decision"], "accepted")

    # -- a changed request conflicts -------------------------------------
    def test_a_refused_command_is_answered_not_raised(self):
        # The actor is not a principal name: the command refuses itself and
        # the bridge answers 400 instead of raising.
        status, body = self.create(actor=5)
        self.assertEqual(status, 400, body)
        self.assertEqual(body["error"]["code"], "DOCUMENT_INVALID")

    def test_a_changed_document_conflicts(self):
        status, body = self.create()
        self.assertEqual(status, 201, body)
        status, body = self.create(document=document("H-002"))
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error"]["code"], "COMMAND_ID_REUSED")

    def test_a_changed_template_conflicts(self):
        status, body = self.create()
        self.assertEqual(status, 201, body)
        status, body = self.create(templateVersion="demo-2")
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error"]["code"], "COMMAND_ID_REUSED")

    def test_a_changed_instance_conflicts(self):
        status, body = self.create()
        self.assertEqual(status, 201, body)
        status, body = self.create(parameters={"subject": "west parapet"})
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error"]["code"], "COMMAND_ID_REUSED")

    def test_a_changed_session_conflicts(self):
        status, body = self.create()
        self.assertEqual(status, 201, body)
        status, body = self.create(sessionId="sess-2")
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error"]["code"], "COMMAND_ID_REUSED")

    def test_a_changed_actor_conflicts(self):
        status, body = self.create()
        self.assertEqual(status, 201, body)
        status, body = self.create(actor="other-coordinator")
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error"]["code"], "COMMAND_ID_REUSED")

    def test_a_changed_work_conflicts(self):
        status, body = self.create()
        self.assertEqual(status, 201, body)
        status, body = self.create(workId="W-2")
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error"]["code"], "COMMAND_ID_REUSED")

    def test_a_changed_plan_conflicts(self):
        status, body = self.create()
        self.assertEqual(status, 201, body)
        status, body = self.create(plan={"steps": ["n01"], "openRequirements": [],
                                         "replanWhen": []})
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error"]["code"], "COMMAND_ID_REUSED")


if __name__ == "__main__":
    unittest.main()
