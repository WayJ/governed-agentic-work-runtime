"""S12 demo wave: publication-demo — lint, approve, publish, conflict, rotate.

The demo drives the frozen W1 publication core through its public API with an
injected deterministic clock and ephemeral never-printed approver keys; these
tests read the SQLite store and the artifact directory directly to assert
what the public path actually produced, never trusting the printed text for
state, and re-derive every count, key and digest locally.
"""

import contextlib
import copy
import hashlib
import io
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from work_runtime.adoption_demo import packaged_card
from work_runtime.publication_demo import (
    CONFLICT_WORK_ID,
    FINAL_LINE,
    WORK_ID,
    run_publication_demo,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

PINNED_PUBLISHING_DIGEST = ("56c85d32da9a9eee6330326e2d14ce0661dbc26d"
                            "782b13d0259c3f149e6be000")
DOCTORED_GOAL = "content.published.doctored"
INSPECT_COMMAND = re.compile(r'^  (python3 -m work_runtime inspect .+)$',
                             re.MULTILINE)
COMMITTED_LINE = re.compile(r'committed artifact: "([^"]+)"')
HASH_NAMED = re.compile(r"^[0-9a-f]{64}\.json$")
MARKER = b"PUBDEMO-SECRET-MARKER-never-print-8613"
MARKER_TWO = b"PUBDEMO-SECRET-TWO-never-print-4271"

RUNTIME_COMMAND_IDS = (
    "cmd-create-pub", "cmd-bind-pub", "cmd-propose-blocked", "publish-once",
    "cmd-complete-pub", "cmd-create-pub2", "cmd-bind-pub2",
    "cmd-propose-conflict-blocked", "cmd-propose-conflict",
)
GATEWAY_COMMAND_IDS = ("cmd-approve-valid", "cmd-approve-conflict")
ABSENT_LINE = re.compile(r"^absent version: (.+)$", re.MULTILINE)
TAMPERED_LINE = re.compile(r"^tampered file: (.+)$", re.MULTILINE)


def canonical_json(value):
    """Canonical JSON with the same parameters the runtime uses (local copy)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def local_digest(value):
    """SHA-256 over canonical JSON, recomputed independently of the product."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def rows(db_path, sql, args=()):
    db = sqlite3.connect(str(db_path))
    try:
        return db.execute(sql, args).fetchall()
    finally:
        db.close()


def committed_artifacts(directory):
    return sorted(path for path in Path(directory).iterdir()
                  if HASH_NAMED.fullmatch(path.name))


def publication_key_of(card):
    return "sop-pub:" + local_digest([card["policy"]["id"],
                                      card["policy"]["version"]])


def artifact_name(key):
    return hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json"


class PublicationDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cls.folder = run_publication_demo(directory=cls.temp.name)
        cls.stdout = out.getvalue()
        cls.store_dir = Path(cls.folder) / "publication" / "store"
        cls.runtime_path = Path(cls.folder) / "publication" / "runtime.sqlite"

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def work_state(self, work_id):
        state = json.loads(rows(self.runtime_path, "SELECT state FROM works "
                                                    "WHERE id=?",
                                (work_id,))[0][0])
        return state

    def operations(self):
        return [json.loads(row[0]) for row in
                rows(self.runtime_path, "SELECT body FROM operations")]

    def evidence_bodies(self):
        return [json.loads(row[0]) for row in
                rows(self.runtime_path, "SELECT body FROM evidence "
                                         "ORDER BY rowid")]

    def test_output_pins_final_line_and_key_codes(self):
        self.assertIn(FINAL_LINE, self.stdout)
        for code in ("REQUIREMENT_UNSATISFIED", "EVIDENCE_AUTHENTICATION_FAILED",
                     "OPERATION_CONTENT_CONFLICT", "EVIDENCE_KEY_RETIRED",
                     "outcome_unknown", "confirmed_succeeded"):
            self.assertIn(code, self.stdout)
        self.assertEqual(self.stdout.count("inspect --db"), 1)

    def test_store_holds_exactly_one_hash_named_artifact_and_zero_stage(self):
        files = list(self.store_dir.iterdir())
        self.assertEqual([path.name for path in committed_artifacts(self.store_dir)],
                         [artifact_name(publication_key_of(
                             packaged_card("publishing.json")))])
        self.assertFalse([path for path in files if path.suffix == ".stage"])

    def test_artifact_is_the_bare_card_with_recomputed_key_and_digests(self):
        artifact = json.loads(committed_artifacts(self.store_dir)[0]
                              .read_text(encoding="utf-8"))
        card = packaged_card("publishing.json")
        self.assertEqual(set(artifact), {"artifact_version", "key",
                                         "content_digest", "document",
                                         "receipt"})
        self.assertEqual(artifact["artifact_version"], 1)
        self.assertEqual(artifact["document"], card)
        self.assertEqual(artifact["content_digest"], local_digest(card))
        self.assertEqual(artifact["content_digest"], PINNED_PUBLISHING_DIGEST)
        self.assertEqual(artifact["key"], publication_key_of(card))
        self.assertEqual(artifact["receipt"]["status"], "accepted")
        self.assertTrue(artifact["receipt"]["external_id"].startswith("FILE-"))
        self.assertEqual(artifact["receipt"]["digest"],
                         artifact["content_digest"])
        operations = self.operations()
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0]["business_key"], artifact["key"])

    def test_works_states_and_operation_recovery(self):
        ids = {row[0] for row in rows(self.runtime_path, "SELECT id FROM works")}
        self.assertEqual(ids, {WORK_ID, CONFLICT_WORK_ID})
        self.assertEqual((self.work_state(WORK_ID)["status"],
                          self.work_state(WORK_ID)["outcome"]),
                         ("closed", "succeeded"))
        self.assertEqual(self.work_state(CONFLICT_WORK_ID)["status"], "active")
        operations = self.operations()
        self.assertEqual(operations[0]["status"], "confirmed_succeeded")
        self.assertEqual(len(operations[0]["attempts"]), 1)
        self.assertEqual(operations[0]["work_id"], WORK_ID)

    def test_evidence_rows_exact(self):
        card = packaged_card("publishing.json")
        doctored = copy.deepcopy(card)
        doctored["policy"]["goal"] = DOCTORED_GOAL
        bodies = self.evidence_bodies()
        self.assertEqual(len(bodies), 3)
        by_event = {body["event_id"]: body for body in bodies}
        valid = by_event["evt-approve-valid"]
        self.assertEqual((valid["source"], valid["kind"], valid["status"]),
                         ("sop-owner", "card_approval", "verified"))
        self.assertEqual(valid["data"],
                         {"digest": local_digest(card),
                          "policy_version": card["policy"]["version"]})
        conflict = by_event["evt-approve-conflict"]
        self.assertEqual((conflict["source"], conflict["kind"],
                          conflict["status"]),
                         ("sop-owner", "card_approval", "verified"))
        self.assertEqual(conflict["data"],
                         {"digest": local_digest(doctored),
                          "policy_version": card["policy"]["version"]})
        operation = self.operations()[0]
        accepted = by_event[operation["id"]]
        self.assertEqual((accepted["source"], accepted["kind"],
                          accepted["status"]),
                         ("sop-store", "accepted", "verified"))
        self.assertEqual(accepted["data"]["digest"], local_digest(card))
        artifact = json.loads(committed_artifacts(self.store_dir)[0]
                              .read_text(encoding="utf-8"))
        self.assertEqual(accepted["data"]["external_id"],
                         artifact["receipt"]["external_id"])

    def test_command_rows_pinned(self):
        found = rows(self.runtime_path, "SELECT actor, id FROM commands")
        self.assertEqual({(row[0], row[1]) for row in found},
                         {("agent", command_id)
                          for command_id in RUNTIME_COMMAND_IDS} |
                         {("sop-owner", command_id)
                          for command_id in GATEWAY_COMMAND_IDS})
        self.assertEqual(len(found),
                         len(RUNTIME_COMMAND_IDS) + len(GATEWAY_COMMAND_IDS))
        conflict_receipt = json.loads(rows(
            self.runtime_path, "SELECT receipt FROM commands "
            "WHERE id='cmd-propose-conflict'")[0][0])
        self.assertEqual(conflict_receipt["decision"], "rejected")
        self.assertEqual(conflict_receipt["code"], "OPERATION_CONTENT_CONFLICT")
        for blocked_id in ("cmd-propose-blocked",
                           "cmd-propose-conflict-blocked"):
            receipt = json.loads(rows(self.runtime_path, "SELECT receipt "
                                      "FROM commands WHERE id=?",
                                      (blocked_id,))[0][0])
            self.assertEqual(receipt["code"], "REQUIREMENT_UNSATISFIED")

    def test_conflict_left_the_winner_artifact_unchanged(self):
        raw = committed_artifacts(self.store_dir)[0].read_bytes()
        self.assertNotIn(DOCTORED_GOAL.encode("utf-8"), raw)
        self.assertNotIn(b"doctored", raw)
        artifact = json.loads(raw.decode("utf-8"))
        self.assertEqual(artifact["document"], packaged_card("publishing.json"))
        self.assertEqual(len(committed_artifacts(self.store_dir)), 1)

    def test_printed_inspect_command_runs_verbatim(self):
        match = INSPECT_COMMAND.search(self.stdout)
        self.assertIsNotNone(match, self.stdout)
        self.assertIn("--policy sop-publish", match.group(1))
        words = shlex.split(match.group(1))
        self.assertEqual(words[0], "python3")
        words[0] = sys.executable
        result = subprocess.run(words, capture_output=True, text=True,
                                timeout=60, cwd=str(REPO_ROOT))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"outcome": "succeeded"', result.stdout)

    def test_printed_artifact_path_is_the_committed_file(self):
        match = COMMITTED_LINE.search(self.stdout)
        self.assertIsNotNone(match, self.stdout)
        printed = Path(match.group(1))
        self.assertTrue(printed.exists(), str(printed))
        self.assertEqual(printed, committed_artifacts(self.store_dir)[0])

    def test_prologue_pins_digest_and_static_boundary(self):
        self.assertIn(PINNED_PUBLISHING_DIGEST, self.stdout)
        self.assertIn("EMPTY_VALUE", self.stdout)
        self.assertIn("static", self.stdout.lower())

    def test_loader_failures_are_printed_distinguishably(self):
        absent = ABSENT_LINE.search(self.stdout)
        tampered = TAMPERED_LINE.search(self.stdout)
        self.assertIsNotNone(absent, self.stdout)
        self.assertIsNotNone(tampered, self.stdout)
        self.assertIn("no published card", absent.group(1))
        self.assertNotIn("no published card", tampered.group(1))
        self.assertNotEqual(absent.group(1), tampered.group(1))

    def test_table_counts_and_metadata_are_pinned(self):
        counts = {table: rows(self.runtime_path, "SELECT COUNT(*) FROM "
                              + table)[0][0]
                  for table in ("works", "commands", "evidence", "operations",
                                "events", "metadata")}
        self.assertEqual(counts, {"works": 2, "commands": 11, "evidence": 3,
                                  "operations": 1, "events": 11,
                                  "metadata": 1})
        self.assertEqual(rows(self.runtime_path, "SELECT * FROM metadata"),
                         [("schema_version", "1")])


class PublicationDemoHygieneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_parent_directory_contents_survive_the_run(self):
        sentinel = Path(self.temp.name) / "sentinel.txt"
        sentinel.write_text("user data", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            run_publication_demo(directory=self.temp.name)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "user data")

    def test_two_runs_use_fresh_stores_each_holding_one_artifact(self):
        with contextlib.redirect_stdout(io.StringIO()):
            folders = {run_publication_demo(directory=self.temp.name),
                       run_publication_demo(directory=self.temp.name)}
        self.assertEqual(len(folders), 2)
        for folder in folders:
            self.assertEqual(len(committed_artifacts(
                Path(folder) / "publication" / "store")), 1)

    def test_demo_runs_with_cwd_outside_the_repository(self):
        previous = os.getcwd()
        os.chdir(self.temp.name)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                folder = run_publication_demo()
        finally:
            os.chdir(previous)
        self.assertEqual(len(committed_artifacts(
            Path(folder) / "publication" / "store")), 1)

    def test_output_never_echoes_secret_material(self):
        """Planted-marker discipline: patch the key generator, run, grep."""
        from unittest import mock
        from work_runtime import publication_demo
        from work_runtime.ingress import sign_evidence
        with mock.patch.object(publication_demo.secrets, "token_bytes",
                               side_effect=[MARKER, MARKER_TWO]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                run_publication_demo(directory=self.temp.name)
        leaked = out.getvalue()
        self.assertIn(FINAL_LINE, leaked)
        self.assertNotIn(MARKER.decode("ascii"), leaked)
        self.assertNotIn(MARKER.hex(), leaked)
        signature = sign_evidence(MARKER, {
            "source": "sop-owner", "command_id": "cmd-probe", "work_id": "x",
            "event_id": "evt-probe", "kind": "card_approval",
            "data": {"digest": "0" * 64, "policy_version": "demo-1"},
            "issued_at": 2000000000})["signature"]
        self.assertNotIn(signature, leaked)


class PublicationDemoCliTests(unittest.TestCase):
    def test_cli_publication_demo_directory_flag_runs_the_demo(self):
        from work_runtime import cli
        with tempfile.TemporaryDirectory() as folder:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = 0
                try:
                    cli.main(["publication-demo", "--directory", folder])
                except SystemExit as raised:
                    code = raised.code
            self.assertEqual(code, 0)
            self.assertIn(FINAL_LINE, out.getvalue())

    def test_cli_publication_demo_rejects_unknown_flags(self):
        from work_runtime import cli
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as raised:
                cli.main(["publication-demo", "--nope"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
