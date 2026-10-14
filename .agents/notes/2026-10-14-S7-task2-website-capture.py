#!/usr/bin/env python3
"""S7 Task2 website-image capture — 2026-10-14.

Fresh, sanitized marketing captures of the accepted S7 GUI (design tokens
from 41bae0e via merge c8138fe) for the four static website showcase
images. Runs the real stdlib ui-demo server and real headless Chrome over
CDP, at the exact dimensions the website declares (1280x900 desktop,
390x844 narrow, deviceScaleFactor 1):

  - desktop shots select `cancel-1` so the right pane shows a real record:
    its cancellation banner states the acknowledged external effect is
    retained, not reversed (the store's honest cancel semantics);
  - narrow shots stay at the top of the page (wrapped topbar/controls,
    tiles, filters, first works) with no selection, matching the framing
    the website has always shown at 390px.

Sanitization/truthfulness enforced per shot: the store is seeded only by
`python3 -m work_runtime ui-demo` under a stated neutral demo root (the
store-source chip must not contain a user-home path), the five real works
must be present with their seeded statuses, polling stays active (the
paused chip must stay hidden), and the transient sampling-time chip is
recorded for disclosure (the UI always shows it; it cannot be removed
without editing product files this task must not touch).

Reuses the committed audit's CDP client and helpers by importing
docs/superpowers/acceptances/assets/S7/s7_gui_audit.py (stdlib only).
Audit artifact, not a runtime dependency.

Usage: 2026-10-14-S7-task2-website-capture.py --out DIR [--chrome PATH]
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

# Stated, machine-neutral demo root for the seeded store (the website docs
# name this root). mkdtemp adds its governed-ui-* child underneath it.
DEMO_ROOT = "/tmp/s7img-gui-store"

# The five real ui-demo works and their seeded statuses (work list chips).
EXPECTED_WORKS = [
    ("wait-1", "waiting"),
    ("uncertain-1", "needs_attention"),
    ("transfer-1", "active"),
    ("succeed-1", "closed"),
    ("cancel-1", "closed"),
]

RESULTS = []


def check(name, ok, observed):
    RESULTS.append(bool(ok))
    print("%s %s — %s" % ("PASS" if ok else "FAIL", name, observed),
          flush=True)


def connect_chrome(chrome):
    profile = tempfile.mkdtemp(prefix="s7img-cap-profile-")
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
        "return {h:r.height,w:r.w,top:r.top,shadow:cs.boxShadow,"
        "background:cs.backgroundColor,color:cs.color};}"
        "return {refresh:box('#refresh'),poll:box('#poll-toggle'),"
        "lang:box('#lang-toggle')};})())")


def works_state(page):
    return page.json_eval(
        "JSON.stringify((function(){var rows=Array.from("
        "document.querySelectorAll('#work-list .work-item'));"
        "return {works:rows.map(function(r){return {"
        "id:r.dataset.workId,"
        "status:(r.querySelector('[class*=chip-st-]')||{}).textContent||'',"
        "selected:r.getAttribute('aria-selected')};}),"
        "status:document.getElementById('list-status').textContent};})())")


def meta_state(page):
    return page.json_eval(
        "JSON.stringify((function(){function txt(id){return document."
        "getElementById(id).textContent;}return {"
        "source:txt('store-source'),schema:txt('store-schema'),"
        "sampledAt:txt('sampled-at'),"
        "pollHidden:document.getElementById('poll-state')"
        ".classList.contains('hidden')};})())")


def overflow_state(page):
    return page.json_eval(
        "JSON.stringify({sw: document.documentElement.scrollWidth,"
        "cw: document.documentElement.clientWidth, sy: window.scrollY})")


def detail_state(page):
    return page.json_eval(
        "JSON.stringify((function(){var t=document.querySelector("
        "'.detail-title');var b=document.querySelector("
        "'.detail-body .cancel-banner');var tab=document.querySelector("
        "'.tab[aria-selected=true]');return {"
        "title:t?t.textContent:null,"
        "banner:b?b.textContent.slice(0,260):null,"
        "bannerVisible:!!(b&&b.offsetHeight),"
        "tab:tab?tab.textContent:null,"
        "bodyVisible:!!(document.querySelector('.detail-body')"
        "&&document.querySelector('.detail-body').offsetHeight)};})())")


def capture_shot(page, url, width, height, label, lang, select):
    tag = "%s-%s" % (label, lang)
    page.set_viewport(width, height)
    page.navigate(url)
    settled = audit.settle_list(page)
    check("%s work list settled (5 works, not loading)" % tag,
          settled and settled.get("items") == 5,
          json.dumps(settled))
    audit.ensure_lang(page, lang)
    check("%s language is %s via the viewer toggle" % (tag, lang),
          page.evaluate("document.documentElement.lang") == lang,
          page.evaluate("document.documentElement.lang"))

    works = works_state(page)
    got = sorted((w["id"], w["status"])
                 for w in (works or {}).get("works", []))
    check("%s five seeded works with exact statuses" % tag,
          got == sorted(EXPECTED_WORKS), json.dumps(got))

    record = {"tag": tag, "width": width, "height": height}

    if select:
        picked = audit.select_work(page, "cancel-1")
        check("%s cancel-1 selected, detail loaded" % tag, picked,
              "select_work -> %s" % picked)
        detail = detail_state(page)
        banner = detail or {}
        retained = ("retained, not reversed" if lang == "en"
                    else "保留，并未被撤销")
        check("%s detail shows cancel-1 with acknowledged retained effect"
              % tag,
              banner.get("title") == "cancel-1" and banner.get("bannerVisible")
              and retained in (banner.get("banner") or ""),
              json.dumps(banner, ensure_ascii=False))
        check("%s overview tab active" % tag,
              banner.get("tab") in ("Overview", "概览"),
              repr(banner.get("tab")))
        record["detail"] = detail

    # Back to the top of the page; let fonts/layout settle before capture.
    page.evaluate("window.scrollTo(0, 0);")
    time.sleep(0.5)

    top = topbar_visible(page)
    check("%s topbar fully inside viewport at scrollY 0" % tag,
          top and top.get("top", -1) >= 0
          and top.get("bottom", 0) <= top.get("vh", 0) + 1
          and top.get("scrollY") == 0,
          json.dumps(top))
    check("%s topbar white card + hairline token" % tag,
          top and top.get("background") == "rgb(255, 255, 255)"
          and top.get("border", "").endswith("rgb(230, 229, 224)"),
          "bg=%r border=%r" % (top and top.get("background"),
                               top and top.get("border")))

    geo = control_geometry(page)
    record["controls"] = geo
    bad = [name for name, box in (geo or {}).items() if box is None]
    check("%s all topbar controls present" % tag, not bad,
          "absent: %s" % bad)
    short = [name for name, box in (geo or {}).items()
             if box and box.get("h", 0) < 44]
    check("%s topbar control targets >= 44px" % tag, not short,
          "short: %s" % short)
    shadows = [name for name, box in (geo or {}).items()
               if box and box.get("shadow") not in ("none", None)]
    check("%s no box-shadow on controls" % tag, not shadows,
          "shadowed: %s" % shadows)
    check("%s refresh control ink/canvas tokens" % tag,
          geo and geo.get("refresh", {}).get("background")
          == "rgb(38, 37, 30)"
          and geo.get("refresh", {}).get("color")
          == "rgb(247, 247, 244)",
          json.dumps(geo and geo.get("refresh")))

    meta = meta_state(page)
    record["meta"] = meta
    # The product renders only the DB basename (os.path.basename), so no
    # directory or user path can appear; assert exactly that.
    check("%s store-source is the bare demo DB name (no path)" % tag,
          meta and (meta.get("source") or "") == "runtime.sqlite",
          repr(meta and meta.get("source")))
    prefix = "Sampling time" if lang == "en" else "采样时间"
    check("%s sampled-at chip present (%s prefix recorded)" % (tag, prefix),
          meta and (meta.get("sampledAt") or "").startswith(prefix),
          repr(meta and meta.get("sampledAt")))
    check("%s polling active (paused chip hidden)" % tag,
          meta and meta.get("pollHidden") is True,
          json.dumps(meta and meta.get("pollHidden")))

    over = overflow_state(page)
    check("%s no horizontal overflow" % tag,
          over and over.get("sw", 10 ** 9) <= over.get("cw", 0) + 1,
          json.dumps(over))

    # In-frame (fold) contract: the accepted S7 design's denser tiles make
    # the top-of-page view taller than one viewport at both widths, so the
    # exact number of works inside the frame is asserted, not assumed.
    frame = page.json_eval(
        "JSON.stringify({vh: window.innerHeight,"
        "items: Array.from(document.querySelectorAll("
        "'#work-list .work-item')).map(function(e){var r="
        "e.getBoundingClientRect();return [e.dataset.workId,"
        "Math.round(r.top), Math.round(r.bottom)];})})")
    record["frame"] = frame
    vh = (frame or {}).get("vh", 0)
    full = [i for i in (frame or {}).get("items", []) if i[2] <= vh]
    partial_top = [i for i in (frame or {}).get("items", [])
                   if i[1] < vh < i[2]]
    need_full = 3 if select else 1
    if select:
        check("%s >= %d works fully in frame at the fold" % (tag, need_full),
              len(full) >= need_full,
              "full=%s partial=%s vh=%s" % ([i[0] for i in full],
                                            [i[0] for i in partial_top], vh))
    else:
        # Narrow top-of-page shot: the wrapped topbar/controls own the
        # frame; the record list must at least have started (first work's
        # id + status-chip row inside the viewport).
        first = (frame or {}).get("items", [])
        check("%s first work's id/chip row started in frame" % tag,
              first and first[0][1] + 24 <= vh,
              json.dumps(first and first[0]))
    if select:
        check("%s uncertain-1 (needs_attention) row starts in frame" % tag,
              any(i[0] == "uncertain-1" and i[1] < vh
                  for i in (frame or {}).get("items", [])),
              json.dumps(frame and frame.get("items")))
        banner = page.json_eval(
            "JSON.stringify((function(){var b=document.querySelector("
            "'.detail-body .cancel-banner');if(!b){return null;}"
            "var r=b.getBoundingClientRect();return {top:Math.round(r.top),"
            "bottom:Math.round(r.bottom),vh:window.innerHeight};})())")
        check("%s acknowledged-effect banner fully in frame" % tag,
              banner and banner.get("top", -1) >= 0
              and banner.get("bottom", 0) <= banner.get("vh", 0),
              json.dumps(banner))
    else:
        filters = page.json_eval(
            "JSON.stringify((function(){var f=document.querySelector("
            "'.filters');var r=f.getBoundingClientRect();"
            "return {top:Math.round(r.top),bottom:Math.round(r.bottom),"
            "vh:window.innerHeight};})())")
        check("%s search + status filters fully in frame" % tag,
              filters and filters.get("bottom", 10 ** 9)
              <= filters.get("vh", 0),
              json.dumps(filters))

    # Re-read the live list: the five-works snapshot above predates the
    # selection, and polling can re-render at any moment.
    selected = [w for w in (works_state(page) or {}).get("works", [])
                if w.get("selected") == "true"]
    if select:
        check("%s exactly cancel-1 marked selected" % tag,
              [w["id"] for w in selected] == ["cancel-1"],
              json.dumps(selected))
    else:
        check("%s nothing selected (top-of-page framing)" % tag,
              not selected, json.dumps(selected))

    shot = "s7img-%s-%s.png" % (lang, label)
    page.screenshot(os.path.join(out_dir, shot))
    record["png"] = shot
    record["png_bytes"] = os.path.getsize(os.path.join(out_dir, shot))
    record["works"] = works
    print("SHOT %s (%d bytes)" % (shot, record["png_bytes"]), flush=True)
    return record


def main():
    global out_dir
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--chrome",
                        default="/Applications/Google Chrome.app/Contents/"
                                "MacOS/Google Chrome")
    args = parser.parse_args()
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)

    os.makedirs(DEMO_ROOT, exist_ok=True)   # ui-demo mkdtemps inside it
    demo = audit.UiServer([sys.executable, "-m", "work_runtime", "ui-demo",
                           "--directory", DEMO_ROOT], cwd=REPO)
    proc = page = None
    record = {"capture": "S7 Task2 website images",
              "demo_root": DEMO_ROOT, "demo_url": demo.url, "shots": {}}
    try:
        proc, page = connect_chrome(args.chrome)
        for width, height, label in ((1280, 900, "desktop"),
                                     (390, 844, "390")):
            for lang in ("en", "zh"):
                record["shots"]["%s-%s" % (label, lang)] = capture_shot(
                    page, demo.url, width, height, label, lang,
                    select=(label == "desktop"))
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

    with open(os.path.join(out_dir, "s7img-capture.json"), "w") as handle:
        json.dump(record, handle, indent=1, ensure_ascii=False)
    failed = RESULTS.count(False)
    print("website image capture: %d assertions, %d failed"
          % (len(RESULTS), failed), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
