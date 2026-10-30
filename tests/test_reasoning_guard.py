"""Issue 573: a thinking model on the quick route must not show its reasoning or loop (star/reasoning_guard.py)."""
import asyncio
from types import SimpleNamespace

import pytest

from star import reasoning_guard as guard
from star.agent import read_stream, system_prefix


def stream_of(*texts):
    async def make():
        for text in texts:
            yield SimpleNamespace(model='m', usage=None, choices=[SimpleNamespace(
                finish_reason=None, delta=SimpleNamespace(content=text, tool_calls=None))])
    return make()


def read(*texts, guarded=True):
    shown = []
    result = asyncio.run(read_stream(stream_of(*texts), shown.append, guard=guarded))
    return result[0], ''.join(e['text'] for e in shown if e.get('event') == 'assistant_delta')


def test_think_blocks_are_never_part_of_the_answer():
    text, shown = read('<think>We need to add', ' these numbers</think>', 'The sum is 19.')
    assert text == shown == 'The sum is 19.'
    assert guard.strip_think('<think>unfinished reasoning') == ''


def test_a_reply_that_opens_as_reasoning_is_stopped_before_anything_is_shown():
    with pytest.raises(guard.ReasoningLoop):
        read('We need to solve this expression. Could be scientific notation...')


def test_a_loop_is_cut_where_it_began_and_the_loop_text_is_not_shown_whole():
    answer = 'The result is about 21349120. Alternatively it could be read as 100 and a half. '
    looping = ('Alternatively, maybe they meant something else. ' * 2) + 'Could be a typo. '
    text, shown = read(answer[:40], answer[40:], looping)
    assert text.startswith('The result is about 21349120.') and 'Could be a typo' not in text
    assert shown == text


def test_a_normal_answer_passes_untouched_and_unguarded_reading_keeps_old_behaviour():
    assert read('Hello there, how can I help?') == ('Hello there, how can I help?',) * 2
    assert read('We need to solve this expression. Could be it.', guarded=False)[0].startswith('We need to solve')


def test_plain_chat_rules_do_not_deny_memory():
    assert 'never say you cannot remember' in system_prefix(tools_attached=False)


def test_the_quick_model_that_reasons_aloud_hands_the_turn_to_the_main_model(tmp_path, monkeypatch):
    from star import desktop_core as core, providers
    asked = []

    class Models:
        async def create(self, **request):
            asked.append(request['model'])
            if request['model'] == 'star-voice':
                return stream_of('We need to solve this expression. Alternatively it could be scientific notation.')
            return stream_of('The answer is 42.')

    class Client:
        chat = SimpleNamespace(completions=Models())

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False
    home = tmp_path / 'profile'
    monkeypatch.setattr(core, 'app_data', lambda: home)
    monkeypatch.setattr(core, 'open_client', lambda *_a, **_k: Client())
    # This test exercises model handoff, not credential storage. Mock only the
    # LAN provider's credential lookup; never depend on a real CI secret.
    monkeypatch.setattr(providers, 'get_api_key',
                        lambda name: 'offline-test-token' if name == providers.STAR_SERVER else None)
    settings = core.Settings(model='star-main', fast_model='star-voice', reasoning_model='star-main', provider='star_server',
                             server_endpoint='http://192.168.1.20:8080/v1', knowledge_endpoint='off')  # star:allow
    monkeypatch.setattr(core, 'model_slots_full', lambda *_a, **_k: asyncio.sleep(0, False))
    answer = core.run_task(settings, 'Say hello to me in a pleasant way', mode='fast', stream_tokens=True)
    assert answer == 'The answer is 42.' and asked == ['star-voice', 'star-main']
