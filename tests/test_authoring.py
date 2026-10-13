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
        # Only the (expected) root-shape complaint; no DEPTH_LIMIT.
        self.assertEqual(codes_of(lint_sop(node)), ["TYPE_MISMATCH"])

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
        card = valid_card()
        card["advice"] = ["advice item %d" % i for i in range(2000)]
        self.assertEqual(lint_sop(card), [])


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



class RootSchemaTests(unittest.TestCase):
    """Root object shape and schema_version checks."""

    def test_non_object_root_is_type_mismatch(self):
        for bad in ([1], "card", 1, None, True):
            with self.subTest(bad=bad):
                result = lint_sop(bad)
                self.assertEqual(codes_of(result), ["TYPE_MISMATCH"])
                self.assertEqual(result[0]["path"], "")
                self.assertEqual(result[0]["message"], "value must be an object")

    def test_every_root_field_required(self):
        for field in ("schema_version", "policy", "defaults", "facts",
                      "collections", "rules", "advice"):
            with self.subTest(field=field):
                card = valid_card()
                del card[field]
                result = lint_sop(card)
                self.assertIn("MISSING_FIELD", codes_of(result))
                self.assertEqual(result[0]["path"], "")
                self.assertEqual(result[0]["message"], "missing required field '%s'" % field)

    def test_unknown_root_field_anchored_at_key(self):
        card = valid_card()
        card["extra"] = 1
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["UNKNOWN_FIELD"])
        self.assertEqual(result[0]["path"], "/extra")
        self.assertEqual(result[0]["message"], "unknown field 'extra'")

    def test_multiple_missing_root_fields_sorted(self):
        card = valid_card()
        del card["advice"]
        del card["rules"]
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["MISSING_FIELD", "MISSING_FIELD"])
        self.assertEqual([d["message"] for d in result],
                         ["missing required field 'advice'", "missing required field 'rules'"])

    def test_schema_version_must_be_integer_one(self):
        for bad, code in ((2, "INVALID_VALUE"), (0, "INVALID_VALUE"), (-1, "INVALID_VALUE"),
                          ("1", "TYPE_MISMATCH"), (True, "TYPE_MISMATCH"),
                          (1.0, "TYPE_MISMATCH"), (None, "TYPE_MISMATCH")):
            with self.subTest(bad=bad):
                card = valid_card()
                card["schema_version"] = bad
                result = lint_sop(card)
                self.assertEqual(codes_of(result), [code])
                self.assertEqual(result[0]["path"], "/schema_version")

    def test_schema_version_messages(self):
        card = valid_card()
        card["schema_version"] = True
        self.assertEqual(lint_sop(card)[0]["message"], "field must be an integer")
        card = valid_card()
        card["schema_version"] = 2
        self.assertEqual(lint_sop(card)[0]["message"], "schema_version must be 1")


class PolicySectionTests(unittest.TestCase):
    """Policy identity, provenance source, scope shape and capabilities."""

    def test_policy_must_be_object(self):
        card = valid_card()
        card["policy"] = []
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["TYPE_MISMATCH"])
        self.assertEqual(result[0]["path"], "/policy")
        self.assertEqual(result[0]["message"], "value must be an object")

    def test_every_policy_field_required(self):
        for field in ("id", "version", "goal", "source", "scope", "capabilities"):
            with self.subTest(field=field):
                card = valid_card()
                del card["policy"][field]
                result = lint_sop(card)
                self.assertEqual(codes_of(result), ["MISSING_FIELD"])
                self.assertEqual(result[0]["path"], "/policy")
                self.assertEqual(result[0]["message"], "missing required field '%s'" % field)

    def test_unknown_policy_field(self):
        card = valid_card()
        card["policy"]["note"] = "x"
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["UNKNOWN_FIELD"])
        self.assertEqual(result[0]["path"], "/policy/note")

    def test_identity_fields_reject_wrong_type_empty_and_whitespace(self):
        for field in ("id", "version", "goal"):
            for bad, code in ((5, "TYPE_MISMATCH"), (None, "TYPE_MISMATCH"),
                              ("", "EMPTY_VALUE"), ("  \t ", "EMPTY_VALUE")):
                with self.subTest(field=field, bad=bad):
                    card = valid_card()
                    card["policy"][field] = bad
                    result = lint_sop(card)
                    self.assertEqual(codes_of(result), [code])
                    self.assertEqual(result[0]["path"], "/policy/" + field)
                    if code == "TYPE_MISMATCH":
                        self.assertEqual(result[0]["message"], "field must be a string")
                    else:
                        self.assertEqual(result[0]["message"],
                                         "string is empty or whitespace-only")

    def test_source_shape(self):
        card = valid_card()
        card["policy"]["source"] = "handbook"
        self.assertEqual(codes_of(lint_sop(card)), ["TYPE_MISMATCH"])
        card = valid_card()
        del card["policy"]["source"]["section"]
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["MISSING_FIELD"])
        self.assertEqual(result[0]["path"], "/policy/source")
        card = valid_card()
        card["policy"]["source"]["page"] = 4
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["UNKNOWN_FIELD"])
        self.assertEqual(result[0]["path"], "/policy/source/page")
        card = valid_card()
        card["policy"]["source"]["document"] = ""
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["EMPTY_VALUE"])
        self.assertEqual(result[0]["path"], "/policy/source/document")

    def test_policy_scope_shape_only(self):
        # Reference resolution (declared collections) is a later layer;
        # here only string shape and emptiness are checked.
        card = valid_card()
        card["policy"]["scope"] = 5
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["TYPE_MISMATCH"])
        self.assertEqual(result[0]["path"], "/policy/scope")
        card = valid_card()
        card["policy"]["scope"] = "  "
        self.assertEqual(codes_of(lint_sop(card))[0], "EMPTY_VALUE")

    def test_capabilities_must_be_list(self):
        card = valid_card()
        card["policy"]["capabilities"] = "expense.submit"
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["TYPE_MISMATCH"])
        self.assertEqual(result[0]["path"], "/policy/capabilities")
        self.assertEqual(result[0]["message"], "field must be a list")

    def test_capability_element_checks(self):
        for bad, code in ((5, "TYPE_MISMATCH"), ("", "EMPTY_VALUE"), ("  ", "EMPTY_VALUE")):
            with self.subTest(bad=bad):
                card = valid_card()
                card["policy"]["capabilities"] = [bad]
                result = lint_sop(card)
                self.assertEqual(codes_of(result), [code])
                self.assertEqual(result[0]["path"], "/policy/capabilities/0")

    def test_duplicate_capability_is_duplicate_id(self):
        card = valid_card()
        card["policy"]["capabilities"] = ["expense.submit", "expense.read", "expense.submit"]
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["DUPLICATE_ID"])
        self.assertEqual(result[0]["path"], "/policy/capabilities/2")
        self.assertEqual(result[0]["message"], "duplicate capability 'expense.submit'")

    def test_goal_capability_is_reserved(self):
        card = valid_card()
        card["policy"]["capabilities"] = ["goal"]
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["INVALID_VALUE"])
        self.assertEqual(result[0]["path"], "/policy/capabilities/0")
        self.assertEqual(result[0]["message"],
                         "capability 'goal' is reserved as the goal-boundary deadline token")

    def test_empty_capabilities_list_allowed(self):
        card = valid_card()
        card["policy"]["capabilities"] = []
        self.assertEqual(lint_sop(card), [])


class DefaultsTests(unittest.TestCase):
    """Defaults object: exact fields, exact pinned values."""

    def test_defaults_must_be_object(self):
        card = valid_card()
        card["defaults"] = []
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["TYPE_MISMATCH"])
        self.assertEqual(result[0]["path"], "/defaults")

    def test_every_defaults_field_required(self):
        for field in ("unknown", "conflict", "exemptions", "migration"):
            with self.subTest(field=field):
                card = valid_card()
                del card["defaults"][field]
                result = lint_sop(card)
                self.assertEqual(codes_of(result), ["MISSING_FIELD"])
                self.assertEqual(result[0]["path"], "/defaults")

    def test_unknown_defaults_field(self):
        card = valid_card()
        card["defaults"]["deadline"] = "goal"
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["UNKNOWN_FIELD"])
        self.assertEqual(result[0]["path"], "/defaults/deadline")

    def test_defaults_values_are_pinned(self):
        pinned = {"unknown": "block", "conflict": "escalate",
                  "exemptions": "forbidden", "migration": "explicit"}
        for field, expected in pinned.items():
            for bad in ("ask", "ignore", "BLOCK", ""):
                with self.subTest(field=field, bad=bad):
                    card = valid_card()
                    card["defaults"][field] = bad
                    result = lint_sop(card)
                    self.assertEqual(codes_of(result), ["INVALID_VALUE"])
                    self.assertEqual(result[0]["path"], "/defaults/" + field)
                    self.assertEqual(result[0]["message"],
                                     "value must be '%s'" % expected)

    def test_defaults_non_string_is_type_mismatch(self):
        card = valid_card()
        card["defaults"]["unknown"] = 1
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["TYPE_MISMATCH"])
        self.assertEqual(result[0]["path"], "/defaults/unknown")
        self.assertEqual(result[0]["message"], "field must be a string")



class FactsCollectionsTests(unittest.TestCase):
    """Facts ({id} exactly) and collections (id/version/completeness/allow_empty)."""

    def test_facts_must_be_list(self):
        card = valid_card()
        card["facts"] = "none"
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["TYPE_MISMATCH"])
        self.assertEqual(result[0]["path"], "/facts")
        self.assertEqual(result[0]["message"], "field must be a list")

    def test_fact_is_exactly_an_id(self):
        card = valid_card()
        card["facts"] = [{"id": "invoice.valid", "note": "x"}]
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["UNKNOWN_FIELD"])
        self.assertEqual(result[0]["path"], "/facts/0/note")
        card = valid_card()
        card["facts"] = [{}]
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["MISSING_FIELD"])
        self.assertEqual(result[0]["path"], "/facts/0")
        card = valid_card()
        card["facts"] = [42]
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["TYPE_MISMATCH"])
        self.assertEqual(result[0]["path"], "/facts/0")

    def test_fact_id_text_checks(self):
        for bad, code in ((5, "TYPE_MISMATCH"), ("", "EMPTY_VALUE"), (" \t ", "EMPTY_VALUE")):
            with self.subTest(bad=bad):
                card = valid_card()
                card["facts"] = [{"id": bad}]
                result = lint_sop(card)
                self.assertEqual(codes_of(result), [code])
                self.assertEqual(result[0]["path"], "/facts/0/id")

    def test_empty_facts_allowed(self):
        card = valid_card()
        card["facts"] = []
        card["rules"][0]["depends_on"] = []
        self.assertEqual(lint_sop(card), [])

    def test_collections_must_be_list(self):
        card = valid_card()
        card["collections"] = {}
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["TYPE_MISMATCH"])
        self.assertEqual(result[0]["path"], "/collections")

    def test_collection_exact_fields(self):
        card = valid_card()
        del card["collections"][0]["completeness"]
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["MISSING_FIELD"])
        self.assertEqual(result[0]["path"], "/collections/0")
        card = valid_card()
        card["collections"][0]["owner"] = "finance"
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["UNKNOWN_FIELD"])
        self.assertEqual(result[0]["path"], "/collections/0/owner")

    def test_collection_text_fields(self):
        for field in ("id", "version", "completeness"):
            for bad, code in ((None, "TYPE_MISMATCH"), ("", "EMPTY_VALUE")):
                with self.subTest(field=field, bad=bad):
                    card = valid_card()
                    card["collections"][0][field] = bad
                    result = lint_sop(card)
                    self.assertEqual(codes_of(result), [code])
                    self.assertEqual(result[0]["path"], "/collections/0/" + field)

    def test_collection_allow_empty_strict_boolean(self):
        for bad in ("false", 1, 0, None, []):
            with self.subTest(bad=bad):
                card = valid_card()
                card["collections"][0]["allow_empty"] = bad
                result = lint_sop(card)
                self.assertEqual(codes_of(result), ["TYPE_MISMATCH"])
                self.assertEqual(result[0]["path"], "/collections/0/allow_empty")
                self.assertEqual(result[0]["message"], "field must be a boolean")

    def test_collection_id_document_is_reserved(self):
        card = valid_card()
        card["collections"] = [{"id": "document", "version": "v1",
                                "completeness": "sealed", "allow_empty": False}]
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["INVALID_VALUE"])
        self.assertEqual(result[0]["path"], "/collections/0/id")
        self.assertEqual(result[0]["message"],
                         "collection id 'document' is reserved as the "
                         "business-document scope token")

    def test_empty_collections_allowed(self):
        card = valid_card()
        card["collections"] = []
        card["rules"][0]["scope"] = "document"
        self.assertEqual(lint_sop(card), [])


class GlobalIdNamespaceTests(unittest.TestCase):
    """Fact, collection and rule IDs share one namespace (D22 B1)."""

    def test_duplicate_fact_ids(self):
        card = valid_card()
        card["facts"] = [{"id": "invoice.valid"}, {"id": "amount.known"},
                         {"id": "invoice.valid"}]
        card["rules"][0]["depends_on"] = []
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["DUPLICATE_ID"])
        self.assertEqual(result[0]["path"], "/facts/2/id")
        self.assertEqual(result[0]["message"], "duplicate ID 'invoice.valid'")

    def test_duplicate_collection_ids(self):
        card = valid_card()
        card["collections"].append(dict(card["collections"][0]))
        card["rules"][0]["scope"] = "document"
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["DUPLICATE_ID"])
        self.assertEqual(result[0]["path"], "/collections/1/id")

    def test_duplicate_rule_ids(self):
        card = valid_card()
        card["rules"].append(dict(card["rules"][0]))
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["DUPLICATE_ID"])
        self.assertEqual(result[0]["path"], "/rules/2/id")

    def test_collection_colliding_with_fact(self):
        card = valid_card()
        card["collections"].append({"id": "invoice.valid", "version": "v1",
                                    "completeness": "sealed", "allow_empty": False})
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["DUPLICATE_ID"])
        self.assertEqual(result[0]["path"], "/collections/1/id")

    def test_rule_colliding_with_fact(self):
        card = valid_card()
        card["rules"][1]["id"] = "invoice.valid"
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["DUPLICATE_ID"])
        self.assertEqual(result[0]["path"], "/rules/1/id")

    def test_rule_colliding_with_collection(self):
        card = valid_card()
        card["rules"][1]["id"] = "expense.invoices"
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["DUPLICATE_ID"])
        self.assertEqual(result[0]["path"], "/rules/1/id")

    def test_triple_collision_reports_each_later_occurrence(self):
        card = valid_card()
        card["collections"].append({"id": "invoice.valid", "version": "v1",
                                    "completeness": "sealed", "allow_empty": False})
        card["rules"][1]["id"] = "invoice.valid"
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["DUPLICATE_ID", "DUPLICATE_ID"])
        self.assertEqual([d["path"] for d in result],
                         ["/collections/1/id", "/rules/1/id"])

    def test_rule_id_still_collected_when_rule_schema_unchecked(self):
        # The namespace spans rules even before/without their full check.
        card = valid_card()
        card["facts"].append({"id": "E01"})
        result = lint_sop(card)
        # Facts are collected before rules, so the rule is the later
        # occurrence and carries the diagnostic.
        self.assertEqual(codes_of(result), ["DUPLICATE_ID"])
        self.assertEqual(result[0]["path"], "/rules/0/id")
        self.assertEqual(result[0]["message"], "duplicate ID 'E01'")



RULE_FIELDS = ("id", "source", "modality", "type", "scope", "trigger",
               "depends_on", "requirement", "deadline", "evidence",
               "unknown", "conflict", "exemption", "migration")


class RulesSchemaTests(unittest.TestCase):
    """Rule cards: all fourteen fields, exact shapes, pinned enums."""

    def test_rules_must_be_list(self):
        card = valid_card()
        card["rules"] = "none"
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["TYPE_MISMATCH"])
        self.assertEqual(result[0]["path"], "/rules")
        self.assertEqual(result[0]["message"], "field must be a list")

    def test_rule_must_be_object(self):
        card = valid_card()
        card["rules"] = ["E01"]
        # The list exists but holds no mandatory rule, so cardinality fires too.
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["NO_MANDATORY_RULE", "TYPE_MISMATCH"])
        self.assertEqual(result[1]["path"], "/rules/0")

    def test_every_rule_field_required(self):
        for field in RULE_FIELDS:
            with self.subTest(field=field):
                card = valid_card()
                del card["rules"][0][field]
                result = lint_sop(card)
                self.assertIn("MISSING_FIELD", codes_of(result))
                missing = [d for d in result
                           if d["code"] == "MISSING_FIELD" and d["path"] == "/rules/0"]
                self.assertEqual(missing[0]["message"],
                                 "missing required field '%s'" % field)

    def test_unknown_rule_field(self):
        card = valid_card()
        card["rules"][0]["note"] = "why"
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["UNKNOWN_FIELD"])
        self.assertEqual(result[0]["path"], "/rules/0/note")

    def test_modality_enum(self):
        for bad, code in (("should", "INVALID_VALUE"), ("MUST", "INVALID_VALUE"),
                          (5, "TYPE_MISMATCH"), (None, "TYPE_MISMATCH")):
            with self.subTest(bad=bad):
                card = valid_card()
                card["rules"][0]["modality"] = bad
                result = lint_sop(card)
                self.assertEqual(codes_of(result), [code])
                self.assertEqual(result[0]["path"], "/rules/0/modality")
                if code == "INVALID_VALUE":
                    self.assertEqual(result[0]["message"],
                                     "value must be 'must' or 'forbidden'")

    def test_type_enum(self):
        for bad, code in (("state-change", "INVALID_VALUE"), ([], "TYPE_MISMATCH")):
            with self.subTest(bad=bad):
                card = valid_card()
                card["rules"][0]["type"] = bad
                result = lint_sop(card)
                self.assertEqual(codes_of(result), [code])
                self.assertEqual(result[0]["path"], "/rules/0/type")
                if code == "INVALID_VALUE":
                    self.assertEqual(result[0]["message"],
                                     "value must be 'state', 'action' or 'history'")

    def test_rule_source_shape(self):
        card = valid_card()
        card["rules"][0]["source"] = []
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["TYPE_MISMATCH"])
        self.assertEqual(result[0]["path"], "/rules/0/source")
        card = valid_card()
        card["rules"][0]["source"]["section"] = " "
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["EMPTY_VALUE"])
        self.assertEqual(result[0]["path"], "/rules/0/source/section")

    def test_rule_scope_shape(self):
        card = valid_card()
        card["rules"][0]["scope"] = 5
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["TYPE_MISMATCH"])
        self.assertEqual(result[0]["path"], "/rules/0/scope")

    def test_trigger_and_requirement_text(self):
        for field in ("trigger", "requirement"):
            for bad, code in (("", "EMPTY_VALUE"), ("\n\t", "EMPTY_VALUE"),
                              (7, "TYPE_MISMATCH")):
                with self.subTest(field=field, bad=bad):
                    card = valid_card()
                    card["rules"][0][field] = bad
                    result = lint_sop(card)
                    self.assertEqual(codes_of(result), [code])
                    self.assertEqual(result[0]["path"], "/rules/0/" + field)

    def test_depends_on_shape(self):
        card = valid_card()
        card["rules"][0]["depends_on"] = "invoice.valid"
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["TYPE_MISMATCH"])
        self.assertEqual(result[0]["path"], "/rules/0/depends_on")
        card = valid_card()
        card["rules"][0]["depends_on"] = [5]
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["TYPE_MISMATCH"])
        self.assertEqual(result[0]["path"], "/rules/0/depends_on/0")
        card = valid_card()
        card["rules"][0]["depends_on"] = [" "]
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["EMPTY_VALUE"])
        self.assertEqual(result[0]["path"], "/rules/0/depends_on/0")

    def test_deadline_shape(self):
        card = valid_card()
        card["rules"][0]["deadline"] = []
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["TYPE_MISMATCH"])
        self.assertEqual(result[0]["path"], "/rules/0/deadline")

    def test_evidence_shape(self):
        card = valid_card()
        card["rules"][0]["evidence"] = "kind"
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["TYPE_MISMATCH"])
        self.assertEqual(result[0]["path"], "/rules/0/evidence")
        card = valid_card()
        del card["rules"][0]["evidence"]["kind"]
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["MISSING_FIELD"])
        self.assertEqual(result[0]["path"], "/rules/0/evidence")
        card = valid_card()
        card["rules"][0]["evidence"]["format"] = "pdf"
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["UNKNOWN_FIELD"])
        self.assertEqual(result[0]["path"], "/rules/0/evidence/format")
        card = valid_card()
        card["rules"][0]["evidence"]["subject"] = ""
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["EMPTY_VALUE"])
        self.assertEqual(result[0]["path"], "/rules/0/evidence/subject")

    def test_fixed_handling_values(self):
        pinned = {"unknown": "block", "conflict": "escalate",
                  "exemption": "forbidden", "migration": "explicit"}
        for field, expected in pinned.items():
            for bad in ("ask", "allowed", "", None):
                with self.subTest(field=field, bad=bad):
                    card = valid_card()
                    card["rules"][0][field] = bad
                    result = lint_sop(card)
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0]["path"], "/rules/0/" + field)
                    if type(bad) is not str:
                        self.assertEqual(result[0]["code"], "TYPE_MISMATCH")
                    else:
                        self.assertEqual(result[0]["code"], "INVALID_VALUE")
                        self.assertEqual(result[0]["message"],
                                         "value must be '%s'" % expected)


class AdviceTests(unittest.TestCase):
    """Advice strings stay separate from mandatory rules."""

    def test_advice_must_be_list(self):
        card = valid_card()
        card["advice"] = "be careful"
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["TYPE_MISMATCH"])
        self.assertEqual(result[0]["path"], "/advice")

    def test_advice_elements_must_be_nonempty_strings(self):
        for bad, code in ((5, "TYPE_MISMATCH"), ("", "EMPTY_VALUE"), ("  ", "EMPTY_VALUE")):
            with self.subTest(bad=bad):
                card = valid_card()
                card["advice"] = [bad]
                result = lint_sop(card)
                self.assertEqual(codes_of(result), [code])
                self.assertEqual(result[0]["path"], "/advice/0")

    def test_empty_advice_allowed(self):
        card = valid_card()
        card["advice"] = []
        self.assertEqual(lint_sop(card), [])


class MandatoryRuleTests(unittest.TestCase):
    """At least one mandatory (must or forbidden) rule; D22 B3."""

    def test_empty_rules_gives_no_mandatory_rule(self):
        card = valid_card()
        card["rules"] = []
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["NO_MANDATORY_RULE"])
        self.assertEqual(result[0]["path"], "/rules")
        self.assertEqual(result[0]["message"],
                         "package has no mandatory (must or forbidden) rule")

    def test_all_forbidden_package_is_valid(self):
        card = valid_card()
        card["rules"][0]["modality"] = "forbidden"
        self.assertEqual(lint_sop(card), [])

    def test_advice_never_satisfies_mandatory_cardinality(self):
        card = valid_card()
        card["rules"] = []
        card["advice"] = ["Verify invoices", "Confirm amounts", "Respect limits"]
        self.assertEqual(codes_of(lint_sop(card)), ["NO_MANDATORY_RULE"])

    def test_invalid_modality_does_not_count_as_mandatory(self):
        card = valid_card()
        card["rules"] = [card["rules"][1]]
        card["rules"][0]["modality"] = "should"
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["NO_MANDATORY_RULE", "INVALID_VALUE"])
        self.assertEqual([d["path"] for d in result], ["/rules", "/rules/0/modality"])

    def test_malformed_rules_list_skips_cardinality(self):
        card = valid_card()
        card["rules"] = "none"
        result = lint_sop(card)
        self.assertEqual(codes_of(result), ["TYPE_MISMATCH"])


if __name__ == "__main__":
    unittest.main()
