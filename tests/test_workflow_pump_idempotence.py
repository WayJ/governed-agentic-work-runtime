"""A routing pass must not repeat a judgment that has not changed.

A human node that declares a named record for **every** decision keeps
waiting when the decision carries no record: the decision stands, the
record is missing, and the node says so with ``WORKFLOW_OUTPUT_MISSING``.
That waiting is a **stable** position — the declared record is part of
the node's completion contract, and until it arrives nothing downstream
may be routed on that node.

The routing pass used to break that stability. Every pass re-derived the
criterion report of the very same stored decision — stamped with the
moment of that pass — appended it to the node's own evidence and wrote a
new ``WorkflowOutputMissing`` event, because the fresh timestamp made the
node body differ from the stored one. So the node's evidence and the
work's audit trail grew for ever while nothing at all had changed: the
OA work ``a6f3a6f7…`` reached 326 identical ``human-check`` reports and
327 ``WorkflowOutputMissing`` events on a node that was simply waiting,
and the growth continued with every tick of the background pump.

The tests below drive the **real pump** over the real store — the same
tick the background ticker of a host runs — and check that the waiting
is stable, that the first miss keeps its evidence, and that everything
that *did* change is still judged: a new decision, a supplied record and
a new attempt on new material.
"""

import json
import os
import sqlite3
import tempfile
import unittest

from work_runtime.runtime import Runtime
from work_runtime.workflow import WorkflowEngine
from work_runtime.workflow_demo import (INTAKE_SHAPE, RECORD_SHAPE,
                                         WorkflowDemoPolicy, workflow_demo_grants,
                                         workflow_demo_validators)

try:
    from workflow_support import submit_valid, version_of
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import submit_valid, version_of

WORK_ID = "W-1"
RUNNER = "workflow-runner"
INTAKE = {"records": [{"id": "R-1", "source": "site-log"}], "standard": "STD-1"}
REASON = "the material was judged against the criterion"


class OpenPolicy(WorkflowDemoPolicy):
    """The demonstration family with its obligation already satisfied."""

    def evaluate(self, work, evidence):
        return [{"id": "R01:" + work["document"]["id"], "rule_id": "R01",
                 "subject": work["document"]["id"], "applicability": "applicable",
                 "fulfillment": "satisfied",
                 "explanation": "The obligation is satisfied in this fixture"}]


class RecordingAdapter:
    """The business system the pump dispatches to.

    The fixture declares no action node, so the pump never calls it. It is
    here because the pump under test is the real one, adapter and all.
    """

    def __init__(self):
        self.calls = 0

    def execute(self, key, document, content_digest, **kwargs):
        self.calls += 1
        return {"status": "accepted", "external_id": "EXT-1",
                "digest": content_digest, "action": kwargs.get("action"),
                "payload": {}}

    def lookup(self, key):
        return None


def pump_template(template_id="pump-idempotence", version="t1"):
    """One agent node and one human node that declares a named record.

    The human node declares the record for every decision — the default,
    with no narrowing — so a rejection without the record leaves the node
    waiting, exactly as the OA node ``M02`` does.
    """
    return {"id": template_id, "version": version,
            "policy_family": "workflow-demo", "entry": "n01",
            "terminal": ["n02"],
            "nodes": {
                "n01": {"kind": "agent", "executor": "agent-executor",
                        "max_attempts": 2,
                        "output": {"object": "intake",
                                   "validation": {"shape": INTAKE_SHAPE,
                                                  "validator": "intake",
                                                  "validator_version": "1"}},
                        "checks": [{"id": "N01-1", "method": "PROGRAM",
                                    "criterion": "Every record names its source.",
                                    "criterion_version": "1",
                                    "validator": "intake",
                                    "validator_version": "1"}]},
                "n02": {"kind": "human", "evidence_kind": "safety_review",
                        "authority": "reviewer-a",
                        "subject": {"object": "intake"},
                        "max_attempts": 2,
                        "output": {"object": "acceptance",
                                   "validation": {"shape": RECORD_SHAPE,
                                                  "validator": "record",
                                                  "validator_version": "1"}},
                        "checks": [{"id": "N02-1", "method": "HUMAN",
                                    "criterion": "The material is accepted "
                                                 "as it stands.",
                                    "criterion_version": "1",
                                    "validator": "safety-review",
                                    "validator_version": "1"}]}},
            "edges": [{"from": "n01", "to": "n02"}]}


class PumpIdempotenceTestCase(unittest.TestCase):
    """The fixture: one agent node, one human node, one named record."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-pump-")
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.counter = 0
        self.runtime, self.engine = self.build()
        self.adapter = RecordingAdapter()
        self.template = pump_template()
        published = self.engine.publish_template("coordinator", self.template)
        self.assertEqual(published["decision"], "accepted", published)

    # -- helpers ---------------------------------------------------------

    def build(self):
        grants = workflow_demo_grants()
        grants[RUNNER] = {"workflow.finalize"}
        runtime = Runtime(self.path, OpenPolicy(), grants)
        engine = WorkflowEngine(runtime, workflow_demo_validators(), runner=RUNNER)
        return runtime, engine

    def next_id(self, label):
        self.counter += 1
        return label + "-" + str(self.counter)

    def instantiate(self, template=None):
        template = template or self.template
        published = self.engine.publish_template("coordinator", template)
        self.assertEqual(published["decision"], "accepted", published)
        self.runtime.command("coordinator", self.next_id("create"), WORK_ID,
                             "create_work",
                             {"document": {"id": "H-001", "subject": "east parapet"}},
                             None)
        self.runtime.command("coordinator", self.next_id("contract"), WORK_ID,
                             "bind_contract",
                             {"policy_id": "workflow-demo",
                              "policy_version": "demo-1",
                              "goal": "workflow.completed"},
                             version_of(self.runtime, WORK_ID))
        self.runtime.command("coordinator", self.next_id("plan"), WORK_ID,
                             "revise_plan",
                             {"steps": ["n01", "n02"], "open_requirements": [],
                              "replan_when": []},
                             version_of(self.runtime, WORK_ID))
        receipt = self.engine.command("coordinator", self.next_id("bind"), WORK_ID,
                                      "bind_workflow",
                                      {"template_id": template["id"],
                                       "template_version": template["version"],
                                       "parameters": {"subject": "east parapet"}},
                                      version_of(self.runtime, WORK_ID))
        self.assertEqual(receipt["decision"], "accepted", receipt)

    def drive_to_human(self):
        """The agent produced the material; the human node is waiting."""
        self.instantiate()
        self.engine.advance(WORK_ID, 1000)
        submitted = submit_valid(self.engine, self.runtime, WORK_ID, "n01", "intake")
        self.assertEqual(submitted["decision"], "accepted", submitted)
        self.engine.advance(WORK_ID, 1000)
        self.assertEqual(self.node()["state"], "running")

    def subject_reference(self):
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT revision,digest FROM workflow_objects "
                             "WHERE work_id=? AND name='intake' ORDER BY revision "
                             "DESC LIMIT 1", (WORK_ID,)).fetchone()
        finally:
            db.close()
        return {"revision": row[0], "digest": row[1]}

    def decide(self, decision="rejected", result=None, attempt=1,
               actor="reviewer-a", source="reviewer-a", reason=REASON,
               command_id=None):
        """Admit a decision, verify it, and leave the judging to the pump.

        The three steps are the platform's: the decision is admitted as
        evidence, the trusted source verifies it, and the routing pass
        judges the verified decision. The pump — not the command — is what
        settles the node, so every assertion below is about the pump.
        """
        reference = self.subject_reference()
        verdict = {"approved": "passed", "rejected": "failed",
                   "request_material": "insufficient"}[decision]
        item = {"check": "N02-1", "verdict": verdict, "reason": reason}
        if verdict == "passed":
            item["evidence"] = ["intake#revision-" + str(reference["revision"])]
        payload = {"node": "n02", "attempt": attempt, "decision": decision,
                   "digest": reference["digest"], "revision": reference["revision"],
                   "actor": actor, "items": [item]}
        if result is not None:
            payload["result"] = result
        receipt = self.runtime.command(
            source, command_id or self.next_id("decision"), WORK_ID,
            "record_decision", payload, version_of(self.runtime, WORK_ID))
        if receipt.get("decision") == "accepted":
            self.runtime.verify_pending(WORK_ID)
        return receipt

    def record(self, record_id="ACC-1"):
        return {"recordId": record_id, "kind": "safety_review",
                "actor": "reviewer-a", "items": ["M-1"]}

    def pump(self, times=1, now=2000):
        """Run the real pump, the way the background ticker of a host does."""
        for index in range(times):
            self.engine.pump(self.adapter, now + index)
        return self

    def node(self, node="n02"):
        for entry in self.engine.instance(WORK_ID)["nodes"]:
            if entry["node"] == node:
                return entry
        return {}

    def stored_node(self, node="n02", attempt=None):
        db = sqlite3.connect(self.path)
        try:
            if attempt is None:
                row = db.execute("SELECT body FROM workflow_nodes WHERE work_id=? AND "
                                 "node=? ORDER BY attempt DESC LIMIT 1",
                                 (WORK_ID, node)).fetchone()
            else:
                row = db.execute("SELECT body FROM workflow_nodes WHERE work_id=? AND "
                                 "node=? AND attempt=?",
                                 (WORK_ID, node, attempt)).fetchone()
        finally:
            db.close()
        return json.loads(row[0]) if row else {}

    def events_of_type(self, event_type):
        return [event for event in self.runtime.events(WORK_ID)
                if event["type"] == event_type]

    def object_rows(self, name="acceptance"):
        db = sqlite3.connect(self.path)
        try:
            return db.execute("SELECT * FROM workflow_objects WHERE work_id=? AND "
                              "name=?", (WORK_ID, name)).fetchall()
        finally:
            db.close()

    def codes(self, node=None):
        entry = self.node() if node is None else node
        return [finding["code"] for finding in entry.get("findings") or []]

    def snapshot(self):
        """What a reader of the work sees: the evidence and the audit trail."""
        stored = self.stored_node()
        return {"missing_events": len(self.events_of_type("WorkflowOutputMissing")),
                "reports": len(stored.get("check_results") or []),
                "version": self.runtime.get_work(WORK_ID)["state_version"],
                "state": self.node()["state"],
                "outcome": self.node()["outcome"],
                "codes": self.codes(),
                "quality": stored.get("quality")}


class RepeatedTickTests(PumpIdempotenceTestCase):
    """The same decision, judged again and again, is one judgment."""

    def setUp(self):
        super().setUp()
        self.drive_to_human()
        receipt = self.decide("rejected")
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.pump(1)
        self.first = self.snapshot()

    def test_the_first_miss_keeps_its_evidence(self):
        """The first pass records the miss: the event, the finding, the report."""
        self.assertGreaterEqual(self.first["missing_events"], 1)
        # One judgment, one report: the pass that judged it recorded it once.
        self.assertEqual(self.first["reports"], 1)
        self.assertIn("WORKFLOW_OUTPUT_MISSING", self.first["codes"])
        self.assertEqual(self.first["state"], "running")
        self.assertIsNone(self.first["outcome"])
        self.assertEqual(self.first["quality"]["mode"], "missing")
        report = self.stored_node()["check_results"][0]
        self.assertEqual(report["checkId"], "N02-1")
        self.assertEqual(report["verdict"], "failed")
        self.assertEqual(report["reason"], REASON)
        self.assertEqual(report["decidedBy"], "reviewer-a")

    def test_repeated_ticks_do_not_repeat_the_missing_evidence(self):
        """The pump may tick as often as it likes: nothing has changed."""
        for index in range(8):
            self.pump(1, now=3000 + index)
        after = self.snapshot()
        self.assertEqual(after["missing_events"], self.first["missing_events"])
        self.assertEqual(after["reports"], self.first["reports"])
        self.assertEqual(after["version"], self.first["version"])
        self.assertEqual(after["state"], self.first["state"])
        self.assertEqual(after["outcome"], self.first["outcome"])
        self.assertEqual(after["codes"], self.first["codes"])
        self.assertEqual(after["quality"], self.first["quality"])

    def test_repeated_ticks_keep_the_node_waiting_for_the_record(self):
        """The missing record is never mistaken for an acceptance."""
        self.pump(5, now=4000)
        self.assertEqual(self.node()["state"], "running")
        self.assertIsNone(self.node()["outcome"])
        self.assertIn("WORKFLOW_OUTPUT_MISSING", self.codes())
        self.assertEqual(self.object_rows(), [])
        self.assertEqual(self.runtime.get_work(WORK_ID)["workflow_current"], "n02")

    def test_the_node_body_does_not_change_between_ticks(self):
        """The stored node is byte for byte the node the first pass wrote."""
        body = self.stored_node()
        self.pump(5, now=5000)
        self.assertEqual(self.stored_node(), body)


class ChangedInputTests(PumpIdempotenceTestCase):
    """What did change is still judged — the dedup never swallows a result."""

    def setUp(self):
        super().setUp()
        self.drive_to_human()
        receipt = self.decide("rejected")
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.pump(1)
        self.pump(3, now=3000)

    def test_a_new_decision_is_judged_again(self):
        """A second, different decision is a second judgment."""
        receipt = self.decide("approved", reason="the material is accepted on "
                                         "a second look")
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.pump(1)
        stored = self.stored_node()
        reports = stored.get("check_results") or []
        self.assertEqual(len(reports), 2)
        self.assertEqual([report["verdict"] for report in reports],
                         ["failed", "passed"])
        # The new judgement did not pass the node: the record is still missing.
        self.assertEqual(self.node()["state"], "running")
        self.assertIn("WORKFLOW_OUTPUT_MISSING", self.codes())
        self.assertEqual(self.object_rows(), [])

    def test_a_different_missing_keeps_its_own_evidence(self):
        """Each missing judgement keeps the evidence that belongs to it."""
        self.decide("approved", reason="the material is accepted on a second look")
        self.pump(1)
        stored = self.stored_node()
        reasons = [report["reason"] for report in stored.get("check_results") or []]
        self.assertEqual(reasons, [REASON,
                                   "the material is accepted on a second look"])
        # And the missing output of both is still the same missing output.
        findings = [finding for finding in stored.get("findings") or []
                    if finding["code"] == "WORKFLOW_OUTPUT_MISSING"]
        self.assertEqual(len(findings), 1)

    def test_a_supplied_record_completes_the_node(self):
        """The lawful completion is still reached after the stable ticks."""
        receipt = self.decide("approved", result=self.record())
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.pump(1)
        self.assertEqual(self.node()["state"], "completed")
        self.assertEqual(self.node()["outcome"], "approved")
        self.assertEqual(len(self.object_rows()), 1)
        binding = self.stored_node().get("output_binding") or {}
        self.assertEqual(binding.get("actor"), "reviewer-a")
        self.assertEqual(binding.get("subject", {}).get("digest"),
                         self.subject_reference()["digest"])

    def test_new_material_opens_a_new_attempt_that_is_judged_again(self):
        """New material supersedes the attempt; the new attempt is judged."""
        receipt = self.runtime.command(
            "coordinator", self.next_id("revise"), WORK_ID, "revise_object",
            {"name": "intake",
             "object": {"records": [{"id": "R-2", "source": "site-log"}],
                        "standard": "STD-2"}},
            version_of(self.runtime, WORK_ID))
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.pump(1)
        node = self.node()
        self.assertEqual(node["attempt"], 2)
        self.assertEqual(node["state"], "running")
        # The new attempt has judged nothing yet: the old attempt's report
        # did not carry over.
        self.assertFalse(self.stored_node(attempt=2).get("check_results"))
        # The human decides again, on the new material.
        receipt = self.decide("rejected", attempt=2)
        self.assertEqual(receipt["decision"], "accepted", receipt)
        self.pump(1)
        self.assertEqual(len(self.stored_node(attempt=2)["check_results"]), 1)
        # The old attempt keeps its own evidence.
        self.assertEqual(len(self.stored_node(attempt=1)["check_results"]), 1)
        self.assertIn("WORKFLOW_OUTPUT_MISSING", self.codes())


if __name__ == "__main__":
    unittest.main()
