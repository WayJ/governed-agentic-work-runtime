"""S4 wave 3: strict lint-sop CLI loader, packaged SOP resources, adoption demo."""

import contextlib
import importlib.resources
import io
import json
import re
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from work_runtime import cli
from work_runtime.adoption_demo import (
    SopFileError,
    _safe_text,
    load_sop_bytes,
    load_sop_file,
    packaged_card,
)
from work_runtime.authoring import lint_sop, sop_digest

# Pinned packaged-card digests (S4 foundation integration report).
PINNED_EXPENSE_DIGEST = "4876285f00f5f9ad0287e92825f1aec212e9fc3bce10fd8c073bd2151d817627"
PINNED_PUBLISHING_DIGEST = "56c85d32da9a9eee6330326e2d14ce0661dbc26d782b13d0259c3f149e6be000"
MIB = 1024 * 1024
RESULT_KEYS = ["valid", "digest", "diagnostics", "scope"]

# A minimal lint-clean rule card as JSON text (test fixture; the packaged
# cards under work_runtime/data/sop stay the single example source).
RULE = {
    "id": "R1",
    "source": {"document": "doc", "version": "1", "section": "1.1"},
    "modality": "must", "type": "state", "scope": "document",
    "trigger": "before demo.run", "depends_on": [],
    "requirement": "The demo must be ready", "deadline": "demo.run",
    "evidence": {"kind": "check", "source": "checker", "subject": "document",
                 "version": "digest"},
    "unknown": "block", "conflict": "escalate", "exemption": "forbidden",
    "migration": "explicit",
}
MINIMAL_CARD = {
    "schema_version": 1,
    "policy": {"id": "demo", "version": "1", "goal": "demo.done",
               "source": {"document": "doc", "version": "1", "section": "1"},
               "scope": "document", "capabilities": ["demo.run"]},
    "defaults": {"unknown": "block", "conflict": "escalate",
                 "exemptions": "forbidden", "migration": "explicit"},
    "facts": [], "collections": [], "rules": [RULE], "advice": [],
}


def run_cli(argv):
    """Invoke the CLI in process; return (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            cli.main(argv)
    except SystemExit as raised:
        code = raised.code if isinstance(raised.code, int) else 1
    return code, out.getvalue(), err.getvalue()


def write_file(directory, name, payload):
    path = Path(directory) / name
    if isinstance(payload, bytes):
        path.write_bytes(payload)
    else:
        path.write_text(payload, encoding="utf-8")
    return path


def with_surrogate(card, field, value):
    """Return card JSON text with ``field`` replaced by a lone surrogate.

    Written as raw JSON text so the surrogate stays escaped (loader-clean)
    instead of crashing this test module's own string handling.
    """
    text = json.dumps(card, ensure_ascii=True, indent=2)
    pattern = '"%s": ' % field
    start = text.index(pattern) + len(pattern)
    end = text.index("\n", start)
    return text[:start] + json.dumps(value, ensure_ascii=True) + "," + text[end:]


class LintCleanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_packaged_publishing_card_json_result(self):
        path = write_file(self.temp.name, "publishing.json",
                          importlib.resources.files("work_runtime")
                          .joinpath("data", "sop", "publishing.json").read_bytes())
        code, out, err = run_cli(["lint-sop", str(path), "--json"])
        self.assertEqual(code, 0, out + err)
        result = json.loads(out)
        self.assertEqual(list(result), RESULT_KEYS)
        self.assertEqual(result, {"valid": True, "digest": PINNED_PUBLISHING_DIGEST,
                                  "diagnostics": [], "scope": "static-only"})

    def test_packaged_expense_card_json_result(self):
        path = write_file(self.temp.name, "expense.json",
                          importlib.resources.files("work_runtime")
                          .joinpath("data", "sop", "expense.json").read_bytes())
        code, out, err = run_cli(["lint-sop", str(path), "--json"])
        self.assertEqual(code, 0, out + err)
        self.assertEqual(json.loads(out)["digest"], PINNED_EXPENSE_DIGEST)

    def test_clean_human_output_prints_digest_and_static_limit(self):
        path = write_file(self.temp.name, "card.json", json.dumps(MINIMAL_CARD))
        code, out, err = run_cli(["lint-sop", str(path)])
        self.assertEqual(code, 0, out + err)
        self.assertIn(sop_digest(MINIMAL_CARD), out)
        self.assertIn("static", out.lower())
        self.assertNotIn('"valid"', out)


class LintDefectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_defect_card_json_exits_one_with_sorted_diagnostics(self):
        card = dict(MINIMAL_CARD)
        del card["defaults"]
        card["extra"] = 1
        path = write_file(self.temp.name, "card.json", json.dumps(card))
        code, out, err = run_cli(["lint-sop", str(path), "--json"])
        self.assertEqual(code, 1, out + err)
        result = json.loads(out)
        self.assertEqual(list(result), RESULT_KEYS)
        self.assertIs(result["valid"], False)
        self.assertIsNone(result["digest"])
        self.assertEqual(result["scope"], "static-only")
        codes = {d["code"] for d in result["diagnostics"]}
        self.assertEqual(codes, {"MISSING_FIELD", "UNKNOWN_FIELD"})
        for diagnostic in result["diagnostics"]:
            self.assertEqual(list(diagnostic), ["code", "path", "message"])
        triples = [(d["path"], d["code"], d["message"]) for d in result["diagnostics"]]
        self.assertEqual(triples, sorted(triples))

    def test_defect_card_human_exits_one_without_traceback(self):
        card = dict(MINIMAL_CARD)
        card["rules"] = []
        path = write_file(self.temp.name, "card.json", json.dumps(card))
        code, out, err = run_cli(["lint-sop", str(path)])
        self.assertEqual(code, 1, out + err)
        self.assertIn("NO_MANDATORY_RULE", out)
        self.assertNotIn("Traceback", out + err)
        self.assertIn("static", out.lower())

    def test_escaped_surrogate_value_is_linter_exit_one_json(self):
        path = write_file(self.temp.name, "card.json",
                          with_surrogate(MINIMAL_CARD, "goal", "\ud800"))
        code, out, err = run_cli(["lint-sop", str(path), "--json"])
        self.assertEqual(code, 1, out + err)
        out.encode("utf-8")  # Lone surrogates in stdout would raise here.
        result = json.loads(out)
        self.assertIs(result["valid"], False)
        self.assertEqual(result["diagnostics"][0]["code"], "INVALID_UNICODE")
        self.assertEqual(result["diagnostics"][0]["path"], "/policy/goal")

    def test_escaped_surrogate_value_human_output_stays_printable(self):
        path = write_file(self.temp.name, "card.json",
                          with_surrogate(MINIMAL_CARD, "requirement", "\ud800fire"))
        code, out, err = run_cli(["lint-sop", str(path)])
        self.assertEqual(code, 1, out + err)
        out.encode("utf-8")
        self.assertIn("INVALID_UNICODE", out)

    def test_escaped_surrogate_key_is_linter_exit_one(self):
        card = json.loads(json.dumps(MINIMAL_CARD))
        card["policy"]["\ud800bad"] = 1
        path = write_file(self.temp.name, "card.json", json.dumps(card, ensure_ascii=True))
        for argv in (["lint-sop", str(path)], ["lint-sop", str(path), "--json"]):
            code, out, err = run_cli(argv)
            self.assertEqual(code, 1, out + err)
            out.encode("utf-8")
            if "--json" in argv:
                self.assertEqual(json.loads(out)["diagnostics"][0]["code"],
                                 "INVALID_UNICODE")


class LoaderExit2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def assert_exit2(self, payload, code, name="case.json"):
        path = write_file(self.temp.name, name, payload)
        result_code, out, err = run_cli(["lint-sop", str(path), "--json"])
        self.assertEqual(result_code, 2, out + err)
        result = json.loads(out)
        self.assertEqual(list(result), RESULT_KEYS)
        self.assertIs(result["valid"], False)
        self.assertIsNone(result["digest"])
        self.assertEqual(result["scope"], "static-only")
        self.assertEqual(len(result["diagnostics"]), 1)
        diagnostic = result["diagnostics"][0]
        self.assertEqual(diagnostic["code"], code)
        self.assertEqual(diagnostic["path"], "")
        self.assertTrue(diagnostic["message"])

    def test_duplicate_top_level_key_exits_two(self):
        self.assert_exit2('{"schema_version": 1, "schema_version": 1}',
                          "DUPLICATE_OBJECT_KEY")

    def test_duplicate_nested_key_exits_two(self):
        card = json.loads(json.dumps(MINIMAL_CARD))
        card["policy"]["id"] = "demo"
        text = json.dumps(card)
        text = text.replace('"policy": {', '"policy": {"id": "other",', 1)
        self.assert_exit2(text, "DUPLICATE_OBJECT_KEY")

    def test_nonfinite_literals_exit_two(self):
        for literal in ("NaN", "Infinity", "-Infinity"):
            self.assert_exit2('{"policy": {"note": %s}}' % literal,
                              "NONFINITE_LITERAL", name="%s.json" % literal)

    def test_malformed_json_exits_two(self):
        self.assert_exit2('{"schema_version": 1,', "MALFORMED_JSON")

    def test_invalid_utf8_bytes_exit_two(self):
        self.assert_exit2(b'{"goal": "\xff\xfe"}', "INVALID_UTF8")

    def test_missing_file_exits_two(self):
        code, _, err = run_cli(["lint-sop", str(Path(self.temp.name) / "nope.json")])
        self.assertEqual(code, 2)
        self.assertIn("FILE_UNREADABLE", err)

    def test_directory_as_file_exits_two(self):
        code, out, _ = run_cli(["lint-sop", self.temp.name, "--json"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["diagnostics"][0]["code"], "FILE_UNREADABLE")

    def test_oversized_file_exits_two(self):
        self.assert_exit2(b" " * (MIB + 1), "FILE_TOO_LARGE")

    def test_exactly_one_mib_file_is_loaded_not_rejected(self):
        path = write_file(self.temp.name, "big.json", b'"' + b"a" * (MIB - 2) + b'"')
        code, out, err = run_cli(["lint-sop", str(path), "--json"])
        self.assertEqual(code, 1, out + err)  # Loads; a JSON string is not a card.
        self.assertEqual(json.loads(out)["diagnostics"][0]["code"], "TYPE_MISMATCH")

    def test_deep_nesting_exits_two_without_traceback(self):
        path = write_file(self.temp.name, "deep.json", b"[" * 20000 + b"]" * 20000)
        code, out, err = run_cli(["lint-sop", str(path)])
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", out + err)
        self.assertIn("DEEP_JSON", err)

    def test_loader_errors_use_bounded_static_messages(self):
        for payload, code in ((b"{", "MALFORMED_JSON"),
                              (b'{"a":1,"a":1}', "DUPLICATE_OBJECT_KEY"),
                              (b"\xff\xfe", "INVALID_UTF8")):
            with self.subTest(code=code):
                with self.assertRaises(SopFileError) as raised:
                    load_sop_bytes(payload)
                self.assertEqual(raised.exception.code, code)
                self.assertTrue(str(raised.exception))  # A bounded static message.


class SecretEchoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_duplicate_key_never_echoes_the_doomed_value(self):
        path = write_file(self.temp.name, "card.json",
                          '{"api_token": "s3cret-dupe-8613", "api_token": "x"}')
        code, out, err = run_cli(["lint-sop", str(path), "--json"])
        self.assertEqual(code, 2)
        self.assertNotIn("s3cret-dupe-8613", out + err)

    def test_malformed_file_never_echoes_its_contents(self):
        path = write_file(self.temp.name, "card.json",
                          '{"secret_field": "s3cret-parse-8613",')
        code, out, err = run_cli(["lint-sop", str(path)])
        self.assertEqual(code, 2)
        self.assertNotIn("s3cret-parse-8613", out + err)


class PackagedResourceTests(unittest.TestCase):
    def test_packaged_cards_lint_clean_with_pinned_digests(self):
        for name, pinned in (("expense.json", PINNED_EXPENSE_DIGEST),
                             ("publishing.json", PINNED_PUBLISHING_DIGEST)):
            with self.subTest(card=name):
                card = packaged_card(name)
                self.assertEqual(lint_sop(card), [])
                self.assertEqual(sop_digest(card), pinned)

    def test_packaged_resources_resolve_under_the_package(self):
        base = importlib.resources.files("work_runtime")
        for name in ("expense.json", "publishing.json"):
            resource = base.joinpath("data", "sop", name)
            self.assertTrue(resource.is_file(), name)
            self.assertTrue(resource.read_bytes(), name)

    def test_load_sop_file_reports_unreadable_files(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(SopFileError) as raised:
                load_sop_file(Path(folder) / "absent.json")
            self.assertEqual(raised.exception.code, "FILE_UNREADABLE")

    def test_safe_text_keeps_lone_surrogates_printable(self):
        cleaned = _safe_text("path-\ud800-key")
        cleaned.encode("utf-8")  # Must not raise.
        self.assertIn("\\ud800", cleaned)


class LintCliUsageTests(unittest.TestCase):
    def test_missing_path_is_a_usage_error(self):
        code, _, err = run_cli(["lint-sop"])
        self.assertEqual(code, 2)
        self.assertIn("usage", err.lower())

    def test_unknown_flag_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "card.json"
            path.write_text("{}", encoding="utf-8")
            code, _, err = run_cli(["lint-sop", str(path), "--yaml"])
            self.assertEqual(code, 2)
            self.assertIn("usage", err.lower())


if __name__ == "__main__":
    unittest.main()
