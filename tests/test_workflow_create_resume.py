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


if __name__ == "__main__":
    unittest.main()
