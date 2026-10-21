"""Shared fixtures for the mixed-node workflow tests.

The demonstration family itself lives in the package
(``work_runtime.workflow_demo``), so the tests and the shipped demonstration
exercise exactly the same definition, policy and validators. This module
only holds the test-side helpers.
"""

import json
import sqlite3
import uuid

from work_runtime.policy import digest
from work_runtime.runtime import Runtime
from work_runtime.workflow import WorkflowEngine
from work_runtime.workflow_demo import (DemoBusinessSystem, WorkflowDemoPolicy,
                                         workflow_demo_grants,
                                         workflow_demo_template,
                                         workflow_demo_validators)
from work_runtime.workflow_spec import ValidatorRegistry

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


def build(path, policy=None, grants=None, validators=None, runner=None):
    """A runtime with a workflow engine attached."""
    runtime = Runtime(path, policy or DemoPolicy(), grants or demo_grants())
    engine = WorkflowEngine(runtime, validators if validators is not None
                            else demo_validators(), runner=runner)
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
                actor="coordinator"):
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
    receipt = engine.command(actor, uuid.uuid4().hex, work_id, "bind_workflow",
                              {"template_id": spec["id"],
                               "template_version": spec["version"],
                               "parameters": parameters or {"subject": "east parapet"}},
                              version_of(runtime, work_id))
    return receipt


def submit(engine, runtime, work_id, node, attempt, name, result, actor="agent-executor"):
    return engine.command(actor, uuid.uuid4().hex, work_id, "submit_node_result",
                          {"node": node, "attempt": attempt, "object": name,
                           "result": result}, version_of(runtime, work_id))


def decide(runtime, engine, work_id, kind, source, decision, digest_value, revision,
           event_id=None):
    """Record a human decision as evidence from its configured trusted source."""
    receipt = send(runtime, source, work_id, "record_evidence",
                   {"event_id": event_id or uuid.uuid4().hex, "kind": kind,
                    "data": {"decision": decision, "digest": digest_value,
                             "revision": revision}})
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
