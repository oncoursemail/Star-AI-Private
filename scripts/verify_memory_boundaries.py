"""Independent memory boundary checks using temporary SQLite and fake completion only."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from star.inner import opinions, recall, reflect  # noqa: E402
from star.inner.context import card_for, turn_context  # noqa: E402
from star.inner.store import FLAGS, InnerStore, person_key  # noqa: E402
from star.social.friends import MAX_MOMENTS, FriendMemory  # noqa: E402


class MemoryBoundaryChecks(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = 1_800_000_000.0
        self.memory = FriendMemory(self.root / "friends.sqlite3", clock=lambda: self.now)
        self.addCleanup(self.memory.close)
        self.store = InnerStore(self.root / "inner.sqlite3", clock=lambda: self.now)
        self.addCleanup(self.store.close)
        self.person = self.memory.person("discord", "fixture", "Fixture")
        self.memory.update(self.person, stated_age=25)

    def context(self, text):
        return turn_context(self.memory, self.person, text, store=self.store, now=self.now, force=True)

    def test_unsupported_negative_role_and_biography_rejected(self):
        self.memory.note_fact(self.person, "I like painting")
        canonical = reflect.rule_card(self.memory, self.person)
        self.assertEqual(reflect.valid_card(canonical, canonical, self.memory, self.person), canonical)
        for claim in ("Fixture has a sister named Violet.", "Fixture does not have any siblings.",
                      "Fixture is a doctor.", "Fixture pretends to be a wizard, so is a wizard."):
            with self.subTest(claim=claim):
                self.assertEqual(reflect.valid_card(claim, canonical + claim, self.memory, self.person), "")

    def test_old_card_never_becomes_model_evidence_or_prompt_fact(self):
        key = person_key(self.memory, self.person)
        old = "Fixture has a sister named Violet and is a doctor."
        self.store.set_card(key, old)
        notes = []

        def complete(_system, user):
            notes.append(user)
            return json.dumps({"card": old})

        reflect.reflect_person(self.store, self.memory, complete, self.person, self.now)
        self.assertNotIn("Violet", " ".join(notes))
        self.assertNotIn("doctor", card_for(self.store, self.memory, self.person))
        self.assertEqual(self.store.card(key)[0], old)  # retained for audit, not used as evidence

    def test_source_fact_removal_prevents_recall(self):
        self.memory.note_fact(self.person, "My profession is astronomer")
        recall.sync_person(self.store, self.memory, self.person)
        self.memory.drop_last_fact(self.person)
        context = self.context("do you remember my astronomer profession?")
        self.assertNotIn("astronomer", context.note)
        self.assertNotIn("astronomer", context.card)

    def test_reused_source_id_replaces_old_fact(self):
        self.memory.note_fact(self.person, "My profession is astronomer")
        old_id = self.memory.fact_records(self.person)[0][0]
        recall.sync_person(self.store, self.memory, self.person)
        self.memory.drop_last_fact(self.person)
        self.memory.note_fact(self.person, "My profession is violinist")
        self.assertEqual(self.memory.fact_records(self.person)[0][0], old_id)
        recall.sync_person(self.store, self.memory, self.person)
        texts = " ".join(ep.text for ep in self.store.episodes(pkey=person_key(self.memory, self.person)))
        self.assertNotIn("astronomer", texts)
        self.assertIn("violinist", texts)

    def test_source_moment_retention_removes_expired_copy(self):
        self.memory.note_moment(self.person, "discord", "they: The obsolete zeppelin story was unusual")
        recall.sync_person(self.store, self.memory, self.person)
        for index in range(MAX_MOMENTS + 5):
            self.memory.note_moment(self.person, "discord", f"they: Today's ordinary activity is painting item {index}")
        recall.sync_person(self.store, self.memory, self.person)
        texts = " ".join(ep.text for ep in self.store.episodes(pkey=person_key(self.memory, self.person)))
        self.assertNotIn("zeppelin", texts)

    def test_minor_transition_uses_only_current_interests(self):
        self.memory.note_fact(self.person, "My profession is astronomer")
        self.memory.note_fact(self.person, "I like painting")
        self.memory.note_moment(self.person, "discord", "they: My private inheritance story involved a zeppelin")
        recall.sync_person(self.store, self.memory, self.person)
        self.store.set_card(person_key(self.memory, self.person), "Fixture is my sweetheart.")
        self.memory.update(self.person, stated_age=15)
        context = self.context("remember my inheritance and astronomer profession?")
        self.assertEqual(context.note, "")
        self.assertIn("painting", context.card)
        self.assertNotIn("astronomer", context.card)
        self.assertNotIn("sweetheart", context.card)

    def test_forget_during_completion_prevents_new_writes(self):
        key = person_key(self.memory, self.person)

        def complete(*_):
            self.memory.forget("discord", "fixture")
            return "{}"

        result = reflect.reflect_person(self.store, self.memory, complete, self.person, self.now)
        self.assertEqual(result, {"card": False, "seed": False})
        self.assertEqual(self.store.card(key)[0], "")

    def test_age_change_during_completion_discards_old_facts(self):
        self.memory.note_fact(self.person, "My profession is astronomer")
        canonical = reflect.rule_card(self.memory, self.person)

        def complete(*_):
            self.memory.update(self.person, stated_age=15)
            return json.dumps({"card": canonical})

        reflect.reflect_person(self.store, self.memory, complete, self.person, self.now)
        self.assertNotIn("astronomer", self.store.card(person_key(self.memory, self.person))[0])

    def test_forgotten_identity_never_falls_through_to_owner(self):
        self.store.add_episode("", "Owner's zeppelin expedition", kind="home_verified", ts=self.now)
        self.memory.forget("discord", "fixture")
        for person in (self.person, self.memory.person("discord", "fixture")):
            context = turn_context(self.memory, person, "remember the zeppelin expedition?", store=self.store,
                                   now=self.now, force=True)
            self.assertEqual((context.card, context.note, context.lines), ("", "", []))

    def test_home_sources_survive_consolidation_and_replay(self):
        history = [{"ts": f"2027-01-15T08:00:0{index}+00:00", "interest": "painting", "summary": "Made a mural",
                    "verified": verified} for index, verified in enumerate((True, False, "false", 1))]
        for _ in range(2):
            reflect.run(self.store, self.memory, lambda *_: "{}", now=self.now, history=history)
        episodes = self.store.episodes(pkey="")
        self.assertEqual(len(episodes), 4)
        self.assertEqual(sum(ep.kind == "home_verified" for ep in episodes), 1)
        self.assertEqual(sum(ep.kind == "home_unverified" for ep in episodes), 3)
        labels = [recall.line_for(ep, self.now) for ep in episodes]
        self.assertEqual(sum("activity reported success" in line for line in labels), 1)

    def test_legacy_home_is_explicitly_unverified(self):
        eid = self.store.add_episode("", "Finished a mural", kind="home", ts=self.now)
        assert eid is not None
        episode = self.store.episode(eid)
        assert episode is not None
        self.assertIn("legacy unverified report", recall.line_for(episode, self.now))

    def test_invalid_history_never_reaches_any_nightly_consumer(self):
        notes = []

        def complete(_system, user):
            notes.append(user)
            return "{}"

        history = [{"ts": stamp, "interest": "invalidzeppelin", "summary": "Invalid source biography",
                    "verified": True} for stamp in (None, 123, "not-a-date", "2027-01-15T08:00:00")]
        reflect.run(self.store, self.memory, complete, now=self.now, history=history)
        self.assertEqual(self.store.episodes(pkey=""), [])
        self.assertIsNone(opinions.get(self.store, "invalidzeppelin"))
        self.assertNotIn("zeppelin", " ".join(notes))

    def test_unknown_verification_is_not_opinion_evidence(self):
        for value in (None, "false", "true", 1, 0):
            row = {"ts": "2027-01-15T08:00:00+00:00", "interest": "unsupported", "summary": "Uncertain result",
                   "verified": value}
            opinions.earn_from_history(self.store, [row], now=self.now)
        self.assertIsNone(opinions.get(self.store, "unsupported"))

    def test_false_preference_signal_retains_explicit_uncertainty(self):
        # The existing False -> weak negative preference heuristic is preserved,
        # not evidence that an activity failed or was a bad lived experience.
        row = {"ts": "2027-01-15T08:00:00+00:00", "interest": "painting", "summary": "Uncertain result",
               "verified": False}
        opinions.earn_from_history(self.store, [row], now=self.now)
        opinion = opinions.get(self.store, "painting")
        assert opinion is not None
        self.assertLess(opinion["valence"], 0)
        self.assertIn("unverified", opinion["reason"])
        self.assertNotIn("failed", opinion["reason"])

    def test_disabled_context_creates_no_home_state(self):
        self.assertIs(FLAGS["inner_chat_enabled"], False)
        home = self.root / "never-created"
        context = turn_context(self.memory, self.person, "remember painting?", home=home)
        self.assertEqual((context.card, context.note), ("", ""))
        self.assertFalse(home.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
