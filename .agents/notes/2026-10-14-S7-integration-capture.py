#!/usr/bin/env python3
"""S7 integration-review supplementary browser capture — 2026-10-14.

Independent integration evidence that the committed S7 matrix cannot
standalone establish: the committed matrix screenshots scroll `.detail-body`
into view before capture, so on narrow viewports the topbar (brand, store
meta, refresh/pause/language controls) is out of frame. This script captures,
in actual headless Chrome over CDP on the combined release-control checkout:

  - top-of-page (scrollY == 0) screenshots at 1440/390/320 in en/zh, proving
    the topbar/controls surface itself (token colors, wrapped controls,
    hairline, visible filters), and
  - the same-page scrolled-detail captures for the same width/language
    pairs (detail region in frame), plus
  - computed-style measurements of the topbar surfaces: control heights
    (>=44px), topbar/card/canvas token colors, meta-chip contrast, focus
    ring on a topbar control after a trusted Tab press, and the
    page-level no-horizontal-overflow proof at 390/320 with a selected work.

Reuses the committed audit's CDP client and helpers by importing
docs/superpowers/acceptances/assets/S7/s7_gui_audit.py (stdlib only).
This is an integration audit artifact, not a runtime dependency.

Usage: 2026-10-14-S7-integration-capture.py --out DIR [--chrome PATH]
Exit 0 when every assertion passes; 1 otherwise.
"""

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
AUDIT_PATH = os.path.join(
    REPO, "docs", "superpowers", "acceptances", "assets", "S7",
    "s7_gui_audit.py")

spec = importlib.util.spec_from_file_location("s7_gui_audit", AUDIT_PATH)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

RESULTS = []


def check(name, ok, observed):
    RESULTS.append(bool(ok))
    print("%s %s — %s" % ("PASS" if ok else "FAIL", name, observed),
          flush=True)


def connect_chrome(chrome):
    profile = tempfile.mkdtemp(prefix="s7-int-cap-profile-")
    proc = subprocess.Popen(
        [chrome, "--headless", "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", "--lang=en-US",
         "--remote-debugging-port=0", "--user-data-dir=" + profile,
         "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    deadline = time.time() + 20
    devtools = None
    while time.time() < deadline:
        line = proc.stderr.readline()
        if "DevTools listening on ws://" in line:
            host = line.split("ws://", 1)[1].strip().rstrip("/")
            devtools = host.rsplit("/devtools", 1)[0]
            break
    if not devtools:
        proc.kill()
        raise RuntimeError("Chrome never reported its DevTools endpoint")
    new = urllib.request.Request("http://%s/json/new?about:blank" % devtools,
                                 method="PUT")
    target = json.load(urllib.request.urlopen(new, timeout=10))
    return proc, audit.CdpPage(devtools, target["id"])


def scroll_top(page):
    page.evaluate("window.scrollTo(0, 0);")


def topbar_visible(page):
    return page.json_eval(
        "JSON.stringify((function(){var t=document.querySelector("
        "'.topbar');if(!t){return null;}var r=t.getBoundingClientRect();"
        "var cs=getComputedStyle(t);return {top:r.top,bottom:r.bottom,"
        "height:r.height, background:cs.backgroundColor,"
        "border:cs.borderBottomWidth+' '+cs.borderBottomColor,"
        "scrollY:window.scrollY,"
        "vw:document.documentElement.clientWidth,"
        "vh:window.innerHeight};})())")


def control_geometry(page):
    return page.json_eval(
        "JSON.stringify((function(){function box(sel){var e="
        "document.querySelector(sel);if(!e){return null;}var r="
        "e.getBoundingClientRect();var cs=getComputedStyle(e);"
        "return {h:r.height,w:r.w,top:r.top,left:r.left,"
        "radius:cs.borderRadius,background:cs.backgroundColor,"
        "color:cs.color,shadow:cs.boxShadow};}"
        "return {refresh:box('#refresh'),poll:box('#poll-toggle'),"
        "lang:box('#lang-toggle'),search:box('#work-search'),"
        "filter:box('#status-filter'),chip:box('.meta-chip')};})())")


def focus_a_topbar_control(page):
    """Trusted Tab keypresses from the brand until a control is focused."""
    page.evaluate(
        "(function(){var b=document.querySelector('.brand');"
        "if(b){b.querySelector('a,button,span')||b;"
        "var f=b.tagName==='A'||b.tagName==='BUTTON'?b:b;f.focus();}})()")
    for _ in range(6):
        page.key("Tab", "Tab", 9)
        time.sleep(0.1)
        active = page.json_eval(
            "JSON.stringify((function(){var a=document.activeElement;"
            "if(!a||a===document.body){return null;}"
            "var s=getComputedStyle(a);return {id:a.id,tag:a.tagName,"
            "style:s.outlineStyle,width:s.outlineWidth,"
            "color:s.outlineColor,offset:s.outlineOffset};})())")
        if active and active.get("id") in ("refresh", "poll-toggle",
                                           "lang-toggle"):
            return active
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--chrome",
                        default="/Applications/Google Chrome.app/Contents/"
                                "MacOS/Google Chrome")
    args = parser.parse_args()
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)

    workdir = tempfile.mkdtemp(prefix="s7-int-cap-stores-")
    demo = audit.UiServer([sys.executable, "-m", "work_runtime", "ui-demo",
                           "--directory", workdir], cwd=REPO)
    proc = page = None
    record = {"capture": "S7 integration supplementary", "widths": {}}
    try:
        proc, page = connect_chrome(args.chrome)
        for width, height in ((1440, 900), (390, 844), (320, 690)):
            page.set_viewport(width, height)
            label = "%d" % width
            for lang in ("en", "zh"):
                page.navigate(demo.url)
                state = audit.settle_list(page)
                audit.ensure_lang(page, lang)
                scroll_top(page)
                time.sleep(0.3)

                tag = "%s-%s" % (label, lang)
                # --- top-of-page capture: topbar/controls in frame -------
                top = topbar_visible(page)
                check("%s topbar inside viewport at scrollY 0"
                      % tag,
                      top and top.get("top", -1) >= 0
                      and top.get("bottom", 0) <= top.get("vh", 0) + 1
                      and top.get("scrollY") == 0,
                      json.dumps(top))
                page.screenshot(os.path.join(
                    out, "s7-integration-top-%s.png" % tag))
                geo = control_geometry(page)
                record["widths"][tag] = {"topbar": top, "controls": geo}
                bad = [name for name, box in (geo or {}).items()
                       if box is None]
                check("%s all topbar controls present" % tag, not bad,
                      "absent: %s" % bad)
                short = [name for name, box in (geo or {}).items()
                         if box and name != "chip"
                         and box.get("h", 0) < 44]
                check("%s topbar control targets >= 44px" % tag,
                      not short, "short: %s" % short)
                shadows = [name for name, box in (geo or {}).items()
                           if box and box.get("shadow") not in
                           ("none", None)]
                check("%s topbar no box-shadow" % tag, not shadows,
                      "shadowed: %s" % shadows)

                # token colors on the topbar surface
                check("%s topbar white card + hairline" % tag,
                      top and top.get("background") == "rgb(255, 255, 255)"
                      and top.get("border", "").endswith("rgb(230, 229, 224)"),
                      "bg=%r border=%r" % (top and top.get("background"),
                                           top and top.get("border")))
                check("%s refresh control ink/canvas" % tag,
                      geo and geo.get("refresh", {}).get("background")
                      == "rgb(38, 37, 30)"
                      and geo.get("refresh", {}).get("color")
                      == "rgb(247, 247, 244)",
                      json.dumps(geo and geo.get("refresh")))

                # meta chip contrast (small text on neutral surface)
                audit.measure_contrast(
                    page, "%s meta-chip small text" % tag,
                    ".meta-chip", 4.5, "after")
                chip_pair = (record["widths"][tag]["controls"]
                             .get("chip", {}) or {})
                record["widths"][tag]["chip"] = chip_pair

                # focus ring on a real topbar control (trusted Tab)
                if lang == "en":
                    ring = focus_a_topbar_control(page)
                    check("%s topbar control keyboard focus ring" % tag,
                          ring and ring.get("style") == "solid"
                          and ring.get("width") == "2px"
                          and ring.get("color") == "rgb(245, 78, 0)"
                          and ring.get("offset") == "2px",
                          json.dumps(ring))
                    scroll_top(page)
                    page.screenshot(os.path.join(
                        out, "s7-integration-focus-%s.png" % tag))
                    record["widths"][tag]["focus"] = ring

                # --- scrolled-detail capture for the same page ------------
                audit.select_work(page, "wait-1")
                if audit.open_tab(page, "events"):
                    audit.wait_true(
                        page,
                        "!!document.querySelector('#detail-body pre.raw')")
                page.evaluate(
                    "(function(){var e=document.querySelector("
                    "'.detail-body');if(e){e.scrollIntoView();}})()")
                time.sleep(0.2)
                page.screenshot(os.path.join(
                    out, "s7-integration-detail-%s.png" % tag))
                overflow = page.json_eval(
                    "JSON.stringify({sw: document.documentElement"
                    ".scrollWidth, cw: document.documentElement"
                    ".clientWidth, sy: window.scrollY})")
                check("%s no page-level horizontal overflow with detail"
                      % tag,
                      overflow and overflow.get("sw", 10 ** 9)
                      <= overflow.get("cw", 0) + 1,
                      json.dumps(overflow))
                record["widths"][tag]["overflow"] = overflow
    finally:
        if page:
            page.close()
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        demo.kill()

    with open(os.path.join(out, "integration-capture.json"), "w") as handle:
        json.dump(record, handle, indent=1, ensure_ascii=False)
    total = len(RESULTS) + len(audit.RESULTS)
    failed = RESULTS.count(False) + audit.RESULTS.count(False)
    print("integration capture: %d assertions, %d failed" % (total, failed),
          flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
