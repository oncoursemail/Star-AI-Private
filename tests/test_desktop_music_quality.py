"""Backend contract tests: no GUI, secrets, real mic or music network required."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import threading
import wave

import pytest

from star.desktop_music_quality import DesktopMusicQuality, OWNER_ACTIONS


def wav(seconds=12, sample=b"\x01\x22"):
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(sample * (16000 * seconds))
    return output.getvalue()


def selected(tmp_path, seconds=12):
    p = tmp_path / "private-recording.wav"
    p.write_bytes(wav(seconds))
    service = DesktopMusicQuality()
    status = service.select_wav(p)
    assert status["selected"] and status["file"] == p.name
    return service, p


def test_only_trusted_bounded_wav_selected_without_key_or_upload(monkeypatch, tmp_path):
    monkeypatch.delenv("STAR_AUDD_API_TOKEN", raising=False)
    monkeypatch.delenv("STAR_ACOUSTID_CLIENT_KEY", raising=False)
    service, path = selected(tmp_path)
    status = service.status()
    assert status["audd_configured"] is False
    assert status["acoustid_configured"] is False
    assert status["duration_seconds"] == 12
    assert status["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert "mic" not in str(status).casefold() or status["microphone_supported"] == "optional_voice_package"
    assert "musicIdentify" in OWNER_ACTIONS and "qualityPreview" in OWNER_ACTIONS
    assert "runShell" not in OWNER_ACTIONS
    assert service.clear_music()["selected"] is False


def test_reject_symlink_oversize_wrong_file_and_malformed_audio(tmp_path):
    service = DesktopMusicQuality()
    wrong = tmp_path / "bad.mp3"
    wrong.write_bytes(b"xyz")
    with pytest.raises(ValueError):
        service.select_wav(wrong)
    invalid = tmp_path / "broken.wav"
    invalid.write_bytes(b"not a wave file")
    with pytest.raises(ValueError):
        service.select_wav(invalid)
    oversize = tmp_path / "too-large.wav"
    oversize.write_bytes(b"z" * (8 * 1024 * 1024 + 1))
    with pytest.raises(ValueError):
        service.select_wav(oversize)
    target = tmp_path / "regular.wav"
    target.write_bytes(wav())
    link = tmp_path / "shortcut.wav"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symlinks require privileges on this runner")
    with pytest.raises(ValueError):
        service.select_wav(link)


def test_each_provider_requires_real_consent_before_capture_or_network(monkeypatch, tmp_path):
    service, _ = selected(tmp_path)
    monkeypatch.setenv("STAR_AUDD_API_TOKEN", "fake-token")
    monkeypatch.setenv("STAR_ACOUSTID_CLIENT_KEY", "fake-client")
    with pytest.raises(PermissionError, match="separate"):
        service.identify({"provider": "audd", "source": "file", "seconds": 12,
                          "uploadConsent": True})
    with pytest.raises(PermissionError, match="required"):
        service.identify({"provider": "acoustid", "source": "file", "seconds": 12,
                          "fingerprintConsent": True})
    with pytest.raises(PermissionError, match="microphone"):
        service.identify({"provider": "audd", "source": "mic", "seconds": 12,
                          "uploadConsent": True, "billingConsent": True})
    for n in (0, -4, 31, True):
        with pytest.raises(ValueError):
            service.identify({"provider": "audd", "source": "file", "seconds": n,
                              "uploadConsent": True, "billingConsent": True})


def test_audd_reuses_selected_audio_and_never_uses_model_written_path(monkeypatch, tmp_path):
    service, path = selected(tmp_path)
    monkeypatch.setenv("STAR_AUDD_API_TOKEN", "fake-token")
    observed = {}
    async def fake(source, **kwargs):
        observed.update(kwargs)
        assert source.source_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
        return {"status": "candidate_matches", "human_verified": False,
                "candidates": [{"title": "Fixture Song", "artist": "Fake"}]}
    monkeypatch.setattr("star.desktop_music_quality.music_recognition.recognize_audd", fake)
    progress = []
    result = service.identify({
        "provider": "audd", "source": "file", "seconds": 8,
        "uploadConsent": True, "billingConsent": True,
        "path": "/secrets/ignore-this.wav",
    }, progress=progress.append)
    assert result["candidates"][0]["title"] == "Fixture Song"
    assert observed["token"] == "fake-token"
    assert observed["seconds"] == 8
    assert progress == ["Uploading the selected snippet"]
    assert "fake-token" not in json.dumps(result)
    assert service.status()["busy"] is False


def test_mic_capture_happens_only_after_consent_and_does_not_persist(monkeypatch):
    service = DesktopMusicQuality()
    monkeypatch.setenv("STAR_AUDD_API_TOKEN", "fake-token")
    captured = []
    def fake_capture(*, seconds, device_index=None):
        captured.append((seconds, device_index))
        from star.audio_understanding import AudioSource
        return AudioSource("consented_mic", wav(seconds))
    async def fake_match(source, **kwargs):
        return {"status": "no_match", "source_id": source.source_id}
    monkeypatch.setattr("star.desktop_music_quality.music_recognition.capture_microphone", fake_capture)
    monkeypatch.setattr("star.desktop_music_quality.music_recognition.recognize_audd", fake_match)
    result = service.identify({
        "provider": "audd", "source": "mic", "seconds": 8, "deviceIndex": 2,
        "micConsent": True, "uploadConsent": True, "billingConsent": True,
    })
    assert captured == [(8, 2)]
    assert result["source_id"] == "consented_mic"
    assert service.status()["selected"] is False


def test_acoustid_uses_only_trusted_chromaprint_selection(monkeypatch, tmp_path):
    service, _ = selected(tmp_path)
    binary = tmp_path / "fpcalc.exe"
    binary.write_bytes(b"fixture")
    assert service.select_fpcalc(binary)["fpcalc_selected"]
    monkeypatch.setenv("STAR_ACOUSTID_CLIENT_KEY", "test-client")
    called = []
    def fake_fpcalc(source, exe, *, begin_seconds, seconds):
        called.append((exe,begin_seconds,seconds))
        return "long_fake_signature_valid", 12, {"source_id":"test",
              "source_sha256":"a"*64,"clip_sha256":"b"*64,
              "start_seconds":0,"duration_seconds":12}
    async def fake_lookup(fingerprint, duration, info, **kwargs):
        assert kwargs["client_key"] == "test-client"
        assert kwargs["noncommercial_usage_confirmed"] is True
        return {"status": "no_match", "human_verified": False}
    monkeypatch.setattr("star.desktop_music_quality.music_recognition.fingerprint_fpcalc", fake_fpcalc)
    monkeypatch.setattr("star.desktop_music_quality.music_recognition.recognize_acoustid", fake_lookup)
    result = service.identify({
        "provider": "acoustid", "source": "file", "seconds": 12,
        "fingerprintConsent": True, "noncommercialConsent": True,
    })
    assert result["status"] == "no_match"
    assert called == [(binary.resolve(), 0, 12)]


def test_quality_only_hashes_artifact_and_never_invents_receipts(tmp_path):
    service = DesktopMusicQuality()
    first = service.quality_preview("game")
    assert first["state"] == "unverified" and not first["selected"]
    py = tmp_path / "feature.py"
    py.write_text("def add(a,b):\n    return a + b\n", encoding="utf-8")
    info = service.select_quality_file(py)
    assert info["selected"]
    assert info["syntax"]["status"] == "passed_static_only"
    gate = service.quality_preview("software")
    assert gate["state"] == "needs_evidence"
    assert gate["checks_passed"] == 0
    assert gate["checks_total"] == 4
    assert gate["artifact"]["artifact_sha256"] == hashlib.sha256(py.read_bytes()).hexdigest()
    assert all(item["state"] == "needs_evidence" for item in gate["criteria"] if item["critical"])
    assert service.clear_quality() == {"selected": False}
    assert service.quality_preview("software")["state"] == "unverified"


def test_bad_source_reports_syntax_failure_but_never_executes_code(tmp_path):
    service = DesktopMusicQuality()
    broken = tmp_path / "bad.py"
    broken.write_text("import os\nraise Exception('should never run')\nif (\n",encoding="utf-8")
    item = service.select_quality_file(broken)
    assert item["syntax"]["status"] == "failed"
    assert item["syntax"]["line"] is not None
    result = service.quality_preview("software")
    assert result["checks_passed"] == 0
    with pytest.raises(ValueError,match="supported"):
        service.quality_preview("perfect_model")
    link = tmp_path / "bad-link.py"
    try:
        link.symlink_to(broken)
    except OSError:
        pytest.skip("Symlinks not available")
    with pytest.raises(ValueError):
        service.select_quality_file(link)


def test_busy_lookup_cannot_overlap_or_replace_audio(tmp_path, monkeypatch):
    service, path = selected(tmp_path)
    monkeypatch.setenv("STAR_AUDD_API_TOKEN", "fake-token")
    service._busy = True  # a simulated active worker, not a real network job
    with pytest.raises(RuntimeError,match="already running"):
        service.identify({"provider":"audd","source":"file","seconds":12,
                          "uploadConsent":True,"billingConsent":True})
    with pytest.raises(RuntimeError,match="running"):
        service.select_wav(path)
    with pytest.raises(RuntimeError,match="running"):
        service.clear_music()
