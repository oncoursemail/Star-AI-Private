"""Synthetic-only tests; never contacts a real inference backend."""
from __future__ import annotations

import re
from threading import Barrier

import pytest

from star.llama_cache_isolation_probe import (
    run_cache_isolation_probe, validate_loopback_endpoint,
)


MARKER = "STAR_CANARY_" + "a" * 24


def _which(payload: dict[str, object]) -> str:
    messages = payload["messages"]
    assert isinstance(messages, list)
    first = messages[0]
    assert isinstance(first, dict)
    system = str(first["content"])
    assert payload["cache_prompt"] is True
    assert payload["stream"] is False
    return "A" if system.startswith("Test A:") else "B"


def test_synthetic_replies_produce_only_a_non_proof_status():
    n = {"a": 0, "b": 0}
    def fake(payload):
        arm = _which(payload)
        if arm == "A":
            n["a"] += 1
            return f"ALPHA_OK_{n['a'] - 1}"
        n["b"] += 1
        return f"BETA_OK_{n['b'] - 1}"

    tokens = iter("STAR_CANARY_" + f"{index:024x}" for index in range(4))
    result = run_cache_isolation_probe(
        fake, pairs=4, filler_blocks=1, token_factory=lambda: next(tokens),
    )
    assert result.verdict == "no_leak_observed_not_proven_safe"
    assert result.completed_pairs == 4
    assert result.attempted_pairs == 4
    assert result.leak_indicators == 0
    assert result.failed_requests == 0
    assert result.response_time_p95_ms is not None
    assert MARKER not in repr(result)
    assert "proof" in result.note.lower()


def test_cross_session_canary_is_detected_and_probe_stops():
    calls = []
    seen = {"marker": ""}
    def fake(payload):
        arm = _which(payload)
        calls.append(arm)
        if arm == "A":
            messages = payload["messages"]
            assert isinstance(messages, list)
            system = str(messages[0]["content"])
            match = re.search(r"STAR_CANARY_[0-9a-f]{24}", system)
            assert match is not None
            seen["marker"] = match.group()
            return "ALPHA_OK_0"
        return f"Oops! {seen['marker']}"

    result = run_cache_isolation_probe(
        fake, pairs=8, filler_blocks=2, token_factory=lambda: MARKER,
    )
    assert result.verdict == "possible_context_leak"
    assert result.leak_indicators == 1
    assert result.completed_pairs == 1
    assert result.attempted_pairs == 1
    assert calls == ["A", "B"]
    assert MARKER not in repr(result)


def test_old_answer_leaking_to_new_turn_is_detected():
    def fake(payload):
        return "ALPHA_OK_0" if _which(payload) == "A" else "ALPHA_OK_0"
    result = run_cache_isolation_probe(
        fake, pairs=2, filler_blocks=1, token_factory=lambda: MARKER,
    )
    assert result.leak_indicators == 1


def test_earlier_session_marker_is_detected_not_only_immediate_pair():
    tokens = iter("STAR_CANARY_" + f"{i:024x}" for i in range(3))
    original = "STAR_CANARY_" + "0" * 24
    def fake(payload):
        arm = _which(payload)
        system = str(payload["messages"][0]["content"])
        if arm == "A":
            match = re.search(r"ALPHA_OK_\d+", system)
            assert match is not None
            return match.group()
        match = re.search(r"BETA_OK_\d+", system)
        assert match is not None
        if match.group() == "BETA_OK_1":
            return original
        return match.group()
    result = run_cache_isolation_probe(
        fake, pairs=3, filler_blocks=1, token_factory=lambda: next(tokens),
    )
    assert result.verdict == "possible_context_leak"
    assert result.completed_pairs == 2
    assert result.leak_indicators == 1


def test_concurrent_two_slot_requests_are_actually_overlapped():
    barrier = Barrier(2)
    def fake(payload):
        arm = _which(payload)
        barrier.wait(timeout=4)
        return "ALPHA_OK_0" if arm == "A" else "BETA_OK_0"
    result = run_cache_isolation_probe(
        fake, pairs=1, filler_blocks=1, concurrent=True,
        token_factory=lambda: MARKER,
    )
    assert result.verdict == "no_leak_observed_not_proven_safe"
    assert result.completed_pairs == 1


def test_reused_marker_is_not_a_valid_isolation_experiment():
    def fake(payload):
        return "ALPHA_OK_0" if _which(payload) == "A" else "BETA_OK_0"
    with pytest.raises(ValueError, match="unique"):
        run_cache_isolation_probe(
            fake, pairs=2, filler_blocks=1, token_factory=lambda: MARKER,
        )


def test_model_noncompliance_is_not_mislabeled_as_cache_safety():
    def fake(payload):
        return "a vague answer" if _which(payload) == "A" else "BETA_OK_0"
    result = run_cache_isolation_probe(
        fake, pairs=1, filler_blocks=1, token_factory=lambda: MARKER,
    )
    assert result.verdict == "inconclusive"
    assert result.unexpected_responses == 1
    assert result.leak_indicators == 0


def test_error_is_bounded_and_cannot_be_counted_as_success():
    def fake(payload):
        if _which(payload) == "B":
            raise TimeoutError("synthetic timeout")
        return "ALPHA_OK_0"
    result = run_cache_isolation_probe(
        fake, pairs=6, filler_blocks=1, token_factory=lambda: MARKER,
    )
    assert result.verdict == "inconclusive"
    assert result.attempted_pairs == 1
    assert result.completed_pairs == 0
    assert result.failed_requests == 1


@pytest.mark.parametrize("kwargs", [
    {"pairs": True}, {"pairs": 0}, {"pairs": 13},
    {"filler_blocks": False}, {"filler_blocks": 0}, {"filler_blocks": 257},
    {"concurrent": 1},
    {"token_factory": lambda: "../bad"},
])
def test_bad_probe_configurations_rejected(kwargs):
    with pytest.raises((ValueError, TypeError)):
        run_cache_isolation_probe(lambda _payload: "", **kwargs)


@pytest.mark.parametrize("bad", [
    "https://127.0.0.1:8080/v1/chat/completions",
    "http://localhost:8080/v1/chat/completions",
    "http://192.168.1.2:8080/v1/chat/completions",
    "http://127.0.0.1:8080/v1/chat/completions?token=x",
    "http://user:pass@127.0.0.1:8080/v1/chat/completions",
    "http://127.0.0.1:8080/other",
    "http://127.0.0.1:8080/v1/chat/completions#override",
    "file:///etc/passwd",
    "http://127.0.0.1:bad/v1/chat/completions",
])
def test_only_literal_loopback_http_endpoint_is_allowed(bad):
    with pytest.raises(ValueError):
        validate_loopback_endpoint(bad)


def test_valid_explicit_loopback_endpoint_is_accepted():
    url = "http://127.0.0.1:8080/v1/chat/completions"
    assert validate_loopback_endpoint(url) == url
