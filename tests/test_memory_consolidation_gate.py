from __future__ import annotations

from dataclasses import replace
import hashlib
import unittest

from star.memory_consolidation_gate import (
    MemoryConsolidationCandidate,
    MemoryConsolidationPolicy,
    evaluate_consolidation,
    seal_candidate,
    verify_decision,
)

KEY = b"star-memory-consolidation-test-key-32-bytes!!"
NOW = 1_800_000_000_000


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def candidate(**overrides):
    values = dict(
        candidate_id="memory-001",
        candidate_sha256=sha("candidate"),
        evidence_sha256=sha("evidence-set"),
        tier="semantic",
        privacy_scope="project_private",
        dependency_manifest_sha256=sha("deps-v1"),
        current_dependency_manifest_sha256=sha("deps-v1"),
        previous_snapshot_sha256=sha("previous-snapshot"),
        proposed_snapshot_sha256=sha("proposed-snapshot"),
        created_at_ms=NOW - 1000,
        expires_at_ms=NOW + 60_000,
        evidence_count=2,
        independent_source_count=2,
        verified_outcome_count=2,
        verified_edge_case_count=0,
        unresolved_conflict_count=0,
        untrusted_source_count=0,
        stale_dependency_count=0,
    )
    values.update(overrides)
    return seal_candidate(MemoryConsolidationCandidate(**values), KEY)


class MemoryConsolidationGateTests(unittest.TestCase):
    def evaluate(self, item, policy=None, now=NOW):
        return evaluate_consolidation(
            item, policy or MemoryConsolidationPolicy(), trusted_host_key=KEY, now_ms=now
        )

    def test_valid_semantic_candidate_is_only_eligible_for_owner_review(self):
        decision = self.evaluate(candidate())
        self.assertEqual(decision.status, "eligible_for_owner_review")
        self.assertTrue(decision.eligible_for_owner_review)
        self.assertTrue(verify_decision(decision, KEY))

    def test_decision_contains_rollback_snapshot(self):
        item = candidate()
        decision = self.evaluate(item)
        self.assertEqual(decision.rollback_to_sha256, item.previous_snapshot_sha256)

    def test_bad_candidate_signature_is_rejected(self):
        item = replace(candidate(), signature="0" * 64)
        with self.assertRaises(PermissionError):
            self.evaluate(item)

    def test_changed_dependency_state_requires_revalidation(self):
        item = candidate(current_dependency_manifest_sha256=sha("deps-v2"))
        decision = self.evaluate(item)
        self.assertEqual(decision.status, "revalidation_required")

    def test_expired_candidate_requires_revalidation(self):
        item = candidate(expires_at_ms=NOW - 1)
        decision = self.evaluate(item)
        self.assertEqual(decision.status, "revalidation_required")

    def test_future_candidate_requires_revalidation(self):
        item = candidate(created_at_ms=NOW + 1, expires_at_ms=NOW + 60_000)
        decision = self.evaluate(item)
        self.assertEqual(decision.status, "revalidation_required")

    def test_stale_dependency_counter_requires_revalidation(self):
        item = candidate(stale_dependency_count=1)
        decision = self.evaluate(item)
        self.assertEqual(decision.status, "revalidation_required")

    def test_conflicting_evidence_is_quarantined(self):
        item = candidate(unresolved_conflict_count=1)
        decision = self.evaluate(item)
        self.assertEqual(decision.status, "quarantined")
        self.assertIn("unresolved_evidence_conflict", decision.reasons)

    def test_untrusted_source_is_quarantined(self):
        item = candidate(untrusted_source_count=1)
        decision = self.evaluate(item)
        self.assertEqual(decision.status, "quarantined")
        self.assertIn("untrusted_evidence_source", decision.reasons)

    def test_viewer_private_memory_is_blocked(self):
        item = candidate(privacy_scope="viewer_private")
        decision = self.evaluate(item)
        self.assertEqual(decision.status, "blocked")

    def test_raw_media_memory_is_blocked(self):
        item = candidate(privacy_scope="raw_media")
        decision = self.evaluate(item)
        self.assertEqual(decision.status, "blocked")

    def test_insufficient_semantic_independent_sources_is_not_promoted(self):
        item = candidate(independent_source_count=1)
        decision = self.evaluate(item)
        self.assertEqual(decision.status, "insufficient_evidence")
        self.assertIn("independent_sources_below_policy", decision.reasons)

    def test_insufficient_verified_outcomes_is_not_promoted(self):
        item = candidate(verified_outcome_count=1)
        decision = self.evaluate(item)
        self.assertEqual(decision.status, "insufficient_evidence")

    def test_procedural_memory_requires_edge_case_coverage(self):
        item = candidate(
            tier="procedural", independent_source_count=1, verified_edge_case_count=0
        )
        decision = self.evaluate(item)
        self.assertEqual(decision.status, "insufficient_evidence")
        self.assertIn("procedural_edge_case_coverage_below_policy", decision.reasons)

    def test_procedural_memory_with_edge_case_is_reviewable(self):
        item = candidate(
            tier="procedural", independent_source_count=1, verified_edge_case_count=1
        )
        decision = self.evaluate(item)
        self.assertEqual(decision.status, "eligible_for_owner_review")

    def test_policy_digest_changes_when_threshold_changes(self):
        first = MemoryConsolidationPolicy()
        second = replace(first, semantic_min_sources=3, semantic_min_evidence=3)
        self.assertNotEqual(first.sha256, second.sha256)

    def test_inconsistent_counts_are_rejected(self):
        with self.assertRaises(ValueError):
            candidate(independent_source_count=3)

    def test_invalid_clock_is_rejected(self):
        with self.assertRaises(ValueError):
            self.evaluate(candidate(), now=True)

    def test_invalid_key_is_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_consolidation(
                candidate(), MemoryConsolidationPolicy(), trusted_host_key=b"short", now_ms=NOW
            )


if __name__ == "__main__":
    unittest.main()
