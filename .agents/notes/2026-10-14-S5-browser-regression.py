#!/usr/bin/env python3
"""Focused S5 GUI browser regression — real headless Chrome over CDP.

Standard library only; launches a real Chrome, drives trusted key events and
device metrics through the DevTools protocol, and asserts the two regressions
fixed in the S5 frontend:

  1. First load renders the work list from the FIRST /api/works response —
     populated stores show their items and empty stores show the empty
     message, without any interaction (poll stability not required).
  2. Repeated ArrowRight/ArrowLeft on the detail tablist keeps focus on the
     LIVE, newly selected tab (connected, aria-selected) at desktop and
     narrow viewports.

Artifact of dispatch task_5dbcb17c2e91; evidence in 2026-10-14-S5-frontend-report.md addendum 3.

Usage: browser_regression.py <populated-url> <empty-url> [--chrome PATH]
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


class CdpPage:
    """Minimal CDP client: one WebSocket per page target, stdlib only."""

    def __init__(self, ws_host_port, target_id):
        self.url = "ws://%s/devtools/page/%s" % (ws_host_port, target_id)
        import socket
        host, port = ws_host_port.rsplit(":", 1)
        self.sock = socket.create_connection((host, int(port)), timeout=30)
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
            if opcode == 1:            # text
                return json.loads(payload.decode("utf-8"))
            if opcode == 9:            # ping -> pong
                self._send_frame(10, payload)
            elif opcode == 8:          # close
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

    def key(self, name, code, vk):
        self.call("Input.dispatchKeyEvent", {
            "type": "keyDown", "key": name, "code": code,
            "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk})
        self.call("Input.dispatchKeyEvent", {
            "type": "keyUp", "key": name, "code": code,
            "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk})


RESULTS = []


def check(name, ok, observed):
    RESULTS.append(ok)
    print("%s %s — %s" % ("PASS" if ok else "FAIL", name, observed))


LIST_STATE = ("JSON.stringify({items: document.querySelectorAll("
              "'#work-list .work-item').length, "
              "status: document.getElementById('list-status').textContent})")


def list_state(page):
    """Evaluate LIST_STATE and decode its JSON-string value."""
    raw = page.evaluate(LIST_STATE)
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return {"items": None, "status": None}


def wait_for_list(page, want_items, timeout=8.0):
    """Poll until the list settles to want_items (or timeout)."""
    deadline = time.time() + timeout
    state = {"items": None, "status": None}
    while time.time() < deadline:
        state = list_state(page)
        if state.get("items") == want_items:
            return state
        time.sleep(0.2)
    return state


def assert_first_load(page, url, want_items, label):
    page.call("Page.navigate", {"url": url})
    deadline = time.time() + 15
    state = {"items": None, "status": None}
    while time.time() < deadline:      # first fetch + render, no interaction
        try:
            state = list_state(page)
        except RuntimeError:
            pass                       # navigation in flight
        if state.get("items") == want_items:
            break
        time.sleep(0.2)
    loading = state.get("status", "").endswith("…") or "Loading" in state.get("status", "")
    check("%s first load shows %d items" % (label, want_items),
          state.get("items") == want_items, json.dumps(state, ensure_ascii=False))
    if want_items == 0:
        check("%s empty store shows the empty message, not loading"
              % label, state.get("items") == 0 and not loading,
              json.dumps(state, ensure_ascii=False))


def assert_tab_arrows(page, label):
    if not page.evaluate("!!document.querySelector('#work-list .work-item')"):
        check("%s tab navigation has list items to select" % label,
              False, "no work items rendered; cannot reach the detail tabs")
        return
    page.evaluate("document.querySelector('#work-list .work-item').click()")
    deadline = time.time() + 10
    while time.time() < deadline:
        if page.evaluate("!!document.querySelector('#detail-body .tabs .tab')"):
            break
        time.sleep(0.2)
    page.evaluate("document.querySelector('#detail-body .tabs .tab').focus()")
    for key_name, code, vk in (("ArrowRight", "ArrowRight", 39),
                               ("ArrowRight", "ArrowRight", 39),
                               ("ArrowLeft", "ArrowLeft", 37),
                               ("ArrowRight", "ArrowRight", 39)):
        page.key(key_name, code, vk)
        state = page.evaluate(
            "JSON.stringify({active: (function(){var a=document.activeElement;"
            "return (a===document.body)?'BODY':"
            "(a.classList&&a.classList.contains('tab'))?a.dataset.tab:a.tagName;})(),"
            "connected: document.activeElement.isConnected,"
            "selected: document.querySelector("
            "'#detail-body .tabs .tab[aria-selected=\"true\"]').dataset.tab})")
        observed = json.loads(state)
        ok = (observed["active"] == observed["selected"]
              and observed["connected"] and observed["active"] != "BODY")
        check("%s %s keeps focus on the live selected tab"
              % (label, key_name), ok, state)


def run_viewport(chrome, devtools, url_populated, url_empty, width, height, label):
    new = urllib.request.Request("http://%s/json/new?about:blank" % devtools,
                                 method="PUT")
    target = json.load(urllib.request.urlopen(new, timeout=10))
    page = CdpPage(devtools, target["id"])
    try:
        page.call("Emulation.setDeviceMetricsOverride",
                  {"width": width, "height": height,
                   "deviceScaleFactor": 1, "mobile": False})
        assert_first_load(page, url_populated, 5, "%s populated" % label)
        assert_tab_arrows(page, "%s tabs" % label)
        assert_first_load(page, url_empty, 0, "%s empty" % label)
    finally:
        try:
            page.sock.close()
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("populated_url")
    parser.add_argument("empty_url")
    parser.add_argument("--chrome",
                        default="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    args = parser.parse_args()
    profile = tempfile.mkdtemp(prefix="s5-cdp-profile-")
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
        run_viewport(proc, devtools, args.populated_url, args.empty_url,
                     1280, 900, "desktop")
        run_viewport(proc, devtools, args.populated_url, args.empty_url,
                     390, 844, "narrow")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    failed = RESULTS.count(False)
    print("browser regression: %d checks, %d failed" % (len(RESULTS), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
