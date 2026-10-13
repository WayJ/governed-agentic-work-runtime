"""A deterministic publishing harness: signed evidence in, one artifact out.

Drives the same trusted-local command protocol as the expense demo, but the
reviewer/author evidence arrives through the HMAC-signed ingress gateway.
It is an integration example of the common command protocol, not a claim of
integration with any model framework or remote service: no credentials, no
network. Signing keys are fresh random bytes per run and are never printed
or persisted.
"""

import secrets
import sqlite3
import tempfile
import uuid
from pathlib import Path

from .ingress import SignedEvidenceGateway, sign_evidence
from .publishing import FakePublisher, PublishingPolicy
from .runtime import Runtime

DEMO_NOW = 2000000000  # Fixed clock keeps runs deterministic.


def publishing_grants():
    return {"agent": {"work.manage", "content.publish"},
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


def _evidence_rows(path):
    db = sqlite3.connect(path)
    try:
        return db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
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

    def signed(source, secret, kind, digest_value):
        return sign_evidence(secret, {
            "source": source, "command_id": uuid.uuid4().hex, "work_id": work_id,
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
                      runtime.get_work(work_id)["document_digest"])
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
        receipt = gateway.record(signed(source, secret, kind, current))
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
    print("\nInspect the durable history:")
    print(f'  python3 -m work_runtime inspect --db "{runtime_path}" --work {work_id} '
          f'--policy content-publish')
    return folder
