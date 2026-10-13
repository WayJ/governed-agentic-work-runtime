"""Static SOP authoring lint and digest tests (D22 authoring foundation)."""

import copy
import json
import unittest

from work_runtime.authoring import lint_sop


def valid_card():
    """A fresh, fully valid expense rule card (schema per docs/sop-authoring.md)."""
    return {
        "schema_version": 1,
        "policy": {
            "id": "expense-submit",
            "version": "demo-1",
            "goal": "expense.accepted",
            "source": {"document": "expense-handbook", "version": "2026-03", "section": "4"},
            "scope": "document",
            "capabilities": ["expense.submit"],
        },
        "defaults": {"unknown": "block", "conflict": "escalate",
                     "exemptions": "forbidden", "migration": "explicit"},
        "facts": [{"id": "invoice.valid"}],
        "collections": [{"id": "expense.invoices", "version": "v1",
                         "completeness": "sealed-by-requester", "allow_empty": False}],
        "rules": [
            {
                "id": "E01",
                "source": {"document": "expense-handbook", "version": "2026-03",
                           "section": "4.1"},
                "modality": "must",
                "type": "state",
                "scope": "expense.invoices",
                "trigger": "before expense.submit is proposed",
                "depends_on": ["invoice.valid"],
                "requirement": "The invoice collection must be complete, nonempty and sealed",
                "deadline": "expense.submit",
                "evidence": {"kind": "requester_confirmation", "source": "requester",
                             "subject": "invoice-collection", "version": "content-digest"},
                "unknown": "block",
                "conflict": "escalate",
                "exemption": "forbidden",
                "migration": "explicit",
            },
            {
                "id": "E03",
                "source": {"document": "expense-handbook", "version": "2026-03",
                           "section": "4.3"},
                "modality": "forbidden",
                "type": "action",
                "scope": "document",
                "trigger": "at expense.submit",
                "depends_on": ["E01"],
                "requirement": "An expense must not be submitted twice for the same invoices",
                "deadline": "goal",
                "evidence": {"kind": "duplicate_clear", "source": "expense-service",
                             "subject": "invoice-set", "version": "content-digest"},
                "unknown": "block",
                "conflict": "escalate",
                "exemption": "forbidden",
                "migration": "explicit",
            },
        ],
        "advice": ["Collect invoices and compute limits in parallel"],
    }


def codes_of(diagnostics):
    return [d["code"] for d in diagnostics]


class PreflightNativeTests(unittest.TestCase):
    """JSON-native preflight: exact types only, never raises, never invokes hooks."""

    def test_clean_card_lints_clean(self):
        self.assertEqual(lint_sop(valid_card()), [])

    def test_tuple_value_is_not_json_native(self):
        card = valid_card()
        card["advice"] = ("parallel", "reuse")
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["NOT_JSON_NATIVE"])
        self.assertEqual(result[0]["path"], "/advice")

    def test_set_and_bytes_rejected(self):
        for bad in ({1, 2}, b"bytes", object(), 3 + 4j, float):
            with self.subTest(bad=type(bad).__name__):
                card = valid_card()
                card["advice"] = bad
                result = lint_sop(card)
                self.assertEqual(codes_of(result), ["NOT_JSON_NATIVE"])
                self.assertEqual(result[0]["path"], "/advice")

    def test_subclasses_rejected_even_of_native_types(self):
        class MyInt(int):
            pass

        class MyStr(str):
            pass

        class MyDict(dict):
            pass

        class MyList(list):
            pass

        for bad, path in ((MyInt(1), "/schema_version"), (MyStr("x"), "/advice"),
                          (MyDict(), "/policy"), (MyList(), "/advice")):
            with self.subTest(cls=type(bad).__name__):
                card = valid_card()
                card["advice" if path == "/advice" else "policy" if path == "/policy"
                     else "schema_version"] = bad
                self.assertEqual(codes_of(lint_sop(card)), ["NOT_JSON_NATIVE"])

    def test_root_subclass_rejected_at_empty_pointer(self):
        class MyDict(dict):
            pass

        result = lint_sop(MyDict())
        self.assertEqual(codes_of(result), ["NOT_JSON_NATIVE"])
        self.assertEqual(result[0]["path"], "")

    def test_bool_and_none_are_native(self):
        result = lint_sop({"x": True, "y": None, "z": False})
        self.assertNotIn("NOT_JSON_NATIVE", codes_of(result))

    def test_non_string_object_key_rejected_at_container(self):
        result = lint_sop({"a": {1: "x"}})
        self.assertEqual(codes_of(result), ["NOT_JSON_NATIVE"])
        self.assertEqual(result[0]["path"], "/a")
        self.assertEqual(result[0]["message"], "object key is not a string")

    def test_entries_under_unusable_keys_are_skipped(self):
        cycle = []
        cycle.append(cycle)
        result = lint_sop({1: cycle})
        self.assertEqual(codes_of(result), ["NOT_JSON_NATIVE"])
        self.assertEqual(result[0]["path"], "")

    def test_preflight_suppresses_schema_layer(self):
        # A non-native value plus a missing root field: preflight-only result.
        result = lint_sop({"schema_version": 1, "policy": (), "rules": "not-a-list"})
        self.assertEqual(codes_of(result), ["NOT_JSON_NATIVE"])
        self.assertEqual(result[0]["path"], "/policy")

    def test_never_raises_for_hostile_inputs(self):
        deep = 0
        for _ in range(70):
            deep = [deep]
        cycle = {}
        cycle["self"] = cycle
        hostile = [None, 42, "x", True, 3.5, (), set(), b"", object(), deep, cycle,
                   float("nan"), {"\ud800": 1}, {"k": "\udfff"}, 2 ** 60]
        for value in hostile:
            with self.subTest(value=type(value).__name__):
                self.assertIsInstance(lint_sop(value), list)

    def test_hostile_hooks_never_invoked(self):
        class HostileRepr:
            def __repr__(self):
                raise AssertionError("repr invoked")

        class HostileIter(list):
            def __iter__(self):
                raise AssertionError("iter invoked")

        class HostileDict(dict):
            def keys(self):
                raise AssertionError("keys invoked")

        for bad in (HostileRepr(), HostileIter(), HostileDict()):
            with self.subTest(cls=type(bad).__name__):
                result = lint_sop({"a": bad})
                self.assertEqual(codes_of(result), ["NOT_JSON_NATIVE"])
                self.assertEqual(result[0]["message"], "value is not a JSON-native type")

    def test_diagnostic_shape_is_exact(self):
        result = lint_sop({"a": (1,)})
        self.assertEqual(len(result), 1)
        self.assertEqual(set(result[0]), {"code", "path", "message"})
        self.assertEqual({type(result[0][k]) for k in result[0]}, {str})


class PreflightLimitsTests(unittest.TestCase):
    """Bounded numeric, Unicode and depth limits of the preflight gate."""

    def test_integer_upper_boundary_allowed(self):
        card = valid_card()
        card["policy"]["version"] = 2 ** 53 - 1
        self.assertNotIn("INTEGER_RANGE", codes_of(lint_sop(card)))

    def test_integer_lower_boundary_allowed(self):
        card = valid_card()
        card["policy"]["version"] = -(2 ** 53) + 1
        self.assertNotIn("INTEGER_RANGE", codes_of(lint_sop(card)))

    def test_integers_beyond_2p53_rejected(self):
        for bad in (2 ** 53, -(2 ** 53), 10 ** 30):
            with self.subTest(bad=bad):
                card = valid_card()
                card["policy"]["version"] = bad
                result = lint_sop(card)
                self.assertEqual(codes_of(result), ["INTEGER_RANGE"])
                self.assertEqual(result[0]["path"], "/policy/version")

    def test_bool_not_subject_to_integer_range(self):
        result = lint_sop({"x": True})
        self.assertNotIn("INTEGER_RANGE", codes_of(result))

    def test_nonfinite_floats_rejected(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(bad=bad):
                card = valid_card()
                card["policy"]["version"] = bad
                result = lint_sop(card)
                self.assertEqual(codes_of(result), ["NONFINITE_FLOAT"])
                self.assertEqual(result[0]["path"], "/policy/version")

    def test_nonfinite_inside_nested_list(self):
        result = lint_sop({"a": [1, float("nan")]})
        self.assertEqual(codes_of(result), ["NONFINITE_FLOAT"])
        self.assertEqual(result[0]["path"], "/a/1")

    def test_surrogate_string_value_rejected(self):
        card = valid_card()
        card["policy"]["goal"] = "expense.\ud800accepted"
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["INVALID_UNICODE"])
        self.assertEqual(result[0]["path"], "/policy/goal")
        self.assertEqual(result[0]["message"], "string is not UTF-8 encodable")

    def test_surrogate_object_key_rejected_at_container(self):
        result = lint_sop({"a": {"\ud800": 1}})
        self.assertEqual(codes_of(result), ["INVALID_UNICODE"])
        self.assertEqual(result[0]["path"], "/a")
        self.assertEqual(result[0]["message"], "object key is not UTF-8 encodable")

    def test_depth_64_allowed(self):
        node = 0
        for _ in range(64):
            node = [node]
        self.assertEqual(lint_sop(node), [])

    def test_depth_65_rejected(self):
        node = 0
        for _ in range(65):
            node = [node]
        result = lint_sop(node)
        self.assertEqual(codes_of(result), ["DEPTH_LIMIT"])
        self.assertEqual(result[0]["path"], "/0" * 65)

    def test_depth_limited_subtree_visited_no_further(self):
        node = 0
        for _ in range(80):
            node = [node]
        result = lint_sop(node)
        self.assertEqual(len(result), 1)
        self.assertEqual(codes_of(result), ["DEPTH_LIMIT"])

    def test_wide_tree_lints_fine(self):
        wide = {"k%d" % i: i for i in range(2000)}
        self.assertEqual(lint_sop(wide), [])


class PreflightCycleAliasTests(unittest.TestCase):
    """Active-path identity cycles vs repeated acyclic aliases."""

    def test_self_referencing_list(self):
        cycle = []
        cycle.append(cycle)
        result = lint_sop(cycle)
        self.assertEqual(codes_of(result), ["CYCLE"])
        self.assertEqual(result[0]["path"], "/0")
        self.assertEqual(result[0]["message"], "input object contains a reference cycle")

    def test_self_referencing_dict(self):
        cycle = {}
        cycle["self"] = cycle
        result = lint_sop(cycle)
        self.assertEqual(codes_of(result), ["CYCLE"])
        self.assertEqual(result[0]["path"], "/self")

    def test_indirect_cycle(self):
        a = {}
        b = {"a": a}
        a["b"] = b
        result = lint_sop(a)
        self.assertEqual(codes_of(result), ["CYCLE"])
        self.assertEqual(result[0]["path"], "/b/a")

    def test_two_cycles_both_reported(self):
        c1 = {}
        c1["x"] = c1
        c2 = {}
        c2["y"] = c2
        result = lint_sop({"a": c1, "b": c2})
        self.assertEqual(codes_of(result), ["CYCLE", "CYCLE"])
        self.assertEqual([d["path"] for d in result], ["/a/x", "/b/y"])

    def test_repeated_acyclic_alias_is_valid(self):
        shared = {"k": "v"}
        doc = {"x": shared, "y": shared, "z": [shared, shared]}
        self.assertNotIn("CYCLE", codes_of(lint_sop(doc)))

    def test_alias_inside_valid_card_is_not_a_cycle(self):
        card = valid_card()
        shared = dict(card["rules"][0])
        card["rules"] = [shared, shared]
        self.assertNotIn("CYCLE", codes_of(lint_sop(card)))


class PointerOrderTests(unittest.TestCase):
    """RFC 6901 pointers, (path, code, message) ordering, dedup, stability."""

    def test_pointer_escapes_tilde_and_slash(self):
        result = lint_sop({"a/b": (1,), "m~n": (2,)})
        self.assertEqual([d["path"] for d in result], ["/a~1b", "/m~0n"])
        self.assertEqual(codes_of(result), ["NOT_JSON_NATIVE", "NOT_JSON_NATIVE"])

    def test_result_sorted_by_path_code_message(self):
        doc = {"b": (1,), "a": float("nan"), "c": {"d": float("inf")}}
        result = lint_sop(doc)
        self.assertEqual([d["path"] for d in result], ["/a", "/b", "/c/d"])
        self.assertEqual(result,
                         sorted(result, key=lambda d: (d["path"], d["code"], d["message"])))

    def test_identical_triples_deduplicated(self):
        result = lint_sop({1: "a", 2: "b"})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["code"], "NOT_JSON_NATIVE")
        self.assertEqual(result[0]["path"], "")

    def test_deterministic_across_calls(self):
        doc = {"a": (1,), "b": float("nan"), "c": {"d/d": (3,)}}
        self.assertEqual(lint_sop(doc), lint_sop(doc))

    def test_root_pointer_is_empty_string(self):
        result = lint_sop(())
        self.assertEqual(result[0]["path"], "")

    def test_input_never_mutated(self):
        card = valid_card()
        frozen = copy.deepcopy(card)
        lint_sop(card)
        self.assertEqual(card, frozen)


if __name__ == "__main__":
    unittest.main()
