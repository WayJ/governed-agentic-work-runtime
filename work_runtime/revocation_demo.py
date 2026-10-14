"""A deterministic revocation harness: withdraw current validity, keep history.

Runs the real Runtime, the persistent FakeOA and FakePublisher — no
credentials, no network, no model session. Each scenario owns a separate
fresh pair of databases, so every printed effect count is checkable against
its own external store. Revocation withdraws a proof's current authority
through the version-bound command protocol; it never rewrites receipts,
closure snapshots or accepted external effects, and it is not compensation:
every accepted effect stays counted, unreversed. The principals are trusted
local grants, not authenticated identities.
"""

import json
import tempfile
from pathlib import Path

from .adapters import FakeOA
from .demo import action, demo_grants, initialize, prerequisites, proof, send
from .policy import ExpensePolicy
from .publishing import FakePublisher, PublishingPolicy
from .runtime import Runtime

FINAL_LINE = ("3 scenarios; retained external effects: 2 accepted applications, "
              "1 published artifact; effects reversed: 0")


def revocation_grants():
    """Expense-family grants: finance is the approval source and may revoke."""
    grants = demo_grants()
    grants["root"] = {"work.intervene"}
    grants["finance"] = {"evidence.write", "evidence.revoke"}
    return grants


def publishing_revocation_grants():
    """Publishing-family grants: reviewer (approval) and publisher (accepted)
    are configured sources with revoke; root is the intervene administrator."""
    return {"agent": {"work.manage", "content.publish"},
            "reviewer": {"evidence.write", "evidence.revoke"},
            "author": {"evidence.write"},
            "publisher": {"evidence.revoke"},
            "root": {"work.intervene"}}


def article():
    return {"id": "ART-001", "title": "Revocation demo announcement",
            "body": "A release note whose approval is later withdrawn.",
            "requires_review": True}


def revoke(runtime, work_id, actor, source, event_id, reason, command_id, version=None):
    """One version-bound public revoke_evidence command (payload exactly D33)."""
    if version is None:
        version = runtime.get_work(work_id)["state_version"]
    return runtime.command(actor, command_id, work_id, "revoke_evidence",
                           {"source": source, "event_id": event_id, "reason": reason},
                           version)


def _requirement(work, rule_id):
    return next(r for r in work["requirements"] if r["rule_id"] == rule_id)


def json_event(event):
    return json.loads(event["body"])


def _publish(runtime, work_id="publish"):
    work = runtime.get_work(work_id)
    return send(runtime, work_id, "propose_action", {
        "capability": "content.publish", "document_digest": work["document_digest"],
        "contract_revision": work["contract"]["revision"],
        "plan_revision": work["plan_revision"]})


def _hold_scenario(folder):
    runtime = Runtime(str(folder / "runtime.sqlite"), ExpensePolicy(), revocation_grants())
    oa = FakeOA(str(folder / "oa.sqlite"))
    print("Scenario A — revoked approval holds dispatch; replacement readmits "
          "(own store: hold/)", flush=True)
    initialize(runtime, "hold")
    prerequisites(runtime, "hold", approval=False)
    proof(runtime, "hold", "approval", "finance", event_id="evt-hold-approval")
    runtime.verify_pending("hold")
    assert _requirement(runtime.get_work("hold"), "E05")["fulfillment"] == "satisfied"
    prepared = action(runtime, work_id="hold", command_id="hold-submit-once")
    assert prepared["decision"] == "accepted"
    operation_id = prepared["operation_id"]
    print("1. Verified finance approval → agent proposes submission → intent prepared",
          flush=True)
    version = runtime.get_work("hold")["state_version"]
    payload = {"source": "finance", "event_id": "evt-hold-approval",
               "reason": "approval withdrawn by finance"}
    receipt = runtime.command("finance", "hold-revoke-approval", "hold",
                              "revoke_evidence", payload, version)
    assert receipt["decision"] == "accepted"
    assert (receipt["evidence_status"], receipt["prior_status"]) == ("revoked", "verified")
    assert _requirement(runtime.get_work("hold"), "E05")["fulfillment"] == "pending"
    print('2. Finance (current approval source, evidence.revoke) revokes '
          '{source, event_id, reason} → accepted, evidence_status "revoked", '
          "prior verified; E05 pending", flush=True)
    blocked = action(runtime, work_id="hold")
    assert (blocked["decision"], blocked["code"]) == ("rejected", "REQUIREMENT_UNSATISFIED")
    assert "E05:EXP-001" in [blocker["id"] for blocker in blocked["blockers"]]
    print("3. Re-propose → rejected REQUIREMENT_UNSATISFIED (E05: a revoked proof "
          "no longer authorizes admission)", flush=True)
    held = runtime.dispatch(operation_id, oa)
    assert (held["status"], held["dispatch_state"], held["reason"]) == (
        "prepared", "held", "REQUIREMENT_UNSATISFIED")
    assert held["attempts"] == [] and oa.accepted_count() == 0
    print("4. Dispatch the prepared intent → held REQUIREMENT_UNSATISFIED, zero "
          "attempts, zero external calls", flush=True)
    events_before = len([event for event in runtime.events("hold")
                         if event["type"] == "EvidenceRevoked"])
    replay = runtime.command("finance", "hold-revoke-approval", "hold",
                             "revoke_evidence", payload, version)
    assert replay == receipt
    assert len([event for event in runtime.events("hold")
                if event["type"] == "EvidenceRevoked"]) == events_before == 1
    print("5. Replay the same revoke command → stored receipt verbatim; still "
          "exactly one EvidenceRevoked event", flush=True)
    resend = send(runtime, "hold", "record_evidence",
                  {"event_id": "evt-hold-approval", "kind": "approval",
                   "data": {"digest": runtime.get_work("hold")["document_digest"]}},
                  actor="finance")
    assert (resend["decision"], resend["evidence_status"]) == ("accepted", "revoked")
    assert resend["evidence_id"] == receipt["evidence_id"]
    print('6. Resend the SAME source event under a NEW command → same evidence id, '
          'evidence_status "revoked" — no new row, no revival', flush=True)
    proof(runtime, "hold", "approval", "finance", event_id="evt-hold-approval-2")
    runtime.verify_pending("hold")
    assert _requirement(runtime.get_work("hold"), "E05")["fulfillment"] == "satisfied"
    readmitted = action(runtime, work_id="hold")
    assert readmitted["decision"] == "accepted"
    assert readmitted["operation_id"] == operation_id
    assert "OperationReadmitted" in [event["type"] for event in runtime.events("hold")]
    confirmed = runtime.dispatch(operation_id, oa)
    assert confirmed["status"] == "confirmed_succeeded"
    assert oa.accepted_count() == 1
    print("7. REPLACEMENT approval (new event id) → E05 satisfied → SAME operation "
          "id readmitted → dispatch → confirmed_succeeded", flush=True)
    print("   accepted applications in this store: 1; effects reversed: 0\n", flush=True)
    return str(folder / "runtime.sqlite")


def _uncertain_scenario(folder):
    runtime = Runtime(str(folder / "runtime.sqlite"), ExpensePolicy(), revocation_grants())
    oa = FakeOA(str(folder / "oa.sqlite"))
    print("Scenario B — revoked proofs around an uncertain external effect "
          "(own store: uncertain/)", flush=True)
    initialize(runtime, "uncertain")
    prerequisites(runtime, "uncertain", approval=False)
    proof(runtime, "uncertain", "approval", "finance", event_id="evt-uncertain-approval")
    runtime.verify_pending("uncertain")
    prepared = action(runtime, work_id="uncertain", command_id="uncertain-submit-once")
    assert prepared["decision"] == "accepted"
    operation_id = prepared["operation_id"]
    print("1. Verified finance approval → agent proposes submission → intent prepared",
          flush=True)
    unknown = runtime.dispatch(operation_id,
                               FakeOA(str(folder / "oa.sqlite"), timeout_after_commit=True))
    assert unknown["status"] == "outcome_unknown" and oa.accepted_count() == 1
    print("2. Dispatch → OA accepted, response lost after commit → outcome_unknown "
          "(the effect exists)", flush=True)
    confirmed = runtime.reconcile(operation_id, FakeOA(str(folder / "oa.sqlite")))
    assert confirmed["status"] == "confirmed_succeeded"
    assert confirmed["external_id"].startswith("OA-")
    assert len(confirmed["attempts"]) == 1 and oa.accepted_count() == 1
    print("3. Reconcile the ORIGINAL business key → confirmed_succeeded, external "
          "id recovered, nothing resent; the uncertain effect is retained exactly "
          "once", flush=True)
    accepted_receipt = revoke(runtime, "uncertain", "root", "oa", operation_id,
                              "acceptance withdrawn by administrator",
                              "uncertain-revoke-acceptance")
    assert accepted_receipt["decision"] == "accepted"
    assert _requirement(runtime.get_work("uncertain"), "E08")["fulfillment"] == "pending"
    print("4. work.intervene administrator revokes the confirmed acceptance → "
          "E08 pending", flush=True)
    reproposed = action(runtime, work_id="uncertain")
    assert reproposed["operation_id"] == operation_id
    assert reproposed["operation_status_at_decision"] == "confirmed_succeeded"
    again = runtime.dispatch(operation_id, oa)
    assert again["status"] == "confirmed_succeeded" and oa.accepted_count() == 1
    print("5. Re-propose → SAME operation returned already confirmed_succeeded — "
          "a confirmed effect never re-executes to regenerate a revoked proof",
          flush=True)
    revoke(runtime, "uncertain", "finance", "finance", "evt-uncertain-approval",
           "approval withdrawn after the effect was confirmed",
           "uncertain-revoke-approval")
    assert _requirement(runtime.get_work("uncertain"), "E05")["fulfillment"] == "pending"
    print("6. Finance revokes the approval → E05 pending (current authority "
          "withdrawn after the fact)", flush=True)
    completion = send(runtime, "uncertain", "request_completion")
    assert (completion["decision"], completion["code"]) == (
        "rejected", "REQUIREMENT_UNSATISFIED")
    assert {"E05:EXP-001", "E08:EXP-001"} <= {b["id"] for b in completion["blockers"]}
    assert oa.accepted_count() == 1
    print("7. request_completion → rejected REQUIREMENT_UNSATISFIED (E05 revoked "
          "approval, E08 revoked acceptance); accepted applications in this "
          "store: 1; effects reversed: 0\n", flush=True)
    return str(folder / "runtime.sqlite")


def _publish_scenario(folder):
    runtime = Runtime(str(folder / "runtime.sqlite"), PublishingPolicy(),
                      publishing_revocation_grants())
    publisher = FakePublisher(str(folder / "publisher.sqlite"))
    print("Scenario C — publishing: hold, readmission, closed-work correction "
          "(own store: publish/)", flush=True)
    send(runtime, "publish", "create_work", {"document": article()})
    send(runtime, "publish", "bind_contract",
         {"policy_id": "content-publish", "policy_version": "demo-1",
          "goal": "content.published"})
    send(runtime, "publish", "revise_plan", {
        "steps": ["draft", "review", "confirm", "publish"],
        "open_requirements": ["C02"], "replan_when": ["reviewer rejects"]})
    for source, kind, event_id in (("reviewer", "approval", "evt-pub-approval"),
                                   ("author", "confirmation", "evt-pub-confirmation")):
        send(runtime, "publish", "record_evidence",
             {"event_id": event_id, "kind": kind,
              "data": {"digest": runtime.get_work("publish")["document_digest"]}},
             actor=source)
    runtime.verify_pending("publish")
    prepared = _publish(runtime)
    assert prepared["decision"] == "accepted"
    operation_id = prepared["operation_id"]
    print("1. Verified reviewer approval and author confirmation → publication "
          "intent prepared", flush=True)
    approval_receipt = revoke(runtime, "publish", "reviewer", "reviewer",
                              "evt-pub-approval", "reviewer withdraws the approval",
                              "pub-revoke-approval")
    assert approval_receipt["decision"] == "accepted"
    assert _requirement(runtime.get_work("publish"), "C02")["fulfillment"] == "pending"
    print("2. Reviewer (current approval source, evidence.revoke) revokes the "
          "approval → C02 pending", flush=True)
    held = runtime.dispatch(operation_id, publisher)
    assert (held["dispatch_state"], held["reason"]) == ("held", "REQUIREMENT_UNSATISFIED")
    assert held["attempts"] == [] and publisher.published_count() == 0
    print("3. Dispatch → held REQUIREMENT_UNSATISFIED, zero attempts, zero "
          "published artifacts", flush=True)
    send(runtime, "publish", "record_evidence",
         {"event_id": "evt-pub-approval-2", "kind": "approval",
          "data": {"digest": runtime.get_work("publish")["document_digest"]}},
         actor="reviewer")
    runtime.verify_pending("publish")
    readmitted = _publish(runtime)
    assert readmitted["operation_id"] == operation_id
    confirmed = runtime.dispatch(operation_id, publisher)
    assert confirmed["status"] == "confirmed_succeeded"
    assert publisher.published_count() == 1
    print("4. REPLACEMENT approval (new event id) → C02 satisfied → SAME operation "
          "id readmitted → published artifacts: 1", flush=True)
    completion = send(runtime, "publish", "request_completion")
    assert completion["decision"] == "accepted"
    work = runtime.get_work("publish")
    assert (work["status"], work["outcome"]) == ("closed", "succeeded")
    print("5. Evidence-backed completion → SUCCEEDED; the completion cites the "
          "verified acceptance", flush=True)
    completion_before = work["completion"]
    revoked_receipt = revoke(runtime, "publish", "root", "publisher", operation_id,
                             "publisher withdraws the acceptance",
                             "pub-revoke-acceptance")
    assert revoked_receipt["decision"] == "accepted"
    corrected = runtime.get_work("publish")
    assert (corrected["status"], corrected["outcome"]) == ("closed", "succeeded")
    assert corrected["completion"] == completion_before
    assert revoked_receipt["evidence_id"] in corrected["completion"]["evidence"]
    assert _requirement(corrected, "C04")["fulfillment"] == "pending"
    event = next(e for e in runtime.events("publish")
                 if e["type"] == "EvidenceRevoked"
                 and json_event(e)["source"] == "publisher")
    body = json_event(event)
    assert body["work_was_closed"] and body["completion_cites_evidence"]
    print("6. Administrator revokes the acceptance on the CLOSED work → outcome "
          "and completion stay byte-identical; C04 pending; EvidenceRevoked "
          "records work_was_closed and completion_cites_evidence", flush=True)
    resend = send(runtime, "publish", "record_evidence",
                  {"event_id": "evt-pub-approval", "kind": "approval",
                   "data": {"digest": runtime.get_work("publish")["document_digest"]}},
                  actor="reviewer")
    assert (resend["decision"], resend["evidence_status"]) == ("accepted", "revoked")
    assert resend["evidence_id"] == approval_receipt["evidence_id"]
    assert publisher.published_count() == 1
    print('7. Resend the revoked approval event under a NEW command → '
          'evidence_status "revoked", same evidence id; published artifacts in '
          "this store: 1; effects reversed: 0\n", flush=True)
    return str(folder / "runtime.sqlite")


def run_revocation_demo(directory=None):
    """Run the three revocation scenarios, each against its own fresh stores."""
    # Fresh directory per run; never removes existing user data.
    folder = Path(tempfile.mkdtemp(prefix="governed-revocation-", dir=directory))
    scenarios = (("hold", _hold_scenario), ("uncertain", _uncertain_scenario),
                 ("publish", _publish_scenario))
    stores = [scenario(folder / name) for name, scenario in scenarios]
    print(FINAL_LINE)
    print("\nInspect the durable history:")
    print(f'  python3 -m work_runtime inspect --db "{stores[0]}" --work hold')
    print(f'  python3 -m work_runtime inspect --db "{stores[1]}" --work uncertain')
    print(f'  python3 -m work_runtime inspect --db "{stores[2]}" --work publish '
          f'--policy content-publish')
    return folder
