"""Minimal local ComfyUI workflow runner. No hosted image API is required.

ComfyUI workflows can contain third-party nodes. STAR only runs a conservative
set of known local core nodes by default. Operators can extend this list in a
reviewed code change rather than asking an LLM to silently execute unknown nodes.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
import re
import time
from urllib.parse import urlencode
from ._lazy import lazy_module
from typing import TYPE_CHECKING
if TYPE_CHECKING:  # type checkers see the real module; at run time it loads on first use
    import httpx
else:
    httpx = lazy_module("httpx")  # loaded on first request, not when the desktop starts

LOCAL_CLASSES = frozenset({
    'CheckpointLoaderSimple', 'CLIPTextEncode', 'EmptyLatentImage', 'KSampler',
    'KSamplerAdvanced', 'VAEDecode', 'VAEEncode', 'SaveImage', 'LoadImage',
    'LoraLoader', 'LoraLoaderModelOnly', 'CLIPSetLastLayer', 'LatentUpscale',
    'ImageScale', 'ImageScaleBy', 'VAELoader', 'CLIPLoader', 'UNETLoader',
    'ConditioningCombine', 'ConditioningSetArea', 'ConditioningAverage',
})


def load_workflow(path: Path, *, prompt_text: str, prompt_node: str):
    path=path.expanduser().resolve(strict=True)
    if path.suffix.lower() != '.json' or path.stat().st_size > 2_000_000:
        raise ValueError('Use a small ComfyUI API-format JSON workflow')
    raw=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(raw,dict) or not raw:
        raise ValueError('Invalid API workflow. Export using ComfyUI Save (API format).')
    for node_id,node in raw.items():
        if not isinstance(node,dict) or node.get('class_type') not in LOCAL_CLASSES:
            raise PermissionError(f'Unreviewed or external workflow node {node_id}: {node.get("class_type") if isinstance(node,dict) else "invalid"}')
    if prompt_node not in raw or raw[prompt_node].get('class_type')!='CLIPTextEncode':
        raise ValueError('Prompt node must be the ID of a CLIPTextEncode node')
    # A hand-edited export can lack the inputs block; that used to surface as a bare KeyError.
    if not isinstance(raw[prompt_node].get('inputs'),dict):
        raise ValueError('The prompt node has no inputs. Export using ComfyUI Save (API format).')
    if not 1 <= len(prompt_text) <= 1500:
        raise ValueError('Prompt must be 1-1500 characters')
    result=copy.deepcopy(raw)
    result[prompt_node]['inputs']['text']=prompt_text
    return result


def generate(workflow_file: Path, *, prompt: str, node_id: str, output: Path, port: int = 8188,
             timeout_seconds: int = 360, cancel_event=None):
    if not 1<=port<=65535:
        raise ValueError('Invalid local ComfyUI port')
    flow=load_workflow(workflow_file, prompt_text=prompt, prompt_node=node_id)
    url=f'http://127.0.0.1:{port}'
    output.mkdir(parents=True,exist_ok=True)
    with httpx.Client(timeout=30, trust_env=False) as client:
        reply=client.post(url+'/prompt',json={'prompt':flow,'client_id':'star-local-desktop'})
        reply.raise_for_status()
        payload=reply.json()
        job=payload.get('prompt_id')
        if not isinstance(job,str) or not re.fullmatch(r'[A-Za-z0-9-]{8,80}',job):
            raise RuntimeError('ComfyUI did not return a valid prompt ID: '+str(payload)[:400])
        finish=time.monotonic()+timeout_seconds
        images=[]
        while time.monotonic()<finish:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError('STAR image generation cancelled by user; the ComfyUI server may still finish the queued job')
            history=client.get(url+'/history/'+job)
            history.raise_for_status()
            detail=history.json().get(job)
            if detail:
                status=detail.get('status',{})
                if status.get('status_str')=='error':
                    raise RuntimeError('ComfyUI generation failed: '+str(status)[:500])
                for node in detail.get('outputs',{}).values():
                    for result in node.get('images',[]):
                        name=result.get('filename','')
                        # ':' would write into an NTFS alternate stream of another file instead of a picture.
                        if not isinstance(name,str) or not name or any(c in name for c in '/\\:') or name in ('.','..'):
                            continue
                        params={'filename':name,'type':result.get('type','output'),'subfolder':result.get('subfolder','')}
                        if params['type'] not in {'output','temp'}:
                            continue
                        if params['subfolder'] and ('..' in params['subfolder'] or params['subfolder'].startswith(('/','\\'))):
                            continue
                        img=client.get(url+'/view',params=params)
                        img.raise_for_status()
                        if len(img.content)>25_000_000:
                            raise ValueError('Generated image exceeds 25 MB limit')
                        new_path=output/(f'{job[:8]}_{len(images)}_'+name)
                        new_path.write_bytes(img.content)
                        images.append(new_path)
                if images:
                    return images
                if status.get('completed'):
                    raise RuntimeError('ComfyUI finished but no SaveImage output was found')
            time.sleep(2)
        raise TimeoutError('ComfyUI job did not finish within allotted time')


# ---- Built-in image model: FLUX.2 klein 4B (distilled), driven through ComfyUI's own nodes --------
#
# The workflows below are STAR's own, written from the templates ComfyUI ships for this model
# (text to image, image edit with reference latents). They use only nodes that are part of
# ComfyUI itself, so nothing here installs or needs a custom node.

KLEIN_FILES = {
    'diffusion_models': 'flux-2-klein-4b-fp8.safetensors',
    'text_encoders': 'qwen_3_4b_fp4_flux2.safetensors',
    'vae': 'flux2-vae.safetensors',
}
KLEIN_NAME = 'FLUX.2 klein 4B (distilled, fp8)'
# Z-Image Turbo (Tongyi-MAI, Apache-2.0), Comfy-Org repack. The bf16 file is 12.3 GB and streams through the 8 GB card.
ZIMAGE_FILES = {
    'diffusion_models': 'z_image_turbo_bf16.safetensors',
    'text_encoders': 'qwen_3_4b_fp4_mixed.safetensors',
    'vae': 'ae.safetensors',
}
ZIMAGE_NAME = 'Z-Image Turbo (bf16)'
ZIMAGE_STEPS = 8               # what the model is trained for
ZIMAGE_STEPS_FAST = 5          # drafts: 4, 5, 6 and 8 steps look the same on six hard prompts, one step of margin over 4 (docs/agents/image-quality-2-20261026.md)
ENGINES = {'klein': (KLEIN_NAME, KLEIN_FILES), 'zimage': (ZIMAGE_NAME, ZIMAGE_FILES)}
KLEIN_STEPS = 4
START_HINT = ('Start it in Settings → Where STAR generates → Start ComfyUI '
              '(or run scripts/media/start_comfyui.sh), then try again.')
SETUP_HINT = ('Run scripts/media/setup_comfyui.sh models to download the model files '
              '(8.26 GB in total), then try again.')
MEMORY_HINT = ('STAR asked ComfyUI to unload its models to free the memory. Close other programs that '
               'use the graphics card (a game, a voice call, another image job) or choose the Draft '
               'size, then try again.')


class ComfyError(RuntimeError):
    """A failure the owner can act on. `kind` is stable; the message is the whole explanation."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def _klein_base(prompt: str, width: int, height: int, seed: int) -> dict:
    return {
        'unet': {'class_type': 'UNETLoader',
                 'inputs': {'unet_name': KLEIN_FILES['diffusion_models'], 'weight_dtype': 'default'}},
        'clip': {'class_type': 'CLIPLoader',
                 'inputs': {'clip_name': KLEIN_FILES['text_encoders'], 'type': 'flux2', 'device': 'default'}},
        'vae': {'class_type': 'VAELoader', 'inputs': {'vae_name': KLEIN_FILES['vae']}},
        'text': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['clip', 0], 'text': prompt}},
        'blank': {'class_type': 'ConditioningZeroOut', 'inputs': {'conditioning': ['text', 0]}},
        'sampler': {'class_type': 'KSamplerSelect', 'inputs': {'sampler_name': 'euler'}},
        'sigmas': {'class_type': 'Flux2Scheduler',
                   'inputs': {'steps': KLEIN_STEPS, 'width': width, 'height': height}},
        'noise': {'class_type': 'RandomNoise', 'inputs': {'noise_seed': seed}},
        'latent': {'class_type': 'EmptyFlux2LatentImage',
                   'inputs': {'width': width, 'height': height, 'batch_size': 1}},
        'guider': {'class_type': 'CFGGuider',
                   'inputs': {'model': ['unet', 0], 'positive': ['text', 0], 'negative': ['blank', 0], 'cfg': 1.0}},
        'sample': {'class_type': 'SamplerCustomAdvanced',
                   'inputs': {'noise': ['noise', 0], 'guider': ['guider', 0], 'sampler': ['sampler', 0],
                              'sigmas': ['sigmas', 0], 'latent_image': ['latent', 0]}},
        'decode': {'class_type': 'VAEDecode', 'inputs': {'samples': ['sample', 0], 'vae': ['vae', 0]}},
        # PreviewImage keeps ComfyUI's own output folder empty: the one original lives in STAR's data.
        'out': {'class_type': 'PreviewImage', 'inputs': {'images': ['decode', 0]}},
    }


def zimage_text_to_image(prompt: str, width: int, height: int, seed: int, steps: int = ZIMAGE_STEPS) -> dict:
    """Z-Image Turbo text to image (CFG 1, no negative: the model is distilled). ComfyUI nodes only."""
    return {
        'unet': {'class_type': 'UNETLoader',
                 'inputs': {'unet_name': ZIMAGE_FILES['diffusion_models'], 'weight_dtype': 'default'}},
        'clip': {'class_type': 'CLIPLoader',
                 'inputs': {'clip_name': ZIMAGE_FILES['text_encoders'], 'type': 'lumina2', 'device': 'default'}},
        'vae': {'class_type': 'VAELoader', 'inputs': {'vae_name': ZIMAGE_FILES['vae']}},
        'text': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['clip', 0], 'text': prompt}},
        'blank': {'class_type': 'ConditioningZeroOut', 'inputs': {'conditioning': ['text', 0]}},
        'model': {'class_type': 'ModelSamplingAuraFlow', 'inputs': {'model': ['unet', 0], 'shift': 3.0}},
        'latent': {'class_type': 'EmptySD3LatentImage', 'inputs': {'width': width, 'height': height, 'batch_size': 1}},
        'sample': {'class_type': 'KSampler',
                   'inputs': {'model': ['model', 0], 'positive': ['text', 0], 'negative': ['blank', 0],
                              'latent_image': ['latent', 0], 'seed': seed, 'steps': steps, 'cfg': 1.0,
                              'sampler_name': 'res_multistep', 'scheduler': 'simple', 'denoise': 1.0}},
        'decode': {'class_type': 'VAEDecode', 'inputs': {'samples': ['sample', 0], 'vae': ['vae', 0]}},
        'out': {'class_type': 'PreviewImage', 'inputs': {'images': ['decode', 0]}},
    }


def zimage_inpaint(prompt: str, image_name: str, mask_name: str, width: int, height: int, seed: int,
                   denoise: float = 0.78, steps: int = ZIMAGE_STEPS) -> dict:
    """Masked repaint with Z-Image itself (white = may change). The same model that drew the picture repairs it, so the
    8 GB card never swaps models. `image_name` and `mask_name` must already be width x height."""
    flow = zimage_text_to_image(prompt, width, height, seed, steps)
    del flow['latent']
    flow['source'] = {'class_type': 'LoadImage', 'inputs': {'image': image_name}}
    flow['encode'] = {'class_type': 'VAEEncode', 'inputs': {'pixels': ['source', 0], 'vae': ['vae', 0]}}
    flow['mask_image'] = {'class_type': 'LoadImage', 'inputs': {'image': mask_name}}
    flow['mask'] = {'class_type': 'ImageToMask', 'inputs': {'image': ['mask_image', 0], 'channel': 'red'}}
    flow['masked'] = {'class_type': 'SetLatentNoiseMask', 'inputs': {'samples': ['encode', 0], 'mask': ['mask', 0]}}
    flow['sample']['inputs'].update({'latent_image': ['masked', 0], 'denoise': denoise})
    return flow


def _add_reference(flow: dict, key: str, image_name: str, megapixels: float | None) -> str:
    """Encode an uploaded image and chain it onto both conditionings. Returns its latent node id."""
    flow[f'{key}_image'] = {'class_type': 'LoadImage', 'inputs': {'image': image_name}}
    pixels = [f'{key}_image', 0]
    if megapixels:
        flow[f'{key}_scale'] = {'class_type': 'ImageScaleToTotalPixels',
                                'inputs': {'image': pixels, 'upscale_method': 'area',
                                           'megapixels': megapixels, 'resolution_steps': 16}}
        pixels = [f'{key}_scale', 0]
    flow[f'{key}_latent'] = {'class_type': 'VAEEncode', 'inputs': {'pixels': pixels, 'vae': ['vae', 0]}}
    for side in ('positive', 'negative'):
        flow[f'{key}_{side}'] = {'class_type': 'ReferenceLatent',
                                 'inputs': {'conditioning': flow['guider']['inputs'][side],
                                            'latent': [f'{key}_latent', 0]}}
        flow['guider']['inputs'][side] = [f'{key}_{side}', 0]
    return f'{key}_latent'


def klein_text_to_image(prompt: str, width: int, height: int, seed: int,
                        references: tuple[str, ...] = (), reference_megapixels: float = 0.5) -> dict:
    """Text to image; `references` are uploaded image names the picture should follow."""
    flow = _klein_base(prompt, width, height, seed)
    for index, name in enumerate(references):
        _add_reference(flow, f'ref{index}', name, reference_megapixels)
    return flow


def klein_edit(prompt: str, image_name: str, width: int, height: int, seed: int,
               mask_name: str | None = None, references: tuple[str, ...] = (),
               reference_megapixels: float = 0.5) -> dict:
    """Edit an uploaded image by instruction. `image_name` must already be width x height.

    With `mask_name` (red channel: white = the area to change) sampling starts from the image
    itself and only the masked area is regenerated.
    """
    flow = _klein_base(prompt, width, height, seed)
    source_latent = _add_reference(flow, 'src', image_name, None)
    for index, name in enumerate(references):
        _add_reference(flow, f'ref{index}', name, reference_megapixels)
    if mask_name:
        flow['mask_image'] = {'class_type': 'LoadImage', 'inputs': {'image': mask_name}}
        flow['mask'] = {'class_type': 'ImageToMask', 'inputs': {'image': ['mask_image', 0], 'channel': 'red'}}
        flow['masked'] = {'class_type': 'SetLatentNoiseMask',
                          'inputs': {'samples': [source_latent, 0], 'mask': ['mask', 0]}}
        flow['sample']['inputs']['latent_image'] = ['masked', 0]
    return flow


def _is_memory_error(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in (
        'outofmemory', 'out of memory', 'allocation on device', 'not enough memory', 'failed to allocate'))


class ComfyClient:
    """The ComfyUI on this computer (127.0.0.1 only: it has no sign-in of its own)."""

    def __init__(self, port: int = 8188, *, timeout: float = 30.0, transport=None, poll: float = 0.5):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('Invalid local ComfyUI port')
        self.port, self.poll = port, poll
        self.url = f'http://127.0.0.1:{port}'
        self._http = httpx.Client(base_url=self.url, timeout=timeout, trust_env=False, transport=transport)

    def close(self) -> None:
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _call(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            return self._http.request(method, path, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ComfyError('not_running', f'ComfyUI is not running on this PC (127.0.0.1:{self.port}). '
                             + START_HINT) from exc
        except httpx.TimeoutException as exc:
            raise ComfyError('timeout', 'ComfyUI on this PC stopped answering. If it is busy reading the '
                             'model for the first time, wait a minute and try again.') from exc

    def status(self) -> dict:
        """Version and graphics memory. Raises ComfyError('not_running') when nothing answers."""
        reply = self._call('GET', '/system_stats', timeout=5.0)
        reply.raise_for_status()
        data = reply.json()
        device = (data.get('devices') or [{}])[0]
        return {'running': True, 'version': str((data.get('system') or {}).get('comfyui_version', ''))[:40],
                'device': str(device.get('name', ''))[:120], 'device_type': str(device.get('type', ''))[:20],
                'vram_total': int(device.get('vram_total') or 0), 'vram_free': int(device.get('vram_free') or 0)}

    def missing_models(self, engine: str = 'klein') -> list[str]:
        """Model files the built-in workflows need that ComfyUI does not list."""
        missing = []
        for folder, name in ENGINES[engine][1].items():
            reply = self._call('GET', f'/models/{folder}', timeout=10.0)
            listed = reply.json() if reply.status_code == 200 else []
            if name not in (listed if isinstance(listed, list) else []):
                missing.append(f'models/{folder}/{name}')
        return missing

    def upload(self, content: bytes, name: str) -> str:
        """Put a PNG into ComfyUI's input folder (fixed names are overwritten, so nothing piles up)."""
        if not re.fullmatch(r'[a-z0-9_]{1,40}\.png', name):
            raise ValueError('Invalid upload name')
        reply = self._call('POST', '/upload/image', files={'image': (name, content, 'image/png')},
                           data={'overwrite': 'true', 'type': 'input', 'subfolder': 'star'})
        if reply.status_code != 200:
            raise ComfyError('failed', f'ComfyUI refused the image upload (HTTP {reply.status_code}).')
        saved = reply.json()
        folder = str(saved.get('subfolder') or '')
        return (folder + '/' if folder else '') + str(saved.get('name') or name)

    def free(self) -> bool:
        """Ask ComfyUI to unload its models and give the graphics memory back."""
        try:
            return self._call('POST', '/free', json={'unload_models': True, 'free_memory': True}).status_code == 200
        except ComfyError:
            return False

    def interrupt(self) -> None:
        try:
            self._call('POST', '/interrupt', json={})
        except ComfyError:
            pass

    def _queue(self, workflow: dict) -> str:
        reply = self._call('POST', '/prompt', json={'prompt': workflow, 'client_id': 'star-local-desktop'})
        if reply.status_code == 400:
            try:
                body = reply.json()
            except ValueError:
                body = {}
            for node in (body.get('node_errors') or {}).values():
                for error in node.get('errors') or []:
                    detail = str(error.get('details', ''))
                    if error.get('type') == 'value_not_in_list' and re.match(r'(unet|clip|vae)_name\b', detail):
                        wanted = re.search(r"'([^']+)'", detail)
                        raise ComfyError('model_missing',
                                         f"ComfyUI does not have the model file {wanted.group(1) if wanted else ''} "
                                         'in its models folder. ' + SETUP_HINT)
                    if error.get('type') == 'value_not_in_list' and detail.startswith('image'):
                        raise ComfyError('failed', 'ComfyUI could not find the uploaded picture. Try again.')
            message = str((body.get('error') or {}).get('message', ''))[:300]
            raise ComfyError('rejected', 'ComfyUI rejected the request: ' + (message or 'HTTP 400')
                             + '. This STAR build expects ComfyUI v0.39.0 or newer.')
        reply.raise_for_status()
        job = reply.json().get('prompt_id')
        if not isinstance(job, str) or not re.fullmatch(r'[A-Za-z0-9-]{8,80}', job):
            raise ComfyError('failed', 'ComfyUI did not return a valid job id')
        return job

    def _failure(self, status: dict) -> ComfyError:
        detail = ''
        for entry in status.get('messages') or []:
            if isinstance(entry, (list, tuple)) and len(entry) == 2 and entry[0] == 'execution_error':
                info = entry[1] if isinstance(entry[1], dict) else {}
                detail = f"{info.get('exception_type', '')}: {info.get('exception_message', '')}".strip(': ')
                node = info.get('node_type')
                if node:
                    detail += f' (in {node})'
        if _is_memory_error(detail):
            self.free()
            return ComfyError('out_of_memory', 'The graphics card ran out of memory while making the image. '
                              + MEMORY_HINT)
        return ComfyError('failed', 'ComfyUI could not make the image: ' + (detail[:400] or 'no reason given'))

    def run(self, workflow: dict, *, timeout_seconds: float = 300.0, cancel_event=None) -> list[bytes]:
        """Queue a workflow, wait for it, and return the pictures it produced (PNG bytes)."""
        job = self._queue(workflow)
        finish = time.monotonic() + timeout_seconds
        while time.monotonic() < finish:
            if cancel_event is not None and cancel_event.is_set():
                self.interrupt()
                self._call('POST', '/queue', json={'delete': [job]})
                raise RuntimeError('STAR image generation cancelled by user')
            reply = self._call('GET', '/history/' + job)
            reply.raise_for_status()
            detail = reply.json().get(job)
            if detail:
                status = detail.get('status') or {}
                if status.get('status_str') == 'error':
                    raise self._failure(status)
                images = []
                for node in (detail.get('outputs') or {}).values():
                    for result in node.get('images') or []:
                        name, folder, kind = (str(result.get(k, '')) for k in ('filename', 'subfolder', 'type'))
                        if (not name or '/' in name or '\\' in name or name in ('.', '..')
                                or kind not in ('output', 'temp') or '..' in folder
                                or folder.startswith(('/', '\\'))):
                            continue
                        picture = self._call('GET', '/view',
                                             params={'filename': name, 'type': kind, 'subfolder': folder})
                        picture.raise_for_status()
                        if len(picture.content) > 25_000_000:
                            raise ComfyError('failed', 'The generated image is larger than 25 MB')
                        images.append(picture.content)
                if images:
                    return images
                if status.get('completed'):
                    raise ComfyError('failed', 'ComfyUI finished but produced no image')
            time.sleep(self.poll)
        self.interrupt()
        raise ComfyError('timeout', f'The image was not finished after {int(timeout_seconds)} seconds, so STAR '
                         'stopped the job. The first image after ComfyUI starts takes longest (the model is '
                         'read from disk); try again.')
