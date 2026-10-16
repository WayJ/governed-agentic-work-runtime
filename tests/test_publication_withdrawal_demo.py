"""S13 demo wave: the publication-demo withdrawal chapter (D77).

The chapter continues the standing S12 publication story inside the same
demo run and the same fresh store: after the published card and the
approver rotation, a governed ``sop.withdraw`` work withdraws the published
version behind a signed ``card_withdrawal``, the loader flips to the
distinct withdrawn error, ``withdrawal_record()`` reads the audit record,
a re-publication of the withdrawn version is refused by the governed
proposal with zero store writes, and an old-key withdrawal envelope is
refused ``EVIDENCE_KEY_RETIRED`` with history untouched. These tests read
the SQLite store and the artifact directory directly (never the printed
text for state) and re-derive every count, key and digest locally.
"""

import contextlib
import hashlib
import io
import json
import re
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from work_runtime.adoption_demo import packaged_card
from work_runtime.publication import WITHDRAWN_MESSAGE
from work_runtime.publication_demo import (
    FINAL_LINE,
    REPUBLICATION_WORK_ID,
    WITHDRAWAL_WORK_ID,
    run_publication_demo,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

PINNED_PUBLISHING_DIGEST = ("56c85d32da9a9eee6330326e2d14ce0661dbc26d"
                            "782b13d0259c3f149e6be000")
DOCTORED_GOAL = "content.published.doctored"
ABSENT_LINE = re.compile(r"^absent version: (.+)$", re.MULTILINE)
TAMPERED_LINE = re.compile(r"^tampered file: (.+)$", re.MULTILINE)
WITHDRAWN_LINE = re.compile(r"^withdrawn version: (.+)$", re.MULTILINE)
WITHDRAWAL_RECORD_LINE = re.compile(r'withdrawal record: "([^"]+)"')
INSPECT_COMMANDS = re.compile(r'^  (python3 -m work_runtime inspect .+)$',
                              re.MULTILINE)
HASH_NAMED = re.compile(r"^[0-9a-f]{64}\.json$")

WITHDRAWAL_RECORD_DOCUMENT = {
    "discriminator": "sop.withdrawal",
    "policy_id": "content-publish",
    "policy_version": "demo-1",
    "published_digest": PINNED_PUBLISHING_DIGEST,
}

WITHDRAWAL_RUNTIME_COMMANDS = (
    "cmd-create-wd1", "cmd-bind-wd1", "cmd-propose-wd1-blocked",
    "withdraw-once", "cmd-complete-wd1", "cmd-create-pub3", "cmd-bind-pub3",
    "cmd-propose-pub3-blocked", "cmd-propose-pub3",
)
WITHDRAWAL_GATEWAY_COMMANDS = ("cmd-approve-wd1", "cmd-approve-pub3")
WITHDRAWAL_BLOCKED_COMMANDS = ("cmd-propose-wd1-blocked",
                               "cmd-propose-pub3-blocked")
# The S12 story contributes the other eleven (nine agent + two sop-owner).
S12_RUNTIME_COMMANDS = (
    "cmd-create-pub", "cmd-bind-pub", "cmd-propose-blocked", "publish-once",
    "cmd-complete-pub", "cmd-create-pub2", "cmd-bind-pub2",
    "cmd-propose-conflict-blocked", "cmd-propose-conflict",
)
S12_GATEWAY_COMMANDS = ("cmd-approve-valid", "cmd-approve-conflict")


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


def withdrawal_key_of(policy_id, policy_version):
    return "sop-withdrawn:" + local_digest([policy_id, policy_version])


def artifact_name(key):
    return hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json"


class WithdrawalChapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cls.folder = run_publication_demo(directory=cls.temp.name)
        cls.stdout = out.getvalue()
        cls.store_dir = Path(cls.folder) / "publication" / "store"
        cls.runtime_path = Path(cls.folder) / "publication" / "runtime.sqlite"
        cls.card = packaged_card("publishing.json")
        cls.publication_artifact = (
            cls.store_dir / artifact_name(publication_key_of(cls.card)))
        cls.withdrawal_artifact = (
            cls.store_dir / artifact_name(withdrawal_key_of("content-publish",
                                                            "demo-1")))

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

    def test_output_pins_final_line_chapter_codes_and_two_inspects(self):
        self.assertIn(FINAL_LINE, self.stdout)
        for code in ("REQUIREMENT_UNSATISFIED", "OPERATION_CONTENT_CONFLICT",
                     "EVIDENCE_KEY_RETIRED", "confirmed_succeeded"):
            self.assertIn(code, self.stdout)
        self.assertEqual(self.stdout.count("inspect --db"), 2)
        self.assertIsNotNone(WITHDRAWAL_RECORD_LINE.search(self.stdout),
                             self.stdout)

    def test_store_holds_exactly_two_hash_named_artifacts_and_zero_stage(self):
        names = [path.name for path in committed_artifacts(self.store_dir)]
        self.assertEqual(set(names),
                         {artifact_name(publication_key_of(self.card)),
                          artifact_name(withdrawal_key_of("content-publish",
                                                          "demo-1"))})
        self.assertFalse([path for path in self.store_dir.iterdir()
                          if path.suffix == ".stage"])

    def test_withdrawal_record_artifact_is_the_closed_record(self):
        artifact = json.loads(self.withdrawal_artifact.read_text(
            encoding="utf-8"))
        self.assertEqual(set(artifact), {"artifact_version", "key",
                                         "content_digest", "document",
                                         "receipt"})
        self.assertEqual(artifact["artifact_version"], 1)
        self.assertEqual(artifact["document"], WITHDRAWAL_RECORD_DOCUMENT)
        self.assertEqual(artifact["content_digest"],
                         local_digest(WITHDRAWAL_RECORD_DOCUMENT))
        key = withdrawal_key_of("content-publish", "demo-1")
        self.assertEqual(artifact["key"], key)
        self.assertEqual(self.withdrawal_artifact.name, artifact_name(key))
        receipt = artifact["receipt"]
        self.assertEqual(receipt["status"], "accepted")
        self.assertTrue(receipt["external_id"].startswith("FILE-"))
        self.assertEqual(receipt["digest"], artifact["content_digest"])

    def test_publication_artifact_bytes_are_unchanged_by_the_chapter(self):
        artifact = json.loads(self.publication_artifact.read_text(
            encoding="utf-8"))
        self.assertEqual(artifact["document"], self.card)
        self.assertEqual(artifact["content_digest"],
                         local_digest(self.card))
        self.assertEqual(artifact["content_digest"], PINNED_PUBLISHING_DIGEST)

    def test_work_states_cover_all_four_works(self):
        ids = {row[0] for row in rows(self.runtime_path, "SELECT id FROM works")}
        self.assertEqual(ids, {"pub-1", "pub-2", WITHDRAWAL_WORK_ID,
                               REPUBLICATION_WORK_ID})
        self.assertEqual((self.work_state("pub-1")["status"],
                          self.work_state("pub-1")["outcome"]),
                         ("closed", "succeeded"))
        self.assertEqual(self.work_state("pub-2")["status"], "active")
        self.assertEqual((self.work_state(WITHDRAWAL_WORK_ID)["status"],
                          self.work_state(WITHDRAWAL_WORK_ID)["outcome"]),
                         ("closed", "succeeded"))
        self.assertEqual(self.work_state(REPUBLICATION_WORK_ID)["status"],
                         "active")

    def test_operations_are_publication_and_withdrawal_only(self):
        operations = self.operations()
        self.assertEqual(len(operations), 2)
        by_key = {operation["business_key"]: operation
                  for operation in operations}
        publication = by_key[publication_key_of(self.card)]
        withdrawal = by_key[withdrawal_key_of("content-publish", "demo-1")]
        for operation in (publication, withdrawal):
            self.assertEqual(operation["status"], "confirmed_succeeded")
            self.assertEqual(len(operation["attempts"]), 1)
        self.assertEqual(publication["work_id"], "pub-1")
        self.assertEqual(withdrawal["work_id"], WITHDRAWAL_WORK_ID)

    def test_evidence_rows_exact(self):
        bodies = self.evidence_bodies()
        self.assertEqual(len(bodies), 6)
        by_event = {body["event_id"]: body for body in bodies}
        doctored = json.loads(json.dumps(self.card))  # local deep copy
        doctored["policy"]["goal"] = DOCTORED_GOAL
        for event_id, digest_value in (
                ("evt-approve-valid", local_digest(self.card)),
                ("evt-approve-conflict", local_digest(doctored)),
                ("evt-approve-pub3", local_digest(self.card))):
            body = by_event[event_id]
            self.assertEqual((body["source"], body["kind"], body["status"]),
                             ("sop-owner", "card_approval", "verified"))
            self.assertEqual(body["data"],
                             {"digest": digest_value,
                              "policy_version": "demo-1"})
        withdrawal_approval = by_event["evt-approve-wd1"]
        self.assertEqual((withdrawal_approval["source"],
                          withdrawal_approval["kind"],
                          withdrawal_approval["status"]),
                         ("sop-owner", "card_withdrawal", "verified"))
        self.assertEqual(withdrawal_approval["data"],
                         {"digest": PINNED_PUBLISHING_DIGEST,
                          "policy_version": "demo-1"})
        accepted = [body for body in bodies
                    if body["source"] == "sop-store"]
        self.assertEqual(len(accepted), 2)
        operations = {operation["id"]: operation
                      for operation in self.operations()}
        for proof in accepted:
            self.assertEqual((proof["kind"], proof["status"]),
                             ("accepted", "verified"))
            operation = operations[proof["event_id"]]
            if operation["business_key"] == publication_key_of(self.card):
                self.assertEqual(proof["data"]["digest"],
                                 local_digest(self.card))
            else:
                self.assertEqual(proof["data"]["digest"],
                                 local_digest(WITHDRAWAL_RECORD_DOCUMENT))
                self.assertEqual(proof["data"]["external_id"],
                                 json.loads(self.withdrawal_artifact.read_text(
                                     encoding="utf-8"))["receipt"]["external_id"])

    def test_command_rows_pinned(self):
        found = rows(self.runtime_path, "SELECT actor, id FROM commands")
        self.assertEqual({(row[0], row[1]) for row in found},
                         {("agent", command_id)
                          for command_id in (S12_RUNTIME_COMMANDS
                                             + WITHDRAWAL_RUNTIME_COMMANDS)} |
                         {("sop-owner", command_id)
                          for command_id in (S12_GATEWAY_COMMANDS
                                             + WITHDRAWAL_GATEWAY_COMMANDS)})
        self.assertEqual(len(found),
                         len(S12_RUNTIME_COMMANDS)
                         + len(WITHDRAWAL_RUNTIME_COMMANDS)
                         + len(S12_GATEWAY_COMMANDS)
                         + len(WITHDRAWAL_GATEWAY_COMMANDS))
        for blocked_id in WITHDRAWAL_BLOCKED_COMMANDS:
            receipt = json.loads(rows(self.runtime_path, "SELECT receipt "
                                                         "FROM commands "
                                                         "WHERE id=?",
                                      (blocked_id,))[0][0])
            self.assertEqual(receipt["code"], "REQUIREMENT_UNSATISFIED")
        conflict = json.loads(rows(self.runtime_path, "SELECT receipt FROM "
                                                      "commands WHERE "
                                                      "id='cmd-propose-pub3'"
                                   )[0][0])
        self.assertEqual(conflict["decision"], "rejected")
        self.assertEqual(conflict["code"], "OPERATION_CONTENT_CONFLICT")

    def test_withdrawn_loader_line_is_distinct_and_exact(self):
        absent = ABSENT_LINE.search(self.stdout)
        tampered = TAMPERED_LINE.search(self.stdout)
        withdrawn = WITHDRAWN_LINE.search(self.stdout)
        for match in (absent, tampered, withdrawn):
            self.assertIsNotNone(match, self.stdout)
        self.assertEqual(withdrawn.group(1), WITHDRAWN_MESSAGE)
        self.assertNotEqual(withdrawn.group(1), absent.group(1))
        self.assertNotEqual(withdrawn.group(1), tampered.group(1))
        self.assertNotEqual(absent.group(1), tampered.group(1))
        self.assertNotIn("no published card", withdrawn.group(1))
        self.assertIn("withdrawn", withdrawn.group(1))
        self.assertIn("new version", withdrawn.group(1))

    def test_narration_states_no_un_withdrawal(self):
        self.assertIn("no un-withdrawal", self.stdout.lower())

    def test_table_counts_and_metadata_are_pinned(self):
        counts = {table: rows(self.runtime_path, "SELECT COUNT(*) FROM "
                              + table)[0][0]
                  for table in ("works", "commands", "evidence", "operations",
                                "events", "metadata")}
        self.assertEqual(counts, {"works": 4, "commands": 22, "evidence": 6,
                                  "operations": 2, "events": 21,
                                  "metadata": 1})
        self.assertEqual(rows(self.runtime_path, "SELECT * FROM metadata"),
                         [("schema_version", "1")])

    def test_printed_inspect_commands_run_verbatim(self):
        commands = INSPECT_COMMANDS.findall(self.stdout)
        self.assertEqual(len(commands), 2, self.stdout)
        self.assertTrue(any("--work %s" % WITHDRAWAL_WORK_ID in command
                            for command in commands), commands)
        for command in commands:
            self.assertIn("--policy sop-publish", command)
            words = shlex.split(command)
            self.assertEqual(words[0], "python3")
            words[0] = sys.executable
            result = subprocess.run(words, capture_output=True, text=True,
                                    timeout=60, cwd=str(REPO_ROOT))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"outcome": "succeeded"', result.stdout)

    def test_printed_withdrawal_record_path_is_the_committed_file(self):
        match = WITHDRAWAL_RECORD_LINE.search(self.stdout)
        self.assertIsNotNone(match, self.stdout)
        printed = Path(match.group(1))
        self.assertTrue(printed.exists(), str(printed))
        self.assertEqual(printed, self.withdrawal_artifact)


def _load_verify_install():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "verify_install", REPO_ROOT / "scripts" / "verify_install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VerifyInstallWithdrawalProofTests(unittest.TestCase):
    """The installer proof reads the chapter's real stores, never stdout."""

    def setUp(self):
        # A fresh demo run per test: every mutation below hits a pristine
        # store, so each rejection is attributable to its own mutation.
        self.verify_install = _load_verify_install()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.folder = run_publication_demo(directory=self.temp.name)
        self.stdout = out.getvalue()
        self.runtime_db = self.folder / "publication" / "runtime.sqlite"
        self.record_file = (self.folder / "publication" / "store"
                            / artifact_name(withdrawal_key_of("content-publish",
                                                              "demo-1")))

    def mutate_db(self, sql, args=()):
        db = sqlite3.connect(str(self.runtime_db))
        with db:
            db.execute(sql, args)
        db.close()

    def proof(self, stdout=None):
        return self.verify_install.require_publication_proof(
            stdout if stdout is not None else self.stdout, "test")

    def test_proof_passes_on_real_demo_output(self):
        runtime_db = self.proof()
        self.assertEqual(Path(runtime_db).parent.name, "publication")

    def test_proof_rejects_deleted_withdrawal_record(self):
        self.record_file.unlink()
        with self.assertRaises(SystemExit) as raised:
            self.proof()
        self.assertIn("withdrawal", str(raised.exception))

    def test_proof_rejects_tampered_withdrawal_record(self):
        raw = json.loads(self.record_file.read_text(encoding="utf-8"))
        raw["document"]["published_digest"] = "f" * 64
        self.record_file.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(SystemExit) as raised:
            self.proof()
        self.assertIn("withdrawal", str(raised.exception))
        self.assertIn("digest", str(raised.exception))

    def test_proof_rejects_flipped_card_withdrawal_status(self):
        self.mutate_db("UPDATE evidence SET body=replace(body, "
                       "'\"status\":\"verified\"', "
                       "'\"status\":\"pending_verification\"') "
                       "WHERE event_id='evt-approve-wd1'")
        with self.assertRaises(SystemExit) as raised:
            self.proof()
        self.assertIn("evt-approve-wd1", str(raised.exception))

    def test_proof_rejects_rewritten_republish_receipt(self):
        self.mutate_db("UPDATE commands SET receipt=replace(receipt, "
                       "'\"OPERATION_CONTENT_CONFLICT\"', '\"accepted\"') "
                       "WHERE id='cmd-propose-pub3'")
        with self.assertRaises(SystemExit) as raised:
            self.proof()
        self.assertIn("OPERATION_CONTENT_CONFLICT", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
