"""Loopback-only HTTP boundary over the read-only inspector.

A local inspection tool, not a service: binds 127.0.0.1 only, serves an
exact route whitelist, grants no CORS, and never writes the store. Loopback
reachability is not authentication of any principal.
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote_plus

from .inspection import GuiReaderError, ReadOnlyInspector

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; "
       "connect-src 'self'; base-uri 'none'; object-src 'none'; "
       "frame-ancestors 'none'; form-action 'none'")

JSON_CONTENT_TYPE = "application/json; charset=utf-8"

# Whitelisted static assets, served from packaged work_runtime/web only.
_STATIC_ROUTES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
}

_API_LIMIT_MAX = 200

# Bounded GuiReaderError codes that carry a status other than 500.
_ERROR_STATUS = {
    "BAD_QUERY": 400,
    "UNKNOWN_WORK": 404,
    "UNKNOWN_ROUTE": 404,
    "METHOD_NOT_ALLOWED": 405,
    "BAD_HOST": 403,
    "BAD_ORIGIN": 403,
    "DB_BUSY": 503,
}


def _json_bytes(payload) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


_LOCAL_HOSTS = ("127.0.0.1", "localhost")


def _split_authority(authority):
    """Split 'host[:port]'; absent port means the HTTP default 80.

    Returns (host, port) lowercased, or (None, None) for anything this
    local tool does not recognize (IPv6 literals, malformed ports).
    """
    authority = authority.strip().lower()
    if not authority or authority.startswith("["):
        return None, None
    if ":" in authority:
        host, _, port_text = authority.rpartition(":")
        if not host or not port_text.isdigit():
            return None, None
        return host, int(port_text, 10)
    return authority, 80


class _UiHandler(BaseHTTPRequestHandler):
    """Whitelist dispatch; every response bounded and leak-free."""

    protocol_version = "HTTP/1.1"
    server_version = "WorkRuntimeUI/1"
    inspector = None  # bound per server by make_ui_server

    # -- plumbing ---------------------------------------------------------

    def do_GET(self):
        self._dispatch()

    def do_HEAD(self):
        self._dispatch()

    def _reject_method(self):
        self._fail("METHOD_NOT_ALLOWED", 405)

    do_POST = do_PUT = do_DELETE = do_OPTIONS = do_PATCH = _reject_method

    def send_error(self, code, message=None, explain=None):
        # Base-class error paths (unsupported methods, malformed request
        # lines) answer with the same bounded JSON envelope, never the
        # default HTML page and never the raw request line.
        if code == 501:
            self._fail("METHOD_NOT_ALLOWED", 405)
        else:
            self._fail("BAD_QUERY", 400, "Malformed request")

    def log_request(self, code="-", size="-"):
        # Method and status only: the raw URL never reaches the log.
        self.log_message("%s %s", self.command, code)

    def log_message(self, format, *args):
        try:
            message = format % args
        except Exception:
            message = "unloggable"
        message = "".join(
            character if character.isprintable() else "?"
            for character in message)
        sys.stderr.write("work-runtime ui: %s\n" % message)
        sys.stderr.flush()

    # -- responses --------------------------------------------------------

    def _respond(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        if getattr(self, "command", "") != "HEAD":
            self.wfile.write(body)

    def _fail(self, code, status, message=None):
        body = _json_bytes({"error": {"code": code, "message": message or code}})
        self.send_response(status)
        self.send_header("Content-Type", JSON_CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        if code == "METHOD_NOT_ALLOWED":
            self.send_header("Allow", "GET, HEAD")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        if getattr(self, "command", "") != "HEAD":
            self.wfile.write(body)

    def _respond_json(self, payload):
        self._respond(200, _json_bytes(payload), JSON_CONTENT_TYPE)

    # -- dispatch ---------------------------------------------------------

    def _dispatch(self):
        target = self.path
        if not target.startswith("/"):
            # Absolute-form, authority-form and asterisk targets are not
            # routes on this local tool.
            return self._fail("UNKNOWN_ROUTE", 404)
        path, _, query = target.partition("?")
        try:
            self._check_host()
            self._check_origin()
            if path in _STATIC_ROUTES:
                if query:
                    raise GuiReaderError("BAD_QUERY",
                                         "static routes accept no query string")
                return self._serve_static(path)
            if path == "/api/summary":
                self._parse_query(query, allowed=(), required=())
                return self._respond_json(self.inspector.summary())
            if path == "/api/works":
                params = self._parse_query(query, allowed=("limit", "offset"))
                limit = self._decimal_param(params, "limit", 100)
                offset = self._decimal_param(params, "offset", 0)
                return self._respond_json(
                    self.inspector.list_works(limit=limit, offset=offset))
            if path == "/api/work":
                params = self._parse_query(query, allowed=("id",), required=("id",))
                if not params["id"]:
                    raise GuiReaderError("BAD_QUERY", "id must be nonempty")
                return self._respond_json(self.inspector.work_detail(params["id"]))
            if path == "/api/events":
                params = self._parse_query(query, allowed=("work_id", "after", "limit"),
                                           required=("work_id",))
                if not params["work_id"]:
                    raise GuiReaderError("BAD_QUERY", "work_id must be nonempty")
                after = self._decimal_param(params, "after", 0)
                limit = self._decimal_param(params, "limit", 100)
                return self._respond_json(
                    self.inspector.events(params["work_id"],
                                          after=after, limit=limit))
            return self._fail("UNKNOWN_ROUTE", 404)
        except GuiReaderError as error:
            self._fail(error.code, _ERROR_STATUS.get(error.code, 500), error.message)
        except Exception:
            self._fail("INTERNAL", 500)

    # -- helpers ----------------------------------------------------------

    def _check_host(self):
        """Exactly one Host, a loopback authority naming the actual port."""
        values = self.headers.get_all("Host")
        if values is None or len(values) != 1:
            raise GuiReaderError("BAD_HOST", "exactly one Host header is required")
        host, port = _split_authority(values[0])
        actual = self.server.server_address[1]
        if host not in _LOCAL_HOSTS or port != actual:
            raise GuiReaderError("BAD_HOST", "Host must name this local server")

    def _check_origin(self):
        """Origin is optional, but when present it must be this origin."""
        values = self.headers.get_all("Origin")
        if not values:
            return
        if len(values) != 1:
            raise GuiReaderError("BAD_ORIGIN", "at most one Origin header is allowed")
        origin = values[0].strip()
        if not origin.lower().startswith("http://"):
            raise GuiReaderError("BAD_ORIGIN", "Origin must be this local origin")
        authority = origin[len("http://"):]
        if any(character in authority for character in "/@?#"):
            raise GuiReaderError("BAD_ORIGIN", "Origin must be this local origin")
        host, port = _split_authority(authority)
        actual = self.server.server_address[1]
        if host not in _LOCAL_HOSTS or port != actual:
            raise GuiReaderError("BAD_ORIGIN", "Origin must be this local origin")

    @staticmethod
    def _parse_query(query, allowed, required=()):
        params = {}
        if query:
            tokens = query.split("&")
            if any(not token for token in tokens):
                raise GuiReaderError("BAD_QUERY", "malformed query string")
            for token in tokens:
                key, _, value = token.partition("=")
                key = unquote_plus(key)
                if key in params:
                    raise GuiReaderError("BAD_QUERY", "duplicate query key")
                params[key] = unquote_plus(value)
        unknown = set(params) - set(allowed)
        if unknown:
            raise GuiReaderError("BAD_QUERY", "unknown query key")
        missing = set(required) - set(params)
        if missing:
            raise GuiReaderError("BAD_QUERY", "missing required query key")
        return params

    @staticmethod
    def _decimal_param(params, key, default):
        if key not in params:
            return default
        value = params[key]
        if not (value.isascii() and value.isdigit()):
            raise GuiReaderError("BAD_QUERY", "%s must be a decimal integer" % key)
        return int(value, 10)

    def _serve_static(self, path):
        name, content_type = _STATIC_ROUTES[path]
        asset = Path(__file__).resolve().parent / "web" / name
        try:
            body = asset.read_bytes()
        except OSError:
            # Frontend-owned assets are assembled by their own owner; until
            # then the bounded response is a plain unknown route.
            return self._fail("UNKNOWN_ROUTE", 404, "static asset not available")
        self._respond(200, body, content_type)


def make_ui_server(db_path, port=0):
    """Build the loopback server; startup validation raises GuiReaderError."""
    handler = type("BoundUiHandler", (_UiHandler,),
                   {"inspector": ReadOnlyInspector(db_path)})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server
