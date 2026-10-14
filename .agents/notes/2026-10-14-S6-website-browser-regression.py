#!/usr/bin/env python3
"""Focused S6 website browser regression — real headless Chrome over CDP.

Standard library only; launches a real Chrome and drives trusted key/mouse
events and device metrics through the DevTools protocol (actual browser,
never a fake DOM). Asserts the S6 website behavior and DESIGN-token visual
contract:

  behavior  copy buttons (success + clipboard byte-equality with granted
            permission; failure announcement on an insecure origin),
            recovery Prev/Next stepping via trusted mouse click and Enter
            key, skip-link Tab/Enter focus path, keyboard focus ring.
  static    required sections/ids, six recovery stages, language
            crosslinks, img alt, https-only external links, no leading-
            slash local URLs.
  visual    computed DESIGN tokens at 1280/390/320 (canvas/CTA/radii/no
            shadow/hero sizes EN 72->32, ZH 52->30), no horizontal
            overflow, images loaded, WCAG contrast ratios recomputed from
            computed styles, optional screenshots.
  nojs      script execution disabled: every section and all six stages
            stay visible, no injected controls, stylesheet still applied.

Artifact of dispatch task_0a416f2410cf (S6 website owner); evidence in
.agents/notes/2026-10-14-S6-website-interface-report.md.

Usage: website_browser_regression.py --en-url URL --zh-url URL
          [--insecure-url URL] [--sections behavior,static,visual,nojs]
          [--shot-dir DIR] [--chrome PATH]
Exit 0 all assertions pass; 1 otherwise. Prints each observed value.
"""

import argparse
import base64
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

VIEWPORTS = [(1280, 900), (390, 844), (320, 568)]


class CdpClient:
    """Minimal CDP client over one WebSocket (browser or page target)."""

    def __init__(self, ws_url):
        self.url = ws_url
        import socket
        host_part, path = ws_url.split("://", 1)[1].split("/", 1)
        host, port = host_part.rsplit(":", 1)
        self.sock = socket.create_connection((host, int(port)), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        request = ("GET /%s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\n"
                   "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
                   "Sec-WebSocket-Version: 13\r\n\r\n" % (path, host_part, key))
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

    def evaluate(self, expression, await_promise=False):
        params = {"expression": expression, "returnByValue": True}
        if await_promise:
            params["awaitPromise"] = True
        result = self.call("Runtime.evaluate", params)
        if result.get("exceptionDetails"):
            raise RuntimeError("page exception: %s"
                               % result["exceptionDetails"].get("text"))
        return result.get("result", {}).get("value")

    def key(self, name, code, vk, text=None):
        params = {"type": "keyDown", "key": name, "code": code,
                  "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
        if text is not None:
            params["text"] = text   # Chrome 155 needs text for activation
        self.call("Input.dispatchKeyEvent", params)
        self.call("Input.dispatchKeyEvent", {
            "type": "keyUp", "key": name, "code": code,
            "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk})

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


RESULTS = []


def check(name, ok, observed):
    RESULTS.append(bool(ok))
    print("%s %s — %s" % ("PASS" if ok else "FAIL", name, observed))


def new_page(devtools):
    request = urllib.request.Request("http://%s/json/new?about:blank" % devtools,
                                     method="PUT")
    target = json.load(urllib.request.urlopen(request, timeout=10))
    return CdpClient("ws://%s/devtools/page/%s" % (devtools, target["id"]))


def navigate(page, url, timeout=15):
    page.call("Page.navigate", {"url": url})
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if page.evaluate("document.readyState") == "complete":
                return
        except RuntimeError:
            pass                      # navigation in flight
        time.sleep(0.2)


def click_selector(page, selector):
    """Trusted mouse click at the element center (real user activation).
    Scrolls the element into view first so viewport coordinates hit it."""
    rect = json.loads(page.evaluate(
        "JSON.stringify((function(){var e=document.querySelector(%r);"
        "if(!e)return null;e.scrollIntoView({block:'center',behavior:'instant'});"
        "var r=e.getBoundingClientRect();"
        "return {x:r.left+r.width/2,y:r.top+r.height/2};})())" % selector))
    if not rect:
        return False
    for type_ in ("mousePressed", "mouseReleased"):
        page.call("Input.dispatchMouseEvent", {
            "type": type_, "x": rect["x"], "y": rect["y"],
            "button": "left", "clickCount": 1})
    return True


def live_text(page):
    return (page.evaluate(
        "(document.querySelector('.live-region')||{}).textContent||''") or "")


def wait_live(page, marker, timeout=6.0):
    deadline = time.time() + timeout
    text = ""
    while time.time() < deadline:
        text = live_text(page)
        if marker in text:
            return text
        time.sleep(0.15)
    return text


def zh(url_page_lang):
    return url_page_lang.startswith("zh")


# ---------------------------------------------------------------- behavior

def check_copy(page, url, label, lang, browser):
    blocks = page.evaluate("document.querySelectorAll('pre[data-copyable]').length")
    buttons = page.evaluate("document.querySelectorAll('.copy-btn').length")
    check("%s copy buttons injected for every code block" % label,
          blocks > 0 and buttons == blocks,
          "blocks=%s buttons=%s" % (blocks, buttons))
    origin = "/".join(url.split("/")[:3])
    browser.call("Browser.grantPermissions", {
        "origin": origin,
        "permissions": ["clipboardReadWrite", "clipboardSanitizedWrite"]})
    expected = page.evaluate(
        "document.querySelector('pre[data-copyable]').textContent")
    if not click_selector(page, ".copy-btn"):
        check("%s copy click lands" % label, False, "no .copy-btn to click")
        return
    ok_marker = "已复制" if lang == "zh" else "Copied"
    text = wait_live(page, ok_marker)
    check("%s copy success announced via aria-live" % label,
          ok_marker in text, repr(text))
    copied = page.evaluate("navigator.clipboard.readText()", await_promise=True)
    check("%s clipboard holds the exact visible text" % label,
          copied == expected, repr(copied))
    browser.call("Browser.resetPermissions")


def check_copy_insecure(page, label, lang):
    has_api = page.evaluate("typeof navigator.clipboard === 'object'")
    expected = page.evaluate(
        "document.querySelector('pre[data-copyable]').textContent")
    if not click_selector(page, ".copy-btn"):
        check("%s insecure copy click lands" % label, False, "no .copy-btn")
        return
    bad_marker = "复制失败" if lang == "zh" else "Copy failed"
    text = wait_live(page, bad_marker)
    check("%s insecure origin announces copy failure" % label,
          bad_marker in text, "navigator.clipboard=%s live=%r"
          % (has_api, text))
    still = page.evaluate(
        "document.querySelector('pre[data-copyable]').textContent")
    check("%s command text remains selectable after failure" % label,
          still == expected and len(still or "") > 10, repr(still))


def check_recovery(page, label):
    stages = page.evaluate("document.querySelectorAll('#recovery-stages .stage').length")
    controls = page.evaluate(
        "document.querySelectorAll('.recovery-controls button').length")
    check("%s six recovery stages present" % label, stages == 6,
          "stages=%s" % stages)
    check("%s recovery Prev/Next controls injected" % label, controls >= 2,
          "buttons=%s" % controls)
    if controls < 2:
        return

    def current():
        return page.evaluate(
            "(document.querySelector('#recovery-stages [aria-current=\"step\"]')"
            "||{dataset:{}}).dataset.stage || ''")

    visible = page.evaluate(
        "JSON.stringify(Array.from(document.querySelectorAll("
            "'#recovery-stages .stage')).map(function(s){"
            "return !!(s.offsetWidth||s.offsetHeight);}))")
    check("%s all stages visible with JS on" % label,
          json.loads(visible) == [True] * 6, visible)

    first = current()
    click_selector(page, ".recovery-controls button:last-child")   # Next
    after_next = current()
    check("%s trusted Next click advances the stage" % label,
          first == "1" and after_next == "2",
          "current %s -> %s" % (first, after_next))

    page.evaluate(
        "document.querySelector('.recovery-controls button:last-child').focus()")
    page.key("Enter", "Enter", 13, text="\r")
    after_enter = current()
    check("%s Enter key on Next advances the stage" % label,
          after_enter == "3", "current=%s" % after_enter)

    click_selector(page, ".recovery-controls button:first-child")  # Prev
    after_prev = current()
    check("%s Prev returns to the previous stage" % label,
          after_prev == "2", "current=%s" % after_prev)
    visible = page.evaluate(
        "Array.from(document.querySelectorAll('#recovery-stages .stage'))"
        ".every(function(s){return !!(s.offsetWidth||s.offsetHeight);})")
    check("%s all stages stay visible while stepping" % label, visible, visible)


def check_skip_focus(page, label):
    page.evaluate("if(document.activeElement){document.activeElement.blur();}")
    page.key("Tab", "Tab", 9)
    active = page.evaluate(
        "(document.activeElement||{}).className || document.activeElement")
    check("%s first Tab focuses the skip link" % label,
          "skip-link" in str(active), repr(active))
    outline = page.evaluate(
        "getComputedStyle(document.activeElement).outlineStyle + ' ' +"
        "getComputedStyle(document.activeElement).outlineColor")
    check("%s keyboard focus ring is visible and orange" % label,
          outline.startswith("solid") and "245, 78, 0" in outline, outline)
    page.key("Enter", "Enter", 13, text="\r")
    time.sleep(0.3)
    moved = page.evaluate("(document.activeElement||{}).id || ''")
    check("%s skip link Enter moves focus to main" % label,
          moved == "main", repr(moved))


def run_behavior(devtools, browser, url, label, lang, insecure_url=None):
    page = new_page(devtools)
    try:
        page.call("Page.bringToFront")
        navigate(page, url)
        # Skip/focus checks run first: "first Tab on first load" — after any
        # click, Chrome's sequential-focus starting point follows that click.
        check_skip_focus(page, label)
        navigate(page, url)
        check_copy(page, url, label, lang, browser)
        check_recovery(page, label)
        if insecure_url:
            navigate(page, insecure_url)
            check_copy_insecure(page, label + " insecure", lang)
    finally:
        page.close()


# ----------------------------------------------------------------- static

def run_static(devtools, url, label, expect_crosslink):
    page = new_page(devtools)
    try:
        navigate(page, url)
        ids = json.loads(page.evaluate(
            "JSON.stringify(['main','why','how','demo','start','contribute']"
            ".map(function(i){return !!document.getElementById(i);}))"))
        check("%s required section ids present" % label, ids == [True] * 6, ids)
        stages = page.evaluate(
            "document.querySelectorAll('#recovery-stages .stage').length")
        check("%s six stages in static DOM" % label, stages == 6,
              "stages=%s" % stages)
        visible = page.evaluate(
            "Array.from(document.querySelectorAll('main > section'))"
            ".every(function(s){return !!(s.offsetWidth||s.offsetHeight);})")
        check("%s all top sections visible" % label, visible, visible)
        cross = page.evaluate(
            '!!document.querySelector("a[href=%r]")' % expect_crosslink)
        check("%s language crosslink %r present" % (label, expect_crosslink),
              cross, cross)
        no_alt = page.evaluate(
            "document.querySelectorAll('img:not([alt]), img[alt=\"\"]').length")
        check("%s every image carries alt text" % label, no_alt == 0,
              "missing=%s" % no_alt)
        leading = json.loads(page.evaluate(
            "JSON.stringify(Array.from(document.querySelectorAll('[href],[src]'))"
            ".map(function(e){return e.getAttribute('href')||"
            "e.getAttribute('src')||'';}).filter(function(v){"
            "return v.startsWith('/');}))"))
        check("%s no leading-slash local URLs" % label, leading == [], leading)
        insecure = json.loads(page.evaluate(
            "JSON.stringify(Array.from(document.querySelectorAll('[href^=\"http\"],[src^=\"http\"]'))"
            ".map(function(e){return e.getAttribute('href')||"
            "e.getAttribute('src');}).filter(function(v){"
            "return v.startsWith('http:');}))"))
        check("%s external URLs are https-only" % label, insecure == [], insecure)
    finally:
        page.close()


# ----------------------------------------------------------------- visual

def parse_rgb(value):
    value = value.strip()
    if value.startswith("rgba") or value.startswith("rgb"):
        nums = value[value.index("(") + 1:value.rindex(")")].split(",")
        r, g, b = (int(float(n)) for n in nums[:3])
        return r, g, b
    return None


def luminance(rgb):
    def chan(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def style(page, selector, prop):
    return page.evaluate(
        "getComputedStyle(document.querySelector(%r)).%s" % (selector, prop))


def check_contrast(page, label, selector, against, minimum=4.5):
    fg = parse_rgb(style(page, selector, "color"))
    bg = parse_rgb(against)
    ratio = contrast(fg, bg) if fg and bg else 0.0
    check("%s %s contrast %.2f >= %.1f" % (label, selector, ratio, minimum),
          ratio >= minimum, "fg=%s bg=%s ratio=%.2f" % (fg, bg, ratio))


def run_visual(devtools, url, label, lang, shot_dir, widths=VIEWPORTS):
    page = new_page(devtools)
    try:
        for width, height in widths:
            tag = "%s %dpx" % (label, width)
            page.call("Emulation.setDeviceMetricsOverride",
                      {"width": width, "height": height,
                       "deviceScaleFactor": 1, "mobile": False})
            navigate(page, url)
            bg = style(page, "body", "backgroundColor")
            check("%s canvas token on body" % tag, bg == "rgb(247, 247, 244)", bg)
            hero = style(page, ".hero-title", "fontSize")
            want_hero = ("52px" if lang == "zh" else "72px") if width >= 1024 \
                else ("30px" if lang == "zh" else "32px")
            check("%s hero size token (%s)" % (tag, want_hero),
                  hero == want_hero, hero)
            cta_bg = style(page, ".btn-primary", "backgroundColor")
            cta_fg = style(page, ".btn-primary", "color")
            check("%s primary CTA is ink/canvas" % tag,
                  cta_bg == "rgb(38, 37, 30)" and cta_fg == "rgb(247, 247, 244)",
                  "%s on %s" % (cta_fg, cta_bg))
            radius = style(page, ".btn-primary", "borderRadius")
            check("%s control radius 8px" % tag, radius == "8px", radius)
            card = style(page, ".card", "borderRadius")
            shadow = style(page, ".card", "boxShadow")
            check("%s card radius 12px, no shadow" % tag,
                  card == "12px" and shadow == "none",
                  "radius=%s shadow=%s" % (card, shadow))
            overflow = page.evaluate(
                "document.documentElement.scrollWidth -"
                "document.documentElement.clientWidth")
            check("%s no horizontal overflow" % tag, overflow <= 0, overflow)
            imgs = page.evaluate(
                "Array.from(document.images).every("
                "function(i){return i.complete && i.naturalWidth > 0;})")
            check("%s all images loaded" % tag, imgs,
                  page.evaluate("document.images.length"))
            if width == widths[0][0]:
                check_contrast(page, tag, "body", bg)
                check_contrast(page, tag, ".footer-links a", bg)
                check_contrast(page, tag, ".stage h3", "rgb(255, 255, 255)")
                check_contrast(page, tag, ".badge", "rgb(230, 229, 224)")
                fg = parse_rgb(cta_fg)
                check("%s CTA contrast 14.33" % tag,
                      abs(contrast(fg, parse_rgb(cta_bg)) - 14.33) < 0.1,
                      contrast(fg, parse_rgb(cta_bg)))
            if shot_dir:
                shot = page.call("Page.captureScreenshot", {
                    "format": "png", "captureBeyondViewport": True})
                name = os.path.join(
                    shot_dir, "s6-%s-%d.png" % (label.lower(), width))
                with open(name, "wb") as fh:
                    fh.write(base64.b64decode(shot["data"]))
                print("SHOT %s" % name)
    finally:
        page.close()


# ------------------------------------------------------------------- nojs

def run_nojs(devtools, url, label):
    page = new_page(devtools)
    try:
        page.call("Emulation.setScriptExecutionDisabled", {"value": True})
        navigate(page, url)
        injected = page.evaluate(
            "document.querySelectorAll('.copy-btn,.recovery-controls').length")
        check("%s noJS: no injected controls" % label, injected == 0, injected)
        stages = page.evaluate(
            "Array.from(document.querySelectorAll('#recovery-stages .stage'))"
            ".every(function(s){return !!(s.offsetWidth||s.offsetHeight);})")
        check("%s noJS: all six stages visible" % label, stages, stages)
        sections = page.evaluate(
            "Array.from(document.querySelectorAll('main > section'))"
            ".every(function(s){return !!(s.offsetWidth||s.offsetHeight);})")
        check("%s noJS: all top sections visible" % label, sections, sections)
        bg = style(page, "body", "backgroundColor")
        check("%s noJS: stylesheet still applied" % label,
              bg == "rgb(247, 247, 244)", bg)
        page.call("Emulation.setScriptExecutionDisabled", {"value": False})
    finally:
        page.close()


# ------------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--en-url", required=True)
    parser.add_argument("--zh-url", required=True)
    parser.add_argument("--insecure-url")
    parser.add_argument("--sections", default="all",
                        help="comma list: behavior,static,visual,nojs,all")
    parser.add_argument("--shot-dir")
    parser.add_argument("--chrome",
                        default="/Applications/Google Chrome.app/Contents/"
                                "MacOS/Google Chrome")
    args = parser.parse_args()
    sections = [s.strip() for s in args.sections.split(",")]
    if "all" in sections:
        sections = ["behavior", "static", "visual", "nojs"]
    if args.shot_dir:
        os.makedirs(args.shot_dir, exist_ok=True)

    profile = tempfile.mkdtemp(prefix="s6-cdp-profile-")
    proc = subprocess.Popen(
        [args.chrome, "--headless", "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", "--remote-debugging-port=0",
         "--user-data-dir=" + profile, "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 15
        devtools = None
        while time.time() < deadline:
            line = proc.stderr.readline()
            if "DevTools listening on ws://" in line:
                host = line.split("ws://", 1)[1].strip().rstrip("/")
                devtools = host.rsplit("/devtools", 1)[0]
                break
        if not devtools:
            raise RuntimeError("Chrome never reported its DevTools endpoint")
        browser_ws = json.load(urllib.request.urlopen(
            "http://%s/json/version" % devtools, timeout=10))["webSocketDebuggerUrl"]
        browser = CdpClient(browser_ws)
        try:
            if "behavior" in sections:
                run_behavior(devtools, browser, args.en_url, "EN", "en",
                             args.insecure_url)
                run_behavior(devtools, browser, args.zh_url, "ZH", "zh")
            if "static" in sections:
                run_static(devtools, args.en_url, "EN", "zh/index.html")
                run_static(devtools, args.zh_url, "ZH", "../index.html")
            if "visual" in sections:
                run_visual(devtools, args.en_url, "EN", "en", args.shot_dir)
                run_visual(devtools, args.zh_url, "ZH", "zh", args.shot_dir)
            if "nojs" in sections:
                run_nojs(devtools, args.en_url, "EN")
                run_nojs(devtools, args.zh_url, "ZH")
        finally:
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    failed = RESULTS.count(False)
    print("website regression: %d checks, %d failed" % (len(RESULTS), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
