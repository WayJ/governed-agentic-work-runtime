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

ROOT_FIELDS = ("schema_version", "policy", "defaults", "facts",
               "collections", "rules", "advice")
POLICY_FIELDS = ("id", "version", "goal", "source", "scope", "capabilities")
SOURCE_FIELDS = ("document", "version", "section")
DEFAULTS_VALUES = {"unknown": "block", "conflict": "escalate",
                   "exemptions": "forbidden", "migration": "explicit"}
COLLECTION_FIELDS = ("id", "version", "completeness", "allow_empty")
ID_LISTS = ("facts", "collections", "rules")


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



def _check_exact_fields(container: Dict[str, Any], path: str, fields,
                        found: List[Dict[str, str]]) -> None:
    """MISSING_FIELD at the container, UNKNOWN_FIELD at the offending key."""
    for name in fields:
        if name not in container:
            found.append(_diag(MISSING_FIELD, path,
                               "missing required field '%s'" % name))
    for key in container:
        if key not in fields:
            found.append(_diag(UNKNOWN_FIELD, path + "/" + _escape(key),
                               "unknown field '%s'" % _snippet(key)))


def _snippet(text: str) -> str:
    """Identifier/enum snippet bounded to 64 characters, never trimmed."""
    return text if len(text) <= 64 else text[:64]


def _require_text(container: Dict[str, Any], base: str, field: str,
                  found: List[Dict[str, str]]) -> None:
    value = container[field]
    path = base + "/" + field
    if type(value) is not str:
        found.append(_diag(TYPE_MISMATCH, path, "field must be a string"))
    elif value.strip() == "":
        found.append(_diag(EMPTY_VALUE, path, "string is empty or whitespace-only"))


def _check_source(container: Dict[str, Any], base: str,
                  found: List[Dict[str, str]]) -> None:
    source = container["source"]
    path = base + "/source"
    if type(source) is not dict:
        found.append(_diag(TYPE_MISMATCH, path, "value must be an object"))
        return
    _check_exact_fields(source, path, SOURCE_FIELDS, found)
    for field in SOURCE_FIELDS:
        if field in source:
            _require_text(source, path, field, found)


def _lint_policy(policy: Any, found: List[Dict[str, str]]) -> None:
    if type(policy) is not dict:
        found.append(_diag(TYPE_MISMATCH, "/policy", "value must be an object"))
        return
    _check_exact_fields(policy, "/policy", POLICY_FIELDS, found)
    for field in ("id", "version", "goal"):
        if field in policy:
            _require_text(policy, "/policy", field, found)
    if "source" in policy:
        _check_source(policy, "/policy", found)
    if "scope" in policy:
        _require_text(policy, "/policy", "scope", found)
    if "capabilities" in policy:
        _check_capabilities(policy["capabilities"], found)


def _check_capabilities(capabilities: Any,
                        found: List[Dict[str, str]]) -> None:
    if type(capabilities) is not list:
        found.append(_diag(TYPE_MISMATCH, "/policy/capabilities", "field must be a list"))
        return
    seen = set()
    for index, capability in enumerate(capabilities):
        path = "/policy/capabilities/%d" % index
        if type(capability) is not str:
            found.append(_diag(TYPE_MISMATCH, path, "field must be a string"))
            continue
        if capability.strip() == "":
            found.append(_diag(EMPTY_VALUE, path, "string is empty or whitespace-only"))
            continue
        if capability == "goal":
            found.append(_diag(INVALID_VALUE, path,
                               "capability 'goal' is reserved as the "
                               "goal-boundary deadline token"))
        if capability in seen:
            found.append(_diag(DUPLICATE_ID, path,
                               "duplicate capability '%s'" % _snippet(capability)))
        seen.add(capability)


def _lint_defaults(defaults: Any, found: List[Dict[str, str]]) -> None:
    if type(defaults) is not dict:
        found.append(_diag(TYPE_MISMATCH, "/defaults", "value must be an object"))
        return
    _check_exact_fields(defaults, "/defaults", tuple(DEFAULTS_VALUES), found)
    for field, expected in DEFAULTS_VALUES.items():
        if field not in defaults:
            continue
        value = defaults[field]
        path = "/defaults/" + field
        if type(value) is not str:
            found.append(_diag(TYPE_MISMATCH, path, "field must be a string"))
        elif value != expected:
            found.append(_diag(INVALID_VALUE, path, "value must be '%s'" % expected))



def _lint_id_list(items: Any, base: str, found: List[Dict[str, str]]) -> None:
    """Shared list-of-objects shape check for facts/collections/rules lists."""
    if type(items) is not list:
        found.append(_diag(TYPE_MISMATCH, base, "field must be a list"))
        return
    for index, item in enumerate(items):
        if type(item) is not dict:
            found.append(_diag(TYPE_MISMATCH, "%s/%d" % (base, index),
                               "value must be an object"))


def _lint_facts(facts: Any, found: List[Dict[str, str]]) -> None:
    _lint_id_list(facts, "/facts", found)
    if type(facts) is not list:
        return
    for index, fact in enumerate(facts):
        if type(fact) is not dict:
            continue
        base = "/facts/%d" % index
        _check_exact_fields(fact, base, ("id",), found)
        if "id" in fact:
            _require_text(fact, base, "id", found)


def _lint_collections(collections: Any, found: List[Dict[str, str]]) -> None:
    _lint_id_list(collections, "/collections", found)
    if type(collections) is not list:
        return
    for index, collection in enumerate(collections):
        if type(collection) is not dict:
            continue
        base = "/collections/%d" % index
        _check_exact_fields(collection, base, COLLECTION_FIELDS, found)
        for field in ("id", "version", "completeness"):
            if field in collection:
                _require_text(collection, base, field, found)
        if "allow_empty" in collection and type(collection["allow_empty"]) is not bool:
            found.append(_diag(TYPE_MISMATCH, base + "/allow_empty",
                               "field must be a boolean"))
        if type(collection.get("id")) is str and collection["id"] == "document":
            found.append(_diag(INVALID_VALUE, base + "/id",
                               "collection id 'document' is reserved as the "
                               "business-document scope token"))


def _collect_global_ids(root: Dict[str, Any],
                        found: List[Dict[str, str]]) -> None:
    """DUPLICATE_ID for any ID reused across the fact/collection/rule namespace.

    Document order is facts, then collections, then rules; a reused ID is
    reported at each later occurrence. Only well-formed nonempty string IDs
    participate.
    """
    seen = {}
    for section in ID_LISTS:
        items = root.get(section)
        if type(items) is not list:
            continue
        for index, item in enumerate(items):
            if type(item) is not dict:
                continue
            identifier = item.get("id")
            if type(identifier) is not str or identifier.strip() == "":
                continue
            path = "/%s/%d/id" % (section, index)
            if identifier in seen:
                found.append(_diag(DUPLICATE_ID, path,
                                   "duplicate ID '%s'" % _snippet(identifier)))
            else:
                seen[identifier] = path


def _lint_schema(root: Any) -> List[Dict[str, str]]:
    """Strict schema layer; runs only after a clean JSON-native preflight."""
    found: List[Dict[str, str]] = []
    if type(root) is not dict:
        found.append(_diag(TYPE_MISMATCH, "", "value must be an object"))
        return found
    _check_exact_fields(root, "", ROOT_FIELDS, found)
    if "schema_version" in root:
        version = root["schema_version"]
        if type(version) is not int:
            found.append(_diag(TYPE_MISMATCH, "/schema_version",
                               "field must be an integer"))
        elif version != 1:
            found.append(_diag(INVALID_VALUE, "/schema_version",
                               "schema_version must be 1"))
    if "policy" in root:
        _lint_policy(root["policy"], found)
    if "defaults" in root:
        _lint_defaults(root["defaults"], found)
    if "facts" in root:
        _lint_facts(root["facts"], found)
    if "collections" in root:
        _lint_collections(root["collections"], found)
    _collect_global_ids(root, found)
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
    found = _preflight(value)
    if not found:
        found = _lint_schema(value)
    return _finalize(found)
