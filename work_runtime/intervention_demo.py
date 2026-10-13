"""A deterministic intervention harness: transfer, cancel and migrate.

Runs the real Runtime and the persistent FakeOA — no credentials, no network,
no model session. Each scenario owns a separate fresh pair of databases, so
every printed effect count is checkable against its own external store.
Cancellation acknowledgement records an external effect; it never reverses it.
"""

import tempfile
from pathlib import Path

from .adapters import FakeOA
from .demo import demo_grants, document, initialize, prerequisites, proof, send
from .policy import ExpensePolicy, ExpensePolicyV2
from .runtime import CommandError, Runtime


def intervention_grants():
    grants = demo_grants()
    grants["root"] = {"work.intervene"}
    grants["delegate"] = {"work.manage", "expense.submit"}
    return grants


def registry_runtime(path):
    """Default v1 policy plus the explicit v1/v2 registry (identity for demo-1)."""
    v1 = ExpensePolicy()
    return Runtime(path, v1, intervention_grants(),
                   policies={"demo-1": v1, "demo-2": ExpensePolicyV2()})


def _propose(runtime, work_id, command_id, actor="agent"):
    """Return (payload, state version, receipt) for one submission proposal."""
    work = runtime.get_work(work_id)
    payload = {"capability": "expense.submit", "document_digest": work["document_digest"],
               "contract_revision": work["contract"]["revision"],
               "plan_revision": work["plan_revision"]}
    return payload, work["state_version"], send(
        runtime, work_id, "propose_action", payload, actor=actor, command_id=command_id)


def _requirement(runtime, work_id, rule):
    return next(r for r in runtime.get_work(work_id)["requirements"] if r["rule_id"] == rule)


def _transfer_scenario(folder):
    runtime = Runtime(str(folder / "runtime.sqlite"), ExpensePolicy(), intervention_grants())
    oa = FakeOA(str(folder / "oa.sqlite"))
    print("Scenario A — ownership transfer (own store: transfer/)", flush=True)
    initialize(runtime, "transfer")
    prerequisites(runtime, "transfer")
    payload, version, receipt = _propose(runtime, "transfer", "transfer-submit-once")
    assert receipt["decision"] == "accepted"
    operation_id = receipt["operation_id"]
    print("1. Agent proposes submission → intent prepared while agent owns the work", flush=True)
    send(runtime, "transfer", "transfer_owner",
         {"owner": "delegate", "reason": "handover"}, command_id="transfer-handover")
    invalidated = runtime.get_operation(operation_id)
    assert (invalidated["dispatch_state"], invalidated["reason"]) == (
        "cancelled", "OWNERSHIP_TRANSFERRED")
    print("2. transfer_owner agent → delegate → prepared intent invalidated "
          "(OWNERSHIP_TRANSFERRED)", flush=True)
    denied = send(runtime, "transfer", "propose_action", payload)
    assert denied["code"] == "AUTHORITY_DENIED"
    replay = runtime.command("agent", "transfer-submit-once", "transfer",
                             "propose_action", payload, version)
    assert replay["code"] == "AUTHORITY_DENIED"
    stored = runtime.get_command("agent", "transfer-submit-once")
    assert stored["decision"] == "accepted" and stored["operation_id"] == operation_id
    assert runtime.dispatch(operation_id, oa)["dispatch_state"] == "cancelled"
    assert oa.accepted_count() == 0
    print("3. Former owner re-proposes → AUTHORITY_DENIED; replays the accepted command → "
          "fresh AUTHORITY_DENIED, stored receipt untouched; dispatch stays cancelled "
          "(0 external calls)", flush=True)
    readmitted = _propose(runtime, "transfer", "delegate-resubmits", actor="delegate")[2]
    assert readmitted["decision"] == "accepted"
    assert readmitted["operation_id"] == operation_id
    print("4. New owner re-proposes → SAME operation id (business key stable) → "
          "intent readmitted", flush=True)
    assert runtime.dispatch(operation_id, oa)["status"] == "confirmed_succeeded"
    assert oa.accepted_count() == 1
    print("5. Dispatch → confirmed_succeeded; accepted applications in this store: 1\n", flush=True)
    return str(folder / "runtime.sqlite")


def _cancel_scenario(folder):
    runtime = Runtime(str(folder / "runtime.sqlite"), ExpensePolicy(), intervention_grants())
    oa = FakeOA(str(folder / "oa.sqlite"))
    print("Scenario B — cancellation with an uncertain external effect (own store: cancel/)",
          flush=True)
    initialize(runtime, "cancel")
    prerequisites(runtime, "cancel")
    receipt = _propose(runtime, "cancel", "cancel-submit-once")[2]
    assert receipt["decision"] == "accepted"
    operation_id = receipt["operation_id"]
    print("1. Agent proposes submission → intent prepared", flush=True)
    unknown = runtime.dispatch(operation_id, FakeOA(str(folder / "oa.sqlite"),
                                                    timeout_after_commit=True))
    assert unknown["status"] == "outcome_unknown"
    assert oa.accepted_count() == 1
    print("2. Dispatch → OA accepted, response lost after commit → outcome unknown "
          "(the effect exists)", flush=True)
    send(runtime, "cancel", "request_cancel", {"reason": "wrong invoice discovered"},
         command_id="cancel-1")
    blocked = send(runtime, "cancel", "finalize_cancel",
                   {"acknowledged_operations": []}, command_id="finalize-too-early")
    assert blocked["code"] == "OUTCOME_UNRESOLVED"
    print("3. request_cancel → intent stored; finalize now → OUTCOME_UNRESOLVED while "
          "the effect is unknown", flush=True)
    recovered = runtime.reconcile(operation_id, FakeOA(str(folder / "oa.sqlite")))
    assert recovered["status"] == "confirmed_succeeded"
    external_id = recovered["external_id"]
    assert oa.accepted_count() == 1 and len(recovered["attempts"]) == 1
    print("4. Reconcile the ORIGINAL business key → confirmed_succeeded, external id "
          "recovered, nothing resent", flush=True)
    mismatch = send(runtime, "cancel", "finalize_cancel",
                    {"acknowledged_operations": []}, command_id="finalize-empty")
    assert mismatch["code"] == "CANCEL_ACKNOWLEDGEMENT_MISMATCH"
    assert mismatch["blockers"] == [operation_id]
    closed = send(runtime, "cancel", "finalize_cancel",
                  {"acknowledged_operations": [operation_id]}, command_id="finalize-exact")
    assert closed["decision"] == "accepted"
    work = runtime.get_work("cancel")
    assert (work["status"], work["outcome"]) == ("closed", "cancelled")
    acknowledged = work["completion"]["acknowledged_operations"]
    assert acknowledged[0]["external_id"] == external_id
    assert oa.accepted_count() == 1
    print("5. finalize [] → CANCEL_ACKNOWLEDGEMENT_MISMATCH; exact acknowledgement [op] → "
          "CLOSED cancelled", flush=True)
    print("6. Acknowledgement records the effect (no reversal); accepted applications "
          "in this store: 1\n", flush=True)
    return str(folder / "runtime.sqlite")


def _migration_scenario(folder):
    runtime = registry_runtime(str(folder / "runtime.sqlite"))
    oa = FakeOA(str(folder / "oa.sqlite"))
    print("Scenario C — explicit policy migration demo-1 → demo-2 (own store: migrate/)",
          flush=True)
    initialize(runtime, "migrate", document(amount=80000))
    prerequisites(runtime, "migrate")  # Includes a demo-1-shaped approval {digest}.
    assert _requirement(runtime, "migrate", "E05")["applicability"] == "not_applicable"
    payload, _, receipt = _propose(runtime, "migrate", "migrate-submit-once")
    assert receipt["decision"] == "accepted"
    operation_id = receipt["operation_id"]
    print("1. Under-limit expense bound to demo-1 → E05 not applicable; a demo-1-shaped "
          "approval exists", flush=True)
    send(runtime, "migrate", "migrate_policy",
         {"policy_id": "expense-submit", "policy_version": "demo-2",
          "reason": "strengthen the approval rule"}, actor="root", command_id="migrate-1")
    work = runtime.get_work("migrate")
    assert work["contract"]["revision"] == 2
    assert (_requirement(runtime, "migrate", "E05")["applicability"],
            _requirement(runtime, "migrate", "E05")["fulfillment"]) == ("applicable", "pending")
    operation = runtime.get_operation(operation_id)
    assert (operation["dispatch_state"], operation["reason"]) == ("cancelled", "POLICY_MIGRATED")
    print("2. work.intervene admin migrates to demo-2 → revision 2; old approval INVALID; "
          "E05 applicable + pending; prepared intent invalidated (POLICY_MIGRATED)", flush=True)
    blocked = _propose(runtime, "migrate", "blocked-after-migration")[2]
    assert blocked["code"] == "REQUIREMENT_UNSATISFIED"
    stale = send(runtime, "migrate", "propose_action", payload)
    assert stale["code"] == "CONTRACT_REVISION_MISMATCH"
    print("3. Re-propose → REQUIREMENT_UNSATISFIED; stale contract revision → "
          "CONTRACT_REVISION_MISMATCH", flush=True)
    current = runtime.get_work("migrate")
    proof(runtime, "migrate", "approval", "finance",
          {"digest": current["document_digest"], "policy_version": "demo-2"})
    runtime.verify_pending("migrate")
    assert _requirement(runtime, "migrate", "E05")["fulfillment"] == "satisfied"
    readmitted = _propose(runtime, "migrate", "migrate-resubmit")[2]
    assert readmitted["decision"] == "accepted"
    assert readmitted["operation_id"] == operation_id
    operation = runtime.get_operation(operation_id)
    assert (operation["contract_revision"], operation["dispatch_state"]) == (2, "ready")
    print("4. Finance approves under demo-2 ({digest, policy_version}) → E05 satisfied → "
          "SAME operation readmitted", flush=True)
    bare = Runtime(str(folder / "runtime.sqlite"), ExpensePolicy(), intervention_grants())
    try:
        bare.get_work("migrate")
        raise AssertionError("reopening without the registry must fail closed")
    except CommandError as error:
        print("   (restart without the registry: %s)" % error, flush=True)
    restarted = registry_runtime(str(folder / "runtime.sqlite"))
    assert restarted.get_work("migrate")["contract"]["policy_version"] == "demo-2"
    print("5. Restart without the registry → fails closed; restart with the registry → "
          "pinned demo-2 usable", flush=True)
    assert restarted.dispatch(operation_id, FakeOA(str(folder / "oa.sqlite")))[
        "status"] == "confirmed_succeeded"
    assert oa.accepted_count() == 1
    print("6. Dispatch → confirmed_succeeded; accepted applications in this store: 1\n",
          flush=True)
    return str(folder / "runtime.sqlite")


def run_intervention_demo(directory=None):
    """Run the three intervention scenarios, each against its own fresh stores."""
    # Fresh directory per run; never removes existing user data.
    folder = Path(tempfile.mkdtemp(prefix="governed-intervention-", dir=directory))
    scenarios = (("transfer", _transfer_scenario), ("cancel", _cancel_scenario),
                 ("migrate", _migration_scenario))
    stores = [scenario(folder / name) for name, scenario in scenarios]
    print("3 scenarios; accepted applications: 3 (one per store); effects reversed: 0")
    print("\nInspect the durable history:")
    print(f'  python3 -m work_runtime inspect --db "{stores[0]}" --work transfer')
    print(f'  python3 -m work_runtime inspect --db "{stores[1]}" --work cancel')
    print(f'  python3 -m work_runtime inspect --db "{stores[2]}" --work migrate '
          f'--policy-versions demo-1,demo-2')
    return folder
