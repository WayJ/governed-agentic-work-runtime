"""A replaceable policy boundary and an explicitly limited expense example."""

import hashlib
import json
from typing import Any, Dict, List, Protocol


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


class Policy(Protocol):
    id: str
    version: str
    goal: str
    evidence_sources: Dict[str, str]

    def validate_document(self, document: dict) -> None: ...
    def evaluate(self, work: dict, evidence: List[dict]) -> List[dict]: ...
    def action_blockers(self, capability: str, requirements: List[dict]) -> List[dict]: ...
    def operation_key(self, capability: str, work: dict) -> str: ...
    def validate_evidence(self, work: dict, candidate: dict) -> bool: ...


class ExpensePolicy:
    """Demo E01–E08 policy; published in code, not extracted from a prompt.

    It trusts in-process source identities configured by the application.
    Real deployments need authenticated adapters and source-specific verifiers.
    """

    id = "expense-submit"
    version = "demo-1"
    goal = "expense.accepted"
    evidence_sources = {
        "invoice_valid": "invoice-service",
        "duplicate_clear": "expense-service",
        "approval": "finance",
        "confirmation": "requester",
        "accepted": "oa",
    }
    # Compensation pairing (S10 D43/D44): the compensating capability maps to
    # the forward capability whose accepted effect it withdraws. A policy
    # without this attribute keeps CAPABILITY_UNSUPPORTED for every
    # non-forward capability — graceful degradation for custom/old policies.
    compensation_capabilities = {"expense.withdraw": "expense.submit"}

    def validate_document(self, document: dict) -> None:
        if set(document) != {"id", "amount", "limit", "invoices", "sealed"}:
            raise ValueError("Document requires id, amount, limit, invoices and sealed")
        if not isinstance(document["id"], str) or not document["id"]:
            raise ValueError("Document id must be a nonempty string")
        for name in ("amount", "limit"):
            value = document[name]
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("Amounts are nonnegative integer minor units or null")
        if type(document["sealed"]) is not bool:
            raise ValueError("sealed must be a boolean")
        invoices = document["invoices"]
        if not isinstance(invoices, list):
            raise ValueError("invoices must be a list")
        for invoice in invoices:
            if (not isinstance(invoice, dict) or set(invoice) != {"id", "revision"}
                    or not isinstance(invoice["id"], str) or not invoice["id"]
                    or type(invoice["revision"]) is not int or invoice["revision"] < 1):
                raise ValueError("Each invoice requires an id and positive revision")
        if len({i["id"] for i in invoices}) != len(invoices):
            raise ValueError("Invoice ids must be unique within the document")

    def validate_evidence(self, work: dict, candidate: dict) -> bool:
        data = candidate["data"]
        kind = candidate["kind"]
        if kind == "invoice_valid":
            return (set(data) == {"invoice_id", "invoice_revision", "valid"}
                    and type(data["invoice_revision"]) is int
                    and data["invoice_revision"] > 0
                    and isinstance(data["invoice_id"], str)
                    and type(data["valid"]) is bool)
        if kind == "accepted":
            return (set(data) == {"digest", "external_id"}
                    and isinstance(data["digest"], str)
                    and isinstance(data["external_id"], str)
                    and bool(data["external_id"]))
        return set(data) == {"digest"} and isinstance(data["digest"], str)

    def evaluate(self, work: dict, evidence: List[dict]) -> List[dict]:
        document = work["document"]
        current = work["document_digest"]
        proofs = [e for e in evidence if e["status"] == "verified"]

        def has(kind: str) -> bool:
            return any(e["kind"] == kind and e["data"].get("digest") == current
                       for e in proofs)

        result = []

        def add(rule: str, subject: str, applicable: str, satisfied: bool,
                explanation: str) -> None:
            result.append({"id": rule + ":" + subject, "rule_id": rule,
                           "subject": subject, "applicability": applicable,
                           "fulfillment": "satisfied" if satisfied else "pending",
                           "explanation": explanation})

        add("E01", document["id"], "applicable",
            bool(document["invoices"]) and document["sealed"],
            "The current invoice set must be nonempty and sealed")
        for invoice in document["invoices"]:
            valid = any(e["kind"] == "invoice_valid"
                        and e["data"].get("invoice_id") == invoice["id"]
                        and e["data"].get("invoice_revision") == invoice["revision"]
                        and e["data"].get("valid") is True for e in proofs)
            add("E02", invoice["id"], "applicable", valid,
                "Trusted verification must cover this invoice revision")
        add("E03", document["id"], "applicable", has("duplicate_clear"),
            "Precheck plus adapter-enforced uniqueness at external acceptance")
        known = document["amount"] is not None and document["limit"] is not None
        add("E04", document["id"], "applicable", known,
            "Amount and applicable limit must be known")
        over = known and document["amount"] > document["limit"]
        add("E05", document["id"], self.approval_applicability(known, over),
            has("approval"), "Over-limit submissions require approval of the current content")
        add("E06", document["id"], "applicable", has("confirmation"),
            "The requester must confirm the current content")
        add("E08", document["id"], "applicable", has("accepted"),
            "OA must accept the current content before successful completion")
        return result

    def action_blockers(self, capability: str, requirements: List[dict]) -> List[dict]:
        if capability != "expense.submit":
            # A paired compensating capability is admitted through its link
            # check (runtime), not requirements: its blockers are empty.
            if self.compensation_capabilities.get(capability) == "expense.submit":
                return []
            return [{"code": "CAPABILITY_UNSUPPORTED", "capability": capability}]
        return [r for r in requirements if r["rule_id"] != "E08" and
                (r["applicability"] in ("unknown", "conflict") or
                 (r["applicability"] == "applicable" and r["fulfillment"] != "satisfied"))]

    def approval_applicability(self, known: bool, over: bool) -> str:
        return "unknown" if not known else "applicable" if over else "not_applicable"

    def operation_key(self, capability: str, work: dict) -> str:
        return digest([self.id, capability, work["document"]["id"],
                       work["document_revision"]])


class ExpensePolicyV2(ExpensePolicy):
    """Illustrative stronger published policy: every known amount needs approval.

    Same family, goal, capability and business-key function as demo-1; only
    the approval rule is strengthened. This demonstrates explicit same-family
    policy migration; it is not a real enterprise rule.
    """

    version = "demo-2"

    def approval_applicability(self, known: bool, over: bool) -> str:
        return "unknown" if not known else "applicable"

    def evaluate(self, work: dict, evidence: list) -> list:
        requirements = super().evaluate(work, evidence)
        for requirement in requirements:
            if requirement["rule_id"] == "E05":
                # Same rule, truthful guidance: v2 demands approval for every
                # known amount and the approval proof is version-bound.
                requirement["explanation"] = ("Every known amount requires version-bound "
                                              "approval of the current content")
        return requirements

    def validate_evidence(self, work: dict, candidate: dict) -> bool:
        if candidate["kind"] == "approval":
            data = candidate["data"]
            return (set(data) == {"digest", "policy_version"}
                    and isinstance(data["digest"], str)
                    and data["policy_version"] == self.version)
        return super().validate_evidence(work, candidate)
