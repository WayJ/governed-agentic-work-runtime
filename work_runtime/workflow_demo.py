"""A demonstration family for the mixed-node workflow runtime.

This module is a *demonstration*, not a core domain: the engine, the spec
language and the HTTP bridge know nothing about it. Everything the scenario
needs is data — a policy family, a validator registry, a published template
and a stand-in external system — so a different family replaces this file
without touching the runtime.

The scenario is the ten-node mixed-node shape: an agent prepares material, a
first human authority reviews it, a second human authority approves it, the
runtime dispatches one external action by itself, a responsible person
reports what was done, an independent reviewer checks it, the agent that
started the work writes the report in the original session, and the runtime
delivers the artifact. Nothing here proves a physical field outcome; it
proves the governance mechanics: exact-version approvals, one idempotent
external effect, durable intents and a restart that repeats no effect.
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .adapter_contract import AdapterContract
from .policy import digest
from .runtime import Runtime
from .workflow import WorkflowEngine
from .workflow_spec import ValidatorRegistry

CHECK_VERDICTS = ("passed", "failed", "insufficient", "conflict", "not_applicable")

POLICY_ID = "workflow-demo"
POLICY_VERSION = "demo-1"
POLICY_GOAL = "workflow.completed"


# The trusted platform runner of this family. It is a principal in the
# grants map, exactly like the other principals: trusted local
# configuration, not authentication.
RUNNER = "workflow-runner"


class WorkflowDemoPolicy:
    """A generic demonstration family: one work envelope plus typed evidence.

    The obligations are kind-level gates; the *exact version* of every
    approval is enforced by the engine, which matches a decision against the
    subject's revision and digest.
    """

    id = POLICY_ID
    version = POLICY_VERSION
    goal = POLICY_GOAL
    evidence_sources = {
        "safety_review": "reviewer-a",
        "project_approval": "reviewer-b",
        "field_report": "responsible-c",
        "independent_review": "reviewer-d",
        "agent_review": "reviewer-v",
        "dispatch_receipt": "business-system",
        "accepted": "business-system",
    }

    def validate_document(self, document: dict) -> None:
        if set(document) != {"id", "subject"}:
            raise ValueError("Document requires id and subject")
        if not isinstance(document["id"], str) or not document["id"]:
            raise ValueError("Document id must be a nonempty string")
        if not isinstance(document["subject"], str) or not document["subject"]:
            raise ValueError("Document subject must be a nonempty string")

    def validate_evidence(self, work: dict, candidate: dict) -> bool:
        data = candidate["data"]
        kind = candidate["kind"]
        if kind in ("safety_review", "project_approval", "field_report",
                    "independent_review"):
            return (set(data) == {"decision", "digest", "revision", "node",
                                  "attempt", "actor", "items"}
                    and data["decision"] in ("approved", "rejected", "request_material")
                    and isinstance(data["digest"], str) and bool(data["digest"])
                    and type(data["revision"]) is int and data["revision"] >= 1
                    and isinstance(data["node"], str) and bool(data["node"])
                    and type(data["attempt"]) is int and data["attempt"] >= 1
                    and isinstance(data["actor"], str) and bool(data["actor"])
                    and isinstance(data["items"], list)
                    and all(_criterion_item_ok(item) for item in data["items"]))
        if kind == "agent_review":
            return (set(data) == {"node", "attempt", "input_digest",
                                  "output_digest", "producer", "verdict", "items"}
                    and isinstance(data["node"], str) and bool(data["node"])
                    and type(data["attempt"]) is int and data["attempt"] >= 1
                    and isinstance(data["input_digest"], str)
                    and bool(data["input_digest"])
                    and isinstance(data["output_digest"], str)
                    and bool(data["output_digest"])
                    and isinstance(data["producer"], str) and bool(data["producer"])
                    and data["verdict"] in ("passed", "failed")
                    and isinstance(data["items"], list)
                    and all(_criterion_item_ok(item) for item in data["items"]))
        if kind in ("accepted", "dispatch_receipt"):
            return (set(data) == {"digest", "external_id"}
                    and isinstance(data["digest"], str) and bool(data["digest"])
                    and isinstance(data["external_id"], str)
                    and bool(data["external_id"]))
        return False

    def evaluate(self, work: dict, evidence: List[dict]) -> List[dict]:
        proofs = [entry for entry in evidence if entry["status"] == "verified"]

        def has(kind):
            return any(entry["kind"] == kind for entry in proofs)

        result = []

        def add(rule, satisfied, explanation):
            result.append({"id": rule + ":" + work["document"]["id"], "rule_id": rule,
                           "subject": work["document"]["id"],
                           "applicability": "applicable",
                           "fulfillment": "satisfied" if satisfied else "pending",
                           "explanation": explanation})

        add("R01", has("project_approval"),
            "Dispatching requires a verified project approval")
        add("R02", has("independent_review"),
            "Delivery requires a verified independent review")
        add("R03", has("field_report"),
            "Delivery requires a verified handling report")
        return result

    def action_blockers(self, capability: str, requirements: List[dict]) -> List[dict]:
        if capability not in ("work.dispatch", "work.deliver"):
            return [{"code": "CAPABILITY_UNSUPPORTED", "capability": capability}]
        wanted = {"work.dispatch": ("R01",),
                  "work.deliver": ("R01", "R02", "R03")}[capability]
        return [r for r in requirements
                if r["rule_id"] in wanted and
                (r["applicability"] in ("unknown", "conflict") or
                 (r["applicability"] == "applicable" and r["fulfillment"] != "satisfied"))]

    def operation_key(self, capability: str, work: dict) -> str:
        return digest([self.id, capability, work["document"]["id"],
                       work["document_revision"]])


def workflow_demo_grants() -> Dict[str, set]:
    """Trusted-local principals. Configuration, not authentication."""
    return {
        "coordinator": {"work.manage", "work.dispatch", "work.deliver"},
        # The trusted platform runner: the only principal that may accept a
        # successful workflow and freeze it.
        RUNNER: {"workflow.finalize"},
        "agent-executor": {"workflow.execute"},
        "reviewer-a": {"evidence.write"},
        "reviewer-b": {"evidence.write"},
        "responsible-c": {"evidence.write"},
        "reviewer-d": {"evidence.write"},
        "reviewer-v": {"evidence.write"},
        "business-system": {"evidence.write"},
    }


# --------------------------------------------------------------------------
# Shapes and validators
# --------------------------------------------------------------------------

INTAKE_SHAPE = {
    "type": "object",
    "properties": {
        "records": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"},
                           "source": {"type": "string"}},
            "required": ["id", "source"]}},
        "standard": {"type": "string"},
    },
    "required": ["records", "standard"],
}

ANALYSIS_SHAPE = {
    "type": "object",
    "properties": {
        "findings": {"type": "array", "items": {
            "type": "object",
            "properties": {"issueId": {"type": "string"},
                           "clause": {"type": "string"},
                           "finding": {"type": "string"}},
            "required": ["issueId", "clause", "finding"]}},
    },
    "required": ["findings"],
}

PROPOSAL_SHAPE = {
    "type": "object",
    "properties": {
        "measures": {"type": "array", "items": {
            "type": "object",
            "properties": {"issueId": {"type": "string"},
                           "measureId": {"type": "string"},
                           "measure": {"type": "string"}},
            "required": ["issueId", "measureId", "measure"]}},
    },
    "required": ["measures"],
}

REPORT_SHAPE = {
    "type": "object",
    "properties": {
        "sections": {"type": "array", "items": {
            "type": "object",
            "properties": {"title": {"type": "string"},
                           "body": {"type": "string"}},
            "required": ["title", "body"]}},
    },
    "required": ["sections"],
}

# The shape of the record a human decision carries: the business record the
# decision archived, with its own identifier, its kind and who made it.
RECORD_SHAPE = {
    "type": "object",
    "properties": {"recordId": {"type": "string"},
                   "kind": {"type": "string"},
                   "actor": {"type": "string"},
                   "items": {"type": "array", "items": {"type": "string"}}},
    "required": ["recordId", "kind", "actor", "items"],
}

# The shape of the business record the external system returns. It is the
# material the automatic nodes validate before the workflow routes on.
EFFECT_SHAPE = {
    "type": "object",
    "properties": {
        "recordId": {"type": "string"},
        "action": {"type": "string"},
        "items": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["recordId", "action", "items"],
}


def _criterion_item_ok(item) -> bool:
    """One criterion report item.

    The evidence may be absent: a shortage keeps its true reason and does
    not invent a reference. A pass carries its evidence, and the core
    enforces that.
    """
    if not isinstance(item, dict):
        return False
    if not {"check", "verdict", "reason"} <= set(item):
        return False
    if set(item) - {"check", "verdict", "reason", "evidence"}:
        return False
    if not isinstance(item["check"], str) or not item["check"]:
        return False
    if item["verdict"] not in CHECK_VERDICTS:
        return False
    if not isinstance(item["reason"], str):
        return False
    evidence = item.get("evidence")
    if evidence is not None and not isinstance(evidence, list):
        return False
    return True


def _require_entries(result, key, code):
    entries = result.get(key)
    if not isinstance(entries, list) or not entries:
        return [{"code": code, "message": "The candidate has no entries",
                 "location": key}]
    return []


def _verdicts(node_ref, reason, evidence=None):
    """A passed verdict for every declared criterion of the node."""
    return [{"check": check, "verdict": "passed", "reason": reason,
             "evidence": list(evidence) if evidence else ["criterion:" + check]}
            for check in (node_ref.get("checks") or [])]


def record(work, node_ref, result):
    """The record a human decision carries, judged against the criterion.

    It must name itself, say what kind of record it is, name who made it
    and name what it is about.
    """
    findings = []
    if not isinstance(result, dict):
        return {"findings": [{"code": "RECORD_NOT_OBJECT",
                              "message": "The record is not an object"}],
                "checks": []}
    if not isinstance(result.get("recordId"), str) or not result["recordId"]:
        findings.append({"code": "RECORD_UNIDENTIFIED",
                         "message": "The record does not name itself"})
    if not isinstance(result.get("kind"), str) or not result["kind"]:
        findings.append({"code": "RECORD_UNKINDED",
                         "message": "The record does not say what it is"})
    if not isinstance(result.get("actor"), str) or not result["actor"]:
        findings.append({"code": "RECORD_UNATTRIBUTED",
                         "message": "The record does not name who made it"})
    if not result.get("items"):
        findings.append({"code": "RECORD_EMPTY",
                         "message": "The record names no item"})
    verdict = "failed" if findings else "passed"
    reason = ("the record names what it archived" if not findings
              else "the record did not satisfy the criterion")
    checks = [{"check": check, "verdict": verdict, "reason": reason,
               "evidence": ["record:" + str(result.get("recordId"))]}
              for check in (node_ref.get("checks") or [])]
    return {"findings": findings, "checks": checks}


def effect(work, node_ref, result):
    """The receipt the external system returned, judged against the criterion.

    The receipt must name the effect it recorded, it must be the effect of
    the capability the node declared, and it must name what it acted on.
    """
    findings = []
    if not isinstance(result, dict):
        return {"findings": [{"code": "EFFECT_NOT_OBJECT",
                              "message": "The receipt is not an object"}],
                "checks": []}
    record_id = result.get("recordId")
    if not isinstance(record_id, str) or not record_id:
        findings.append({"code": "EFFECT_UNIDENTIFIED",
                         "message": "The receipt does not name the effect"})
    capability = node_ref.get("capability")
    if capability and result.get("action") != capability:
        findings.append({"code": "EFFECT_ACTION_MISMATCH",
                         "message": "The receipt names another action"})
    if not result.get("items"):
        findings.append({"code": "EFFECT_EMPTY",
                         "message": "The receipt names no item"})
    verdict = "failed" if findings else "passed"
    reason = ("the receipt names the effect it recorded" if not findings
              else "the receipt did not satisfy the criterion")
    checks = [{"check": check, "verdict": verdict, "reason": reason,
               "evidence": ["receipt:" + str(record_id)]}
              for check in (node_ref.get("checks") or [])]
    return {"findings": findings, "checks": checks}


def workflow_demo_validators() -> ValidatorRegistry:
    """Host-registered, version-pinned business validators.

    Registering a validator is a host trust decision. The registry never
    runs anything until both the id and the version resolve. A validator
    answers with the findings it found and a verdict for every criterion
    the protected definition declared for the node.
    """
    registry = ValidatorRegistry()

    def intake(work, node_ref, result):
        findings = _require_entries(result, "records", "INTAKE_EMPTY")
        for index, entry in enumerate(result.get("records") or []):
            if not isinstance(entry, dict) or not entry.get("source"):
                findings.append({"code": "INTAKE_UNSOURCED",
                                 "message": "Every extracted record needs a source",
                                 "location": "records[" + str(index) + "]"})
        return {"findings": findings,
                "checks": _verdicts(node_ref, "every record names its source")}

    def analysis(work, node_ref, result):
        findings = _require_entries(result, "findings", "ANALYSIS_EMPTY")
        for index, entry in enumerate(result.get("findings") or []):
            if isinstance(entry, dict) and not entry.get("clause"):
                findings.append({"code": "ANALYSIS_UNCITED",
                                 "message": "Every finding needs a clause reference",
                                 "location": "findings[" + str(index) + "]"})
        return {"findings": findings,
                "checks": _verdicts(node_ref, "every finding cites a clause")}

    def proposal(work, node_ref, result):
        findings = _require_entries(result, "measures", "PROPOSAL_EMPTY")
        seen = set()
        for index, entry in enumerate(result.get("measures") or []):
            if not isinstance(entry, dict):
                continue
            if not entry.get("measureId"):
                findings.append({"code": "PROPOSAL_UNIDENTIFIED",
                                 "message": "Every measure needs a stable identifier",
                                 "location": "measures[" + str(index) + "]"})
            if entry.get("measureId") in seen:
                findings.append({"code": "PROPOSAL_DUPLICATE",
                                 "message": "Measure identifiers must be unique",
                                 "location": "measures[" + str(index) + "]"})
            seen.add(entry.get("measureId"))
        return {"findings": findings,
                "checks": _verdicts(node_ref, "every issue has an identified measure")}

    def report(work, node_ref, result):
        findings = _require_entries(result, "sections", "REPORT_EMPTY")
        return {"findings": findings,
                "checks": _verdicts(node_ref, "the report covers the signed record")}

    def review_specification(work, node_ref, result):
        """The review configuration a human criterion is bound to.

        It judges nothing by itself: the human decision carries the verdict.
        It exists so the protected definition can pin the review rules'
        version and fail closed when that version is not loadable.
        """
        return {"findings": [], "checks": []}

    registry.register("review-rubric", "1", review_specification)
    registry.register("intake", "1", intake)
    registry.register("analysis", "1", analysis)
    registry.register("proposal", "1", proposal)
    registry.register("report", "1", report)
    registry.register("effect", "1", effect)
    registry.register("record", "1", record)
    for name in ("safety-review", "project-approval", "field-report",
                 "independent-review"):
        registry.register(name, "1", review_specification)
    return registry


# --------------------------------------------------------------------------
# The published definition: the scenario is data
# --------------------------------------------------------------------------

def workflow_demo_template(template_id="inspection-review-delivery",
                           version="test-1", policy_family=POLICY_ID) -> Dict[str, Any]:
    """The ten-node scenario as a published definition."""
    return {
        "id": template_id,
        "version": version,
        "policy_family": policy_family,
        "entry": "n01",
        "terminal": ["n10"],
        "required_checks": ["N01-1", "N03-1", "N04-2", "N04-3", "N05-3",
                            "N06-1", "N06W-1", "N07-2", "N08-3", "N08-4",
                            "N09-2", "N10-1"],
        "parameters_schema": {
            "type": "object",
            "properties": {"subject": {"type": "string"},
                           "sessionId": {"type": "string"}},
            "required": ["subject"]},
        "nodes": {
            "n01": {"kind": "agent", "executor": "agent-executor", "max_attempts": 2,
                    "output": {"object": "intake",
                               "validation": {"shape": INTAKE_SHAPE,
                                              "validator": "intake",
                                              "validator_version": "1"}},
                    "checks": [{"id": "N01-1",
                                "method": "PROGRAM",
                                "criterion": "Every extracted record names the "
                                            "source it came from.",
                                "criterion_version": "1",
                                "validator": "intake",
                                "validator_version": "1"}]},
            "n02": {"kind": "agent", "executor": "agent-executor", "max_attempts": 2,
                    "inputs": [{"object": "intake"}],
                    "output": {"object": "analysis",
                               "validation": {"shape": ANALYSIS_SHAPE,
                                              "validator": "analysis",
                                              "validator_version": "1"}},
                    "checks": [{"id": "N02-1",
                                "method": "PROGRAM",
                                "criterion": "Every finding cites a clause of "
                                            "the adopted standard.",
                                "criterion_version": "1",
                                "validator": "analysis",
                                "validator_version": "1"}]},
            "n03": {"kind": "agent", "executor": "agent-executor", "max_attempts": 2,
                    "inputs": [{"object": "analysis"}],
                    "output": {"object": "proposal",
                               "validation": {"shape": PROPOSAL_SHAPE,
                                              "validator": "proposal",
                                              "validator_version": "1"}},
                    "checks": [{"id": "N03-1",
                                "method": "PROGRAM",
                                "criterion": "Every issue has a measure with a "
                                            "stable identifier.",
                                "criterion_version": "1",
                                "validator": "proposal",
                                "validator_version": "1"}]},
            "n04": {"kind": "human", "evidence_kind": "safety_review",
                    "authority": "reviewer-a", "subject": {"object": "proposal"},
                    "on_reject": "n03", "max_attempts": 3,
                    "output": {"object": "safety_approval",
                               "validation": {"shape": RECORD_SHAPE,
                                              "validator": "record",
                                              "validator_version": "1"}},
                    "checks": [{"id": "N04-2",
                                "method": "HUMAN",
                                "criterion": "The proposal covers every applicable "
                                            "requirement and cites its doubt.",
                                "criterion_version": "1",
                                "validator": "safety-review",
                                "validator_version": "1"},
                               {"id": "N04-3",
                                "method": "PROGRAM",
                                "criterion": "The approval record names the record "
                                            "it archived.",
                                "criterion_version": "1",
                                "validator": "record",
                                "validator_version": "1"}]},
            "n05": {"kind": "human", "evidence_kind": "project_approval",
                    "authority": "reviewer-b", "subject": {"object": "proposal"},
                    "inputs": [{"object": "safety_approval"}],
                    "on_reject": "n03", "max_attempts": 3,
                    "distinct_from": ["n04"],
                    "checks": [{"id": "N05-3",
                                "method": "HUMAN",
                                "criterion": "The arrangement names a responsible "
                                            "party, a deadline and its basis.",
                                "criterion_version": "1",
                                "validator": "project-approval",
                                "validator_version": "1"}]},
            "n06": {"kind": "action", "capability": "work.dispatch",
                    "subject": {"object": "proposal"},
                    "output": {"object": "order",
                               "evidence_kind": "dispatch_receipt",
                               "validation": {"shape": EFFECT_SHAPE,
                                              "validator": "effect",
                                              "validator_version": "1"}},
                    "checks": [{"id": "N06-1",
                                "method": "PROGRAM",
                                "criterion": "The dispatch receipt names the "
                                            "order it created.",
                                "criterion_version": "1",
                                "validator": "effect",
                                "validator_version": "1"}]},
            "n06w": {"kind": "wait", "deadline_s": 86400,
                     "match": {"evidence_kind": "dispatch_receipt",
                               "subject": {"object": "order"},
                               "bind": {"node": "n06"}},
                     "output": {"object": "dispatch_receipt",
                                "validation": {"shape": EFFECT_SHAPE,
                                               "validator": "effect",
                                               "validator_version": "1"}},
                     "checks": [{"id": "N06W-1",
                                 "method": "PROGRAM",
                                 "criterion": "The dispatch receipt names the "
                                             "order it created.",
                                 "criterion_version": "1",
                                 "validator": "effect",
                                 "validator_version": "1"}]},
            "n07": {"kind": "human", "evidence_kind": "field_report",
                    "authority": "responsible-c", "subject": {"object": "order"},
                    "inputs": [{"object": "order"}],
                    "max_attempts": 3,
                    "output": {"object": "field_feedback",
                               "validation": {"shape": RECORD_SHAPE,
                                              "validator": "record",
                                              "validator_version": "1"}},
                    "checks": [{"id": "N07-1",
                                "method": "HUMAN",
                                "criterion": "Every measure has a result and the "
                                            "material of this round.",
                                "criterion_version": "1",
                                "validator": "field-report",
                                "validator_version": "1"},
                               {"id": "N07-2",
                                "method": "PROGRAM",
                                "criterion": "The feedback record names the record "
                                            "it archived.",
                                "criterion_version": "1",
                                "validator": "record",
                                "validator_version": "1"}]},
            "n08": {"kind": "human", "evidence_kind": "independent_review",
                    "authority": "reviewer-d", "subject": {"object": "order"},
                    "inputs": [{"object": "order"}],
                    "on_reject": "n07", "max_attempts": 3,
                    "distinct_from": ["n07"],
                    "output": {"object": "verification",
                               "validation": {"shape": RECORD_SHAPE,
                                              "validator": "record",
                                              "validator_version": "1"}},
                    "checks": [{"id": "N08-3",
                                "method": "HUMAN",
                                "criterion": "Every applicable requirement has an "
                                            "independent conclusion.",
                                "criterion_version": "1",
                                "validator": "independent-review",
                                "validator_version": "1"},
                               {"id": "N08-4",
                                "method": "PROGRAM",
                                "criterion": "The verification record names the "
                                            "record it archived.",
                                "criterion_version": "1",
                                "validator": "record",
                                "validator_version": "1"}]},
            "n09": {"kind": "agent", "executor": "agent-executor", "max_attempts": 2,
                    "review": {"evidence_kind": "agent_review",
                               "reviewer": "reviewer-v",
                               "rubric": {"validator": "review-rubric",
                                          "validator_version": "1"}},
                    "output": {"object": "report",
                               "validation": {"shape": REPORT_SHAPE,
                                              "validator": "report",
                                              "validator_version": "1"}},
                    "checks": [{"id": "N09-2",
                                "method": "PROGRAM",
                                "criterion": "The report covers the signed record "
                                            "without changing it.",
                                "criterion_version": "1",
                                "validator": "report",
                                "validator_version": "1"},
                               {"id": "N09-2-review",
                                "criterion": "An independent reviewer confirms "
                                            "that the report follows the record.",
                                "method": "AGENT",
                                "criterion_version": "1",
                                "validator": "review-rubric",
                                "validator_version": "1"}]},
            "n10": {"kind": "action", "capability": "work.deliver",
                    "subject": {"object": "report"},
                    "output": {"object": "delivery",
                               "validation": {"shape": EFFECT_SHAPE,
                                              "validator": "effect",
                                              "validator_version": "1"}},
                    "checks": [{"id": "N10-1",
                                "method": "PROGRAM",
                                "criterion": "The delivery receipt names the "
                                            "delivery it recorded.",
                                "criterion_version": "1",
                                "validator": "effect",
                                "validator_version": "1"}]},
        },
        "edges": [{"from": "n01", "to": "n02"},
                  {"from": "n02", "to": "n03"},
                  {"from": "n03", "to": "n04"},
                  {"from": "n04", "to": "n05"},
                  {"from": "n05", "to": "n06"},
                  {"from": "n06", "to": "n06w"},
                  {"from": "n06w", "to": "n07"},
                  {"from": "n07", "to": "n08"},
                  {"from": "n08", "to": "n09"},
                  {"from": "n09", "to": "n10"}],
    }


# --------------------------------------------------------------------------
# The stand-in external system
# --------------------------------------------------------------------------

def effect_payload(action, external_id, document) -> Dict[str, Any]:
    """The business record the external system created.

    The record is what the external system really knows about the effect;
    the workflow engine validates it and adopts it as a named object. It is
    derived from the material the action was given, never invented here.
    """
    items = []
    for key in ("measures", "sections", "records", "findings"):
        for entry in document.get(key) or []:
            if not isinstance(entry, dict):
                continue
            for field in ("measureId", "id", "issueId", "title"):
                value = entry.get(field)
                if isinstance(value, str) and value:
                    items.append(value)
                    break
    if not items and isinstance(document.get("id"), str):
        items = [document["id"]]
    return {"recordId": external_id, "action": action, "items": items}


class DemoBusinessSystem:
    """A persistent stand-in for the external business system.

    Its own store survives the process, so an effect committed before a crash
    is still findable by key afterwards. The effect count is read back from
    that store, never from a counter in the process that performed it.
    """
    contract = AdapterContract(
        actions=("work.dispatch", "work.deliver"),
        idempotency_scope="adapter-store:key",
        retention="lifetime-of-store",
        lookup_consistency="authoritative-by-key",
        uniqueness=("external.id",),
        supports_action_context=True)

    def __init__(self, path: str):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15)
        try:
            db.execute("CREATE TABLE IF NOT EXISTS effects ("
                       "key TEXT PRIMARY KEY, digest TEXT, action TEXT, result TEXT)")
            db.commit()
        finally:
            db.close()
        self.calls = 0

    def execute(self, key: str, document: dict, content_digest: str, *,
                action=None, compensates=None) -> dict:
        self.calls += 1
        db = sqlite3.connect(self.path, timeout=15)
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT digest,result FROM effects WHERE key=?",
                              (key,)).fetchone()
            if row is not None:
                if row[0] != content_digest:
                    raise ValueError("Idempotency key reused with different content")
                result = json.loads(row[1])
            else:
                external_id = "EXT-" + digest([key, action])[:12]
                result = {"status": "accepted",
                          "external_id": external_id,
                          "digest": content_digest,
                          "action": action,
                          "payload": effect_payload(action, external_id, document)}
                db.execute("INSERT INTO effects VALUES (?,?,?,?)",
                           (key, content_digest, action, json.dumps(result)))
            db.commit()
        finally:
            db.close()
        return result

    def lookup(self, key: str) -> Optional[dict]:
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT result FROM effects WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None
        finally:
            db.close()

    def effect_count(self) -> int:
        """The number of distinct external effects, counted in the store."""
        db = sqlite3.connect(self.path)
        try:
            return db.execute("SELECT COUNT(*) FROM effects").fetchone()[0]
        finally:
            db.close()

    def effects(self) -> List[dict]:
        db = sqlite3.connect(self.path)
        try:
            return [json.loads(row[0]) for row in
                    db.execute("SELECT result FROM effects ORDER BY rowid")]
        finally:
            db.close()


# --------------------------------------------------------------------------
# The demonstration
# --------------------------------------------------------------------------

CANONICAL_RESULTS = {
    "intake": {"records": [{"id": "REC-1", "source": "inspection-log"}],
               "standard": "STD-2026-01"},
    "analysis": {"findings": [{"issueId": "H-001", "clause": "STD-2026-01#3.2",
                               "finding": "the east parapet guard is incomplete"}]},
    "proposal": {"measures": [{"issueId": "H-001", "measureId": "M-1",
                                "measure": "complete the guard and record the result"}]},
    "report": {"sections": [{"title": "What happened",
                             "body": "the guard was completed and independently checked"}]},
}


def build_demo_runtime(path: str, adapter=None) -> Tuple[Runtime, WorkflowEngine]:
    runtime = Runtime(path, WorkflowDemoPolicy(), workflow_demo_grants())
    engine = WorkflowEngine(runtime, workflow_demo_validators(), runner=RUNNER)
    return runtime, engine


def _version(runtime, work_id):
    return runtime.get_work(work_id)["state_version"]


def _send(runtime, actor, work_id, kind, payload, command_id=None):
    return runtime.command(actor, command_id or uuid.uuid4().hex, work_id, kind,
                           payload, _version(runtime, work_id))


def _record_decision(runtime, engine, work_id, kind, source, decision,
                     digest_value, revision, event_id=None, node=None, attempt=None,
                     actor=None, items=None, evidence=None, result=None):
    """Record a human decision: the node, the attempt, the actor, the
    itemized verdict for every criterion the node declared and, when the
    node declares one, the named record the decision carries."""
    if attempt is None and node is not None:
        attempt = _attempt(engine, work_id, node)
    if items is None and node is not None:
        items = _decision_items(node, evidence=evidence)
    payload = {"node": node, "attempt": attempt, "decision": decision,
               "digest": digest_value, "revision": revision,
               "actor": actor or source, "items": items or []}
    if result is not None:
        payload["result"] = result
    if event_id is not None:
        payload["event_id"] = event_id
    receipt = engine.command(source, event_id or uuid.uuid4().hex, work_id,
                             "record_decision", payload,
                             _version(runtime, work_id))
    if receipt.get("decision") == "accepted":
        runtime.verify_pending(work_id)
        engine.advance(work_id, int(__import__("time").time()))
    return receipt


def _decision_items(node, verdict="passed", reason="reviewed against the criterion",
                    evidence=None):
    """The human's verdict for every criterion the human judges.

    A criterion another judge owns keeps its own identifier and its own
    record: the program criterion of a node is judged by the validator, not
    by the human's decision.
    """
    template = workflow_demo_template()
    declaration = (template.get("nodes") or {}).get(node) or {}
    return [{"check": check["id"], "verdict": verdict, "reason": reason,
             "evidence": list(evidence) if evidence else ["proposal#revision-1"]}
            for check in declaration.get("checks") or []
            if check.get("method") in (None, "HUMAN")]


def _object_reference(runtime, work_id, name):
    with runtime._connection() as db:
        row = db.execute("SELECT name,revision,digest FROM workflow_objects "
                         "WHERE work_id=? AND name=? ORDER BY revision DESC LIMIT 1",
                         (work_id, name)).fetchone()
    return {"name": row[0], "revision": row[1], "digest": row[2]}


def run_workflow_demo(directory=None):
    """The ten-node scenario with a real crash, a restart and counted effects."""
    folder = Path(tempfile.mkdtemp(prefix="governed-workflow-", dir=directory))
    runtime_path = folder / "runtime.sqlite"
    effects_path = folder / "business-system.sqlite"
    work_id = "W-001"
    session_id = "session-original-1"

    runtime, engine = build_demo_runtime(str(runtime_path))
    system = DemoBusinessSystem(str(effects_path))
    template = workflow_demo_template()
    published = engine.publish_template("coordinator", template)
    assert published["decision"] == "accepted", published
    print(f"0. Published template {published['template_id']}@{published['template_version']}"
          f" (digest {published['digest'][:12]}…)", flush=True)

    runtime.command("coordinator", "create", work_id, "create_work",
                    {"document": {"id": "H-001", "subject": "east parapet"}}, None)
    runtime.command("coordinator", "contract", work_id, "bind_contract",
                    {"policy_id": POLICY_ID, "policy_version": POLICY_VERSION,
                     "goal": POLICY_GOAL}, _version(runtime, work_id))
    runtime.command("coordinator", "plan", work_id, "revise_plan",
                    {"steps": ["n01", "n02", "n03", "n04", "n05", "n06", "n07",
                               "n08", "n09", "n10"],
                     "open_requirements": ["R01"],
                     "replan_when": ["a reviewer rejects the proposal"]},
                    _version(runtime, work_id))
    bound = engine.command("coordinator", "bind", work_id, "bind_workflow",
                            {"template_id": template["id"],
                             "template_version": template["version"],
                             "parameters": {"subject": "east parapet"},
                             "session_id": session_id},
                            _version(runtime, work_id))
    assert bound["decision"] == "accepted", bound
    engine.advance(work_id, int(__import__("time").time()))
    print(f"1. Instance bound to the published definition; session {session_id}",
          flush=True)

    # -- N01 to N03: the agent prepares the material ----------------------
    for node, name in (("n01", "intake"), ("n02", "analysis"), ("n03", "proposal")):
        attempt = _attempt(engine, work_id, node)
        receipt = engine.command("agent-executor", uuid.uuid4().hex, work_id,
                                 "submit_node_result",
                                 {"node": node, "attempt": attempt, "object": name,
                                  "result": CANONICAL_RESULTS[name],
                                  "input_digest": _input_digest(engine, work_id, node)},
                                 _version(runtime, work_id))
        assert receipt["decision"] == "accepted", receipt
    proposal = _object_reference(runtime, work_id, "proposal")
    print(f"2. N01–N03 agent nodes accepted and validated; proposal revision "
          f"{proposal['revision']} (digest {proposal['digest'][:12]}…)", flush=True)

    # -- N04: the safety reviewer approves and archives the record --------
    approval = {"recordId": "APR-" + proposal["digest"][:8], "kind": "safety_approval",
                "actor": "reviewer-a", "items": ["M-1"]}
    _record_decision(runtime, engine, work_id, "safety_review", "reviewer-a",
                     "approved", proposal["digest"], proposal["revision"],
                     node="n04", result=approval)
    archived = _object_reference(runtime, work_id, "safety_approval")
    pending = engine.intents(kind="human_task")
    assert [entry["node"] for entry in pending] == ["n05"], pending
    print(f"3. N04 approved → GAWR archived the signed approval record "
          f"{archived['name']} revision {archived['revision']} and created "
          f"the N05 task {pending[0]['id']} with no agent turn in between",
          flush=True)

    # -- N05: the project approver approves; the runtime dispatches -------
    _record_decision(runtime, engine, work_id, "project_approval", "reviewer-b",
                     "approved", proposal["digest"], proposal["revision"],
                     node="n05")
    operations = _operations(runtime, work_id)
    assert len(operations) == 1, operations
    operation = operations[0]
    print(f"4. N05 approved → the runtime prepared exactly one external action "
          f"{operation['id']} (key {operation['business_key'][:12]}…)", flush=True)

    # -- the crash chapter -------------------------------------------------
    process = subprocess.run(
        [sys.executable, "-m", "work_runtime", "workflow-worker",
         "--runtime", str(runtime_path), "--system", str(effects_path),
         "--operation", operation["id"], "--crash-after-effect"], check=False)
    assert process.returncode == 73, process.returncode
    counted = DemoBusinessSystem(str(effects_path)).effect_count()
    assert counted == 1, counted
    print("5. The worker committed the effect and died before recording it "
          "(a real process crash)", flush=True)

    runtime, engine = build_demo_runtime(str(runtime_path))
    system = DemoBusinessSystem(str(effects_path))
    engine.recover(system, int(__import__("time").time()))
    counted = DemoBusinessSystem(str(effects_path)).effect_count()
    assert counted == 1, counted
    recovered = runtime.get_operation(operation["id"])
    assert recovered["status"] == "confirmed_succeeded", recovered
    print(f"6. Restart → the original operation was looked up, not repeated: "
          f"status {recovered['status']}, external effects {counted}", flush=True)

    # -- N07 to N08: the responsible person and the independent reviewer --
    engine.advance(work_id, int(__import__("time").time()))
    order = _object_reference(runtime, work_id, "order")
    view = engine.instance(work_id)
    n06 = [entry for entry in view["nodes"] if entry["node"] == "n06"][0]
    n06w = [entry for entry in view["nodes"] if entry["node"] == "n06w"][0]
    assert n06["state"] == "completed", n06
    assert n06["quality"]["mode"] == "validated", n06
    assert n06w["state"] == "completed", n06w
    print(f"7. N06 dispatch receipt validated → order revision "
          f"{order['revision']} (digest {order['digest'][:12]}…); N06W wait "
          f"matched the bound proof {n06w['waitMatch']['eventId']}", flush=True)
    _record_decision(runtime, engine, work_id, "field_report", "responsible-c",
                     "approved", order["digest"], order["revision"], node="n07",
                     evidence=["order#revision-" + str(order["revision"])],
                     result={"recordId": "FB-" + order["digest"][:8],
                             "kind": "field_report", "actor": "responsible-c",
                             "items": ["M-1"]})
    _record_decision(runtime, engine, work_id, "independent_review", "reviewer-d",
                     "approved", order["digest"], order["revision"], node="n08",
                     evidence=["order#revision-" + str(order["revision"])],
                     result={"recordId": "VR-" + order["digest"][:8],
                             "kind": "independent_review", "actor": "reviewer-d",
                             "items": ["M-1"]})
    feedback = _object_reference(runtime, work_id, "field_feedback")
    verification = _object_reference(runtime, work_id, "verification")
    agent_intents = engine.intents(kind="agent_task", status="pending")
    assert len(agent_intents) == 1, agent_intents
    assert agent_intents[0]["session_id"] == session_id, agent_intents
    print(f"8. N07 and N08 judged the order itself (revision "
          f"{order['revision']}) and archived their own records "
          f"({feedback['name']}, {verification['name']}) → the original session "
          f"was queued with the stable request id {agent_intents[0]['id']}",
          flush=True)

    # -- N09: the report, and the independent review of the report --------
    attempt = _attempt(engine, work_id, "n09")
    receipt = engine.command("agent-executor", uuid.uuid4().hex, work_id,
                             "submit_node_result",
                             {"node": "n09", "attempt": attempt, "object": "report",
                              "result": CANONICAL_RESULTS["report"],
                              "input_digest": _input_digest(engine, work_id, "n09")},
                             _version(runtime, work_id))
    assert receipt["decision"] == "accepted", receipt
    report = _object_reference(runtime, work_id, "report")
    view = engine.instance(work_id)
    n09 = [entry for entry in view["nodes"] if entry["node"] == "n09"][0]
    assert n09["state"] == "submitted", n09
    node = [entry for entry in engine.instance(work_id)["nodes"]
            if entry["node"] == "n09"][0]
    runtime.command("reviewer-v", uuid.uuid4().hex, work_id, "record_evidence",
                    {"event_id": uuid.uuid4().hex, "kind": "agent_review",
                     "data": {"node": "n09", "attempt": node["attempt"],
                              "input_digest": node["inputDigest"],
                              "output_digest": report["digest"],
                              "producer": "reviewer-v", "verdict": "passed",
                              "items": [{"check": "N09-2-review", "verdict": "passed",
                                         "reason": "the report follows the record",
                                         "evidence": ["proposal#revision-1"]}]}}, None)
    runtime.verify_pending(work_id)
    engine.advance(work_id, int(__import__("time").time()))
    print("9. N09 report accepted, then completed only after the independent "
          "review evidence arrived", flush=True)

    # -- N10: the delivery -------------------------------------------------
    engine.pump(system, int(__import__("time").time()))
    counted = DemoBusinessSystem(str(effects_path)).effect_count()
    assert counted == 2, counted
    view = engine.instance(work_id)
    assert view["workflowStatus"] == "finished", view
    print(f"10. N10 delivery receipt validated → external effects {counted} "
          f"(one dispatch, one delivery); workflow {view['workflowStatus']}",
          flush=True)

    # -- the acceptance: the runner freezes the successful workflow --------
    receipt = engine.command(RUNNER, "final-1", work_id,
                              "finalize_workflow_success", {},
                              _version(runtime, work_id))
    assert receipt["decision"] == "accepted", receipt
    finalization = receipt["finalization"]
    assert finalization["terminal"]["outcome"] == "completed", finalization
    assert finalization["finalizedBy"] == RUNNER, finalization
    # The completion read answers the same snapshot, every time.
    assert engine.finalization(work_id) == finalization
    # Nothing may change an accepted workflow: the manager's revision and
    # the runner's second acceptance are both refused.
    refused = engine.command("coordinator", "object-after-final", work_id,
                              "revise_object",
                              {"name": "proposal", "object": {"measures": []}},
                              _version(runtime, work_id))
    assert refused["decision"] == "rejected", refused
    again = engine.command(RUNNER, "final-2", work_id,
                            "finalize_workflow_success", {},
                            _version(runtime, work_id))
    assert again["decision"] == "rejected", again
    print(f"11. The trusted runner accepted the successful workflow and froze it "
          f"(finalization {finalization['finalizationId'][:12]}…, terminal "
          f"{finalization['terminal']['node']}, snapshot digest "
          f"{finalization['digest'][:12]}…); a later revision is refused "
          f"({refused['code']}) and a second acceptance creates no second "
          f"finalization ({again['code']})", flush=True)

    # -- the counts are read back independently ----------------------------
    effects = DemoBusinessSystem(str(effects_path)).effects()
    print("\nExternal effects recorded in the business system's own store:")
    for effect in effects:
        print(f"  - {effect['action']} → {effect['external_id']}")
    print("\nInspect the durable history:")
    print(f'  python3 -m work_runtime inspect --db "{runtime_path}" --work {work_id}')
    return folder


def _attempt(engine, work_id, node):
    for entry in engine.instance(work_id)["nodes"]:
        if entry["node"] == node:
            return entry["attempt"]
    return 0


def _input_digest(engine, work_id, node):
    """The digest of the inputs the node currently pins."""
    for entry in engine.instance(work_id)["nodes"]:
        if entry["node"] == node:
            return entry.get("inputDigest")
    return None


def _operations(runtime, work_id):
    with runtime._connection() as db:
        return [json.loads(row[0]) for row in
                db.execute("SELECT body FROM operations WHERE work_id=?",
                           (work_id,))]


def run_workflow_worker(runtime_path, system_path, operation_id,
                        crash_after_effect=False):
    """Dispatch one operation; optionally die after the external effect."""
    runtime, _ = build_demo_runtime(runtime_path)
    system = DemoBusinessSystem(system_path)
    fault = (lambda: os._exit(73)) if crash_after_effect else None
    runtime.dispatch(operation_id, system, fault=fault)
