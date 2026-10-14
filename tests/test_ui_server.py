"""Tests for work_runtime.ui_server — the loopback read-only HTTP boundary."""

import http.client
import json
import threading
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
