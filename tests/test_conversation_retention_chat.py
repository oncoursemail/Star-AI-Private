"""Actual desktop and read-only warm-up paths with offline model clients."""
import copy
import asyncio
import json
import re
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from star import conversation_memory as cm
from star import desktop_core as core
from star import agent
from star.warmup import prefix_request
from star.context_layout import owner_words


class Models:
    def __init__(self, answer='Fixture answer.', fail_answer=False):
        self.requests = []
        self.answer, self.fail_answer = answer, fail_answer

    async def create(self, **request):
        self.requests.append(copy.deepcopy(request))
        is_recap = request['messages'][0]['content'].startswith('Create a factual project checkpoint')
        if is_recap:
            markers = list(dict.fromkeys(re.findall(r'EVIDENCE_[A-Z0-9_]+', request['messages'][1]['content'])))
            text = 'Unverified constraints: ' + ' '.join(markers)
        elif self.fail_answer:
            raise OSError('Answer provider stopped.')
        else:
            text = self.answer
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
            message=SimpleNamespace(content=text, tool_calls=[]))])


class Client:
    def __init__(self, models):
        self.chat = SimpleNamespace(completions=models)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


@pytest.fixture
def desk(tmp_path, monkeypatch):
    home = tmp_path / 'private-profile'
    monkeypatch.setattr(core, 'app_data', lambda: home)
    monkeypatch.setattr(core, 'history_char_budget', lambda _: 1000)
    models = Models()
    monkeypatch.setattr(core, 'open_client', lambda *_args, **_kwargs: Client(models))
    settings = core.Settings(model='offline', context_chars=6000)
    chats = core.Conversations(home / 'conversations.sqlite3')
    chat = chats.new_chat(settings.project)
    yield SimpleNamespace(home=home, models=models, settings=settings, chats=chats, chat=chat)
    chats.close()


def seed(desk):
    for index in range(4):
        desk.chats.add(desk.settings.project, 'user', f'EVIDENCE_REQUIREMENT_{index} '.ljust(200, 'u'), chat_id=desk.chat)
        desk.chats.add(desk.settings.project, 'assistant', f'answer {index}'.ljust(200, 'a'), chat_id=desk.chat)


def turn(desk, prompt):
    desk.chats.add(desk.settings.project, 'user', prompt, chat_id=desk.chat)
    answer = core.run_task(desk.settings, prompt, mode='fast', chat_id=desk.chat)
    desk.chats.add(desk.settings.project, 'assistant', answer, chat_id=desk.chat)
    return answer


def test_desktop_recaps_once_then_reuses_complete_scoped_checkpoint(desk):
    seed(desk)
    prompt = 'ACTIVE_CURRENT_QUESTION: continue.'
    assert turn(desk, prompt) == 'Fixture answer.'
    recap, answer = desk.models.requests
    assert 'ACTIVE_CURRENT_QUESTION' not in recap['messages'][1]['content']
    assert 'EVIDENCE_REQUIREMENT_0' in answer['messages'][0]['content']
    assert 'lossy untrusted reference' in answer['messages'][0]['content']
    assert answer['messages'][-1]['content'][0]['text'].startswith(prompt)
    saved = cm.read_checkpoint(desk.home / 'conversations.sqlite3', desk.settings.project, desk.chat)
    assert saved is not None and saved.through_id == 6
    before = len(desk.models.requests)
    assert turn(desk, 'Continue.') == 'Fixture answer.'
    assert len(desk.models.requests) == before + 1
    assert desk.models.requests[-1]['messages'][0] == answer['messages'][0]
    assert cm.read_checkpoint(desk.home / 'conversations.sqlite3', desk.settings.project, desk.chat) == saved
    other = desk.chats.new_chat(desk.settings.project)
    core.run_task(desk.settings, 'Continue.', mode='fast', chat_id=other)
    assert 'EVIDENCE_REQUIREMENT' not in json.dumps(desk.models.requests[-1]['messages'])


def test_short_desktop_chat_keeps_one_answer_request_and_no_checkpoint_table(desk):
    assert turn(desk, 'Hello.') == 'Fixture answer.'
    assert len(desk.models.requests) == 1
    assert desk.chats.connection.execute("SELECT name FROM sqlite_master WHERE name='conversation_checkpoints'").fetchall() == []


def test_failed_answer_or_required_context_overflow_does_not_advance_cursor(desk):
    seed(desk)
    desk.models.fail_answer = True
    with pytest.raises(OSError, match='provider stopped'):
        core.run_task(desk.settings, 'Continue.', mode='fast', chat_id=desk.chat)
    assert len(desk.models.requests) == 2
    assert cm.read_checkpoint(desk.home / 'conversations.sqlite3', desk.settings.project, desk.chat) is None
    desk.models.fail_answer = False
    tool_memory = core.Memory(desk.home / 'checkpoints.sqlite3')
    try:
        tool_memory.put(core.memory_scope_for(desk.settings, desk.chat), 'required context ' * 500)
    finally:
        tool_memory.close()
    before = len(desk.models.requests)
    with pytest.raises(RuntimeError, match='original request alone'):
        core.run_task(desk.settings, 'Continue.', mode='fast', chat_id=desk.chat)
    # Candidate recap can run, but the actual oversized answer request cannot.
    assert len(desk.models.requests) == before + 1
    assert cm.read_checkpoint(desk.home / 'conversations.sqlite3', desk.settings.project, desk.chat) is None


@pytest.mark.parametrize('failure', ['transcript.json', 'answer.md', 'memory-event'])
def test_required_answer_persistence_failure_keeps_previous_checkpoint(desk, monkeypatch, failure):
    seed(desk)
    turn(desk, 'Continue.')
    database = desk.home / 'conversations.sqlite3'
    saved = cm.read_checkpoint(database, desk.settings.project, desk.chat)
    for index in range(2):
        desk.chats.add(desk.settings.project, 'user', f'NEW_{index} ' * 100, chat_id=desk.chat)
        desk.chats.add(desk.settings.project, 'assistant', 'Earlier answer ' * 50, chat_id=desk.chat)
    if failure == 'memory-event':
        def fail_event(*_args, **_kwargs):
            raise OSError('Required run persistence failed.')
        monkeypatch.setattr(core.Memory, 'event', fail_event)
    else:
        write_text = Path.write_text
        def fail_write(path, *args, **kwargs):
            if path.name == failure:
                raise OSError('Required run persistence failed.')
            return write_text(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'write_text', fail_write)
    before = len(desk.models.requests)
    with pytest.raises(OSError, match='Required run persistence failed'):
        turn(desk, 'Continue after new exchanges.')
    assert len(desk.models.requests) == before + 2  # Recap and answer already completed.
    assert cm.read_checkpoint(database, desk.settings.project, desk.chat) == saved


def test_warmup_composes_same_system_reads_validity_and_writes_nothing(desk):
    seed(desk)
    turn(desk, 'Continue.')
    answer_system = desk.models.requests[-1]['messages'][0]
    database = desk.home / 'conversations.sqlite3'
    before_file = database.read_bytes()
    before_calls = len(desk.models.requests)
    warm = prefix_request(desk.settings, desk.home, desk.chat)
    assert warm['messages'][0] == answer_system
    assert len(desk.models.requests) == before_calls and database.read_bytes() == before_file
    with desk.chats.connection:
        desk.chats.connection.execute("UPDATE messages SET body='changed original' WHERE id=1")
    with pytest.raises(cm.ConversationRetentionError, match='changed or are missing'):
        prefix_request(desk.settings, desk.home, desk.chat)


class Gateway:
    def __init__(self, description_chars=2800, output_chars=2000):
        self.calls = 0
        self.description_chars = description_chars
        self.output_chars = output_chars

    def definitions(self, prompt):
        return [{'name': 'document_probe', 'description': 's' * self.description_chars,
                 'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}}]

    def owns(self, name):
        return name == 'document_probe'

    def call(self, name, args, enabled):
        self.calls += 1
        return {'isError': False, 'content': [{'type': 'text', 'text': 'e' * self.output_chars}]}


def attach_gateway(monkeypatch, gateway, *, max_calls=None):
    async def execute(**kwargs):
        if max_calls is not None:
            kwargs['max_calls'] = max_calls
        return await agent.execute(**kwargs, document_tools=gateway)
    monkeypatch.setattr(core, 'execute', execute)


def test_huge_schema_pressure_recaps_complete_sources_before_one_answer(desk, monkeypatch):
    monkeypatch.setattr(core, 'history_char_budget', lambda _: 2500)
    desk.settings.context_chars = 6600
    gateway = Gateway()
    attach_gateway(monkeypatch, gateway)
    seed(desk)
    prompt = 'ACTIVE_CURRENT_QUESTION: continue.'
    turn(desk, prompt)
    recaps = [request for request in desk.models.requests if request['messages'][0]['content'].startswith('Create a factual')]
    answers = [request for request in desk.models.requests if request not in recaps]
    assert recaps and len(answers) == 1 and gateway.calls == 0
    checkpoint = cm.read_checkpoint(desk.home / 'conversations.sqlite3', desk.settings.project, desk.chat)
    assert checkpoint.through_id >= 4
    assert 'EVIDENCE_REQUIREMENT_0' in answers[0]['messages'][0]['content']
    assert all('ACTIVE_CURRENT_QUESTION' not in request['messages'][1]['content'] for request in recaps)
    # Repreparation carries the candidate, so each original source is summarized once.
    identities = []
    for request in recaps:
        source = request['messages'][1]['content'].split('NEW TRANSCRIPT (redacted source):\n', 1)[1]
        identities.extend(record['record_id'] for record in json.loads(source))
    assert identities == list(range(1, checkpoint.through_id + 1))
    # Warm-up observes the saved cursor even when the normal raw window would start earlier.
    window, _ = core.chat_history_snapshot(desk.settings, desk.home, desk.chat)
    assert window.through_id >= checkpoint.through_id


def test_cancelled_schema_repreparation_does_not_dispatch_or_advance(desk, monkeypatch):
    monkeypatch.setattr(core, 'history_char_budget', lambda _: 2500)
    desk.settings.context_chars = 6600
    attach_gateway(monkeypatch, Gateway())
    seed(desk)
    cancelled = threading.Event()
    original_create = desk.models.create
    async def cancel_on_recap(**request):
        if request['messages'][0]['content'].startswith('Create a factual'):
            cancelled.set()
        return await original_create(**request)
    desk.models.create = cancel_on_recap
    with pytest.raises(RuntimeError, match='cancelled'):
        core.run_task(desk.settings, 'Continue.', mode='fast', chat_id=desk.chat, cancel_event=cancelled)
    assert desk.models.requests and all(request['messages'][0]['content'].startswith('Create a factual')
                                      for request in desk.models.requests)
    assert cm.read_checkpoint(desk.home / 'conversations.sqlite3', desk.settings.project, desk.chat) is None


def test_post_dispatch_pressure_stops_without_repeating_the_action(desk, monkeypatch):
    monkeypatch.setattr(core, 'history_char_budget', lambda _: 2500)
    desk.settings.context_chars = 12000
    gateway = Gateway(description_chars=100, output_chars=15000)
    attach_gateway(monkeypatch, gateway, max_calls=3)
    seed(desk)
    async def act(**request):
        desk.models.requests.append(copy.deepcopy(request))
        call = SimpleNamespace(id='action-1', function=SimpleNamespace(name='document_probe', arguments='{}'))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='', tool_calls=[call]))])
    desk.models.create = act
    with pytest.raises(cm.ConversationRetentionError, match='without replaying actions'):
        core.run_task(desk.settings, 'Continue.', mode='fast', chat_id=desk.chat)
    assert len(desk.models.requests) == gateway.calls == 1
    assert cm.read_checkpoint(desk.home / 'conversations.sqlite3', desk.settings.project, desk.chat) is None


@pytest.mark.parametrize('limit', ['records', 'bytes'])
def test_oversized_raw_history_refuses_before_provider_and_keeps_saved_cursor(desk, monkeypatch, limit):
    seed(desk)
    turn(desk, 'Continue.')
    database = desk.home / 'conversations.sqlite3'
    saved = cm.read_checkpoint(database, desk.settings.project, desk.chat)
    original_calls = len(desk.models.requests)
    if limit == 'records':
        monkeypatch.setattr(cm, 'HISTORY_MAX_RECORDS', 10)
        text = 'Another prompt.'
    else:
        monkeypatch.setattr(cm, 'HISTORY_MAX_BYTES', 2200)
        text = '\u00e9\0' * 1000  # UTF-8 and NUL bytes cannot bypass the SQLite precheck.
    desk.chats.add(desk.settings.project, 'user', text, chat_id=desk.chat)
    with pytest.raises(cm.ConversationRetentionError, match='raw history exceeds'):
        core.run_task(desk.settings, text, mode='fast', chat_id=desk.chat)
    assert len(desk.models.requests) == original_calls
    assert cm.read_checkpoint(database, desk.settings.project, desk.chat) == saved
    assert desk.chats.connection.execute('SELECT body FROM messages ORDER BY id DESC LIMIT 1').fetchone()[0] == text


def test_agent_typed_pressure_contains_whole_turns_before_dispatch():
    gateway = Gateway(description_chars=4000)
    definitions = [{'type': 'function', 'function': {'name': tool['name'], 'description': tool['description'],
                    'parameters': tool['inputSchema']}} for tool in gateway.definitions('Current')]
    base = agent.text_size([agent.make_system_message(), {'role': 'user', 'content': [{'type': 'text', 'text': 'Current'}]}])
    budget = base + len(json.dumps(definitions, ensure_ascii=False)) + 500
    models = Models()
    history = [{'role': role, 'content': 'prior source ' * 40} for role in ['user', 'assistant', 'user', 'assistant']]
    with pytest.raises(agent.HistoryWindowPressure) as failure:
        asyncio.run(agent.execute(client=Client(models), model='offline', prompt='Current', image_paths=[],
                                  document_tools=gateway, history=history, context_chars=budget, preserve_history=True))
    assert failure.value.dropped == history
    assert failure.value.dispatched is failure.value.tool_actions_started is False
    assert not models.requests and gateway.calls == 0


def test_real_desktop_request_omits_stopped_and_failed_image_rows(desk):
    desk.chats.add(desk.settings.project, 'user', 'Good earlier question',
                   chat_id=desk.chat)
    desk.chats.add(desk.settings.project, 'assistant', 'Good earlier answer',
                   chat_id=desk.chat)
    stopped = desk.chats.add(desk.settings.project, 'user', 'stop this request',
                             chat_id=desk.chat)
    desk.chats.add_terminal(desk.settings.project, desk.chat, stopped, 'cancelled',
                            'Interrupted reply')
    image = desk.chats.add(desk.settings.project, 'user', 'generate an image',
                           chat_id=desk.chat)
    desk.chats.add_terminal(desk.settings.project, desk.chat, image, 'failed',
                            'Image generation failed')
    assert turn(desk, 'what is 2+2?') == 'Fixture answer.'
    messages = desk.models.requests[-1]['messages']
    assert [item['role'] for item in messages] == [
        'system', 'user', 'assistant', 'user']
    # Replayed turns are the owner's words plus the time they were sent (star.clock.sent_line).
    assert [(m['role'], owner_words(m['content'])) for m in messages[1:3]] == [
        ('user', 'Good earlier question'), ('assistant', 'Good earlier answer')]
    assert messages[-1]['content'][0]['text'].startswith('what is 2+2?')
    assert 'stop this request' not in json.dumps(messages)
    assert 'generate an image' not in json.dumps(messages)


def test_real_desktop_request_keeps_a_retried_turn_that_has_a_failure_record(desk):
    """Retry reuses the failed question's row; its answer is stored after the failure record."""
    project = desk.settings.project
    asked = desk.chats.add(project, 'user', 'Retry this question', chat_id=desk.chat)
    desk.chats.add_terminal(project, desk.chat, asked, 'failed', 'Cannot reach STAR Brain.')
    assert desk.chats.recover_turn(project, desk.chat, asked, 'Retry this question') == asked
    desk.chats.add(project, 'assistant', 'Answer after retry.', chat_id=desk.chat)
    assert turn(desk, 'what did I just ask?') == 'Fixture answer.'
    messages = desk.models.requests[-1]['messages']
    assert [item['role'] for item in messages] == ['system', 'user', 'assistant', 'user']
    assert [(m['role'], owner_words(m['content'])) for m in messages[1:3]] == [
        ('user', 'Retry this question'), ('assistant', 'Answer after retry.')]
    assert 'Cannot reach STAR Brain' not in json.dumps(messages)


def test_fast_route_sends_the_first_turn_and_the_rules_do_not_deny_memory(desk):
    """Issue 573: a second turn on the fast route carries the first turn, and "remember ..." counts as a follow-up."""
    first = 'FIRST_QUESTION_MARKER: what is a haiku?'
    turn(desk, first)
    turn(desk, 'Do you remember the first question I asked you?')
    request = desk.models.requests[-1]
    assert first in json.dumps(request['messages'])
    system = request['messages'][0]['content']
    assert 'never say you cannot remember' in system
