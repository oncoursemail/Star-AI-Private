"""Privacy-safe fast sentence scanning and bounded hidden-stream regression tests."""
from __future__ import annotations

import random

import pytest

from star.voice.chunker import SentenceChunker


@pytest.mark.parametrize("token_size", [1, 2, 3, 7, 19, 400])
def test_protected_spans_and_punctuation_are_chunk_size_invariant(token_size: int) -> None:
    content = (
        "Start here. <think>Never speak hidden words. Really?</think> "
        "Now run this. ```luau\nprint('secret. text')\n``` "
        "The main.py file costs 3.5 units. Wait... you made it!"
    )
    chunker = SentenceChunker()
    spoken = []
    for offset in range(0, len(content), token_size):
        spoken.extend(chunker.feed(content[offset:offset + token_size]))
    spoken.extend(chunker.flush())
    assert spoken == [
        "Start here.",
        "Now run this.",
        "I've put the code on screen for you. The main.py file costs 3.5 units.",
        "Wait...", "you made it!",
    ]


def test_hidden_code_and_reasoning_too_large_fail_closed_without_resuming() -> None:
    for prefix in ("<think>", "```luau\n"):
        chunker = SentenceChunker()
        assert chunker.feed(prefix) == []
        with pytest.raises(ValueError, match="bounded pending buffer"):
            chunker.feed("a" * 65_536)
        assert chunker.pending == ""
        with pytest.raises(RuntimeError, match="discard overflowed"):
            chunker.feed("</think>Everything is good.")
        with pytest.raises(RuntimeError, match="discard overflowed"):
            chunker.flush()


def test_randomized_stream_sizes_do_not_leak_markup() -> None:
    rng = random.Random(26030)
    phrases = [
        "That is good. ", "A 3.5 score! ", "Ask Dr. Mei. ",
        "<think>hidden reasoning! secret.</think> ",
        "```lua\nprint(1)\n``` ", "We can go. ",
        "Wait?! ", "and then we can run. ",
    ]
    for _ in range(128):
        text = "".join(rng.choices(phrases, k=rng.randrange(2, 12)))
        chunker = SentenceChunker()
        out = []
        position = 0
        while position < len(text):
            size = rng.randrange(1, 13)
            out.extend(chunker.feed(text[position:position + size]))
            position += size
        out.extend(chunker.flush())
        assert "hidden reasoning" not in " ".join(out)
        assert "print(1)" not in " ".join(out)
        assert all("<think>" not in piece and "```" not in piece for piece in out)