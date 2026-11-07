"""Exercise the real Bridge.close body even on CI without PySide6.

The nested method's compiled code is used unchanged; only its service dependencies
are faked. These tests are not evidence of a packaged Restart Manager upgrade.
"""
from types import CodeType, FunctionType, SimpleNamespace
import threading

import pytest

import star.react_shell as shell_module
from star.desktop_core import Conversations


def _bridge_close():
    # Bridge is local to launch(). Its close method has no Qt closure, so run
    # that exact production code without constructing a GUI or copying its body.
    code = shell_module.launch.__code__
    for name in ('Bridge', 'close'):
        code = next(item for item in code.co_consts
                    if isinstance(item, CodeType) and item.co_name == name)
    assert not code.co_freevars
    return FunctionType(code, vars(shell_module), 'close')


@pytest.mark.parametrize('platform,frozen', [
    ('nt', True), ('nt', False), ('posix', True), ('posix', False),
])
@pytest.mark.parametrize('running', [False, True], ids=['idle', 'running'])
@pytest.mark.parametrize('voice_seconds', [0.0, 2.0], ids=['quick-voice', 'slow-voice'])
def test_real_close_cleans_children_before_watchdog(
        monkeypatch, tmp_path, platform, frozen, running, voice_seconds):
    close = _bridge_close()
    database = tmp_path / 'conversations.sqlite3'
    chats = Conversations(database)
    try:
        chat_id = chats.active_chat('default')
        user_id = chats.add('default', 'user', 'A test turn', chat_id=chat_id)
        if not running:
            chats.add('default', 'assistant', 'Already complete', chat_id=chat_id)
    finally:
        chats.close()

    def records():
        chats = Conversations(database)
        try:
            return chats.recent_records('default', limit=20, chat_id=chat_id)
        finally:
            chats.close()

    before = records()
    events = []
    stopped = set()
    timers = []
    now = [0.0]
    cancellation = threading.Event()
    bridge = SimpleNamespace(
        _closing=False, cancel_chat=cancellation, bulk_lock=threading.RLock(), bulk_tasks=None,
        turn=shell_module.TurnRef('default', chat_id, user_id) if running else None,
    )
    record_failure = shell_module.record_turn_failure

    def record(home, turn, status, detail):
        assert cancellation.is_set()
        assert bridge._closing
        assert record_failure(home, turn, status, detail)
        events.append('cancelled.saved')
        return True

    def advance(seconds):
        now[0] += seconds
        for timer in timers:
            if timer.deadline is not None and not timer.fired and now[0] >= timer.deadline:
                timer.fired = True
                timer.callback()

    def exited(code):
        assert code == 0
        assert stopped == {'comfy', 'warmer', 'runtime'}
        events.append('exit')

    class Timer:
        def __init__(self, interval, callback):
            # Construction itself must follow cleanup, not just Timer.start().
            assert stopped == {'comfy', 'warmer', 'runtime'}
            assert interval == 1.8
            self.interval = interval
            self.callback = callback
            self.daemon = False
            self.deadline = None
            self.fired = False
            timers.append(self)
            events.append('timer.created')

        def start(self):
            assert self.daemon is True
            assert now[0] == 18.0
            self.deadline = now[0] + self.interval
            events.append('timer.started')

    def cleanup(name, seconds=0.0):
        assert cancellation.is_set()
        terminal = [row for row in records() if row['status'] == 'cancelled']
        assert len(terminal) == int(running)
        events.append(name + '.start')
        if name == 'comfy':
            # A second close while cleanup is in progress must also be harmless.
            close(bridge)
        advance(seconds)
        stopped.add(name)
        events.append(name + '.done')

    def close_voice():
        assert stopped == {'comfy', 'warmer', 'runtime'}
        events.append('voice.start')
        advance(voice_seconds)
        events.append('voice.done')

    def shutdown(*, wait, cancel_futures):
        assert wait is False
        assert cancel_futures is True
        events.append('pool.shutdown')

    bridge.comfy_launcher = SimpleNamespace(stop=lambda: cleanup('comfy', 8.0))
    bridge.warmer = SimpleNamespace(cancel=lambda: cleanup('warmer'))
    bridge.draft_warmer = SimpleNamespace(cancel=lambda: None)
    bridge.runtime = SimpleNamespace(stop=lambda: cleanup('runtime', 10.0))
    bridge.voice = SimpleNamespace(close=close_voice)
    bridge.discord = SimpleNamespace(close=lambda: events.append('discord.close'))
    research_stops = []
    # The hourly research-watch timer is stopped once, before any child process is cleaned up.
    bridge.research_timer = SimpleNamespace(stop=lambda: research_stops.append(list(events)))
    bridge.pool = SimpleNamespace(shutdown=shutdown)
    monkeypatch.setattr(shell_module, 'app_data', lambda: tmp_path)
    monkeypatch.setattr(shell_module, 'record_turn_failure', record)
    # Do not mutate the process-wide os.name, sys.frozen or threading.Timer.
    monkeypatch.setattr(shell_module, 'os', SimpleNamespace(name=platform, _exit=exited))
    monkeypatch.setattr(shell_module, 'sys', SimpleNamespace(frozen=frozen))
    monkeypatch.setattr(shell_module, 'threading', SimpleNamespace(Timer=Timer))

    close(bridge)
    packaged_windows = platform == 'nt' and frozen
    expected = ['cancelled.saved'] if running else []
    expected += ['comfy.start', 'comfy.done', 'discord.close', 'warmer.start', 'warmer.done',
                 'runtime.start', 'runtime.done']
    if packaged_windows:
        expected += ['timer.created', 'timer.started']
    expected += ['voice.start']
    if packaged_windows and voice_seconds >= 1.8:
        expected += ['exit']
    expected += ['voice.done', 'pool.shutdown']
    assert events == expected
    assert bridge._closing and cancellation.is_set()
    assert len(timers) == int(packaged_windows)
    assert research_stops == [[]]

    saved = records()
    close(bridge)
    assert events == expected
    assert records() == saved
    if running:
        terminal = [row for row in saved if row['status'] == 'cancelled']
        assert len(terminal) == 1
        assert not any(row['role'] == 'assistant' and row['status'] == 'complete'
                       for row in saved)
    else:
        assert saved == before
