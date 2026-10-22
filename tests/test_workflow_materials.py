"""Relational output validation: the material a node attempt pinned.

A structural shape cannot prove that an output covers the material it was
produced from. The engine now hands an output validator the exact material
the attempt pinned - the inputs and the subject it holds, resolved from its
own references and never from the latest revision of an object - so that a
host-registered validator can compare identifiers and coverage.

The validator is the host's own: the core stays domain-neutral, and the
fixture below registers a generic "every identifier of the pinned input
appears exactly once in the output" validator.
"""

import json
import os
import sqlite3
import tempfile
import unittest

from work_runtime.adapter_contract import AdapterContract
from work_runtime.policy import canonical, digest
from work_runtime.runtime import Runtime
from work_runtime.workflow import WorkflowEngine, WorkflowError
from work_runtime.workflow_demo import (WorkflowDemoPolicy, workflow_demo_grants,
                                         workflow_demo_validators)

try:
    from workflow_support import version_of
except ImportError:  # pragma: no cover - repository-root import style
    from tests.workflow_support import version_of

WORK_ID = "W-1"
IDS = ["A-1", "B-2"]

ID_SHAPE = {"type": "object",
            "properties": {"ids": {"type": "array",
                                    "items": {"type": "string"}}},
            "required": ["ids"]}


class MaterialsPolicy(WorkflowDemoPolicy):
    """The demonstration family with one satisfied obligation and a proof
    kind that carries material."""

    evidence_sources = dict(WorkflowDemoPolicy.evidence_sources,
                             coverage_proof="business-system")

    def evaluate(self, work, evidence):
        return [{"id": "R01:" + work["document"]["id"], "rule_id": "R01",
                 "subject": work["document"]["id"], "applicability": "applicable",
                 "fulfillment": "satisfied",
                 "explanation": "The obligation is satisfied in this fixture"}]

    def validate_evidence(self, work, candidate):
        if candidate["kind"] == "coverage_proof":
            data = candidate["data"]
            return (set(data) == {"ids"} and isinstance(data["ids"], list)
                    and all(isinstance(entry, str) for entry in data["ids"]))
        return WorkflowDemoPolicy.validate_evidence(self, work, candidate)


def coverage_validator(work, node_ref, result):
    """Every identifier of the pinned input appears exactly once in the output.

    The context carries the exact material this attempt pinned, so the
    comparison is against the input the node was given - never against the
    latest revision of that object.
    """
    materials = node_ref.get("materials") or []
    pinned = [entry for entry in materials if entry.get("role") == "input"]
    if not pinned:
        # A node that pins no input compares against its protected subject.
        pinned = [entry for entry in materials if entry.get("role") == "subject"]
    if not pinned:
        return {"findings": [{"code": "COVERAGE_NO_MATERIAL",
                              "message": "The node pinned no material to compare with"}],
                "checks": []}
    inputs = pinned
    expected = list((inputs[0].get("object") or {}).get("ids") or [])
    produced = list((result or {}).get("ids") or [])
    findings = []
    for identifier in produced:
        if identifier not in expected:
            findings.append({"code": "COVERAGE_UNKNOWN_ID",
                             "message": "The output names an identifier the "
                                        "pinned input does not",
                             "location": identifier})
    for identifier in expected:
        if identifier not in produced:
            findings.append({"code": "COVERAGE_MISSING_ID",
                             "message": "The output does not name every "
                                        "identifier of the pinned input",
                             "location": identifier})
    for identifier in sorted(set(produced)):
        if produced.count(identifier) > 1:
            findings.append({"code": "COVERAGE_DUPLICATE_ID",
                             "message": "The output names an identifier twice",
                             "location": identifier})
    verdict = "failed" if findings else "passed"
    reason = ("the output covers the pinned input exactly" if not findings
              else "the output does not cover the pinned input")
    checks = [{"check": check, "verdict": verdict, "reason": reason,
               "evidence": ["material:" + str(inputs[0]["reference"]["digest"])]}
              for check in (node_ref.get("checks") or [])]
    return {"findings": findings, "checks": checks}


def materials_template(kind, template_id=None, version="t1"):
    """A one-node workflow per output-producing kind.

    Every kind gets its own published definition: a published definition
    never changes under the same id and version.
    """
    template_id = template_id or ("materials-" + kind)
    validation = {"shape": ID_SHAPE, "validator": "coverage",
                  "validator_version": "1"}
    checks = [{"id": "N01-1", "method": "PROGRAM",
               "criterion": "The output covers the pinned input exactly.",
               "criterion_version": "1", "validator": "coverage",
               "validator_version": "1"}]
    common = {"inputs": [{"object": "source"}],
              "output": {"object": "result", "validation": validation},
              "checks": checks}
    if kind == "agent":
        node = dict(common, kind="agent", executor="agent-executor",
                    max_attempts=1)
    elif kind == "human":
        node = dict(common, kind="human", evidence_kind="safety_review",
                    authority="reviewer-a", subject={"object": "source"})
    elif kind == "action":
        node = dict(common, kind="action", capability="work.dispatch",
                    subject={"object": "source"})
    elif kind == "wait":
        node = dict(common, kind="wait", deadline_s=86400,
                    match={"evidence_kind": "coverage_proof"})
    else:  # pragma: no cover - the fixture names its kinds
        raise ValueError("unknown kind: " + kind)
    return {"id": template_id, "version": version,
            "policy_family": "workflow-demo", "entry": "n01",
            "terminal": ["n01"], "nodes": {"n01": node}, "edges": []}


class MaterialsAdapter:
    """An external system that returns the material the fixture declares."""

    contract = AdapterContract(actions=("work.dispatch",),
                                idempotency_scope="adapter-store:key",
                                retention="lifetime-of-store",
                                lookup_consistency="authoritative-by-key",
                                uniqueness=("external.id",))

    def __init__(self, payload):
        self.payload = payload
        self.effects = 0

    def execute(self, key, document, content_digest, *, action=None,
                compensates=None):
        self.effects += 1
        return {"status": "accepted", "external_id": "EXT-1",
                "digest": content_digest, "action": action,
                "payload": self.payload}

    def lookup(self, key):
        return None


class MaterialsTestCase(unittest.TestCase):
    """The fixture: one workflow, one pinned input, one validator."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="gawr-materials-")
        self.path = os.path.join(self.folder, "runtime.sqlite")
        self.seen = []
        self.counter = 0
        self.runtime, self.engine = self.build()
        self.template = materials_template("agent")
        published = self.engine.publish_template("coordinator", self.template)
        self.assertEqual(published["decision"], "accepted", published)

    # -- helpers ---------------------------------------------------------

    def build(self, path=None):
        registry = workflow_demo_validators()
        registry.register("coverage", "1", self._coverage)
        runtime = Runtime(path or self.path, MaterialsPolicy(),
                          workflow_demo_grants())
        engine = WorkflowEngine(runtime, registry)
        return runtime, engine

    def _coverage(self, work, node_ref, result):
        """The host validator, recorded so a test can read what it received."""
        self.seen.append({"work": work, "context": node_ref, "result": result})
        return coverage_validator(work, node_ref, result)

    def _plain(self, work, node_ref, result):
        """A validator that ignores the context, recorded the same way."""
        self.seen.append({"work": work, "context": node_ref, "result": result})
        return plain_validator(work, node_ref, result)

    def next_id(self, label):
        self.counter += 1
        return label + "-" + str(self.counter)

    def command(self, kind, payload, actor="coordinator"):
        return self.engine.command(actor, self.next_id(kind), WORK_ID, kind,
                                    payload, version_of(self.runtime, WORK_ID))

    def instantiate(self, kind):
        """A fresh work bound to the definition of one kind."""
        return self.instantiate_with(materials_template(kind))

    def instantiate_with(self, template):
        """A fresh work bound to a given definition."""
        self.template = template
        published = self.engine.publish_template("coordinator", self.template)
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
                             {"steps": ["n01"], "open_requirements": [],
                              "replan_when": []},
                             version_of(self.runtime, WORK_ID))
        receipt = self.engine.command("coordinator", self.next_id("bind"), WORK_ID,
                                      "bind_workflow",
                                      {"template_id": self.template["id"],
                                       "template_version": self.template["version"],
                                       "parameters": {"subject": "east parapet"}},
                                      version_of(self.runtime, WORK_ID))
        self.assertEqual(receipt["decision"], "accepted", receipt)

    def write_source(self, ids=None, name="source"):
        receipt = self.command("revise_object",
                               {"name": name,
                                "object": {"ids": list(ids or IDS)}})
        self.assertEqual(receipt["decision"], "accepted", receipt)
        return receipt

    def write_newer_revision(self, name, ids):
        """Write a newer revision straight into the store.

        The runtime's own revision path supersedes the node that pinned the
        object, so this writes the newer revision the way a concurrent
        writer would: the node keeps the revision it pinned.
        """
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT revision FROM workflow_objects WHERE "
                             "work_id=? AND name=? ORDER BY revision DESC "
                             "LIMIT 1", (WORK_ID, name)).fetchone()
            body = {"ids": list(ids)}
            db.execute("INSERT INTO workflow_objects VALUES (?,?,?,?,?)",
                       (WORK_ID, name, row[0] + 1, digest(body), canonical(body)))
            db.commit()
        finally:
            db.close()

    def source_reference(self, name="source"):
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT revision,digest FROM workflow_objects "
                             "WHERE work_id=? AND name=? ORDER BY revision DESC "
                             "LIMIT 1", (WORK_ID, name)).fetchone()
        finally:
            db.close()
        return {"name": name, "revision": row[0], "digest": row[1]}

    def materials_of(self, index=-1):
        return self.seen[index]["context"].get("materials") or []

    # -- the four output-producing kinds ----------------------------------

    def drive_agent(self, ids=None):
        self.instantiate("agent")
        self.write_source()
        self.engine.advance(WORK_ID, 1000)
        return self.command("submit_node_result",
                             {"node": "n01", "attempt": 1, "object": "result",
                              "result": {"ids": list(ids or IDS)},
                              "input_digest": self.input_digest()},
                             actor="agent-executor")

    def drive_human(self, ids=None):
        self.instantiate("human")
        self.write_source()
        self.engine.advance(WORK_ID, 1000)
        reference = self.source_reference()
        payload = {"node": "n01", "attempt": 1, "decision": "approved",
                   "digest": reference["digest"], "revision": reference["revision"],
                   "actor": "reviewer-a", "items": [],
                   "result": {"ids": list(ids or IDS)}}
        return self.engine.command("reviewer-a", self.next_id("decision"), WORK_ID,
                                   "record_decision", payload,
                                   version_of(self.runtime, WORK_ID))

    def drive_action(self, ids=None):
        self.instantiate("action")
        self.write_source()
        self.engine.advance(WORK_ID, 1000)
        adapter = MaterialsAdapter({"ids": list(ids or IDS)})
        self.engine.pump(adapter, 1000)
        self.engine.advance(WORK_ID, 1000)
        return adapter

    def drive_wait(self, ids=None):
        self.instantiate("wait")
        self.write_source()
        self.engine.advance(WORK_ID, 1000)
        self.runtime.command("business-system", self.next_id("proof"), WORK_ID,
                             "record_evidence",
                             {"event_id": "proof-1", "kind": "coverage_proof",
                              "data": {"ids": list(ids or IDS)}}, None)
        self.runtime.verify_pending(WORK_ID)
        self.engine.advance(WORK_ID, 1000)
        return self.runtime.get_work(WORK_ID)

    def input_digest(self):
        for entry in self.engine.instance(WORK_ID)["nodes"]:
            if entry["node"] == "n01":
                return entry.get("inputDigest")
        return None

    def stored_instance(self, node="n01"):
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT body FROM workflow_nodes WHERE work_id=? "
                             "AND node=? ORDER BY attempt DESC LIMIT 1",
                             (WORK_ID, node)).fetchone()
        finally:
            db.close()
        return json.loads(row[0]) if row else {}

    def node_state(self):
        for entry in self.engine.instance(WORK_ID)["nodes"]:
            if entry["node"] == "n01":
                return entry
        return {}


def mutating_validator(work, node_ref, result):
    """A validator that tries to change what it was given."""
    for entry in node_ref.get("materials") or []:
        entry["object"]["ids"] = ["tampered"]
        entry["reference"]["digest"] = "tampered"
    work["document"] = {"id": "tampered", "subject": "tampered"}
    work["requirements"] = []
    checks = [{"check": check, "verdict": "passed",
               "reason": "the validator changed nothing that matters",
               "evidence": ["material:mutated"]}
              for check in (node_ref.get("checks") or [])]
    return {"findings": [], "checks": checks}


def plain_validator(work, node_ref, result):
    """A validator that ignores the context entirely."""
    checks = [{"check": check, "verdict": "passed",
               "reason": "the material was accepted",
               "evidence": ["material:plain"]}
              for check in (node_ref.get("checks") or [])]
    return {"findings": [], "checks": checks}


class CoverageValidationTests(MaterialsTestCase):
    """A generic identifiers-in-output against pinned-input validator."""

    def test_the_agent_output_is_judged_against_its_pinned_input(self):
        receipt = self.drive_agent()
        self.assertEqual(receipt["decision"], "accepted", receipt)
        materials = self.materials_of()
        self.assertEqual(len(materials), 1)
        entry = materials[0]
        self.assertEqual(entry["role"], "input")
        self.assertEqual(entry["reference"]["name"], "source")
        self.assertEqual(entry["reference"]["revision"], 1)
        self.assertEqual(entry["reference"]["digest"],
                         self.source_reference()["digest"])
        self.assertEqual(entry["object"], {"ids": IDS})

    def test_an_unknown_identifier_is_rejected(self):
        receipt = self.drive_agent(ids=IDS + ["Z-9"])
        self.assertEqual(receipt["decision"], "rejected", receipt)
        self.assertEqual(receipt["code"], "WORKFLOW_RESULT_INVALID")
        codes = [finding["code"] for finding in receipt.get("blockers") or []]
        self.assertIn("COVERAGE_UNKNOWN_ID", codes)

    def test_a_missing_identifier_is_rejected(self):
        receipt = self.drive_agent(ids=IDS[:1])
        self.assertEqual(receipt["decision"], "rejected", receipt)
        codes = [finding["code"] for finding in receipt.get("blockers") or []]
        self.assertIn("COVERAGE_MISSING_ID", codes)

    def test_a_duplicated_identifier_is_rejected(self):
        receipt = self.drive_agent(ids=IDS + [IDS[0]])
        self.assertEqual(receipt["decision"], "rejected", receipt)
        codes = [finding["code"] for finding in receipt.get("blockers") or []]
        self.assertIn("COVERAGE_DUPLICATE_ID", codes)

    def test_the_materials_are_the_pinned_revision_not_the_latest(self):
        """A newer revision in the store does not change what was pinned."""
        self.instantiate("agent")
        self.write_source()
        self.engine.advance(WORK_ID, 1000)
        pinned = self.source_reference()
        self.write_newer_revision("source", ["C-3"])
        self.assertEqual(self.source_reference()["revision"], 2)
        # The candidate that covers the pinned identifiers is accepted.
        receipt = self.command("submit_node_result",
                               {"node": "n01", "attempt": 1, "object": "result",
                                "result": {"ids": IDS},
                                "input_digest": self.input_digest()},
                               actor="agent-executor")
        self.assertEqual(receipt["decision"], "accepted", receipt)
        materials = self.materials_of()
        self.assertEqual(materials[0]["reference"]["revision"], 1)
        self.assertEqual(materials[0]["reference"]["digest"], pinned["digest"])
        self.assertEqual(materials[0]["object"], {"ids": IDS})

    def test_a_candidate_covering_the_latest_revision_is_refused(self):
        self.instantiate("agent")
        self.write_source()
        self.engine.advance(WORK_ID, 1000)
        self.write_newer_revision("source", ["C-3"])
        receipt = self.command("submit_node_result",
                               {"node": "n01", "attempt": 1, "object": "result",
                                "result": {"ids": ["C-3"]},
                                "input_digest": self.input_digest()},
                               actor="agent-executor")
        self.assertEqual(receipt["decision"], "rejected", receipt)
        codes = [finding["code"] for finding in receipt.get("blockers") or []]
        self.assertIn("COVERAGE_UNKNOWN_ID", codes)


class SubjectCoverageTests(MaterialsTestCase):
    """A node that pins no input compares against its protected subject."""

    def subject_template(self):
        """A node that pins a subject and no input."""
        template = materials_template("human", template_id="materials-subject")
        template["nodes"]["n01"].pop("inputs")
        return template

    def drive_subject(self, ids=None):
        template = self.subject_template()
        published = self.engine.publish_template("coordinator", template)
        self.assertEqual(published["decision"], "accepted", published)
        self.instantiate_with(template)
        self.write_source()
        self.engine.advance(WORK_ID, 1000)
        reference = self.source_reference()
        payload = {"node": "n01", "attempt": 1, "decision": "approved",
                   "digest": reference["digest"], "revision": reference["revision"],
                   "actor": "reviewer-a", "items": [],
                   "result": {"ids": list(ids or IDS)}}
        return self.engine.command("reviewer-a", self.next_id("decision"), WORK_ID,
                                   "record_decision", payload,
                                   version_of(self.runtime, WORK_ID))

    def test_the_output_is_judged_against_the_protected_subject(self):
        receipt = self.drive_subject()
        self.assertEqual(receipt["decision"], "accepted", receipt)
        materials = self.materials_of()
        self.assertEqual([entry["role"] for entry in materials], ["subject"])
        self.assertEqual(materials[0]["reference"]["name"], "source")
        self.assertEqual(materials[0]["object"], {"ids": IDS})

    def test_an_output_that_does_not_cover_the_subject_is_refused(self):
        """The record is refused; the decision itself is never lost."""
        receipt = self.drive_subject(ids=["Z-9"])
        self.assertEqual(receipt["decision"], "accepted", receipt)
        instance = self.stored_instance()
        self.assertNotEqual(instance["state"], "completed")
        self.assertEqual(instance["quality"]["mode"], "rejected")
        codes = [finding["code"]
                 for finding in instance.get("output_findings") or []]
        self.assertIn("COVERAGE_UNKNOWN_ID", codes)


class MaterialsPerKindTests(MaterialsTestCase):
    """Every output-producing kind hands over the same material."""

    def test_the_human_record_is_judged_against_the_pinned_material(self):
        receipt = self.drive_human()
        self.assertEqual(receipt["decision"], "accepted", receipt)
        materials = self.materials_of()
        self.assertEqual([entry["role"] for entry in materials],
                         ["input", "subject"])
        for entry in materials:
            self.assertEqual(entry["reference"]["name"], "source")
            self.assertEqual(entry["reference"]["revision"], 1)
            self.assertEqual(entry["object"], {"ids": IDS})

    def test_the_automatic_output_is_judged_against_the_pinned_material(self):
        adapter = self.drive_action()
        self.assertEqual(adapter.effects, 1)
        node = self.node_state()
        self.assertEqual(node["state"], "completed")
        self.assertEqual(node["quality"]["mode"], "validated")
        materials = self.materials_of()
        self.assertEqual([entry["role"] for entry in materials],
                         ["input", "subject"])
        self.assertEqual(materials[0]["object"], {"ids": IDS})

    def test_the_waited_material_is_judged_against_the_pinned_material(self):
        work = self.drive_wait()
        node = self.node_state()
        self.assertEqual(node["state"], "completed", work)
        materials = self.materials_of()
        self.assertEqual([entry["role"] for entry in materials], ["input"])
        self.assertEqual(materials[0]["object"], {"ids": IDS})

    def test_a_rejected_automatic_output_keeps_the_effect(self):
        """The effect really happened; the output is refused, not repeated."""
        self.instantiate("action")
        self.write_source()
        self.engine.advance(WORK_ID, 1000)
        adapter = MaterialsAdapter({"ids": ["Z-9"]})
        self.engine.pump(adapter, 1000)
        self.engine.advance(WORK_ID, 1000)
        node = self.node_state()
        self.assertEqual(node["state"], "failed")
        self.assertEqual(node["effect"]["status"], "succeeded")
        self.assertEqual(adapter.effects, 1)
        self.assertEqual(self.stored_instance()["reason"],
                         "WORKFLOW_OUTPUT_INVALID")


class MaterialIsolationTests(MaterialsTestCase):
    """A validator cannot change what it is given."""

    def register_mutating(self):
        registry = self.engine.validators
        registry.register("mutating", "1", mutating_validator)
        template = materials_template("agent", template_id="materials-mutating")
        template["nodes"]["n01"]["output"]["validation"] = {
            "shape": ID_SHAPE, "validator": "mutating", "validator_version": "1"}
        template["nodes"]["n01"]["checks"] = [
            {"id": "N01-1", "method": "PROGRAM",
             "criterion": "The output covers the pinned input exactly.",
             "criterion_version": "1", "validator": "mutating",
             "validator_version": "1"}]
        return template

    def test_a_mutating_validator_cannot_change_the_stored_material(self):
        template = self.register_mutating()
        published = self.engine.publish_template("coordinator", template)
        self.assertEqual(published["decision"], "accepted", published)
        self.instantiate_with(template)
        self.write_source()
        self.engine.advance(WORK_ID, 1000)
        receipt = self.command("submit_node_result",
                               {"node": "n01", "attempt": 1, "object": "result",
                                "result": {"ids": IDS},
                                "input_digest": self.input_digest()},
                               actor="agent-executor")
        self.assertEqual(receipt["decision"], "accepted", receipt)
        # The stored object still holds what it held.
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT body FROM workflow_objects WHERE work_id=? "
                             "AND name='source'", (WORK_ID,)).fetchone()
        finally:
            db.close()
        self.assertEqual(json.loads(row[0]), {"ids": IDS})
        # And the stored work is untouched.
        work = self.runtime.get_work(WORK_ID)
        self.assertEqual(work["document"], {"id": "H-001", "subject": "east parapet"})
        self.assertTrue(work["requirements"])

    def test_an_existing_validator_without_the_materials_still_works(self):
        registry = self.engine.validators
        registry.register("plain", "1", self._plain)
        template = materials_template("agent", template_id="materials-plain")
        template["nodes"]["n01"]["output"]["validation"] = {
            "shape": ID_SHAPE, "validator": "plain", "validator_version": "1"}
        template["nodes"]["n01"]["checks"] = [
            {"id": "N01-1", "method": "PROGRAM",
             "criterion": "The output covers the pinned input exactly.",
             "criterion_version": "1", "validator": "plain",
             "validator_version": "1"}]
        published = self.engine.publish_template("coordinator", template)
        self.assertEqual(published["decision"], "accepted", published)
        self.instantiate_with(template)
        self.write_source()
        self.engine.advance(WORK_ID, 1000)
        receipt = self.command("submit_node_result",
                               {"node": "n01", "attempt": 1, "object": "result",
                                "result": {"ids": IDS},
                                "input_digest": self.input_digest()},
                               actor="agent-executor")
        self.assertEqual(receipt["decision"], "accepted", receipt)
        # The context carries the materials; the validator simply ignores them.
        self.assertTrue(self.materials_of())


class FailClosedTests(MaterialsTestCase):
    """A missing or corrupt pinned object never yields a partial material."""

    def delete_source(self):
        db = sqlite3.connect(self.path)
        try:
            db.execute("DELETE FROM workflow_objects WHERE work_id=? AND "
                       "name='source'", (WORK_ID,))
            db.commit()
        finally:
            db.close()

    def corrupt_source(self):
        db = sqlite3.connect(self.path)
        try:
            db.execute("UPDATE workflow_objects SET body=? WHERE work_id=? AND "
                       "name='source'", ('{"ids": ["tampered"]}', WORK_ID))
            db.commit()
        finally:
            db.close()

    def test_a_missing_pinned_object_fails_closed(self):
        self.instantiate("agent")
        self.write_source()
        self.engine.advance(WORK_ID, 1000)
        self.delete_source()
        with self.assertRaises(WorkflowError) as caught:
            self.command("submit_node_result",
                         {"node": "n01", "attempt": 1, "object": "result",
                          "result": {"ids": IDS},
                          "input_digest": self.input_digest()},
                         actor="agent-executor")
        self.assertIn("source", str(caught.exception))
        # Nothing was stored and the node did not complete.
        self.assertNotEqual(self.node_state()["state"], "completed")

    def test_a_corrupt_pinned_object_fails_closed(self):
        self.instantiate("agent")
        self.write_source()
        self.engine.advance(WORK_ID, 1000)
        self.corrupt_source()
        with self.assertRaises(WorkflowError) as caught:
            self.command("submit_node_result",
                         {"node": "n01", "attempt": 1, "object": "result",
                          "result": {"ids": IDS},
                          "input_digest": self.input_digest()},
                         actor="agent-executor")
        self.assertIn("digest", str(caught.exception))
        self.assertNotEqual(self.node_state()["state"], "completed")

    def test_the_materials_survive_a_restart(self):
        """A settlement after a restart resolves the same pinned material."""
        self.instantiate("action")
        self.write_source()
        self.engine.advance(WORK_ID, 1000)
        adapter = MaterialsAdapter({"ids": IDS})
        self.runtime, self.engine = self.build()
        self.engine.pump(adapter, 1000)
        self.engine.advance(WORK_ID, 1000)
        node = self.node_state()
        self.assertEqual(node["state"], "completed", node)
        materials = self.materials_of()
        self.assertEqual(materials[0]["object"], {"ids": IDS})


if __name__ == "__main__":
    unittest.main()
