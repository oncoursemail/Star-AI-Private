"""Media on the owner's PC: image generation through ComfyUI, the "where to generate" switch,
visual references, picture understanding and video understanding. Every path runs against fakes
here; the live tests at the end are skipped unless the real service is present.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import threading
import wave
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image, ImageChops, ImageDraw

from star import chat_media, image_gen, media_actions, media_places, references, video_understanding, vision
from star.chat_images import PREFIX, chat_image, generate_chat_image
from star.comfy import (KLEIN_FILES, ComfyClient, ComfyError, klein_edit, klein_text_to_image)
from star.desktop_core import Settings, picture_limit
from star.media import image_part

LAN = 'http://192.168.1.20:8080/v1'          # documentation placeholder, not a real machine (star:allow)


def png(size=(64, 64), colour=(200, 40, 40)) -> bytes:
    out = io.BytesIO()
    Image.new('RGB', size, colour).save(out, format='PNG')
    return out.getvalue()


def picture(path: Path, size=(640, 480), colour=(30, 90, 160)) -> Path:
    Image.new('RGB', size, colour).save(path)
    return path


def server_settings(**extra) -> Settings:
    return Settings(provider='star_server', server_endpoint=LAN, model='star-fast', project='Test', **extra)


# ---- built-in workflows ---------------------------------------------------------------------

CORE_NODES = {'UNETLoader', 'CLIPLoader', 'VAELoader', 'CLIPTextEncode', 'ConditioningZeroOut', 'KSamplerSelect',
              'Flux2Scheduler', 'RandomNoise', 'EmptyFlux2LatentImage', 'CFGGuider', 'SamplerCustomAdvanced',
              'VAEDecode', 'PreviewImage', 'LoadImage', 'ImageScaleToTotalPixels', 'VAEEncode', 'ReferenceLatent',
              'ImageToMask', 'SetLatentNoiseMask'}


def test_text_to_image_workflow_uses_only_core_nodes_and_the_installed_files():
    flow = klein_text_to_image('a red door', 1024, 1024, 7)
    assert {node['class_type'] for node in flow.values()} <= CORE_NODES
    assert flow['unet']['inputs']['unet_name'] == KLEIN_FILES['diffusion_models']
    assert flow['clip']['inputs'] == {'clip_name': KLEIN_FILES['text_encoders'], 'type': 'flux2', 'device': 'default'}
    assert flow['sigmas']['inputs'] == {'steps': 4, 'width': 1024, 'height': 1024}
    assert flow['noise']['inputs']['noise_seed'] == 7 and flow['text']['inputs']['text'] == 'a red door'
    assert flow['guider']['inputs']['cfg'] == 1.0
    # every link points at a node that exists
    for node in flow.values():
        for value in node['inputs'].values():
            if isinstance(value, list):
                assert value[0] in flow


def test_references_and_edits_are_chained_onto_both_conditionings():
    flow = klein_text_to_image('same shop at night', 1024, 1024, 1, references=('star/star_ref0.png', 'star/star_ref1.png'))
    assert flow['guider']['inputs']['positive'] == ['ref1_positive', 0]
    assert flow['ref1_positive']['inputs']['conditioning'] == ['ref0_positive', 0]
    assert flow['ref0_positive']['inputs']['conditioning'] == ['text', 0]
    assert flow['ref0_negative']['inputs']['conditioning'] == ['blank', 0]
    assert flow['ref0_image']['inputs']['image'] == 'star/star_ref0.png'

    edit = klein_edit('make it snow', 'star/star_src.png', 1024, 768, 3)
    assert edit['src_latent']['inputs']['pixels'] == ['src_image', 0]          # the source is not rescaled by ComfyUI
    assert edit['sample']['inputs']['latent_image'] == ['latent', 0]

    inpaint = klein_edit('a red door', 'star/star_src.png', 1024, 768, 3, mask_name='star/star_mask.png')
    assert inpaint['masked']['class_type'] == 'SetLatentNoiseMask'
    assert inpaint['masked']['inputs'] == {'samples': ['src_latent', 0], 'mask': ['mask', 0]}
    assert inpaint['sample']['inputs']['latent_image'] == ['masked', 0]
    assert {node['class_type'] for node in inpaint.values()} <= CORE_NODES


# ---- the ComfyUI client against a fake server -----------------------------------------------

class FakeComfyServer:
    """Answers the ComfyUI routes STAR uses. `mode` picks the failure to play."""

    def __init__(self, mode='ok', models=None):
        self.mode, self.calls, self.uploads, self.prompts = mode, [], {}, []
        self.models = models if models is not None else dict(KLEIN_FILES)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        if self.mode == 'down':
            raise httpx.ConnectError('refused', request=request)
        if path == '/system_stats':
            return httpx.Response(200, json={'system': {'comfyui_version': '0.39.0'}, 'devices': [
                {'name': 'cuda:0 Test GPU', 'type': 'cuda', 'vram_total': 8 * 2 ** 30, 'vram_free': 6 * 2 ** 30}]})
        if path.startswith('/models/'):
            folder = path.rsplit('/', 1)[1]
            return httpx.Response(200, json=[self.models[folder]] if folder in self.models else [])
        if path == '/upload/image':
            body = request.read()
            name = body.split(b'filename="')[1].split(b'"')[0].decode()
            self.uploads[name] = body
            return httpx.Response(200, json={'name': name, 'subfolder': 'star', 'type': 'input'})
        if path == '/prompt':
            self.prompts.append(json.loads(request.read())['prompt'])
            if self.mode == 'model_missing':
                return httpx.Response(400, json={'error': {'message': 'Prompt outputs failed validation'}, 'node_errors': {
                    'unet': {'class_type': 'UNETLoader', 'errors': [{
                        'type': 'value_not_in_list',
                        'details': "unet_name: 'flux-2-klein-4b-fp8.safetensors' not in []"}]}}})
            return httpx.Response(200, json={'prompt_id': 'job-12345678'})
        if path == '/history/job-12345678':
            if self.mode == 'oom':
                return httpx.Response(200, json={'job-12345678': {'status': {'status_str': 'error', 'messages': [
                    ['execution_error', {'exception_type': 'torch.OutOfMemoryError', 'node_type': 'SamplerCustomAdvanced',
                                         'exception_message': 'Allocation on device 0 would exceed allowed memory.'}]]}}})
            if self.mode == 'slow':
                return httpx.Response(200, json={})
            return httpx.Response(200, json={'job-12345678': {'status': {'status_str': 'success', 'completed': True},
                                                             'outputs': {'out': {'images': [
                                                                 {'filename': 'ComfyUI_temp_00001_.png', 'subfolder': '', 'type': 'temp'},
                                                                 {'filename': '../evil.png', 'subfolder': '', 'type': 'temp'}]}}}})
        if path == '/view':
            return httpx.Response(200, content=png((1024, 1024)))
        if path in ('/free', '/interrupt', '/queue'):
            return httpx.Response(200, json={})
        return httpx.Response(404)


def client_for(server: FakeComfyServer) -> ComfyClient:
    return ComfyClient(transport=httpx.MockTransport(server), poll=0.0)


def test_client_queues_waits_and_fetches_only_safe_file_names():
    server = FakeComfyServer()
    with client_for(server) as comfy:
        assert comfy.status()['version'] == '0.39.0' and comfy.missing_models() == []
        assert comfy.upload(png(), 'star_src.png') == 'star/star_src.png'
        images = comfy.run(klein_text_to_image('x', 512, 512, 1))
    assert len(images) == 1 and images[0][:8] == b'\x89PNG\r\n\x1a\n'     # the "../evil.png" entry was skipped
    assert [call for call in server.calls if call[1] == '/view'] == [('GET', '/view')]


def test_not_running_is_said_plainly_with_the_step_to_take():
    with client_for(FakeComfyServer('down')) as comfy, pytest.raises(ComfyError) as caught:
        comfy.status()
    assert caught.value.kind == 'not_running'
    assert 'not running on this PC (127.0.0.1:8188)' in str(caught.value) and 'Start ComfyUI' in str(caught.value)


def test_missing_model_names_the_file_and_the_setup_step():
    with client_for(FakeComfyServer('model_missing')) as comfy, pytest.raises(ComfyError) as caught:
        comfy.run(klein_text_to_image('x', 512, 512, 1))
    assert caught.value.kind == 'model_missing'
    assert 'flux-2-klein-4b-fp8.safetensors' in str(caught.value) and 'setup_comfyui.sh models' in str(caught.value)
    with client_for(FakeComfyServer(models={'vae': KLEIN_FILES['vae']})) as comfy:
        assert comfy.missing_models() == ['models/diffusion_models/' + KLEIN_FILES['diffusion_models'],
                                          'models/text_encoders/' + KLEIN_FILES['text_encoders']]


def test_out_of_memory_frees_the_card_and_gives_the_recovery_step():
    server = FakeComfyServer('oom')
    with client_for(server) as comfy, pytest.raises(ComfyError) as caught:
        comfy.run(klein_text_to_image('x', 1024, 1024, 1))
    assert caught.value.kind == 'out_of_memory'
    assert ('POST', '/free') in server.calls                       # STAR asked ComfyUI to unload its models
    message = str(caught.value)
    assert 'ran out of memory' in message and 'Close other programs' in message and 'Draft' in message


def test_stop_interrupts_the_job():
    server, stop = FakeComfyServer('slow'), threading.Event()
    stop.set()
    with client_for(server) as comfy, pytest.raises(RuntimeError, match='cancelled by user'):
        comfy.run(klein_text_to_image('x', 512, 512, 1), cancel_event=stop)
    assert ('POST', '/interrupt') in server.calls and ('POST', '/queue') in server.calls


def test_a_job_that_never_finishes_times_out_honestly():
    with client_for(FakeComfyServer('slow')) as comfy, pytest.raises(ComfyError) as caught:
        comfy.run(klein_text_to_image('x', 512, 512, 1), timeout_seconds=0.05)
    assert caught.value.kind == 'timeout'


# ---- image generation, editing and inpainting -----------------------------------------------

class FakeComfy:
    """Stands in for ComfyClient: returns a flat green picture of the size the workflow asks for."""

    def __init__(self, error: Exception | None = None):
        self.uploads, self.flows, self.error = {}, [], error

    def status(self):
        if self.error:
            raise self.error
        return {'running': True}

    def upload(self, content: bytes, name: str) -> str:
        self.uploads[name] = content
        return 'star/' + name

    def run(self, flow, **_):
        self.flows.append(flow)
        return [png((flow['latent']['inputs']['width'], flow['latent']['inputs']['height']), (0, 200, 0))]

    def close(self):
        pass


def test_text_to_image_saves_the_original_and_a_note_in_the_data_folder(tmp_path):
    comfy = FakeComfy()
    made = image_gen.generate(Settings(project='Test'), 'a lighthouse', tmp_path, size='wide', seed=42, client=comfy)
    saved = made['path']
    assert saved.parent == tmp_path / 'generated-images' and saved.is_file()
    with Image.open(saved) as image:
        assert image.size == (1280, 720)
    note = json.loads(saved.with_suffix('.json').read_text(encoding='utf-8'))
    assert note['prompt'] == 'a lighthouse' and note['seed'] == 42 and note['mode'] == 'text' and note['place'] == 'pc'
    assert made['message'] == PREFIX + saved.name and made['image'].startswith('data:image/webp;base64,')
    assert 'on this PC' in made['answer'] and '1280 x 720' in made['answer'] and 'seed 42' in made['answer']
    # reopening the chat shows the same line, read back from the note beside the picture
    assert chat_image(tmp_path, made['message'])['text'] == made['answer']
    assert image_gen.latest(tmp_path) == saved


def test_edit_keeps_the_shape_of_the_attached_picture(tmp_path):
    comfy = FakeComfy()
    source = picture(tmp_path / 'room.png', (1600, 900))
    made = image_gen.generate(Settings(project='Test'), 'make it night', tmp_path, source=source, seed=1, client=comfy)
    flow = comfy.flows[0]
    assert (flow['latent']['inputs']['width'], flow['latent']['inputs']['height']) == (1360, 768)
    assert flow['src_image']['inputs']['image'] == 'star/star_src.png' and 'masked' not in flow
    with Image.open(io.BytesIO(comfy.uploads['star_src.png'])) as sent:
        assert sent.size == (1360, 768)
    assert made['note']['mode'] == 'edit' and made['answer'].startswith('Image edited on this PC')


def test_inpaint_changes_only_the_masked_area(tmp_path):
    comfy = FakeComfy()
    source = picture(tmp_path / 'wall.png', (1024, 1024), (30, 90, 160))
    mask = Image.new('L', (1024, 1024), 0)
    ImageDraw.Draw(mask).rectangle((384, 384, 640, 640), fill=255)
    mask.save(tmp_path / 'mask.png')
    made = image_gen.generate(Settings(project='Test'), 'a window', tmp_path, source=source, mask=tmp_path / 'mask.png',
                              seed=5, client=comfy)
    assert comfy.flows[0]['masked']['class_type'] == 'SetLatentNoiseMask'
    with Image.open(made['path']) as result:
        result = result.convert('RGB')
        assert result.getpixel((512, 512)) == (0, 200, 0)                    # inside the mask: the new picture
        for corner in ((5, 5), (1018, 5), (5, 1018), (1018, 1018), (200, 512), (512, 860)):
            assert result.getpixel(corner) == (30, 90, 160)                  # outside: the original, untouched
    assert 'outside the mask is the original' in made['answer']


def test_mask_rules(tmp_path):
    source = picture(tmp_path / 'a.png')
    Image.new('L', (64, 64), 0).save(tmp_path / 'black.png')
    with pytest.raises(ValueError, match='no white area'):
        image_gen.generate(Settings(project='Test'), 'x', tmp_path, source=source, mask=tmp_path / 'black.png',
                           client=FakeComfy())
    with pytest.raises(ValueError, match='needs the picture'):
        image_gen.generate(Settings(project='Test'), 'x', tmp_path, mask=tmp_path / 'black.png', client=FakeComfy())
    erased = Image.new('RGBA', (64, 64), (255, 255, 255, 255))
    ImageDraw.Draw(erased).rectangle((0, 0, 31, 63), fill=(0, 0, 0, 0))       # the erased half is the part to change
    erased.save(tmp_path / 'erased.png')
    mask = image_gen.read_mask(tmp_path / 'erased.png', (64, 64))
    assert mask.getpixel((5, 5)) == 255 and mask.getpixel((60, 5)) == 0


def test_generation_errors_reach_the_owner_unchanged(tmp_path):
    down = ComfyError('not_running', 'ComfyUI is not running on this PC (127.0.0.1:8188). Start it.')
    with pytest.raises(ComfyError, match='not running'):
        image_gen.generate(Settings(project='Test'), 'x', tmp_path, client=FakeComfy(down))
    assert not (tmp_path / 'generated-images').exists()                       # nothing was saved or pretended
    with pytest.raises(ValueError, match='image sizes'):
        image_gen.generate(Settings(project='Test'), 'x', tmp_path, size='huge', client=FakeComfy())


def test_pinned_references_are_given_to_the_image_model(tmp_path):
    references.pin(tmp_path, 'Test', picture(tmp_path / 'approved.png', (800, 600)), label='Shop front')
    comfy = FakeComfy()
    made = image_gen.generate(Settings(project='Test'), 'the same shop at night', tmp_path, client=comfy)
    assert 'star_ref0.png' in comfy.uploads and comfy.flows[0]['ref0_image']['inputs']['image'] == 'star/star_ref0.png'
    assert made['note']['references'] == ['Shop front'] and 'followed 1 project reference: Shop front' in made['answer']
    quiet = FakeComfy()
    image_gen.generate(Settings(project='Test', media_use_references=False), 'x', tmp_path, client=quiet)
    assert quiet.uploads == {} and 'ref0_image' not in quiet.flows[0]
    other = FakeComfy()
    image_gen.generate(Settings(project='Another'), 'x', tmp_path, client=other)   # references belong to one project
    assert other.uploads == {}


def test_chat_entry_point_uses_the_built_in_model_without_a_workflow_file(tmp_path, monkeypatch):
    seen = {}

    def fake(settings, prompt, home, **kwargs):
        seen.update(kwargs, prompt=prompt)
        (home / 'generated-images').mkdir(parents=True, exist_ok=True)
        (home / 'generated-images' / 'x.png').write_bytes(b'x')
        return {'answer': 'ok', 'image': 'data:image/webp;base64,AA', 'message': PREFIX + 'x.png', 'path': home, 'note': {}}
    monkeypatch.setattr(image_gen, 'generate', fake)
    result = generate_chat_image(Settings(project='Test'), 'a cat', tmp_path, size='draft')
    assert result == {'answer': 'ok', 'image': 'data:image/webp;base64,AA', 'message': PREFIX + 'x.png'}
    assert seen['size'] == 'draft' and seen['source'] is None and seen['prompt'] == 'a cat'


# ---- the switch -----------------------------------------------------------------------------

def test_switch_lists_both_places_for_every_capability_with_honest_notes(tmp_path, monkeypatch):
    monkeypatch.delenv('STAR_SERVER_API_KEY', raising=False)
    monkeypatch.setattr('star.providers.get_api_key', lambda name: None)
    shown = {entry['id']: entry for entry in media_places.describe(Settings(), tmp_path)}
    assert list(shown) == ['images', 'voice', 'video']
    for entry in shown.values():
        assert [option['label'] for option in entry['options']] == ['STAR Brains (servers)', 'This PC (your GPU)']
        for option in entry['options']:
            assert option['available'] or option['reason'].startswith('Not available')
    images = {option['id']: option for option in shown['images']['options']}
    assert shown['images']['chosen'] == 'pc' and images['pc']['available'] and not images['servers']['available']
    assert 'Measured on this PC' in images['pc']['note'] and '1024x1024 in 6.8 s' in images['pc']['note']
    assert 'no graphics card' in images['servers']['reason'] and 'estimate' in images['servers']['reason']
    assert '480 to 1500 s' in images['servers']['reason'] and 'not measured on the servers' in images['servers']['reason']
    voice = {option['id']: option for option in shown['voice']['options']}
    assert voice['pc']['available'] and not voice['servers']['available']
    assert 'no speech recogniser or voice is installed on the servers' in voice['servers']['reason']
    video = {option['id']: option for option in shown['video']['options']}
    assert not video['servers']['available'] and 'no STAR Server is connected' in video['servers']['reason']
    assert not video['pc']['available'] and 'on-device brain is not installed' in video['pc']['reason']
    # Settings can make video places available; images and voice on the servers cannot exist here.
    assert video['servers']['fixable'] and video['pc']['fixable']
    assert images['servers']['fixable'] is False and voice['servers']['fixable'] is False
    assert images['pc']['fixable'] and voice['pc']['fixable']


def test_an_unavailable_place_is_refused_never_replaced(tmp_path, monkeypatch):
    with pytest.raises(media_places.PlaceUnavailable, match='Images is set to STAR Brains'):
        image_gen.generate(Settings(project='Test', media_images='servers'), 'x', tmp_path, client=FakeComfy())
    with pytest.raises(media_places.PlaceUnavailable):
        generate_chat_image(Settings(project='Test', media_images='servers', comfy_workflow='C:/flow.json'), 'x', tmp_path)
    with pytest.raises(media_places.PlaceUnavailable, match='Voice is set to STAR Brains'):
        media_places.require(Settings(media_voice='servers'), 'voice', tmp_path)
    assert media_places.require(Settings(), 'voice', tmp_path) == 'pc'
    with pytest.raises(ValueError, match='STAR Brains'):
        Settings(media_images='cloud').validate()


def test_video_frames_go_only_to_the_chosen_place(tmp_path, monkeypatch):
    monkeypatch.setattr('star.providers.get_api_key', lambda name: 'k' * 20)
    assert media_places.require_video_provider(server_settings(), tmp_path) == 'servers'
    hosted = Settings(provider='groq', server_endpoint=LAN, model='m')
    with pytest.raises(media_places.PlaceUnavailable, match='does not send frames of your video anywhere else'):
        media_places.require_video_provider(hosted, tmp_path)
    (tmp_path / 'brain.json').write_text('{}', encoding='utf-8')
    local = Settings(provider='local', model='m', media_video='pc')
    assert media_places.require_video_provider(local, tmp_path) == 'pc'
    with pytest.raises(media_places.PlaceUnavailable, match='Select On-device'):
        media_places.require_video_provider(server_settings(media_video='pc'), tmp_path)


# ---- visual references ----------------------------------------------------------------------

def test_pin_list_unpin_per_project(tmp_path):
    source = picture(tmp_path / 'ui.png', (3000, 1500))
    entry = references.pin(tmp_path, 'Game A', source, label='Main menu', note='approved 11 Oct')
    listed = references.listing(tmp_path, 'Game A')
    assert [row['label'] for row in listed] == ['Main menu'] and listed[0]['preview'].startswith('data:image/webp')
    assert (listed[0]['width'], listed[0]['height']) == (2048, 1024)          # stored copy is bounded
    assert references.listing(tmp_path, 'Game B') == []
    assert source.is_file()                                                   # the owner's file is only copied
    with pytest.raises(ValueError, match='already pinned'):
        references.pin(tmp_path, 'Game A', source)
    with pytest.raises(ValueError, match='PNG, JPEG or WebP'):
        (tmp_path / 'notes.txt').write_text('x')
        references.pin(tmp_path, 'Game A', tmp_path / 'notes.txt')
    assert references.unpin(tmp_path, 'Game A', entry['id']) is True
    assert references.listing(tmp_path, 'Game A') == [] and source.is_file()
    with pytest.raises(ValueError):
        references.path_of(tmp_path, 'Game A', '../../secret')


def test_reference_limit(tmp_path):
    for index in range(references.MAX_REFERENCES):
        references.pin(tmp_path, 'P', picture(tmp_path / f'r{index}.png', (40, 40), (index * 10, 0, 0)))
    with pytest.raises(ValueError, match='at most 12'):
        references.pin(tmp_path, 'P', picture(tmp_path / 'extra.png', (40, 40), (1, 2, 3)))


def test_references_join_a_turn_about_looks_only(tmp_path):
    references.pin(tmp_path, 'P', picture(tmp_path / 'menu.png'), label='Main menu', note='gold on navy')
    paths, line = references.for_turn(tmp_path, 'P', 'Build the shop UI to match the reference')
    assert len(paths) == 1 and 'Main menu (gold on navy)' in line and 'one-to-one' in line
    assert references.for_turn(tmp_path, 'P', 'Why does my DataStore save fail?') == ([], '')
    assert references.for_turn(tmp_path, 'Other', 'Build the shop UI') == ([], '')
    assert references.for_turn(tmp_path, 'P', 'Build the shop UI', already=4) == ([], '')
    assert references.for_turn(tmp_path, 'P', 'Build the shop UI', enabled=False) == ([], '')


def test_measure_and_side_by_side(tmp_path):
    reference = picture(tmp_path / 'ref.png', (400, 300), (20, 20, 20))
    output = Image.new('RGB', (400, 400), (20, 20, 20))
    ImageDraw.Draw(output).rectangle((0, 300, 399, 399), fill=(250, 250, 250))
    output.save(tmp_path / 'out.png')
    facts = references.measure(reference, tmp_path / 'out.png')
    assert facts['reference_size'] == [400, 300] and facts['output_size'] == [400, 400]
    assert any(line.startswith('Shape differs') for line in facts['lines'])
    assert any('brighter' in line for line in facts['lines'])
    assert facts['most_different_regions'][0]['region'].startswith('bottom')
    same = references.measure(reference, reference)
    assert same['difference_percent'] == 0 and same['lines'] == ['No measurable difference at this scale (under 1.5% of the pixel range).']
    sheet = references.side_by_side(reference, tmp_path / 'out.png', tmp_path / 'sheet.png')
    with Image.open(sheet) as image:
        assert image.height == 768 + 34 and image.width > 1024


def test_compare_lists_the_models_differences_and_survives_its_absence(tmp_path):
    entry = references.pin(tmp_path, 'P', picture(tmp_path / 'ref.png', (400, 300), (20, 20, 20)), label='Menu')
    candidate = picture(tmp_path / 'out.png', (400, 300), (200, 200, 200))
    asked = {}

    def ask(settings, question, images, **kwargs):
        asked.update(question=question, images=images)
        return vision.Seen(text='- The title is centred instead of left.\n- Button is blue, not gold.\nNice work!',
                           model='star-vision', seconds=1.5, images=2)
    result = references.compare(server_settings(), tmp_path, 'P', entry['id'], candidate, ask=ask)
    assert result['differences'] == ['The title is centred instead of left.', 'Button is blue, not gold.']
    assert result['model'] == 'star-vision' and result['model_error'] == ''
    assert asked['images'][0] == references.path_of(tmp_path, 'P', entry['id']) and asked['images'][1] == candidate
    assert 'APPROVED REFERENCE' in asked['question'] and 'Do not praise' in asked['question']
    assert result['side_by_side'].is_file() and result['side_by_side'].parent == tmp_path / 'comparisons'

    def unreachable(*_, **__):
        raise ConnectionError('server is off')
    offline = references.compare(server_settings(), tmp_path, 'P', entry['id'], candidate, ask=unreachable)
    assert offline['differences'] == [] and 'ConnectionError' in offline['model_error']
    assert offline['measured']['lines'] and offline['side_by_side'].is_file()      # measured facts still stand


# ---- picture understanding ------------------------------------------------------------------

class FakeModel:
    def __init__(self, text='A fox on a log.'):
        self.text, self.calls = text, []
        self.chat = SimpleNamespace(completions=self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(model='star-fast', choices=[SimpleNamespace(message=SimpleNamespace(content=self.text))])


def test_vision_question_sends_the_pictures_capped_and_without_hidden_reasoning(tmp_path, monkeypatch):
    model = FakeModel()
    monkeypatch.setattr('star.providers.open_client', lambda settings, **kw: model)
    big = picture(tmp_path / 'screen.png', (2560, 1600))
    seen = vision.ask(server_settings(), 'What is this?', [big])
    assert seen.text == 'A fox on a log.' and seen.model == 'star-fast' and seen.images == 1
    call = model.calls[0]
    assert call['model'] == 'star-fast' and call['extra_body'] == {'chat_template_kwargs': {'enable_thinking': False}}
    parts = call['messages'][-1]['content']
    assert parts[0] == {'type': 'text', 'text': 'What is this?'} and parts[1]['type'] == 'image_url'
    import base64
    with Image.open(io.BytesIO(base64.b64decode(parts[1]['image_url']['url'].split(',', 1)[1]))) as sent:
        assert sent.size == (1280, 800)                                      # scaled for our own hardware
    with Image.open(big) as original:
        assert original.size == (2560, 1600)                                 # the file itself is unchanged
    with pytest.raises(ValueError, match='1-6 images'):
        vision.ask(server_settings(), 'x', [])


def test_picture_size_cap_applies_to_own_hardware_only(tmp_path):
    assert picture_limit(server_settings()) == 1280
    assert picture_limit(Settings(provider='local')) == 1280
    assert picture_limit(server_settings(picture_max_side=0)) is None
    assert picture_limit(Settings(provider='groq')) is None
    small = picture(tmp_path / 'small.png', (300, 200))
    assert image_part(small, 1280) == image_part(small)                      # smaller pictures are not touched
    with pytest.raises(ValueError, match='Picture size'):
        Settings(picture_max_side=100).validate()


# ---- video understanding --------------------------------------------------------------------

class FakeASR:
    model_name, device = 'small.en', 'cuda'

    def __init__(self, lines=('I am building a shop.', 'Then I test the remote event.')):
        self.lines, self.calls = list(lines), 0

    def transcribe(self, pcm: bytes, rate: int) -> str:
        self.calls += 1
        return self.lines.pop(0) if self.lines else ''


def fake_ffmpeg(monkeypatch, *, duration=75.0, audio=True, audio_seconds=45, level=3000):
    """Replace ffprobe/ffmpeg with stand-ins that write tiny frames and a steady-level sound track."""
    commands = []

    def run(command, timeout):
        commands.append(command)
        if 'ffprobe' in command[0]:
            streams = [{'codec_type': 'video', 'width': 1920, 'height': 1080}] + ([{'codec_type': 'audio'}] if audio else [])
            return SimpleNamespace(stdout=json.dumps({'format': {'duration': str(duration)}, 'streams': streams}), returncode=0)
        target = Path(command[-1])
        if target.suffix == '.jpg':
            Image.new('RGB', (768, 432), (10, 120, 60)).save(target)
        elif target.suffix == '.wav':
            with wave.open(str(target), 'wb') as out:
                out.setnchannels(1), out.setsampwidth(2), out.setframerate(16000)
                out.writeframes(int(level).to_bytes(2, 'little', signed=True) * 16000 * audio_seconds)
        return SimpleNamespace(stdout='', returncode=0)
    monkeypatch.setattr(video_understanding, '_run', run)
    monkeypatch.setattr(video_understanding, 'ffmpeg_tools', lambda folder='': ('ffmpeg', 'ffprobe'))
    return commands


def test_video_becomes_bounded_frames_plus_a_transcript(tmp_path, monkeypatch):
    commands = fake_ffmpeg(monkeypatch)
    clip = tmp_path / 'clip.mp4'
    clip.write_bytes(b'not really a video')
    asr = FakeASR()
    evidence = video_understanding.prepare(clip, tmp_path / 'work', frames=4, asr=asr)
    assert len(evidence.frames) == 4 and evidence.times == [9.4, 28.1, 46.9, 65.6]
    assert evidence.transcript == [(0.0, 'I am building a shop.'), (30.0, 'Then I test the remote event.')]
    assert asr.calls == 2 and evidence.asr == 'small.en on cuda'
    assert sum(1 for command in commands if command[-1].endswith('.jpg')) == 4
    text = video_understanding.evidence_text(evidence)
    assert '4 still frames sampled at 0:09, 0:28, 0:46, 1:05' in text and 'You have NOT seen what happens between them' in text
    assert '[0:30] Then I test the remote event.' in text and 'never fill a gap by guessing' in text
    footer = video_understanding.footer(evidence)
    assert 'Based on 4 sampled frames of "clip.mp4"' in footer and 'the rest of the video was not seen' in footer
    with pytest.raises(ValueError):
        video_understanding.prepare(clip, tmp_path / 'work', frames=9, asr=asr)


def test_video_without_sound_or_without_a_recogniser_says_so(tmp_path, monkeypatch):
    clip = tmp_path / 'clip.mp4'
    clip.write_bytes(b'x')
    fake_ffmpeg(monkeypatch, audio=False)
    silent = video_understanding.prepare(clip, tmp_path / 'a', frames=2, asr=FakeASR())
    assert silent.transcript == [] and silent.audio_note == 'The file has no sound track.'
    assert 'No transcript of the sound: The file has no sound track.' in video_understanding.evidence_text(silent)
    assert 'no transcript (the file has no sound track)' in video_understanding.footer(silent)

    fake_ffmpeg(monkeypatch, level=0)             # silence never reaches the recogniser, which would invent words
    listener = FakeASR()
    quiet = video_understanding.prepare(clip, tmp_path / 'q', frames=2, asr=listener)
    assert listener.calls == 0 and quiet.transcript == [] and quiet.audio_note.startswith('The sound track is silent')

    fake_ffmpeg(monkeypatch)

    def missing():
        raise ImportError('faster_whisper')
    monkeypatch.setattr(video_understanding, 'voice_asr', missing)
    deaf = video_understanding.prepare(clip, tmp_path / 'b', frames=2)
    assert deaf.transcript == [] and 'speech recogniser is unavailable' in deaf.audio_note and len(deaf.frames) == 2


def test_video_errors_are_plain(tmp_path, monkeypatch):
    with pytest.raises(video_understanding.VideoError, match='Unsupported video type'):
        notes = tmp_path / 'a.txt'
        notes.write_text('x')
        video_understanding.prepare(notes, tmp_path / 'w')
    monkeypatch.setattr(video_understanding.shutil, 'which', lambda name, path=None: None)
    monkeypatch.delenv('STAR_FFMPEG_DIR', raising=False)
    clip = tmp_path / 'clip.mp4'
    clip.write_bytes(b'x')
    with pytest.raises(video_understanding.VideoError, match='FFmpeg was not found'):
        video_understanding.prepare(clip, tmp_path / 'w')


def test_a_link_or_title_is_never_a_watched_video():
    rule = video_understanding.link_only_note('Summarise https://www.youtube.com/watch?v=abc123 for me', False)
    assert 'You have NOT watched it' in rule and 'attaches the video file' in rule
    assert video_understanding.link_only_note('https://youtu.be/abc what happens at the end?', False) == rule
    assert video_understanding.link_only_note('see https://example.com/clips/intro.mp4', False) == rule
    assert video_understanding.link_only_note('Summarise https://www.youtube.com/watch?v=abc123', True) == ''
    assert video_understanding.link_only_note('How do I add a video to my Roblox game?', False) == ''


def test_chat_turn_with_a_video(tmp_path, monkeypatch):
    monkeypatch.setattr('star.providers.get_api_key', lambda name: 'k' * 20)
    fake_ffmpeg(monkeypatch)
    clip = tmp_path / 'clip.mp4'
    clip.write_bytes(b'x')
    shot = picture(tmp_path / 'shot.png')
    turn = chat_media.prepare_turn(server_settings(), tmp_path, 'What happens here?', [shot, clip], tmp_path / 'w',
                                   asr=FakeASR())
    assert turn.pictures[0] == shot and len(turn.pictures) == 4               # 1 picture + 3 frames: the cap is 4
    assert turn.video is not None and len(turn.video.frames) == 3
    assert 'VIDEO FILE "clip.mp4"' in turn.prompt('What happens here?') and turn.footer.startswith('\n\n_Based on 3 sampled frames')
    with pytest.raises(media_places.PlaceUnavailable):                         # a hosted provider never gets the frames
        chat_media.prepare_turn(Settings(provider='groq', server_endpoint=LAN, model='m', project='Test'), tmp_path,
                                'What happens here?', [clip], tmp_path / 'w2', asr=FakeASR())
    with pytest.raises(ValueError, match='one video at a time'):
        chat_media.prepare_turn(server_settings(), tmp_path, 'x', [clip, clip.with_name('b.mp4')], tmp_path / 'w3')


def test_chat_turn_with_only_a_video_link_or_with_references(tmp_path, monkeypatch):
    linked = chat_media.prepare_turn(server_settings(), tmp_path, 'What is in https://youtu.be/xyz ?', [], tmp_path / 'w')
    assert linked.pictures == [] and 'You have NOT watched it' in linked.prompt('q') and linked.footer == ''
    references.pin(tmp_path, 'Test', picture(tmp_path / 'menu.png'), label='Main menu')
    plain = chat_media.prepare_turn(server_settings(), tmp_path, 'Build the shop UI', [], tmp_path / 'w')
    assert plain.pictures == [] and plain.references == 0                      # no vision model known: nothing is added
    with_vision = server_settings(vision_model='star-vision')
    turn = chat_media.prepare_turn(with_vision, tmp_path, 'Build the shop UI', [], tmp_path / 'w')
    assert turn.references == 1 and len(turn.pictures) == 1 and 'Approved visual reference' in turn.prompt('q')
    code = chat_media.prepare_turn(with_vision, tmp_path, 'Fix this pcall error', [], tmp_path / 'w')
    assert code.pictures == [] and code.extras == []


# ---- bridge actions -------------------------------------------------------------------------

def test_media_actions(tmp_path, monkeypatch):
    settings = server_settings()
    allowed = {picture(tmp_path / 'ok.png', (300, 200), (9, 9, 9)).resolve(), picture(tmp_path / 'out.png', (300, 200)).resolve()}

    def allowed_file(path: Path) -> Path:
        if path.resolve() not in allowed:
            raise PermissionError('Choose the file through STAR Attach before using it')
        return path.resolve()
    kwargs = dict(settings=settings, home=tmp_path, allowed_file=allowed_file)
    pinned = media_actions.handle('pinReference', {'file': str(tmp_path / 'ok.png'), 'label': 'Menu'}, **kwargs)
    assert [row['label'] for row in pinned['references']] == ['Menu']
    with pytest.raises(PermissionError):
        media_actions.handle('pinReference', {'file': str(picture(tmp_path / 'sneaky.png'))}, **kwargs)
    listed = media_actions.handle('listReferences', {}, **kwargs)
    assert listed['limit'] == 12 and listed['enabled'] is True and len(listed['references']) == 1
    with pytest.raises(ValueError, match='no generated image to compare yet'):
        media_actions.handle('compareReference', {'id': pinned['pinned']}, **kwargs)
    ask = lambda *a, **k: vision.Seen('- Background is blue instead of black.', 'star-vision', 2.0, 2)   # noqa: E731
    compared = media_actions.handle('compareReference', {'id': pinned['pinned'], 'file': str(tmp_path / 'out.png')},
                                    ask=ask, **kwargs)
    assert compared['differences'] == ['Background is blue instead of black.'] and compared['image'].startswith('data:image/webp')
    assert compared['candidate'] == 'out.png' and isinstance(compared['measured']['lines'], list)
    removed = media_actions.handle('unpinReference', {'id': pinned['pinned']}, **kwargs)
    assert removed['removed'] is True and removed['references'] == []
    with pytest.raises(PermissionError):
        media_actions.handle('deleteEverything', {}, **kwargs)

    monkeypatch.setattr(image_gen, 'status', lambda s: {'running': False, 'ready': False, 'missing': [], 'message': 'off'})
    monkeypatch.setattr('star.providers.get_api_key', lambda name: None)
    monkeypatch.setattr(media_actions, 'detect_comfy_home', lambda: '')       # not the ComfyUI of this PC
    state = media_actions.handle('mediaStatus', {}, **kwargs)
    assert [entry['id'] for entry in state['places']] == ['images', 'voice', 'video']
    assert state['images']['message'] == 'off' and [size['id'] for size in state['sizes']] == ['square', 'wide', 'tall', 'draft']
    assert state['can_start'] is False and isinstance(state['ffmpeg']['found'], bool)


def test_launcher_only_ever_binds_this_computer(tmp_path):
    with pytest.raises(ValueError, match='ComfyUI folder'):
        media_actions.ComfyLauncher.command('', 8188)
    with pytest.raises(ValueError, match='main.py'):
        media_actions.ComfyLauncher.command(str(tmp_path), 8188)
    (tmp_path / 'main.py').write_text('')
    with pytest.raises(ValueError, match='own Python'):
        media_actions.ComfyLauncher.command(str(tmp_path), 8188)
    scripts = tmp_path / '.venv' / 'Scripts'
    scripts.mkdir(parents=True)
    (scripts / 'python.exe').write_text('')
    command, folder = media_actions.ComfyLauncher.command(str(tmp_path), 8190)
    assert command[1:] == ['main.py', '--listen', '127.0.0.1', '--port', '8190', '--disable-auto-launch']
    assert folder == tmp_path
    launcher = media_actions.ComfyLauncher()
    already = launcher.start(Settings(comfy_home=str(tmp_path)), tmp_path, is_up=lambda: True)
    assert already == {'started': False, 'running': True, 'message': 'ComfyUI is already running.'}


def _comfy_install(folder):
    folder.mkdir(parents=True)
    (folder / 'main.py').write_text('')
    (folder / '.venv' / 'Scripts').mkdir(parents=True)
    (folder / '.venv' / 'Scripts' / 'python.exe').write_text('')
    return str(folder)


def test_comfyui_is_found_on_its_own_only_in_the_fixed_places(tmp_path):
    profile = tmp_path / 'profile'
    nowhere = dict(env={}, data_dir=tmp_path / 'data', user_home=profile)
    code = profile / 'Documents' / 'work' / 'Star-AI'
    code.mkdir(parents=True)
    assert media_actions.find_comfy_home(search_from=(code,), **nowhere) == ''
    # next to the code, up to four levels above it, inside the user's profile
    found = _comfy_install(profile / 'Documents' / 'work' / 'media' / 'ComfyUI')
    assert media_actions.find_comfy_home(search_from=(code,), **nowhere) == found
    deep = code / 'worktrees' / 'wt-one' / 'star'
    deep.mkdir(parents=True)
    assert media_actions.find_comfy_home(search_from=(deep,), **nowhere) == found
    # the environment variable and STAR's own data folder come first
    mine = _comfy_install(tmp_path / 'data' / 'media' / 'ComfyUI')
    assert media_actions.find_comfy_home(search_from=(code,), **nowhere) == mine
    named = _comfy_install(tmp_path / 'chosen' / 'ComfyUI')
    assert media_actions.find_comfy_home(search_from=(code,), **{**nowhere, 'env': {'STAR_COMFY_HOME': named}}) == named


def test_comfyui_is_found_in_the_projects_media_folder_inside_the_profile(tmp_path):
    profile = tmp_path / 'profile'
    nowhere = dict(env={}, data_dir=tmp_path / 'data', user_home=profile)
    elsewhere = tmp_path / 'Program Files' / 'STAR'
    elsewhere.mkdir(parents=True)
    assert media_actions.find_comfy_home(search_from=(elsewhere,), **nowhere) == ''
    found = _comfy_install(profile / 'Documents' / 'starai' / 'media' / 'ComfyUI')
    assert media_actions.find_comfy_home(search_from=(elsewhere,), **nowhere) == found


def test_a_folder_that_is_not_a_complete_install_or_sits_outside_the_profile_is_not_used(tmp_path):
    profile = tmp_path / 'profile'
    code = profile / 'work' / 'Star-AI'
    code.mkdir(parents=True)
    options = dict(env={}, data_dir=tmp_path / 'data', user_home=profile, search_from=(code,))
    half = profile / 'work' / 'media' / 'ComfyUI'
    half.mkdir(parents=True)
    (half / 'main.py').write_text('')                       # no ComfyUI Python of its own
    assert media_actions.find_comfy_home(**options) == ''
    # a drive-root style folder that any user of the PC could have made: climbing stops at the profile
    _comfy_install(tmp_path / 'media' / 'ComfyUI')
    assert media_actions.find_comfy_home(**options) == ''
    assert media_actions.find_comfy_home(**{**options, 'env': {'STAR_COMFY_HOME': str(tmp_path / 'missing')}}) == ''


def test_a_folder_chosen_in_settings_is_never_replaced_by_a_found_one(tmp_path, monkeypatch):
    monkeypatch.setattr(media_actions, 'detect_comfy_home', lambda: str(tmp_path / 'found'))
    assert media_actions.effective_comfy_home(Settings(comfy_home='  ')) == str(tmp_path / 'found')
    assert media_actions.effective_comfy_home(Settings(comfy_home=str(tmp_path / 'mine'))) == str(tmp_path / 'mine')


def test_a_start_that_never_answers_is_stopped_again(tmp_path, monkeypatch):
    (tmp_path / 'main.py').write_text('')
    scripts = tmp_path / '.venv' / 'Scripts'
    scripts.mkdir(parents=True)
    (scripts / 'python.exe').write_text('')
    started, ended = [], []

    class Hung:
        pid = 4242

        def __init__(self, command, **kwargs):
            started.append((command, kwargs['cwd']))
            self.alive = True

        def poll(self):
            return None if self.alive else 1

        def terminate(self):
            self.alive = False

        def kill(self):
            self.alive = False

        def wait(self, timeout=None):
            self.alive = False
            return 1

    def run(command, **_):
        ended.append(command)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(media_actions.subprocess, 'Popen', Hung)
    monkeypatch.setattr(media_actions.subprocess, 'run', run)
    launcher = media_actions.ComfyLauncher()
    with pytest.raises(TimeoutError, match='STAR stopped it again'):
        launcher.start(Settings(comfy_home=str(tmp_path)), tmp_path / 'home', wait_seconds=0.05, is_up=lambda: False)
    assert len(started) == 1 and '--listen' in started[0][0] and started[0][1] == str(tmp_path)
    assert not launcher.running()                         # nothing is left holding the graphics card
    if os.name == 'nt':
        assert ended and ended[0][:3] == ['taskkill', '/PID', '4242'] and '/T' in ended[0]
    assert (tmp_path / 'home' / 'logs' / 'comfyui.log').is_file()


def test_bridge_allows_the_media_actions_and_words_failures_for_the_owner():
    from star.react_shell import ALLOWED_ACTIONS, PERMITTED_SETTINGS, failure_outcome
    assert media_actions.MEDIA_ACTIONS <= ALLOWED_ACTIONS
    assert {'media_images', 'media_voice', 'media_video', 'media_use_references', 'comfy_home', 'ffmpeg_dir',
            'picture_max_side'} <= PERMITTED_SETTINGS
    status, message = failure_outcome('generateImage', ComfyError('not_running', 'ComfyUI is not running on this PC. Start it.'))
    assert (status, message) == ('failed', 'ComfyUI is not running on this PC. Start it.')
    long_reason = media_places.PlaceUnavailable('Images is set to STAR Brains (servers). ' + 'x' * 500)
    assert len(failure_outcome('generateImage', long_reason)[1]) > 400          # the reason is not cut mid-sentence
    assert failure_outcome('sendMessage', video_understanding.VideoError('FFmpeg was not found.'))[1] == 'FFmpeg was not found.'


# ---- live: skipped unless the real service is there -----------------------------------------

def _comfy_is_up() -> bool:
    try:
        with ComfyClient(timeout=2.0) as comfy:
            return comfy.status()['running'] and not comfy.missing_models()
    except Exception:
        return False


@pytest.mark.skipif(os.environ.get('STAR_LIVE_COMFY') != '1', reason='set STAR_LIVE_COMFY=1 with ComfyUI running on 127.0.0.1:8188')
def test_live_image_generation_on_this_pc(tmp_path):
    if not _comfy_is_up():
        pytest.skip('ComfyUI with the klein model is not running on 127.0.0.1:8188')
    made = image_gen.generate(Settings(project='Live'), 'a small blue teapot on a wooden table', tmp_path, size='draft', seed=3)
    with Image.open(made['path']) as image:
        assert image.size == (512, 512)
        assert ImageChops.difference(image.convert('RGB'), Image.new('RGB', image.size, image.getpixel((0, 0)))).getbbox()
    edited = image_gen.generate(Settings(project='Live'), 'make the teapot red', tmp_path, size='draft', source=made['path'], seed=4)
    assert edited['note']['mode'] == 'edit' and edited['path'].is_file()


def _live_server() -> Settings | None:
    url = os.environ.get('STAR_LIVE_SERVER_URL', '').strip()
    if not url or not os.environ.get('STAR_SERVER_API_KEY', '').strip():
        return None
    return Settings(provider='star_server', server_endpoint=url.rstrip('/'), model='star-fast', project='Live')


@pytest.mark.skipif(_live_server() is None, reason='set STAR_LIVE_SERVER_URL and STAR_SERVER_API_KEY')
def test_live_picture_understanding_on_the_server(tmp_path):
    sign = Image.new('RGB', (512, 256), (255, 255, 255))
    ImageDraw.Draw(sign).rectangle((40, 40, 240, 216), fill=(220, 20, 20))
    sign.save(tmp_path / 'sign.png')
    seen = vision.ask(_live_server(), 'What colour is the rectangle? One word.', [tmp_path / 'sign.png'], max_tokens=20)
    assert 'red' in seen.text.lower() and seen.seconds > 0


@pytest.mark.skipif(_live_server() is None or not shutil.which('ffmpeg'), reason='needs the server variables and ffmpeg on PATH')
def test_live_video_understanding_on_the_server(tmp_path):
    import subprocess
    clip = tmp_path / 'bars.mp4'
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=640x360:d=3',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3', '-shortest', '-pix_fmt', 'yuv420p', '-y', str(clip)],
                   check=True, timeout=60)
    evidence = video_understanding.prepare(clip, tmp_path / 'work', frames=2)
    assert len(evidence.frames) == 2 and evidence.has_audio
    seen = vision.ask(_live_server(), video_understanding.evidence_text(evidence) + '\n\nQuestion: what colour fills the frames? One word.',
                      evidence.frames, max_tokens=20)
    assert 'blue' in seen.text.lower()


@pytest.mark.skipif(os.environ.get('STAR_LIVE_VOICE') != '1', reason='set STAR_LIVE_VOICE=1 with the voice extras installed')
def test_live_speech_recogniser_loads_where_the_switch_says(tmp_path):
    assert media_places.require(Settings(), 'voice', tmp_path) == 'pc'
    asr = video_understanding.voice_asr()
    # Given pure silence Whisper may still write a stray word, which is why video pieces below
    # QUIET_LEVEL are not sent to it; here only loading and running on the chosen device is checked.
    assert asr.device in ('cuda', 'cpu') and isinstance(asr.transcribe(b'\x00\x00' * 16000, 16000), str)


def test_documents_go_to_the_document_tools_not_to_the_picture_model(tmp_path):
    notes = tmp_path / 'design.md'
    notes.write_text('# Shop\nGold buttons.', encoding='utf-8')
    sheet = tmp_path / 'prices.csv'
    sheet.write_text('item,price\nsword,10\n', encoding='utf-8')
    shot = picture(tmp_path / 'shot.png')
    turn = chat_media.prepare_turn(server_settings(), tmp_path, 'Check the prices against the design', [notes, shot, sheet],
                                   tmp_path / 'w')
    assert turn.documents == [notes, sheet] and turn.pictures == [shot] and turn.extras == []
