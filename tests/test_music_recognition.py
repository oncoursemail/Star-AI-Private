"""Mock-only music identification; no live song database, mic or paid call."""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import types
import wave

import httpx
import pytest

from star.audio_understanding import AudioSource
from star import music_recognition as music


def wav(*, seconds=12, rate=16000, sample=b"\x11\x22"):
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(sample * (seconds * rate))
    return output.getvalue()


def source(*, seconds=12, sample=b"\x11\x22"):
    return AudioSource("approved_clip", wav(seconds=seconds, sample=sample))


def run(coroutine):
    return asyncio.run(coroutine)


def test_exact_clip_provenance_and_window_checks():
    src = source(seconds=22)
    clip, info = music.clip_wav(src, begin_seconds=5, seconds=12)
    assert info["source_sha256"] == src.source_sha256
    assert info["clip_sha256"] == hashlib.sha256(clip).hexdigest()
    assert info["duration_seconds"] == 12
    assert info["start_seconds"] == 5
    assert len(clip) == 44 + 12 * 16000 * 2
    with pytest.raises(ValueError, match="four seconds"):
        music.clip_wav(src, begin_seconds=20, seconds=12)
    with pytest.raises(ValueError, match="limits"):
        music.clip_wav(src, seconds=40)
    with pytest.raises(ValueError, match="silent"):
        music.clip_wav(source(sample=b"\x00\x00"))


def test_audd_never_uploads_without_both_explicit_consents():
    src = source()
    with pytest.raises(PermissionError, match="consent"):
        run(music.recognize_audd(src, token="fake-token", allow_audio_upload=True))
    with pytest.raises(PermissionError):
        run(music.recognize_audd(src, token="fake-token", accept_possible_billing=True))


def test_audd_uploads_only_selected_clip_and_does_not_leak_key():
    calls = []
    def mock(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert str(request.url) == music.AUDD_ENDPOINT
        assert request.method == "POST"
        assert request.headers.get("authorization") is None
        assert request.url.query == b""
        assert b"fake-token" in request.content
        assert b"RIFF" in request.content
        return httpx.Response(200, json={
            "status": "success",
            "result": {"title": "Fictional Song", "artist": "Synthetic Artist",
                       "album": "Demo Album", "release_date": "2020"},
        })
    src = source(seconds=22)
    out = run(music.recognize_audd(
        src, token="fake-token", allow_audio_upload=True, accept_possible_billing=True,
        begin_seconds=4, seconds=12, transport=httpx.MockTransport(mock),
    ))
    assert len(calls) == 1
    assert out["status"] == "candidate_matches"
    assert out["candidates"][0]["title"] == "Fictional Song"
    assert out["candidates"][0]["score"] is None
    assert out["human_verified"] is False
    assert out["transferred"].startswith("Short selected WAV")
    assert "fake-token" not in json.dumps(out)


def test_audd_unmatched_and_refuses_credentials_errors_and_redirect():
    result = run(music.recognize_audd(
        source(), token="fake-token", allow_audio_upload=True, accept_possible_billing=True,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"status":"success", "result":None})),
    ))
    assert result["status"] == "no_match"
    for code in (302, 402, 429, 500):
        with pytest.raises(music.MusicRecognitionUnavailable):
            run(music.recognize_audd(
                source(), token="fake-token", allow_audio_upload=True, accept_possible_billing=True,
                transport=httpx.MockTransport(lambda request: httpx.Response(code)),
            ))


def test_provider_large_body_bad_json_do_not_echo_response():
    for payload in (b"z" * (music.MAX_RESPONSE_BYTES + 1), b"{not-json"):
        with pytest.raises(music.MusicRecognitionUnavailable):
            run(music.recognize_audd(
                source(), token="fake-token", allow_audio_upload=True, accept_possible_billing=True,
                transport=httpx.MockTransport(lambda request: httpx.Response(200, content=payload)),
            ))


def test_fingerprint_lookup_sends_no_raw_pcm_and_handles_ambiguous_results():
    fp = "aB12_" * 30
    _, info = music.clip_wav(source())
    def mock(request):
        assert str(request.url) == music.ACOUSTID_ENDPOINT
        assert request.method == "POST"
        assert b"RIFF" not in request.content
        assert b"fingerprint=" in request.content
        assert b"sample" not in request.content
        return httpx.Response(200, json={"status":"ok", "results": [
            {"score": 0.96, "recordings": [
                {"id":"r-1", "title":"Demo Song", "artists":[{"name":"Imaginary Artist"}]},
                {"id":"r-2", "title":"Demo Song Alternate", "artists":[{"name":"Another Artist"}]},
            ]},
        ]})
    result = run(music.recognize_acoustid(
        fp, 12, info, client_key="test-key",
        allow_fingerprint_lookup=True, noncommercial_usage_confirmed=True,
        transport=httpx.MockTransport(mock),
    ))
    assert result["status"] == "candidate_matches"
    assert len(result["candidates"]) == 2
    assert result["candidates"][0]["score_meaning"].startswith("Uncalibrated")
    assert result["human_verified"] is False
    assert fp not in json.dumps(result)
    assert "test-key" not in json.dumps(result)


def test_fingerprint_rejects_unapproved_commercial_and_malformed_inputs():
    _, info = music.clip_wav(source())
    with pytest.raises(PermissionError):
        run(music.recognize_acoustid(
            "x"*100, 12, info, client_key="test-key", allow_fingerprint_lookup=True))
    with pytest.raises(ValueError, match="fingerprint"):
        run(music.recognize_acoustid(
            "%bad", 12, info, client_key="test-key",
            allow_fingerprint_lookup=True, noncommercial_usage_confirmed=True))
    with pytest.raises(ValueError, match="provenance"):
        run(music.recognize_acoustid(
            "x" * 100, 12, {"source_id":"../bad"}, client_key="test-key",
            allow_fingerprint_lookup=True, noncommercial_usage_confirmed=True))


def test_local_fpcalc_uses_no_network_and_removes_temp_wave(monkeypatch, tmp_path):
    fpcalc = tmp_path / "fpcalc"
    fpcalc.write_text("stub", encoding="utf-8")
    seen = []
    def fake_run(argv, **kwargs):
        assert argv[:4] == [str(fpcalc.resolve()), "-length", "12", "-json"]
        filename = argv[-1]
        seen.append(filename)
        assert "star-fingerprint" in filename
        assert b"RIFF" in __import__("pathlib").Path(filename).read_bytes()
        return types.SimpleNamespace(returncode=0, stdout=json.dumps({
            "duration":12.0,"fingerprint":"abcdef0123456789_"
        }).encode())
    monkeypatch.setattr(music.subprocess, "run", fake_run)
    fp, duration, info = music.fingerprint_fpcalc(source(), fpcalc, seconds=12)
    assert fp and duration == 12
    assert info["source_id"] == "approved_clip"
    assert not __import__("pathlib").Path(seen[0]).exists()
    assert seen
