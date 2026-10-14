#!/usr/bin/env python3
"""S8 viewer browser evidence — actual Chrome/CDP, standard library only.

Phase-parameterized RED/GREEN for the D37 closed-work revoked-evidence
notice ("red" proves the notice is MISSING on the committed assets with the
derived API already present; "green" proves the implemented notice, revoked
chip, bilingual copy, keyboard path, polling/disconnect regressions, DESIGN
computed styles/contrast, screenshots at 1440/390/320 and all-table
zero-write equality).

Store: one real store seeded entirely through the public Runtime API
(create/bind/record_evidence/verify_pending/propose_action/dispatch/
request_completion/request_cancel/finalize_cancel/revoke_evidence) with five
works: succeed-closed (cited approval revoked, huge document integer),
cancel-closed (acknowledged effect + revoked proof), unbound-closed (D-1
family), open-revoked (active — no notice), clean-closed (no notice).

Reuses the S7 audit's stdlib CDP client and helpers by importing
docs/superpowers/acceptances/assets/S7/s7_gui_audit.py. Audit artifact, not
a runtime dependency, not part of unittest discovery.

Usage: 2026-10-15-S8-viewer-browser.py --phase red|green --out DIR
       [--chrome PATH]
Exit 0 when every phase check holds; 1 otherwise.
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

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AUDIT = os.path.join(REPO, "docs/superpowers/acceptances/assets/S7/s7_gui_audit.py")

sys.path.insert(0, REPO)

spec = importlib.util.spec_from_file_location("s7_gui_audit", AUDIT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

check, measure, wait_true = audit.check, audit.measure, audit.wait_true
CdpPage, UiServer, snapshot = audit.CdpPage, audit.UiServer, audit.snapshot
settle_list, wait_detail, select_work = (audit.settle_list, audit.wait_detail,
                                         audit.select_work)
ensure_lang, open_tab, active_tab = audit.ensure_lang, audit.open_tab, audit.active_tab
measure_contrast = audit.measure_contrast

from work_runtime.adapters import FakeOA                      # noqa: E402
from work_runtime.demo import (action, demo_grants, document,  # noqa: E402
                               initialize, prerequisites, send)
from work_runtime.policy import ExpensePolicy                 # noqa: E402
from work_runtime.runtime import Runtime                      # noqa: E402

HUGE = 10000000000000001
NOTICE = ".revoked-notice"
CITED = ".revoked-notice-cited"

EN_TITLE = "Revoked evidence on a closed work"
EN_BODY_MARK = "historical closure"
EN_CITED_MARK = "now-revoked evidence id"
ZH_TITLE = "已关闭工作上的被撤销证据"
ZH_BODY_MARK = "历史关闭及其结果保持原记录不变"
ZH_CITED_MARK = "现已撤销的证据编号"


def grants():
    base = demo_grants()
    base["root"] = {"work.intervene"}
    base["finance"] = {"evidence.write", "evidence.revoke"}
    return base


def revoke_approval(runtime, work_id):
    """Revoke the stored approval proof through the public command."""
    import sqlite3
    import uuid
    db = sqlite3.connect(runtime.path)
    rows = db.execute("SELECT source, event_id, body FROM evidence "
                      "WHERE work_id=?", (work_id,)).fetchall()
    db.close()
    for source, event_id, body in rows:
        proof = json.loads(body)
        if proof.get("kind") == "approval":
            version = runtime.get_work(work_id)["state_version"]
            receipt = runtime.command(
                "finance", uuid.uuid4().hex, work_id, "revoke_evidence",
                {"source": source, "event_id": event_id, "reason": "withdrawn"},
                version)
            assert receipt["decision"] == "accepted", receipt
            return proof["id"]
    raise AssertionError("no approval proof on " + work_id)


def seed_store(db_path, oa_dir):
    """Five works through real public commands only; no direct SQL writes."""
    runtime = Runtime(db_path, ExpensePolicy(), grants())

    # succeed-closed: cited approval revoked after closure, huge integer.
    initialize(runtime, work_id="succeed-closed",
               doc=document(amount=HUGE, invoice_id="INV-101",
                            document_id="EXP-101"))
    prerequisites(runtime, work_id="succeed-closed")
    send(runtime, "succeed-closed", "register_wait", {
        "requirement_id": "E05:EXP-101", "deadline": 2000000000,
        "owner": "finance"})
    receipt = action(runtime, work_id="succeed-closed")
    runtime.dispatch(receipt["operation_id"],
                     FakeOA(os.path.join(oa_dir, "oa-succeed.sqlite")))
    final = send(runtime, "succeed-closed", "request_completion")
    assert final["decision"] == "accepted", final
    cited_id = revoke_approval(runtime, "succeed-closed")

    # cancel-closed: acknowledged external effect, revoked proof, no citations.
    initialize(runtime, work_id="cancel-closed",
               doc=document(amount=90000, invoice_id="INV-102",
                            document_id="EXP-102"))
    prerequisites(runtime, work_id="cancel-closed")
    operation_id = action(runtime, work_id="cancel-closed")["operation_id"]
    runtime.dispatch(operation_id,
                     FakeOA(os.path.join(oa_dir, "oa-cancel.sqlite")))
    send(runtime, "cancel-closed", "request_cancel", {"reason": "stop"})
    final = send(runtime, "cancel-closed", "finalize_cancel",
                 {"acknowledged_operations": [operation_id]})
    assert final["decision"] == "accepted", final
    revoke_approval(runtime, "cancel-closed")

    # unbound-closed: D-1 family — closed unbound work with a revoked proof.
    send(runtime, "unbound-closed", "create_work",
         {"document": document(amount=1, invoice_id="INV-901",
                               document_id="UNB-901")})
    send(runtime, "unbound-closed", "record_evidence",
         {"event_id": "evt-unbound-901", "kind": "approval",
          "data": {"digest": "d"}}, actor="finance")
    send(runtime, "unbound-closed", "request_cancel", {"reason": "stop"})
    final = send(runtime, "unbound-closed", "finalize_cancel",
                 {"acknowledged_operations": []})
    assert final["decision"] == "accepted", final
    revoke_approval(runtime, "unbound-closed")

    # open-revoked: active work with revoked evidence — no closed-work notice.
    initialize(runtime, work_id="open-revoked",
               doc=document(amount=80000, invoice_id="INV-103",
                            document_id="EXP-103"))
    prerequisites(runtime, work_id="open-revoked")
    revoke_approval(runtime, "open-revoked")

    # clean-closed: closed succeeded without any revocation — no notice.
    initialize(runtime, work_id="clean-closed",
               doc=document(amount=70000, invoice_id="INV-104",
                            document_id="EXP-104"))
    prerequisites(runtime, work_id="clean-closed")
    receipt = action(runtime, work_id="clean-closed")
    runtime.dispatch(receipt["operation_id"],
                     FakeOA(os.path.join(oa_dir, "oa-clean.sqlite")))
    final = send(runtime, "clean-closed", "request_completion")
    assert final["decision"] == "accepted", final
    return cited_id


def notice_state(page):
    return page.json_eval(
        "JSON.stringify((function(){var n=document.querySelector(%s);"
        "if(!n){return {present:false};}"
        "var c=n.querySelector(%s);"
        "return {present:true, text:n.textContent,"
        " cited: c?c.textContent:null,"
        " buttons: Array.prototype.map.call("
        "n.querySelectorAll('button'),function(b){return b.textContent;})};"
        "})())" % (json.dumps(NOTICE), json.dumps(CITED)))


def chip_state(page):
    return page.json_eval(
        "JSON.stringify((function(){var chips=document.querySelectorAll("
        "'.tabpanel .chip');var hit=null;"
        "chips.forEach(function(c){if(c.textContent==='revoked'){hit=c;}});"
        "if(!hit){return null;}"
        "var s=getComputedStyle(hit);"
        "return {className:hit.className, background:s.backgroundColor,"
        "color:s.color};})())")


def start_server(db_path, port=None):
    argv = [sys.executable, "-m", "work_runtime", "ui", "--db", db_path]
    if port:
        argv += ["--port", str(port)]
    return UiServer(argv, cwd=REPO)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["red", "green"], required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--chrome",
                        default="/Applications/Google Chrome.app/Contents/"
                                "MacOS/Google Chrome")
    args = parser.parse_args()
    phase = args.phase
    out = os.path.abspath(args.out)
    shots = os.path.join(out, "%s-views" % phase)
    os.makedirs(shots, exist_ok=True)
    green = phase == "green"

    workdir = tempfile.mkdtemp(prefix="s8-viewer-stores-")
    db_path = os.path.join(workdir, "runtime.sqlite")
    cited_id = seed_store(db_path, workdir)
    before_digest = snapshot(db_path)

    server = start_server(db_path)
    port = int(server.url.rsplit(":", 1)[1].rstrip("/"))

    profile = tempfile.mkdtemp(prefix="s8-viewer-cdp-")
    proc = subprocess.Popen(
        [args.chrome, "--headless", "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", "--lang=en-US",
         "--remote-debugging-port=0", "--user-data-dir=" + profile,
         "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    page = None
    fail = 1
    try:
        deadline = time.time() + 20
        devtools = None
        while time.time() < deadline:
            line = proc.stderr.readline()
            if "DevTools listening on ws://" in line:
                host = line.split("ws://", 1)[1].strip().rstrip("/")
                devtools = host.rsplit("/devtools", 1)[0]
                break
        if not devtools:
            raise RuntimeError("Chrome never reported its DevTools endpoint")
        target = json.load(urllib.request.urlopen(
            urllib.request.Request(
                "http://%s/json/new?about:blank" % devtools, method="PUT"),
            timeout=10))
        page = CdpPage(devtools, target["id"])

        page.set_viewport(1440, 900)
        page.navigate(server.url)
        state = settle_list(page)
        check("%s: five seeded works settle in the list" % phase,
              state and state.get("items") == 5,
              json.dumps(state, ensure_ascii=False))

        # The derived API is present in BOTH phases (backend shipped first).
        api = page.json_eval(
            "(function(){var r=new XMLHttpRequest();r.open('GET',"
            "'/api/work?id=succeed-closed',false);r.send();"
            "var p=JSON.parse(r.responseText);"
            "return JSON.stringify({revoked:p.revoked_evidence.length,"
            "cited:p.completion_revoked_evidence_ids});})()")
        check("%s: /api/work carries revoked_evidence + cited ids" % phase,
              api == {"revoked": 1, "cited": [cited_id]}, json.dumps(api))

        # The machine's Chrome may come up in either locale; pin EN first.
        ensure_lang(page, "en")
        expect_notice = {"succeed-closed": True, "cancel-closed": True,
                         "unbound-closed": True, "open-revoked": False,
                         "clean-closed": False}
        for work_id, wanted in expect_notice.items():
            select_work(page, work_id)
            got = notice_state(page)
            has = bool(got and got.get("present"))
            if green:
                check("green: notice %s on %s" % ("shown" if wanted
                                                  else "absent", work_id),
                      has == wanted, "present=%s" % has)
            else:
                # RED: the notice must be demonstrably MISSING everywhere,
                # most importantly on the closed-revoked works it must exist
                # for — that absence IS the recorded RED evidence.
                check("red: notice missing on %s (absent before the fix)"
                      % work_id, has is False, "present=%s" % has)
            if wanted and green:
                check("green: EN notice distinguishes history/current on %s"
                      % work_id,
                      EN_TITLE in got["text"] and EN_BODY_MARK in got["text"],
                      repr(got["text"][:140]))
                cited = bool(got.get("cited"))
                if work_id == "succeed-closed":
                    check("green: derived citation count + exact id text",
                          cited_id in got["cited"] and "1" in got["cited"],
                          repr(got["cited"]))
                else:
                    # Cancellation/unbound completions never invent citations.
                    check("green: no fabricated citation line on %s" % work_id,
                          cited is False, repr(got.get("cited")))

        if not green:
            # RED: with the derived API present, the neutral revoked chip is
            # still rendered by the neutral base (recorded, not failed).
            select_work(page, "succeed-closed")
            open_tab(page, "evidence")
            audit.wait_true(
                page,
                "(function(){var c=Array.prototype.slice.call("
                "document.querySelectorAll('.tabpanel .chip'));"
                "return c.some(function(x){return x.textContent==='revoked';"
                "});})()")
            chip = chip_state(page)
            measure("red: revoked chip renders on the neutral base", chip)

        if green:
            # --- notice structure, styles, contrast ---------------------
            select_work(page, "succeed-closed")
            notice = page.json_eval(
                "JSON.stringify((function(){var n=document.querySelector("
                "'.revoked-notice');if(!n){return null;}"
                "var s=getComputedStyle(n);var t=n.querySelector("
                "'.revoked-notice-title');var b=n.querySelector("
                "'.revoked-notice-body');"
                "return {bg:s.backgroundColor,border:s.borderWidth+' '+"
                "s.borderStyle+' '+s.borderColor,radius:s.borderRadius,"
                "shadow:s.boxShadow,display:s.display,"
                "titleColor:t?getComputedStyle(t).color:null,"
                "bodyColor:b?getComputedStyle(b).color:null,"
                "buttons:n.querySelectorAll('button').length};})())")
            check("green: notice uses cream-soft card tokens (12px radius, "
                  "hairline, no shadow)",
                  notice["bg"] == "rgb(250, 250, 247)"
                  and notice["radius"] == "12px"
                  and notice["border"].startswith("1px solid rgb(207, 205, 196)")
                  and notice["shadow"] == "none",
                  json.dumps(notice))
            measure("green: notice computed styles", notice)
            measure_contrast(page, "notice-title", ".revoked-notice-title",
                             4.5, "after")
            measure_contrast(page, "notice-body", ".revoked-notice-body",
                             4.5, "after")

            # --- evidence tab: revoked chip on error tokens -------------
            open_tab(page, "evidence")
            audit.wait_true(
                page,
                "(function(){var c=Array.prototype.slice.call("
                "document.querySelectorAll('.tabpanel .chip'));"
                "return c.some(function(x){return x.textContent==='revoked';"
                "});})()")
            chip = chip_state(page)
            check("green: revoked chip on measured error tokens",
                  chip and "chip-st-revoked" in chip["className"]
                  and chip["background"] == "rgb(249, 232, 236)"
                  and chip["color"] == "rgb(179, 36, 73)",
                  json.dumps(chip))
            measure_contrast(page, "revoked-chip", ".chip-st-revoked", 4.5,
                             "after")

            # --- raw exactness: huge integer as exact text --------------
            open_tab(page, "documents")
            # Probe with a STRING literal: a JS numeric literal would already
            # round 10000000000000001 to ...000 — the hazard this UI avoids.
            exact = page.evaluate(
                "(function(){var t=document.querySelector('#detail-body')"
                ".textContent;return t.indexOf(%s)!==-1;})()"
                % json.dumps(str(HUGE)))
            check("green: huge integer survives as exact text in documents",
                  bool(exact), "looking for %d" % HUGE)

            # --- keyboard: notice buttons switch tabs -------------------
            select_work(page, "succeed-closed")
            page.focus(".revoked-notice-actions button")
            focused = page.evaluate(
                "(document.activeElement||{}).textContent || null")
            page.key("Enter", "Enter", 13, text="\r")
            check("green: Enter on the first notice button opens Evidence",
                  active_tab(page) == "evidence" and focused in ("Evidence",
                                                                 "证据"),
                  "tab=%s focused=%r" % (active_tab(page), focused))
            page.focus(".revoked-notice-actions button:nth-of-type(2)")
            page.key("Enter", "Enter", 13, text="\r")
            check("green: Enter on the second notice button opens Events",
                  active_tab(page) == "events", active_tab(page) or "none")
            # tab arrows still move between tabs with the notice present
            page.focus('#detail-body .tabs [data-tab="decisions"]')
            page.key("ArrowRight", "ArrowRight", 39)
            check("green: tab ArrowRight navigation intact",
                  active_tab(page) == "documents", active_tab(page) or "none")

            # --- polling keeps the notice without stealing focus -------
            select_work(page, "succeed-closed")
            page.evaluate(
                "document.querySelector('.work-item[data-work-id="
                "\"succeed-closed\"]').focus()")
            time.sleep(5.6)  # at least one 5s poll while selected
            kept = notice_state(page)
            focus_id = page.evaluate(
                "(document.activeElement && document.activeElement.dataset)"
                " ? document.activeElement.dataset.workId : null")
            check("green: poll refresh keeps the notice and list focus",
                  kept and kept.get("present") and focus_id == "succeed-closed",
                  "present=%s focus=%r" % (kept and kept.get("present"),
                                           focus_id))

            # --- disconnect banner + recovery on the same port ----------
            server.kill()
            page.click("#refresh")
            disconnected = wait_true(
                page,
                "!document.getElementById('connection-banner')"
                ".classList.contains('hidden')", timeout=15)
            check("green: server loss raises the disconnected banner",
                  bool(disconnected), "banner hidden?")
            server = start_server(db_path, port=port)
            page.click("#refresh")
            recovered = wait_true(
                page,
                "document.getElementById('connection-banner')"
                ".classList.contains('hidden')", timeout=15)
            kept = notice_state(page)
            check("green: recovery clears the banner, notice intact",
                  bool(recovered) and kept and kept.get("present"),
                  "recovered=%s present=%s" % (bool(recovered),
                                               kept and kept.get("present")))

            # --- bilingual toggle --------------------------------------
            ensure_lang(page, "zh")
            zh = notice_state(page)
            check("green: ZH notice distinguishes history/current",
                  ZH_TITLE in zh["text"] and ZH_BODY_MARK in zh["text"]
                  and cited_id in (zh["cited"] or "") and "1" in zh["cited"],
                  repr(zh["text"][:140]))
            ensure_lang(page, "en")

            # --- screenshots -------------------------------------------
            for width, height, tag in ((1440, 900, "desktop"),
                                       (390, 844, "n390"),
                                       (320, 690, "n320")):
                page.set_viewport(width, height)
                select_work(page, "succeed-closed")
                page.evaluate(
                    "document.querySelector(%s)"
                    ".scrollIntoView({block:'center'})" % json.dumps(NOTICE))
                page.screenshot(os.path.join(
                    shots, "%s-succeed-closed-%s.png" % (phase, tag)))
                hscroll = page.evaluate(
                    "document.documentElement.scrollWidth > "
                    "document.documentElement.clientWidth")
                check("green: no horizontal overflow at %dpx" % width,
                      hscroll is False, "scrollWidth exceeds clientWidth")
            page.set_viewport(1440, 900)
            select_work(page, "clean-closed")
            page.screenshot(os.path.join(
                shots, "%s-clean-closed-desktop.png" % phase))
            page.set_viewport(390, 844)
            select_work(page, "clean-closed")
            page.screenshot(os.path.join(
                shots, "%s-clean-closed-n390.png" % phase))
            ensure_lang(page, "zh")
            page.set_viewport(1440, 900)
            select_work(page, "succeed-closed")
            page.screenshot(os.path.join(
                shots, "%s-succeed-closed-zh.png" % phase))
            ensure_lang(page, "en")
            select_work(page, "succeed-closed")
            open_tab(page, "evidence")
            page.screenshot(os.path.join(
                shots, "%s-succeed-closed-evidence.png" % phase))

        after_digest = snapshot(db_path)
        check("%s: all six store tables byte-identical after the session"
              % phase, before_digest == after_digest,
              "%s… vs %s…" % (before_digest[:12], after_digest[:12]))

        fail = 0 if all(audit.RESULTS) else 1
        summary = {"phase": phase, "checks": audit.RECORD.get("checks", []),
                   "measurements": audit.RECORD.get("measurements", {}),
                   "ok": fail == 0, "store": db_path}
    finally:
        if page:
            page.close()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        server.kill()
        with open(os.path.join(out, "%s-results.json" % phase), "w") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=1)
    print("%s phase: %d checks, %d passed, exit %d"
          % (phase, len(audit.RESULTS), sum(audit.RESULTS), fail), flush=True)
    return fail


if __name__ == "__main__":
    sys.exit(main())
