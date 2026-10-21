"""Durable mixed-node workflow engine.

The engine composes the runtime primitives that already exist — Work, CAS on
``state_version``, command dedup under ``(actor, command_id)``, Evidence,
Wait, Operation/Attempt, adapter dispatch and reconcile — into a generic
mixed-node workflow: agent nodes, human approval nodes, automatic action
nodes and wait nodes, routed deterministically from stored state.

Trust boundary: principals are trusted-local configuration, not
authentication. Every principal (executor, reviewer, runner, owner) is a
name in the grants map, exactly like a policy evidence source today. The
engine adds no network service of its own and claims no distributed
exactly-once, tenant isolation or production-safety property.

Domain neutrality: nothing here knows about any business domain. Node kinds,
predicates, authorities, capabilities and validators are declared by a
published template and by host configuration.
"""

import json
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .policy import canonical, digest
from .workflow_spec import (ValidatorRegistry, eval_predicate, lint_template,
                             template_digest, validate_shape)

# Command kinds the runtime routes to the engine. They are ordinary runtime
# commands: CAS-guarded, deduplicated and receipt-bearing like every other.
WORKFLOW_COMMANDS = ("bind_workflow", "revise_object", "submit_node_result")

TERMINAL_NODE_STATES = ("completed", "failed", "expired", "cancelled")
MAX_FINDINGS = 32
MAX_VIEW_NODES = 64
MAX_VIEW_INTENTS = 32
MAX_VIEW_FINDINGS = 16
MAX_ADVANCE_STEPS = 128

DEFAULT_MAX_ATTEMPTS = 1


class WorkflowError(Exception):
    """Local API misuse raised by the engine (never a persisted rejection)."""


def _bounded(findings: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return findings[:MAX_FINDINGS]


def _finding(code: str, message: str, **extra) -> Dict[str, Any]:
    entry = {"code": code, "message": message}
    entry.update(extra)
    return entry


class _Context:
    """Predicate context backed by the engine's stored state."""

    def __init__(self, engine, db, work):
        self._engine = engine
        self._db = db
        self._work = work

    def node_completed(self, node):
        instance = self._engine._latest_instance(self._db, self._work["id"], node)
        if instance is None:
            return False
        return instance["state"] == "completed"

    def field_value(self, object_name, path):
        row = self._engine._object_row(self._db, self._work["id"], object_name)
        if row is None:
            return (False, None)
        value = json.loads(row["body"])
        for part in path or []:
            if not isinstance(value, dict) or part not in value:
                return (False, None)
            value = value[part]
        return (True, value)

    def evidence_verified(self, evidence_kind, subject):
        for proof in self._engine.runtime._proofs(self._db, self._work["id"]):
            if proof["status"] != "verified" or proof["kind"] != evidence_kind:
                continue
            data = proof.get("data") or {}
            if subject:
                name = subject.get("object")
                if name and not self._engine._proof_covers_object(
                        self._db, self._work["id"], data, name):
                    continue
            return True
        return False

    def requirement_state(self, rule_id):
        for requirement in self._work.get("requirements", []):
            if requirement.get("rule_id") == rule_id or requirement.get("id") == rule_id:
                if requirement.get("applicability") == "unknown":
                    return "unknown"
                if requirement.get("applicability") == "conflict":
                    return "conflict"
                if requirement.get("fulfillment") == "satisfied":
                    return "satisfied"
                if requirement.get("applicability") == "not_applicable":
                    return "not_applicable"
                return "unknown"
        return None


class WorkflowEngine:
    """Mixed-node workflow engine over one runtime store.

    The engine owns published templates, named objects, node instances and
    durable intents; the runtime owns the Work, the evidence ledger, the
    operation ledger and the adapter dispatch boundary.
    """

    def __init__(self, runtime, validators: Optional[ValidatorRegistry] = None,
                 runner: Optional[str] = None):
        self.runtime = runtime
        self.validators = validators if validators is not None else ValidatorRegistry()
        self.runner = runner
        runtime.workflow = self

    # ------------------------------------------------------------------
    # Published templates
    # ------------------------------------------------------------------

    def publish_template(self, actor: str, template: Dict[str, Any]) -> Dict[str, Any]:
        """Publish an immutable workflow definition.

        Publication is a host authoring act: the definition is linted, every
        referenced validator must resolve at its exact version, and the
        published record is content-addressed. Re-publishing the same
        id/version with different content is refused — a published definition
        is immutable, so a binding can always be checked against the exact
        bytes it pinned.
        """
        if not isinstance(actor, str) or not actor:
            raise WorkflowError("actor must be a nonempty string")
        if not isinstance(template, dict):
            raise WorkflowError("template must be an object")
        findings = lint_template(template)
        if findings:
            return {"decision": "rejected", "code": "WORKFLOW_SPEC_INVALID",
                    "findings": _bounded(findings)}
        template_id = template["id"]
        version = template["version"]
        content_digest = template_digest(template)
        unknown = self._unknown_validators(template)
        if unknown:
            return {"decision": "rejected", "code": "WORKFLOW_VALIDATOR_UNKNOWN",
                    "validators": unknown}
        with self.runtime._transaction() as db:
            row = db.execute(
                "SELECT digest,body FROM workflow_templates WHERE id=? AND version=?",
                (template_id, version)).fetchone()
            if row is not None:
                if row[0] != content_digest:
                    return {"decision": "rejected", "code": "WORKFLOW_TEMPLATE_IMMUTABLE",
                            "template_id": template_id, "template_version": version}
                return {"decision": "accepted", "template_id": template_id,
                        "template_version": version, "digest": content_digest}
            body = {"id": template_id, "version": version, "digest": content_digest,
                    "spec": template, "published_by": actor,
                    "published_at": int(time.time())}
            db.execute("INSERT INTO workflow_templates VALUES (?,?,?,?)",
                       (template_id, version, content_digest, canonical(body)))
            return {"decision": "accepted", "template_id": template_id,
                    "template_version": version, "digest": content_digest}

    def list_templates(self) -> List[Dict[str, Any]]:
        with self.runtime._connection() as db:
            return [{"template_id": row[0], "template_version": row[1],
                     "digest": row[2]} for row in db.execute(
                         "SELECT id,version,digest FROM workflow_templates "
                         "ORDER BY id,version")]

    def template(self, template_id: str, version: str) -> Optional[Dict[str, Any]]:
        with self.runtime._connection() as db:
            row = db.execute(
                "SELECT body FROM workflow_templates WHERE id=? AND version=?",
                (template_id, version)).fetchone()
            return json.loads(row[0]) if row else None

    def _unknown_validators(self, spec: Dict[str, Any]) -> List[Dict[str, str]]:
        missing = []
        for node_id, node in (spec.get("nodes") or {}).items():
            if not isinstance(node, dict):
                continue
            validations = []
            output = node.get("output")
            if isinstance(output, dict):
                validations.append(output.get("validation"))
            for entry in node.get("inputs") or []:
                if isinstance(entry, dict):
                    validations.append(entry.get("validation"))
            for validation in validations:
                if not isinstance(validation, dict):
                    continue
                name = validation.get("validator")
                version = validation.get("validator_version")
                if name is None and version is None:
                    continue
                if self.validators.resolve(name, version) is None:
                    missing.append({"node": node_id, "validator": str(name),
                                    "validator_version": str(version)})
        return missing[:MAX_FINDINGS]

    # ------------------------------------------------------------------
    # Command entry point
    # ------------------------------------------------------------------

    def command(self, actor: str, command_id: str, work_id: str, kind: str,
                payload: Optional[dict] = None,
                expected_version: Optional[int] = None,
                now: Optional[int] = None) -> dict:
        """Run one runtime command and settle the workflow afterwards.

        The command itself is an ordinary runtime command (CAS, dedup,
        receipt). The settle pass is a separate transaction: a routing
        failure can never roll back a command that was already accepted.
        A rejected command still settles when it changed stored state (a
        rejected candidate fails its node and opens a rework attempt), so
        the settle pass runs for both outcomes.
        """
        receipt = self.runtime.command(actor, command_id, work_id, kind, payload,
                                       expected_version)
        try:
            self.advance(work_id, int(time.time()) if now is None else int(now))
        except Exception as error:  # pragma: no cover - defensive, surfaced durably
            self._record_advance_failure(work_id, type(error).__name__)
        return receipt

    def replay_allowed(self, actor: str, work: dict, kind: str) -> bool:
        """Replay re-authorization for workflow command kinds."""
        if kind == "bind_workflow":
            return self.runtime._manager(actor, work)
        if kind == "revise_object":
            return self.runtime._manager(actor, work)
        if kind == "submit_node_result":
            return "workflow.execute" in self.runtime.grants.get(actor, set())
        return False

    def apply_command(self, db, actor: str, work: dict, kind: str, payload: dict,
                      version: int) -> dict:
        """Dispatch one workflow command kind (called by the runtime)."""
        if kind == "bind_workflow":
            return self._bind(db, actor, work, payload, version)
        if kind == "revise_object":
            return self._revise_object(db, actor, work, payload, version)
        if kind == "submit_node_result":
            return self._submit_result(db, actor, work, payload, version)
        return self.runtime._reject("COMMAND_UNSUPPORTED", version)

    # ------------------------------------------------------------------
    # Binding
    # ------------------------------------------------------------------

    def _bind(self, db, actor, work, payload, version):
        allowed = {"template_id", "template_version", "parameters", "session_id"}
        if not set(payload) <= allowed or not {"template_id", "template_version",
                                               "parameters"} <= set(payload):
            raise WorkflowError("bind_workflow requires exactly template_id, "
                                "template_version and parameters, and may carry "
                                "an optional session_id")
        if work.get("workflow"):
            return self.runtime._reject("WORKFLOW_ALREADY_BOUND", version)
        if not work.get("contract"):
            return self.runtime._reject("CONTRACT_NOT_ACTIVE", version)
        template_id = payload["template_id"]
        template_version = payload["template_version"]
        if not isinstance(template_id, str) or not isinstance(template_version, str):
            raise WorkflowError("template_id and template_version must be strings")
        row = db.execute("SELECT digest,body FROM workflow_templates WHERE id=? AND version=?",
                         (template_id, template_version)).fetchone()
        if row is None:
            return self.runtime._reject("WORKFLOW_TEMPLATE_UNKNOWN", version,
                                        [template_id + "@" + template_version])
        stored = json.loads(row[1])
        spec = stored["spec"]
        policy = self.runtime._policy_for(work)
        if spec.get("policy_family") != policy.id:
            return self.runtime._reject("WORKFLOW_FAMILY_MISMATCH", version,
                                        [spec.get("policy_family"), policy.id])
        parameters = payload["parameters"]
        if not isinstance(parameters, dict):
            raise WorkflowError("parameters must be an object")
        schema = spec.get("parameters_schema")
        if isinstance(schema, dict):
            findings = validate_shape(schema, parameters, "parameters")
            if findings:
                return self.runtime._reject("WORKFLOW_PARAMETERS_INVALID", version,
                                            _bounded(findings))
        unknown = self._unknown_validators(spec)
        if unknown:
            return self.runtime._reject("WORKFLOW_VALIDATOR_UNKNOWN", version, unknown)
        authority = self._unknown_authorities(spec, policy)
        if authority:
            return self.runtime._reject("WORKFLOW_AUTHORITY_UNKNOWN", version, authority)
        missing_checks = self._missing_required_checks(spec)
        if missing_checks:
            return self.runtime._reject("WORKFLOW_REQUIRED_CHECKS_MISSING", version,
                                        missing_checks)
        unsupported = self._unsupported_capabilities(spec, policy)
        if unsupported:
            return self.runtime._reject("WORKFLOW_CAPABILITY_UNSUPPORTED", version,
                                        unsupported)
        session_id = payload.get("session_id")
        if session_id is not None and (not isinstance(session_id, str) or not session_id):
            raise WorkflowError("session_id must be a nonempty string or absent")
        work["workflow"] = {"template_id": template_id, "template_version": template_version,
                            "digest": stored["digest"], "revision": 1,
                            "parameters": parameters, "session_id": session_id}
        work["workflow_status"] = "active"
        work["workflow_current"] = None
        self.runtime._save(db, work, "WorkflowBound", {
            "template_id": template_id, "template_version": template_version,
            "digest": stored["digest"], "parameters": parameters})
        return self.runtime._accepted(work, template_id=template_id,
                                      template_version=template_version,
                                      workflow_digest=stored["digest"])

    def _unknown_authorities(self, spec, policy) -> List[Dict[str, str]]:
        missing = []
        sources = getattr(policy, "evidence_sources", {}) or {}
        for node_id, node in (spec.get("nodes") or {}).items():
            if not isinstance(node, dict):
                continue
            kinds = []
            if node.get("kind") == "human" and node.get("evidence_kind"):
                kinds.append(node["evidence_kind"])
            review = node.get("review")
            if isinstance(review, dict) and review.get("evidence_kind"):
                kinds.append(review["evidence_kind"])
            match = node.get("match")
            if isinstance(match, dict) and match.get("evidence_kind"):
                kinds.append(match["evidence_kind"])
            for kind in kinds:
                if kind not in sources:
                    missing.append({"node": node_id, "evidence_kind": kind})
        return missing[:MAX_FINDINGS]

    def _missing_required_checks(self, spec) -> List[str]:
        required = spec.get("required_checks")
        if not isinstance(required, list):
            return []
        covered = set()
        for node in (spec.get("nodes") or {}).values():
            if isinstance(node, dict) and isinstance(node.get("checks"), list):
                covered.update(node["checks"])
        return sorted(set(required) - covered)

    def _unsupported_capabilities(self, spec, policy) -> List[str]:
        unsupported = []
        for node_id, node in (spec.get("nodes") or {}).items():
            if not isinstance(node, dict) or node.get("kind") != "action":
                continue
            capability = node.get("capability")
            if not isinstance(capability, str):
                continue
            blockers = policy.action_blockers(capability, [])
            if any(blocker.get("code") == "CAPABILITY_UNSUPPORTED"
                   for blocker in blockers):
                unsupported.append(capability)
        return sorted(set(unsupported))

    # ------------------------------------------------------------------
    # Named objects
    # ------------------------------------------------------------------

    def _object_row(self, db, work_id, name):
        return db.execute(
            "SELECT name,revision,digest,body FROM workflow_objects "
            "WHERE work_id=? AND name=? ORDER BY revision DESC LIMIT 1",
            (work_id, name)).fetchone()

    def _object_at(self, db, work_id, name, revision):
        return db.execute(
            "SELECT name,revision,digest,body FROM workflow_objects "
            "WHERE work_id=? AND name=? AND revision=?", (work_id, name, revision)).fetchone()

    def _write_object(self, db, work_id, name, body):
        row = self._object_row(db, work_id, name)
        revision = (row["revision"] + 1) if row else 1
        content_digest = digest(body)
        db.execute("INSERT INTO workflow_objects VALUES (?,?,?,?,?)",
                   (work_id, name, revision, content_digest, canonical(body)))
        return {"name": name, "revision": revision, "digest": content_digest}

    def _revise_object(self, db, actor, work, payload, version):
        if set(payload) != {"name", "object"}:
            raise WorkflowError("revise_object requires exactly name and object")
        name = payload["name"]
        body = payload["object"]
        if not isinstance(name, str) or not name:
            raise WorkflowError("object name must be a nonempty string")
        if not isinstance(body, dict):
            raise WorkflowError("object body must be an object")
        if not self.runtime._manager(actor, work):
            return self.runtime._reject("AUTHORITY_DENIED", version)
        if work.get("cancellation"):
            return self.runtime._reject("CANCELLATION_ACTIVE", version)
        reference = self._write_object(db, work["id"], name, body)
        superseded = self._supersede_pinned(db, work, name)
        self.runtime._save(db, work, "ObjectRevised", {
            "name": name, "revision": reference["revision"], "digest": reference["digest"],
            "superseded_nodes": superseded})
        return self.runtime._accepted(work, object=reference,
                                      superseded_nodes=superseded)

    def _supersede_pinned(self, db, work, name) -> List[str]:
        """Cancel node instances pinned to a superseded object revision."""
        affected = []
        rows = db.execute("SELECT node,attempt,body FROM workflow_nodes WHERE work_id=?",
                          (work["id"],)).fetchall()
        for row in rows:
            instance = json.loads(row["body"])
            if instance["state"] not in ("running", "blocked", "submitted"):
                continue
            pinned = list(instance.get("inputs") or []) + list(instance.get("subject") or [])
            if not any(entry.get("name") == name for entry in pinned):
                continue
            instance["state"] = "cancelled"
            instance["outcome"] = "cancelled"
            instance["reason"] = "OBJECT_SUPERSEDED"
            db.execute("UPDATE workflow_nodes SET state=?,body=? "
                       "WHERE work_id=? AND node=? AND attempt=?",
                       (instance["state"], canonical(instance), work["id"],
                        instance["node"], instance["attempt"]))
            self._cancel_intents(db, work["id"], instance["node"], instance["attempt"])
            affected.append(instance["node"] + "#" + str(instance["attempt"]))
        return affected

    # ------------------------------------------------------------------
    # Node instances and intents
    # ------------------------------------------------------------------

    def _proof_covers_object(self, db, work_id, data, name):
        """True when a proof's digest covers the current revision of an object.

        A proof that names a subject covers it only when it was made against
        the revision that is current now: a superseded object is not covered
        by the proof that covered its predecessor.
        """
        if not isinstance(data, dict):
            return False
        claimed = data.get("digest")
        if not isinstance(claimed, str) or not claimed:
            return False
        row = self._object_row(db, work_id, name)
        if row is None:
            return False
        return row["digest"] == claimed

    def _latest_instance(self, db, work_id, node):
        row = db.execute(
            "SELECT attempt,body FROM workflow_nodes WHERE work_id=? AND node=? "
            "ORDER BY attempt DESC LIMIT 1", (work_id, node)).fetchone()
        return json.loads(row["body"]) if row else None

    def _instances(self, db, work_id):
        rows = db.execute("SELECT node,attempt,body FROM workflow_nodes WHERE work_id=? "
                          "ORDER BY node,attempt", (work_id,)).fetchall()
        return [json.loads(row["body"]) for row in rows]

    def _intent_id(self, work_id, node, attempt, kind):
        return "wf:" + work_id + ":" + node + ":" + str(attempt) + ":" + kind

    def _write_intent(self, db, work_id, node, attempt, kind, body):
        intent_id = self._intent_id(work_id, node, attempt, kind)
        existing = db.execute("SELECT id,status FROM workflow_intents WHERE id=?",
                              (intent_id,)).fetchone()
        if existing is not None:
            return intent_id
        payload = dict(body)
        payload.update({"id": intent_id, "work_id": work_id, "node": node,
                        "attempt": attempt, "kind": kind, "status": "pending"})
        db.execute("INSERT INTO workflow_intents VALUES (?,?,?,?,?,?,?)",
                   (intent_id, work_id, node, attempt, kind, "pending", canonical(payload)))
        return intent_id

    def _cancel_intents(self, db, work_id, node, attempt):
        for row in db.execute("SELECT id,body FROM workflow_intents "
                              "WHERE work_id=? AND node=? AND attempt=? AND status='pending'",
                              (work_id, node, attempt)).fetchall():
            body = json.loads(row[1])
            body["status"] = "cancelled"
            db.execute("UPDATE workflow_intents SET status=?,body=? WHERE id=?",
                       ("cancelled", canonical(body), row[0]))

    def intents(self, kind: Optional[str] = None, session_id: Optional[str] = None,
                status: Optional[str] = "pending", work_id: Optional[str] = None,
                limit: int = MAX_VIEW_INTENTS) -> List[Dict[str, Any]]:
        """List durable intents for a platform bridge."""
        with self.runtime._connection() as db:
            query = ("SELECT body FROM workflow_intents WHERE 1=1")
            arguments: List[Any] = []
            if kind:
                query += " AND kind=?"
                arguments.append(kind)
            if work_id:
                query += " AND work_id=?"
                arguments.append(work_id)
            if status:
                query += " AND status=?"
                arguments.append(status)
            query += " ORDER BY rowid LIMIT ?"
            arguments.append(max(1, min(int(limit), MAX_VIEW_INTENTS)))
            found = []
            for row in db.execute(query, tuple(arguments)).fetchall():
                body = json.loads(row[0])
                if session_id is not None and body.get("session_id") != session_id:
                    continue
                found.append(body)
            return found

    def acknowledge_intent(self, actor: str, intent_id: str,
                           command_id: Optional[str] = None) -> Dict[str, Any]:
        """Acknowledge a durable intent (the bridge has taken it over)."""
        with self.runtime._transaction() as db:
            row = db.execute("SELECT body FROM workflow_intents WHERE id=?",
                             (intent_id,)).fetchone()
            if row is None:
                return {"decision": "rejected", "code": "WORKFLOW_INTENT_UNKNOWN"}
            body = json.loads(row[0])
            if body["status"] == "cancelled":
                return {"decision": "rejected", "code": "WORKFLOW_INTENT_CANCELLED"}
            if body["status"] == "done":
                return {"decision": "accepted", "intent_id": intent_id,
                        "status": body["status"]}
            body["status"] = "acknowledged"
            body["acknowledged_by"] = actor
            body["acknowledged_at"] = int(time.time())
            db.execute("UPDATE workflow_intents SET status=?,body=? WHERE id=?",
                       ("acknowledged", canonical(body), intent_id))
            return {"decision": "accepted", "intent_id": intent_id,
                    "status": body["status"]}

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def spec_for(self, work) -> Optional[Dict[str, Any]]:
        binding = work.get("workflow")
        if not binding:
            return None
        with self.runtime._connection() as db:
            row = db.execute(
                "SELECT body FROM workflow_templates WHERE id=? AND version=?",
                (binding["template_id"], binding["template_version"])).fetchone()
        if row is None:
            return None
        return json.loads(row[0])["spec"]

    def _spec_in(self, db, work) -> Optional[Dict[str, Any]]:
        binding = work.get("workflow")
        if not binding:
            return None
        row = db.execute("SELECT body FROM workflow_templates WHERE id=? AND version=?",
                         (binding["template_id"], binding["template_version"])).fetchone()
        if row is None:
            return None
        return json.loads(row[0])["spec"]

    def _entry_node(self, spec) -> str:
        entry = spec.get("entry")
        if entry:
            return entry
        inbound = {node_id: 0 for node_id in spec["nodes"]}
        for edge in spec.get("edges") or []:
            if edge.get("to") in inbound:
                inbound[edge["to"]] += 1
        candidates = [node_id for node_id, count in inbound.items() if count == 0]
        return sorted(candidates)[0] if candidates else sorted(spec["nodes"])[0]

    def _max_attempts(self, spec, node_id) -> int:
        node = spec["nodes"].get(node_id) or {}
        value = node.get("max_attempts")
        if type(value) is not int or value < 1:
            return DEFAULT_MAX_ATTEMPTS
        return value

    def advance(self, work_id: str, now: int) -> Dict[str, Any]:
        """One deterministic routing pass over a work's stored state."""
        with self.runtime._transaction() as db:
            work = self.runtime._work(db, work_id)
            spec = self._spec_in(db, work)
            if spec is None:
                return {"decision": "noop", "work_id": work_id}
            changed = False
            for _ in range(MAX_ADVANCE_STEPS):
                stepped, stop = self._step(db, work, spec, now)
                changed = changed or stepped
                if stop or not stepped:
                    break
            return {"decision": "advanced" if changed else "noop",
                    "work_id": work_id, "current": work.get("workflow_current"),
                    "status": work.get("workflow_status")}

    def _step(self, db, work, spec, now) -> Tuple[bool, bool]:
        changed = False
        persisted = False
        current = work.get("workflow_current")
        if current is None:
            current = self._entry_node(spec)
            work["workflow_current"] = current
            changed = True
        instance = self._latest_instance(db, work["id"], current)
        if instance is None:
            instance = self._open_attempt(db, work, spec, current, now)
            changed = True
            if instance is None:
                self._persist(db, work, "WorkflowReworkLimitExceeded", {"node": current})
                return changed, True
        elif instance["state"] == "blocked":
            # A blocked node re-resolves its inputs: a missing object may
            # have arrived since the last pass.
            progressed = self._activate(db, work, spec, current, instance, now)
            changed = changed or progressed
            persisted = persisted or progressed
            instance = self._latest_instance(db, work["id"], current)
        elif instance["state"] in ("running", "submitted"):
            progressed = self._settle(db, work, spec, current, instance, now)
            changed = changed or progressed
            persisted = persisted or progressed
            instance = self._latest_instance(db, work["id"], current)
        if instance is None:
            return changed, True
        if instance["state"] in TERMINAL_NODE_STATES:
            successor = self._successor(db, work, spec, current, instance)
            if successor is None:
                work["workflow_current"] = None
                work["workflow_status"] = ("needs_attention" if work.get("cancellation")
                                          else "finished")
                self._persist(db, work, "WorkflowFinished",
                              {"node": current, "outcome": instance.get("outcome")})
                return True, True
            if successor == "blocked":
                work["workflow_status"] = "needs_attention"
                self._persist(db, work, "WorkflowBlocked",
                              {"node": current, "reason": "PREDICATE_UNKNOWN"})
                return changed, True
            work["workflow_current"] = successor
            opened = self._open_attempt(db, work, spec, successor, now)
            if opened is None:
                work["workflow_status"] = "needs_attention"
                self._persist(db, work, "WorkflowReworkLimitExceeded", {"node": successor})
                return changed, True
            changed = True
            persisted = True
        if changed and not persisted:
            # The cursor moved but no node transition wrote the work row.
            self._persist(db, work, "WorkflowRouted", {"node": work.get("workflow_current")})
        return changed, not changed

    def _persist(self, db, work, event, details=None):
        """Write the work only when its state actually changed.

        A routing pass that changes nothing must not bump the state version
        or append an event: two identical passes leave the store byte for
        byte as one pass did.
        """
        self.runtime._evaluate(db, work)
        row = db.execute("SELECT state FROM works WHERE id=?", (work["id"],)).fetchone()
        if row is not None:
            previous = json.loads(row[0])
            if self._state_snapshot(previous) == self._state_snapshot(work):
                return False
        self.runtime._save(db, work, event, details or {})
        return True

    @staticmethod
    def _state_snapshot(work):
        """The work state without the version counter."""
        return {key: value for key, value in work.items() if key != "state_version"}

    def _open_attempt(self, db, work, spec, node_id, now) -> Optional[Dict[str, Any]]:
        """Open (or re-open) the current attempt of a node.

        Returns the instance, or ``None`` when the bounded rework allowance
        for that node is exhausted.
        """
        latest = self._latest_instance(db, work["id"], node_id)
        if latest is not None and latest["state"] in ("running", "submitted"):
            return latest
        attempt = (latest["attempt"] + 1) if latest is not None else 1
        if attempt > self._max_attempts(spec, node_id):
            return None
        node = spec["nodes"][node_id]
        instance = {"node": node_id, "kind": node.get("kind"), "attempt": attempt,
                    "state": "blocked", "outcome": None, "reason": None,
                    "inputs": [], "subject": None, "output": None,
                    "findings": [], "blockers": [], "actor": None,
                    "operation_id": None, "intent_id": None, "result": None,
                    "created_at": now}
        db.execute("INSERT INTO workflow_nodes VALUES (?,?,?,?,?)",
                   (work["id"], node_id, attempt, "blocked", canonical(instance)))
        self._activate(db, work, spec, node_id, instance, now)
        return self._latest_instance(db, work["id"], node_id)

    def _activate(self, db, work, spec, node_id, instance, now) -> bool:
        """Resolve inputs and subject, then start the node's own work.

        The pass is idempotent: when the resolved state is identical to the
        stored one, nothing is written at all.
        """
        node = spec["nodes"][node_id]
        kind = node.get("kind")
        before = canonical(instance)
        findings: List[Dict[str, Any]] = []
        pinned_inputs = []
        for entry in node.get("inputs") or []:
            name = entry.get("object")
            row = self._object_row(db, work["id"], name)
            if row is None:
                findings.append(_finding("INPUT_MISSING",
                                         "Required input object is not available",
                                         node=node_id, object=name))
                continue
            validation = entry.get("validation")
            if isinstance(validation, dict) and isinstance(validation.get("shape"), dict):
                problems = validate_shape(validation["shape"], json.loads(row["body"]),
                                           name)
                for problem in problems:
                    findings.append(_finding(problem["code"],
                                             "Input does not match the declared shape",
                                             node=node_id, object=name,
                                             location=problem.get("path", "")))
            pinned_inputs.append({"name": name, "revision": row["revision"],
                                  "digest": row["digest"]})
        subject = None
        subject_spec = node.get("subject")
        if isinstance(subject_spec, dict) and subject_spec.get("object"):
            name = subject_spec["object"]
            row = self._object_row(db, work["id"], name)
            if row is None:
                findings.append(_finding("SUBJECT_MISSING",
                                         "Approval subject is not available",
                                         node=node_id, object=name))
            else:
                subject = {"name": name, "revision": row["revision"],
                           "digest": row["digest"]}
        instance["inputs"] = pinned_inputs
        instance["subject"] = subject
        instance["findings"] = _bounded(findings)
        if findings:
            instance["state"] = "blocked"
            instance["blockers"] = [{"code": finding["code"],
                                      "detail": finding["message"]} for finding in findings]
            return self._save_instance(db, work, instance, "WorkflowNodeBlocked")
        instance["blockers"] = []
        deadline = node.get("deadline_s")
        instance["deadline_at"] = (now + deadline) if isinstance(deadline, int) else None
        instance["state"] = "running"
        if kind == "agent":
            self._start_agent(db, work, spec, node_id, instance, now)
        elif kind == "human":
            self._start_human(db, work, spec, node_id, instance, now)
        elif kind == "action":
            self._start_action(db, work, spec, node_id, instance, now)
        elif kind == "wait":
            self._start_wait(db, work, spec, node_id, instance, now)
        if canonical(instance) == before:
            return False
        return self._save_instance(db, work, instance, "WorkflowNodeActivated")

    def _save_instance(self, db, work, instance, event, details=None) -> bool:
        body = canonical(instance)
        row = db.execute("SELECT body FROM workflow_nodes WHERE work_id=? AND node=? "
                         "AND attempt=?",
                         (work["id"], instance["node"], instance["attempt"])).fetchone()
        if row is not None and row[0] == body:
            return False
        db.execute("UPDATE workflow_nodes SET state=?,body=? WHERE work_id=? AND node=? "
                   "AND attempt=?",
                   (instance["state"], body, work["id"],
                    instance["node"], instance["attempt"]))
        payload = {"node": instance["node"], "attempt": instance["attempt"],
                   "kind": instance.get("kind"), "state": instance["state"]}
        payload.update(details or {})
        self.runtime._save(db, work, event, payload)
        return True

    def _start_agent(self, db, work, spec, node_id, instance, now):
        session_id = (work.get("workflow") or {}).get("session_id")
        body = {"session_id": session_id, "executor": spec["nodes"][node_id].get("executor"),
                "inputs": instance.get("inputs") or [],
                "output": spec["nodes"][node_id].get("output"),
                "checks": spec["nodes"][node_id].get("checks") or [],
                "deadline_at": instance.get("deadline_at"),
                "created_at": now}
        instance["intent_id"] = self._write_intent(
            db, work["id"], node_id, instance["attempt"], "agent_task", body)

    def _start_human(self, db, work, spec, node_id, instance, now):
        node = spec["nodes"][node_id]
        body = {"session_id": (work.get("workflow") or {}).get("session_id"),
                "authority": node.get("evidence_kind"), "subject": instance.get("subject"),
                "inputs": instance.get("inputs") or [],
                "checks": node.get("checks") or [],
                "allowed_actions": ["record_decision"],
                "deadline_at": instance.get("deadline_at"), "created_at": now}
        instance["intent_id"] = self._write_intent(
            db, work["id"], node_id, instance["attempt"], "human_task", body)

    def _start_wait(self, db, work, spec, node_id, instance, now):
        node = spec["nodes"][node_id]
        instance["match"] = node.get("match")
        instance["intent_id"] = None

    def _start_action(self, db, work, spec, node_id, instance, now):
        node = spec["nodes"][node_id]
        subject = instance.get("subject")
        if subject is None:
            instance["state"] = "blocked"
            instance["blockers"] = [{"code": "SUBJECT_MISSING",
                                      "detail": "Action subject is not available"}]
            return
        # The automatic action is proposed by the work owner: binding a
        # published template is the owner's authorization of its action
        # nodes. The configured runner is recorded on the instance for audit.
        actor = work.get("owner") or self.runner
        if actor is None:
            instance["state"] = "blocked"
            instance["blockers"] = [{"code": "WORKFLOW_RUNNER_UNKNOWN",
                                      "detail": "No machine runner is configured"}]
            return
        instance["runner"] = self.runner
        payload = {"capability": node["capability"],
                   "contract_revision": work["contract"]["revision"],
                   "plan_revision": work["plan_revision"],
                   "document_digest": subject["digest"],
                   "object": {"name": subject["name"], "revision": subject["revision"],
                              "digest": subject["digest"]}}
        receipt = self.runtime._propose(db, actor, work, payload)
        if receipt.get("decision") != "accepted":
            instance["state"] = "blocked"
            instance["blockers"] = [{"code": receipt.get("code", "PROPOSAL_REJECTED"),
                                      "detail": "The automatic action was not admitted"}]
            return
        instance["operation_id"] = receipt.get("operation_id")

    # ------------------------------------------------------------------
    # Settling a node
    # ------------------------------------------------------------------

    def _settle(self, db, work, spec, node_id, instance, now) -> bool:
        node = spec["nodes"][node_id]
        kind = node.get("kind")
        if kind == "human":
            return self._settle_human(db, work, spec, node_id, instance, now)
        if kind == "agent":
            return self._settle_agent(db, work, spec, node_id, instance, now)
        if kind == "action":
            return self._settle_action(db, work, spec, node_id, instance, now)
        if kind == "wait":
            return self._settle_wait(db, work, spec, node_id, instance, now)
        return False

    def _expire_if_due(self, db, work, instance, now) -> bool:
        deadline = instance.get("deadline_at")
        if deadline is None or now < deadline:
            return False
        instance["state"] = "expired"
        instance["outcome"] = "expired"
        instance["reason"] = "DEADLINE_EXCEEDED"
        self._cancel_intents(db, work["id"], instance["node"], instance["attempt"])
        self._save_instance(db, work, instance, "WorkflowNodeExpired")
        return True

    def _settle_human(self, db, work, spec, node_id, instance, now) -> bool:
        node = spec["nodes"][node_id]
        subject = instance.get("subject")
        candidates = self._find_decisions(db, work, node, subject)
        if not candidates:
            return self._expire_if_due(db, work, instance, now)
        # A decision that violates separation of duties never advances the
        # node: the violation is recorded and the node keeps waiting.
        admitted = []
        violation = None
        for proof, verdict in candidates:
            isolation = self._isolation_finding(db, work, spec, node_id, proof)
            if isolation is None:
                admitted.append((proof, verdict))
            elif violation is None:
                violation = isolation
        if not admitted:
            return self._block_with_finding(db, work, instance, violation,
                                           "WorkflowNodeIsolationViolation")
        authority = node.get("authority")
        authorized = [entry for entry in admitted
                      if authority is None or entry[0]["source"] == authority]
        if not authorized:
            return self._block_with_finding(
                db, work, instance,
                _finding("WORKFLOW_AUTHORITY_MISMATCH",
                         "The decision did not come from the declared authority"),
                "WorkflowNodeAuthorityViolation")
        proof, verdict = authorized[0]
        instance["actor"] = proof["source"]
        instance["outcome"] = verdict
        instance["state"] = "completed"
        instance["decision_event_id"] = proof["event_id"]
        self._finish_intent(db, work, instance)
        self._save_instance(db, work, instance, "WorkflowNodeCompleted",
                            {"outcome": verdict})
        return True

    def _block_with_finding(self, db, work, instance, finding, event) -> bool:
        """Record a bounded finding on a node and keep it waiting."""
        findings = list(instance.get("findings") or [])
        if finding is not None and not any(
                entry.get("code") == finding["code"] for entry in findings):
            findings.append(finding)
        instance["findings"] = _bounded(findings)
        instance["blockers"] = ([{"code": finding["code"], "detail": finding["message"]}]
                                if finding is not None else [])
        self._save_instance(db, work, instance, event)
        return False

    def _find_decisions(self, db, work, node, subject):
        """Every exact-version decision evidence for a human node.

        A decision counts only when it is verified, of the node's declared
        kind, and covers the subject's exact revision and digest. A stale
        decision never satisfies a node.
        """
        if subject is None:
            return []
        kind = node.get("evidence_kind")
        found = []
        for proof in self.runtime._proofs(db, work["id"]):
            if proof["status"] != "verified" or proof["kind"] != kind:
                continue
            data = proof.get("data") or {}
            verdict = data.get("decision")
            if verdict not in ("approved", "rejected"):
                continue
            if data.get("digest") != subject["digest"]:
                continue
            if data.get("revision") != subject["revision"]:
                continue
            found.append((proof, verdict))
        return found

    def _isolation_finding(self, db, work, spec, node_id, proof):
        """Role isolation: an executor may never approve, and separation
        rules forbid reusing an actor who did the work being reviewed."""
        source = proof.get("source")
        executors = set()
        for other in (spec.get("nodes") or {}).values():
            if isinstance(other, dict) and other.get("executor"):
                executors.add(other["executor"])
        if source in executors:
            return _finding("WORKFLOW_EXECUTOR_MAY_NOT_APPROVE",
                            "An executor may not approve a node")
        node = spec["nodes"][node_id]
        for other_id in node.get("distinct_from") or []:
            other = self._latest_instance(db, work["id"], other_id)
            if other is not None and other.get("actor") == source:
                return _finding("WORKFLOW_ROLE_ISOLATION",
                                "The reviewer must differ from the actor of another node")
        return None

    def _settle_agent(self, db, work, spec, node_id, instance, now) -> bool:
        node = spec["nodes"][node_id]
        review = node.get("review")
        if instance.get("result") is None:
            return self._expire_if_due(db, work, instance, now)
        if not isinstance(review, dict) or not review.get("evidence_kind"):
            return False
        result = instance["result"]
        covered = False
        for proof in self.runtime._proofs(db, work["id"]):
            if proof["status"] != "verified" or proof["kind"] != review["evidence_kind"]:
                continue
            data = proof.get("data") or {}
            if data.get("digest") != result["digest"]:
                continue
            covered = True
            break
        if not covered:
            return self._expire_if_due(db, work, instance, now)
        instance["state"] = "completed"
        instance["outcome"] = "completed"
        self._finish_intent(db, work, instance)
        self._save_instance(db, work, instance, "WorkflowNodeCompleted",
                            {"outcome": "completed"})
        return True

    def _settle_action(self, db, work, spec, node_id, instance, now) -> bool:
        operation_id = instance.get("operation_id")
        if not operation_id:
            return self._expire_if_due(db, work, instance, now)
        row = db.execute("SELECT body FROM operations WHERE id=?", (operation_id,)).fetchone()
        if row is None:
            return self._expire_if_due(db, work, instance, now)
        operation = json.loads(row[0])
        if operation["status"] == "confirmed_succeeded":
            instance["state"] = "completed"
            instance["outcome"] = "completed"
            instance["external_id"] = operation.get("external_id")
            self._finish_intent(db, work, instance)
            self._save_instance(db, work, instance, "WorkflowNodeCompleted",
                                {"outcome": "completed"})
            return True
        if operation["status"] == "confirmed_failed":
            instance["state"] = "failed"
            instance["outcome"] = "failed"
            instance["reason"] = "OPERATION_FAILED"
            self._finish_intent(db, work, instance)
            self._save_instance(db, work, instance, "WorkflowNodeFailed",
                                {"outcome": "failed"})
            return True
        if operation["status"] == "prepared" and operation["dispatch_state"] == "cancelled":
            instance["state"] = "failed"
            instance["outcome"] = "failed"
            instance["reason"] = "OPERATION_CANCELLED"
            self._finish_intent(db, work, instance)
            self._save_instance(db, work, instance, "WorkflowNodeFailed",
                                {"outcome": "failed", "reason": "OPERATION_CANCELLED"})
            return True
        return self._expire_if_due(db, work, instance, now)

    def _settle_wait(self, db, work, spec, node_id, instance, now) -> bool:
        match = instance.get("match") or {}
        if match.get("timeout"):
            return self._expire_if_due(db, work, instance, now)
        context = _Context(self, db, work)
        satisfied = False
        if match.get("evidence_kind"):
            subject = match.get("subject")
            answer = context.evidence_verified(match["evidence_kind"], subject)
            satisfied = answer is True
        elif match.get("node_completed"):
            satisfied = context.node_completed(match["node_completed"]) is True
        if not satisfied:
            return self._expire_if_due(db, work, instance, now)
        instance["state"] = "completed"
        instance["outcome"] = "completed"
        self._finish_intent(db, work, instance)
        self._save_instance(db, work, instance, "WorkflowNodeCompleted",
                            {"outcome": "completed"})
        return True

    def _finish_intent(self, db, work, instance):
        intent_id = instance.get("intent_id")
        if not intent_id:
            return
        row = db.execute("SELECT body FROM workflow_intents WHERE id=?", (intent_id,)).fetchone()
        if row is None:
            return
        body = json.loads(row[0])
        if body.get("status") != "cancelled":
            body["status"] = "done"
            db.execute("UPDATE workflow_intents SET status=?,body=? WHERE id=?",
                       ("done", canonical(body), intent_id))

    # ------------------------------------------------------------------
    # Successors and rework
    # ------------------------------------------------------------------

    def _successor(self, db, work, spec, node_id, instance):
        """The node that follows, or None when the workflow is finished.

        Returns the string ``"blocked"`` when a routing predicate is unknown:
        an unknown fact blocks the edge, exactly like an unresolved
        obligation blocks an action today.
        """
        node = spec["nodes"][node_id]
        outcome = instance.get("outcome")
        reason = instance.get("reason")
        if outcome == "rejected" and node.get("on_reject"):
            return node["on_reject"]
        if outcome == "failed":
            if reason == "WORKFLOW_RESULT_INVALID" and node.get("kind") == "agent":
                # A rejected candidate is re-executed as a new attempt of the
                # same node; the bounded allowance decides when to escalate.
                return node_id
            if node.get("on_failure"):
                return node["on_failure"]
            return None
        if outcome == "expired":
            if node.get("on_timeout"):
                return node["on_timeout"]
            return None
        if outcome == "cancelled":
            if reason == "OBJECT_SUPERSEDED":
                return node_id
            return None
        context = _Context(self, db, work)
        candidates = [edge for edge in spec.get("edges") or [] if edge.get("from") == node_id]
        if not candidates:
            return None
        unknown = False
        for edge in candidates:
            predicate = edge.get("when")
            if predicate is None:
                return edge["to"]
            verdict = eval_predicate(predicate, context)
            if verdict == "true":
                return edge["to"]
            if verdict == "unknown":
                unknown = True
        return "blocked" if unknown else None

    # ------------------------------------------------------------------
    # Agent result submission
    # ------------------------------------------------------------------

    def _submit_result(self, db, actor, work, payload, version):
        if set(payload) != {"node", "attempt", "object", "result"}:
            raise WorkflowError("submit_node_result requires exactly node, attempt, "
                                "object and result")
        node_id = payload["node"]
        attempt = payload["attempt"]
        result = payload["result"]
        if not isinstance(node_id, str) or type(attempt) is not int:
            raise WorkflowError("submit_node_result requires a node id and an attempt")
        if not isinstance(result, dict):
            raise WorkflowError("submit_node_result requires an object result")
        if "workflow.execute" not in self.runtime.grants.get(actor, set()):
            return self.runtime._reject("AUTHORITY_DENIED", version)
        spec = self._spec_in(db, work)
        if spec is None:
            return self.runtime._reject("WORKFLOW_NOT_BOUND", version)
        node = spec["nodes"].get(node_id)
        if node is None or node.get("kind") != "agent":
            return self.runtime._reject("WORKFLOW_NODE_UNKNOWN", version, [node_id])
        if node.get("executor") != actor:
            return self.runtime._reject("AUTHORITY_DENIED", version)
        instance = self._latest_instance(db, work["id"], node_id)
        if instance is None or instance["attempt"] != attempt:
            return self.runtime._reject("WORKFLOW_ATTEMPT_STALE", version, [node_id])
        if instance["state"] != "running":
            return self.runtime._reject("WORKFLOW_ATTEMPT_STALE", version, [node_id])
        if payload["object"] != (node.get("output") or {}).get("object"):
            return self.runtime._reject("WORKFLOW_OBJECT_MISMATCH", version,
                                        [str(payload["object"])])
        validation = (node.get("output") or {}).get("validation") or {}
        findings = []
        shape = validation.get("shape")
        if isinstance(shape, dict):
            for problem in validate_shape(shape, result, payload["object"]):
                findings.append(_finding(problem["code"],
                                         "Candidate output does not match the declared shape",
                                         location=problem.get("path", "")))
        validator_id = validation.get("validator")
        validator_version = validation.get("validator_version")
        if validator_id is not None:
            validator = self.validators.resolve(validator_id, validator_version)
            if validator is None:
                return self.runtime._reject("WORKFLOW_VALIDATOR_UNKNOWN", version,
                                            [{"validator": str(validator_id),
                                              "validator_version": str(validator_version)}])
            reported = validator(work, {"node": node_id, "attempt": attempt}, result)
            for problem in reported or []:
                findings.append(_finding(problem.get("code", "VALIDATOR_REJECTED"),
                                         problem.get("message", "The validator rejected the candidate"),
                                         location=problem.get("location", "")))
        if findings:
            instance["findings"] = _bounded(findings)
            instance["state"] = "failed"
            instance["outcome"] = "failed"
            instance["reason"] = "WORKFLOW_RESULT_INVALID"
            instance["validator"] = {"id": validator_id, "version": validator_version}
            self._cancel_intents(db, work["id"], node_id, attempt)
            self._save_instance(db, work, instance, "WorkflowResultRejected", {
                "validator": validator_id, "validator_version": validator_version,
                "findings": instance["findings"]})
            return self.runtime._reject("WORKFLOW_RESULT_INVALID", version,
                                        instance["findings"])
        reference = self._write_object(db, work["id"], payload["object"], result)
        instance["result"] = {"digest": reference["digest"], "revision": reference["revision"],
                              "name": reference["name"]}
        instance["output"] = reference
        instance["validator"] = {"id": validator_id, "version": validator_version}
        review = node.get("review")
        if isinstance(review, dict) and review.get("evidence_kind"):
            instance["state"] = "submitted"
            self._save_instance(db, work, instance, "WorkflowResultSubmitted", {
                "validator": validator_id, "validator_version": validator_version,
                "output": reference})
        else:
            instance["state"] = "completed"
            instance["outcome"] = "completed"
            self._finish_intent(db, work, instance)
            self._save_instance(db, work, instance, "WorkflowNodeCompleted",
                                {"outcome": "completed", "output": reference})
        return self.runtime._accepted(work, node=node_id, attempt=attempt,
                                      output=reference,
                                      state=instance["state"])

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    def cancel_in_transaction(self, db, work) -> None:
        """Cancel the running workflow inside the runtime's cancel transaction.

        The runtime cancels the work, its waits and its prepared operations;
        the workflow cancels its node instances and its durable intents in the
        same transaction, so a crash can never leave a running node behind a
        cancelled work.
        """
        if not work.get("workflow"):
            return
        for instance in self._instances(db, work["id"]):
            if instance["state"] in ("running", "blocked", "submitted"):
                instance["state"] = "cancelled"
                instance["outcome"] = "cancelled"
                instance["reason"] = "WORK_CANCELLED"
                db.execute("UPDATE workflow_nodes SET state=?,body=? "
                           "WHERE work_id=? AND node=? AND attempt=?",
                           ("cancelled", canonical(instance), work["id"],
                            instance["node"], instance["attempt"]))
                self._cancel_intents(db, work["id"], instance["node"],
                                     instance["attempt"])
        work["workflow_current"] = None
        work["workflow_status"] = "needs_attention"

    def _cancel_workflow(self, work_id: str) -> None:
        """Cancel the workflow of a work that is already cancelling."""
        with self.runtime._transaction() as db:
            work = self.runtime._work(db, work_id)
            if not work.get("workflow"):
                return
            if not work.get("cancellation"):
                return
            self.cancel_in_transaction(db, work)
            self.runtime._save(db, work, "WorkflowCancelled", {"workflow": True})

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    def workflow_work_ids(self) -> List[str]:
        with self.runtime._connection() as db:
            identifiers = []
            for row in db.execute("SELECT id,state FROM works"):
                try:
                    work = json.loads(row[1])
                except ValueError:  # pragma: no cover - corrupted store
                    continue
                if work.get("workflow"):
                    identifiers.append(row[0])
            return identifiers

    def pump(self, adapter, now: Optional[int] = None) -> List[Dict[str, Any]]:
        """Advance every workflow and dispatch the actions they created.

        The dispatch happens outside the routing transaction, exactly like
        every other external call: the routing pass persists the intent, the
        dispatch performs the effect, and a second pass settles the node
        against the confirmed result.
        """
        moment = int(time.time()) if now is None else int(now)
        work_ids = self.workflow_work_ids()
        for work_id in work_ids:
            self.advance(work_id, moment)
        results = []
        for operation_id in self._prepared_operations(work_ids):
            results.append(self.runtime.dispatch(operation_id, adapter))
        for work_id in self.workflow_work_ids():
            self.advance(work_id, moment)
        return results

    def _prepared_operations(self, work_ids) -> List[str]:
        """Prepared, dispatchable operations of the given works."""
        wanted = set(work_ids)
        if not wanted:
            return []
        found = []
        with self.runtime._connection() as db:
            for row in db.execute("SELECT body FROM operations").fetchall():
                operation = json.loads(row[0])
                if operation["work_id"] not in wanted:
                    continue
                if (operation["status"] == "prepared"
                        and operation["dispatch_state"] == "ready"):
                    found.append(operation["id"])
        return found

    def recover(self, adapter, now: Optional[int] = None) -> List[Dict[str, Any]]:
        """Resume progress after a restart.

        Order matters: evidence is evaluated, waits expire, the workflow is
        routed (so newly ready nodes create their intents and operations),
        and only then are uncertain calls reconciled and prepared intents
        dispatched. Uncertain external effects are looked up, never repeated.
        """
        moment = int(time.time()) if now is None else int(now)
        for work_id in self.workflow_work_ids():
            self.runtime.verify_pending(work_id)
            self.runtime.expire_waits(work_id, moment)
            self._cancel_workflow(work_id)
            self.advance(work_id, moment)
        results = self.runtime.recover(adapter, moment)
        # The dispatch above may have confirmed an operation: settle the nodes
        # that were waiting for it.
        for work_id in self.workflow_work_ids():
            self.advance(work_id, moment)
        return results

    def _record_advance_failure(self, work_id: str, reason: str) -> None:
        try:
            with self.runtime._transaction() as db:
                work = self.runtime._work(db, work_id)
                work["workflow_status"] = "needs_attention"
                self.runtime._save(db, work, "WorkflowAdvanceFailed", {"reason": reason})
        except Exception:  # pragma: no cover - the failure is already reported
            pass

    # ------------------------------------------------------------------
    # Read model
    # ------------------------------------------------------------------

    def instance(self, work_id: str) -> Dict[str, Any]:
        """A bounded read model of one workflow instance."""
        with self.runtime._connection() as db:
            work = self.runtime._work(db, work_id)
            spec = self._spec_in(db, work)
            binding = work.get("workflow")
            if not binding or spec is None:
                raise WorkflowError("Work has no workflow bound: " + work_id)
            instances = self._instances(db, work_id)
            latest: Dict[str, Dict[str, Any]] = {}
            for instance in instances:
                latest[instance["node"]] = instance
            nodes = []
            for node_id in sorted(spec["nodes"])[:MAX_VIEW_NODES]:
                instance = latest.get(node_id)
                nodes.append({
                    "node": node_id,
                    "kind": (spec["nodes"][node_id] or {}).get("kind"),
                    "state": instance["state"] if instance else "pending",
                    "attempt": instance["attempt"] if instance else 0,
                    "outcome": instance.get("outcome") if instance else None,
                    "inputs": (instance.get("inputs") or []) if instance else [],
                    "subject": instance.get("subject") if instance else None,
                    "outputs": ([instance["output"]] if instance and instance.get("output")
                                else []),
                    "findings": (instance.get("findings") or [])[:MAX_VIEW_FINDINGS]
                    if instance else [],
                    "blockers": (instance.get("blockers") or [])[:MAX_VIEW_FINDINGS]
                    if instance else [],
                    "intentId": instance.get("intent_id") if instance else None,
                    "checks": (spec["nodes"][node_id] or {}).get("checks") or [],
                })
            intents = []
            for row in db.execute("SELECT body FROM workflow_intents WHERE work_id=? "
                                  "ORDER BY rowid", (work_id,)).fetchall():
                body = json.loads(row[0])
                intents.append({"id": body["id"], "kind": body["kind"],
                                "node": body["node"], "attempt": body["attempt"],
                                "status": body["status"],
                                "sessionId": body.get("session_id")})
            checks = []
            for node_id in sorted(spec["nodes"]):
                for check in (spec["nodes"][node_id] or {}).get("checks") or []:
                    checks.append({"checkId": check, "node": node_id})
            current = work.get("workflow_current")
            allowed = []
            if current is not None:
                instance = latest.get(current)
                node = spec["nodes"].get(current) or {}
                if instance and instance["state"] in ("running", "submitted"):
                    if node.get("kind") == "agent":
                        allowed.append({"action": "submit_node_result", "node": current,
                                        "attempt": instance["attempt"],
                                        "required": ["result"]})
                    if node.get("kind") == "human":
                        allowed.append({"action": "record_decision", "node": current,
                                        "attempt": instance["attempt"],
                                        "required": ["decision", "digest", "revision"]})
            return {
                "workId": work_id,
                "status": work["status"],
                "workflowStatus": work.get("workflow_status"),
                "stateVersion": work["state_version"],
                "currentNode": current,
                "workflow": {"templateId": binding["template_id"],
                             "templateVersion": binding["template_version"],
                             "digest": binding["digest"],
                             "revision": binding["revision"],
                             "parameters": binding["parameters"]},
                "nodes": nodes,
                "checks": checks[:MAX_VIEW_NODES],
                "allowedActions": allowed,
                "intents": intents[:MAX_VIEW_INTENTS],
            }
