"""Run production picker/chat methods without constructing Qt or a model client.

Bridge is local to launch(). Compile its actual method ASTs, unchanged except
for the Qt Slot decorator, so the picker/filter and chat handoff really execute.
Only GUI, conversation persistence, references and model boundaries are fakes;
classification, XML parsing, document storage and budgeting are production code.
"""
import ast
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import ModuleType, SimpleNamespace
import uuid

import pytest

from star.documents import DocumentStore
from star.react_shell import song_lookup_request

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / 'fixtures' / 'rbx_xml'


def actual_methods():
    path = ROOT / 'star' / 'react_shell.py'
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    launch = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'launch')
    bridge = next(n for n in launch.body if isinstance(n, ast.ClassDef) and n.name == 'Bridge')
    methods = [n for n in bridge.body if isinstance(n, ast.FunctionDef) and n.name in {'invoke', '_run_chat'}]
    helpers = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'file_allowed']
    for method in methods:
        method.decorator_list = []
    return compile(ast.Module(body=helpers + methods, type_ignores=[]), str(path), 'exec')


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    media_features = ModuleType('star.media_features')
    media_features.AUDIO_EXTENSIONS = {'.wav'}
    media_features.VIDEO_EXTENSIONS = {'.mp4'}
    monkeypatch.setitem(sys.modules, 'star.media_features', media_features)

    # Load the real media module in an isolated namespace. Do not pollute the
    # application's imported chat_media module for tests elsewhere in the suite.
    path = ROOT / 'star' / 'chat_media.py'
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    tree.body = [n for n in tree.body if not (
        isinstance(n, ast.ImportFrom) and n.level == 1 and n.module is None)]
    module = ModuleType('star._rbx_attachment_test_media')
    module.__package__ = 'star'
    module.references = SimpleNamespace(for_turn=lambda *a, **k: ([], ''))
    module.video_understanding = SimpleNamespace(link_only_note=lambda *a: '')
    module.media_places = SimpleNamespace()
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(compile(tree, str(path), 'exec'), module.__dict__)

    captured = SimpleNamespace(filter='', names=[], documents=[], pictures=[], context='', turns=[])

    class Dialog:
        @staticmethod
        def getOpenFileNames(host, title, directory, file_filter):
            captured.filter = file_filter
            return captured.names, ''

    class Chats:
        def __init__(self, path):
            pass

        def active_chat(self, project):
            return 'chat'

        def add(self, project, role, text, **kwargs):
            captured.turns.append((role, text))
            return len(captured.turns)

        def close(self):
            pass

    settings = SimpleNamespace(model='fixture-model', project='project', media_use_references=False,
                               session_capabilities_prompt=False)

    def model_boundary(settings, prompt, pictures, **kwargs):
        captured.pictures = pictures
        captured.documents = kwargs.get('documents', [])
        with DocumentStore(tmp_path / 'home', settings.project, kwargs['chat_id']) as store:
            store.ingest(captured.documents, kwargs['cancel_event'])
            captured.context = store.context(prompt, 4000)
        return 'Fixture answer'

    namespace = dict(__package__='star', Path=Path, json=json, threading=threading,
                     tempfile=tempfile, uuid=uuid, ALLOWED_ACTIONS={'pickFiles', 'sendMessage'},
                     WARM_UP_STOPPERS=set(), VOICE_ACTIONS=set(), MEDIA_ACTIONS=set(), DISCORD_ACTIONS=set(),
                     CLIP_ACTIONS=set(), CLIP_INTEROP_ACTIONS=set(), MUSIC_ACTIONS=set(),
                     song_lookup_request=song_lookup_request,
                     LESSON_ACTIONS=set(), LEARNED_ACTIONS=set(), CORRECTION_ACTIONS=set(),
                     ROBLOX_ACTIONS=set(), STUDIO_HOST_ACTIONS=set(),
                     QFileDialog=Dialog, Settings=SimpleNamespace(load=lambda path: settings),
                     Conversations=Chats, app_data=lambda: tmp_path / 'home',
                     TurnRef=lambda *args: args, prepare_turn=module.prepare_turn,
                     run_task=model_boundary, provider_kind=lambda settings: 'local')
    exec(actual_methods(), namespace)
    host = SimpleNamespace(host=None, allowed_files=set(), active_task=False,
                           settings_file=tmp_path / 'settings.json', cancel_chat=threading.Event(),
                           _warm=lambda **kwargs: None, _digest_when_idle=lambda: None)
    host._run = lambda request, action, worker: worker()
    host._run_chat = lambda *args, **kwargs: namespace['_run_chat'](host, *args, **kwargs)
    return host, lambda body: json.loads(namespace['invoke'](host, json.dumps(body))), captured


@pytest.mark.parametrize('filename', ['model.rbxmx', 'place.rbxlx'])
def test_actual_picker_and_chat_handoff(bridge, filename):
    host, invoke, captured = bridge
    path = (FIXTURES / filename).resolve()
    captured.names = [str(path)]
    picked = invoke({'action': 'pickFiles'})
    assert picked == {'ok': True, 'data': [str(path)]}
    assert path in host.allowed_files
    for suffix in ('rbxmx', 'rbxlx', 'rbxm', 'rbxl', 'txt', 'pdf'):
        assert '*.' + suffix in captured.filter
    result = invoke({'action': 'sendMessage', 'prompt': 'Explain FireClient', 'files': picked['data']})
    assert result['ok'], result
    assert captured.documents == [path]
    assert captured.pictures == []
    assert 'Roblox XML outline' in captured.context
    assert len(captured.context) <= 4000
    assert captured.turns[-1] == ('assistant', 'Fixture answer')


@pytest.mark.parametrize('suffix', ['.rbxm', '.rbxl'])
def test_actual_chat_binary_refusal_is_not_an_image(bridge, tmp_path, suffix):
    host, invoke, captured = bridge
    path = tmp_path / ('binary' + suffix)
    path.write_bytes(b'<roblox!\x89\xff\r\n\x1a\n')
    captured.names = [str(path)]
    picked = invoke({'action': 'pickFiles'})
    result = invoke({'action': 'sendMessage', 'prompt': 'Explain model', 'files': picked['data']})
    assert not result['ok']
    assert 'Binary Roblox' in result['error'] and 'export as XML' in result['error']
    assert captured.documents == [path]
    assert captured.pictures == []
    assert not host.active_task


def test_actual_picker_cancellation_and_existing_image_filter(bridge):
    host, invoke, captured = bridge
    assert invoke({'action': 'pickFiles'}) == {'ok': True, 'data': []}
    assert host.allowed_files == set()
    assert invoke({'action': 'pickFiles', 'kind': 'image'})['ok']
    assert captured.filter == 'Images (*.png *.jpg *.jpeg *.webp)'


def test_actual_chat_still_requires_picker_approval(bridge):
    host, invoke, captured = bridge
    result = invoke({'action': 'sendMessage', 'prompt': 'Explain model',
                     'files': [str(FIXTURES / 'model.rbxmx')]})
    assert not result['ok'] and 'Choose the file through STAR Attach' in result['error']
    assert captured.documents == []
