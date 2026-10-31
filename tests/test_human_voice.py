"""Issue 613 (STAR Digital Life): the quick model must not read its own plan or instructions aloud.

Measured 2026-10-25 on the live brain (docs/agents/human-voice-20261025.md): star-voice runs with the thinking block
already empty (template and `reasoning = off` are correct), and still wrote its plan into the reply on ~3 % of voice
turns ("Okay, the user just asked ... I need to start with a short warm reaction ..."). The voice path had no guard at
all, so the plan was spoken. The replies below are the real ones.
"""
import pytest

from star.persona import check_reply, leaked_reasoning, strip_reasoning
from star.voice.call import FALLBACK_LINE, RETRY_NOTE, CallConfig, CallSession
from star.voice.turn import TurnConfig
from voice_fakes import Events, FakeASR, FakeBrain, FakeSpeaker, FakeTTS, FakeVAD, quiet, speech

REAL_LEAKS = [
    'Okay, the user just asked, "is night school still running?" Let me recall the guidelines.',
    "As Star, I need to start with a short warm reaction of two to five words ending with a full stop.",
    "Oh, right. I need to keep it short and warm. Let me recall the key points: I'm Star, your caring assistant.",
    "The user asks about the weather where I am. I need to start with a short warm reaction of two to five words.",
    "That's the only learning from the context provided: the current date and time.",
    "We previously set my persona: Star (she/her), warm, confident, playful.",
    "Okay, Star needs to know if night school is still running. She's his assistant, warm and steady like a mum.",
    "No further web results or data are required. I'll keep the response concise.",
]
REAL_CLEAN = [
    "Hey! Evening's going well, just wrapped up some night school tries. What about you?",
    "Spaces, obviously. Keeps things clean and consistent.",
    "Ugh, coding all day long? Been there. Want a quick stretch?",
    "Oh, that sounds draining. Would you like a short break before we look at more code?",
    "I am an AI.",
    "Honestly, I can't see the weather from here, love. Tell me your city and I'll look it up.",
    "You should take the weekend off after that push, and I mean it.",
    "Good night, you. Sleep well.",
    "The user's inventory is saved in a DataStore, so check the key name first.",
    "I need a coffee before that deploy, honestly.",
    "Let me know if you want me to show an example on screen.",
]


@pytest.mark.parametrize("text", REAL_LEAKS)
def test_the_plans_the_model_actually_wrote_are_recognised(text):
    assert leaked_reasoning(text)
    assert "reasoning leaked into the reply" in check_reply(text)


@pytest.mark.parametrize("text", REAL_CLEAN)
def test_ordinary_replies_are_not_mistaken_for_plans(text):
    assert not leaked_reasoning(text)
    assert strip_reasoning(text) == text


TEXTS = {1: "is night school still running"}
END = quiet(40)
PLAN = "Okay, the user just asked about night school. I need to start with a short warm reaction of two to five words."


def call(replies):
    events, speaker, tts = Events(), FakeSpeaker(), FakeTTS()
    brain = FakeBrain(replies)
    session = CallSession(vad=FakeVAD(), asr=FakeASR(TEXTS, 0.0), brain=brain, tts=tts, speaker=speaker,
                          config=CallConfig(turn=TurnConfig(), partial_transcripts=False), on_event=events)
    session.start()
    for frame in speech(1, 20) + END:
        session.feed(frame)
    assert session.wait_idle(5)
    return session, events, brain, tts


def test_a_plan_is_never_spoken_and_the_turn_is_asked_again_once():
    session, events, brain, tts = call([PLAN, "Yep, it's running. Forty one tries so far tonight."])
    assert tts.spoken == ["Yep, it's running.", "Forty one tries so far tonight."]
    assert len(brain.requests) == 2 and brain.requests[1][-1]["content"].endswith(RETRY_NOTE)
    assert brain.requests[0][-1]["content"] == TEXTS[1]
    assert [e["retry"] for e in events.of("reasoning_dropped")] == [True]
    assert session.history[-1] == {"role": "assistant", "content": "Yep, it's running. Forty one tries so far tonight."}


def test_two_plans_in_a_row_end_in_one_honest_line_and_the_plan_stays_out_of_the_history():
    session, events, brain, tts = call([PLAN, PLAN])
    assert tts.spoken == [FALLBACK_LINE]
    assert len(brain.requests) == 2
    assert FALLBACK_LINE in session.history[-1]["content"] and "user just asked" not in str(session.history)


def test_a_plan_that_starts_after_a_real_first_sentence_cuts_the_reply_there():
    session, events, brain, tts = call(["Yep, it's running. The user asks about tries. I need to say how many."])
    assert tts.spoken == ["Yep, it's running."]
    assert len(brain.requests) == 1 and brain.streams[0].closed.is_set()
    assert session.history[-1]["content"] == "Yep, it's running."


def test_a_normal_reply_is_untouched():
    session, events, brain, tts = call(["Yep, it's running. Forty one tries so far tonight."])
    assert tts.spoken == ["Yep, it's running.", "Forty one tries so far tonight."]
    assert len(brain.requests) == 1 and not events.of("reasoning_dropped")
