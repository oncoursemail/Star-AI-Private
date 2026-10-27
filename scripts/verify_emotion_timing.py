"""Social appraisal timing with temporary friend memory and fake emotion/model edges."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from star.social.chat import SocialChat
from star.social.friends import FriendMemory


class Emotion:
    def __init__(self, enabled=True):
        self.on = enabled
        self.messages, self.events, self.reads = [], [], []
        self.tone = "old tone"
    def enabled(self): return self.on
    def on_message(self, text, *, person=None):
        self.messages.append((text, person))
        self.tone = "glad about the praise" if text == "great work" else "concerned about this"
        return "owner_praise" if text == "great work" else None
    def on_event(self, kind, **kwargs): self.events.append((kind, kwargs))
    def directive(self, **kwargs):
        self.reads.append((self.tone, kwargs))
        return self.tone


class Checks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="star-emotion-timing-")
        self.addCleanup(self.temp.cleanup)
        self.memory = FriendMemory(Path(self.temp.name) / "friends.sqlite3", clock=lambda: 100.0)
        self.addCleanup(self.memory.close)
        # Never read the owner's inner-memory settings/store in this verifier.
        self.inner = patch("star.social.chat._inner_context", return_value=None)
        self.inner.start()
        self.addCleanup(self.inner.stop)
        self.emotion, self.requests = Emotion(), []
        def complete(system, user):
            self.requests.append((system, user))
            return "Thanks, that's kind."
        self.chat = SocialChat(self.memory, emotion=self.emotion, complete=complete, clock=lambda: 100.0)

    def test_current_message_affects_current_prompt_exactly_once(self):
        reply = self.chat.handle("discord", "fixture", "great work")
        self.assertIsNotNone(reply)
        self.assertIn("(mood: glad about the praise)", self.requests[0][1])
        self.assertNotIn("old tone", self.requests[0][1])
        self.assertEqual(len(self.emotion.messages), 1)
        self.assertEqual(len(self.emotion.reads), 1)
        self.assertEqual(self.emotion.events, [])
        self.assertEqual(self.emotion.messages[0][1], f"friend-{reply.person.id}")

    def test_next_message_uses_its_own_appraisal_without_double_counting(self):
        self.chat.handle("discord", "fixture", "great work")
        self.chat.handle("discord", "fixture", "that was upsetting")
        self.assertIn("(mood: concerned about this)", self.requests[1][1])
        self.assertEqual([text for text, _ in self.emotion.messages], ["great work", "that was upsetting"])
        self.assertEqual(len(self.emotion.reads), 2)

    def test_friend_goodbye_adds_only_one_departure_event(self):
        person = self.memory.person("discord", "fixture")
        self.memory.update(person, relationship="friend")
        self.chat.handle("discord", "fixture", "bye")
        self.assertEqual(len(self.emotion.messages), 1)
        self.assertEqual([kind for kind, _ in self.emotion.events], ["friend_left"])

    def test_off_engine_gets_no_appraisal_or_directive_access(self):
        self.emotion.on = False
        self.chat.handle("discord", "fixture", "great work")
        self.assertNotIn("(mood:", self.requests[0][1])
        self.assertEqual(self.emotion.messages + self.emotion.events + self.emotion.reads, [])

    def test_absent_engine_stays_optional(self):
        self.chat._emotion = None
        self.assertIsNotNone(self.chat.handle("discord", "fixture", "great work"))
        self.assertNotIn("(mood:", self.requests[0][1])

    def test_blocked_sender_has_no_model_or_emotion_event(self):
        person = self.memory.person("discord", "fixture")
        self.memory.update(person, blocked=True)
        self.assertIsNone(self.chat.handle("discord", "fixture", "great work"))
        self.assertEqual(self.requests + self.emotion.messages + self.emotion.events, [])

    def test_forget_path_keeps_its_fixed_reply_and_no_appraisal(self):
        self.memory.person("discord", "fixture")
        reply = self.chat.handle("discord", "fixture", "forget me")
        self.assertIn("forgotten", reply.text)
        self.assertFalse(reply.stored)
        self.assertEqual(self.requests + self.emotion.messages + self.emotion.events, [])

    def test_forget_last_fact_path_does_not_add_appraisal(self):
        person = self.memory.person("discord", "fixture")
        self.memory.note_fact(person, "I like jazz")
        reply = self.chat.handle("discord", "fixture", "forget that")
        self.assertEqual(reply.text, "Forgotten.")
        self.assertEqual(self.memory.facts(person), [])
        self.assertEqual(self.requests + self.emotion.messages + self.emotion.events, [])

    def test_leave_path_keeps_only_existing_rejection_event(self):
        reply = self.chat.handle("discord", "fixture", "leave me alone")
        self.assertIn("leave you be", reply.text)
        self.assertEqual(self.requests + self.emotion.messages, [])
        self.assertEqual([kind for kind, _ in self.emotion.events], ["owner_criticism"])

    def test_explicit_remember_again_path_has_no_new_appraisal(self):
        self.memory.person("discord", "fixture")
        self.memory.forget("discord", "fixture")
        reply = self.chat.handle("discord", "fixture", "you can remember me again")
        self.assertIn("remember you", reply.text)
        self.assertEqual(self.requests + self.emotion.messages + self.emotion.events, [])

    def test_appraisal_failure_does_not_break_current_reply(self):
        def fail(*args, **kwargs): raise OSError("fixture")
        self.emotion.on_message = fail
        self.assertIsNotNone(self.chat.handle("discord", "fixture", "great work"))
        self.assertEqual(len(self.requests), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
