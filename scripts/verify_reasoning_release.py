"""Reproduce split-trigger leakage and bounded sentence release without a model."""
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from star.agent import read_stream
from star.reasoning_guard import ReasoningLoop


async def chunks(parts):
    for text in parts:
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text, tool_calls=None))])


def read(parts):
    events = []
    result = asyncio.run(read_stream(chunks(parts), events.append, guard=True))
    return result[0], "".join(e["text"] for e in events if e.get("event") == "assistant_delta")


def main():
    prefix = "In preparing this answer with all of the details from this discussion, I sho"
    assert read(["Hello. ", prefix, "uld check the status first."]) == ("Hello.", "Hello.")
    for size in (1, 2, 7, 60, 1000):
        text = "Hello. " + prefix + "uld check the status first."
        assert read([text[i:i + size] for i in range(0, len(text), size)]) == ("Hello.", "Hello.")
    # A punctuation character at a chunk boundary is provisional until a separator arrives.
    try:
        read(["The version is 1.", "25, and I sho", "uld check the status first."])
        raise AssertionError("a provisional punctuation boundary exposed the rejected sentence")
    except ReasoningLoop:
        pass
    for text in ("Hello", "word " * 40, "One complete sentence. Final tail",
                 "```python\n" + "".join(f"value_{i} = {i}  # I should check this\n" for i in range(300)) + "```\nDone."):
        assert read([text[i:i + 17] for i in range(0, len(text), 17)]) == (text, text)
    for text in ("x" * 4100, " " * 65537, "<think>" + "x" * 65536):
        try:
            read([text])
            raise AssertionError("oversized held response was released")
        except ReasoningLoop:
            pass
        assert read(["Hello. ", text]) == ("Hello.", "Hello.")
    assert read([]) == ("", "")
    print("Split reasoning triggers, provisional punctuation, normal/code tails and bounded buffers verified")


if __name__ == "__main__":
    main()
