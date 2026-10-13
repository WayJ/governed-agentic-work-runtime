"""A deterministic proposer: no model credentials required."""

import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from .adapters import FakeOA
from .policy import ExpensePolicy
from .runtime import Runtime


def demo_grants():
    return {"agent": {"work.manage", "expense.submit"},
            "finance": {"evidence.write"}, "requester": {"evidence.write"},
            "invoice-service": {"evidence.write"}, "expense-service": {"evidence.write"}}


def document(amount=120000, limit=100000, invoice_id="INV-001", document_id="EXP-001"):
    return {"id": document_id, "amount": amount, "limit": limit,
            "invoices": [{"id": invoice_id, "revision": 1}], "sealed": True}


def send(runtime, work_id, kind, payload=None, actor="agent", command_id=None):
    version = None if kind in ("create_work", "record_evidence") else runtime.get_work(work_id)["state_version"]
    return runtime.command(actor, command_id or uuid.uuid4().hex, work_id, kind, payload, version)


def initialize(runtime, work_id="demo", doc=None):
    send(runtime, work_id, "create_work", {"document": doc or document()})
    send(runtime, work_id, "bind_contract", {"policy_id": "expense-submit",
         "policy_version": "demo-1", "goal": "expense.accepted"})
    send(runtime, work_id, "revise_plan", {"steps": ["verify", "approve", "confirm", "submit"],
         "open_requirements": ["E05"], "replan_when": ["invoice anomaly"]})


def proof(runtime, work_id, kind, actor, data=None, event_id=None):
    work = runtime.get_work(work_id)
    return send(runtime, work_id, "record_evidence", {
        "event_id": event_id or uuid.uuid4().hex, "kind": kind,
        "data": data if data is not None else {"digest": work["document_digest"]}}, actor=actor)


def prerequisites(runtime, work_id="demo", approval=True):
    work = runtime.get_work(work_id)
    for invoice in work["document"]["invoices"]:
        proof(runtime, work_id, "invoice_valid", "invoice-service", {
            "invoice_id": invoice["id"], "invoice_revision": invoice["revision"], "valid": True})
    proof(runtime, work_id, "duplicate_clear", "expense-service")
    proof(runtime, work_id, "confirmation", "requester")
    if approval:
        proof(runtime, work_id, "approval", "finance")
    runtime.verify_pending(work_id)


def action(runtime, work_id="demo", command_id=None):
    work = runtime.get_work(work_id)
    return send(runtime, work_id, "propose_action", {
        "capability": "expense.submit", "document_digest": work["document_digest"],
        "contract_revision": work["contract"]["revision"], "plan_revision": work["plan_revision"]},
        command_id=command_id)


def run_demo(directory=None):
    # Fresh directory per run; never removes existing user data.
    folder = Path(tempfile.mkdtemp(prefix="governed-work-", dir=directory))
    runtime_path, oa_path = folder / "runtime.sqlite", folder / "oa.sqlite"
    runtime = Runtime(str(runtime_path), ExpensePolicy(), demo_grants())
    oa = FakeOA(str(oa_path))
    initialize(runtime)
    prerequisites(runtime, approval=False)
    receipt = action(runtime)
    assert receipt["decision"] == "rejected"
    print("1. Agent proposes submission → BLOCKED by E05 (approval missing)", flush=True)
    wait = {"requirement_id": "E05:EXP-001", "deadline": 2000000000, "owner": "finance"}
    send(runtime, "demo", "register_wait", wait)
    print("2. Work waits durably; no model session needs to stay alive", flush=True)
    proof(runtime, "demo", "approval", "finance")
    runtime.verify_pending("demo")
    receipt = action(runtime, command_id="submit-once")
    assert receipt["decision"] == "accepted"
    operation_id = receipt["operation_id"]
    print("3. Finance approves current content → submission intent accepted", flush=True)
    process = subprocess.run([sys.executable, "-m", "work_runtime", "worker",
                              "--runtime", str(runtime_path), "--oa", str(oa_path),
                              "--operation", operation_id, "--crash-after-effect"], check=False)
    assert process.returncode == 73, process.returncode
    assert oa.accepted_count() == 1
    print("4. OA accepts → worker exits before saving the response (real process crash)", flush=True)
    restarted = Runtime(str(runtime_path), ExpensePolicy(), demo_grants())
    restarted.recover(oa)
    assert restarted.get_operation(operation_id)["status"] == "confirmed_succeeded"
    print("5. Restart → query original operation → existing OA receipt recovered", flush=True)
    replay = action(restarted, command_id="another-request-same-operation")
    assert replay["operation_id"] == operation_id
    final = send(restarted, "demo", "request_completion")
    assert final["decision"] == "accepted"
    assert oa.accepted_count() == 1
    print("6. Evidence-backed completion → SUCCEEDED; external applications created: 1")
    print("\nInspect the durable history:")
    print(f'  python3 -m work_runtime inspect --db "{runtime_path}" --work demo')
    return folder


def run_worker(runtime_path, oa_path, operation_id, crash_after_effect=False):
    runtime = Runtime(runtime_path, ExpensePolicy(), demo_grants())
    runtime.dispatch(operation_id, FakeOA(oa_path),
                     fault=(lambda: os._exit(73)) if crash_after_effect else None)
