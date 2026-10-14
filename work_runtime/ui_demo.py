"""A five-work sample store for the local operations GUI, seeded through
real commands.

Every state in the seeded store was reached by the real Runtime and the real
persistent FakeOA — no direct SQL writes, no fabricated fields. The external
store keeps its committed effects: an uncertain work retains its accepted
application, and a cancelled work acknowledges the confirmed effect instead
of reversing it.
"""

import sys
import tempfile
from pathlib import Path

from .adapters import FakeOA
from .demo import action, document, initialize, prerequisites, proof, send
from .intervention_demo import intervention_grants
from .policy import ExpensePolicy
from .runtime import Runtime

# A fixed epoch deadline keeps the seeded wait durable for any viewer clock.
DEMO_WAIT_DEADLINE = 2000000000


class UnavailableLookup:
    """Composition wrapper whose authoritative lookup reports no result.

    ``lookup`` always returns ``None`` so ``Runtime.reconcile`` escalates to
    ``NO_AUTHORITATIVE_RESULT``/needs_attention. The wrapped adapter keeps
    every committed effect; this wrapper only models an authority that cannot
    answer, it never edits the adapter or its store.
    """

    def __init__(self, adapter):
        self._adapter = adapter

    def lookup(self, key):
        return None


def _requirement(work, rule):
    return next(r for r in work["requirements"] if r["rule_id"] == rule)


def _propose(runtime, work_id, command_id, actor="agent"):
    return send(runtime, work_id, "propose_action", {
        "capability": "expense.submit",
        "document_digest": runtime.get_work(work_id)["document_digest"],
        "contract_revision": runtime.get_work(work_id)["contract"]["revision"],
        "plan_revision": runtime.get_work(work_id)["plan_revision"]},
        actor=actor, command_id=command_id)


def _seed_wait(runtime):
    """wait-1: durable wait with the approval still pending verification."""
    initialize(runtime, "wait-1",
               document(document_id="EXP-UI-001", invoice_id="INV-UI-001"))
    prerequisites(runtime, "wait-1", approval=False)
    rejected = action(runtime, "wait-1", command_id="wait-1-propose")
    assert rejected["decision"] == "rejected"
    assert rejected["code"] == "REQUIREMENT_UNSATISFIED"
    e05 = _requirement(runtime.get_work("wait-1"), "E05")
    send(runtime, "wait-1", "register_wait",
         {"requirement_id": e05["id"], "deadline": DEMO_WAIT_DEADLINE,
          "owner": "finance"}, command_id="wait-1-wait")
    # Finance has submitted the approval, but nobody verified it yet: the
    # evidence stays pending_verification and the work keeps waiting.
    proof(runtime, "wait-1", "approval", "finance")
    work = runtime.get_work("wait-1")
    assert work["status"] == "waiting" and work["waits"][0]["status"] == "waiting"
    print("wait-1: waiting on E05 approval; approval evidence pending "
          "verification; earlier proposal persisted as a rejected decision",
          flush=True)


def _seed_uncertain(runtime, oa_path):
    """uncertain-1: committed external effect, no authoritative result."""
    initialize(runtime, "uncertain-1",
               document(document_id="EXP-UI-002", invoice_id="INV-UI-002"))
    prerequisites(runtime, "uncertain-1")
    operation_id = action(runtime, "uncertain-1",
                          command_id="uncertain-1-propose")["operation_id"]
    unknown = runtime.dispatch(
        operation_id, FakeOA(oa_path, timeout_after_commit=True))
    assert unknown["status"] == "outcome_unknown"
    # A post-commit timeout alone leaves the work active, not needs_attention.
    assert runtime.get_work("uncertain-1")["status"] == "active"
    escalated = runtime.reconcile(operation_id, UnavailableLookup(FakeOA(oa_path)))
    assert escalated["reason"] == "NO_AUTHORITATIVE_RESULT"
    assert runtime.get_work("uncertain-1")["status"] == "needs_attention"
    print("uncertain-1: OA accepted, response lost, lookup unavailable → "
          "needs_attention with the effect retained in the external store",
          flush=True)


def _seed_transfer(runtime, oa):
    """transfer-1: ownership handed to a delegate, same operation readmitted."""
    initialize(runtime, "transfer-1",
               document(document_id="EXP-UI-003", invoice_id="INV-UI-003"))
    prerequisites(runtime, "transfer-1")
    operation_id = action(runtime, "transfer-1",
                          command_id="transfer-1-propose")["operation_id"]
    send(runtime, "transfer-1", "transfer_owner",
         {"owner": "delegate", "reason": "handover to the delegate"},
         command_id="transfer-1-handover")
    invalidated = runtime.get_operation(operation_id)
    assert (invalidated["dispatch_state"], invalidated["reason"]) == (
        "cancelled", "OWNERSHIP_TRANSFERRED")
    readmitted = _propose(runtime, "transfer-1", "transfer-1-readmit", actor="delegate")
    assert readmitted["operation_id"] == operation_id
    assert runtime.dispatch(operation_id, oa)["status"] == "confirmed_succeeded"
    work = runtime.get_work("transfer-1")
    assert (work["owner"], work["status"]) == ("delegate", "active")
    print("transfer-1: owner agent → delegate; prepared intent invalidated then "
          "readmitted; submission confirmed", flush=True)


def _seed_succeed(runtime, oa):
    """succeed-1: evidence-backed completion."""
    initialize(runtime, "succeed-1",
               document(document_id="EXP-UI-004", invoice_id="INV-UI-004"))
    prerequisites(runtime, "succeed-1")
    operation_id = action(runtime, "succeed-1",
                          command_id="succeed-1-propose")["operation_id"]
    assert runtime.dispatch(operation_id, oa)["status"] == "confirmed_succeeded"
    final = send(runtime, "succeed-1", "request_completion",
                 command_id="succeed-1-complete")
    assert final["decision"] == "accepted"
    work = runtime.get_work("succeed-1")
    assert (work["status"], work["outcome"]) == ("closed", "succeeded")
    print("succeed-1: OA accepted and evidence-backed completion → closed "
          "succeeded", flush=True)


def _seed_cancel(runtime, oa, oa_path):
    """cancel-1: cancellation acknowledging the exact confirmed effect."""
    initialize(runtime, "cancel-1",
               document(document_id="EXP-UI-005", invoice_id="INV-UI-005"))
    prerequisites(runtime, "cancel-1")
    operation_id = action(runtime, "cancel-1",
                          command_id="cancel-1-propose")["operation_id"]
    unknown = runtime.dispatch(
        operation_id, FakeOA(oa_path, timeout_after_commit=True))
    assert unknown["status"] == "outcome_unknown"
    send(runtime, "cancel-1", "request_cancel",
         {"reason": "wrong invoice discovered"}, command_id="cancel-1-request")
    recovered = runtime.reconcile(operation_id, FakeOA(oa_path))
    assert recovered["status"] == "confirmed_succeeded"
    closed = send(runtime, "cancel-1", "finalize_cancel",
                  {"acknowledged_operations": [operation_id]},
                  command_id="cancel-1-finalize")
    assert closed["decision"] == "accepted"
    work = runtime.get_work("cancel-1")
    acknowledged = work["completion"]["acknowledged_operations"]
    assert (work["status"], work["outcome"]) == ("closed", "cancelled")
    assert acknowledged[0]["external_id"] == recovered["external_id"]
    print("cancel-1: uncertain submission reconciled to a confirmed effect; "
          "cancellation acknowledges the exact effect (no reversal)", flush=True)


def seed_ui_demo(directory=None):
    """Seed one fresh five-work expense-family store; return the DB path.

    Runs real Runtime commands and the real FakeOA only. A fresh folder is
    created per call; existing user data is never touched or deleted.
    """
    folder = Path(tempfile.mkdtemp(prefix="governed-ui-", dir=directory))
    runtime_path, oa_path = folder / "runtime.sqlite", folder / "oa.sqlite"
    runtime = Runtime(str(runtime_path), ExpensePolicy(), intervention_grants())
    oa = FakeOA(str(oa_path))
    print("Seeding a five-work sample store (real commands, no fabricated state):",
          flush=True)
    _seed_wait(runtime)
    _seed_uncertain(runtime, str(oa_path))
    _seed_transfer(runtime, oa)
    _seed_succeed(runtime, oa)
    _seed_cancel(runtime, oa, str(oa_path))
    assert oa.accepted_count() == 4
    print("5 works seeded; accepted applications in the external store: 4; "
          "effects reversed: 0", flush=True)
    print(f'seeded store: "{runtime_path}"', flush=True)
    print("Inspect the durable history:", flush=True)
    print(f'  python3 -m work_runtime inspect --db "{runtime_path}" --work wait-1',
          flush=True)
    return str(runtime_path)


def _startup_fail(message):
    """Report one bounded startup problem and exit 2 (house convention)."""
    print("work-runtime ui: " + message, file=sys.stderr, flush=True)
    raise SystemExit(2)


def _valid_port(port):
    return isinstance(port, int) and 0 <= port <= 65535


def serve_ui(db_path, port=0, server_factory=None):
    """Serve the read-only GUI on loopback until interrupted.

    The read-only backend is imported lazily so installs without it keep
    every prior CLI command working; startup failures exit 2 with a bounded
    message, the actual URL is printed (flushed) before serving starts, and
    an interrupt shuts the server down cleanly. ``server_factory`` overrides
    the backend lookup for lifecycle tests only.
    """
    if not _valid_port(port):
        _startup_fail("port must be an integer between 0 and 65535")
    if not Path(db_path).is_file():
        _startup_fail("database not found: %s" % db_path)
    try:
        if server_factory is not None:
            httpd = server_factory(db_path, port)
        else:
            from .ui_server import make_ui_server
            httpd = make_ui_server(db_path, port)
    except ImportError:
        _startup_fail("UI backend (work_runtime.ui_server) is not available "
                      "in this install")
    except Exception as error:
        _startup_fail("cannot start UI: %s" % error)
    print("http://127.0.0.1:%d/" % httpd.server_address[1], flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def run_ui_demo(directory=None, port=0, server_factory=None):
    """Seed a fresh sample store, then serve the read-only GUI over it."""
    if not _valid_port(port):
        _startup_fail("port must be an integer between 0 and 65535")
    db_path = seed_ui_demo(directory)
    serve_ui(db_path, port, server_factory=server_factory)
