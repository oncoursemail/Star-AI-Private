"""star.inner is reached from the social chat (card + recall note in the user message) and from STAR Home's loop (night)."""
from __future__ import annotations

import types

import pytest

import star.inner
from star.home import loop
from star.inner import night
from star.social.chat import SocialChat
from star.social.friends import FriendMemory


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def memory(tmp_path):
    mem = FriendMemory(tmp_path / "friends.sqlite3")
    yield mem
    mem.close()


def test_chat_puts_the_inner_card_and_note_in_the_user_message_and_marks_them_used(memory, monkeypatch):
    used = []
    ctx = types.SimpleNamespace(card="Mira: loves horror games, cat Miso.", note="(maybe useful: she beat the boss)",
                                done=lambda: used.append(True))
    monkeypatch.setattr(star.inner, "turn_context", lambda *a, **k: ctx)
    calls = []
    chat = SocialChat(memory, complete=lambda system, user: calls.append((system, user)) or "nice!",
                      emotion=None, clock=Clock())
    chat.handle("discord", "Mira", "guess what happened today")
    system, user = calls[-1]
    assert "Miso" not in system                                    # the system prompt stays the same for everyone
    assert user.startswith("Mira: loves horror games") and user.rstrip().endswith("(maybe useful: she beat the boss)")
    assert used == [True]


def test_chat_without_inner_context_keeps_friend_memory(memory, monkeypatch):
    monkeypatch.setattr(star.inner, "turn_context", lambda *a, **k: types.SimpleNamespace(card="", note="",
                                                                                        done=lambda: None))
    calls = []
    chat = SocialChat(memory, complete=lambda system, user: calls.append((system, user)) or "ok", emotion=None,
                      clock=Clock())
    chat.handle("discord", "Jon", "My cat is called Miso.")
    chat.handle("discord", "Jon", "what was my cat called?")
    assert "Miso" in calls[-1][1]


def test_home_loop_runs_her_night_tick_each_cycle_and_survives_errors(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(night, "tick", lambda **kw: seen.append(kw) or {})
    loop._inner_tick(tmp_path, None)
    assert seen and seen[0]["life_home"] == tmp_path

    def broken(**kw):
        raise RuntimeError("disk full")
    monkeypatch.setattr(night, "tick", broken)
    loop._inner_tick(tmp_path, None)                               # logged, never raised
