"""A generic HTTP bridge for the mixed-node workflow runtime.

The surface is deliberately separate from any product-specific delivery
route: it speaks only the generic workflow language — published templates,
instances, node results, human decisions, durable intents — and it never
decides a business outcome. It is a *bridge*: the platform keeps its own
task, approval and artifact records, and GAWR keeps the governance truth.

Trust boundary: this is a trusted-local service. Principals are names in the
configured grants map, not authenticated identities; a caller that reaches
this service is inside the trusted boundary. The bridge never accepts an
approving identity from a request body: the approving principal is resolved
from the published node and the policy's source registry.

Every mutating call settles the workflow before it answers, and a background
ticker advances and recovers the store on its own, so no client has to poll
for progress.
"""

import json
import os
import sys
import threading
import time
import weakref
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from .policy import canonical, digest as content_digest
from .runtime import CommandError
from .workflow import MATERIAL_WAIT_REQUEST_VERSION, WorkflowError

API_PREFIX = "/v1/workflows"
MAX_BODY_BYTES = 1 << 20
MAX_LIST_LIMIT = 64

# Request fields that may carry a secret. They are never echoed back and
# never written to the log.
SECRET_FIELDS = ("token", "secret", "password", "passwd", "credential",
                 "authorization", "api_key", "apikey", "cookie", "session_key")

# Engine rejection code -> HTTP status. Unknown codes are reported as 422
# (a business rejection) rather than as a server fault.
STATUS_BY_CODE = {
    "AUTHORITY_DENIED": 403,
    "WORKFLOW_TEMPLATE_UNKNOWN": 404,
    "WORKFLOW_INTENT_UNKNOWN": 404,
    "WORKFLOW_NODE_UNKNOWN": 404,
    "WORK_UNKNOWN": 404,
    "WORKFLOW_TEMPLATE_IMMUTABLE": 409,
    "WORKFLOW_ALREADY_BOUND": 409,
    "WORKFLOW_ATTEMPT_STALE": 409,
    "WORKFLOW_OBJECT_MISMATCH": 409,
    "WORKFLOW_DECISION_STALE": 409,
    "WORKFLOW_INTENT_CANCELLED": 409,
    "COMMAND_ID_REUSED": 409,
    "SOURCE_EVENT_CONFLICT": 409,
    "STATE_VERSION_CONFLICT": 409,
    "CONTRACT_ALREADY_BOUND": 409,
    "WORK_ALREADY_EXISTS": 409,
    "OUTCOME_UNRESOLVED": 409,
    "REQUIREMENT_UNSATISFIED": 409,
    "CANCELLATION_ALREADY_REQUESTED": 409,
    "WORKFLOW_SPEC_INVALID": 422,
    "WORKFLOW_VALIDATOR_UNKNOWN": 422,
    "WORKFLOW_FAMILY_MISMATCH": 422,
    "WORKFLOW_PARAMETERS_INVALID": 422,
    "WORKFLOW_AUTHORITY_UNKNOWN": 422,
    "WORKFLOW_REQUIRED_CHECKS_MISSING": 422,
    "WORKFLOW_CAPABILITY_UNSUPPORTED": 422,
    "WORKFLOW_RESULT_INVALID": 422,
    "WORKFLOW_ROLE_ISOLATION": 422,
    "WORKFLOW_EXECUTOR_MAY_NOT_APPROVE": 422,
    "WORKFLOW_AUTHORITY_MISMATCH": 422,
    "WORKFLOW_NOT_BOUND": 422,
    "WORKFLOW_ENGINE_UNAVAILABLE": 503,
    "WORKFLOW_TEMPLATE_MISMATCH": 409,
    "WORKFLOW_POLICY_MISMATCH": 422,
    "WORKFLOW_PARTICIPANT_UNKNOWN": 422,
    "WORKFLOW_CHECK_REPORT_INVALID": 422,
    "WORKFLOW_CHECK_SHORTFALL": 422,
    "WORKFLOW_ACTOR_MISSING": 422,
    "WORKFLOW_INPUT_STALE": 422,
    "WORKFLOW_RUNNER_MISMATCH": 403,
    "WORKFLOW_RUNNER_UNCONFIGURED": 422,
    "WORKFLOW_NOT_FINALIZED": 404,
    "WORKFLOW_FINALIZED": 409,
    "WORKFLOW_NOT_FINISHED": 409,
    "WORKFLOW_TERMINAL_NOT_COMPLETED": 409,
    "WORKFLOW_TERMINAL_NOT_DECLARED": 409,
    "WORKFLOW_NODE_UNSETTLED": 409,
    "WORKFLOW_NODE_NOT_CURRENT": 409,
    "WORKFLOW_NODE_NOT_WAITABLE": 409,
    "WORKFLOW_NODE_WAITING": 409,
    "WORKFLOW_NOT_WAITING": 409,
    "WORKFLOW_MATERIAL_NOT_DEPENDENCY": 422,
    "WORKFLOW_MATERIAL_TOO_LARGE": 422,
    "WORKFLOW_ADOPTION_LIMIT_EXCEEDED": 422,
    "INPUT_DEPENDENCIES_REQUIRE_REVALIDATION": 422,
    "WORKFLOW_SOURCE_REFERENCE_INVALID": 422,
    "WORKFLOW_SOURCE_REFERENCE_TOO_LARGE": 422,
    "WORKFLOW_SOURCE_NOT_PRODUCER": 409,
    "WORKFLOW_SOURCE_NOT_COMPLETED": 409,
    "WORKFLOW_WAITING_TICKET_STALE": 409,
    "WORKFLOW_REVALIDATION_EFFECT_PRESENT": 409,
    "WORKFLOW_REVALIDATION_BUDGET_EXHAUSTED": 409,
    "WORKFLOW_REVALIDATION_NO_CONSUMERS": 409,
    "WORKFLOW_NODE_NOT_COMPLETED": 409,
    "WORKFLOW_QUALITY_UNSETTLED": 409,
    "WORKFLOW_CHECK_UNSATISFIED": 409,
    "WORKFLOW_EFFECT_UNRESOLVED": 409,
    "WORKFLOW_REQUIREMENT_UNSATISFIED": 409,
    "WORKFLOW_INTENT_UNSETTLED": 409,
    "WORKFLOW_SNAPSHOT_UNBOUNDED": 409,
    "WORKFLOW_ACCEPTANCE_REQUIRED": 409,
    "CANCELLATION_NOT_REQUESTED": 409,
    "CANCEL_ACKNOWLEDGEMENT_MISMATCH": 409,
    "WORKFLOW_COMPLETION_PROOF_UNAVAILABLE": 409,
    "WORKFLOW_COMPLETION_PROOF_UNVERIFIED": 409,
    "WORKFLOW_CANCELLED": 409,
    "WORK_NOT_ACTIONABLE": 409,
}

DEFAULT_PLAN = {"steps": [], "open_requirements": [], "replan_when": []}

# The durable preparation of a multi-stage creation. The bridge owns this
# table: it records, before a stage is issued, the exact command identity,
# body and compare-and-swap version of that stage, so a resume re-issues
# the recorded command instead of recomputing one against a version that
# has moved on.
CREATE_PREPARATIONS = """
CREATE TABLE IF NOT EXISTS workflow_creates (
    command_id TEXT NOT NULL,
    work_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    stages TEXT NOT NULL,
    PRIMARY KEY(command_id, work_id))
"""


def redact(value: Any) -> Any:
    """Strip anything that looks like a credential from a value."""
    if isinstance(value, dict):
        cleaned = {}
        for key, entry in value.items():
            if isinstance(key, str) and any(marker in key.lower()
                                             for marker in SECRET_FIELDS):
                continue
            cleaned[key] = redact(entry)
        return cleaned
    if isinstance(value, list):
        return [redact(entry) for entry in value]
    return value


class CoordinatorLock:
    """A single-coordinator lock over one store.

    The runtime is a single-coordinator system: two coordinators writing one
    store would break the command dedup and the CAS discipline. The lock is
    an operating-system file lock, so a crashed coordinator releases it
    instead of leaving the store unusable.
    """

    def __init__(self, path: str):
        self.path = str(path)
        self._handle = None

    def acquire(self) -> bool:
        try:
            import fcntl
        except ImportError:  # pragma: no cover - non-POSIX fallback
            return self._acquire_exclusive()
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._handle = open(self.path, "a+")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._handle.close()
            self._handle = None
            return False
        return True

    def _acquire_exclusive(self) -> bool:  # pragma: no cover - non-POSIX fallback
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        os.write(descriptor, str(os.getpid()).encode("utf-8"))
        os.close(descriptor)
        return True

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            import fcntl
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        except ImportError:  # pragma: no cover - non-POSIX fallback
            pass
        finally:
            self._handle.close()
            self._handle = None


class CreatePreparations:
    """The durable preparation of one instance creation.

    The creation is four commands, not one: the work is created, the
    contract is bound, the plan is revised and the workflow is bound. Each
    of them is a compare-and-swap on the work's state version, so a version
    recomputed on a later attempt makes a *different* command and the
    runtime refuses it as a reused command id. The preparation is written
    before the stage is issued, and the resume re-issues the recorded
    command.
    """

    def __init__(self, runtime):
        self.runtime = runtime
        self._ready = False

    def _ensure(self) -> None:
        if self._ready:
            return
        with self.runtime._connection() as db:
            db.execute(CREATE_PREPARATIONS)
        self._ready = True

    def load(self, command_id: str, work_id: str) -> Optional[Dict[str, Any]]:
        """The recorded preparation of a creation, or None."""
        self._ensure()
        with self.runtime._connection() as db:
            row = db.execute("SELECT actor,request_digest,stages FROM workflow_creates "
                             "WHERE command_id=? AND work_id=?",
                             (command_id, work_id)).fetchone()
        if row is None:
            return None
        return {"actor": row[0], "request_digest": row[1],
                "stages": json.loads(row[2])}

    def prepare(self, command_id: str, work_id: str, actor: str,
                request_digest: str, name: str, kind: str,
                payload: Dict[str, Any],
                expected_version: Optional[int]) -> Optional[Dict[str, Any]]:
        """The stage of a creation, prepared inside one transaction.

        The stored preparation is never replaced from a stale snapshot: the
        row is read and written in the same transaction, a recorded stage
        is never overwritten, and the actor and the request digest of a
        recorded creation are immutable. ``None`` means the command id
        belongs to another request.
        """
        self._ensure()
        with self.runtime._transaction() as db:
            row = db.execute("SELECT actor,request_digest,stages FROM workflow_creates "
                             "WHERE command_id=? AND work_id=?",
                             (command_id, work_id)).fetchone()
            if row is None:
                stages = {}
            else:
                if row[0] != actor or row[1] != request_digest:
                    return None  # The command id belongs to another request.
                stages = json.loads(row[2])
            recorded = stages.get(name)
            if recorded is not None:
                return recorded
            entry = {"kind": kind,
                     "command_id": command_id + ":" + name,
                     "payload": payload,
                     "expected_version": expected_version}
            stages[name] = entry
            db.execute("INSERT OR REPLACE INTO workflow_creates VALUES (?,?,?,?,?)",
                       (command_id, work_id, actor, request_digest,
                        canonical(stages)))
            return entry


class _CreationLock:
    """A lock the collector may take when nobody waits for it."""

    def __init__(self):
        self._lock = threading.Lock()

    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, *exception):
        self._lock.release()
        return False


class WorkflowService:
    """The request-independent behaviour of the bridge.

    The HTTP handler is a thin adapter over this class, so the same surface
    is callable from Python without a socket.
    """

    def __init__(self, runtime, engine, adapter=None, *, actor_for=None,
                 now=None):
        self.runtime = runtime
        self.engine = engine
        self.adapter = adapter
        self.preparations = CreatePreparations(runtime)
        self._creation_locks = weakref.WeakValueDictionary()
        self._creation_locks_guard = threading.Lock()
        self._now = now
        self._actor_for = actor_for or (lambda work_id: "coordinator")

    # -- helpers ---------------------------------------------------------
    def _creation_lock(self, key):
        """The lock of one creation.

        Two callers that create the same instance at the same time take
        turns instead of interleaving: the second one finds the finished
        preparation and replays it, so the durable stages are never
        written from a stale snapshot.
        """
        with self._creation_locks_guard:
            lock = self._creation_locks.get(key)
            if lock is None:
                lock = _CreationLock()
                self._creation_locks[key] = lock
            return lock

    def now(self) -> int:
        return int(time.time()) if self._now is None else int(self._now)

    def _settle(self, work_id: str) -> None:
        """Route the workflow and perform the actions it just authorized."""
        if self.adapter is not None:
            self.engine.pump(self.adapter, self.now())
        else:
            self.engine.advance(work_id, self.now())

    def _policy(self):
        return self.runtime.policy

    def _evidence_kind_for(self, work, node_id):
        """The evidence kind of a human node, from the published definition.

        The kind selects the trusted ingress source; it never comes from
        the request body.
        """
        with self.runtime._connection() as db:
            spec = self.engine._spec_in(db, work)
        if spec is None:
            return None
        node = (spec.get("nodes") or {}).get(node_id)
        if not isinstance(node, dict) or node.get("kind") != "human":
            return None
        return node.get("evidence_kind")

    # -- endpoints -------------------------------------------------------
    def list_templates(self) -> Tuple[int, Dict[str, Any]]:
        return 200, {"templates": self.engine.list_templates()}

    def publish_template(self, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        spec = body.get("spec")
        if not isinstance(spec, dict):
            return 400, _error("SPEC_NOT_OBJECT", "A template requires a spec object")
        for name in ("id", "version"):
            if name not in spec:
                return 400, _error("SPEC_FIELD_MISSING",
                                   "A template requires an id and a version")
        actor = body.get("actor") or self._actor_for(spec["id"])
        result = self.engine.publish_template(actor, spec)
        if result.get("decision") != "accepted":
            return _status_for(result), _error(result.get("code", "REJECTED"),
                                               "The template was not published",
                                               result.get("findings"))
        return 201, {"templateId": result["template_id"],
                     "templateVersion": result["template_version"],
                     "digest": result["digest"]}

    def get_template(self, template_id: str, version: str) -> Tuple[int, Dict[str, Any]]:
        stored = self.engine.template(template_id, version)
        if stored is None:
            return 404, _error("WORKFLOW_TEMPLATE_UNKNOWN",
                               "No such published template")
        return 200, {"templateId": stored["id"], "templateVersion": stored["version"],
                     "digest": stored["digest"], "spec": stored["spec"],
                     "publishedBy": stored.get("published_by"),
                     "publishedAt": stored.get("published_at")}

    def create_instance(self, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """Create an instance: the work, the contract, the plan, the binding.

        The creation is four commands, not one. Each of them is a
        compare-and-swap on the work's state version, so the version is
        part of the command's identity: a version recomputed on a later
        attempt is a *different* command and the runtime refuses it as a
        reused command id. The exact identity, body and version of every
        stage are therefore recorded before the stage is issued, and a
        replay re-issues the recorded command instead of recomputing one.
        A command id is bound to one request: a changed request under the
        same id conflicts rather than being dropped.
        """
        work_id = body.get("workId")
        document = body.get("document")
        template_id = body.get("templateId")
        template_version = body.get("templateVersion")
        parameters = body.get("parameters") or {}
        session_id = body.get("sessionId")
        if not isinstance(work_id, str) or not work_id:
            return 400, _error("WORK_ID_REQUIRED", "workId is required")
        if not isinstance(document, dict):
            return 400, _error("DOCUMENT_REQUIRED", "document is required")
        if not isinstance(template_id, str) or not isinstance(template_version, str):
            return 400, _error("TEMPLATE_REQUIRED",
                               "templateId and templateVersion are required")
        if not isinstance(parameters, dict):
            return 400, _error("PARAMETERS_INVALID", "parameters must be an object")
        if session_id is not None and (not isinstance(session_id, str) or not session_id):
            return 400, _error("SESSION_ID_INVALID",
                               "sessionId must be a nonempty string or absent")
        command_id = self._command_id(body)
        if command_id is None:
            return 400, _error("COMMAND_ID_REQUIRED",
                               "commandId is required and must be stable")
        actor = body.get("actor") or self._actor_for(work_id)
        policy = self._policy()
        submitted = body.get("policy")
        if submitted is not None:
            # The contract is the registered, immutable policy. A submitted
            # contract is checked against it, never silently replaced.
            if (not isinstance(submitted, dict)
                    or submitted.get("policyId") != policy.id
                    or submitted.get("policyVersion") != policy.version
                    or submitted.get("goal") != policy.goal):
                return 422, _error("WORKFLOW_POLICY_MISMATCH",
                                   "The submitted contract is not the registered "
                                   "policy")
        snapshot = body.get("instance")
        parameters, session_id, participants = self._trusted_snapshot(body, snapshot)
        if parameters is None:
            return 400, _error("INSTANCE_INVALID",
                               "The instance snapshot is malformed")
        # The plan and the pinned template are settled before anything is
        # written: a refused request creates nothing at all.
        submitted_plan = body.get("plan")
        if submitted_plan is None:
            plan = self._default_plan(template_id, template_version)
            normalized_plan = None
        else:
            plan = self._normalized_plan(submitted_plan)
            normalized_plan = plan
            if plan is None or not all(isinstance(plan.get(key), list)
                                       for key in ("steps", "open_requirements",
                                                   "replan_when")):
                return 400, _error("PLAN_INVALID",
                                   "plan requires steps, open_requirements and "
                                   "replan_when lists")
        expected_digest = body.get("templateDigest")
        if expected_digest is not None:
            if not isinstance(expected_digest, str) or not expected_digest:
                return 400, _error("TEMPLATE_DIGEST_INVALID",
                                   "templateDigest must be a nonempty string")
            published = self.engine.template(template_id, template_version)
            if published is None:
                return 404, _error("WORKFLOW_TEMPLATE_UNKNOWN",
                                   "No such published template")
            if published["digest"] != expected_digest:
                return 409, _error("WORKFLOW_TEMPLATE_MISMATCH",
                                   "The published template has another digest")
        # The identity of the request. A command id belongs to one request:
        # a receipt that exists is never proof that the request is the same.
        request_digest = content_digest({
            "actor": actor,
            "work_id": work_id,
            "document": document,
            "template_id": template_id,
            "template_version": template_version,
            "template_digest": expected_digest,
            "parameters": parameters,
            "session_id": session_id,
            "participants": participants,
            "plan": normalized_plan,
            "instance": snapshot,
        })
        def stage(name, kind, payload, expected_version):
            """The prepared stage of the creation.

            A recorded stage keeps the command identity, the body and the
            compare-and-swap version it was prepared with: a resume issues
            the very same command, and the runtime recognises it. ``None``
            means the command id belongs to another request.
            """
            return self.preparations.prepare(command_id, work_id, actor,
                                              request_digest, name, kind,
                                              payload, expected_version)

        def conflict():
            return 409, _error("COMMAND_ID_REUSED",
                               "The command id was already used for "
                               "another request")

        # The creation of one instance is serialized: two callers that
        # create it at the same time take turns, and the second one finds
        # the finished preparation and replays it.
        with self._creation_lock((command_id, work_id)):
            created = stage("create", "create_work", {"document": document},
                            None)
            if created is None:
                return conflict()
            try:
                receipt = self.runtime.command(actor, created["command_id"],
                                               work_id, created["kind"],
                                               created["payload"],
                                               created["expected_version"])
            except CommandError as error:
                return 400, _error("DOCUMENT_INVALID", str(error))
            if receipt.get("decision") != "accepted":
                return _status_for(receipt), _error(receipt.get("code", "REJECTED"),
                                                    "The work was not created")
            contract = {"policy_id": policy.id, "policy_version": policy.version,
                        "goal": policy.goal}
            bound = stage("contract", "bind_contract", contract,
                          self._version(work_id))
            if bound is None:
                return conflict()
            receipt = self.runtime.command(actor, bound["command_id"], work_id,
                                           bound["kind"], bound["payload"],
                                           bound["expected_version"])
            if receipt.get("decision") != "accepted":
                return _status_for(receipt), _error(receipt.get("code", "REJECTED"),
                                                    "The contract was not bound")
            revised = stage("plan", "revise_plan", plan, self._version(work_id))
            if revised is None:
                return conflict()
            receipt = self.runtime.command(actor, revised["command_id"], work_id,
                                           revised["kind"], revised["payload"],
                                           revised["expected_version"])
            if receipt.get("decision") != "accepted":
                return _status_for(receipt), _error(receipt.get("code", "REJECTED"),
                                                    "The plan was not revised")
            payload = {"template_id": template_id,
                       "template_version": template_version,
                       "parameters": parameters}
            if session_id is not None:
                payload["session_id"] = session_id
            if participants is not None:
                payload["participants"] = participants
            binding = stage("bind", "bind_workflow", payload,
                            self._version(work_id))
            if binding is None:
                return conflict()
            receipt = self.engine.command(actor, binding["command_id"], work_id,
                                          binding["kind"], binding["payload"],
                                          binding["expected_version"],
                                          now=self.now())
            if receipt.get("decision") != "accepted":
                return _status_for(receipt), _error(receipt.get("code", "REJECTED"),
                                                    "The workflow was not bound",
                                                    receipt.get("blockers"))
            self._settle(work_id)
        status, view = self.instance(work_id)
        view["commandId"] = command_id
        view["commandIds"] = {"create": command_id + ":create",
                              "contract": command_id + ":contract",
                              "plan": command_id + ":plan",
                              "bind": command_id + ":bind"}
        view["bindingCommandId"] = command_id + ":bind"
        return 201, redact(view)

    def _trusted_snapshot(self, body, snapshot):
        """The trusted platform create snapshot.

        The platform's own create path produces it; it is not arbitrary
        caller input. It carries the session, the instance parameters and
        the participant assignment the protected definition resolves
        against.
        """
        if snapshot is None:
            parameters = body.get("parameters")
            if parameters is None:
                parameters = {}
            if not isinstance(parameters, dict):
                return None, None, None
            session_id = body.get("sessionId")
            if session_id is not None and (not isinstance(session_id, str)
                                           or not session_id):
                return None, None, None
            return parameters, session_id, None
        if not isinstance(snapshot, dict):
            return None, None, None
        required = {"workspaceId", "taskId", "ownerUserId", "sessionId",
                    "parameters", "participants"}
        if not required <= set(snapshot):
            return None, None, None
        if "id" in snapshot and snapshot["id"] != body.get("workId"):
            # The snapshot names the instance it creates.
            return None, None, None
        for name in ("workspaceId", "taskId", "ownerUserId", "sessionId"):
            if not isinstance(snapshot[name], str) or not snapshot[name]:
                return None, None, None
        parameters = snapshot["parameters"]
        participants = snapshot["participants"]
        if not isinstance(parameters, dict) or not isinstance(participants, dict):
            return None, None, None
        for member_id in participants.values():
            if not isinstance(member_id, str) or not member_id:
                return None, None, None
        return parameters, snapshot["sessionId"], participants

    @staticmethod
    def _normalized_plan(plan):
        """The plan in the runtime's field names.

        The wire shape accepts both spellings; the stored plan always uses
        the runtime's own field names.
        """
        if not isinstance(plan, dict):
            return None
        allowed = {"steps", "open_requirements", "openRequirements",
                   "replan_when", "replanWhen"}
        if set(plan) - allowed:
            return None
        normalized = {"steps": plan.get("steps"),
                      "open_requirements": plan.get("open_requirements",
                                                    plan.get("openRequirements")),
                      "replan_when": plan.get("replan_when",
                                              plan.get("replanWhen"))}
        return normalized

    def _default_plan(self, template_id, template_version):
        """The plan of an instance that did not submit one."""
        stored = self.engine.template(template_id, template_version)
        if stored is None:
            return dict(DEFAULT_PLAN)
        spec = stored.get("spec") or {}
        return {"steps": sorted(spec.get("nodes") or {}),
                "open_requirements": list(spec.get("required_checks") or []),
                "replan_when": []}

    def instance(self, work_id: str) -> Tuple[int, Dict[str, Any]]:
        try:
            view = self.engine.instance(work_id)
        except Exception:
            return 404, _error("WORK_UNKNOWN", "No such work")
        return 200, redact(view)

    def submit_result(self, work_id: str, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        if self._finalized(work_id):
            return 409, _error("WORKFLOW_FINALIZED",
                               "The workflow was accepted and frozen; it accepts "
                               "no further mutation")
        payload = {"node": body.get("node"), "attempt": body.get("attempt"),
                   "object": body.get("object"), "result": body.get("result"),
                   "input_digest": body.get("inputDigest")}
        if not isinstance(payload["node"], str) or type(payload["attempt"]) is not int:
            return 400, _error("SUBMISSION_INVALID",
                               "node and attempt are required")
        if not isinstance(payload["result"], dict):
            return 400, _error("SUBMISSION_INVALID", "result must be an object")
        if not isinstance(payload["input_digest"], str) or not payload["input_digest"]:
            return 400, _error("SUBMISSION_INVALID",
                               "inputDigest is required: the candidate is bound "
                               "to the inputs it was produced from")
        actor = body.get("actor")
        if not isinstance(actor, str) or not actor:
            return 400, _error("ACTOR_REQUIRED", "actor is required")
        command_id = self._command_id(body)
        if command_id is None:
            return 400, _error("COMMAND_ID_REQUIRED",
                               "commandId is required and must be stable")
        try:
            expected_version = self._expected_version(body)
        except ValueError as error:
            return 400, _error("EXPECTED_VERSION_INVALID", str(error))
        if expected_version is None:
            return 400, _error("EXPECTED_VERSION_REQUIRED",
                               "expectedVersion is required for a compare-and-swap "
                               "mutation")
        receipt = self.engine.command(actor, command_id, work_id, "submit_node_result",
                                      payload, expected_version, now=self.now())
        if receipt.get("decision") != "accepted":
            return _status_for(receipt), _error(receipt.get("code", "REJECTED"),
                                                "The candidate was not accepted",
                                                receipt.get("blockers"))
        self._settle(work_id)
        status, view = self.instance(work_id)
        view["result"] = {"node": payload["node"], "attempt": payload["attempt"],
                          "output": receipt.get("output"),
                          "state": receipt.get("state"),
                          "resultStateVersion": receipt.get("result_state_version")}
        return 200, redact(view)

    def decide(self, work_id: str, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        if self._finalized(work_id):
            return 409, _error("WORKFLOW_FINALIZED",
                               "The workflow was accepted and frozen; it accepts "
                               "no further mutation")
        node_id = body.get("node")
        attempt = body.get("attempt")
        decision = body.get("decision")
        digest_value = body.get("digest")
        revision = body.get("revision")
        event_id = body.get("eventId")
        actor_id = body.get("actorId")
        items = body.get("items")
        if not isinstance(node_id, str) or not node_id:
            return 400, _error("DECISION_INVALID", "node is required")
        if type(attempt) is not int:
            return 400, _error("DECISION_INVALID", "attempt is required")
        if decision not in ("approved", "rejected", "request_material"):
            return 400, _error("DECISION_INVALID",
                               "decision must be approved, rejected or request_material")
        if not isinstance(digest_value, str) or not digest_value:
            return 400, _error("DECISION_INVALID", "digest is required")
        if type(revision) is not int:
            return 400, _error("DECISION_INVALID", "revision must be an integer")
        if event_id is not None and (not isinstance(event_id, str) or not event_id):
            return 400, _error("DECISION_INVALID",
                               "eventId must be a nonempty string or absent")
        if not isinstance(actor_id, str) or not actor_id:
            return 400, _error("ACTOR_ID_REQUIRED",
                               "actorId is required: the decision names the "
                               "authenticated actor")
        if not isinstance(items, list) or not items:
            return 400, _error("DECISION_INVALID",
                               "items are required: every declared criterion "
                               "needs a verdict, a reason and its evidence")
        command_id = self._command_id(body)
        if command_id is None:
            return 400, _error("COMMAND_ID_REQUIRED",
                               "commandId is required and must be stable")
        try:
            expected_version = self._expected_version(body)
        except ValueError as error:
            return 400, _error("EXPECTED_VERSION_INVALID", str(error))
        if expected_version is None:
            return 400, _error("EXPECTED_VERSION_REQUIRED",
                               "expectedVersion is required: the decision is "
                               "admitted against the version the caller observed")
        work = self.runtime.get_work(work_id)
        kind = self._evidence_kind_for(work, node_id)
        if kind is None:
            return 404, _error("WORKFLOW_NODE_UNKNOWN", "No such human node")
        # The command's actor is the platform ingress configured for this
        # node's evidence kind; the actual decider is in the payload and the
        # core checks it against the resolved assignment.
        source = self._policy().evidence_sources.get(kind)
        if not source:
            return 422, _error("WORKFLOW_AUTHORITY_UNKNOWN",
                               "No trusted source is configured for this kind")
        effective = self.engine.effective_authority(work_id, node_id)
        if effective is None or effective != actor_id:
            # The actor must be the principal the protected definition
            # assigned to this node, resolved against the platform's current
            # assignment. The ingress source is never the actor.
            return 403, _error("WORKFLOW_AUTHORITY_MISMATCH",
                               "The decision did not come from the assigned authority")
        node = self._node(work_id, node_id)
        if node is None:
            return 404, _error("WORKFLOW_NODE_UNKNOWN", "No such human node")
        if node.get("attempt") != attempt:
            return 409, _error("WORKFLOW_ATTEMPT_STALE",
                               "The decision names another attempt of the node")
        current = node.get("subject")
        if current is not None and (current["digest"] != digest_value
                                    or current["revision"] != revision):
            return 409, _error("WORKFLOW_DECISION_STALE",
                               "The decision does not cover the current version")
        payload = {"node": node_id, "attempt": attempt, "decision": decision,
                   "digest": digest_value, "revision": revision, "actor": actor_id,
                   "items": items}
        if event_id is not None:
            payload["event_id"] = event_id
        result = body.get("result")
        if result is not None:
            if not isinstance(result, dict):
                return 400, _error("DECISION_INVALID",
                                   "result must be an object or absent")
            # The named record the decision carries is judged and written in
            # the same command: the caller's compare-and-swap covers it.
            payload["result"] = result
        receipt = self.engine.command(source, command_id, work_id, "record_decision",
                                      payload, expected_version, now=self.now())
        if receipt.get("decision") != "accepted":
            return _status_for(receipt), _error(receipt.get("code", "REJECTED"),
                                                "The decision was not recorded",
                                                receipt.get("blockers"))
        self.runtime.verify_pending(work_id)
        self._settle(work_id)
        status, view = self.instance(work_id)
        view["decision"] = {"node": node_id, "attempt": attempt,
                            "outcome": (self._node(work_id, node_id) or {}).get("outcome"),
                            "actorId": actor_id,
                            "resultStateVersion": self.runtime.get_work(work_id)["state_version"]}
        return 200, redact(view)

    def revise_object(self, work_id: str, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        if self._finalized(work_id):
            return 409, _error("WORKFLOW_FINALIZED",
                               "The workflow was accepted and frozen; it accepts "
                               "no further mutation")
        name = body.get("name")
        value = body.get("object")
        if not isinstance(name, str) or not name:
            return 400, _error("OBJECT_INVALID", "name is required")
        if not isinstance(value, dict):
            return 400, _error("OBJECT_INVALID", "object must be an object")
        actor = body.get("actor")
        if not isinstance(actor, str) or not actor:
            return 400, _error("ACTOR_REQUIRED", "actor is required")
        command_id = self._command_id(body)
        if command_id is None:
            return 400, _error("COMMAND_ID_REQUIRED",
                               "commandId is required and must be stable")
        try:
            expected_version = self._expected_version(body)
        except ValueError as error:
            return 400, _error("EXPECTED_VERSION_INVALID", str(error))
        if expected_version is None:
            return 400, _error("EXPECTED_VERSION_REQUIRED",
                               "expectedVersion is required for a compare-and-swap "
                               "mutation")
        receipt = self.engine.command(actor, command_id, work_id, "revise_object",
                                      {"name": name, "object": value},
                                      expected_version, now=self.now())
        if receipt.get("decision") != "accepted":
            return _status_for(receipt), _error(receipt.get("code", "REJECTED"),
                                                "The object was not revised")
        self._settle(work_id)
        status, view = self.instance(work_id)
        view["object"] = {"name": name, "object": receipt.get("object"),
                          "supersededNodes": receipt.get("superseded_nodes"),
                          "resultStateVersion": receipt.get("result_state_version")}
        return 200, redact(view)

    def request_material_wait(self, work_id: str,
                              body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """Park the current agent node for business material.

        The bridge owns no waiting engine of its own: it issues the
        runtime's own command, so the wait is admitted by the same
        compare-and-swap, the same command dedup and the same receipt store
        as every other mutation. The body states the version of the request
        it speaks, and a version the bridge does not know is refused instead
        of half-understood.
        """
        if self._finalized(work_id):
            return 409, _error("WORKFLOW_FINALIZED",
                               "The workflow was accepted and frozen; it accepts "
                               "no further mutation")
        node_id = body.get("node")
        attempt = body.get("attempt")
        digest_value = body.get("inputDigest")
        reason = body.get("reason")
        if not isinstance(node_id, str) or not node_id:
            return 400, _error("MATERIAL_WAIT_INVALID", "node is required")
        if type(attempt) is not int:
            return 400, _error("MATERIAL_WAIT_INVALID", "attempt is required")
        if not isinstance(digest_value, str) or not digest_value:
            return 400, _error("MATERIAL_WAIT_INVALID",
                               "inputDigest is required: the wait is pinned to "
                               "the inputs the node holds now")
        if not isinstance(reason, str) or not reason:
            return 400, _error("MATERIAL_WAIT_INVALID", "reason is required")
        version = self._request_version(body)
        if version is None:
            return 400, _error("MATERIAL_WAIT_VERSION_UNSUPPORTED",
                               "requestVersion 1 is the supported version")
        actor, error = self._request_actor(body)
        if error is not None:
            return 400, error
        if not self._body_names_this_work(work_id, body):
            return 400, _error("WORK_MISMATCH",
                               "the request body names another work")
        command_id = self._command_id(body)
        if command_id is None:
            return 400, _error("COMMAND_ID_REQUIRED",
                               "commandId is required and must be stable")
        try:
            expected_version = self._expected_version(body)
        except ValueError as error:
            return 400, _error("EXPECTED_VERSION_INVALID", str(error))
        if expected_version is None:
            return 400, _error("EXPECTED_VERSION_REQUIRED",
                               "expectedVersion is required for a compare-and-swap "
                               "mutation")
        receipt = self._material_command(
            actor, command_id, work_id, "request_material_wait",
            {"node": node_id, "attempt": attempt, "input_digest": digest_value,
             "reason": reason, "request_version": version}, expected_version)
        if receipt.get("decision") != "accepted":
            return _status_for(receipt), _error(
                receipt.get("code", "REJECTED"),
                "The material wait was not recorded", receipt.get("blockers"))
        self._settle(work_id)
        status, view = self.instance(work_id)
        view["materialWait"] = {"node": node_id, "attempt": attempt,
                                "wait": receipt.get("wait"),
                                "resultStateVersion": receipt.get("result_state_version")}
        return 200, redact(view)

    def adopt_material(self, work_id: str,
                       body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """Adopt externally provided material under an active wait."""
        if self._finalized(work_id):
            return 409, _error("WORKFLOW_FINALIZED",
                               "The workflow was accepted and frozen; it accepts "
                               "no further mutation")
        node_id = body.get("node")
        attempt = body.get("attempt")
        name = body.get("name")
        value = body.get("object")
        if not isinstance(node_id, str) or not node_id:
            return 400, _error("MATERIAL_ADOPT_INVALID", "node is required")
        if type(attempt) is not int:
            return 400, _error("MATERIAL_ADOPT_INVALID", "attempt is required")
        if not isinstance(name, str) or not name:
            return 400, _error("MATERIAL_ADOPT_INVALID", "name is required")
        if not isinstance(value, dict):
            return 400, _error("MATERIAL_ADOPT_INVALID", "object must be an object")
        version = self._request_version(body)
        if version is None:
            return 400, _error("MATERIAL_WAIT_VERSION_UNSUPPORTED",
                               "requestVersion 1 is the supported version")
        actor, error = self._request_actor(body)
        if error is not None:
            return 400, error
        if not self._body_names_this_work(work_id, body):
            return 400, _error("WORK_MISMATCH",
                               "the request body names another work")
        command_id = self._command_id(body)
        if command_id is None:
            return 400, _error("COMMAND_ID_REQUIRED",
                               "commandId is required and must be stable")
        try:
            expected_version = self._expected_version(body)
        except ValueError as error:
            return 400, _error("EXPECTED_VERSION_INVALID", str(error))
        if expected_version is None:
            return 400, _error("EXPECTED_VERSION_REQUIRED",
                               "expectedVersion is required for a compare-and-swap "
                               "mutation")
        receipt = self._material_command(
            actor, command_id, work_id, "adopt_material",
            {"node": node_id, "attempt": attempt, "name": name, "object": value,
             "request_version": version}, expected_version)
        if receipt.get("decision") != "accepted":
            return _status_for(receipt), _error(
                receipt.get("code", "REJECTED"),
                "The material was not adopted", receipt.get("blockers"))
        self._settle(work_id)
        status, view = self.instance(work_id)
        view["materialAdoption"] = {"node": node_id, "attempt": attempt,
                                    "adoption": receipt.get("adoption"),
                                    "wait": receipt.get("wait"),
                                    "resultStateVersion": receipt.get("result_state_version")}
        return 200, redact(view)

    def resume_material_wait(self, work_id: str,
                             body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """Resume the waiting node behind the dependency gate."""
        if self._finalized(work_id):
            return 409, _error("WORKFLOW_FINALIZED",
                               "The workflow was accepted and frozen; it accepts "
                               "no further mutation")
        node_id = body.get("node")
        attempt = body.get("attempt")
        if not isinstance(node_id, str) or not node_id:
            return 400, _error("MATERIAL_RESUME_INVALID", "node is required")
        if type(attempt) is not int:
            return 400, _error("MATERIAL_RESUME_INVALID", "attempt is required")
        version = self._request_version(body)
        if version is None:
            return 400, _error("MATERIAL_WAIT_VERSION_UNSUPPORTED",
                               "requestVersion 1 is the supported version")
        actor, error = self._request_actor(body)
        if error is not None:
            return 400, error
        if not self._body_names_this_work(work_id, body):
            return 400, _error("WORK_MISMATCH",
                               "the request body names another work")
        command_id = self._command_id(body)
        if command_id is None:
            return 400, _error("COMMAND_ID_REQUIRED",
                               "commandId is required and must be stable")
        try:
            expected_version = self._expected_version(body)
        except ValueError as error:
            return 400, _error("EXPECTED_VERSION_INVALID", str(error))
        if expected_version is None:
            return 400, _error("EXPECTED_VERSION_REQUIRED",
                               "expectedVersion is required for a compare-and-swap "
                               "mutation")
        receipt = self._material_command(
            actor, command_id, work_id, "resume_material_wait",
            {"node": node_id, "attempt": attempt, "request_version": version},
            expected_version)
        if receipt.get("decision") != "accepted":
            return _status_for(receipt), _error(
                receipt.get("code", "REJECTED"),
                "The material wait was not resumed", receipt.get("blockers"))
        self._settle(work_id)
        status, view = self.instance(work_id)
        view["materialResume"] = {"node": node_id, "attempt": attempt,
                                  "state": receipt.get("state"),
                                  "inputDigest": receipt.get("input_digest"),
                                  "wait": receipt.get("wait"),
                                  "resultStateVersion": receipt.get("result_state_version")}
        return 200, redact(view)

    def replace_material(self, work_id: str,
                         body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """Replace the archived source material and revalidate its consumers.

        The bridge owns no replacement engine of its own: it issues the
        runtime's own command, so the compare-and-swap, the command dedup
        and the receipts are the ones every other mutation already has.

        The body carries the **frozen source reference** the platform
        acquired and froze — a manifest, never the material, never a
        location and never a credential. The core wraps it in the same
        envelope the source output carries and writes it as a new revision.
        """
        if self._finalized(work_id):
            return 409, _error("WORKFLOW_FINALIZED",
                               "The workflow was accepted and frozen; it accepts "
                               "no further mutation")
        node_id = body.get("node")
        reference = body.get("sourceReference")
        reason = body.get("reason")
        waiting_node = body.get("waitingNode")
        waiting_ticket = body.get("waitingTicket")
        if not isinstance(node_id, str) or not node_id:
            return 400, _error("MATERIAL_REPLACE_INVALID",
                               "node is required: the source node whose "
                               "material is replaced")
        if not isinstance(reference, dict) or not reference:
            return 400, _error("MATERIAL_REPLACE_INVALID",
                               "sourceReference is required: the frozen "
                               "reference the platform acquired")
        if not isinstance(reason, str) or not reason:
            return 400, _error("MATERIAL_REPLACE_INVALID", "reason is required")
        if waiting_node is not None and not isinstance(waiting_node, str):
            return 400, _error("MATERIAL_REPLACE_INVALID",
                               "waitingNode must be a node id or absent")
        if waiting_ticket is not None and not isinstance(waiting_ticket, str):
            return 400, _error("MATERIAL_REPLACE_INVALID",
                               "waitingTicket must be the ticket the manager "
                               "observed or absent")
        version = self._request_version(body)
        if version is None:
            return 400, _error("MATERIAL_WAIT_VERSION_UNSUPPORTED",
                               "requestVersion 1 is the supported version")
        actor, error = self._request_actor(body)
        if error is not None:
            return 400, error
        if not self._body_names_this_work(work_id, body):
            return 400, _error("WORK_MISMATCH",
                               "the request body names another work")
        command_id = self._command_id(body)
        if command_id is None:
            return 400, _error("COMMAND_ID_REQUIRED",
                               "commandId is required and must be stable")
        try:
            expected_version = self._expected_version(body)
        except ValueError as error:
            return 400, _error("EXPECTED_VERSION_INVALID", str(error))
        if expected_version is None:
            return 400, _error("EXPECTED_VERSION_REQUIRED",
                               "expectedVersion is required for a compare-and-swap "
                               "mutation")
        receipt = self._material_command(
            actor, command_id, work_id, "replace_material",
            {"node": node_id, "source_reference": reference, "reason": reason,
             "request_version": version, "waiting_node": waiting_node,
             "waiting_ticket": waiting_ticket}, expected_version)
        if receipt.get("decision") != "accepted":
            return _status_for(receipt), _error(
                receipt.get("code", "REJECTED"),
                "The source material was not replaced", receipt.get("blockers"))
        self._settle(work_id)
        status, view = self.instance(work_id)
        plan = view.get("materialRevalidation") or {}
        view["materialReplacement"] = {
            "node": node_id,
            "attestation": plan.get("attestation"),
            "affected": receipt.get("affected"),
            "generation": receipt.get("generation"),
            "resultStateVersion": receipt.get("result_state_version")}
        return 200, redact(view)

    def finalize(self, work_id: str, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """Accept a successful workflow and freeze it.

        The request is issued by the trusted runner the engine was
        configured with: the body may name that runner, but it may never
        name anybody else. The acceptance is a compare-and-swap against the
        version the caller observed, and the command id is the caller's own
        idempotency key.
        """
        command_id = self._command_id(body)
        if command_id is None:
            return 400, _error("COMMAND_ID_REQUIRED",
                                "commandId is required and must be stable")
        try:
            expected_version = self._expected_version(body)
        except ValueError as error:
            return 400, _error("EXPECTED_VERSION_INVALID", str(error))
        if expected_version is None:
            return 400, _error("EXPECTED_VERSION_REQUIRED",
                                "expectedVersion is required for a compare-and-swap "
                                "mutation")
        runner = self.engine.runner
        if not runner:
            return 422, _error("WORKFLOW_RUNNER_UNCONFIGURED",
                                "No trusted runner is configured for this runtime")
        claimed = body.get("actor")
        if claimed is not None and claimed != runner:
            return 403, _error("WORKFLOW_RUNNER_MISMATCH",
                                "Only the trusted runner may accept the workflow")
        receipt = self.engine.command(runner, command_id, work_id,
                                      "finalize_workflow_success", {},
                                      expected_version, now=self.now())
        if receipt.get("decision") != "accepted":
            return _status_for(receipt), _error(receipt.get("code", "REJECTED"),
                                                "The workflow was not accepted",
                                                receipt.get("blockers"))
        status, view = self.instance(work_id)
        view["finalization"] = receipt.get("finalization")
        return 200, redact(view)

    def request_cancel(self, work_id: str,
                       body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """Request the cancellation of a work through the runtime command.

        The command is the runtime's own ``request_cancel``: it runs in the
        work's transaction, cancels the workflow's active nodes and durable
        intents and every never-dispatched prepared operation, and stores an
        immutable receipt under the caller's command id. The actor must be
        the work's owner or a ``work.intervene`` administrator — the core
        decides that, never the transport: a request that reaches this
        route grants nothing by itself.
        """
        actor = body.get("actor")
        if not isinstance(actor, str) or not actor:
            return 400, _error("ACTOR_REQUIRED", "actor is required")
        reason = body.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            return 400, _error("REASON_REQUIRED",
                               "reason is required: a cancellation says why")
        command_id = self._command_id(body)
        if command_id is None:
            return 400, _error("COMMAND_ID_REQUIRED",
                               "commandId is required and must be stable")
        try:
            expected_version = self._expected_version(body)
        except ValueError as error:
            return 400, _error("EXPECTED_VERSION_INVALID", str(error))
        if expected_version is None:
            return 400, _error("EXPECTED_VERSION_REQUIRED",
                               "expectedVersion is required for a compare-and-swap "
                               "mutation")
        if self._finalized(work_id):
            return 409, _error("WORKFLOW_FINALIZED",
                               "The workflow was accepted and frozen; it accepts "
                               "no further mutation")
        try:
            receipt = self.engine.command(actor, command_id, work_id,
                                          "request_cancel", {"reason": reason},
                                          expected_version, now=self.now())
        except CommandError:
            # The command never ran: there is no receipt and no effect. A
            # missing work is a missing work — never proof about effects;
            # a reader that lost the answer consults the command receipt.
            return 404, _error("WORK_UNKNOWN", "No such work")
        if receipt.get("decision") != "accepted":
            return _status_for(receipt), _error(receipt.get("code", "REJECTED"),
                                                "The cancellation was not requested",
                                                receipt.get("blockers"))
        intent = (self.runtime.get_work(work_id).get("cancellation") or {})
        summary = {"requested": True,
                   "requestedBy": intent.get("requested_by"),
                   "reason": intent.get("reason"),
                   "resultStateVersion": receipt.get("result_state_version")}
        status, view = self.instance(work_id)
        if status != 200:
            # The command was accepted — the receipt is the truth — but the
            # instance view needs a bound workflow, and a work whose
            # creation is still between its stages has none yet. The answer
            # never reports an accepted cancellation back as a missing work.
            return 200, redact({"workId": work_id, "cancellation": summary,
                                "instanceView": "unavailable"})
        view["cancellation"] = summary
        return 200, redact(view)

    def finalize_cancel(self, work_id: str,
                        body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """Close a cancelled work through the runtime command.

        The acknowledgement must equal **exactly** the set of
        ``confirmed_succeeded`` operation ids: an effect that already
        happened is never pretended away, an unresolved effect blocks the
        closure, and the closed work keeps every operation's disposition.
        The actor must be the work's owner or a ``work.intervene``
        administrator — the core decides that, never the transport.
        """
        actor = body.get("actor")
        if not isinstance(actor, str) or not actor:
            return 400, _error("ACTOR_REQUIRED", "actor is required")
        acknowledged = body.get("acknowledgedOperations")
        if (not isinstance(acknowledged, list)
                or not all(isinstance(entry, str) and entry
                           for entry in acknowledged)
                or len(set(acknowledged)) != len(acknowledged)):
            return 400, _error("ACKNOWLEDGEMENT_INVALID",
                               "acknowledgedOperations must be a list of distinct "
                               "nonempty operation ids")
        command_id = self._command_id(body)
        if command_id is None:
            return 400, _error("COMMAND_ID_REQUIRED",
                               "commandId is required and must be stable")
        try:
            expected_version = self._expected_version(body)
        except ValueError as error:
            return 400, _error("EXPECTED_VERSION_INVALID", str(error))
        if expected_version is None:
            return 400, _error("EXPECTED_VERSION_REQUIRED",
                               "expectedVersion is required for a compare-and-swap "
                               "mutation")
        if self._finalized(work_id):
            return 409, _error("WORKFLOW_FINALIZED",
                               "The workflow was accepted and frozen; it accepts "
                               "no further mutation")
        try:
            receipt = self.engine.command(actor, command_id, work_id,
                                          "finalize_cancel",
                                          {"acknowledged_operations": acknowledged},
                                          expected_version, now=self.now())
        except CommandError:
            return 404, _error("WORK_UNKNOWN", "No such work")
        if receipt.get("decision") != "accepted":
            return _status_for(receipt), _error(receipt.get("code", "REJECTED"),
                                                "The cancellation was not finalized",
                                                receipt.get("blockers"))
        work = self.runtime.get_work(work_id)
        completion = work.get("completion") or {}
        acknowledged_view = [entry.get("operation_id") for entry in
                             completion.get("acknowledged_operations") or []]
        summary = {"finalized": True,
                   "requestedBy": (work.get("cancellation") or {})
                   .get("requested_by"),
                   "acknowledgedOperations": acknowledged_view,
                   "resultStateVersion": receipt.get("result_state_version")}
        status, view = self.instance(work_id)
        if status != 200:
            return 200, redact({"workId": work_id, "cancellation": summary,
                                "instanceView": "unavailable"})
        view["cancellation"] = summary
        return 200, redact(view)

    def cancellation(self, work_id: str) -> Tuple[int, Dict[str, Any]]:
        """The safe cancellation state of one work.

        The read answers what a platform needs to drive a cancellation:
        whether an intent exists, which operations are still unresolved and
        which exact successful operation ids the acknowledgement must name.
        It carries no payload body and no credential.
        """
        try:
            with self.runtime._connection() as db:
                work = self.runtime._work(db, work_id)
                operations = [json.loads(row[0]) for row in db.execute(
                    "SELECT body FROM operations WHERE work_id=?",
                    (work_id,)).fetchall()]
        except CommandError:
            # Only a genuinely unknown work is a missing work. A store that
            # cannot answer fails unavailable instead: a transient error
            # must never be read as "there is nothing here".
            return 404, _error("WORK_UNKNOWN", "No such work")
        intent = work.get("cancellation")
        if work["status"] == "closed" and work.get("outcome") == "cancelled":
            state = "cancelled"
        elif intent:
            state = "requested"
        else:
            state = "none"
        unresolved = sorted(operation["id"] for operation in operations
                            if operation["status"] not in ("confirmed_succeeded",
                                                           "confirmed_failed")
                            and operation.get("dispatch_state") != "cancelled")
        required = sorted(operation["id"] for operation in operations
                          if operation["status"] == "confirmed_succeeded")
        return 200, redact({
            "workId": work_id,
            "state": state,
            "status": work.get("status"),
            "outcome": work.get("outcome"),
            "stateVersion": work.get("state_version"),
            "requestedBy": (intent or {}).get("requested_by"),
            "reason": (intent or {}).get("reason"),
            "unresolvedOperations": unresolved,
            "requiredAcknowledgements": required,
            "operations": sorted(
                ({"operationId": operation["id"],
                  "externalId": operation.get("external_id"),
                  "status": operation["status"],
                  "dispatchState": operation.get("dispatch_state")}
                 for operation in operations),
                key=lambda entry: entry["operationId"]),
        })

    def completion(self, work_id: str) -> Tuple[int, Dict[str, Any]]:
        """The immutable completion read of a finalized workflow.

        It answers with the snapshot the acceptance froze: the same bytes
        for every reader, and no way to change them.

        It also answers with the **canonical text** of that proof: the exact
        UTF-8 a reader hashes to obtain the digest the acceptance recorded.
        The text is emitted only when the proof needs no redaction and when
        the stored digest still matches it; otherwise the read refuses and
        emits neither the text nor a hash of a redacted proof.
        """
        try:
            finalization = self.engine.finalization(work_id)
        except Exception:
            return 404, _error("WORK_UNKNOWN", "No such work")
        if finalization is None:
            return 404, _error("WORKFLOW_NOT_FINALIZED",
                                "The workflow was not accepted")
        if redact(finalization) != finalization:
            # The stored proof carries something that looks like a
            # credential: its canonical text would carry it verbatim, so
            # neither the text nor a hash of a redacted proof is emitted.
            return 409, _error("WORKFLOW_COMPLETION_PROOF_UNAVAILABLE",
                               "The accepted proof needs redaction; its canonical "
                               "text is not available")
        try:
            canonical_text = self.engine.finalization_canonical(finalization)
        except WorkflowError:
            return 409, _error("WORKFLOW_COMPLETION_PROOF_UNVERIFIED",
                               "The stored proof does not match its digest")
        return 200, redact({"workId": work_id, "finalization": finalization,
                             "finalizationCanonical": canonical_text})

    def object_revision(self, work_id: str, name: str, revision: str,
                        query: Optional[Dict[str, List[str]]] = None
                        ) -> Tuple[int, Dict[str, Any]]:
        """The stored content of one object revision.

        The default read is exact: the body is returned unchanged and the
        digest covers exactly what was returned, so a reviewer approves the
        material the digest names. When the stored material contains a field
        that looks like a credential, the exact read refuses rather than
        returning something the digest does not cover; the caller may ask
        for the declared redacted form instead, which says what it returned
        and what the original digest was.
        """
        try:
            number = int(revision)
        except ValueError:
            return 400, _error("REVISION_INVALID", "revision must be an integer")
        with self.runtime._connection() as db:
            row = db.execute(
                "SELECT name,revision,digest,body FROM workflow_objects "
                "WHERE work_id=? AND name=? AND revision=?",
                (work_id, name, number)).fetchone()
        if row is None:
            return 404, _error("WORKFLOW_OBJECT_UNKNOWN", "No such object revision")
        body = json.loads(row[3])
        stored_digest = row[2]
        requested = _first(query or {}, "redact")
        if requested in ("true", "1", "yes"):
            redacted = redact(body)
            return 200, {"workId": work_id, "name": row[0], "revision": row[1],
                         "digest": content_digest(redacted),
                         "originalDigest": stored_digest,
                         "redacted": True,
                         "object": redacted}
        if _has_credential_fields(body):
            return 422, _error(
                "WORKFLOW_OBJECT_CONTAINS_SECRETS",
                "The stored material contains a field that looks like a "
                "credential. Read it with ?redact=true and do not use a "
                "fragment as complete approval material.")
        return 200, {"workId": work_id, "name": row[0], "revision": row[1],
                     "digest": stored_digest, "originalDigest": stored_digest,
                     "redacted": False, "object": body}

    def list_intents(self, work_id: str, query: Dict[str, List[str]]) -> Tuple[int, Dict[str, Any]]:
        kind = _first(query, "kind")
        session_id = _first(query, "sessionId")
        status = _first(query, "status")
        limit = _first(query, "limit")
        work_ids = _first(query, "workIds")
        try:
            limit_value = int(limit) if limit else MAX_LIST_LIMIT
        except ValueError:
            return 400, _error("LIMIT_INVALID", "limit must be an integer")
        wanted = None
        if work_ids:
            wanted = [entry for entry in work_ids.split(",") if entry]
            if work_id and work_id not in wanted:
                wanted.append(work_id)
        if work_id:
            wanted = [work_id]
        found = []
        for identifier in (wanted or [None]):
            found.extend(self.engine.intents(kind=kind, session_id=session_id,
                                             status=status, work_id=identifier,
                                             limit=limit_value))
        return 200, {"intents": [redact(_intent_view(intent)) for intent in found]}

    def acknowledge_intent(self, intent_id: str, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        actor = body.get("actor")
        if not isinstance(actor, str) or not actor:
            return 400, _error("ACTOR_REQUIRED", "actor is required")
        result = self.engine.acknowledge_intent(actor, intent_id,
                                                body.get("commandId"))
        if result.get("decision") != "accepted":
            return _status_for(result), _error(result.get("code", "REJECTED"),
                                                "The intent was not acknowledged")
        return 200, {"intentId": result["intent_id"], "status": result["status"]}

    def command_receipt(self, command_id: str, query: Dict[str, List[str]]
                        ) -> Tuple[int, Dict[str, Any]]:
        """The stored receipt of one command, read-only.

        It answers "was this command accepted?" after a lost response or a
        withdrawn authority, without re-sending the command and without
        turning an executed command into a rejected one.
        """
        work_id = _first(query, "workId")
        actor = _first(query, "actor")
        if not work_id or not actor:
            return 400, _error("COMMAND_SCOPE_REQUIRED",
                               "workId and actor are required to scope a receipt")
        receipt = self.runtime.get_command_receipt(actor, command_id, work_id)
        if receipt is None:
            return 404, _error("COMMAND_RECEIPT_UNKNOWN",
                               "No such command receipt for this work and actor")
        return 200, {"commandId": command_id, "workId": work_id, "actor": actor,
                     "receipt": redact(receipt)}

    def node_attempts(self, work_id: str, node_id: str) -> Tuple[int, Dict[str, Any]]:
        """The attempt history of one node, with its stored judgments."""
        try:
            history = self.engine.attempts(work_id, node_id)
        except Exception:
            return 404, _error("WORKFLOW_NODE_UNKNOWN", "No such node")
        return 200, {"workId": work_id, "node": node_id, "attempts": redact(history)}

    def events(self, work_id: str, query: Dict[str, List[str]]) -> Tuple[int, Dict[str, Any]]:
        after = _first(query, "after")
        try:
            after_value = int(after) if after else 0
        except ValueError:
            return 400, _error("AFTER_INVALID", "after must be an integer")
        events = self.runtime.events(work_id, after_value)
        rendered = []
        altered = False
        for event in events:
            body = event.get("body")
            cleaned = redact(body)
            if cleaned != body:
                altered = True
                cleaned = dict(cleaned)
                cleaned["redacted"] = True
            rendered.append(dict(event, body=cleaned))
        return 200, {"events": rendered, "redacted": altered}

    def advance(self, work_id: str) -> Tuple[int, Dict[str, Any]]:
        self._settle(work_id)
        work = self.runtime.get_work(work_id)
        return 200, {"decision": "advanced", "currentNode": work.get("workflow_current"),
                     "workflowStatus": work.get("workflow_status"),
                     "resultStateVersion": work["state_version"]}

    def health(self) -> Tuple[int, Dict[str, Any]]:
        works = self.engine.workflow_work_ids()
        return 200, {"status": "ok", "workflows": len(works),
                     "coordinator": "single", "api": API_PREFIX}

    # -- internals -------------------------------------------------------
    def _version(self, work_id: str) -> int:
        return self.runtime.get_work(work_id)["state_version"]

    @staticmethod
    def _command_id(body: Dict[str, Any]) -> Optional[str]:
        """The stable command id of a mutation.

        Every mutation carries one: the id is the client's own idempotency
        key, so a retry returns the original receipt instead of acting twice.
        """
        command_id = body.get("commandId")
        if not isinstance(command_id, str) or not command_id:
            return None
        return command_id

    @staticmethod
    def _expected_version(body: Dict[str, Any]) -> Optional[int]:
        """The compare-and-swap version the client observed."""
        version = body.get("expectedVersion")
        if version is None:
            return None
        if type(version) is not int:
            raise ValueError("expectedVersion must be an integer")
        return version

    @staticmethod
    def _request_actor(body: Dict[str, Any]):
        """The principal a material request claims to act as.

        The trusted platform wire may name it `actor` or `actorId`; both
        name the same thing. A body that carries **two different** ones is
        refused rather than guessed at, and a body that names neither is
        refused. The principal is only an assertion: the core decides
        whether it may act.
        """
        actor = body.get("actor")
        actor_id = body.get("actorId")
        if actor is not None and actor_id is not None and actor != actor_id:
            return None, _error("ACTOR_CONFLICT",
                                "the request names two different actors")
        claimed = actor if actor is not None else actor_id
        if not isinstance(claimed, str) or not claimed:
            return None, _error("ACTOR_REQUIRED", "actor is required")
        return claimed, None

    @staticmethod
    def _body_names_this_work(work_id: str, body: Dict[str, Any]) -> bool:
        """Whether a request body agrees with the work of the path.

        The path is authoritative. A body that names **another** work is
        refused rather than ignored: the request would be about one work
        and applied to another.
        """
        named = body.get("workId")
        return named is None or named == work_id

    def _material_command(self, actor: str, command_id: str, work_id: str,
                          kind: str, payload: Dict[str, Any],
                          expected_version: int) -> Dict[str, Any]:
        """Issue one material-wait command and classify a missing work.

        A work that does not exist is a missing work, never a fact about
        effects: the command never ran, so there is no receipt and nothing
        was written. A reader that lost the answer consults the command
        receipt.
        """
        try:
            return self.engine.command(actor, command_id, work_id, kind,
                                        payload, expected_version,
                                        now=self.now())
        except CommandError:
            return {"decision": "rejected", "code": "WORK_UNKNOWN"}

    @staticmethod
    def _request_version(body: Dict[str, Any]) -> Optional[int]:
        """The version of the material-wait request the caller speaks.

        The bridge knows exactly one version. A request that states another
        one is refused rather than half-understood, so a caller never
        believes a shape was honoured that was not.
        """
        version = body.get("requestVersion")
        if version is None:
            return None
        if type(version) is not int or version != MATERIAL_WAIT_REQUEST_VERSION:
            return None
        return version

    def _finalized(self, work_id: str) -> bool:
        """Whether the work carries an accepted, frozen workflow."""
        try:
            return bool(self.runtime.get_work(work_id).get("workflow_finalization"))
        except Exception:
            return False

    def _node(self, work_id: str, node_id: str) -> Optional[Dict[str, Any]]:
        try:
            view = self.engine.instance(work_id)
        except Exception:
            return None
        for entry in view.get("nodes") or []:
            if entry.get("node") == node_id:
                return entry
        return None

    def _node_subject(self, work_id: str, node_id: str) -> Optional[Dict[str, Any]]:
        """The exact object revision a human node must decide on."""
        node = self._node(work_id, node_id)
        if node is None:
            return None
        return node.get("subject")


def _has_credential_fields(value: Any) -> bool:
    """True when a value carries a field that looks like a credential."""
    if isinstance(value, dict):
        for key, entry in value.items():
            if (isinstance(key, str)
                    and any(marker in key.lower() for marker in SECRET_FIELDS)):
                return True
            if _has_credential_fields(entry):
                return True
        return False
    if isinstance(value, list):
        return any(_has_credential_fields(entry) for entry in value)
    return False


def _intent_view(intent: Dict[str, Any]) -> Dict[str, Any]:
    """The wire shape of one durable intent."""
    return {
        "id": intent.get("id"),
        "kind": intent.get("kind"),
        "node": intent.get("node"),
        "attempt": intent.get("attempt"),
        "status": intent.get("status"),
        "sessionId": intent.get("session_id"),
        "executor": intent.get("executor"),
        "authority": intent.get("authority"),
        "subject": intent.get("subject"),
        "inputs": intent.get("inputs") or [],
        "inputDigest": intent.get("input_digest"),
        "inputGeneration": intent.get("input_generation", 0),
        "checks": intent.get("checks") or [],
        "deadlineAt": intent.get("deadline_at"),
        "createdAt": intent.get("created_at"),
        "acknowledgedBy": intent.get("acknowledged_by"),
    }


def _error(code: str, message: str, findings=None) -> Dict[str, Any]:
    error = {"code": code, "message": message}
    if findings:
        error["findings"] = findings
    return {"error": error}


def _status_for(receipt: Dict[str, Any]) -> int:
    return STATUS_BY_CODE.get(receipt.get("code"), 422)


def _first(query: Dict[str, List[str]], name: str) -> Optional[str]:
    values = query.get(name)
    if not values:
        return None
    return values[0]


class WorkflowRequestHandler(BaseHTTPRequestHandler):
    """The HTTP adapter: routing, JSON envelopes and a quiet log."""

    server_version = "gawr-workflow/1"
    protocol_version = "HTTP/1.1"

    @property
    def service(self) -> WorkflowService:
        return self.server.service  # type: ignore[attr-defined]

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        # The log records the method, the path and the outcome. Bodies and
        # headers are never logged, so a credential in a request cannot reach
        # the log.
        self.server.log.append(  # type: ignore[attr-defined]
            "%s %s" % (self.command, urlparse(self.path).path))

    def do_GET(self):  # noqa: N802 - stdlib signature
        self._dispatch("GET")

    def do_POST(self):  # noqa: N802 - stdlib signature
        self._dispatch("POST")

    def do_PUT(self):  # noqa: N802 - stdlib signature
        self._dispatch("PUT")

    def do_DELETE(self):  # noqa: N802 - stdlib signature
        self._dispatch("DELETE")

    def _dispatch(self, method: str):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        try:
            body = self._read_body() if method in ("POST", "PUT") else {}
            status, payload = self._route(method, path, query, body)
        except CommandError as error:
            status, payload = 400, _error("BAD_REQUEST", str(error))
        except ValueError:
            status, payload = 400, _error("BAD_REQUEST", "The request is malformed")
        except Exception:  # pragma: no cover - a fault must still answer
            status, payload = 500, _error("INTERNAL_ERROR",
                                          "The request could not be completed")
        self._respond(status, payload)

    def _read_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise ValueError("The request body is too large")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ValueError("The request body is not JSON")
        if not isinstance(parsed, dict):
            raise ValueError("The request body must be a JSON object")
        return parsed

    def _route(self, method, path, query, body):
        service = self.service
        if not path.startswith(API_PREFIX):
            return 404, _error("ROUTE_UNKNOWN", "No such route")
        rest = path[len(API_PREFIX):].strip("/")
        parts = [part for part in rest.split("/") if part]
        if not parts:
            return 200, service.health()[1]
        head = parts[0]
        if head == "templates":
            if method == "GET" and len(parts) == 1:
                return service.list_templates()
            if method == "POST" and len(parts) == 1:
                return service.publish_template(body)
            if method == "GET" and len(parts) == 3:
                return service.get_template(parts[1], parts[2])
            return 405, _error("METHOD_NOT_ALLOWED", "Method not allowed here")
        if head == "commands":
            if method == "GET" and len(parts) == 2:
                return service.command_receipt(parts[1], query)
            return 405, _error("METHOD_NOT_ALLOWED", "Method not allowed here")
        if head == "intents":
            if method == "GET" and len(parts) == 1:
                return service.list_intents(None, query)
            if method == "POST" and len(parts) == 3 and parts[2] == "ack":
                return service.acknowledge_intent(parts[1], body)
            return 405, _error("METHOD_NOT_ALLOWED", "Method not allowed here")
        if head == "instances":
            if method == "POST" and len(parts) == 1:
                return service.create_instance(body)
            if len(parts) < 2:
                return 405, _error("METHOD_NOT_ALLOWED", "Method not allowed here")
            work_id = parts[1]
            tail = parts[2:]
            if method == "GET" and not tail:
                return service.instance(work_id)
            if method == "GET" and tail == ["intents"]:
                return service.list_intents(work_id, query)
            if method == "GET" and tail == ["events"]:
                return service.events(work_id, query)
            if (method == "GET" and len(tail) == 3 and tail[0] == "nodes"
                    and tail[2] == "attempts"):
                return service.node_attempts(work_id, tail[1])
            if method == "POST" and tail == ["results"]:
                return service.submit_result(work_id, body)
            if method == "POST" and tail == ["decisions"]:
                return service.decide(work_id, body)
            if method == "POST" and tail == ["objects"]:
                return service.revise_object(work_id, body)
            if method == "POST" and tail == ["cancel"]:
                return service.request_cancel(work_id, body)
            if method == "POST" and tail == ["cancel", "finalize"]:
                return service.finalize_cancel(work_id, body)
            if method == "GET" and tail == ["cancellation"]:
                return service.cancellation(work_id)
            if method == "POST" and tail == ["finalize"]:
                return service.finalize(work_id, body)
            if method == "POST" and tail == ["material", "wait"]:
                return service.request_material_wait(work_id, body)
            if method == "POST" and tail == ["material", "adopt"]:
                return service.adopt_material(work_id, body)
            if method == "POST" and tail == ["material", "resume"]:
                return service.resume_material_wait(work_id, body)
            if method == "POST" and tail == ["material", "replace"]:
                return service.replace_material(work_id, body)
            if method == "GET" and tail == ["completion"]:
                return service.completion(work_id)
            if (method == "GET" and len(tail) == 4 and tail[0] == "objects"
                    and tail[2] == "revisions"):
                return service.object_revision(work_id, tail[1], tail[3], query)
            if method == "POST" and tail == ["advance"]:
                return service.advance(work_id)
            return 404, _error("ROUTE_UNKNOWN", "No such route")
        return 404, _error("ROUTE_UNKNOWN", "No such route")

    def _respond(self, status: int, payload: Dict[str, Any]):
        body = json.dumps(redact(payload), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class WorkflowHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, service: WorkflowService):
        super().__init__(address, WorkflowRequestHandler)
        self.service = service
        self.log: List[str] = []

    def handle_error(self, request, client_address):
        """A client that hangs up is not a server fault."""
        kind = sys.exc_info()[0]
        if kind is not None and issubclass(kind, (ConnectionError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


class WorkflowTicker:
    """The periodic advance/recover loop.

    Progress does not depend on a client polling: the bridge advances the
    workflow, dispatches the actions it authorized and reconciles unknown
    effects on its own schedule. The loop performs bounded work per tick.
    """

    def __init__(self, service: WorkflowService, adapter=None, interval_s: float = 5.0,
                 recover_every: int = 5):
        self.service = service
        self.adapter = adapter if adapter is not None else service.adapter
        self.interval_s = max(0.05, float(interval_s))
        self.recover_every = max(1, int(recover_every))
        self._thread = None
        self._stop = threading.Event()
        self.ticks = 0

    def start(self):
        if self._thread is not None:
            return self._thread
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="gawr-workflow-ticker",
                                        daemon=True)
        self._thread.start()
        return self._thread

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # pragma: no cover - a failed tick must not kill the loop
                pass
            self._stop.wait(self.interval_s)

    def tick(self):
        """One bounded advance/recover pass over every workflow work."""
        self.ticks += 1
        engine = self.service.engine
        if self.adapter is not None:
            if self.ticks % self.recover_every == 0:
                engine.recover(self.adapter, self.service.now())
            else:
                engine.pump(self.adapter, self.service.now())
        else:
            for work_id in engine.workflow_work_ids():
                engine.advance(work_id, self.service.now())


def serve(runtime, engine, adapter=None, host="127.0.0.1", port=0,
          interval_s=5.0, lock_path=None, actor_for=None):
    """Start the bridge on the loopback interface.

    Returns (server, ticker, lock). The caller serves forever; the ticker
    keeps the workflow moving without any client polling.
    """
    service = WorkflowService(runtime, engine, adapter, actor_for=actor_for)
    server = WorkflowHTTPServer((host, port), service)
    lock = None
    if lock_path:
        lock = CoordinatorLock(lock_path)
        if not lock.acquire():
            server.server_close()
            raise RuntimeError("Another coordinator already holds this store")
    ticker = WorkflowTicker(service, adapter, interval_s=interval_s)
    ticker.start()
    # The socket is served on its own thread so the caller keeps control of
    # the process (it may still use the server object directly).
    thread = threading.Thread(target=server.serve_forever, name="gawr-workflow-http",
                              daemon=True)
    thread.start()
    server.thread = thread  # type: ignore[attr-defined]
    return server, ticker, lock
