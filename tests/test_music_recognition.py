"""Song recognition: fake catalogs (httpx.MockTransport) and a fake fpcalc; no network, microphone or paid call."""
from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from types import SimpleNamespace
import wave

import httpx
import pytest

from star import agent, music_recognition as music
from star.audio_understanding import AudioSource
from star.react_shell import song_lookup_request

KEY = "owner-test-key-123"
PUBLIC = "93.184.215.14"


def wav(seconds=20, rate=16000, sample=b"\x11\x22"):
    out = io.BytesIO()
    with wave.open(out, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(sample * (seconds * rate))
    return out.getvalue()


def source(**kwargs):
    return AudioSource("test_song", wav(**kwargs))


def settings(on=True, fpcalc_path=""):
    return SimpleNamespace(music_recognition_enabled=on, fpcalc_path=fpcalc_path)


def keys(name):
    return KEY


class Catalog:
    """Records each request (URL, Host, body) and answers with `reply`."""

    def __init__(self, reply, status=200):
        self.reply, self.status, self.seen = reply, status, []

    def transport(self):
        def handle(request: httpx.Request) -> httpx.Response:
            request.read()
            self.seen.append(SimpleNamespace(url=str(request.url), host=request.headers.get("host"),
                                             body=request.content, method=request.method))
            return httpx.Response(self.status, json=self.reply)
        return httpx.MockTransport(handle)


def lookup(catalog, src=None, *, provider="audd", consent=True, cfg=None, key_for=keys, **kwargs):
    return asyncio.run(music.identify(src or source(), provider=provider, consent=consent, settings=cfg or settings(),
                                      key_for=key_for, transport=catalog.transport(),
                                      resolver=lambda host, port: [PUBLIC], **kwargs))


AUDD_HIT = {"status": "success", "result": {"title": "Test Song", "artist": "Test Artist", "album": "Test Album"}}


def test_audd_uploads_only_the_selected_window_to_the_audd_host():
    catalog = Catalog(AUDD_HIT)
    out = lookup(catalog, source(seconds=20), begin_seconds=5, seconds=8)
    [request] = catalog.seen
    assert request.method == "POST" and request.host == "api.audd.io" and PUBLIC in request.url
    # exactly 8 s of 16 kHz mono PCM16 went out, as a WAV, with the owner's token in the form
    assert (8 * 16000 * 2).to_bytes(4, "little") in request.body and b"RIFF" in request.body
    assert KEY.encode() in request.body
    assert out["status"] == "match"
    assert out["candidates"] == [{"song": "Test Song by Test Artist (album: Test Album)", "score": None}]
    assert "AudD" in out["sent"] and out["seconds"] == 8 and out["start_seconds"] == 5
    assert KEY not in json.dumps(out)


@pytest.mark.parametrize("changes, error", [
    ({"cfg": settings(on=False)}, PermissionError),
    ({"consent": False}, PermissionError),
    ({"consent": "yes"}, PermissionError),
    ({"seconds": 13}, ValueError),                       # AudD takes at most 12 s
    ({"begin_seconds": 17}, ValueError),                 # fewer than 4 s left
    ({"src": source(sample=b"\x00\x00")}, ValueError),   # silence
])
def test_nothing_is_sent_without_the_setting_consent_and_a_usable_clip(changes, error):
    catalog = Catalog(AUDD_HIT)
    with pytest.raises(error):
        lookup(catalog, **changes)
    assert catalog.seen == []


def test_missing_key_or_fpcalc_is_a_clear_result_and_sends_nothing(monkeypatch, tmp_path):
    catalog = Catalog(AUDD_HIT)
    assert lookup(catalog, key_for=lambda name: None)["status"] == "not_configured"
    monkeypatch.setattr(music.shutil, "which", lambda name: None)
    out = lookup(catalog, provider="acoustid")
    assert out["status"] == "not_installed" and "fpcalc" in out["note"]
    # a Settings path that is not fpcalc is not run
    other = tmp_path / "notepad.exe"
    other.write_bytes(b"x")
    assert lookup(catalog, provider="acoustid", cfg=settings(fpcalc_path=str(other)))["status"] == "not_installed"
    assert catalog.seen == []


def test_acoustid_sends_only_the_fingerprint(monkeypatch, tmp_path):
    fpcalc = tmp_path / "fpcalc.exe"
    fpcalc.write_bytes(b"fake")
    ran = []

    def fake_run(command, **kwargs):
        ran.append(command)
        clip = Path(command[-1]).read_bytes()
        assert clip[:4] == b"RIFF" and len(clip) == 44 + 30 * 16000 * 2
        return SimpleNamespace(returncode=0, stdout=json.dumps({"fingerprint": "AQAAfingerprint", "duration": 30}).encode())
    monkeypatch.setattr(music.subprocess, "run", fake_run)
    catalog = Catalog({"status": "ok", "results": [
        {"score": 0.42, "recordings": [{"title": "Second", "artists": [{"name": "B"}]}]},
        {"score": 0.97, "recordings": [{"title": "First", "artists": [{"name": "A", "joinphrase": " & "}, {"name": "C"}]}]},
        {"score": 2, "recordings": [{"title": "Bad score", "artists": [{"name": "X"}]}]},
    ]})
    out = lookup(catalog, source(seconds=40), provider="acoustid", cfg=settings(fpcalc_path=str(fpcalc)))
    assert ran and ran[0][0] == str(fpcalc)
    [request] = catalog.seen
    assert request.host == "api.acoustid.org" and b"RIFF" not in request.body
    assert b"fingerprint=AQAAfingerprint" in request.body and b"duration=30" in request.body
    assert [c["song"] for c in out["candidates"]] == ["First by A & C", "Second by B"]
    assert out["candidates"][0]["score"] == 0.97 and "stays on this PC" in out["sent"]


@pytest.mark.parametrize("reply, status, message", [
    ({"status": "error", "error": {"error_code": 901, "error_message": "x"}}, 200, "error 901"),
    ({}, 401, "HTTP 401"),
])
def test_catalog_failures_are_reported_without_the_key(reply, status, message):
    with pytest.raises(music.LookupFailed, match=message) as caught:
        lookup(Catalog(reply, status))
    assert KEY not in str(caught.value)


def test_an_empty_audd_answer_is_no_match():
    assert lookup(Catalog({"status": "success", "result": None}))["status"] == "no_match"


def test_chat_tool_does_one_lookup_of_the_approved_attachment(tmp_path):
    clip = tmp_path / "song.wav"
    clip.write_bytes(wav())
    catalog = Catalog(AUDD_HIT)
    tool = music.ChatSongLookup(clip, "audd", settings(), key_for=keys, transport=catalog.transport(),
                                resolver=lambda host, port: [PUBLIC])
    name = music.TOOL["name"]
    with pytest.raises(PermissionError):
        asyncio.run(tool.call(name, {}, enabled=set()))
    with pytest.raises(ValueError):
        asyncio.run(tool.call(name, {"path": "C:/other.wav"}, enabled={name}))
    assert asyncio.run(tool.call(name, {}, enabled={name}))["status"] == "match"
    with pytest.raises(PermissionError, match="One song lookup"):
        asyncio.run(tool.call(name, {}, enabled={name}))
    assert len(catalog.seen) == 1


def reply(*, text=None, calls=None):
    return SimpleNamespace(model="offline", choices=[SimpleNamespace(
        message=SimpleNamespace(content=text, tool_calls=calls), finish_reason="tool_calls" if calls else "stop")])


class Models:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []

    async def create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs, default=str)))
        return self.responses.pop(0) if self.responses else reply(text="done")


class Client:
    def __init__(self, models):
        self.chat = SimpleNamespace(completions=models)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


def test_agent_offers_and_runs_the_tool_only_with_an_approval(tmp_path):
    clip = tmp_path / "song.wav"
    clip.write_bytes(wav())
    catalog = Catalog(AUDD_HIT)
    tool = music.ChatSongLookup(clip, "audd", settings(), key_for=keys, transport=catalog.transport(),
                                resolver=lambda host, port: [PUBLIC])
    use = SimpleNamespace(id="c1", function=SimpleNamespace(name="star_identify_song", arguments="{}"))
    models = Models([reply(calls=[use]), reply(text="It is Test Song.")])
    asyncio.run(agent.execute(client=Client(models), model="offline", prompt="What song is this?", image_paths=[],
                              song_lookup=tool, now=""))
    assert "star_identify_song" in {t["function"]["name"] for t in models.requests[0]["tools"]}
    tool_reply = [m["content"] for m in models.requests[1]["messages"] if m["role"] == "tool"][0]
    assert "Test Song by Test Artist" in tool_reply and KEY not in tool_reply
    # Without an approval the tool is not offered and a call to it is refused.
    models = Models([reply(calls=[use])])
    asyncio.run(agent.execute(client=Client(models), model="offline", prompt="What song is this?", image_paths=[],
                              now=""))
    assert "star_identify_song" not in {t["function"]["name"] for t in models.requests[0].get("tools", [])}
    assert len(catalog.seen) == 1


def test_composer_approval_is_checked_on_the_desktop_side(tmp_path):
    files = [str(tmp_path / "song.wav"), str(tmp_path / "notes.txt")]
    selected = [Path(f) for f in files]
    good = {"provider": "acoustid", "file": files[0], "consent": True}
    assert song_lookup_request(None, files, selected, settings(on=False)) is None
    assert song_lookup_request(good, files, selected, settings()) == (selected[0], "acoustid")
    with pytest.raises(PermissionError):
        song_lookup_request(good, files, selected, settings(on=False))
    for bad in ({**good, "consent": False}, {**good, "file": "C:/elsewhere.wav"}, {**good, "provider": "shazam"},
                {**good, "file": files[1]}, {**good, "extra": 1}):
        with pytest.raises(ValueError):
            song_lookup_request(bad, files, selected, settings())


def test_desktop_session_records_only_with_consent_and_never_returns_keys(tmp_path):
    recorded = []

    def record(**kwargs):
        recorded.append(kwargs)
        return source(seconds=12)
    session = music.DesktopSession(record=record)
    catalog = Catalog(AUDD_HIT)
    run = dict(key_for=keys, transport=catalog.transport(), resolver=lambda host, port: [PUBLIC])
    body = {"provider": "audd", "source": "mic", "seconds": 8, "consent": True}
    with pytest.raises(PermissionError):
        session.identify(body, settings(), **run)
    with pytest.raises(PermissionError):
        session.identify({**body, "micConsent": True}, settings(on=False), **run)
    assert recorded == [] and catalog.seen == []
    assert session.identify({**body, "micConsent": True}, settings(), **run)["status"] == "match"
    assert recorded == [{"seconds": 8, "device_index": None}]
    clip = tmp_path / "song.wav"
    clip.write_bytes(wav())
    assert session.choose(clip)["file"] == "song.wav"
    status = session.status(settings(), key_for=keys)
    assert status["audd_key"] is True and status["file"] == "song.wav" and KEY not in json.dumps(status)
    out = session.identify({"provider": "audd", "source": "file", "seconds": 12, "startSeconds": 2, "consent": True},
                           settings(), **run)
    assert out["start_seconds"] == 2 and len(catalog.seen) == 2
