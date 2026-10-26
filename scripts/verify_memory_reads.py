"""Source-memory reads and reconciliation on temporary databases; no accounts or model calls."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from star.inner import opinions, recall, reflect
from star.inner.store import InnerStore, person_key, resolve
from star.social.friends import FriendMemory


class Checks(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="star-memory-reads-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.memory = FriendMemory(self.root / "friends.db", clock=lambda: 1800000000.0)
        self.addCleanup(self.memory.close)
        self.store = InnerStore(self.root / "inner.db", clock=lambda: 1800000000.0)
        self.addCleanup(self.store.close)
        self.person = self.memory.person("discord", "reader", "Reader")

    def test_reads_preserve_source_order_and_do_not_manufacture_reciprocity(self):
        self.memory.note_fact(self.person, "I like jazz")
        self.memory.note_fact(self.person, "I draw landscapes")
        self.memory.note_moment(self.person, "discord", "they: I enjoy painting mountain landscapes")
        facts = self.memory.fact_records(self.person)
        self.assertEqual([r[1] for r in facts], ["I like jazz", "I draw landscapes"])
        self.assertEqual(self.memory.fact_records(self.person, after_id=facts[0][0]), facts[1:])
        self.assertEqual(self.memory.moment_records(self.person)[0][1:],
                         ("discord", "they: I enjoy painting mountain landscapes", 1800000000.0))
        self.assertFalse(self.memory.people()[0].they_started)
        facts.clear()
        self.assertEqual(len(self.memory.fact_records(self.person)), 2)

    def test_interest_filter_works_on_preexisting_adult_facts(self):
        self.memory.note_fact(self.person, "I work as an astronomer")
        self.memory.note_fact(self.person, "I like jazz")
        self.assertEqual(self.memory.facts(self.person, interests_only=True), ["I like jazz"])
        self.assertEqual(self.memory.facts(self.person, 0, interests_only=True), [])

    def test_forgotten_source_cannot_restore_identity(self):
        key = person_key(self.memory, self.person)
        self.memory.forget("discord", "reader")
        self.assertIsNone(self.memory.person_created(self.person))
        self.assertEqual(self.memory.people(), [])
        self.assertEqual(self.memory.fact_records(self.person), [])
        self.assertEqual(self.memory.moment_records(self.person), [])
        self.assertIsNone(resolve(self.memory, key))
        self.assertEqual(person_key(self.memory, self.person), "")

    def test_invalid_read_cursors_leave_sources_unchanged(self):
        self.memory.note_fact(self.person, "I like jazz")
        for cursor in (True, -1, 1.5, "1"):
            for method in (self.memory.fact_records, self.memory.moment_records):
                with self.subTest(cursor=cursor, method=method.__name__), self.assertRaises(ValueError):
                    method(self.person, after_id=cursor)
        self.assertEqual(self.memory.facts(self.person), ["I like jazz"])

    def test_source_reads_wait_for_existing_write_guard(self):
        entered, done = threading.Event(), threading.Event()
        errors = []
        def read():
            entered.set()
            try:
                self.memory.people()
                self.memory.person_created(self.person)
                self.memory.fact_records(self.person)
                self.memory.moment_records(self.person)
            except Exception as error:
                errors.append(type(error).__name__)
            finally:
                done.set()
        with self.memory._lock:
            worker = threading.Thread(target=read, daemon=True)
            worker.start()
            self.assertTrue(entered.wait(1))
            self.assertFalse(done.wait(0.05))
        self.assertTrue(done.wait(2))
        worker.join(1)
        self.assertEqual(errors, [])

    def test_deleted_and_reused_fact_ids_do_not_keep_old_episode(self):
        self.memory.note_fact(self.person, "I work as an astronomer")
        recall.sync_person(self.store, self.memory, self.person)
        self.memory.drop_last_fact(self.person)
        self.memory.note_fact(self.person, "I like jazz")
        recall.sync_person(self.store, self.memory, self.person)
        episodes = self.store.episodes(pkey=person_key(self.memory, self.person))
        self.assertEqual([e.text for e in episodes], ["I like jazz"])
        self.assertEqual(recall.sync_person(self.store, self.memory, self.person), 0)

    def test_unknown_verification_cannot_create_earned_preferences(self):
        for value in (None, "false", "true", 0, 1, {}, []):
            count = opinions.earn_from_history(self.store,
                [{"interest": "drawing", "verified": value, "summary": "masterpiece", "ts": "old"}])
            self.assertEqual(count, 0)
        self.assertIsNone(opinions.get(self.store, "drawing"))

    def test_boolean_preference_signals_remain_attributed_reports(self):
        for verified, name in ((True, "drawing"), (False, "music")):
            opinions.earn_from_history(self.store,
                [{"interest": name, "verified": verified, "summary": "an activity", "ts": name}])
            self.assertTrue(opinions.get(self.store, name)["reason"].startswith("Activity report ("))
        self.assertIn("unverified", opinions.get(self.store, "music")["reason"])

    def test_diary_notes_and_fallback_do_not_promote_truthy_verification(self):
        result = reflect.write_diary(self.store, lambda *_: json.dumps({}), 1800000000.0,
            history=[{"interest": "drawing", "verified": "false", "summary": "a perfect drawing"}],
            emotion_events=[], people_count=0, new_facts=0)
        self.assertIn("outcome unverified", result["notes"])
        self.assertNotIn("activity reported success", result["notes"])
        self.assertIn("0 reported success", result["diary"])
        self.assertNotIn("I did", result["diary"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
