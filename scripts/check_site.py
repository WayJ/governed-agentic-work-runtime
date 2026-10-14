#!/usr/bin/env python3
"""Structural checker for the static website under website/.

Standard library only, Python >= 3.9. Offline: never fetches. Scans every
*.html file under the root and reports findings deterministically sorted by
(file, line, kind):

- required files exist: index.html, zh/index.html, assets/styles.css,
  assets/site.js;
- every local href/src/srcset target resolves to a file inside the root
  (percent-decoded, query and fragment stripped);
- no local URL starts with "/" (the site is served under a repository
  subpath, so root-relative URLs would break);
- fragment anchors resolve to an id in the target document;
- navigation hrefs may go out via https: or mailto: only;
- asset URLs (link/script/img/source) must be scheme-less local paths;
- img elements carry an alt attribute;
- index.html links zh/index.html and zh/index.html links ../index.html.

A missing or unassembled website root is reported as missing-required
findings and exits 1 — never a silent pass. These are structural checks
only; they do not prove browser behavior, contrast or visual layout.

Usage: python3 scripts/check_site.py [--root website]
Exits 0 when clean, 1 when findings exist.
"""

import argparse
import os
import re
import sys
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = REPO_ROOT / "website"

REQUIRED_FILES = ("index.html", "zh/index.html", "assets/styles.css", "assets/site.js")
EN_LANG_LINK = "zh/index.html"
ZH_LANG_LINK = "../index.html"
ALLOWED_NAV_SCHEMES = ("https", "mailto")

SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

# tag -> attribute holding a single URL
NAV_ATTRS = {"a": "href"}
ASSET_ATTRS = {"link": "href", "script": "src", "img": "src", "source": "src"}
SRCSET_TAGS = ("img", "source")


class Finding(NamedTuple):
    file: str
    line: int
    kind: str
    detail: str


class _PageScan(HTMLParser):
    """Collect URL references, id anchors and img alt presence from one page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nav = []    # type: List[Tuple[str, int]]
        self.assets = []  # type: List[Tuple[str, int, str]]
        self.ids = set()  # type: set
        self.img_tags = []  # type: List[Tuple[int, bool]]

    def handle_starttag(self, tag, attrs):
        line = self.getpos()[0]
        data = dict(attrs)
        tag = tag.lower()
        identifier = data.get("id")
        if identifier:
            self.ids.add(identifier)
        if tag in NAV_ATTRS:
            url = data.get(NAV_ATTRS[tag])
            if url:
                self.nav.append((url, line))
        if tag in ASSET_ATTRS:
            url = data.get(ASSET_ATTRS[tag])
            if url:
                self.assets.append((url, line, tag + " " + ASSET_ATTRS[tag]))
        if tag in SRCSET_TAGS:
            srcset = data.get("srcset")
            if srcset:
                for candidate in srcset.split(","):
                    candidate = candidate.strip()
                    if candidate:
                        url = candidate.split()[0]
                        self.assets.append((url, line, tag + " srcset"))
        if tag == "img":
            self.img_tags.append((line, "alt" in data))


def _load_pages(root):
    # type: (Path) -> List[Tuple[Path, _PageScan]]
    pages = []
    if root.is_dir():
        for path in sorted(root.rglob("*.html")):
            parser = _PageScan()
            parser.feed(path.read_text(encoding="utf-8", errors="replace"))
            parser.close()
            pages.append((path, parser))
    return pages


def _split_url(url):
    # type: (str) -> Tuple[str, str]
    """Return (path_part, fragment) with the query string stripped."""
    body, _, fragment = url.partition("#")
    path_part = body.split("?", 1)[0]
    return path_part, fragment


def _resolve(source, raw):
    # type: (Path, str) -> Path
    """Percent-decode raw and resolve it lexically against the page's directory."""
    decoded = urllib.parse.unquote(raw)
    return Path(os.path.normpath(str(source.parent / decoded)))


def _contained(root, path):
    # type: (Path, Path) -> bool
    return path == root or root in path.parents


def _check_local(root, source, rel, url, line, what):
    # type: (Path, Path, str, str, int, str) -> List[Finding]
    findings = []
    path_part, _fragment = _split_url(url)
    if path_part.startswith("/"):
        findings.append(Finding(rel, line, "leading-slash",
                                "%s URL must not start with '/': %s" % (what, url)))
        return findings
    resolved = _resolve(source, path_part)
    if not _contained(root, resolved):
        findings.append(Finding(rel, line, "out-of-root",
                                "%s URL escapes the site root: %s" % (what, url)))
    elif not resolved.is_file():
        findings.append(Finding(rel, line, "missing-target",
                                "%s target missing: %s" % (what, url)))
    return findings


def _check_fragments(root, source, rel, pages_by_rel, nav):
    # type: (Path, Path, str, dict, List[Tuple[str, int]]) -> List[Finding]
    findings = []
    for url, line in nav:
        path_part, fragment = _split_url(url)
        if not fragment:
            continue
        if not path_part:
            target_rel, target_page = rel, pages_by_rel.get(rel)
        else:
            if SCHEME.match(path_part) or path_part.startswith("/"):
                continue  # already reported as disallowed-scheme / leading-slash
            resolved = _resolve(source, path_part)
            if not _contained(root, resolved):
                continue  # already reported as leading-slash/out-of-root
            target_rel = resolved.relative_to(root).as_posix()
            target_page = pages_by_rel.get(target_rel)
        if target_page is not None and fragment not in target_page.ids:
            findings.append(Finding(rel, line, "dangling-fragment",
                                    "fragment does not match any id in %s: %s"
                                    % (target_rel, url)))
    return findings


def scan(root):
    # type: (Path) -> List[Finding]
    """Scan the website root; return findings sorted by (file, line, kind)."""
    root = Path(os.path.normpath(str(root)))
    findings = []
    for required in REQUIRED_FILES:
        if not (root / required).is_file():
            findings.append(Finding(required, 0, "missing-required",
                                    "required file missing: %s" % required))
    pages = _load_pages(root)
    pages_by_rel = {path.relative_to(root).as_posix(): parser
                    for path, parser in pages}
    for path, parser in pages:
        source = Path(path)
        rel = path.relative_to(root).as_posix()
        for url, line in parser.nav:
            path_part, _fragment = _split_url(url)
            if not path_part:
                continue  # pure fragment (or empty href): handled below
            scheme = SCHEME.match(url)
            if scheme:
                if url.split(":", 1)[0].lower() not in ALLOWED_NAV_SCHEMES:
                    findings.append(Finding(rel, line, "disallowed-scheme",
                                            "navigation scheme not allowed "
                                            "(https/mailto only): %s" % url))
                continue
            findings.extend(_check_local(root, source, rel, url, line, "link"))
        for url, line, what in parser.assets:
            if SCHEME.match(url):
                findings.append(Finding(rel, line, "external-asset",
                                        "asset URL must be local: %s (%s)"
                                        % (url, what)))
                continue
            path_part, _fragment = _split_url(url)
            if not path_part:
                continue
            findings.extend(_check_local(root, source, rel, url, line, what))
        findings.extend(_check_fragments(root, source, rel, pages_by_rel, parser.nav))
        for line, has_alt in parser.img_tags:
            if not has_alt:
                findings.append(Finding(rel, line, "missing-alt",
                                        "img element has no alt attribute"))
        nav_urls = [url for url, _line in parser.nav]
        if rel == "index.html" and EN_LANG_LINK not in nav_urls:
            findings.append(Finding(rel, 0, "missing-lang-link",
                                    "English page must link %s" % EN_LANG_LINK))
        if rel == "zh/index.html" and ZH_LANG_LINK not in nav_urls:
            findings.append(Finding(rel, 0, "missing-lang-link",
                                    "Chinese page must link %s" % ZH_LANG_LINK))
    return sorted(findings, key=lambda finding: (finding.file, finding.line, finding.kind))


def main(argv=None):
    # type: (Optional[List[str]]) -> int
    parser = argparse.ArgumentParser(
        description="Check the static website's structure (offline, no fetching).")
    parser.add_argument("--root", default=str(DEFAULT_ROOT),
                        help="website root directory (default: this checkout's website/)")
    args = parser.parse_args(argv)
    root = Path(args.root)
    findings = scan(root)
    for finding in findings:
        print("%s: %s:%d %s" % (finding.kind, finding.file, finding.line, finding.detail))
    pages = len(list(root.rglob("*.html"))) if root.is_dir() else 0
    plural = "s" if len(findings) != 1 else ""
    print("checked %d pages, %d finding%s" % (pages, len(findings), plural))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
