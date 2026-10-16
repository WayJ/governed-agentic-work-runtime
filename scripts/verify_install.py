#!/usr/bin/env python3
"""Verify the package installs into a fresh venv and runs outside this checkout.

Standard library only, Python >= 3.9. Stages, all of which must pass:

1. Create a brand-new virtual environment in a temporary directory (never
   reuses an existing environment or an already-installed package).
2. `pip install <repository>` — a real (non-editable) install. Any pip
   failure fails this script with the full pip output. Note: pip's isolated
   build downloads the build backend (setuptools) declared in pyproject.toml,
   so this stage needs index access; offline runs fail here by design.
3. Assert `work_runtime` now imports from inside that venv, with the working
   directory outside the repository and PYTHONPATH stripped, so the checkout
   cannot silently satisfy the import.
4. Assert no third-party runtime dependency was installed.
5. Run `python -m work_runtime demo` outside the checkout and assert both the
   printed result and — independently of the printed text — that the demo's
   fake OA database contains exactly one accepted application.
6. Run `python -m work_runtime publish-demo` outside the checkout and assert
   both the printed result and — independently of the printed text — that the
   demo's publisher database contains exactly one publication.
7. Run `python -m work_runtime intervention-demo` outside the checkout, assert
   the printed result, require exactly three printed scenario databases, and
   count each scenario's fake OA database independently: exactly one accepted
   application per store. Also run the installed `inspect --policy-versions
   demo-1,demo-2` against the migrated store and assert it reads the demo-2 pin.
8. Run the `work-runtime demo` console entry point outside the checkout and
   assert the same printed result.
9. Run the `work-runtime intervention-demo` console entry point outside the
   checkout and assert the same printed result and the same independent
   per-store counts as stage 7.
10. Assert the packaged SOP example cards ship inside the (non-editable)
    install — `importlib.resources.files("work_runtime")` resolves inside the
    venv and both data/sop cards are present — and the installed `lint-sop`
    on an extracted copy of publishing.json exits 0 with the pinned digest.
11. Run `python -m work_runtime adoption-demo` outside the checkout and verify
    it INDEPENDENTLY of the printed text: enumerate the printed artifact
    directory (exactly one hash-named committed .json, zero .stage leftovers),
    parse the artifact with the standard library only (exact keys, version 1,
    key equal to the operation's business key, recomputed document digest,
    accepted FILE- receipt), read the runtime database directly (work
    article-1 closed/succeeded, operation confirmed_succeeded), and re-run the
    demo's printed inspect command verbatim.
12. Run the `work-runtime adoption-demo` console entry point outside the
    checkout and apply the same independent enumeration/parse checks.
13. Run `python -m work_runtime revocation-demo` outside the checkout and
    verify it INDEPENDENTLY of the printed text: parse each of the three
    scenario stores (hold, uncertain, publish) directly — revoked/verified
    evidence statuses, preserved source-event fingerprints (recomputed with
    the standard library), the readmitted operation's business key
    (recomputed from the policy family, document id and revision/digest),
    closed-work completion still citing the revoked acceptance, and each
    external store holding exactly one accepted effect.
14. Run the `work-runtime revocation-demo` console entry point outside the
    checkout and apply the same independent store proof.
15. Run `python -m work_runtime compensation-demo` outside the checkout and
    verify it INDEPENDENTLY of the printed text: parse both scenario stores
    (crash, refusal) directly with locally recomputed business keys
    (forward key vs the S10 compensation key digest([family, capability,
    original id])), the immutable original snapshot, the stored
    adapter_result bound to the original, tagged receipts with the
    recomputed link digest, exactly one withdrawal row per original,
    unchanged invoices, accepted/withdrawn counts, the withdrawn-kind proof
    (never a forward accepted proof) and the retained E08 truth, the exact
    two-id closure ack with the compensation disposition, and for the
    refusal scenario the authoritative ORIGINAL_ABSENT rejection with a
    single-id ack and zero effects; also re-run the demo's printed inspect
    command verbatim against the installed entry point.
16. Run the `work-runtime compensation-demo` console entry point outside the
    checkout and apply the same independent store proof.
17. Assert the packaged GUI web assets ship inside the (non-editable)
    install — `work_runtime/web/{index.html,app.js,app.css}` resolve inside
    the venv — so the read-only viewer is never served from this checkout.
18. Installed UI (module AND console): when the read-only backend
    (`work_runtime.ui_server`) is present in the install, start `ui-demo` as
    a real subprocess outside the checkout, read the printed URL, fetch
    HTML/JS/CSS/summary/works/work/events over real HTTP (five seeded works),
    hash every runtime table before/after the HTTP reads (read-only
    equality), then interrupt the process (SIGINT) and require a clean exit;
    also run the `ui --db` console command once on the seeded store through
    URL + summary + clean interrupt. When the backend is not assembled in
    this build the stage prints an explicit SKIPPED line and the final
    summary discloses the skip — it never reports UI coverage it did not
    actually run.
19. Run `python -m work_runtime rotation-demo` outside the checkout and
    verify it INDEPENDENTLY of the printed text: read the runtime store
    directly — the six-table history digest recomputed locally and matched
    against the printed digest, exactly two verified approval-evidence rows
    with recomputed fingerprints and document digest, exactly one command row
    per rotation command id with the original cached receipt still
    pending_verification while its evidence row is verified, zero operations —
    and re-run the demo's printed inspect command verbatim.
20. Run the `work-runtime rotation-demo` console entry point outside the
    checkout and apply the same independent store proof.
21. Run `python -m work_runtime publication-demo` outside the checkout and
    verify it INDEPENDENTLY of the printed text: parse the committed
    artifact and the runtime store directly — exactly one hash-named
    artifact with the recomputed bare-card digest, digest-based publication
    key and accepted FILE- receipt; the closed/succeeded work with its
    one-attempt confirmed operation; the runtime-written sop-store accepted
    proof (event_id = operation id); the doctored-card conflict receipt
    (OPERATION_CONTENT_CONFLICT) and both blocked proposals; the printed
    absent-vs-tampered loader lines distinguishable — and re-run the demo's
    printed `inspect --policy sop-publish` command verbatim.
22. Run the `work-runtime publication-demo` console entry point outside the
    checkout and apply the same independent store proof.

Usage: python3 scripts/verify_install.py [--python INTERP] [--repo PATH] [--keep]
"""

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_FINAL_LINE = "external applications created: 1"
PUBLISH_FINAL_LINE = "published artifacts: 1"
INTERVENTION_FINAL_LINE = "accepted applications: 3 (one per store)"
ADOPTION_FINAL_LINE = "committed file artifacts: 1"
REVOCATION_FINAL_LINE = ("retained external effects: 2 accepted applications, "
                         "1 published artifact; effects reversed: 0")
REVOCATION_SCENARIOS = ("hold", "uncertain", "publish")
COMPENSATION_FINAL_LINE = ("2 scenarios; retained forward effects: 2 accepted "
                           "applications; withdrawal effects: 1; refused "
                           "withdrawals: 1; refusal is not reversal")
COMPENSATION_SCENARIOS = ("crash", "refusal")
ROTATION_FINAL_LINE = ("1 scenario; dual-key accepts: 2; retired refusals: 1 (zero "
                       "writes); cached receipts verbatim: 2; new commands: 1; "
                       "history rewritten: 0")
ROTATION_BEFORE_DIGEST = re.compile(r"six-table digest before rotation: ([0-9a-f]{16})")
ROTATION_FINAL_DIGEST = re.compile(r"six-table digest after all steps: ([0-9a-f]{16})")
ROTATION_TABLES = ("works", "commands", "evidence", "operations", "events", "metadata")
ROTATION_COMMAND_IDS = ("cmd-rotation-k1", "cmd-rotation-k2", "cmd-rotation-resend")
ROTATION_EVENT_IDS = ("evt-rotation-1", "evt-rotation-2")
PUBLICATION_FINAL_LINE = ("1 published card version; withdrawal records: 1; "
                          "committed artifacts: 2; doctored same-version "
                          "conflicts: 1 (after its own approval); "
                          "re-publication of the withdrawn version refused: "
                          "1 (zero store writes); loader fail-closed "
                          "refusals: 3; retired-key refusals: 2 (zero "
                          "writes); history rewritten: 0")
PUBLICATION_ABSENT_LINE = re.compile(r"^absent version: (.+)$", re.MULTILINE)
PUBLICATION_TAMPERED_LINE = re.compile(r"^tampered file: (.+)$", re.MULTILINE)
PUBLICATION_WITHDRAWN_LINE = re.compile(r"^withdrawn version: (.+)$",
                                        re.MULTILINE)
WITHDRAWAL_RECORD_LINE = re.compile(r'withdrawal record: "([^"]+)"')
PUBLICATION_RUN_COMMANDS = (
    "cmd-create-pub", "cmd-bind-pub", "cmd-propose-blocked", "publish-once",
    "cmd-complete-pub", "cmd-create-pub2", "cmd-bind-pub2",
    "cmd-propose-conflict-blocked", "cmd-propose-conflict",
    "cmd-create-wd1", "cmd-bind-wd1", "cmd-propose-wd1-blocked",
    "withdraw-once", "cmd-complete-wd1", "cmd-create-pub3", "cmd-bind-pub3",
    "cmd-propose-pub3-blocked", "cmd-propose-pub3",
)
PUBLICATION_GATEWAY_COMMANDS = ("cmd-approve-valid", "cmd-approve-conflict",
                                "cmd-approve-wd1", "cmd-approve-pub3")
PUBLICATION_BLOCKED_COMMANDS = ("cmd-propose-blocked",
                                "cmd-propose-conflict-blocked",
                                "cmd-propose-wd1-blocked",
                                "cmd-propose-pub3-blocked")
UI_WORK_IDS = {"wait-1", "uncertain-1", "transfer-1", "succeed-1", "cancel-1"}
PINNED_PUBLISHING_DIGEST = ("56c85d32da9a9eee6330326e2d14ce0661dbc26d"
                            "782b13d0259c3f149e6be000")
INSPECT_DB = re.compile(r'--db "([^"]+)"')
INSPECT_COMMAND = re.compile(r'^  (python3 -m work_runtime inspect .+)$', re.MULTILINE)
COMMITTED_ARTIFACT = re.compile(r'committed artifact: "([^"]+)"')
HASH_NAMED = re.compile(r"^[0-9a-f]{64}\.json$")
# pkg-resources appears as a virtual entry on some Debian-derived pips.
ALLOWED_PACKAGES = {"pip", "setuptools", "wheel", "pkg-resources", "governed-work-runtime"}


def clean_env():
    """Child environment that cannot accidentally import from this checkout."""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return env


def run(command, cwd, show=False):
    """Run a command; on failure print everything and abort the script."""
    env = clean_env()
    words = [str(part) for part in command]
    result = subprocess.run(words, cwd=str(cwd), capture_output=True, text=True, env=env)
    if result.returncode != 0:
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit("FAILED (exit %d): %s" % (result.returncode, " ".join(words)))
    if show:
        sys.stdout.write(result.stdout)
    return result


def count_accepted(oa_db):
    """Count accepted applications directly in the demo's fake OA database."""
    db = sqlite3.connect(str(oa_db))
    try:
        rows = [json.loads(row[0]) for row in db.execute("SELECT result FROM receipts")]
    finally:
        db.close()
    return sum(1 for row in rows if row.get("status") == "accepted")


def count_publications(publisher_db):
    """Count published artifacts directly in the demo's publisher database."""
    db = sqlite3.connect(str(publisher_db))
    try:
        return db.execute("SELECT COUNT(*) FROM publications").fetchone()[0]
    finally:
        db.close()


def require(condition, message):
    if not condition:
        raise SystemExit("FAILED: " + message)


def require_intervention_store_counts(stdout, source):
    """Give a module or console intervention-demo run independent store proof.

    Extracts the printed scenario databases and requires exactly three
    distinct stores named transfer, cancel, migrate in that order, then
    counts each store's receipts directly: exactly one accepted application
    per store. Returns the resolved store paths.
    """
    stores = INSPECT_DB.findall(stdout)
    require(len(stores) == 3,
            "%s printed %d inspect databases (expected exactly 3: "
            "transfer, cancel, migrate)" % (source, len(stores)))
    require(len(set(stores)) == 3,
            "%s printed duplicate store paths: %s" % (source, stores))
    names = [Path(store).parent.name for store in stores]
    require(names == ["transfer", "cancel", "migrate"],
            "%s printed scenario directories %s (expected transfer, cancel, "
            "migrate in order)" % (source, names))
    for store in stores:
        oa_db = Path(store).parent / "oa.sqlite"
        require(oa_db.exists(),
                "%s store %s has no external database at %s" % (source, store, oa_db))
        accepted = count_accepted(oa_db)
        require(accepted == 1,
                "%s store %s holds %d accepted applications (expected exactly 1)"
                % (source, store, accepted))
    return stores


def canonical_json(value):
    """Canonical JSON with the same parameters the runtime uses.

    Implemented locally on purpose: this script never imports the product
    package for its proofs.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def parse_committed_artifact(path, source):
    """Parse and validate one committed FilePublisher artifact, stdlib only."""
    artifact = json.loads(Path(path).read_text(encoding="utf-8"))
    require(isinstance(artifact, dict) and set(artifact) == {
        "artifact_version", "key", "content_digest", "document", "receipt"},
        "%s artifact %s does not have the exact expected keys" % (source, path))
    require(type(artifact["artifact_version"]) is int
            and artifact["artifact_version"] == 1,
            "%s artifact_version is %r (expected integer 1)"
            % (source, artifact["artifact_version"]))
    require(isinstance(artifact["key"], str) and artifact["key"],
            "%s artifact key is not a nonempty string" % source)
    document = artifact["document"]
    require(isinstance(document, dict),
            "%s artifact document is not an object" % source)
    recomputed = hashlib.sha256(
        canonical_json(document).encode("utf-8")).hexdigest()
    require(artifact["content_digest"] == recomputed,
            "%s artifact content digest does not match its document" % source)
    receipt = artifact["receipt"]
    require(isinstance(receipt, dict)
            and set(receipt) == {"status", "external_id", "digest"},
            "%s artifact receipt does not have the exact expected keys" % source)
    require(receipt["status"] == "accepted",
            "%s artifact receipt status is %r" % (source, receipt["status"]))
    require(isinstance(receipt["external_id"], str)
            and receipt["external_id"].startswith("FILE-"),
            "%s artifact receipt external_id is %r (expected FILE-...)"
            % (source, receipt.get("external_id")))
    require(receipt["digest"] == artifact["content_digest"],
            "%s artifact receipt digest does not match the content digest" % source)
    return artifact


def require_adoption_proof(stdout, source):
    """Independent module/console adoption-demo proof, never stdout-only.

    Enumerates the printed artifact directory (exactly one hash-named
    committed .json, zero .stage leftovers), validates the artifact with the
    standard library only, reads the runtime database directly (work
    article-1 closed/succeeded, one confirmed_succeeded operation whose
    business key equals the artifact key), and re-runs the printed inspect
    command verbatim against the installed entry point. Returns
    (artifact_path, runtime_db_path).
    """
    require(ADOPTION_FINAL_LINE in stdout,
            "%s output lacks %r" % (source, ADOPTION_FINAL_LINE))
    artifact_match = COMMITTED_ARTIFACT.search(stdout)
    require(artifact_match is not None,
            "%s printed no committed artifact path" % source)
    artifact_path = Path(artifact_match.group(1))
    require(artifact_path.exists(),
            "%s printed artifact %s does not exist" % (source, artifact_path))
    directory = artifact_path.parent
    hash_named = sorted(path for path in directory.iterdir()
                        if HASH_NAMED.match(path.name))
    require(len(hash_named) == 1,
            "%s directory %s holds %d hash-named artifacts (expected exactly 1)"
            % (source, directory, len(hash_named)))
    require(hash_named[0] == artifact_path,
            "%s printed artifact %s is not the committed file %s"
            % (source, artifact_path, hash_named[0]))
    leftovers = [path for path in directory.iterdir() if path.suffix == ".stage"]
    require(not leftovers,
            "%s left staging files: %s" % (source, leftovers))
    artifact = parse_committed_artifact(artifact_path, source)

    db_match = INSPECT_DB.search(stdout)
    require(db_match is not None, "%s printed no inspect --db path" % source)
    runtime_db = Path(db_match.group(1))
    require(runtime_db.exists(),
            "%s runtime database %s does not exist" % (source, runtime_db))
    db = sqlite3.connect(str(runtime_db))
    try:
        works = {row[0]: json.loads(row[1])
                 for row in db.execute("SELECT id, state FROM works")}
        operations = [json.loads(row[0])
                      for row in db.execute("SELECT body FROM operations")]
    finally:
        db.close()
    require(set(works) == {"article-1"},
            "%s works are %s (expected exactly article-1)" % (source, sorted(works)))
    work = works["article-1"]
    require((work["status"], work["outcome"]) == ("closed", "succeeded"),
            "%s work article-1 is %s/%s (expected closed/succeeded)"
            % (source, work["status"], work["outcome"]))
    require(len(operations) == 1,
            "%s hold %d operations (expected exactly 1)" % (source, len(operations)))
    operation = operations[0]
    require(operation["status"] == "confirmed_succeeded",
            "%s operation is %s (expected confirmed_succeeded)"
            % (source, operation["status"]))
    require(artifact["key"] == operation["business_key"],
            "%s artifact key does not equal the operation business key" % source)
    require(artifact["document"] == work["document"],
            "%s artifact document differs from the work's document" % source)
    return artifact_path, runtime_db


def local_digest(value):
    """SHA-256 over canonical JSON, same parameters as the runtime's digest.

    Implemented locally on purpose: this script never imports the product
    package for its proofs.
    """
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def db_rows(path, sql, args=(), source="store"):
    db = sqlite3.connect(str(path))
    try:
        return db.execute(sql, args).fetchall()
    finally:
        db.close()


def require_work_state(runtime_db, work_id, source):
    rows = db_rows(runtime_db, "SELECT state FROM works WHERE id=?", (work_id,), source)
    require(len(rows) == 1,
            "%s store %s holds %d rows for work %s (expected exactly 1)"
            % (source, runtime_db, len(rows), work_id))
    return json.loads(rows[0][0])


def require_operation(runtime_db, source, label, external_prefix):
    """Exactly one confirmed operation with a stable business key; returns it."""
    rows = db_rows(runtime_db, "SELECT body FROM operations", source=source)
    require(len(rows) == 1,
            "%s store %s holds %d operations (expected exactly 1: %s)"
            % (source, runtime_db, len(rows), label))
    operation = json.loads(rows[0][0])
    require(operation["status"] == "confirmed_succeeded"
            and operation["dispatch_state"] == "finished",
            "%s %s operation is %s/%s (expected confirmed_succeeded/finished)"
            % (source, label, operation.get("status"), operation.get("dispatch_state")))
    require(len(operation.get("attempts", [])) == 1
            and str(operation.get("external_id", "")).startswith(external_prefix),
            "%s %s operation does not hold exactly one attempt with a retained "
            "%s external id" % (source, label, external_prefix))
    return operation


def require_source_event_proof(runtime_db, work_id, source_row, event_id,
                               expected_status, source):
    """One record_evidence row: exact status and preserved source-event
    fingerprint recomputed locally from (work id, event payload)."""
    rows = db_rows(runtime_db,
                   "SELECT body,fingerprint FROM evidence WHERE source=? AND event_id=?",
                   (source_row, event_id), source)
    require(len(rows) == 1,
            "%s store %s holds %d rows for %s/%s (expected exactly 1)"
            % (source, runtime_db, len(rows), source_row, event_id))
    body = json.loads(rows[0][0])
    require(body["status"] == expected_status,
            "%s evidence %s/%s status is %r (expected %r)"
            % (source, source_row, event_id, body["status"], expected_status))
    require(rows[0][1] == local_digest(
        [work_id, {"event_id": event_id, "kind": body["kind"], "data": body["data"]}]),
        "%s evidence %s/%s fingerprint does not match its preserved source event"
        % (source, source_row, event_id))
    return body


def require_accepted_proof(runtime_db, accepted_source, operation_id, source):
    """One runtime-written acceptance row, revoked, its fingerprint still the
    digest of the original (verified) acceptance — only the status changed."""
    rows = db_rows(runtime_db,
                   "SELECT body,fingerprint FROM evidence WHERE source=? AND event_id=?",
                   (accepted_source, operation_id), source)
    require(len(rows) == 1,
            "%s store holds %d acceptance rows for %s/%s (expected exactly 1)"
            % (source, len(rows), accepted_source, operation_id))
    body = json.loads(rows[0][0])
    require(body["status"] == "revoked" and body["kind"] == "accepted",
            "%s acceptance %s/%s is %s/%s (expected revoked/accepted)"
            % (source, accepted_source, operation_id, body["status"], body["kind"]))
    require(rows[0][1] == local_digest(dict(body, status="verified")),
            "%s acceptance %s/%s fingerprint is not the preserved original "
            "acceptance digest" % (source, accepted_source, operation_id))
    return body


def require_revoked_event_sources(runtime_db, expected_sources, source):
    rows = db_rows(runtime_db,
                   "SELECT body FROM events WHERE type='EvidenceRevoked' ORDER BY seq",
                   source=source)
    sources = [json.loads(row[0])["source"] for row in rows]
    require(sources == list(expected_sources),
            "%s store %s EvidenceRevoked sources are %s (expected %s)"
            % (source, runtime_db, sources, list(expected_sources)))
    return [json.loads(row[0]) for row in rows]


def require_revocation_hold(store, source):
    runtime_db = Path(store)
    oa_db = runtime_db.parent / "oa.sqlite"
    require(oa_db.exists(),
            "%s hold store has no external database at %s" % (source, oa_db))
    state = require_work_state(runtime_db, "hold", source)
    require_source_event_proof(runtime_db, "hold", "finance", "evt-hold-approval",
                               "revoked", source)
    require_source_event_proof(runtime_db, "hold", "finance", "evt-hold-approval-2",
                               "verified", source)
    operation = require_operation(runtime_db, source, "hold", "OA-")
    require(operation["business_key"] == local_digest(
        ["expense-submit", "expense.submit",
         state["document"]["id"], state["document_revision"]]),
        "%s hold operation business key does not equal the recomputed expense "
        "operation key" % source)
    require_revoked_event_sources(runtime_db, ("finance",), source)
    require(db_rows(oa_db, "SELECT COUNT(*) FROM receipts")[0][0] == 1,
            "%s hold external store holds %d receipts (expected exactly 1: zero "
            "calls while held, one final acceptance)"
            % (source, db_rows(oa_db, "SELECT COUNT(*) FROM receipts")[0][0]))
    require(count_accepted(oa_db) == 1,
            "%s hold external store does not hold exactly 1 accepted application"
            % source)


def require_revocation_uncertain(store, source):
    runtime_db = Path(store)
    oa_db = runtime_db.parent / "oa.sqlite"
    require(oa_db.exists(),
            "%s uncertain store has no external database at %s" % (source, oa_db))
    state = require_work_state(runtime_db, "uncertain", source)
    require_source_event_proof(runtime_db, "uncertain", "finance",
                               "evt-uncertain-approval", "revoked", source)
    operation = require_operation(runtime_db, source, "uncertain", "OA-")
    require_accepted_proof(runtime_db, "oa", operation["id"], source)
    fulfillment = {r["id"]: r["fulfillment"] for r in state["requirements"]}
    require(fulfillment.get("E05:EXP-001") == "pending"
            and fulfillment.get("E08:EXP-001") == "pending",
            "%s uncertain requirements are %r (expected E05 and E08 pending)"
            % (source, fulfillment))
    require_revoked_event_sources(runtime_db, ("oa", "finance"), source)
    require(db_rows(oa_db, "SELECT COUNT(*) FROM receipts")[0][0] == 1,
            "%s uncertain external store does not hold exactly 1 receipt "
            "(the uncertain effect must be retained exactly once, never resent)"
            % source)
    require(count_accepted(oa_db) == 1,
            "%s uncertain external store does not hold exactly 1 accepted "
            "application" % source)


def require_revocation_publish(store, source):
    runtime_db = Path(store)
    publisher_db = runtime_db.parent / "publisher.sqlite"
    require(publisher_db.exists(),
            "%s publish store has no external database at %s" % (source, publisher_db))
    state = require_work_state(runtime_db, "publish", source)
    require((state["status"], state["outcome"]) == ("closed", "succeeded"),
            "%s publish work is %s/%s (expected closed/succeeded)"
            % (source, state.get("status"), state.get("outcome")))
    require_source_event_proof(runtime_db, "publish", "reviewer", "evt-pub-approval",
                               "revoked", source)
    require_source_event_proof(runtime_db, "publish", "reviewer", "evt-pub-approval-2",
                               "verified", source)
    operation = require_operation(runtime_db, source, "publish", "PUB-")
    require(operation["business_key"] == local_digest(
        ["content-publish", "content.publish",
         state["document"]["id"], state["document_digest"]]),
        "%s publish operation business key does not equal the recomputed "
        "publishing operation key" % source)
    accepted = require_accepted_proof(runtime_db, "publisher", operation["id"], source)
    require(accepted["id"] in state["completion"]["evidence"],
            "%s publish completion no longer cites the (now revoked) acceptance "
            "— the historical closure snapshot must stay byte-identical" % source)
    fulfillment = {r["id"]: r["fulfillment"] for r in state["requirements"]}
    require(fulfillment.get("C04:ART-001") == "pending",
            "%s publish C04 fulfillment is %r (expected pending after the "
            "closed-work correction)"
            % (source, fulfillment.get("C04:ART-001")))
    events = require_revoked_event_sources(runtime_db, ("reviewer", "publisher"), source)
    require(events[1]["work_was_closed"] and events[1]["completion_cites_evidence"],
            "%s closed-correction event flags are not work_was_closed/"
            "completion_cites_evidence" % source)
    require(count_publications(publisher_db) == 1,
            "%s publish external store does not hold exactly 1 publication"
            % source)


def require_revocation_proof(stdout, source):
    """Independent module/console revocation-demo proof, never stdout-only.

    Requires the demo's exact final line and exactly three distinct printed
    scenario stores (hold, uncertain, publish in order), then verifies each
    store directly: evidence statuses, preserved fingerprints, the stable
    business key of the single readmitted operation, closed-work correction
    facts and one retained external effect per store. Returns the store paths.
    """
    require(REVOCATION_FINAL_LINE in stdout,
            "%s output lacks %r" % (source, REVOCATION_FINAL_LINE))
    stores = INSPECT_DB.findall(stdout)
    require(len(stores) == 3,
            "%s printed %d inspect databases (expected exactly 3: hold, "
            "uncertain, publish)" % (source, len(stores)))
    require(len(set(stores)) == 3,
            "%s printed duplicate store paths: %s" % (source, stores))
    names = [Path(store).parent.name for store in stores]
    require(names == list(REVOCATION_SCENARIOS),
            "%s printed scenario directories %s (expected hold, uncertain, "
            "publish in order)" % (source, names))
    require_revocation_hold(stores[0], source)
    require_revocation_uncertain(stores[1], source)
    require_revocation_publish(stores[2], source)
    return stores


def require_compensation_operations(runtime_db, source):
    """(work state, forward, withdrawal) with locally recomputed business keys.

    The forward key is the pre-S10 expense key; the withdrawal key is the S10
    compensation key digest([policy family, capability, original operation id])
    — structurally distinct from every forward key and stable across re-admission.
    """
    state = require_work_state(runtime_db, "expense", source)
    require((state["status"], state["outcome"]) == ("closed", "cancelled"),
            "%s work expense is %s/%s (expected closed/cancelled)"
            % (source, state["status"], state["outcome"]))
    operations = [json.loads(row[0]) for row in
                  db_rows(runtime_db, "SELECT body FROM operations", source=source)]
    require(len(operations) == 2,
            "%s store %s holds %d operations (expected exactly 2: forward + "
            "withdrawal)" % (source, runtime_db, len(operations)))
    forward = next((op for op in operations
                    if op.get("capability") == "expense.submit"), None)
    withdrawal = next((op for op in operations
                       if op.get("capability") == "expense.withdraw"), None)
    require(forward is not None and withdrawal is not None,
            "%s store %s does not hold one forward and one withdrawal operation"
            % (source, runtime_db))
    require(forward["business_key"] == local_digest(
        ["expense-submit", "expense.submit",
         state["document"]["id"], state["document_revision"]]),
        "%s forward business key does not equal the recomputed expense "
        "operation key" % source)
    require(withdrawal["business_key"] == local_digest(
        ["expense-submit", "expense.withdraw", forward["id"]]),
        "%s withdrawal business key does not equal the recomputed compensation "
        "key digest([family, capability, original id])" % source)
    return state, forward, withdrawal


def require_runtime_proof(runtime_db, accepted_source, event_id, kind,
                          expected_data, source):
    """One runtime-written proof row: exact kind/status/data with a fingerprint
    recomputed locally from the stored body."""
    rows = db_rows(runtime_db,
                   "SELECT body,fingerprint FROM evidence WHERE source=? AND event_id=?",
                   (accepted_source, event_id), source)
    require(len(rows) == 1,
            "%s store holds %d proof rows for %s/%s (expected exactly 1)"
            % (source, len(rows), accepted_source, event_id))
    body = json.loads(rows[0][0])
    require((body["kind"], body["status"]) == (kind, "verified"),
            "%s proof %s/%s is %s/%s (expected %s/verified)"
            % (source, accepted_source, event_id, body["kind"], body["status"], kind))
    require(body["data"] == expected_data,
            "%s proof %s/%s data is %r (expected %r)"
            % (source, accepted_source, event_id, body["data"], expected_data))
    require(rows[0][1] == local_digest(body),
            "%s proof %s/%s fingerprint does not match its stored body"
            % (source, accepted_source, event_id))
    return body


def require_compensation_crash(store, source):
    """Crash-scenario store proof: both effects confirmed once, immutable link,
    stored adapter result bound to the original, receipts/withdrawal/invoice
    rows, withdrawn-kind proof, retained E08 truth, exact two-id closure."""
    runtime_db = Path(store)
    oa_db = runtime_db.parent / "oa.sqlite"
    require(oa_db.exists(),
            "%s crash store has no external database at %s" % (source, oa_db))
    state, forward, withdrawal = require_compensation_operations(runtime_db, source)
    for operation, prefix, label in ((forward, "OA-", "forward"),
                                     (withdrawal, "WD-", "withdrawal")):
        require(operation["status"] == "confirmed_succeeded"
                and operation["dispatch_state"] == "finished",
                "%s %s operation is %s/%s (expected confirmed_succeeded/finished)"
                % (source, label, operation["status"], operation["dispatch_state"]))
        require(len(operation["attempts"]) == 1
                and operation["attempts"][0]["status"] == "confirmed_succeeded"
                and str(operation.get("external_id", "")).startswith(prefix),
                "%s %s operation does not hold exactly one succeeded attempt "
                "with a retained %s external id" % (source, label, prefix))
    require(withdrawal["compensates"] == {
        "operation_id": forward["id"],
        "external_id": forward["external_id"],
        "capability": "expense.submit"},
        "%s withdrawal compensates link is not the immutable original snapshot "
        "(operation id, external id, capability)" % source)
    require(withdrawal["adapter_result"] == {
        "status": "accepted", "external_id": withdrawal["external_id"],
        "digest": forward["document_digest"],
        "original_external_id": forward["external_id"]},
        "%s withdrawal adapter_result does not bind the original external id "
        "and the withdrawal id truthfully" % source)
    # Proofs: the forward accepted proof stays verified; the withdrawal
    # appended a distinct withdrawn-kind proof — never a forward accepted one.
    require_runtime_proof(runtime_db, "oa", forward["id"], "accepted",
                          {"digest": forward["document_digest"],
                           "external_id": forward["external_id"]}, source)
    require_runtime_proof(runtime_db, "oa", withdrawal["id"], "withdrawn",
                          {"digest": withdrawal["document_digest"],
                           "external_id": withdrawal["external_id"],
                           "original_external_id": forward["external_id"]}, source)
    # Current E08 truth: still satisfied by the retained forward acceptance.
    e08 = [r for r in state["requirements"] if r["rule_id"] == "E08"]
    require(len(e08) == 1 and e08[0]["fulfillment"] == "satisfied",
            "%s E08 fulfillment is %r (expected satisfied by the retained "
            "forward acceptance; the withdrawal appends history, it never "
            "deletes it)" % (source, e08[0].get("fulfillment") if e08 else None))
    # External store: two tagged receipts, one withdrawal row per original,
    # unchanged invoices, counts recomputed from the rows.
    receipts = db_rows(oa_db, "SELECT key,digest,action,link_digest,result "
                              "FROM receipts", source=source)
    require(len(receipts) == 2,
            "%s crash external store holds %d receipts (expected exactly 2: "
            "forward + withdrawal)" % (source, len(receipts)))
    forward_row = next((r for r in receipts if r[0] == forward["business_key"]), None)
    withdrawal_row = next((r for r in receipts if r[0] == withdrawal["business_key"]), None)
    require(forward_row is not None and withdrawal_row is not None,
            "%s crash external store does not hold one receipt per business key"
            % source)
    require((forward_row[2] or "expense.submit", forward_row[3])
            == ("expense.submit", None)
            and forward_row[1] == forward["document_digest"],
            "%s forward receipt is not an unlinked expense.submit receipt of "
            "the original digest" % source)
    require(withdrawal_row[2] == "expense.withdraw"
            and withdrawal_row[3] == local_digest(withdrawal["compensates"]),
            "%s withdrawal receipt is not tagged with the withdraw action and "
            "the recomputed link digest" % source)
    require(json.loads(withdrawal_row[4]) == withdrawal["adapter_result"],
            "%s withdrawal receipt result differs from the stored adapter_result"
            % source)
    require(db_rows(oa_db, "SELECT original_external_id,external_id,key,digest "
                           "FROM withdrawals", source=source)
            == [(forward["external_id"], withdrawal["external_id"],
                 withdrawal["business_key"], withdrawal["document_digest"])],
            "%s crash external store does not hold exactly one withdrawal row "
            "bound to the original under the withdrawal key" % source)
    require(db_rows(oa_db, "SELECT invoice_id,external_id FROM invoices",
                    source=source) == [("INV-001", forward["external_id"])],
            "%s original invoices changed (the forward effect is never deleted)"
            % source)
    forward_accepted = set()
    for action, stored in db_rows(oa_db, "SELECT action,result FROM receipts",
                                  source=source):
        result = json.loads(stored)
        if (result.get("status") == "accepted"
                and (action is None or action == "expense.submit")
                and isinstance(result.get("external_id"), str) and result["external_id"]):
            forward_accepted.add(result["external_id"])
    require(forward_accepted == {forward["external_id"]},
            "%s crash external store accepted forward ids are %s (expected "
            "exactly the original)" % (source, sorted(forward_accepted)))
    # Closure: the exact two-id ack and the compensation disposition.
    completion = state["completion"]
    acknowledged = {entry["operation_id"]: entry["external_id"]
                    for entry in completion["acknowledged_operations"]}
    require(sorted(acknowledged) == sorted([forward["id"], withdrawal["id"]]),
            "%s closure ack names %s (expected exactly the original and the "
            "succeeded withdrawal)" % (source, sorted(acknowledged)))
    require(acknowledged[forward["id"]] == forward["external_id"]
            and acknowledged[withdrawal["id"]] == withdrawal["external_id"],
            "%s closure ack external ids do not match the operations" % source)
    dispositions = {entry["operation_id"]: entry
                    for entry in completion["operation_dispositions"]}
    require(set(dispositions[forward["id"]])
            == {"operation_id", "status", "dispatch_state"},
            "%s forward disposition is not the ordinary three-field shape"
            % source)
    require(set(dispositions[withdrawal["id"]])
            == {"operation_id", "status", "dispatch_state",
                "compensates", "adapter_result"},
            "%s withdrawal disposition does not carry compensates and "
            "adapter_result" % source)
    require(dispositions[withdrawal["id"]]["compensates"] == withdrawal["compensates"]
            and dispositions[withdrawal["id"]]["adapter_result"]
            == withdrawal["adapter_result"],
            "%s withdrawal disposition does not restate the link and the "
            "stored adapter result" % source)


def require_compensation_refusal(store, source):
    """Refusal-scenario store proof: an authoritative stored rejection, not an
    unknown or a reversal — confirmed_failed withdrawal, single-id ack, the
    refusing store queryable with zero effects, the original retained."""
    runtime_db = Path(store)
    oa_db = runtime_db.parent / "oa.sqlite"
    absent_db = runtime_db.parent / "absent.sqlite"
    require(oa_db.exists() and absent_db.exists(),
            "%s refusal scenario is missing an external database (%s, %s)"
            % (source, oa_db, absent_db))
    state, forward, withdrawal = require_compensation_operations(runtime_db, source)
    require(forward["status"] == "confirmed_succeeded"
            and forward["dispatch_state"] == "finished",
            "%s refusal forward operation is %s (expected confirmed_succeeded)"
            % (source, forward["status"]))
    require(withdrawal["status"] == "confirmed_failed"
            and withdrawal["dispatch_state"] == "finished"
            and len(withdrawal["attempts"]) == 1
            and withdrawal["attempts"][0]["status"] == "confirmed_failed",
            "%s refusal withdrawal is not confirmed_failed with exactly one "
            "failed attempt" % source)
    require(withdrawal["adapter_result"].get("status") == "rejected"
            and withdrawal["adapter_result"].get("reason") == "ORIGINAL_ABSENT"
            and withdrawal["adapter_result"].get("original_external_id")
            == forward["external_id"],
            "%s refusal adapter_result is not the stored ORIGINAL_ABSENT "
            "rejection bound to the original" % source)
    require_runtime_proof(runtime_db, "oa", forward["id"], "accepted",
                          {"digest": forward["document_digest"],
                           "external_id": forward["external_id"]}, source)
    require(not db_rows(runtime_db,
                        "SELECT body FROM evidence WHERE source='oa' AND event_id=?",
                        (withdrawal["id"],), source),
            "%s refused withdrawal must not insert a withdrawn proof" % source)
    completion = state["completion"]
    acknowledged = [entry["operation_id"]
                    for entry in completion["acknowledged_operations"]]
    require(acknowledged == [forward["id"]],
            "%s refusal closure ack is %s (expected exactly the retained "
            "forward id; a failed withdrawal is excluded)" % (source, acknowledged))
    disposition = next((entry for entry in completion["operation_dispositions"]
                        if entry["operation_id"] == withdrawal["id"]), None)
    require(disposition is not None
            and disposition["status"] == "confirmed_failed"
            and disposition["adapter_result"]["reason"] == "ORIGINAL_ABSENT",
            "%s refusal closure does not keep the refused withdrawal with its "
            "reason" % source)
    require(db_rows(oa_db, "SELECT COUNT(*) FROM withdrawals", source=source)[0][0] == 0
            and count_accepted(oa_db) == 1,
            "%s refusal original store does not hold exactly one accepted "
            "application and zero withdrawal effects" % source)
    absent_receipts = db_rows(absent_db, "SELECT action,link_digest,result "
                                         "FROM receipts", source=source)
    require(len(absent_receipts) == 1,
            "%s refusing store holds %d receipts (expected exactly 1 queryable "
            "rejection)" % (source, len(absent_receipts)))
    require(absent_receipts[0][0] == "expense.withdraw"
            and absent_receipts[0][1] == local_digest(withdrawal["compensates"]),
            "%s refusing store receipt is not tagged with the action and link "
            "digest" % source)
    refusal = json.loads(absent_receipts[0][2])
    require(refusal.get("status") == "rejected"
            and refusal.get("reason") == "ORIGINAL_ABSENT"
            and refusal.get("original_external_id") == forward["external_id"],
            "%s refusing store receipt is not the ORIGINAL_ABSENT rejection "
            "bound to the original" % source)
    require(db_rows(absent_db, "SELECT COUNT(*) FROM withdrawals",
                    source=source)[0][0] == 0,
            "%s refusing store must hold zero withdrawal effects" % source)


def require_compensation_proof(stdout, source):
    """Independent module/console compensation-demo proof, never stdout-only.

    Requires the demo's exact final line and exactly two distinct printed
    scenario stores (crash, refusal in order), then verifies each store
    directly with locally recomputed keys/fingerprints: business-key
    derivation, the immutable original snapshot, the stored adapter result
    binding, tagged receipts and the unique withdrawal row, unchanged
    invoices, accepted/withdrawn counts, the withdrawn-kind proof, current
    E08 truth, the exact closure ack and the refusal disposition. Returns the
    store paths.
    """
    require(COMPENSATION_FINAL_LINE in stdout,
            "%s output lacks %r" % (source, COMPENSATION_FINAL_LINE))
    stores = INSPECT_DB.findall(stdout)
    require(len(stores) == 2,
            "%s printed %d inspect databases (expected exactly 2: crash, "
            "refusal)" % (source, len(stores)))
    require(len(set(stores)) == 2,
            "%s printed duplicate store paths: %s" % (source, stores))
    names = [Path(store).parent.name for store in stores]
    require(names == list(COMPENSATION_SCENARIOS),
            "%s printed scenario directories %s (expected crash, refusal in "
            "order)" % (source, names))
    require_compensation_crash(stores[0], source)
    require_compensation_refusal(stores[1], source)
    return stores


def rotation_six_table_digest(runtime_db):
    """SHA-256 over the ordered rowid dumps of all six tables (16-char prefix).

    Recomputed locally on purpose: this script never imports the product
    package for its proofs.
    """
    dump = {}
    db = sqlite3.connect(str(runtime_db))
    try:
        for table in ROTATION_TABLES:
            dump[table] = [list(row) for row in
                           db.execute("SELECT * FROM %s ORDER BY rowid" % table)]
    finally:
        db.close()
    return hashlib.sha256(canonical_json(dump).encode("utf-8")).hexdigest()[:16]


def require_rotation_proof(stdout, source):
    """Independent module/console rotation-demo proof, never stdout-only.

    Requires the demo's exact final line, its printed before/after six-table
    digests and exactly one printed store, then verifies the store directly:
    the six-table digest recomputed locally must equal the printed after-all-
    steps digest (and differ from the before-rotation digest), exactly two
    verified approval-evidence rows with locally recomputed fingerprints and
    document digest, exactly one command row per rotation command id with the
    original cached receipt still pending_verification while its evidence row
    is verified, zero operations and schema 1. Returns the store path.
    """
    require(ROTATION_FINAL_LINE in stdout,
            "%s output lacks %r" % (source, ROTATION_FINAL_LINE))
    printed = ROTATION_FINAL_DIGEST.search(stdout)
    require(printed is not None, "%s printed no after-all-steps digest" % source)
    before_printed = ROTATION_BEFORE_DIGEST.search(stdout)
    require(before_printed is not None, "%s printed no before-rotation digest" % source)
    store_match = INSPECT_DB.search(stdout)
    require(store_match is not None, "%s printed no inspect --db path" % source)
    runtime_db = Path(store_match.group(1))
    require(runtime_db.exists(),
            "%s runtime database %s does not exist" % (source, runtime_db))
    require(runtime_db.parent.name == "rotate",
            "%s store directory is %s (expected rotate)"
            % (source, runtime_db.parent.name))

    state = require_work_state(runtime_db, "rotate", source)
    require((state.get("status"), state.get("state_version")) == ("active", 4),
            "%s work rotate is %s/%s (expected active/4)"
            % (source, state.get("status"), state.get("state_version")))
    document_digest = local_digest(state["document"])

    evidence_ids = {}
    for event_id in ROTATION_EVENT_IDS:
        body = require_source_event_proof(runtime_db, "rotate", "finance", event_id,
                                          "verified", source)
        require(body["kind"] == "approval"
                and body["data"] == {"digest": document_digest},
                "%s evidence %s is not an approval of the work document"
                % (source, event_id))
        evidence_ids[event_id] = body["id"]
    require(db_rows(runtime_db, "SELECT COUNT(*) FROM evidence",
                    source=source)[0][0] == 2,
            "%s store holds evidence rows beyond the two rotation approvals" % source)

    commands = db_rows(runtime_db, "SELECT actor,id FROM commands", source=source)
    require(len(commands) == 6,
            "%s store holds %d command rows (expected exactly 6: three "
            "initialization + three rotation commands, the same-command "
            "re-sign adding none)" % (source, len(commands)))
    by_id = {}
    for actor, command_id in commands:
        by_id.setdefault(command_id, []).append(actor)
    for command_id in ROTATION_COMMAND_IDS:
        require(by_id.get(command_id) == ["finance"],
                "%s command %s appears %d times with actors %s (expected "
                "exactly once, by finance)"
                % (source, command_id, len(by_id.get(command_id, [])),
                   by_id.get(command_id)))
    receipt = json.loads(db_rows(runtime_db, "SELECT receipt FROM commands "
                                 "WHERE id='cmd-rotation-k1'", source=source)[0][0])
    require(receipt.get("decision") == "accepted"
            and receipt.get("evidence_status") == "pending_verification"
            and receipt.get("evidence_id") == evidence_ids["evt-rotation-1"],
            "%s cached receipt for cmd-rotation-k1 is not the original "
            "accepted/pending_verification receipt of evt-rotation-1 (the "
            "same-command re-sign must return the stored receipt verbatim, "
            "never a refreshed status)" % source)

    require(db_rows(runtime_db, "SELECT COUNT(*) FROM operations",
                    source=source)[0][0] == 0,
            "%s store holds operations (expected 0: evidence-only scenario)"
            % source)
    require(db_rows(runtime_db, "SELECT COUNT(*) FROM events",
                    source=source)[0][0] == 4,
            "%s store holds %d events (expected exactly 4: WorkCreated, "
            "ContractBound, PlanRevised, EvidenceEvaluated)"
            % (source, db_rows(runtime_db, "SELECT COUNT(*) FROM events",
                               source=source)[0][0]))
    require(db_rows(runtime_db, "SELECT * FROM metadata", source=source)
            == [("schema_version", "1")],
            "%s metadata is not exactly schema_version 1" % source)

    digest = rotation_six_table_digest(runtime_db)
    require(digest == printed.group(1),
            "%s recomputed six-table digest %s does not equal the printed "
            "digest %s" % (source, digest, printed.group(1)))
    require(printed.group(1) != before_printed.group(1),
            "%s printed identical before/after digests (the new command must "
            "be reflected)" % source)
    return str(runtime_db)


def require_publication_proof(stdout, source):
    """Independent module/console publication-demo proof, never stdout-only.

    Requires the demo's exact final line and its printed fail-closed loader
    lines (absent vs tampered vs withdrawn, pairwise distinguishable),
    locates the runtime store from the printed inspect command and both
    artifacts from the printed artifact paths, then verifies both stores
    directly with the standard library only: exactly two hash-named
    committed .json (the publication and the withdrawal record) and zero
    .stage leftovers; each artifact parsed (exact keys, artifact_version 1,
    recomputed content digest, accepted FILE- receipt, digest-based key,
    sha256(key) file name; the publication document is the bare packaged
    card, the withdrawal record document is the closed four-field shape
    binding the publication's content digest); the runtime database read
    directly (pub-1 closed/succeeded, pub-2 active, wd-1 closed/succeeded,
    pub-3 active, exactly two confirmed_succeeded operations with one
    attempt each whose business keys are the publication and withdrawal
    keys, exactly six evidence rows — three verified sop-owner card
    approvals, the conflict one bound to different content than the winner,
    one verified sop-owner card_withdrawal binding the published digest,
    plus the two runtime-written sop-store accepted proofs with event_id
    equal to the operation ids — and the pinned command rows with both D66
    conflict codes and all four blocked codes). Returns the runtime store
    path.
    """
    require(PUBLICATION_FINAL_LINE in stdout,
            "%s output lacks %r (history rewritten must stay 0)"
            % (source, PUBLICATION_FINAL_LINE))
    absent = PUBLICATION_ABSENT_LINE.search(stdout)
    require(absent is not None, "%s printed no absent-version loader line"
            % source)
    tampered = PUBLICATION_TAMPERED_LINE.search(stdout)
    require(tampered is not None, "%s printed no tampered-file loader line"
            % source)
    withdrawn = PUBLICATION_WITHDRAWN_LINE.search(stdout)
    require(withdrawn is not None, "%s printed no withdrawn-version loader "
            "line" % source)
    require("no published card" in absent.group(1)
            and "no published card" not in tampered.group(1)
            and "no published card" not in withdrawn.group(1)
            and len({absent.group(1), tampered.group(1),
                     withdrawn.group(1)}) == 3,
            "%s loader failure lines are not distinguishable (absent=%r, "
            "tampered=%r, withdrawn=%r)" % (source, absent.group(1),
                                            tampered.group(1),
                                            withdrawn.group(1)))
    require("withdrawn" in withdrawn.group(1),
            "%s withdrawn-version line does not name withdrawal (%r)"
            % (source, withdrawn.group(1)))
    store_match = INSPECT_DB.search(stdout)
    require(store_match is not None, "%s printed no inspect --db path" % source)
    runtime_db = Path(store_match.group(1))
    require(runtime_db.exists(),
            "%s runtime database %s does not exist" % (source, runtime_db))
    require(runtime_db.parent.name == "publication",
            "%s store directory is %s (expected publication)"
            % (source, runtime_db.parent.name))
    artifact_match = COMMITTED_ARTIFACT.search(stdout)
    require(artifact_match is not None, "%s printed no artifact path" % source)
    artifact_file = Path(artifact_match.group(1))
    require(artifact_file.exists(),
            "%s printed artifact %s does not exist" % (source, artifact_file))
    store_dir = artifact_file.parent
    committed = sorted(path for path in store_dir.iterdir()
                       if HASH_NAMED.fullmatch(path.name))
    require(len(committed) == 2,
            "%s publication store holds %d hash-named artifacts (expected "
            "exactly 2: one publication identity per card version plus one "
            "withdrawal record per withdrawn version)"
            % (source, len(committed)))
    require(not [path for path in store_dir.iterdir()
                 if path.suffix == ".stage"],
            "%s publication store holds .stage leftovers" % source)

    artifact = json.loads(artifact_file.read_text(encoding="utf-8"))
    require(set(artifact) == {"artifact_version", "key", "content_digest",
                              "document", "receipt"},
            "%s artifact keys are %s (expected the exact FilePublisher shape)"
            % (source, sorted(artifact)))
    require(artifact["artifact_version"] == 1,
            "%s artifact_version is %r (expected 1)" % (source,
                                                        artifact.get("artifact_version")))
    document = artifact["document"]
    policy = document.get("policy") if isinstance(document, dict) else None
    require(isinstance(policy, dict)
            and (policy.get("id"), policy.get("version")) == ("content-publish",
                                                              "demo-1"),
            "%s stored document is not the bare packaged publishing card"
            % source)
    content_digest = local_digest(document)
    require(artifact["content_digest"] == content_digest,
            "%s artifact content digest does not match its recomputed "
            "document digest (tampered artifact?)" % source)
    receipt = artifact["receipt"]
    require(set(receipt) == {"status", "external_id", "digest"},
            "%s artifact receipt keys are %s" % (source, sorted(receipt)))
    require(receipt["status"] == "accepted"
            and receipt["external_id"].startswith("FILE-")
            and receipt["digest"] == content_digest,
            "%s artifact receipt is not an accepted FILE- receipt of the "
            "card digest" % source)
    key = "sop-pub:" + local_digest(["content-publish", "demo-1"])
    require(artifact["key"] == key,
            "%s artifact key is not the digest-based publication key" % source)
    require(artifact_file.name
            == hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json",
            "%s artifact file name is not sha256(publication key)" % source)

    # The withdrawal record: located by its printed path AND by the sha256
    # name its digest-based key must occupy, then parsed like the publication
    # artifact — the closed four-field document binds the exact published
    # content digest (D67-D69).
    withdrawal_key = ("sop-withdrawn:"
                      + local_digest(["content-publish", "demo-1"]))
    withdrawal_name = (hashlib.sha256(
        withdrawal_key.encode("utf-8")).hexdigest() + ".json")
    require({path.name for path in committed} == {artifact_file.name,
                                                  withdrawal_name},
            "%s publication store census is not exactly the publication "
            "artifact plus the withdrawal record" % source)
    record_match = WITHDRAWAL_RECORD_LINE.search(stdout)
    require(record_match is not None, "%s printed no withdrawal record path"
            % source)
    record_file = Path(record_match.group(1))
    require(record_file.exists(),
            "%s printed withdrawal record %s does not exist"
            % (source, record_file))
    require(record_file.name == withdrawal_name,
            "%s withdrawal record file name is not sha256(withdrawal key)"
            % source)
    record_artifact = json.loads(record_file.read_text(encoding="utf-8"))
    require(set(record_artifact) == {"artifact_version", "key",
                                     "content_digest", "document", "receipt"},
            "%s withdrawal record keys are %s (expected the exact "
            "FilePublisher shape)" % (source, sorted(record_artifact)))
    require(record_artifact["artifact_version"] == 1,
            "%s withdrawal record artifact_version is %r (expected 1)"
            % (source, record_artifact.get("artifact_version")))
    record = record_artifact["document"]
    require(record == {"discriminator": "sop.withdrawal",
                       "policy_id": "content-publish",
                       "policy_version": "demo-1",
                       "published_digest": content_digest},
            "%s withdrawal record document is not the closed four-field "
            "shape binding the published digest" % source)
    record_digest = local_digest(record)
    require(record_artifact["content_digest"] == record_digest,
            "%s withdrawal record content digest does not match its "
            "recomputed document digest (tampered withdrawal record?)"
            % source)
    record_receipt = record_artifact["receipt"]
    require(record_receipt["status"] == "accepted"
            and record_receipt["external_id"].startswith("FILE-")
            and record_receipt["digest"] == record_digest,
            "%s withdrawal record receipt is not an accepted FILE- receipt "
            "of the record digest" % source)
    require(record_artifact["key"] == withdrawal_key,
            "%s withdrawal record key is not the digest-based withdrawal "
            "key" % source)

    completed = require_work_state(runtime_db, "pub-1", source)
    require((completed.get("status"), completed.get("outcome"))
            == ("closed", "succeeded"),
            "%s work pub-1 is %s/%s (expected closed/succeeded)"
            % (source, completed.get("status"), completed.get("outcome")))
    conflicting = require_work_state(runtime_db, "pub-2", source)
    require(conflicting.get("status") == "active",
            "%s work pub-2 is %s (expected active with its persisted "
            "conflict receipt)" % (source, conflicting.get("status")))
    withdrawn_work = require_work_state(runtime_db, "wd-1", source)
    require((withdrawn_work.get("status"), withdrawn_work.get("outcome"))
            == ("closed", "succeeded"),
            "%s withdrawal work wd-1 is %s/%s (expected closed/succeeded)"
            % (source, withdrawn_work.get("status"),
               withdrawn_work.get("outcome")))
    republishing = require_work_state(runtime_db, "pub-3", source)
    require(republishing.get("status") == "active",
            "%s work pub-3 is %s (expected active with its persisted "
            "re-publication refusal)" % (source, republishing.get("status")))

    operations = [json.loads(row[0]) for row in
                  db_rows(runtime_db, "SELECT body FROM operations", source=source)]
    require(len(operations) == 2,
            "%s store holds %d operations (expected exactly 2: the "
            "publication and the withdrawal)" % (source, len(operations)))
    operation = operations[0]
    require(operation["status"] == "confirmed_succeeded"
            and len(operation["attempts"]) == 1,
            "%s operation is not confirmed_succeeded with one attempt"
            % source)
    require(operation["business_key"] == key and operation["work_id"] == "pub-1",
            "%s operation business key/work do not match the publication"
            % source)
    withdrawal_operation = [candidate for candidate in operations
                            if candidate["business_key"] == withdrawal_key]
    require(len(withdrawal_operation) == 1,
            "%s store holds %d operations under the withdrawal key (expected "
            "exactly 1)" % (source, len(withdrawal_operation)))
    withdrawal_operation = withdrawal_operation[0]
    require(withdrawal_operation["status"] == "confirmed_succeeded"
            and len(withdrawal_operation["attempts"]) == 1,
            "%s withdrawal operation is not confirmed_succeeded with one "
            "attempt" % source)
    require(withdrawal_operation["work_id"] == "wd-1",
            "%s withdrawal operation does not belong to the withdrawal work"
            % source)

    evidence = {json.loads(row[2])["event_id"]: (row[0], json.loads(row[2]))
                for row in db_rows(runtime_db, "SELECT source, event_id, body "
                                   "FROM evidence", source=source)}
    for event_id, digest_value in (("evt-approve-valid", content_digest),
                                   ("evt-approve-conflict", None),
                                   ("evt-approve-pub3", content_digest)):
        require(event_id in evidence,
                "%s evidence %s is missing" % (source, event_id))
        row_source, body = evidence[event_id]
        require((row_source, body["kind"], body["status"])
                == ("sop-owner", "card_approval", "verified"),
                "%s evidence %s is not a verified sop-owner card approval"
                % (source, event_id))
        require(body["data"].get("policy_version") == "demo-1",
                "%s card approval %s is not version-bound" % (source, event_id))
        if digest_value is not None:
            require(body["data"].get("digest") == digest_value,
                    "%s card approval %s did not bind the published digest"
                    % (source, event_id))
        else:
            # The doctored card's own approval: same version, DIFFERENT content
            # than the winner (D66).
            require(body["data"].get("digest") != content_digest
                    and len(body["data"].get("digest", "")) == 64,
                    "%s conflict approval bound the winner's digest (the "
                    "doctored card differs)" % source)
    require("evt-approve-wd1" in evidence,
            "%s evidence evt-approve-wd1 is missing" % source)
    row_source, withdrawal_body = evidence["evt-approve-wd1"]
    require((row_source, withdrawal_body["kind"], withdrawal_body["status"])
            == ("sop-owner", "card_withdrawal", "verified"),
            "%s evidence evt-approve-wd1 is not a verified sop-owner "
            "card_withdrawal" % source)
    require(withdrawal_body["data"].get("policy_version") == "demo-1"
            and withdrawal_body["data"].get("digest") == content_digest,
            "%s card_withdrawal evt-approve-wd1 is not version-bound to the "
            "published digest" % source)
    accepted_rows = [pair for event_id, pair in evidence.items()
                     if pair[0] == "sop-store"]
    require(len(evidence) == 6,
            "%s store holds %d evidence rows (expected exactly 6: three "
            "card approvals, one card_withdrawal and two runtime-written "
            "accepted proofs)" % (source, len(evidence)))
    require(len(accepted_rows) == 2,
            "%s store holds %d sop-store rows (expected exactly the two "
            "runtime-written accepted proofs)" % (source, len(accepted_rows)))
    accepted_by_id = {pair[1]["event_id"]: pair[1] for pair in accepted_rows}
    require(operation["id"] in accepted_by_id,
            "%s store holds no sop-store accepted proof for the publication "
            "operation %s" % (source, operation["id"]))
    accepted = accepted_by_id[operation["id"]]
    require(accepted["kind"] == "accepted" and accepted["status"] == "verified",
            "%s accepted proof under sop-store is not verified (event_id must "
            "equal the operation id; no principal can sign as sop-store)"
            % source)
    require(accepted["event_id"] == operation["id"],
            "%s accepted proof event_id is not the operation id" % source)
    require(accepted["data"].get("digest") == content_digest
            and accepted["data"].get("external_id") == receipt["external_id"],
            "%s accepted proof is not bound to the committed artifact" % source)
    require(withdrawal_operation["id"] in accepted_by_id,
            "%s store holds no sop-store accepted proof for the withdrawal "
            "operation %s" % (source, withdrawal_operation["id"]))
    withdrawal_accepted = accepted_by_id[withdrawal_operation["id"]]
    require(withdrawal_accepted["kind"] == "accepted"
            and withdrawal_accepted["status"] == "verified",
            "%s withdrawal accepted proof under sop-store is not verified"
            % source)
    require(withdrawal_accepted["data"].get("digest") == record_digest
            and withdrawal_accepted["data"].get("external_id")
            == record_receipt["external_id"],
            "%s withdrawal accepted proof is not bound to the committed "
            "withdrawal record" % source)

    commands = db_rows(runtime_db, "SELECT actor, id FROM commands", source=source)
    by_id = {}
    for actor, command_id in commands:
        by_id.setdefault(command_id, []).append(actor)
    for command_id in PUBLICATION_RUN_COMMANDS + PUBLICATION_GATEWAY_COMMANDS:
        require(by_id.get(command_id) is not None and len(by_id[command_id]) == 1,
                "%s command %s appears %d times (expected exactly once)"
                % (source, command_id, len(by_id.get(command_id, []))))
    require(len(commands) == len(PUBLICATION_RUN_COMMANDS)
            + len(PUBLICATION_GATEWAY_COMMANDS),
            "%s store holds %d command rows (expected exactly 22)"
            % (source, len(commands)))
    for conflict_id, whose in (("cmd-propose-conflict", "doctored card"),
                               ("cmd-propose-pub3",
                                "re-publication of the withdrawn version")):
        conflict_receipt = json.loads(db_rows(
            runtime_db, "SELECT receipt FROM commands WHERE id=?",
            args=(conflict_id,), source=source)[0][0])
        require(conflict_receipt.get("code") == "OPERATION_CONTENT_CONFLICT",
                "%s receipt for %s lost its OPERATION_CONTENT_CONFLICT code "
                "(the D66 order must stay visible: the %s conflict surfaces "
                "only after that work's own approval)" % (source, conflict_id,
                                                          whose))
    for blocked_id in PUBLICATION_BLOCKED_COMMANDS:
        blocked_receipt = json.loads(db_rows(
            runtime_db, "SELECT receipt FROM commands WHERE id=?",
            args=(blocked_id,), source=source)[0][0])
        require(blocked_receipt.get("code") == "REQUIREMENT_UNSATISFIED",
                "%s receipt for %s lost its REQUIREMENT_UNSATISFIED code"
                % (source, blocked_id))
    require(db_rows(runtime_db, "SELECT COUNT(*) FROM events",
                    source=source)[0][0] == 21,
            "%s store holds an unexpected event count" % source)
    require(db_rows(runtime_db, "SELECT * FROM metadata", source=source)
            == [("schema_version", "1")],
            "%s metadata is not exactly schema_version 1" % source)
    return str(runtime_db)


def run_printed_inspect_command(stdout, venv_python, outside, source,
                                outcome_marker='"outcome": "succeeded"'):
    """Re-run every printed inspect command verbatim (python3 swapped)."""
    commands = INSPECT_COMMAND.findall(stdout)
    require(commands, "%s printed no inspect command" % source)
    for command in commands:
        words = shlex.split(command)
        require(words[0] == "python3",
                "%s inspect command is not python3-based" % source)
        words[0] = str(venv_python)
        result = run(words, outside)
        require(outcome_marker in result.stdout,
                "%s installed inspect did not report %s" % (source,
                                                            outcome_marker))


def http_get(url, timeout=10):
    """One real HTTP GET with the standard library; returns (status, headers, body)."""
    request = urllib.request.Request(url, headers={"Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.headers, response.read()


def http_json(url, source):
    status, headers, body = http_get(url)
    require(status == 200, "%s: HTTP %s for %s" % (source, status, url))
    require("application/json" in (headers.get("Content-Type") or ""),
            "%s: %s served %r (expected application/json)"
            % (source, url, headers.get("Content-Type")))
    return json.loads(body.decode("utf-8"))


def snapshot_tables(db_path):
    """Full row snapshot of every table, for read-only equality proofs."""
    db = sqlite3.connect(str(db_path))
    try:
        tables = [row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {name: db.execute('SELECT * FROM "%s"' % name).fetchall()
                for name in tables}
    finally:
        db.close()


def start_ui_subprocess(command, outside, source):
    """Start a ui/ui-demo command; block until it prints its loopback URL."""
    proc = subprocess.Popen([str(part) for part in command], cwd=str(outside),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env=clean_env())
    for _ in range(400):
        line = proc.stdout.readline()
        if not line:
            proc.wait(timeout=10)
            raise SystemExit("FAILED: %s exited before printing a URL: %s"
                             % (source, proc.stderr.read()[-800:]))
        line = line.strip()
        if line.startswith("http://127.0.0.1:"):
            return proc, line
    stop_ui_cleanly(proc, source)
    raise SystemExit("FAILED: %s printed no loopback URL line" % source)


def stop_ui_cleanly(proc, source):
    """Interrupt the server process and require a prompt, clean exit."""
    proc.send_signal(signal.SIGINT if os.name != "nt" else signal.SIGTERM)
    try:
        code = proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)
        raise SystemExit("FAILED: %s did not exit after the interrupt" % source)
    if os.name != "nt":
        require(code == 0,
                "%s exited %s after the interrupt (expected a clean exit 0)"
                % (source, code))


def require_ui_over_http(base_url, package_dir, db_path, source):
    """Real-HTTP proof over one running UI server; returns the seeded db path.

    Fetches the HTML/JS/CSS and requires byte equality with the packaged
    assets, reads the four API endpoints and requires the five seeded works
    with their pinned states, and proves the store byte-identical before and
    after every read (read-only viewer).
    """
    before = snapshot_tables(db_path)
    status, headers, html = http_get(base_url)
    require(status == 200, "%s: HTTP %s for %s" % (source, status, base_url))
    require("text/html" in (headers.get("Content-Type") or ""),
            "%s: index served %r" % (source, headers.get("Content-Type")))
    require(html == (package_dir / "web" / "index.html").read_bytes(),
            "%s: served index.html differs from the packaged asset" % source)
    for name, kind in (("app.js", "javascript"), ("app.css", "css")):
        asset_headers = http_get(base_url + name)[1]
        require(kind in (asset_headers.get("Content-Type") or ""),
                "%s: %s served %r" % (source, name, asset_headers.get("Content-Type")))
        require(http_get(base_url + name)[2]
                == (package_dir / "web" / name).read_bytes(),
                "%s: served %s differs from the packaged asset" % (source, name))
    summary = http_json(base_url + "api/summary", source)
    require(summary.get("counts", {}).get("works") == 5,
            "%s: summary counts.works is %r (expected 5)"
            % (source, summary.get("counts", {}).get("works")))
    require(isinstance(summary.get("source"), str) and summary.get("source"),
            "%s: summary source is not a nonempty string" % source)
    works = http_json(base_url + "api/works?limit=200&offset=0", source)
    require({work["id"] for work in works.get("works", [])} == UI_WORK_IDS,
            "%s: /api/works ids are %s" % (source, sorted(
                work["id"] for work in works.get("works", []))))
    detail = http_json(base_url + "api/work?id=cancel-1", source)
    work = detail.get("work", {})
    require((work.get("status"), work.get("outcome")) == ("closed", "cancelled"),
            "%s: cancel-1 is %s/%s" % (source, work.get("status"), work.get("outcome")))
    operations = detail.get("operations", [])
    require(any(operation.get("status") == "confirmed_succeeded"
                and operation.get("external_id")
                for operation in operations),
            "%s: cancel-1 shows no confirmed external effect" % source)
    events = http_json(base_url + "api/events?work_id=uncertain-1&after=0&limit=10",
                       source)
    seqs = [int(event["seq"]) for event in events.get("events", [])]
    require(seqs == sorted(seqs) and seqs,
            "%s: uncertain-1 events are not ascending seq" % source)
    after = snapshot_tables(db_path)
    require(after == before,
            "%s: the UI changed the store while serving (tables differ)" % source)
    print("%s: HTML/JS/CSS byte-equal to the packaged assets; summary/works/"
          "work/events correct; store tables unchanged" % source)


def run_ui_stages(venv_python, console, outside, workspace, package_dir):
    """Stage 14: installed module AND console UI over real HTTP, or a loud skip.

    The read-only backend (work_runtime.ui_server) is assembled by a separate
    owner; when it is absent from this build the stage prints an explicit
    SKIPPED line and returns the skip reason for the final summary. It never
    reports UI coverage it did not actually run.
    """
    probe = subprocess.run([str(venv_python), "-c", "import work_runtime.ui_server"],
                           cwd=str(outside), capture_output=True, text=True,
                           env=clean_env())
    if probe.returncode != 0:
        print("SKIPPED: read-only UI backend (work_runtime.ui_server) is not "
              "present in this build; installed UI HTTP verification runs once "
              "the backend is assembled.")
        return "installed-UI HTTP (backend not assembled)"
    module_dir = workspace / "ui-module"
    console_dir = workspace / "ui-console"
    module_dir.mkdir()
    console_dir.mkdir()
    proc, url = start_ui_subprocess(
        [venv_python, "-m", "work_runtime", "ui-demo", "--directory", module_dir],
        outside, "module ui-demo")
    try:
        require_ui_over_http(url, package_dir, module_store(module_dir), "module ui-demo")
        stop_ui_cleanly(proc, "module ui-demo")
    except BaseException:
        proc.kill()
        raise
    console_proc, console_url = start_ui_subprocess(
        [console, "ui-demo", "--directory", console_dir], outside, "console ui-demo")
    try:
        require_ui_over_http(console_url, package_dir,
                             module_store(console_dir), "console ui-demo")
        stop_ui_cleanly(console_proc, "console ui-demo")
    except BaseException:
        console_proc.kill()
        raise
    ui_proc, ui_url = start_ui_subprocess(
        [console, "ui", "--db", module_store(module_dir)], outside, "console ui")
    try:
        summary = http_json(ui_url + "api/summary", "console ui")
        require(summary.get("counts", {}).get("works") == 5,
                "console ui: summary counts.works is %r (expected 5)"
                % summary.get("counts", {}).get("works"))
        stop_ui_cleanly(ui_proc, "console ui")
    except BaseException:
        ui_proc.kill()
        raise
    print("independent check: module and console UI served real HTTP with the "
          "five seeded works and shut down cleanly on interrupt")
    return None


def module_store(seed_directory):
    """The runtime.sqlite inside a ui-demo seed folder (exactly one folder)."""
    folders = [path for path in Path(seed_directory).iterdir() if path.is_dir()]
    require(len(folders) == 1,
            "ui-demo seed directory %s holds %d folders (expected exactly 1)"
            % (seed_directory, len(folders)))
    store = folders[0] / "runtime.sqlite"
    require(store.is_file(), "no runtime.sqlite under %s" % folders[0])
    return store


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fresh-venv install and outside-checkout verification.")
    parser.add_argument("--python", default=sys.executable, help="interpreter used to create the venv")
    parser.add_argument("--repo", default=str(REPO_ROOT), help="repository to install")
    parser.add_argument("--keep", action="store_true", help="keep the temporary workspace for inspection")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    workspace = Path(tempfile.mkdtemp(prefix="gwr-verify-install-"))
    venv = workspace / "venv"
    outside = workspace / "outside"
    suffix = ".exe" if os.name == "nt" else ""
    venv_python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    console = venv / ("Scripts" if os.name == "nt" else "bin") / ("work-runtime" + suffix)
    started = time.time()
    try:
        print("=== fresh virtual environment ===")
        version = subprocess.run([args.python, "--version"], capture_output=True, text=True)
        sys.stdout.write(version.stdout)
        print("workspace: %s" % workspace)
        outside.mkdir()
        run([args.python, "-m", "venv", venv], workspace)

        print("=== install (real, non-editable) ===")
        run([venv_python, "-m", "pip", "install", repo], workspace)

        print("=== import resolves inside the venv, not the checkout ===")
        origin = run([venv_python, "-c",
                      "import work_runtime, sys; sys.stdout.write(work_runtime.__file__)"],
                     outside)
        # Resolve both sides: on macOS the venv may live behind a /var vs
        # /private/var symlink, which is a location detail, not a wrong origin.
        require(Path(origin.stdout).resolve().is_relative_to(venv.resolve()),
                "work_runtime imported from %s (expected inside %s); the checkout or "
                "another environment satisfied the import" % (origin.stdout or "<nothing>", venv))
        print(origin.stdout)

        print("=== zero third-party runtime dependencies ===")
        listing = run([venv_python, "-m", "pip", "list", "--format=freeze"], outside).stdout
        installed = {line.split("==", 1)[0] for line in listing.splitlines() if line.strip()}
        extras = installed - ALLOWED_PACKAGES
        require(not extras, "unexpected installed packages: %s" % sorted(extras))
        print(", ".join(sorted(installed)))

        print("=== module demo outside the checkout ===")
        module_demo = run([venv_python, "-m", "work_runtime", "demo"], outside, show=True)
        require(DEMO_FINAL_LINE in module_demo.stdout,
                "module demo output lacks %r" % DEMO_FINAL_LINE)
        match = INSPECT_DB.search(module_demo.stdout)
        require(match is not None, "module demo printed no inspect --db path to locate its databases")
        oa_db = Path(match.group(1)).parent / "oa.sqlite"
        accepted = count_accepted(oa_db)
        require(accepted == 1,
                "fake OA database %s holds %d accepted applications (expected exactly 1)"
                % (oa_db, accepted))
        print("independent check: fake OA accepted applications = %d" % accepted)

        print("=== module publish-demo outside the checkout ===")
        module_publish = run([venv_python, "-m", "work_runtime", "publish-demo"],
                             outside, show=True)
        require(PUBLISH_FINAL_LINE in module_publish.stdout,
                "module publish-demo output lacks %r" % PUBLISH_FINAL_LINE)
        pub_match = INSPECT_DB.search(module_publish.stdout)
        require(pub_match is not None,
                "publish-demo printed no inspect --db path to locate its databases")
        publisher_db = Path(pub_match.group(1)).parent / "publisher.sqlite"
        publications = count_publications(publisher_db)
        require(publications == 1,
                "publisher database %s holds %d publications (expected exactly 1)"
                % (publisher_db, publications))
        print("independent check: published artifacts = %d" % publications)

        print("=== module intervention-demo outside the checkout ===")
        module_intervention = run([venv_python, "-m", "work_runtime", "intervention-demo"],
                                  outside, show=True)
        require(INTERVENTION_FINAL_LINE in module_intervention.stdout,
                "module intervention-demo output lacks %r" % INTERVENTION_FINAL_LINE)
        stores = require_intervention_store_counts(module_intervention.stdout,
                                                   "module intervention-demo")
        print("independent check: one accepted application per intervention store")

        print("=== installed inspect reads the migrated pinned work ===")
        migrated = run([venv_python, "-m", "work_runtime", "inspect",
                        "--db", stores[2], "--work", "migrate",
                        "--policy-versions", "demo-1,demo-2"], outside)
        require('"policy_version": "demo-2"' in migrated.stdout,
                "installed inspect with --policy-versions did not read the demo-2 pin")

        print("=== console demo outside the checkout ===")
        console_demo = run([console, "demo"], outside, show=True)
        require(DEMO_FINAL_LINE in console_demo.stdout,
                "console demo output lacks %r" % DEMO_FINAL_LINE)

        print("=== console intervention-demo outside the checkout ===")
        console_intervention = run([console, "intervention-demo"], outside, show=True)
        require(INTERVENTION_FINAL_LINE in console_intervention.stdout,
                "console intervention-demo output lacks %r" % INTERVENTION_FINAL_LINE)
        require_intervention_store_counts(console_intervention.stdout,
                                          "console intervention-demo")

        print("=== packaged SOP resources and installed lint-sop ===")
        probe = run([venv_python, "-c",
                     "import importlib.resources, os, sys; "
                     "sys.stdout.write(os.fspath("
                     "importlib.resources.files('work_runtime')))"], outside)
        package_dir = Path(probe.stdout)
        require(package_dir.resolve().is_relative_to(venv.resolve()),
                "work_runtime package resolves to %s (expected inside %s); "
                "the SOP data files would not ship with a real install"
                % (package_dir, venv))
        for name in ("expense.json", "publishing.json"):
            require((package_dir / "data" / "sop" / name).is_file(),
                    "the install ships no packaged SOP card %s" % name)
        sample = workspace / "publishing-sample.json"
        sample.write_bytes((package_dir / "data" / "sop" / "publishing.json")
                           .read_bytes())
        lint = run([console, "lint-sop", str(sample), "--json"], outside)
        lint_result = json.loads(lint.stdout)
        require(lint_result == {"valid": True,
                                "digest": PINNED_PUBLISHING_DIGEST,
                                "diagnostics": [], "scope": "static-only"},
                "installed lint-sop reported %r (expected clean with the pinned "
                "digest)" % lint_result)

        print("=== module adoption-demo outside the checkout ===")
        module_adoption = run([venv_python, "-m", "work_runtime", "adoption-demo"],
                              outside, show=True)
        require_adoption_proof(module_adoption.stdout, "module adoption-demo")
        run_printed_inspect_command(module_adoption.stdout, venv_python, outside,
                                    "module adoption-demo")
        print("independent check: one hash-named committed artifact, digest/"
              "receipt/business key verified, work closed succeeded")

        print("=== console adoption-demo outside the checkout ===")
        console_adoption = run([console, "adoption-demo"], outside, show=True)
        require_adoption_proof(console_adoption.stdout, "console adoption-demo")
        run_printed_inspect_command(console_adoption.stdout, venv_python, outside,
                                    "console adoption-demo")

        print("=== module revocation-demo outside the checkout ===")
        module_revocation = run([venv_python, "-m", "work_runtime", "revocation-demo"],
                                outside, show=True)
        require_revocation_proof(module_revocation.stdout, "module revocation-demo")
        print("independent check: revoked statuses, preserved fingerprints, "
              "business keys and one retained effect per store re-verified "
              "from the three scenario databases")

        print("=== console revocation-demo outside the checkout ===")
        console_revocation = run([console, "revocation-demo"], outside, show=True)
        require_revocation_proof(console_revocation.stdout, "console revocation-demo")

        print("=== module compensation-demo outside the checkout ===")
        module_compensation = run([venv_python, "-m", "work_runtime",
                                   "compensation-demo"], outside, show=True)
        require_compensation_proof(module_compensation.stdout,
                                   "module compensation-demo")
        run_printed_inspect_command(module_compensation.stdout, venv_python, outside,
                                    "module compensation-demo",
                                    outcome_marker='"outcome": "cancelled"')
        print("independent check: business keys, link binding, receipts/"
              "withdrawal rows, withdrawn-kind proof, E08 truth and closure "
              "re-verified from the two scenario databases")

        print("=== console compensation-demo outside the checkout ===")
        console_compensation = run([console, "compensation-demo"], outside, show=True)
        require_compensation_proof(console_compensation.stdout,
                                   "console compensation-demo")

        print("=== module rotation-demo outside the checkout ===")
        module_rotation = run([venv_python, "-m", "work_runtime", "rotation-demo"],
                              outside, show=True)
        require_rotation_proof(module_rotation.stdout, "module rotation-demo")
        run_printed_inspect_command(module_rotation.stdout, venv_python, outside,
                                    "module rotation-demo",
                                    outcome_marker='"status": "active"')
        print("independent check: recomputed six-table digest, verified evidence "
              "statuses/fingerprints, the original cached receipt and one command "
              "row per rotation command id re-verified from the rotation store")

        print("=== console rotation-demo outside the checkout ===")
        console_rotation = run([console, "rotation-demo"], outside, show=True)
        require_rotation_proof(console_rotation.stdout, "console rotation-demo")

        print("=== module publication-demo outside the checkout ===")
        module_publication = run([venv_python, "-m", "work_runtime",
                                  "publication-demo"], outside, show=True)
        require_publication_proof(module_publication.stdout,
                                  "module publication-demo")
        run_printed_inspect_command(module_publication.stdout, venv_python,
                                    outside, "module publication-demo")
        print("independent check: two hash-named artifacts parsed with the "
              "standard library (bare packaged card plus the closed "
              "withdrawal record, recomputed digests and digest-based keys, "
              "accepted FILE- receipts), the runtime store re-verified "
              "(closed/succeeded publication and withdrawal works, two "
              "confirmed operations with runtime-written accepted proofs, "
              "both D66 conflict receipts, distinguishable loader failures "
              "incl. the withdrawn error)")

        print("=== console publication-demo outside the checkout ===")
        console_publication = run([console, "publication-demo"], outside, show=True)
        require_publication_proof(console_publication.stdout,
                                  "console publication-demo")

        print("=== packaged web assets ship with the install ===")
        for name in ("index.html", "app.js", "app.css"):
            require((package_dir / "web" / name).is_file(),
                    "the install ships no packaged web asset %s" % name)
        print("web assets: index.html, app.js, app.css")

        print("=== installed UI (module and console) over real HTTP ===")
        ui_skip = run_ui_stages(venv_python, console, outside, workspace, package_dir)

        print("=== PASS ===")
        print("fresh venv install; import origin inside the venv; no third-party runtime "
              "dependencies; module and console demos outside the checkout with exactly "
              "one external application, one published artifact, one accepted "
              "application per intervention store and one independently parsed "
              "committed file artifact per adoption entry point; module and console "
              "revocation-demo stores re-verified (revoked statuses, preserved "
              "fingerprints, stable business keys, one retained effect per store); "
              "module and console compensation-demo stores re-verified (recomputed "
              "business keys, immutable link and adapter-result binding, tagged "
              "receipts and one withdrawal row, withdrawn-kind proof with retained "
              "E08 truth, exact two-id ack, refusal-not-reversal); module and console "
              "rotation-demo stores re-verified (recomputed six-table digest, "
              "verified evidence fingerprints, original cached receipt, one "
              "command row per rotation command id); module and console "
              "publication-demo stores re-verified (recomputed bare-card "
              "artifact digest and digest-based publication key, the closed "
              "withdrawal record binding the published digest, two "
              "confirmed operations with runtime-written accepted proofs, "
              "both D66 conflict receipts, distinguishable loader failures "
              "incl. the withdrawn error); "
              "packaged web assets "
              "shipped%s (%.1fs)"
              % ("; SKIPPED stages: " + ui_skip if ui_skip else "",
                 time.time() - started))
        return 0
    finally:
        if args.keep:
            print("kept workspace: %s" % workspace)
        else:
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
