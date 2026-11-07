"""The shared background cap on star-fast (docs/agents/chat-slot-20261020.md)."""
from __future__ import annotations

import io
import json

import pytest

from star import background_cap as cap


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def slots(*busy: bool) -> list[dict]:
    return [{"id": i, "is_processing": b} for i, b in enumerate(busy)]


def test_background_never_gets_slot_zero_and_at_most_two_slots(monkeypatch):
    monkeypatch.delenv("STAR_BACKGROUND_SLOTS", raising=False)
    assert cap.background_slots(1) == []
    assert cap.background_slots(2) == [1]
    assert cap.background_slots(3) == [1, 2]
    assert cap.background_slots(6) == [1, 2]
    monkeypatch.setenv("STAR_BACKGROUND_SLOTS", "3")
    assert cap.background_slots(6) == [1, 2, 3]


def test_choose_prefers_an_idle_background_slot_else_queues_on_the_first():
    assert cap.choose(slots(False, False, False)) == 1
    assert cap.choose(slots(False, True, False)) == 2
    assert cap.choose(slots(True, True, False)) == 2
    # both background slots busy: name slot 1 and wait in the server's queue; slot 0 stays free for chat
    assert cap.choose(slots(False, True, True)) == 1
    assert cap.choose(slots(False, True)) == 1
    assert cap.choose(slots(False)) is None
    assert cap.choose({"error": "x"}) is None


def test_slot_for_asks_the_server_with_the_key_and_falls_back_to_slot_one():
    seen = {}

    def opener(request, timeout):
        seen["url"], seen["auth"] = request.full_url, request.headers.get("Authorization")
        return Reply(json.dumps(slots(False, True, False)).encode())

    assert cap.slot_for("http://brain:8080/", "k", "star-fast", opener=opener) == 2
    assert seen == {"url": "http://brain:8080/slots?model=star-fast", "auth": "Bearer k"}

    def broken(request, timeout):
        raise OSError("refused")
    assert cap.slot_for("http://brain:8080", "k", "star-vision", opener=broken) == cap.FALLBACK_SLOT == 1
    single = lambda request, timeout: Reply(json.dumps(slots(False)).encode())
    assert cap.slot_for("http://brain:8080", "k", "star-fast", opener=single) is None


@pytest.mark.parametrize("model", ["star-voice", "star-quick", "star-deep", ""])
def test_other_models_are_not_capped(model):
    def opener(request, timeout):
        raise AssertionError("no probe for an uncapped model")
    assert cap.slot_for("http://brain:8080", "k", model, opener=opener) is None


def test_process_flag(monkeypatch):
    monkeypatch.delenv("STAR_BACKGROUND_WORK", raising=False)
    assert not cap.process_is_background()
    monkeypatch.setenv("STAR_BACKGROUND_WORK", "1")
    assert cap.process_is_background()


# ------------------------------------------------------------------ the background clients name a background slot

def brain_opener(seen: list, report: list, answer: dict):
    """A fake brain: GET /slots answers `report`, POST /v1/chat/completions answers `answer`."""
    def opener(request, timeout):
        if request.get_method() == "GET":
            seen.append(("GET", request.full_url))
            return Reply(json.dumps(report).encode())
        seen.append(("POST", json.loads(request.data)))
        return Reply(json.dumps(answer).encode())
    return opener


CHAT = {"choices": [{"message": {"content": '{"defects": [], "looks_ok": true}'}}], "usage": {}}


def test_playtest_brain_names_an_idle_background_slot(tmp_path):
    from star import playtest_learning as pl
    key = tmp_path / "key"
    key.write_text("k\n", encoding="utf-8")
    seen: list = []
    brain = pl.Brain("http://brain:8080", key_file=str(key), opener=brain_opener(seen, slots(True, True, False), CHAT))
    assert brain([{"role": "user", "content": "x"}])["ok"]
    assert seen[0] == ("GET", "http://brain:8080/slots?model=star-fast") and seen[1][1]["id_slot"] == 2

    seen.clear()
    quick = pl.Brain("http://brain:8080", key_file=str(key), model="star-quick",
                     opener=brain_opener(seen, slots(False, False), CHAT))
    assert quick([{"role": "user", "content": "x"}])["ok"]
    assert [s[0] for s in seen] == ["POST"] and "id_slot" not in seen[0][1]


def test_studio_lab_critic_names_a_background_slot(tmp_path):
    from star import studio_lab
    key = tmp_path / "key"
    key.write_text("k\n", encoding="utf-8")
    seen: list = []
    critic = studio_lab.BrainCritic("http://brain:8080", key_file=str(key),
                                    opener=brain_opener(seen, slots(False, True, True), CHAT))
    assert critic([("a", b"x", "image/png")], "s")["ok"]
    assert seen[0] == ("GET", "http://brain:8080/slots?model=star-vision") and seen[1][1]["id_slot"] == 1


def test_a_background_process_pins_every_star_fast_request_to_a_background_slot(monkeypatch):
    from star.desktop_core import Settings
    from star.providers import llama_request_fields, remember_server_limits
    endpoint = "http://192.168.50.21:8080/v1"      # a made-up LAN address (star:allow)
    lan = Settings(provider="star_server", server_endpoint=endpoint, model="star-fast")
    remember_server_limits(endpoint, "star-fast", 98304, 3)
    remember_server_limits(endpoint, "star-voice", 32768, 2)
    monkeypatch.setenv("STAR_BACKGROUND_WORK", "1")
    for kwargs in ({"conversation": "STAR::chat::a"}, {"conversation": "x", "background": True}, {}):
        assert llama_request_fields(lan, model="star-fast", **kwargs)["id_slot"] == 2
    assert "id_slot" not in llama_request_fields(lan, model="star-voice", background=True)
    monkeypatch.delenv("STAR_BACKGROUND_WORK")
    assert "id_slot" not in llama_request_fields(lan, model="star-fast", background=True)


def test_the_eval_runner_marks_its_process_as_background(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from star import eval_runner
    monkeypatch.setenv("STAR_BACKGROUND_WORK", "0")
    monkeypatch.delenv("STAR_EVAL_SERVER", raising=False)
    monkeypatch.setenv("STAR_SERVER_API_KEY", "")
    monkeypatch.setenv("STAR_SKILL_PACKS", "")
    key = tmp_path / "key"
    key.write_text("k\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        eval_runner.build_real(SimpleNamespace(key_file=str(key), packs="", server=""))
    assert cap.process_is_background()
