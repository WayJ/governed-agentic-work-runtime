"""A deterministic governed SOP publication harness: lint, approve, publish,
withdraw (S13).

Runs the frozen S12 publication core (``work_runtime/publication.py``) through
its public API on a real Runtime, SQLite store and artifact directory: a dirty
card is refused by lint, the packaged card publishes behind a signed
version-bound approval, the response is lost after the immutable commit and
recovered by reconciling the original key, a doctored same-version card
conflicts only after its own approval (D66), the loader fails closed, and an
approver-key rotation refuses the retired key without touching history. The
S13 chapter then withdraws the published version through the governed flow
(signed ``card_withdrawal``, W02/W03): the loader answers the distinct
withdrawn error, a re-publication of the withdrawn version is refused by the
governed proposal with zero store writes, and a retired-key withdrawal
envelope is refused without touching history. There is no un-withdrawal:
corrected content ships as a new version string.

No credentials, no network, no model session. The approver keys are ephemeral
in-memory random bytes for the run and are never printed, logged or persisted
— only key ids appear in the output. Trust is trusted-local configuration
(see docs/sop-authoring.md): the approver is a configured principal name with
a shared-key signature, not an authentication; rotation is a configuration
act with no persistent revocation memory; and published cards never execute
(D62).
"""

import copy
import hashlib
import json
import re
import secrets
import shutil
import sqlite3
import tempfile
import uuid
from pathlib import Path

from .adoption_demo import lint_result, packaged_card
from .authoring import sop_digest
from .ingress import (CODE_KEY_RETIRED, OPTIONAL_KEY_FIELD,
                      SignedEvidenceGateway, SourceKey, sign_evidence)
from .publication import (SopPublicationPolicy, SopPublicationStore,
                          SopWithdrawalStore, WITHDRAWAL_KEY_PREFIX,
                          WITHDRAWN_MESSAGE, WITHDRAWAL_DISCRIMINATOR,
                          load_published_card, publication_key,
                          withdrawal_key, withdrawal_record)
from .runtime import Runtime

DEMO_NOW = 2000000000  # Fixed clock keeps runs deterministic.
GRACE = 300  # == max_age, the documented minimum so envelopes land inside it
OLD_KEY_ID = "sop-owner-2026-08"
NEW_KEY_ID = "sop-owner-2026-10"
CARD_NAME = "publishing.json"
WORK_ID = "pub-1"
CONFLICT_WORK_ID = "pub-2"
WITHDRAWAL_WORK_ID = "wd-1"
REPUBLICATION_WORK_ID = "pub-3"
DOCTORED_GOAL = "content.published.doctored"
FINAL_LINE = ("1 published card version; withdrawal records: 1; committed "
              "artifacts: 2; doctored same-version conflicts: 1 (after its "
              "own approval); re-publication of the withdrawn version "
              "refused: 1 (zero store writes); loader fail-closed "
              "refusals: 3; retired-key refusals: 2 (zero writes); history "
              "rewritten: 0")
TABLES = ("works", "commands", "evidence", "operations", "events", "metadata")
_HASH_JSON = re.compile(r"[0-9a-f]{64}\.json")


def publication_grants():
    """Demo-local grants (design Q7), mirroring withdrawal_grants()."""
    return {"agent": {"work.manage", "sop.publish", "sop.withdraw"},
            "sop-owner": {"evidence.write"}}


def _key(key_id, **fields):
    """One ephemeral keyring entry; the secret never leaves this process."""
    return SourceKey(key_id, secrets.token_bytes(32), **fields)


def _committed_artifacts(directory):
    """Sorted hash-named committed artifact files under ``directory``."""
    return sorted(path for path in Path(directory).iterdir()
                  if _HASH_JSON.fullmatch(path.name))


def _artifact_file(directory, key):
    """The committed path a store key occupies (sha256 hex name, as always)."""
    return (Path(directory)
            / (hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json"))


def _table_counts(path):
    db = sqlite3.connect(str(path))
    try:
        return {table: db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                for table in TABLES}
    finally:
        db.close()


def _table_dump(path):
    """Ordered rowid dump of all six tables, for byte-identity proofs."""
    dump = {}
    db = sqlite3.connect(str(path))
    try:
        for table in TABLES:
            dump[table] = db.execute(
                "SELECT * FROM %s ORDER BY rowid" % table).fetchall()
    finally:
        db.close()
    return dump


def _evidence_bodies(path):
    db = sqlite3.connect(str(path))
    try:
        return [json.loads(row[0]) for row in
                db.execute("SELECT body FROM evidence ORDER BY rowid")]
    finally:
        db.close()


def _send(runtime, work_id, kind, payload=None, actor="agent", command_id=None):
    version = None if kind in ("create_work", "record_evidence") \
        else runtime.get_work(work_id)["state_version"]
    return runtime.command(actor, command_id or uuid.uuid4().hex, work_id, kind,
                           payload, version)


def _propose(runtime, work_id, capability="sop.publish", command_id=None):
    work = runtime.get_work(work_id)
    return _send(runtime, work_id, "propose_action", {
        "capability": capability, "document_digest": work["document_digest"],
        "contract_revision": work["contract"]["revision"],
        "plan_revision": work["plan_revision"]}, command_id=command_id)


class ResponseLossPublicationStore:
    """Composition wrapper: the real store commits, then the response is lost.

    The wrapper holds a real :class:`SopPublicationStore` and never stubs or
    edits it: ``execute`` delegates the durable commit and then raises
    ``TimeoutError`` exactly where an external service would lose its response
    AFTER the side effect. ``lookup`` delegates unchanged, so a restart
    reconciles the original key against the real committed artifact. The
    delegate's declared contract is surfaced so the Runtime's capability
    preflight still applies (composition, not a bypass).
    """

    def __init__(self, store):
        self._store = store
        self.contract = store.contract

    def execute(self, key, document, content_digest):
        self._store.execute(key, document, content_digest)
        raise TimeoutError("response lost after the publication commit")

    def lookup(self, key):
        return self._store.lookup(key)


def run_publication_demo(directory=None):
    """Run the publication scenario in its own fresh store; return the folder.

    Fresh directory per run; never removes existing user data. Every printed
    count is asserted inside this function against the real SQLite store and
    the artifact directory, never against the narration itself.
    """
    folder = Path(tempfile.mkdtemp(prefix="governed-publication-", dir=directory))
    run_dir = folder / "publication"
    store_dir = run_dir / "store"
    runtime_path = run_dir / "runtime.sqlite"
    clock = {"now": DEMO_NOW}

    def tick(now):
        clock["now"] = now
        return now

    card = packaged_card(CARD_NAME)
    policy = SopPublicationPolicy()
    grants = publication_grants()
    runtime = Runtime(str(runtime_path), policy, grants)
    old_key = _key(OLD_KEY_ID, current=True)
    new_key = _key(NEW_KEY_ID)
    print("Scenario — publish a lint-clean SOP rule card through the governed "
          "flow (own store: publication/)", flush=True)
    print("ephemeral in-memory approver keys %s (current) and %s; secrets are "
          "never printed, only key ids" % (OLD_KEY_ID, NEW_KEY_ID), flush=True)

    def message(command_id, event_id, work_id, data, key_id=OLD_KEY_ID,
                kind="card_approval"):
        return {"source": "sop-owner", "command_id": command_id,
                "work_id": work_id, "event_id": event_id,
                "kind": kind, "data": data,
                "issued_at": clock["now"], OPTIONAL_KEY_FIELD: key_id}

    gateway = SignedEvidenceGateway(runtime, {"sop-owner": [old_key, new_key]},
                                    clock=lambda: clock["now"])

    # Static prologue: lint is structural review only, never execution.
    dirty = copy.deepcopy(card)
    dirty["policy"]["goal"] = "  "
    dirty["rogue_field"] = 1
    invalid = lint_result(dirty)
    assert invalid["valid"] is False and invalid["diagnostics"]
    first = invalid["diagnostics"][0]
    print("Static SOP review (lint-sop; never executed by the Runtime):",
          flush=True)
    print("1. Dirty demo card -> %d diagnostics, first %s at %s (lint-sop exit "
          "1; work admission would refuse it bounded and unpersisted)"
          % (len(invalid["diagnostics"]), first["code"],
             first["path"] or "<root>"), flush=True)
    clean = lint_result(card)
    assert clean["valid"] is True and clean["digest"] == sop_digest(card)
    print("2. Packaged card %s lint-clean with pinned digest %s (lint-sop exit "
          "0) -> it becomes the work document (card = document)"
          % (CARD_NAME, clean["digest"]), flush=True)

    print("Live governed publication on the unchanged Runtime (family %s):"
          % policy.id, flush=True)
    _send(runtime, WORK_ID, "create_work", {"document": card},
          command_id="cmd-create-pub")
    _send(runtime, WORK_ID, "bind_contract",
          {"policy_id": policy.id, "policy_version": policy.version,
           "goal": policy.goal}, command_id="cmd-bind-pub")
    work = runtime.get_work(WORK_ID)
    assert work["document"] == card
    assert work["document_digest"] == sop_digest(card) == clean["digest"]
    print("3. Publication work created: document_digest == sop_digest == the "
          "pinned digest", flush=True)

    blocked = _propose(runtime, WORK_ID, command_id="cmd-propose-blocked")
    assert blocked["decision"] == "rejected"
    assert blocked["code"] == "REQUIREMENT_UNSATISFIED"
    assert any(blocker["id"].startswith("S02:") for blocker in blocked["blockers"])
    assert not store_dir.exists()
    print("4. Agent proposes publication -> BLOCKED %s (S02 approval pending)"
          % blocked["code"], flush=True)

    tampered = sign_evidence(old_key.secret, message(
        "cmd-approve-tampered", "evt-approve-tampered", WORK_ID,
        {"digest": sop_digest(card), "policy_version": card["policy"]["version"]}))
    tampered["data"]["digest"] = "0" * 64  # forged after signing
    intake_before = _table_counts(runtime_path)
    rejection = gateway.record(tampered)
    assert rejection == {"decision": "rejected",
                         "code": "EVIDENCE_AUTHENTICATION_FAILED"}
    assert _table_counts(runtime_path) == intake_before
    print("5. Tampered card_approval -> rejected %s before any intake write "
          "(six tables unchanged)" % rejection["code"], flush=True)

    valid = gateway.record(sign_evidence(old_key.secret, message(
        "cmd-approve-valid", "evt-approve-valid", WORK_ID,
        {"digest": runtime.get_work(WORK_ID)["document_digest"],
         "policy_version": card["policy"]["version"]})))
    assert valid["decision"] == "accepted"
    assert valid["evidence_status"] == "pending_verification"
    runtime.verify_pending(WORK_ID)
    intent = _propose(runtime, WORK_ID, command_id="publish-once")
    assert intent["decision"] == "accepted"
    assert (runtime.get_operation(intent["operation_id"])["business_key"]
            == publication_key(card))
    print("6. Valid signed {digest, policy_version} approval verified -> intent "
          "accepted; business key = the publication key", flush=True)

    unknown = runtime.dispatch(intent["operation_id"],
                               ResponseLossPublicationStore(
                                   SopPublicationStore(str(store_dir))))
    assert unknown["status"] == "outcome_unknown"
    artifacts = _committed_artifacts(store_dir)
    assert len(artifacts) == 1
    assert artifacts[0].name == hashlib.sha256(
        publication_key(card).encode("utf-8")).hexdigest() + ".json"
    assert json.loads(artifacts[0].read_text(encoding="utf-8"))["document"] == card
    print("7. Dispatch commits exactly ONE hash-named artifact; response lost "
          "AFTER the commit -> outcome_unknown", flush=True)

    restarted = Runtime(str(runtime_path), policy, grants)
    recovered = restarted.reconcile(intent["operation_id"],
                                    SopPublicationStore(str(store_dir)))
    assert recovered["status"] == "confirmed_succeeded"
    assert len(restarted.get_operation(intent["operation_id"])
               ["attempts"]) == 1
    print("8. Restart -> reconcile the ORIGINAL key -> confirmed_succeeded, one "
          "attempt, nothing resent", flush=True)

    accepted = [event for event in _evidence_bodies(runtime_path)
                if event["kind"] == "accepted"][0]
    assert "sop-store" not in grants  # no principal can sign as the store
    assert accepted["source"] == "sop-store"
    assert accepted["event_id"] == intent["operation_id"]
    assert accepted["status"] == "verified"
    print("9. Accepted proof runtime-written under the store source %s (absent "
          "from grants), event_id = the operation id" % accepted["source"],
          flush=True)

    completion = _send(restarted, WORK_ID, "request_completion",
                       command_id="cmd-complete-pub")
    assert completion["decision"] == "accepted"
    work = restarted.get_work(WORK_ID)
    assert (work["status"], work["outcome"]) == ("closed", "succeeded")
    winner_bytes = _committed_artifacts(store_dir)[0].read_bytes()
    print("10. Evidence-backed completion -> SUCCEEDED; committed file "
          "artifacts: 1", flush=True)

    doctored = copy.deepcopy(card)
    doctored["policy"]["goal"] = DOCTORED_GOAL
    assert publication_key(doctored) == publication_key(card)
    assert sop_digest(doctored) != sop_digest(card)
    _send(runtime, CONFLICT_WORK_ID, "create_work", {"document": doctored},
          command_id="cmd-create-pub2")
    _send(runtime, CONFLICT_WORK_ID, "bind_contract",
          {"policy_id": policy.id, "policy_version": policy.version,
           "goal": policy.goal}, command_id="cmd-bind-pub2")
    blocked_again = _propose(runtime, CONFLICT_WORK_ID,
                             command_id="cmd-propose-conflict-blocked")
    assert blocked_again["code"] == "REQUIREMENT_UNSATISFIED"  # D66 order
    print("11. Doctored same-version card enters as a NEW work -> BLOCKED %s "
          "first (D66 order: requirement blockers before the business key)"
          % blocked_again["code"], flush=True)
    conflict_approval = gateway.record(sign_evidence(old_key.secret, message(
        "cmd-approve-conflict", "evt-approve-conflict", CONFLICT_WORK_ID,
        {"digest": runtime.get_work(CONFLICT_WORK_ID)["document_digest"],
         "policy_version": doctored["policy"]["version"]})))
    assert conflict_approval["decision"] == "accepted"
    runtime.verify_pending(CONFLICT_WORK_ID)
    conflict = _propose(runtime, CONFLICT_WORK_ID,
                        command_id="cmd-propose-conflict")
    assert conflict["decision"] == "rejected"
    assert conflict["code"] == "OPERATION_CONTENT_CONFLICT"
    assert _committed_artifacts(store_dir)[0].read_bytes() == winner_bytes
    assert len(_committed_artifacts(store_dir)) == 1
    print("    ... then after its OWN verified approval -> persisted %s; the "
          "winner artifact bytes are unchanged (still exactly one .json)"
          % conflict["code"], flush=True)

    loaded = load_published_card(str(store_dir), card["policy"]["id"],
                                 card["policy"]["version"])
    assert loaded == card and sop_digest(loaded) == clean["digest"]
    absent_error = None
    try:
        load_published_card(str(store_dir), card["policy"]["id"],
                            "demo-1-absent")
    except ValueError as error:
        absent_error = str(error)
    assert absent_error is not None
    tampered_dir = run_dir / "store-tampered"
    shutil.copytree(store_dir, tampered_dir)  # the real store stays untouched
    tampered_file = _committed_artifacts(tampered_dir)[0]
    raw = json.loads(tampered_file.read_text(encoding="utf-8"))
    raw["document"]["policy"]["goal"] = "tampered.after.demo"
    tampered_file.write_text(json.dumps(raw), encoding="utf-8")
    tampered_error = None
    try:
        load_published_card(str(tampered_dir), card["policy"]["id"],
                            card["policy"]["version"])
    except ValueError as error:
        tampered_error = str(error)
    assert (tampered_error is not None
            and "no published card" not in tampered_error
            and tampered_error != absent_error)
    print("12. Loader fail-closed: the published card returns with its "
          "matching digest; absent version and a tampered file refuse with "
          "distinguishable bounded errors:", flush=True)
    print("absent version: %s" % absent_error, flush=True)
    print("tampered file: %s" % tampered_error, flush=True)

    before = _table_dump(runtime_path)
    before_bytes = _committed_artifacts(store_dir)[0].read_bytes()
    rotated = SignedEvidenceGateway(
        runtime,
        {"sop-owner": [SourceKey(OLD_KEY_ID, old_key.secret,
                                 not_after=DEMO_NOW + GRACE),
                       SourceKey(NEW_KEY_ID, new_key.secret, current=True)]},
        clock=lambda: clock["now"])
    tick(DEMO_NOW + GRACE + 1)
    retired = rotated.record(sign_evidence(old_key.secret, message(
        "cmd-approve-rotated-old", "evt-approve-rotated-old", WORK_ID,
        {"digest": sop_digest(card),
         "policy_version": card["policy"]["version"]})))
    assert retired == {"decision": "rejected", "code": CODE_KEY_RETIRED}
    assert _table_dump(runtime_path) == before
    assert _committed_artifacts(store_dir)[0].read_bytes() == before_bytes
    print("13. Approver key rotated (new key current, %s retained to T+%d): a "
          "fresh old-key envelope one second past grace -> rejected %s; six "
          "tables and the artifact bytes untouched (publication history is "
          "rotation-invariant)" % (OLD_KEY_ID, GRACE, CODE_KEY_RETIRED),
          flush=True)

    # S13 withdrawal chapter (D67-D79): end the CURRENT validity of the
    # published version through the governed flow — same family, second
    # capability — never touching a committed byte.
    print("Withdrawal chapter — end the current validity of the published "
          "version through the governed flow (same family, capability "
          "sop.withdraw, own work and second immutable record):", flush=True)
    request = {"discriminator": WITHDRAWAL_DISCRIMINATOR,
               "policy_id": card["policy"]["id"],
               "policy_version": card["policy"]["version"],
               "published_digest": clean["digest"]}
    assert withdrawal_record(str(store_dir), card["policy"]["id"],
                             card["policy"]["version"]) is None
    _send(runtime, WITHDRAWAL_WORK_ID, "create_work", {"document": request},
          command_id="cmd-create-wd1")
    _send(runtime, WITHDRAWAL_WORK_ID, "bind_contract",
          {"policy_id": policy.id, "policy_version": policy.version,
           "goal": policy.goal}, command_id="cmd-bind-wd1")
    withdrawal_blocked = _propose(runtime, WITHDRAWAL_WORK_ID,
                                  capability="sop.withdraw",
                                  command_id="cmd-propose-wd1-blocked")
    assert withdrawal_blocked["decision"] == "rejected"
    assert withdrawal_blocked["code"] == "REQUIREMENT_UNSATISFIED"
    assert any(blocker["id"].startswith("W02:")
               for blocker in withdrawal_blocked["blockers"])
    print("14. Withdrawal work created (closed request document naming the "
          "version and the published digest; withdrawal_record() reads None) "
          "-> proposes sop.withdraw -> BLOCKED %s (W02 approval pending; D66 "
          "order: requirement blockers before the business key)"
          % withdrawal_blocked["code"], flush=True)

    withdrawal_approval = rotated.record(sign_evidence(
        new_key.secret, message("cmd-approve-wd1", "evt-approve-wd1",
                                WITHDRAWAL_WORK_ID,
                                {"digest": clean["digest"],
                                 "policy_version": card["policy"]["version"]},
                                key_id=NEW_KEY_ID, kind="card_withdrawal")))
    assert withdrawal_approval["decision"] == "accepted"
    runtime.verify_pending(WITHDRAWAL_WORK_ID)
    withdrawal_intent = _propose(runtime, WITHDRAWAL_WORK_ID,
                                 capability="sop.withdraw",
                                 command_id="withdraw-once")
    assert withdrawal_intent["decision"] == "accepted"
    wkey = withdrawal_key(card["policy"]["id"], card["policy"]["version"])
    assert (runtime.get_operation(withdrawal_intent["operation_id"])
            ["business_key"] == wkey)
    print("15. Valid signed {digest, policy_version} card_withdrawal from the "
          "current (rotated) key verifies -> intent accepted; business key = "
          "the withdrawal key", flush=True)

    publication_file = _artifact_file(store_dir, publication_key(card))
    withdrawal_file = _artifact_file(store_dir, wkey)
    publication_bytes = publication_file.read_bytes()
    resolved_withdrawal = runtime.dispatch(
        withdrawal_intent["operation_id"], SopWithdrawalStore(str(store_dir)))
    assert resolved_withdrawal["status"] == "confirmed_succeeded"
    assert len(_committed_artifacts(store_dir)) == 2
    assert not [path for path in Path(store_dir).iterdir()
                if path.suffix == ".stage"]
    assert publication_file.read_bytes() == publication_bytes
    record_artifact = json.loads(withdrawal_file.read_text(encoding="utf-8"))
    assert record_artifact["document"] == request
    print("16. Dispatch through SopWithdrawalStore commits exactly ONE new "
          "hash-named artifact (the withdrawal record; census 2, zero .stage); "
          "the publication artifact bytes are unchanged", flush=True)
    withdrawal_accepted = [event for event in _evidence_bodies(runtime_path)
                           if event["kind"] == "accepted"
                           and event["event_id"]
                           == withdrawal_intent["operation_id"]][0]
    assert withdrawal_accepted["source"] == "sop-store"
    assert withdrawal_accepted["status"] == "verified"
    withdrawal_completion = _send(runtime, WITHDRAWAL_WORK_ID,
                                  "request_completion",
                                  command_id="cmd-complete-wd1")
    assert withdrawal_completion["decision"] == "accepted"
    withdrawn_work = runtime.get_work(WITHDRAWAL_WORK_ID)
    assert ((withdrawn_work["status"], withdrawn_work["outcome"])
            == ("closed", "succeeded"))
    print("    ... W03 satisfied by the store's own acceptance (accepted "
          "proof runtime-written under sop-store, event_id = the withdrawal "
          "operation id) -> completion SUCCEEDED", flush=True)

    withdrawn_error = None
    try:
        load_published_card(str(store_dir), card["policy"]["id"],
                            card["policy"]["version"])
    except ValueError as error:
        withdrawn_error = str(error)
    assert withdrawn_error == WITHDRAWN_MESSAGE
    assert withdrawn_error != absent_error
    assert "no published card" not in withdrawn_error
    print("17. Loader now fails closed on the WITHDRAWN error — a class of "
          "its own, distinct from absent and from corrupt:", flush=True)
    print("withdrawn version: %s" % withdrawn_error, flush=True)
    print("    no un-withdrawal exists: while the record stands this answer "
          "is permanent — corrected content ships as a NEW version string",
          flush=True)

    assert withdrawal_record(str(store_dir), card["policy"]["id"],
                             card["policy"]["version"]) == request
    print("18. withdrawal_record() audit read returns the exact closed record "
          "(who withdrew and when live in the governed ledger, not the store)",
          flush=True)

    _send(runtime, REPUBLICATION_WORK_ID, "create_work", {"document": card},
          command_id="cmd-create-pub3")
    _send(runtime, REPUBLICATION_WORK_ID, "bind_contract",
          {"policy_id": policy.id, "policy_version": policy.version,
           "goal": policy.goal}, command_id="cmd-bind-pub3")
    republish_blocked = _propose(runtime, REPUBLICATION_WORK_ID,
                                 command_id="cmd-propose-pub3-blocked")
    assert republish_blocked["code"] == "REQUIREMENT_UNSATISFIED"
    republish_approval = rotated.record(sign_evidence(
        new_key.secret, message("cmd-approve-pub3", "evt-approve-pub3",
                                REPUBLICATION_WORK_ID,
                                {"digest": clean["digest"],
                                 "policy_version": card["policy"]["version"]},
                                key_id=NEW_KEY_ID)))
    assert republish_approval["decision"] == "accepted"
    runtime.verify_pending(REPUBLICATION_WORK_ID)
    withdrawal_bytes = withdrawal_file.read_bytes()
    republish = _propose(runtime, REPUBLICATION_WORK_ID,
                         command_id="cmd-propose-pub3")
    assert republish["decision"] == "rejected"
    assert republish["code"] == "OPERATION_CONTENT_CONFLICT"
    assert len(_committed_artifacts(store_dir)) == 2
    assert publication_file.read_bytes() == publication_bytes
    assert withdrawal_file.read_bytes() == withdrawal_bytes
    print("19. Re-publishing the withdrawn version in the same database -> "
          "BLOCKED %s first, then persisted %s after its OWN approval — "
          "zero store writes (census and both artifacts unchanged; no "
          "un-withdrawal, correction means a new version string)"
          % (republish_blocked["code"], republish["code"]), flush=True)

    history_dump = _table_dump(runtime_path)
    publication_bytes_now = publication_file.read_bytes()
    withdrawal_bytes_now = withdrawal_file.read_bytes()
    retired_withdrawal = rotated.record(sign_evidence(
        old_key.secret, message("cmd-withdraw-rotated-old",
                                "evt-withdraw-rotated-old",
                                WITHDRAWAL_WORK_ID,
                                {"digest": clean["digest"],
                                 "policy_version": card["policy"]["version"]},
                                key_id=OLD_KEY_ID, kind="card_withdrawal")))
    assert retired_withdrawal == {"decision": "rejected",
                                  "code": CODE_KEY_RETIRED}
    assert _table_dump(runtime_path) == history_dump
    assert publication_file.read_bytes() == publication_bytes_now
    assert withdrawal_file.read_bytes() == withdrawal_bytes_now
    print("20. A retired approver key cannot sign a withdrawal: a fresh "
          "old-key card_withdrawal one second past grace -> rejected %s; six "
          "tables, the publication artifact and the withdrawal record all "
          "untouched (publication and withdrawal history are "
          "rotation-invariant)" % CODE_KEY_RETIRED, flush=True)

    # Closing census: every count re-read from the real SQLite store and the
    # artifact directory, never from the narration above.
    counts = _table_counts(runtime_path)
    assert (counts["works"] == 4 and counts["commands"] == 22
            and counts["evidence"] == 6 and counts["operations"] == 2)
    db = sqlite3.connect(str(runtime_path))
    try:
        refusal_codes = [json.loads(row[0]).get("code") for row in
                         db.execute("SELECT receipt FROM commands")]
    finally:
        db.close()
    assert refusal_codes.count("REQUIREMENT_UNSATISFIED") == 4
    assert refusal_codes.count("OPERATION_CONTENT_CONFLICT") == 2
    artifacts = _committed_artifacts(store_dir)
    parsed = [json.loads(path.read_text(encoding="utf-8"))
              for path in artifacts]
    assert len(artifacts) == 2
    assert sum(1 for a in parsed
               if a["key"].startswith("sop-pub:")) == 1
    assert sum(1 for a in parsed
               if a["key"].startswith(WITHDRAWAL_KEY_PREFIX)) == 1
    assert (withdrawn_error is not None and absent_error is not None
            and tampered_error is not None
            and len({withdrawn_error, absent_error, tampered_error}) == 3)
    print(FINAL_LINE)
    print("\nInspect the durable history and the real artifacts:")
    print('  python3 -m work_runtime inspect --db "%s" --work %s '
          '--policy sop-publish' % (runtime_path, WORK_ID))
    print('  python3 -m work_runtime inspect --db "%s" --work %s '
          '--policy sop-publish' % (runtime_path, WITHDRAWAL_WORK_ID))
    print('  committed artifact: "%s"' % publication_file)
    print('  withdrawal record: "%s"' % withdrawal_file)
    return folder
