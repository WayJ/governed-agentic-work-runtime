"""A deterministic compensation harness: withdraw an accepted expense, keep history.

Runs the real Runtime and the persistent FakeOA — no credentials, no network,
no model session. Each scenario owns a separate fresh set of databases, so
every printed effect count is checkable against its own external store.
Compensation here is bounded (S10): an expense-family withdrawal executed
only inside the active cancellation window, linked to the immutable original
snapshot under its own stable business key. It is not a general reversal
guarantee: the forward acceptance, its receipts, invoices and proof stay
recorded (history is appended, never deleted), a refused withdrawal is an
explicit stored refusal — never a reversal and never an unknown — and an
unresolved compensation blocks closure rather than being abandoned. The
principals are trusted local grants, not authenticated identities.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from .adapters import FakeOA
from .demo import action, demo_grants, initialize, prerequisites, send
from .inspection import ReadOnlyInspector
from .policy import ExpensePolicy
from .runtime import Runtime

FINAL_LINE = ("2 scenarios; retained forward effects: 2 accepted applications; "
              "withdrawal effects: 1; refused withdrawals: 1; refusal is not reversal")

_PACKAGE_PARENT = str(Path(__file__).resolve().parent.parent)


def compensation_grants():
    """Demo grants plus the compensating capability for the owner and the
    cancellation administrator; the shipped demo grants stay untouched."""
    grants = demo_grants()
    grants["agent"] = set(grants["agent"]) | {"expense.withdraw"}
    grants["admin"] = {"work.intervene"}
    return grants


def crash_worker_script(runtime_path, oa_path, operation_id):
    """Inline child source: a scoped grants-carrying worker that dispatches the
    prepared withdrawal through the public API and dies (exit 73) right after
    the external commit.

    The shipped ``worker`` CLI cannot perform this step: it hardwires the demo
    grants, which hold no ``expense.withdraw``, so such a dispatch holds
    AUTHORITY_DENIED with zero attempts and zero effects (pinned in the demo
    tests). ``sys.path`` is seeded with this package's parent so the child
    imports the exact same package copy in a checkout and in an install."""
    return (
        "import os, sys\n"
        "sys.path.insert(0, {parent!r})\n"
        "from work_runtime.adapters import FakeOA\n"
        "from work_runtime.compensation_demo import compensation_grants\n"
        "from work_runtime.policy import ExpensePolicy\n"
        "from work_runtime.runtime import Runtime\n"
        "runtime = Runtime({runtime!r}, ExpensePolicy(), compensation_grants())\n"
        "runtime.dispatch({operation!r}, FakeOA({oa!r}),"
        " fault=lambda: os._exit(73))\n"
    ).format(parent=_PACKAGE_PARENT, runtime=str(runtime_path),
             operation=operation_id, oa=str(oa_path))


def run_crash_worker(runtime_path, oa_path, operation_id):
    """Run the crash worker as a real child process; returns its exit status."""
    return subprocess.run([sys.executable, "-c",
                           crash_worker_script(runtime_path, oa_path, operation_id)],
                          check=False)


def withdrawal(runtime, work_id, target_id, command_id):
    """One linked compensation proposal: the exact five-key payload (S10 D43)."""
    work = runtime.get_work(work_id)
    return send(runtime, work_id, "propose_action", {
        "capability": "expense.withdraw",
        "document_digest": work["document_digest"],
        "contract_revision": work["contract"]["revision"],
        "plan_revision": work["plan_revision"],
        "compensates": target_id}, command_id=command_id)


def _crash_scenario(folder):
    runtime_path, oa_path = folder / "runtime.sqlite", folder / "oa.sqlite"
    runtime = Runtime(str(runtime_path), ExpensePolicy(), compensation_grants())
    oa = FakeOA(str(oa_path))
    print("Scenario A — accepted expense withdrawn inside the cancellation "
          "window, across a real worker crash (own store: crash/)", flush=True)
    initialize(runtime, "expense")
    prerequisites(runtime, "expense")
    forward = action(runtime, work_id="expense", command_id="submit-once")
    assert forward["decision"] == "accepted"
    forward_id = forward["operation_id"]
    confirmed = runtime.dispatch(forward_id, oa)
    assert confirmed["status"] == "confirmed_succeeded"
    external = confirmed["external_id"]
    assert oa.accepted_count() == 1
    print("1. Verified invoices, duplicate clear, requester confirmation and "
          f"finance approval → submission → OA accepts ({external}) → "
          "confirmed_succeeded; E08 satisfied by the accepted proof", flush=True)
    cancel = send(runtime, "expense", "request_cancel",
                  {"reason": "duplicate invoice found in the batch"}, actor="admin")
    assert cancel["decision"] == "accepted"
    print("2. Admin (work.intervene) requests cancellation — the window opens; "
          "nothing is reversed by that request alone", flush=True)
    proposal = withdrawal(runtime, "expense", forward_id, command_id="withdraw-once")
    assert proposal["decision"] == "accepted"
    withdrawal_id = proposal["operation_id"]
    withdrawal_op = runtime.get_operation(withdrawal_id)
    assert withdrawal_op["compensates"] == {"operation_id": forward_id,
                                            "external_id": external,
                                            "capability": "expense.submit"}
    print("3. Owner proposes the linked withdrawal (five-key payload, "
          f"compensates={forward_id}) → prepared with the immutable original "
          "snapshot {operation_id, external_id, capability} and its own stable "
          "business key — separate from the forward key", flush=True)
    child = run_crash_worker(runtime_path, oa_path, withdrawal_id)
    assert child.returncode == 73, child.returncode
    assert oa.withdrawn_count() == 1
    assert runtime.get_operation(withdrawal_id)["status"] == "dispatched"
    print("4. A grants-carrying worker subprocess dispatches the withdrawal → "
          "the external withdrawal commits (WD-…) → the worker dies before "
          f"recording the outcome (exit code {child.returncode}). The shipped "
          "worker CLI cannot take this step: its demo grants hold no "
          "expense.withdraw, so it would hold the dispatch AUTHORITY_DENIED "
          "with zero attempts and zero effects", flush=True)
    restarted = Runtime(str(runtime_path), ExpensePolicy(), compensation_grants())
    restarted.recover(oa)
    withdrawal_op = restarted.get_operation(withdrawal_id)
    assert withdrawal_op["status"] == "confirmed_succeeded"
    assert len(withdrawal_op["attempts"]) == 1
    assert withdrawal_op["attempts"][0]["status"] == "confirmed_succeeded"
    assert withdrawal_op["external_id"].startswith("WD-")
    assert withdrawal_op["adapter_result"]["original_external_id"] == external
    assert oa.lookup(withdrawal_op["business_key"]) == withdrawal_op["adapter_result"]
    assert (oa.accepted_count(), oa.withdrawn_count()) == (1, 1)
    print("5. Restart → recover() reconciles the original business key → "
          "confirmed_succeeded in exactly one attempt (nothing resent)", flush=True)
    inspector = ReadOnlyInspector(str(runtime_path))
    detail = inspector.work_detail("expense")
    kinds = [(entry["kind"], entry["status"]) for entry in detail["evidence"]
             if entry["source"] == "oa"]
    assert ("accepted", "verified") in kinds and ("withdrawn", "verified") in kinds
    e08 = next(r for r in detail["work"]["requirements"] if r["rule_id"] == "E08")
    assert e08["fulfillment"] == "satisfied"
    print("6. Store truth, read back read-only: the forward accepted proof is "
          "still verified and still satisfies E08; the withdrawal appended a "
          "distinct withdrawn-kind proof and its own receipt — accepted "
          "applications 1, withdrawal effects 1; history appended, never "
          "deleted", flush=True)
    ack = sorted([forward_id, withdrawal_id])
    closure = send(restarted, "expense", "finalize_cancel",
                   {"acknowledged_operations": ack}, actor="admin")
    assert closure["decision"] == "accepted"
    work = restarted.get_work("expense")
    assert (work["status"], work["outcome"]) == ("closed", "cancelled")
    completion = work["completion"]
    assert sorted(entry["operation_id"]
                  for entry in completion["acknowledged_operations"]) == ack
    disposition = next(entry for entry in completion["operation_dispositions"]
                       if entry["operation_id"] == withdrawal_id)
    assert disposition["compensates"] == withdrawal_op["compensates"]
    assert disposition["adapter_result"] == withdrawal_op["adapter_result"]
    print("7. Admin finalizes with the exact two-id ack (original + succeeded "
          "withdrawal) → closed/cancelled; the closure disposition carries "
          "compensates + the stored adapter result", flush=True)
    print("   accepted applications: 1; withdrawal effects: 1 (asserted against "
          "this scenario's own SQLite stores)\n", flush=True)
    return str(runtime_path)


def _refusal_scenario(folder):
    runtime_path, oa_path = folder / "runtime.sqlite", folder / "oa.sqlite"
    absent_path = folder / "absent.sqlite"
    runtime = Runtime(str(runtime_path), ExpensePolicy(), compensation_grants())
    oa = FakeOA(str(oa_path))
    print("Scenario B — withdrawal pointed at an external store that never saw "
          "the original: authoritative refusal, not reversal (own store: "
          "refusal/)", flush=True)
    initialize(runtime, "expense")
    prerequisites(runtime, "expense")
    forward = action(runtime, work_id="expense", command_id="submit-once")
    assert forward["decision"] == "accepted"
    forward_id = forward["operation_id"]
    confirmed = runtime.dispatch(forward_id, oa)
    assert confirmed["status"] == "confirmed_succeeded"
    external = confirmed["external_id"]
    print(f"1. Fresh expense accepted and confirmed in its own external store "
          f"({external})", flush=True)
    cancel = send(runtime, "expense", "request_cancel",
                  {"reason": "requester withdraws the request"}, actor="admin")
    assert cancel["decision"] == "accepted"
    proposal = withdrawal(runtime, "expense", forward_id, command_id="withdraw-once")
    assert proposal["decision"] == "accepted"
    withdrawal_id = proposal["operation_id"]
    print("2. Cancellation requested → linked withdrawal prepared with the same "
          "immutable snapshot shape and its own stable key", flush=True)
    refused = runtime.dispatch(withdrawal_id, FakeOA(str(absent_path)))
    assert refused["status"] == "confirmed_failed"
    assert refused["adapter_result"]["reason"] == "ORIGINAL_ABSENT"
    assert refused["adapter_result"]["original_external_id"] == external
    assert (oa.accepted_count(), oa.withdrawn_count()) == (1, 0)
    print("3. Dispatch is caller-trusted: pointing the withdrawal at a second "
          "external store (absent.sqlite) that holds no forward receipt for "
          "the original yields an authoritative stored rejection "
          "ORIGINAL_ABSENT — a queryable receipt with zero withdrawal "
          "effects, a bounded refusal that is neither an unknown nor a "
          "fabricated withdrawal", flush=True)
    closure = send(runtime, "expense", "finalize_cancel",
                   {"acknowledged_operations": [forward_id]}, actor="admin")
    assert closure["decision"] == "accepted"
    work = runtime.get_work("expense")
    assert (work["status"], work["outcome"]) == ("closed", "cancelled")
    completion = work["completion"]
    assert [entry["operation_id"]
            for entry in completion["acknowledged_operations"]] == [forward_id]
    disposition = next(entry for entry in completion["operation_dispositions"]
                       if entry["operation_id"] == withdrawal_id)
    assert disposition["status"] == "confirmed_failed"
    assert disposition["adapter_result"]["reason"] == "ORIGINAL_ABSENT"
    print("4. The failure is explicit: the runtime records confirmed_failed "
          "with the refusal reason stored in adapter_result, and finalize "
          "acknowledges ONLY the retained forward effect (ack = exactly one "
          "id); the closure disposition keeps the refusal — refusal is not "
          "reversal, the original effect remains", flush=True)
    print("   accepted applications: 1; withdrawal effects: 0; refused "
          "receipts: 1\n", flush=True)
    return str(runtime_path)


def run_compensation_demo(directory=None):
    """Run the two compensation scenarios, each against its own fresh stores."""
    # Fresh directory per run; never removes existing user data.
    folder = Path(tempfile.mkdtemp(prefix="governed-compensation-", dir=directory))
    scenarios = (("crash", _crash_scenario), ("refusal", _refusal_scenario))
    stores = [scenario(folder / name) for name, scenario in scenarios]
    print(FINAL_LINE)
    print("\nInspect the durable history:")
    print(f'  python3 -m work_runtime inspect --db "{stores[0]}" --work expense')
    print(f'  python3 -m work_runtime inspect --db "{stores[1]}" --work expense')
    return folder
