#!/usr/bin/env python3
"""S7 GUI audit — actual headless Chrome over CDP, standard library only.

Captures the S7 before/after evidence matrix on a real `ui-demo` store and
asserts, in actual Chrome, the behavior, integrity and (after phase) the
ratified D30/D31 visual requirements for the offline bilingual read-only
operations viewer.

Fixes the known S5 empty-list readiness race: the empty state is asserted
only after `#list-status` has settled to a non-empty, non-loading text, so
"not loaded yet" can never pass for "loaded and empty".

Evidence phases:
  --phase before  run on the untouched checkout: assert unchanged
                  behavioral/integrity checks; RECORD visual measurements
                  (tokens, typography, radii, shadows, 44px targets,
                  contrast, page-overflow geometry) as baseline values
                  without failing on them.
  --phase after   same flow; additionally assert the ratified visual
                  requirements and measured contrast.

Stores:
  - demo   real `ui-demo` seed (real commands, real FakeOA) — the matrix,
                  interactions and the six-table no-writes proof run here.
  - empty  labeled harness fixture: stdlib-sqlite copy of the demo DB with
                  the five data tables emptied (metadata kept). Fixture, not
                  runtime-seeded data.
  - xss    labeled harness fixture: copy with hostile markup and huge
                  integer payloads injected into stored text fields.
  - gone   labeled harness fixture, harness-mutated mid-run (a work row is
                  deleted while selected) to reach the UNKNOWN_WORK state,
                  then its server is killed for the disconnect state. It is
                  therefore excluded from the no-writes comparison.

Input trust: every keyboard claim is delivered through CDP
Input.dispatchKeyEvent; clicks through Input.dispatchMouseEvent at real
element coordinates; text through Input.insertText. DOM .click() is never
used as interaction evidence.

Usage: s7_gui_audit.py --phase before|after --out DIR [--chrome PATH] [--keep]
Exit 0 when all assertions for the phase pass; 1 otherwise.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

WORKS = ["wait-1", "uncertain-1", "transfer-1", "succeed-1", "cancel-1"]
WIDTHS = [(1440, 900), (390, 844), (320, 690)]
TABLES = ["works", "commands", "evidence", "operations", "events", "metadata"]
HUGE = "9007199254740993"            # 2**53 + 1: not representable as float64
HUGE2 = "123456789012345678901234567890"
HOSTILE = '<img src=x onerror="window.__xssEvil=1">'
HOSTILE_SCRIPT = "<script>window.__xssEvil=2</script>"

RESULTS = []
RECORD = {}          # visual measurements + check outcomes for the JSON dump


def check(name, ok, observed):
    RESULTS.append(bool(ok))
    print("%s %s — %s" % ("PASS" if ok else "FAIL", name, observed), flush=True)
    RECORD["checks"] = RECORD.get("checks", [])
    RECORD["checks"].append({"name": name, "ok": bool(ok), "observed": observed})


def measure(name, value):
    """Record a visual measurement without asserting it (baseline phase)."""
    print("MEAS %s — %s" % (name, value), flush=True)
    RECORD["measurements"] = RECORD.get("measurements", {})
    RECORD["measurements"][name] = value


# --------------------------------------------------------------------------
# Minimal CDP client (adapted from .agents/notes/2026-10-14-S5-browser-regression.py)
# --------------------------------------------------------------------------

class CdpPage:
    def __init__(self, ws_host_port, target_id):
        self.url = "ws://%s/devtools/page/%s" % (ws_host_port, target_id)
        import socket
        host, port = ws_host_port.rsplit(":", 1)
        self.sock = socket.create_connection((host, int(port)), timeout=60)
        key = base64.b64encode(os.urandom(16)).decode()
        request = ("GET /devtools/page/%s HTTP/1.1\r\nHost: %s\r\n"
                   "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                   "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n"
                   % (target_id, ws_host_port, key))
        self.sock.sendall(request.encode())
        header = b""
        while b"\r\n\r\n" not in header:
            chunk = self.sock.recv(1)
            if not chunk:
                raise RuntimeError("websocket handshake ended early")
            header += chunk
        if b" 101 " not in header.split(b"\r\n", 1)[0]:
            raise RuntimeError("websocket handshake failed: %r" % header[:120])
        self.buffer = b""
        self.next_id = 0

    def _read_exact(self, count):
        while len(self.buffer) < count:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("socket closed mid-frame")
            self.buffer += chunk
        data, self.buffer = self.buffer[:count], self.buffer[count:]
        return data

    def _send_frame(self, opcode, payload):
        mask = os.urandom(4)
        header = bytes([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header += bytes([0x80 | length])
        elif length < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", length)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", length)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def _recv_text(self):
        while True:
            head = self._read_exact(2)
            opcode = head[0] & 0x0F
            length = head[1] & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read_exact(8))[0]
            payload = self._read_exact(length)
            if opcode == 1:
                return json.loads(payload.decode("utf-8"))
            if opcode == 9:
                self._send_frame(10, payload)
            elif opcode == 8:
                raise RuntimeError("websocket closed by server")

    def call(self, method, params=None):
        self.next_id += 1
        call_id = self.next_id
        self._send_frame(1, json.dumps(
            {"id": call_id, "method": method, "params": params or {}}).encode())
        while True:
            message = self._recv_text()
            if message.get("id") == call_id:
                if "error" in message:
                    raise RuntimeError("CDP error %s: %s"
                                       % (method, message["error"]))
                return message.get("result", {})

    def evaluate(self, expression):
        result = self.call("Runtime.evaluate",
                           {"expression": expression, "returnByValue": True})
        if result.get("exceptionDetails"):
            raise RuntimeError("page exception: %s"
                               % result["exceptionDetails"].get("text"))
        return result.get("result", {}).get("value")

    def json_eval(self, expression):
        raw = self.evaluate(expression)
        try:
            return json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return None

    # ---- trusted input ----------------------------------------------------

    def key(self, name, code, vk, text=None):
        params = {"type": "keyDown", "key": name, "code": code,
                  "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
        if text:
            params["text"] = text
        self.call("Input.dispatchKeyEvent", params)
        release = {"type": "keyUp", "key": name, "code": code,
                   "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
        self.call("Input.dispatchKeyEvent", release)

    def insert_text(self, text):
        self.call("Input.insertText", {"text": text})

    def click(self, selector):
        box = self.json_eval(
            "(function(){var e=document.querySelector(%s);"
            "if(!e||!e.getBoundingClientRect){return null;}"
            "e.scrollIntoView({block:'center'});"
            "var r=e.getBoundingClientRect();"
            "return {x:r.left+r.width/2,y:r.top+r.height/2,"
            "w:r.width,h:r.height};})()" % json.dumps(selector))
        if not box:
            return False
        for typ in ("mousePressed", "mouseReleased"):
            self.call("Input.dispatchMouseEvent", {
                "type": typ, "x": box["x"], "y": box["y"],
                "button": "left", "clickCount": 1})
        return True

    def focus(self, selector):
        return self.evaluate(
            "(function(){var e=document.querySelector(%s);"
            "if(e){e.focus();return true;}return false;})()"
            % json.dumps(selector))

    # ---- viewport / network / capture --------------------------------------

    def set_viewport(self, width, height):
        self.call("Emulation.setDeviceMetricsOverride",
                  {"width": width, "height": height,
                   "deviceScaleFactor": 1, "mobile": False})

    def navigate(self, url):
        self.call("Page.navigate", {"url": url})

    def reload(self):
        self.call("Page.reload", {})

    def latency(self, ms):
        self.call("Network.enable", {})
        self.call("Network.emulateNetworkConditions", {
            "offline": False, "latency": ms,
            "downloadThroughput": -1, "uploadThroughput": -1})

    def screenshot(self, path):
        data = self.call("Page.captureScreenshot", {"format": "png"})["data"]
        with open(path, "wb") as handle:
            handle.write(base64.b64decode(data))

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


# --------------------------------------------------------------------------
# WCAG contrast (Python-side, over computed colors from the real DOM)
# --------------------------------------------------------------------------

def _lin(component):
    component = component / 255.0
    return component / 12.92 if component <= 0.04045 \
        else ((component + 0.055) / 1.055) ** 2.4


def parse_rgb(text):
    if not text:
        return None
    match = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)", text)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)),
            float(match.group(4)) if match.group(4) is not None else 1.0)


def blend(fg, bg):
    """Composite fg over bg (both rgba tuples) — alpha text over surface."""
    if fg[3] >= 1.0:
        return fg[:3]
    if bg is None:
        bg = (255, 255, 255, 1.0)
    return tuple(round(fg[i] * fg[3] + bg[i] * (1 - fg[3])) for i in range(3))


def ratio(fg_text, bg_text):
    fg, bg = parse_rgb(fg_text), parse_rgb(bg_text)
    if not fg or not bg:
        return None
    f = blend(fg, bg)
    b = blend(bg, (255, 255, 255, 1.0)) if bg[3] < 1.0 else bg[:3]
    lf = 0.2126 * _lin(f[0]) + 0.7152 * _lin(f[1]) + 0.0722 * _lin(f[2])
    lb = 0.2126 * _lin(b[0]) + 0.7152 * _lin(b[1]) + 0.0722 * _lin(b[2])
    lighter, darker = max(lf, lb), min(lf, lb)
    return (lighter + 0.05) / (darker + 0.05)


def page_pair(page, selector, prop="color", bg_prop="backgroundColor"):
    """Computed (foreground, background) for the first element matching."""
    return page.json_eval(
        "(function(){var e=document.querySelector(%s);if(!e){return null;}"
        "var s=getComputedStyle(e);return {fg:s.%s,bg:s.%s};})()"
        % (json.dumps(selector), prop, bg_prop))


def measure_contrast(page, label, selector, minimum, phase,
                     prop="color", bg_prop="backgroundColor"):
    pair = page_pair(page, selector, prop, bg_prop)
    if not pair:
        # F1: a required measurement whose element never appeared must not
        # pass silently — record it and fail a check in every phase, so the
        # audit cannot exit 0 with this measurement omitted.
        measure("contrast " + label, "element missing")
        check("contrast %s >= %.2f" % (label, minimum), False,
              "element missing — selector %s matched nothing" % selector)
        return
    value = ratio(pair["fg"], pair["bg"])
    entry = {"fg": pair["fg"], "bg": pair["bg"], "ratio": value}
    measure("contrast " + label, entry)
    if phase == "after":
        check("contrast %s >= %.2f" % (label, minimum),
              value is not None and value >= minimum,
              "%s on %s = %.2f" % (pair["fg"], pair["bg"], value or -1))


# --------------------------------------------------------------------------
# Servers, fixtures, snapshots
# --------------------------------------------------------------------------

class UiServer:
    def __init__(self, argv, cwd):
        self.proc = subprocess.Popen(
            argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True)
        self.url = None
        deadline = time.time() + 90
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                break
            match = re.search(r"(http://127\.0\.0\.1:\d+/)", line)
            if match:
                self.url = match.group(1)
                break
        if not self.url:
            self.kill()
            raise RuntimeError("ui server never printed a URL: %r" % argv)

    def kill(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def snapshot(db_path):
    """Digest of all six persisted tables, ordered, via a read-only URI."""
    digest = hashlib.sha256()
    uri = "file:%s?mode=ro" % db_path
    db = sqlite3.connect(uri, uri=True)
    try:
        for table in TABLES:
            digest.update(table.encode())
            for row in db.execute(
                    "SELECT * FROM %s ORDER BY 1, 2" % table):
                digest.update(repr(row).encode())
    finally:
        db.close()
    return digest.hexdigest()


def backup_copy(src, dst):
    db = sqlite3.connect(src)
    try:
        target = sqlite3.connect(dst)
        try:
            db.backup(target)
            # The source runs in WAL mode; a checkpointed copy served from a
            # fresh path must not depend on -wal/-shm side files.
            target.execute("PRAGMA journal_mode=DELETE")
            target.commit()
        finally:
            target.close()
    finally:
        db.close()


def make_empty_fixture(src, dst):
    backup_copy(src, dst)
    db = sqlite3.connect(dst)
    try:
        for table in ("works", "commands", "evidence", "operations", "events"):
            db.execute("DELETE FROM %s" % table)
        db.commit()
    finally:
        db.close()


def make_xss_fixture(src, dst):
    """Hostile markup + huge integers inside stored text fields (a copy)."""
    backup_copy(src, dst)
    db = sqlite3.connect(dst)
    try:
        row = db.execute(
            "SELECT state FROM works WHERE id='wait-1'").fetchone()
        state = json.loads(row[0])
        state["state_version"] = int(HUGE)          # exactness via _decimal
        contract = state.get("contract")
        if not isinstance(contract, dict):
            contract = {}
            state["contract"] = contract
        contract["goal"] = HOSTILE + " 目标" + HOSTILE_SCRIPT
        db.execute("UPDATE works SET state=? WHERE id='wait-1'",
                   (json.dumps(state, ensure_ascii=False),))
        db.execute(
            "UPDATE events SET version=?, body=? WHERE work_id='wait-1'"
            " AND seq=(SELECT MIN(seq) FROM events WHERE work_id='wait-1')",
            # body stays VALID stored JSON (the reader rejects non-JSON);
            # the hostile markup lives inside a JSON string value and the
            # huge integer beyond int64 lives in the raw text.
            (int(HUGE), json.dumps(
                {"note": HOSTILE_SCRIPT, "huge": int(HUGE2)},
                ensure_ascii=False)))
        evd = db.execute(
            "SELECT body FROM evidence WHERE work_id='wait-1' LIMIT 1"
        ).fetchone()
        if evd:
            proof = json.loads(evd[0])
            if isinstance(proof.get("data"), dict):
                proof["data"]["hostile"] = HOSTILE
            else:
                proof["data"] = HOSTILE
            db.execute(
                "UPDATE evidence SET body=? WHERE work_id='wait-1'"
                " AND source=(SELECT source FROM evidence WHERE"
                " work_id='wait-1' LIMIT 1)",
                (json.dumps(proof, ensure_ascii=False),))
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------
# Page-level helpers
# --------------------------------------------------------------------------

def loading_text(text):
    if not text:
        return False
    return text.endswith("…") or "Loading" in text or "正在加载" in text


def list_state(page):
    return page.json_eval(
        "JSON.stringify({items: document.querySelectorAll("
        "'#work-list .work-item').length, "
        "status: document.getElementById('list-status').textContent,"
        "lang: document.documentElement.lang})")


def settle_list(page, timeout=20.0):
    """S5 race fix: wait until #list-status settled (non-empty, not loading),
    then also wait one extra poll beat so a transient empty-vs-error flip
    cannot pass as settled."""
    deadline = time.time() + timeout
    state = None
    while time.time() < deadline:
        try:
            state = list_state(page)
        except RuntimeError:
            state = None
        if state and state.get("status") and not loading_text(state["status"]):
            return state
        time.sleep(0.2)
    return state


def wait_true(page, expression, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if page.evaluate(expression):
                return True
        except RuntimeError:
            pass
        time.sleep(0.2)
    return False


def wait_detail(page, work_id, timeout=15.0):
    return wait_true(
        page,
        "(function(){var e=document.querySelector('.detail-title');"
        "return !!e && e.textContent === %s;})()" % json.dumps(work_id),
        timeout)


def select_work(page, work_id):
    if not page.click('.work-item[data-work-id="%s"]' % work_id):
        return False
    return wait_detail(page, work_id)


def ensure_lang(page, want):
    """Locale-agnostic language control: navigator.language follows the
    machine's system locale, so never assume the initial language — read it
    and toggle through the real button when needed."""
    current = page.evaluate("document.documentElement.lang")
    if current != want:
        page.click("#lang-toggle")
        wait_true(page, "document.documentElement.lang === %s" % json.dumps(want))
    return page.evaluate("document.documentElement.lang")


def open_tab(page, tab):
    if not page.click('#detail-body .tabs [data-tab="%s"]' % tab):
        return False
    return wait_true(
        page,
        '(function(){var p=document.querySelector("#detail-body .tabpanel");'
        "return !!p && p.children.length > 0;})()")


def active_tab(page):
    return page.evaluate(
        "(function(){var e=document.querySelector("
        "'#detail-body .tabs .tab[aria-selected=\"true\"]');"
        "return e ? e.dataset.tab : null;})()")


def visual_dump(page, phase, label):
    """Computed tokens/typography/geometry — recorded, asserted after-only."""
    data = page.json_eval("""
JSON.stringify((function(){
  function cs(sel, props){var e=document.querySelector(sel);if(!e){return null;}
    var s=getComputedStyle(e),o={};props.forEach(function(p){o[p]=s[p];});return o;}
  var root=getComputedStyle(document.documentElement);
  var tokens={};["--color-canvas","--color-canvas-soft","--color-surface-card",
    "--color-surface-strong","--color-hairline","--color-hairline-strong",
    "--color-ink","--color-body","--color-accent","--color-accent-active",
    "--color-on-ink","--color-success","--color-success-soft","--color-warn",
    "--color-warn-soft","--color-error","--color-error-soft",
    "--color-neutral-soft","--radius-control","--radius-card","--radius-chip",
    "--space-xxs","--space-xs","--space-sm","--space-base","--space-md",
    "--space-lg","--font-sans","--font-mono","--content-max",
    "--tracking-display-md","--tracking-display-sm"
  ].forEach(function(t){tokens[t]=root.getPropertyValue(t).trim();});
  var geometry={};
  [["#refresh","refresh"],["#lang-toggle","langToggle"],
   ["#work-search","search"],["#status-filter","statusFilter"],
   ["#detail-body .tabs .tab","tab"],[".work-item","workItem"],
   ["details.raw-block summary","summary"]].forEach(function(pair){
    var e=document.querySelector(pair[0]);
    geometry[pair[1]]=e?{height:e.offsetHeight,width:e.offsetWidth}:null;});
  return {
    tokens: tokens,
    body: cs("body",["backgroundColor","color","fontFamily","fontSize",
                     "overflowX"]),
    htmlOverflowX: getComputedStyle(document.documentElement).overflowX,
    card: cs(".tile",["backgroundColor","borderRadius","borderTopWidth",
                      "borderTopColor","boxShadow"]),
    detailCard: cs(".detail-body",["backgroundColor","borderRadius",
                                   "borderTopColor","boxShadow"]),
    button: cs("#refresh",["borderRadius","backgroundColor","color"]),
    input: cs("#work-search",["borderRadius"]),
    chip: cs(".chip",["borderRadius","backgroundColor","color"]),
    tileValue: cs(".tile-value",["fontSize","fontWeight","letterSpacing"]),
    detailTitle: cs(".detail-title",["fontSize","fontWeight","letterSpacing",
                                     "fontFamily"]),
    label: cs(".tabpanel h3",["fontSize","fontWeight"]),
    mono: cs(".mono",["fontFamily","fontSize"]),
    raw: cs("pre.raw",["fontFamily","fontSize"]),
    tabSelected: cs('.tab[aria-selected="true"]',
                    ["backgroundColor","color"]),
    workSelected: cs('.work-item[aria-selected="true"]',["borderTopColor",
                                                         "backgroundColor"]),
    layout: cs(".layout",["gridTemplateColumns","maxWidth"]),
    note: cs(".note",["color","backgroundColor"]),
    tileDesc: cs(".tile-desc",["color"]),
    fieldsDt: cs(".fields dt",["color"]),
    tableTh: cs("table.data th",["color","backgroundColor"]),
    geometry: geometry,
    fonts: {
      jetbrains: document.fonts.check("13px 'JetBrains Mono'"),
      pingfang: document.fonts.check("13px 'PingFang SC'")
    },
    page: {
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth
    }
  };
})())""")
    data = data or {}
    measure("visual/" + label, data)
    return data


def assert_visual(page, phase, data, label):
    """Assert ratified visual requirements (after phase only)."""
    if phase != "after" or not data:
        return

    def eq(name, actual, expected):
        check("%s %s == %s" % (label, name, expected),
              actual == expected, repr(actual))

    def has(name, actual, expected):
        check("%s %s contains %s" % (label, name, expected),
              actual is not None and expected in str(actual), repr(actual))

    body = data.get("body") or {}
    eq("body background", body.get("backgroundColor"), "rgb(247, 247, 244)")
    eq("body color", body.get("color"), "rgb(38, 37, 30)")
    eq("body overflow-x", body.get("overflowX"), "visible")
    eq("html overflow-x", data.get("htmlOverflowX"), "visible")
    card = data.get("card") or {}
    eq("card radius", card.get("borderRadius"), "12px")
    eq("card border", (card.get("borderTopWidth"), card.get("borderTopColor")),
       ("1px", "rgb(230, 229, 224)"))
    eq("card background", card.get("backgroundColor"), "rgb(255, 255, 255)")
    eq("card shadow", card.get("boxShadow"), "none")
    detail = data.get("detailCard") or {}
    eq("detail card radius", detail.get("borderRadius"), "12px")
    eq("detail card shadow", detail.get("boxShadow"), "none")
    eq("button radius", (data.get("button") or {}).get("borderRadius"), "8px")
    eq("input radius", (data.get("input") or {}).get("borderRadius"), "8px")
    eq("chip pill radius", (data.get("chip") or {}).get("borderRadius"),
       "9999px")
    tile_value = data.get("tileValue") or {}
    eq("tile value 26px/400", (tile_value.get("fontSize"),
                               tile_value.get("fontWeight")), ("26px", "400"))
    title = data.get("detailTitle") or {}
    eq("detail title 22px/400", (title.get("fontSize"),
                                 title.get("fontWeight")), ("22px", "400"))
    has("detail title mono", title.get("fontFamily"), "JetBrains Mono")
    has("mono family", (data.get("mono") or {}).get("fontFamily"),
        "JetBrains Mono")
    # pre.raw only exists on raw-data tabs; asserted at the documents step
    lab = data.get("label") or {}
    eq("section label 16px/600", (lab.get("fontSize"), lab.get("fontWeight")),
       ("16px", "600"))
    tab_sel = data.get("tabSelected") or {}
    eq("selected tab ink/canvas",
       (tab_sel.get("backgroundColor"), tab_sel.get("color")),
       ("rgb(38, 37, 30)", "rgb(247, 247, 244)"))
    eq("primary control ink/canvas",
       ((data.get("button") or {}).get("backgroundColor"),
        (data.get("button") or {}).get("color")),
       ("rgb(38, 37, 30)", "rgb(247, 247, 244)"))
    work_sel = data.get("workSelected") or {}
    eq("selected work ink border", work_sel.get("borderTopColor"),
       "rgb(38, 37, 30)")
    layout = data.get("layout") or {}
    eq("content cap", layout.get("maxWidth"), "1200px")
    tracks = len([t for t in str(layout.get("gridTemplateColumns",
                                            "")).split() if t])
    expected_tracks = 2 if label.startswith("1440") else 1
    check("%s layout tracks == %d" % (label, expected_tracks),
          tracks == expected_tracks,
          repr(layout.get("gridTemplateColumns")))
    geometry = data.get("geometry") or {}
    for target, box in geometry.items():
        if box is None:
            measure("%s %s target absent on this tab" % (label, target), None)
            continue
        check("%s %s target >= 44px" % (label, target),
              box.get("height", 0) >= 44, repr(box))
    pagebox = data.get("page") or {}
    check("%s no page-level horizontal overflow" % label,
          pagebox.get("scrollWidth", 10 ** 9)
          <= pagebox.get("clientWidth", 0) + 1,
          repr(pagebox))
    tokens = data.get("tokens") or {}
    for name in ("--color-canvas", "--color-ink", "--color-body",
                 "--color-accent", "--color-hairline", "--color-hairline-strong",
                 "--radius-control", "--radius-card", "--font-sans",
                 "--font-mono", "--content-max"):
        check("%s token %s defined" % (label, name),
              bool(tokens.get(name)), repr(tokens.get(name)))
    eq("token canvas", tokens.get("--color-canvas"), "#f7f7f4")
    eq("token ink", tokens.get("--color-ink"), "#26251e")
    eq("token body", tokens.get("--color-body"), "#5a5852")
    eq("token accent", tokens.get("--color-accent"), "#f54e00")
    eq("token hairline", tokens.get("--color-hairline"), "#e6e5e0")
    eq("token hairline strong", tokens.get("--color-hairline-strong"),
       "#cfcdc4")
    eq("token content cap", tokens.get("--content-max"), "1200px")


def focus_outline(page, phase, shots_dir):
    """Keyboard focus a tab (trusted arrows after programmatic focus) and
    capture the focus outline."""
    if not page.evaluate(
            "!!document.querySelector('#detail-body .tabs .tab')"):
        check("focus outline captured", False, "no detail tabs to focus")
        return None
    page.focus("#detail-body .tabs .tab")
    page.key("ArrowRight", "ArrowRight", 39)
    outline = page.json_eval(
        "(function(){var a=document.activeElement;var s=getComputedStyle(a);"
        "return {tab:a.dataset.tab, style:s.outlineStyle,"
        "width:s.outlineWidth, color:s.outlineColor,"
        "offset:s.outlineOffset, connected:a.isConnected};})()")
    measure("focus outline", outline)
    page.screenshot(os.path.join(shots_dir, "view-focus-outline.png"))
    if phase == "after" and outline:
        check("focus outline solid 2px orange offset 2px",
              outline.get("style") == "solid"
              and outline.get("width") == "2px"
              and outline.get("color") == "rgb(245, 78, 0)"
              and outline.get("offset") == "2px",
              repr(outline))
        outline_ratio = ratio(outline.get("color"), "rgb(255, 255, 255)")
        measure("contrast focus outline on white card",
                {"ratio": outline_ratio})
        check("focus outline non-text contrast >= 3.0 on white",
              outline_ratio is not None and outline_ratio >= 3.0,
              repr(outline_ratio))
    return outline


def assert_zh_tracking(page, phase):
    ensure_lang(page, "zh")
    if not page.evaluate("!!document.querySelector('.detail-title')"):
        select_work(page, "wait-1")   # tracking needs an open detail title
    value = page.json_eval(
        "JSON.stringify({"
        "title:(function(){var e=document.querySelector('.detail-title');"
        "return e?getComputedStyle(e).letterSpacing:null;})(),"
        "tile:(function(){var e=document.querySelector('.tile-value');"
        "return e?getComputedStyle(e).letterSpacing:null;})()})")
    measure("zh letter-spacing", value)
    if phase == "after" and value:
        # Chrome computes letter-spacing 0 as "normal"
        check("zh display tracking zero",
              value.get("title") in ("0px", "normal")
              and value.get("tile") in ("0px", "normal"),
              repr(value))


# --------------------------------------------------------------------------
# Main flow
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["before", "after"], required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--chrome",
                        default="/Applications/Google Chrome.app/Contents/"
                                "MacOS/Google Chrome")
    parser.add_argument("--keep", action="store_true",
                        help="keep the seeded stores for reuse/inspection")
    args = parser.parse_args()

    out = os.path.abspath(args.out)
    shots = os.path.join(out, "%s-matrix" % args.phase)
    views = os.path.join(out, "%s-views" % args.phase)
    for path in (shots, views):
        os.makedirs(path, exist_ok=True)
    RECORD["phase"] = args.phase

    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))
    # Stores live outside the evidence tree: the out dir receives only the
    # screenshots and JSON that belong in the acceptance assets.
    workdir = tempfile.mkdtemp(prefix="s7-audit-stores-")

    # ---- stores ------------------------------------------------------------
    demo = UiServer([sys.executable, "-m", "work_runtime", "ui-demo",
                     "--directory", workdir], cwd=repo)
    demo_db = None
    seed_log = os.path.join(workdir, "demo-seed-path.txt")
    # ui-demo prints the seeded store path; find the newest runtime.sqlite.
    time.sleep(0.2)
    candidates = sorted(
        (os.path.join(workdir, d, "runtime.sqlite")
         for d in os.listdir(workdir)
         if os.path.isfile(os.path.join(workdir, d, "runtime.sqlite"))),
        key=os.path.getmtime)
    if not candidates:
        demo.kill()
        raise RuntimeError("no seeded runtime.sqlite found under " + workdir)
    demo_db = candidates[-1]
    with open(seed_log, "w") as handle:
        handle.write(demo_db + "\n")

    empty_db = os.path.join(workdir, "fixture-empty.sqlite")
    xss_db = os.path.join(workdir, "fixture-xss.sqlite")
    gone_db = os.path.join(workdir, "fixture-gone.sqlite")
    make_empty_fixture(demo_db, empty_db)
    make_xss_fixture(demo_db, xss_db)
    backup_copy(demo_db, gone_db)

    empty = UiServer([sys.executable, "-m", "work_runtime", "ui",
                      "--db", empty_db], cwd=repo)
    xss = UiServer([sys.executable, "-m", "work_runtime", "ui",
                    "--db", xss_db], cwd=repo)
    gone = UiServer([sys.executable, "-m", "work_runtime", "ui",
                     "--db", gone_db], cwd=repo)

    snapshots_before = {name: snapshot(path) for name, path in
                        (("demo", demo_db), ("empty", empty_db),
                         ("xss", xss_db))}

    # ---- chrome ------------------------------------------------------------
    profile = tempfile.mkdtemp(prefix="s7-cdp-profile-")
    proc = subprocess.Popen(
        [args.chrome, "--headless", "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", "--lang=en-US",
         "--remote-debugging-port=0",
         "--user-data-dir=" + profile, "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    page = None
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
        new = urllib.request.Request("http://%s/json/new?about:blank" % devtools,
                                     method="PUT")
        target = json.load(urllib.request.urlopen(new, timeout=10))
        page = CdpPage(devtools, target["id"])

        # ---------- behavioral checks, demo store, 1440 en -----------------
        page.set_viewport(1440, 900)
        page.navigate(demo.url)
        state = settle_list(page)
        check("first load renders 5 works without interaction",
              state and state.get("items") == 5,
              json.dumps(state, ensure_ascii=False))
        check("first load settles past loading",
              state and not loading_text(state.get("status", "")),
              repr(state and state.get("status")))

        def focused_work():
            return page.evaluate(
                "(document.activeElement && document.activeElement.dataset)"
                " ? document.activeElement.dataset.workId : null")

        page.evaluate(
            "document.querySelector('.work-item').focus()")
        first = focused_work()
        page.key("ArrowDown", "ArrowDown", 40)
        page.key("ArrowDown", "ArrowDown", 40)
        second = focused_work()
        page.key("Enter", "Enter", 13, text="\r")
        entered = wait_detail(page, second) if second else False
        check("keyboard: ArrowDown x2 + Enter selects the focused work",
              bool(first) and bool(second) and first != second and entered,
              "first=%r second=%r detail=%r" % (
                  first, second, page.evaluate(
                      "(function(){var e=document.querySelector("
                      "'.detail-title');return e?e.textContent:null;})()")))

        # list arrows move focus (trusted keys), order-independent
        page.focus("#work-list .work-item")
        before = focused_work()
        page.key("ArrowDown", "ArrowDown", 40)
        after = focused_work()
        check("list ArrowDown moves focus to the next work item",
              bool(before) and bool(after) and before != after,
              "%r -> %r" % (before, after))

        # tab arrows keep focus on the live selected tab (S5 regression)
        detail_open = page.evaluate(
            "!!document.querySelector('#detail-body .tabs .tab')")
        if not detail_open:
            check("tab ArrowRight/Left keep focus on live selected tab",
                  False, "detail view never opened; cannot reach the tabs")
        else:
            page.focus("#detail-body .tabs .tab")
            sequence = (("ArrowRight", 39), ("ArrowRight", 39),
                        ("ArrowLeft", 37), ("ArrowRight", 39))
            ok_arrows = True
            for step, (key_name, vk) in enumerate(sequence):
                page.key(key_name, key_name, vk)
                time.sleep(0.15)   # let the app rebuild + refocus settle
                obs = page.json_eval(
                    "JSON.stringify({active:(function(){var a="
                    "document.activeElement;return (a===document.body)?"
                    "'BODY':(a.classList&&a.classList.contains('tab'))?"
                    "a.dataset.tab:a.tagName;})(), connected: "
                    "document.activeElement.isConnected, selected: "
                    "document.querySelector('#detail-body .tab["
                    "aria-selected=\"true\"]').dataset.tab})")
                measure("tab arrow step %d" % step, obs)
                ok_arrows = ok_arrows and obs \
                    and obs["active"] == obs["selected"] \
                    and obs["connected"] and obs["active"] != "BODY"
            check("tab ArrowRight/Left keep focus on live selected tab",
                  ok_arrows, "4 trusted key presses at 1440")

        outline = focus_outline(page, args.phase, views)

        # "/" focuses search; typing filters (trusted input)
        page.key("/", "Slash", 191)
        in_search = page.evaluate(
            "document.activeElement === "
            "document.getElementById('work-search')")
        check("\"/\" focuses the search box", in_search,
              repr(page.evaluate(
                  "(document.activeElement||{}).id")))
        page.insert_text("succeed")
        state = settle_list(page)
        check("typing filters the list to 1 work",
              state and state.get("items") == 1,
              json.dumps(state, ensure_ascii=False))
        for _ in range(len("succeed")):
            page.key("Backspace", "Backspace", 8)
        state = settle_list(page)
        check("clearing the filter restores 5 works",
              state and state.get("items") == 5,
              json.dumps(state, ensure_ascii=False))

        # status filter via keyboard on the native select (focus, then
        # trusted keys: ArrowDown steps to the next option; if this Chrome
        # build ignores arrow keys on selects, fall back to the native
        # type-to-jump letter, still a trusted key event)
        page.focus("#status-filter")
        focus_landed = page.evaluate(
            "document.activeElement && document.activeElement.id "
            "=== 'status-filter'")
        page.key("ArrowDown", "ArrowDown", 40)
        chosen = page.evaluate(
            "document.getElementById('status-filter').value")
        mechanism = "ArrowDown"
        if chosen == "":
            page.key("w", "KeyW", 87, text="w")
            chosen = page.evaluate(
                "document.getElementById('status-filter').value")
            mechanism = "letter w jump"
        state = settle_list(page)
        items_after = (state or {}).get("items")
        check("status filter keyboard select filters the list",
              focus_landed and chosen == "waiting" and items_after == 1,
              "focus=%r mechanism=%s chosen=%r items=%r" % (
                  focus_landed, mechanism, chosen, items_after))
        # back to "All statuses": ArrowUp steps back if arrows drive this
        # select; otherwise reload the page (a fresh, unfiltered load) and
        # verify the full list returns.
        for _ in range(6):
            if page.evaluate(
                    "document.getElementById('status-filter').value") == "":
                break
            page.key("ArrowUp", "ArrowUp", 38)
        if page.evaluate(
                "document.getElementById('status-filter').value") != "":
            page.navigate(demo.url)
        state = settle_list(page)
        chosen_back = page.evaluate(
            "document.getElementById('status-filter').value")
        check("status filter back to all restores 5 works",
              state and chosen_back == "" and state.get("items") == 5,
              "chosen=%r state=%s" % (chosen_back, json.dumps(
                  state, ensure_ascii=False)))

        # language toggle — locale-agnostic: read the current language,
        # flip through the real button, verify the flip and the copy change
        initial_lang = page.evaluate("document.documentElement.lang")
        footer_before = page.evaluate(
            "document.querySelector('.footer span').textContent")
        page.click("#lang-toggle")
        flipped = ensure_lang(page, "zh" if initial_lang == "en" else "en")
        footer_after = page.evaluate(
            "document.querySelector('.footer span').textContent")
        check("language toggle flips the interface language",
              flipped != initial_lang and footer_after != footer_before,
              "lang %r->%r footer %r->%r" % (initial_lang, flipped,
                                             footer_before, footer_after))
        assert_zh_tracking(page, args.phase)
        ensure_lang(page, initial_lang)
        check("language toggle flips back",
              page.evaluate("document.documentElement.lang") == initial_lang,
              repr(page.evaluate("document.documentElement.lang")))

        # refresh + pause/resume polling
        page.click("#refresh")
        state = settle_list(page)
        check("manual refresh keeps the list rendered",
              state and state.get("items") == 5,
              json.dumps(state, ensure_ascii=False))
        page.click("#poll-toggle")
        paused = page.json_eval(
            "JSON.stringify({chip: !document.getElementById('poll-state')"
            ".classList.contains('hidden'), text: document."
            "getElementById('poll-toggle').textContent})")
        check("pause shows the paused chip and resume label",
              paused and paused.get("chip")
              and ("恢复" in paused.get("text", "")
                   or "Resume" in paused.get("text", "")),
              json.dumps(paused, ensure_ascii=False))
        page.click("#poll-toggle")
        check("resume hides the paused chip",
              page.evaluate("document.getElementById('poll-state')"
                            ".classList.contains('hidden')"),
              "hidden class present after resume click")

        # ---------- visual dump + contrast, 1440 en ------------------------
        select_work(page, "wait-1")
        data_1440 = visual_dump(page, args.phase, "1440-en")
        assert_visual(page, args.phase, data_1440, "1440-en")

        contrast_targets = [
            ("tile description on white card", ".tile-desc", 4.5),
            ("note text on neutral surface", ".note", 4.5),
            ("field label on white card", ".fields dt", 4.5),
            ("waiting warn chip", ".chip-st-waiting", 4.5),
            ("table header on neutral surface", "table.data th", 4.5),
        ]
        for label, selector, minimum in contrast_targets:
            measure_contrast(page, label, selector, minimum, args.phase)

        # selected + tab + primary control pairs
        select_work(page, "uncertain-1")
        for label, selector, minimum in (
                ("needs_attention error chip", ".chip-st-needs_attention", 4.5),):
            measure_contrast(page, label, selector, minimum, args.phase)
        select_work(page, "succeed-1")
        measure_contrast(page, "succeeded success chip",
                         ".chip-st-succeeded", 4.5, args.phase)
        measure_contrast(page, "selected tab text on ink",
                         '.tab[aria-selected="true"]', 4.5, args.phase)
        measure_contrast(page, "primary control text on ink",
                         "#refresh", 4.5, args.phase)
        measure_contrast(page, "selected work item text",
                         '.work-item[aria-selected="true"]', 4.5, args.phase)
        # body text on canvas
        measure_contrast(page, "body text on canvas", "body", 4.5, args.phase)

        # detail views on demo, 1440 en
        select_work(page, "wait-1")
        if open_tab(page, "decisions"):
            page.screenshot(os.path.join(views, "view-blockers.png"))
            measure_contrast(page, "rejected decision chip",
                             ".chip-decision-rejected", 4.5, args.phase)
        if open_tab(page, "events"):
            # event type chips use the un-styled chip-st-evt class: the
            # neutral fallback every unknown stored status class gets.
            # The events panel renders a loading note first and loads its
            # cards asynchronously, so wait for a rendered event chip before
            # measuring (same pattern as the xss step's pre.raw wait below)
            # or the measurement races the fetch and records nothing.
            wait_true(
                page,
                "!!document.querySelector('#detail-body .chip-st-evt')")
            measure_contrast(page, "base chip (unknown/extra classes neutral)",
                             ".chip-st-evt", 4.5, args.phase)
            page.screenshot(os.path.join(views, "view-events.png"))
        select_work(page, "uncertain-1")
        if open_tab(page, "operations"):
            page.screenshot(os.path.join(views, "view-uncertain-ops.png"))
        select_work(page, "cancel-1")
        page.screenshot(os.path.join(views, "view-cancel-ack.png"))
        measure_contrast(page, "cancellation banner error text",
                         ".cancel-banner", 4.5, args.phase)
        select_work(page, "succeed-1")
        if open_tab(page, "documents"):
            page.screenshot(os.path.join(views, "view-raw-documents.png"))
            summary = page.json_eval(
                "(function(){var s=document.querySelector("
                "'details.raw-block summary');"
                "return s?{height:s.offsetHeight}:null;})()")
            measure("raw disclosure summary target", summary)
            if args.phase == "after":
                check("raw disclosure summary target >= 44px",
                      summary and summary.get("height", 0) >= 44,
                      repr(summary))

        # ---------- narrow geometry + tab arrows at 390 --------------------
        for width, height in ((390, 844), (320, 690)):
            page.set_viewport(width, height)
            page.navigate(demo.url)
            state = settle_list(page)
            check("%d first load renders 5 works" % width,
                  state and state.get("items") == 5,
                  json.dumps(state, ensure_ascii=False))
            # measure with a selected work so selected/detail surfaces exist
            select_work(page, "wait-1")
            label = "%d-en" % width
            data = visual_dump(page, args.phase, label)
            assert_visual(page, args.phase, data, label)
            # S5 narrow focus regression
            page.focus("#detail-body .tabs .tab")
            ok_narrow = True
            for key_name, vk in (("ArrowRight", 39), ("ArrowLeft", 37)):
                page.key(key_name, key_name, vk)
                time.sleep(0.15)
                obs = page.json_eval(
                    "JSON.stringify({active:(function(){var a="
                    "document.activeElement;return (a===document.body)?"
                    "'BODY':(a.classList&&a.classList.contains('tab'))?"
                    "a.dataset.tab:a.tagName;})()})")
                ok_narrow = ok_narrow and obs and obs["active"] != "BODY"
            check("%d tab arrows keep tab focus" % width, ok_narrow,
                  "trusted ArrowRight/Left at %d" % width)

        # ---------- the matrix: 3 widths x 2 langs x 5 works ---------------
        for width, height in WIDTHS:
            page.set_viewport(width, height)
            for lang in ("en", "zh"):
                page.navigate(demo.url)
                state = settle_list(page)
                ensure_lang(page, lang)
                for work in WORKS:
                    if select_work(page, work):
                        # show the selected work's detail region in the
                        # capture (narrow viewports stack it under the list)
                        page.evaluate(
                            "(function(){var e=document.querySelector("
                            "'.detail-body');if(e){e.scrollIntoView();}})()")
                        page.screenshot(os.path.join(
                            shots, "%d-%s-%s.png" % (width, lang, work)))
                        if lang == "zh" and work == WORKS[3]:
                            assert_zh_tracking(page, args.phase)
                    else:
                        check("matrix %d-%s-%s selectable"
                              % (width, lang, work), False, "not found")
        expected_matrix = len(WIDTHS) * 2 * len(WORKS)
        actual_matrix = len([f for f in os.listdir(shots)
                             if f.endswith(".png")])
        check("matrix captures %d pngs" % expected_matrix,
              actual_matrix == expected_matrix,
              "%d files" % actual_matrix)

        # ---------- xss / huge-value fixture store -------------------------
        page.set_viewport(1440, 900)
        page.navigate(xss.url)
        settle_list(page)
        select_work(page, "wait-1")
        goal = page.evaluate(
            "(function(){var dds=document.querySelectorAll('.fields dd');"
            "for (var i=0;i<dds.length;i++){if(dds[i].textContent."
            "indexOf('onerror')!==-1){return dds[i].textContent;}}"
            "return null;})()")
        check("hostile stored goal renders as inert text",
              goal is not None and HOSTILE in goal,
              repr(goal)[:120])
        version = page.evaluate(
            "(function(){var dts=document.querySelectorAll('.fields dt');"
            "var dds=document.querySelectorAll('.fields dd');"
            "for (var i=0;i<dts.length;i++){"
            "if(dts[i].textContent.indexOf('State version')!==-1"
            "||dts[i].textContent.indexOf('状态版本')!==-1)"
            "{return dds[i].textContent;}}return null;})()")
        check("huge state_version renders exactly",
              version == HUGE, repr(version))
        page.screenshot(os.path.join(views, "view-xss-overview.png"))
        if open_tab(page, "events"):
            # the events panel loads itself asynchronously: wait for the
            # first rendered card before reading its text
            wait_true(page, "!!document.querySelector('#detail-body pre.raw')")
            body = page.evaluate(
                "(function(){var pres=document.querySelectorAll('pre.raw');"
                "for (var i=0;i<pres.length;i++){if(pres[i].textContent."
                "indexOf('onerror')!==-1||pres[i].textContent."
                "indexOf('<script>')!==-1){return pres[i].textContent;}}"
                "return null;})()")
            check("hostile event body renders as inert text",
                  body is not None and HOSTILE_SCRIPT in body
                  and HUGE2 in body,
                  repr(body)[:120])
            seqver = page.evaluate(
                "(function(){var heads=document.querySelectorAll("
                "'.card-head .mono');for (var i=0;i<heads.length;i++){"
                "if(heads[i].textContent.indexOf(HUGE) !== -1)"
                "{return heads[i].textContent;}}"
                "return null;})()".replace("HUGE", json.dumps(HUGE)))
            check("huge event version renders exactly",
                  seqver is not None, repr(seqver))
            page.screenshot(os.path.join(views, "view-xss-events.png"))
        if open_tab(page, "evidence"):
            wait_true(page, "!!document.querySelector('#detail-body pre.raw')")
            evd = page.evaluate(
                "(function(){var pres=document.querySelectorAll('pre.raw');"
                "for (var i=0;i<pres.length;i++){"
                "if(pres[i].textContent.indexOf('onerror')!==-1)"
                "{return true;}}return false;})()")
            check("hostile evidence data renders as inert text",
                  bool(evd), repr(evd))
        scripts_ran = page.evaluate(
            "window.__xssEvil === undefined && window.__xss === undefined")
        check("no hostile markup executed (window clean)", bool(scripts_ran),
              "window.__xssEvil=%r" % page.evaluate("window.__xssEvil"))

        # ---------- empty store (S5 race fix) ------------------------------
        page.navigate(empty.url)
        state = settle_list(page)
        check("empty store settles to 0 works with the empty message",
              state and state.get("items") == 0
              and not loading_text(state.get("status", ""))
              and ("no works" in state.get("status", "").lower()
                   or "没有" in state.get("status", "")),
              json.dumps(state, ensure_ascii=False))
        page.screenshot(os.path.join(views, "view-empty.png"))

        # ---------- loading state under emulated latency -------------------
        page.latency(1500)
        page.reload()
        deadline = time.time() + 5
        observed_status = None
        while time.time() < deadline:
            try:
                observed_status = (list_state(page) or {}).get("status")
            except RuntimeError:
                observed_status = None
            if observed_status:
                break
            time.sleep(0.1)
        check("loading state visible under emulated latency",
              loading_text(observed_status), repr(observed_status))
        page.screenshot(os.path.join(views, "view-loading.png"))
        page.latency(0)
        settle_list(page)

        # ---------- gone (UNKNOWN_WORK) then disconnected ------------------
        page.navigate(gone.url)
        settle_list(page)
        select_work(page, "transfer-1")
        db = sqlite3.connect(gone_db)
        try:
            db.execute("DELETE FROM works WHERE id='transfer-1'")
            db.commit()
        finally:
            db.close()
        gone_shown = wait_true(
            page,
            "(function(){var e=document.getElementById('detail-error-text');"
            "var box=document.getElementById('detail-error');"
            "return e && box && !box.classList.contains('hidden') && ("
            "e.textContent.indexOf('no longer present')!==-1 || "
            "e.textContent.indexOf('不在存储中')!==-1);})()", timeout=12.0)
        check("deleted work shows the gone message with retry",
              gone_shown and page.evaluate(
                  "(function(){var b=document.getElementById("
                  "'detail-retry');return b && !b.disabled && "
                  "b.offsetHeight > 0;})()"),
              "poll picked up the external delete")
        page.screenshot(os.path.join(views, "view-gone.png"))

        gone.kill()
        disconnected = wait_true(
            page,
            "(function(){var b=document.getElementById("
                "'connection-banner');"
            "return b && !b.classList.contains('hidden');})()", timeout=14.0)
        banner_text = page.evaluate(
            "document.getElementById('connection-banner').textContent")
        check("server kill shows the disconnected banner",
              disconnected and ("Disconnected" in (banner_text or "")
                                or "断开" in (banner_text or "")),
              repr(banner_text))
        measure_contrast(page, "disconnected banner error text",
                         "#connection-banner", 4.5, args.phase)
        page.screenshot(os.path.join(views, "view-disconnected.png"))
        before_text = page.evaluate(
            "document.getElementById('poll-toggle').textContent")
        page.click("#poll-toggle")
        after_text = page.evaluate(
            "document.getElementById('poll-toggle').textContent")
        check("pause/resume control stays usable while disconnected",
              before_text != after_text,
              "%r -> %r" % (before_text, after_text))
    finally:
        if page:
            page.close()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        gone.kill()
        empty.kill()
        xss.kill()
        demo.kill()

    # ---------- no-writes proof ---------------------------------------------
    snapshots_after = {name: snapshot(path) for name, path in
                       (("demo", demo_db), ("empty", empty_db),
                        ("xss", xss_db))}
    for name in ("demo", "empty", "xss"):
        check("%s store six tables identical after all reads/interactions"
              % name,
              snapshots_before[name] == snapshots_after[name],
              "%s... -> %s..." % (snapshots_before[name][:12],
                                  snapshots_after[name][:12]))

    results_path = os.path.join(out, "%s-results.json" % args.phase)
    with open(results_path, "w") as handle:
        json.dump(RECORD, handle, indent=1, ensure_ascii=False)
    failed = RESULTS.count(False)
    print("s7 audit (%s): %d checks, %d failed; evidence: %s"
          % (args.phase, len(RESULTS), failed, results_path), flush=True)
    if not args.keep:
        shutil.rmtree(profile, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
