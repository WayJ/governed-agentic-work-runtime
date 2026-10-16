"""Content publication demo policy and its fake external publisher.

The policy is the second business domain on the shared Runtime: review,
confirmation and publication rules travel with the policy instead of the
lifecycle engine. Source names (`reviewer`, `author`, `publisher`) are
local trust configuration, not authentication — signed ingress
authenticates evidence sources and direct Runtime calls stay trusted-local
(see docs/signed-evidence.md and docs/adapter-contract.md).
"""

import json
import sqlite3
import uuid
from pathlib import Path
from typing import List

from .adapter_contract import AdapterContract
from .policy import canonical, digest


class PublishingPolicy:
    """Demo C01–C04 policy for publishing a reviewed document.

    It trusts in-process source identities configured by the application,
    like ExpensePolicy. `requires_review` None means review applicability
    is unknown, which blocks publication until it is decided.
    """

    id = "content-publish"
    version = "demo-1"
    goal = "content.published"
    evidence_sources = {
        "approval": "reviewer",
        "confirmation": "author",
        "accepted": "publisher",
    }
    # Compensation pairing (S14 D81/D89): the compensating capability maps
    # to the forward capability whose accepted effect it retracts. A policy
    # without this attribute keeps CAPABILITY_UNSUPPORTED for every
    # non-forward capability — graceful degradation for custom/old policies.
    compensation_capabilities = {"content.unpublish": "content.publish"}

    def validate_document(self, document: dict) -> None:
        if set(document) != {"id", "title", "body", "requires_review"}:
            raise ValueError("Document requires id, title, body and requires_review")
        for name in ("id", "title", "body"):
            if not isinstance(document[name], str) or not document[name]:
                raise ValueError("Document %s must be a nonempty string" % name)
        if document["requires_review"] is not None and type(document["requires_review"]) is not bool:
            raise ValueError("requires_review must be a boolean or null (unknown)")

    def validate_evidence(self, work: dict, candidate: dict) -> bool:
        data = candidate["data"]
        kind = candidate["kind"]
        if kind in ("approval", "confirmation"):
            return set(data) == {"digest"} and isinstance(data["digest"], str)
        if kind == "accepted":
            # Reserved shape adopted from Runtime-written receipts (design M5).
            return (set(data) == {"digest", "external_id"}
                    and isinstance(data["digest"], str)
                    and isinstance(data["external_id"], str)
                    and bool(data["external_id"]))
        return False

    def evaluate(self, work: dict, evidence: List[dict]) -> List[dict]:
        document = work["document"]
        current = work["document_digest"]
        proofs = [e for e in evidence if e["status"] == "verified"]

        def has(kind: str) -> bool:
            source = self.evidence_sources[kind]
            return any(e["kind"] == kind and e["source"] == source
                       and e["data"].get("digest") == current for e in proofs)

        result = []

        def add(rule: str, subject: str, applicable: str, satisfied: bool,
                explanation: str) -> None:
            result.append({"id": rule + ":" + subject, "rule_id": rule,
                           "subject": subject, "applicability": applicable,
                           "fulfillment": "satisfied" if satisfied else "pending",
                           "explanation": explanation})

        add("C01", document["id"], "applicable",
            bool(document["title"]) and bool(document["body"]),
            "The current artifact must be complete (nonempty title and body)")
        review = document["requires_review"]
        applicable = ("unknown" if review is None
                      else "applicable" if review else "not_applicable")
        add("C02", document["id"], applicable, has("approval"),
            "A true requires_review needs the reviewer's approval of the current content; "
            "a false one is not applicable, and an unknown one blocks")
        add("C03", document["id"], "applicable", has("confirmation"),
            "The author must confirm the current content")
        add("C04", document["id"], "applicable", has("accepted"),
            "The publisher must have accepted the current content")
        return result

    def action_blockers(self, capability: str, requirements: List[dict]) -> List[dict]:
        if capability != "content.publish":
            # A paired compensating capability is admitted through its link
            # check (runtime), not requirements: its blockers are empty.
            if self.compensation_capabilities.get(capability) == "content.publish":
                return []
            return [{"code": "CAPABILITY_UNSUPPORTED", "capability": capability}]
        return [r for r in requirements if r["rule_id"] != "C04" and
                (r["applicability"] in ("unknown", "conflict")
                 or (r["applicability"] == "applicable"
                     and r["fulfillment"] != "satisfied"))]

    def operation_key(self, capability: str, work: dict) -> str:
        return digest([self.id, capability, work["document"]["id"],
                       work["document_digest"]])


class FakePublisher:
    """A separate SQLite store models an external publishing service.

    Survives worker crashes like FakeOA. One published artifact per
    (document id, content digest): identical content resubmitted under
    another idempotency key reuses the existing external id, changed
    content becomes a new publication version. Since S14 it also executes
    the paired `content.unpublish` retraction action (the FakeOA D46
    pattern): one retraction effect per original, append-only history.
    """

    # Declared assertions for trusted local configuration, not a remote guarantee.
    # supports_action_context opts into explicit action/link execution; the
    # forward action stays FIRST (conformance derives forward context from
    # actions[0]).
    contract = AdapterContract(
        actions=("content.publish", "content.unpublish"),
        idempotency_scope="adapter-store:key",
        retention="lifetime-of-store",
        lookup_consistency="authoritative-by-key",
        uniqueness=("document.id+content_digest",
                    "retraction.original_external_id"),
        supports_action_context=True)

    def __init__(self, path: str, timeout_after_commit: bool = False):
        self.path = str(path)
        self.timeout_after_commit = timeout_after_commit
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15)
        try:
            # Additive migration (S14, the S10 D46 pattern): the probe and
            # every ALTER/CREATE run inside one BEGIN IMMEDIATE transaction
            # so concurrent first-open serializes instead of racing
            # duplicate-column errors.
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS receipts (
                key TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS publications (
                document_id TEXT, digest TEXT, external_id TEXT NOT NULL,
                document TEXT NOT NULL, PRIMARY KEY(document_id, digest))""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(receipts)")}
            if "action" not in columns:
                db.execute("ALTER TABLE receipts ADD COLUMN action TEXT")
            if "link_digest" not in columns:
                db.execute("ALTER TABLE receipts ADD COLUMN link_digest TEXT")
            db.execute("""CREATE TABLE IF NOT EXISTS retractions (
                original_external_id TEXT PRIMARY KEY, external_id TEXT NOT NULL,
                key TEXT NOT NULL, digest TEXT NOT NULL)""")
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def execute(self, key: str, document: dict, content_digest: str, *,
                action=None, compensates=None) -> dict:
        if digest(document) != content_digest:
            raise ValueError("Content digest does not match document")
        if action is None:
            # FakePublisher-side normalization for its own legacy direct
            # callers; not a protocol rule (legacy adapters are simply never
            # called with kwargs).
            action = "content.publish"
        if action not in ("content.publish", "content.unpublish"):
            raise ValueError("Unknown action: " + str(action))
        link_digest = None
        if action == "content.unpublish":
            if not self._valid_link(compensates):
                raise ValueError("content.unpublish requires a compensates link "
                                 "with operation_id, external_id and capability")
            link_digest = digest(compensates)
        elif compensates is not None:
            raise ValueError("Forward execution must not carry a compensates link")
        db = sqlite3.connect(self.path, timeout=15)
        try:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT digest,action,link_digest,result FROM receipts WHERE key=?",
                (key,)).fetchone()
            if old:
                # Replay requires digest, normalized action and link fingerprint
                # to match (legacy NULL action reads back as the forward action;
                # legacy NULL link digest means no compensation link).
                if (old[0] != content_digest
                        or (old[1] or "content.publish") != action
                        or old[2] != link_digest):
                    raise ValueError("Idempotency key reused with different content")
                result = json.loads(old[3])
            elif action == "content.unpublish":
                result = self._execute_retraction(db, key, content_digest,
                                                   compensates, link_digest)
            else:
                result = self._execute_forward(db, key, content_digest, document)
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
        if self.timeout_after_commit:
            raise TimeoutError("Response lost after the publisher committed")
        return result

    @staticmethod
    def _valid_link(compensates) -> bool:
        return (isinstance(compensates, dict)
                and set(compensates) == {"operation_id", "external_id", "capability"}
                and all(isinstance(compensates[field], str) and compensates[field]
                        for field in compensates))

    def _execute_forward(self, db, key, content_digest, document):
        existing = db.execute(
            "SELECT external_id FROM publications WHERE document_id=? AND digest=?",
            (document["id"], content_digest)).fetchone()
        if existing:
            external_id = existing[0]
        else:
            external_id = "PUB-" + uuid.uuid4().hex[:12]
            db.execute("INSERT INTO publications VALUES (?,?,?,?)",
                       (document["id"], content_digest, external_id,
                        canonical(document)))
        result = {"status": "accepted", "external_id": external_id,
                  "digest": content_digest}
        # The single mechanical column-naming edit (D87 as amended): forward
        # rows keep NULL action/link_digest — byte-identical store state for
        # identical inputs, pre- and post-migration.
        db.execute("INSERT INTO receipts (key,digest,result) VALUES (?,?,?)",
                   (key, content_digest, canonical(result)))
        return result

    def _execute_retraction(self, db, key, content_digest, compensates, link_digest):
        """One retraction effect per original; receipts stay the call surface.

        Known absence of the original is an authoritative stored business
        rejection (ORIGINAL_ABSENT); only a genuine store failure is left
        uncertain (the caller sees the exception, never a fabricated verdict).
        """
        original = compensates["external_id"]
        row = db.execute("SELECT external_id FROM retractions WHERE original_external_id=?",
                         (original,)).fetchone()
        if row is not None:
            # Effect exists (possibly created under a different key in a shared
            # store): record a requesting-digest alias receipt reusing the RTR id.
            result = {"status": "accepted", "external_id": row[0],
                      "digest": content_digest, "original_external_id": original}
        elif self._forward_receipt_exists(db, original):
            external_id = "RTR-" + uuid.uuid4().hex[:12]
            db.execute("INSERT INTO retractions VALUES (?,?,?,?)",
                       (original, external_id, key, content_digest))
            result = {"status": "accepted", "external_id": external_id,
                      "digest": content_digest, "original_external_id": original}
        else:
            result = {"status": "rejected", "external_id": "RTR-" + uuid.uuid4().hex[:12],
                      "digest": content_digest, "original_external_id": original,
                      "reason": "ORIGINAL_ABSENT"}
        db.execute("INSERT INTO receipts (key,digest,result,action,link_digest) "
                   "VALUES (?,?,?,?,?)",
                   (key, content_digest, canonical(result), "content.unpublish",
                    link_digest))
        return result

    @staticmethod
    def _forward_receipt_exists(db, external_id) -> bool:
        """Original existence = an accepted FORWARD receipt, not publications-only.

        The publications short-circuit covers the common case; the receipts
        scan is authoritative and keeps deciding presence when either side
        lost rows (store repair stays honest in both directions).
        """
        if db.execute("SELECT 1 FROM publications WHERE external_id=? LIMIT 1",
                      (external_id,)).fetchone():
            return True
        for action, stored in db.execute("SELECT action,result FROM receipts"):
            result = json.loads(stored)
            if (result.get("status") == "accepted"
                    and (action is None or action == "content.publish")
                    and result.get("external_id") == external_id):
                return True
        return False

    def lookup(self, key: str):
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT result FROM receipts WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None
        finally:
            db.close()

    def published_count(self) -> int:
        """Publication rows: effects are never counted away by retraction."""
        db = sqlite3.connect(self.path)
        try:
            return db.execute("SELECT COUNT(*) FROM publications").fetchone()[0]
        finally:
            db.close()

    def retracted_count(self) -> int:
        """Retraction effect rows: exactly one per retracted original."""
        db = sqlite3.connect(self.path)
        try:
            return db.execute("SELECT COUNT(*) FROM retractions").fetchone()[0]
        finally:
            db.close()
