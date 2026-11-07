"""Small OpenAI-compatible client for STAR's mesh router (litha for writing specs, star-fast for vision)."""
from __future__ import annotations

import base64
import urllib.error
import json
import os
import re
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

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


def _get(url: str, headers: dict | None = None, timeout: float = 8.0) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=timeout) as r:
        return json.load(r)


def usable_nodes() -> list[tuple[str, str]]:
    """(name, model base url) of GPU nodes that are usable now, fastest first (from the router's status)."""
    st = _get(_router() + "/mesh/status", {"Authorization": "Bearer " + _key()})
    out = []
    for n in sorted(st.get("nodes", []), key=lambda n: -float(n.get("tok_s") or 0)):
        if not n.get("usable") or not n.get("status_url"):
            continue
        try:
            ns = _get(n["status_url"])
        except OSError:
            continue
        for m in ns.get("models", []):
            if m.get("loaded") and m.get("url"):
                out.append((n["name"], m["url"].rstrip("/")))
                break
    return out


def node_chat(body: dict, wait_s: float = 1800.0, timeout: float = 600.0) -> tuple[dict, str]:
    """Send a litha request straight to a usable GPU node (never the slow brain fallback); wait while none is free."""
    token = (Path.home() / ".star" / "mesh_token").read_text(encoding="utf-8").splitlines()[0].strip()
    deadline = time.time() + wait_s
    last = ""
    while True:
        for name, url in usable_nodes():
            b: dict[str, Any] = dict(body, model="litha-fast")
            b["chat_template_kwargs"] = {"enable_thinking": False}
            req = urllib.request.Request(url + "/chat/completions", json.dumps(b).encode("utf-8"),
                                         {"Authorization": "Bearer " + token, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return json.load(r), name
            except urllib.error.HTTPError as e:
                if e.code == 400:  # the request itself is wrong (too long for the context): do not retry it
                    raise ValueError(f"{name}: HTTP 400 {e.read()[:200]!r}") from e
                last = f"{name}: HTTP {e.code}"
            except OSError as e:  # busy / unloading: try the next node or wait
                last = f"{name}: {type(e).__name__} {str(e)[:120]}"
        if time.time() > deadline:
            raise RuntimeError("no GPU node answered: " + last)
        time.sleep(20)


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
        if model == "litha" and os.environ.get("STAR_ASSET3D_VIA_ROUTER") != "1":
            data, backend = node_chat(body, timeout=timeout)
        else:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.load(r)
                backend = r.headers.get("X-Mesh-Backend", "")
    text = data["choices"][0]["message"].get("content") or ""
    return text, {"seconds": round(time.time() - t, 1), "usage": data.get("usage", {}), "backend": backend,
                  "finish": data["choices"][0].get("finish_reason")}


def image_part(path: str | Path) -> dict:
    b = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    mime = "image/jpeg" if str(path).lower().endswith((".jpg", ".jpeg")) else "image/png"
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b}"}}


def estimate_tokens(text: str) -> int:
    """Rough token count for gemma: digits are about one token each, other text about 3.2 chars per token."""
    digits = sum(c.isdigit() for c in text)
    return int(digits * 0.95 + (len(text) - digits) / 3.2) + 8


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
