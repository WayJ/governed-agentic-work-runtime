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
15. Assert the packaged GUI web assets ship inside the (non-editable)
    install — `work_runtime/web/{index.html,app.js,app.css}` resolve inside
    the venv — so the read-only viewer is never served from this checkout.
16. Installed UI (module AND console): when the read-only backend
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


def run_printed_inspect_command(stdout, venv_python, outside, source):
    """Re-run the demo's printed inspect command verbatim (python3 swapped)."""
    command = INSPECT_COMMAND.search(stdout)
    require(command is not None, "%s printed no inspect command" % source)
    words = shlex.split(command.group(1))
    require(words[0] == "python3", "%s inspect command is not python3-based" % source)
    words[0] = str(venv_python)
    result = run(words, outside)
    require('"outcome": "succeeded"' in result.stdout,
            "%s installed inspect did not report the succeeded work" % source)


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
