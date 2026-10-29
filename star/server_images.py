"""Pictures from the STAR image service on the servers (`server/imagegen`: SANA-Sprint 0.6B on brain 1's processors).

The service is on the home network only and takes the STAR Server key. It makes square pictures:
512 x 512 in about 5.5 s and 1024 x 1024 in about 14 s (measured 2026-10-28, see `media_measurements`),
text to image only; changing an attached picture needs ComfyUI on this PC.

While a picture is being made the servers' language models write about three times slower (measured),
so the place "Automatic" uses this PC's graphics card whenever it is free and the servers only when it
is not (`media_places.resolve`).
"""
from __future__ import annotations

import base64
from typing import TYPE_CHECKING

from ._lazy import lazy_module

if TYPE_CHECKING:
    import httpx
else:
    httpx = lazy_module("httpx")

MODEL = 'SANA-Sprint 0.6B'
SIZES = {'square': 1024, 'draft': 512}      # the service's sizes; wide and tall pictures are made square


class ServerImageError(RuntimeError):
    """The image service could not make the picture. The message says why, for the chat."""


def address(settings) -> str:
    return str(getattr(settings, 'media_images_server', '') or '').strip().rstrip('/')


def _key() -> str:
    from .providers import STAR_SERVER, get_api_key
    return get_api_key(STAR_SERVER) or ''


def configured(settings) -> bool:
    """An image service address is set and the STAR Server key is stored."""
    return bool(address(settings)) and bool(_key())


def side(size: str) -> int:
    return SIZES.get(size, SIZES['square'])


def generate(settings, prompt: str, *, size: str = 'square', seed: int | None = None, timeout: float = 150.0,
             transport=None) -> tuple[bytes, dict]:
    """One PNG from the service and what it reported (seed, steps, seconds). Raises ServerImageError."""
    if not configured(settings):
        raise ServerImageError('No image service on the servers is set up: add its address in Settings → Where STAR '
                               'generates, and connect STAR Server (its key is used).')
    pixels = side(size)
    body: dict[str, object] = {'prompt': prompt, 'size': f'{pixels}x{pixels}', 'response_format': 'b64_json'}
    if seed is not None:
        body['seed'] = int(seed) % 2 ** 63
    try:
        with httpx.Client(timeout=timeout, trust_env=False, transport=transport) as client:
            response = client.post(address(settings) + '/v1/images/generations', json=body,
                                   headers={'Authorization': f'Bearer {_key()}'})
    except httpx.TimeoutException as exc:
        raise ServerImageError(f'The image service on the servers did not answer within {timeout:.0f} s.') from exc
    except httpx.HTTPError as exc:
        raise ServerImageError('The image service on the servers could not be reached '
                               f'({type(exc).__name__}). Check its address in Settings → Where STAR generates.') from exc
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code != 200:
        why = str((data.get('error') or {}).get('message') or '')[:200] if isinstance(data, dict) else ''
        meaning = {401: 'it refused the STAR Server key', 429: 'it is busy with other pictures',
                   503: 'it is still starting'}.get(response.status_code, f'it answered {response.status_code}')
        raise ServerImageError(f'The image service on the servers did not make the picture: {meaning}'
                               + (f' ({why})' if why else '') + '.')
    try:
        picture = base64.b64decode(data['data'][0]['b64_json'], validate=True)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ServerImageError('The image service on the servers sent an answer without a picture.') from exc
    if not picture.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ServerImageError('The image service on the servers sent something that is not a PNG picture.')
    return picture, {'seed': data.get('seed'), 'steps': data.get('steps'), 'seconds': data.get('seconds'),
                     'model': data.get('model') or MODEL, 'width': pixels, 'height': pixels}


def status(settings, *, timeout: float = 3.0, transport=None) -> dict:
    """What Settings shows about the service. Never raises."""
    if not address(settings):
        return {'ready': False, 'message': 'No image service address is set.'}
    try:
        with httpx.Client(timeout=timeout, trust_env=False, transport=transport) as client:
            data = client.get(address(settings) + '/health').json()
    except Exception as exc:   # noqa: BLE001 - shown as text
        return {'ready': False, 'message': f'The image service did not answer ({type(exc).__name__}).'}
    ready = isinstance(data, dict) and data.get('status') == 'ok'
    return {'ready': ready, 'busy': bool(isinstance(data, dict) and data.get('busy')),
            'message': 'Ready.' if ready else f"Not ready: {str((data or {}).get('status', 'unknown'))[:40]}."}
