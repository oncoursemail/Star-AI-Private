"""Reproductions and negative tests for the Strata #728 loop circuit breaker."""
import pytest

from star.strata_loop_guard import (
    MAX_TAIL, StrataRepetitionError, StrataRepetitionGuard,
)


def test_thinking_sentence_repeated_at_length_is_cut_off():
    guard = StrataRepetitionGuard()
    sentence = (
        "Actually, wait: maybe the screenshot is showing the app's old Disk bar? "
        "No, the screenshot shows both Disk and Steam rows. "
    )
    with pytest.raises(StrataRepetitionError, match="reasoning") as error:
        for _ in range(300):
            guard.feed("reasoning", sentence)
    assert "screenshot" not in str(error.value).lower()
    assert len(guard._tails["reasoning"]) <= MAX_TAIL


def test_repeat_in_answer_even_when_thinking_off():
    guard = StrataRepetitionGuard()
    with pytest.raises(StrataRepetitionError, match="answer"):
        for _ in range(300):
            guard.feed("answer", "It may be a networking timeout after the retry. ")


def test_periodic_numerical_loop_is_bounded():
    guard = StrataRepetitionGuard()
    with pytest.raises(StrataRepetitionError):
        for _ in range(200):
            guard.feed("reasoning", "45123098764" * 4)


def test_long_code_or_similar_repeated_keys_not_treated_as_loop():
    guard = StrataRepetitionGuard()
    for i in range(250):
        guard.feed("answer", f"line_{i} = {{'key': 'value', 'value': {i}}}\n")
    assert len(guard._tails["answer"]) <= MAX_TAIL


def test_two_short_repetitions_do_not_trigger():
    guard = StrataRepetitionGuard()
    for _ in range(2):
        guard.feed("answer", "The same status appears again. " * 10)
    for i in range(200):
        guard.feed("answer", f"unique observation {i} differs from the prior result. ")
    assert guard._sizes["answer"] > 5000


def test_nontext_sections_are_rejected():
    guard = StrataRepetitionGuard()
    with pytest.raises(ValueError):
        guard.feed("tool_arguments", "foo")


def test_chunk_boundaries_do_not_hide_long_repetition():
    sentence = "Wait again, the inputs disagree and I should revisit my last conclusion. "
    text = sentence * 180
    guards = [StrataRepetitionGuard(), StrataRepetitionGuard()]
    for size, guard in zip((3, 221), guards):
        with pytest.raises(StrataRepetitionError):
            for index in range(0, len(text), size):
                guard.feed("reasoning", text[index:index + size])
