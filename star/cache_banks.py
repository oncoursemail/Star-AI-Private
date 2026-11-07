"""Saved project memory (G0b): llama.cpp KV snapshots of the stable start of STAR's requests. Opt-in.

The start of every STAR request is byte-stable: the system message (rules, memory, an approved reference packet)
and the tool list (star/context_layout.py). After a model restart the server has to read it again (the tool
prompt alone is ~1,100 tokens, 16-30 s on star-fast). With a bank, STAR has the server save that start once
(`POST /slots/{id}?action=save`, the server's own --slot-save-path) and later restores it instead of re-reading.

How:
  * the start is rendered by the server's own chat template (`/apply-template`, system + tools + a placeholder
    user message, twice with different placeholders; the bank is the common start) and keyed by the SHA-256 of
    that text, the model, the server and STAR_KV_BANK_MODEL_REVISION;
  * only the start is banked (a raw `/v1/completions` of exactly that text, then save), never a conversation:
    star-fast is hybrid, so a slot can be reused only up to a saved checkpoint, and a saved conversation would be
    of no use to another chat;
  * restore or build happens only into an EMPTY slot (it holds no tokens: the model process just started, or the
    slot was erased; `GET /slots` n_prompt_tokens). A used slot is left alone: its own contents or the server's
    RAM prompt cache serve the start already, and a restore would replace the slot's contents without the server keeping them;
  * at most MAX_BANKS files on the server, per STAR install: the file names are a fixed pool and the least
    recently used bank's name is reused, so the server's disk use is bounded without a delete endpoint;
  * the server checks the restored tokens against every request (cache_prompt), so a stale or foreign file can
    only cost time, never change an answer.

Off unless STAR_KV_BANKS=on AND STAR_KV_BANK_MODEL_REVISION names the exact model file (change it whenever the
GGUF, template or adapter changes). STAR Server (LAN) only; the index in app data holds hashes and sizes, never
prompt text. Server side: `slot-save-path` in models.ini (server/brain/kv_banks/enable.sh, undo.sh).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any

import httpx

from .providers import connection_for, provider_kind, server_slots

ENV_ENABLE = "STAR_KV_BANKS"
ENV_REVISION = "STAR_KV_BANK_MODEL_REVISION"
ENV_MAX = "STAR_KV_BANKS_MAX"
SCHEMA_VERSION = 2
DEFAULT_MAX_BANKS = 8
MAX_INDEX_BYTES = 64_000
MAX_SLOTS_REPLY_BYTES = 8 * 1024 * 1024   # ~1.3 KB per slot; a server with slots debug on adds every prompt
MAX_REPLY_BYTES = 4_096
MAX_SNAPSHOT_BYTES = 16 * 1024**3
MODEL_REV = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{7,95}$")
FINGERPRINT = re.compile(r"^[a-f0-9]{64}$")
BANK_NAME = re.compile(r"^star-kv-[a-f0-9]{8}-[0-9]{2}\.bin$")
# Two placeholder user messages that differ in their first character: the common start of the two renders ends
# exactly where the user's words begin.
_PLACEHOLDERS = ("alpha", "omega")


def enabled() -> bool:
    """Explicit opt-in; no other environment value means approval."""
    return os.environ.get(ENV_ENABLE) == "on"


def max_banks() -> int:
    try:
        return min(64, max(1, int(os.environ.get(ENV_MAX, DEFAULT_MAX_BANKS))))
    except ValueError:
        return DEFAULT_MAX_BANKS


def _common_length(a: str, b: str) -> int:
    n = min(len(a), len(b))
    return next((i for i in range(n) if a[i] != b[i]), n)


def fingerprint(server: str, model: str, revision: str, prefix: str) -> str:
    return hashlib.sha256(json.dumps([SCHEMA_VERSION, server, model, revision, prefix],
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def pool_name(home: Path, number: int) -> str:
    """This install's file name number `number`: installs sharing one server never overwrite each other's banks."""
    return f"star-kv-{hashlib.sha256(str(home).encode('utf-8')).hexdigest()[:8]}-{number:02d}.bin"


def _index_path(home: Path) -> Path:
    folder = home / "cache-banks"
    if home.is_symlink() or folder.is_symlink():
        raise PermissionError("KV bank index cannot be in a symlink")
    return folder / "index.json"


def _load(home: Path) -> dict:
    try:
        file = _index_path(home)
        if file.is_symlink() or not file.is_file() or file.stat().st_size > MAX_INDEX_BYTES:
            return {}
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, PermissionError, UnicodeError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("version") != SCHEMA_VERSION or not isinstance(data.get("banks"), dict):
        return {}
    return {key: value for key, value in data["banks"].items()
            if FINGERPRINT.fullmatch(str(key)) and isinstance(value, dict)
            and BANK_NAME.fullmatch(str(value.get("file", ""))) and type(value.get("used")) in (int, float)}


def _write(home: Path, banks: dict) -> None:
    """Atomic, restricted local metadata only: hashes, file names, sizes, times."""
    file = _index_path(home)
    file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if file.is_symlink():
        raise PermissionError("KV bank index cannot be a symlink")
    payload = json.dumps({"version": SCHEMA_VERSION, "banks": banks},
                         sort_keys=True, separators=(",", ":")).encode("utf-8")
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=file.parent, prefix=".kv-bank-", delete=False) as stream:
            name = Path(stream.name)
            os.chmod(name, 0o600)
            stream.write(payload)
        os.replace(name, file)
    finally:
        if name is not None:
            name.unlink(missing_ok=True)


def pick_file(home: Path, banks: dict) -> str:
    """A free name of this install's pool, else the name of the least recently used bank (that bank is dropped)."""
    taken = {value["file"] for value in banks.values()}
    for number in range(max_banks()):
        name = pool_name(home, number)
        if name not in taken:
            return name
    oldest = min(banks, key=lambda key: banks[key]["used"])
    return banks.pop(oldest)["file"]


def _connection(settings) -> tuple[str, dict] | None:
    endpoint, key = connection_for(settings)
    endpoint = str(endpoint).rstrip("/")
    if not endpoint.endswith("/v1") or not isinstance(key, str) or not key:
        return None
    return endpoint[:-3], {"Authorization": "Bearer " + key, "Accept": "application/json"}


async def _json(response: httpx.Response, limit: int) -> Any:
    parts, total = [], 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > limit:
            raise ValueError("reply too large")
        parts.append(chunk)
    return json.loads(b"".join(parts))


async def slot_state(client: httpx.AsyncClient, root: str, headers: dict, model: str, slot: int) -> str:
    """'empty' (the slot holds no tokens: model just started, or erased), 'used', 'busy', or 'unavailable'."""
    try:
        async with client.stream("GET", root + "/slots", params={"model": model}, headers=headers) as reply:
            if reply.status_code != 200:
                return "unavailable"
            rows = await _json(reply, MAX_SLOTS_REPLY_BYTES)
    except (httpx.HTTPError, ValueError):
        return "unavailable"
    row = next((row for row in rows if isinstance(row, dict) and row.get("id") == slot), None) if isinstance(
        rows, list) else None
    if row is None:
        return "unavailable"
    if row.get("is_processing") is not False:
        return "busy"
    # n_prompt_tokens is the number of tokens the slot holds now (0 after an erase; absent before its first task)
    return "used" if row.get("n_prompt_tokens") else "empty"


async def render_prefix(client: httpx.AsyncClient, root: str, headers: dict, request: dict) -> str | None:
    """The request's stable start as the server's template renders it, up to where the first user words begin."""
    base = {"model": request["model"]}
    if request.get("tools"):
        base["tools"] = request["tools"]
    kwargs = (request.get("extras") or {}).get("chat_template_kwargs")
    if kwargs:
        base["chat_template_kwargs"] = kwargs
    texts = []
    for word in _PLACEHOLDERS:
        reply = await client.post(root + "/apply-template", headers=headers, json={
            **base, "messages": [request["messages"][0], {"role": "user", "content": word}]})
        if reply.status_code != 200:
            return None
        texts.append(str(reply.json().get("prompt") or ""))
    n = _common_length(*texts)
    if n == 0 or not texts[0][n:].startswith(_PLACEHOLDERS[0]) or not texts[1][n:].startswith(_PLACEHOLDERS[1]):
        return None
    return texts[0][:n]


async def slot_action(client: httpx.AsyncClient, root: str, headers: dict, model: str, slot: int,
                      action: str, filename: str) -> dict | None:
    """POST /slots/{slot}?action=save|restore; {'tokens', 'bytes', 'ms'} from a verified receipt, else None."""
    try:
        async with client.stream("POST", root + f"/slots/{slot}", params={"action": action},
                                 headers={**headers, "Content-Type": "application/json"},
                                 json={"filename": filename, "model": model}) as reply:
            if reply.status_code != 200:
                return None
            payload = await _json(reply, MAX_REPLY_BYTES)
    except (httpx.HTTPError, ValueError):
        return None
    count = payload.get("n_saved" if action == "save" else "n_restored") if isinstance(payload, dict) else None
    size = payload.get("n_written" if action == "save" else "n_read") if isinstance(payload, dict) else None
    if (payload.get("id_slot") != slot or payload.get("filename") != filename
            or type(count) is not int or not 0 < count <= 10_000_000
            or type(size) is not int or not 0 < size <= MAX_SNAPSHOT_BYTES):
        return None
    took = (payload.get("timings") or {}).get("save_ms" if action == "save" else "restore_ms")
    return {"tokens": count, "bytes": size, **({"ms": round(took, 1)} if isinstance(took, (int, float)) else {})}


def _usable(settings, request: dict) -> tuple[str, int] | str:
    """(model, slot) for a request a bank may serve, else why not."""
    if provider_kind(settings) != "lan":
        return "not_local_server"
    messages = request.get("messages") if isinstance(request, dict) else None
    if not isinstance(messages, list) or not messages or not isinstance(messages[0], dict) or (
            messages[0].get("role") != "system"):
        return "no_system"
    model, extras = request.get("model"), request.get("extras")
    if not isinstance(model, str) or not 1 <= len(model) <= 180 or not isinstance(extras, dict):
        return "request"
    slot = extras.get("id_slot")
    slots = server_slots(settings, model)
    if type(slot) is not int or not 2 <= slots <= 64 or not 0 <= slot < slots or extras.get("cache_prompt") is not True:
        return "unpinned"
    return model, slot


async def _prepare(settings, home: Path, request: dict, transport, now) -> dict:
    revision = os.environ.get(ENV_REVISION, "")
    if not MODEL_REV.fullmatch(revision):
        return {"bank": "skipped", "reason": "revision"}
    usable = _usable(settings, request)
    if isinstance(usable, str):
        return {"bank": "skipped", "reason": usable}
    model, slot = usable
    connection = _connection(settings)
    if connection is None:
        return {"bank": "skipped", "reason": "endpoint"}
    root, headers = connection
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=2.0), trust_env=False,
                                 follow_redirects=False, transport=transport) as client:
        state = await slot_state(client, root, headers, model, slot)
        if state != "empty":
            return {"bank": "skipped", "reason": "slot_" + state}
        prefix = await render_prefix(client, root, headers, request)
        if not prefix:
            return {"bank": "skipped", "reason": "template"}
        key = fingerprint(root, model, revision, prefix)
        banks = _load(home)
        known = banks.get(key)
        if known is not None:
            restored = await slot_action(client, root, headers, model, slot, "restore", known["file"])
            if restored is not None:
                banks[key] = {**known, "used": now}
                _write(home, banks)
                return {"bank": "restored", **restored}
            del banks[key]   # gone or overwritten on the server: build it again
        began = time.perf_counter()
        reply = await client.post(root + "/v1/completions", headers=headers, json={
            "model": model, "prompt": prefix, "max_tokens": 1, "temperature": 0,
            "cache_prompt": True, "id_slot": slot})
        if reply.status_code != 200:
            return {"bank": "skipped", "reason": "prefill_failed"}
        read_ms = int((time.perf_counter() - began) * 1000)
        name = pick_file(home, banks)
        saved = await slot_action(client, root, headers, model, slot, "save", name)
        if saved is None:
            return {"bank": "skipped", "reason": "save_failed", "read_ms": read_ms}
        banks[key] = {"file": name, "used": now, "tokens": saved["tokens"], "bytes": saved["bytes"]}
        _write(home, banks)
        return {"bank": "saved", "read_ms": read_ms, **saved}


async def prepare(settings, home: Path, request: dict, *, cancel_event=None, transport=None, now=None) -> dict:
    """Before priming or sending `request`: restore its banked start into its slot, or read and bank it, when that
    slot is empty. Never raises; returns a small nonsecret report ({'bank': 'restored'|'saved'|'skipped', ...})."""
    if not enabled():
        return {"bank": "skipped", "reason": "off"}
    if cancel_event is not None and cancel_event.is_set():
        return {"bank": "skipped", "reason": "cancelled"}
    job = asyncio.ensure_future(_prepare(settings, home, request, transport, time.time() if now is None else now))
    try:
        while True:
            done, _ = await asyncio.wait({job}, timeout=0.1)
            if done:
                return job.result()
            if cancel_event is not None and cancel_event.is_set():
                return {"bank": "skipped", "reason": "cancelled"}
    except (httpx.HTTPError, OSError, PermissionError, ValueError, TypeError, KeyError, AttributeError):
        return {"bank": "skipped", "reason": "unavailable"}
    finally:
        if not job.done():
            job.cancel()   # closes the connection; the server stops after the batch it is reading
            await asyncio.gather(job, return_exceptions=True)
