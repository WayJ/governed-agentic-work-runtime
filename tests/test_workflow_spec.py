"""Static workflow definition language: lint, digest, predicates, shapes."""

import unittest

from work_runtime.workflow_spec import (ValidatorRegistry, eval_predicate, lint_template,
                                         template_digest, validate_shape)


def agent_node(**overrides):
    node = {"kind": "agent", "executor": "worker", "max_attempts": 3,
            "output": {"object": "pack",
                       "validation": {"validator": "pack", "validator_version": "1"}}}
    node.update(overrides)
    return node


def human_node(**overrides):
    node = {"kind": "human", "evidence_kind": "review", "subject": {"object": "pack"}}
    node.update(overrides)
    return node


def action_node(**overrides):
    node = {"kind": "action", "capability": "dispatch", "subject": {"object": "pack"}}
    node.update(overrides)
    return node


def wait_node(**overrides):
    node = {"kind": "wait", "match": {"timeout": True}, "deadline_s": 60}
    node.update(overrides)
    return node


def template(nodes=None, edges=None, **overrides):
    spec = {
        "id": "demo-flow",
        "version": "v1",
        "policy_family": "demo-family",
        "nodes": nodes or {"A": agent_node(), "B": human_node()},
        "edges": edges if edges is not None else [{"from": "A", "to": "B"}],
    }
    spec.update(overrides)
    return spec


class LintTests(unittest.TestCase):
    def test_clean_template_has_no_diagnostics(self):
        self.assertEqual(lint_template(template()), [])

    def test_missing_top_level_fields_are_reported(self):
        codes = {finding["code"] for finding in lint_template({"nodes": {}})}
        self.assertIn("SPEC_FIELD_MISSING", codes)

    def test_unknown_top_level_field_is_reported(self):
        codes = {finding["code"] for finding in lint_template(template(dynamic_graph=True))}
        self.assertIn("SPEC_FIELD_UNKNOWN", codes)

    def test_unknown_node_kind_is_reported(self):
        spec = template(nodes={"A": {"kind": "magic"}})
        codes = {finding["code"] for finding in lint_template(spec)}
        self.assertIn("NODE_KIND_UNKNOWN", codes)

    def test_missing_required_node_field_is_reported(self):
        spec = template(nodes={"A": {"kind": "agent", "executor": "worker"}})
        codes = {finding["code"] for finding in lint_template(spec)}
        self.assertIn("NODE_FIELD_MISSING", codes)

    def test_dangling_edge_reference_is_reported(self):
        spec = template(edges=[{"from": "A", "to": "Z"}])
        codes = {finding["code"] for finding in lint_template(spec)}
        self.assertIn("EDGE_REFERENCE_UNKNOWN", codes)

    def test_cycle_is_reported(self):
        spec = template(nodes={"A": agent_node(), "B": human_node()},
                        edges=[{"from": "A", "to": "B"}, {"from": "B", "to": "A"}])
        codes = {finding["code"] for finding in lint_template(spec)}
        self.assertIn("GRAPH_CYCLE", codes)

    def test_ambiguous_entry_is_reported(self):
        spec = template(nodes={"A": agent_node(), "B": human_node()}, edges=[])
        codes = {finding["code"] for finding in lint_template(spec)}
        self.assertIn("ENTRY_AMBIGUOUS", codes)

    def test_branch_to_unknown_node_is_reported(self):
        spec = template(nodes={"A": agent_node(), "B": human_node(on_reject="Z")},
                        edges=[{"from": "A", "to": "B"}])
        codes = {finding["code"] for finding in lint_template(spec)}
        self.assertIn("EDGE_REFERENCE_UNKNOWN", codes)

    def test_bad_predicate_operator_is_reported(self):
        spec = template(edges=[{"from": "A", "to": "B", "when": {"op": "not", "of": []}}])
        codes = {finding["code"] for finding in lint_template(spec)}
        self.assertIn("PREDICATE_INVALID", codes)

    def test_diagnostic_messages_do_not_echo_payload(self):
        spec = template(nodes={"A": agent_node(output={"object": "secret-content-here",
                                                        "validation": {"validator": 7,
                                                                       "validator_version": "1"}})})
        findings = lint_template(spec)
        self.assertTrue(findings)
        for finding in findings:
            self.assertNotIn("secret-content-here", finding["message"])

    def test_digest_is_stable_across_key_order(self):
        first = template()
        second = {"edges": first["edges"], "nodes": first["nodes"],
                  "policy_family": first["policy_family"], "version": first["version"],
                  "id": first["id"]}
        self.assertEqual(template_digest(first), template_digest(second))

    def test_digest_changes_when_content_changes(self):
        first = template()
        second = template()
        second["nodes"]["A"]["max_attempts"] = 4
        self.assertNotEqual(template_digest(first), template_digest(second))


class ShapeTests(unittest.TestCase):
    def test_matching_object_passes(self):
        descriptor = {"type": "object",
                      "properties": {"id": {"type": "string", "minLength": 1},
                                     "count": {"type": "integer", "minimum": 0}},
                      "required": ["id", "count"]}
        self.assertEqual(validate_shape(descriptor, {"id": "x", "count": 2}), [])

    def test_missing_field_is_reported(self):
        descriptor = {"type": "object", "properties": {"id": {"type": "string"}},
                      "required": ["id"]}
        codes = {finding["code"] for finding in validate_shape(descriptor, {})}
        self.assertIn("SHAPE_MISSING_FIELD", codes)

    def test_unexpected_field_is_reported(self):
        descriptor = {"type": "object", "properties": {"id": {"type": "string"}},
                      "required": ["id"]}
        codes = {finding["code"] for finding in validate_shape(descriptor, {"id": "x", "y": 1})}
        self.assertIn("SHAPE_UNEXPECTED_FIELD", codes)

    def test_type_mismatch_is_reported(self):
        descriptor = {"type": "object", "properties": {"count": {"type": "integer"}}}
        codes = {finding["code"] for finding in validate_shape(descriptor, {"count": True})}
        self.assertIn("SHAPE_TYPE", codes)

    def test_enum_and_range_are_enforced(self):
        descriptor = {"type": "object",
                      "properties": {"kind": {"type": "string", "enum": ["a", "b"]},
                                     "score": {"type": "number", "maximum": 10}}}
        codes = {finding["code"] for finding in
                 validate_shape(descriptor, {"kind": "c", "score": 99})}
        self.assertIn("SHAPE_ENUM", codes)
        self.assertIn("SHAPE_RANGE", codes)

    def test_array_item_shape_is_checked(self):
        descriptor = {"type": "object",
                      "properties": {"items": {"type": "array",
                                               "items": {"type": "string",
                                                         "minLength": 2}}}}
        codes = {finding["code"] for finding in
                 validate_shape(descriptor, {"items": ["ok", "x"]})}
        self.assertIn("SHAPE_LENGTH", codes)

    def test_malformed_descriptor_yields_one_finding(self):
        self.assertEqual(len(validate_shape("nope", {})), 1)


class Context:
    def __init__(self, completed=(), fields=None, evidence=None, requirements=None):
        self.completed = set(completed)
        self.fields = fields or {}
        self.evidence = evidence or {}
        self.requirements = requirements or {}

    def node_completed(self, node):
        return node in self.completed

    def field_value(self, object_name, path):
        value = self.fields.get(object_name)
        if value is None:
            return (False, None)
        for part in path:
            if not isinstance(value, dict) or part not in value:
                return (False, None)
            value = value[part]
        return (True, value)

    def evidence_verified(self, evidence_kind, subject):
        return self.evidence.get(evidence_kind)

    def requirement_state(self, rule_id):
        return self.requirements.get(rule_id)


class PredicateTests(unittest.TestCase):
    def test_always_is_true(self):
        self.assertEqual(eval_predicate({"op": "always"}, Context()), "true")

    def test_node_completed_reflects_state(self):
        self.assertEqual(eval_predicate({"op": "node_completed", "node": "A"},
                                         Context(completed=["A"])), "true")
        self.assertEqual(eval_predicate({"op": "node_completed", "node": "A"},
                                         Context()), "false")

    def test_missing_field_is_unknown_not_false(self):
        predicate = {"op": "field", "object": "pack", "path": ["risk"], "cmp": "eq",
                     "value": "high"}
        self.assertEqual(eval_predicate(predicate, Context()), "unknown")

    def test_field_comparison_operators(self):
        context = Context(fields={"pack": {"risk": "high", "score": 5}})
        self.assertEqual(eval_predicate({"op": "field", "object": "pack", "path": ["risk"],
                                          "cmp": "eq", "value": "high"}, context), "true")
        self.assertEqual(eval_predicate({"op": "field", "object": "pack", "path": ["score"],
                                          "cmp": "ge", "value": 5}, context), "true")
        self.assertEqual(eval_predicate({"op": "field", "object": "pack", "path": ["score"],
                                          "cmp": "gt", "value": 5}, context), "false")

    def test_unknown_evidence_fact_blocks(self):
        self.assertEqual(eval_predicate({"op": "evidence_verified",
                                          "evidence_kind": "handoff"}, Context()), "unknown")

    def test_all_requires_every_true(self):
        predicate = {"op": "all", "of": [{"op": "always"},
                                          {"op": "node_completed", "node": "A"}]}
        self.assertEqual(eval_predicate(predicate, Context(completed=["A"])), "true")
        self.assertEqual(eval_predicate(predicate, Context()), "false")

    def test_any_with_unknown_member_is_unknown(self):
        predicate = {"op": "any", "of": [{"op": "evidence_verified",
                                          "evidence_kind": "handoff"}]}
        self.assertEqual(eval_predicate(predicate, Context()), "unknown")

    def test_requirement_state_is_read(self):
        context = Context(requirements={"G05": "satisfied"})
        self.assertEqual(eval_predicate({"op": "requirement", "rule": "G05",
                                          "state": "satisfied"}, context), "true")


class ValidatorRegistryTests(unittest.TestCase):
    def test_unknown_validator_does_not_resolve(self):
        registry = ValidatorRegistry()
        self.assertIsNone(registry.resolve("missing", "1"))

    def test_version_must_match_exactly(self):
        registry = ValidatorRegistry()
        registry.register("pack", "1", lambda work, node, value: [])
        self.assertIsNotNone(registry.resolve("pack", "1"))
        self.assertIsNone(registry.resolve("pack", "2"))

    def test_ids_and_versions_are_reported(self):
        registry = ValidatorRegistry()
        registry.register("pack", "2", lambda work, node, value: [])
        registry.register("pack", "1", lambda work, node, value: [])
        self.assertEqual(registry.versions("pack"), ("1", "2"))
        self.assertEqual(registry.ids(), ("pack",))


if __name__ == "__main__":
    unittest.main()


class MaterialGenerationLintTests(unittest.TestCase):
    """The definition declares how often a node's material may be replaced.

    The material budget is separate from the quality allowance: a node
    declares both, and they bound different things.
    """

    def base(self):
        return {
            "id": "t", "version": "1", "policy_family": "f",
            "entry": "n01", "terminal": ["n01"],
            "nodes": {"n01": {"kind": "agent", "executor": "e",
                              "output": {"object": "o"}, "max_attempts": 2}},
            "edges": [],
        }

    def test_a_material_budget_is_accepted(self):
        spec = self.base()
        spec["nodes"]["n01"]["material_generations"] = 2
        self.assertEqual([], lint_template(spec))

    def test_a_negative_budget_is_refused(self):
        spec = self.base()
        spec["nodes"]["n01"]["material_generations"] = -1
        codes = [finding["code"] for finding in lint_template(spec)]
        self.assertIn("NODE_FIELD_TYPE", codes)

    def test_a_budget_that_is_not_an_integer_is_refused(self):
        spec = self.base()
        spec["nodes"]["n01"]["material_generations"] = "2"
        codes = [finding["code"] for finding in lint_template(spec)]
        self.assertIn("NODE_FIELD_TYPE", codes)

    def test_no_budget_means_no_revalidation(self):
        spec = self.base()
        self.assertEqual([], lint_template(spec))
        self.assertNotIn("material_generations", spec["nodes"]["n01"])
