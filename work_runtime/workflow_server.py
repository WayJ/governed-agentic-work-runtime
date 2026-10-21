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
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from .runtime import CommandError

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
}

DEFAULT_PLAN = {"steps": [], "open_requirements": [], "replan_when": []}


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
        self._now = now
        self._actor_for = actor_for or (lambda work_id: "coordinator")

    # -- helpers ---------------------------------------------------------
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

    def _authority_for(self, work, node_id):
        """The principal that may decide a human node.

        The principal comes from the published node and the policy's source
        registry — never from the request body.
        """
        with self.runtime._connection() as db:
            spec = self.engine._spec_in(db, work)
        if spec is None:
            return None, None
        node = (spec.get("nodes") or {}).get(node_id)
        if not isinstance(node, dict) or node.get("kind") != "human":
            return None, None
        kind = node.get("evidence_kind")
        source = self._policy().evidence_sources.get(kind)
        authority = node.get("authority") or source
        return kind, authority

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
        try:
            created = self.runtime.command(actor, command_id + ":create", work_id,
                                           "create_work", {"document": document})
        except CommandError as error:
            return 400, _error("DOCUMENT_INVALID", str(error))
        if created.get("decision") != "accepted":
            return _status_for(created), _error(created.get("code", "REJECTED"),
                                                "The work was not created")
        contract = {"policy_id": policy.id, "policy_version": policy.version,
                    "goal": policy.goal}
        bound = self.runtime.command(actor, command_id + ":contract", work_id,
                                     "bind_contract", contract,
                                     self.runtime.get_work(work_id)["state_version"])
        if bound.get("decision") != "accepted":
            return _status_for(bound), _error(bound.get("code", "REJECTED"),
                                              "The contract was not bound")
        plan = body.get("plan") or dict(DEFAULT_PLAN)
        if not isinstance(plan, dict) or not all(isinstance(plan.get(key), list)
                                                 for key in
                                                 ("steps", "open_requirements",
                                                  "replan_when")):
            return 400, _error("PLAN_INVALID",
                               "plan requires steps, open_requirements and replan_when lists")
        revised = self.runtime.command(actor, command_id + ":plan", work_id,
                                       "revise_plan", plan,
                                       self.runtime.get_work(work_id)["state_version"])
        if revised.get("decision") != "accepted":
            return _status_for(revised), _error(revised.get("code", "REJECTED"),
                                                "The plan was not revised")
        payload = {"template_id": template_id, "template_version": template_version,
                   "parameters": parameters}
        if session_id is not None:
            payload["session_id"] = session_id
        receipt = self.engine.command(actor, command_id + ":bind", work_id,
                                      "bind_workflow", payload,
                                      self.runtime.get_work(work_id)["state_version"],
                                      now=self.now())
        if receipt.get("decision") != "accepted":
            return _status_for(receipt), _error(receipt.get("code", "REJECTED"),
                                                "The workflow was not bound",
                                                receipt.get("blockers"))
        self._settle(work_id)
        return 201, self.instance(work_id)[1]

    def instance(self, work_id: str) -> Tuple[int, Dict[str, Any]]:
        try:
            view = self.engine.instance(work_id)
        except Exception:
            return 404, _error("WORK_UNKNOWN", "No such work")
        return 200, redact(view)

    def submit_result(self, work_id: str, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
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
        work = self.runtime.get_work(work_id)
        kind, authority = self._authority_for(work, node_id)
        if kind is None or authority is None:
            return 404, _error("WORKFLOW_NODE_UNKNOWN", "No such human node")
        if actor_id != authority:
            # The decision must come from the principal the protected
            # definition assigned to this node. The ingress source is the
            # platform channel; it is never the actor.
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
        data = {"decision": decision, "digest": digest_value, "revision": revision,
                "node": node_id, "attempt": attempt, "actor": actor_id,
                "items": items}
        receipt = self.runtime.command(authority, event_id or command_id,
                                       work_id, "record_evidence",
                                       {"event_id": event_id or command_id,
                                        "kind": kind, "data": data})
        if receipt.get("decision") != "accepted":
            return _status_for(receipt), _error(receipt.get("code", "REJECTED"),
                                                "The decision was not recorded")
        self.runtime.verify_pending(work_id)
        self._settle(work_id)
        status, view = self.instance(work_id)
        view["decision"] = {"node": node_id, "attempt": attempt,
                            "outcome": (self._node(work_id, node_id) or {}).get("outcome"),
                            "actorId": actor_id,
                            "resultStateVersion": self.runtime.get_work(work_id)["state_version"]}
        return 200, redact(view)

    def revise_object(self, work_id: str, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
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

    def object_revision(self, work_id: str, name: str,
                        revision: str) -> Tuple[int, Dict[str, Any]]:
        """The exact stored content of one object revision."""
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
        return 200, {"workId": work_id, "name": row[0], "revision": row[1],
                     "digest": row[2], "object": redact(body)}

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

    def events(self, work_id: str, query: Dict[str, List[str]]) -> Tuple[int, Dict[str, Any]]:
        after = _first(query, "after")
        try:
            after_value = int(after) if after else 0
        except ValueError:
            return 400, _error("AFTER_INVALID", "after must be an integer")
        events = self.runtime.events(work_id, after_value)
        return 200, {"events": [redact(event) for event in events]}

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
            if method == "POST" and tail == ["results"]:
                return service.submit_result(work_id, body)
            if method == "POST" and tail == ["decisions"]:
                return service.decide(work_id, body)
            if method == "POST" and tail == ["objects"]:
                return service.revise_object(work_id, body)
            if (method == "GET" and len(tail) == 4 and tail[0] == "objects"
                    and tail[2] == "revisions"):
                return service.object_revision(work_id, tail[1], tail[3])
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
