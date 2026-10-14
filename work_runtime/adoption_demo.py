"""S4 adoption harness: strict SOP file loading and the file-adapter demo.

Two surfaces live here. The strict loader and :func:`packaged_card` back the
``lint-sop`` CLI: file-level failures (unreadable, oversized, invalid UTF-8,
malformed JSON, duplicate object keys, non-finite literals, unparseably deep
nesting) are bounded exit-2 errors that never echo file contents, while a
syntactically valid escaped surrogate stays loader-clean and surfaces as a
linter ``INVALID_UNICODE`` diagnostic (exit 1). Linting is static structural
review only: it never executes textual predicates and confers no publication
or policy authority (see docs/sop-authoring.md and docs/contributor-guide.md).

The demonstration part drives the unchanged Runtime/PublishingPolicy with
HMAC-signed reviewer/author evidence and the real ``FilePublisher`` adapter.
Fresh temporary stores per run; no credentials, no network, no user data
deleted. The filesystem directory is trusted local configuration — no
hostile-filesystem, power-loss or distributed exactly-once claims.
"""

import importlib.resources
import json
import re
import secrets
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path

from .authoring import lint_sop, sop_digest
from .file_adapter import FilePublisher
from .ingress import SignedEvidenceGateway, sign_evidence
from .publishing import PublishingPolicy
from .publishing_demo import article, publishing_grants
from .runtime import Runtime

MAX_SOP_BYTES = 1024 * 1024  # D22 loader cap: files may be at most 1 MiB.

SCOPE = "static-only"
STATIC_ONLY_NOTE = ("static structural review only - linting never executes "
                    "textual predicates and confers no publication or policy "
                    "authority")

# D22 file-level loader failures (CLI exit 2), each with a bounded static
# message; never the file path, contents or secrets.
FILE_UNREADABLE = "FILE_UNREADABLE"
FILE_TOO_LARGE = "FILE_TOO_LARGE"
INVALID_UTF8 = "INVALID_UTF8"
MALFORMED_JSON = "MALFORMED_JSON"
DUPLICATE_OBJECT_KEY = "DUPLICATE_OBJECT_KEY"
NONFINITE_LITERAL = "NONFINITE_LITERAL"
DEEP_JSON = "DEEP_JSON"

_LOADER_MESSAGES = {
    FILE_UNREADABLE: "file cannot be read",
    FILE_TOO_LARGE: "file exceeds the 1 MiB limit",
    INVALID_UTF8: "file is not valid UTF-8",
    MALFORMED_JSON: "file is not well-formed JSON",
    DUPLICATE_OBJECT_KEY: "JSON object contains a duplicate key",
    NONFINITE_LITERAL: "JSON contains a non-finite number literal",
    DEEP_JSON: "JSON nesting is too deep to parse",
}


class _LoaderFault(Exception):
    """Internal sentinel raised inside json hooks; never escapes."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class SopFileError(Exception):
    """Bounded file-level SOP loading failure.

    ``code`` is one of the module loader codes; the message is fixed static
    text and never echoes input content.
    """

    def __init__(self, code):
        super().__init__(_LOADER_MESSAGES[code])
        self.code = code
        self.message = _LOADER_MESSAGES[code]


def _reject_duplicate_keys(pairs):
    seen = set()
    for key, _value in pairs:
        if key in seen:
            raise _LoaderFault(DUPLICATE_OBJECT_KEY)
        seen.add(key)
    return dict(pairs)


def _reject_constants(token):
    raise _LoaderFault(NONFINITE_LITERAL)


def load_sop_bytes(raw):
    """Parse SOP file bytes under the strict D22 loader rules."""
    if len(raw) > MAX_SOP_BYTES:
        raise SopFileError(FILE_TOO_LARGE)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise SopFileError(INVALID_UTF8) from None
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicate_keys,
                          parse_constant=_reject_constants)
    except _LoaderFault as fault:
        raise SopFileError(fault.code) from None
    except RecursionError:
        raise SopFileError(DEEP_JSON) from None
    except ValueError:
        raise SopFileError(MALFORMED_JSON) from None


def load_sop_file(path):
    """Read ``path`` fully (1 MiB cap applies), then parse it strictly."""
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        raise SopFileError(FILE_UNREADABLE) from None
    return load_sop_bytes(raw)


def packaged_card(name):
    """Load a packaged example card shipped inside the installed package.

    The valid example cards under ``work_runtime/data/sop`` are the single
    source of truth (D22): they are read through ``importlib.resources``, so
    an installed non-editable copy works without the checkout and without a
    duplicate embedded example anywhere.
    """
    resource = importlib.resources.files("work_runtime").joinpath("data", "sop", name)
    try:
        raw = resource.read_bytes()
    except OSError:
        raise SopFileError(FILE_UNREADABLE) from None
    return load_sop_bytes(raw)


def lint_result(value):
    """Exact static-only JSON result envelope for one parsed SOP value."""
    diagnostics = lint_sop(value)
    if diagnostics:
        return {"valid": False, "digest": None, "diagnostics": diagnostics,
                "scope": SCOPE}
    return {"valid": True, "digest": sop_digest(value), "diagnostics": [],
            "scope": SCOPE}


def _safe_text(text):
    """Make any diagnostic line printable on a strict UTF-8 stdout.

    Lone surrogates in paths or messages (possible only through future
    linter changes today, possible in principle always) are backslash-
    escaped instead of crashing the print.
    """
    return text.encode("utf-8", "backslashreplace").decode("utf-8")


def _print_result(result):
    # ensure_ascii keeps the envelope pure ASCII, so no diagnostic content
    # can ever crash stdout on encode.
    print(json.dumps(result, ensure_ascii=True, indent=2))


def run_lint_sop(path, as_json=False):
    """CLI body of ``lint-sop <path> [--json]``; returns the exit code.

    Exit 0 lint-clean, 1 lint diagnostics, 2 file-level failure (D22).
    """
    try:
        value = load_sop_file(path)
    except SopFileError as error:
        if as_json:
            _print_result({"valid": False, "digest": None,
                           "diagnostics": [{"code": error.code, "path": "",
                                            "message": error.message}],
                           "scope": SCOPE})
        else:
            print("lint-sop: cannot load file: %s: %s"
                  % (error.code, error.message), file=sys.stderr)
        return 2
    result = lint_result(value)
    if as_json:
        _print_result(result)
        return 0 if result["valid"] else 1
    if result["valid"]:
        print("SOP is lint-clean.")
        print("digest: %s" % result["digest"])
        print("Lint is %s." % STATIC_ONLY_NOTE)
        return 0
    for diagnostic in result["diagnostics"]:
        print(_safe_text("%s %s %s" % (diagnostic["code"],
                                       diagnostic["path"] or "<root>",
                                       diagnostic["message"])))
    print("%d lint diagnostic(s); lint is %s."
          % (len(result["diagnostics"]), STATIC_ONLY_NOTE))
    return 1


DEMO_NOW = 2000000000  # Fixed clock keeps runs deterministic.

# An intentionally invalid demonstration card (NOT a copy of any packaged
# example): a whitespace-only goal, an unknown root field and an undeclared
# deadline capability give the prologue bounded, deterministic diagnostics.
INVALID_CARD = {
    "schema_version": 1,
    "policy": {"id": "adoption-demo", "version": "1", "goal": "  ",
               "source": {"document": "doc", "version": "1", "section": "1"},
               "scope": "document", "capabilities": ["demo.run"]},
    "defaults": {"unknown": "block", "conflict": "escalate",
                 "exemptions": "forbidden", "migration": "explicit"},
    "facts": [], "collections": [],
    "rules": [{
        "id": "R1",
        "source": {"document": "doc", "version": "1", "section": "1.1"},
        "modality": "must", "type": "state", "scope": "document",
        "trigger": "before demo.run", "depends_on": [],
        "requirement": "The demo must be ready", "deadline": "demo.missing",
        "evidence": {"kind": "check", "source": "checker", "subject": "document",
                     "version": "digest"},
        "unknown": "block", "conflict": "escalate", "exemption": "forbidden",
        "migration": "explicit",
    }],
    "advice": [],
    "reviewers": [],
}


class ResponseLossPublisher:
    """Composition wrapper: the real FilePublisher commits, then the response is lost.

    The wrapper holds a real :class:`~work_runtime.file_adapter.FilePublisher`
    and never stubs or edits it: ``execute`` delegates the durable commit and
    then raises ``TimeoutError`` exactly where an external service would lose
    its response AFTER the side effect. ``lookup`` delegates unchanged, so a
    restart reconciles the original key against the real committed artifact.
    """

    def __init__(self, publisher):
        self._publisher = publisher
        # Surface the delegate's declared contract so the Runtime capability
        # preflight still applies (composition, not a bypass).
        self.contract = publisher.contract

    def execute(self, key, document, content_digest):
        self._publisher.execute(key, document, content_digest)
        raise TimeoutError("response lost after the real file commit")

    def lookup(self, key):
        return self._publisher.lookup(key)


def _committed_artifacts(directory):
    """Sorted hash-named committed artifact files under ``directory``."""
    return sorted(path for path in Path(directory).iterdir()
                  if re.fullmatch(r"[0-9a-f]{64}\.json", path.name))


def _evidence_rows(path):
    db = sqlite3.connect(str(path))
    try:
        return db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
    finally:
        db.close()


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


def run_adoption_demo(directory=None):
    """Lint the packaged rule cards, then adopt the file adapter end to end.

    Fresh temporary stores per run; no credentials, no network, nothing
    deleted. The static prologue never executes linted JSON; the live part
    drives the unchanged Runtime/PublishingPolicy with HMAC-signed
    reviewer/author candidates and commits exactly one real hash-named
    artifact through ``FilePublisher``, losing the response after the commit
    and recovering it by reconciling the original business key after a
    restart.
    """
    folder = Path(tempfile.mkdtemp(prefix="governed-adoption-", dir=directory))
    runtime_path = folder / "runtime.sqlite"
    policy = PublishingPolicy()
    work_id = "article-1"
    runtime = Runtime(str(runtime_path), policy, publishing_grants())

    invalid = lint_result(INVALID_CARD)
    assert invalid["valid"] is False and invalid["diagnostics"]
    first = invalid["diagnostics"][0]
    print("Static SOP review (lint-sop; never executed by the Runtime):", flush=True)
    print("1. Invalid demo card -> %d diagnostics, first %s at %s (lint-sop exit 1)"
          % (len(invalid["diagnostics"]), first["code"], first["path"] or "<root>"),
          flush=True)
    cards = []
    for name in ("expense.json", "publishing.json"):
        result = lint_result(packaged_card(name))
        assert result["valid"] is True
        cards.append((name, result["digest"]))
    print("2. Packaged cards lint-clean with exact content digests (lint-sop exit 0):",
          flush=True)
    for name, card_digest in cards:
        print("     %-15s %s" % (name, card_digest), flush=True)
    print("   Lint is %s; the live part below executes the engineered" % STATIC_ONLY_NOTE)
    print("   PublishingPolicy - the linted JSON is not executed by the Runtime.",
          flush=True)

    print("Live adoption on the unchanged Runtime with the third adapter:", flush=True)
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
    print("3. Agent proposes publication -> BLOCKED by C02 (reviewer approval missing)",
          flush=True)

    tampered = signed("reviewer", reviewer_key, "approval",
                      runtime.get_work(work_id)["document_digest"])
    tampered["data"]["digest"] = "0" * 64
    intake_before = _evidence_rows(runtime_path)
    rejection = gateway.record(tampered)
    assert rejection == {"decision": "rejected", "code": "EVIDENCE_AUTHENTICATION_FAILED"}
    assert _evidence_rows(runtime_path) == intake_before
    print("4. Tampered reviewer approval -> rejected EVIDENCE_AUTHENTICATION_FAILED "
          "before any intake write", flush=True)

    current = runtime.get_work(work_id)["document_digest"]
    for source, secret, kind in (("reviewer", reviewer_key, "approval"),
                                 ("author", author_key, "confirmation")):
        receipt = gateway.record(signed(source, secret, kind, current))
        assert receipt["decision"] == "accepted"
        assert receipt["evidence_status"] == "pending_verification"
    runtime.verify_pending(work_id)
    intent = _propose(runtime, work_id, command_id="publish-once")
    assert intent["decision"] == "accepted"
    print("5. Valid signed approval/confirmation stay candidates until verified "
          "-> intent accepted", flush=True)

    publisher = FilePublisher(str(folder / "publisher"))
    unknown = runtime.dispatch(intent["operation_id"], ResponseLossPublisher(publisher))
    assert unknown["status"] == "outcome_unknown"
    artifacts = _committed_artifacts(folder / "publisher")
    assert len(artifacts) == 1
    print("6. FilePublisher commits a real hash-named artifact; response lost AFTER "
          "the commit -> outcome unknown", flush=True)

    restarted = Runtime(str(runtime_path), policy, publishing_grants())
    recovered = restarted.reconcile(intent["operation_id"],
                                    FilePublisher(str(folder / "publisher")))
    assert recovered["status"] == "confirmed_succeeded"
    assert len(restarted.get_operation(intent["operation_id"])["attempts"]) == 1
    assert len(_committed_artifacts(folder / "publisher")) == 1
    print("7. Restart -> reconcile the ORIGINAL business key -> confirmed_succeeded, "
          "nothing resent", flush=True)

    completion = _send(restarted, work_id, "request_completion", command_id="complete")
    assert completion["decision"] == "accepted"
    work = restarted.get_work(work_id)
    assert (work["status"], work["outcome"]) == ("closed", "succeeded")
    artifacts = _committed_artifacts(folder / "publisher")
    assert len(artifacts) == 1
    artifact = json.loads(artifacts[0].read_text(encoding="utf-8"))
    operation = restarted.get_operation(intent["operation_id"])
    assert artifact["key"] == operation["business_key"]
    assert artifact["document"] == article()
    print("8. Evidence-backed completion -> SUCCEEDED; committed file artifacts: %d"
          % len(artifacts), flush=True)
    print("\nInspect the durable history and the real artifact:")
    print('  python3 -m work_runtime inspect --db "%s" --work %s --policy content-publish'
          % (runtime_path, work_id))
    print('  committed artifact: "%s"' % artifacts[0])
    return folder
