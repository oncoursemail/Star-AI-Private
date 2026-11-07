"""Offline social identity regressions. Temporary SQLite only; no accounts, model or desktop."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sys
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from star.social import rules
from star.social.chat import SocialChat
from star.social.friends import FriendMemory


class LifecycleChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "friends.sqlite3"
        self.memory = FriendMemory(self.path, clock=lambda: 1_000_000.0)
        self.inner = patch("star.social.chat._inner_context", return_value=None)
        self.inner.start()
        self.chat = SocialChat(self.memory, complete=lambda *_: "Sounds good.", emotion=None)

    def tearDown(self):
        self.inner.stop()
        self.memory.close()
        self.tmp.cleanup()

    def race(self, first, second, predicate):
        """Pause inside real SQLite while the first public operation must own its lock."""
        entered, release, second_started = threading.Event(), threading.Event(), threading.Event()
        connection = self.memory._db

        class PausedDB:
            paused = False

            def execute(self, sql, args=()):
                cursor = connection.execute(sql, args)
                if not self.paused and predicate(sql, args):
                    self.paused = True
                    entered.set()
                    if not release.wait(5):
                        raise RuntimeError("synthetic interleave timed out")
                return cursor

            def __getattr__(self, name):
                return getattr(connection, name)

            def __enter__(self):
                return connection.__enter__()

            def __exit__(self, *args):
                return connection.__exit__(*args)

        self.memory._db = PausedDB()

        def next_operation():
            second_started.set()
            return second()

        with ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(first)
            try:
                self.assertTrue(entered.wait(3))
                acquired = self.memory._lock.acquire(blocking=False)
                if acquired:
                    self.memory._lock.release()
                self.assertFalse(acquired, "public operation did not retain the database lock")
                two = pool.submit(next_operation)
                self.assertTrue(second_started.wait(3))
            finally:
                release.set()
            return one.result(timeout=3), two.result(timeout=3)

    def test_two_thread_creation_serializes_counter_and_keeps_distinct_profiles(self):
        first, second = self.race(
            lambda: self.memory.observe_incoming("minecraft", "one"),
            lambda: self.memory.person("minecraft", "two"),
            lambda sql, _: sql.startswith("UPDATE meta SET value = CAST(value AS INTEGER) + 1"))
        self.assertNotEqual(first.id, second.id)
        self.assertEqual((first.they_started, second.they_started), (True, False))
        self.assertEqual(self.memory._db.execute("SELECT count(*) FROM people").fetchone()[0], 2)

    def test_two_thread_link_then_forget_keeps_alias_opt_out_atomic(self):
        person = self.memory.person("discord", "source")
        self.race(lambda: self.memory.link(person, "minecraft", "alias"),
                  lambda: self.memory.forget("discord", "source"),
                  lambda sql, _: sql.startswith("INSERT INTO handles VALUES"))
        self.assertIsNone(self.memory.known("discord", "source"))
        self.assertIsNone(self.memory.known("minecraft", "alias"))
        self.assertTrue(self.memory.is_forgotten("minecraft", "alias"))

    def test_two_thread_forget_then_create_keeps_new_identity_separate(self):
        original = self.memory.person("minecraft", "original")
        _, replacement = self.race(lambda: self.memory.forget("minecraft", "original"),
                                   lambda: self.memory.person("minecraft", "replacement"),
                                   lambda sql, _: sql.startswith("DELETE FROM people WHERE id"))
        self.assertGreater(replacement.id, original.id)
        self.assertTrue(self.memory.is_forgotten("minecraft", "original"))
        self.assertFalse(self.memory.observe_incoming("minecraft", "original").remembered)

    def test_normalization_reuses_identity_without_overwriting_display_name(self):
        person = self.memory.person("minecraft", " Builder ", "Builder")
        again = self.memory.person("minecraft", "BUILDER", "Someone Else")
        self.assertEqual(person.id, again.id)
        self.assertEqual(again.name, "Builder")
        self.assertEqual(self.memory.handles(person), [("minecraft", "builder")])

    def test_oversized_handle_never_collides_with_truncated_prefix(self):
        key = "a" * 100
        person = self.memory.person("discord", key)
        with self.assertRaises(ValueError):
            self.memory.person("discord", key + "different")
        self.assertIsNone(self.memory.known("discord", key + "different"))
        self.assertEqual(self.memory.known("discord", key).id, person.id)

    def test_invalid_handles_do_not_create_profiles(self):
        for handle in (None, 123, "", "   ", "name\x00other", "na\u202eme"):
            with self.subTest(handle=handle), self.assertRaises(ValueError):
                self.memory.person("discord", handle)
            self.assertIsNone(self.memory.known("discord", handle))
        self.assertEqual(self.memory._db.execute("SELECT count(*) FROM people").fetchone()[0], 0)

    def test_alias_link_is_idempotent_and_keeps_age_and_contact_state(self):
        person = self.memory.person("discord", "primary")
        self.memory.update(person, stated_age=16, minor_signals=2, muted=True, blocked=True)
        self.memory.link(person, "minecraft", " Builder ")
        self.memory.link(person, "minecraft", "BUILDER")
        alias = self.memory.person("minecraft", "builder")
        self.assertEqual(alias.id, person.id)
        self.assertEqual((alias.stated_age, alias.minor_signals, alias.muted, alias.blocked), (16, 2, True, True))
        self.assertEqual(len(self.memory.handles(person)), 2)

    def test_link_collision_cannot_swap_minor_and_adult_profiles(self):
        adult = self.memory.person("discord", "adult")
        minor = self.memory.person("minecraft", "younger")
        self.memory.update(adult, stated_age=27)
        self.memory.update(minor, stated_age=15, muted=True)
        with self.assertRaises(ValueError):
            self.memory.link(adult, "minecraft", "YOUNGER")
        current = self.memory.person("minecraft", "younger")
        self.assertEqual((current.id, current.stated_age, current.muted), (minor.id, 15, True))
        self.assertEqual(self.memory.get(adult.id).stated_age, 27)

    def test_forgotten_alias_cannot_be_reintroduced_by_link_or_inbound(self):
        forgotten = self.memory.person("minecraft", "private")
        self.memory.note_fact(forgotten, "I like chess")
        self.memory.forget("minecraft", " PRIVATE ")
        other = self.memory.person("discord", "other")
        with self.assertRaises(ValueError):
            self.memory.link(other, "minecraft", "private")
        self.assertFalse(self.memory.observe_incoming("minecraft", "PRIVATE").remembered)
        self.assertTrue(self.memory.is_forgotten("minecraft", "private"))
        self.memory.allow_again("minecraft", " PRIVATE ")
        returned = self.memory.observe_incoming("minecraft", "private")
        self.assertEqual(self.memory.facts(returned), [])
        self.assertIsNone(returned.stated_age)

    def test_stale_deleted_profile_cannot_acquire_an_alias(self):
        person = self.memory.person("discord", "gone")
        self.memory.forget("discord", "gone")
        with self.assertRaises(KeyError):
            self.memory.link(person, "minecraft", "new_alias")
        self.assertIsNone(self.memory.known("minecraft", "new_alias"))

    def test_deleted_id_is_not_recycled_for_a_new_person_or_after_reopening(self):
        original = self.memory.person("discord", "original")
        self.memory.forget("discord", "original")
        self.memory.close()
        self.memory = FriendMemory(self.path)
        replacement = self.memory.person("discord", "replacement")
        self.assertGreater(replacement.id, original.id)
        with self.assertRaises(KeyError):
            self.memory.link(original, "minecraft", "wrong_alias")
        self.assertIsNone(self.memory.known("minecraft", "wrong_alias"))

    def test_legacy_database_bootstraps_counter_without_reidentifying_existing_person(self):
        self.memory._db.execute("DELETE FROM meta WHERE key = 'person_id_high_water'")
        self.memory._db.execute("INSERT INTO people (id,name,created,updated,stated_age) VALUES (50,'Existing',1,1,17)")
        self.memory._db.execute("INSERT INTO handles VALUES ('minecraft','existing',50)")
        self.memory._db.commit()
        self.memory.close()
        self.memory = FriendMemory(self.path)
        existing = self.memory.known("minecraft", "existing")
        self.assertEqual((existing.id, existing.stated_age), (50, 17))
        self.assertGreater(self.memory.person("minecraft", "new").id, 50)

    def test_public_then_private_inbound_updates_reciprocity_on_real_chat_path(self):
        public = self.chat.handle("minecraft", "builder", "Hello Star", public=True)
        self.memory.update(public.person, relationship="friend")
        self.assertFalse(rules.may_initiate(self.memory.get(public.person.id), "minecraft"))
        # A lookup claiming they_started must not rewrite an existing profile.
        self.assertFalse(self.memory.person("minecraft", "builder", they_started=True).they_started)
        private = self.chat.handle("minecraft", "builder", "Want to build together?", public=False)
        self.assertEqual(private.person.id, public.person.id)
        self.assertTrue(private.person.they_started)
        self.assertTrue(rules.may_initiate(private.person, "minecraft"))
        self.assertEqual(private.mode.age_status, "unknown")

    def test_public_messages_never_manufacture_private_reciprocity(self):
        first = self.chat.handle("minecraft", "public_player", "Hello Star", public=True)
        again = self.chat.handle("minecraft", "public_player", "Good game", public=True)
        self.assertEqual(first.person.id, again.person.id)
        self.assertFalse(again.person.they_started)

    def test_inbound_observation_preserves_existing_opt_out_and_minor_evidence(self):
        person = self.memory.person("discord", "quiet")
        self.memory.update(person, muted=True, blocked=True, stated_age=14, minor_signals=1)
        seen = self.memory.observe_incoming("discord", "quiet")
        self.assertTrue(seen.they_started)
        self.assertTrue(seen.muted and seen.blocked)
        self.assertEqual((seen.stated_age, seen.minor_signals), (14, 1))
        self.assertFalse(rules.may_initiate(seen, "discord"))

    def test_reciprocity_and_links_survive_reopening_without_changing_age(self):
        person = self.memory.observe_incoming("discord", "known")
        self.memory.update(person, stated_age=17)
        self.memory.link(person, "minecraft", "known_builder")
        self.memory.close()
        self.memory = FriendMemory(self.path)
        reopened = self.memory.known("minecraft", "KNOWN_BUILDER")
        self.assertEqual((reopened.id, reopened.stated_age, reopened.they_started), (person.id, 17, True))

    def test_direct_moments_skip_obvious_credentials_and_payment_details(self):
        person = self.memory.person("minecraft", "builder")
        sensitive = ("they: my password is fixture-only", "me: token: fixture-only",
                     "they: my CVV is 123", "they: my credit card is 4111111111111111",
                     "they: sk-" + "FakeFixtureOnly" * 3,
                     "they: Bearer " + "FakeFixtureOnly" * 3)
        for line in sensitive:
            with self.subTest(marker=line[:20]):
                self.memory.note_moment(person, "minecraft", line)
        self.assertEqual(self.memory.moments(person), [])
        self.memory.note_moment(person, "minecraft", "they: I like building castles")
        self.assertEqual(self.memory.moments(person), [("minecraft", "they: I like building castles")])

    def test_chat_does_not_store_incoming_or_echoed_secret_in_facts_or_moments(self):
        secret = "sk-" + "FakeFixtureOnly" * 3
        self.chat = SocialChat(self.memory, complete=lambda *_: "You said " + secret, emotion=None)
        reply = self.chat.handle("minecraft", "builder", "I like " + secret, public=False)
        self.assertIsNotNone(reply)
        person = self.memory.known("minecraft", "builder")
        self.assertEqual(self.memory.facts(person), [])
        self.assertEqual(self.memory.moments(person), [])
        self.assertNotIn(secret, "\n".join(self.memory._db.iterdump()))

    def test_sensitive_markers_are_checked_before_memory_truncation(self):
        person = self.memory.person("minecraft", "builder")
        line = "I like " + "building " * 40 + "my password is fixture-only"
        self.assertFalse(self.memory.note_fact(person, line))
        self.memory.note_moment(person, "minecraft", "they: " + line)
        self.assertEqual(self.memory.facts(person), [])
        self.assertEqual(self.memory.moments(person), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
