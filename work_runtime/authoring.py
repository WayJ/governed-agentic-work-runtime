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
RULE_FIELDS = ("id", "source", "modality", "type", "scope", "trigger",
               "depends_on", "requirement", "deadline", "evidence",
               "unknown", "conflict", "exemption", "migration")
EVIDENCE_FIELDS = ("kind", "source", "subject", "version")
RULE_HANDLING = {"unknown": "block", "conflict": "escalate",
                 "exemption": "forbidden", "migration": "explicit"}
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



def _require_enum(container: Dict[str, Any], base: str, field: str,
                  allowed: tuple, message: str,
                  found: List[Dict[str, str]]) -> None:
    value = container[field]
    path = base + "/" + field
    if type(value) is not str:
        found.append(_diag(TYPE_MISMATCH, path, "field must be a string"))
    elif value not in allowed:
        found.append(_diag(INVALID_VALUE, path, message))


def _require_pinned(container: Dict[str, Any], base: str, field: str,
                    expected: str, found: List[Dict[str, str]]) -> None:
    value = container[field]
    path = base + "/" + field
    if type(value) is not str:
        found.append(_diag(TYPE_MISMATCH, path, "field must be a string"))
    elif value != expected:
        found.append(_diag(INVALID_VALUE, path, "value must be '%s'" % expected))


def _lint_rules(rules: Any, found: List[Dict[str, str]]) -> None:
    _lint_id_list(rules, "/rules", found)
    if type(rules) is not list:
        return
    mandatory = False
    for index, rule in enumerate(rules):
        if type(rule) is not dict:
            continue
        base = "/rules/%d" % index
        _check_exact_fields(rule, base, RULE_FIELDS, found)
        for field in ("id", "scope", "trigger", "requirement", "deadline"):
            if field in rule:
                _require_text(rule, base, field, found)
        if "source" in rule:
            _check_source(rule, base, found)
        if "modality" in rule:
            _require_enum(rule, base, "modality", ("must", "forbidden"),
                          "value must be 'must' or 'forbidden'", found)
            if rule["modality"] in ("must", "forbidden"):
                mandatory = True
        if "type" in rule:
            _require_enum(rule, base, "type", ("state", "action", "history"),
                          "value must be 'state', 'action' or 'history'", found)
        if "depends_on" in rule:
            _lint_depends_on_shape(rule["depends_on"], base, found)
        if "evidence" in rule:
            _lint_evidence(rule["evidence"], base, found)
        for field, expected in RULE_HANDLING.items():
            if field in rule:
                _require_pinned(rule, base, field, expected, found)
    if not mandatory:
        found.append(_diag(NO_MANDATORY_RULE, "/rules",
                           "package has no mandatory (must or forbidden) rule"))


def _lint_depends_on_shape(depends_on: Any, base: str,
                           found: List[Dict[str, str]]) -> None:
    if type(depends_on) is not list:
        found.append(_diag(TYPE_MISMATCH, base + "/depends_on",
                           "field must be a list"))
        return
    for index, entry in enumerate(depends_on):
        path = base + "/depends_on/%d" % index
        if type(entry) is not str:
            found.append(_diag(TYPE_MISMATCH, path, "field must be a string"))
        elif entry.strip() == "":
            found.append(_diag(EMPTY_VALUE, path, "string is empty or whitespace-only"))


def _lint_evidence(evidence: Any, base: str,
                   found: List[Dict[str, str]]) -> None:
    path = base + "/evidence"
    if type(evidence) is not dict:
        found.append(_diag(TYPE_MISMATCH, path, "value must be an object"))
        return
    _check_exact_fields(evidence, path, EVIDENCE_FIELDS, found)
    for field in EVIDENCE_FIELDS:
        if field in evidence:
            _require_text(evidence, path, field, found)


def _lint_advice(advice: Any, found: List[Dict[str, str]]) -> None:
    if type(advice) is not list:
        found.append(_diag(TYPE_MISMATCH, "/advice", "field must be a list"))
        return
    for index, entry in enumerate(advice):
        path = "/advice/%d" % index
        if type(entry) is not str:
            found.append(_diag(TYPE_MISMATCH, path, "field must be a string"))
        elif entry.strip() == "":
            found.append(_diag(EMPTY_VALUE, path, "string is empty or whitespace-only"))



def _declared_collection_ids(root: Dict[str, Any]):
    """Declared collection IDs, or None when the list itself is malformed."""
    items = root.get("collections")
    if type(items) is not list:
        return None
    declared = set()
    for item in items:
        if type(item) is dict:
            identifier = item.get("id")
            if type(identifier) is str and identifier.strip() != "":
                declared.add(identifier)
    return declared


def _declared_capability_ids(root: Dict[str, Any]):
    policy = root.get("policy")
    if type(policy) is not dict:
        return None
    capabilities = policy.get("capabilities")
    if type(capabilities) is not list:
        return None
    return {capability for capability in capabilities
            if type(capability) is str and capability.strip() != ""}


def _declared_reference_ids(root: Dict[str, Any]):
    """All fact/collection/rule IDs, or None when any list is malformed."""
    declared = set()
    for section in ID_LISTS:
        items = root.get(section)
        if type(items) is not list:
            return None
        for item in items:
            if type(item) is dict:
                identifier = item.get("id")
                if type(identifier) is str and identifier.strip() != "":
                    declared.add(identifier)
    return declared


def _check_scope(scope: Any, path: str, collection_ids,
                 found: List[Dict[str, str]]) -> None:
    if collection_ids is None or type(scope) is not str or scope.strip() == "":
        return
    if scope != "document" and scope not in collection_ids:
        found.append(_diag(UNKNOWN_REFERENCE, path,
                           "scope '%s' is not the literal 'document' or a "
                           "declared collection" % _snippet(scope)))


def _check_references(root: Dict[str, Any],
                      found: List[Dict[str, str]]) -> None:
    """Reference layer: runs against declared IDs collected from navigable lists."""
    collection_ids = _declared_collection_ids(root)
    capability_ids = _declared_capability_ids(root)
    reference_ids = _declared_reference_ids(root)
    policy = root.get("policy")
    if type(policy) is dict:
        _check_scope(policy.get("scope"), "/policy/scope", collection_ids, found)
    rules = root.get("rules")
    if type(rules) is not list:
        return
    for index, rule in enumerate(rules):
        if type(rule) is not dict:
            continue
        base = "/rules/%d" % index
        _check_scope(rule.get("scope"), base + "/scope", collection_ids, found)
        deadline = rule.get("deadline")
        if (capability_ids is not None and type(deadline) is str
                and deadline.strip() != ""):
            if deadline != "goal" and deadline not in capability_ids:
                found.append(_diag(UNKNOWN_REFERENCE, base + "/deadline",
                                   "deadline '%s' is not the literal 'goal' or "
                                   "a declared capability" % _snippet(deadline)))
        depends_on = rule.get("depends_on")
        if reference_ids is None or type(depends_on) is not list:
            continue
        seen = set()
        for position, entry in enumerate(depends_on):
            if type(entry) is not str or entry.strip() == "":
                continue
            path = base + "/depends_on/%d" % position
            if entry not in reference_ids:
                found.append(_diag(UNKNOWN_REFERENCE, path,
                                   "reference '%s' is not a declared fact, "
                                   "collection or rule" % _snippet(entry)))
            if entry in seen:
                found.append(_diag(DUPLICATE_ID, path,
                                   "duplicate reference '%s'" % _snippet(entry)))
            seen.add(entry)


def _cyclic_components(graph: Dict[int, List[int]]) -> List[List[int]]:
    """Iterative Tarjan SCC; the rule graph is not bounded by the JSON depth.

    Flat dependency graphs can be arbitrarily large, so this never recurses
    and never enumerates simple cycles — one component per diagnostic.
    """
    counter = 0
    indices = {}
    lowlink = {}
    on_stack = set()
    stack = []
    components = []
    for start in sorted(graph):
        if start in indices:
            continue
        work = [(start, 0)]
        while work:
            node, position = work[-1]
            if position == 0:
                indices[node] = lowlink[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            descended = False
            children = graph[node]
            while position < len(children):
                child = children[position]
                position += 1
                if child not in indices:
                    work[-1] = (node, position)
                    work.append((child, 0))
                    descended = True
                    break
                if child in on_stack and indices[child] < lowlink[node]:
                    lowlink[node] = indices[child]
            if descended:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                if lowlink[node] < lowlink[parent]:
                    lowlink[parent] = lowlink[node]
            if lowlink[node] == indices[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(component)
    return [component for component in components
            if len(component) > 1 or component[0] in graph[component[0]]]


def _check_rule_cycles(root: Dict[str, Any],
                       found: List[Dict[str, str]]) -> None:
    rules = root.get("rules")
    if type(rules) is not list:
        return
    nodes = []
    first_index = {}
    for index, rule in enumerate(rules):
        if type(rule) is not dict:
            continue
        identifier = rule.get("id")
        depends_on = rule.get("depends_on")
        if (type(identifier) is str and identifier.strip() != ""
                and type(depends_on) is list):
            nodes.append((index, identifier))
            first_index.setdefault(identifier, index)
    graph = {}
    ids = dict(nodes)
    for index, identifier in nodes:
        edges = set()
        for entry in rules[index]["depends_on"]:
            if type(entry) is str and entry in first_index:
                edges.add(first_index[entry])
        graph[index] = sorted(edges)
    for component in _cyclic_components(graph):
        lowest = min(component)
        message = "rule dependency cycle component: '%s'" % _snippet(ids[lowest])
        if len(component) > 1:
            message += " (+%d more members)" % (len(component) - 1)
        found.append(_diag(CYCLE, "/rules/%d" % lowest, message))


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
    if "rules" in root:
        _lint_rules(root["rules"], found)
    if "advice" in root:
        _lint_advice(root["advice"], found)
    _collect_global_ids(root, found)
    _check_references(root, found)
    _check_rule_cycles(root, found)
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
