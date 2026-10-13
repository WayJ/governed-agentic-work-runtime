"""Content publication domain tests: policy rules, adapter, runtime flow, demo, CLI."""

import unittest
import uuid

from work_runtime.policy import digest
from work_runtime.publishing import PublishingPolicy


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
