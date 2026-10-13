"""Tests for scripts/check_docs.py, the local Markdown link checker."""

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_docs.py"

_spec = importlib.util.spec_from_file_location("check_docs", SCRIPT)
check_docs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_docs)


def write(root, relpath, content):
    path = Path(root) / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class CheckDocsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def check(self):
        return check_docs.check(self.root)

    def findings(self):
        return self.check()[2]

    def run_cli(self):
        return subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root)],
                              capture_output=True, text=True)

    def test_valid_links_pass(self):
        write(self.root, "target.md", "# t\n")
        write(self.root, "sp ace.md", "# t\n")
        write(self.root, "docs/child.md", "[up](../target.md)\n")
        write(self.root, "index.md",
              "[plain](target.md)\n[encoded](sp%20ace.md)\n[dir](docs)\n"
              "[fragment](target.md#section)\n")
        self.assertEqual(self.check(), (4, 5, []))

    def test_broken_link_reported_with_location(self):
        write(self.root, "index.md", "intro\n[missing](gone.md)\n")
        files, links, findings = self.check()
        self.assertEqual((files, links), (1, 1))
        source, line, target = findings[0]
        self.assertEqual(source, self.root / "index.md")
        self.assertEqual(line, 2)
        self.assertEqual(target, "gone.md")

    def test_external_urls_and_mailto_skipped(self):
        write(self.root, "index.md",
              "[web](https://example.com/a.md)\n[site](http://example.com)\n"
              "[mail](mailto:a@b.example)\n[ftp](ftp://h/x.md)\n")
        self.assertEqual(self.check(), (1, 0, []))

    def test_pure_anchor_and_empty_links_skipped(self):
        write(self.root, "index.md", "[jump](#section)\n[empty]()\n")
        self.assertEqual(self.check(), (1, 0, []))

    def test_fragment_targets_check_file_only(self):
        write(self.root, "there.md", "x\n")
        write(self.root, "index.md", "[ok](there.md#anchor)\n[bad](nowhere.md#anchor)\n")
        findings = self.findings()
        self.assertEqual([(f[1], f[2]) for f in findings], [(2, "nowhere.md#anchor")])

    def test_fenced_code_blocks_skipped(self):
        write(self.root, "keep.md", "x\n")
        write(self.root, "index.md",
              "```text\n[bad](gone.md)\n```\n"
              "~~~\n[bad2](gone2.md)\n~~~\n"
              "   ```\n[bad3](gone3.md)\n   ```\n"
              "[good](keep.md)\n[after](nope.md)\n")
        findings = self.findings()
        self.assertEqual([f[2] for f in findings], ["nope.md"])

    def test_inline_code_spans_skipped(self):
        write(self.root, "index.md", "run `[x](broken.md)` now\n[real](also-broken.md)\n")
        findings = self.findings()
        self.assertEqual([f[2] for f in findings], ["also-broken.md"])

    def test_reference_links_checked(self):
        write(self.root, "ok.md", "x\n")
        write(self.root, "index.md",
              "[text][ref]\n[uses uppercase][REF2]\n\n"
              "[REF]: ok.md\n[ref2]: missing.md\n")
        findings = self.findings()
        self.assertEqual([(f[1], f[2]) for f in findings], [(2, "missing.md")])

    def test_images_checked(self):
        write(self.root, "index.md", "![logo](pics/logo.png)\n")
        findings = self.findings()
        self.assertEqual([f[2] for f in findings], ["pics/logo.png"])

    def test_leading_slash_resolves_from_root(self):
        write(self.root, "target.md", "x\n")
        write(self.root, "docs/deep.md", "[ok](/target.md)\n[bad](/missing.md)\n")
        findings = self.findings()
        self.assertEqual([f[2] for f in findings], ["/missing.md"])

    def test_excluded_sources_are_not_checked(self):
        write(self.root, "idea.md", "[x](broken.md)\n")
        write(self.root, "上一次建议.md", "[x](broken.md)\n")
        write(self.root, ".agents/note.md", "[x](broken.md)\n")
        write(self.root, "build/b.md", "[x](broken.md)\n")
        write(self.root, "pkg.egg-info/e.md", "[x](broken.md)\n")
        write(self.root, "docs/bad.md", "[x](broken.md)\n")
        files, links, findings = self.check()
        self.assertEqual(files, 1)
        self.assertEqual([f[0] for f in findings], [self.root / "docs" / "bad.md"])

    def test_cli_clean_tree_exits_zero(self):
        write(self.root, "index.md", "[ok](there.md)\n")
        write(self.root, "there.md", "x\n")
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("0 broken", result.stdout)

    def test_cli_broken_link_exits_one_and_prints(self):
        write(self.root, "index.md", "[missing](gone.md)\n")
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        self.assertIn("broken link:", result.stdout)
        self.assertIn("gone.md", result.stdout)
        self.assertIn("1 broken", result.stdout)


if __name__ == "__main__":
    unittest.main()
