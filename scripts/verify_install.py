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

Usage: python3 scripts/verify_install.py [--python INTERP] [--repo PATH] [--keep]
"""

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_FINAL_LINE = "external applications created: 1"
PUBLISH_FINAL_LINE = "published artifacts: 1"
INTERVENTION_FINAL_LINE = "accepted applications: 3 (one per store)"
ADOPTION_FINAL_LINE = "committed file artifacts: 1"
PINNED_PUBLISHING_DIGEST = ("56c85d32da9a9eee6330326e2d14ce0661dbc26d"
                            "782b13d0259c3f149e6be000")
INSPECT_DB = re.compile(r'--db "([^"]+)"')
INSPECT_COMMAND = re.compile(r'^  (python3 -m work_runtime inspect .+)$', re.MULTILINE)
COMMITTED_ARTIFACT = re.compile(r'committed artifact: "([^"]+)"')
HASH_NAMED = re.compile(r"^[0-9a-f]{64}\.json$")
# pkg-resources appears as a virtual entry on some Debian-derived pips.
ALLOWED_PACKAGES = {"pip", "setuptools", "wheel", "pkg-resources", "governed-work-runtime"}


def run(command, cwd, show=False):
    """Run a command; on failure print everything and abort the script."""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
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

        print("=== PASS ===")
        print("fresh venv install; import origin inside the venv; no third-party runtime "
              "dependencies; module and console demos outside the checkout with exactly "
              "one external application, one published artifact, one accepted "
              "application per intervention store and one independently parsed "
              "committed file artifact per adoption entry point (%.1fs)"
              % (time.time() - started))
        return 0
    finally:
        if args.keep:
            print("kept workspace: %s" % workspace)
        else:
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
