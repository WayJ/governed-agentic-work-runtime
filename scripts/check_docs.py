#!/usr/bin/env python3
"""Check that local Markdown links in this repository resolve.

Standard library only, Python >= 3.9. External URLs, mailto links and pure
fragment anchors are skipped; a link with both a file part and a fragment
(`page.md#section`) is checked for the file part only. Link-like text inside
fenced code blocks (``` or ~~~) or inline code spans is treated as an
example, not a link.

Historical source material (idea.md, 上一次建议.md per AGENTS.md) and
working notes (.agents/) are not checked as link sources; links that target
them are still validated. Build artifacts (build/, dist/, *.egg-info) are
never checked, so running scripts/verify_install.py cannot change the result.

Usage: python3 scripts/check_docs.py [--root PATH] [paths...]
Exits 1 if any local link is broken.
"""

import argparse
import os
import re
import sys
import urllib.parse
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

EXCLUDED_DIRS = {".git", ".agents", ".claude", ".venv", "__pycache__", "build", "dist"}
EXCLUDED_FILES = {"idea.md", "上一次建议.md"}
# Historical source material that moved into docs/ideas: personal
# notes whose links point at the author's own machine, never the repo.
EXCLUDED_PATHS = ("docs/ideas",)

SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
INLINE_LINK = re.compile(r"!?\[([^\]\n]*)\]\(\s*(<[^>\n]*>|[^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
REFERENCE_DEF = re.compile(r"^ {0,3}\[([^\]\n]+)\]:\s*(<[^>\n]*>|[^\s]+)")
REFERENCE_USE = re.compile(r"!?\[([^\]\n]*)\]\[([^\]\n]*)\]")
INLINE_CODE = re.compile(r"`[^`\n]*`")


class Link(NamedTuple):
    file: str
    line: int
    target: str


def _unwrap(target):
    if target.startswith("<") and target.endswith(">"):
        return target[1:-1]
    return target


def _stripped_lines(text):
    """Yield (lineno, line) with fenced code blocks removed.

    A fence only closes on a marker of the same character at least as long
    as the opening one, so a ``` example inside a ```` block stays fenced.
    """
    fence_char = None
    fence_len = 0
    for lineno, line in enumerate(text.splitlines(), 1):
        marker = FENCE.match(line)
        if fence_char is not None:
            if marker and marker.group(1)[0] == fence_char and len(marker.group(1)) >= fence_len:
                fence_char = None
            continue
        if marker:
            fence_char = marker.group(1)[0]
            fence_len = len(marker.group(1))
            continue
        yield lineno, line


def extract_links(text):
    # type: (str) -> List[Link]
    """Return links with their line numbers; targets stay exactly as written."""
    # Reference definitions are collected only from non-fenced lines, so a
    # `[ref]: url` inside a code example cannot define a label.
    references = {}
    for lineno, line in _stripped_lines(text):
        definition = REFERENCE_DEF.match(line)
        if definition:
            references[definition.group(1).strip().lower()] = _unwrap(definition.group(2))
    links = []
    for lineno, line in _stripped_lines(text):
        if REFERENCE_DEF.match(line):
            continue
        cleaned = INLINE_CODE.sub(" ", line)
        for use in INLINE_LINK.finditer(cleaned):
            links.append(Link("-", lineno, _unwrap(use.group(2))))
        for use in REFERENCE_USE.finditer(cleaned):
            label = (use.group(2) or use.group(1)).strip().lower()
            target = references.get(label)
            if target is not None:
                links.append(Link("-", lineno, target))
    return links


def is_local_target(raw):
    # type: (str) -> bool
    if not raw or raw.startswith("#"):
        return False
    return SCHEME.match(raw) is None


def _resolve(root, source, raw):
    # type: (Path, Path, str) -> Path
    target = urllib.parse.unquote(raw.split("#", 1)[0].strip())
    if target.startswith("/"):
        return Path(os.path.normpath(str(root / target.lstrip("/"))))
    return Path(os.path.normpath(str(source.parent / target)))


def iter_markdown_files(root):
    # type: (Path) -> List[Path]
    files = []
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root)
        if len(relative.parts) == 1 and relative.name in EXCLUDED_FILES:
            continue
        if any(part in EXCLUDED_DIRS or part.endswith(".egg-info") for part in relative.parts):
            continue
        if "/".join(relative.parts[:-1]) in EXCLUDED_PATHS:
            continue
        files.append(path)
    return files


def check(root, sources=None):
    # type: (Path, Optional[List[Path]]) -> Tuple[int, int, List[Tuple[Path, int, str]]]
    """Check Markdown sources under root; return (files, local_links, findings)."""
    root = Path(root)
    files = list(sources) if sources is not None else iter_markdown_files(root)
    local = 0
    findings = []
    for source in files:
        text = Path(source).read_text(encoding="utf-8")
        for link in extract_links(text):
            if not is_local_target(link.target):
                continue
            local += 1
            if not _resolve(root, Path(source), link.target).exists():
                findings.append((Path(source), link.line, link.target))
    return len(files), local, findings


def main(argv):
    # type: (List[str]) -> int
    parser = argparse.ArgumentParser(description="Check that local Markdown links resolve.")
    parser.add_argument("--root", default=str(REPO_ROOT),
                        help="repository root for path resolution (default: this checkout)")
    parser.add_argument("paths", nargs="*",
                        help="optional Markdown files or directories to check instead of the root")
    args = parser.parse_args(argv)
    root = Path(args.root)
    sources = None
    if args.paths:
        sources = []
        for item in args.paths:
            path = Path(item)
            sources.extend(iter_markdown_files(path) if path.is_dir() else [path])
    files, links, findings = check(root, sources)
    for source, line, target in findings:
        try:
            shown = source.relative_to(root)
        except ValueError:
            shown = source
        print(f"broken link: {shown}:{line} -> {target}")
    print(f"checked {files} markdown files, {links} local links, {len(findings)} broken")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
