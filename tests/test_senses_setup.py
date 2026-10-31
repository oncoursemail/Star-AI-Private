"""star.senses.setup: the installer's model step. Fakes only: nothing is downloaded."""
from __future__ import annotations

import re

import pytest

from star.senses import fastpath, setup


@pytest.fixture(autouse=True)
def folder(tmp_path, monkeypatch):
    monkeypatch.setenv("STAR_VOICE_MODELS", str(tmp_path / "voice"))
    monkeypatch.setattr(setup, "asr_ready", lambda model: False)
    return tmp_path / "voice"


def test_every_pin_has_a_size_and_a_sha256():
    for model in setup.ASR_MODELS.values():
        assert re.fullmatch(r"[0-9a-f]{64}", model.sha256) and re.fullmatch(r"[0-9a-f]{40}", model.revision)
        assert model.size > 1_000_000
    # the names are the ones fastpath's profiles and star.voice ask faster-whisper for
    assert {fastpath.PROFILES[p].asr_model for p in ("dedicated", "game")} <= set(setup.ASR_MODELS)


def test_plan_lists_every_download_once_and_marks_what_is_there(folder):
    folder.mkdir(parents=True)
    kokoro = setup.setup_models.MODEL_FILES[0]
    (folder / kokoro.name).write_bytes(b"x" * kokoro.size)
    rows = {row["name"]: row for row in setup.plan()}
    assert rows[kokoro.name]["present"] is True
    assert rows["Qwen3.5-4B-Q4_K_M.gguf"]["present"] is False and rows["Qwen3.5-2B-Q4_K_M.gguf"]["step"] == "fast"
    assert rows["llama-b11870-bin-win-cuda-12.4-x64.zip"]["step"] == "server"
    assert len(rows) == len(setup.plan())                      # no name twice
    assert sum(r["bytes"] for r in rows.values()) > 5_000_000_000


def test_list_downloads_nothing_and_prints_a_total(capsys, monkeypatch):
    monkeypatch.setattr(setup.setup_models, "download", lambda *a, **k: pytest.fail("downloaded"))
    assert setup.main(["--list"]) == 0
    out = capsys.readouterr().out
    assert "MISSING" in out and "to download:" in out and "Qwen3.5-4B" in out


def test_steps_report_ok_and_one_failure_does_not_stop_the_rest(capsys, monkeypatch):
    calls = []
    monkeypatch.setattr(setup.setup_models, "download", lambda *a, **k: calls.append("voice") or ["a", "b"])
    monkeypatch.setattr(setup, "fetch_asr", lambda model, report=print: calls.append(model.name) or True)

    def fast(profile, **_):
        calls.append(profile)
        if profile == "dedicated":
            raise RuntimeError("SHA-256 mismatch")
        return {"model": "m.gguf", "server": "s.exe"}
    monkeypatch.setattr(fastpath, "setup", fast)
    assert setup.main([]) == 1
    out = capsys.readouterr().out
    assert calls == ["voice", "small.en", "distil-small.en", "dedicated", "game"]
    assert "OK voice files" in out and "FAILED fast path, profile dedicated: RuntimeError: SHA-256 mismatch" in out
    assert "OK fast path, profile game: m.gguf" in out


def test_only_and_profiles_select_steps(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(setup.setup_models, "download", lambda *a, **k: calls.append("voice") or [])
    monkeypatch.setattr(fastpath, "setup", lambda p, **_: calls.append(p) or {"model": "m", "server": "s.exe"})
    assert setup.main(["--only", "fast", "--profiles", "game"]) == 0
    assert setup.main(["--only", "server"]) == 0
    assert calls == ["game", "game-tight"]
    assert setup.main(["--only", "bogus"]) == 2
    assert setup.main(["--profiles", "nonsense"]) == 2


def test_a_profile_without_a_local_model_is_not_downloaded(monkeypatch):
    calls = []
    monkeypatch.setattr(fastpath, "setup", lambda p, **_: calls.append(p) or {"model": "", "server": "s"})
    assert setup.main(["--only", "fast", "--profiles", "game-tight"]) == 0
    assert calls == []
