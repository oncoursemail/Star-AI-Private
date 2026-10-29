"""Model calls for the builder: STAR's router (OpenAI-compatible). Text: `litha`; vision critic: `star-fast`.

The key is read from ~/.star/server_api_key (or STAR_ROUTER_KEY); it is never printed or returned.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

def _router() -> str:
    """Router URL: STAR_ROUTER_URL, else the first line of ~/.star/mesh_url (kept out of the repository)."""
    env = os.environ.get("STAR_ROUTER_URL", "").strip()
    if env:
        return env
    try:
        return (Path.home() / ".star" / "mesh_url").read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError):
        return "http://127.0.0.1:8100"


ROUTER = _router()
TEXT_MODEL = os.environ.get("STAR_BUILD_MODEL", "litha")
VISION_MODEL = os.environ.get("STAR_BUILD_VISION", "star-fast")


def _key() -> str:
    env = os.environ.get("STAR_ROUTER_KEY", "").strip()
    if env:
        return env
    path = Path.home() / ".star" / "server_api_key"
    return path.read_text(encoding="utf-8").splitlines()[0].strip()


# Router helpers that would change a structured answer (answer cache, grounding, docs, general helper): off.
PLAIN = {"X-Mesh-Cache": "off", "X-Mesh-Ground": "off", "X-Mesh-General": "off", "X-Mesh-Docs": "off"}


def brain_load() -> int | None:
    """Requests in flight on brain1 (the vision model's host), from the router status; None if unknown."""
    try:
        req = urllib.request.Request(ROUTER.rstrip("/") + "/mesh/status", headers={"Authorization": "Bearer " + _key()})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return int(json.load(resp).get("brain", {}).get("inflight"))
    except Exception:
        return None


def idle_nodes() -> list[str] | None:
    try:
        req = urllib.request.Request(ROUTER.rstrip("/") + "/mesh/status", headers={"Authorization": "Bearer " + _key()})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return [n.get("name") for n in json.load(resp).get("nodes", []) if n.get("state") == "idle"]
    except Exception:
        return None


def wait_for_node(max_wait_s: float = 4 * 3600, poll_s: float = 20) -> float:
    """Block until a GPU node is idle (so `litha` is not sent to the overloaded brain queue). Returns seconds waited."""
    started = time.monotonic()
    while time.monotonic() - started < max_wait_s:
        nodes = idle_nodes()
        if nodes is None or nodes:
            break
        time.sleep(poll_s)
    return round(time.monotonic() - started, 1)


def _stream_once(body: dict, first_token_s: float, timeout: float) -> tuple[str, dict]:
    req = urllib.request.Request(ROUTER.rstrip("/") + "/v1/chat/completions", data=json.dumps({**body, "stream": True}).encode(),
                                 headers={"Authorization": "Bearer " + _key(), "Content-Type": "application/json", **PLAIN})
    started = time.monotonic()
    chunks, first = [], None
    with urllib.request.urlopen(req, timeout=first_token_s) as resp:
        resp.fp.raw._sock.settimeout(first_token_s) if hasattr(resp.fp, "raw") else None
        for raw in resp:
            now = time.monotonic()
            if now - started > timeout:
                raise TimeoutError("total timeout")
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except ValueError:
                continue
            if "error" in obj:
                raise RuntimeError("stream error")
            delta = (obj.get("choices") or [{}])[0].get("delta") or {}
            piece = delta.get("content") or ""
            if piece:
                if first is None:
                    first = now - started
                    try:
                        resp.fp.raw._sock.settimeout(120)
                    except Exception:
                        pass
                chunks.append(piece)
    return "".join(chunks), {"seconds": round(time.monotonic() - started, 1), "ttft": round(first or 0, 1)}


def chat(messages: list[dict], *, model: str = TEXT_MODEL, max_tokens: int = 3000, temperature: float = 0.4,
         json_mode: bool = True, timeout: float = 900.0, first_token_s: float = 75.0) -> tuple[str, dict]:
    """Streamed call; when no token comes within first_token_s (e.g. the router picked the overloaded brain),
    give up on that attempt and ask again (the router re-plans)."""
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    last = None
    waited = 0.0
    for attempt in range(8):
        if model == TEXT_MODEL:
            waited += wait_for_node()
        try:
            text, meta = _stream_once(body, first_token_s, timeout)
            meta.update({"model": model, "attempts": attempt + 1, "waited_for_node_s": waited})
            return text, meta
        except (urllib.error.URLError, TimeoutError, OSError, RuntimeError, ValueError) as error:
            last = error
            time.sleep(2 + attempt * 3)
    raise RuntimeError(f"router call failed: {type(last).__name__}")


def parse_json(text: str) -> dict | None:
    """The first JSON object in a reply (tolerates ``` fences, thinking text, trailing commas)."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    candidates = [fence.group(1)] if fence else []
    start = text.find("{")
    if start >= 0:
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
                    candidates.append(text[start:i + 1])
                    break
        else:
            candidates.append(text[start:] + "}" * max(1, depth))
    for raw in candidates:
        for attempt in (raw, re.sub(r",\s*([}\]])", r"\1", raw)):
            try:
                value = json.loads(attempt)
                if isinstance(value, dict):
                    return value
            except ValueError:
                continue
    return None


def image_part(path: Path, max_side: int = 1024) -> dict:
    data = Path(path).read_bytes()
    try:
        from io import BytesIO

        from PIL import Image
        im = Image.open(BytesIO(data)).convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = BytesIO()
        im.save(buf, "JPEG", quality=82)
        data = buf.getvalue()
    except Exception:
        pass
    return {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(data).decode()}}
