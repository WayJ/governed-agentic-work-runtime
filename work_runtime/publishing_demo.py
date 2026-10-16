"""A deterministic publishing harness: signed evidence in, artifacts out.

Drives the same trusted-local command protocol as the expense demo, but the
reviewer/author evidence arrives through the HMAC-signed ingress gateway.
Work one keeps the succeeded-completion story (signed review gates, a
post-commit timeout recovered by lookup, evidence-backed completion). Since
S14 a second chapter appends on the same stores: a second document is
published, the work is cancelled inside the active window and its artifact
retracted through the linked ``content.unpublish`` compensation across a
real grants-carrying worker crash, closing with the exact two-id
acknowledgement. Retraction is bounded (active window, current owner), not
reversal: the original publication, receipt, accepted proof and history stay
recorded — appended, never deleted. It is an integration example of the
common command protocol, not a claim of integration with any model framework
or remote service: no credentials, no network. Signing keys are fresh random
bytes per run and are never printed or persisted.
"""

import json
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from .ingress import SignedEvidenceGateway, sign_evidence
from .publishing import FakePublisher, PublishingPolicy
from .runtime import Runtime

DEMO_NOW = 2000000000  # Fixed clock keeps runs deterministic.

FINAL_LINE = ("2 works; published artifacts: 2; retraction effects: 1; "
              "bounded in-window retraction, not reversal")

_PACKAGE_PARENT = str(Path(__file__).resolve().parent.parent)


def publishing_grants():
    """Demo grants: the owning agent holds the forward and, since S14 (D83),
    the paired compensating capability — trusted-local configuration, not
    authentication."""
    return {"agent": {"work.manage", "content.publish", "content.unpublish"},
            "reviewer": {"evidence.write"}, "author": {"evidence.write"}}


def article(article_id="ART-001", title="Release notes: governed publication",
            body="Version one of the announcement.", requires_review=True):
    return {"id": article_id, "title": title, "body": body,
            "requires_review": requires_review}


def _send(runtime, work_id, kind, payload=None, actor="agent", command_id=None):
    version = None if kind in ("create_work", "record_evidence") \
        else runtime.get_work(work_id)["state_version"]
    return runtime.command(actor, command_id or uuid.uuid4().hex, work_id, kind,
                           payload, version)


def _propose(runtime, work_id, command_id=None):
    work = runtime.get_work(work_id)
    return _send(runtime, work_id, "propose_action", {
        "capability": "content.publish", "document_digest": work["document_digest"],
        "contract_revision": work["contract"]["revision"],
        "plan_revision": work["plan_revision"]}, command_id=command_id)


def _retraction(runtime, work_id, target_id, command_id=None):
    """One linked compensation proposal: the exact five-key payload (S14)."""
    work = runtime.get_work(work_id)
    return _send(runtime, work_id, "propose_action", {
        "capability": "content.unpublish",
        "document_digest": work["document_digest"],
        "contract_revision": work["contract"]["revision"],
        "plan_revision": work["plan_revision"],
        "compensates": target_id}, command_id=command_id)


def crash_worker_script(runtime_path, publisher_path, operation_id):
    """Inline child source: a grants-carrying worker that dispatches the
    prepared retraction through the public API and dies (exit 73) right after
    the external commit.

    The shipped ``worker`` CLI cannot take this step: it hardwires the
    expense demo grants and the FakeOA adapter, so it can neither hold
    ``content.unpublish`` nor reach the publishing store. ``sys.path`` is
    seeded with this package's parent so the child imports the exact same
    package copy in a checkout and in an install."""
    return (
        "import os, sys\n"
        "sys.path.insert(0, {parent!r})\n"
        "from work_runtime.publishing import FakePublisher, PublishingPolicy\n"
        "from work_runtime.publishing_demo import publishing_grants\n"
        "from work_runtime.runtime import Runtime\n"
        "runtime = Runtime({runtime!r}, PublishingPolicy(), publishing_grants())\n"
        "runtime.dispatch({operation!r}, FakePublisher({publisher!r}),"
        " fault=lambda: os._exit(73))\n"
    ).format(parent=_PACKAGE_PARENT, runtime=str(runtime_path),
             operation=operation_id, publisher=str(publisher_path))


def run_crash_worker(runtime_path, publisher_path, operation_id):
    """Run the crash worker as a real child process; returns its exit status."""
    return subprocess.run([sys.executable, "-c",
                           crash_worker_script(runtime_path, publisher_path,
                                               operation_id)],
                          check=False)


def _evidence_rows(path):
    db = sqlite3.connect(path)
    try:
        return db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
    finally:
        db.close()


def _count(path, sql):
    db = sqlite3.connect(path)
    try:
        return db.execute(sql).fetchone()[0]
    finally:
        db.close()


def run_demo(directory=None):
    # Fresh directory per run; never removes existing user data.
    folder = Path(tempfile.mkdtemp(prefix="governed-publish-", dir=directory))
    runtime_path, publisher_path = folder / "runtime.sqlite", folder / "publisher.sqlite"
    policy = PublishingPolicy()
    work_id = "article-1"
    runtime = Runtime(str(runtime_path), policy, publishing_grants())
    reviewer_key, author_key = secrets.token_bytes(32), secrets.token_bytes(32)
    gateway = SignedEvidenceGateway(runtime, {"reviewer": reviewer_key,
                                              "author": author_key},
                                    clock=lambda: DEMO_NOW)

    def signed(source, secret, kind, digest_value, subject):
        return sign_evidence(secret, {
            "source": source, "command_id": uuid.uuid4().hex, "work_id": subject,
            "event_id": uuid.uuid4().hex, "kind": kind,
            "data": {"digest": digest_value}, "issued_at": DEMO_NOW})

    _send(runtime, work_id, "create_work", {"document": article()})
    _send(runtime, work_id, "bind_contract", {"policy_id": policy.id,
         "policy_version": policy.version, "goal": policy.goal})
    _send(runtime, work_id, "revise_plan", {
        "steps": ["draft", "review", "confirm", "publish"],
        "open_requirements": ["C02"], "replan_when": ["reviewer rejects"]})

    blocked = _propose(runtime, work_id)
    assert blocked["decision"] == "rejected"
    print("1. Agent proposes publication → BLOCKED by C02 (reviewer approval missing)",
          flush=True)

    tampered = signed("reviewer", reviewer_key, "approval",
                      runtime.get_work(work_id)["document_digest"], work_id)
    tampered["data"]["digest"] = "0" * 64
    intake_before = _evidence_rows(str(runtime_path))
    rejection = gateway.record(tampered)
    assert rejection == {"decision": "rejected", "code": "EVIDENCE_AUTHENTICATION_FAILED"}
    assert _evidence_rows(str(runtime_path)) == intake_before
    print("2. Tampered reviewer approval → rejected EVIDENCE_AUTHENTICATION_FAILED "
          "before any intake write", flush=True)

    current = runtime.get_work(work_id)["document_digest"]
    for source, secret, kind in (("reviewer", reviewer_key, "approval"),
                                 ("author", author_key, "confirmation")):
        receipt = gateway.record(signed(source, secret, kind, current, work_id))
        assert receipt["decision"] == "accepted"
        assert receipt["evidence_status"] == "pending_verification"
    assert any(r["fulfillment"] == "pending"
               for r in runtime.get_work(work_id)["requirements"])
    runtime.verify_pending(work_id)
    intent = _propose(runtime, work_id, command_id="publish-once")
    assert intent["decision"] == "accepted"
    print("3. Valid signed approval/confirmation stay candidates until verified "
          "→ intent accepted", flush=True)

    publisher = FakePublisher(str(publisher_path), timeout_after_commit=True)
    unknown = runtime.dispatch(intent["operation_id"], publisher)
    assert unknown["status"] == "outcome_unknown"
    assert publisher.published_count() == 1
    print("4. Publisher commits, response times out → outcome unknown, artifact exists",
          flush=True)

    restarted = Runtime(str(runtime_path), policy, publishing_grants())
    recovered = restarted.reconcile(intent["operation_id"],
                                    FakePublisher(str(publisher_path)))
    assert recovered["status"] == "confirmed_succeeded"
    assert len(restarted.get_operation(intent["operation_id"])["attempts"]) == 1
    print("5. Restart → query the same operation → receipt recovered, nothing resent",
          flush=True)

    completion = _send(restarted, work_id, "request_completion", command_id="complete")
    assert completion["decision"] == "accepted"
    assert publisher.published_count() == 1
    print("6. Evidence-backed completion → SUCCEEDED; published artifacts: 1")

    # Retraction chapter (S14 D90 structure (b)): appended on the same stores,
    # additive — the succeeded-completion story above stays verbatim.
    print("Retraction chapter — cancel the second work and retract its published "
          "artifact inside the active window (same stores, appended history)",
          flush=True)

    second_id = "article-2"
    second_doc = article(article_id="ART-002", title="Correction notice",
                         body="The announcement is withdrawn.")
    _send(runtime, second_id, "create_work", {"document": second_doc})
    _send(runtime, second_id, "bind_contract", {"policy_id": policy.id,
         "policy_version": policy.version, "goal": policy.goal})
    _send(runtime, second_id, "revise_plan", {
        "steps": ["draft", "review", "confirm", "publish"],
        "open_requirements": ["C02"], "replan_when": ["reviewer rejects"]})
    current = runtime.get_work(second_id)["document_digest"]
    for source, secret, kind in (("reviewer", reviewer_key, "approval"),
                                 ("author", author_key, "confirmation")):
        receipt = gateway.record(signed(source, secret, kind, current, second_id))
        assert receipt["decision"] == "accepted"
    runtime.verify_pending(second_id)
    second = _propose(runtime, second_id, command_id="publish-second")
    assert second["decision"] == "accepted"
    publish_id = second["operation_id"]
    publisher = FakePublisher(str(publisher_path))
    confirmed = runtime.dispatch(publish_id, publisher)
    assert confirmed["status"] == "confirmed_succeeded"
    assert confirmed["external_id"].startswith("PUB-")
    assert publisher.published_count() == 2
    print("7. A second document enters as its own work through the same signed "
          f"gateway → published and confirmed ({confirmed['external_id']}); "
          "published artifacts: 2", flush=True)

    cancel = _send(runtime, second_id, "request_cancel",
                   {"reason": "the announcement must come down"})
    assert cancel["decision"] == "accepted"
    print("8. The owner requests cancellation — the active window opens; the "
          "confirmed publication is untouched by the request alone", flush=True)

    proposal = _retraction(runtime, second_id, publish_id,
                           command_id="unpublish-once")
    assert proposal["decision"] == "accepted"
    retraction_id = proposal["operation_id"]
    retraction_op = runtime.get_operation(retraction_id)
    assert retraction_op["compensates"] == {
        "operation_id": publish_id, "external_id": confirmed["external_id"],
        "capability": "content.publish"}
    print("9. Owner proposes the linked retraction (five-key payload, "
          f"compensates={publish_id}) → prepared with the immutable original "
          "snapshot {operation_id, external_id, capability} and its own stable "
          "business key — separate from the forward key", flush=True)

    child = run_crash_worker(runtime_path, publisher_path, retraction_id)
    assert child.returncode == 73, child.returncode
    assert _count(str(publisher_path), "SELECT COUNT(*) FROM retractions") == 1
    assert runtime.get_operation(retraction_id)["status"] == "dispatched"
    print("10. A grants-carrying worker subprocess dispatches the retraction → "
          "the external retraction commits (RTR-…) → the worker dies before "
          f"recording the outcome (exit code {child.returncode}). The shipped "
          "worker CLI cannot take this step: it hardwires the expense demo "
          "grants and the OA adapter", flush=True)

    restarted = Runtime(str(runtime_path), policy, publishing_grants())
    recovered = restarted.recover(FakePublisher(str(publisher_path)))
    assert len(recovered) == 1
    retraction_op = restarted.get_operation(retraction_id)
    assert retraction_op["status"] == "confirmed_succeeded"
    assert len(retraction_op["attempts"]) == 1
    assert retraction_op["external_id"].startswith("RTR-")
    assert retraction_op["adapter_result"]["original_external_id"] \
        == confirmed["external_id"]
    print("11. Restart → recover() reconciles the original business key → "
          "confirmed_succeeded in exactly one attempt (nothing resent); the "
          "retraction appends a withdrawn proof at the publisher source while "
          "the original publication, receipt and accepted proof stay intact",
          flush=True)

    ack = sorted([publish_id, retraction_id])
    closure = _send(restarted, second_id, "finalize_cancel",
                   {"acknowledged_operations": ack},
                   command_id="finalize-retraction")
    assert closure["decision"] == "accepted"
    second_work = restarted.get_work(second_id)
    assert (second_work["status"], second_work["outcome"]) == ("closed", "cancelled")
    completion = second_work["completion"]
    externals = {entry["operation_id"]: entry["external_id"]
                 for entry in completion["acknowledged_operations"]}
    assert set(externals) == set(ack)
    assert externals[publish_id].startswith("PUB-")
    assert externals[retraction_id].startswith("RTR-")
    disposition = next(entry for entry in completion["operation_dispositions"]
                       if entry["operation_id"] == retraction_id)
    assert disposition["compensates"] == retraction_op["compensates"]
    assert disposition["adapter_result"] == retraction_op["adapter_result"]
    print("12. Finalize with the exact two-id ack (publication + retraction) → "
          "closed/cancelled; the compensation disposition carries compensates "
          "+ the stored adapter result", flush=True)

    # Closing truth read from the stores directly, never parsed from stdout.
    assert _count(str(publisher_path), "SELECT COUNT(*) FROM publications") == 2
    assert _count(str(publisher_path), "SELECT COUNT(*) FROM retractions") == 1
    db = sqlite3.connect(str(runtime_path))
    try:
        proof_row = db.execute(
            "SELECT body FROM evidence WHERE source='publisher' AND event_id=?",
            (retraction_id,)).fetchone()
    finally:
        db.close()
    proof = json.loads(proof_row[0])
    assert (proof["kind"], proof["status"]) == ("withdrawn", "verified")
    assert proof["data"] == {"digest": retraction_op["document_digest"],
                             "external_id": retraction_op["external_id"],
                             "original_external_id": confirmed["external_id"]}
    print(FINAL_LINE, flush=True)
    print("\nInspect the durable history:")
    print(f'  python3 -m work_runtime inspect --db "{runtime_path}" --work {work_id} '
          f'--policy content-publish')
    print(f'  python3 -m work_runtime inspect --db "{runtime_path}" --work {second_id} '
          f'--policy content-publish')
    return folder
