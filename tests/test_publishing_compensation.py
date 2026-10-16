"""S14 publishing-compensation core: linked content.unpublish retraction.

Implements the master-ratified design D80-D91: linked compensation for the
publishing family inside the active cancellation window, on the unchanged
S10 machinery. Publishing family and active-cancellation window only;
post-closure compensation, chains, cross-work compensation and intervener
authority remain deferred scope. `content.unpublish` (content family) is
distinct from S13's `sop.withdraw` (SOP authoring family).
"""

import unittest

from work_runtime.file_adapter import FilePublisher
from work_runtime.publishing import FakePublisher, PublishingPolicy


def publishing_compensation_grants():
    """Demo grants with the compensating capability held by the owner."""
    return {"agent": {"work.manage", "content.publish", "content.unpublish"},
            "reviewer": {"evidence.write"}, "author": {"evidence.write"},
            "admin": {"work.intervene"}}


def pending_requirements():
    """C01-C03 pending requirement results, the pre-publication state."""
    return [{"id": "C01:ART-001", "rule_id": "C01", "subject": "ART-001",
             "applicability": "applicable", "fulfillment": "pending",
             "explanation": "The current artifact must be complete"},
            {"id": "C02:ART-001", "rule_id": "C02", "subject": "ART-001",
             "applicability": "applicable", "fulfillment": "pending",
             "explanation": "A true requires_review needs the reviewer's approval"},
            {"id": "C03:ART-001", "rule_id": "C03", "subject": "ART-001",
             "applicability": "applicable", "fulfillment": "pending",
             "explanation": "The author must confirm the current content"}]


class PolicyPairingTests(unittest.TestCase):
    def test_paired_capability_attribute_and_empty_blockers(self):
        policy = PublishingPolicy()
        self.assertEqual(policy.compensation_capabilities,
                         {"content.unpublish": "content.publish"})
        # A paired compensating capability is admitted through its link check
        # (runtime), never through requirements: its blockers are empty even
        # while every publication requirement is still pending.
        self.assertEqual(policy.action_blockers("content.unpublish",
                                                pending_requirements()), [])

    def test_off_family_capabilities_stay_unsupported(self):
        policy = PublishingPolicy()
        for capability in ("content.withdraw", "expense.submit", "expense.withdraw"):
            with self.subTest(capability=capability):
                self.assertEqual(
                    policy.action_blockers(capability, pending_requirements()),
                    [{"code": "CAPABILITY_UNSUPPORTED", "capability": capability}])

    def test_forward_capability_blockers_shape_unchanged(self):
        policy = PublishingPolicy()
        pending = pending_requirements()
        # The forward filter keeps returning the pending requirement objects.
        self.assertEqual(policy.action_blockers("content.publish", pending), pending)

    def test_policy_version_is_unchanged(self):
        # D89: the pairing is a family declaration, not a new policy version.
        self.assertEqual(PublishingPolicy.version, "demo-1")

    def test_file_publisher_stays_forward_only(self):
        # D88: FilePublisher is untouched — no pairing, forward-only contract.
        self.assertFalse(getattr(FilePublisher, "compensation_capabilities", None))
        self.assertEqual(FilePublisher.contract.actions, ("content.publish",))
        self.assertIs(FilePublisher.contract.supports_action_context, False)


if __name__ == "__main__":
    unittest.main()
