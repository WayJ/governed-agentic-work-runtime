#!/usr/bin/env python3
"""S7 Task2 PNG authenticity verifier — 2026-10-14.

Standard-library-only PNG inspection (zlib + manual defiltering; no
dependencies, no CDN image service): decodes each PNG's raw pixels and
proves, locally and reproducibly, that

  - every NEW capture has the exact declared dimensions (1280x900 /
    390x844) and carries the accepted S7 design tokens in its actual
    pixels — cream canvas #f7f7f4, white cards #ffffff, ink #26251e and
    the scarce orange brand mark #f54e00 — while containing ZERO pixels
    of the pre-S7 theme (#f5f7fa bg, #2456c6 blue accent, #eef1f6
    neutral, #1c2433 ink);
  - the OLD website images (still in website/assets at this point) carry
    that old theme and the same dimensions — a genuine before/after
    record, not a re-hash of either.

Counting exact flat-area pixel matches is robust here because canvas,
card fills, the ink refresh button and the brand-mark glyph are large
flat surfaces rendered without gradients at deviceScaleFactor 1.

Usage: 2026-10-14-S7-task2-png-verify.py --new DIR [--old DIR]
  --new DIR: directory holding s7img-{en,zh}-{desktop,390}.png
  --old DIR: directory holding the current gui-*.png (default: website/assets)
Writes s7img-png-verify.json next to the new captures; exit 0 iff all pass.
"""

import argparse
import json
import os
import struct
import zlib

NEW_TOKENS = {
    "canvas_#f7f7f4": (0xF7, 0xF7, 0xF4),
    "white_card_#ffffff": (0xFF, 0xFF, 0xFF),
    "ink_#26251e": (0x26, 0x25, 0x1E),
    "orange_mark_#f54e00": (0xF5, 0x4E, 0x00),
}
OLD_TOKENS = {
    "old_bg_#f5f7fa": (0xF5, 0xF7, 0xFA),
    "old_accent_#2456c6": (0x24, 0x56, 0xC6),
    "old_neutral_#eef1f6": (0xEE, 0xF1, 0xF6),
    "old_ink_#1c2433": (0x1C, 0x24, 0x33),
}
DIMS = {"desktop": (1280, 900), "390": (390, 844)}


def paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def decode_png(path):
    """Return (width, height, bytes-per-pixel, rows) with filters undone."""
    with open(path, "rb") as handle:
        data = handle.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG: %s" % path)
    pos, idat, width, height, depth, color = 8, [], None, None, None, None
    while pos < len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            width, height, depth, color = struct.unpack(">IIBB", chunk[:10])
        elif ctype == b"IDAT":
            idat.append(chunk)
        elif ctype == b"IEND":
            break
        pos += 12 + length
    if depth != 8 or color not in (2, 6):
        raise ValueError("unsupported PNG layout (depth=%s color=%s): %s"
                         % (depth, color, path))
    bpp = 3 if color == 2 else 4
    stride = width * bpp
    raw = zlib.decompress(b"".join(idat))
    rows, prev = [], bytearray(stride)
    for y in range(height):
        ftype = raw[y * (stride + 1)]
        row = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        if ftype == 1:                      # Sub
            for i in range(bpp, stride):
                row[i] = (row[i] + row[i - bpp]) & 0xFF
        elif ftype == 2:                    # Up
            for i in range(stride):
                row[i] = (row[i] + prev[i]) & 0xFF
        elif ftype == 3:                    # Average
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:                    # Paeth
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                upleft = prev[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + paeth(left, prev[i], upleft)) & 0xFF
        rows.append(bytes(row))
        prev = row
    return width, height, bpp, rows


def count_colors(path, palette):
    width, height, bpp, rows = decode_png(path)
    rgb_to_name = {v: k for k, v in palette.items()}
    counts = {}
    for row in rows:
        for i in range(0, len(row) - bpp + 1, bpp):
            name = rgb_to_name.get((row[i], row[i + 1], row[i + 2]))
            if name:
                counts[name] = counts.get(name, 0) + 1
    return width, height, counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--new", required=True)
    parser.add_argument("--old", default=os.path.join(
        "website", "assets"))
    args = parser.parse_args()
    report = {"new": {}, "old": {}}
    failures = []

    for label, want_dims in DIMS.items():
        for lang in ("en", "zh"):
            name = "s7img-%s-%s.png" % (lang, label)
            path = os.path.join(args.new, name)
            width, height, counts = count_colors(path, NEW_TOKENS)
            report["new"][name] = {"dims": [width, height], "tokens": counts}
            if (width, height) != want_dims:
                failures.append("%s dims %sx%s != %s"
                                % (name, width, height, want_dims))
            for token in NEW_TOKENS:
                got = counts.get(token, 0)
                floor = 40 if token.startswith("orange") else 1000
                if got < floor:
                    failures.append("%s missing %s (count %d < %d)"
                                    % (name, token, got, floor))
            old_path = os.path.join(args.old, "gui-%s-%s.png" % (lang, label))
            owidth, oheight, ocounts = count_colors(
                old_path, dict(OLD_TOKENS, **{"canvas_#f7f7f4": NEW_TOKENS["canvas_#f7f7f4"]}))
            report["old"][os.path.basename(old_path)] = {
                "dims": [owidth, oheight],
                "old_theme": {k: v for k, v in ocounts.items()
                              if k != "canvas_#f7f7f4"},
                "new_canvas_leak": ocounts.get("canvas_#f7f7f4", 0)}
            if (owidth, oheight) != want_dims:
                failures.append("old %s dims %sx%s != %s"
                                % (old_path, owidth, oheight, want_dims))
            if ocounts.get("old_bg_#f5f7fa", 0) < 1000:
                failures.append("old %s lacks old background token"
                                % old_path)
            if ocounts.get("canvas_#f7f7f4", 0) > 0:
                failures.append("old %s already shows new canvas?!"
                                % old_path)

    # Old-theme colors must be entirely absent from the new captures.
    for label in DIMS:
        for lang in ("en", "zh"):
            name = "s7img-%s-%s.png" % (lang, label)
            _, _, stale = count_colors(
                os.path.join(args.new, name), OLD_TOKENS)
            report["new"][name]["old_theme_residue"] = stale
            for token, n in stale.items():
                failures.append("%s contains old %s x%d" % (name, token, n))

    out = os.path.join(args.new, "s7img-png-verify.json")
    with open(out, "w") as handle:
        json.dump(report, handle, indent=1)
    print(json.dumps(report, indent=1))
    if failures:
        print("png verify: %d FAILURES" % len(failures))
        for line in failures:
            print("FAIL " + line)
        return 1
    print("png verify: all dimension/token checks passed")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
