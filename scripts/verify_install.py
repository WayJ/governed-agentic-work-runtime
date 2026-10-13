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
7. Run the `work-runtime demo` console entry point outside the checkout and
   assert the same printed result.

Usage: python3 scripts/verify_install.py [--python INTERP] [--repo PATH] [--keep]
"""

import argparse
import json
import os
import re
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
INSPECT_DB = re.compile(r'--db "([^"]+)"')
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

        print("=== console demo outside the checkout ===")
        console_demo = run([console, "demo"], outside, show=True)
        require(DEMO_FINAL_LINE in console_demo.stdout,
                "console demo output lacks %r" % DEMO_FINAL_LINE)

        print("=== PASS ===")
        print("fresh venv install; import origin inside the venv; no third-party runtime "
              "dependencies; module and console demos outside the checkout with exactly "
              "one external application and one published artifact (%.1fs)"
              % (time.time() - started))
        return 0
    finally:
        if args.keep:
            print("kept workspace: %s" % workspace)
        else:
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
