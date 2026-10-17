"""A deterministic support-ticket harness: unknown blocks admission, a crash recovers by reference.

Runs the real Runtime and the persistent GitHub-issue-shaped FakeIssueTracker
— no credentials, no network, no model session, no secrets: all data is
fixed. Chapter one files a critical billing ticket through triage — an
unresolved severity or category blocks acceptance because unknown never
passes as within-policy — the desk then commits an in-budget SLA and the
tracker accepts the ticket as issue #1; the work closes on the tracker's
acceptance evidence. Chapter two dispatches a second ticket through a
grants-carrying worker subprocess that really dies (exit 73) after the
tracker accepted the write; a restarted Runtime recovers() by the
ticket-reference business key — the original receipt, exactly one attempt,
nothing re-sent — and the work closes. Every printed count is checkable
against the stores directly. The principals are trusted local grants, not
authenticated identities.
"""

import json
import sqlite3
import tempfile
import uuid
from pathlib import Path

from .runtime import Runtime
from .support import FakeIssueTracker, SupportPolicy, run_crash_worker, support_grants

FINAL_LINE = ("2 works; issues filed: 2; crash-recovered receipts: 1; "
              "effects re-sent: 0")


def _send(runtime, work_id, kind, payload=None, actor="agent", command_id=None):
    version = None if kind in ("create_work", "record_evidence") \
        else runtime.get_work(work_id)["state_version"]
    return runtime.command(actor, command_id or uuid.uuid4().hex, work_id, kind,
                           payload, version)


def _initialize(runtime, work_id, document):
    _send(runtime, work_id, "create_work", {"document": document})
    _send(runtime, work_id, "bind_contract",
          {"policy_id": SupportPolicy.id, "policy_version": SupportPolicy.version,
           "goal": SupportPolicy.goal})
    _send(runtime, work_id, "revise_plan",
          {"steps": ["triage", "commit-sla", "dispatch"],
           "open_requirements": ["T01", "T02"],
           "replan_when": ["triage cannot resolve"]})


def _propose(runtime, work_id, command_id):
    work = runtime.get_work(work_id)
    return _send(runtime, work_id, "propose_action", {
        "capability": "ticket.dispatch",
        "document_digest": work["document_digest"],
        "contract_revision": work["contract"]["revision"],
        "plan_revision": work["plan_revision"]}, command_id=command_id)


def _record_sla(runtime, work_id, minutes, event_id):
    current = runtime.get_work(work_id)["document_digest"]
    return _send(runtime, work_id, "record_evidence",
                 {"event_id": event_id, "kind": "sla",
                  "data": {"digest": current,
                           "response_target_minutes": minutes}},
                 actor="support-desk")


def _count(path, sql):
    db = sqlite3.connect(str(path))
    try:
        return db.execute(sql).fetchone()[0]
    finally:
        db.close()


def run_demo(directory=None):
    # Fresh directory per run; never removes existing user data.
    folder = Path(tempfile.mkdtemp(prefix="governed-support-", dir=directory))
    runtime_path, tracker_path = folder / "runtime.sqlite", folder / "tracker.sqlite"
    policy = SupportPolicy()

    print("Chapter 1 — forward: triage resolves the unknown, the tracker "
          "files the issue", flush=True)
    runtime = Runtime(str(runtime_path), policy, support_grants())
    first = "ticket-1"
    _initialize(runtime, first, {"id": "TCK-1001",
                                 "summary": "Payment failed after the update",
                                 "severity": None, "category": None})
    blocked = _propose(runtime, first, "propose-unresolved")
    assert blocked["decision"] == "rejected"
    assert blocked["code"] == "APPLICABILITY_UNRESOLVED"
    print("1. Ticket filed with unresolved severity and category → proposal "
          "BLOCKED (APPLICABILITY_UNRESOLVED): unknown never passes as "
          "within-policy; issues: 0", flush=True)

    triaged = _send(runtime, first, "revise_document", {
        "document": {"id": "TCK-1001", "summary": "Payment failed after the update",
                     "severity": "critical", "category": "billing"}})
    assert triaged["decision"] == "accepted"
    no_sla = _propose(runtime, first, "propose-no-sla")
    assert no_sla["code"] == "REQUIREMENT_UNSATISFIED"
    print("2. Triage resolves severity=critical and category=billing → the "
          "urgent SLA now applies and blocks dispatch until the desk commits "
          "one (REQUIREMENT_UNSATISFIED); issues: 0", flush=True)

    sla = _record_sla(runtime, first, 45, "evt-sla-1")
    assert sla["decision"] == "accepted"
    runtime.verify_pending(first)
    proposal = _propose(runtime, first, "dispatch-once")
    assert proposal["decision"] == "accepted"
    print("3. The support desk commits a 45-minute SLA (critical budget 60) "
          "→ verified → admission accepted; the business key is the ticket "
          "reference, not a content digest", flush=True)

    tracker = FakeIssueTracker(str(tracker_path))
    confirmed = runtime.dispatch(proposal["operation_id"], tracker)
    assert confirmed["status"] == "confirmed_succeeded"
    assert confirmed["external_id"] == "#1"
    assert tracker.issue_count() == 1
    print("4. Dispatch → the tracker accepts the ticket as issue #1 → "
          "confirmed_succeeded with a GitHub-issue-shaped receipt; issues: 1",
          flush=True)

    completion = _send(runtime, first, "request_completion", command_id="complete-1")
    assert completion["decision"] == "accepted"
    work = runtime.get_work(first)
    assert (work["status"], work["outcome"]) == ("closed", "succeeded")
    print("5. The tracker-source acceptance satisfies the goal → work closed "
          "succeeded; issues: 1", flush=True)

    print("Chapter 2 — crash recovery: the worker dies after the tracker "
          "accepted the write", flush=True)
    second = "ticket-2"
    _initialize(runtime, second, {"id": "TCK-1002",
                                  "summary": "Cannot sign in on mobile",
                                  "severity": "high", "category": "technical"})
    sla = _record_sla(runtime, second, 120, "evt-sla-2")
    assert sla["decision"] == "accepted"
    runtime.verify_pending(second)
    proposal = _propose(runtime, second, "dispatch-high")
    assert proposal["decision"] == "accepted"
    print("6. A second ticket (TCK-1002, high/technical, 120-minute SLA within "
          "the 240 budget) enters its own work on the same stores → prepared",
          flush=True)

    child = run_crash_worker(runtime_path, tracker_path, proposal["operation_id"])
    assert child.returncode == 73, child.returncode
    tracker = FakeIssueTracker(str(tracker_path))
    assert tracker.issue_count() == 2
    assert runtime.get_operation(proposal["operation_id"])["status"] == "dispatched"
    print("7. A grants-carrying worker subprocess dispatches it → the tracker "
          "files issue #2 → the worker dies before recording the outcome "
          f"(exit code {child.returncode}). The shipped worker CLI cannot "
          "take this step: it hardwires the expense demo grants and the OA "
          "adapter", flush=True)

    restarted = Runtime(str(runtime_path), policy, support_grants())
    recovered = restarted.recover(FakeIssueTracker(str(tracker_path)))
    assert len(recovered) == 1
    operation = restarted.get_operation(proposal["operation_id"])
    assert operation["status"] == "confirmed_succeeded"
    assert operation["external_id"] == "#2"
    assert len(operation["attempts"]) == 1
    assert tracker.issue_count() == 2
    assert _count(tracker_path, "SELECT COUNT(*) FROM receipts") == 2
    print("8. Restart → recover() reconciles the ticket-reference business "
          "key → the original receipt recovered, confirmed_succeeded in "
          "exactly one attempt (nothing re-sent); issues: 2; receipts: 2",
          flush=True)

    completion = _send(restarted, second, "request_completion",
                       command_id="complete-2")
    assert completion["decision"] == "accepted"
    work = restarted.get_work(second)
    assert (work["status"], work["outcome"]) == ("closed", "succeeded")
    print("9. The second work closes on its own acceptance evidence → "
          "closed succeeded", flush=True)

    # Closing truth read from the stores directly, never parsed from stdout.
    assert _count(tracker_path, "SELECT COUNT(*) FROM issues") == 2
    db = sqlite3.connect(str(tracker_path))
    try:
        statuses = [json.loads(row[0])["status"] for row in
                    db.execute("SELECT result FROM receipts")]
    finally:
        db.close()
    assert statuses == ["accepted", "accepted"]
    for work_id in (first, second):
        db = sqlite3.connect(str(runtime_path))
        try:
            state = json.loads(db.execute(
                "SELECT state FROM works WHERE id=?", (work_id,)).fetchone()[0])
        finally:
            db.close()
        assert (state["status"], state["outcome"]) == ("closed", "succeeded")
    print(FINAL_LINE, flush=True)
    print("\nInspect the durable history:")
    print(f'  python3 -m work_runtime inspect --db "{runtime_path}" --work {first} '
          f'--policy support-ticket')
    print(f'  python3 -m work_runtime inspect --db "{runtime_path}" --work {second} '
          f'--policy support-ticket')
    return folder
