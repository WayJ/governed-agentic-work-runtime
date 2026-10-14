"""Tests for the ui/ui-demo CLI surface and the lazy backend serve loop.

The read-only backend (work_runtime.ui_server) is owned by another worker and
may not exist in this checkout: prior CLI commands must keep working without
it, the new commands must import it lazily, and startup failures must exit 2
with bounded messages. Real HTTP serving is proven by scripts/verify_install.py
against the assembled backend; these tests pin the CLI lifecycle logic.
"""

import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from work_runtime import cli
from work_runtime.ui_demo import run_ui_demo, seed_ui_demo, serve_ui

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = "work_runtime.ui_server"
BACKEND_PRESENT = importlib.util.find_spec(BACKEND) is not None


def first_line(text):
    return text.splitlines()[0] if text.splitlines() else ""


class StubServer:
    """Interface-conforming stand-in for make_ui_server's ThreadingHTTPServer.

    Used only to unit-test the serve lifecycle (URL line, interrupt, close);
    it makes no HTTP or browser claims.
    """

    def __init__(self, seen=None):
        self.seen = seen
        self.address = ("127.0.0.1", 8123)
        self.served = False
        self.closed = False

    @property
    def server_address(self):
        return self.address

    def serve_forever(self):
        self.served = True
        raise KeyboardInterrupt()

    def server_close(self):
        self.closed = True


class LazyImportTests(unittest.TestCase):
    def test_importing_cli_never_imports_the_ui_backend(self):
        code = ("import work_runtime.cli, sys; "
                "sys.exit(1 if %r in sys.modules else 0)" % BACKEND)
        result = subprocess.run([sys.executable, "-c", code], cwd=str(REPO_ROOT),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0,
                         "importing work_runtime.cli pulled in %s: %s"
                         % (BACKEND, result.stderr))

    def test_prior_subcommand_runs_without_the_backend(self):
        parent = tempfile.mkdtemp()
        db = seed_ui_demo(parent)
        result = subprocess.run(
            [sys.executable, "-m", "work_runtime", "inspect", "--db", db,
             "--work", "succeed-1"], cwd=str(REPO_ROOT), capture_output=True,
            text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"outcome": "succeeded"', result.stdout)


class StartupValidationTests(unittest.TestCase):
    def setUp(self):
        self.parent = tempfile.mkdtemp()

    def assert_startup_error(self, db_path, port):
        error = io.StringIO()
        with redirect_stderr(error), self.assertRaises(SystemExit) as raised:
            serve_ui(db_path, port)
        self.assertEqual(raised.exception.code, 2)
        message = error.getvalue()
        self.assertTrue(message.strip(), "expected a bounded startup message")
        self.assertNotIn("Traceback", message)
        return message

    def test_port_out_of_range_exits_2_before_any_backend_import(self):
        for port in (-1, 70000):
            self.assert_startup_error(str(Path(self.parent) / "runtime.sqlite"), port)
        self.assertNotIn(BACKEND, sys.modules)

    def test_missing_database_exits_2(self):
        missing = str(Path(self.parent) / "nope.sqlite")
        message = self.assert_startup_error(missing, 0)
        self.assertIn(missing, message)

    def test_directory_as_database_exits_2(self):
        self.assert_startup_error(self.parent, 0)


@unittest.skipIf(BACKEND_PRESENT, "backend assembled: absent-install path unreachable")
class AbsentBackendTests(unittest.TestCase):
    def test_absent_backend_is_a_bounded_startup_error(self):
        parent = tempfile.mkdtemp()
        db = Path(parent) / "runtime.sqlite"
        db.write_bytes(b"")  # Existing file; only the backend import can fail.
        error = io.StringIO()
        with redirect_stderr(error), self.assertRaises(SystemExit) as raised:
            serve_ui(str(db), 0)
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("not available", error.getvalue())
        self.assertNotIn("Traceback", error.getvalue())


class ServeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.parent = tempfile.mkdtemp()
        self.db = Path(self.parent) / "runtime.sqlite"
        self.db.write_bytes(b"")

    def test_prints_actual_url_and_stops_cleanly_on_interrupt(self):
        stub = StubServer()
        out = io.StringIO()
        with redirect_stdout(out):
            serve_ui(str(self.db), 0, server_factory=lambda db_path, port: stub)
        self.assertEqual(first_line(out.getvalue()), "http://127.0.0.1:8123/")
        self.assertTrue(stub.served and stub.closed)

    def test_factory_receives_the_db_path_and_port(self):
        seen = {}
        stub = StubServer()
        seen["factory"] = lambda db_path, port: (seen.update(args=(db_path, port)), stub)[1]
        out = io.StringIO()
        with redirect_stdout(out):
            serve_ui(str(self.db), 8125, server_factory=seen["factory"])
        self.assertEqual(seen["args"], (str(self.db), 8125))

    def test_startup_failure_inside_the_factory_exits_2(self):
        def broken_factory(db_path, port):
            raise RuntimeError("NOT_A_DATABASE: not a SQLite database")
        error = io.StringIO()
        with redirect_stderr(error), self.assertRaises(SystemExit) as raised:
            serve_ui(str(self.db), 0, server_factory=broken_factory)
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("cannot start UI", error.getvalue())
        self.assertNotIn("Traceback", error.getvalue())

    def test_run_ui_demo_seeds_then_serves(self):
        target = Path(self.parent) / "demo-target"
        target.mkdir()
        stub = StubServer()
        out = io.StringIO()
        with redirect_stdout(out):
            run_ui_demo(str(target), 0, server_factory=lambda db_path, port: stub)
        text = out.getvalue()
        self.assertIn("seeded store:", text)
        self.assertIn("5 works seeded", text)
        url_lines = [line for line in text.splitlines() if line.startswith("http://")]
        self.assertEqual(first_line(url_lines[0]), "http://127.0.0.1:8123/")
        seeded = list(target.iterdir())
        self.assertEqual(len(seeded), 1)
        self.assertTrue(seeded[0].name.startswith("governed-ui-"))
        self.assertEqual((seeded[0] / "runtime.sqlite").is_file(), True)
        self.assertEqual(first_line([l for l in text.splitlines() if l.startswith("http://")][0]),
                         "http://127.0.0.1:8123/")


class CliWiringTests(unittest.TestCase):
    def setUp(self):
        self.parent = tempfile.mkdtemp()

    def run_cli(self, argv):
        out, error = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(error):
            with self.assertRaises(SystemExit) as raised:
                cli.main(argv)
        return raised.exception.code, out.getvalue(), error.getvalue()

    def test_ui_requires_db(self):
        code, _, _ = self.run_cli(["ui"])
        self.assertEqual(code, 2)

    def test_ui_bad_port_exits_2_with_bounded_message(self):
        code, _, error = self.run_cli(
            ["ui", "--db", str(Path(self.parent) / "runtime.sqlite"), "--port", "70000"])
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", error)

    def test_ui_missing_db_exits_2(self):
        code, _, error = self.run_cli(["ui", "--db", str(Path(self.parent) / "none.sqlite")])
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", error)

    def test_ui_demo_bad_port_exits_2_before_seeding(self):
        code, _, error = self.run_cli(["ui-demo", "--directory", self.parent, "--port", "-5"])
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", error)
        self.assertEqual(list(Path(self.parent).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
