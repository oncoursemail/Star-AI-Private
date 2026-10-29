"""Small OpenAI-compatible client for STAR's mesh router (litha for writing specs, star-fast for vision)."""
from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
import urllib.request
from pathlib import Path

def _router() -> str:
    """Mesh router address: env STAR_MESH_URL, else ~/.star/mesh_url (same rule as star.system_view)."""
    if os.environ.get("STAR_MESH_URL", "").strip():
        return os.environ["STAR_MESH_URL"].strip().rstrip("/")
    f = Path.home() / ".star" / "mesh_url"
    return f.read_text(encoding="utf-8").splitlines()[0].strip().rstrip("/")
KEY_FILE = Path(os.path.expanduser("~/.star/server_api_key"))


# The GPU nodes serve one long request at a time (ctx 4096); a second concurrent request can spill to the slow brain
# fallback, so this process sends one request per model at a time.
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock(model: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(model, threading.Lock())


def _key() -> str:
    return KEY_FILE.read_text(encoding="utf-8").strip()


def chat(model: str, messages: list, max_tokens: int = 3000, temperature: float = 0.3, json_mode: bool = False,
         timeout: float = 900.0) -> tuple[str, dict]:
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    base = _router()
    if model.startswith("http://"):  # a private llama-server, e.g. the CPU vision critic: http://127.0.0.1:8111
        base, body["model"] = model.rstrip("/"), "critic"
        body["chat_template_kwargs"] = {"enable_thinking": False}
    req = urllib.request.Request(f"{base}/v1/chat/completions", json.dumps(body).encode("utf-8"),
                                 {"Authorization": "Bearer " + _key(), "Content-Type": "application/json",
                                  # plain generation: no answer cache, grounding, general helper or docs block
                                  "X-Mesh-Cache": "off", "X-Mesh-Ground": "off", "X-Mesh-General": "off",
                                  "X-Mesh-Docs": "off"})
    with _lock(model):
        t = time.time()
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
            backend = r.headers.get("X-Mesh-Backend", "")
    text = data["choices"][0]["message"].get("content") or ""
    return text, {"seconds": round(time.time() - t, 1), "usage": data.get("usage", {}), "backend": backend}


def image_part(path: str | Path) -> dict:
    b = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    mime = "image/jpeg" if str(path).lower().endswith((".jpg", ".jpeg")) else "image/png"
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b}"}}


def extract_json(text: str):
    """First balanced JSON object in a model reply (tolerates ``` fences and prose)."""
    text = re.sub(r"```(?:json)?", "", text)
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    raise ValueError("no JSON object in reply")
