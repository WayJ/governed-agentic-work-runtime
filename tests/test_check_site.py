"""Tests for scripts/check_site.py, the structural website checker."""

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_site.py"

_spec = importlib.util.spec_from_file_location("check_site", SCRIPT)
check_site = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_site)


def write(root, relpath, content):
    path = Path(root) / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def index_html(body_extra=""):
    """Standard clean English entry page; body_extra is appended inside <main>."""
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        "<title>Governed Work Runtime</title>\n"
        '<link rel="stylesheet" href="assets/styles.css">\n'
        '<script src="assets/site.js" defer></script>\n'
        "</head>\n"
        '<body id="top">\n'
        "<nav>\n"
        '<a href="#top">Top</a>\n'
        '<a href="zh/index.html">Chinese</a>\n'
        '<a href="https://github.com/WayJ/governed-agentic-work-runtime">GitHub</a>\n'
        '<a href="mailto:nobody@example.net">Mail</a>\n'
        "</nav>\n"
        "<main>\n"
        '<a href="docs.html#intro">Docs</a>\n'
        '<a href="docs.html?v=2">Versioned docs</a>\n'
        + body_extra +
        '<img src="assets/gui.png" alt="Local UI five-work sample" '
        'srcset="assets/gui.png 1x, assets/gui@2x.png 2x">\n'
        "</main>\n"
        "</body>\n"
        "</html>\n"
    )


ZH_INDEX_HTML = (
    "<!doctype html>\n"
    '<html lang="zh">\n'
    "<head>\n"
    '<meta charset="utf-8">\n'
    "<title>Governed Work Runtime</title>\n"
    '<link rel="stylesheet" href="../assets/styles.css">\n'
    '<script src="../assets/site.js" defer></script>\n'
    "</head>\n"
    '<body id="top">\n'
    "<nav><a href=\"../index.html\">English</a></nav>\n"
    "<main>\n"
    '<a href="../docs.html#intro">Docs</a>\n'
    '<img src="../assets/gui.png" alt="Local UI five-work sample">\n'
    "</main>\n"
    "</body>\n"
    "</html>\n"
)

DOCS_HTML = (
    "<!doctype html>\n"
    '<html lang="en">\n'
    "<head><meta charset=\"utf-8\"><title>Docs</title></head>\n"
    "<body>\n"
    '<h1 id="intro">Docs</h1>\n'
    '<p><a href="index.html">Home</a> <a href="zh/index.html">Chinese</a></p>\n'
    "</body>\n"
    "</html>\n"
)


def base_site(root, index=None):
    """Write a complete clean site; index overrides the English entry page."""
    write(root, "assets/styles.css", "body{color:#26251e}\n")
    write(root, "assets/site.js", "// copy buttons only\n")
    write(root, "assets/gui.png", "png")
    write(root, "assets/gui@2x.png", "png")
    write(root, "docs.html", DOCS_HTML)
    write(root, "index.html", index if index is not None else index_html())
    write(root, "zh/index.html", ZH_INDEX_HTML)


class CheckSiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # A parent directory outside the site root exists for out-of-root cases.
        self.root = Path(self.temp.name) / "site"

    def scan(self):
        return check_site.scan(self.root)

    def kinds(self):
        return [finding.kind for finding in self.scan()]

    def run_cli(self, extra_args=()):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), *extra_args],
            capture_output=True, text=True)

    def test_clean_bilingual_site_passes(self):
        base_site(self.root)
        self.assertEqual(self.scan(), [])
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("0 findings", result.stdout)

    def test_broken_internal_link_reported_with_location(self):
        base_site(self.root, index="<html><body>\n<a href=\"gone.html\">x</a>\n</body></html>\n")
        matches = [f for f in self.scan() if f.kind == "missing-target"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].file, "index.html")
        self.assertEqual(matches[0].line, 2)
        self.assertIn("gone.html", matches[0].detail)

    def test_missing_asset_reported(self):
        base_site(self.root, index=index_html(
            '<img src="assets/gone.png" alt="missing asset">\n'))
        matches = [f for f in self.scan() if f.kind == "missing-target"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].file, "index.html")
        self.assertIn("assets/gone.png", matches[0].detail)

    def test_leading_slash_local_urls_reported(self):
        base_site(self.root, index=index_html(
            '<a href="/index.html">root</a>\n'
            '<img src="/assets/gui.png" alt="root asset">\n'))
        matches = [f for f in self.scan() if f.kind == "leading-slash"]
        self.assertEqual(len(matches), 2)
        self.assertEqual({m.line for m in matches}, {19, 20})

    def test_dangling_fragment_same_document(self):
        base_site(self.root, index=index_html(
            '<a href="#top">ok</a>\n<a href="#nowhere">bad</a>\n'))
        matches = [f for f in self.scan() if f.kind == "dangling-fragment"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].file, "index.html")
        self.assertEqual(matches[0].line, 20)
        self.assertIn("#nowhere", matches[0].detail)

    def test_fragment_in_other_document(self):
        base_site(self.root, index=index_html('<a href="docs.html#nowhere">bad</a>\n'))
        matches = [f for f in self.scan() if f.kind == "dangling-fragment"]
        self.assertEqual(len(matches), 1)
        self.assertIn("docs.html#nowhere", matches[0].detail)

    def test_missing_zh_page_reported_as_required(self):
        base_site(self.root)
        (self.root / "zh" / "index.html").unlink()
        findings = self.scan()
        required = [f for f in findings if f.kind == "missing-required"]
        self.assertEqual([(f.file, f.line) for f in required], [("zh/index.html", 0)])
        # The English page's link to it is still a broken local target.
        self.assertIn("missing-target", self.kinds())

    def test_missing_required_styles_and_js(self):
        base_site(self.root)
        (self.root / "assets" / "styles.css").unlink()
        (self.root / "assets" / "site.js").unlink()
        required = [f for f in self.scan() if f.kind == "missing-required"]
        self.assertEqual([f.file for f in required], ["assets/site.js", "assets/styles.css"])

    def test_insecure_and_non_https_navigation_schemes(self):
        base_site(self.root, index=index_html(
            '<a href="http://example.com/x">insecure</a>\n'
            '<a href="ftp://example.com/y">ftp</a>\n'))
        matches = [f for f in self.scan() if f.kind == "disallowed-scheme"]
        self.assertEqual(len(matches), 2)
        self.assertIn("http://example.com/x", matches[0].detail)
        self.assertIn("ftp://example.com/y", matches[1].detail)

    def test_external_asset_urls_rejected(self):
        base_site(self.root, index=(
            "<html><head>\n"
            '<link rel="stylesheet" href="https://cdn.example/x.css">\n'
            '<script src="https://cdn.example/x.js"></script>\n'
            "</head><body>\n"
            '<img src="https://cdn.example/x.png" alt="cdn image">\n'
            "</body></html>\n"))
        matches = [f for f in self.scan() if f.kind == "external-asset"]
        self.assertEqual(len(matches), 3)
        self.assertEqual({m.line for m in matches}, {2, 3, 5})

    def test_non_asset_link_rels_ignored(self):
        base_site(self.root, index=(
            '<html lang="en"><head>\n'
            '<link rel="canonical" href="https://wayj.github.io/governed-agentic-work-runtime/">\n'
            '<link rel="alternate" hreflang="zh" href="zh/index.html">\n'
            '<link rel="stylesheet" href="assets/styles.css">\n'
            '<script src="assets/site.js" defer></script>\n'
            "</head><body>\n"
            '<a href="zh/index.html">Chinese</a>\n'
            "</body></html>\n"))
        self.assertEqual([f for f in self.scan() if f.kind == "external-asset"], [])

    def test_missing_img_alt(self):
        base_site(self.root, index=index_html('<img src="assets/gui.png">\n'))
        matches = [f for f in self.scan() if f.kind == "missing-alt"]
        self.assertEqual(len(matches), 1)
        self.assertEqual((matches[0].file, matches[0].line), ("index.html", 19))

    def test_out_of_root_literal_and_encoded(self):
        (self.root.parent / "outside.html").write_text("outside", encoding="utf-8")
        base_site(self.root, index=index_html(
            '<a href="../outside.html">literal</a>\n'
            '<a href="%2e%2e/outside.html">encoded</a>\n'))
        matches = [f for f in self.scan() if f.kind == "out-of-root"]
        self.assertEqual(len(matches), 2)
        self.assertIn("../outside.html", matches[0].detail)
        self.assertIn("%2e%2e/outside.html", matches[1].detail)

    def test_percent_encoded_and_entity_urls_resolve(self):
        base_site(self.root, index=index_html(
            '<a href="sp%20ace.html">encoded</a>\n'
            '<a href="a&amp;b.html">entity</a>\n'))
        write(self.root, "sp ace.html", "<html><body>ok</body></html>\n")
        write(self.root, "a&b.html", "<html><body>ok</body></html>\n")
        self.assertEqual(self.scan(), [])

    def test_srcset_candidates_checked_individually(self):
        base_site(self.root, index=index_html(
            '<img src="assets/gui.png" alt="x" '
            'srcset="assets/gui.png 1x, assets/gone.png 2x">\n'
            '<picture><source srcset="assets/gone2.png 1x"></picture>\n'))
        matches = [f for f in self.scan() if f.kind == "missing-target"]
        self.assertEqual(len(matches), 2)
        details = " ".join(m.detail for m in matches)
        self.assertIn("assets/gone.png", details)
        self.assertIn("assets/gone2.png", details)

    def test_language_crosslinks_required(self):
        write(self.root, "assets/styles.css", "body{}\n")
        write(self.root, "assets/site.js", "//\n")
        write(self.root, "index.html", "<html><body>no switch</body></html>\n")
        write(self.root, "zh/index.html", "<html><body>无切换</body></html>\n")
        matches = [f for f in self.scan() if f.kind == "missing-lang-link"]
        self.assertEqual([(f.file, f.line) for f in matches],
                         [("index.html", 0), ("zh/index.html", 0)])

    def test_absent_root_reports_missing_required_not_success(self):
        self.root = self.root / "does-not-exist"
        findings = self.scan()
        self.assertEqual([f.kind for f in findings], ["missing-required"] * 4)
        self.assertEqual([f.file for f in findings],
                         ["assets/site.js", "assets/styles.css",
                          "index.html", "zh/index.html"])
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        self.assertIn("4 findings", result.stdout)

    def test_findings_sorted_by_file_line_kind(self):
        write(self.root, "assets/styles.css", "body{}\n")
        write(self.root, "assets/site.js", "//\n")
        write(self.root, "index.html",
              "<html><body>\n<a href=\"gone1.html\">a</a>\n<a href=\"/abs.html\">b</a>\n</body></html>\n")
        write(self.root, "zh/index.html",
              "<html><body>\n<a href=\"#nope\">c</a>\n</body></html>\n")
        expected = [
            ("index.html", 0, "missing-lang-link"),
            ("index.html", 2, "missing-target"),
            ("index.html", 3, "leading-slash"),
            ("zh/index.html", 0, "missing-lang-link"),
            ("zh/index.html", 2, "dangling-fragment"),
        ]
        self.assertEqual([(f.file, f.line, f.kind) for f in self.scan()], expected)

    def test_cli_findings_exit_one_and_print(self):
        base_site(self.root, index=index_html('<a href="gone.html">x</a>\n'))
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing-target", result.stdout)
        self.assertIn("gone.html", result.stdout)
        self.assertIn("1 finding", result.stdout)


if __name__ == "__main__":
    unittest.main()
