"""Voice replies opened with the prompt's own example ("Oh, well done." in 57 of 100 replies, docs/agents/human-voice-20261025.md).
CallConfig.varied_openers: no example phrase in the system prompt, a different few openers in each turn's user message."""
import pytest

from star.voice.call import RETRY_NOTE, CallConfig, CallSession
from star.voice.persona import (HINT_SIZE, STYLE_PROMPTS, _OPENER_LINES, _OPENER_POOLS, opener_hint, system_message)
from star.voice.turn import TurnConfig
from voice_fakes import Events, FakeASR, FakeBrain, FakeSpeaker, FakeTTS, FakeVAD, quiet, speech

TEXTS = {1: "i finished the pull request"}


def call(varied, replies=("Oh, nice. Tell me more.",)):
    events, brain = Events(), FakeBrain(list(replies))
    session = CallSession(vad=FakeVAD(), asr=FakeASR(TEXTS, 0.0), brain=brain, tts=FakeTTS(), speaker=FakeSpeaker(),
                          config=CallConfig(turn=TurnConfig(), partial_transcripts=False, varied_openers=varied), on_event=events)
    session.start()
    for frame in speech(1, 20) + quiet(40):
        session.feed(frame)
    assert session.wait_idle(5)
    return session, brain


@pytest.mark.parametrize("style", sorted(STYLE_PROMPTS))
def test_the_varied_prompt_drops_the_example_phrases_and_keeps_the_rest(style):
    literal, described = _OPENER_LINES[style]
    plain, varied = system_message(style=style)["content"], system_message(style=style, varied=True)["content"]
    assert literal in plain and plain == STYLE_PROMPTS[style]          # off: the prompt is byte-identical to before
    assert literal not in varied and described in varied
    assert varied.replace(described, literal) == plain                  # nothing else changed
    for phrase in ('"Oh, well done."', '"Okay, I hear you."', '"Good."', '"Okay, okay!"'):
        assert phrase not in varied


@pytest.mark.parametrize("style", sorted(_OPENER_POOLS))
def test_every_turn_offers_other_openers_than_the_turn_before(style):
    pool = _OPENER_POOLS[style]
    offered = [{p for p in pool if f'"{p}"' in opener_hint(turn, style)} for turn in range(1, 9)]
    assert all(len(o) == HINT_SIZE for o in offered)
    assert all(not a & b for a, b in zip(offered, offered[1:]))
    assert len(set().union(*offered)) == len(pool)                        # all of them come up within a cycle
    assert opener_hint(1, style) == opener_hint(1, style)                 # deterministic, so the test above is stable


def test_off_the_request_is_exactly_what_it_was_and_on_the_note_is_in_the_request_but_not_the_history():
    session, brain = call(False)
    assert brain.requests[0][-1]["content"] == TEXTS[1] and brain.requests[0][0]["content"] == STYLE_PROMPTS["warm-caring"]
    session, brain = call(True)
    last = brain.requests[0][-1]["content"]
    assert last.startswith(TEXTS[1]) and last == TEXTS[1] + opener_hint(1) and "well done" not in brain.requests[0][0]["content"]
    assert session.history[0] == {"role": "user", "content": TEXTS[1]}      # the note never enters the history


def test_the_plan_retry_keeps_the_note():
    plan = "Okay, the user just asked about the pull request. I need to start with a short warm reaction."
    session, brain = call(True, [plan, "Oh, nice. Well done."])
    assert brain.requests[1][-1]["content"] == TEXTS[1] + opener_hint(1) + RETRY_NOTE
