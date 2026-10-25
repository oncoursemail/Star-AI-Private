"""Offline privacy, provenance and contextual grounding tests for Star streams."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from star.knowledge import KnowledgeStore
from star.stream_knowledge import KnowledgePacket, public_knowledge_packet
from star.stream_stage import StarStage
from star.stream_director import StreamSignal


class StreamKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = KnowledgeStore(Path(self.temp.name))
        self.addCleanup(self.store.db.close)

    def note(self, text, *, project="game", reviewed=True,
             source="manual://owner-approved-guide", kind="fact"):
        ident = self.store.add_note(project=project, kind=kind, text=text,
                                    source=source, revision="v1")
        if reviewed:
            self.store.review_note(project=project, note_id=ident,
                                   evidence="independently verified test evidence")
        return ident

    def packet(self, query, public_ids, *, project="game", now=None, **kw):
        return public_knowledge_packet(
            self.store, project=project, query=query,
            public_note_ids=frozenset(public_ids), now=now, **kw,
        )

    def test_reviewed_owner_approved_note_only(self):
        ident = self.note("The checkpoint persists within the current round.")
        p = self.packet("checkpoint", [ident])
        self.assertIsInstance(p, KnowledgePacket)
        self.assertEqual(p.note_ids, (ident,))
        self.assertIn("checkpoint persists", p.context_record)
        self.assertIn("USER-LEVEL", p.context_record)
        self.assertEqual(p.user_message()["role"], "user")
        self.assertNotIn("manual://owner-approved-guide", p.context_record)
        self.assertLessEqual(len(p.context_record), 1400)

    def test_unreviewed_never_exposed_even_if_explicitly_allowed(self):
        ident = self.note("Unchecked lore says the moon is cheese.", reviewed=False)
        self.assertIsNone(self.packet("moon", [ident]))

    def test_reviewed_but_not_public_does_not_leak(self):
        allowed = self.note("The official checkpoint is saved.")
        private = self.note("PRIVATE checkpoint email alex@example.test",
                            source="mail://private-guide")
        p = self.packet("checkpoint", [allowed])
        self.assertIsNotNone(p)
        self.assertEqual(p.note_ids, (allowed,))
        self.assertNotIn("alex@example.test", p.context_record)
        self.assertNotIn("mail://private-guide", p.context_record)
        self.assertEqual(self.packet("checkpoint", []), None)
        self.assertNotEqual(private, allowed)

    def test_project_scope_unchanged(self):
        a = self.note("Checkpoint is saved in the game.", project="game")
        b = self.note("Checkpoint private note for server.", project="server")
        p = self.packet("checkpoint", [a, b], project="game")
        self.assertEqual(p.note_ids, (a,))
        self.assertNotIn("private note for server", p.context_record)

    def test_age_limits_and_future_sources_skipped(self):
        ident = self.note("The checkpoint is at the bridge.")
        current = datetime.now(timezone.utc)
        self.assertIsNone(self.packet(
            "checkpoint", [ident], now=current + timedelta(days=200),
            max_age_days=180,
        ))
        self.assertIsNone(self.packet(
            "checkpoint", [ident], now=current - timedelta(days=2),
        ))
        self.assertIsNotNone(self.packet("checkpoint", [ident], now=current))

    def test_reject_long_raw_notes_and_nonpublic_note_types(self):
        overlong = self.note("checkpoint " + "very " * 80)
        observation = self.note("checkpoint spot is private", kind="observation")
        self.assertIsNone(self.packet("checkpoint", [overlong, observation]))

    def test_bounded_packet_when_more_facts_available(self):
        ids = [self.note(f"checkpoint recipe {i} works " + ("x" * 80))
               for i in range(14)]
        p = self.packet("checkpoint", ids, limit=4)
        self.assertIsNotNone(p)
        self.assertLessEqual(len(p.note_ids), 4)
        self.assertLessEqual(len(p.context_record), 1400)

    def test_invalid_input_types_rejected(self):
        ident = self.note("A checkpoint event was observed.")
        cases = [
            {"query": ""}, {"query": "x" * 301},
            {"public_note_ids": {ident}},  # mutable set not allowed
            {"public_note_ids": frozenset({True})},
            {"limit": 0}, {"limit": True}, {"limit": 100},
            {"max_age_days": 0}, {"max_age_days": True},
            {"now": datetime(2026, 10, 25)},
        ]
        for extra in cases:
            kwargs = {"project": "game", "query": "checkpoint",
                      "public_note_ids": frozenset([ident])}
            kwargs.update(extra)
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                public_knowledge_packet(self.store, **kwargs)

    def test_stream_stage_injects_only_with_moderated_question(self):
        ident = self.note("Animal shooter checkpoint: reach the gold gate.")
        packet = self.packet("checkpoint", [ident])
        s = StarStage(clock=lambda: 100)
        s.enable(owner_approved=True)
        s.offer(StreamSignal("one", "viewer_question", 100,
                             "Where is the checkpoint?", "viewer", "unknown"),
                now=100, moderated=True)
        plan = s.prepare(now=100, knowledge=packet)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.user_message()["role"], "user")
        self.assertIn("gold gate", plan.context_record)
        self.assertIn("END STAR STREAM KNOWLEDGE DATA", plan.context_record)
        self.assertNotIn("gold gate", str(s.metrics()))
        s.finish(plan, now=100)

    def test_stream_stage_does_not_inject_notes_into_gameplay_or_ambient(self):
        ident = self.note("Checkpoint is by the river.")
        packet = self.packet("checkpoint", [ident])
        s = StarStage(clock=lambda: 100)
        s.enable(owner_approved=True)
        s.offer(StreamSignal("one", "game_success", 100,
                             "Victory", "", "observed"), now=100)
        plan = s.prepare(now=100, knowledge=packet)
        self.assertNotIn("Checkpoint is by the river", plan.context_record)
        s.finish(plan, now=100)
        self.assertEqual(s.metrics()["director"]["completed"], 0)

    def test_no_forged_knowledge_packet_type(self):
        s = StarStage(clock=lambda: 100)
        s.enable(owner_approved=True)
        with self.assertRaises(TypeError):
            s.prepare(now=100, knowledge={"content": "private"})


if __name__ == "__main__":
    unittest.main()
