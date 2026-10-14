"""Tests for work_runtime.ui_server — the loopback read-only HTTP boundary."""

import http.client
import io
import json
import socket
import sqlite3
import sys
import threading
import unittest
from pathlib import Path
from urllib.parse import quote

from work_runtime.demo import demo_grants, initialize, send
from work_runtime.inspection import GuiReaderError
from work_runtime.policy import ExpensePolicy
from work_runtime.runtime import Runtime
from work_runtime.ui_server import make_ui_server

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
       "base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'none'")


class UiServerFixture(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.path = str(self.dir / "runtime.sqlite")
        runtime = Runtime(self.path, ExpensePolicy(), demo_grants())
        initialize(runtime)
        initialize(runtime, work_id='订单/"A"&1')
        plan = {"steps": ["verify"], "open_requirements": [], "replan_when": []}
        send(runtime, "demo", "revise_plan", plan)
        send(runtime, "demo", "revise_plan", plan)
        self.server = make_ui_server(self.path, 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)

    def request(self, method, target, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request(method, target, headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response, body

    def raw_request(self, method, target, header_lines, version="HTTP/1.1"):
        """Hand-built request for cases http.client cannot express."""
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        try:
            lines = ["%s %s %s" % (method, target, version),
                     "Connection: close"] + list(header_lines)
            sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("utf-8"))
            data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
        finally:
            sock.close()
        head, _, body = data.partition(b"\r\n\r\n")
        status_line = head.split(b"\r\n")[0].decode("latin-1")
        return int(status_line.split()[1]), head.decode("latin-1"), body

    def error_code(self, body):
        return json.loads(body)["error"]["code"]


class ServerCoreTests(UiServerFixture):
    def test_factory_binds_loopback_ephemeral(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertGreater(self.port, 0)

    def test_startup_invalid_store_raises(self):
        with self.assertRaises(GuiReaderError) as caught:
            make_ui_server(str(self.dir / "absent.sqlite"), 0)
        self.assertEqual(caught.exception.code, "DB_NOT_FOUND")

    def test_api_routes_json_and_security_headers(self):
        for target in ("/api/summary", "/api/works", "/api/work?id=demo",
                       "/api/events?work_id=demo"):
            with self.subTest(target=target):
                response, body = self.request("GET", target)
                self.assertEqual(response.status, 200, target)
                self.assertEqual(response.getheader("Content-Type"),
                                 "application/json; charset=utf-8")
                self.assertEqual(int(response.getheader("Content-Length")),
                                 len(body))
                self.assertEqual(response.getheader("X-Content-Type-Options"),
                                 "nosniff")
                self.assertEqual(response.getheader("Cache-Control"), "no-store")
                self.assertEqual(
                    response.getheader("Content-Security-Policy"), CSP)
                for key, _ in response.getheaders():
                    self.assertFalse(key.startswith("Access-Control-"), key)
                payload = json.loads(body)
                self.assertIsInstance(payload, dict)

    def test_summary_payload_shape(self):
        _, body = self.request("GET", "/api/summary")
        summary = json.loads(body)
        self.assertEqual(summary["source"], "runtime.sqlite")
        self.assertEqual(summary["schema_version"], "1")
        self.assertEqual(summary["counts"]["works"], 2)
        self.assertIn("attempts", summary["counts"])

    def test_works_envelope_uses_works_key(self):
        _, body = self.request("GET", "/api/works?limit=1&offset=0")
        payload = json.loads(body)
        self.assertEqual(set(payload), {"total", "limit", "offset", "works"})
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["limit"], 1)
        self.assertEqual(payload["offset"], 0)
        self.assertEqual(len(payload["works"]), 1)

    def test_head_mirrors_get(self):
        get_response, get_body = self.request("GET", "/api/summary")
        head_response, head_body = self.request("HEAD", "/api/summary")
        self.assertEqual(head_response.status, 200)
        self.assertEqual(head_body, b"")
        self.assertEqual(head_response.getheader("Content-Length"),
                         get_response.getheader("Content-Length"))
        self.assertEqual(int(head_response.getheader("Content-Length")),
                         len(get_body))
        self.assertEqual(head_response.getheader("Content-Type"),
                         "application/json; charset=utf-8")
        self.assertEqual(head_response.getheader("X-Content-Type-Options"), "nosniff")

    def test_methods_rejected(self):
        for method in ("POST", "PUT", "DELETE", "OPTIONS", "PATCH"):
            with self.subTest(method=method):
                response, body = self.request(method, "/api/summary")
                self.assertEqual(response.status, 405)
                self.assertEqual(response.getheader("Allow"), "GET, HEAD")
                self.assertEqual(self.error_code(body), "METHOD_NOT_ALLOWED")
                for key, _ in response.getheaders():
                    self.assertFalse(key.startswith("Access-Control-"), key)

    def test_unknown_routes_404(self):
        for target in ("/api/nope", "/foo", "/app.js.bak", "/api/", "/api"):
            with self.subTest(target=target):
                response, body = self.request("GET", target)
                self.assertEqual(response.status, 404, target)
                self.assertEqual(self.error_code(body), "UNKNOWN_ROUTE")

    def test_static_assets_bounded_404_without_files(self):
        web_dir = Path(__file__).resolve().parents[1] / "work_runtime" / "web"
        for target in ("/", "/app.js", "/app.css"):
            with self.subTest(target=target):
                response, body = self.request("GET", target)
                self.assertEqual(response.status, 404)
                self.assertEqual(self.error_code(body), "UNKNOWN_ROUTE")
                self.assertNotIn(str(self.dir), body.decode("utf-8"))
        self.assertFalse(web_dir.exists())

    def test_query_validation_400(self):
        cases = (
            "/api/summary?x=1",
            "/api/works?limit=1&limit=2",
            "/api/works?limit=abc",
            "/api/works?limit=0",
            "/api/works?limit=201",
            "/api/works?offset=-1",
            "/api/works?offset=x",
            "/api/events?after=-1",
            "/api/events?after=x",
            "/api/events?limit=0",
            "/api/work",
            "/api/work?id=",
            "/api/events",
            "/api/events?work_id=",
            "/api/works?&&",
            "/?x=1",
            "/app.js?v=2",
        )
        for target in cases:
            with self.subTest(target=target):
                response, body = self.request("GET", target)
                self.assertEqual(response.status, 400, target)
                self.assertEqual(self.error_code(body), "BAD_QUERY")

    def test_unicode_work_id_via_query_encoding(self):
        from urllib.parse import quote
        encoded = quote('订单/"A"&1', safe="")
        response, body = self.request("GET", "/api/work?id=" + encoded)
        self.assertEqual(response.status, 200)
        detail = json.loads(body)
        self.assertEqual(detail["work"]["id"], '订单/"A"&1')
        events_response, events_body = self.request(
            "GET", "/api/events?work_id=" + encoded + "&limit=2")
        self.assertEqual(events_response.status, 200)
        self.assertEqual(json.loads(events_body)["events"][0]["work_id"],
                         '订单/"A"&1')

    def test_events_route_paging(self):
        _, first_body = self.request("GET", "/api/events?work_id=demo&limit=2")
        first = json.loads(first_body)
        self.assertEqual(len(first["events"]), 2)
        self.assertTrue(first["has_more"])
        self.assertIsInstance(first["next_after"], str)
        seqs = [int(e["seq"]) for e in first["events"]]
        _, second_body = self.request(
            "GET", "/api/events?work_id=demo&limit=2&after=" + first["next_after"])
        second = json.loads(second_body)
        seqs.extend(int(e["seq"]) for e in second["events"])
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(set(seqs)), len(seqs))

    def test_shutdown_clean(self):
        server = make_ui_server(self.path, 0)
        thread = threading.Thread(target=server.serve_forever,
                                  kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection("127.0.0.1",
                                                server.server_address[1], timeout=10)
        connection.request("GET", "/api/summary")
        self.assertEqual(connection.getresponse().status, 200)
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())


class BoundaryTests(UiServerFixture):
    def correct_host(self):
        return "Host: 127.0.0.1:%d" % self.port

    def test_host_accepts_loopback_authority_with_actual_port(self):
        for host in ("127.0.0.1:%d" % self.port, "localhost:%d" % self.port,
                     "LOCALHOST:%d" % self.port):
            with self.subTest(host=host):
                status, _, body = self.raw_request(
                    "GET", "/api/summary", ["Host: " + host])
                self.assertEqual(status, 200)
                self.assertIn(b"works", body)

    def test_host_rejected(self):
        cases = (
            ["Host: evil.com"],
            ["Host: evil.com:%d" % self.port],
            ["Host: 127.0.0.1:9"],
            ["Host: 127.0.0.1"],
            ["Host: localhost"],
            ["Host: [::1]:%d" % self.port],
            ["Host: 127.0.0.1:%d" % self.port, "Host: localhost:%d" % self.port],
        )
        for headers in cases:
            with self.subTest(headers=headers):
                status, _, body = self.raw_request("GET", "/api/summary", headers)
                self.assertEqual(status, 403, headers)
                self.assertEqual(self.error_code(body), "BAD_HOST")

    def test_missing_host_rejected(self):
        # Both HTTP versions reach the boundary check itself: no Host at
        # all is a 403 BAD_HOST, not a silent default.
        for version in ("HTTP/1.0", "HTTP/1.1"):
            with self.subTest(version=version):
                status, _, body = self.raw_request(
                    "GET", "/api/summary", [], version=version)
                self.assertEqual(status, 403)
                self.assertEqual(self.error_code(body), "BAD_HOST")

    def test_origin_accepted_when_matching(self):
        # Same-alias pairs: the Origin equals the request's own Host origin.
        pairs = (
            ("Host: 127.0.0.1:%d" % self.port, "http://127.0.0.1:%d" % self.port),
            ("Host: localhost:%d" % self.port, "http://localhost:%d" % self.port),
        )
        for host_header, origin in pairs:
            with self.subTest(host=host_header, origin=origin):
                status, _, body = self.raw_request(
                    "GET", "/api/summary", [host_header, "Origin: " + origin])
                self.assertEqual(status, 200, (host_header, origin))

    def test_origin_rejected(self):
        cases = (
            "https://127.0.0.1:%d" % self.port,
            "http://evil.com",
            "http://evil.com:%d" % self.port,
            "http://127.0.0.1:9",
            "null",
            "http://127.0.0.1:%d/" % self.port,
            "http://user@127.0.0.1:%d" % self.port,
            "",
        )
        for origin in cases:
            with self.subTest(origin=origin):
                status, _, body = self.raw_request(
                    "GET", "/api/summary", [self.correct_host(), "Origin: " + origin])
                self.assertEqual(status, 403, origin)
                self.assertEqual(self.error_code(body), "BAD_ORIGIN")

    def test_origin_cross_alias_rejected(self):
        # D25: Origin must match the request's own local origin (its Host
        # authority). The other loopback alias is a different origin, even
        # with the right port — both cross-alias pairs are 403.
        pairs = (
            ("Host: 127.0.0.1:%d" % self.port, "http://localhost:%d" % self.port),
            ("Host: localhost:%d" % self.port, "http://127.0.0.1:%d" % self.port),
        )
        for host_header, origin in pairs:
            with self.subTest(host=host_header, origin=origin):
                status, _, body = self.raw_request(
                    "GET", "/api/summary", [host_header, "Origin: " + origin])
                self.assertEqual(status, 403, (host_header, origin))
                self.assertEqual(self.error_code(body), "BAD_ORIGIN")

    def test_duplicate_origin_rejected(self):
        status, _, body = self.raw_request("GET", "/api/summary", [
            self.correct_host(),
            "Origin: http://127.0.0.1:%d" % self.port,
            "Origin: http://evil.com"])
        self.assertEqual(status, 403)
        self.assertEqual(self.error_code(body), "BAD_ORIGIN")

    def test_absolute_form_target_rejected(self):
        status, _, body = self.raw_request(
            "GET", "http://127.0.0.1:%d/api/summary" % self.port, [self.correct_host()])
        self.assertEqual(status, 404)
        self.assertEqual(self.error_code(body), "UNKNOWN_ROUTE")
        status, _, body = self.raw_request(
            "GET", "http://evil.com/api/summary", [self.correct_host()])
        self.assertEqual(status, 404)

    def test_traversal_targets_rejected(self):
        for target in ("/%2e%2e/", "/..%2fapp.js",
                       "/app.js/../../etc/passwd", "//127.0.0.1/api/summary"):
            with self.subTest(target=target):
                status, _, body = self.raw_request(
                    "GET", target, [self.correct_host()])
                self.assertEqual(status, 404, target)
                self.assertEqual(self.error_code(body), "UNKNOWN_ROUTE")

    def test_error_bodies_have_no_paths(self):
        hostile = quote("../../etc/passwd\x00", safe="")
        for target in ("/api/work?id=" + hostile, "/%2e%2e/etc/passwd",
                       "/api/events?work_id=" + hostile):
            with self.subTest(target=target):
                _, _, body = self.raw_request("GET", target, [self.correct_host()])
                text = body.decode("utf-8", "replace")
                self.assertNotIn("/Users/", text)
                self.assertNotIn(str(self.dir), text)
                self.assertNotIn("work_runtime", text)
                json.loads(body)  # still the bounded JSON envelope

    def test_access_log_never_echoes_raw_url(self):
        stream = io.StringIO()
        stderr, sys.stderr = sys.stderr, stream
        try:
            self.raw_request("GET", "/api/works?limit=1&limit=2&mark=\x01secret",
                             [self.correct_host()])
            self.raw_request("GET", "/%2e%2e/etc/passwd", [self.correct_host()])
        finally:
            sys.stderr = stderr
        logged = stream.getvalue()
        self.assertNotIn("secret", logged)
        self.assertNotIn("passwd", logged)
        self.assertNotIn("limit", logged)
        self.assertNotIn("\x01", logged)

    def test_db_busy_maps_503(self):
        writer = sqlite3.connect(self.path)
        writer.execute("PRAGMA journal_mode=DELETE")
        writer.execute("BEGIN EXCLUSIVE")
        try:
            response, body = self.request("GET", "/api/summary")
            self.assertEqual(response.status, 503)
            self.assertEqual(self.error_code(body), "DB_BUSY")
        finally:
            writer.rollback()
            writer.close()
        response, _ = self.request("GET", "/api/summary")
        self.assertEqual(response.status, 200)

    def test_invalid_store_maps_500(self):
        db = sqlite3.connect(self.path)
        db.execute("UPDATE works SET state='{\"broken'")
        db.commit()
        db.close()
        response, body = self.request("GET", "/api/works")
        self.assertEqual(response.status, 500)
        self.assertEqual(self.error_code(body), "INVALID_STORE")
        self.assertNotIn(str(self.dir), body.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
