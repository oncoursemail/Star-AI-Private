"""STAR image service: text to image on a server without a graphics card (LAN only, brain key).

    GET  /health                    no auth: {"status": "ok"|"loading"|"error", "model", "sizes", "busy", "waiting"}
    POST /v1/images/generations     Bearer key (a line of the brain's own key file), OpenAI-style body:
                                    {"prompt", "size": "512x512"|"768x768"|"1024x1024", "seed"?, "steps"?,
                                     "response_format": "b64_json"} -> {"created", "model", "data": [{"b64_json"}],
                                     "size", "seed", "steps", "seconds", "timings"}

One picture at a time (the CPU is shared with STAR's language models: the unit runs at a lower
priority so a chat answer always wins); a few requests may wait, more get 429. Prompts are never
logged. The engine is `engine.FastSana` (SANA-Sprint 0.6B); tests pass a fake one.

    python -I service.py            (config: STAR_IMAGES_CONFIG=<json file>, defaults below)
"""
from __future__ import annotations

import base64
import hmac
import io
import json
import os
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEFAULTS = {
    'listen': '0.0.0.0',                          # inside its own container; ufw admits only the LAN
    'port': 8095,
    'keys_file': '/etc/star-images/api_keys',
    'model_dir': '/data/star/imagegen/models/sana-sprint-0.6b',
    'lite_vae_dir': '/data/star/imagegen/models/dc-ae-lite',
    'openvino_dir': '/var/cache/star-images/openvino',
    'threads': 24,
    'pin_threads': True,
    'sizes': [512, 1024],                         # each size compiled keeps its own weights: ~5 GB per size
    'max_waiting': 3,
    'max_prompt': 1500,
    'max_body_bytes': 16384,
}


def load_config(path: str | None = None) -> dict:
    cfg = dict(DEFAULTS)
    path = path or os.environ.get('STAR_IMAGES_CONFIG', '')
    if path and Path(path).is_file():
        cfg.update(json.loads(Path(path).read_text(encoding='utf-8')))
    return cfg


class KeyFile:
    """Accepted Bearer keys: the non-empty lines of a file, re-read when it changes. Never logged."""

    def __init__(self, path: str):
        self.path, self.stamp, self.keys = Path(path), None, ()

    def check(self, token: str) -> bool:
        try:
            stamp = self.path.stat().st_mtime_ns
            if stamp != self.stamp:
                self.keys = tuple(line.strip() for line in self.path.read_text(encoding='utf-8').splitlines()
                                  if line.strip())
                self.stamp = stamp
        except OSError:
            self.keys = ()
        return bool(token) and any(hmac.compare_digest(token.encode(), key.encode()) for key in self.keys)


class Worker:
    """Owns the engine: loads it in the background, then runs one picture at a time."""

    def __init__(self, cfg: dict, make_engine):
        self.cfg, self.make_engine = cfg, make_engine
        self.engine, self.state, self.error = None, 'loading', ''
        self.lock, self.count_lock, self.waiting = threading.Lock(), threading.Lock(), 0

    def load(self) -> None:
        try:
            engine = self.make_engine(self.cfg)
            engine.warm(self.cfg['sizes'])
            self.engine, self.state = engine, 'ok'
        except Exception as exc:          # noqa: BLE001 - reported on /health, the service stays up
            self.state, self.error = 'error', f'{type(exc).__name__}: {exc}'[:300]

    def health(self) -> dict:
        return {'status': self.state, 'model': getattr(self.engine, 'model_name', 'SANA-Sprint 0.6B'),
                'sizes': self.cfg['sizes'], 'busy': self.lock.locked(), 'waiting': self.waiting,
                **({'error': self.error} if self.error else {})}

    def generate(self, prompt: str, size: int, steps: int | None, seed: int):
        """(png bytes, info) or raises Busy / NotReady."""
        if self.state != 'ok':
            raise NotReady(self.error or 'the image model is still loading')
        with self.count_lock:
            if self.waiting >= self.cfg['max_waiting'] + 1:
                raise Busy()
            self.waiting += 1
        try:
            with self.lock:
                started = time.time()
                image, timings = self.engine.generate(prompt, size, steps, seed)
                out = io.BytesIO()
                image.save(out, format='PNG')
                return out.getvalue(), {'seconds': round(time.time() - started, 2), 'timings': timings}
        finally:
            with self.count_lock:
                self.waiting -= 1


class Busy(Exception):
    pass


class NotReady(Exception):
    pass


def parse_request(body: dict, cfg: dict) -> tuple[str, int, int | None, int]:
    """Validated (prompt, size, steps, seed). Raises ValueError with a message for the client."""
    if not isinstance(body, dict):
        raise ValueError('send a JSON object')
    prompt = body.get('prompt')
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= cfg['max_prompt']:
        raise ValueError(f"prompt must be 1-{cfg['max_prompt']} characters")
    if int(body.get('n', 1) or 1) != 1:
        raise ValueError('n must be 1')
    if body.get('response_format', 'b64_json') != 'b64_json':
        raise ValueError('response_format must be b64_json')
    size_text = str(body.get('size') or f"{cfg['sizes'][0]}x{cfg['sizes'][0]}")
    width, _, height = size_text.partition('x')
    if not (width.isdigit() and width == height and int(width) in cfg['sizes']):
        raise ValueError('size must be one of ' + ', '.join(f'{s}x{s}' for s in cfg['sizes']))
    steps = body.get('steps')
    if steps is not None and (type(steps) is not int or not 1 <= steps <= 4):
        raise ValueError('steps must be 1-4')
    seed = body.get('seed')
    if seed is None:
        seed = secrets.randbelow(2 ** 31)
    elif type(seed) is not int or not 0 <= seed < 2 ** 63:
        raise ValueError('seed must be a non-negative integer')
    return prompt.strip(), int(width), steps, seed


def make_handler(cfg: dict, keys: KeyFile, worker: Worker):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        server_version = 'star-images/1'

        def log_message(self, fmt, *args):       # no request logging: prompts may be personal
            pass

        def _send(self, status: int, obj: dict) -> None:
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, message: str) -> None:
            self._send(status, {'error': {'message': message}})

        def do_GET(self):
            if self.path.split('?')[0] == '/health':
                return self._send(200, worker.health())
            return self._error(404, 'not found')

        def do_POST(self):
            if self.path.split('?')[0] != '/v1/images/generations':
                return self._error(404, 'not found')
            auth = self.headers.get('Authorization', '')
            if not keys.check(auth[7:].strip() if auth.lower().startswith('bearer ') else ''):
                return self._error(401, 'invalid api key')
            try:
                length = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                length = -1
            if not 0 < length <= cfg['max_body_bytes']:
                return self._error(413 if length > 0 else 400, 'body missing or too large')
            try:
                prompt, size, steps, seed = parse_request(json.loads(self.rfile.read(length)), cfg)
            except (ValueError, TypeError) as exc:
                return self._error(400, str(exc) if isinstance(exc, ValueError) else 'invalid request')
            try:
                png, info = worker.generate(prompt, size, steps, seed)
            except Busy:
                return self._error(429, 'busy: other pictures are being made, try again shortly')
            except NotReady as exc:
                return self._error(503, f'not ready: {exc}')
            except Exception as exc:          # noqa: BLE001
                return self._error(500, f'generation failed ({type(exc).__name__})')
            used = steps or getattr(worker.engine, 'steps_for', lambda s: None)(size)
            return self._send(200, {'created': int(time.time()), 'model': worker.health()['model'],
                                    'data': [{'b64_json': base64.b64encode(png).decode()}],
                                    'size': f'{size}x{size}', 'seed': seed, 'steps': used, **info})
    return Handler


def make_engine(cfg: dict):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from engine import STEPS, MODEL_NAME, FastSana      # noqa: E402 - torch loads only in the real service
    engine = FastSana(cfg['model_dir'], cfg['lite_vae_dir'], cfg['openvino_dir'], cfg['threads'], cfg['pin_threads'])
    engine.model_name = MODEL_NAME
    engine.steps_for = lambda size: STEPS.get(size, 2)
    return engine


def serve(cfg: dict, engine_factory=make_engine) -> ThreadingHTTPServer:
    worker = Worker(cfg, engine_factory)
    server = ThreadingHTTPServer((cfg['listen'], cfg['port']), make_handler(cfg, KeyFile(cfg['keys_file']), worker))
    server.daemon_threads = True
    server.worker = worker
    threading.Thread(target=worker.load, name='load-engine', daemon=True).start()
    return server


if __name__ == '__main__':
    config = load_config()
    httpd = serve(config)
    print(f"star-images listening on {config['listen']}:{config['port']}", flush=True)
    httpd.serve_forever()
