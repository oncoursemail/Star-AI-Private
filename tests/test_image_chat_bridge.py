"""Run the real Qt bridge methods for chat pictures (no Qt window, no GPU, no network).

`Bridge` lives inside `launch()` and cannot be built without PySide6, so its methods are compiled from
the source and run against the live `star.react_shell` module: `monkeypatch.setattr(shell, ...)` then
reaches them. (Compiling against a copy of the module's names would let the real model provider or the
real ComfyUI client run, which is what failed in CI.)
"""
import ast
import inspect
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from star import media_actions
from star import react_shell as shell
from star.chat_images import PREFIX, latest_generated_path
from star.desktop_core import Conversations, Settings

DOG = 'Generate an image of a dog'


def bridge_class():
    tree = ast.parse(inspect.getsource(shell.launch))
    bridge = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == 'Bridge')
    names = {'_run_chat', '_run_image', 'invoke'}
    methods = [n for n in bridge.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in methods} == names
    for method in methods:
        method.decorator_list = []                       # @Slot is a Qt name that exists only inside launch()
    cls = ast.ClassDef(name='BridgeUnderTest', bases=[], keywords=[], body=methods, decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    namespace = vars(shell)                              # the live module: patches made by a test are seen
    exec(compile(module, str(Path(shell.__file__)), 'exec'), namespace)
    return namespace.pop('BridgeUnderTest')


def host(tmp_path, monkeypatch, **changes):
    monkeypatch.setattr(shell, 'app_data', lambda: tmp_path)
    # Never find the ComfyUI of the PC the tests run on: a test that wants a found folder says so.
    monkeypatch.setattr(media_actions, 'detect_comfy_home', lambda: '')
    settings_file = tmp_path / 'settings.json'
    settings = Settings()
    settings.model = 'test-model'
    for name, value in changes.items():
        setattr(settings, name, value)
    settings.save(settings_file)
    instance = bridge_class()()
    instance.settings_file = settings_file
    instance.cancel_chat = threading.Event()
    instance.turn = None
    instance.active_task = False
    instance.allowed_files = set()
    instance.warmer = Mock()
    instance.draft_warmer = Mock()
    instance.digester = Mock()
    instance._emit = Mock()
    instance._warm = Mock()
    instance._digest_when_idle = Mock()
    instance.comfy_launcher = SimpleNamespace(start=Mock())

    def run_now(request_id, action, worker):             # the pool, but in this thread
        try:
            shell.run_worker(request_id, action, worker, emit=instance._emit, home=tmp_path,
                             current_turn=lambda: instance.turn, cancelled=instance.cancel_chat.is_set,
                             settings_file=settings_file)
        finally:
            instance.turn = None
            instance.active_task = False
    instance._run = run_now
    return instance


def ask(instance, **body):
    reply = json.loads(instance.invoke(json.dumps({'action': 'generateImage', 'requestId': 'request', **body})))
    return reply


def emitted(instance, kind):
    return [call.args[2] for call in instance._emit.call_args_list if call.args[1] == kind]


def rows(tmp_path):
    chats = Conversations(tmp_path / 'conversations.sqlite3')
    try:
        project = Settings.load(tmp_path / 'settings.json').project
        return chats.recent_records(project, chat_id=chats.active_chat(project))
    finally:
        chats.close()


def retry_state(tmp_path):
    chats = Conversations(tmp_path / 'conversations.sqlite3')
    try:
        project = Settings.load(tmp_path / 'settings.json').project
        return chats.retry_state(project, chats.active_chat(project))
    finally:
        chats.close()


def saved_picture(tmp_path, name='picture.png', answered_with=None):
    """A picture on disk and, in the active chat, the answer that points at it."""
    folder = tmp_path / 'generated-images'
    folder.mkdir(exist_ok=True)
    (folder / name).write_bytes(b'png bytes')
    chats = Conversations(tmp_path / 'conversations.sqlite3')
    try:
        project = Settings.load(tmp_path / 'settings.json').project
        chats.add(project, 'assistant', answered_with or PREFIX + name, chat_id=chats.active_chat(project))
    finally:
        chats.close()
    return (folder / name).resolve()


def made(name='made.png'):
    return Mock(return_value={'answer': 'Created', 'image': 'data:image/png;base64,AA==', 'message': PREFIX + name})


def fake_chat_turn(monkeypatch, provider):
    monkeypatch.setattr(shell, 'run_task', provider)
    monkeypatch.setattr(shell, 'provider_kind', lambda settings: 'local')
    monkeypatch.setattr(shell, 'prepare_turn', lambda *a, **kw: SimpleNamespace(
        pictures=[], documents=[], footer='', prompt=lambda text: text))


# --- the ordinary chat path (_run_chat) -------------------------------------------------------------

def test_real_run_chat_plain_message_uses_the_provider_with_the_typed_text(tmp_path, monkeypatch):
    instance = host(tmp_path, monkeypatch)
    provider = Mock(return_value='A normal reply')
    fake_chat_turn(monkeypatch, provider)
    result = instance._run_chat('request', 'Hello STAR', [])
    assert result['answer'] == 'A normal reply'
    provider.assert_called_once()
    assert provider.call_args.args[1] == 'Hello STAR'
    assert [(row['role'], row['body']) for row in rows(tmp_path)][-2:] == [
        ('user', 'Hello STAR'), ('assistant', 'A normal reply')]


def test_capability_sentence_is_added_to_the_prompt_only_when_the_setting_is_on(tmp_path, monkeypatch):
    provider = Mock(return_value='ok')
    fake_chat_turn(monkeypatch, provider)
    host(tmp_path, monkeypatch)._run_chat('request', 'Hello STAR', [])
    assert provider.call_args.args[1] == 'Hello STAR'
    provider.reset_mock()
    host(tmp_path, monkeypatch, session_capabilities_prompt=True)._run_chat('request', 'Hello STAR', [])
    prompt = provider.call_args.args[1]
    assert prompt.startswith('Session capabilities:') and prompt.endswith('Hello STAR')


# --- a picture request (_run_image) -----------------------------------------------------------------

def test_real_run_image_starts_engine_and_stores_the_typed_words(tmp_path, monkeypatch):
    instance = host(tmp_path, monkeypatch, comfy_home=str(tmp_path))
    monkeypatch.setattr(shell.image_gen, 'status', lambda settings: {'running': False})
    generator = made('picture.png')
    monkeypatch.setattr(shell, 'generate_chat_image', generator)
    result = instance._run_image('request', 'a dog', display_prompt=DOG)
    assert result['answer'] == 'Created'
    instance.comfy_launcher.start.assert_called_once()
    generator.assert_called_once()
    assert generator.call_args.args[1] == 'a dog'                 # the picture model gets the subject only
    assert any('Starting the image engine' in str(c) for c in instance._emit.call_args_list)
    assert [(r['role'], r['body']) for r in rows(tmp_path)][-2:] == [
        ('user', DOG), ('assistant', PREFIX + 'picture.png')]


def test_no_engine_and_no_folder_fails_clearly_and_keeps_the_question_for_retry(tmp_path, monkeypatch):
    instance = host(tmp_path, monkeypatch)
    monkeypatch.setattr(shell.image_gen, 'status', lambda settings: {'running': False})
    generator = Mock(side_effect=AssertionError('the picture engine must not be called'))
    monkeypatch.setattr(shell, 'generate_chat_image', generator)
    reply = ask(instance, prompt='a dog', display_prompt=DOG)
    assert reply['ok'] is True
    [detail] = emitted(instance, 'error')
    assert emitted(instance, 'result') == []
    assert 'ComfyUI' in detail and 'not running' in detail and 'Where STAR generates' in detail
    instance.comfy_launcher.start.assert_not_called()
    generator.assert_not_called()
    state = retry_state(tmp_path)
    assert state['status'] == 'failed' and state['prompt'] == DOG and state['detail'] == detail
    assert [row['role'] for row in rows(tmp_path)] == ['user', 'event']      # no invented answer


def test_a_folder_found_on_its_own_is_used_when_none_is_chosen(tmp_path, monkeypatch):
    instance = host(tmp_path, monkeypatch)
    monkeypatch.setattr(media_actions, 'detect_comfy_home', lambda: str(tmp_path))
    monkeypatch.setattr(shell.image_gen, 'status', lambda settings: {'running': False})
    monkeypatch.setattr(shell, 'generate_chat_image', made('found.png'))
    result = instance._run_image('request', 'a dog', display_prompt=DOG)
    assert result['answer'] == 'Created'
    instance.comfy_launcher.start.assert_called_once()


def test_a_place_that_cannot_make_pictures_fails_before_anything_is_started(tmp_path, monkeypatch):
    instance = host(tmp_path, monkeypatch, comfy_home=str(tmp_path), media_images='servers')
    status = Mock(return_value={'running': False})
    monkeypatch.setattr(shell.image_gen, 'status', status)
    monkeypatch.setattr(shell, 'generate_chat_image', Mock(side_effect=AssertionError('engine called')))
    ask(instance, prompt='a dog', display_prompt=DOG)
    [detail] = emitted(instance, 'error')
    assert 'Images is set to' in detail and 'STAR Brains' in detail
    instance.comfy_launcher.start.assert_not_called()
    status.assert_not_called()


def test_real_run_image_followup_reuses_saved_picture(tmp_path, monkeypatch):
    instance = host(tmp_path, monkeypatch)
    monkeypatch.setattr(shell.image_gen, 'status', lambda settings: {'running': True})
    path = saved_picture(tmp_path)
    generator = made('edited.png')
    monkeypatch.setattr(shell, 'generate_chat_image', generator)
    result = instance._run_image('request', 'make it brown', followup=True)
    assert result['answer'] == 'Created'
    assert generator.call_args.kwargs['source'] == path


@pytest.mark.parametrize('later_answer', [None, 'A text answer about something else.'])
def test_followup_without_a_picture_just_before_it_fails_instead_of_editing_an_old_one(tmp_path, monkeypatch, later_answer):
    instance = host(tmp_path, monkeypatch)
    monkeypatch.setattr(shell.image_gen, 'status', lambda settings: {'running': True})
    generator = Mock(side_effect=AssertionError('engine called'))
    monkeypatch.setattr(shell, 'generate_chat_image', generator)
    if later_answer:
        saved_picture(tmp_path)
        saved_picture(tmp_path, name='unused.png', answered_with=later_answer)
    ask(instance, prompt='make it brown', followup=True)
    [detail] = emitted(instance, 'error')
    assert 'previous picture is no longer available' in detail
    generator.assert_not_called()


# --- the request as the page sends it (invoke) ------------------------------------------------------

def test_bad_request_text_is_refused_before_a_turn_starts(tmp_path, monkeypatch):
    instance = host(tmp_path, monkeypatch)
    monkeypatch.setattr(shell, 'generate_chat_image', Mock(side_effect=AssertionError('engine called')))
    for bad in ({'display_prompt': {'text': 'x'}}, {'display_prompt': '   '}, {'display_prompt': 'x' * 1501},
                {'retryMessageId': 'one'}, {'retryMessageId': 0}, {'retryMessageId': True}):
        reply = ask(instance, prompt='a dog', **bad)
        assert reply['ok'] is False, bad
        assert instance.active_task is False
    assert rows(tmp_path) == []


def test_retry_runs_the_same_question_as_a_picture_without_a_second_user_row(tmp_path, monkeypatch):
    instance = host(tmp_path, monkeypatch)
    monkeypatch.setattr(shell.image_gen, 'status', lambda settings: {'running': False})
    ask(instance, prompt='a dog', display_prompt=DOG)                       # fails: no ComfyUI, no folder
    first = retry_state(tmp_path)
    assert first['status'] == 'failed'
    settings = Settings.load(instance.settings_file)
    settings.comfy_home = str(tmp_path)
    settings.save(instance.settings_file)
    monkeypatch.setattr(shell.image_gen, 'status', lambda settings: {'running': True})
    monkeypatch.setattr(shell, 'generate_chat_image', made('dog.png'))
    reply = ask(instance, prompt='a dog', display_prompt=DOG, retryMessageId=first['message_id'])
    assert reply['ok'] is True and len(emitted(instance, 'result')) == 1
    assert [(r['role'], r['body']) for r in rows(tmp_path) if r['role'] != 'event'] == [
        ('user', DOG), ('assistant', PREFIX + 'dog.png')]
    assert retry_state(tmp_path) is None


def test_retry_of_a_question_that_is_no_longer_unanswered_is_refused(tmp_path, monkeypatch):
    instance = host(tmp_path, monkeypatch)
    monkeypatch.setattr(shell.image_gen, 'status', lambda settings: {'running': True})
    monkeypatch.setattr(shell, 'generate_chat_image', made())
    ask(instance, prompt='a dog', display_prompt=DOG)                       # answered
    reply = ask(instance, prompt='a dog', display_prompt=DOG, retryMessageId=1)
    assert reply['ok'] is False and 'no longer available for Retry' in reply['error']
    assert instance.active_task is False


# --- follow-up lookup -------------------------------------------------------------------------------

def test_latest_generated_path_is_only_the_newest_answer_and_only_inside_the_pictures_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(shell, 'app_data', lambda: tmp_path)
    Settings().save(tmp_path / 'settings.json')
    project = Settings().project
    chats = Conversations(tmp_path / 'conversations.sqlite3')
    chat_id = chats.active_chat(project)
    chats.close()
    assert latest_generated_path(tmp_path, project, chat_id) is None
    path = saved_picture(tmp_path)
    assert latest_generated_path(tmp_path, project, chat_id) == path
    saved_picture(tmp_path, name='later.png', answered_with='Plain words.')
    assert latest_generated_path(tmp_path, project, chat_id) is None
    saved_picture(tmp_path, name='ok.png')
    assert latest_generated_path(tmp_path, project, chat_id).name == 'ok.png'
    (tmp_path / 'secret.png').write_bytes(b'x')
    saved_picture(tmp_path, name='ok2.png', answered_with=PREFIX + '../secret.png')
    assert latest_generated_path(tmp_path, project, chat_id) is None


# --- issue 573: a picture request the chat detector missed must not end as "I can't create images" ---------

COW = 'Generate a real cow with no weird legs'
REFUSAL = "I can't create or show images directly."


def test_a_text_models_image_refusal_hands_the_same_turn_to_the_image_engine(tmp_path, monkeypatch):
    instance = host(tmp_path, monkeypatch, comfy_home=str(tmp_path))
    fake_chat_turn(monkeypatch, Mock(return_value=REFUSAL))
    monkeypatch.setattr(shell.image_gen, 'status', lambda settings: {'running': True})
    generator = made('cow.png')
    monkeypatch.setattr(shell, 'generate_chat_image', generator)
    result = instance._run_chat('request', COW, [])
    assert result == {'answer': 'Created', 'image': 'data:image/png;base64,AA=='}
    assert generator.call_args.args[1] == COW
    assert [(r['role'], r['body']) for r in rows(tmp_path)] == [('user', COW), ('assistant', PREFIX + 'cow.png')]


@pytest.mark.parametrize('prompt,settings', [('Can you create images?', {}), (COW, {'media_chat_auto': False})])
def test_the_refusal_stays_when_nothing_was_asked_to_be_drawn_or_the_owner_turned_picture_routing_off(
        tmp_path, monkeypatch, prompt, settings):
    instance = host(tmp_path, monkeypatch, **settings)
    fake_chat_turn(monkeypatch, Mock(return_value=REFUSAL))
    generator = made('cow.png')
    monkeypatch.setattr(shell, 'generate_chat_image', generator)
    assert instance._run_chat('request', prompt, [])['answer'] == REFUSAL
    generator.assert_not_called()
    assert [r['role'] for r in rows(tmp_path)] == ['user', 'assistant']


def test_a_picture_made_through_the_bridge_shows_in_the_chat_state_right_after(tmp_path, monkeypatch):
    """Issue 573 end to end: the real built-in engine path (fake ComfyUI), then the state the chat renders."""
    import io
    from PIL import Image

    class FakeComfy:
        def status(self):
            return {'running': True}

        def run(self, flow, **_):
            out = io.BytesIO()
            Image.new('RGB', (64, 64), (0, 200, 0)).save(out, 'PNG')
            return [out.getvalue()]

        def close(self):
            pass
    from star import image_gen
    instance = host(tmp_path, monkeypatch, comfy_home=str(tmp_path), image_quality=False)
    monkeypatch.setattr(shell.image_gen, 'status', lambda settings: {'running': True})
    real = image_gen.generate
    monkeypatch.setattr(image_gen, 'generate', lambda *a, **k: real(*a, client=FakeComfy(), **k))
    instance._run_image('request', 'a retro game', display_prompt='Generate image of a retro game')
    shown = [m for m in shell._chat_view(tmp_path, Settings.load(tmp_path / 'settings.json'))['messages']
             if m['role'] == 'assistant']
    assert shown and shown[-1]['image'].startswith('data:image/webp;base64,')
    assert 'missing' not in shown[-1]['text'] and 'unavailable' not in shown[-1]['text']
