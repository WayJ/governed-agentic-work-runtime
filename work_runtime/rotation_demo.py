"""A deterministic signing-key rotation harness: rotate keys, never history.

Runs the real Runtime and the S11 core gateway through its public API with an
injected deterministic clock and ephemeral in-memory keys — no credentials, no
network, no model session. Only key ids are ever printed; secret material
exists in process memory for the run and is never echoed, logged or persisted.
Rotation is a configuration act: reconstructing the gateway from new
configuration writes nothing, and every pre-rotation row of every table stays
byte-identical across the rotation acts. Trust is config-only (see
docs/signed-evidence.md): there is no persistent key revocation memory, a
pre-rotation configuration rollback revives the old key, and the principals
are trusted local grants, not authentication.
"""

import hashlib
import json
import secrets
import sqlite3
import tempfile
from pathlib import Path

from .demo import demo_grants, initialize
from .ingress import (CODE_KEY_RETIRED, OPTIONAL_KEY_FIELD, SIGNED_FIELDS,
                      SignedEvidenceGateway, SourceKey, sign_evidence)
from .policy import ExpensePolicy
from .runtime import Runtime

T0 = 2000000000
GRACE = 300  # == max_age, the documented minimum so in-flight envelopes land inside it
OLD_KEY_ID = "finance-2026-08"
NEW_KEY_ID = "finance-2026-10"
FINAL_LINE = ("1 scenario; dual-key accepts: 2; retired refusals: 1 (zero writes); "
              "cached receipts verbatim: 2; new commands: 1; history rewritten: 0")
TABLES = ("works", "commands", "evidence", "operations", "events", "metadata")


def _key(key_id, **fields):
    """One ephemeral keyring entry; the secret never leaves this process."""
    return SourceKey(key_id, secrets.token_bytes(32), **fields)


def _table_dump(path):
    """Ordered rowid dump of all six tables, for byte-identity proofs."""
    dump = {}
    db = sqlite3.connect(str(path))
    try:
        for table in TABLES:
            dump[table] = db.execute("SELECT * FROM %s ORDER BY rowid" % table).fetchall()
    finally:
        db.close()
    return dump


def _six_table_digest(path):
    """SHA-256 over the ordered rowid dumps of all six tables (16-char prefix)."""
    dump = {table: [list(row) for row in rows]
            for table, rows in _table_dump(path).items()}
    encoded = json.dumps(dump, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _evidence_status(path, event_id):
    db = sqlite3.connect(str(path))
    try:
        row = db.execute("SELECT body FROM evidence WHERE source='finance' "
                         "AND event_id=?", (event_id,)).fetchone()
    finally:
        db.close()
    return json.loads(row[0])["status"]


def run_rotation_demo(directory=None):
    """Run the rotation scenario against its own fresh store; return the folder."""
    # Fresh directory per run; never removes existing user data.
    folder = Path(tempfile.mkdtemp(prefix="governed-rotation-", dir=directory))
    store = folder / "rotate" / "runtime.sqlite"
    store.parent.mkdir()
    clock = {"now": T0}

    def tick(now):
        clock["now"] = now
        return now

    runtime = Runtime(str(store), ExpensePolicy(), demo_grants())
    initialize(runtime, "rotate")
    digest = runtime.get_work("rotate")["document_digest"]
    old_key = _key(OLD_KEY_ID, current=True)
    new_key = _key(NEW_KEY_ID)
    print("Scenario — rotate a source signing key without rewriting history "
          "(own store: rotate/)", flush=True)
    print("ephemeral in-memory keys %s (current) and %s; secrets are never "
          "printed, only key ids" % (OLD_KEY_ID, NEW_KEY_ID), flush=True)

    def message(command_id, event_id, issued_at, key_id):
        return {"source": "finance", "command_id": command_id, "work_id": "rotate",
                "event_id": event_id, "kind": "approval", "data": {"digest": digest},
                "issued_at": issued_at, OPTIONAL_KEY_FIELD: key_id}

    gateway = SignedEvidenceGateway(runtime, {"finance": [old_key, new_key]},
                                    clock=lambda: clock["now"])
    envelope = sign_evidence(old_key.secret,
                             message("cmd-rotation-k1", "evt-rotation-1", T0,
                                     OLD_KEY_ID))
    assert set(envelope) - {"signature"} == set(SIGNED_FIELDS) | {OPTIONAL_KEY_FIELD}
    first = gateway.record(envelope)
    second = gateway.record(sign_evidence(new_key.secret,
                                           message("cmd-rotation-k2", "evt-rotation-2",
                                                   T0, NEW_KEY_ID)))
    assert first["decision"] == "accepted" and second["decision"] == "accepted"
    print("1. Dual-key window: approvals signed by both keys authenticate under "
          "one keyring → accepted (pending_verification)", flush=True)

    runtime.verify_pending("rotate")
    assert _evidence_status(store, "evt-rotation-1") == "verified"
    assert _evidence_status(store, "evt-rotation-2") == "verified"
    before = _table_dump(store)
    digest_before = _six_table_digest(store)
    print("2. verify_pending → both approvals verified (the last legitimate "
          "writes before rotation)", flush=True)
    print("   six-table digest before rotation: %s" % digest_before, flush=True)

    # Rotation is a configuration act: a fresh gateway over the rotated ring
    # (old key retained with its grace window, new key current). The clock sits
    # exactly on the inclusive boundary, where the key window edge and the
    # freshness edge of the original envelope coincide.
    rotated = SignedEvidenceGateway(
        runtime,
        {"finance": [SourceKey(OLD_KEY_ID, old_key.secret, not_after=T0 + GRACE),
                     SourceKey(NEW_KEY_ID, new_key.secret, current=True)]},
        clock=lambda: clock["now"])
    tick(T0 + GRACE)
    boundary = rotated.record(envelope)
    assert boundary == first  # the ORIGINAL cached receipt, verbatim
    assert _table_dump(store) == before
    print("3. Rotate: %s becomes current, %s retained with not_after = T+%d "
          "(grace == max_age); clock AT the boundary → replay the ORIGINAL "
          "old-key envelope → the ORIGINAL cached receipt returned verbatim, "
          "zero writes" % (NEW_KEY_ID, OLD_KEY_ID, GRACE), flush=True)

    tick(T0 + GRACE + 1)
    retired = rotated.record(envelope)
    assert retired == {"decision": "rejected", "code": CODE_KEY_RETIRED}
    assert _table_dump(store) == before
    print("4. Clock one second past grace: the SAME original envelope → "
          "rejected EVIDENCE_KEY_RETIRED (window precedes freshness; the cached "
          "receipt is unreachable behind authentication), zero writes", flush=True)

    resigned = rotated.record(sign_evidence(
        new_key.secret, message("cmd-rotation-k1", "evt-rotation-1",
                                T0 + GRACE + 1, NEW_KEY_ID)))
    assert resigned == first  # byte-verbatim; the timestamp is not business content
    assert _table_dump(store) == before
    print("5. Re-sign under the new key, SAME command id and business payload "
          "(fresh timestamp) → the ORIGINAL cached receipt byte-verbatim; no "
          "new command row, zero writes", flush=True)

    resend = rotated.record(sign_evidence(
        new_key.secret, message("cmd-rotation-resend", "evt-rotation-1",
                                T0 + GRACE + 1, NEW_KEY_ID)))
    assert resend["decision"] == "accepted"
    assert resend["evidence_id"] == first["evidence_id"]
    assert resend["evidence_status"] == "verified"  # the CURRENT status
    after = _table_dump(store)
    for table in ("works", "evidence", "operations", "events", "metadata"):
        assert after[table] == before[table], table
    assert len(after["commands"]) == len(before["commands"]) + 1
    print('6. NEW command id, same source event → accepted; evidence_status '
          '"verified" (the CURRENT status); exactly one new command row, no '
          "new evidence row", flush=True)

    digest_final = _six_table_digest(store)
    assert digest_final != digest_before
    print("7. six-table digest after all steps: %s — all six tables stayed "
          "byte-identical to before rotation through the boundary replay, the "
          "retired refusal and the re-sign; the new command appended exactly "
          "one commands row (five tables still byte-identical)" % digest_final,
          flush=True)
    print(FINAL_LINE)
    print("\nInspect the durable history:")
    print(f'  python3 -m work_runtime inspect --db "{store}" --work rotate')
    return folder
