"""Pictures from the servers: the image service (server/imagegen/service.py, fake engine), the desktop client
(star/server_images.py), the 'auto' place (media_places.resolve) and the server branch of image_gen."""
from __future__ import annotations

import base64
import importlib.util
import io
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from star import image_gen, media_places, server_images
from star.desktop_core import Settings

ROOT = Path(__file__).resolve().parents[1]
KEY = 'k' * 32


def _service_module():
    spec = importlib.util.spec_from_file_location('star_images_service_under_test',
                                                  ROOT / 'server' / 'imagegen' / 'service.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


service = _service_module()


class FakeEngine:
    model_name = 'Fake Sana'

    def __init__(self, gate: threading.Event | None = None):
        self.gate, self.calls, self.warmed = gate, [], None

    def warm(self, sizes):
        self.warmed = list(sizes)

    def steps_for(self, size):
        return {512: 2, 1024: 1}[size]

    def generate(self, prompt, size, steps, seed):
        self.calls.append((prompt, size, steps, seed))
        if self.gate is not None:
            self.gate.wait(5)
        return Image.new('RGB', (size, size), (200, 30, 30)), {'total_s': 0.01}


@pytest.fixture
def running(tmp_path):
    keys = tmp_path / 'api_keys'
    keys.write_text(KEY + '\n', encoding='utf-8')
    started = []

    def start(engine=None, **cfg):
        engine = engine or FakeEngine()
        config = {**service.DEFAULTS, 'listen': '127.0.0.1', 'port': 0, 'keys_file': str(keys), **cfg}
        httpd = service.serve(config, lambda _cfg: engine)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        started.append(httpd)
        for _ in range(100):
            if httpd.worker.state != 'loading':
                break
            threading.Event().wait(0.02)
        return f'http://127.0.0.1:{httpd.server_address[1]}', engine, httpd
    yield start
    for httpd in started:
        httpd.shutdown()
        httpd.server_close()


def _post(url, body, key=KEY):
    req = urllib.request.Request(url + '/v1/images/generations', json.dumps(body).encode(),
                                 {'Content-Type': 'application/json', **({'Authorization': 'Bearer ' + key} if key else {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


# ---- the service ------------------------------------------------------------------------------

def test_service_makes_a_png_with_the_brain_key_and_reports_seed_and_steps(running):
    url, engine, _ = running()
    with urllib.request.urlopen(url + '/health', timeout=5) as r:
        health = json.loads(r.read())
    assert health['status'] == 'ok' and health['sizes'] == [512, 1024] and engine.warmed == [512, 1024]
    status, data = _post(url, {'prompt': ' a red fox ', 'size': '1024x1024', 'seed': 7})
    assert status == 200 and data['seed'] == 7 and data['steps'] == 1 and data['size'] == '1024x1024'
    picture = Image.open(io.BytesIO(base64.b64decode(data['data'][0]['b64_json'])))
    assert picture.size == (1024, 1024) and picture.format == 'PNG'
    assert engine.calls == [('a red fox', 1024, None, 7)]


def test_service_refuses_missing_or_wrong_keys_and_bad_requests(running):
    url, engine, _ = running()
    assert _post(url, {'prompt': 'x'}, key='')[0] == 401
    assert _post(url, {'prompt': 'x'}, key='wrong')[0] == 401
    for body, words in [({'prompt': ''}, 'prompt'), ({'prompt': 'x' * 1501}, 'prompt'),
                        ({'prompt': 'x', 'size': '640x640'}, 'size must be one of 512x512, 1024x1024'),
                        ({'prompt': 'x', 'size': '512x1024'}, 'size'), ({'prompt': 'x', 'n': 2}, 'n must be 1'),
                        ({'prompt': 'x', 'steps': 9}, 'steps'), ({'prompt': 'x', 'seed': -1}, 'seed'),
                        ({'prompt': 'x', 'response_format': 'url'}, 'b64_json')]:
        status, data = _post(url, body)
        assert status == 400 and words in data['error']['message'], body
    assert engine.calls == []


def test_service_makes_one_picture_at_a_time_and_turns_away_a_long_queue(running):
    gate = threading.Event()
    url, engine, httpd = running(FakeEngine(gate), max_waiting=1)
    results = []
    threads = [threading.Thread(target=lambda: results.append(_post(url, {'prompt': 'x', 'size': '512x512'})[0]))
               for _ in range(2)]
    for thread in threads:
        thread.start()
    for _ in range(100):
        if httpd.worker.waiting == 2:
            break
        threading.Event().wait(0.02)
    assert httpd.worker.waiting == 2 and httpd.worker.lock.locked()
    assert _post(url, {'prompt': 'x', 'size': '512x512'})[0] == 429      # one running + one waiting = full
    gate.set()
    for thread in threads:
        thread.join(10)
    assert sorted(results) == [200, 200] and len(engine.calls) == 2


def test_service_says_not_ready_while_loading_and_reports_a_failed_load(running):
    class Broken(FakeEngine):
        def warm(self, sizes):
            raise RuntimeError('no model files')
    url, _, _ = running(Broken())
    with urllib.request.urlopen(url + '/health', timeout=5) as r:
        health = json.loads(r.read())
    assert health['status'] == 'error' and 'no model files' in health['error']
    status, data = _post(url, {'prompt': 'x', 'size': '512x512'})
    assert status == 503 and 'no model files' in data['error']['message']


def test_key_file_is_read_again_when_it_changes(tmp_path):
    path = tmp_path / 'keys'
    path.write_text('first\n', encoding='utf-8')
    keys = service.KeyFile(str(path))
    assert keys.check('first') and not keys.check('second') and not keys.check('')
    path.write_text('second\n\n', encoding='utf-8')
    import os
    os.utime(path, ns=(1, 10 ** 18))
    assert keys.check('second') and not keys.check('first')
    assert not service.KeyFile(str(tmp_path / 'missing')).check('first')


# ---- the desktop client -------------------------------------------------------------------------

def _png(size=1024) -> bytes:
    out = io.BytesIO()
    Image.new('RGB', (size, size), 'blue').save(out, format='PNG')
    return out.getvalue()


@pytest.fixture
def server_key(monkeypatch):
    monkeypatch.setattr('star.providers.get_api_key', lambda name: KEY)


def test_client_sends_the_key_and_size_and_returns_the_png(server_key):
    seen = {}

    def handler(request):
        seen.update(url=str(request.url), auth=request.headers['Authorization'], body=json.loads(request.content))
        return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(_png(512)).decode()}],
                                         'seed': 5, 'steps': 2, 'seconds': 5.4, 'model': 'SANA-Sprint 0.6B'})
    settings = Settings(media_images_server='http://images.test:8095/')
    picture, info = server_images.generate(settings, 'a cat', size='draft', seed=5,
                                           transport=httpx.MockTransport(handler))
    assert picture.startswith(b'\x89PNG') and info['width'] == info['height'] == 512 and info['steps'] == 2
    assert seen == {'url': 'http://images.test:8095/v1/images/generations', 'auth': 'Bearer ' + KEY,
                    'body': {'prompt': 'a cat', 'size': '512x512', 'response_format': 'b64_json', 'seed': 5}}


@pytest.mark.parametrize('status,body,words', [
    (401, {'error': {'message': 'invalid api key'}}, 'refused the STAR Server key'),
    (429, {'error': {'message': 'busy'}}, 'busy with other pictures'),
    (503, {'error': {'message': 'not ready'}}, 'still starting'),
    (200, {'data': [{'b64_json': base64.b64encode(b'GIF89a').decode()}]}, 'not a PNG'),
    (200, {'nothing': True}, 'without a picture'),
])
def test_client_explains_every_failure(server_key, status, body, words):
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=body))
    with pytest.raises(server_images.ServerImageError, match=words):
        server_images.generate(Settings(media_images_server='http://images.test:8095'), 'x', transport=transport)


def test_client_needs_an_address_and_the_key(monkeypatch):
    monkeypatch.setattr('star.providers.get_api_key', lambda name: None)
    assert not server_images.configured(Settings(media_images_server='http://images.test:8095'))
    monkeypatch.setattr('star.providers.get_api_key', lambda name: KEY)
    assert not server_images.configured(Settings())
    with pytest.raises(server_images.ServerImageError, match='No image service'):
        server_images.generate(Settings(), 'x')


# ---- where a picture is made --------------------------------------------------------------------

def test_auto_uses_the_pc_while_its_card_is_free_and_the_servers_while_it_is_busy(tmp_path, server_key):
    settings = Settings(media_images='auto', media_images_server='http://images.test:8095')
    assert media_places.resolve(settings, 'images', tmp_path, gpu_free=lambda: True) == 'pc'
    assert media_places.resolve(settings, 'images', tmp_path, gpu_free=lambda: False) == 'servers'
    assert media_places.resolve(Settings(), 'images', tmp_path, gpu_free=lambda: False) == 'pc'
    shown = {o['id']: o for o in media_places.describe(settings, tmp_path)[0]['options']}
    assert shown['servers']['available'] and shown['auto']['available'] and shown['auto']['reason'] == ''


def test_auto_without_an_image_service_is_refused_not_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr('star.providers.get_api_key', lambda name: None)
    with pytest.raises(media_places.PlaceUnavailable, match='no image service address'):
        media_places.resolve(Settings(media_images='auto'), 'images', tmp_path, gpu_free=lambda: False)


def test_pc_card_is_free_with_enough_memory_and_no_game_or_when_comfyui_is_loaded():
    reading = lambda util, used: (lambda: SimpleNamespace(utilization=util, free_mib=8192 - used))  # noqa: E731
    settings = Settings()
    assert media_places.pc_gpu_free(settings, read_gpu=reading(3, 1997), comfy_running=lambda: False)
    assert not media_places.pc_gpu_free(settings, read_gpu=reading(3, 7700), comfy_running=lambda: False)
    assert not media_places.pc_gpu_free(settings, read_gpu=reading(97, 3000), comfy_running=lambda: False)
    assert media_places.pc_gpu_free(settings, read_gpu=reading(40, 7900), comfy_running=lambda: True)
    assert media_places.pc_gpu_free(settings, read_gpu=lambda: None, comfy_running=lambda: False)


def test_a_server_picture_is_saved_with_its_note_and_says_where_it_was_made(tmp_path, server_key, monkeypatch):
    monkeypatch.setattr(server_images, 'generate', lambda settings, prompt, **kw: (
        _png(1024), {'seed': kw['seed'], 'steps': 1, 'seconds': 14.0, 'model': 'SANA-Sprint 0.6B',
                     'width': 1024, 'height': 1024}))
    settings = Settings(project='Test', media_images='servers', media_images_server='http://images.test:8095')
    made = image_gen.generate(settings, 'a castle', tmp_path, size='wide', seed=11)
    assert 'on the STAR Brains (servers)' in made['answer'] and 'made square' in made['answer']
    assert made['note']['place'] == 'servers' and made['note']['width'] == 1024 and made['note']['seed'] == 11
    assert made['path'].is_file() and made['path'].parent == tmp_path / 'generated-images'


def test_changing_a_picture_never_goes_to_the_servers(tmp_path, server_key, monkeypatch):
    monkeypatch.setattr(server_images, 'generate', lambda *a, **k: pytest.fail('edits must not reach the servers'))
    source = tmp_path / 'in.png'
    source.write_bytes(_png(256))
    settings = Settings(project='Test', media_images='servers', media_images_server='http://images.test:8095')
    with pytest.raises(media_places.PlaceUnavailable, match='Changing an attached picture runs on this PC'):
        image_gen.generate(settings, 'make it green', tmp_path, source=source)
    monkeypatch.setattr(media_places, 'resolve', lambda *a, **k: pytest.fail('auto edits are decided as the PC'))

    class Stop(Exception):
        pass

    class NoComfy:
        def status(self):
            raise Stop()

        def close(self):
            pass
    with pytest.raises(Stop):     # reached the PC path (ComfyUI), not the servers
        image_gen.generate(Settings(project='Test', media_images='auto', media_images_server='http://images.test:8095'),
                           'make it green', tmp_path, source=source, client=NoComfy())


def test_settings_accept_auto_only_for_images_and_a_plain_service_address():
    Settings(media_images='auto', media_images_server='http://images.test:8095').validate()
    with pytest.raises(ValueError):
        Settings(media_voice='auto').validate()
    for bad in ('images.test:8095', 'http://user:pw@images.test:8095', 'ftp://images.test', 'http://a b'):
        with pytest.raises(ValueError, match='image service address'):
            Settings(media_images_server=bad).validate()
