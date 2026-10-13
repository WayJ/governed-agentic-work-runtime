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
import sys

from .authoring import lint_sop, sop_digest

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
