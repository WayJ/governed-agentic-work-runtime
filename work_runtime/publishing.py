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
        if action != "content.publish":
            # The paired retraction action widens this guard when its execution
            # path lands (Task 3 of the S14 plan); declaring it in the contract
            # first would hold at the runtime preflight, never execute blind.
            raise ValueError("Unknown action: " + str(action))
        if compensates is not None:
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
                        or old[2] is not None):
                    raise ValueError("Idempotency key reused with different content")
                result = json.loads(old[3])
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
