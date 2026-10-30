"""Pure offline tests; never dispatch local models, record audio, or open OBS."""
from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace

import pytest

import star.inference_stream_benchmark as mod
from star.inference_stream_benchmark import (
    StartupProbe, benchmark_stream_startup, summarize_stream_startup,
)


def _packet(text=None, *, finish=None, reasoning=None):
    return SimpleNamespace(choices=[SimpleNamespace(
        delta=SimpleNamespace(content=text, reasoning_content=reasoning),
        finish_reason=finish,
    )])


class FakeStream:
    def __init__(self, owner, prompt, mode):
        self.owner = owner
        self.prompt = prompt
        self.mode = mode
        self.closed = False

    async def __aiter__(self):
        yield _packet()  # role-only chunk is not audible or visible text
        yield _packet(reasoning="thinking, not spoken")
        if self.mode == "empty":
            yield _packet(finish="stop")
            return
        if self.mode == "exception":
            raise RuntimeError("secret-key-NEVER-LEAK")
        if self.mode == "slow":
            await asyncio.sleep(0.05)
        else:
            await asyncio.sleep(0.001)
        token = re.findall(r"STAR-CANARY-\d{2}", self.prompt)
        if token:
            assert len(token) == 1
            response = token[0]
            if self.mode == "stale" and self.owner.previous is not None:
                response = self.owner.previous
            self.owner.previous = token[0]
        elif self.mode == "long":
            response = "safe " * 75
        else:
            response = "Synthetic visible words"
        yield _packet(response[:6])
        yield _packet(response[6:])
        if self.mode == "no_stop":
            return
        yield _packet(finish="length" if self.mode == "length" else "stop")

    async def close(self):
        if not self.closed:
            self.closed = True
            self.owner.active -= 1
            self.owner.closed += 1


class FakeCompletions:
    def __init__(self, mode="good"):
        self.mode = mode
        self.calls = []
        self.active = 0
        self.peak = 0
        self.closed = 0
        self.previous = None

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        self.active += 1
        self.peak = max(self.peak, self.active)
        return FakeStream(self, kwargs["messages"][1]["content"], self.mode)


def _client(stub):
    return SimpleNamespace(chat=SimpleNamespace(completions=stub))


def _run(stub, **opts):
    return asyncio.run(benchmark_stream_startup(
        "http://127.0.0.1:8080/v1", "local-test",
        client=_client(stub), **opts,
    ))


def test_real_async_chunks_measure_visible_text_and_complete_stop():
    fake = FakeCompletions()
    report = _run(fake, requests=4, parallel=2)
    assert report["requests"] == report["completed"] == 4
    assert report["failed"] == 0
    assert report["first_visible_p50_ms"] is not None
    assert 0 <= report["first_visible_p95_ms"] <= report["complete_p95_ms"]
    assert fake.closed == len(fake.calls) == 4
    assert fake.active == 0 and fake.peak == 2
    assert all(call["stream"] is True for call in fake.calls)
    assert all(call["max_tokens"] == 96 and call["temperature"] == 0 for call in fake.calls)
    assert all([msg["role"] for msg in call["messages"]] == ["system", "user"]
               for call in fake.calls)
    assert report["workload_sha256"] == _run(FakeCompletions(), requests=4,
                                             parallel=1)["workload_sha256"]
    assert report["workload_sha256"] != _run(FakeCompletions(), requests=4,
                                             workload="repeat")["workload_sha256"]
    assert not report["repeated_prompt_warning"]
    assert report["statuses"]["ok"] == 4
    assert "Synthetic visible" not in repr(report)
    assert "first audible" in report["note"].lower()


@pytest.mark.parametrize("mode,status,part", [
    ("empty", "empty", 0),
    ("no_stop", "incomplete", 1),
    ("length", "truncated", 1),
    ("exception", "failed", 0),
])
def test_incomplete_and_failed_streams_never_improve_latency(mode, status, part):
    fake = FakeCompletions(mode)
    report = _run(fake, requests=1)
    assert report["statuses"][status] == 1
    assert report["completed"] == 0
    assert report["first_visible_p50_ms"] is None
    assert report["complete_p95_ms"] is None
    assert report["partial_visible_failures"] == part
    assert fake.active == 0
    assert "secret-key" not in repr(report)


def test_long_ordinary_replies_are_not_evidence_of_truncated_streams():
    fake = FakeCompletions("long")
    report = _run(fake, requests=3)
    # The 256-character capture cap is for secret-minimization and canary
    # comparison, NOT an artificial ceiling on a normal model's spoken reply.
    assert report["completed"] == 3
    assert report["statuses"]["truncated"] == 0


def test_unique_canaries_detect_stale_backend_slot_state():
    fine = _run(FakeCompletions("good"), requests=4, workload="canary")
    assert fine["completed"] == 4 and fine["canary_mismatches"] == 0
    bad = _run(FakeCompletions("stale"), requests=4, workload="canary")
    assert bad["completed"] == 1
    assert bad["canary_mismatches"] == 3
    assert bad["statuses"]["canary_mismatch"] == 3
    assert bad["partial_visible_failures"] == 3


def test_server_failure_and_timeout_close_async_stream(monkeypatch):
    monkeypatch.setattr(mod, "_REQUEST_TIMEOUT_SECONDS", 0.002)
    fake = FakeCompletions("slow")
    report = _run(fake, requests=1)
    assert report["statuses"]["timeout"] == 1
    assert report["completed"] == 0
    assert fake.active == 0 and fake.closed == 1


@pytest.mark.parametrize("opts", [
    {"requests": 0}, {"requests": 9}, {"requests": True},
    {"parallel": 0}, {"parallel": 3}, {"parallel": True},
    {"workload": "other"}, {"workload": None},
    {"server": 1}, {"model": ""}, {"model": None},
    {"requests": 5, "workload": "canary", "parallel": 2},
])
def test_bad_requests_do_not_contact_server(opts):
    fake = FakeCompletions()
    with pytest.raises((ValueError, TypeError)):
        _run(fake, **opts)
    assert fake.calls == []


def test_public_server_blocked_without_network_call():
    fake = FakeCompletions()
    with pytest.raises(ValueError):
        asyncio.run(benchmark_stream_startup(
            "https://provider.example.com/v1", "local-test",
            client=_client(fake),
        ))
    assert not fake.calls


def test_repeat_mode_is_explicitly_labeled_cache_sensitive():
    report = _run(FakeCompletions(), requests=4, workload="repeat")
    assert report["repeated_prompt_warning"] and report["completed"] == 4


def test_summary_rejects_fabricated_latency_values_and_bad_counts():
    good = StartupProbe("safe", 2.0, 3.0, "ok")
    summary = summarize_stream_startup([good], 4, parallel=1,
                                       workload="mixed", workload_digest="a" * 64)
    assert summary["first_visible_p50_ms"] == 2
    for bad in (
        StartupProbe("x", 5.0, 3.0, "ok"),
        StartupProbe("x", float("nan"), 4.0, "ok"),
        StartupProbe("x", 1.0, -1.0, "ok"),
        StartupProbe("x", 1.0, 2.0, "fake"),
    ):
        with pytest.raises(ValueError):
            summarize_stream_startup([bad], 4, parallel=1,
                                     workload="mixed", workload_digest="a" * 64)
    with pytest.raises(ValueError):
        summarize_stream_startup([good], -1, parallel=1,
                                 workload="mixed", workload_digest="a" * 64)


def test_existing_cli_has_opt_in_stream_mode_with_same_synthetic_workload(monkeypatch, capsys):
    import scripts.benchmark_star as cli

    async def fake_stream(*args, **kwargs):
        assert args == ("http://127.0.0.1:8080/v1", "model-a")
        assert kwargs == {
            "requests": 3, "parallel": 1,
            "workload": "canary", "server": False,
        }
        return {"completed": 3, "first_visible_p95_ms": 8}

    async def unavailable(*args, **kwargs):
        raise AssertionError("wrong benchmark selected")

    monkeypatch.setattr(cli, "benchmark_stream_startup", fake_stream)
    monkeypatch.setattr(cli, "benchmark_local_model", unavailable)
    cli.main(["--model", "model-a", "--stream-startup",
              "--requests", "3", "--workload", "canary"])
    assert '"first_visible_p95_ms": 8' in capsys.readouterr().out


def test_existing_cli_default_completion_route_remains_intact(monkeypatch, capsys):
    import scripts.benchmark_star as cli

    async def fake_completion(*args, **kwargs):
        assert kwargs["parallel"] == 2
        return {"successful": 2, "median_request_ms": 42}

    async def unavailable(*args, **kwargs):
        raise AssertionError("streaming must remain off by default")

    monkeypatch.setattr(cli, "benchmark_stream_startup", unavailable)
    monkeypatch.setattr(cli, "benchmark_local_model", fake_completion)
    cli.main(["--model", "model-a", "--parallel", "2"])
    assert '"median_request_ms": 42' in capsys.readouterr().out


# The operational voice pipeline waits for a sentence/phrase, NOT merely a
# first character. Exercise the exact production SentenceChunker with realistic
# split SSE deltas; none of the fragments are persisted in the report.
class SegmentedStream:
    def __init__(self, fragments):
        self.fragments = fragments
        self.closed = False

    async def __aiter__(self):
        yield _packet(reasoning="private internal analysis")
        for content, delay in self.fragments:
            await asyncio.sleep(delay)
            yield _packet(content)
        yield _packet(finish="stop")

    async def close(self):
        self.closed = True


class SegmentedCompletions:
    def __init__(self, fragments):
        self.fragments = fragments
        self.streams = []

    async def create(self, **kwargs):
        stream = SegmentedStream(self.fragments)
        self.streams.append(stream)
        return stream


def test_first_speakable_waits_for_production_phrase_not_first_letter():
    fake = SegmentedCompletions([
        ("Hey, ", 0.002),
        ("we can play", 0.003),
        (" now!", 0.003),
    ])
    report = _run(fake, requests=1)
    assert report["completed"] == report["speakable_ready"] == 1
    assert report["speakable_missing"] == 0
    assert 0 < report["first_visible_p50_ms"] < report["first_speakable_p50_ms"]
    assert report["first_speakable_p95_ms"] <= report["complete_p95_ms"]
    assert all(stream.closed for stream in fake.streams)
    assert "we can play" not in repr(report)


def test_punctuation_free_reply_becomes_speakable_at_stream_end():
    report = _run(SegmentedCompletions([
        ("We should", 0.002), (" test the checkpoint first", 0.002),
    ]), requests=1)
    assert report["completed"] == report["speakable_ready"] == 1
    assert report["first_visible_p50_ms"] < report["first_speakable_p50_ms"]
    assert report["first_speakable_p50_ms"] <= report["complete_p50_ms"]


def test_hidden_only_reply_reports_missing_speech_without_false_low_latency():
    report = _run(SegmentedCompletions([
        ("<think>reasoning only.</think>", 0.001),
        (" ** ** 🎮", 0.001),
    ]), requests=1)
    assert report["completed"] == 1  # a visible nonempty transport response
    assert report["speakable_ready"] == 0
    assert report["speakable_missing"] == 1
    assert report["first_speakable_p50_ms"] is None
    assert report["first_speakable_p95_ms"] is None


def test_long_canary_never_leaks_or_references_unassigned_capture_piece():
    fake = SegmentedCompletions([
        ("A" * (mod._OUTPUT_BOUND + 20), 0.001),
        ("another packet", 0.001),
    ])
    report = _run(fake, workload="canary", requests=1)
    assert report["completed"] == 0
    assert report["statuses"]["truncated"] == 1
    assert report["statuses"]["failed"] == 0
    assert all(stream.closed for stream in fake.streams)
    assert "another packet" not in repr(report)


@pytest.mark.parametrize("invalid", [
    StartupProbe("case", 8, 20, "ok", first_speakable_ms=2),
    StartupProbe("case", None, 20, "ok", first_speakable_ms=5),
    StartupProbe("case", 2, 20, "ok", first_speakable_ms=21.5),
    StartupProbe("case", 2, 20, "ok", first_speakable_ms=float("nan")),
    StartupProbe("case", 2, 20, "ok", first_speakable_ms=True),
])
def test_speakable_summary_rejects_impossible_or_fabricated_clock_values(invalid):
    with pytest.raises(ValueError):
        summarize_stream_startup([invalid], 30, parallel=1,
                                 workload="mixed", workload_digest="a" * 64)
