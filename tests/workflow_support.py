"""Shared fixtures for the mixed-node workflow tests.

The demonstration family itself lives in the package
(``work_runtime.workflow_demo``), so the tests and the shipped demonstration
exercise exactly the same definition, policy and validators. This module
only holds the test-side helpers.
"""

import uuid
from typing import List

from work_runtime.policy import digest
from work_runtime.runtime import Runtime
from work_runtime.workflow import WorkflowEngine
from work_runtime.workflow_demo import (ANALYSIS_SHAPE as DEMO_ANALYSIS_SHAPE,
                                         INTAKE_SHAPE as DEMO_INTAKE_SHAPE,
                                         PROPOSAL_SHAPE as DEMO_PROPOSAL_SHAPE,
                                         DemoBusinessSystem, WorkflowDemoPolicy,
                                         workflow_demo_grants,
                                         workflow_demo_template,
                                         workflow_demo_validators)

POLICY_ID = "workflow-demo"
POLICY_VERSION = "demo-1"
POLICY_GOAL = "workflow.completed"

# The names the tests use.
DemoPolicy = WorkflowDemoPolicy
demo_grants = workflow_demo_grants
demo_validators = workflow_demo_validators
scenario_template = workflow_demo_template
RecordingAdapter = DemoBusinessSystem

INTAKE_SHAPE = None
ANALYSIS_SHAPE = None
PROPOSAL_SHAPE = None
REPORT_SHAPE = None

# A definition of its own: one agent node that validates its input and
# carries a deadline. The demonstration family declares no validation on
# the input of n02 and no deadline on any agent node, and every object it
# names is produced by one of its own nodes, so a family of its own is
# needed for externally supplied material.
FOCUSED_TEMPLATE = {
    "id": "material-wait-focused",
    "version": "test-1",
    "policy_family": POLICY_ID,
    "entry": "n01",
    "terminal": ["n01"],
    "nodes": {
        "n01": {"kind": "agent", "executor": "agent-executor", "max_attempts": 2,
                "deadline_s": 60,
                "inputs": [{"object": "intake",
                            "validation": {"shape": DEMO_INTAKE_SHAPE,
                                           "validator": "intake",
                                           "validator_version": "1"}}],
                "output": {"object": "analysis",
                           "validation": {"shape": DEMO_ANALYSIS_SHAPE,
                                          "validator": "analysis",
                                          "validator_version": "1"}},
                "checks": [{"id": "N01-1", "method": "PROGRAM",
                            "criterion": "Every finding cites a clause.",
                            "criterion_version": "1",
                            "validator": "analysis",
                            "validator_version": "1"}]},
    },
    "edges": [],
}


def build(path, policy=None, grants=None, validators=None, runner=None,
          resolver=None):
    """A runtime with a workflow engine attached."""
    runtime = Runtime(path, policy or DemoPolicy(), grants or demo_grants())
    engine = WorkflowEngine(runtime, validators if validators is not None
                            else demo_validators(), runner=runner,
                            resolver=resolver)
    return runtime, engine


def document(work_id="H-001", subject="east parapet"):
    return {"id": work_id, "subject": subject}


def version_of(runtime, work_id):
    return runtime.get_work(work_id)["state_version"]


def send(runtime, actor, work_id, kind, payload=None, command_id=None,
         expected_version=None):
    if expected_version is None and kind not in ("create_work", "record_evidence"):
        expected_version = version_of(runtime, work_id)
    return runtime.command(actor, command_id or uuid.uuid4().hex, work_id, kind,
                           payload, expected_version)


def instantiate(runtime, engine, work_id="W-1", template=None, parameters=None,
                actor="coordinator", participants=None):
    """Create the work, bind the contract, plan and published template."""
    spec = template or scenario_template()
    send(runtime, actor, work_id, "create_work", {"document": document()})
    send(runtime, actor, work_id, "bind_contract",
         {"policy_id": POLICY_ID, "policy_version": POLICY_VERSION,
          "goal": POLICY_GOAL})
    send(runtime, actor, work_id, "revise_plan",
         {"steps": ["n01", "n02", "n03", "n04", "n05", "n06", "n07", "n08",
                    "n09", "n10"],
          "open_requirements": ["R01"], "replan_when": ["review rejects"]})
    payload = {"template_id": spec["id"],
               "template_version": spec["version"],
               "parameters": parameters or {"subject": "east parapet"}}
    if participants is not None:
        payload["participants"] = participants
    receipt = engine.command(actor, uuid.uuid4().hex, work_id, "bind_workflow",
                              payload, version_of(runtime, work_id))
    return receipt


def submit(engine, runtime, work_id, node, attempt, name, result,
           actor="agent-executor", input_digest=None):
    if input_digest is None:
        input_digest = input_digest_of(engine, work_id, node)
    return engine.command(actor, uuid.uuid4().hex, work_id, "submit_node_result",
                          {"node": node, "attempt": attempt, "object": name,
                           "result": result, "input_digest": input_digest},
                          version_of(runtime, work_id))


def input_digest_of(engine, work_id, node):
    """The digest of the inputs a node currently pins."""
    for entry in engine.instance(work_id)["nodes"]:
        if entry["node"] == node:
            return entry.get("inputDigest")
    return None


def decide(runtime, engine, work_id, kind, source, decision, digest_value, revision,
           event_id=None, node=None, attempt=None, actor=None, items=None,
           result=None, raw=False):
    """Record a human decision as evidence from its configured trusted source.

    The decision binds the node and the attempt it was made for, names the
    actor who decided (never the ingress source) and carries the itemized
    verdict for every criterion the node declared.
    """
    if node is None:
        node = NODE_BY_EVIDENCE_KIND.get(kind)
    if attempt is None and node is not None:
        attempt = current_attempt(engine, runtime, work_id, node)
    if items is None and node is not None:
        items = default_items(node)
    if result is None and not raw:
        result = default_result(node, actor or source)
    if result is not None:
        # The node declares a named record. A record can only arrive with
        # the decision itself, so the decision goes through the workflow
        # command — the same CAS-guarded path a host uses.
        return decide_command(engine, runtime, work_id, kind, source, decision,
                              digest_value, revision, node=node, attempt=attempt,
                              actor=actor, items=items, command_id=event_id,
                              result=result)
    data = {"decision": decision, "digest": digest_value, "revision": revision,
            "node": node, "attempt": attempt, "actor": actor or source,
            "items": items or []}
    receipt = send(runtime, source, work_id, "record_evidence",
                   {"event_id": event_id or uuid.uuid4().hex, "kind": kind,
                    "data": data})
    runtime.verify_pending(work_id)
    engine.advance(work_id, 1_000_000)
    return receipt


NODE_BY_EVIDENCE_KIND = {
    "safety_review": "n04",
    "project_approval": "n05",
    "field_report": "n07",
    "independent_review": "n08",
}


def default_items(node, verdict="passed", reason="reviewed against the criterion",
                  evidence=None):
    """One verdict per criterion the human judges.

    A criterion another judge owns keeps its own identifier and its own
    record: the program criterion of a node is judged by the validator, not
    by the human's decision.
    """
    template = scenario_template()
    declaration = (template.get("nodes") or {}).get(node) or {}
    items = []
    for check in declaration.get("checks") or []:
        identifier = check["id"] if isinstance(check, dict) else check
        method = check.get("method") if isinstance(check, dict) else None
        if method not in (None, "HUMAN"):
            continue
        items.append({"check": identifier, "verdict": verdict, "reason": reason,
                      "evidence": evidence or ["document#revision-1"]})
    return items


def default_result(node, actor):
    """The named record a human decision carries, when the node declares one."""
    template = scenario_template()
    declaration = (template.get("nodes") or {}).get(node) or {}
    output = declaration.get("output") or {}
    if not output:
        return None
    kind = declaration.get("evidence_kind") or "record"
    return {"recordId": "REC-" + kind + "-" + uuid.uuid4().hex[:6],
            "kind": kind, "actor": actor, "items": ["M-1"]}


def decide_command(engine, runtime, work_id, kind, source, decision, digest_value,
                   revision, node=None, attempt=None, actor=None, items=None,
                   command_id=None, expected_version=None, result=None):
    """Admit a decision through the workflow command (CAS + dedup).

    The command's actor is the ingress source; the actual decider is the
    asserted actor in the payload. The named record the node declares is
    carried in the same command, so the caller's compare-and-swap covers it.
    """
    if node is None:
        node = NODE_BY_EVIDENCE_KIND.get(kind)
    if attempt is None and node is not None:
        attempt = current_attempt(engine, runtime, work_id, node)
    if items is None and node is not None:
        items = default_items(node)
    payload = {"node": node, "attempt": attempt, "decision": decision,
               "digest": digest_value, "revision": revision,
               "actor": actor or source, "items": items or []}
    if result is not None:
        payload["result"] = result
    if expected_version is None:
        expected_version = version_of(runtime, work_id)
    receipt = engine.command(source, command_id or uuid.uuid4().hex, work_id,
                             "record_decision", payload, expected_version)
    if receipt.get("decision") == "accepted":
        runtime.verify_pending(work_id)
        engine.advance(work_id, 1_000_000)
    return receipt


def instance_of(engine, runtime, work_id, node):
    for entry in engine.instance(work_id)["nodes"]:
        if entry["node"] == node:
            return entry
    return None


VALID_RESULTS = {
    "intake": {"records": [{"id": "R-1", "source": "site-log"}], "standard": "STD-1"},
    "analysis": {"findings": [{"issueId": "H-001", "clause": "C-1",
                                "finding": "gap"}]},
    "proposal": {"measures": [{"issueId": "H-001", "measureId": "M-1",
                                "measure": "install guard"}]},
    "report": {"sections": [{"title": "summary", "body": "text"}]},
}


def current_attempt(engine, runtime, work_id, node):
    entry = instance_of(engine, runtime, work_id, node)
    return entry["attempt"] if entry else 0


def submit_valid(engine, runtime, work_id, node, name, result=None,
                 actor="agent-executor"):
    attempt = current_attempt(engine, runtime, work_id, node)
    payload = VALID_RESULTS[name] if result is None else result
    return submit(engine, runtime, work_id, node, attempt, name, payload, actor=actor)


# A family of its own, shaped like the safety workflow: a source read
# that produces the archived material, two consumers that judge it, and a
# third that waits for what is still missing. Every consumer declares a
# material budget, so a controlled replacement may revalidate it.
REVALIDATION_TEMPLATE = {
    "id": "material-revalidation-focused",
    "version": "test-1",
    "policy_family": POLICY_ID,
    "entry": "s00",
    "terminal": ["n03"],
    "nodes": {
        "s00": {"kind": "action", "capability": "work.dispatch",
                "subject": {"object": "request"},
                "output": {"object": "sources",
                           "validation": {"shape": {
                               "type": "object",
                               "properties": {"recordId": {"type": "string"},
                                              "action": {"type": "string"},
                                              "items": {"type": "array",
                                                        "items": {"type": "string"}}},
                               "required": ["recordId", "action", "items"]},
                           "validator": "effect", "validator_version": "1"}},
                "checks": [{"id": "N00-1", "method": "PROGRAM",
                            "criterion": "The receipt names the effect it "
                                         "recorded.",
                            "criterion_version": "1",
                            "validator": "effect",
                            "validator_version": "1"}],
                "max_attempts": 1},
        "n01": {"kind": "agent", "executor": "agent-executor", "max_attempts": 2,
                "material_generations": 1,
                "inputs": [{"object": "sources"}],
                "output": {"object": "intake",
                           "validation": {"shape": DEMO_INTAKE_SHAPE,
                                          "validator": "intake",
                                          "validator_version": "1"}},
                "checks": [{"id": "N01-1", "method": "PROGRAM",
                            "criterion": "Every extracted record names its "
                                         "source.",
                            "criterion_version": "1",
                            "validator": "intake",
                            "validator_version": "1"}]},
        "n02": {"kind": "agent", "executor": "agent-executor", "max_attempts": 2,
                "material_generations": 1,
                "inputs": [{"object": "intake"}, {"object": "sources"}],
                "output": {"object": "analysis",
                           "validation": {"shape": DEMO_ANALYSIS_SHAPE,
                                          "validator": "analysis",
                                          "validator_version": "1"}},
                "checks": [{"id": "N02-1", "method": "PROGRAM",
                            "criterion": "Every finding cites a clause.",
                            "criterion_version": "1",
                            "validator": "analysis",
                            "validator_version": "1"}]},
        "n03": {"kind": "agent", "executor": "agent-executor", "max_attempts": 2,
                "material_generations": 1,
                "inputs": [{"object": "analysis"}],
                "output": {"object": "proposal",
                           "validation": {"shape": DEMO_PROPOSAL_SHAPE,
                                          "validator": "proposal",
                                          "validator_version": "1"}},
                "checks": [{"id": "N03-1", "method": "PROGRAM",
                            "criterion": "Every measure has a stable identifier.",
                            "criterion_version": "1",
                            "validator": "proposal",
                            "validator_version": "1"}]},
    },
    "edges": [{"from": "s00", "to": "n01"}, {"from": "n01", "to": "n02"},
              {"from": "n02", "to": "n03"}],
}


class RevalidationPolicy:
    """A family whose source read is not gated by an approval obligation.

    The demonstration family blocks every dispatch until a project approval
    exists. A source read is a trusted read of an archive, so this family
    declares no obligation: the *engine* still decides whether a node may
    be revalidated, and the business effect is still never replayed.
    """

    id = POLICY_ID
    version = POLICY_VERSION
    goal = POLICY_GOAL
    evidence_sources = {"dispatch_receipt": "business-system",
                        "accepted": "business-system"}

    def validate_document(self, document: dict) -> None:
        if set(document) != {"id", "subject"}:
            raise ValueError("Document requires id and subject")
        if not isinstance(document["id"], str) or not document["id"]:
            raise ValueError("Document id must be a nonempty string")
        if not isinstance(document["subject"], str) or not document["subject"]:
            raise ValueError("Document subject must be a nonempty string")

    def validate_evidence(self, work: dict, candidate: dict) -> bool:
        data = candidate["data"]
        if candidate["kind"] in ("dispatch_receipt", "accepted"):
            return (set(data) == {"digest", "external_id"}
                    and isinstance(data["digest"], str) and bool(data["digest"])
                    and isinstance(data["external_id"], str))
        return False

    def evaluate(self, work: dict, evidence: List[dict]) -> List[dict]:
        return []

    def action_blockers(self, capability: str,
                        requirements: List[dict]) -> List[dict]:
        if capability not in ("work.dispatch", "work.deliver"):
            return [{"code": "CAPABILITY_UNSUPPORTED", "capability": capability}]
        return []

    def operation_key(self, capability: str, work: dict) -> str:
        return digest([self.id, capability, work["document"]["id"],
                       work["document_revision"]])
