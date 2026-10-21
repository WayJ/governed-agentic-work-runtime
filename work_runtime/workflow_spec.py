"""Static workflow definition language: lint, digest, predicates and shapes.

Pure module. It touches no store, no clock, no policy and no network. A
workflow definition is *data*: it is linted, digested and bound like a
published rule card, and it never executes. Every construct below is a
closed, bounded language interpreted by fixed code — no user code, no
expression evaluation, no natural-language predicates.

The lint mirrors the authoring discipline of ``work_runtime.authoring``:
deterministic diagnostic codes, bounded static messages that never echo
payload content, and a canonical digest that is stable across key order.
"""

import json
from typing import Any, Callable, Dict, List, Optional, Tuple

from .policy import canonical, digest

# Bounded limits. A definition that exceeds them is rejected at lint time
# rather than becoming an unbounded document.
MAX_NODES = 64
MAX_EDGES = 256
MAX_PREDICATE_DEPTH = 8
MAX_FINDINGS = 32
MAX_ID_LENGTH = 64
MAX_SCHEMA_DEPTH = 8

NODE_KINDS = ("agent", "human", "action", "wait")

_TOP_REQUIRED = ("id", "version", "policy_family", "nodes", "edges")
_TOP_OPTIONAL = ("entry", "terminal", "parameters_schema", "required_checks",
                 "description")

_NODE_REQUIRED = {
    "agent": ("executor", "output", "max_attempts"),
    "human": ("evidence_kind", "subject"),
    "action": ("capability", "subject"),
    "wait": ("match", "deadline_s"),
}
_NODE_OPTIONAL = ("inputs", "checks", "on_reject", "on_failure", "on_timeout",
                  "deadline_s", "max_attempts", "distinct_from", "review",
                  "authority", "description")

_SHAPE_TYPES = ("object", "array", "string", "integer", "number", "boolean", "null")
_COMPARISONS = ("eq", "ne", "gt", "ge", "lt", "le")


def _finding(code: str, path: str, message: str) -> Dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _is_identifier(value: Any) -> bool:
    return (isinstance(value, str) and bool(value) and len(value) <= MAX_ID_LENGTH
            and not any(character.isspace() for character in value))


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and len(value) <= 512


def _is_int(value: Any) -> bool:
    return type(value) is int


# --------------------------------------------------------------------------
# Shape descriptors
# --------------------------------------------------------------------------

def _lint_shape(descriptor: Any, path: str, findings: List[Dict[str, str]],
                depth: int = 0) -> None:
    """Validate one shape descriptor node. Never executes, never coerces."""
    if depth > MAX_SCHEMA_DEPTH:
        findings.append(_finding("SHAPE_TOO_DEEP", path, "Shape descriptor is too deep"))
        return
    if not isinstance(descriptor, dict):
        findings.append(_finding("SHAPE_INVALID", path, "Shape descriptor must be an object"))
        return
    kind = descriptor.get("type")
    if kind not in _SHAPE_TYPES:
        findings.append(_finding("SHAPE_TYPE_UNKNOWN", path + ".type",
                                 "Shape type must be one of the supported kinds"))
        return
    allowed = {
        "object": ("type", "properties", "required", "additionalProperties"),
        "array": ("type", "items", "maxItems", "minItems"),
        "string": ("type", "minLength", "maxLength", "enum"),
        "integer": ("type", "minimum", "maximum"),
        "number": ("type", "minimum", "maximum"),
        "boolean": ("type",),
        "null": ("type",),
    }[kind]
    for key in descriptor:
        if key not in allowed:
            findings.append(_finding("SHAPE_FIELD_UNKNOWN", path + "." + str(key),
                                     "Shape descriptor field is not supported"))
    if kind == "object":
        properties = descriptor.get("properties")
        if not isinstance(properties, dict):
            findings.append(_finding("SHAPE_INVALID", path + ".properties",
                                     "Object shape requires a properties object"))
        else:
            for name, sub in properties.items():
                if not _is_identifier(name):
                    findings.append(_finding("SHAPE_INVALID", path + ".properties",
                                             "Property name must be a nonempty identifier"))
                    continue
                _lint_shape(sub, path + ".properties." + name, findings, depth + 1)
        required = descriptor.get("required")
        if required is not None:
            if (not isinstance(required, list)
                    or not all(_is_identifier(name) for name in required)):
                findings.append(_finding("SHAPE_INVALID", path + ".required",
                                         "Required must be a list of property names"))
            elif isinstance(properties, dict):
                for name in required:
                    if name not in properties:
                        findings.append(_finding("SHAPE_INVALID", path + ".required",
                                                 "Required property is not declared"))
        additional = descriptor.get("additionalProperties", False)
        if not isinstance(additional, bool):
            findings.append(_finding("SHAPE_INVALID", path + ".additionalProperties",
                                     "additionalProperties must be a boolean"))
    elif kind == "array":
        if "items" not in descriptor:
            findings.append(_finding("SHAPE_INVALID", path + ".items",
                                     "Array shape requires an items descriptor"))
        else:
            _lint_shape(descriptor["items"], path + ".items", findings, depth + 1)
        for bound in ("maxItems", "minItems"):
            if bound in descriptor and not _is_int(descriptor[bound]):
                findings.append(_finding("SHAPE_INVALID", path + "." + bound,
                                         "Array bounds must be integers"))
    elif kind == "string":
        for bound in ("minLength", "maxLength"):
            if bound in descriptor and not _is_int(descriptor[bound]):
                findings.append(_finding("SHAPE_INVALID", path + "." + bound,
                                         "String bounds must be integers"))
        if "enum" in descriptor:
            enum = descriptor["enum"]
            if (not isinstance(enum, list) or not enum
                    or not all(isinstance(entry, str) for entry in enum)):
                findings.append(_finding("SHAPE_INVALID", path + ".enum",
                                         "Enum must be a nonempty list of strings"))
    elif kind in ("integer", "number"):
        for bound in ("minimum", "maximum"):
            value = descriptor.get(bound)
            if value is not None and (isinstance(value, bool)
                                      or not isinstance(value, (int, float))):
                findings.append(_finding("SHAPE_INVALID", path + "." + bound,
                                         "Numeric bounds must be numbers"))


def _shape_value_matches(descriptor: Dict[str, Any], value: Any) -> bool:
    kind = descriptor.get("type")
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return type(value) is int
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "boolean":
        return type(value) is bool
    if kind == "null":
        return value is None
    return False


def _compare(left: Any, operator: str, right: Any) -> bool:
    if operator == "eq":
        return left == right and type(left) is type(right)
    if operator == "ne":
        return not (left == right and type(left) is type(right))
    if isinstance(left, bool) or isinstance(right, bool):
        return False
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return False
    if operator == "gt":
        return left > right
    if operator == "ge":
        return left >= right
    if operator == "lt":
        return left < right
    if operator == "le":
        return left <= right
    return False


def validate_shape(descriptor: Any, value: Any, path: str = "") -> List[Dict[str, str]]:
    """Validate a value against a closed shape descriptor.

    Returns a bounded list of findings; an empty list means the value matches
    the descriptor. The evaluator never coerces a value and never raises on
    malformed input — a malformed descriptor yields a single finding.
    """
    findings: List[Dict[str, str]] = []

    def walk(node: Dict[str, Any], candidate: Any, where: str, depth: int) -> None:
        if len(findings) >= MAX_FINDINGS or depth > MAX_SCHEMA_DEPTH:
            return
        kind = node.get("type")
        if not _shape_value_matches(node, candidate):
            findings.append(_finding("SHAPE_TYPE", where,
                                     "Value does not match the declared type"))
            return
        if kind == "object":
            properties = node.get("properties") or {}
            required = node.get("required") or []
            for name in required:
                if name not in candidate:
                    findings.append(_finding("SHAPE_MISSING_FIELD", where + "." + name,
                                             "Required field is missing"))
            if node.get("additionalProperties", False) is False:
                for name in candidate:
                    if name not in properties:
                        findings.append(_finding("SHAPE_UNEXPECTED_FIELD", where + "." + name,
                                                 "Field is not declared by the shape"))
            for name, sub in properties.items():
                if name in candidate:
                    walk(sub, candidate[name], where + "." + name, depth + 1)
        elif kind == "array":
            items = node.get("items")
            minimum, maximum = node.get("minItems"), node.get("maxItems")
            if isinstance(minimum, int) and len(candidate) < minimum:
                findings.append(_finding("SHAPE_RANGE", where, "Array is shorter than allowed"))
            if isinstance(maximum, int) and len(candidate) > maximum:
                findings.append(_finding("SHAPE_RANGE", where, "Array is longer than allowed"))
            if isinstance(items, dict):
                for index, entry in enumerate(candidate):
                    walk(items, entry, where + "[" + str(index) + "]", depth + 1)
        elif kind == "string":
            minimum, maximum = node.get("minLength"), node.get("maxLength")
            if isinstance(minimum, int) and len(candidate) < minimum:
                findings.append(_finding("SHAPE_LENGTH", where, "String is shorter than allowed"))
            if isinstance(maximum, int) and len(candidate) > maximum:
                findings.append(_finding("SHAPE_LENGTH", where, "String is longer than allowed"))
            enum = node.get("enum")
            if isinstance(enum, list) and candidate not in enum:
                findings.append(_finding("SHAPE_ENUM", where, "Value is not an allowed member"))
        elif kind in ("integer", "number"):
            minimum, maximum = node.get("minimum"), node.get("maximum")
            if isinstance(minimum, (int, float)) and candidate < minimum:
                findings.append(_finding("SHAPE_RANGE", where, "Value is below the allowed bound"))
            if isinstance(maximum, (int, float)) and candidate > maximum:
                findings.append(_finding("SHAPE_RANGE", where, "Value is above the allowed bound"))

    if not isinstance(descriptor, dict):
        return [_finding("SHAPE_INVALID", path or "value", "Shape descriptor must be an object")]
    walk(descriptor, value, path, 0)
    return findings[:MAX_FINDINGS]


# --------------------------------------------------------------------------
# Predicates
# --------------------------------------------------------------------------

class PredicateContext:
    """Read-only state view the predicate evaluator needs.

    Every accessor returns ``None`` when the fact cannot be established from
    stored state; ``None`` means *unknown* and blocks the edge exactly like
    an unresolved obligation blocks an action today. The engine supplies the
    implementation; the evaluator itself stays pure.
    """

    def node_completed(self, node: str) -> Optional[bool]:
        return None

    def field_value(self, object_name: str, path: List[str]) -> Tuple[bool, Any]:
        return (False, None)

    def evidence_verified(self, evidence_kind: str, subject: Optional[dict]) -> Optional[bool]:
        return None

    def requirement_state(self, rule_id: str) -> Optional[str]:
        return None


def _lint_predicate(predicate: Any, path: str, findings: List[Dict[str, str]],
                    depth: int = 0) -> None:
    if depth > MAX_PREDICATE_DEPTH:
        findings.append(_finding("PREDICATE_TOO_DEEP", path, "Predicate is nested too deeply"))
        return
    if not isinstance(predicate, dict):
        findings.append(_finding("PREDICATE_INVALID", path, "Predicate must be an object"))
        return
    operator = predicate.get("op")
    if operator == "always":
        return
    if operator == "node_completed":
        if not _is_identifier(predicate.get("node")):
            findings.append(_finding("PREDICATE_INVALID", path + ".node",
                                     "node_completed requires a node identifier"))
        return
    if operator == "field":
        name = predicate.get("object")
        if not _is_identifier(name):
            findings.append(_finding("PREDICATE_INVALID", path + ".object",
                                     "field requires an object name"))
        field_path = predicate.get("path")
        if (not isinstance(field_path, list)
                or not all(_is_identifier(part) for part in field_path)):
            findings.append(_finding("PREDICATE_INVALID", path + ".path",
                                     "field requires a list of field names"))
        if predicate.get("cmp") not in _COMPARISONS:
            findings.append(_finding("PREDICATE_INVALID", path + ".cmp",
                                     "Comparison operator is not supported"))
        if "value" not in predicate:
            findings.append(_finding("PREDICATE_INVALID", path + ".value",
                                     "field requires a comparison value"))
        return
    if operator == "evidence_verified":
        if not _is_identifier(predicate.get("evidence_kind")):
            findings.append(_finding("PREDICATE_INVALID", path + ".evidence_kind",
                                     "evidence_verified requires an evidence kind"))
        subject = predicate.get("subject")
        if subject is not None and not isinstance(subject, dict):
            findings.append(_finding("PREDICATE_INVALID", path + ".subject",
                                     "subject must be an object reference"))
        return
    if operator == "requirement":
        if not _is_identifier(predicate.get("rule")):
            findings.append(_finding("PREDICATE_INVALID", path + ".rule",
                                     "requirement requires a rule identifier"))
        if predicate.get("state") not in ("satisfied", "not_applicable"):
            findings.append(_finding("PREDICATE_INVALID", path + ".state",
                                     "requirement state must be satisfied or not_applicable"))
        return
    if operator in ("all", "any"):
        entries = predicate.get("of")
        if not isinstance(entries, list) or not entries:
            findings.append(_finding("PREDICATE_INVALID", path + ".of",
                                     "Composite predicate requires a nonempty list"))
            return
        for index, entry in enumerate(entries):
            _lint_predicate(entry, path + ".of[" + str(index) + "]", findings, depth + 1)
        return
    findings.append(_finding("PREDICATE_INVALID", path + ".op",
                             "Predicate operator is not supported"))


def eval_predicate(predicate: Any, context: PredicateContext) -> str:
    """Evaluate a predicate to ``true``, ``false`` or ``unknown``.

    Unknown is not false: a missing field, an unknown obligation or an
    unestablished fact blocks the edge instead of silently taking it.
    """
    if not isinstance(predicate, dict):
        return "unknown"
    operator = predicate.get("op")
    if operator == "always":
        return "true"
    if operator == "node_completed":
        answer = context.node_completed(predicate.get("node"))
        if answer is None:
            return "unknown"
        return "true" if answer else "false"
    if operator == "field":
        found, value = context.field_value(predicate.get("object"),
                                           predicate.get("path") or [])
        if not found:
            return "unknown"
        if not _compare(value, predicate.get("cmp"), predicate.get("value")):
            return "false"
        return "true"
    if operator == "evidence_verified":
        answer = context.evidence_verified(predicate.get("evidence_kind"),
                                           predicate.get("subject"))
        if answer is None:
            return "unknown"
        return "true" if answer else "false"
    if operator == "requirement":
        answer = context.requirement_state(predicate.get("rule"))
        if answer is None:
            return "unknown"
        return "true" if answer == predicate.get("state") else "false"
    if operator == "all":
        answers = [eval_predicate(entry, context) for entry in predicate.get("of") or []]
        if "false" in answers:
            return "false"
        if "unknown" in answers:
            return "unknown"
        return "true"
    if operator == "any":
        answers = [eval_predicate(entry, context) for entry in predicate.get("of") or []]
        if "true" in answers:
            return "true"
        if "unknown" in answers:
            return "unknown"
        return "false"
    return "unknown"


# --------------------------------------------------------------------------
# Template lint and digest
# --------------------------------------------------------------------------

def _lint_subject(subject: Any, path: str, findings: List[Dict[str, str]]) -> None:
    if not isinstance(subject, dict):
        findings.append(_finding("SPEC_FIELD_TYPE", path, "Subject must be an object reference"))
        return
    if set(subject) != {"object"}:
        findings.append(_finding("SPEC_FIELD_UNKNOWN", path,
                                 "Subject reference requires exactly an object name"))
        return
    if not _is_identifier(subject.get("object")):
        findings.append(_finding("SPEC_FIELD_TYPE", path + ".object",
                                 "Subject requires an object name"))


def _lint_node(node_id: str, node: Any, findings: List[Dict[str, str]]) -> None:
    path = "nodes." + node_id
    if not isinstance(node, dict):
        findings.append(_finding("SPEC_FIELD_TYPE", path, "Node must be an object"))
        return
    kind = node.get("kind")
    if kind not in NODE_KINDS:
        findings.append(_finding("NODE_KIND_UNKNOWN", path + ".kind",
                                 "Node kind must be agent, human, action or wait"))
        return
    required = _NODE_REQUIRED[kind]
    allowed = set(required) | set(_NODE_OPTIONAL) | {"kind"}
    for name in required:
        if name not in node:
            findings.append(_finding("NODE_FIELD_MISSING", path + "." + name,
                                     "Node kind requires this field"))
    for name in node:
        if name not in allowed:
            findings.append(_finding("NODE_FIELD_UNKNOWN", path + "." + name,
                                     "Node field is not supported for this kind"))
    if "executor" in node and not _is_identifier(node["executor"]):
        findings.append(_finding("NODE_FIELD_TYPE", path + ".executor",
                                 "Executor must be a principal identifier"))
    if "capability" in node and not _is_identifier(node["capability"]):
        findings.append(_finding("NODE_FIELD_TYPE", path + ".capability",
                                 "Capability must be an identifier"))
    if "evidence_kind" in node and not _is_identifier(node["evidence_kind"]):
        findings.append(_finding("NODE_FIELD_TYPE", path + ".evidence_kind",
                                 "Evidence kind must be an identifier"))
    if "authority" in node:
        _lint_authority(node["authority"], path + ".authority", findings)
    if "max_attempts" in node and (not _is_int(node["max_attempts"])
                                   or node["max_attempts"] < 1):
        findings.append(_finding("NODE_FIELD_TYPE", path + ".max_attempts",
                                 "max_attempts must be a positive integer"))
    if "deadline_s" in node and (not _is_int(node["deadline_s"])
                                 or node["deadline_s"] < 1):
        findings.append(_finding("NODE_FIELD_TYPE", path + ".deadline_s",
                                 "deadline_s must be a positive integer"))
    if "inputs" in node:
        inputs = node["inputs"]
        if not isinstance(inputs, list):
            findings.append(_finding("NODE_FIELD_TYPE", path + ".inputs",
                                     "inputs must be a list"))
        else:
            for index, entry in enumerate(inputs):
                if not isinstance(entry, dict) or "object" not in entry:
                    findings.append(_finding("SPEC_FIELD_TYPE",
                                             path + ".inputs[" + str(index) + "]",
                                             "Input requires an object name"))
                    continue
                if set(entry) - {"object", "validation"}:
                    findings.append(_finding("SPEC_FIELD_UNKNOWN",
                                             path + ".inputs[" + str(index) + "]",
                                             "Input supports only object and validation"))
                if "validation" in entry:
                    validation = entry["validation"]
                    if not isinstance(validation, dict):
                        findings.append(_finding("SPEC_FIELD_TYPE",
                                                 path + ".inputs[" + str(index) + "].validation",
                                                 "Input validation must be an object"))
                    else:
                        _lint_validation(validation,
                                         path + ".inputs[" + str(index) + "].validation",
                                         findings)
    if "output" in node:
        _lint_output(node["output"], path + ".output", findings)
    if "subject" in node:
        _lint_subject(node["subject"], path + ".subject", findings)
    if "review" in node:
        review = node["review"]
        allowed_review = {"evidence_kind", "reviewer", "rubric"}
        if not isinstance(review, dict):
            findings.append(_finding("SPEC_FIELD_TYPE", path + ".review",
                                     "review must be an object"))
        else:
            for name in review:
                if name not in allowed_review:
                    findings.append(_finding("SPEC_FIELD_UNKNOWN",
                                             path + ".review." + name,
                                             "Review field is not supported"))
            if "evidence_kind" not in review:
                findings.append(_finding("SPEC_FIELD_MISSING",
                                         path + ".review.evidence_kind",
                                         "A review requires an evidence kind"))
            elif not _is_identifier(review["evidence_kind"]):
                findings.append(_finding("SPEC_FIELD_TYPE",
                                         path + ".review.evidence_kind",
                                         "Review evidence kind must be an identifier"))
            if "reviewer" not in review:
                findings.append(_finding("SPEC_FIELD_MISSING", path + ".review.reviewer",
                                         "A review requires the independent reviewer"))
            elif not _is_identifier(review["reviewer"]):
                findings.append(_finding("SPEC_FIELD_TYPE", path + ".review.reviewer",
                                         "A reviewer must be a principal identifier"))
            if "rubric" not in review:
                findings.append(_finding("SPEC_FIELD_MISSING", path + ".review.rubric",
                                         "A review requires its pinned rubric"))
            else:
                _lint_validation(review["rubric"], path + ".review.rubric", findings)
    if "distinct_from" in node:
        entries = node["distinct_from"]
        if (not isinstance(entries, list)
                or not all(_is_identifier(entry) for entry in entries)):
            findings.append(_finding("SPEC_FIELD_TYPE", path + ".distinct_from",
                                     "distinct_from must be a list of node identifiers"))
    if "checks" in node:
        entries = node["checks"]
        if not isinstance(entries, list):
            findings.append(_finding("SPEC_FIELD_TYPE", path + ".checks",
                                     "checks must be a list of check declarations"))
        else:
            seen = set()
            for index, entry in enumerate(entries):
                _lint_check(entry, path + ".checks[" + str(index) + "]", findings)
                if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                    if entry["id"] in seen:
                        findings.append(_finding("SPEC_FIELD_TYPE",
                                                 path + ".checks[" + str(index) + "].id",
                                                 "A node may not declare a criterion twice"))
                    seen.add(entry["id"])
    if kind == "wait" and "match" in node:
        match = node["match"]
        if not isinstance(match, dict):
            findings.append(_finding("SPEC_FIELD_TYPE", path + ".match",
                                     "Wait match must be an object"))
        else:
            allowed_match = {"evidence_kind", "subject", "node_completed", "timeout"}
            for name in match:
                if name not in allowed_match:
                    findings.append(_finding("SPEC_FIELD_UNKNOWN", path + ".match." + name,
                                             "Wait match field is not supported"))
            if "evidence_kind" in match and not _is_identifier(match["evidence_kind"]):
                findings.append(_finding("SPEC_FIELD_TYPE", path + ".match.evidence_kind",
                                         "Wait match evidence kind must be an identifier"))
            if "subject" in match:
                _lint_subject(match["subject"], path + ".match.subject", findings)
            if "node_completed" in match and not _is_identifier(match["node_completed"]):
                findings.append(_finding("SPEC_FIELD_TYPE", path + ".match.node_completed",
                                         "Wait match node must be an identifier"))


def _lint_authority(authority: Any, path: str, findings: List[Dict[str, str]]) -> None:
    """The principal that may decide a node.

    Two closed forms: a static principal name, or ``{"assigned": true}``,
    which means "whoever the platform currently assigns to this node". The
    core never sees a workspace role id: the assignment is resolved through
    a trusted, injected participant resolver, and it fails closed when no
    resolver is configured.
    """
    if _is_identifier(authority):
        return
    if isinstance(authority, dict) and set(authority) == {"assigned"}:
        if authority.get("assigned") is not True:
            findings.append(_finding("SPEC_FIELD_TYPE", path + ".assigned",
                                     "An assigned authority must be true"))
        return
    findings.append(_finding("SPEC_FIELD_TYPE", path,
                             "Authority must be a principal identifier or an "
                             "assigned authority"))


def _lint_check(entry: Any, path: str, findings: List[Dict[str, str]]) -> None:
    """One declared criterion: an identifier, its text and an optional validator.

    The criterion text is part of the protected definition: a binding pins
    the digest of the definition, so the text a reviewer read is the text
    that is enforced.
    """
    if not isinstance(entry, dict):
        findings.append(_finding("SPEC_FIELD_TYPE", path,
                                 "A check declaration must be an object"))
        return
    allowed = {"id", "criterion", "method", "criterion_version", "validator",
               "validator_version", "required", "allow_not_applicable"}
    for name in entry:
        if name not in allowed:
            findings.append(_finding("SPEC_FIELD_UNKNOWN", path + "." + name,
                                     "Check declaration field is not supported"))
    if "id" not in entry:
        findings.append(_finding("SPEC_FIELD_MISSING", path + ".id",
                                 "A check declaration requires an identifier"))
    elif not _is_identifier(entry["id"]):
        findings.append(_finding("SPEC_FIELD_TYPE", path + ".id",
                                 "Check identifier must be a nonempty identifier"))
    if "criterion" not in entry:
        findings.append(_finding("SPEC_FIELD_MISSING", path + ".criterion",
                                 "A check declaration requires its criterion text"))
    elif not _is_text(entry["criterion"]):
        findings.append(_finding("SPEC_FIELD_TYPE", path + ".criterion",
                                 "A criterion must be a nonempty string"))
    if "method" not in entry:
        findings.append(_finding("SPEC_FIELD_MISSING", path + ".method",
                                 "A criterion declaration names the judge that "
                                 "checks it"))
    elif entry["method"] not in ("PROGRAM", "AGENT", "HUMAN"):
        findings.append(_finding("SPEC_FIELD_TYPE", path + ".method",
                                 "A criterion method must be PROGRAM, AGENT or HUMAN"))
    if "criterion_version" in entry and not _is_text(entry["criterion_version"]):
        findings.append(_finding("SPEC_FIELD_TYPE", path + ".criterion_version",
                                 "A criterion version must be a nonempty string"))
    if "validator" in entry and not _is_identifier(entry["validator"]):
        findings.append(_finding("SPEC_FIELD_TYPE", path + ".validator",
                                 "Validator must be an identifier"))
    if "validator_version" in entry and not _is_text(entry["validator_version"]):
        findings.append(_finding("SPEC_FIELD_TYPE", path + ".validator_version",
                                 "Validator version must be a nonempty string"))
    if ("validator" in entry) != ("validator_version" in entry):
        findings.append(_finding("SPEC_FIELD_MISSING", path,
                                 "A check validator binds an id and a version together"))
    for flag in ("required", "allow_not_applicable"):
        if flag in entry and not isinstance(entry[flag], bool):
            findings.append(_finding("SPEC_FIELD_TYPE", path + "." + flag,
                                     flag + " must be a boolean"))


def _lint_validation(validation: Any, path: str, findings: List[Dict[str, str]]) -> None:
    if not isinstance(validation, dict):
        findings.append(_finding("SPEC_FIELD_TYPE", path, "Validation must be an object"))
        return
    allowed = {"shape", "validator", "validator_version"}
    for name in validation:
        if name not in allowed:
            findings.append(_finding("SPEC_FIELD_UNKNOWN", path + "." + name,
                                     "Validation field is not supported"))
    if "shape" in validation:
        _lint_shape(validation["shape"], path + ".shape", findings)
    if "validator" in validation and not _is_identifier(validation["validator"]):
        findings.append(_finding("SPEC_FIELD_TYPE", path + ".validator",
                                 "Validator must be an identifier"))
    if "validator_version" in validation and not _is_text(validation["validator_version"]):
        findings.append(_finding("SPEC_FIELD_TYPE", path + ".validator_version",
                                 "Validator version must be a nonempty string"))


def _lint_output(output: Any, path: str, findings: List[Dict[str, str]]) -> None:
    if not isinstance(output, dict):
        findings.append(_finding("SPEC_FIELD_TYPE", path, "Output must be an object"))
        return
    allowed = {"object", "validation"}
    for name in output:
        if name not in allowed:
            findings.append(_finding("SPEC_FIELD_UNKNOWN", path + "." + name,
                                     "Output field is not supported"))
    if "object" not in output:
        findings.append(_finding("SPEC_FIELD_MISSING", path + ".object",
                                 "Output requires an object name"))
    elif not _is_identifier(output["object"]):
        findings.append(_finding("SPEC_FIELD_TYPE", path + ".object",
                                 "Output requires an object name"))
    if "validation" in output:
        _lint_validation(output["validation"], path + ".validation", findings)


def lint_template(spec: Any) -> List[Dict[str, str]]:
    """Static lint of a workflow template.

    Returns a bounded list of diagnostics. An empty list means the definition
    is structurally sound; policy-family, authority and validator resolution
    happen at binding time, not here.
    """
    findings: List[Dict[str, str]] = []
    if not isinstance(spec, dict):
        return [_finding("SPEC_NOT_OBJECT", "", "Workflow definition must be an object")]
    for name in _TOP_REQUIRED:
        if name not in spec:
            findings.append(_finding("SPEC_FIELD_MISSING", name,
                                     "Workflow definition requires this field"))
    for name in spec:
        if name not in _TOP_REQUIRED and name not in _TOP_OPTIONAL:
            findings.append(_finding("SPEC_FIELD_UNKNOWN", name,
                                     "Workflow definition field is not supported"))
    for name in ("id", "version", "policy_family"):
        if name in spec and not _is_text(spec[name]):
            findings.append(_finding("SPEC_FIELD_TYPE", name,
                                     "Workflow definition field must be a nonempty string"))
    nodes = spec.get("nodes")
    node_ids: List[str] = []
    if not isinstance(nodes, dict):
        if "nodes" in spec:
            findings.append(_finding("SPEC_FIELD_TYPE", "nodes",
                                     "nodes must be an object"))
    else:
        if len(nodes) > MAX_NODES:
            findings.append(_finding("SPEC_TOO_LARGE", "nodes",
                                     "Workflow definition declares too many nodes"))
        for node_id, node in nodes.items():
            if not _is_identifier(node_id):
                findings.append(_finding("NODE_ID_INVALID", "nodes",
                                         "Node identifier is invalid"))
                continue
            node_ids.append(node_id)
            _lint_node(node_id, node, findings)
    known = set(node_ids)
    edges = spec.get("edges")
    if not isinstance(edges, list):
        if "edges" in spec:
            findings.append(_finding("SPEC_FIELD_TYPE", "edges", "edges must be a list"))
        edges = []
    elif len(edges) > MAX_EDGES:
        findings.append(_finding("SPEC_TOO_LARGE", "edges",
                                 "Workflow definition declares too many edges"))
    for index, edge in enumerate(edges):
        path = "edges[" + str(index) + "]"
        if not isinstance(edge, dict):
            findings.append(_finding("SPEC_FIELD_TYPE", path, "Edge must be an object"))
            continue
        for name in edge:
            if name not in ("from", "to", "when"):
                findings.append(_finding("SPEC_FIELD_UNKNOWN", path + "." + name,
                                         "Edge field is not supported"))
        for name in ("from", "to"):
            value = edge.get(name)
            if not _is_identifier(value):
                findings.append(_finding("SPEC_FIELD_TYPE", path + "." + name,
                                         "Edge requires a node identifier"))
            elif value not in known:
                findings.append(_finding("EDGE_REFERENCE_UNKNOWN", path + "." + name,
                                         "Edge references an undeclared node"))
        if edge.get("from") == edge.get("to") and edge.get("from") is not None:
            findings.append(_finding("EDGE_SELF", path, "Edge cannot reference itself"))
        if "when" in edge:
            _lint_predicate(edge["when"], path + ".when", findings)
    if known:
        for node_id, node in nodes.items():
            if not isinstance(node, dict):
                continue
            for name in ("on_reject", "on_failure", "on_timeout"):
                if name in node:
                    target = node[name]
                    if not _is_identifier(target):
                        findings.append(_finding("SPEC_FIELD_TYPE",
                                                 "nodes." + node_id + "." + name,
                                                 "Branch target must be a node identifier"))
                    elif target not in known:
                        findings.append(_finding("EDGE_REFERENCE_UNKNOWN",
                                                 "nodes." + node_id + "." + name,
                                                 "Branch references an undeclared node"))
            if node.get("kind") == "wait" and "match" in node:
                match = node["match"]
                if isinstance(match, dict) and "node_completed" in match:
                    if match["node_completed"] not in known:
                        findings.append(_finding("EDGE_REFERENCE_UNKNOWN",
                                                 "nodes." + node_id + ".match.node_completed",
                                                 "Wait match references an undeclared node"))
            if node.get("kind") == "human" and "distinct_from" in node:
                for target in node["distinct_from"] or []:
                    if target not in known:
                        findings.append(_finding("EDGE_REFERENCE_UNKNOWN",
                                                 "nodes." + node_id + ".distinct_from",
                                                 "Separation rule references an undeclared node"))
    inbound = {node_id: 0 for node_id in known}
    for edge in edges:
        if isinstance(edge, dict) and edge.get("to") in inbound:
            inbound[edge["to"]] += 1
    entry = spec.get("entry")
    if entry is not None:
        if not _is_identifier(entry) or entry not in known:
            findings.append(_finding("EDGE_REFERENCE_UNKNOWN", "entry",
                                     "Entry references an undeclared node"))
        elif inbound.get(entry):
            findings.append(_finding("ENTRY_HAS_INBOUND", "entry",
                                     "Entry node must not have inbound edges"))
    elif known:
        candidates = [node_id for node_id in known if inbound.get(node_id) == 0]
        if len(candidates) != 1:
            findings.append(_finding("ENTRY_AMBIGUOUS", "entry",
                                     "Workflow must declare exactly one entry node"))
    terminal = spec.get("terminal")
    if terminal is not None:
        if (not isinstance(terminal, list)
                or not all(_is_identifier(entry) for entry in terminal)):
            findings.append(_finding("SPEC_FIELD_TYPE", "terminal",
                                     "terminal must be a list of node identifiers"))
        else:
            for node_id in terminal:
                if node_id not in known:
                    findings.append(_finding("EDGE_REFERENCE_UNKNOWN", "terminal",
                                             "Terminal references an undeclared node"))
                elif any(isinstance(edge, dict) and edge.get("from") == node_id
                         for edge in edges):
                    findings.append(_finding("TERMINAL_HAS_OUTBOUND", "terminal",
                                             "Terminal node must not have outbound edges"))
    if "parameters_schema" in spec:
        _lint_shape(spec["parameters_schema"], "parameters_schema", findings)
    if "required_checks" in spec:
        entries = spec["required_checks"]
        if not isinstance(entries, list) or not all(_is_identifier(entry) for entry in entries):
            findings.append(_finding("SPEC_FIELD_TYPE", "required_checks",
                                     "required_checks must be a list of check identifiers"))
    _lint_cycles(nodes, edges, findings)
    return findings[:MAX_FINDINGS]


def _lint_cycles(nodes: Any, edges: List[Any], findings: List[Dict[str, str]]) -> None:
    """Advance edges must form a DAG; rework branches are separate and may go back."""
    if not isinstance(nodes, dict):
        return
    successors: Dict[str, List[str]] = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source, target = edge.get("from"), edge.get("to")
        if isinstance(source, str) and isinstance(target, str):
            successors.setdefault(source, []).append(target)
    state: Dict[str, int] = {}

    def visit(node_id: str) -> None:
        state[node_id] = 1
        for successor in successors.get(node_id, []):
            mark = state.get(successor, 0)
            if mark == 1:
                findings.append(_finding("GRAPH_CYCLE", "edges",
                                         "Advance edges must not contain a cycle"))
                return
            if mark == 0:
                visit(successor)
        state[node_id] = 2

    for node_id in list(nodes):
        if state.get(node_id, 0) == 0:
            visit(node_id)


def template_digest(spec: Any) -> str:
    """Canonical content digest of a definition; stable across key order."""
    return digest(spec)


def canonical_json(value: Any) -> str:
    """Canonical JSON text of a value (stable key order)."""
    return canonical(value)


# --------------------------------------------------------------------------
# Validator registry
# --------------------------------------------------------------------------

class ValidatorRegistry:
    """Host-registered, version-pinned output validators.

    Registering a validator is a host trust decision: it is configuration, not
    something a workflow participant can grant itself. The registry never
    executes anything until a validator id *and* version both resolve.
    """

    def __init__(self, entries: Optional[Dict[Tuple[str, str], Callable]] = None):
        self._entries: Dict[Tuple[str, str], Callable] = {}
        for key, validator in (entries or {}).items():
            self._entries[tuple(key)] = validator

    def register(self, validator_id: str, version: str, validate: Callable) -> None:
        if not _is_identifier(validator_id):
            raise ValueError("validator id must be a nonempty identifier")
        if not _is_text(version):
            raise ValueError("validator version must be a nonempty string")
        if not callable(validate):
            raise ValueError("validator must be callable")
        self._entries[(validator_id, version)] = validate

    def resolve(self, validator_id: Any, version: Any) -> Optional[Callable]:
        if not isinstance(validator_id, str) or not isinstance(version, str):
            return None
        return self._entries.get((validator_id, version))

    def versions(self, validator_id: str) -> Tuple[str, ...]:
        return tuple(sorted(version for (name, version) in self._entries
                            if name == validator_id))

    def ids(self) -> Tuple[str, ...]:
        return tuple(sorted({name for (name, _) in self._entries}))
