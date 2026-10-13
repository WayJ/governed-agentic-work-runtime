"""Static SOP rule-card linting and content digests (S4 authoring foundation).

``lint_sop`` and ``sop_digest`` are pure functions implementing the ratified
D22 authoring contracts: deterministic structural diagnostics for reviewable
rule cards, and a canonical content digest for lint-clean packages. The
linter is static-only — it never executes textual predicates, never verifies
provenance and cannot confer policy authority (see docs/sop-authoring.md).
"""

import math
from typing import Any, Dict, List

MAX_DEPTH = 64
MAX_INTEGER = 2 ** 53 - 1

# The exactly-14 diagnostic codes of D22.
NOT_JSON_NATIVE = "NOT_JSON_NATIVE"
NONFINITE_FLOAT = "NONFINITE_FLOAT"
INVALID_UNICODE = "INVALID_UNICODE"
INTEGER_RANGE = "INTEGER_RANGE"
DEPTH_LIMIT = "DEPTH_LIMIT"
CYCLE = "CYCLE"
MISSING_FIELD = "MISSING_FIELD"
UNKNOWN_FIELD = "UNKNOWN_FIELD"
TYPE_MISMATCH = "TYPE_MISMATCH"
EMPTY_VALUE = "EMPTY_VALUE"
INVALID_VALUE = "INVALID_VALUE"
DUPLICATE_ID = "DUPLICATE_ID"
UNKNOWN_REFERENCE = "UNKNOWN_REFERENCE"
NO_MANDATORY_RULE = "NO_MANDATORY_RULE"

_INPUT_CYCLE_MESSAGE = "input object contains a reference cycle"


def _diag(code: str, path: str, message: str) -> Dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _escape(token: str) -> str:
    """RFC 6901 pointer token escaping: ~ then /."""
    return token.replace("~", "~0").replace("/", "~1")


def _preflight(root: Any) -> List[Dict[str, str]]:
    """Iteratively validate JSON-native structure; never raises.

    Exact types only (subclasses are not coerced), depth <= MAX_DEPTH,
    finite floats, UTF-8-encodable strings and keys, integers within
    +/- MAX_INTEGER, and active-path identity cycle detection. Repeated
    acyclic aliases stay valid. Non-native values are reported without
    invoking any of their methods.
    """
    found: List[Dict[str, str]] = []
    enter, exit_ = 0, 1
    stack = [(enter, root, "", 0)]
    active = set()  # ids of containers on the current traversal path
    while stack:
        event, node, path, depth = stack.pop()
        if event == exit_:
            active.remove(id(node))
            continue
        if depth > MAX_DEPTH:
            found.append(_diag(DEPTH_LIMIT, path,
                               "value is nested deeper than 64 levels"))
            continue
        kind = type(node)
        if kind is dict or kind is list:
            if id(node) in active:
                found.append(_diag(CYCLE, path, _INPUT_CYCLE_MESSAGE))
                continue
            children = []
            if kind is dict:
                bad_key = bad_unicode = False
                for key in node:
                    if type(key) is not str:
                        bad_key = True
                        continue
                    try:
                        key.encode("utf-8")
                    except UnicodeEncodeError:
                        bad_unicode = True
                        continue
                    children.append((key, node[key]))
                if bad_key:
                    found.append(_diag(NOT_JSON_NATIVE, path,
                                       "object key is not a string"))
                if bad_unicode:
                    found.append(_diag(INVALID_UNICODE, path,
                                       "object key is not UTF-8 encodable"))
            else:
                children = [(str(index), node[index]) for index in range(len(node))]
            if children:
                active.add(id(node))
                stack.append((exit_, node, path, depth))
                for token, child in reversed(children):
                    stack.append((enter, child, path + "/" + _escape(token), depth + 1))
        elif kind is str:
            try:
                node.encode("utf-8")
            except UnicodeEncodeError:
                found.append(_diag(INVALID_UNICODE, path,
                                   "string is not UTF-8 encodable"))
        elif kind is float:
            if not math.isfinite(node):
                found.append(_diag(NONFINITE_FLOAT, path, "float is not finite"))
        elif kind is int:
            if node > MAX_INTEGER or node < -MAX_INTEGER:
                found.append(_diag(INTEGER_RANGE, path,
                                   "integer is outside the interoperable 2^53-1 range"))
        elif kind is bool or node is None:
            pass
        else:
            found.append(_diag(NOT_JSON_NATIVE, path,
                               "value is not a JSON-native type"))
    return found


def _finalize(diagnostics: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Sort by (path, code, message) and drop identical triples."""
    triples = {(d["path"], d["code"], d["message"]) for d in diagnostics}
    return [{"code": code, "path": path, "message": message}
            for path, code, message in sorted(triples)]


def lint_sop(value: Any) -> List[Dict[str, str]]:
    """Return deterministic ``{code, path, message}`` diagnostics for a value.

    A pure function: it never raises, never mutates its input, never
    evaluates textual predicates and never touches the filesystem or the
    runtime. JSON-native preflight findings suppress the schema layer.
    """
    return _finalize(_preflight(value))
