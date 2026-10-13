"""Content publication domain tests: policy rules, adapter, runtime flow, demo, CLI."""

import contextlib
import io
import json
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from work_runtime import Runtime
from work_runtime.ingress import SignedEvidenceGateway, sign_evidence
from work_runtime.policy import digest
from work_runtime.publishing import FakePublisher, PublishingPolicy
from work_runtime.publishing_demo import run_demo

try:
    from adapter_conformance import AdapterConformanceMixin
except ImportError:
    from tests.adapter_conformance import AdapterConformanceMixin


def article(article_id="ART-001", title="Release notes", body="Draft body",
            requires_review=True):
    return {"id": article_id, "title": title, "body": body,
            "requires_review": requires_review}


def publishing_grants():
    return {"agent": {"work.manage", "content.publish"},
            "reviewer": {"evidence.write"}, "author": {"evidence.write"}}


def proof(kind, source, data, status="verified"):
    return {"id": uuid.uuid4().hex, "source": source, "event_id": uuid.uuid4().hex,
            "kind": kind, "data": data, "status": status}


def work_state(document=None):
    doc = article() if document is None else document
    return {"id": "w1", "document": doc, "document_digest": digest(doc)}


def requirement(rules, rule_id):
    return next(r for r in rules if r["rule_id"] == rule_id)


class PublishingDocumentTests(unittest.TestCase):
    def setUp(self):
        self.policy = PublishingPolicy()

    def test_valid_documents_cover_all_review_states(self):
        for requires_review in (True, False, None):
            with self.subTest(requires_review=requires_review):
                self.policy.validate_document(article(requires_review=requires_review))

    def test_document_requires_exact_fields(self):
        for field in ("id", "title", "body", "requires_review"):
            missing = {k: v for k, v in article().items() if k != field}
            with self.subTest(missing=field):
                with self.assertRaises(ValueError):
                    self.policy.validate_document(missing)
        with self.assertRaises(ValueError):
            self.policy.validate_document({**article(), "invoices": []})

    def test_identity_strings_must_be_nonempty(self):
        for field in ("id", "title", "body"):
            for bad in ("", 7, None):
                with self.subTest(field=field, bad=bad):
                    with self.assertRaises(ValueError):
                        self.policy.validate_document({**article(), field: bad})

    def test_requires_review_must_be_bool_or_none(self):
        for bad in (1, 0, "yes", [True]):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.policy.validate_document({**article(), "requires_review": bad})


class PublishingEvidenceShapeTests(unittest.TestCase):
    def setUp(self):
        self.policy = PublishingPolicy()
        self.work = work_state()

    def check(self, kind, data):
        return self.policy.validate_evidence(self.work, {"kind": kind, "data": data})

    def test_review_and_confirmation_require_exact_digest_shape(self):
        for kind in ("approval", "confirmation"):
            self.assertTrue(self.check(kind, {"digest": "a" * 64}), kind)
            for bad in ({}, {"digest": "a" * 64, "note": "x"}, {"digest": 5},
                        {"digest": None}, set()):
                with self.subTest(kind=kind, bad=bad):
                    self.assertFalse(self.check(kind, bad))

    def test_accepted_requires_digest_and_nonempty_external_id(self):
        self.assertTrue(self.check("accepted", {"digest": "a" * 64, "external_id": "PUB-1"}))
        for bad in ({"digest": "a" * 64, "external_id": ""},
                    {"digest": "a" * 64, "external_id": 7},
                    {"digest": "a" * 64},
                    {"external_id": "PUB-1"},
                    {"digest": "a" * 64, "external_id": "PUB-1", "extra": True}):
            with self.subTest(bad=bad):
                self.assertFalse(self.check("accepted", bad))

    def test_unknown_kinds_are_invalid(self):
        for kind in ("invoice_valid", "duplicate_clear", "", None):
            with self.subTest(kind=kind):
                self.assertFalse(self.check(kind, {"digest": "a" * 64}))


class PublishingEvaluateTests(unittest.TestCase):
    def setUp(self):
        self.policy = PublishingPolicy()
        self.work = work_state()
        self.current = self.work["document_digest"]

    def rules(self, document=None, proofs=()):
        work = work_state(document)
        return self.policy.evaluate(work, list(proofs))

    def test_review_rule_applicability_matrix(self):
        for requires_review, expected in ((True, "applicable"), (False, "not_applicable"),
                                          (None, "unknown")):
            with self.subTest(requires_review=requires_review):
                rules = self.rules(article(requires_review=requires_review))
                self.assertEqual(requirement(rules, "C02")["applicability"], expected)
                self.assertEqual(requirement(rules, "C02")["fulfillment"], "pending")

    def test_current_digest_evidence_from_configured_sources_satisfies_rules(self):
        rules = self.rules(proofs=[
            proof("approval", "reviewer", {"digest": self.current}),
            proof("confirmation", "author", {"digest": self.current}),
            proof("accepted", "publisher",
                  {"digest": self.current, "external_id": "PUB-1"})])
        self.assertEqual(requirement(rules, "C01")["fulfillment"], "satisfied")
        for rule_id in ("C02", "C03", "C04"):
            self.assertEqual(requirement(rules, rule_id)["fulfillment"], "satisfied", rule_id)
            self.assertEqual(requirement(rules, rule_id)["applicability"], "applicable", rule_id)

    def test_old_digest_evidence_leaves_rules_pending(self):
        old = digest(article(body="previous body"))
        rules = self.rules(proofs=[
            proof("approval", "reviewer", {"digest": old}),
            proof("confirmation", "author", {"digest": old}),
            proof("accepted", "publisher", {"digest": old, "external_id": "PUB-0"})])
        for rule_id in ("C02", "C03", "C04"):
            self.assertEqual(requirement(rules, rule_id)["fulfillment"], "pending", rule_id)

    def test_wrong_source_does_not_satisfy_rules(self):
        rules = self.rules(proofs=[
            proof("approval", "author", {"digest": self.current}),
            proof("confirmation", "reviewer", {"digest": self.current}),
            proof("accepted", "author",
                  {"digest": self.current, "external_id": "PUB-1"})])
        for rule_id in ("C02", "C03", "C04"):
            self.assertEqual(requirement(rules, rule_id)["fulfillment"], "pending", rule_id)

    def test_unverified_evidence_does_not_satisfy_rules(self):
        rules = self.rules(proofs=[
            proof("approval", "reviewer", {"digest": self.current},
                  status="pending_verification"),
            proof("confirmation", "author", {"digest": self.current},
                  status="pending_verification")])
        for rule_id in ("C02", "C03"):
            self.assertEqual(requirement(rules, rule_id)["fulfillment"], "pending", rule_id)

    def test_plan_content_cannot_remove_review_requirement(self):
        work = work_state()
        work["plan"] = {"steps": ["publish"], "open_requirements": [],
                        "replan_when": []}
        rules = self.policy.evaluate(work, [])
        blockers = self.policy.action_blockers("content.publish", rules)
        self.assertIn("C02:" + work["document"]["id"],
                      [b["id"] for b in blockers])

    def test_action_blockers_track_applicability_and_exclude_accepted_rule(self):
        rules = self.rules(article(requires_review=None))
        blockers = self.policy.action_blockers("content.publish", rules)
        self.assertEqual([b["rule_id"] for b in blockers], ["C02", "C03"])
        self.assertEqual(blockers[0]["applicability"], "unknown")
        self.assertNotIn("C04", [b["rule_id"] for b in blockers])
        satisfied = self.rules(article(requires_review=False), proofs=[
            proof("confirmation", "author", {"digest": digest(article(requires_review=False))})])
        self.assertEqual(
            self.policy.action_blockers("content.publish", satisfied), [])

    def test_unsupported_capability_is_always_blocked(self):
        blockers = self.policy.action_blockers(
            "expense.submit", self.rules(article(requires_review=False)))
        self.assertEqual(blockers, [{"code": "CAPABILITY_UNSUPPORTED",
                                     "capability": "expense.submit"}])

    def test_operation_key_is_content_digest_bound(self):
        work = work_state()
        changed = work_state(article(body="revised body"))
        key = self.policy.operation_key("content.publish", work)
        self.assertEqual(key, digest(["content-publish", "content.publish",
                                      work["document"]["id"], work["document_digest"]]))
        self.assertNotEqual(key, self.policy.operation_key("content.publish", changed))


if __name__ == "__main__":
    unittest.main()


class PublishingCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "work_runtime", *args],
                              capture_output=True, text=True)

    def test_publish_demo_command_runs_the_harness(self):
        result = self.run_cli("publish-demo", "--directory", self.temp.name)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("published artifacts: 1", result.stdout)

    def test_inspect_content_publish_policy_reads_publication_work(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            folder = run_demo(directory=self.temp.name)
        result = self.run_cli("inspect", "--db", str(Path(folder) / "runtime.sqlite"),
                              "--work", "article-1", "--policy", "content-publish")
        self.assertEqual(result.returncode, 0, result.stderr)
        snapshot = json.loads(result.stdout)
        self.assertEqual(snapshot["work"]["contract"]["goal"], "content.published")
        self.assertEqual(snapshot["work"]["status"], "closed")

    def test_inspect_defaults_to_expense_policy(self):
        from work_runtime.demo import run_demo as expense_demo
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            folder = expense_demo(self.temp.name)
        result = self.run_cli("inspect", "--db", str(Path(folder) / "runtime.sqlite"))
        self.assertEqual(result.returncode, 0, result.stderr)
        snapshot = json.loads(result.stdout)
        self.assertEqual(snapshot["work"]["contract"]["goal"], "expense.accepted")

    def test_inspect_rejects_unknown_policy_choice(self):
        result = self.run_cli("inspect", "--db", "unused.sqlite", "--policy", "bogus")
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)


class PublishingDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def run_capture(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            folder = run_demo(directory=self.temp.name)
        return folder, buffer.getvalue()

    def test_demo_story_and_independent_publication_count(self):
        folder, output = self.run_capture()
        for expected in ("1.", "2.", "3.", "4.", "5.", "6.", "BLOCKED",
                         "EVIDENCE_AUTHENTICATION_FAILED", "published artifacts: 1",
                         "--policy content-publish"):
            self.assertIn(expected, output)
        runtime_path = Path(folder) / "runtime.sqlite"
        publisher_path = Path(folder) / "publisher.sqlite"
        self.assertTrue(runtime_path.exists())
        self.assertTrue(publisher_path.exists())
        with sqlite3.connect(str(publisher_path)) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM publications").fetchone()[0], 1)
        self.assertNotRegex(output, "[0-9a-f]{64}")

    def test_demo_runs_repeatably_in_fresh_directories(self):
        first, first_output = self.run_capture()
        second, second_output = self.run_capture()
        self.assertIn("published artifacts: 1", first_output)
        self.assertIn("published artifacts: 1", second_output)
        self.assertNotEqual(first, second)
        for folder in (first, second):
            with sqlite3.connect(str(Path(folder) / "publisher.sqlite")) as db:
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM publications").fetchone()[0], 1)


class CountingPublisher:
    """Delegates to a real adapter while counting external interactions."""

    contract = FakePublisher.contract

    def __init__(self, inner):
        self.inner = inner
        self.executed = 0
        self.looked_up = 0

    def execute(self, *args):
        self.executed += 1
        return self.inner.execute(*args)

    def lookup(self, *args):
        self.looked_up += 1
        return self.inner.lookup(*args)


def evidence_kinds(path):
    with sqlite3.connect(path) as db:
        return [json.loads(r[0])["kind"] for r in db.execute("SELECT body FROM evidence")]


def table_counts(path):
    with sqlite3.connect(path) as db:
        return {t: db.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
                for t in ("works", "commands", "evidence", "operations", "events", "metadata")}


class PublishingFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "runtime.sqlite")
        self.publisher_path = str(Path(self.temp.name) / "publisher.sqlite")
        self.now = 2000000000
        self.reviewer_key = secrets.token_bytes(32)
        self.author_key = secrets.token_bytes(32)
        self.runtime = self.fresh_runtime()
        self.work_id = "article-1"
        self.gateway = SignedEvidenceGateway(
            self.runtime, {"reviewer": self.reviewer_key, "author": self.author_key},
            clock=lambda: self.now)

    def fresh_runtime(self):
        return Runtime(self.path, PublishingPolicy(), publishing_grants())

    def send(self, kind, payload=None, actor="agent", command_id=None):
        version = None if kind in ("create_work", "record_evidence") \
            else self.runtime.get_work(self.work_id)["state_version"]
        return self.runtime.command(actor, command_id or uuid.uuid4().hex,
                                    self.work_id, kind, payload, version)

    def initialize(self, requires_review=True):
        self.send("create_work",
                  {"document": article(requires_review=requires_review)})
        self.send("bind_contract", {"policy_id": "content-publish",
                                    "policy_version": "demo-1",
                                    "goal": "content.published"})
        self.send("revise_plan", {"steps": ["draft", "review", "confirm", "publish"],
                                  "open_requirements": ["C02"],
                                  "replan_when": ["reviewer rejects"]})

    def signed(self, source, secret, kind, data, command_id=None, event_id=None):
        return sign_evidence(secret, {
            "source": source, "command_id": command_id or uuid.uuid4().hex,
            "work_id": self.work_id, "event_id": event_id or uuid.uuid4().hex,
            "kind": kind, "data": data, "issued_at": self.now})

    def approve_and_confirm(self, digest_value=None):
        current = digest_value or self.runtime.get_work(self.work_id)["document_digest"]
        self.gateway.record(self.signed("reviewer", self.reviewer_key, "approval",
                                        {"digest": current}))
        self.gateway.record(self.signed("author", self.author_key, "confirmation",
                                        {"digest": current}))
        self.runtime.verify_pending(self.work_id)

    def propose(self, command_id=None):
        work = self.runtime.get_work(self.work_id)
        return self.send("propose_action", {
            "capability": "content.publish", "document_digest": work["document_digest"],
            "contract_revision": work["contract"]["revision"],
            "plan_revision": work["plan_revision"]}, command_id=command_id)

    def requirement(self, rule_id):
        return requirement(self.runtime.get_work(self.work_id)["requirements"], rule_id)

    def test_missing_review_blocks_publication(self):
        self.initialize(requires_review=True)
        receipt = self.propose()
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "REQUIREMENT_UNSATISFIED")
        blockers = [b["id"] for b in receipt["blockers"]]
        self.assertIn("C02:ART-001", blockers)
        self.assertIn("C03:ART-001", blockers)

    def test_unknown_review_state_blocks_with_applicability_unresolved(self):
        self.initialize(requires_review=None)
        receipt = self.propose()
        self.assertEqual(receipt["decision"], "rejected")
        self.assertEqual(receipt["code"], "APPLICABILITY_UNRESOLVED")
        self.assertIn("C02", [b["rule_id"] for b in receipt["blockers"]])

    def test_plan_revision_cannot_remove_review_requirement(self):
        self.initialize(requires_review=True)
        self.send("revise_plan", {"steps": ["publish"], "open_requirements": [],
                                  "replan_when": []})
        receipt = self.propose()
        self.assertEqual(receipt["code"], "REQUIREMENT_UNSATISFIED")
        self.assertIn("C02:ART-001", [b["id"] for b in receipt["blockers"]])

    def test_content_revision_invalidates_approval_and_confirmation(self):
        self.initialize(requires_review=True)
        self.approve_and_confirm()
        stale_operation = self.propose(command_id="publish-old")["operation_id"]
        self.send("revise_document", {"document": article(body="Revised after review")})
        for rule_id in ("C02", "C03"):
            self.assertEqual(self.requirement(rule_id)["fulfillment"], "pending", rule_id)
        persisted = self.runtime.get_operation(stale_operation)
        self.assertEqual((persisted["dispatch_state"], persisted["reason"]),
                         ("cancelled", "STALE_INTENT"))
        old_digest = digest(article())
        self.approve_and_confirm(digest_value=old_digest)
        self.assertEqual(self.requirement("C02")["fulfillment"], "pending")
        self.assertEqual(self.propose()["code"], "REQUIREMENT_UNSATISFIED")
        self.approve_and_confirm()
        self.assertEqual(self.propose(command_id="publish-new")["decision"], "accepted")

    def test_signed_evidence_stays_pending_until_verification(self):
        self.initialize(requires_review=True)
        current = self.runtime.get_work(self.work_id)["document_digest"]
        receipt = self.gateway.record(self.signed("reviewer", self.reviewer_key,
                                                  "approval", {"digest": current}))
        self.assertEqual(receipt["decision"], "accepted")
        self.assertEqual(receipt["evidence_status"], "pending_verification")
        self.assertEqual(self.requirement("C02")["fulfillment"], "pending")
        self.runtime.verify_pending(self.work_id)
        self.assertEqual(self.requirement("C02")["fulfillment"], "satisfied")

    def test_tampered_signed_approval_is_rejected_before_intake(self):
        self.initialize(requires_review=True)
        current = self.runtime.get_work(self.work_id)["document_digest"]
        envelope = self.signed("reviewer", self.reviewer_key, "approval",
                               {"digest": current})
        envelope["data"]["digest"] = "f" * 64
        before = table_counts(self.path)
        receipt = self.gateway.record(envelope)
        self.assertEqual(receipt,
                         {"decision": "rejected", "code": "EVIDENCE_AUTHENTICATION_FAILED"})
        self.assertEqual(table_counts(self.path), before)

    def test_full_goal_completion_with_one_publication(self):
        self.initialize(requires_review=True)
        self.approve_and_confirm()
        operation = self.propose(command_id="publish-once")["operation_id"]
        resolved = self.runtime.dispatch(operation, FakePublisher(self.publisher_path))
        self.assertEqual(resolved["status"], "confirmed_succeeded")
        self.assertEqual(self.requirement("C04")["fulfillment"], "satisfied")
        completion = self.send("request_completion")
        self.assertEqual(completion["decision"], "accepted")
        work = self.runtime.get_work(self.work_id)
        self.assertEqual((work["status"], work["outcome"]), ("closed", "succeeded"))
        self.assertEqual(FakePublisher(self.publisher_path).published_count(), 1)
        self.assertEqual(sorted(evidence_kinds(self.path)),
                         ["accepted", "approval", "confirmation"])

    def test_timeout_after_commit_recovers_by_lookup_without_resend(self):
        self.initialize(requires_review=True)
        self.approve_and_confirm()
        operation = self.propose(command_id="publish-once")["operation_id"]
        flaky = CountingPublisher(
            FakePublisher(self.publisher_path, timeout_after_commit=True))
        unknown = self.runtime.dispatch(operation, flaky)
        self.assertEqual(unknown["status"], "outcome_unknown")
        self.assertEqual(flaky.executed, 1)
        self.assertEqual(FakePublisher(self.publisher_path).published_count(), 1)
        restarted = self.fresh_runtime()
        recovery = CountingPublisher(FakePublisher(self.publisher_path))
        recovered = restarted.reconcile(operation, recovery)
        self.assertEqual(recovered["status"], "confirmed_succeeded")
        self.assertEqual((recovery.executed, recovery.looked_up), (0, 1))
        self.assertEqual(len(restarted.get_operation(operation)["attempts"]), 1)
        completion = restarted.command("agent", "complete", self.work_id,
                                       "request_completion", None,
                                       restarted.get_work(self.work_id)["state_version"])
        self.assertEqual(completion["decision"], "accepted")
        self.assertEqual(FakePublisher(self.publisher_path).published_count(), 1)


class MalformedResultTests(unittest.TestCase):
    """One isolated runtime+publisher fixture per variant; the real adapter executes."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 2000000000

    def drive_to_dispatch(self, name, mutate):
        base = str(Path(self.temp.name) / name)
        runtime = Runtime(base + "-runtime.sqlite", PublishingPolicy(), publishing_grants())
        reviewer_key, author_key = secrets.token_bytes(32), secrets.token_bytes(32)
        gateway = SignedEvidenceGateway(runtime, {"reviewer": reviewer_key,
                                                  "author": author_key},
                                        clock=lambda: self.now)

        def send(kind, payload=None):
            version = None if kind == "create_work" else runtime.get_work("a")["state_version"]
            return runtime.command("agent", uuid.uuid4().hex, "a", kind, payload, version)

        send("create_work", {"document": article()})
        send("bind_contract", {"policy_id": "content-publish", "policy_version": "demo-1",
                               "goal": "content.published"})
        send("revise_plan", {"steps": ["review", "confirm", "publish"],
                             "open_requirements": ["C02"], "replan_when": []})
        current = runtime.get_work("a")["document_digest"]
        for source, secret, kind in (("reviewer", reviewer_key, "approval"),
                                     ("author", author_key, "confirmation")):
            gateway.record(sign_evidence(secret, {
                "source": source, "command_id": uuid.uuid4().hex, "work_id": "a",
                "event_id": uuid.uuid4().hex, "kind": kind, "data": {"digest": current},
                "issued_at": self.now}))
        runtime.verify_pending("a")
        work = runtime.get_work("a")
        operation = send("propose_action", {
            "capability": "content.publish", "document_digest": work["document_digest"],
            "contract_revision": work["contract"]["revision"],
            "plan_revision": work["plan_revision"]})["operation_id"]

        class Tampered:
            contract = FakePublisher.contract

            def __init__(self):
                self.executed = 0
                self.inner = FakePublisher(base + "-publisher.sqlite")

            def execute(self, *args):
                self.executed += 1
                return mutate(self.inner.execute(*args))

            def lookup(self, *args):
                return self.inner.lookup(*args)

        adapter = Tampered()
        return runtime, adapter, runtime.dispatch(operation, adapter)

    def test_malformed_results_are_quarantined_without_accepted_proof(self):
        def drop(result, key):
            return {k: v for k, v in result.items() if k != key}

        variants = {
            "none": lambda result: None,
            "string": lambda result: "accepted",
            "missing-external-id": lambda result: drop(result, "external_id"),
            "empty-external-id": lambda result: {**result, "external_id": ""},
            "wrong-digest": lambda result: {**result, "digest": "0" * 64},
            "bad-status": lambda result: {**result, "status": "pending"},
        }
        for name, mutate in variants.items():
            with self.subTest(variant=name):
                runtime, adapter, dispatched = self.drive_to_dispatch(name, mutate)
                self.assertEqual(dispatched["status"], "outcome_unknown")
                self.assertEqual(dispatched["reason"], "ADAPTER_RESULT_INVALID")
                self.assertEqual(adapter.executed, 1)
                self.assertEqual(adapter.inner.published_count(), 1)
                self.assertEqual(runtime.get_work("a")["status"], "needs_attention")
                self.assertNotIn("accepted", evidence_kinds(runtime.path))


class FakePublisherConformanceTests(AdapterConformanceMixin, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def make_adapter(self):
        return FakePublisher(str(Path(self.temp.name) / ("publisher-" + uuid.uuid4().hex + ".sqlite")))

    def sample_document(self):
        return article()

    def changed_document(self):
        return article(body="A substantially revised body")

    def effect_count(self, adapter):
        return adapter.published_count()


def store_counts(path):
    db = sqlite3.connect(path)
    try:
        return {t: db.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
                for t in ("receipts", "publications")}
    finally:
        db.close()


class FakePublisherDomainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "publisher.sqlite")

    def test_digest_mismatch_is_rejected_without_writes(self):
        publisher = FakePublisher(self.path)
        doc = article()
        with self.assertRaises(ValueError):
            publisher.execute("key-1", doc, digest(article(body="other")))
        self.assertEqual(store_counts(self.path), {"receipts": 0, "publications": 0})

    def test_same_key_different_content_raises_without_new_effect(self):
        publisher = FakePublisher(self.path)
        doc = article()
        publisher.execute("key-1", doc, digest(doc))
        with self.assertRaises(ValueError):
            publisher.execute("key-1", article(body="changed"), digest(article(body="changed")))
        self.assertEqual(store_counts(self.path), {"receipts": 1, "publications": 1})

    def test_duplicate_content_under_another_key_reuses_external_id_and_one_artifact(self):
        publisher = FakePublisher(self.path)
        doc = article()
        first = publisher.execute("key-1", doc, digest(doc))
        second = publisher.execute("key-2", doc, digest(doc))
        self.assertEqual(first["external_id"], second["external_id"])
        self.assertEqual(store_counts(self.path), {"receipts": 2, "publications": 1})
        self.assertEqual(publisher.published_count(), 1)

    def test_changed_content_under_another_key_adds_a_publication_version(self):
        publisher = FakePublisher(self.path)
        original = article()
        revised = article(body="Revised body")
        first = publisher.execute("key-1", original, digest(original))
        second = publisher.execute("key-2", revised, digest(revised))
        self.assertNotEqual(first["external_id"], second["external_id"])
        self.assertEqual(store_counts(self.path), {"receipts": 2, "publications": 2})

    def test_timeout_after_commit_raises_with_publication_committed(self):
        publisher = FakePublisher(self.path, timeout_after_commit=True)
        doc = article()
        with self.assertRaises(TimeoutError):
            publisher.execute("key-1", doc, digest(doc))
        self.assertEqual(store_counts(self.path), {"receipts": 1, "publications": 1})
        replay = FakePublisher(self.path)
        self.assertEqual(replay.lookup("key-1")["external_id"],
                         sqlite3.connect(self.path).execute(
                             "SELECT external_id FROM publications").fetchone()[0])

    def test_lookup_missing_key_returns_none_and_persisted_document_matches(self):
        publisher = FakePublisher(self.path)
        self.assertIsNone(publisher.lookup("missing"))
        doc = article()
        publisher.execute("key-1", doc, digest(doc))
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT document_id,digest,document FROM publications").fetchone()
        self.assertEqual((row[0], row[1]), (doc["id"], digest(doc)))
        self.assertEqual(json.loads(row[2]), doc)
