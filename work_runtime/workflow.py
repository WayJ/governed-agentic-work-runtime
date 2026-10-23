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

import copy
import json
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .adapter_contract import receipt_is_valid
from .policy import canonical, digest
from .workflow_spec import (EFFECT_POLICIES, EFFECT_POLICY_ONCE,
                             EFFECT_POLICY_PER_REVISION, ValidatorRegistry,
                             eval_predicate, lint_template, template_digest,
                             validate_shape)

# Command kinds the runtime routes to the engine. They are ordinary runtime
# commands: CAS-guarded, deduplicated and receipt-bearing like every other.
WORKFLOW_COMMANDS = ("bind_workflow", "revise_object", "submit_node_result",
                     "record_decision", "finalize_workflow_success",
                     "request_material_wait", "adopt_material")

TERMINAL_NODE_STATES = ("completed", "failed", "expired", "cancelled")

# The verdicts a node may complete with. An automatic node completes with
# "completed"; a human node completes with the verdict of its kind,
# "approved". Every other verdict (a rejection, a failure, an expiry, a
# cancellation) is not a success, whatever the node's state says.
SUCCESSFUL_NODE_OUTCOMES = ("completed", "approved")

# The verdicts a criterion report may carry.
CRITERION_VERDICTS = ("passed", "failed", "insufficient", "conflict",
                       "not_applicable")

# The methods that may produce a criterion report.
REPORT_METHODS = ("PROGRAM", "AGENT", "HUMAN")
MAX_FINDINGS = 32
MAX_VIEW_NODES = 64
MAX_VIEW_INTENTS = 32
MAX_VIEW_FINDINGS = 16
MAX_ADVANCE_STEPS = 128

DEFAULT_MAX_ATTEMPTS = 1

# The version of the material-wait request. A caller states the version it
# speaks, so a later shape is refused instead of half-understood.
MATERIAL_WAIT_REQUEST_VERSION = 1

# The bound of the reason a manager gives for a wait.
MAX_WAIT_REASON_CHARS = 512

# The bound of the adoptions one wait may carry.
MAX_WAIT_ADOPTIONS = 16

# The source of the proofs the engine writes itself. It is the engine's own
# trusted channel, never the ingress source of a signed evidence kind: the
# engine must not impersonate a platform channel.
WORKFLOW_EVENT_SOURCE = "workflow-engine"

# The codes of the native action context read.
ACTION_CONTEXT_ABSENT = "ACTION_CONTEXT_ABSENT"
ACTION_CONTEXT_REFUSED = "ACTION_CONTEXT_REFUSED"

# The refusals of the workflow-success finalization. Every one of them says
# what is *not* settled yet; none of them freezes anything.
WORKFLOW_RUNNER_UNCONFIGURED = "WORKFLOW_RUNNER_UNCONFIGURED"
WORKFLOW_RUNNER_MISMATCH = "WORKFLOW_RUNNER_MISMATCH"
WORKFLOW_NOT_FINISHED = "WORKFLOW_NOT_FINISHED"
WORKFLOW_TERMINAL_NOT_COMPLETED = "WORKFLOW_TERMINAL_NOT_COMPLETED"
WORKFLOW_TERMINAL_NOT_DECLARED = "WORKFLOW_TERMINAL_NOT_DECLARED"
WORKFLOW_NODE_UNSETTLED = "WORKFLOW_NODE_UNSETTLED"
WORKFLOW_NODE_NOT_COMPLETED = "WORKFLOW_NODE_NOT_COMPLETED"
WORKFLOW_QUALITY_UNSETTLED = "WORKFLOW_QUALITY_UNSETTLED"
WORKFLOW_CHECK_UNSATISFIED = "WORKFLOW_CHECK_UNSATISFIED"
WORKFLOW_EFFECT_UNRESOLVED = "WORKFLOW_EFFECT_UNRESOLVED"
WORKFLOW_REQUIREMENT_UNSATISFIED = "WORKFLOW_REQUIREMENT_UNSATISFIED"
WORKFLOW_INTENT_UNSETTLED = "WORKFLOW_INTENT_UNSETTLED"
WORKFLOW_CANCELLED = "WORKFLOW_CANCELLED"
WORKFLOW_SNAPSHOT_UNBOUNDED = "WORKFLOW_SNAPSHOT_UNBOUNDED"

# The reasons an automatic node refuses to produce its external effect. The
# default policy refuses with WORKFLOW_EFFECT_ALREADY_APPLIED; the
# per-revision policy names the exact reason it refuses.
WORKFLOW_EFFECT_ALREADY_APPLIED = "WORKFLOW_EFFECT_ALREADY_APPLIED"
WORKFLOW_EFFECT_SUBJECT_UNCHANGED = "WORKFLOW_EFFECT_SUBJECT_UNCHANGED"
WORKFLOW_EFFECT_UNRESOLVED = "WORKFLOW_EFFECT_UNRESOLVED"
WORKFLOW_EFFECT_OUTPUT_INVALID = "WORKFLOW_EFFECT_OUTPUT_INVALID"
WORKFLOW_EFFECT_REUSED = "WORKFLOW_EFFECT_REUSED"

# Bounds on what the engine keeps of an external receipt.
MAX_RECEIPT_BYTES = 8192
MAX_OUTPUT_BYTES = 65536

# The bound of the frozen final snapshot: the named objects it names.
MAX_FINALIZATION_OBJECTS = 64


class WorkflowError(Exception):
    """Local API misuse raised by the engine (never a persisted rejection)."""


class ParticipantResolver:
    """The trusted port that answers "who currently holds this assignment?".

    The core never learns a workspace role id, a membership rule or a
    department rule: it knows a *principal* per node and asks the host who
    currently holds it. An enterprise adapter resolves only from the trusted
    create snapshot plus the platform's current check; the default is no
    resolver at all, and an assigned authority then fails closed.
    """

    def resolve(self, work, node_id, member_id) -> Optional[str]:
        """The principal of the member, or None when it may not act now."""
        return None


def _bounded(findings: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return findings[:MAX_FINDINGS]


def _bounded_receipt(receipt: Any) -> Tuple[Optional[Dict[str, Any]],
                                            Optional[Dict[str, Any]]]:
    """The receipt the adapter returned, and its business payload, bounded.

    The transport fields are kept exactly as the external system stated
    them — they are what the receipt schema and the digest linkage are
    checked against. The payload is kept apart and bounded on its own, so
    an oversized business record is refused instead of silently truncated.
    """
    if not isinstance(receipt, dict):
        return None, None
    view = {name: value for name, value in receipt.items() if name != "payload"}
    try:
        if len(canonical(view).encode("utf-8")) > MAX_RECEIPT_BYTES:
            return None, None
    except (TypeError, ValueError):
        return None, None
    payload = receipt.get("payload")
    if payload is None:
        return view, None
    if not isinstance(payload, dict):
        return None, None
    try:
        if len(canonical(payload).encode("utf-8")) > MAX_OUTPUT_BYTES:
            return None, None
    except (TypeError, ValueError):
        return None, None
    return view, payload


def _receipt_view(stored: Any) -> Optional[Dict[str, Any]]:
    """The transport facts of a stored receipt, without its payload.

    The payload is a business record and is read through the object it was
    written as; the receipt view carries only what links the effect to the
    operation it belongs to.
    """
    if not isinstance(stored, dict):
        return None
    receipt = stored.get("receipt")
    origin = stored.get("origin") or {}
    if not isinstance(receipt, dict):
        return None
    view = {"externalId": receipt.get("external_id"),
            "status": receipt.get("status"),
            "digest": receipt.get("digest"),
            "action": receipt.get("action")}
    if origin:
        view["operationId"] = origin.get("operationId")
        view["capability"] = origin.get("capability")
        view["adapter"] = origin.get("adapter")
    return view


def _finding(code: str, message: str, **extra) -> Dict[str, Any]:
    entry = {"code": code, "message": message}
    entry.update(extra)
    return entry


class _ReceiptRecorder:
    """The receipts the external system really returned.

    The engine wraps the adapter it is given so the receipt that came back
    from the external system — not a summary invented afterwards — is the
    material the node's output is validated against. The recorder changes
    nothing about the call: it forwards the call and keeps what came back.
    """

    def __init__(self, adapter):
        self.adapter = adapter
        self.receipts: Dict[str, Any] = {}
        self.adapter_name = type(adapter).__name__

    def execute(self, key, document, content_digest, **kwargs):
        result = self.adapter.execute(key, document, content_digest, **kwargs)
        self._remember(key, result)
        return result

    def lookup(self, key):
        result = self.adapter.lookup(key)
        if result is not None:
            self._remember(key, result)
        return result

    def _remember(self, key, result):
        if isinstance(result, dict):
            self.receipts[key] = result

    def __getattr__(self, name):
        if name.startswith("_") or name == "adapter":
            raise AttributeError(name)
        return getattr(self.__dict__["adapter"], name)


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
                 runner: Optional[str] = None,
                 resolver: Optional[ParticipantResolver] = None):
        self.runtime = runtime
        self.validators = validators if validators is not None else ValidatorRegistry()
        self.runner = runner
        # The trusted participant port. None means an assigned authority can
        # never be resolved, so it fails closed.
        self.resolver = resolver
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
            for check in node.get("checks") or []:
                if isinstance(check, dict) and check.get("validator") is not None:
                    validations.append({"validator": check.get("validator"),
                                        "validator_version": check.get("validator_version")})
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

    def replay_allowed(self, actor: str, work: dict, kind: str,
                       payload: Optional[dict] = None) -> bool:
        """Replay re-authorization for workflow command kinds.

        A stored receipt is replayed only while the authority that decided
        it still holds: for a decision, the ingress source must still be
        the configured source and the actor must still hold the assignment.
        """
        if kind in ("bind_workflow", "revise_object", "request_material_wait",
                    "adopt_material"):
            return self.runtime._manager(actor, work)
        if kind == "submit_node_result":
            return "workflow.execute" in self.runtime.grants.get(actor, set())
        if kind == "record_decision":
            return self._decision_authority_holds(actor, work, payload or {})
        if kind == "finalize_workflow_success":
            # The stored receipt of a finalization is replayed while the
            # trusted runner still holds the role that decided it.
            return self.runner is not None and actor == self.runner
        return False

    def _decision_authority_holds(self, actor: str, work: dict,
                                   payload: dict) -> bool:
        """The ingress source and the actor of a decision, re-checked."""
        node_id = payload.get("node")
        if not isinstance(node_id, str):
            return False
        spec = self.spec_for(work)
        if spec is None:
            return False
        node = (spec.get("nodes") or {}).get(node_id)
        if not isinstance(node, dict) or node.get("kind") != "human":
            return False
        kind = node.get("evidence_kind")
        if self.runtime._policy_for(work).evidence_sources.get(kind) != actor:
            return False
        effective = self._effective_authority(work, node_id, node)
        return effective is not None and effective == payload.get("actor")

    def apply_command(self, db, actor: str, work: dict, kind: str, payload: dict,
                      version: int, command_id: Optional[str] = None) -> dict:
        """Dispatch one workflow command kind (called by the runtime)."""
        if kind == "bind_workflow":
            return self._bind(db, actor, work, payload, version)
        if kind == "revise_object":
            return self._revise_object(db, actor, work, payload, version)
        if kind == "submit_node_result":
            return self._submit_result(db, actor, work, payload, version)
        if kind == "record_decision":
            return self._record_decision(db, actor, work, payload, version,
                                         command_id)
        if kind == "finalize_workflow_success":
            return self._finalize_success(db, actor, work, payload, version)
        if kind == "request_material_wait":
            return self._request_material_wait(db, actor, work, payload, version)
        if kind == "adopt_material":
            return self._adopt_material(db, actor, work, payload, version)
        return self.runtime._reject("COMMAND_UNSUPPORTED", version)

    # ------------------------------------------------------------------
    # Binding
    # ------------------------------------------------------------------

    def _bind(self, db, actor, work, payload, version):
        allowed = {"template_id", "template_version", "parameters", "session_id",
                   "participants"}
        if not set(payload) <= allowed or not {"template_id", "template_version",
                                               "parameters"} <= set(payload):
            raise WorkflowError("bind_workflow requires exactly template_id, "
                                "template_version and parameters, and may carry "
                                "an optional session_id and participants map")
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
        unknown_policies = self._unknown_effect_policies(spec)
        if unknown_policies:
            return self.runtime._reject("WORKFLOW_EFFECT_POLICY_UNKNOWN", version,
                                        unknown_policies)
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
        participants = self._validated_participants(spec, payload.get("participants"))
        if participants is None:
            return self.runtime._reject("WORKFLOW_PARTICIPANT_UNKNOWN", version)
        work["workflow"] = {"template_id": template_id, "template_version": template_version,
                            "digest": stored["digest"], "revision": 1,
                            "parameters": parameters, "session_id": session_id,
                            "participants": participants}
        work["workflow_status"] = "active"
        work["workflow_current"] = None
        self.runtime._save(db, work, "WorkflowBound", {
            "template_id": template_id, "template_version": template_version,
            "digest": stored["digest"], "parameters": parameters})
        return self.runtime._accepted(work, template_id=template_id,
                                      template_version=template_version,
                                      workflow_digest=stored["digest"])

    @staticmethod
    def _validated_participants(spec, participants) -> Optional[Dict[str, str]]:
        """The trusted assignment snapshot of an instance.

        Every key must be a node the pinned definition declares: an
        assignment to an unknown node is a mistake that would silently leave
        a node unassigned, so it is refused.
        """
        if participants is None:
            return {}
        if not isinstance(participants, dict):
            return None
        declared = set(spec.get("nodes") or {})
        cleaned = {}
        for node_id, member_id in participants.items():
            if not isinstance(node_id, str) or node_id not in declared:
                return None
            if not isinstance(member_id, str) or not member_id:
                return None
            cleaned[node_id] = member_id
        return cleaned

    def _effective_authority(self, work: dict, node_id: str,
                             node: Dict[str, Any]) -> Optional[str]:
        """The principal that may currently decide a node.

        A static authority is the principal itself. An assigned authority is
        whoever the platform currently assigns to this node, resolved
        through the trusted participant port; with no resolver it fails
        closed and nobody may decide.
        """
        authority = node.get("authority")
        if isinstance(authority, str) and authority:
            return authority
        if not (isinstance(authority, dict) and authority.get("assigned") is True):
            return None
        participants = (work.get("workflow") or {}).get("participants") or {}
        member_id = participants.get(node_id)
        if not isinstance(member_id, str) or not member_id:
            return None
        if self.resolver is None:
            return None
        try:
            resolved = self.resolver.resolve(work, node_id, member_id)
        except Exception:  # pragma: no cover - a failing resolver decides nobody
            return None
        if not isinstance(resolved, str) or not resolved:
            return None
        return resolved

    def effective_authority(self, work_id: str, node_id: str) -> Optional[str]:
        """The principal that may currently decide a node, if any.

        A static authority is the principal itself; an assigned authority is
        resolved through the trusted participant port and fails closed when
        no resolver is configured.
        """
        work = self.runtime.get_work(work_id)
        with self.runtime._connection() as db:
            spec = self._spec_in(db, work)
        if spec is None:
            return None
        node = (spec.get("nodes") or {}).get(node_id)
        if not isinstance(node, dict):
            return None
        return self._effective_authority(work, node_id, node)

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
                covered.update(self._check_ids(node))
        return sorted(set(required) - covered)

    @staticmethod
    def _check_ids(node) -> List[str]:
        """The declared criterion identifiers of a node."""
        identifiers = []
        for check in (node or {}).get("checks") or []:
            if isinstance(check, dict) and isinstance(check.get("id"), str):
                identifiers.append(check["id"])
            elif isinstance(check, str):
                identifiers.append(check)
        return identifiers

    @staticmethod
    def _check_declarations(node) -> List[Dict[str, Any]]:
        """The declared criteria of a node, as bound to their judge."""
        declarations = []
        for check in (node or {}).get("checks") or []:
            if isinstance(check, dict):
                declarations.append(check)
        return declarations

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

    def _unknown_effect_policies(self, spec: Dict[str, Any]) -> List[Dict[str, str]]:
        """The action nodes whose declared effect policy this engine does not know.

        The definition is published against one engine. A policy a later
        engine does not know is refused at binding, exactly like an unknown
        validator version: the pinned definition is never executed under
        rules its author did not read.
        """
        unknown = []
        for node_id, node in (spec.get("nodes") or {}).items():
            if not isinstance(node, dict) or node.get("kind") != "action":
                continue
            policy = node.get("effect_policy")
            if policy is None:
                continue
            if policy not in EFFECT_POLICIES:
                unknown.append({"node": node_id, "effect_policy": str(policy)})
        return unknown[:MAX_FINDINGS]

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
        """Cancel node instances pinned to a superseded object revision.

        A node pins three kinds of material: its declared inputs, the
        subject it decides on and the candidate it produced. A new revision
        of any of them supersedes the node — a review of a superseded
        candidate must never be able to complete it.
        """
        affected = []
        rows = db.execute("SELECT node,attempt,body FROM workflow_nodes WHERE work_id=?",
                          (work["id"],)).fetchall()
        for row in rows:
            instance = json.loads(row["body"])
            if instance["state"] not in ("running", "blocked", "submitted"):
                continue
            pinned = []
            for key in ("inputs", "subject", "output"):
                value = instance.get(key)
                if isinstance(value, list):
                    pinned.extend(entry for entry in value if isinstance(entry, dict))
                elif isinstance(value, dict):
                    pinned.append(value)
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
            if work.get("workflow_finalization"):
                # A finalized workflow is frozen: no routing, no new node,
                # no new effect. Late evidence may still be recorded, but it
                # never reopens what was accepted.
                return {"decision": "noop", "work_id": work_id,
                        "status": work.get("workflow_status"),
                        "finalized": True}
            if work.get("cancellation") or work["status"] == "closed":
                # A cancelling work stops, and a closed work stays closed.
                # Without this, the next pass would walk the completed chain
                # from the entry node and open fresh attempts behind the
                # cancelled ones — a restart of the work, not a stop — and
                # new intents and re-admissions would follow. Cancellation
                # keeps the runtime's own paths open: evidence intake, the
                # verifier, expiry and the unknown-effect reconciliation
                # never run through this pass.
                return {"decision": "noop", "work_id": work_id,
                        "status": work.get("workflow_status"),
                        "cancelling": bool(work.get("cancellation"))}
            if work.get("workflow_terminal"):
                # The routing stopped at a terminal: a finished workflow is
                # not routed again. Without this, the next pass would walk
                # the completed chain and open a fresh attempt of the last
                # node, and a terminal that says "completed" would not be a
                # fact anybody could rely on.
                return {"decision": "noop", "work_id": work_id,
                        "status": work.get("workflow_status")}
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
        elif instance["state"] == "waiting":
            # A node that waits for material is stable: the pass neither
            # settles it nor opens anything behind it. The manager resumes
            # it, adopts the material or cancels the work.
            return changed, True
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
                work["workflow_status"] = (
                    "needs_attention" if (work.get("cancellation")
                                          or instance.get("reason") == "WORKFLOW_OUTPUT_INVALID")
                    else "finished")
                work["workflow_terminal"] = {"node": current,
                                              "outcome": instance.get("outcome"),
                                              "reason": instance.get("reason")}
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
        if latest is not None and latest["state"] in ("running", "submitted",
                                                      "waiting"):
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
        input_report: List[Dict[str, Any]] = []
        for entry in node.get("inputs") or []:
            name = entry.get("object")
            row = self._object_row(db, work["id"], name)
            if row is None:
                findings.append(_finding("INPUT_MISSING",
                                         "Required input object is not available",
                                         node=node_id, object=name))
                continue
            problems, report = self._judge_material(
                work, node_id, instance, name, row, entry.get("validation"), "input")
            findings.extend(problems)
            if report is not None:
                input_report.append(report)
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
                # A subject that declares its own validation is a protected
                # input: it is judged before the node starts, exactly like a
                # declared input.
                problems, report = self._judge_material(
                    work, node_id, instance, name, row,
                    subject_spec.get("validation"), "subject")
                findings.extend(problems)
                if report is not None:
                    input_report.append(report)
                subject = {"name": name, "revision": row["revision"],
                           "digest": row["digest"]}
        instance["inputs"] = pinned_inputs
        instance["input_digest"] = digest(pinned_inputs)
        instance["input_report"] = input_report
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

    def _start_review(self, db, work, spec, node_id, instance, now):
        """The durable review intent of a node that declares a review.

        It pins the rubric, the criteria, the candidate revision and the
        input digest, and names the independent producer. It follows the
        same dedup, recovery and acknowledgement discipline as the agent
        and human intents.
        """
        node = spec["nodes"][node_id]
        review = node.get("review") or {}
        body = {"node": node_id, "attempt": instance["attempt"],
                "evidence_kind": review.get("evidence_kind"),
                "reviewer": review.get("reviewer"),
                "rubric": review.get("rubric"),
                "criteria": self._check_declarations(node),
                "candidate": instance.get("output"),
                "input_digest": instance.get("input_digest"),
                "inputs": instance.get("inputs") or [],
                "deadline_at": instance.get("deadline_at"),
                "created_at": now}
        instance["intent_id"] = self._write_intent(
            db, work["id"], node_id, instance["attempt"], "review_task", body)

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
        denial = self._effect_admission(db, work, node_id, instance, node, subject)
        if denial is not None:
            self._refuse_effect(db, work, instance, denial)
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
        operation_id = receipt.get("operation_id")
        reused = self._reused_operation(db, work["id"], node_id, instance,
                                         operation_id)
        if reused is not None:
            # The admission must own a new operation: an operation this node
            # already used is the effect of an earlier attempt, never a new
            # one.
            self._refuse_effect(db, work, instance, reused)
            return
        instance["operation_id"] = operation_id

    def _refuse_effect(self, db, work, instance, denial) -> None:
        """Record the refusal to produce the external effect.

        A refusal that waits (an operation that must be reconciled first)
        keeps the node blocked: nothing is written and the workflow waits
        for the truth. Every other refusal fails the node closed, exactly
        like the default policy does.
        """
        code = denial["code"]
        instance["reason"] = code
        instance["blockers"] = [{"code": code, "detail": denial["detail"]}]
        if denial.get("waiting"):
            instance["state"] = "blocked"
            self._save_instance(db, work, instance, "WorkflowNodeBlocked",
                                {"reason": code})
            return
        instance["state"] = "failed"
        instance["outcome"] = "failed"
        self._save_instance(db, work, instance, "WorkflowNodeFailed",
                            {"outcome": "failed", "reason": code})

    def _effect_admission(self, db, work, node_id, instance, node, subject):
        """Whether this attempt may produce the node's external effect.

        The default is one effect per node: a later attempt of a node whose
        effect already happened fails closed and never repeats it. The
        per-revision policy admits a new effect for a **new revision with a
        new digest** of the node's subject, and only after the previous
        effect of the node is settled.
        """
        policy = node.get("effect_policy") or EFFECT_POLICY_ONCE
        if policy != EFFECT_POLICY_PER_REVISION:
            if self._effect_already_applied(db, work["id"], node_id):
                return {"code": WORKFLOW_EFFECT_ALREADY_APPLIED,
                        "detail": "The external effect was already applied"}
            return None
        for prior in self._instances(db, work["id"]):
            if prior["node"] != node_id or prior["attempt"] >= instance["attempt"]:
                continue
            denial = self._prior_effect_denial(db, prior, subject)
            if denial is not None:
                return denial
        return None

    def _prior_effect_denial(self, db, prior, subject):
        """The refusal an earlier attempt of this node causes, if any.

        An earlier attempt constrains the new one through its operation:
        the operation says whether an external effect really happened, and
        the attempt says whether its output was accepted. Neither is
        inferred from the capability or from the work's cursor.
        """
        operation_id = prior.get("operation_id")
        if not operation_id:
            # The attempt never left: it produced no effect.
            return None
        row = db.execute("SELECT body FROM operations WHERE id=?",
                         (operation_id,)).fetchone()
        if row is None:
            return {"code": WORKFLOW_EFFECT_UNRESOLVED, "waiting": True,
                    "detail": "The previous operation is unknown and must be "
                              "reconciled before a new effect"}
        operation = json.loads(row[0])
        status = operation.get("status")
        if status == "confirmed_failed":
            # The effect did not happen: it constrains nothing.
            return None
        if status != "confirmed_succeeded":
            # The effect may still happen — the operation is prepared, in
            # flight or of an unknown outcome. It is reconciled, never
            # written over, and nothing new is written while it is unsettled.
            return {"code": WORKFLOW_EFFECT_UNRESOLVED, "waiting": True,
                    "detail": "The previous operation is not settled and must "
                              "be reconciled before a new effect"}
        if prior.get("reason") == "WORKFLOW_OUTPUT_INVALID":
            # The effect happened and its output was refused. A new subject
            # does not bypass it and a manual retry does not either.
            return {"code": WORKFLOW_EFFECT_OUTPUT_INVALID,
                    "detail": "The previous effect really happened and its "
                              "output failed validation"}
        previous = operation.get("object") or prior.get("subject") or {}
        if (subject.get("revision") == previous.get("revision")
                and subject.get("digest") == previous.get("digest")):
            return {"code": WORKFLOW_EFFECT_ALREADY_APPLIED,
                    "detail": "The external effect was already applied to this "
                              "subject"}
        revision = previous.get("revision")
        if (not isinstance(revision, int)
                or not isinstance(subject.get("revision"), int)
                or subject["revision"] <= revision
                or subject.get("digest") == previous.get("digest")):
            # The subject is not a new version of the pinned object: the
            # effect would be the same one.
            return {"code": WORKFLOW_EFFECT_SUBJECT_UNCHANGED,
                    "detail": "The subject is not a new version of the pinned "
                              "object"}
        return None

    def _reused_operation(self, db, work_id, node_id, instance, operation_id):
        """The refusal when the admitted operation is not a new one.

        A new effect needs a new operation: an operation id or a business
        key this node already used belongs to an earlier attempt, and the
        effect behind it is never produced again. An operation that another
        node instance already links is refused as well — the linkage of an
        operation is exact, and a second link would make the native action
        context ambiguous.
        """
        if not operation_id:
            return None
        row = db.execute("SELECT body FROM operations WHERE id=?",
                         (operation_id,)).fetchone()
        if row is None:
            return {"code": WORKFLOW_EFFECT_UNRESOLVED, "waiting": True,
                    "detail": "The admitted operation is not readable"}
        operation = json.loads(row[0])
        for prior in self._instances(db, work_id):
            if prior["node"] != node_id or prior["attempt"] >= instance["attempt"]:
                continue
            other_id = prior.get("operation_id")
            if not other_id:
                continue
            if other_id == operation_id:
                return {"code": WORKFLOW_EFFECT_REUSED,
                        "detail": "The admitted operation belongs to an "
                                  "earlier attempt of this node"}
            other = db.execute("SELECT body FROM operations WHERE id=?",
                               (other_id,)).fetchone()
            if other is None:
                continue
            previous = json.loads(other[0])
            if previous.get("business_key") == operation.get("business_key"):
                return {"code": WORKFLOW_EFFECT_REUSED,
                        "detail": "The admitted operation belongs to an "
                                  "earlier attempt of this node"}
        for link in self._operation_links(db, operation_id):
            link_work, link_node, link_attempt = link[0], link[1], link[2]
            if (link_work == work_id and link_node == node_id
                    and link_attempt == instance["attempt"]):
                # The very instance that is being admitted: its own pending
                # operation, still linked to it alone.
                continue
            return {"code": WORKFLOW_EFFECT_REUSED,
                    "detail": "The admitted operation is already linked to "
                              "another node instance"}
        return None

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
        candidates = self._find_decisions(db, work, node, subject, node_id,
                                          instance["attempt"])
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
        effective = self._effective_authority(work, node_id, node)
        authorized = [entry for entry in admitted
                      if effective is not None
                      and (entry[0].get("data") or {}).get("actor") == effective]
        if not authorized:
            return self._block_with_finding(
                db, work, instance,
                _finding("WORKFLOW_AUTHORITY_MISMATCH",
                         "The decision did not come from the assigned authority"),
                "WorkflowNodeAuthorityViolation")
        # The latest decision is the current position.
        proof, verdict = authorized[-1]
        data = proof.get("data") or {}
        actor = data.get("actor")
        if not isinstance(actor, str) or not actor:
            return self._block_with_finding(
                db, work, instance,
                _finding("WORKFLOW_ACTOR_MISSING",
                         "The decision does not name the actor who made it"),
                "WorkflowNodeActorViolation")
        report = self._check_report_from_items(
            node, data.get("items") or [], actor,
            instance.get("input_digest"),
            (subject or {}).get("digest"), now)
        missing = self._missing_check_results(node, report, "HUMAN")
        if missing:
            return self._block_with_finding(
                db, work, instance,
                _finding("WORKFLOW_CHECK_RESULT_MISSING",
                         "A declared criterion has no verdict in the decision",
                         checks=missing),
                "WorkflowNodeCheckResultsMissing")
        shortfalls = self._criterion_shortfalls(node, report, "HUMAN")
        if verdict == "approved" and shortfalls:
            # An approval that carries a failing required criterion does not
            # complete the node. The shortage is kept, exactly as reported.
            instance["check_results"] = self._ordered_report(                node, (instance.get("check_results") or []) + report)
            instance["actor"] = actor
            return self._block_with_finding(
                db, work, instance,
                _finding("WORKFLOW_CHECK_SHORTFALL",
                         "A required criterion is not satisfied by the approval",
                         shortfalls=shortfalls),
                "WorkflowNodeCheckShortfall")
        if verdict == "request_material":
            # A request for more material keeps the node waiting. It is
            # neither an approval nor a rejection: it does not complete the
            # node and it does not open a rework attempt.
            instance["actor"] = actor
            instance["check_results"] = self._ordered_report(                node, (instance.get("check_results") or []) + report)
            instance["material_request"] = {
                "items": data.get("items") or [],
                "reason": data.get("reason") or "",
                "event_id": proof["event_id"]}
            self._save_instance(db, work, instance, "WorkflowMaterialRequested",
                                {"actor": actor})
            return False
        output = node.get("output") or {}
        output_required = self._output_required_for(node, verdict)
        if not output:
            # Compatibility: this node declared no named record. It completes
            # exactly as it always did, and the record says plainly that
            # nothing was checked.
            instance["quality"] = {"declared": False, "mode": "undeclared"}
        elif not output_required:
            # The protected declaration exempts this decision from the named
            # output: the decision settles the node, and no acceptance
            # record is invented for a decision that must not have one.
            instance["quality"] = {"declared": True, "mode": "exempt",
                                   "validator": None}
        if output and output_required and not instance.get("output"):
            # The node declared a named record and the record is not on the
            # node yet: the decision stands, but nothing downstream is
            # routed on a node whose own output is missing.
            instance["actor"] = actor
            instance["check_results"] = self._ordered_report(                node, (instance.get("check_results") or []) + report)
            return self._block_with_finding(
                db, work, instance,
                _finding("WORKFLOW_OUTPUT_MISSING",
                         "The declared output has not been produced yet",
                         node=node_id, object=output.get("object")),
                "WorkflowOutputMissing")
        instance["actor"] = actor
        instance["outcome"] = verdict
        instance["state"] = "completed"
        instance["check_results"] = self._ordered_report(            node, (instance.get("check_results") or []) + report)
        instance["decision_event_id"] = proof["event_id"]
        self._finish_intent(db, work, instance)
        self._save_instance(db, work, instance, "WorkflowNodeCompleted",
                            {"outcome": verdict})
        return True

    def _criterion_findings(self, node, items) -> List[Dict[str, Any]]:
        """The quality of a criterion report, checked at the core boundary.

        An item that names an undeclared criterion, repeats one, carries a
        blank reason or empty evidence, or a verdict outside the closed set
        is refused. A report is never accepted on the strength of its
        verdict alone.
        """
        findings = []
        declared = {declaration["id"]: declaration
                    for declaration in self._check_declarations(node)}
        seen = set()
        for index, item in enumerate(items or []):
            where = "items[" + str(index) + "]"
            if not isinstance(item, dict):
                findings.append(_finding("WORKFLOW_CHECK_REPORT_INVALID",
                                         "A criterion report item must be an object",
                                         location=where))
                continue
            check = item.get("check")
            if not isinstance(check, str) or check not in declared:
                findings.append(_finding("WORKFLOW_CHECK_REPORT_INVALID",
                                         "The report names a criterion the node "
                                         "does not declare", location=where))
                continue
            if check in seen:
                findings.append(_finding("WORKFLOW_CHECK_REPORT_INVALID",
                                         "The report names a criterion twice",
                                         location=where))
                continue
            seen.add(check)
            if item.get("verdict") not in CRITERION_VERDICTS:
                findings.append(_finding("WORKFLOW_CHECK_REPORT_INVALID",
                                         "The verdict is not one of the allowed ones",
                                         location=where))
            reason = item.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                findings.append(_finding("WORKFLOW_CHECK_REPORT_INVALID",
                                         "The verdict needs a reason", location=where))
            evidence = item.get("evidence")
            if evidence is not None and (not isinstance(evidence, list)
                                         or not all(isinstance(entry, str)
                                                    and entry.strip()
                                                    for entry in evidence)):
                findings.append(_finding("WORKFLOW_CHECK_REPORT_INVALID",
                                         "The evidence must be a list of references",
                                         location=where))
            if item.get("verdict") == "passed" and not evidence:
                # A pass must point at what it was made on. A shortage may
                # carry no evidence at all: its reason is the missing fact.
                findings.append(_finding("WORKFLOW_CHECK_REPORT_INVALID",
                                         "A passed criterion needs its evidence",
                                         location=where))
        return findings

    def _criterion_shortfalls(self, node, report, method) -> List[Dict[str, Any]]:
        """The required criteria of that judge that the report does not satisfy.

        A required criterion needs a verdict; a not-applicable verdict
        counts only when the protected declaration allows it. A criterion
        declared for another judge is not this judge's business: the
        stages of one criterion keep their own identifiers and their own
        records.
        """
        judged = {entry.get("checkId"): entry for entry in report
                  if entry.get("method") == method}
        shortfalls = []
        for declaration in self._check_declarations(node):
            if declaration.get("required") is False:
                continue
            if declaration.get("method") not in (None, method):
                continue
            entry = judged.get(declaration["id"])
            if entry is None:
                shortfalls.append({"checkId": declaration["id"], "verdict": None,
                                   "reason": "NO_VERDICT"})
                continue
            verdict = entry.get("verdict")
            if verdict == "passed":
                continue
            if verdict == "not_applicable" and declaration.get("allow_not_applicable"):
                continue
            shortfalls.append({"checkId": declaration["id"], "verdict": verdict,
                               "reason": entry.get("reason")})
        return shortfalls

    def _missing_check_results(self, node, report, method) -> List[str]:
        """The required criteria of that judge that no report covers."""
        judged = {entry.get("checkId") for entry in report
                  if entry.get("method") == method}
        return sorted(declaration["id"] for declaration in self._check_declarations(node)
                      if declaration.get("required") is not False
                      and declaration.get("method") in (None, method)
                      and declaration["id"] not in judged)

    def _check_report_from_items(self, node, items, actor, input_digest=None,
                                 output_digest=None, at=None, method="HUMAN",
                                 validator_id=None, validator_version=None
                                 ) -> List[Dict[str, Any]]:
        """The persisted criterion report of a judgment.

        The report keeps what was actually judged, at judgment time: the
        method that produced it, the criterion version, the validator that
        was bound, the digests the judgment was made against, the real
        verdict, the reason, the evidence and the actor. A historical
        judgment is therefore reconstructible from the stored record and
        not from the current state of the node.
        """
        report = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            bound = self._bound_validator_for(node, item.get("check"))
            report.append({
                "checkId": item.get("check"),
                "verdict": item.get("verdict"),
                "reason": item.get("reason"),
                "evidence": item.get("evidence") or [],
                "method": method,
                "criterionVersion": (bound or {}).get("criterion_version"),
                "validator": (validator_id if validator_id is not None
                              else ((bound or {}).get("validator"))),
                "validatorVersion": (validator_version if validator_version is not None
                                     else ((bound or {}).get("validator_version"))),
                "reviewedInputDigest": input_digest,
                "reviewedOutputDigest": output_digest,
                "decidedBy": actor,
                "at": at,
            })
        return report

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

    def _find_decisions(self, db, work, node, subject, node_id, attempt):
        """Every decision that covers this node, attempt and subject.

        A decision counts only when it is verified, of the node's declared
        kind, and covers the subject's exact revision and digest *and* the
        node and attempt it was made for. A decision of an earlier attempt
        never satisfies a later one, even when the content is identical.
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
            if verdict not in ("approved", "rejected", "request_material"):
                continue
            if data.get("digest") != subject["digest"]:
                continue
            if data.get("revision") != subject["revision"]:
                continue
            if data.get("node") != node_id:
                continue
            if data.get("attempt") != attempt:
                continue
            found.append((proof, verdict))
        return found

    def _isolation_finding(self, db, work, spec, node_id, proof):
        """Role isolation, compared on the actor who actually decided.

        The proof's source is the platform ingress: it says which channel
        carried the decision, never who decided. The actor comes from the
        decision's asserted principal, and the separation rules are checked
        against that actor.
        """
        data = proof.get("data") or {}
        actor = data.get("actor")
        if not isinstance(actor, str) or not actor:
            return _finding("WORKFLOW_ACTOR_MISSING",
                            "The decision does not name the actor who made it")
        executors = set()
        for other in (spec.get("nodes") or {}).values():
            if isinstance(other, dict) and other.get("executor"):
                executors.add(other["executor"])
        if actor in executors:
            return _finding("WORKFLOW_EXECUTOR_MAY_NOT_APPROVE",
                            "An executor may not approve a node")
        node = spec["nodes"][node_id]
        for other_id in node.get("distinct_from") or []:
            other = self._latest_instance(db, work["id"], other_id)
            if other is not None and other.get("actor") == actor:
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
        accepted = None
        for proof in self.runtime._proofs(db, work["id"]):
            if proof["status"] != "verified" or proof["kind"] != review["evidence_kind"]:
                continue
            data = proof.get("data") or {}
            # The review binds the exact instance: the node, the attempt and
            # both digests. A review of an earlier attempt never satisfies
            # the current one, even when the candidate is identical.
            if data.get("node") != node_id:
                continue
            if data.get("attempt") != instance["attempt"]:
                continue
            if data.get("input_digest") != instance.get("input_digest"):
                continue
            if data.get("output_digest") != result["digest"]:
                continue
            producer = data.get("producer")
            if not isinstance(producer, str) or not producer:
                continue
            if producer == node.get("executor"):
                # The executor may never review its own candidate.
                continue
            if review.get("reviewer") and producer != review["reviewer"]:
                continue
            accepted = (proof, data, producer)
            break
        if accepted is None:
            return self._expire_if_due(db, work, instance, now)
        proof, data, producer = accepted
        items = data.get("items") or []
        findings = self._criterion_findings(node, items)
        if findings:
            instance["findings"] = _bounded(findings)
            instance["blockers"] = [{"code": "WORKFLOW_CHECK_REPORT_INVALID",
                                     "detail": "The review report is malformed"}]
            self._save_instance(db, work, instance, "WorkflowReviewReportInvalid")
            return False
        report = self._check_report_from_items(
            node, items, producer, instance.get("input_digest"),
            result["digest"], now, method="AGENT",
            validator_id=(review.get("rubric") or {}).get("validator"),
            validator_version=(review.get("rubric") or {}).get("validator_version"))
        instance["check_results"] = self._ordered_report(            node, (instance.get("check_results") or []) + report)
        shortfalls = self._criterion_shortfalls(node, report, "AGENT")
        if data.get("verdict") != "passed" or shortfalls:
            instance["state"] = "failed"
            instance["outcome"] = "failed"
            instance["reason"] = "WORKFLOW_RESULT_INVALID"
            instance["review_shortfalls"] = shortfalls
            self._finish_intent(db, work, instance)
            self._save_instance(db, work, instance, "WorkflowReviewRejected",
                                {"producer": producer, "shortfalls": shortfalls})
            return True
        instance["state"] = "completed"
        instance["outcome"] = "completed"
        self._finish_intent(db, work, instance)
        self._save_instance(db, work, instance, "WorkflowNodeCompleted",
                            {"outcome": "completed", "producer": producer})
        return True

    def _pinned_references(self, instance) -> List[Tuple[str, Dict[str, Any]]]:
        """The references this node attempt pinned, in a stable order.

        The inputs come first, in the order the node pinned them, and the
        subject last. A malformed reference is a corrupt instance, never an
        absent one: it is reported, never skipped.
        """
        references: List[Tuple[str, Dict[str, Any]]] = []
        for entry in instance.get("inputs") or []:
            if not isinstance(entry, dict):
                raise WorkflowError("A pinned input of the node is not an object")
            references.append(("input", entry))
        subject = instance.get("subject")
        if subject is not None:
            if not isinstance(subject, dict):
                raise WorkflowError("The pinned subject of the node is not an object")
            references.append(("subject", subject))
        return references

    def _node_materials(self, db, work, instance) -> List[Dict[str, Any]]:
        """The exact material this node attempt pinned.

        The entries are resolved from the instance's own references - the
        inputs it pinned and the subject it decided on - and never from the
        latest revision of an object: a node judges the material it was
        given. Every entry carries the exact stored object, verified
        against the digest its reference names. A missing or corrupt
        reference fails closed: the list is never partial, never truncated
        and never silently shortened.
        """
        materials: List[Dict[str, Any]] = []
        for role, reference in self._pinned_references(instance):
            name = reference.get("name")
            revision = reference.get("revision")
            expected = reference.get("digest")
            if not isinstance(name, str) or not name:
                raise WorkflowError("A pinned " + role + " of the node names "
                                    "no object")
            if type(revision) is not int:
                raise WorkflowError("The pinned " + role + " of the node names "
                                    "no revision: " + name)
            if not isinstance(expected, str) or not expected:
                raise WorkflowError("The pinned " + role + " of the node names "
                                    "no digest: " + name)
            row = self._object_at(db, work["id"], name, revision)
            if row is None:
                raise WorkflowError("The pinned " + role + " object is not in "
                                    "the store: " + name + "#" + str(revision))
            if row["digest"] != expected:
                raise WorkflowError("The pinned " + role + " object does not "
                                    "match its reference: " + name + "#"
                                    + str(revision))
            try:
                body = json.loads(row["body"])
            except ValueError:
                raise WorkflowError("The stored " + role + " object is not "
                                    "readable: " + name + "#" + str(revision))
            if digest(body) != row["digest"]:
                raise WorkflowError("The stored " + role + " object does not "
                                    "match its digest: " + name + "#"
                                    + str(revision))
            materials.append({"role": role,
                              "reference": {"name": name, "revision": revision,
                                            "digest": expected},
                              "object": copy.deepcopy(body)})
        return materials

    def _output_validator_call(self, db, work, instance, node_ref, material,
                                validator):
        """Call an output validator with the material this attempt pinned.

        The work is an isolated copy and the materials are deep copies: a
        validator that changes what it is given cannot change the stored
        work, the stored instance or a stored object.
        """
        context = dict(node_ref)
        context["materials"] = self._node_materials(db, work, instance)
        return validator(copy.deepcopy(work), context, material)

    def _judge_material(self, work, node_id, instance, name, row, validation,
                        role):
        """Judge one declared material: its shape and its pinned validator.

        The report says who judged it, at which version, against which exact
        revision and digest. A material that is refused blocks the node
        before it starts any work, so no intent is opened and no external
        effect is authorized.
        """
        findings: List[Dict[str, Any]] = []
        report = None
        body = json.loads(row["body"])
        if isinstance(validation, dict) and isinstance(validation.get("shape"), dict):
            for problem in validate_shape(validation["shape"], body, name):
                findings.append(_finding(problem["code"],
                                         "The material does not match the declared shape",
                                         node=node_id, object=name, role=role,
                                         revision=row["revision"],
                                         digest=row["digest"],
                                         location=problem.get("path", "")))
        if not (isinstance(validation, dict)
                and validation.get("validator") is not None):
            return findings, report
        validator_id = validation.get("validator")
        validator_version = validation.get("validator_version")
        validator = self.validators.resolve(validator_id, validator_version)
        if validator is None:
            findings.append(_finding("INPUT_VALIDATOR_UNKNOWN",
                                     "The declared validator does not resolve",
                                     node=node_id, object=name, role=role,
                                     validator=str(validator_id),
                                     validator_version=str(validator_version),
                                     revision=row["revision"],
                                     digest=row["digest"]))
            return findings, report
        reported = validator(work, {"node": node_id, "attempt": instance["attempt"],
                                    "checks": [], "role": role, "object": name},
                             body)
        raw_findings, _ = self._split_validator_report(reported)
        for problem in raw_findings:
            findings.append(_finding(
                problem.get("code", "VALIDATOR_REJECTED"),
                problem.get("message", "The material was rejected"),
                node=node_id, object=name, role=role,
                validator=validator_id, validator_version=validator_version,
                revision=row["revision"], digest=row["digest"],
                location=problem.get("location", "")))
        report = {"object": name, "role": role, "revision": row["revision"],
                  "digest": row["digest"], "validator": validator_id,
                  "validatorVersion": validator_version,
                  "verdict": "failed" if raw_findings else "passed"}
        return findings, report

    def _validate_output_material(self, db, work, node_id, node, instance,
                                  material, role, capability=None):
        """Judge a material against the node's declared output.

        Returns the findings and the per-criterion report. The material is
        judged by the declared shape and by the pinned validator; the report
        says which judge produced every verdict and against which exact
        digests.
        """
        output = node.get("output") or {}
        validation = output.get("validation") or {}
        declarations = self._check_declarations(node)
        findings: List[Dict[str, Any]] = []
        check_report: List[Dict[str, Any]] = []
        shape = validation.get("shape")
        if isinstance(shape, dict):
            for problem in validate_shape(shape, material,
                                          output.get("object") or "output"):
                findings.append(_finding(problem["code"],
                                         "The material does not match the declared shape",
                                         location=problem.get("path", "")))
        validator_id = validation.get("validator")
        validator_version = validation.get("validator_version")
        if validator_id is None:
            findings.append(_finding("WORKFLOW_VALIDATOR_MISSING",
                                     "A declared output requires a pinned validator"))
            return findings, check_report
        validator = self.validators.resolve(validator_id, validator_version)
        if validator is None:
            findings.append(_finding("WORKFLOW_VALIDATOR_UNKNOWN",
                                     "The declared validator does not resolve"))
            return findings, check_report
        check_ids = [declaration["id"] for declaration in declarations
                     if declaration.get("method") in (None, "PROGRAM")]
        reported = self._output_validator_call(
            db, work, instance,
            {"node": node_id, "attempt": instance["attempt"],
             "checks": check_ids, "role": role, "capability": capability},
            material, validator)
        raw_findings, raw_checks = self._split_validator_report(reported)
        for problem in raw_findings:
            findings.append(_finding(problem.get("code", "VALIDATOR_REJECTED"),
                                     problem.get("message",
                                                 "The validator rejected the material"),
                                     location=problem.get("location", "")))
        check_report = self._check_report_from_validator(
            node, raw_checks, validator_id, validator_version,
            instance.get("input_digest"), digest(material), int(time.time()))
        findings.extend(self._report_findings(node, check_report))
        missing = self._missing_check_results(node, check_report, "PROGRAM")
        if missing:
            findings.append(_finding("WORKFLOW_CHECK_RESULT_MISSING",
                                     "A declared criterion has no verdict from the validator",
                                     checks=missing))
        shortfalls = self._criterion_shortfalls(node, check_report, "PROGRAM")
        if shortfalls:
            findings.append(_finding("WORKFLOW_CHECK_SHORTFALL",
                                     "A required criterion is not satisfied by the validator",
                                     shortfalls=shortfalls))
        return findings, check_report

    def _effect_already_applied(self, db, work_id, node_id) -> bool:
        """True when an earlier attempt of this node already had its effect.

        An external effect that really happened is never produced a second
        time. A node whose output was rejected keeps the record of the
        effect it caused and fails closed instead of dispatching again.
        """
        for instance in self._instances(db, work_id):
            if instance["node"] != node_id:
                continue
            effect = instance.get("effect") or {}
            if effect.get("status") == "succeeded":
                return True
        return False

    def _settle_action(self, db, work, spec, node_id, instance, now) -> bool:
        operation_id = instance.get("operation_id")
        if not operation_id:
            return self._expire_if_due(db, work, instance, now)
        row = db.execute("SELECT body FROM operations WHERE id=?", (operation_id,)).fetchone()
        if row is None:
            return self._expire_if_due(db, work, instance, now)
        operation = json.loads(row[0])
        if operation["status"] == "confirmed_succeeded":
            return self._settle_action_effect(db, work, spec, node_id, instance, now,
                                              operation)
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

    def _settle_action_effect(self, db, work, spec, node_id, instance, now,
                               operation) -> bool:
        """Settle an action node whose external effect really succeeded.

        The effect and the output are two different facts. The effect
        happened; the output is judged now, against the receipt the
        external system really returned. A rejected output is a business
        rejection of the *output* — never a false external failure — and it
        never causes the effect to be produced a second time.
        """
        node = spec["nodes"][node_id]
        output = node.get("output") or {}
        declarations = self._check_declarations(node)
        effect = {"status": "succeeded",
                  "externalId": operation.get("external_id"),
                  "operationId": operation["id"],
                  "capability": operation["capability"],
                  "documentDigest": operation["document_digest"]}
        if not output and not declarations:
            # Compatibility: this node declared no quality at all. It
            # completes exactly as it always did, and the record says
            # plainly that nothing was checked.
            instance["quality"] = {"declared": False, "mode": "undeclared"}
            instance["effect"] = effect
            instance["state"] = "completed"
            instance["outcome"] = "completed"
            instance["external_id"] = operation.get("external_id")
            self._finish_intent(db, work, instance)
            self._save_instance(db, work, instance, "WorkflowNodeCompleted",
                                {"outcome": "completed"})
            return True
        stored = instance.get("receipt") or {}
        receipt = stored.get("receipt")
        payload = stored.get("payload")
        if not isinstance(receipt, dict):
            # The receipt has not been captured yet. Nothing about the
            # effect is guessed: the node keeps waiting for the receipt.
            return self._expire_if_due(db, work, instance, now)
        findings = []
        if not receipt_is_valid(receipt, operation["document_digest"]):
            findings.append(_finding("WORKFLOW_RECEIPT_INVALID",
                                     "The receipt does not match the operation"))
        action = receipt.get("action")
        if action is not None and action != operation["capability"]:
            findings.append(_finding("WORKFLOW_RECEIPT_ACTION_MISMATCH",
                                     "The receipt names another action"))
        origin = stored.get("origin") or {}
        if (origin.get("externalId")
                and receipt.get("external_id") != origin.get("externalId")):
            findings.append(_finding("WORKFLOW_RECEIPT_LINK_MISMATCH",
                                     "The receipt does not belong to the recorded effect"))
        if not isinstance(payload, dict):
            findings.append(_finding("WORKFLOW_OUTPUT_MISSING",
                                     "The receipt carries no business payload"))
            payload = None
        validation = output.get("validation") or {}
        validator_id = validation.get("validator")
        validator_version = validation.get("validator_version")
        check_report = []
        if payload is not None:
            problems, check_report = self._validate_output_material(
                db, work, node_id, node, instance, payload, "output",
                operation["capability"])
            findings.extend(problems)
        if findings:
            instance["findings"] = _bounded(findings)
            instance["check_results"] = self._ordered_report(node, check_report)
            instance["quality"] = {
                "declared": True, "mode": "rejected",
                "validator": ({"id": validator_id, "version": validator_version}
                              if validator_id else None)}
            # The effect stays recorded as what it was: it really happened.
            instance["effect"] = effect
            instance["state"] = "failed"
            instance["outcome"] = "failed"
            instance["reason"] = "WORKFLOW_OUTPUT_INVALID"
            instance["external_id"] = operation.get("external_id")
            self._finish_intent(db, work, instance)
            self._save_instance(db, work, instance, "WorkflowOutputRejected", {
                "outcome": "failed", "reason": "WORKFLOW_OUTPUT_INVALID",
                "effect": effect, "findings": instance["findings"]})
            return True
        reference = None
        if output.get("object"):
            reference = self._write_object(db, work["id"], output["object"], payload)
            instance["output"] = reference
        instance["check_results"] = self._ordered_report(node, check_report)
        instance["quality"] = {
            "declared": True, "mode": "validated",
            "validator": ({"id": validator_id, "version": validator_version}
                          if validator_id else None)}
        instance["effect"] = effect
        instance["state"] = "completed"
        instance["outcome"] = "completed"
        instance["external_id"] = operation.get("external_id")
        if output.get("evidence_kind"):
            self._write_output_proof(db, work, node_id, instance, output, reference,
                                     effect, payload)
        self._finish_intent(db, work, instance)
        self._save_instance(db, work, instance, "WorkflowNodeCompleted",
                            {"outcome": "completed", "output": reference})
        return True

    @staticmethod
    def _ordered_report(node, report) -> List[Dict[str, Any]]:
        """The report in the order the definition declares its criteria.

        A reader sees the criteria of a node in the order the protected
        definition declares them, whichever judge produced the verdict.
        """
        order = {declaration["id"]: index
                 for index, declaration
                 in enumerate(WorkflowEngine._check_declarations(node))}
        return sorted(report,
                      key=lambda entry: order.get(entry.get("checkId"), len(order)))

    def _report_findings(self, node, report) -> List[Dict[str, Any]]:
        """The quality of a validator's per-criterion report.

        A report is never accepted on the strength of its verdict alone: it
        names declared criteria only, carries a reason, carries the evidence
        of a pass, and comes from the validator the criterion was bound to.
        """
        findings = []
        items = [{"check": entry.get("checkId"), "verdict": entry.get("verdict"),
                  "reason": entry.get("reason"), "evidence": entry.get("evidence")}
                 for entry in report]
        findings.extend(self._criterion_findings(node, items))
        for entry in report:
            bound = self._bound_validator_for(node, entry.get("checkId"))
            if bound and (bound.get("validator") != entry.get("validator")
                          or bound.get("validator_version") != entry.get("validatorVersion")):
                findings.append(_finding("WORKFLOW_CHECK_VALIDATOR_MISMATCH",
                                         "The verdict came from a validator the "
                                         "criterion was not bound to",
                                         location=str(entry.get("checkId"))))
        return findings

    def _write_output_proof(self, db, work, node_id, instance, output, reference,
                            effect, payload) -> Optional[str]:
        """The engine's own proof that the external event really happened.

        The proof binds the work, the node, the attempt, the object revision
        and digest and the event provenance, so a wait that awaits this event
        can never be satisfied by the proof of an earlier attempt.
        """
        kind = output.get("evidence_kind")
        if not kind:
            return None
        event_id = "wf:" + str(effect.get("operationId"))
        row = db.execute("SELECT 1 FROM evidence WHERE source=? AND event_id=?",
                         (WORKFLOW_EVENT_SOURCE, event_id)).fetchone()
        if row is not None:
            return event_id
        data = {"node": node_id, "attempt": instance["attempt"], "work": work["id"],
                "object": reference, "external_id": effect.get("externalId"),
                "operation_id": effect.get("operationId"),
                "capability": effect.get("capability"), "payload": payload}
        proof = {"id": uuid.uuid4().hex, "source": WORKFLOW_EVENT_SOURCE,
                 "event_id": event_id, "kind": kind, "status": "verified",
                 "data": data}
        db.execute("INSERT INTO evidence VALUES (?,?,?,?,?)",
                   (WORKFLOW_EVENT_SOURCE, event_id, work["id"], digest(proof),
                    canonical(proof)))
        return event_id

    def _settle_wait(self, db, work, spec, node_id, instance, now) -> bool:
        match = instance.get("match") or {}
        if match.get("timeout"):
            return self._expire_if_due(db, work, instance, now)
        if match.get("evidence_kind"):
            proof = self._wait_evidence(db, work, node_id, instance, match)
            if proof is None:
                return self._expire_if_due(db, work, instance, now)
            return self._settle_wait_matched(db, work, spec, node_id, instance, now,
                                             proof, match)
        if match.get("node_completed"):
            context = _Context(self, db, work)
            if context.node_completed(match["node_completed"]) is not True:
                return self._expire_if_due(db, work, instance, now)
            return self._settle_wait_on_node(db, work, spec, node_id, instance, now,
                                             match)
        return self._expire_if_due(db, work, instance, now)

    def _wait_evidence(self, db, work, node_id, instance, match):
        """The verified proof that satisfies this wait, if there is one.

        A bound wait only accepts a proof of the node it names, at the
        attempt it awaits: an old proof never satisfies a new attempt. A
        subject pins the proof to the current revision of the object it
        covers, so a superseded object is not covered either.
        """
        kind = match["evidence_kind"]
        subject = match.get("subject") or {}
        bind = match.get("bind") or {}
        expected_attempt = None
        if bind.get("node"):
            if bind.get("attempt") is not None:
                expected_attempt = bind["attempt"]
            else:
                target = self._latest_instance(db, work["id"], bind["node"])
                if target is None:
                    return None
                expected_attempt = target["attempt"]
        for proof in self.runtime._proofs(db, work["id"]):
            if proof["status"] != "verified" or proof["kind"] != kind:
                continue
            data = proof.get("data") or {}
            if bind.get("node"):
                if data.get("node") != bind["node"]:
                    continue
                if (expected_attempt is not None
                        and data.get("attempt") != expected_attempt):
                    continue
            if subject.get("object"):
                name = subject["object"]
                reference = data.get("object")
                if isinstance(reference, dict):
                    row = self._object_row(db, work["id"], name)
                    if row is None:
                        continue
                    if reference.get("name") != name:
                        continue
                    if reference.get("revision") != row["revision"]:
                        continue
                    if reference.get("digest") != row["digest"]:
                        continue
                elif not self._proof_covers_object(db, work["id"], data, name):
                    continue
            return proof
        return None

    def _settle_wait_matched(self, db, work, spec, node_id, instance, now, proof,
                              match) -> bool:
        """Settle a wait on the proof it matched.

        The binding that was matched is recorded: the work, the node, the
        attempt, the object revision and digest, and the provenance of the
        event. The output the node declares is validated before the workflow
        routes onward.
        """
        data = proof.get("data") or {}
        reference = data.get("object") if isinstance(data.get("object"), dict) else None
        bind = match.get("bind") or {}
        subject = match.get("subject") or {}
        bound_attempt = None
        if bind.get("node"):
            if bind.get("attempt") is not None:
                bound_attempt = bind["attempt"]
            else:
                target = self._latest_instance(db, work["id"], bind["node"])
                bound_attempt = target["attempt"] if target else None
        instance["wait_match"] = {
            "mode": "bound" if (bind.get("node") or subject.get("object")) else "kind_only",
            "evidenceKind": proof["kind"], "source": proof["source"],
            "eventId": proof["event_id"], "work": work["id"], "node": node_id,
            "attempt": instance["attempt"], "boundNode": bind.get("node"),
            "boundAttempt": bound_attempt, "object": reference}
        payload = data.get("payload") if isinstance(data.get("payload"), dict) else data
        return self._settle_wait_output(db, work, spec, node_id, instance, now, payload)

    def _settle_wait_on_node(self, db, work, spec, node_id, instance, now,
                             match) -> bool:
        """Settle a wait that awaits the completion of another node."""
        target = self._latest_instance(db, work["id"], match["node_completed"])
        reference = (target or {}).get("output") or {}
        payload = None
        if reference.get("name"):
            row = self._object_at(db, work["id"], reference["name"],
                                  reference["revision"])
            if row is not None:
                payload = json.loads(row["body"])
        instance["wait_match"] = {
            "mode": "node", "evidenceKind": None, "source": None,
            "eventId": None, "work": work["id"], "node": node_id,
            "attempt": instance["attempt"], "boundNode": match["node_completed"],
            "boundAttempt": (target or {}).get("attempt"), "object": reference}
        return self._settle_wait_output(db, work, spec, node_id, instance, now, payload)

    def _settle_wait_output(self, db, work, spec, node_id, instance, now,
                             payload) -> bool:
        """Validate the output a wait declares before the workflow routes on."""
        node = spec["nodes"][node_id]
        output = node.get("output") or {}
        declarations = self._check_declarations(node)
        if not output and not declarations:
            instance["quality"] = {"declared": False, "mode": "undeclared"}
            instance["state"] = "completed"
            instance["outcome"] = "completed"
            self._finish_intent(db, work, instance)
            self._save_instance(db, work, instance, "WorkflowNodeCompleted",
                                {"outcome": "completed"})
            return True
        findings = []
        validation = output.get("validation") or {}
        validator_id = validation.get("validator")
        validator_version = validation.get("validator_version")
        check_report = []
        if not isinstance(payload, dict):
            findings.append(_finding("WORKFLOW_OUTPUT_MISSING",
                                     "The matched evidence carries no payload"))
            payload = {}
        problems, check_report = self._validate_output_material(
            db, work, node_id, node, instance, payload, "output")
        findings.extend(problems)
        if findings:
            instance["findings"] = _bounded(findings)
            instance["check_results"] = self._ordered_report(node, check_report)
            instance["quality"] = {
                "declared": True, "mode": "rejected",
                "validator": ({"id": validator_id, "version": validator_version}
                              if validator_id else None)}
            instance["state"] = "failed"
            instance["outcome"] = "failed"
            instance["reason"] = "WORKFLOW_OUTPUT_INVALID"
            self._finish_intent(db, work, instance)
            self._save_instance(db, work, instance, "WorkflowOutputRejected", {
                "outcome": "failed", "reason": "WORKFLOW_OUTPUT_INVALID",
                "findings": instance["findings"]})
            return True
        reference = None
        if output.get("object"):
            reference = self._write_object(db, work["id"], output["object"], payload)
            instance["output"] = reference
        instance["check_results"] = self._ordered_report(node, check_report)
        instance["quality"] = {
            "declared": True, "mode": "validated",
            "validator": ({"id": validator_id, "version": validator_version}
                          if validator_id else None)}
        instance["state"] = "completed"
        instance["outcome"] = "completed"
        self._finish_intent(db, work, instance)
        self._save_instance(db, work, instance, "WorkflowNodeCompleted",
                            {"outcome": "completed", "output": reference})
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
            if reason == "WORKFLOW_OUTPUT_INVALID" and node.get("on_failure") == node_id:
                # The external effect of this node really happened. Routing
                # back into it would ask for the same effect again.
                return None
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
        if set(payload) != {"node", "attempt", "object", "result", "input_digest"}:
            raise WorkflowError("submit_node_result requires exactly node, attempt, "
                                "object, result and input_digest")
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
        if instance["state"] == "waiting":
            # The node waits for material: its result is not accepted
            # until the manager resumes it. Nothing is stored.
            return self.runtime._reject("WORKFLOW_NODE_WAITING", version, [node_id])
        if instance["state"] != "running":
            return self.runtime._reject("WORKFLOW_ATTEMPT_STALE", version, [node_id])
        if payload["input_digest"] != instance.get("input_digest"):
            # A candidate produced from a superseded input is refused: the
            # content it was derived from is not the content in force.
            return self.runtime._reject("WORKFLOW_INPUT_STALE", version, [node_id])
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
        check_report = []
        if validator_id is not None:
            validator = self.validators.resolve(validator_id, validator_version)
            if validator is None:
                return self.runtime._reject("WORKFLOW_VALIDATOR_UNKNOWN", version,
                                            [{"validator": str(validator_id),
                                              "validator_version": str(validator_version)}])
            # The output validator judges the criteria that are declared
            # for a program check. A criterion another judge owns keeps its
            # own identifier and its own record.
            check_ids = [declaration["id"]
                         for declaration in self._check_declarations(node)
                         if declaration.get("method") in (None, "PROGRAM")]
            reported = self._output_validator_call(
                db, work, instance,
                {"node": node_id, "attempt": attempt, "checks": check_ids},
                result, validator)
            raw_findings, raw_checks = self._split_validator_report(reported)
            for problem in raw_findings:
                findings.append(_finding(problem.get("code", "VALIDATOR_REJECTED"),
                                         problem.get("message", "The validator rejected the candidate"),
                                         location=problem.get("location", "")))
            check_report = self._check_report_from_validator(
                node, raw_checks, validator_id, validator_version,
                instance.get("input_digest"), digest(result), int(time.time()))
            missing = self._missing_check_results(node, check_report, "PROGRAM")
            if missing:
                findings.append(_finding("WORKFLOW_CHECK_RESULT_MISSING",
                                         "A declared criterion has no verdict from the validator",
                                         checks=missing))
            for entry in check_report:
                bound = self._bound_validator_for(node, entry.get("checkId"))
                if bound and (bound.get("validator") != validator_id
                              or bound.get("validator_version") != validator_version):
                    findings.append(_finding("WORKFLOW_CHECK_VALIDATOR_MISMATCH",
                                             "The verdict came from a validator the "
                                             "criterion was not bound to",
                                             location=str(entry.get("checkId"))))
        if findings:
            instance["findings"] = _bounded(findings)
            instance["state"] = "failed"
            instance["outcome"] = "failed"
            instance["reason"] = "WORKFLOW_RESULT_INVALID"
            instance["validator"] = {"id": validator_id, "version": validator_version}
            instance["quality"] = {"declared": True, "mode": "rejected",
                                   "validator": {"id": validator_id,
                                                 "version": validator_version}}
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
        instance["check_results"] = self._ordered_report(node, check_report)
        instance["validator"] = {"id": validator_id, "version": validator_version}
        instance["quality"] = {"declared": True, "mode": "validated",
                               "validator": {"id": validator_id,
                                             "version": validator_version}}
        review = node.get("review")
        if isinstance(review, dict) and review.get("evidence_kind"):
            # The candidate is produced; the independent review is now due.
            self._finish_intent(db, work, instance)
            instance["state"] = "submitted"
            self._start_review(db, work, spec, node_id, instance, int(time.time()))
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
    # Material waiting
    # ------------------------------------------------------------------

    def _request_material_wait(self, db, actor, work, payload, version):
        """Park the current agent node until the manager supplies material.

        Business material is not candidate quality. The wait keeps the
        attempt, withdraws the agent's durable intent and refuses result
        acceptance; it opens no rework attempt and spends no quality
        allowance, so a workflow that waited may still complete on the
        attempt it started with.

        The request is pinned to the exact node, attempt and input digest
        the caller observed, so a wait that was decided against a moved
        work is refused instead of parking the wrong attempt.
        """
        if set(payload) != {"node", "attempt", "input_digest", "reason",
                            "request_version"}:
            raise WorkflowError("request_material_wait requires exactly node, "
                                "attempt, input_digest, reason and request_version")
        node_id = payload["node"]
        attempt = payload["attempt"]
        reason = payload["reason"]
        if not isinstance(node_id, str) or type(attempt) is not int:
            raise WorkflowError("request_material_wait requires a node id and "
                                "an attempt")
        if payload["request_version"] != MATERIAL_WAIT_REQUEST_VERSION:
            raise WorkflowError("request_material_wait requires request_version "
                                + str(MATERIAL_WAIT_REQUEST_VERSION))
        if (not isinstance(reason, str) or not reason
                or len(reason) > MAX_WAIT_REASON_CHARS):
            raise WorkflowError("the reason must be a nonempty bounded string")
        if not isinstance(payload["input_digest"], str) or not payload["input_digest"]:
            raise WorkflowError("input_digest must be a nonempty string")
        if not self.runtime._manager(actor, work):
            return self.runtime._reject("AUTHORITY_DENIED", version)
        if work.get("cancellation"):
            return self.runtime._reject("CANCELLATION_ACTIVE", version)
        spec = self._spec_in(db, work)
        if spec is None:
            return self.runtime._reject("WORKFLOW_NOT_BOUND", version)
        node = spec["nodes"].get(node_id)
        if node is None:
            return self.runtime._reject("WORKFLOW_NODE_UNKNOWN", version, [node_id])
        if node.get("kind") != "agent":
            # A human node asks for material through its decision; an
            # automatic node owns an effect. Neither is a manager wait.
            return self.runtime._reject("WORKFLOW_NODE_NOT_WAITABLE", version,
                                        [node_id])
        if work.get("workflow_current") != node_id:
            return self.runtime._reject("WORKFLOW_NODE_NOT_CURRENT", version,
                                        [node_id])
        instance = self._latest_instance(db, work["id"], node_id)
        if instance is None or instance["attempt"] != attempt:
            return self.runtime._reject("WORKFLOW_ATTEMPT_STALE", version, [node_id])
        if instance["state"] == "waiting":
            return self.runtime._reject("WORKFLOW_NODE_WAITING", version, [node_id])
        if instance["state"] != "running":
            return self.runtime._reject("WORKFLOW_NODE_NOT_WAITABLE", version,
                                        [node_id])
        if payload["input_digest"] != instance.get("input_digest"):
            # The caller pinned a digest the node does not hold: the
            # attempt it saw is not the attempt in force.
            return self.runtime._reject("WORKFLOW_INPUT_STALE", version, [node_id])
        dependencies = [dict(entry) for entry in (instance.get("inputs") or [])]
        subject = instance.get("subject")
        if isinstance(subject, dict):
            dependencies.append(dict(subject))
        instance["state"] = "waiting"
        instance["material_wait"] = {
            "state": "waiting",
            "request_version": payload["request_version"],
            "requested_by": actor,
            "reason": reason,
            "requested_at": int(time.time()),
            "input_digest": instance.get("input_digest"),
            "dependencies": dependencies,
            "adoptions": [],
            "resumed": None,
        }
        # The agent's own task is withdrawn: nothing asks the executor to
        # keep working while the material is missing.
        self._cancel_intents(db, work["id"], node_id, attempt)
        work["workflow_status"] = "waiting"
        self._save_instance(db, work, instance, "WorkflowMaterialWaitRequested",
                            {"actor": actor, "reason": reason,
                             "dependencies": dependencies})
        return self.runtime._accepted(work, node=node_id, attempt=attempt,
                                      wait=dict(instance["material_wait"]))

    def _adopt_material(self, db, actor, work, payload, version):
        """Adopt externally provided material under an active wait.

        The adopted material becomes a **new immutable revision** of the
        named object: the historical revisions and the decisions that were
        made on them stay on the record, and the adoption itself re-runs
        nothing. The wait accepts the adopted revision; the node is still
        waiting until the manager resumes it.
        """
        if set(payload) != {"node", "attempt", "name", "object",
                            "request_version"}:
            raise WorkflowError("adopt_material requires exactly node, attempt, "
                                "name, object and request_version")
        node_id = payload["node"]
        attempt = payload["attempt"]
        name = payload["name"]
        body = payload["object"]
        if not isinstance(node_id, str) or type(attempt) is not int:
            raise WorkflowError("adopt_material requires a node id and an attempt")
        if not isinstance(name, str) or not name:
            raise WorkflowError("adopt_material requires a nonempty object name")
        if not isinstance(body, dict):
            raise WorkflowError("adopt_material requires an object body")
        if payload["request_version"] != MATERIAL_WAIT_REQUEST_VERSION:
            raise WorkflowError("adopt_material requires request_version "
                                + str(MATERIAL_WAIT_REQUEST_VERSION))
        if not self.runtime._manager(actor, work):
            return self.runtime._reject("AUTHORITY_DENIED", version)
        if work.get("cancellation"):
            return self.runtime._reject("CANCELLATION_ACTIVE", version)
        spec = self._spec_in(db, work)
        if spec is None:
            return self.runtime._reject("WORKFLOW_NOT_BOUND", version)
        instance = self._latest_instance(db, work["id"], node_id)
        if instance is None or instance["attempt"] != attempt:
            return self.runtime._reject("WORKFLOW_ATTEMPT_STALE", version, [node_id])
        wait = instance.get("material_wait")
        if instance["state"] != "waiting" or not isinstance(wait, dict):
            return self.runtime._reject("WORKFLOW_NOT_WAITING", version, [node_id])
        dependencies = wait.get("dependencies") or []
        entry = next((item for item in dependencies
                      if item.get("name") == name), None)
        if entry is None:
            # Only the material the wait is actually about may be adopted:
            # an adoption of anything else would be a silent write.
            return self.runtime._reject("WORKFLOW_MATERIAL_NOT_DEPENDENCY",
                                        version, [name])
        adoptions = wait.get("adoptions") or []
        if len(adoptions) >= MAX_WAIT_ADOPTIONS:
            return self.runtime._reject("WORKFLOW_ADOPTION_LIMIT_EXCEEDED",
                                        version, [name])
        if len(canonical(body).encode("utf-8")) > MAX_OUTPUT_BYTES:
            return self.runtime._reject("WORKFLOW_MATERIAL_TOO_LARGE", version,
                                        [name])
        reference = self._write_object(db, work["id"], name, body)
        entry["revision"] = reference["revision"]
        entry["digest"] = reference["digest"]
        entry["adopted"] = True
        adoptions.append({"name": name, "revision": reference["revision"],
                          "digest": reference["digest"], "adopted_by": actor,
                          "adopted_at": int(time.time())})
        wait["dependencies"] = dependencies
        wait["adoptions"] = adoptions
        instance["material_wait"] = wait
        self._save_instance(db, work, instance, "WorkflowMaterialAdopted",
                            {"actor": actor, "name": name,
                             "revision": reference["revision"],
                             "digest": reference["digest"]})
        return self.runtime._accepted(work, node=node_id, attempt=attempt,
                                      adoption=dict(adoptions[-1]),
                                      wait=copy.deepcopy(wait))

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

    @staticmethod
    def _split_validator_report(reported):
        """A validator may answer with findings, or with findings and a
        per-criterion report. Both shapes are accepted; neither is coerced."""
        if isinstance(reported, dict):
            return (list(reported.get("findings") or []),
                    list(reported.get("checks") or []))
        return (list(reported or []), [])

    def _check_report_from_validator(self, node, raw_checks, validator_id,
                                     validator_version, input_digest=None,
                                     output_digest=None, at=None
                                     ) -> List[Dict[str, Any]]:
        """The persisted criterion report of a validated candidate."""
        report = []
        for entry in raw_checks:
            if not isinstance(entry, dict):
                continue
            bound = self._bound_validator_for(node, entry.get("check"))
            report.append({
                "checkId": entry.get("check"),
                "verdict": entry.get("verdict"),
                "reason": entry.get("reason"),
                "evidence": entry.get("evidence") or [],
                "method": "PROGRAM",
                "criterionVersion": (bound or {}).get("criterion_version"),
                "decidedBy": None,
                "validator": validator_id,
                "validatorVersion": validator_version,
                "reviewedInputDigest": input_digest,
                "reviewedOutputDigest": output_digest,
                "at": at,
            })
        return report

    @staticmethod
    def _bound_validator_for(node, check_id):
        """The validator a criterion is bound to, if the definition says so."""
        for declaration in WorkflowEngine._check_declarations(node):
            if declaration.get("id") == check_id and declaration.get("validator"):
                return declaration
        return None

    @staticmethod
    def _output_required_for(node, decision) -> bool:
        """Whether the node's named output is required for this decision.

        The default is the historical one: a declared output is required
        for **every** decision. A published human node may narrow that
        explicitly - the declaration is protected material, and it is the
        declaration that decides, never the caller.
        """
        output = node.get("output") or {}
        declared = output.get("on_decisions")
        if decision == "approved":
            # An approval always needs its acceptance record: the named
            # output is what says the work was accepted, so no declaration
            # may exempt it.
            return True
        if declared is None:
            return True
        return decision in declared

    def _record_decision(self, db, actor, work, payload, version,
                         command_id=None) -> dict:
        """Admit one human decision.

        The command's actor is the *ingress source* — the platform channel
        configured for this node's evidence kind. The actual decider is in
        the payload and is checked against the resolved assignment. The
        write happens in the runtime's command transaction, so the caller's
        compare-and-swap version, the evidence intake and the decision
        admission are one atomic step.
        """
        required = {"node", "attempt", "decision", "digest", "revision",
                    "actor", "items"}
        if (not required <= set(payload)
                or set(payload) - required - {"event_id", "result"}):
            raise WorkflowError("record_decision requires exactly node, attempt, "
                                "decision, digest, revision, actor and items, "
                                "and may carry an optional result")
        node_id = payload["node"]
        attempt = payload["attempt"]
        if not isinstance(node_id, str) or type(attempt) is not int:
            raise WorkflowError("record_decision requires a node id and an attempt")
        if payload["decision"] not in ("approved", "rejected", "request_material"):
            raise WorkflowError("record_decision requires a known decision")
        if not isinstance(payload["actor"], str) or not payload["actor"]:
            raise WorkflowError("record_decision requires the actor who decided")
        spec = self._spec_in(db, work)
        if spec is None:
            return self.runtime._reject("WORKFLOW_NOT_BOUND", version)
        node = spec["nodes"].get(node_id)
        if node is None or node.get("kind") != "human":
            return self.runtime._reject("WORKFLOW_NODE_UNKNOWN", version, [str(node_id)])
        kind = node.get("evidence_kind")
        if self.runtime._policy_for(work).evidence_sources.get(kind) != actor:
            return self.runtime._reject("AUTHORITY_DENIED", version)
        instance = self._latest_instance(db, work["id"], node_id)
        if (instance is None or instance["attempt"] != attempt
                or instance["state"] != "running"):
            return self.runtime._reject("WORKFLOW_ATTEMPT_STALE", version, [node_id])
        subject = instance.get("subject")
        if (subject is None or subject["digest"] != payload["digest"]
                or subject["revision"] != payload["revision"]):
            return self.runtime._reject("WORKFLOW_DECISION_STALE", version)
        effective = self._effective_authority(work, node_id, node)
        if effective is None or effective != payload["actor"]:
            return self.runtime._reject("WORKFLOW_AUTHORITY_MISMATCH", version)
        findings = self._criterion_findings(node, payload["items"])
        if findings:
            return self.runtime._reject("WORKFLOW_CHECK_REPORT_INVALID", version,
                                        _bounded(findings))
        output = node.get("output") or {}
        result = payload.get("result")
        if result is not None and not isinstance(result, dict):
            raise WorkflowError("record_decision requires an object result")
        if result is not None and not output:
            return self.runtime._reject("WORKFLOW_OUTPUT_UNDECLARED", version,
                                        [node_id])
        output_required = self._output_required_for(node, payload["decision"])
        if result is not None and not output_required:
            # The declaration exempts this decision from the named output: a
            # supplied record would be an acceptance output for a decision
            # that must not have one, so it is refused, not written.
            return self.runtime._reject("WORKFLOW_OUTPUT_NOT_REQUIRED", version,
                                        [node_id])
        data = {"decision": payload["decision"], "digest": payload["digest"],
                "revision": payload["revision"], "node": node_id, "attempt": attempt,
                "actor": payload["actor"], "items": payload["items"]}
        event_id = payload.get("event_id") or command_id or uuid.uuid4().hex
        receipt = self.runtime._receive(db, actor, work,
                                        {"event_id": event_id, "kind": kind,
                                         "data": data})
        if receipt.get("decision") != "accepted":
            return receipt
        if output and output_required:
            # The named record the decision carries is judged and written in
            # the same compare-and-swap guarded command as the decision
            # itself: no separate write can rebase the caller's version.
            self._apply_decision_output(db, work, node_id, node, instance,
                                         output, result, payload["actor"], actor)
            # The record was written in this transaction, so the receipt
            # reports the version the work is at now.
            receipt["result_state_version"] = work["state_version"]
        return receipt

    def _apply_decision_output(self, db, work, node_id, node, instance, output,
                               result, actor, source) -> None:
        """Judge and write the named record a human decision carries.

        The decision itself is genuine and stays: it is the record of what
        the human decided. The named output is judged on its own — against
        the declared shape and the pinned validator — and a rejected record
        is not written, so the previous revision of the object is never
        overwritten by a record that failed its quality.
        """
        if not output:
            # Nothing was declared: the node completes as it always did and
            # the record says plainly that nothing was checked.
            instance["quality"] = {"declared": False, "mode": "undeclared"}
            self._save_instance(db, work, instance, "WorkflowNodeCompleted",
                                {"actor": actor})
            return
        if result is None:
            # The node declared a named output and the decision did not carry
            # it. The decision stands; the node keeps waiting for the record.
            instance["output_findings"] = _bounded([_finding(
                "WORKFLOW_OUTPUT_MISSING",
                "The decision carries no record for the declared output",
                node=node_id, object=output.get("object"))])
            instance["quality"] = {"declared": True, "mode": "missing",
                                   "validator": None}
            self._save_instance(db, work, instance, "WorkflowOutputMissing",
                                {"actor": actor})
            return
        findings, check_report = self._validate_output_material(
            db, work, node_id, node, instance, result, "decision")
        validation = output.get("validation") or {}
        if findings:
            instance["output_findings"] = _bounded(findings)
            instance["findings"] = _bounded((instance.get("findings") or []) + findings)
            instance["quality"] = {
                "declared": True, "mode": "rejected",
                "validator": {"id": validation.get("validator"),
                              "version": validation.get("validator_version")}}
            instance["check_results"] = self._ordered_report(node, check_report)
            self._save_instance(db, work, instance, "WorkflowOutputRejected", {
                "actor": actor, "source": source, "outcome": "rejected",
                "findings": instance["output_findings"]})
            return
        reference = self._write_object(db, work["id"], output["object"], result)
        instance["output"] = reference
        instance["check_results"] = self._ordered_report(node, check_report)
        instance["quality"] = {
            "declared": True, "mode": "validated",
            "validator": {"id": validation.get("validator"),
                          "version": validation.get("validator_version")}}
        # The binding the record was made under: who decided, through which
        # channel, for which node and attempt, against which subject and
        # inputs, and with which digest of its own.
        instance["output_binding"] = {
            "actor": actor, "source": source, "node": node_id,
            "attempt": instance["attempt"], "object": reference,
            "subject": instance.get("subject"),
            "inputDigest": instance.get("input_digest"),
            "outputDigest": reference["digest"]}
        self._save_instance(db, work, instance, "WorkflowOutputAccepted", {
            "actor": actor, "source": source, "output": reference})

    # ------------------------------------------------------------------
    # Workflow-success finalization
    # ------------------------------------------------------------------

    def _finalize_success(self, db, actor, work, payload, version):
        """Accept a successful workflow and freeze it, in one transaction.

        The finalization is an acceptance decision, not a read: it verifies
        the declared terminal, the settled material, the settled effects and
        the settled obligations, and only then freezes the work and records
        the exact final snapshot it accepted. A workflow that is not
        verifiably successful is never frozen, and a frozen workflow is never
        routed, revised, cancelled or reopened again.
        """
        if payload:
            raise WorkflowError("finalize_workflow_success takes no payload")
        if self.runner is None:
            # No trusted runner is configured: the acceptance has no actor.
            return self.runtime._reject(WORKFLOW_RUNNER_UNCONFIGURED, version)
        if actor != self.runner:
            # The acceptance belongs to the protected runner, never to an
            # agent, a reviewer or the work owner.
            return self.runtime._reject(WORKFLOW_RUNNER_MISMATCH, version)
        binding = work.get("workflow")
        if not binding:
            return self.runtime._reject("WORKFLOW_NOT_BOUND", version)
        spec = self._spec_in(db, work)
        if spec is None:
            return self.runtime._reject("WORKFLOW_TEMPLATE_UNKNOWN", version)
        if work.get("cancellation"):
            return self.runtime._reject(WORKFLOW_CANCELLED, version)
        latest: Dict[str, Dict[str, Any]] = {}
        for instance in self._instances(db, work["id"]):
            latest[instance["node"]] = instance

        terminal = work.get("workflow_terminal") or {}
        terminal_node = latest.get(terminal.get("node")) or {}
        # The state of the terminal node is the fact that matters: a
        # completed node is a node that finished successfully, whatever its
        # kind calls that verdict ("completed", "approved"). A node that
        # failed, expired, was cancelled or whose output was refused is not
        # a success, whatever the routing says.
        if terminal_node and (terminal_node.get("state") != "completed"
                              or terminal_node.get("outcome")
                              not in SUCCESSFUL_NODE_OUTCOMES):
            return self.runtime._reject(WORKFLOW_TERMINAL_NOT_COMPLETED,
                                        version, [{
                                            "node": terminal.get("node"),
                                            "state": terminal_node.get("state"),
                                            "outcome": terminal.get("outcome"),
                                            "reason": terminal.get("reason")}])
        finished = (work.get("workflow_status") == "finished"
                    and work.get("workflow_current") is None)
        if not finished:
            # "Finished" is the precondition; a running, a blocked or a
            # reopened workflow is never accepted.
            return self.runtime._reject(WORKFLOW_NOT_FINISHED, version, [{
                "status": work.get("workflow_status"),
                "currentNode": work.get("workflow_current")}])
        if not terminal_node:
            # A finished workflow without a readable terminal instance has
            # no terminal to accept.
            return self.runtime._reject(WORKFLOW_TERMINAL_NOT_COMPLETED,
                                        version, [{
                                            "node": terminal.get("node"),
                                            "outcome": terminal.get("outcome"),
                                            "reason": terminal.get("reason")}])
        declared_terminals = spec.get("terminal") or []
        if declared_terminals and terminal.get("node") not in declared_terminals:
            return self.runtime._reject(WORKFLOW_TERMINAL_NOT_DECLARED,
                                        version, [{
                                            "node": terminal.get("node"),
                                            "declared": list(declared_terminals)}])

        operations = []
        unresolved = []
        for row in db.execute("SELECT body FROM operations WHERE work_id=?",
                              (work["id"],)).fetchall():
            operation = json.loads(row[0])
            operations.append({"id": operation["id"],
                               "capability": operation.get("capability"),
                               "businessKey": operation.get("business_key"),
                               "status": operation.get("status"),
                               "dispatchState": operation.get("dispatch_state"),
                               "externalId": operation.get("external_id")})
            if (operation.get("status") not in ("confirmed_succeeded",
                                                "confirmed_failed")
                    and operation.get("dispatch_state") != "cancelled"):
                # A prepared, dispatched or unknown effect is not settled.
                unresolved.append(operation["id"])
        if unresolved:
            return self.runtime._reject(WORKFLOW_EFFECT_UNRESOLVED, version,
                                        unresolved)

        requirements = []
        blockers = []
        for requirement in work.get("requirements") or []:
            requirements.append({"id": requirement.get("id"),
                                 "ruleId": requirement.get("rule_id"),
                                 "applicability": requirement.get("applicability"),
                                 "fulfillment": requirement.get("fulfillment")})
            applicability = requirement.get("applicability")
            if applicability in ("unknown", "conflict"):
                blockers.append(requirement.get("id"))
            elif (applicability == "applicable"
                    and requirement.get("fulfillment") != "satisfied"):
                blockers.append(requirement.get("id"))
        if blockers:
            return self.runtime._reject(WORKFLOW_REQUIREMENT_UNSATISFIED, version,
                                        blockers)

        unsettled = []
        not_completed = []
        quality_open = []
        checks_open = []
        passed_checks = set()
        for node_id in sorted(latest):
            instance = latest[node_id]
            node = spec["nodes"].get(node_id) or {}
            if instance.get("state") not in TERMINAL_NODE_STATES:
                unsettled.append({"node": node_id, "state": instance.get("state")})
                continue
            if (instance.get("state") != "completed"
                    or instance.get("outcome") not in SUCCESSFUL_NODE_OUTCOMES):
                not_completed.append({"node": node_id, "state": instance.get("state"),
                                      "outcome": instance.get("outcome"),
                                      "reason": instance.get("reason")})
            quality = instance.get("quality") or {}
            if quality.get("declared") and quality.get("mode") != "validated":
                quality_open.append({"node": node_id, "mode": quality.get("mode")})
            results = {}
            for entry in instance.get("check_results") or []:
                results.setdefault(entry.get("checkId"), entry)
                if entry.get("verdict") == "passed":
                    passed_checks.add(entry.get("checkId"))
            for declaration in self._check_declarations(node):
                identifier = declaration.get("id")
                if not isinstance(identifier, str) or not identifier:
                    continue
                if declaration.get("required") is False:
                    continue
                entry = results.get(identifier)
                verdict = (entry or {}).get("verdict")
                if verdict == "passed":
                    continue
                if (verdict == "not_applicable"
                        and declaration.get("allow_not_applicable")):
                    # The protected declaration allows this criterion to be
                    # not applicable, and the node's own settlement applied
                    # exactly this rule when it completed.
                    continue
                checks_open.append({"node": node_id, "checkId": identifier,
                                    "verdict": verdict})
        if unsettled:
            return self.runtime._reject(WORKFLOW_NODE_UNSETTLED, version, unsettled)
        if not_completed:
            return self.runtime._reject(WORKFLOW_NODE_NOT_COMPLETED, version,
                                        not_completed)
        if quality_open:
            return self.runtime._reject(WORKFLOW_QUALITY_UNSETTLED, version,
                                        quality_open)
        if checks_open:
            return self.runtime._reject(WORKFLOW_CHECK_UNSATISFIED, version,
                                        checks_open)
        missing = [{"checkId": identifier, "reason": "no passed verdict"}
                   for identifier in (spec.get("required_checks") or [])
                   if identifier not in passed_checks]
        if missing:
            return self.runtime._reject(WORKFLOW_CHECK_UNSATISFIED, version, missing)

        pending = [row[0] for row in db.execute(
            "SELECT id FROM workflow_intents WHERE work_id=? AND status='pending'",
            (work["id"],)).fetchall()]
        if pending:
            return self.runtime._reject(WORKFLOW_INTENT_UNSETTLED, version, pending)

        object_count = db.execute(
            "SELECT COUNT(DISTINCT name) FROM workflow_objects WHERE work_id=?",
            (work["id"],)).fetchone()[0]
        if (object_count > MAX_FINALIZATION_OBJECTS
                or len(latest) > MAX_VIEW_NODES):
            # A snapshot that does not name every object and every node is
            # not the snapshot of the accepted workflow: the acceptance is
            # refused instead of freezing a partial proof.
            return self.runtime._reject(WORKFLOW_SNAPSHOT_UNBOUNDED, version, [{
                "objects": object_count, "nodes": len(latest),
                "maxObjects": MAX_FINALIZATION_OBJECTS,
                "maxNodes": MAX_VIEW_NODES}])
        snapshot = self._final_snapshot(db, work, binding, latest, terminal,
                                        version, actor, operations, requirements)
        work["workflow_finalization"] = snapshot
        # The accepted work is closed: no later command may revise, replace,
        # cancel or reopen it, and no later command may produce an effect.
        work["status"] = "closed"
        work["outcome"] = "succeeded"
        work["completion"] = {"contract": work.get("contract"),
                              "document_digest": work.get("document_digest"),
                              "evidence": list(snapshot["evidence"]),
                              "workflow": {"finalizationId": snapshot["finalizationId"],
                                           "digest": snapshot["digest"]}}
        self.runtime._save(db, work, "WorkflowFinalized", {
            "finalization_id": snapshot["finalizationId"],
            "digest": snapshot["digest"],
            "terminal": snapshot["terminal"],
            "template": snapshot["template"],
            "contract": snapshot["contract"],
            "plan_revision": snapshot["plan"]["revision"],
            "document": snapshot["document"]})
        return self.runtime._accepted(work, finalization=snapshot)

    def _final_snapshot(self, db, work, binding, latest, terminal, version,
                        actor, operations, requirements):
        """The exact final snapshot of the accepted workflow.

        It names the identities the acceptance rests on: the published
        definition, the bound contract, the plan and the document in force,
        every named object revision, every node attempt with its judgment,
        every effect, every obligation and the verified evidence. Bodies are
        not copied: a snapshot names what was accepted, and the material
        stays readable as the object revision it names.
        """
        objects = []
        for row in db.execute("SELECT name,revision,digest FROM workflow_objects "
                              "WHERE work_id=? ORDER BY name,revision",
                              (work["id"],)).fetchall():
            reference = {"name": row["name"], "revision": row["revision"],
                         "digest": row["digest"]}
            if objects and objects[-1]["name"] == reference["name"]:
                objects[-1] = reference
            else:
                objects.append(reference)
        nodes = []
        for node_id in sorted(latest):
            instance = latest[node_id]
            nodes.append({
                "node": node_id,
                "kind": instance.get("kind"),
                "attempt": instance.get("attempt"),
                "state": instance.get("state"),
                "outcome": instance.get("outcome"),
                "reason": instance.get("reason"),
                "actor": instance.get("actor"),
                "inputs": instance.get("inputs") or [],
                "subject": instance.get("subject"),
                "output": instance.get("output"),
                "quality": instance.get("quality"),
                "effect": instance.get("effect"),
                "checks": [{"checkId": entry.get("checkId"),
                            "verdict": entry.get("verdict"),
                            "method": entry.get("method")}
                           for entry in (instance.get("check_results") or [])],
            })
        terminal_instance = latest.get(terminal.get("node")) or {}
        contract = work.get("contract") or {}
        plan = work.get("plan") or {}
        proofs = self.runtime._proofs(db, work["id"])
        snapshot = {
            "finalizationId": uuid.uuid4().hex,
            "workId": work["id"],
            "finalizedBy": actor,
            "finalizedAt": int(time.time()),
            "stateVersion": version + 1,
            "workflowStatus": work.get("workflow_status"),
            "terminal": {"node": terminal.get("node"),
                         "attempt": terminal_instance.get("attempt"),
                         "state": terminal_instance.get("state"),
                         "outcome": terminal.get("outcome"),
                         "reason": terminal.get("reason")},
            "template": {"id": binding.get("template_id"),
                         "version": binding.get("template_version"),
                         "digest": binding.get("digest"),
                         "revision": binding.get("revision")},
            "contract": {"policyId": contract.get("policy_id"),
                         "policyVersion": contract.get("policy_version"),
                         "goal": contract.get("goal"),
                         "revision": contract.get("revision")},
            "plan": {"revision": work.get("plan_revision"),
                     "steps": list(plan.get("steps") or []),
                     "openRequirements": list(plan.get("open_requirements") or []),
                     "replanWhen": list(plan.get("replan_when") or [])},
            "document": {"revision": work.get("document_revision"),
                         "digest": work.get("document_digest")},
            "objects": objects,
            "nodes": nodes,
            "operations": operations,
            "requirements": requirements,
            "evidence": sorted(entry["id"] for entry in proofs
                               if entry.get("status") == "verified"),
        }
        snapshot["digest"] = digest(snapshot)
        return snapshot

    def finalization(self, work_id: str) -> Optional[Dict[str, Any]]:
        """The stored final snapshot of a finalized workflow.

        A read-only answer: the snapshot was written once, by the
        finalization that accepted the workflow, and it never changes.
        """
        with self.runtime._connection() as db:
            work = self.runtime._work(db, work_id)
            return work.get("workflow_finalization")

    def finalization_canonical(self, snapshot: Dict[str, Any]) -> str:
        """The canonical text of an accepted proof.

        It is the exact text a reader hashes: the canonical JSON of the
        snapshot **without** its ``digest`` entry, so that the SHA-256 over
        its UTF-8 bytes is the digest the acceptance recorded. A reader that
        parses the text therefore holds the very snapshot the acceptance
        froze, without reimplementing this canonical form.

        The stored digest is verified first: a snapshot whose digest does
        not match its content yields no text at all.
        """
        if not isinstance(snapshot, dict):
            raise WorkflowError("The accepted proof must be an object")
        body = {key: value for key, value in snapshot.items() if key != "digest"}
        text = canonical(body)
        if digest(body) != snapshot.get("digest"):
            raise WorkflowError("The stored proof does not match its digest")
        return text

    def workflow_finalized(self, work: dict) -> bool:
        """Whether the work carries an accepted, frozen workflow."""
        return bool(work.get("workflow_finalization"))

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
        recorder = _ReceiptRecorder(adapter)
        work_ids = self.workflow_work_ids()
        for work_id in work_ids:
            self.advance(work_id, moment)
        results = []
        for operation_id in self._prepared_operations(work_ids):
            results.append(self.runtime.dispatch(operation_id, recorder))
        self._capture_receipts(recorder)
        for work_id in self.workflow_work_ids():
            self.advance(work_id, moment)
        return results

    def _capture_receipts(self, recorder) -> None:
        """Persist the receipts the adapter returned onto the waiting nodes.

        The receipt is the material the node's output is validated against,
        so it is stored with the node that awaits it: bounded, with the
        origin that links it to the operation it belongs to.
        """
        pending = []
        with self.runtime._connection() as db:
            for work_id in self.workflow_work_ids():
                for instance in self._instances(db, work_id):
                    if instance["state"] not in ("running", "submitted"):
                        continue
                    operation_id = instance.get("operation_id")
                    if not operation_id:
                        continue
                    row = db.execute("SELECT body FROM operations WHERE id=?",
                                     (operation_id,)).fetchone()
                    if row is None:
                        continue
                    operation = json.loads(row[0])
                    if operation["status"] != "confirmed_succeeded":
                        continue
                    pending.append((work_id, instance["node"], instance["attempt"],
                                    operation))
        if not pending:
            return
        captured = []
        for work_id, node_id, attempt, operation in pending:
            receipt = recorder.receipts.get(operation["business_key"])
            if receipt is None:
                # An operation that was confirmed outside this engine is
                # back-filled from the authoritative lookup of the same
                # business key — never from a second effect.
                receipt = recorder.lookup(operation["business_key"])
            if receipt is None:
                continue
            captured.append((work_id, node_id, attempt, operation, receipt))
        if not captured:
            return
        with self.runtime._transaction() as db:
            for work_id, node_id, attempt, operation, receipt in captured:
                self._store_receipt(db, work_id, node_id, attempt, operation,
                                    receipt, recorder.adapter_name)

    def _store_receipt(self, db, work_id, node_id, attempt, operation, receipt,
                       adapter_name) -> None:
        """Write the receipt and its origin onto the node instance."""
        view, payload = _bounded_receipt(receipt)
        if view is None:
            return
        origin = {"operationId": operation["id"], "capability": operation["capability"],
                  "businessKey": operation["business_key"],
                  "externalId": operation.get("external_id"),
                  "digest": operation["document_digest"], "adapter": adapter_name}
        stored = {"receipt": view, "origin": origin, "payload": payload}
        row = db.execute("SELECT body FROM workflow_nodes WHERE work_id=? AND node=? "
                         "AND attempt=?", (work_id, node_id, attempt)).fetchone()
        if row is None:
            return
        instance = json.loads(row[0])
        if instance.get("receipt") == stored:
            return
        instance["receipt"] = stored
        work = self.runtime._work(db, work_id)
        self._save_instance(db, work, instance, "WorkflowReceiptCaptured", {
            "operation_id": operation["id"], "external_id": operation.get("external_id"),
            "adapter": adapter_name})

    def recover(self, adapter, now: Optional[int] = None) -> List[Dict[str, Any]]:
        """Resume progress after a restart.

        Order matters: evidence is evaluated, waits expire, the workflow is
        routed (so newly ready nodes create their intents and operations),
        and only then are uncertain calls reconciled and prepared intents
        dispatched. Uncertain external effects are looked up, never repeated.
        """
        moment = int(time.time()) if now is None else int(now)
        recorder = _ReceiptRecorder(adapter)
        for work_id in self.workflow_work_ids():
            self.runtime.verify_pending(work_id)
            self.runtime.expire_waits(work_id, moment)
            self._cancel_workflow(work_id)
            self.advance(work_id, moment)
        results = self.runtime.recover(recorder, moment)
        self._capture_receipts(recorder)
        # The dispatch above may have confirmed an operation: settle the nodes
        # that were waiting for it.
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

    def attempts(self, work_id: str, node_id: str) -> List[Dict[str, Any]]:
        """The attempt history of one node, with its stored judgments.

        A judgment belongs to the attempt that produced it: the history is
        what a reader consults, not the current state of the node.
        """
        with self.runtime._connection() as db:
            work = self.runtime._work(db, work_id)
            spec = self._spec_in(db, work)
            if spec is None:
                raise WorkflowError("Work has no workflow bound: " + work_id)
            history = []
            for instance in self._instances(db, work_id):
                if instance["node"] != node_id:
                    continue
                history.append({
                    "node": node_id,
                    "attempt": instance["attempt"],
                    "state": instance["state"],
                    "outcome": instance.get("outcome"),
                    "reason": instance.get("reason"),
                    "actor": instance.get("actor"),
                    "inputDigest": instance.get("input_digest"),
                    "output": instance.get("output"),
                    "checkResults": (instance.get("check_results") or [])[:MAX_VIEW_FINDINGS],
                    "quality": instance.get("quality"),
                    "effect": instance.get("effect"),
                    "waitMatch": instance.get("wait_match"),
                    "createdAt": instance.get("created_at"),
                })
        return history

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
                    "checkResults": (instance.get("check_results") or [])[:MAX_VIEW_FINDINGS]
                    if instance else [],
                    "inputDigest": instance.get("input_digest") if instance else None,
                    "actor": instance.get("actor") if instance else None,
                    "blockers": (instance.get("blockers") or [])[:MAX_VIEW_FINDINGS]
                    if instance else [],
                    "intentId": instance.get("intent_id") if instance else None,
                    "checks": (spec["nodes"][node_id] or {}).get("checks") or [],
                    "quality": instance.get("quality") if instance else None,
                    "effect": instance.get("effect") if instance else None,
                    "waitMatch": instance.get("wait_match") if instance else None,
                    "receipt": _receipt_view(instance.get("receipt"))
                    if instance else None,
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
                for declaration in self._check_declarations(spec["nodes"][node_id]):
                    checks.append({
                        "checkId": declaration.get("id"),
                        "node": node_id,
                        "criterion": declaration.get("criterion"),
                        "validator": declaration.get("validator"),
                        "validatorVersion": declaration.get("validator_version")})
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
                "terminalNode": (work.get("workflow_terminal") or {}).get("node"),
                "terminalOutcome": (work.get("workflow_terminal") or {}).get("outcome"),
                "workflow": {"templateId": binding["template_id"],
                             "templateVersion": binding["template_version"],
                             "digest": binding["digest"],
                             "revision": binding["revision"],
                             "parameters": binding["parameters"],
                             "sessionId": binding.get("session_id"),
                             "participants": binding.get("participants") or {}},
                "nodes": nodes,
                "checks": checks[:MAX_VIEW_NODES],
                "allowedActions": allowed,
                "intents": intents[:MAX_VIEW_INTENTS],
            }

    # ------------------------------------------------------------------
    # The native action context
    # ------------------------------------------------------------------

    def action_context(self, business_key: str) -> Dict[str, Any]:
        """The native context of the automatic action behind a business key.

        A platform adapter receives the native business key and nothing
        else. This read answers what that key really is: the operation it
        names, the workflow node instance that proposed it, the pinned
        definition, the contract and plan revision it belongs to and the
        subject the action is bound to.

        The read is local, read-only and snapshot-consistent: every row is
        read inside one deferred transaction, so the answer always describes
        one committed state. It describes stored facts and nothing else: it
        routes nothing, writes nothing, grants no capability and calls no
        external system. Every answer carries ``authorizesExecution:
        False``: a context is never an authority to execute.

        Three answers are possible:

        * ``{"present": False, "code": "ACTION_CONTEXT_ABSENT"}`` — no
          operation carries that key.
        * ``{"present": False, "code": "ACTION_CONTEXT_REFUSED",
          "reason": ...}`` — the operation exists, but its linkage is
          missing, ambiguous or inconsistent. The context is refused, never
          guessed and never partially answered.
        * ``{"present": True, "context": {...}, "current": {...}}`` — the
          stable facts of the action and the mutable state around it.

        The stable part is the identity of the action and the mutable part
        is what may still change: the operation's status, the node's
        state, the work's state version and the cancellation. The two are
        never mixed.

        The stable part reflects the **current native admission** of the
        operation. While the operation is only ``prepared``, the runtime may
        still re-admit it — a dispatch that was cancelled or held is
        admitted again with the actor and the revisions of that admission —
        so those fields are what the store says now. From the dispatch on
        (dispatched, reconciled, confirmed) the admission is settled and the
        stable part no longer moves. The context is never a claim of global
        immutability.
        """
        if not isinstance(business_key, str) or not business_key:
            raise WorkflowError("A business key must be a nonempty string")
        with self.runtime._connection() as db:
            # One deferred transaction: every row below is read from the
            # same committed snapshot.
            db.execute("BEGIN")
            return self._action_context_in(db, business_key)

    @staticmethod
    def _action_context_absence(business_key: str) -> Dict[str, Any]:
        return {"present": False, "businessKey": business_key,
                "code": ACTION_CONTEXT_ABSENT, "authorizesExecution": False}

    @staticmethod
    def _action_context_refusal(business_key: str, reason: str,
                                detail: str) -> Dict[str, Any]:
        return {"present": False, "businessKey": business_key,
                "code": ACTION_CONTEXT_REFUSED, "reason": reason,
                "detail": detail, "authorizesExecution": False}

    @staticmethod
    def _operation_links(db, operation_id: str) -> List[Tuple[str, str, int,
                                                               Dict[str, Any]]]:
        """Every node instance in the store that references the operation.

        The link is the stored ``operation_id`` on the node instance and
        nothing else: the node is never inferred from the capability, from
        the work's cursor or from the latest instance of a node.
        """
        links = []
        rows = db.execute("SELECT work_id,node,attempt,state,body FROM workflow_nodes")
        for row in rows.fetchall():
            try:
                body = json.loads(row["body"])
            except ValueError:
                # A corrupt row cannot be a link. It is skipped, exactly like
                # the engine skips a corrupt work when it lists workflows.
                continue
            if isinstance(body, dict) and body.get("operation_id") == operation_id:
                links.append((row["work_id"], row["node"], row["attempt"],
                              row["state"], body))
        return links

    @staticmethod
    def _contract_history(db, work_id: str) -> List[Dict[str, Any]]:
        """Every contract the work was bound to, with its revision.

        The work keeps only the contract that is in force now. The history
        of the contract is in the event ledger: the binding and every
        migration record the contract they replaced. This is a recovery of
        a stored fact, never a reconstruction: what the ledger does not
        hold stays unknown.
        """
        history: List[Dict[str, Any]] = []
        rows = db.execute("SELECT type,body FROM events WHERE work_id=? ORDER BY seq",
                          (work_id,))
        for row in rows.fetchall():
            try:
                body = json.loads(row["body"])
            except ValueError:
                continue
            if not isinstance(body, dict):
                continue
            if row["type"] == "ContractBound":
                history.append({"policyId": body.get("policy_id"),
                                "policyVersion": body.get("policy_version"),
                                "goal": body.get("goal"), "revision": 1})
            elif row["type"] == "PolicyMigrated":
                for entry in (body.get("from"), body.get("to")):
                    if isinstance(entry, dict):
                        history.append({"policyId": entry.get("policy_id"),
                                        "policyVersion": entry.get("policy_version"),
                                        "goal": entry.get("goal"),
                                        "revision": entry.get("revision")})
        return history

    def _action_context_in(self, db, business_key: str) -> Dict[str, Any]:
        row = db.execute("SELECT id,work_id,body FROM operations WHERE business_key=?",
                         (business_key,)).fetchone()
        if row is None:
            return self._action_context_absence(business_key)
        try:
            operation = json.loads(row["body"])
        except ValueError:
            return self._action_context_refusal(
                business_key, "OPERATION_BODY_INVALID",
                "The stored operation cannot be read")
        if not isinstance(operation, dict):
            return self._action_context_refusal(
                business_key, "OPERATION_BODY_INVALID",
                "The stored operation is not an object")
        if (operation.get("id") != row["id"]
                or operation.get("business_key") != business_key):
            return self._action_context_refusal(
                business_key, "OPERATION_IDENTITY_MISMATCH",
                "The stored operation does not match its row")
        if operation.get("work_id") != row["work_id"]:
            return self._action_context_refusal(
                business_key, "OPERATION_ROW_INCONSISTENT",
                "The stored operation does not match the work of its row")
        operation_id = operation.get("id")
        links = self._operation_links(db, operation_id)
        if not links:
            return self._action_context_refusal(
                business_key, "OPERATION_NOT_WORKFLOW_BOUND",
                "No workflow node instance proposed this operation")
        if len(links) > 1:
            return self._action_context_refusal(
                business_key, "OPERATION_LINK_AMBIGUOUS",
                "Several node instances reference this operation")
        work_id, node_id, attempt, node_state, instance = links[0]
        if work_id != operation.get("work_id"):
            return self._action_context_refusal(
                business_key, "OPERATION_LINK_WORK_MISMATCH",
                "The node instance belongs to another work")
        if (instance.get("node") != node_id
                or instance.get("attempt") != attempt
                or instance.get("state") != node_state):
            return self._action_context_refusal(
                business_key, "NODE_ROW_INCONSISTENT",
                "The node instance does not match its stored row")
        if instance.get("kind") != "action":
            return self._action_context_refusal(
                business_key, "OPERATION_LINK_WRONG_KIND",
                "The node instance is not an action node")
        work_row = db.execute("SELECT state FROM works WHERE id=?", (work_id,)).fetchone()
        if work_row is None:
            return self._action_context_refusal(
                business_key, "OPERATION_WORK_UNKNOWN",
                "The work of this operation is gone")
        try:
            work = json.loads(work_row[0])
        except ValueError:
            return self._action_context_refusal(
                business_key, "OPERATION_WORK_INVALID",
                "The work of this operation cannot be read")
        binding = work.get("workflow")
        if not isinstance(binding, dict):
            return self._action_context_refusal(
                business_key, "OPERATION_WORK_NOT_BOUND",
                "The work of this operation has no workflow binding")
        spec = self._spec_in(db, work)
        node = ((spec or {}).get("nodes") or {}).get(node_id)
        if not isinstance(node, dict):
            return self._action_context_refusal(
                business_key, "OPERATION_NODE_UNKNOWN",
                "The pinned definition does not declare the node")
        if node.get("kind") != "action":
            return self._action_context_refusal(
                business_key, "OPERATION_LINK_WRONG_KIND",
                "The pinned definition does not declare an action node")
        if node.get("capability") != operation.get("capability"):
            return self._action_context_refusal(
                business_key, "OPERATION_CAPABILITY_MISMATCH",
                "The operation does not carry the capability of its node")
        template = db.execute(
            "SELECT digest FROM workflow_templates WHERE id=? AND version=?",
            (binding.get("template_id"), binding.get("template_version"))).fetchone()
        if template is None:
            return self._action_context_refusal(
                business_key, "OPERATION_TEMPLATE_UNKNOWN",
                "The published definition of this work is gone")
        if template[0] != binding.get("digest"):
            return self._action_context_refusal(
                business_key, "OPERATION_TEMPLATE_MISMATCH",
                "The published definition is not the one the work pinned")
        subject = instance.get("subject")
        bound = operation.get("object")
        if not isinstance(subject, dict) or not isinstance(bound, dict):
            return self._action_context_refusal(
                business_key, "OPERATION_SUBJECT_MISSING",
                "The action is not bound to a subject")
        for field in ("name", "revision", "digest"):
            if subject.get(field) != bound.get(field):
                return self._action_context_refusal(
                    business_key, "OPERATION_SUBJECT_MISMATCH",
                    "The subject of the node is not the subject of the operation")
        object_row = self._object_at(db, work_id, subject["name"], subject["revision"])
        if object_row is None:
            return self._action_context_refusal(
                business_key, "OPERATION_OBJECT_UNAVAILABLE",
                "The bound revision of the subject is gone")
        if (object_row["digest"] != operation.get("document_digest")
                or object_row["digest"] != subject.get("digest")):
            return self._action_context_refusal(
                business_key, "OPERATION_OBJECT_DIGEST_MISMATCH",
                "The bound subject does not carry the digest of the operation")
        try:
            body = json.loads(object_row["body"])
        except ValueError:
            return self._action_context_refusal(
                business_key, "OPERATION_OBJECT_BODY_INVALID",
                "The bound subject cannot be read")
        if digest(body) != object_row["digest"]:
            return self._action_context_refusal(
                business_key, "OPERATION_OBJECT_BODY_MISMATCH",
                "The bound subject does not match its own digest")
        if body != operation.get("document"):
            return self._action_context_refusal(
                business_key, "OPERATION_DOCUMENT_MISMATCH",
                "The operation does not carry the body of its bound subject")
        input_digest = instance.get("input_digest")
        if not isinstance(input_digest, str) or not input_digest:
            return self._action_context_refusal(
                business_key, "OPERATION_INPUT_DIGEST_MISSING",
                "The node instance does not carry the digest of its inputs")
        # The contract the action was proposed under. A migration moves the
        # work to a new contract; the historical one is recovered from the
        # event ledger, and what the ledger does not hold stays unknown.
        contract = work.get("contract") or {}
        current_contract = {"policyId": contract.get("policy_id"),
                            "policyVersion": contract.get("policy_version"),
                            "goal": contract.get("goal"),
                            "revision": contract.get("revision")}
        operation_revision = operation.get("contract_revision")
        if contract.get("revision") == operation_revision:
            historical_contract = dict(current_contract)
            contract_source = "current"
        else:
            historical_contract = None
            for entry in self._contract_history(db, work_id):
                if entry.get("revision") == operation_revision:
                    historical_contract = entry
                    break
            contract_source = "ledger" if historical_contract is not None else "unknown"
        if historical_contract is None:
            historical_contract = {"policyId": None, "policyVersion": None,
                                   "goal": None, "revision": operation_revision}
        stable = {
            "businessKey": business_key,
            "operationId": operation_id,
            "workId": work_id,
            "node": node_id,
            "attempt": attempt,
            "actor": operation.get("actor"),
            "capability": operation.get("capability"),
            "contract": historical_contract,
            "contractRevision": operation_revision,
            "planRevision": operation.get("plan_revision"),
            "inputDigest": input_digest,
            "template": {"id": binding.get("template_id"),
                         "version": binding.get("template_version"),
                         "digest": binding.get("digest")},
            "subject": {"name": subject["name"], "revision": subject["revision"],
                        "digest": subject["digest"], "body": body},
            "envelope": {"sessionId": binding.get("session_id"),
                         "participants": binding.get("participants") or {},
                         "parameters": binding.get("parameters") or {},
                         "runner": instance.get("runner")},
        }
        current = {
            "operationStatus": operation.get("status"),
            "dispatchState": operation.get("dispatch_state"),
            "externalId": operation.get("external_id"),
            "nodeState": instance.get("state"),
            "nodeOutcome": instance.get("outcome"),
            "nodeReason": instance.get("reason"),
            "workStatus": work.get("status"),
            "workflowStatus": work.get("workflow_status"),
            "stateVersion": work.get("state_version"),
            "contract": current_contract,
            "contractRevision": contract.get("revision"),
            "contractProvenance": {"source": contract_source,
                                   "revision": operation_revision},
            "planRevision": work.get("plan_revision"),
            "owner": work.get("owner"),
            "cancelled": bool(work.get("cancellation")),
            "cancellation": work.get("cancellation"),
            "task": {"document": work.get("document"),
                     "documentDigest": work.get("document_digest"),
                     "documentRevision": work.get("document_revision")},
        }
        # The answer is a copy: changing it can never change the store.
        return copy.deepcopy({"present": True, "businessKey": business_key,
                              "authorizesExecution": False,
                              "context": stable, "current": current})
