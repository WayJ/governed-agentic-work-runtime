"""Support-ticket family: policy and its fake GitHub-issue-shaped tracker.

The third business family on the shared Runtime (S15). The policy carries
severity/category admission with an unknown-blocking rule (an unresolved
severity or category can never pass as within-policy), an urgent-SLA
conditional obligation, and a ticket-reference business key. The tracker
adapter models an external issue tracker. Source names (`support-desk`,
`tracker`) are local trust configuration, not authentication — see
docs/adapter-contract.md and docs/runtime-boundaries.md.
"""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import List

from .adapter_contract import AdapterContract
from .policy import canonical, digest

SEVERITIES = ("critical", "high", "normal")
CATEGORIES = ("billing", "technical", "account")


class SupportPolicy:
    """Support-ticket policy: severity/category admission and urgent SLA.

    A ``None`` severity or category means triage is unresolved: the rule's
    applicability is unknown, which blocks admission — unknown never passes
    as within-policy (RFC-001 P3/R3). ``SupportPolicyV2`` tightens the
    urgent-SLA budget without touching the business key.
    """

    id = "support-ticket"
    version = "demo-1"
    goal = "ticket.dispatched"
    evidence_sources = {
        "sla": "support-desk",
        "accepted": "tracker",
    }
    # No compensation_capabilities: this family has no compensation (D94).

    def validate_document(self, document: dict) -> None:
        if set(document) != {"id", "summary", "severity", "category"}:
            raise ValueError("Document requires id, summary, severity and "
                             "category")
        for name in ("id", "summary"):
            if not isinstance(document[name], str) or not document[name]:
                raise ValueError("Document %s must be a nonempty string" % name)
        for name, vocabulary in (("severity", SEVERITIES), ("category", CATEGORIES)):
            value = document[name]
            if value is not None and value not in vocabulary:
                raise ValueError("Document %s must be one of %s or null (unknown)"
                                 % (name, ", ".join(vocabulary)))

    def validate_evidence(self, work: dict, candidate: dict) -> bool:
        data = candidate["data"]
        kind = candidate["kind"]
        if kind == "sla":
            return (set(data) == {"digest", "response_target_minutes"}
                    and isinstance(data["digest"], str)
                    and type(data["response_target_minutes"]) is int
                    and data["response_target_minutes"] > 0)
        if kind == "accepted":
            # Reserved shape adopted from Runtime-written receipts (design M5).
            return (set(data) == {"digest", "external_id"}
                    and isinstance(data["digest"], str)
                    and isinstance(data["external_id"], str)
                    and bool(data["external_id"]))
        return False

    # Urgent-SLA response budgets (minutes) by severity. SupportPolicyV2
    # tightens the critical budget; the ticket-reference business key is
    # untouched by either version.
    urgent_sla_budget_minutes = {"critical": 60, "high": 240}

    def evaluate(self, work: dict, evidence: List[dict]) -> List[dict]:
        document = work["document"]
        current = work["document_digest"]
        proofs = [e for e in evidence if e["status"] == "verified"]
        # The document id IS the external ticket reference (the frozen
        # command surface keys object identity on document id), so the rule
        # subject is the ticket reference.
        subject = document["id"]
        result = []

        def add(rule: str, applicable: str, satisfied: bool,
                explanation: str) -> None:
            result.append({"id": rule + ":" + subject, "rule_id": rule,
                           "subject": subject, "applicability": applicable,
                           "fulfillment": "satisfied" if satisfied else "pending",
                           "explanation": explanation})

        add("T01",
            "unknown" if document["severity"] is None else "applicable",
            document["severity"] is not None,
            "Triage must resolve the severity; an unresolved severity never "
            "passes as within-policy")
        add("T02",
            "unknown" if document["category"] is None else "applicable",
            document["category"] is not None,
            "Triage must resolve the category; an unresolved category never "
            "passes as within-policy")
        severity = document["severity"]
        if severity is None:
            sla_applicable = "unknown"
        elif severity in self.urgent_sla_budget_minutes:
            sla_applicable = "applicable"
        else:
            sla_applicable = "not_applicable"
        sla_satisfied = False
        if sla_applicable == "applicable":
            budget = self.urgent_sla_budget_minutes[severity]
            sla_satisfied = any(
                e["kind"] == "sla" and e["source"] == self.evidence_sources["sla"]
                and e["data"].get("digest") == current
                and type(e["data"].get("response_target_minutes")) is int
                and 0 < e["data"]["response_target_minutes"] <= budget
                for e in proofs)
        add("T03", sla_applicable, sla_satisfied,
            "An urgent severity must carry a support-desk SLA commitment within "
            "the severity budget; while the severity is unknown, SLA "
            "applicability cannot be decided")
        accepted = any(
            e["kind"] == "accepted" and e["source"] == self.evidence_sources["accepted"]
            and e["data"].get("digest") == current
            and bool(e["data"].get("external_id")) for e in proofs)
        add("T04", "applicable", accepted,
            "The tracker must have accepted the current ticket content")
        return result

    def action_blockers(self, capability: str, requirements: List[dict]) -> List[dict]:
        if capability != "ticket.dispatch":
            return [{"code": "CAPABILITY_UNSUPPORTED", "capability": capability}]
        return [r for r in requirements if r["rule_id"] != "T04" and
                (r["applicability"] in ("unknown", "conflict")
                 or (r["applicability"] == "applicable"
                     and r["fulfillment"] != "satisfied"))]

    def operation_key(self, capability: str, work: dict) -> str:
        # The ticket-reference business key: no document digest, no policy
        # version — the key is the external reference and stays stable across
        # policy versions of this family (distinct from the digest-bound
        # expense/publishing shapes). Changed content under a used reference
        # is a conflict for the runtime to surface, never a second operation.
        return digest([self.id, capability, work["document"]["id"]])


class SupportPolicyV2(SupportPolicy):
    """Same family, tighter urgent-SLA budget for critical tickets (demo-2).

    The migration target proves the business key survives policy versions:
    ``operation_key`` is inherited untouched.
    """

    version = "demo-2"
    urgent_sla_budget_minutes = {"critical": 30, "high": 240}


class FakeIssueTracker:
    """A separate SQLite store models an external GitHub-issue-shaped tracker.

    Survives worker crashes like FakeOA/FakePublisher. One issue per ticket
    reference: the reference travels in the written object and in every
    receipt, identical content under another idempotency key reuses the same
    issue number (an alias receipt, no second issue), and changed content
    under a used reference is a queryable business rejection. This family has
    no compensation, so a link-carrying call is invalid.
    """

    # Declared assertions for trusted local configuration, not a remote
    # guarantee. supports_action_context opts into the explicit forward
    # action; compensates is always None for this family.
    contract = AdapterContract(
        actions=("ticket.dispatch",),
        idempotency_scope="adapter-store:key",
        retention="lifetime-of-store",
        lookup_consistency="authoritative-by-key",
        uniqueness=("ticket.reference",),
        supports_action_context=True)

    def __init__(self, path: str, timeout_after_commit: bool = False):
        self.path = str(path)
        self.timeout_after_commit = timeout_after_commit
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15)
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS receipts (
                key TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS issues (
                ticket_reference TEXT PRIMARY KEY, issue_number INTEGER NOT NULL UNIQUE,
                digest TEXT NOT NULL, document TEXT NOT NULL)""")
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _receipt(content_digest, ticket_reference, issue_number, *, status="accepted",
                 reason=None):
        result = {"status": status, "external_id": "#%d" % issue_number,
                  "digest": content_digest, "ticket_reference": ticket_reference,
                  "issue_number": issue_number, "issue_state": "open"}
        if reason is not None:
            result["reason"] = reason
        return result

    def execute(self, key: str, document: dict, content_digest: str, *,
                action=None, compensates=None) -> dict:
        if digest(document) != content_digest:
            raise ValueError("Content digest does not match document")
        if action is None:
            # Tracker-side normalization for its own legacy direct callers;
            # not a protocol rule (legacy adapters are never called with kwargs).
            action = "ticket.dispatch"
        if action != "ticket.dispatch":
            raise ValueError("Unknown action: " + str(action))
        if compensates is not None:
            raise ValueError("ticket.dispatch has no compensation; a "
                             "compensates link is invalid")
        reference = document["id"]
        db = sqlite3.connect(self.path, timeout=15)
        try:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT digest,result FROM receipts WHERE key=?",
                             (key,)).fetchone()
            if old:
                if old[0] != content_digest:
                    raise ValueError("Idempotency key reused with different content")
                result = json.loads(old[1])
            else:
                row = db.execute(
                    "SELECT issue_number,digest FROM issues WHERE ticket_reference=?",
                    (reference,)).fetchone()
                if row is None:
                    number = db.execute(
                        "SELECT COALESCE(MAX(issue_number), 0) + 1 FROM issues"
                    ).fetchone()[0]
                    db.execute("INSERT INTO issues VALUES (?,?,?,?)",
                               (reference, number, content_digest,
                                canonical(document)))
                    result = self._receipt(content_digest, reference, number)
                elif row[1] == content_digest:
                    # Identical content under a fresh key: reuse the issue
                    # (alias receipt, no second external effect).
                    result = self._receipt(content_digest, reference, row[0])
                else:
                    # Known conflict, authoritative and queryable — never a
                    # second issue and never a fabricated acceptance.
                    result = self._receipt(content_digest, reference, row[0],
                                           status="rejected",
                                           reason="TICKET_REFERENCE_CONTENT_CONFLICT")
                db.execute("INSERT INTO receipts (key,digest,result) VALUES (?,?,?)",
                           (key, content_digest, canonical(result)))
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
        if self.timeout_after_commit:
            raise TimeoutError("Response lost after the tracker committed")
        return result

    def lookup(self, key: str):
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT result FROM receipts WHERE key=?",
                             (key,)).fetchone()
            return json.loads(row[0]) if row else None
        finally:
            db.close()

    def issue_count(self) -> int:
        """Issue rows: exactly one per dispatched ticket reference."""
        db = sqlite3.connect(self.path)
        try:
            return db.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
        finally:
            db.close()

    def issue_for_reference(self, ticket_reference: str):
        """The written issue object for a reference, or None."""
        db = sqlite3.connect(self.path)
        try:
            row = db.execute(
                "SELECT issue_number,digest,document FROM issues "
                "WHERE ticket_reference=?", (ticket_reference,)).fetchone()
            if row is None:
                return None
            return {"issue_number": row[0], "digest": row[1],
                    "document": json.loads(row[2])}
        finally:
            db.close()


def support_grants():
    """Demo grants for the support-ticket family: the owning agent holds the
    dispatch capability, the support desk writes SLA evidence, and the lead
    holds the admin intervention grant used for policy migration —
    trusted-local configuration, not authentication."""
    return {"agent": {"work.manage", "ticket.dispatch"},
            "support-desk": {"evidence.write"},
            "lead": {"work.intervene"}}

_PACKAGE_PARENT = str(Path(__file__).resolve().parent.parent)


def crash_worker_script(runtime_path, tracker_path, operation_id):
    """Inline child source: a grants-carrying worker that dispatches the
    prepared ticket through the public API and dies (exit 73) right after
    the tracker accepted the write — before the outcome is recorded.
    ``sys.path`` is seeded with this package's parent so the child imports
    the exact same package copy in a checkout and in an install."""
    return (
        "import os, sys\n"
        "sys.path.insert(0, {parent!r})\n"
        "from work_runtime.support import FakeIssueTracker, SupportPolicy, "
        "support_grants\n"
        "from work_runtime.runtime import Runtime\n"
        "runtime = Runtime({runtime!r}, SupportPolicy(), support_grants())\n"
        "runtime.dispatch({operation!r}, FakeIssueTracker({tracker!r}),"
        " fault=lambda: os._exit(73))\n"
    ).format(parent=_PACKAGE_PARENT, runtime=str(runtime_path),
             operation=operation_id, tracker=str(tracker_path))


def run_crash_worker(runtime_path, tracker_path, operation_id):
    """Run the crash worker as a real child process; returns its exit status."""
    return subprocess.run([sys.executable, "-c",
                           crash_worker_script(runtime_path, tracker_path,
                                               operation_id)],
                          check=False)
