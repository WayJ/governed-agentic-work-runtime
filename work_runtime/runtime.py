"""SQLite-backed command, evidence and operation lifecycle.

Only trusted local application code instantiates this runtime. Principal names
are not authentication. Do not expose these methods as an unauthenticated API.
"""

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Dict, Optional, Protocol

from .adapter_contract import receipt_is_valid, valid_contract
from .policy import Policy, canonical, digest


class CommandError(ValueError):
    """Malformed input or local API misuse (not a persisted business rejection)."""


class Adapter(Protocol):
    def execute(self, key: str, document: dict, content_digest: str) -> dict: ...
    def lookup(self, key: str) -> Optional[dict]: ...


_MISSING_CONTRACT = object()


def _declared_contract(adapter: Adapter) -> Optional[object]:
    """Only an absent descriptor keeps legacy adapters trusted.

    A descriptor that is present but None or invalid is malformed, never
    silently legacy.
    """
    descriptor = getattr(adapter, "contract", _MISSING_CONTRACT)
    if descriptor is _MISSING_CONTRACT:
        return None
    if not valid_contract(descriptor):
        raise CommandError("Adapter contract descriptor is malformed: "
                           + type(descriptor).__name__)
    return descriptor


_POLICY_METHODS = ("validate_document", "evaluate", "action_blockers",
                   "operation_key", "validate_evidence")


def _validated_registry(policy: Policy, policies: Optional[Dict[str, Policy]]) -> Dict[str, Policy]:
    """Validate an explicitly loaded, same-family policy registry.

    Returns a copied mapping that always contains the default version bound
    to the default object. Malformed input raises before any filesystem or
    database write; definitions themselves stay trusted-local.
    """
    if policies is None:
        return {policy.version: policy}
    if not isinstance(policies, dict):
        raise CommandError("policies must be a dict of version to Policy")
    registry: Dict[str, Policy] = {}
    for version, candidate in policies.items():
        if not isinstance(version, str) or not version:
            raise CommandError("Registry keys must be nonempty version strings")
        for attribute in ("id", "version", "goal"):
            value = getattr(candidate, attribute, None)
            if not isinstance(value, str) or not value:
                raise CommandError("Registry policies require a nonempty " + attribute)
        if not isinstance(getattr(candidate, "evidence_sources", None), dict):
            raise CommandError("Registry policies require an evidence_sources dict")
        for method in _POLICY_METHODS:
            if not callable(getattr(candidate, method, None)):
                raise CommandError("Registry policies require a callable " + method)
        if candidate.version != version:
            raise CommandError("Registry key must equal the policy version")
        if (candidate.id, candidate.goal) != (policy.id, policy.goal):
            raise CommandError("Registry policies must share the default policy family and goal")
        registry[version] = candidate
    if registry.get(policy.version, policy) is not policy:
        raise CommandError("The default version must map to the default policy object")
    registry[policy.version] = policy
    return registry


class Runtime:
    def __init__(self, path: str, policy: Policy, grants: Dict[str, set],
                 *, policies: Optional[Dict[str, Policy]] = None):
        self.policies = _validated_registry(policy, policies)
        self.path, self.policy, self.grants = str(path), policy, grants
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS works (
                    id TEXT PRIMARY KEY, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS commands (
                    actor TEXT, id TEXT, fingerprint TEXT NOT NULL,
                    work_id TEXT NOT NULL, receipt TEXT NOT NULL,
                    PRIMARY KEY(actor, id));
                CREATE TABLE IF NOT EXISTS evidence (
                    source TEXT, event_id TEXT, work_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(source, event_id));
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY, business_key TEXT UNIQUE NOT NULL,
                    work_id TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    work_id TEXT NOT NULL, version INTEGER NOT NULL,
                    type TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            row = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
            if row and row[0] != "1":
                raise CommandError("Unsupported database schema version")
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('schema_version','1')")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def _connection(self):
        db = self._connect()
        try:
            yield db
            db.commit()
        finally:
            db.close()

    @contextmanager
    def _transaction(self):
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _work(self, db, work_id):
        row = db.execute("SELECT state FROM works WHERE id=?", (work_id,)).fetchone()
        if not row:
            raise CommandError("Unknown work: " + work_id)
        work = json.loads(row[0])
        self._policy_for(work)  # Fails closed on a pinned version that is not loaded.
        return work

    def _policy_for(self, work: dict) -> Policy:
        """Every Work resolves its own pinned policy; migration is never implicit."""
        contract = work.get("contract")
        if not contract:
            return self.policy
        if contract["policy_version"] == self.policy.version:
            # The default version tracks the live default slot, so trusted-local
            # reconfiguration of the default keeps its fail-closed semantics.
            if (self.policy.id, self.policy.goal) != (contract["policy_id"], contract["goal"]):
                raise CommandError("Load the policy version bound to this Work; migration is not implicit")
            return self.policy
        policy = self.policies.get(contract["policy_version"])
        if policy is None or (policy.id, policy.goal) != (contract["policy_id"], contract["goal"]):
            raise CommandError("Load the policy version bound to this Work; migration is not implicit")
        return policy

    def _proofs(self, db, work_id):
        return [json.loads(r[0]) for r in db.execute(
            "SELECT body FROM evidence WHERE work_id=?", (work_id,))]

    def _evaluate(self, db, work):
        policy = self._policy_for(work)
        work["requirements"] = policy.evaluate(work, self._proofs(db, work["id"]))
        if not work["contract"]:
            work["status"] = "establishing"
            return
        if work["status"] != "closed":
            requirements = {r["id"]: r for r in work["requirements"]}
            for wait in work["waits"]:
                requirement = requirements.get(wait["requirement_id"])
                if requirement and (requirement["fulfillment"] == "satisfied"
                                    or requirement["applicability"] == "not_applicable"):
                    wait["status"] = "triggered"
            if work["status"] != "needs_attention":
                work["status"] = "waiting" if any(
                    w["status"] == "waiting" for w in work["waits"]) else "active"

    def _save(self, db, work, event, details=None):
        work["state_version"] += 1
        self._evaluate(db, work)
        db.execute("INSERT OR REPLACE INTO works VALUES (?,?)",
                   (work["id"], canonical(work)))
        db.execute("INSERT INTO events(work_id,version,type,body) VALUES (?,?,?,?)",
                   (work["id"], work["state_version"], event, canonical(details or {})))

    def _get_op(self, db, operation_id):
        row = db.execute("SELECT body FROM operations WHERE id=?", (operation_id,)).fetchone()
        if not row:
            raise CommandError("Unknown operation")
        return json.loads(row[0])

    def _save_op(self, db, operation):
        db.execute("INSERT OR REPLACE INTO operations VALUES (?,?,?,?)",
                   (operation["id"], operation["business_key"],
                    operation["work_id"], canonical(operation)))

    def get_work(self, work_id: str) -> dict:
        with self._connection() as db:
            return self._work(db, work_id)

    def get_operation(self, operation_id: str) -> dict:
        with self._connection() as db:
            return self._get_op(db, operation_id)

    def get_command(self, actor: str, command_id: str) -> Optional[dict]:
        with self._connection() as db:
            row = db.execute("SELECT receipt FROM commands WHERE actor=? AND id=?",
                             (actor, command_id)).fetchone()
            return json.loads(row[0]) if row else None

    def events(self, work_id: str, after: int = 0) -> list:
        with self._connection() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM events WHERE work_id=? AND seq>? ORDER BY seq",
                (work_id, after))]

    def command(self, actor: str, command_id: str, work_id: str, kind: str,
                payload: Optional[dict] = None, expected_version: Optional[int] = None) -> dict:
        payload = payload or {}
        if not all(isinstance(v, str) and v for v in (actor, command_id, work_id, kind)):
            raise CommandError("Command identity fields must be nonempty strings")
        if not isinstance(payload, dict):
            raise CommandError("payload must be an object")
        if kind != "create_work" and kind != "record_evidence" and type(expected_version) is not int:
            raise CommandError("A state version is required")
        request_hash = digest([work_id, kind, payload, expected_version])
        with self._transaction() as db:
            if actor not in self.grants:
                return {"decision": "rejected", "code": "AUTHORITY_DENIED"}
            old = db.execute("SELECT fingerprint,receipt FROM commands WHERE actor=? AND id=?",
                             (actor, command_id)).fetchone()
            if old:
                if old[0] != request_hash:
                    return {"decision": "rejected", "code": "COMMAND_ID_REUSED"}
                return json.loads(old[1])

            if kind == "create_work":
                receipt = self._create(db, actor, work_id, payload)
            else:
                work = self._work(db, work_id)
                version = work["state_version"]
                if kind != "record_evidence" and expected_version != version:
                    receipt = self._reject("STATE_VERSION_CONFLICT", version)
                elif kind == "record_evidence":
                    receipt = self._receive(db, actor, work, payload)
                elif work["status"] == "closed":
                    receipt = self._reject("WORK_NOT_ACTIONABLE", version)
                else:
                    receipt = self._apply(db, actor, work, kind, payload)
            receipt = {"command_id": command_id, **receipt}
            db.execute("INSERT INTO commands VALUES (?,?,?,?,?)",
                       (actor, command_id, request_hash, work_id, canonical(receipt)))
            return receipt

    @staticmethod
    def _reject(code, version, blockers=None):
        return {"decision": "rejected", "code": code,
                "observed_state_version": version, "blockers": blockers or []}

    @staticmethod
    def _accepted(work, **extra):
        return {"decision": "accepted", "result_state_version": work["state_version"], **extra}

    def _create(self, db, actor, work_id, payload):
        if "work.manage" not in self.grants[actor]:
            return self._reject("AUTHORITY_DENIED", 0)
        if db.execute("SELECT 1 FROM works WHERE id=?", (work_id,)).fetchone():
            return self._reject("WORK_ALREADY_EXISTS", 0)
        self.policy.validate_document(payload["document"])
        work = {"id": work_id, "state_version": 0, "status": "establishing",
                "outcome": None, "contract": None, "plan_revision": 0,
                "owner": actor,
                "plan": {}, "document": payload["document"], "document_revision": 1,
                "document_digest": digest(payload["document"]), "waits": [],
                "requirements": []}
        self._save(db, work, "WorkCreated")
        work["status"] = "establishing"
        db.execute("UPDATE works SET state=? WHERE id=?", (canonical(work), work_id))
        return self._accepted(work)

    def _apply(self, db, actor, work, kind, payload):
        version = work["state_version"]
        if kind == "propose_action":
            return self._propose(db, actor, work, payload)
        if kind == "request_cancel":
            return self._request_cancel(db, actor, work, payload, version)
        if "work.manage" not in self.grants[actor]:
            return self._reject("AUTHORITY_DENIED", version)
        if work.get("cancellation"):
            return self._reject("CANCELLATION_ACTIVE", version)
        if kind == "bind_contract":
            if work["contract"]:
                return self._reject("CONTRACT_ALREADY_BOUND", version)
            policy = self._policy_for(work)
            if payload != {"policy_id": policy.id, "policy_version": policy.version,
                           "goal": policy.goal}:
                return self._reject("CONTRACT_UNSUPPORTED", version)
            work["contract"] = {**payload, "revision": 1}
            work["status"] = "active"
            self._save(db, work, "ContractBound", payload)
        elif not work["contract"]:
            return self._reject("CONTRACT_NOT_ACTIVE", version)
        elif kind == "revise_plan":
            if set(payload) != {"steps", "open_requirements", "replan_when"} or not all(
                    isinstance(payload[k], list) for k in payload):
                raise CommandError("Plan requires steps, open_requirements and replan_when lists")
            work["plan_revision"] += 1
            work["plan"] = payload
            self._cancel_prepared(db, work["id"])
            self._save(db, work, "PlanRevised", {"revision": work["plan_revision"]})
        elif kind == "revise_document":
            # Example-specific object command; not a general Contract mutation.
            self._policy_for(work).validate_document(payload["document"])
            if payload["document"]["id"] != work["document"]["id"]:
                return self._reject("DOCUMENT_ID_MISMATCH", version)
            work["document"] = payload["document"]
            work["document_revision"] += 1
            work["document_digest"] = digest(payload["document"])
            work["waits"] = [{**w, "status": "cancelled"} for w in work["waits"]]
            self._cancel_prepared(db, work["id"])
            self._save(db, work, "DocumentRevised")
        elif kind == "register_wait":
            if not {"requirement_id", "deadline", "owner"} <= set(payload):
                raise CommandError("Wait requires requirement_id, deadline and owner")
            if type(payload["deadline"]) is not int or not isinstance(payload["owner"], str):
                raise CommandError("Wait deadline must be epoch seconds and owner a string")
            if payload["requirement_id"] not in {r["id"] for r in work["requirements"]}:
                return self._reject("REQUIREMENT_UNKNOWN", version)
            work["waits"].append({**payload, "id": uuid.uuid4().hex, "status": "waiting"})
            self._save(db, work, "WaitRegistered")
        elif kind == "request_completion":
            blockers = [r for r in work["requirements"] if
                        r["applicability"] in ("unknown", "conflict") or
                        (r["applicability"] == "applicable" and r["fulfillment"] != "satisfied")]
            unresolved = [json.loads(r[0])["id"] for r in db.execute(
                "SELECT body FROM operations WHERE work_id=?", (work["id"],))
                if json.loads(r[0])["status"] not in ("confirmed_succeeded", "confirmed_failed")
                and json.loads(r[0])["dispatch_state"] != "cancelled"]
            if unresolved:
                return self._reject("OUTCOME_UNRESOLVED", version, unresolved)
            if blockers:
                return self._reject("REQUIREMENT_UNSATISFIED", version, blockers)
            work["status"], work["outcome"] = "closed", "succeeded"
            work["completion"] = {"contract": work["contract"],
                                  "document_digest": work["document_digest"],
                                  "evidence": [e["id"] for e in self._proofs(db, work["id"])
                                               if e["status"] == "verified"]}
            self._save(db, work, "WorkCompleted", work["completion"])
        else:
            return self._reject("COMMAND_UNSUPPORTED", version)
        return self._accepted(work)

    def _cancel_prepared(self, db, work_id, reason="STALE_INTENT"):
        cancelled = []
        for row in db.execute("SELECT body FROM operations WHERE work_id=?", (work_id,)).fetchall():
            op = json.loads(row[0])
            if op["status"] == "prepared":
                op["dispatch_state"] = "cancelled"
                op["reason"] = reason
                self._save_op(db, op)
                cancelled.append(op["id"])
        return cancelled

    def _is_admin(self, actor: str) -> bool:
        return "work.intervene" in self.grants.get(actor, set())

    def _intervener(self, actor: str, work: dict) -> bool:
        """Interventions: work.intervene administrator or the current owner."""
        if self._is_admin(actor):
            return True
        owner = work.get("owner")
        return (owner is not None and actor == owner
                and "work.manage" in self.grants.get(actor, set()))

    def _request_cancel(self, db, actor, work, payload, version):
        if (set(payload) != {"reason"} or not isinstance(payload["reason"], str)
                or not payload["reason"]):
            raise CommandError("request_cancel requires exactly one nonempty reason string")
        if not self._intervener(actor, work):
            return self._reject("AUTHORITY_DENIED", version)
        if work.get("cancellation"):
            return self._reject("CANCELLATION_ALREADY_REQUESTED", version)
        work["cancellation"] = {"requested_by": actor, "reason": payload["reason"]}
        cancelled_waits = []
        for wait in work["waits"]:
            if wait["status"] in ("waiting", "triggered"):
                wait["status"] = "cancelled"
                cancelled_waits.append(wait["id"])
        cancelled_operations = self._cancel_prepared(db, work["id"], reason="WORK_CANCELLED")
        self._save(db, work, "CancellationRequested", {
            "actor": actor, "reason": payload["reason"],
            "cancelled_operations": cancelled_operations,
            "cancelled_waits": cancelled_waits})
        return self._accepted(work)

    def _propose(self, db, actor, work, payload):
        version = work["state_version"]
        capability = payload.get("capability")
        if capability not in self.grants[actor]:
            return self._reject("AUTHORITY_DENIED", version)
        if work.get("cancellation"):
            return self._reject("CANCELLATION_ACTIVE", version)
        if not work["contract"]:
            return self._reject("CONTRACT_NOT_ACTIVE", version)
        if payload.get("contract_revision") != work["contract"]["revision"]:
            return self._reject("CONTRACT_REVISION_MISMATCH", version)
        if payload.get("plan_revision") != work["plan_revision"]:
            return self._reject("PLAN_REVISION_MISMATCH", version)
        if payload.get("document_digest") != work["document_digest"]:
            return self._reject("EVIDENCE_SCOPE_MISMATCH", version)
        policy = self._policy_for(work)
        blockers = policy.action_blockers(capability, work["requirements"])
        if blockers:
            code = "APPLICABILITY_UNRESOLVED" if any(
                r.get("applicability") in ("unknown", "conflict") for r in blockers
            ) else "REQUIREMENT_UNSATISFIED"
            return self._reject(code, version, blockers)
        for row in db.execute("SELECT body FROM operations WHERE work_id=?", (work["id"],)):
            pending = json.loads(row[0])
            if (pending["status"] in ("dispatched", "outcome_unknown")
                    and pending["document_digest"] != work["document_digest"]):
                return self._reject("OUTCOME_UNRESOLVED", version, [pending["id"]])
        key = policy.operation_key(capability, work)
        old = db.execute("SELECT body FROM operations WHERE business_key=?", (key,)).fetchone()
        if old:
            operation = json.loads(old[0])
            if operation["document_digest"] != work["document_digest"] or operation["work_id"] != work["id"]:
                return self._reject("OPERATION_CONTENT_CONFLICT", version)
            if operation["status"] == "prepared" and operation["dispatch_state"] in ("cancelled", "held"):
                operation.update(actor=actor, plan_revision=work["plan_revision"], dispatch_state="ready")
                operation.pop("reason", None)
                self._save_op(db, operation)
                self._save(db, work, "OperationReadmitted", {"operation_id": operation["id"]})
            return self._accepted(work, operation_id=operation["id"],
                                  operation_status_at_decision=operation["status"])
        operation = {"id": uuid.uuid4().hex, "business_key": key, "work_id": work["id"],
                     "actor": actor, "capability": capability, "status": "prepared",
                     "dispatch_state": "ready", "attempts": [],
                     "document": work["document"], "document_digest": work["document_digest"],
                     "plan_revision": work["plan_revision"], "contract_revision": 1}
        self._save_op(db, operation)
        self._save(db, work, "OperationPrepared", {"operation_id": operation["id"]})
        return self._accepted(work, operation_id=operation["id"], operation_status_at_decision="prepared")

    def _receive(self, db, actor, work, payload):
        required = {"event_id", "kind", "data"}
        if set(payload) != required or not isinstance(payload["data"], dict):
            raise CommandError("Evidence requires event_id, kind and data")
        kind, event_id = payload["kind"], payload["event_id"]
        if not isinstance(event_id, str) or not event_id:
            raise CommandError("Source event id is required")
        if (self._policy_for(work).evidence_sources.get(kind) != actor
                or "evidence.write" not in self.grants[actor]):
            return self._reject("AUTHORITY_DENIED", work["state_version"])
        fingerprint = digest([work["id"], payload])
        old = db.execute("SELECT fingerprint,body FROM evidence WHERE source=? AND event_id=?",
                         (actor, event_id)).fetchone()
        if old:
            if old[0] != fingerprint:
                return self._reject("SOURCE_EVENT_CONFLICT", work["state_version"])
            return self._accepted(work, evidence_id=json.loads(old[1])["id"])
        candidate = {"id": uuid.uuid4().hex, "source": actor, "event_id": event_id,
                     "kind": kind, "data": payload["data"], "status": "pending_verification"}
        db.execute("INSERT INTO evidence VALUES (?,?,?,?,?)",
                   (actor, event_id, work["id"], fingerprint, canonical(candidate)))
        return self._accepted(work, evidence_id=candidate["id"],
                              evidence_status="pending_verification")

    def verify_pending(self, work_id: str, fault: Optional[Callable] = None) -> int:
        """Trusted verifier entry point; candidate validation and evaluation are atomic."""
        with self._transaction() as db:
            work = self._work(db, work_id)
            policy = self._policy_for(work)
            count = 0
            for candidate in self._proofs(db, work_id):
                if candidate["status"] != "pending_verification":
                    continue
                candidate["status"] = "verified" if policy.validate_evidence(work, candidate) else "invalid"
                db.execute("UPDATE evidence SET body=? WHERE source=? AND event_id=?",
                           (canonical(candidate), candidate["source"], candidate["event_id"]))
                count += 1
            if count:
                if fault:
                    fault()  # Raising or process death rolls back evidence adoption.
                self._save(db, work, "EvidenceEvaluated", {"count": count})
            return count

    def expire_waits(self, work_id: str, now: int) -> int:
        with self._transaction() as db:
            work = self._work(db, work_id)
            if work["status"] == "closed":
                return 0
            count = 0
            for wait in work["waits"]:
                if wait["status"] == "waiting" and wait["deadline"] <= now:
                    wait["status"] = "expired"
                    count += 1
            if count:
                work["status"] = "needs_attention"
                self._save(db, work, "WaitExpired", {"count": count})
            return count

    def _accepted_source(self, work: dict) -> str:
        source = self._policy_for(work).evidence_sources.get("accepted")
        if not isinstance(source, str) or not source:
            raise CommandError(
                "Policy must configure a nonempty accepted evidence source for external effects")
        return source

    def dispatch(self, operation_id: str, adapter: Adapter, fault: Optional[Callable] = None) -> dict:
        """Single coordinator only. Unknown outcomes must be reconciled, never dispatched again."""
        with self._transaction() as db:
            op = self._get_op(db, operation_id)
            if op["status"] != "prepared" or op["dispatch_state"] == "cancelled":
                return op
            work = self._work(db, op["work_id"])
            policy = self._policy_for(work)
            if work.get("cancellation") and op["dispatch_state"] != "cancelled":
                # Belt and braces: request_cancel already cancelled every
                # prepared intent; nothing new may ever leave under cancel.
                op["dispatch_state"], op["reason"] = "cancelled", "WORK_CANCELLED"
                self._save_op(db, op)
                self._save(db, work, "DispatchCancelled", {"operation_id": op["id"]})
                return op
            if (work["status"] == "closed" or op["document_digest"] != work["document_digest"]
                    or op["plan_revision"] != work["plan_revision"]):
                op["dispatch_state"] = "cancelled"
                op["reason"] = "STALE_INTENT"
                self._save_op(db, op)
                self._save(db, work, "DispatchCancelled", {"operation_id": op["id"]})
                return op
            blockers = policy.action_blockers(op["capability"], work["requirements"])
            if op["capability"] not in self.grants.get(op["actor"], set()) or blockers:
                op["dispatch_state"] = "held"
                op["reason"] = "AUTHORITY_DENIED" if not blockers else "REQUIREMENT_UNSATISFIED"
                self._save_op(db, op)
                self._save(db, work, "DispatchHeld", {"operation_id": op["id"], "reason": op["reason"]})
                return op
            self._accepted_source(work)
            contract = _declared_contract(adapter)
            if contract is not None and op["capability"] not in contract.actions:
                op["dispatch_state"] = "held"
                op["reason"] = "ADAPTER_ACTION_UNSUPPORTED"
                self._save_op(db, op)
                self._save(db, work, "DispatchHeld",
                           {"operation_id": op["id"], "reason": op["reason"]})
                return op
            op["status"], op["dispatch_state"] = "dispatched", "in_flight"
            op["attempts"].append({"id": uuid.uuid4().hex, "status": "outcome_unknown"})
            self._save_op(db, op)
            self._save(db, work, "AttemptStarted", {"operation_id": op["id"]})
        try:
            result = adapter.execute(op["business_key"], op["document"], op["document_digest"])
        except Exception as error:
            return self._unknown(operation_id, type(error).__name__)
        if fault:
            fault()  # Injection point: external effect committed, local outcome not recorded.
        return self._resolve(operation_id, result)

    def _unknown(self, operation_id, reason):
        with self._transaction() as db:
            op = self._get_op(db, operation_id)
            if op["status"] == "outcome_unknown" and op.get("reason") == reason:
                return op  # Repeated reconciliation with the same finding writes nothing.
            op["status"], op["reason"] = "outcome_unknown", reason
            self._save_op(db, op)
            self._save(db, self._work(db, op["work_id"]), "OutcomeUnknown", {"operation_id": op["id"]})
            return op

    def reconcile(self, operation_id: str, adapter: Adapter) -> dict:
        op = self.get_operation(operation_id)
        if op["status"] not in ("dispatched", "outcome_unknown"):
            return op
        self._accepted_source(self.get_work(op["work_id"]))
        try:
            result = adapter.lookup(op["business_key"])
        except Exception as error:
            return self._unknown(operation_id, type(error).__name__)
        if result is not None:
            return self._resolve(operation_id, result)
        with self._transaction() as db:
            op = self._get_op(db, operation_id)
            work = self._work(db, op["work_id"])
            if (op["status"] == "outcome_unknown" and op.get("reason") == "NO_AUTHORITATIVE_RESULT"
                    and work["status"] == "needs_attention"):
                return op  # Idempotent recovery: the escalation is already durable.
            op["status"] = "outcome_unknown"
            op["reason"] = "NO_AUTHORITATIVE_RESULT"
            self._save_op(db, op)
            work["status"] = "needs_attention"
            self._save(db, work, "ReconciliationRequired", {"operation_id": op["id"]})
            return op

    def _resolve(self, operation_id, result):
        with self._transaction() as db:
            op = self._get_op(db, operation_id)
            if op["status"] in ("confirmed_succeeded", "confirmed_failed"):
                return op
            work = self._work(db, op["work_id"])
            if not receipt_is_valid(result, op["document_digest"]):
                if (op["status"] == "outcome_unknown" and op.get("reason") == "ADAPTER_RESULT_INVALID"
                        and work["status"] == "needs_attention"):
                    return op  # Idempotent recovery: the quarantine is already durable.
                op["status"], op["reason"] = "outcome_unknown", "ADAPTER_RESULT_INVALID"
                work["status"] = "needs_attention"
            else:
                source = self._accepted_source(work)
                op["status"] = "confirmed_succeeded" if result["status"] == "accepted" else "confirmed_failed"
                op["dispatch_state"] = "finished"
                op["external_id"] = result["external_id"]
                op["attempts"][-1]["status"] = op["status"]
                if result["status"] == "accepted":
                    proof = {"id": uuid.uuid4().hex, "source": source, "event_id": op["id"],
                             "kind": "accepted", "status": "verified",
                             "data": {"digest": op["document_digest"], "external_id": result["external_id"]}}
                    db.execute("INSERT INTO evidence VALUES (?,?,?,?,?)",
                               (source, op["id"], work["id"], digest(proof), canonical(proof)))
                else:
                    work["status"] = "needs_attention"
            self._save_op(db, op)
            self._save(db, work, "OperationResolved", {"operation_id": op["id"], "status": op["status"]})
            return op

    def recover(self, adapter: Adapter, now: Optional[int] = None) -> list:
        """Reconcile uncertain calls; safe prepared intents can then be dispatched."""
        with self._connection() as db:
            operations = [json.loads(r[0]) for r in db.execute("SELECT body FROM operations")]
            work_ids = [r[0] for r in db.execute("SELECT id FROM works")]
        for work_id in work_ids:
            self.verify_pending(work_id)
            self.expire_waits(work_id, int(time.time()) if now is None else now)
        results = []
        for op in operations:
            if op["status"] in ("dispatched", "outcome_unknown"):
                results.append(self.reconcile(op["id"], adapter))
            elif op["status"] == "prepared" and op["dispatch_state"] == "ready":
                results.append(self.dispatch(op["id"], adapter))
        return results
