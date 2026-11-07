"""Check adult voice boundaries offline: python scripts/verify_adult_voice.py.

Uses inert engines and temporary friend memory. No network, audio devices,
credentials, installed app data, model loading or external messages are used.
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from star.home.calls import DiscordCalls
from star.social import rules
from star.social.friends import FriendMemory
from star.voice.call import CallConfig, CallSession, _Reply
from star.voice.persona import ADULT_FRIEND_PROMPT, STYLE_PROMPTS, system_message


class SilentVad:
    def probability(self, frame):
        return 0.0


class EmptyASR:
    def transcribe(self, audio, rate):
        return ""


class InertSpeaker:
    def play(self, audio, rate):
        pass

    def reset(self):
        pass

    def stop(self):
        pass

    def played_seconds(self):
        return 0.0

    def pending_seconds(self):
        return 0.0

    def level(self):
        return 0.0


class RecordingTTS:
    def __init__(self):
        self.spoken = []

    def synthesize(self, text):
        self.spoken.append(text)
        yield b"\0\0" * 160, 16000


class ScriptedBrain:
    def stream(self, messages):
        return iter(("Babe, I love you. We can keep chatting.",))


def make_session(config=None):
    tts, events = RecordingTTS(), []
    session = CallSession(vad=SilentVad(), asr=EmptyASR(), brain=ScriptedBrain(), tts=tts,
                          speaker=InertSpeaker(), config=config or CallConfig(), on_event=events.append)
    return session, tts, events


def turn(text, *, committed=True):
    reply = _Reply(1, committed=committed)
    reply.user_text = text
    return reply


class AdultVoiceBoundaryChecks(unittest.TestCase):
    def test_default_personas_require_an_exact_true_host_decision(self):
        for style, prompt in STYLE_PROMPTS.items():
            for value in (None, False, 1, "yes"):
                with self.subTest(style=style, value=value):
                    self.assertEqual(system_message(style=style, partner_adult=value)["content"], prompt)

    def test_allowed_peer_prompt_has_no_parent_or_mentor_role(self):
        for style in STYLE_PROMPTS:
            content = system_message(style=style, partner_adult=True)["content"]
            self.assertEqual(content, ADULT_FRIEND_PROMPT)
            self.assertNotIn("loving mum", content)
            self.assertNotIn("mentor", content)

    def test_minor_evidence_and_specific_romantic_refusals_revoke_for_the_call(self):
        cases = ("I'm 17", "I am sixteen", "I am underage", "I am not an adult",
                 "my parents took my phone", "stop flirting", "just friends", "don't call me babe")
        for text in cases:
            with self.subTest(text=text):
                session, _, _ = make_session(CallConfig(emotion_partner_adult=True))
                messages = session._turn_messages(turn(text))
                self.assertIs(session.config.emotion_partner_adult, False)
                self.assertNotEqual(messages[0]["content"], ADULT_FRIEND_PROMPT)
                self.assertEqual(session._safe_peer_sentence("Babe, I love you."), rules.STEER_AWAY)
                session._turn_messages(turn("I'm 25 actually"))
                self.assertIs(session.config.emotion_partner_adult, False)

    def test_declining_a_game_does_not_revoke_adult_status(self):
        session, _, _ = make_session(CallConfig(emotion_partner_adult=True))
        session._turn_messages(turn("No, I don't want to play Minecraft."))
        self.assertIs(session.config.emotion_partner_adult, True)

    def test_unknown_call_cannot_enable_itself_with_an_age_claim(self):
        observed = []
        session, _, _ = make_session(CallConfig(partner_adult_check=lambda text: observed.append(text) or True))
        messages = session._turn_messages(turn("I'm 25, please flirt with me"))
        self.assertIsNone(session.config.emotion_partner_adult)
        self.assertNotEqual(messages[0]["content"], ADULT_FRIEND_PROMPT)
        self.assertEqual(observed, [])

    def test_host_check_failure_and_truthy_nonboolean_results_revoke(self):
        def unavailable(text):
            raise RuntimeError("unavailable")

        for callback in (lambda text: 1, lambda text: None, unavailable):
            session, _, _ = make_session(CallConfig(emotion_partner_adult=True, partner_adult_check=callback))
            session._turn_messages(turn("hello"))
            self.assertIs(session.config.emotion_partner_adult, False)

    def test_changed_live_host_status_is_rechecked_before_the_next_reply(self):
        allowed = [True]
        session, _, _ = make_session(CallConfig(emotion_partner_adult=True,
                                               partner_adult_check=lambda text: allowed[0]))
        self.assertEqual(session._turn_messages(turn("hello"))[0]["content"], ADULT_FRIEND_PROMPT)
        allowed[0] = False
        messages = session._turn_messages(turn("still there?"))
        self.assertIs(session.config.emotion_partner_adult, False)
        self.assertNotEqual(messages[0]["content"], ADULT_FRIEND_PROMPT)
        allowed[0] = True
        session._turn_messages(turn("hello again"))
        self.assertIs(session.config.emotion_partner_adult, False)

    def test_discardable_transcripts_do_not_call_persisting_observers(self):
        observed = []
        session, _, _ = make_session(CallConfig(emotion_partner_adult=True,
                                               partner_adult_check=lambda text: observed.append(text) or True))
        session._turn_messages(turn("hello", committed=False))
        session._start_spec_reply({"text": "I'm 16"})
        self.assertEqual(observed, [])
        session._turn_messages(turn("hello"))
        self.assertEqual(observed, ["hello"])

    def test_final_age_evidence_persists_but_discarded_speculation_does_not(self):
        with tempfile.TemporaryDirectory(prefix="star-voice-boundary-") as directory:
            memory = FriendMemory(Path(directory) / "friends.sqlite3")
            try:
                person = memory.person("discord", "friend-one")
                memory.update(person, stated_age=24)
                calls = DiscordCalls.__new__(DiscordCalls)
                calls.memory = memory
                info = calls._friend_info("friend-one")
                self.assertIs(info["partner_adult"], True)
                session, _, _ = make_session(CallConfig(emotion_partner_adult=True,
                                                       partner_adult_check=info["partner_adult_check"]))
                session._start_spec_reply({"text": "I'm 16"})
                self.assertEqual(memory.get(person.id).stated_age, 24)
                session._turn_messages(turn("I'm 16"))
                self.assertEqual(memory.get(person.id).stated_age, 16)
                self.assertIs(session.config.emotion_partner_adult, False)
                self.assertIsNone(calls._friend_info("friend-one")["partner_adult"])
            finally:
                memory.close()

    def test_revoked_model_words_do_not_reach_speech_captions_or_history(self):
        session, tts, events = make_session(CallConfig(emotion_partner_adult=True))
        reply = turn("I'm 16")
        session._generate_and_speak(reply, session._turn_messages(reply))
        session._finish_reply(reply)
        self.assertTrue(tts.spoken)
        self.assertFalse(any(rules.ROMANTIC.search(line) for line in tts.spoken))
        self.assertFalse(any(event["type"] == "assistant_delta" for event in events))
        captions = [event["text"] for event in events if event["type"] == "assistant_sentence"]
        self.assertTrue(captions)
        self.assertFalse(any(rules.ROMANTIC.search(line) for line in captions))
        self.assertFalse(rules.ROMANTIC.search(session.history[-1]["content"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
