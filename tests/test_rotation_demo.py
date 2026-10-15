"""S11 demo wave: rotation demo — dual-key window, retirement, verbatim cache, history.

The demo drives the frozen W1 core through its public gateway API with an
injected deterministic clock and ephemeral keys (secrets.token_bytes, never
printed — only key ids); these tests read the SQLite store directly to assert
what the public path actually produced, never trusting the printed text for
state, and re-derive every count and digest locally.
"""

import contextlib
import hashlib
import io
import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

FINAL_LINE = ("1 scenario; dual-key accepts: 2; retired refusals: 1 (zero writes); "
              "cached receipts verbatim: 2; new commands: 1; history rewritten: 0")
KEY_IDS = ("finance-2026-08", "finance-2026-10")
EVENT_IDS = ("evt-rotation-1", "evt-rotation-2")
COMMAND_IDS = ("cmd-rotation-k1", "cmd-rotation-k2", "cmd-rotation-resend")
BEFORE_DIGEST = re.compile(r"six-table digest before rotation: ([0-9a-f]{16})")
FINAL_DIGEST = re.compile(r"six-table digest after all steps: ([0-9a-f]{16})")
INSPECT_DB = re.compile(r'--db "([^"]+)"')
HEX64 = re.compile(r"[0-9a-f]{64}")
TABLES = ("works", "commands", "evidence", "operations", "events", "metadata")


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


def six_table_digest(db_path):
    """SHA-256 over the ordered rowid dumps of all six tables (16-char prefix)."""
    dump = {}
    db = sqlite3.connect(str(db_path))
    try:
        for table in TABLES:
            dump[table] = [list(row) for row in
                           db.execute("SELECT * FROM %s ORDER BY rowid" % table)]
    finally:
        db.close()
    return hashlib.sha256(canonical_json(dump).encode("utf-8")).hexdigest()[:16]


def evidence_body(db_path, source, event_id):
    found = rows(db_path, "SELECT body FROM evidence WHERE source=? AND event_id=?",
                 (source, event_id))
    return json.loads(found[0][0]) if found else None


class RotationDemoTests(unittest.TestCase):
    def setUp(self):
        from work_runtime import rotation_demo
        self.rotation_demo = rotation_demo
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def run_demo(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            folder = self.rotation_demo.run_rotation_demo(self.temp.name)
        return folder, out.getvalue()

    def store(self, folder):
        return folder / "rotate" / "runtime.sqlite"

    def test_demo_creates_fresh_store(self):
        folder, _ = self.run_demo()
        self.assertTrue(self.store(folder).is_file(), self.store(folder))

    def test_store_evidence_rows_statuses_and_fingerprints(self):
        folder, _ = self.run_demo()
        store = self.store(folder)
        state = json.loads(rows(store, "SELECT state FROM works WHERE id='rotate'")[0][0])
        for event_id in EVENT_IDS:
            body = evidence_body(store, "finance", event_id)
            self.assertIsNotNone(body, event_id)
            self.assertEqual((body["kind"], body["status"]), ("approval", "verified"))
            self.assertEqual(body["data"], {"digest": local_digest(state["document"])})
            fingerprint = rows(store, "SELECT fingerprint FROM evidence "
                                      "WHERE source='finance' AND event_id=?",
                               (event_id,))[0][0]
            self.assertEqual(fingerprint, local_digest(
                ["rotate", {"event_id": event_id, "kind": body["kind"],
                            "data": body["data"]}]))
        self.assertEqual(rows(store, "SELECT COUNT(*) FROM evidence")[0][0], 2)

    def test_store_command_rows_exact_with_original_cached_receipt(self):
        folder, _ = self.run_demo()
        store = self.store(folder)
        self.assertEqual(rows(store, "SELECT COUNT(*) FROM commands")[0][0], 6)
        for command_id in COMMAND_IDS:
            self.assertEqual(rows(store, "SELECT COUNT(*) FROM commands WHERE id=?",
                                  (command_id,))[0][0], 1, command_id)
        actors = dict(rows(store, "SELECT id, actor FROM commands WHERE id IN "
                                  "('cmd-rotation-k1','cmd-rotation-k2','cmd-rotation-resend')"))
        self.assertEqual(set(actors.values()), {"finance"})
        receipt = json.loads(rows(store, "SELECT receipt FROM commands "
                                         "WHERE id='cmd-rotation-k1'")[0][0])
        self.assertEqual(receipt["decision"], "accepted")
        # The stored receipt is the ORIGINAL: recorded while the evidence was
        # still pending, never refreshed to the current verified status.
        self.assertEqual(receipt["evidence_status"], "pending_verification")
        self.assertEqual(receipt["evidence_id"],
                         evidence_body(store, "finance", "evt-rotation-1")["id"])

    def test_store_table_counts_and_work_state(self):
        folder, _ = self.run_demo()
        store = self.store(folder)
        self.assertEqual(rows(store, "SELECT COUNT(*) FROM works")[0][0], 1)
        self.assertEqual(rows(store, "SELECT COUNT(*) FROM operations")[0][0], 0)
        self.assertEqual(rows(store, "SELECT COUNT(*) FROM events")[0][0], 4)
        self.assertEqual(rows(store, "SELECT * FROM metadata"),
                         [("schema_version", "1")])
        state = json.loads(rows(store, "SELECT state FROM works WHERE id='rotate'")[0][0])
        self.assertEqual(state["status"], "active")
        self.assertEqual(state["state_version"], 4)

    def test_six_table_digest_matches_printed_final_digest(self):
        folder, out = self.run_demo()
        before = BEFORE_DIGEST.search(out)
        final = FINAL_DIGEST.search(out)
        self.assertIsNotNone(before, "no printed before-rotation digest")
        self.assertIsNotNone(final, "no printed after-all-steps digest")
        self.assertEqual(final.group(1), six_table_digest(self.store(folder)))
        self.assertNotEqual(final.group(1), before.group(1))

    def test_output_pins_narrative_without_secret_material(self):
        _, out = self.run_demo()
        self.assertIn(FINAL_LINE, out)
        self.assertIn("EVIDENCE_KEY_RETIRED", out)
        self.assertIn("verbatim", out)
        self.assertIn("zero writes", out)
        for key_id in KEY_IDS:
            self.assertIn(key_id, out)
        self.assertEqual(out.count("inspect --db"), 1)
        self.assertIn("--work rotate", out)
        # Key ids are public data; secrets and signature values are not: no
        # 64-hex-char token may appear anywhere in the demo output.
        self.assertIsNone(HEX64.search(out), HEX64.search(out))

    def test_demo_runs_are_repeatable(self):
        folder_one, out_one = self.run_demo()
        folder_two, out_two = self.run_demo()
        self.assertNotEqual(folder_one, folder_two)
        self.assertIn(FINAL_LINE, out_one)
        self.assertIn(FINAL_LINE, out_two)


if __name__ == "__main__":
    unittest.main()
